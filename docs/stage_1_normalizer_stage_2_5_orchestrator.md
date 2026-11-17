# MCP Server Forge: OpenAPI Normalizer & Self-Healing Orchestrator

This codebase implements the deterministic host pipeline that drives the Forge:
1. **`forge/ingest_openapi.py` (Stage 1):** Parses OpenAPI 3.x YAML/JSON, dereferences internal `$ref`s while rejecting external `$ref` URIs (per MCP `2026-07-28` schema security rules), chunks endpoints to $\le 15$ tools, derives MCP `ToolAnnotations` from HTTP semantics, and emits `forge-manifest.json`.
2. **`forge/orchestrator.py` (Stages 2–5):** Clones the Golden Template, locks core files, executes the AI coding agent in a `--network=none` sandboxed Docker container with write access restricted to `src/tools/`, `tests/unit/`, and `README.md`, runs up to $3$ deterministic self-healing iterations via `scripts/validate_mcp.py`, and generates deployment configs + security-review PR metadata.

---

## 1. `forge/ingest_openapi.py` (Stage 1 Normalizer)

```python
from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

import yaml

MAX_TOOLS_PER_SERVER = 15
HTTP_METHODS = ("get", "post", "put", "patch", "delete")


class SpecNormalizationError(ValueError):
    """Raised when an input OpenAPI specification violates Forge or MCP 2026-07-28 constraints."""


def _to_snake_case(raw: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", raw)
    s1 = re.sub(r"([a-z0-9])([A-Za-z])", lambda m: f"{m.group(1)}_{m.group(2)}" if m.group(2).isupper() else m.group(0), cleaned)
    snake = re.sub(r"_+", "_", s1).strip("_").lower()
    if not snake or not snake[0].isalpha():
        snake = f"op_{snake}"
    return snake[:64]


def _resolve_local_refs(node: Any, root: dict[str, Any], depth: int = 0) -> Any:
    """Inline internal #/components/... $refs and reject external URIs per MCP 2026-07-28."""
    if depth > 25:
        raise SpecNormalizationError("OpenAPI schema $ref nesting depth exceeds safety limit (25).")
    if isinstance(node, dict):
        if "$ref" in node and isinstance(node["$ref"], str):
            ref = node["$ref"]
            if not ref.startswith("#/"):
                raise SpecNormalizationError(
                    f"External $ref URIs are forbidden by MCP 2026-07-28 security guidelines: {ref}"
                )
            target: Any = root
            for part in ref[2:].split("/"):
                part_unescaped = part.replace("~1", "/").replace("~0", "~")
                if not isinstance(target, dict) or part_unescaped not in target:
                    raise SpecNormalizationError(f"Unresolvable internal $ref: {ref}")
                target = target[part_unescaped]
            return _resolve_local_refs(copy.deepcopy(target), root, depth + 1)
        return {k: _resolve_local_refs(v, root, depth + 1) for k, v in node.items()}
    if isinstance(node, list):
        return [_resolve_local_refs(item, root, depth + 1) for item in node]
    return node


def _extract_auth_config(spec: dict[str, Any], env_prefix: str) -> dict[str, Any]:
    schemes = spec.get("components", {}).get("securitySchemes", {})
    if not schemes:
        return {"type": "none"}

    _, first_scheme = next(iter(schemes.items()))
    scheme_type = str(first_scheme.get("type", "")).lower()

    if scheme_type == "http":
        http_scheme = str(first_scheme.get("scheme", "bearer")).lower()
        if http_scheme == "bearer":
            return {"type": "bearer", "token_env": f"{env_prefix}_API_TOKEN"}
        if http_scheme == "basic":
            return {
                "type": "basic",
                "username_env": f"{env_prefix}_USERNAME",
                "password_env": f"{env_prefix}_PASSWORD",
            }
    if scheme_type == "apikey":
        location = str(first_scheme.get("in", "header")).lower()
        param_name = str(first_scheme.get("name", "X-API-Key"))
        if location == "query":
            return {
                "type": "api_key_query",
                "key_env": f"{env_prefix}_API_KEY",
                "param_name": param_name,
            }
        return {
            "type": "api_key_header",
            "key_env": f"{env_prefix}_API_KEY",
            "header_name": param_name,
        }
    if scheme_type == "oauth2":
        flows = first_scheme.get("flows", {})
        cc_flow = flows.get("clientCredentials", {})
        scopes = " ".join(cc_flow.get("scopes", {}).keys())
        return {
            "type": "oauth2_client_credentials",
            "token_url_env": f"{env_prefix}_OAUTH_TOKEN_URL",
            "client_id_env": f"{env_prefix}_CLIENT_ID",
            "client_secret_env": f"{env_prefix}_CLIENT_SECRET",
            "scope": scopes,
        }
    return {"type": "bearer", "token_env": f"{env_prefix}_API_TOKEN"}


def _infer_annotations(method: str) -> dict[str, bool]:
    m = method.upper()
    return {
        "readOnlyHint": m == "GET",
        "destructiveHint": m == "DELETE",
        "idempotentHint": m in {"GET", "PUT", "DELETE"},
        "openWorldHint": True,
    }


def normalize_openapi_to_manifest(
    spec_path: Path,
    server_name: str,
    tag_filter: str | None = None,
) -> dict[str, Any]:
    """Parse an OpenAPI 3.x file into a deterministic forge-manifest.json dictionary."""
    raw_text = spec_path.read_text(encoding="utf-8")
    raw_spec: dict[str, Any] = (
        json.loads(raw_text) if spec_path.suffix.lower() == ".json" else yaml.safe_load(raw_text)
    )
    resolved_spec: dict[str, Any] = _resolve_local_refs(raw_spec, raw_spec)

    env_prefix = re.sub(r"[^A-Z0-9]+", "_", server_name.upper()).strip("_")
    servers = resolved_spec.get("servers", [])
    default_base_url = (
        str(servers[0].get("url", "https://localhost")) if servers else "https://localhost"
    )

    tools: list[dict[str, Any]] = []
    seen_names: set[str] = set()

    for path_str, path_item in sorted(resolved_spec.get("paths", {}).items()):
        if not isinstance(path_item, dict):
            continue
        path_level_params = path_item.get("parameters", [])

        for method in HTTP_METHODS:
            op = path_item.get(method)
            if not isinstance(op, dict):
                continue
            if tag_filter and tag_filter not in op.get("tags", []):
                continue

            raw_op_id = op.get("operationId") or f"{method}_{path_str}"
            tool_name = _to_snake_case(str(raw_op_id))
            if tool_name in seen_names:
                tool_name = _to_snake_case(f"{method}_{tool_name}")
            seen_names.add(tool_name)

            merged_params = [*path_level_params, *op.get("parameters", [])]
            required_params: list[str] = []
            parameter_specs: list[dict[str, Any]] = []
            for p in merged_params:
                if not isinstance(p, dict) or "name" not in p:
                    continue
                p_name = _to_snake_case(str(p["name"]))
                is_req = bool(p.get("required", False) or p.get("in") == "path")
                if is_req and p_name not in required_params:
                    required_params.append(p_name)
                parameter_specs.append(
                    {
                        "name": p_name,
                        "wire_name": str(p["name"]),
                        "in": str(p.get("in", "query")),
                        "required": is_req,
                        "description": str(p.get("description") or f"Parameter {p['name']}"),
                        "schema": p.get("schema", {"type": "string"}),
                    }
                )

            req_body_schema: dict[str, Any] | None = None
            if "requestBody" in op and isinstance(op["requestBody"], dict):
                content = op["requestBody"].get("content", {})
                json_media = content.get("application/json", {})
                if isinstance(json_media, dict) and "schema" in json_media:
                    req_body_schema = json_media["schema"]

            summary = str(op.get("summary") or op.get("description") or f"{method.upper()} {path_str}").strip()
            if len(summary) < 15:
                summary = f"Execute {method.upper()} request on {path_str} endpoint."

            tools.append(
                {
                    "name": tool_name,
                    "title": str(op.get("summary") or tool_name.replace("_", " ").title())[:80],
                    "method": method.upper(),
                    "path": path_str,
                    "description": summary[:400],
                    "annotations": _infer_annotations(method),
                    "required_params": required_params,
                    "parameters": parameter_specs,
                    "request_body_schema": req_body_schema,
                }
            )

    if not tools:
        raise SpecNormalizationError("Zero HTTP operations matched in the OpenAPI specification.")
    if len(tools) > MAX_TOOLS_PER_SERVER:
        raise SpecNormalizationError(
            f"Spec yielded {len(tools)} tools (max {MAX_TOOLS_PER_SERVER}). "
            "Re-run with --tag-filter to split into domain-scoped MCP servers."
        )

    info = resolved_spec.get("info", {})
    return {
        "protocol_revision": "2026-07-28",
        "server_name": server_name,
        "title": str(info.get("title", server_name)),
        "version": str(info.get("version", "1.0.0")),
        "description": str(
            info.get("description") or f"Stateless MCP 2026-07-28 server for {server_name}."
        )[:500],
        "upstream": {
            "base_url_env": f"{env_prefix}_BASE_URL",
            "default_base_url": default_base_url,
            "timeout_seconds": 15.0,
            "max_response_bytes": 32768,
        },
        "auth": _extract_auth_config(resolved_spec, env_prefix),
        "tools": tools,
    }
```

