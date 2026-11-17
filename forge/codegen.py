"""Deterministic local FastMCP 2026-07-28 tool, unit-test, and README synthesizer."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

SENSITIVE_PARAM_RE = re.compile(
    r"(password|passwd|secret|token|api_?key|authorization|credential|ssn)",
    re.IGNORECASE,
)


def _to_pascal_case(snake: str) -> str:
    parts = [p for p in re.split(r"[^A-Za-z0-9]+", snake) if p]
    return "".join(p[:1].upper() + p[1:] for p in parts) or "Tool"


def _sanitize_docstring(raw: str) -> str:
    cleaned = " ".join(raw.replace('"""', "'''").replace("\\", "/").split())
    cleaned = re.sub(
        r"ignore\s+(all\s+)?previous\s+instructions",
        "process input",
        cleaned,
        flags=re.I,
    )
    cleaned = re.sub(r"system\s+prompt", "configuration", cleaned, flags=re.I)
    cleaned = re.sub(r"you\s+must\s+always\s+call", "call", cleaned, flags=re.I)
    if len(cleaned) < 15:
        cleaned = f"{cleaned} Execute stateless MCP 2026-07-28 operation."
    return cleaned[:72]


def _collect_tool_params(tool_spec: dict[str, Any]) -> list[dict[str, Any]]:
    path_str = str(tool_spec.get("path", "/"))
    required_names = list(tool_spec.get("required_params", []))
    raw_params: list[dict[str, Any]] = list(tool_spec.get("parameters", []))

    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []

    for p in raw_params:
        if not isinstance(p, dict) or "name" not in p:
            continue
        name = str(p["name"])
        if name in seen or name == "client":
            continue
        seen.add(name)
        normalized.append(
            {
                "name": name,
                "wire_name": str(p.get("wire_name", name)),
                "in": str(p.get("in", "path" if f"{{{name}}}" in path_str else "query")),
                "required": name in required_names or bool(p.get("required", False)),
                "description": _sanitize_docstring(
                    str(p.get("description") or f"Parameter {name}.")
                ),
                "schema": p.get("schema", {"type": "string"}),
                "x-mcp-header": p.get("x-mcp-header"),
            }
        )

    for req_name in required_names:
        if req_name not in seen and req_name != "client":
            seen.add(req_name)
            loc = "path" if f"{{{req_name}}}" in path_str else "query"
            normalized.append(
                {
                    "name": req_name,
                    "wire_name": req_name,
                    "in": loc,
                    "required": True,
                    "description": f"Required {req_name} identifier.",
                    "schema": {"type": "string"},
                    "x-mcp-header": None,
                }
            )

    body_schema = tool_spec.get("request_body_schema")
    if isinstance(body_schema, dict):
        props = body_schema.get("properties", {})
        if isinstance(props, dict):
            for prop_name, prop_schema in props.items():
                snake_name = re.sub(r"[^a-z0-9]+", "_", prop_name.lower()).strip("_")
                if not snake_name or snake_name in seen or snake_name == "client":
                    continue
                seen.add(snake_name)
                p_schema = prop_schema if isinstance(prop_schema, dict) else {"type": "string"}
                desc = _sanitize_docstring(
                    str(p_schema.get("description") or f"Body field {snake_name}.")
                )
                normalized.append(
                    {
                        "name": snake_name,
                        "wire_name": str(prop_name),
                        "in": "body",
                        "required": snake_name in required_names,
                        "description": desc,
                        "schema": p_schema,
                        "x-mcp-header": None,
                    }
                )

    req_list = [p for p in normalized if p["required"]]
    opt_list = [p for p in normalized if not p["required"]]
    return [*req_list, *opt_list]


def _python_type_and_default(param: dict[str, Any]) -> tuple[str, str | None, Any]:
    schema = param.get("schema")
    schema_type = str(schema.get("type", "string")) if isinstance(schema, dict) else "string"
    is_req = bool(param.get("required", False))
    has_header = bool(param.get("x-mcp-header"))

    if schema_type == "integer":
        py_type = "int"
        default_repr = None if is_req else "25"
        sample_val: Any = 1
    elif schema_type == "boolean":
        py_type = "bool"
        default_repr = None if is_req else "False"
        sample_val = True
    else:
        py_type = "str"
        if is_req:
            default_repr = None
        elif has_header:
            default_repr = '""'
        else:
            default_repr = "None"
            py_type = "str | None"
        sample_val = "INC-1"

    return py_type, default_repr, sample_val


