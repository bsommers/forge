"""Tests M3-T1..T3 for Per-Operation OpenAPI Security Overrides & RouteDispatchAuth."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
import yaml

from forge.ingest_openapi import SpecNormalizationError, normalize_openapi_to_manifest
from forge.orchestrator import run_forge_pipeline
from src.auth import (
    ManifestConfigError,
    RouteDispatchAuth,
    build_auth_from_manifest,
    iter_manifest_auth_env_vars,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
GOLDEN_TEMPLATE_DIR = REPO_ROOT / "golden-template"
PROMPT_FILE = REPO_ROOT / "forge" / "AGENT_SYSTEM_PROMPT.md"


def _multi_scheme_spec() -> dict[str, Any]:
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Acme Multi-Auth Service",
            "version": "1.3.0",
            "description": "API combining public health, Bearer read, Admin API key, and OAuth2.",
        },
        "servers": [{"url": "https://api.acme.internal/v1"}],
        "security": [{"BearerAuth": []}],
        "components": {
            "securitySchemes": {
                "BearerAuth": {"type": "http", "scheme": "bearer"},
                "AdminKey": {"type": "apiKey", "in": "header", "name": "X-Admin-Key"},
                "SvcOAuth": {
                    "type": "oauth2",
                    "flows": {
                        "clientCredentials": {
                            "tokenUrl": "https://auth.acme.internal/token",
                            "scopes": {"read:all": "Read", "admin:purge": "Purge"},
                        }
                    },
                },
            }
        },
        "paths": {
            "/health": {
                "get": {
                    "operationId": "get_health",
                    "summary": "Public unauthenticated health probe",
                    "security": [],
                    "responses": {
                        "200": {
                            "description": "Health status",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {"status": {"type": "string"}},
                                    }
                                }
                            },
                        }
                    },
                }
            },
            "/incidents/{incident_id}": {
                "get": {
                    "operationId": "get_incident",
                    "summary": "Read incident using default BearerAuth",
                    "parameters": [
                        {
                            "name": "incident_id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "Incident details",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "id": {"type": "string"},
                                            "title": {"type": "string"},
                                        },
                                    }
                                }
                            },
                        }
                    },
                }
            },
            "/admin/audit/{audit_id}": {
                "delete": {
                    "operationId": "purge_audit_log",
                    "summary": "Purge audit log using AdminKey header override",
                    "security": [{"AdminKey": []}],
                    "parameters": [
                        {
                            "name": "audit_id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                    "responses": {"204": {"description": "Purged"}},
                }
            },
            "/admin/sync": {
                "post": {
                    "operationId": "sync_directory",
                    "summary": "Trigger directory sync with scoped SvcOAuth",
                    "security": [{"SvcOAuth": ["admin:purge"]}],
                    "responses": {
                        "200": {
                            "description": "Sync status",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {"status": {"type": "string"}},
                                    }
                                }
                            },
                        }
                    },
                }
            },
        },
    }


def test_m3_t1_per_op_auth_normalization_and_validation(tmp_path: Path) -> None:
    spec_path = tmp_path / "multi_auth.yaml"
    spec_path.write_text(yaml.safe_dump(_multi_scheme_spec()), encoding="utf-8")

    manifest = normalize_openapi_to_manifest(spec_path, "acme-multi")
    assert manifest["auth"] == {"type": "bearer", "token_env": "ACME_MULTI_API_TOKEN"}

    tools = {t["name"]: t for t in manifest["tools"]}
    assert tools["get_health"]["auth_scheme"] == "none"
    assert "auth_scheme" not in tools["get_incident"]
    assert tools["purge_audit_log"]["auth_scheme"] == "AdminKey"
    assert tools["sync_directory"]["auth_scheme"] == "SvcOAuth__admin_purge"

    schemes = manifest["auth_schemes"]
    assert schemes["AdminKey"] == {
        "type": "api_key_header",
        "key_env": "ACME_MULTI_ADMIN_KEY_API_KEY",
        "header_name": "X-Admin-Key",
    }
    assert schemes["SvcOAuth__admin_purge"]["scope"] == "admin:purge"

    env_vars = iter_manifest_auth_env_vars(manifest)
    assert "ACME_MULTI_API_TOKEN" in env_vars
    assert "ACME_MULTI_ADMIN_KEY_API_KEY" in env_vars
    assert "ACME_MULTI_SVC_OAUTH_CLIENT_SECRET" in env_vars

    bad_spec = _multi_scheme_spec()
    bad_spec["paths"]["/health"]["get"]["security"] = [{"GhostScheme": []}]
    bad_path = tmp_path / "bad_auth.json"
    bad_path.write_text(json.dumps(bad_spec), encoding="utf-8")
    with pytest.raises(SpecNormalizationError, match="undeclared securityScheme 'GhostScheme'"):
        normalize_openapi_to_manifest(bad_path, "acme-multi")


@respx.mock
async def test_m3_t2_route_dispatch_auth_over_shared_http_pool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec_Doc = _multi_scheme_spec()
    del spec_Doc["paths"]["/admin/sync"]
    spec_path = tmp_path / "dispatch.yaml"
    spec_path.write_text(yaml.safe_dump(spec_Doc), encoding="utf-8")
    manifest = normalize_openapi_to_manifest(spec_path, "acme-multi")

    monkeypatch.setenv("ACME_MULTI_API_TOKEN", "bearer-secret-123")
    monkeypatch.setenv("ACME_MULTI_ADMIN_KEY_API_KEY", "admin-key-999")

    auth_handler = build_auth_from_manifest(manifest)
    assert isinstance(auth_handler, RouteDispatchAuth)

    health_route = respx.get("https://api.acme.internal/v1/health").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )
    inc_route = respx.get("https://api.acme.internal/v1/incidents/INC-7").mock(
        return_value=httpx.Response(200, json={"id": "INC-7", "title": "DB"})
    )
    admin_route = respx.delete("https://api.acme.internal/v1/admin/audit/AUD-1").mock(
        return_value=httpx.Response(204)
    )

    async with httpx.AsyncClient(
        base_url="https://api.acme.internal/v1", auth=auth_handler
    ) as client:
        await client.get("/health")
        await client.get("/incidents/INC-7")
        await client.delete("/admin/audit/AUD-1")
        await client.get("/incidents/INC-7", extensions={"forge_auth_scheme": "none"})

    # 1. Public /health must carry ZERO credentials
    req_health = health_route.calls[0].request
    assert "authorization" not in req_health.headers
    assert "x-admin-key" not in req_health.headers

    # 2. Default /incidents/{id} must carry Bearer token only
    req_inc = inc_route.calls[0].request
    assert req_inc.headers["authorization"] == "Bearer bearer-secret-123"
    assert "x-admin-key" not in req_inc.headers

    # 3. Admin /admin/audit/{id} must carry X-Admin-Key only
    req_admin = admin_route.calls[0].request
    assert req_admin.headers["x-admin-key"] == "admin-key-999"
    assert "authorization" not in req_admin.headers

    # 4. Explicit extension override forge_auth_scheme="none" skips auth
    req_ext = inc_route.calls[1].request
    assert "authorization" not in req_ext.headers

    bad_manifest = json.loads(json.dumps(manifest))
    bad_manifest["auth_schemes"] = {}
    with pytest.raises(ManifestConfigError, match="unknown auth_scheme"):
        build_auth_from_manifest(bad_manifest)


def test_m3_t3_end_to_end_multi_auth_local_forge_passes_five_gates(tmp_path: Path) -> None:
    spec_doc = _multi_scheme_spec()
    del spec_doc["paths"]["/admin/sync"]
    spec_path = tmp_path / "multi_e2e.yaml"
    spec_path.write_text(yaml.safe_dump(spec_doc), encoding="utf-8")

    out_dir = tmp_path / "forged_multi_auth"
    artifacts = run_forge_pipeline(
        spec_path=spec_path,
        server_name="acme-multi",
        golden_template_dir=GOLDEN_TEMPLATE_DIR,
        system_prompt_path=PROMPT_FILE,
        output_dir=out_dir,
        agent_image="unused",
        validator_image="unused",
        execution_mode="local",
    )
    mcp_env = artifacts["client_config"]["mcpServers"]["acme-multi"]["env"]
    assert "ACME_MULTI_API_TOKEN" in mcp_env
    assert "ACME_MULTI_ADMIN_KEY_API_KEY" in mcp_env
