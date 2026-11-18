"""Tests T1-T6 for M1 High-Signal Response Schema Projection & --local Codegen."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from forge.codegen import render_tool_module, synthesize_workspace_code
from forge.orchestrator import run_forge_pipeline
from forge.projection import project_response_schema

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
GOLDEN_TEMPLATE_DIR = REPO_ROOT / "golden-template"
PROMPT_FILE = REPO_ROOT / "forge" / "AGENT_SYSTEM_PROMPT.md"


def _build_hundred_field_schema() -> dict[str, Any]:
    props: dict[str, Any] = {
        "id": {"type": "string", "description": "Unique incident ID."},
        "title": {"type": "string", "description": "Incident headline."},
        "status": {"type": "string", "description": "Current status."},
        "severity": {"type": "string", "description": "Severity level."},
        "commander": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Commander full name."},
                "avatar_b64": {"type": "string"},
            },
        },
        "total_usd": {"type": "number", "description": "Estimated impact in USD."},
        "updated_at": {"type": "string", "description": "Last update timestamp."},
        "raw_html": {"type": "string", "description": "Huge raw HTML body."},
        "stack_trace": {"type": "string", "description": "Internal stack trace."},
        "_internal_flag": {"type": "boolean"},
    }
    for idx in range(90):
        props[f"extra_telemetry_attr_{idx:03d}"] = {
            "type": "string" if idx % 2 == 0 else "integer",
            "description": f"Low-priority telemetry attribute #{idx}.",
        }
    return {
        "type": "object",
        "required": ["id", "title", "status", "severity"],
        "properties": props,
    }


def test_t1_hundred_field_schema_trimmed_deterministically() -> None:
    schema = _build_hundred_field_schema()
    proj1 = project_response_schema(schema, method="GET", max_output_fields=7)
    proj2 = project_response_schema(schema, method="GET", max_output_fields=7)

    assert proj1 == proj2
    assert proj1.kind == "object"
    assert len(proj1.fields) == 7
    names = [f.py_name for f in proj1.fields]
    assert names == [
        "id",
        "title",
        "severity",
        "status",
        "commander",
        "total_usd",
        "updated_at",
    ]
    assert "raw_html" not in names
    assert "stack_trace" not in names


def test_t2_x_mcp_fields_explicit_allowlist_and_nested_path() -> None:
    schema = _build_hundred_field_schema()
    proj = project_response_schema(
        schema,
        method="GET",
        x_mcp_fields=["id", "commander.name", "severity"],
        max_output_fields=8,
    )
    assert proj.kind == "object"
    assert [f.py_name for f in proj.fields] == ["id", "commander_name", "severity"]
    assert proj.fields[1].source_path == ("commander", "name")


def test_t3_paginated_collection_envelope_and_root_array() -> None:
    item_schema = _build_hundred_field_schema()
    envelope_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "incidents": {"type": "array", "items": item_schema},
            "next_cursor": {"type": "string"},
        },
    }
    proj = project_response_schema(envelope_schema, method="GET", max_output_fields=5)
    assert proj.kind == "collection"
    assert proj.collection_key == "incidents"
    assert proj.cursor_key == "next_cursor"
    assert len(proj.fields) == 5

    array_proj = project_response_schema(
        {"type": "array", "items": item_schema}, method="GET", max_output_fields=4
    )
    assert array_proj.kind == "collection"
    assert array_proj.collection_key is None
    assert len(array_proj.fields) == 4


def test_t4_and_t5_delete_204_ack_blocklist_and_legacy_fallback() -> None:
    del_proj = project_response_schema(None, method="DELETE")
    assert del_proj.kind == "status_ack"
    assert [f.py_name for f in del_proj.fields] == ["id", "deleted", "status"]

    only_blocked = {
        "type": "object",
        "properties": {
            "raw_html": {"type": "string"},
            "debug_blob": {"type": "string"},
            "_secret": {"type": "string"},
        },
    }
    blocked_proj = project_response_schema(only_blocked, method="GET", max_output_fields=8)
    assert blocked_proj.kind == "status_ack"
    assert [f.py_name for f in blocked_proj.fields] == ["id", "status"]

    legacy_tool: dict[str, Any] = {
        "name": "legacy_op",
        "method": "GET",
        "path": "/legacy",
        "description": "Legacy manifest entry without response_schema key.",
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
        "required_params": [],
    }
    legacy_code = render_tool_module(legacy_tool)
    assert "data: dict[str, Any]" in legacy_code


def test_t6_end_to_end_hundred_field_local_forge_passes_all_five_gates(tmp_path: Path) -> None:
    hundred_schema = _build_hundred_field_schema()
    spec_doc: dict[str, Any] = {
        "openapi": "3.1.0",
        "info": {
            "title": "Enterprise Hundred-Field Incident API",
            "version": "1.1.0",
            "description": "Synthetic 100-field API verifying M1 schema projection.",
        },
        "servers": [{"url": "https://api.enterprise.internal/v1"}],
        "components": {
            "securitySchemes": {"Bearer": {"type": "http", "scheme": "bearer"}},
            "schemas": {"BloatedIncident": hundred_schema},
        },
        "paths": {
            "/incidents/{incident_id}": {
                "get": {
                    "operationId": "get_incident",
                    "summary": "Get concise incident summary",
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
                            "description": "100-field upstream incident object",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/BloatedIncident"}
                                }
                            },
                        }
                    },
                },
                "delete": {
                    "operationId": "delete_incident",
                    "summary": "Delete incident record",
                    "parameters": [
                        {
                            "name": "incident_id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                    "responses": {"204": {"description": "Deleted"}},
                },
            },
            "/incidents": {
                "get": {
                    "operationId": "list_incidents",
                    "summary": "List operational incidents",
                    "parameters": [
                        {
                            "name": "limit",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "integer"},
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "Paginated 100-field incidents",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "incidents": {
                                                "type": "array",
                                                "items": {
                                                    "$ref": "#/components/schemas/BloatedIncident"
                                                },
                                            },
                                            "next_cursor": {"type": "string"},
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
    spec_path = tmp_path / "hundred_field.openapi.yaml"
    spec_path.write_text(yaml.safe_dump(spec_doc), encoding="utf-8")

    forged_dir = tmp_path / "forged_enterprise"
    artifacts = run_forge_pipeline(
        spec_path=spec_path,
        server_name="enterprise-incidents",
        golden_template_dir=GOLDEN_TEMPLATE_DIR,
        system_prompt_path=PROMPT_FILE,
        output_dir=forged_dir,
        agent_image="unused",
        validator_image="unused",
        execution_mode="local",
        max_output_fields=6,
    )
    assert artifacts["governance"]["total_tools"] == 3

    get_code = (forged_dir / "src" / "tools" / "get_incident.py").read_text(encoding="utf-8")
    assert "data: dict[str, Any]" not in get_code
    assert "extra_telemetry_attr_" not in get_code
    assert "commander: str | None" in get_code

    list_code = (forged_dir / "src" / "tools" / "list_incidents.py").read_text(encoding="utf-8")
    assert "class ListIncidentsItem(BaseModel):" in list_code
    assert "items: list[ListIncidentsItem]" in list_code

    # Determinism check: re-synthesizing produces byte-identical files
    manifest = json.loads((forged_dir / "forge-manifest.json").read_text(encoding="utf-8"))
    before_bytes = (forged_dir / "src" / "tools" / "get_incident.py").read_bytes()
    synthesize_workspace_code(forged_dir, manifest)
    after_bytes = (forged_dir / "src" / "tools" / "get_incident.py").read_bytes()
    assert before_bytes == after_bytes
