"""Stages 2–5: Self-Healing Orchestrator for MCP Server Forge (MCP 2026-07-28)."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from forge.codegen import synthesize_workspace_code
from forge.ingest_openapi import normalize_openapi_to_manifest

MAX_HEAL_ITERATIONS = 3


@dataclass(frozen=True)
class ValidationOutcome:
    """Result of executing the deterministic Stage 4 verification harness."""

    passed: bool
    diagnostics: str


def stage_workspace(
    golden_template_dir: Path,
    workspace_dir: Path,
    manifest: dict[str, Any],
) -> None:
    """Stage 2: Clone Golden Template, write forge-manifest.json, and clear stub tools."""
    if workspace_dir.exists():
        shutil.rmtree(workspace_dir)

    source_dir = golden_template_dir
    if not source_dir.exists() and (source_dir.resolve().parent / "src" / "server.py").exists():
        source_dir = source_dir.resolve().parent

    if (source_dir / ".venv").exists():
        shutil.copytree(
            source_dir,
            workspace_dir,
            ignore=shutil.ignore_patterns(
                ".venv",
                ".git",
                "__pycache__",
                ".pytest_cache",
                ".mypy_cache",
                ".ruff_cache",
                ".coverage",
                "dashboard",
                "docs",
                "spec",
                "forge",
                "golden-template",
                "test_ingest_openapi.py",
                "test_orchestrator.py",
            ),
        )
        (workspace_dir / ".venv").symlink_to((source_dir / ".venv").resolve())
    else:
        shutil.copytree(source_dir, workspace_dir)
        parent_venv = source_dir.resolve().parent / ".venv"
        if parent_venv.exists() and not (workspace_dir / ".venv").exists():
            (workspace_dir / ".venv").symlink_to(parent_venv)

    # Clear reference example tools so the agent builds strictly from forge-manifest.json
    tools_dir = workspace_dir / "src" / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    for py_file in tools_dir.glob("*.py"):
        if py_file.name != "__init__.py":
            py_file.unlink()

    unit_test_dir = workspace_dir / "tests" / "unit"
    unit_test_dir.mkdir(parents=True, exist_ok=True)
    for py_file in unit_test_dir.glob("*.py"):
        if py_file.name != "__init__.py":
            py_file.unlink()
    (unit_test_dir / "__init__.py").touch()

    manifest_path = workspace_dir / "forge-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def build_agent_task_prompt(
    system_prompt_path: Path,
    manifest: dict[str, Any],
    iteration: int,
    last_error_log: str | None,
) -> str:
    """Compose the initial generation prompt or self-healing retry prompt."""
    base_rules = system_prompt_path.read_text(encoding="utf-8")
    manifest_json = json.dumps(manifest, indent=2)

    if iteration == 1 or not last_error_log:
        return (
            f"{base_rules}\n\n"
            f"## Target `forge-manifest.json`\n```json\n{manifest_json}\n```\n\n"
            "Implement every tool listed in `forge-manifest.json` under `src/tools/`, "
            "write comprehensive `respx` unit tests (happy path + HTTP 401/404/429/500) "
            "under `tests/unit/`, and document setup + client snippets in `README.md`."
        )

    return (
        f"{base_rules}\n\n"
        f"## Self-Healing Iteration {iteration}/{MAX_HEAL_ITERATIONS}\n"
        "Your previous implementation failed the deterministic Stage 4 verification suite. "
        "Inspect the exact error output below and fix the implementation in `src/tools/` "
        "or `tests/unit/` without weakening test coverage.\n\n"
        f"### Validator Diagnostics (`stderr`/`stdout`)\n```text\n{last_error_log[-12000:]}\n```"
    )


def invoke_sandboxed_agent(
    workspace_dir: Path,
    agent_image: str,
    prompt_text: str,
    llm_api_key_env: str = "ANTHROPIC_API_KEY",
) -> None:
    """
    Stage 3: Run the coding agent inside a hardened container.
    - Root filesystem of workspace is mounted read-only (:ro).
    - ONLY src/tools/, tests/unit/, and README.md are overlaid read-write (:rw).
    - Linux capabilities are dropped; privilege escalation is blocked.
    """
    prompt_file = workspace_dir / ".forge-agent-prompt.md"
    prompt_file.write_text(prompt_text, encoding="utf-8")

    readme_path = workspace_dir / "README.md"
    readme_path.touch(exist_ok=True)

    docker_cmd = [
        "docker",
        "run",
        "--rm",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true",
        "--pids-limit=256",
        "--memory=2g",
        "-e",
        llm_api_key_env,
        "-w",
        "/workspace",
        # Mount full repository READ-ONLY first so locked files cannot be tampered with
        "-v",
        f"{workspace_dir.resolve()}:/workspace:ro",
        # Overlay ONLY permitted agent-writable paths as READ-WRITE
        "-v",
        f"{(workspace_dir / 'src' / 'tools').resolve()}:/workspace/src/tools:rw",
        "-v",
        f"{(workspace_dir / 'tests' / 'unit').resolve()}:/workspace/tests/unit:rw",
        "-v",
        f"{readme_path.resolve()}:/workspace/README.md:rw",
        agent_image,
        "claude",
        "--print",
        "--dangerously-skip-permissions",
        "-p",
        "/workspace/.forge-agent-prompt.md",
    ]
    proc = subprocess.run(docker_cmd, text=True, capture_output=True, check=False)  # noqa: S603
    prompt_file.unlink(missing_ok=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"Coding agent container exited with code {proc.returncode}:\n{proc.stderr}"
        )


def run_isolated_validation(
    workspace_dir: Path,
    validator_image: str,
) -> ValidationOutcome:
    """
    Stage 4: Execute `scripts/validate_mcp.py` inside a `--network=none` container
    so tests cannot make live outbound calls or exfiltrate secrets.
    """
    docker_cmd = [
        "docker",
        "run",
        "--rm",
        "--network=none",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true",
        "-w",
        "/workspace",
        "-v",
        f"{workspace_dir.resolve()}:/workspace:ro",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=256m",  # noqa: S108
        "-e",
        "PYTHONDONTWRITEBYTECODE=1",
        "-e",
        "COVERAGE_FILE=/tmp/.coverage",  # noqa: S108
        validator_image,
        "uv",
        "run",
        "--frozen",
        "python",
        "scripts/validate_mcp.py",
    ]
    proc = subprocess.run(docker_cmd, text=True, capture_output=True, check=False)  # noqa: S603
    combined = f"{proc.stdout}\n{proc.stderr}".strip()
    return ValidationOutcome(passed=(proc.returncode == 0), diagnostics=combined)


def run_local_validation(workspace_dir: Path) -> ValidationOutcome:
    """Execute `scripts/validate_mcp.py` locally via `sys.executable` for offline runs."""
    validator_script = workspace_dir / "scripts" / "validate_mcp.py"
    if not validator_script.exists():
        return ValidationOutcome(
            passed=False,
            diagnostics=f"Missing verification script: {validator_script}",
        )
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = str(workspace_dir.resolve())
    proc = subprocess.run(  # noqa: S603
        [sys.executable, str(validator_script)],
        cwd=workspace_dir,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    combined = f"{proc.stdout}\n{proc.stderr}".strip()
    return ValidationOutcome(passed=(proc.returncode == 0), diagnostics=combined)


def emit_stage5_packaging_artifacts(
    workspace_dir: Path,
    manifest: dict[str, Any],
    registry_prefix: str,
) -> dict[str, Any]:
    """
    Stage 5: Generate client `mcpServers` JSON snippets and PR security governance metadata
    flagging mutating/destructive tools per MCP 2026-07-28 Human-in-the-Loop guidelines.
    """
    server_name = manifest["server_name"]
    image_tag = f"{registry_prefix}/forged-mcp-{server_name}:{manifest['version']}"

    required_envs: list[str] = []
    base_url_env = manifest.get("upstream", {}).get("base_url_env")
    if base_url_env:
        required_envs.append(base_url_env)
    for key, val in manifest.get("auth", {}).items():
        if key.endswith("_env") and isinstance(val, str):
            required_envs.append(val)

    docker_args = ["run", "-i", "--rm"]
    for env_var in required_envs:
        docker_args.extend(["-e", env_var])
    docker_args.append(image_tag)

    client_config = {
        "mcpServers": {
            server_name: {
                "command": "docker",
                "args": docker_args,
                "env": {env_var: f"${{{env_var}}}" for env_var in required_envs},
            }
        }
    }

    mutating_tools = [
        {
            "name": t["name"],
            "method": t["method"],
            "path": t["path"],
            "destructiveHint": t.get("annotations", {}).get("destructiveHint", False),
        }
        for t in manifest["tools"]
        if not t.get("annotations", {}).get("readOnlyHint", False)
    ]

    artifacts: dict[str, Any] = {
        "protocol_revision": "2026-07-28",
        "container_image": image_tag,
        "client_config": client_config,
        "governance": {
            "required_labels": ["needs-security-review", "mcp-2026-07-28"],
            "requires_appsec_destructive_signoff": any(
                t["destructiveHint"] for t in mutating_tools
            ),
            "mutating_tools": mutating_tools,
            "total_tools": len(manifest["tools"]),
        },
    }
    out_path = workspace_dir / "forge-release-artifacts.json"
    out_path.write_text(json.dumps(artifacts, indent=2) + "\n", encoding="utf-8")
    return artifacts


def run_forge_pipeline(
    spec_path: Path,
    server_name: str,
    golden_template_dir: Path,
    system_prompt_path: Path,
    output_dir: Path,
    agent_image: str,
    validator_image: str,
    registry_prefix: str = "ghcr.io/org",
    tag_filter: str | None = None,
    execution_mode: str = "docker",
) -> dict[str, Any]:
    """Run all 5 stages of the MCP Server Forge pipeline."""
    print(f"[Stage 1] Normalizing {spec_path} -> forge-manifest.json ...", file=sys.stderr)  # noqa: T201
    manifest = normalize_openapi_to_manifest(spec_path, server_name, tag_filter=tag_filter)

    print(  # noqa: T201
        f"[Stage 2] Scaffolding locked FastMCP 4.2 Golden Template in {output_dir} ...",
        file=sys.stderr,
    )
    stage_workspace(golden_template_dir, output_dir, manifest)

    last_diagnostics: str | None = None
    for attempt in range(1, MAX_HEAL_ITERATIONS + 1):
        print(  # noqa: T201
            f"[Stage 3] Running Coding Agent (Iteration {attempt}/{MAX_HEAL_ITERATIONS}) ...",
            file=sys.stderr,
        )
        prompt = build_agent_task_prompt(system_prompt_path, manifest, attempt, last_diagnostics)
        if execution_mode == "local":
            synthesize_workspace_code(output_dir, manifest)
        else:
            invoke_sandboxed_agent(output_dir, agent_image=agent_image, prompt_text=prompt)

        print(  # noqa: T201
            f"[Stage 4] Running Offline Verification Harness (Iteration {attempt}) ...",
            file=sys.stderr,
        )
        if execution_mode == "local":
            outcome = run_local_validation(output_dir)
        else:
            outcome = run_isolated_validation(output_dir, validator_image=validator_image)

        if outcome.passed:
            print("[Stage 4] Verification PASSED!", file=sys.stderr)  # noqa: T201
            break
        last_diagnostics = outcome.diagnostics
        print(  # noqa: T201
            f"[Stage 4] Verification FAILED on attempt {attempt}:\n{outcome.diagnostics}",
            file=sys.stderr,
        )
    else:
        raise SystemExit(
            f"Forge aborted after {MAX_HEAL_ITERATIONS} failed verification attempts."
        )

    print(  # noqa: T201
        "[Stage 5] Emitting deployment snippets & PR governance report ...",
        file=sys.stderr,
    )
    artifacts = emit_stage5_packaging_artifacts(output_dir, manifest, registry_prefix)
    print(json.dumps(artifacts, indent=2))  # noqa: T201
    return artifacts


def main(argv: list[str] | None = None) -> None:
    """CLI entrypoint for the MCP Server Forge 5-Stage Orchestrator."""
    parser = argparse.ArgumentParser(description="MCP Server Forge Orchestrator (MCP 2026-07-28)")
    parser.add_argument("--spec", type=Path, required=True, help="OpenAPI 3.x YAML/JSON file")
    parser.add_argument("--name", type=str, required=True, help="Kebab-case MCP server name")
    parser.add_argument("--tag-filter", type=str, default=None, help="Optional OpenAPI tag slice")
    parser.add_argument("--template-dir", type=Path, default=Path("./golden-template"))
    parser.add_argument("--prompt-file", type=Path, default=Path("./forge/AGENT_SYSTEM_PROMPT.md"))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--agent-image", type=str, default="mcp-forge-agent:latest")
    parser.add_argument("--validator-image", type=str, default="mcp-forge-validator:latest")
    parser.add_argument("--registry-prefix", type=str, default="ghcr.io/org")
    parser.add_argument(
        "--execution-mode",
        choices=("docker", "local"),
        default="docker",
        help="Execution mode: 'docker' (hardened containers) or 'local' (deterministic codegen)",
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="Shorthand for --execution-mode local",
    )
    args = parser.parse_args(argv)
    mode = "local" if args.local else args.execution_mode

    run_forge_pipeline(
        spec_path=args.spec,
        server_name=args.name,
        golden_template_dir=args.template_dir,
        system_prompt_path=args.prompt_file,
        output_dir=args.output_dir,
        agent_image=args.agent_image,
        validator_image=args.validator_image,
        registry_prefix=args.registry_prefix,
        tag_filter=args.tag_filter,
        execution_mode=mode,
    )


if __name__ == "__main__":
    main()
