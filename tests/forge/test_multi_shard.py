"""Tests M3-T4..T6 for Automated Multi-Tag Sharding (--auto-split-tags) & CI Hardening."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from forge.ingest_openapi import MAX_TOOLS_PER_SERVER, plan_openapi_shards
from forge.orchestrator import main

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
GOLDEN_TEMPLATE_DIR = REPO_ROOT / "golden-template"
PROMPT_FILE = REPO_ROOT / "forge" / "AGENT_SYSTEM_PROMPT.md"
PINNED_ACTION_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@[0-9a-f]{40}$")


def _build_large_multi_tag_spec(
    incidents_count: int = 17,
    billing_count: int = 4,
    audit_count: int = 3,
) -> dict[str, Any]:
    paths: dict[str, Any] = {}
    for idx in range(incidents_count):
        paths[f"/incidents/op-{idx:02d}"] = {
            "get": {
                "operationId": f"get_incident_metric_{idx:02d}",
                "summary": f"Fetch incident metric {idx:02d} summary",
                "tags": ["incidents"],
                "responses": {
                    "200": {
                        "description": "Metric payload",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
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
        }
    for idx in range(billing_count):
        paths[f"/billing/inv-{idx:02d}"] = {
            "get": {
                "operationId": f"get_invoice_{idx:02d}",
                "summary": f"Retrieve billing invoice {idx:02d}",
                "tags": ["billing"],
                "responses": {
                    "200": {
                        "description": "Invoice payload",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "invoice_id": {"type": "string"},
                                        "total_usd": {"type": "number"},
                                    },
                                }
                            }
                        },
                    }
                },
            }
        }
    for idx in range(audit_count):
        paths[f"/audit/log-{idx:02d}"] = {
            "delete": {
                "operationId": f"purge_audit_{idx:02d}",
                "summary": f"Purge audit archive {idx:02d}",
                "tags": ["audit"],
                "security": [{"AdminKey": []}],
                "responses": {"204": {"description": "Deleted"}},
            }
        }

    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Acme Platform Monolith API",
            "version": "1.3.0",
            "description": "24-endpoint multi-domain OpenAPI specification.",
        },
        "servers": [{"url": "https://api.platform.internal/v1"}],
        "security": [{"BearerAuth": []}],
        "components": {
            "securitySchemes": {
                "BearerAuth": {"type": "http", "scheme": "bearer"},
                "AdminKey": {"type": "apiKey", "in": "header", "name": "X-Admin-Key"},
            }
        },
        "paths": paths,
    }


def test_m3_t4_plan_openapi_shards_chunks_oversized_tags_and_prunes_auth(tmp_path: Path) -> None:
    spec_path = tmp_path / "monolith_24.yaml"
    spec_path.write_text(yaml.safe_dump(_build_large_multi_tag_spec()), encoding="utf-8")

    shards = plan_openapi_shards(spec_path, "acme-platform", max_output_fields=6)
    shard_names = [s["server_name"] for s in shards]
    assert shard_names == [
        "acme-platform-audit",
        "acme-platform-billing",
        "acme-platform-incidents-part1",
        "acme-platform-incidents-part2",
    ]
    for shard in shards:
        assert 1 <= len(shard["tools"]) <= MAX_TOOLS_PER_SERVER
        assert shard["upstream"]["base_url_env"] == "ACME_PLATFORM_BASE_URL"

    by_name = {s["server_name"]: s for s in shards}
    # AdminKey should ONLY appear in the audit shard, never in read-only billing/incidents shards!
    assert "AdminKey" in by_name["acme-platform-audit"]["auth_schemes"]
    assert "auth_schemes" not in by_name["acme-platform-billing"]
    assert len(by_name["acme-platform-incidents-part1"]["tools"]) == 15
    assert len(by_name["acme-platform-incidents-part2"]["tools"]) == 2


def test_m3_t5_auto_split_tags_cli_forges_and_validates_all_shards(tmp_path: Path) -> None:
    # 18 total operations (> 15 ceiling) across 2 tags (10 incidents + 8 billing)
    spec_doc = _build_large_multi_tag_spec(incidents_count=10, billing_count=6, audit_count=2)
    spec_path = tmp_path / "platform_18.json"
    spec_path.write_text(json.dumps(spec_doc), encoding="utf-8")

    suite_out = tmp_path / "sharded_suite"
    main(
        [
            "--spec",
            str(spec_path),
            "--name",
            "acme-suite",
            "--template-dir",
            str(GOLDEN_TEMPLATE_DIR),
            "--prompt-file",
            str(PROMPT_FILE),
            "--output-dir",
            str(suite_out),
            "--auto-split-tags",
            "--local",
        ]
    )

    suite_report = json.loads(
        (suite_out / "forge-suite-artifacts.json").read_text(encoding="utf-8")
    )
    assert suite_report["total_shards"] == 3
    assert suite_report["governance"]["total_tools"] == 18
    assert suite_report["governance"]["requires_appsec_destructive_signoff"] is True

    mcp_servers = suite_report["client_config"]["mcpServers"]
    assert set(mcp_servers.keys()) == {
        "acme-suite-audit",
        "acme-suite-billing",
        "acme-suite-incidents",
    }
    for s_name in mcp_servers:
        assert (suite_out / s_name / "forge-release-artifacts.json").exists()


def test_m3_t6_github_workflows_are_sha_pinned_and_least_privilege() -> None:
    workflows_dir = REPO_ROOT / ".github" / "workflows"
    workflow_files = sorted(workflows_dir.glob("*.yml"))
    assert len(workflow_files) >= 2

    for wf_path in workflow_files:
        raw_text = wf_path.read_text(encoding="utf-8")
        wf = yaml.safe_load(raw_text)
        assert wf.get("permissions") == {"contents": "read"}, (
            f"{wf_path.name} must set top-level permissions: contents: read"
        )
        assert wf.get("concurrency", {}).get("cancel-in-progress") is True, (
            f"{wf_path.name} must enable concurrency cancel-in-progress"
        )
        assert "pull_request_target" not in raw_text

        for job_name, job in wf.get("jobs", {}).items():
            assert isinstance(job.get("timeout-minutes"), int), (
                f"{wf_path.name}:{job_name} must set explicit timeout-minutes"
            )
            for step in job.get("steps", []):
                if "uses" in step:
                    uses_val = str(step["uses"]).strip()
                    assert PINNED_ACTION_RE.match(uses_val), (
                        f"{wf_path.name}:{job_name} unpinned action '{uses_val}'"
                    )
