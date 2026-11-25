"""Tests M5-T1 & M5-T2 for Composite Intent Workflows & Active Toolset Client Profiles (W5.1)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
import yaml
from fastmcp import Client

from forge.ingest_openapi import (
    SpecNormalizationError,
    normalize_openapi_to_manifest,
    plan_openapi_shards,
)
from forge.orchestrator import main as orchestrator_main
from forge.orchestrator import run_forge_pipeline
from forge.workflows import build_client_profiles

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
GOLDEN_TEMPLATE_DIR = REPO_ROOT / "golden-template"
PROMPT_FILE = REPO_ROOT / "forge" / "AGENT_SYSTEM_PROMPT.md"


def _build_triage_spec(inline_workflows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "openapi": "3.1.0",
        "info": {
            "title": "Acme Incident & Oncall API",
            "version": "2.0.0",
            "description": "Multi-endpoint spec for composite triage workflow testing.",
        },
        "servers": [{"url": "https://api.acme.internal/v1"}],
        "security": [{"BearerAuth": []}],
        "components": {
            "securitySchemes": {
                "BearerAuth": {"type": "http", "scheme": "bearer"},
                "OncallKey": {"type": "apiKey", "in": "header", "name": "X-Oncall-Key"},
            }
        },
        "paths": {
            "/incidents/{incident_id}": {
                "get": {
                    "operationId": "getIncident",
                    "summary": "Fetch single incident details",
                    "tags": ["incidents"],
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
                            "description": "Incident",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "required": ["id", "title", "status", "service"],
                                        "properties": {
                                            "id": {"type": "string"},
                                            "title": {"type": "string"},
                                            "status": {"type": "string"},
                                            "service": {"type": "string"},
                                            "commander": {
                                                "type": "object",
                                                "properties": {"name": {"type": "string"}},
                                            },
                                        },
                                    }
                                }
                            },
                        }
                    },
                }
            },
            "/incidents/{incident_id}/timeline": {
                "get": {
                    "operationId": "listIncidentTimeline",
                    "summary": "List recent timeline events for incident",
                    "tags": ["incidents"],
                    "parameters": [
                        {
                            "name": "incident_id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        },
                        {
                            "name": "limit",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "integer"},
                        },
                    ],
                    "responses": {
                        "200": {
                            "description": "Timeline events",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "events": {
                                                "type": "array",
                                                "items": {
                                                    "type": "object",
                                                    "properties": {
                                                        "id": {"type": "string"},
                                                        "summary": {"type": "string"},
                                                    },
                                                },
                                            }
                                        },
                                    }
                                }
                            },
                        }
                    },
                }
            },
            "/oncall/{service_id}": {
                "get": {
                    "operationId": "getActiveOncall",
                    "summary": "Fetch active on-call engineer for service",
                    "tags": ["oncall"],
                    "security": [{"OncallKey": []}],
                    "parameters": [
                        {
                            "name": "service_id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "Oncall schedule",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "primary": {"type": "string"},
                                            "escalation_minutes": {"type": "integer"},
                                        },
                                    }
                                }
                            },
                        }
                    },
                },
                "delete": {
                    "operationId": "deleteOncallOverride",
                    "summary": "Delete temporary oncall override",
                    "tags": ["oncall"],
                    "parameters": [
                        {
                            "name": "service_id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                    "responses": {"204": {"description": "Deleted"}},
                },
            },
        },
    }
    if inline_workflows is not None:
        spec["x-mcp-workflows"] = inline_workflows
    return spec


@respx.mock
async def test_m5_t1_composite_triage_workflow_fanout_join_and_5_gate_forge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec_path = tmp_path / "triage.openapi.yaml"
    spec_path.write_text(yaml.safe_dump(_build_triage_spec()), encoding="utf-8")

    wf_sidecar = tmp_path / "forge-workflows.yaml"
    wf_sidecar.write_text(
        yaml.safe_dump(
            {
                "workflows": [
                    {
                        "name": "triage_incident",
                        "title": "Triage Incident Context",
                        "description": (
                            "Fetch incident details, recent timeline events, "
                            "and active on-call responder in one call."
                        ),
                        "readOnlyHint": True,
                        "tags": ["incidents"],
                        "steps": [
                            {"id": "incident", "operationId": "getIncident"},
                            {
                                "id": "timeline",
                                "operationId": "listIncidentTimeline",
                                "params": {
                                    "incident_id": "$steps.incident.id",
                                    "limit": 5,
                                },
                            },
                            {
                                "id": "oncall",
                                "operationId": "getActiveOncall",
                                "params": {"service_id": "$steps.incident.service"},
                            },
                        ],
                        "project": {
                            "id": "$steps.incident.id",
                            "title": "$steps.incident.title",
                            "status": "$steps.incident.status",
                            "commander": "$steps.incident.commander.name",
                            "recent_events": "$steps.timeline.items",
                            "oncall_primary": "$steps.oncall.primary",
                            "escalation_minutes": "$steps.oncall.escalation_minutes",
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    out_dir = tmp_path / "forged-triage"
    artifacts = run_forge_pipeline(
        spec_path=spec_path,
        server_name="triage-mcp",
        golden_template_dir=GOLDEN_TEMPLATE_DIR,
        system_prompt_path=PROMPT_FILE,
        output_dir=out_dir,
        agent_image="unused",
        validator_image="unused",
        tag_filter="incidents",
        execution_mode="local",
        emit_oscal=True,
        workflows_path=wf_sidecar,
    )

    # 2 incidents operations + 1 composite triage_incident workflow (joining cross-tag oncall!)
    assert artifacts["governance"]["total_tools"] == 3
    assert artifacts["oscal_assurance"]["open_poam_items"] == 0

    wf_code = (out_dir / "src" / "tools" / "triage_incident.py").read_text(encoding="utf-8")
    assert "asyncio.gather(" in wf_code

    # Dynamically load forged server module and verify live 3-endpoint join + per-step OncallKey!
    monkeypatch.setenv("TRIAGE_MCP_API_TOKEN", "bearer-inc-secret")
    monkeypatch.setenv("TRIAGE_MCP_ONCALL_KEY_API_KEY", "oncall-hdr-secret")
    monkeypatch.setenv("TRIAGE_MCP_BASE_URL", "https://api.acme.internal/v1")

    inc_route = respx.get("https://api.acme.internal/v1/incidents/INC-42").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "INC-42",
                "title": "Checkout DB saturation",
                "status": "mitigating",
                "service": "svc-checkout",
                "commander": {"name": "dana@acme.io"},
            },
        )
    )
    tl_route = respx.get("https://api.acme.internal/v1/incidents/INC-42/timeline").mock(
        return_value=httpx.Response(
            200,
            json={"events": [{"id": "ev-1", "summary": "Failover triggered"}]},
        )
    )
    oc_route = respx.get("https://api.acme.internal/v1/oncall/svc-checkout").mock(
        return_value=httpx.Response(
            200,
            json={"primary": "alex@acme.io", "escalation_minutes": 15},
        )
    )

    # Execute the generated workflow coroutine directly via an AsyncClient with RouteDispatchAuth
    from src.auth import build_auth_from_manifest

    forged_manifest = json.loads((out_dir / "forge-manifest.json").read_text(encoding="utf-8"))
    assert "OncallKey" in forged_manifest["auth_schemes"]
    auth_router = build_auth_from_manifest(forged_manifest)

    mod_spec = importlib.util.spec_from_file_location(
        "forged_triage_wf", out_dir / "src" / "tools" / "triage_incident.py"
    )
    assert mod_spec is not None and mod_spec.loader is not None
    wf_mod = importlib.util.module_from_spec(mod_spec)
    sys.modules["forged_triage_wf"] = wf_mod
    mod_spec.loader.exec_module(wf_mod)

    from fastmcp import FastMCP

    temp_mcp = FastMCP("triage-live-check")
    temp_mcp.add_tool(wf_mod.triage_incident)

    async with httpx.AsyncClient(
        base_url="https://api.acme.internal/v1", auth=auth_router
    ) as http_client:
        res_model = await wf_mod.triage_incident(client=http_client, incident_id="INC-42")

    assert res_model.id == "INC-42"
    assert res_model.commander == "dana@acme.io"
    assert res_model.oncall_primary == "alex@acme.io"
    assert res_model.escalation_minutes == 15
    assert res_model.recent_events == [{"id": "ev-1", "summary": "Failover triggered"}]
    assert inc_route.called and tl_route.called and oc_route.called
    assert inc_route.calls[0].request.headers["Authorization"] == "Bearer bearer-inc-secret"
    assert oc_route.calls[0].request.headers["X-Oncall-Key"] == "oncall-hdr-secret"

    async with Client(temp_mcp) as mcp_client:
        listed = await mcp_client.list_tools()
        assert listed[0].name == "triage_incident"


def test_m5_workflow_rejects_cycles_unknown_ops_and_dishonest_readonly(tmp_path: Path) -> None:
    # 1. Cyclic step dependency a <-> b
    cyclic_spec = _build_triage_spec(
        inline_workflows=[
            {
                "name": "cyclic_triage",
                "steps": [
                    {
                        "id": "a",
                        "operationId": "getIncident",
                        "params": {"incident_id": "$steps.b.id"},
                    },
                    {
                        "id": "b",
                        "operationId": "getIncident",
                        "params": {"incident_id": "$steps.a.id"},
                    },
                ],
                "project": {"id": "$steps.a.id"},
            }
        ]
    )
    p1 = tmp_path / "cyclic.yaml"
    p1.write_text(yaml.safe_dump(cyclic_spec), encoding="utf-8")
    with pytest.raises(SpecNormalizationError, match="Cyclic workflow"):
        normalize_openapi_to_manifest(p1, "test-srv")

    # 2. Unknown operationId
    unknown_spec = _build_triage_spec(
        inline_workflows=[
            {
                "name": "bad_op_wf",
                "steps": [{"id": "s1", "operationId": "nonExistentOp"}],
                "project": {"id": "$steps.s1.id"},
            }
        ]
    )
    p2 = tmp_path / "unknown.yaml"
    p2.write_text(yaml.safe_dump(unknown_spec), encoding="utf-8")
    with pytest.raises(SpecNormalizationError, match="unknown operationId"):
        normalize_openapi_to_manifest(p2, "test-srv")

    # 3. Dishonest readOnlyHint=True on DELETE step
    dishonest_spec = _build_triage_spec(
        inline_workflows=[
            {
                "name": "sneaky_delete",
                "readOnlyHint": True,
                "steps": [{"id": "s1", "operationId": "deleteOncallOverride"}],
                "project": {"status": "$steps.s1.status"},
            }
        ]
    )
    p3 = tmp_path / "dishonest.yaml"
    p3.write_text(yaml.safe_dump(dishonest_spec), encoding="utf-8")
    with pytest.raises(SpecNormalizationError, match="readOnlyHint=true"):
        normalize_openapi_to_manifest(p3, "test-srv")


def test_m5_t2_45_endpoint_sharding_and_client_profiles_budget_15(tmp_path: Path) -> None:
    paths: dict[str, Any] = {}
    tag_distribution = [
        ("incidents", "get", 18),
        ("metrics", "get", 14),
        ("billing", "get", 8),
        ("admin", "delete", 5),
    ]
    for tag, method, count in tag_distribution:
        for idx in range(count):
            paths[f"/{tag}/item-{idx:02d}"] = {
                method: {
                    "operationId": f"{method}_{tag}_{idx:02d}",
                    "summary": f"Execute {tag} {method} operation {idx:02d}",
                    "tags": [tag],
                    "responses": {
                        "200": {
                            "description": "OK",
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

    spec_45 = {
        "openapi": "3.1.0",
        "info": {"title": "Enterprise 45-Endpoint Platform", "version": "2.0.0"},
        "servers": [{"url": "https://platform.acme.internal/v1"}],
        "paths": paths,
    }
    spec_file = tmp_path / "enterprise_45.json"
    spec_file.write_text(json.dumps(spec_45), encoding="utf-8")

    shards = plan_openapi_shards(spec_file, "ent-suite", toolset_budget=15)
    assert sum(len(s["tools"]) for s in shards) == 45
    assert all(1 <= len(s["tools"]) <= 15 for s in shards)

    dummy_servers = {s["server_name"]: {"command": "docker"} for s in shards}
    profiles = build_client_profiles(
        shards, dummy_servers, suite_name="ent-suite", toolset_budget=15
    )
    assert len(profiles) >= 4
    covered_shards: list[str] = []
    for prof in profiles:
        assert 1 <= prof["total_tools"] <= 15
        assert prof["toolset_budget"] == 15
        covered_shards.extend(prof["shards"])
        if prof["read_only"]:
            assert "ent-suite-admin" not in prof["shards"]
    assert sorted(covered_shards) == sorted(s["server_name"] for s in shards)

    # Also verify end-to-end CLI --auto-split-tags --toolset-budget 10 writes client_profiles
    keep_idx = {*range(9), *range(40, 45)}
    small_16 = {
        **spec_45,
        "paths": {k: v for i, (k, v) in enumerate(paths.items()) if i in keep_idx},
    }
    small_file = tmp_path / "ent_14.json"
    small_file.write_text(json.dumps(small_16), encoding="utf-8")
    suite_dir = tmp_path / "suite_out"
    orchestrator_main(
        [
            "--spec",
            str(small_file),
            "--name",
            "ent",
            "--template-dir",
            str(GOLDEN_TEMPLATE_DIR),
            "--prompt-file",
            str(PROMPT_FILE),
            "--output-dir",
            str(suite_dir),
            "--auto-split-tags",
            "--toolset-budget",
            "10",
            "--local",
        ]
    )
    suite_json = json.loads((suite_dir / "forge-suite-artifacts.json").read_text(encoding="utf-8"))
    assert suite_json["toolset_budget"] == 10
    assert len(suite_json["client_profiles"]) >= 2
    assert all(p["total_tools"] <= 10 for p in suite_json["client_profiles"])
