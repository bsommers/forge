"""Tests for M4 Wild OpenAPI Resilience, Dual-Axis Bounding & M3.5 Stage 5 OSCAL Attestation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
import yaml
from fastmcp import Client
from fastmcp.exceptions import ToolError

from forge.ingest_openapi import SpecNormalizationError, normalize_openapi_to_manifest
from forge.orchestrator import run_forge_pipeline
from forge.oscal_attestation import verify_oscal_policy_gate
from forge.projection import flatten_composed_schema, project_response_schema
from src.server import bound_structured_content, mcp

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_m4_w41_cyclic_refs_diamond_reuse_and_path_confined_relative_refs(
    tmp_path: Path,
) -> None:
    common_dir = tmp_path / "common"
    common_dir.mkdir()
    (common_dir / "tag.yaml").write_text(
        yaml.safe_dump(
            {
                "Tag": {
                    "type": "object",
                    "properties": {"key": {"type": "string"}, "value": {"type": "string"}},
                }
            }
        ),
        encoding="utf-8",
    )

    spec_doc: dict[str, Any] = {
        "openapi": "3.1.0",
        "info": {"title": "Cyclic & Relative Spec", "version": "1.0.0"},
        "components": {
            "schemas": {
                "User": {
                    "type": "object",
                    "required": ["id", "email"],
                    "properties": {
                        "id": {"type": "string"},
                        "email": {"type": "string"},
                        "manager": {"$ref": "#/components/schemas/User"},
                    },
                },
                "Ticket": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "reporter": {"$ref": "#/components/schemas/User"},
                        "assignee": {"$ref": "#/components/schemas/User"},
                        "primary_tag": {"$ref": "./common/tag.yaml#/Tag"},
                    },
                },
            }
        },
        "paths": {
            "/tickets/{ticket_id}": {
                "get": {
                    "operationId": "get_ticket",
                    "summary": "Retrieve ticket with cyclic user graph",
                    "parameters": [
                        {
                            "name": "ticket_id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "OK",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Ticket"}
                                }
                            },
                        }
                    },
                }
            }
        },
    }
    spec_file = tmp_path / "spec.yaml"
    spec_file.write_text(yaml.safe_dump(spec_doc), encoding="utf-8")

    manifest = normalize_openapi_to_manifest(spec_file, "tickets-mcp")
    resp_props = manifest["tools"][0]["response_schema"]["properties"]

    # Diamond reuse: both reporter and assignee expand User.email, while manager cycle breaks
    assert "email" in resp_props["reporter"]["properties"]
    assert "email" in resp_props["assignee"]["properties"]
    assert resp_props["reporter"]["properties"]["manager"]["x-mcp-cycle-broken"] is True
    assert "key" in resp_props["primary_tag"]["properties"]

    # Path traversal outside spec root directory MUST fail closed
    traversal_spec = json.loads(json.dumps(spec_doc))
    traversal_spec["components"]["schemas"]["Ticket"]["properties"]["primary_tag"] = {
        "$ref": "../outside.yaml#/Secret"
    }
    bad_file = tmp_path / "traversal.yaml"
    bad_file.write_text(yaml.safe_dump(traversal_spec), encoding="utf-8")
    with pytest.raises(SpecNormalizationError, match="path traversal"):
        normalize_openapi_to_manifest(bad_file, "tickets-mcp")


def test_m4_w42_allof_nullable_union_and_datapoints_array_projection() -> None:
    composed_metric: dict[str, Any] = {
        "allOf": [
            {
                "type": "object",
                "required": ["id"],
                "properties": {
                    "id": {"type": "string"},
                    "created_at": {"type": "string"},
                    "updated_at": {"type": "string"},
                    "deleted_at": {"type": "string"},
                },
            },
            {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "datapoints": {"type": "array", "items": {"type": "number"}},
                    "note": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                },
            },
        ]
    }
    flat = flatten_composed_schema(composed_metric)
    assert flat["properties"]["note"]["nullable"] is True

    proj = project_response_schema(composed_metric, method="GET", max_output_fields=4)
    assert proj.kind == "object"
    projected_names = {f.py_name: f.py_type for f in proj.fields}
    assert projected_names["id"] == "str"
    assert projected_names["name"] == "str | None"
    assert projected_names["datapoints"] == "list[float]"


@respx.mock
async def test_m4_w44_dual_axis_middleware_bounds_3500_short_ids_and_live_mcp_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 1. Direct torture test: 3,500 10-byte IDs (~49 KiB, zero strings >= 16 bytes)
    short_id_payload: dict[str, Any] = {
        "items": [f"inc-{i:06d}" for i in range(3500)],
        "next_cursor": "cur-2",
        "total_returned": 3500,
        "truncated": False,
    }
    bounded = bound_structured_content(short_id_payload, budget_bytes=16_000)
    wire_bytes = len(json.dumps(bounded, ensure_ascii=True, separators=(",", ":")).encode("utf-8"))
    assert wire_bytes <= 16_000
    assert 1 <= len(bounded["items"]) < 3500
    assert bounded["total_returned"] == len(bounded["items"])
    assert bounded["truncated"] is True

    # 2. Irreducible scalar grid fail-closed check
    irreducible = {f"counter_{i:03d}": 987654321 for i in range(40)}
    with pytest.raises(ToolError, match="safety budget"):
        bound_structured_content(irreducible, budget_bytes=128)

    # 3. Live FastMCP middleware check on list_incidents returning 900 short-field items (> 60 KiB)
    monkeypatch.setenv("ACME_API_TOKEN", "test-token")
    monkeypatch.setenv("ACME_BASE_URL", "https://api.acme.internal/v1")
    many_incidents = [
        {"id": f"INC-{i:05d}", "title": "db-lat", "severity": "sev2", "status": "monitoring"}
        for i in range(900)
    ]
    respx.get("https://api.acme.internal/v1/incidents").mock(
        return_value=httpx.Response(
            200, json={"incidents": many_incidents, "next_cursor": "c-900"}
        )
    )
    async with Client(mcp) as client:
        res = await client.call_tool("list_incidents", {"limit": 100})
        assert res.is_error is False
        assert res.structured_content is not None
        sc = res.structured_content
        assert 1 <= len(sc["incidents"]) < 900
        assert sc["total_returned"] == len(sc["incidents"])
        assert len(json.dumps(sc).encode("utf-8")) <= 16_384


def test_m4_w43_and_m35_end_to_end_wild_spec_forge_with_emit_oscal(tmp_path: Path) -> None:
    wild_spec: dict[str, Any] = {
        "openapi": "3.1.0",
        "info": {
            "title": "Wild Observability & Alerts API",
            "version": "1.4.0",
            "description": "Exercises cyclic refs, allOf datapoints, typed POST body, and OSCAL.",
        },
        "servers": [{"url": "https://obs.acme.internal/v1"}],
        "components": {
            "securitySchemes": {
                "BearerAuth": {"type": "http", "scheme": "bearer"},
            },
            "schemas": {
                "BaseMeta": {
                    "type": "object",
                    "required": ["id"],
                    "properties": {
                        "id": {"type": "string"},
                        "updated_at": {"type": "string"},
                    },
                },
                "Owner": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "backup": {"$ref": "#/components/schemas/Owner"},
                    },
                },
                "MetricSeries": {
                    "allOf": [
                        {"$ref": "#/components/schemas/BaseMeta"},
                        {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "owner": {"$ref": "#/components/schemas/Owner"},
                                "datapoints": {"type": "array", "items": {"type": "number"}},
                            },
                        },
                    ]
                },
            },
        },
        "paths": {
            "/metrics/{metric_id}": {
                "get": {
                    "operationId": "get_metric_series",
                    "summary": "Fetch metric series with datapoints",
                    "parameters": [
                        {
                            "name": "metric_id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "Series",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/MetricSeries"}
                                }
                            },
                        }
                    },
                }
            },
            "/alerts": {
                "post": {
                    "operationId": "create_alert_rule",
                    "summary": "Create typed alert rule with float, enum, list, and object",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["name", "threshold", "severity"],
                                    "properties": {
                                        "name": {"type": "string"},
                                        "threshold": {"type": "number"},
                                        "severity": {
                                            "type": "string",
                                            "enum": ["critical", "warning", "info"],
                                        },
                                        "tags": {
                                            "type": "array",
                                            "items": {"type": "string"},
                                        },
                                        "routing": {
                                            "type": "object",
                                            "required": ["team_id"],
                                            "properties": {
                                                "team_id": {"type": "string"},
                                                "escalate": {"type": "boolean"},
                                            },
                                        },
                                    },
                                }
                            }
                        },
                    },
                    "responses": {
                        "201": {
                            "description": "Created",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "required": ["id", "status"],
                                        "properties": {
                                            "id": {"type": "string"},
                                            "status": {"type": "string"},
                                        },
                                    }
                                }
                            },
                        }
                    },
                }
            },
        },
    }
    spec_file = tmp_path / "wild.yaml"
    spec_file.write_text(yaml.safe_dump(wild_spec), encoding="utf-8")
    out_dir = tmp_path / "forged-wild"

    artifacts = run_forge_pipeline(
        spec_path=spec_file,
        server_name="wild-obs",
        golden_template_dir=REPO_ROOT / "golden-template",
        system_prompt_path=REPO_ROOT / "forge" / "AGENT_SYSTEM_PROMPT.md",
        output_dir=out_dir,
        agent_image="unused",
        validator_image="unused",
        registry_prefix="ghcr.io/bsommers",
        execution_mode="local",
        emit_oscal=True,
    )

    # Verify W4.3 generated tool source uses real float, Literal, list[str], and nested BaseModel
    alert_src = (out_dir / "src" / "tools" / "create_alert_rule.py").read_text(encoding="utf-8")
    assert "float," in alert_src
    assert 'Literal["critical", "warning", "info"]' in alert_src
    assert "list[str] | None" in alert_src
    assert "class CreateAlertRuleRoutingInput(BaseModel):" in alert_src

    # Verify M3.5 OSCAL 1.1.2 bundle emitted and passes policy gate with SC-5 satisfied
    oscal_meta = artifacts["oscal_assurance"]
    assert oscal_meta["oscal_ssp_gate_allow"] is True
    assert (out_dir / "SSP.md").is_file()
    ssp = json.loads((out_dir / "oscal" / "ssp.json").read_text(encoding="utf-8"))
    sar = json.loads((out_dir / "oscal" / "assessment-results.json").read_text(encoding="utf-8"))
    poam = json.loads((out_dir / "oscal" / "poam.json").read_text(encoding="utf-8"))
    assert verify_oscal_policy_gate(ssp, sar, poam) == []

    sc5_finding = next(
        f
        for f in sar["assessment-results"]["results"][0]["findings"]
        if f["target"]["target-id"] == "sc-5"
    )
    assert sc5_finding["target"]["status"]["state"] == "satisfied"
