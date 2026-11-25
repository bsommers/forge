"""Tests M5-T3 & M5-T4 for Host OS Kernel Sandboxing & Recorded Contract Replay (W5.2)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from scripts.validate_mcp import check_payload_against_schema

from forge.orchestrator import run_forge_pipeline
from forge.oscal_attestation import emit_oscal_assurance_bundle, verify_oscal_policy_gate
from forge.sandbox import (
    SandboxCapability,
    SandboxUnavailableError,
    build_linux_bwrap_command,
    build_macos_seatbelt_profile,
    prepare_sandboxed_agent_command,
    probe_kernel_sandbox_capability,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
GOLDEN_TEMPLATE_DIR = REPO_ROOT / "golden-template"
ACME_YAML_SPEC = REPO_ROOT / "spec" / "acme-incidents.openapi.yaml"
PROMPT_FILE = REPO_ROOT / "forge" / "AGENT_SYSTEM_PROMPT.md"


def test_m5_t3_macos_seatbelt_and_linux_bwrap_profiles_protect_locked_workspace(
    tmp_path: Path,
) -> None:
    # Place workspace inside tmp_path (/tmp or /var/folders) to verify workspace re-locking!
    ws = tmp_path / "forged_ws"
    (ws / "src" / "tools").mkdir(parents=True)
    (ws / "tests" / "unit").mkdir(parents=True)
    (ws / "README.md").write_text("# Forged\n", encoding="utf-8")
    fake_home = tmp_path / "fake_home"
    (fake_home / ".ssh").mkdir(parents=True)
    (fake_home / ".aws").mkdir(parents=True)

    sbpl = build_macos_seatbelt_profile(ws, allow_network=False, home_dir=fake_home)
    assert "(version 1)" in sbpl
    assert "(deny network*)" in sbpl
    assert f'(subpath "{(fake_home / ".ssh").resolve()}")' in sbpl
    assert f'(subpath "{(fake_home / ".aws").resolve()}")' in sbpl

    # Crucial rule ordering invariant: workspace deny MUST come AFTER /tmp allow and BEFORE
    # the 3 agent-writable carve-outs!
    tmp_allow_pos = sbpl.index('(subpath "/tmp")')
    ws_deny_pos = sbpl.index(f'(deny file-write* (subpath "{ws.resolve()}"))')
    tools_allow_pos = sbpl.index(f'(subpath "{(ws / "src" / "tools").resolve()}")')
    assert tmp_allow_pos < ws_deny_pos < tools_allow_pos

    # Linux bwrap command verification
    bwrap_cmd = build_linux_bwrap_command(
        ["python3", "agent.py"],
        ws,
        bwrap_bin="/usr/bin/bwrap",
        allow_network=False,
        home_dir=fake_home,
    )
    assert bwrap_cmd[:5] == ["/usr/bin/bwrap", "--die-with-parent", "--ro-bind", "/", "/"]
    assert "--unshare-net" in bwrap_cmd
    assert str(fake_home / ".ssh") in bwrap_cmd
    ws_ro_idx = bwrap_cmd.index(str(ws.resolve()))
    tools_rw_idx = bwrap_cmd.index(str((ws / "src" / "tools").resolve()))
    assert bwrap_cmd[ws_ro_idx - 1] == "--ro-bind"
    assert bwrap_cmd[tools_rw_idx - 1] == "--bind"
    assert ws_ro_idx < tools_rw_idx


def test_m5_t3_sandbox_wrapper_policies_and_sc39_poam_closure(tmp_path: Path) -> None:
    ws = tmp_path / "ws_sb"
    (ws / "src" / "tools").mkdir(parents=True)
    (ws / "tests" / "unit").mkdir(parents=True)

    # 1. Simulated macOS seatbelt capability wraps with sandbox-exec -f <profile.sb>
    mac_cap = SandboxCapability(
        backend="macos-seatbelt",
        available=True,
        outer_sandbox_detected=False,
        binary_path="/usr/bin/sandbox-exec",
        reason="ok",
    )
    plan_mac = prepare_sandboxed_agent_command(
        ["python3", "-V"], ws, policy="required", capability=mac_cap
    )
    try:
        assert plan_mac.enforced is True
        assert plan_mac.command[:2] == ["/usr/bin/sandbox-exec", "-f"]
        assert Path(plan_mac.command[2]).is_file()
    finally:
        for p in plan_mac.cleanup_paths:
            p.unlink(missing_ok=True)

    # 2. Simulated bare unsandboxed host fails closed under policy='required'
    none_cap = SandboxCapability(
        backend="none",
        available=False,
        outer_sandbox_detected=False,
        binary_path=None,
        reason="bwrap missing",
    )
    with pytest.raises(SandboxUnavailableError, match="NIST SC-39"):
        prepare_sandboxed_agent_command(
            ["python3", "-V"], ws, policy="required", capability=none_cap
        )

    # 3. Live host capability probe runs deterministically without crashing
    live_cap = probe_kernel_sandbox_capability()
    assert live_cap.backend in {"macos-seatbelt", "linux-bwrap", "none"}

    # 4. Verify SC-39 / POAM-FORGE-W5.2 is CLOSED (0 POA&Ms) when sandbox_enforced=True,
    #    and honestly re-opened if --sandbox-policy=off disables sandboxing in agent mode!
    dummy_manifest = {
        "protocol_revision": "2026-07-28",
        "server_name": "acme-incidents",
        "title": "Acme Incidents",
        "version": "2.0.0",
        "description": "Test server",
        "tools": [],
    }
    closed_summary = emit_oscal_assurance_bundle(
        ws,
        dummy_manifest,
        {"container_image": "ghcr.io/bsommers/acme:2.0.0"},
        execution_mode="agent",
        sandbox_enforced=True,
        sandbox_backend="macos-seatbelt",
    )
    assert closed_summary["open_poam_items"] == 0
    sar_closed = json.loads((ws / "oscal" / "assessment-results.json").read_text(encoding="utf-8"))
    sc39_closed = next(
        f
        for f in sar_closed["assessment-results"]["results"][0]["findings"]
        if f["target"]["target-id"] == "sc-39"
    )
    assert sc39_closed["target"]["status"]["state"] == "satisfied"

    open_summary = emit_oscal_assurance_bundle(
        ws,
        dummy_manifest,
        {"container_image": "ghcr.io/bsommers/acme:2.0.0"},
        execution_mode="agent",
        sandbox_enforced=False,
        sandbox_backend="disabled",
    )
    assert open_summary["open_poam_items"] == 1
    ssp = json.loads((ws / "oscal" / "ssp.json").read_text(encoding="utf-8"))
    sar = json.loads((ws / "oscal" / "assessment-results.json").read_text(encoding="utf-8"))
    poam = json.loads((ws / "oscal" / "poam.json").read_text(encoding="utf-8"))
    assert verify_oscal_policy_gate(ssp, sar, poam) == []


def test_m5_t4_recorded_contract_fixture_replay_catches_null_drift_with_jsonpath(
    tmp_path: Path,
) -> None:
    # Unit-level JSONPath drift diagnostics
    inc_schema = {
        "type": "object",
        "required": ["id", "severity", "status"],
        "properties": {
            "id": {"type": "string"},
            "severity": {"type": "string", "enum": ["sev1", "sev2", "sev3"]},
            "status": {"type": "string"},
        },
    }
    drifts = check_payload_against_schema(
        {"id": "INC-101", "severity": None, "status": "open"},
        inc_schema,
    )
    assert len(drifts) == 1
    assert "$.severity" in drifts[0]
    assert "undocumented null" in drifts[0]

    # End-to-end Stage 2-5 forge with valid recorded fixture succeeds; drifted fixture fails Gate!
    valid_fx = tmp_path / "valid_fixtures"
    valid_fx.mkdir()
    (valid_fx / "get_incident.json").write_text(
        json.dumps(
            {
                "tool": "get_incident",
                "args": {"incident_id": "INC-101"},
                "status_code": 200,
                "response": {
                    "id": "INC-101",
                    "title": "API gateway spike",
                    "severity": "sev2",
                    "status": "investigating",
                },
            }
        ),
        encoding="utf-8",
    )

    forged_dir = tmp_path / "forged_with_fixtures"
    artifacts = run_forge_pipeline(
        spec_path=ACME_YAML_SPEC,
        server_name="acme-incidents",
        golden_template_dir=GOLDEN_TEMPLATE_DIR,
        system_prompt_path=PROMPT_FILE,
        output_dir=forged_dir,
        agent_image="unused",
        validator_image="unused",
        execution_mode="local",
        emit_oscal=True,
        fixtures_dir=valid_fx,
    )
    assert artifacts["oscal_assurance"]["open_poam_items"] == 0
    assert (forged_dir / "tests" / "fixtures" / "get_incident.json").is_file()

    # Now run validate_mcp.py against a drifted recorded production fixture (severity=null)
    bad_fx = tmp_path / "drifted_fixtures"
    bad_fx.mkdir()
    (bad_fx / "get_incident.json").write_text(
        json.dumps(
            {
                "tool": "get_incident",
                "args": {"incident_id": "INC-101"},
                "status_code": 200,
                "response": {
                    "id": "INC-101",
                    "title": "API gateway spike",
                    "severity": None,
                    "status": "investigating",
                },
            }
        ),
        encoding="utf-8",
    )
    proc = subprocess.run(  # noqa: S603
        [
            sys.executable,
            str(forged_dir / "scripts" / "validate_mcp.py"),
            "--fixtures-dir",
            str(bad_fx),
        ],
        cwd=forged_dir,
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode != 0
    assert "Recorded Contract Fixture Replay" in proc.stderr
    assert "$.severity" in proc.stderr
