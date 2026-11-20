"""Stages 2–5: Self-Healing Orchestrator for MCP Server Forge (MCP 2026-07-28)."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from forge.codegen import synthesize_workspace_code
from forge.ingest_openapi import (
    DEFAULT_MAX_OUTPUT_FIELDS,
    normalize_openapi_to_manifest,
    plan_openapi_shards,
)
from forge.oscal_attestation import emit_oscal_assurance_bundle

MAX_HEAL_ITERATIONS = 3

LOCKED_RELATIVE_PATHS: tuple[str, ...] = (
    "pyproject.toml",
    "Dockerfile",
    "forge-manifest.json",
    "respx",
    "src/auth.py",
    "src/deps.py",
    "src/server.py",
    "tests/contract",
    "scripts/validate_mcp.py",
)


class TamperDetectionError(RuntimeError):
    """Raised when a host-mode coding agent modifies or deletes a locked Golden Template path."""


@dataclass(frozen=True)
class ValidationOutcome:
    """Result of executing the deterministic Stage 4 verification harness."""

    passed: bool
    diagnostics: str


def _iter_locked_files(workspace_dir: Path) -> list[Path]:
    found: list[Path] = []
    for rel in LOCKED_RELATIVE_PATHS:
        target = workspace_dir / rel
        if not target.exists():
            continue
        if target.is_file():
            found.append(target)
        elif target.is_dir():
            for child in sorted(target.rglob("*")):
                if (
                    child.is_file()
                    and "__pycache__" not in child.parts
                    and child.suffix != ".pyc"
                ):
                    found.append(child)
    return sorted(set(found))


def snapshot_locked_digests(workspace_dir: Path) -> dict[str, str]:
    """Compute SHA-256 hex digests for all locked Golden Template files in workspace_dir."""
    digests: dict[str, str] = {}
    for file_path in _iter_locked_files(workspace_dir):
        rel = file_path.relative_to(workspace_dir).as_posix()
        digests[rel] = hashlib.sha256(file_path.read_bytes()).hexdigest()
    return digests


def _snapshot_locked_bytes(workspace_dir: Path) -> dict[str, bytes]:
    return {
        p.relative_to(workspace_dir).as_posix(): p.read_bytes()
        for p in _iter_locked_files(workspace_dir)
    }


def _set_locked_permissions(workspace_dir: Path, *, writable: bool) -> None:
    for file_path in _iter_locked_files(workspace_dir):
        current_mode = stat.S_IMODE(file_path.stat().st_mode)
        if writable:
            file_path.chmod(current_mode | stat.S_IWUSR)
        else:
            file_path.chmod(current_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))


def enforce_and_verify_locked_digests(
    workspace_dir: Path,
    baseline_digests: dict[str, str],
    baseline_bytes: dict[str, bytes] | None = None,
) -> None:
    """Verify no locked Golden Template file was modified, deleted, or injected; restore & abort."""
    current_digests = snapshot_locked_digests(workspace_dir)
    tampered: list[str] = []

    for rel, expected_hash in baseline_digests.items():
        actual_hash = current_digests.get(rel)
        if actual_hash != expected_hash:
            tampered.append(rel)

    for rel in current_digests:
        if rel not in baseline_digests:
            tampered.append(rel)

    if tampered:
        if baseline_bytes is not None:
            for rel in tampered:
                target = workspace_dir / rel
                if rel in baseline_bytes:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if target.exists():
                        target.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
                    target.write_bytes(baseline_bytes[rel])
                elif target.exists():
                    target.unlink()
        joined = ", ".join(sorted(set(tampered)))
        raise TamperDetectionError(
            f"Locked Golden Template path(s) modified during host-agent execution: {joined}"
        )


def _unlock_tree_for_rmtree(root: Path) -> None:
    for p in root.rglob("*"):
        if not p.is_symlink():
            try:
                p.chmod(stat.S_IMODE(p.stat().st_mode) | stat.S_IWUSR)
            except OSError:
                pass


def stage_workspace(
    golden_template_dir: Path,
    workspace_dir: Path,
    manifest: dict[str, Any],
) -> None:
    """Stage 2: Clone Golden Template, write forge-manifest.json, and clear stub tools."""
    if workspace_dir.exists():
        _unlock_tree_for_rmtree(workspace_dir)
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
                "test_docs_alignment.py",
                "test_schema_projection.py",
                "test_host_agent_mode.py",
                "test_per_op_auth.py",
                "test_multi_shard.py",
            ),
        )
        (workspace_dir / ".venv").symlink_to((source_dir / ".venv").resolve())
    else:
        shutil.copytree(source_dir, workspace_dir)
        parent_venv = source_dir.resolve().parent / ".venv"
        if parent_venv.exists() and not (workspace_dir / ".venv").exists():
            (workspace_dir / ".venv").symlink_to(parent_venv)

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
        "-v",
        f"{workspace_dir.resolve()}:/workspace:ro",
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


def invoke_host_agent(
    workspace_dir: Path,
    agent_cmd: str,
    prompt_text: str,
    timeout_sec: float = 300.0,
) -> None:
    """
    Stage 3 (Docker-free `agent` mode): Run a host CLI coding agent against workspace_dir
    while enforcing 0444 read-only permissions and pre/post SHA-256 lock verification.
    """
    if not agent_cmd.strip():
        raise ValueError("Host-agent mode requires a non-empty --agent-cmd command string.")

    baseline_digests = snapshot_locked_digests(workspace_dir)
    baseline_bytes = _snapshot_locked_bytes(workspace_dir)

    prompt_file = (workspace_dir / ".forge-agent-prompt.md").resolve()
    prompt_file.write_text(prompt_text, encoding="utf-8")

    raw_tokens = shlex.split(agent_cmd)
    uses_prompt_placeholder = any("{prompt_file}" in tok for tok in raw_tokens)
    resolved_cmd = [
        tok.replace("{prompt_file}", str(prompt_file)).replace(
            "{workspace}", str(workspace_dir.resolve())
        )
        for tok in raw_tokens
    ]

    env = dict(os.environ)
    env["FORGE_PROMPT_FILE"] = str(prompt_file)
    env["FORGE_WORKSPACE_DIR"] = str(workspace_dir.resolve())

    _set_locked_permissions(workspace_dir, writable=False)
    try:
        proc = subprocess.run(  # noqa: S603
            resolved_cmd,
            cwd=workspace_dir,
            env=env,
            input=None if uses_prompt_placeholder else prompt_text,
            text=True,
            capture_output=True,
            timeout=timeout_sec,
            check=False,
        )
    finally:
        _set_locked_permissions(workspace_dir, writable=True)
        prompt_file.unlink(missing_ok=True)

    enforce_and_verify_locked_digests(workspace_dir, baseline_digests, baseline_bytes)

    if proc.returncode != 0:
        raise RuntimeError(
            f"Host coding agent exited with code {proc.returncode}:\n{proc.stderr}"
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
    *,
    emit_oscal: bool = False,
    execution_mode: str = "docker",
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
        if key.endswith("_env") and isinstance(val, str) and val not in required_envs:
            required_envs.append(val)
    named_schemes = manifest.get("auth_schemes", {})
    if isinstance(named_schemes, dict):
        for sub_cfg in named_schemes.values():
            if isinstance(sub_cfg, dict):
                for key, val in sub_cfg.items():
                    if (
                        key.endswith("_env")
                        and isinstance(val, str)
                        and val not in required_envs
                    ):
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
    if emit_oscal:
        artifacts["oscal_assurance"] = emit_oscal_assurance_bundle(
            workspace_dir=workspace_dir,
            manifest=manifest,
            release_artifacts=artifacts,
            execution_mode=execution_mode,
        )
    out_path = workspace_dir / "forge-release-artifacts.json"
    out_path.write_text(json.dumps(artifacts, indent=2) + "\n", encoding="utf-8")
    return artifacts


def _execute_manifest_pipeline(
    manifest: dict[str, Any],
    golden_template_dir: Path,
    system_prompt_path: Path,
    output_dir: Path,
    agent_image: str,
    validator_image: str,
    registry_prefix: str,
    execution_mode: str,
    agent_cmd: str,
    emit_oscal: bool = False,
) -> dict[str, Any]:
    print(
        f"[Stage 2] Scaffolding locked FastMCP 4.x Golden Template in {output_dir} ...",
        file=sys.stderr,
    )
    stage_workspace(golden_template_dir, output_dir, manifest)

    last_diagnostics: str | None = None
    for attempt in range(1, MAX_HEAL_ITERATIONS + 1):
        print(
            f"[Stage 3] Running Coding Agent (Iteration {attempt}/{MAX_HEAL_ITERATIONS}) ...",
            file=sys.stderr,
        )
        prompt = build_agent_task_prompt(system_prompt_path, manifest, attempt, last_diagnostics)
        if execution_mode == "local":
            synthesize_workspace_code(output_dir, manifest)
        elif execution_mode == "agent":
            if attempt == 1:
                synthesize_workspace_code(output_dir, manifest)
            invoke_host_agent(output_dir, agent_cmd=agent_cmd, prompt_text=prompt)
        else:
            invoke_sandboxed_agent(output_dir, agent_image=agent_image, prompt_text=prompt)

        print(
            f"[Stage 4] Running Offline Verification Harness (Iteration {attempt}) ...",
            file=sys.stderr,
        )
        if execution_mode in {"local", "agent"}:
            outcome = run_local_validation(output_dir)
        else:
            outcome = run_isolated_validation(output_dir, validator_image=validator_image)

        if outcome.passed:
            print("[Stage 4] Verification PASSED!", file=sys.stderr)
            break
        last_diagnostics = outcome.diagnostics
        print(
            f"[Stage 4] Verification FAILED on attempt {attempt}:\n{outcome.diagnostics}",
            file=sys.stderr,
        )
    else:
        raise SystemExit(
            f"Forge aborted after {MAX_HEAL_ITERATIONS} failed verification attempts."
        )

    print(
        "[Stage 5] Emitting deployment snippets & PR governance report ...",
        file=sys.stderr,
    )
    return emit_stage5_packaging_artifacts(
        output_dir,
        manifest,
        registry_prefix,
        emit_oscal=emit_oscal,
        execution_mode=execution_mode,
    )


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
    agent_cmd: str = "",
    max_output_fields: int = DEFAULT_MAX_OUTPUT_FIELDS,
    emit_oscal: bool = False,
) -> dict[str, Any]:
    """Run all 5 stages of the MCP Server Forge pipeline."""
    print(f"[Stage 1] Normalizing {spec_path} -> forge-manifest.json ...", file=sys.stderr)
    manifest = normalize_openapi_to_manifest(
        spec_path,
        server_name,
        tag_filter=tag_filter,
        max_output_fields=max_output_fields,
    )
    artifacts = _execute_manifest_pipeline(
        manifest=manifest,
        golden_template_dir=golden_template_dir,
        system_prompt_path=system_prompt_path,
        output_dir=output_dir,
        agent_image=agent_image,
        validator_image=validator_image,
        registry_prefix=registry_prefix,
        execution_mode=execution_mode,
        agent_cmd=agent_cmd,
        emit_oscal=emit_oscal,
    )
    print(json.dumps(artifacts, indent=2))
    return artifacts


def run_sharded_forge_pipeline(
    spec_path: Path,
    server_name: str,
    golden_template_dir: Path,
    system_prompt_path: Path,
    output_dir: Path,
    agent_image: str,
    validator_image: str,
    registry_prefix: str = "ghcr.io/org",
    execution_mode: str = "docker",
    agent_cmd: str = "",
    max_output_fields: int = DEFAULT_MAX_OUTPUT_FIELDS,
    emit_oscal: bool = False,
) -> dict[str, Any]:
    """Partition an OpenAPI spec by tag into <=15-tool shards and forge every shard."""
    print(f"[Stage 1] Planning domain shards for {spec_path} ...", file=sys.stderr)
    shard_manifests = plan_openapi_shards(
        spec_path=spec_path,
        base_server_name=server_name,
        max_output_fields=max_output_fields,
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    merged_mcp_servers: dict[str, Any] = {}
    shard_reports: list[dict[str, Any]] = []
    all_mutating: list[dict[str, Any]] = []
    total_tools = 0

    for shard_manifest in shard_manifests:
        s_name = str(shard_manifest["server_name"])
        shard_dir = output_dir / s_name
        shard_art = _execute_manifest_pipeline(
            manifest=shard_manifest,
            golden_template_dir=golden_template_dir,
            system_prompt_path=system_prompt_path,
            output_dir=shard_dir,
            agent_image=agent_image,
            validator_image=validator_image,
            registry_prefix=registry_prefix,
            execution_mode=execution_mode,
            agent_cmd=agent_cmd,
            emit_oscal=emit_oscal,
        )
        merged_mcp_servers.update(shard_art["client_config"]["mcpServers"])
        gov = shard_art["governance"]
        all_mutating.extend(gov["mutating_tools"])
        total_tools += int(gov["total_tools"])
        shard_reports.append(
            {
                "server_name": s_name,
                "workspace": shard_dir.name,
                "container_image": shard_art["container_image"],
                "tool_count": gov["total_tools"],
            }
        )

    suite_artifacts: dict[str, Any] = {
        "protocol_revision": "2026-07-28",
        "suite_name": server_name,
        "total_shards": len(shard_reports),
        "shards": shard_reports,
        "client_config": {"mcpServers": merged_mcp_servers},
        "governance": {
            "required_labels": ["needs-security-review", "mcp-2026-07-28"],
            "requires_appsec_destructive_signoff": any(
                t["destructiveHint"] for t in all_mutating
            ),
            "mutating_tools": all_mutating,
            "total_tools": total_tools,
        },
    }
    suite_path = output_dir / "forge-suite-artifacts.json"
    suite_path.write_text(json.dumps(suite_artifacts, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(suite_artifacts, indent=2))
    return suite_artifacts


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
        "--max-output-fields",
        type=int,
        default=DEFAULT_MAX_OUTPUT_FIELDS,
        help="Maximum high-signal fields projected per tool outputSchema (1..20, default 8)",
    )
    parser.add_argument(
        "--execution-mode",
        choices=("docker", "local", "agent"),
        default="docker",
        help="Execution mode: 'docker', 'local' (deterministic projection), or 'agent' (host CLI)",
    )
    parser.add_argument(
        "--agent-cmd",
        type=str,
        default="",
        help="Host CLI command for --execution-mode agent ({prompt_file}, {workspace})",
    )
    parser.add_argument(
        "--auto-split-tags",
        action="store_true",
        help="Automatically partition >15-tool specs by OpenAPI tag into <=15-tool shards",
    )
    parser.add_argument(
        "--emit-oscal",
        action="store_true",
        help="Emit NIST OSCAL 1.1.2 SSP, SAR, POA&M, and SSP.md during Stage 5",
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="Shorthand for --execution-mode local",
    )
    args = parser.parse_args(argv)
    mode = "local" if args.local else args.execution_mode

    if args.auto_split_tags:
        run_sharded_forge_pipeline(
            spec_path=args.spec,
            server_name=args.name,
            golden_template_dir=args.template_dir,
            system_prompt_path=args.prompt_file,
            output_dir=args.output_dir,
            agent_image=args.agent_image,
            validator_image=args.validator_image,
            registry_prefix=args.registry_prefix,
            execution_mode=mode,
            agent_cmd=args.agent_cmd,
            max_output_fields=args.max_output_fields,
            emit_oscal=args.emit_oscal,
        )
    else:
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
            agent_cmd=args.agent_cmd,
            max_output_fields=args.max_output_fields,
            emit_oscal=args.emit_oscal,
        )


if __name__ == "__main__":
    main()
