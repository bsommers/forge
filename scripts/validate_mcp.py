from __future__ import annotations

import argparse
import ast
import asyncio
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402
import respx  # noqa: E402
from fastmcp import Client  # noqa: E402
from fastmcp.client.transports import PythonStdioTransport  # noqa: E402

from src.auth import iter_manifest_auth_env_vars, load_manifest  # noqa: E402
from src.server import mcp  # noqa: E402

TOOLS_DIR = ROOT / "src" / "tools"
DEFAULT_FIXTURES_DIR = ROOT / "tests" / "fixtures"

FORBIDDEN_IMPORTS = {
    "os",
    "sys",
    "subprocess",
    "socket",
    "shutil",
    "pathlib",
    "ctypes",
    "pickle",
    "importlib",
}
FORBIDDEN_CALLS = {"eval", "exec", "compile", "open", "__import__", "print"}
DEPRECATED_2026_METHODS = {"sample", "list_roots", "set_logging_level"}
PROMPT_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"system\s+prompt", re.IGNORECASE),
    re.compile(r"<\|im_start\|>", re.IGNORECASE),
    re.compile(r"you\s+must\s+always\s+call", re.IGNORECASE),
]


def run_cmd(label: str, cmd: list[str]) -> None:
    print(f"==> [Gate] {label}: {' '.join(cmd)}", file=sys.stderr)
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT)
    proc = subprocess.run(cmd, cwd=ROOT, env=env, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        sys.stderr.write(f"\n[FAIL] {label}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}\n")
        sys.exit(proc.returncode)


def audit_tools_ast() -> None:
    print("==> [Gate] AST Security, SEP-2577 Deprecation & Docstring Audit", file=sys.stderr)
    errors: list[str] = []
    py_files = sorted(p for p in TOOLS_DIR.rglob("*.py") if p.name != "__init__.py")
    if not py_files:
        errors.append("No tool implementation files found in src/tools/.")

    for path in py_files:
        rel = path.relative_to(ROOT)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(rel))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top in FORBIDDEN_IMPORTS:
                        errors.append(f"{rel}:{node.lineno} forbidden import '{alias.name}'")
            elif isinstance(node, ast.ImportFrom) and node.module:
                top = node.module.split(".")[0]
                if top in FORBIDDEN_IMPORTS:
                    errors.append(f"{rel}:{node.lineno} forbidden import from '{node.module}'")
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_CALLS:
                    errors.append(f"{rel}:{node.lineno} forbidden builtin call '{node.func.id}()'")
                elif (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr in DEPRECATED_2026_METHODS
                ):
                    errors.append(
                        f"{rel}:{node.lineno} call to deprecated MCP 2026-07-28 feature "
                        f"'.{node.func.attr}()' (SEP-2577)"
                    )
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)):
                doc = ast.get_docstring(node) or ""
                for pattern in PROMPT_INJECTION_PATTERNS:
                    if pattern.search(doc):
                        errors.append(
                            f"{rel}: docstring matches forbidden prompt-injection pattern "
                            f"'{pattern.pattern}'"
                        )

    if errors:
        sys.stderr.write(
            "\n[FAIL] AST Security Audit:\n" + "\n".join(f"  - {e}" for e in errors) + "\n"
        )
        sys.exit(1)


def _is_schema_nullable(schema: dict[str, Any]) -> bool:
    if schema.get("nullable") is True:
        return True
    raw_t = schema.get("type")
    if isinstance(raw_t, list) and "null" in raw_t:
        return True
    for union_kw in ("anyOf", "oneOf"):
        variants = schema.get(union_kw)
        if isinstance(variants, list) and any(
            isinstance(v, dict) and v.get("type") == "null" for v in variants
        ):
            return True
    return False