---

## 2. `forge/orchestrator.py` (Stages 2–5 Self-Healing Runner)

```python
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from forge.ingest_openapi import normalize_openapi_to_manifest

MAX_HEAL_ITERATIONS = 3


@dataclass(frozen=True)
class ValidationOutcome:
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
    shutil.copytree(golden_template_dir, workspace_dir)

    # Clear reference example tools so the agent builds strictly from forge-manifest.json
    tools_dir = workspace_dir / "src" / "tools"
    for py_file in tools_dir.glob("*.py"):
        if py_file.name != "__init__.py":
            py_file.unlink()

    unit_test_dir = workspace_dir / "tests" / "unit"
    unit_test_dir.mkdir(parents=True, exist_ok=True)
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
        "docker", "run", "--rm",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true",
        "--pids-limit=256",
        "--memory=2g",
        "-e", llm_api_key_env,
        "-w", "/workspace",
        # Mount full repository READ-ONLY first so locked files cannot be tampered with
        "-v", f"{workspace_dir.resolve()}:/workspace:ro",
        # Overlay ONLY permitted agent-writable paths as READ-WRITE
        "-v", f"{(workspace_dir / 'src' / 'tools').resolve()}:/workspace/src/tools:rw",
        "-v", f"{(workspace_dir / 'tests' / 'unit').resolve()}:/workspace/tests/unit:rw",
        "-v", f"{readme_path.resolve()}:/workspace/README.md:rw",
        agent_image,
        "claude", "--print", "--dangerously-skip-permissions",
        "-p", "/workspace/.forge-agent-prompt.md",
    ]
    proc = subprocess.run(docker_cmd, text=True, capture_output=True, check=False)
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
        "docker", "run", "--rm",
        "--network=none",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true",
        "-w", "/workspace",
        "-v", f"{workspace_dir.resolve()}:/workspace:ro",
        "--tmpfs", "/tmp:rw,noexec,nosuid,size=256m",
        "-e", "PYTHONDONTWRITEBYTECODE=1",
        "-e", "COVERAGE_FILE=/tmp/.coverage",
        validator_image,
        "uv", "run", "--frozen", "python", "scripts/validate_mcp.py",
    ]
    proc = subprocess.run(docker_cmd, text=True, capture_output=True, check=False)
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

    artifacts = {
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
) -> None:
    print(f"[Stage 1] Normalizing {spec_path} -> forge-manifest.json ...", file=sys.stderr)
    manifest = normalize_openapi_to_manifest(spec_path, server_name, tag_filter=tag_filter)

    print(f"[Stage 2] Scaffolding locked FastMCP 4.2 Golden Template in {output_dir} ...", file=sys.stderr)
    stage_workspace(golden_template_dir, output_dir, manifest)

    last_diagnostics: str | None = None
    for attempt in range(1, MAX_HEAL_ITERATIONS + 1):
        print(f"[Stage 3] Running Coding Agent (Iteration {attempt}/{MAX_HEAL_ITERATIONS}) ...", file=sys.stderr)
        prompt = build_agent_task_prompt(system_prompt_path, manifest, attempt, last_diagnostics)
        invoke_sandboxed_agent(output_dir, agent_image=agent_image, prompt_text=prompt)

        print(f"[Stage 4] Running Offline Verification Harness (Iteration {attempt}) ...", file=sys.stderr)
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

    print("[Stage 5] Emitting deployment snippets & PR governance report ...", file=sys.stderr)
    artifacts = emit_stage5_packaging_artifacts(output_dir, manifest, registry_prefix)
    print(json.dumps(artifacts, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="MCP Server Forge Orchestrator (MCP 2026-07-28)")
    parser.add_argument("--spec", type=Path, required=True, help="OpenAPI 3.x YAML/JSON file")
    parser.add_argument("--name", type=str, required=True, help="Kebab-case MCP server name")
    parser.add_argument("--tag-filter", type=str, default=None, help="Optional OpenAPI tag slice")
    parser.add_argument("--template-dir", type=Path, default=Path("./golden-template"))
    parser.add_argument("--prompt-file", type=Path, default=Path("./forge/AGENT_SYSTEM_PROMPT.md"))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--agent-image", type=str, default="mcp-forge-agent:latest")
    parser.add_argument("--validator-image", type=str, default="mcp-forge-validator:latest")
    args = parser.parse_args()

    run_forge_pipeline(
        spec_path=args.spec,
        server_name=args.name,
        golden_template_dir=args.template_dir,
        system_prompt_path=args.prompt_file,
        output_dir=args.output_dir,
        agent_image=args.agent_image,
        validator_image=args.validator_image,
        tag_filter=args.tag_filter,
    )


if __name__ == "__main__":
    main()
```