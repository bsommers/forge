from __future__ import annotations

import ast
import asyncio
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastmcp import Client  # noqa: E402
from fastmcp.client.transports import PythonStdioTransport  # noqa: E402

from src.auth import iter_manifest_auth_env_vars, load_manifest  # noqa: E402

TOOLS_DIR = ROOT / "src" / "tools"

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


def main() -> None:
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
    asyncio.run(verify_stdio_protocol_2026_07_28())
    print(
        "\n[PASS] All MCP Server Forge (2026-07-28) verification gates succeeded.",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