def check_payload_against_schema(
    payload: Any,
    schema: dict[str, Any],
    json_path: str = "$",
) -> list[str]:
    """Validate a recorded upstream JSON payload against OpenAPI schema; return JSONPath drifts."""
    drifts: list[str] = []

    if isinstance(schema.get("allOf"), list):
        for branch in schema["allOf"]:
            if isinstance(branch, dict):
                drifts.extend(check_payload_against_schema(payload, branch, json_path))
        return drifts

    if payload is None:
        if not _is_schema_nullable(schema):
            expected_t = schema.get("type", "non-null")
            drifts.append(
                f"{json_path}: undocumented null on non-nullable field (expected {expected_t})"
            )
        return drifts

    for union_kw in ("anyOf", "oneOf"):
        variants = schema.get(union_kw)
        if isinstance(variants, list):
            non_null = [v for v in variants if isinstance(v, dict) and v.get("type") != "null"]
            if len(non_null) == 1:
                return check_payload_against_schema(payload, non_null[0], json_path)

    raw_t = schema.get("type")
    if isinstance(raw_t, list):
        non_null_types = [t for t in raw_t if t != "null"]
        s_type = str(non_null_types[0]) if non_null_types else None
    else:
        s_type = str(raw_t) if isinstance(raw_t, str) else None

    if s_type is None and isinstance(schema.get("properties"), dict):
        s_type = "object"

    if s_type == "object":
        if not isinstance(payload, dict):
            drifts.append(f"{json_path}: expected object, got {type(payload).__name__}")
            return drifts
        props = schema.get("properties", {})
        req_keys = schema.get("required", [])
        if isinstance(req_keys, list):
            for rk in req_keys:
                rk_str = str(rk)
                if rk_str not in payload:
                    drifts.append(f"{json_path}.{rk_str}: missing required field")
        if isinstance(props, dict):
            for pk, p_schema in props.items():
                if pk in payload and isinstance(p_schema, dict):
                    drifts.extend(
                        check_payload_against_schema(
                            payload[pk], p_schema, f"{json_path}.{pk}"
                        )
                    )
        return drifts

    if s_type == "array":
        if not isinstance(payload, list):
            drifts.append(f"{json_path}: expected array, got {type(payload).__name__}")
            return drifts
        items_schema = schema.get("items")
        if isinstance(items_schema, dict):
            for idx, item in enumerate(payload):
                drifts.extend(
                    check_payload_against_schema(item, items_schema, f"{json_path}[{idx}]")
                )
        return drifts

    if s_type == "string":
        if not isinstance(payload, str):
            drifts.append(f"{json_path}: expected string, got {type(payload).__name__}")
        elif isinstance(schema.get("enum"), list) and payload not in schema["enum"]:
            drifts.append(f"{json_path}: value {payload!r} not in enum {schema['enum']}")
    elif s_type == "integer":
        if not isinstance(payload, int) or isinstance(payload, bool):
            drifts.append(f"{json_path}: expected integer, got {type(payload).__name__}")
    elif s_type == "number":
        if not isinstance(payload, (int, float)) or isinstance(payload, bool):
            drifts.append(f"{json_path}: expected number, got {type(payload).__name__}")
    elif s_type == "boolean" and not isinstance(payload, bool):
        drifts.append(f"{json_path}: expected boolean, got {type(payload).__name__}")

    return drifts


def _sample_arg_for_input_prop(prop_schema: dict[str, Any], defs: dict[str, Any]) -> Any:
    if "$ref" in prop_schema and isinstance(prop_schema["$ref"], str):
        ref_name = prop_schema["$ref"].rsplit("/", 1)[-1]
        if ref_name in defs and isinstance(defs[ref_name], dict):
            return _sample_arg_for_input_prop(defs[ref_name], defs)
    for union_kw in ("anyOf", "oneOf"):
        variants = prop_schema.get(union_kw)
        if isinstance(variants, list):
            for v in variants:
                if isinstance(v, dict) and v.get("type") != "null":
                    return _sample_arg_for_input_prop(v, defs)
    if isinstance(prop_schema.get("enum"), list) and prop_schema["enum"]:
        return prop_schema["enum"][0]
    p_type = prop_schema.get("type", "string")
    if p_type == "integer":
        return 1
    if p_type == "number":
        return 1.5
    if p_type == "boolean":
        return True
    if p_type == "array":
        items = prop_schema.get("items")
        return (
            [_sample_arg_for_input_prop(items, defs)] if isinstance(items, dict) else ["item-1"]
        )
    if p_type == "object":
        sub_props = prop_schema.get("properties", {})
        sub_req = prop_schema.get("required", [])
        if isinstance(sub_props, dict):
            return {
                str(rk): _sample_arg_for_input_prop(sub_props.get(rk, {"type": "string"}), defs)
                for rk in sub_req
                if rk in sub_props
            }
        return {}
    return "INC-1"


