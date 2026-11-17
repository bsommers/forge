"""Tests for Stages 2–5 Orchestrator & Local Codegen (forge/orchestrator.py, forge/codegen.py)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from forge.codegen import synthesize_workspace_code
from forge.ingest_openapi import normalize_openapi_to_manifest
from forge.orchestrator import (
    MAX_HEAL_ITERATIONS,
    ValidationOutcome,
    build_agent_task_prompt,
    emit_stage5_packaging_artifacts,
    invoke_sandboxed_agent,
    main,
    run_forge_pipeline,
    run_isolated_validation,
    run_local_validation,
    stage_workspace,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
ACME_YAML_SPEC = REPO_ROOT / "spec" / "acme-incidents.openapi.yaml"
BILLING_JSON_SPEC = REPO_ROOT / "spec" / "cloud-billing.openapi.json"
PROMPT_FILE = REPO_ROOT / "forge" / "AGENT_SYSTEM_PROMPT.md"


def _make_dummy_template(template_dir: Path) -> None:
    (template_dir / "src" / "tools").mkdir(parents=True, exist_ok=True)
    (template_dir / "src" / "tools" / "__init__.py").write_text("", encoding="utf-8")
    (template_dir / "src" / "tools" / "stub_example.py").write_text("# stub\n", encoding="utf-8")
    (template_dir / "tests" / "unit").mkdir(parents=True, exist_ok=True)
    (template_dir / "scripts").mkdir(parents=True, exist_ok=True)
    (template_dir / "scripts" / "validate_mcp.py").write_text(
        "import sys\nsys.exit(0)\n", encoding="utf-8"
    )


def test_stage_workspace_clears_stubs_and_writes_manifest(tmp_path: Path) -> None:
    tpl_dir = tmp_path / "template"
    _make_dummy_template(tpl_dir)
    out_dir = tmp_path / "workspace"
    out_dir.mkdir()
    (out_dir / "stale.txt").write_text("old", encoding="utf-8")

    manifest = normalize_openapi_to_manifest(ACME_YAML_SPEC, "acme-incidents")
    stage_workspace(tpl_dir, out_dir, manifest)

    assert not (out_dir / "stale.txt").exists()
    assert not (out_dir / "src" / "tools" / "stub_example.py").exists()
    assert (out_dir / "src" / "tools" / "__init__.py").exists()
    assert (out_dir / "tests" / "unit" / "__init__.py").exists()
    written_manifest = json.loads((out_dir / "forge-manifest.json").read_text(encoding="utf-8"))
    assert written_manifest["server_name"] == "acme-incidents"


def test_build_agent_task_prompt_initial_vs_self_healing() -> None:
    manifest = normalize_openapi_to_manifest(ACME_YAML_SPEC, "acme-incidents")
    p1 = build_agent_task_prompt(PROMPT_FILE, manifest, iteration=1, last_error_log=None)
    assert "## Target `forge-manifest.json`" in p1
    assert "Self-Healing Iteration" not in p1

    huge_log = "DROPPED_HEAD_MARKER_" + ("E" * 15000) + "FINAL_ERROR_TAIL"
    p2 = build_agent_task_prompt(PROMPT_FILE, manifest, iteration=2, last_error_log=huge_log)
    assert f"## Self-Healing Iteration 2/{MAX_HEAL_ITERATIONS}" in p2
    assert "FINAL_ERROR_TAIL" in p2
    assert "DROPPED_HEAD_MARKER_" not in p2


def test_invoke_sandboxed_agent_mounts_and_error_handling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "ws"
    (workspace / "src" / "tools").mkdir(parents=True)
    (workspace / "tests" / "unit").mkdir(parents=True)

    recorded_cmds: list[list[str]] = []

    def _fake_run(cmd: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:  # noqa: ANN401
        recorded_cmds.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    invoke_sandboxed_agent(workspace, "mcp-forge-agent:latest", "prompt-body")

    assert len(recorded_cmds) == 1
    cmd = recorded_cmds[0]
    assert "--cap-drop=ALL" in cmd
    assert "--security-opt=no-new-privileges:true" in cmd
    assert f"{workspace.resolve()}:/workspace:ro" in cmd
    assert f"{(workspace / 'src' / 'tools').resolve()}:/workspace/src/tools:rw" in cmd
    assert f"{(workspace / 'tests' / 'unit').resolve()}:/workspace/tests/unit:rw" in cmd
    assert not (workspace / ".forge-agent-prompt.md").exists()

    def _fail_run(cmd: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:  # noqa: ANN401
        return subprocess.CompletedProcess(cmd, 2, stdout="", stderr="container boom")

    monkeypatch.setattr(subprocess, "run", _fail_run)
    with pytest.raises(RuntimeError, match="exited with code 2"):
        invoke_sandboxed_agent(workspace, "mcp-forge-agent:latest", "prompt-body")


def test_run_isolated_validation_enforces_network_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorded_cmds: list[list[str]] = []

    def _fake_run(cmd: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:  # noqa: ANN401
        recorded_cmds.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="[PASS]", stderr="")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    outcome = run_isolated_validation(tmp_path, "mcp-forge-validator:latest")
    assert outcome.passed is True
    assert "[PASS]" in outcome.diagnostics
    cmd = recorded_cmds[0]
    assert "--network=none" in cmd
    assert "--cap-drop=ALL" in cmd
    assert f"{tmp_path.resolve()}:/workspace:ro" in cmd


def test_emit_stage5_packaging_artifacts_governance_flags(tmp_path: Path) -> None:
    acme_manifest = normalize_openapi_to_manifest(ACME_YAML_SPEC, "acme-incidents")
    artifacts = emit_stage5_packaging_artifacts(tmp_path, acme_manifest, "ghcr.io/acme")
    assert artifacts["protocol_revision"] == "2026-07-28"
    assert artifacts["container_image"] == "ghcr.io/acme/forged-mcp-acme-incidents:1.0.0"
    assert artifacts["governance"]["requires_appsec_destructive_signoff"] is True
    assert artifacts["governance"]["total_tools"] == 5

    readonly_manifest = normalize_openapi_to_manifest(
        BILLING_JSON_SPEC, "cloud-billing-ro", tag_filter="invoices"
    )
    ro_artifacts = emit_stage5_packaging_artifacts(tmp_path, readonly_manifest, "ghcr.io/acme")
    assert ro_artifacts["governance"]["requires_appsec_destructive_signoff"] is False
    assert ro_artifacts["governance"]["mutating_tools"] == []


def test_self_healing_retry_recovery_and_abort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tpl_dir = tmp_path / "tpl"
    _make_dummy_template(tpl_dir)
    out_dir = tmp_path / "out"

    agent_calls: list[int] = []
    monkeypatch.setattr(
        "forge.orchestrator.invoke_sandboxed_agent",
        lambda *_a, **_kw: agent_calls.append(1),
    )

    outcomes = iter(
        [
            ValidationOutcome(passed=False, diagnostics="ruff error on line 10"),
            ValidationOutcome(passed=True, diagnostics="[PASS]"),
        ]
    )
    monkeypatch.setattr(
        "forge.orchestrator.run_isolated_validation",
        lambda *_a, **_kw: next(outcomes),
    )

    artifacts = run_forge_pipeline(
        spec_path=ACME_YAML_SPEC,
        server_name="acme-incidents",
        golden_template_dir=tpl_dir,
        system_prompt_path=PROMPT_FILE,
        output_dir=out_dir,
        agent_image="agent:latest",
        validator_image="validator:latest",
    )
    assert len(agent_calls) == 2
    assert artifacts["governance"]["total_tools"] == 5

    monkeypatch.setattr(
        "forge.orchestrator.run_isolated_validation",
        lambda *_a, **_kw: ValidationOutcome(passed=False, diagnostics="persistent failure"),
    )
    with pytest.raises(SystemExit, match=f"after {MAX_HEAL_ITERATIONS} failed"):
        run_forge_pipeline(
            spec_path=ACME_YAML_SPEC,
            server_name="acme-incidents",
            golden_template_dir=tpl_dir,
            system_prompt_path=PROMPT_FILE,
            output_dir=tmp_path / "out_fail",
            agent_image="agent:latest",
            validator_image="validator:latest",
        )


def test_local_execution_mode_codegen_and_cli(tmp_path: Path) -> None:
    tpl_dir = tmp_path / "tpl"
    _make_dummy_template(tpl_dir)
    out_dir = tmp_path / "local_forged"

    main(
        [
            "--spec",
            str(BILLING_JSON_SPEC),
            "--name",
            "cloud-billing",
            "--template-dir",
            str(tpl_dir),
            "--prompt-file",
            str(PROMPT_FILE),
            "--output-dir",
            str(out_dir),
            "--local",
        ]
    )

    for tool_name in ("list_invoices", "get_budget", "upsert_budget", "dismiss_cost_alert"):
        tool_file = out_dir / "src" / "tools" / f"{tool_name}.py"
        assert tool_file.exists()
        code = tool_file.read_text(encoding="utf-8")
        assert f'name="{tool_name}"' in code

    assert (out_dir / "tests" / "unit" / "test_tools.py").exists()
    assert (out_dir / "README.md").exists()
    assert (out_dir / "forge-release-artifacts.json").exists()

    missing_outcome = run_local_validation(tmp_path / "empty_dir")
    assert missing_outcome.passed is False
    assert "Missing verification script" in missing_outcome.diagnostics

    acme_manifest = normalize_openapi_to_manifest(ACME_YAML_SPEC, "acme-incidents")
    written = synthesize_workspace_code(tmp_path / "synth_only", acme_manifest)
    assert len(written) == 7
