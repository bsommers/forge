"""Tests T7-T8 for M2 Host-Agent Semantic Refinement & SHA-256 Lock Guard."""

from __future__ import annotations

import stat
import sys
from pathlib import Path

import pytest

from forge.ingest_openapi import normalize_openapi_to_manifest
from forge.orchestrator import (
    TamperDetectionError,
    invoke_host_agent,
    run_forge_pipeline,
    snapshot_locked_digests,
    stage_workspace,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
GOLDEN_TEMPLATE_DIR = REPO_ROOT / "golden-template"
ACME_YAML_SPEC = REPO_ROOT / "spec" / "acme-incidents.openapi.yaml"
PROMPT_FILE = REPO_ROOT / "forge" / "AGENT_SYSTEM_PROMPT.md"


def test_t7_tamper_detection_aborts_and_restores_locked_files(tmp_path: Path) -> None:
    workspace = tmp_path / "ws_tamper"
    manifest = normalize_openapi_to_manifest(ACME_YAML_SPEC, "acme-incidents")
    stage_workspace(GOLDEN_TEMPLATE_DIR, workspace, manifest)

    auth_file = workspace / "src" / "auth.py"
    original_auth = auth_file.read_bytes()
    baseline_digests = snapshot_locked_digests(workspace)
    assert "src/auth.py" in baseline_digests
    assert "tests/contract/test_forge_contract.py" in baseline_digests

    # Rogue agent script that runs chmod +w on src/auth.py and overwrites it
    rogue_script = tmp_path / "rogue_agent.py"
    rogue_script.write_text(
        "import os, stat, sys\n"
        "from pathlib import Path\n"
        "ws = Path(os.environ['FORGE_WORKSPACE_DIR'])\n"
        "target = ws / 'src' / 'auth.py'\n"
        "target.chmod(stat.S_IRUSR | stat.S_IWUSR)\n"
        "target.write_text('# TAMPERED AUTH\\n', encoding='utf-8')\n",
        encoding="utf-8",
    )

    with pytest.raises(TamperDetectionError, match="src/auth.py"):
        invoke_host_agent(
            workspace_dir=workspace,
            agent_cmd=f"{sys.executable} {rogue_script}",
            prompt_text="prompt",
        )

    # Verify src/auth.py was restored byte-for-byte and permissions are writable again for cleanup
    assert auth_file.read_bytes() == original_auth
    assert bool(stat.S_IMODE(auth_file.stat().st_mode) & stat.S_IWUSR)

    with pytest.raises(ValueError, match="non-empty --agent-cmd"):
        invoke_host_agent(workspace_dir=workspace, agent_cmd="   ", prompt_text="prompt")


def test_t8_host_agent_self_healing_two_attempts_passes_five_gates(tmp_path: Path) -> None:
    state_file = tmp_path / "attempt_counter.txt"
    agent_script = tmp_path / "healing_host_agent.py"
    agent_script.write_text(
        "import sys\n"
        "from pathlib import Path\n"
        "prompt_path = Path(sys.argv[1])\n"
        "ws = Path(sys.argv[2])\n"
        "state = Path(sys.argv[3])\n"
        "count = int(state.read_text()) + 1 if state.exists() else 1\n"
        "state.write_text(str(count))\n"
        "prompt_text = prompt_path.read_text(encoding='utf-8')\n"
        "broken = ws / 'src' / 'tools' / 'broken_extra.py'\n"
        "if count == 1:\n"
        "    # Verify locked files are 0444 read-only while agent runs\n"
        "    auth_mode = (ws / 'src' / 'auth.py').stat().st_mode\n"
        "    assert (auth_mode & 0o222) == 0, 'Expected src/auth.py to be 0444 read-only'\n"
        "    broken.write_text('import os\\n', encoding='utf-8')\n"
        "else:\n"
        "    assert 'Self-Healing Iteration 2' in prompt_text\n"
        "    broken.unlink(missing_ok=True)\n",
        encoding="utf-8",
    )

    forged_dir = tmp_path / "host_agent_forged"
    agent_cmd = (
        f"{sys.executable} {agent_script} "
        "{prompt_file} {workspace} "
        f"{state_file}"
    )

    artifacts = run_forge_pipeline(
        spec_path=ACME_YAML_SPEC,
        server_name="acme-incidents",
        golden_template_dir=GOLDEN_TEMPLATE_DIR,
        system_prompt_path=PROMPT_FILE,
        output_dir=forged_dir,
        agent_image="unused",
        validator_image="unused",
        execution_mode="agent",
        agent_cmd=agent_cmd,
        max_output_fields=6,
    )

    assert state_file.read_text(encoding="utf-8") == "2"
    assert artifacts["governance"]["total_tools"] == 5
    assert (forged_dir / "forge-release-artifacts.json").exists()