async def verify_recorded_fixtures(fixtures_dir: Path | None) -> None:
    """Replay recorded upstream JSON fixtures against OpenAPI schemas & live MCP tools."""
    target_dir = fixtures_dir if fixtures_dir is not None else DEFAULT_FIXTURES_DIR
    if fixtures_dir is None and not target_dir.is_dir():
        return
    if not target_dir.is_dir():
        sys.stderr.write(f"\n[FAIL] Recorded Contract Fixture Replay: missing dir {target_dir}\n")
        sys.exit(1)

    fixture_files = sorted(target_dir.glob("*.json"))
    if not fixture_files:
        return

    print(
        f"==> [Gate] Recorded Contract Fixture Replay ({len(fixture_files)} file(s))",
        file=sys.stderr,
    )
    manifest = load_manifest(ROOT / "forge-manifest.json")
    tools_by_name = {str(t["name"]): t for t in manifest.get("tools", [])}

    saved_env: dict[str, str | None] = {}
    seed_vars = iter_manifest_auth_env_vars(manifest)
    base_url_env = manifest.get("upstream", {}).get("base_url_env")
    for var in seed_vars:
        saved_env[var] = os.environ.get(var)
        os.environ[var] = "fixture-replay-dummy-secret"
    if isinstance(base_url_env, str) and base_url_env:
        saved_env[base_url_env] = os.environ.get(base_url_env)
        os.environ[base_url_env] = "https://api.fixture-replay.internal/v1"

    errors: list[str] = []
    try:
        for fpath in fixture_files:
            loaded: Any = json.loads(fpath.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and "tool" in loaded and "response" in loaded:
                cases = [loaded]
            elif (
                isinstance(loaded, list)
                and loaded
                and isinstance(loaded[0], dict)
                and "tool" in loaded[0]
                and "response" in loaded[0]
            ):
                cases = loaded
            else:
                cases = [{"tool": fpath.stem, "response": loaded}]

            for idx, case in enumerate(cases):
                t_name = str(case.get("tool", fpath.stem))
                resp_payload = case.get("response")
                status_code = int(case.get("status_code", 200))
                label = f"{fpath.name}[{idx}]({t_name})"

                if t_name not in tools_by_name:
                    errors.append(f"{label}: unknown manifest tool '{t_name}'")
                    continue

                tool_meta = tools_by_name[t_name]
                resp_schema = tool_meta.get("response_schema")
                if isinstance(resp_schema, dict) and 200 <= status_code < 300:
                    drifts = check_payload_against_schema(resp_payload, resp_schema, "$")
                    for d in drifts:
                        errors.append(f"{label} schema drift at {d}")

                with respx.mock(assert_all_called=False) as router:
                    router.route().mock(
                        return_value=httpx.Response(status_code, json=resp_payload)
                    )
                    async with Client(mcp) as client:
                        reg = {t.name: t for t in await client.list_tools()}
                        t_def = reg[t_name]
                        in_s: dict[str, Any] = (
                            t_def.input_schema
                            if hasattr(t_def, "input_schema")
                            else getattr(t_def, "inputSchema", {})
                        )
                        props = in_s.get("properties", {})
                        defs = in_s.get("$defs", {})
                        raw_args = case.get("args")
                        call_args = (
                            dict(raw_args)
                            if isinstance(raw_args, dict)
                            else {
                                p: _sample_arg_for_input_prop(
                                    props.get(p, {"type": "string"}), defs
                                )
                                for p in tool_meta.get("required_params", [])
                            }
                        )
                        call_res = await client.call_tool(t_name, call_args)
                        if call_res.is_error or call_res.structured_content is None:
                            errors.append(
                                f"{label}: live MCP tool replay failed structured output check"
                            )
    finally:
        for k, prev in saved_env.items():
            if prev is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = prev

    if errors:
        sys.stderr.write(
            "\n[FAIL] Recorded Contract Fixture Replay:\n"
            + "\n".join(f"  - {e}" for e in errors)
            + "\n"
        )
        sys.exit(1)


async def verify_stdio_protocol_2026_07_28() -> None:
    """Verify clean newline-delimited UTF-8 JSON-RPC over stdio on MCP 2026-07-28."""
    print(
        "==> [Gate] Subprocess STDIO Discovery & Frame Hygiene (MCP 2026-07-28)",
        file=sys.stderr,
    )
    manifest = load_manifest(ROOT / "forge-manifest.json")
    env = dict(os.environ)
    env["MCP_TRANSPORT"] = "stdio"
    env["PYTHONPATH"] = str(ROOT)
    for env_var in iter_manifest_auth_env_vars(manifest):
        env[env_var] = "stdio-validation-dummy-secret"

    transport = PythonStdioTransport(
        script_path=str(ROOT / "src" / "server.py"),
        python_cmd=sys.executable,
        env=env,
        cwd=str(ROOT),
    )
    # Note: MCP 2026-07-28 removed `ping` and `initialize`; Client probes `server/discover`
    async with asyncio.timeout(5.0), Client(transport) as client:
        if client.protocol_version != "2026-07-28":
            raise RuntimeError(
                f"Expected modern MCP 2026-07-28 protocol over stdio, got {client.protocol_version}"
            )
        tools = await client.list_tools()
        expected_names = {t["name"] for t in manifest.get("tools", [])}
        actual_names = {t.name for t in tools}
        if actual_names != expected_names:
            raise RuntimeError(
                f"STDIO tools/list mismatch: expected {expected_names}, got {actual_names}"
            )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Deterministic 5-Gate MCP 2026-07-28 Verification Harness"
    )
    parser.add_argument(
        "--fixtures-dir",
        type=Path,
        default=None,
        help="Optional directory of recorded upstream JSON fixtures for schema drift replay",
    )
    args = parser.parse_args(argv)

    run_cmd("Ruff Lint & Security", [sys.executable, "-m", "ruff", "check", "src", "tests"])
    run_cmd("Mypy Strict Typecheck", [sys.executable, "-m", "mypy", "src"])
    audit_tools_ast()
    run_cmd(
        "Pytest Contract + Unit & Branch Coverage",
        [
            sys.executable,
            "-m",
            "pytest",
            "--cov=src/tools",
            "--cov-branch",
            "--cov-fail-under=85",
        ],
    )
    asyncio.run(verify_recorded_fixtures(args.fixtures_dir))
    asyncio.run(verify_stdio_protocol_2026_07_28())
    print(
        "\n[PASS] All MCP Server Forge (2026-07-28) verification gates succeeded.",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
