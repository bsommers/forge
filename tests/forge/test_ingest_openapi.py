"""Tests for Stage 1 OpenAPI 3.x Normalizer (forge/ingest_openapi.py)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from forge.ingest_openapi import (
    MAX_TOOLS_PER_SERVER,
    SpecNormalizationError,
    _extract_auth_config,
    _infer_annotations,
    _resolve_local_refs,
    _to_snake_case,
    main,
    normalize_openapi_to_manifest,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
ACME_YAML_SPEC = REPO_ROOT / "spec" / "acme-incidents.openapi.yaml"
BILLING_JSON_SPEC = REPO_ROOT / "spec" / "cloud-billing.openapi.json"


def test_to_snake_case_conversions() -> None:
    assert _to_snake_case("getIncidentById") == "get_incident_by_id"
    assert _to_snake_case("POST /incidents/{id}/status") == "post_incidents_id_status"
    assert _to_snake_case("123_numeric_start") == "op_123_numeric_start"
    assert _to_snake_case("___") == "op"
    long_id = "get_" + ("very_long_segment_" * 10)
    assert len(_to_snake_case(long_id)) == 64


def test_infer_annotations_all_http_methods() -> None:
    assert _infer_annotations("get") == {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
    assert _infer_annotations("post") == {
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    }
    assert _infer_annotations("put") == {
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
    assert _infer_annotations("patch") == {
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    }
    assert _infer_annotations("delete") == {
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    }


def test_resolve_local_refs_json_pointer_escaping() -> None:
    root: dict[str, Any] = {
        "components": {
            "schemas": {
                "a/b~c": {
                    "type": "string",
                    "description": "Escaped pointer target",
                }
            }
        },
        "target": {
            "$ref": "#/components/schemas/a~1b~0c",
            "description": "Overridden description",
        },
    }
    resolved = _resolve_local_refs(root, root)
    assert resolved["target"] == {
        "type": "string",
        "description": "Overridden description",
    }


def test_resolve_local_refs_rejects_external_uri() -> None:
    malicious: dict[str, Any] = {
        "paths": {
            "/items": {
                "get": {
                    "parameters": [
                        {"$ref": "https://attacker.example.com/ssrf-schema.json#/Item"}
                    ]
                }
            }
        }
    }
    with pytest.raises(SpecNormalizationError, match="External \\$ref URIs are forbidden"):
        _resolve_local_refs(malicious, malicious)


def test_resolve_local_refs_missing_target_raises() -> None:
    broken: dict[str, Any] = {"item": {"$ref": "#/components/schemas/DoesNotExist"}}
    with pytest.raises(SpecNormalizationError, match="Unresolvable internal \\$ref"):
        _resolve_local_refs(broken, broken)


def test_resolve_local_refs_depth_guard() -> None:
    cyclic: dict[str, Any] = {
        "components": {
            "schemas": {
                "Node": {
                    "$ref": "#/components/schemas/Node",
                }
            }
        }
    }
    with pytest.raises(SpecNormalizationError, match="nesting depth exceeds safety limit"):
        _resolve_local_refs(cyclic, cyclic)


def test_extract_auth_config_all_six_variants() -> None:
    assert _extract_auth_config({}, "ACME") == {"type": "none"}

    bearer_spec = {
        "components": {"securitySchemes": {"Bearer": {"type": "http", "scheme": "bearer"}}}
    }
    assert _extract_auth_config(bearer_spec, "ACME") == {
        "type": "bearer",
        "token_env": "ACME_API_TOKEN",
    }

    basic_spec = {
        "components": {"securitySchemes": {"Basic": {"type": "http", "scheme": "basic"}}}
    }
    assert _extract_auth_config(basic_spec, "ACME") == {
        "type": "basic",
        "username_env": "ACME_USERNAME",
        "password_env": "ACME_PASSWORD",
    }

    header_key_spec = {
        "components": {
            "securitySchemes": {
                "HeaderKey": {"type": "apiKey", "in": "header", "name": "X-Custom-Key"}
            }
        }
    }
    assert _extract_auth_config(header_key_spec, "ACME") == {
        "type": "api_key_header",
        "key_env": "ACME_API_KEY",
        "header_name": "X-Custom-Key",
    }

    query_key_spec = {
        "components": {
            "securitySchemes": {
                "QueryKey": {"type": "apiKey", "in": "query", "name": "api_key"}
            }
        }
    }
    assert _extract_auth_config(query_key_spec, "ACME") == {
        "type": "api_key_query",
        "key_env": "ACME_API_KEY",
        "param_name": "api_key",
    }

    oauth_spec = {
        "components": {
            "securitySchemes": {
                "OAuth": {
                    "type": "oauth2",
                    "flows": {
                        "clientCredentials": {
                            "tokenUrl": "https://auth.acme.internal/token",
                            "scopes": {"incidents:read": "Read", "incidents:write": "Write"},
                        }
                    },
                }
            }
        }
    }
    assert _extract_auth_config(oauth_spec, "ACME") == {
        "type": "oauth2_client_credentials",
        "token_url_env": "ACME_OAUTH_TOKEN_URL",
        "client_id_env": "ACME_CLIENT_ID",
        "client_secret_env": "ACME_CLIENT_SECRET",
        "scope": "incidents:read incidents:write",
    }

    fallback_spec = {
        "components": {"securitySchemes": {"Custom": {"type": "openIdConnect"}}}
    }
    assert _extract_auth_config(fallback_spec, "ACME") == {
        "type": "bearer",
        "token_env": "ACME_API_TOKEN",
    }


def test_normalize_acme_incidents_yaml_spec() -> None:
    manifest = normalize_openapi_to_manifest(ACME_YAML_SPEC, "acme-incidents")
    assert manifest["protocol_revision"] == "2026-07-28"
    assert manifest["server_name"] == "acme-incidents"
    assert manifest["upstream"]["default_base_url"] == "https://api.acme.internal/v1"
    assert manifest["upstream"]["base_url_env"] == "ACME_INCIDENTS_BASE_URL"
    assert manifest["auth"] == {
        "type": "bearer",
        "token_env": "ACME_INCIDENTS_API_TOKEN",
    }

    tools_by_name = {t["name"]: t for t in manifest["tools"]}
    assert set(tools_by_name.keys()) == {
        "get_incident",
        "list_incidents",
        "create_incident",
        "update_incident_status",
        "delete_incident",
    }
    assert tools_by_name["get_incident"]["required_params"] == ["incident_id"]
    assert tools_by_name["get_incident"]["annotations"]["readOnlyHint"] is True
    assert tools_by_name["delete_incident"]["annotations"]["destructiveHint"] is True
    assert tools_by_name["create_incident"]["request_body_schema"] is not None
    assert "title" in tools_by_name["create_incident"]["request_body_schema"]["properties"]


def test_normalize_cloud_billing_json_and_tag_filter() -> None:
    all_manifest = normalize_openapi_to_manifest(BILLING_JSON_SPEC, "cloud-billing")
    assert all_manifest["auth"] == {
        "type": "api_key_header",
        "key_env": "CLOUD_BILLING_API_KEY",
        "header_name": "X-Billing-Key",
    }
    assert len(all_manifest["tools"]) == 4

    invoices_only = normalize_openapi_to_manifest(
        BILLING_JSON_SPEC, "cloud-billing-invoices", tag_filter="invoices"
    )
    assert [t["name"] for t in invoices_only["tools"]] == ["list_invoices"]
    params_by_name = {p["name"]: p for p in invoices_only["tools"][0]["parameters"]}
    assert params_by_name["tenant_id"].get("x-mcp-header") == "X-Tenant-Id"


def test_normalize_rejects_zero_tools_and_exceeding_max_tools(tmp_path: Path) -> None:
    with pytest.raises(SpecNormalizationError, match="Zero HTTP operations matched"):
        normalize_openapi_to_manifest(
            ACME_YAML_SPEC, "acme-incidents", tag_filter="nonexistent-tag"
        )

    many_paths: dict[str, Any] = {}
    for idx in range(MAX_TOOLS_PER_SERVER + 2):
        many_paths[f"/items/{idx}"] = {
            "get": {"operationId": f"get_item_{idx}", "summary": "Short"}
        }
    bloated_spec = {"openapi": "3.1.0", "info": {"title": "Bloated"}, "paths": many_paths}
    spec_file = tmp_path / "bloated.yaml"
    spec_file.write_text(yaml.safe_dump(bloated_spec), encoding="utf-8")

    with pytest.raises(SpecNormalizationError, match=f"max {MAX_TOOLS_PER_SERVER}"):
        normalize_openapi_to_manifest(spec_file, "bloated-server")


def test_duplicate_operation_ids_and_cli_main(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dup_spec = {
        "openapi": "3.1.0",
        "info": {"title": "Dup Test"},
        "paths": {
            "/items": {
                "get": {"operationId": "handle_items", "summary": "Short"},
                "post": {"operationId": "handle_items", "summary": "Short"},
            }
        },
    }
    spec_path = tmp_path / "dup.json"
    spec_path.write_text(json.dumps(dup_spec), encoding="utf-8")

    out_path = tmp_path / "manifest.json"
    main(["--spec", str(spec_path), "--name", "dup-srv", "--output", str(out_path)])
    written = json.loads(out_path.read_text(encoding="utf-8"))
    assert [t["name"] for t in written["tools"]] == ["handle_items", "post_handle_items"]
    assert written["tools"][0]["description"] == "Execute GET request on /items endpoint."

    main(["--spec", str(spec_path), "--name", "dup-srv"])
    captured = capsys.readouterr()
    assert '"server_name": "dup-srv"' in captured.out


def test_response_schema_x_mcp_fields_and_max_output_fields(tmp_path: Path) -> None:
    manifest = normalize_openapi_to_manifest(ACME_YAML_SPEC, "acme-incidents", max_output_fields=6)
    tools_by_name = {t["name"]: t for t in manifest["tools"]}

    get_inc = tools_by_name["get_incident"]
    assert get_inc["max_output_fields"] == 6
    assert get_inc["response_schema"] is not None
    assert "commander" in get_inc["response_schema"]["properties"]
    # Internal $ref CommanderInfo must already be inlined
    assert "name" in get_inc["response_schema"]["properties"]["commander"]["properties"]

    list_inc = tools_by_name["list_incidents"]
    assert list_inc["response_schema"] is not None
    assert "incidents" in list_inc["response_schema"]["properties"]

    del_inc = tools_by_name["delete_incident"]
    assert del_inc["response_schema"] is None

    with pytest.raises(SpecNormalizationError, match="max_output_fields"):
        normalize_openapi_to_manifest(ACME_YAML_SPEC, "acme-incidents", max_output_fields=0)
    with pytest.raises(SpecNormalizationError, match="max_output_fields"):
        normalize_openapi_to_manifest(ACME_YAML_SPEC, "acme-incidents", max_output_fields=25)

    custom_spec: dict[str, Any] = {
        "openapi": "3.1.0",
        "info": {"title": "Custom Fields"},
        "paths": {
            "/users/{user_id}": {
                "get": {
                    "operationId": "get_user",
                    "summary": "Fetch user record",
                    "x-mcp-fields": ["id", "commander.name", "id"],
                    "responses": {
                        "202": {
                            "description": "Accepted summary",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {"id": {"type": "string"}},
                                    }
                                }
                            },
                        }
                    },
                }
            }
        },
    }
    spec_file = tmp_path / "custom.json"
    spec_file.write_text(json.dumps(custom_spec), encoding="utf-8")
    parsed = normalize_openapi_to_manifest(spec_file, "users-srv")
    assert parsed["tools"][0]["x_mcp_fields"] == ["id", "commander.name"]
    assert parsed["tools"][0]["response_schema"] is not None

    bad_fields_spec = copy_spec = json.loads(json.dumps(custom_spec))
    copy_spec["paths"]["/users/{user_id}"]["get"]["x-mcp-fields"] = ["bad field!"]
    bad_file = tmp_path / "bad_fields.json"
    bad_file.write_text(json.dumps(bad_fields_spec), encoding="utf-8")
    with pytest.raises(SpecNormalizationError, match="invalid x-mcp-fields"):
        normalize_openapi_to_manifest(bad_file, "users-srv")

    empty_fields_spec = json.loads(json.dumps(custom_spec))
    empty_fields_spec["paths"]["/users/{user_id}"]["get"]["x-mcp-fields"] = []
    empty_file = tmp_path / "empty_fields.json"
    empty_file.write_text(json.dumps(empty_fields_spec), encoding="utf-8")
    with pytest.raises(SpecNormalizationError, match="non-empty list"):
        normalize_openapi_to_manifest(empty_file, "users-srv")