def render_tool_module(tool_spec: dict[str, Any]) -> str:
    """Synthesize a strict-typed FastMCP 4.2 tool module for src/tools/<name>.py."""
    name = str(tool_spec["name"])
    title = str(tool_spec.get("title") or name.replace("_", " ").title())[:70]
    method = str(tool_spec.get("method", "GET")).upper()
    path_str = str(tool_spec.get("path", "/"))
    description = _sanitize_docstring(str(tool_spec.get("description") or f"{method} {path_str}"))
    ann = tool_spec.get("annotations", {})
    read_only = bool(ann.get("readOnlyHint", method == "GET"))
    destructive = bool(ann.get("destructiveHint", method == "DELETE"))
    idempotent = bool(ann.get("idempotentHint", method in {"GET", "PUT", "DELETE"}))
    open_world = bool(ann.get("openWorldHint", True))

    model_name = f"{_to_pascal_case(name)}Response"
    params = _collect_tool_params(tool_spec)

    lines: list[str] = [
        "from __future__ import annotations",
        "",
        "from typing import Annotated, Any",
        "",
        "from fastmcp.tools import tool",
        "from mcp.types import ToolAnnotations",
        "from pydantic import BaseModel, Field",
        "",
        "from src.deps import ApiClient, request_json",
        "",
        "",
        f"class {model_name}(BaseModel):",
        f'    """Concise structured output for {name}."""',
        "",
        '    id: str = Field(default="", description="Primary resource identifier.")',
        '    title: str = Field(default="", description="Short resource summary or title.")',
        '    status: str = Field(default="ok", description="Operational status.")',
        '    severity: str = Field(default="unknown", description="Severity or classification.")',
        "    data: dict[str, Any] = Field(",
        "        default_factory=dict,",
        '        description="Normalized upstream response payload.",',
        "    )",
        "",
        "",
        "@tool(",
        f"    name={json.dumps(name)},",
        f"    title={json.dumps(title)},",
        "    annotations=ToolAnnotations(",
        f"        read_only_hint={read_only},",
        f"        destructive_hint={destructive},",
        f"        idempotent_hint={idempotent},",
        f"        open_world_hint={open_world},",
        "    ),",
        ")",
        f"async def {name}(",
        "    client: ApiClient,",
    ]

    for p in params:
        p_name = p["name"]
        py_type, default_repr, _ = _python_type_and_default(p)
        desc_json = json.dumps(p["description"])
        x_header = p.get("x-mcp-header")
        extra_line: str | None = None
        if (
            isinstance(x_header, str)
            and x_header
            and not SENSITIVE_PARAM_RE.search(p_name)
            and py_type in {"str", "int", "bool"}
        ):
            hdr_json = json.dumps(x_header)
            extra_line = f'            json_schema_extra={{"x-mcp-header": {hdr_json}}},'

        lines.append(f"    {p_name}: Annotated[")
        lines.append(f"        {py_type},")
        lines.append("        Field(")
        if default_repr is not None:
            lines.append(f"            default={default_repr},")
        lines.append(f"            description={desc_json},")
        if extra_line is not None:
            lines.append(extra_line)
        lines.append("        ),")
        if default_repr is not None:
            lines.append(f"    ] = {default_repr},")
        else:
            lines.append("    ],")

    lines.extend(
        [
            f") -> {model_name}:",
            f'    """{description}"""',
        ]
    )

    # Format path interpolation
    url_expr = f'f"{path_str}"' if "{" in path_str else f'"{path_str}"'
    query_params = [p for p in params if p["in"] in {"query", "header"}]
    body_params = [p for p in params if p["in"] == "body"]

    call_lines = [
        "    raw: Any = await request_json(",
        "        client,",
        f'        "{method}",',
        f"        {url_expr},",
    ]
    if query_params:
        call_lines.append("        params={")
        for qp in query_params:
            call_lines.append(f'            {json.dumps(qp["wire_name"])}: {qp["name"]},')
        call_lines.append("        },")
    if body_params:
        call_lines.append("        json_body={")
        for bp in body_params:
            call_lines.append(f'            {json.dumps(bp["wire_name"])}: {bp["name"]},')
        call_lines.append("        },")
    call_lines.append("    )")
    lines.extend(call_lines)

    lines.extend(
        [
            "    payload: dict[str, Any] = dict(raw)",
            f"    return {model_name}(",
            '        id=str(payload.get("id", "")),',
            '        title=str(payload.get("title", "")),',
            '        status=str(payload.get("status", "ok")),',
            '        severity=str(payload.get("severity", "unknown")),',
            "        data=payload,",
            "    )",
            "",
        ]
    )
    return "\n".join(lines)


def render_unit_tests(manifest: dict[str, Any]) -> str:
    """Synthesize comprehensive respx unit tests covering happy and HTTP error paths."""
    tools: list[dict[str, Any]] = list(manifest.get("tools", []))
    lines: list[str] = [
        "from __future__ import annotations",
        "",
        "import httpx",
        "import pytest",
        "import respx",
        "from fastmcp import Client",
        "from fastmcp.exceptions import ToolError",
        "",
        "from src.auth import load_manifest",
        "from src.server import mcp",
        "",
        "",
        "@pytest.fixture(autouse=True)",
        "def _seed_test_env(monkeypatch: pytest.MonkeyPatch) -> None:",
        "    manifest = load_manifest()",
        '    for key, val in manifest.get("auth", {}).items():',
        '        if key.endswith("_env") and isinstance(val, str):',
        '            monkeypatch.setenv(val, "test-secret-token")',
        '    base_url_env = manifest.get("upstream", {}).get("base_url_env")',
        "    if base_url_env:",
        '        monkeypatch.setenv(base_url_env, "https://api.test.internal/v1")',
        "",
    ]

    for tool_spec in tools:
        t_name = str(tool_spec["name"])
        params = _collect_tool_params(tool_spec)
        sample_args: dict[str, Any] = {}
        for p in params:
            _, _, sample_val = _python_type_and_default(p)
            sample_args[p["name"]] = sample_val

        args_literal = json.dumps(sample_args)
        lines.extend(
            [
                "",
                "@respx.mock",
                f"async def test_{t_name}_happy_and_error_paths() -> None:",
                f"    args = {args_literal}",
                "    mock_body = {",
                '        "id": "INC-1",',
                '        "title": "Test Item",',
                '        "status": "ok",',
                '        "severity": "sev2",',
                "    }",
                "    respx.route().mock(",
                "        return_value=httpx.Response(200, json=mock_body)",
                "    )",
                "    async with Client(mcp) as client:",
                f'        result = await client.call_tool("{t_name}", args)',
                "        assert result.is_error is False",
                "        assert result.structured_content is not None",
                "",
                "        for status_code in (401, 404, 429, 500):",
                "            err_resp = httpx.Response(status_code, json={\"error\": \"failed\"})",
                "            respx.route().mock(return_value=err_resp)",
                "            with pytest.raises(ToolError):",
                f'                await client.call_tool("{t_name}", args)',
                "",
            ]
        )

    return "\n".join(lines)


def render_readme(manifest: dict[str, Any]) -> str:
    """Synthesize server README.md with env table and mcpServers config."""
    server_name = str(manifest.get("server_name", "forged-mcp"))
    title = str(manifest.get("title", server_name))
    description = str(manifest.get("description", ""))
    upstream = manifest.get("upstream", {})
    base_url_env = str(upstream.get("base_url_env", "UPSTREAM_BASE_URL"))
    default_url = str(upstream.get("default_base_url", "https://localhost"))

    env_vars = [base_url_env]
    for k, v in manifest.get("auth", {}).items():
        if k.endswith("_env") and isinstance(v, str):
            env_vars.append(v)

    tool_rows = [
        f"| `{t['name']}` | `{t['method']} {t['path']}` | {t['description']} |"
        for t in manifest.get("tools", [])
    ]
    env_rows = [
        f"| `{var}` | Server-bound variable (`{default_url}` default for base URL) |"
        for var in env_vars
    ]

    return "\n".join(
        [
            f"# {title} (`{server_name}`)",
            "",
            description,
            "",
            "## Protocol Compliance",
            "",
            "- **MCP Revision:** `2026-07-28` (`SEP-2575`, `SEP-2567` stateless HTTP)",
            "- **Runtime:** Python 3.12 + FastMCP 4.2",
            "",
            "## Environment Variables",
            "",
            "| Variable | Description |",
            "| :--- | :--- |",
            *env_rows,
            "",
            "## Registered Tools",
            "",
            "| Tool Name | Upstream Endpoint | Description |",
            "| :--- | :--- | :--- |",
            *tool_rows,
            "",
        ]
    )


def synthesize_workspace_code(workspace_dir: Path, manifest: dict[str, Any]) -> list[Path]:
    """Generate src/tools/<tool>.py, tests/unit/test_tools.py, and README.md from manifest."""
    written: list[Path] = []
    tools_dir = workspace_dir / "src" / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    init_file = tools_dir / "__init__.py"
    if not init_file.exists():
        init_file.write_text('"""Generated MCP 2026-07-28 tools."""\n', encoding="utf-8")

    for tool_spec in manifest.get("tools", []):
        tool_path = tools_dir / f"{tool_spec['name']}.py"
        tool_path.write_text(render_tool_module(tool_spec), encoding="utf-8")
        written.append(tool_path)

    unit_dir = workspace_dir / "tests" / "unit"
    unit_dir.mkdir(parents=True, exist_ok=True)
    (unit_dir / "__init__.py").touch()
    unit_test_path = unit_dir / "test_tools.py"
    unit_test_path.write_text(render_unit_tests(manifest), encoding="utf-8")
    written.append(unit_test_path)

    readme_path = workspace_dir / "README.md"
    readme_path.write_text(render_readme(manifest), encoding="utf-8")
    written.append(readme_path)

    return written
