"""Deterministic local FastMCP 2026-07-28 tool, unit-test, and README synthesizer."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from forge.projection import (
    ProjectedField,
    ResponseProjection,
    flatten_composed_schema,
    project_response_schema,
)

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

    body_schema = tool_spec.get("request_body_schema")
    if isinstance(body_schema, dict):
        flat_body = flatten_composed_schema(body_schema)
        body_req_raw = {str(r) for r in flat_body.get("required", []) if isinstance(r, str)}
        props = flat_body.get("properties", {})
        if isinstance(props, dict):
            for prop_name, prop_schema in props.items():
                snake_name = re.sub(r"[^a-z0-9]+", "_", prop_name.lower()).strip("_")
                if not snake_name or snake_name in seen or snake_name == "client":
                    continue
                seen.add(snake_name)
                p_schema = (
                    flatten_composed_schema(prop_schema)
                    if isinstance(prop_schema, dict)
                    else {"type": "string"}
                )
                desc = _sanitize_docstring(
                    str(p_schema.get("description") or f"Body field {snake_name}.")
                )
                is_body_req = snake_name in required_names or str(prop_name) in body_req_raw
                normalized.append(
                    {
                        "name": snake_name,
                        "wire_name": str(prop_name),
                        "in": "body",
                        "required": is_body_req,
                        "description": desc,
                        "schema": p_schema,
                        "x-mcp-header": None,
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

    req_list = [p for p in normalized if p["required"]]
    opt_list = [p for p in normalized if not p["required"]]
    return [*req_list, *opt_list]


def _nested_input_model_info(
    tool_pascal: str, param: dict[str, Any]
) -> tuple[str, list[str], dict[str, Any]] | None:
    """Return (ModelName, class_lines, sample_dict) when a body param is a typed object."""
    if param.get("in") != "body":
        return None
    schema = param.get("schema")
    if not isinstance(schema, dict):
        return None
    flat = flatten_composed_schema(schema)
    props = flat.get("properties")
    if not isinstance(props, dict) or not props:
        return None

    model_name = f"{tool_pascal}{_to_pascal_case(str(param['name']))}Input"
    req_set = {str(r) for r in flat.get("required", []) if isinstance(r, str)}
    lines = [
        f"class {model_name}(BaseModel):",
        f'    """Structured input object for {param["name"]}."""',
        "",
    ]
    sample: dict[str, Any] = {}
    used: set[str] = set()
    for raw_k, raw_v in props.items():
        sub_name = re.sub(r"[^a-z0-9]+", "_", str(raw_k).lower()).strip("_")
        if not sub_name or not sub_name[0].isalpha() or sub_name in used:
            continue
        used.add(sub_name)
        sub_s = flatten_composed_schema(raw_v) if isinstance(raw_v, dict) else {"type": "string"}
        st = str(sub_s.get("type", "string"))
        is_sub_req = str(raw_k) in req_set
        s_val: Any
        if st == "integer":
            f_type, def_r, s_val = ("int", "0", 1) if is_sub_req else ("int | None", "None", 1)
        elif st == "number":
            f_type, def_r, s_val = (
                ("float", "0.0", 1.5) if is_sub_req else ("float | None", "None", 1.5)
            )
        elif st == "boolean":
            f_type, def_r, s_val = (
                ("bool", "False", True) if is_sub_req else ("bool | None", "None", True)
            )
        else:
            f_type, def_r, s_val = (
                ("str", '""', "val-1") if is_sub_req else ("str | None", "None", "val-1")
            )
        desc_j = json.dumps(_sanitize_docstring(str(sub_s.get("description") or f"Field {raw_k}.")))
        if is_sub_req:
            lines.append(f"    {sub_name}: {f_type} = Field(description={desc_j})")
        else:
            lines.append(
                f"    {sub_name}: {f_type} = Field(default={def_r}, description={desc_j})"
            )
        sample[sub_name] = s_val

    if not used:
        return None
    lines.extend(["", ""])
    return (model_name, lines, sample)


def _python_type_and_default(
    param: dict[str, Any], tool_pascal: str = "Tool"
) -> tuple[str, str | None, Any]:
    raw_schema = param.get("schema")
    schema = flatten_composed_schema(raw_schema) if isinstance(raw_schema, dict) else {}
    raw_t = schema.get("type", "string")
    if isinstance(raw_t, list):
        non_null = [t for t in raw_t if t != "null"]
        schema_type = str(non_null[0]) if non_null else "string"
    else:
        schema_type = str(raw_t or "string")

    is_req = bool(param.get("required", False))
    has_header = bool(param.get("x-mcp-header"))

    nested_info = _nested_input_model_info(tool_pascal, param)
    if nested_info is not None:
        m_name, _, m_sample = nested_info
        if is_req:
            return (m_name, None, m_sample)
        return (f"{m_name} | None", "None", m_sample)

    if schema_type == "integer":
        py_type = "int"
        default_repr = None if is_req else "25"
        sample_val: Any = 1
    elif schema_type == "number":
        if is_req:
            py_type, default_repr = "float", None
        else:
            py_type, default_repr = ("float", "0.0") if has_header else ("float | None", "None")
        sample_val = 12.5
    elif schema_type == "boolean":
        py_type = "bool"
        default_repr = None if is_req else "False"
        sample_val = True
    elif schema_type == "array" and not has_header:
        items = schema.get("items")
        item_t = str(items.get("type", "string")) if isinstance(items, dict) else "string"
        if item_t == "integer":
            elem_t, sample_val = "int", [1]
        elif item_t == "number":
            elem_t, sample_val = "float", [1.5]
        elif item_t == "boolean":
            elem_t, sample_val = "bool", [True]
        else:
            elem_t, sample_val = "str", ["tag-1"]
        if is_req:
            py_type, default_repr = f"list[{elem_t}]", None
        else:
            py_type, default_repr = f"list[{elem_t}] | None", "None"
    else:
        raw_enum = schema.get("enum")
        if (
            isinstance(raw_enum, list)
            and 1 <= len(raw_enum) <= 12
            and all(isinstance(e, str) and e for e in raw_enum)
            and not has_header
        ):
            lit_inner = ", ".join(json.dumps(str(e)) for e in raw_enum)
            lit_type = f"Literal[{lit_inner}]"
            sample_val = str(raw_enum[0])
            if is_req:
                return (lit_type, None, sample_val)
            return (f"{lit_type} | None", "None", sample_val)

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


def _projection_for_tool(tool_spec: dict[str, Any]) -> ResponseProjection:
    has_schema_key = "response_schema" in tool_spec or "x_mcp_fields" in tool_spec
    resp_schema = tool_spec.get("response_schema")
    x_fields = tool_spec.get("x_mcp_fields")
    max_fields = int(tool_spec.get("max_output_fields", 8))
    return project_response_schema(
        resp_schema if isinstance(resp_schema, dict) else None,
        method=str(tool_spec.get("method", "GET")),
        x_mcp_fields=list(x_fields) if isinstance(x_fields, list) else None,
        max_output_fields=max_fields,
        has_schema_key=has_schema_key,
    )


def _render_field_decl(pf: ProjectedField) -> list[str]:
    desc_json = json.dumps(_sanitize_docstring(pf.description)[:64])
    if pf.default_repr == "[]":
        return [
            f"    {pf.py_name}: {pf.py_type} = Field(",
            "        default_factory=list,",
            f"        description={desc_json},",
            "    )",
        ]
    return [
        f"    {pf.py_name}: {pf.py_type} = Field(",
        f"        default={pf.default_repr},",
        f"        description={desc_json},",
        "    )",
    ]


def _render_value_expr(pf: ProjectedField, src_var: str) -> str:
    if len(pf.source_path) == 1:
        raw_expr = f"{src_var}.get({json.dumps(pf.source_path[0])})"
    else:
        k0, k1 = pf.source_path[0], pf.source_path[1]
        raw_expr = f"_nested_get({src_var}, {json.dumps(k0)}, {json.dumps(k1)})"

    if pf.py_type == "list[str]":
        return f"_as_str_list({raw_expr})"
    if pf.py_type == "list[int]":
        return f"_as_int_list({raw_expr})"
    if pf.py_type == "list[float]":
        return f"_as_float_list({raw_expr})"
    if pf.py_type == "list[bool]":
        return f"_as_bool_list({raw_expr})"
    if pf.py_type == "list[dict[str, Any]]":
        return f"_as_dict_list({raw_expr})"
    if pf.py_type == "str":
        return f"str({raw_expr} or {pf.default_repr})"
    if pf.py_type == "int":
        return f"int({raw_expr} or 0)"
    if pf.py_type == "float":
        return f"float({raw_expr} or 0.0)"
    if pf.py_type == "bool":
        fallback = "True" if pf.default_repr == "True" else "False"
        return f"bool({src_var}.get({json.dumps(pf.source_path[0])}, {fallback}))"
    if pf.py_type == "str | None":
        return f"_opt_str({raw_expr})"
    if pf.py_type == "int | None":
        return f"_opt_int({raw_expr})"
    if pf.py_type == "float | None":
        return f"_opt_float({raw_expr})"
    return f"_opt_bool({raw_expr})"


def _helper_functions_needed(
    fields: tuple[ProjectedField, ...], *, has_nested_body: bool = False
) -> list[str]:
    helpers: list[str] = []
    if has_nested_body:
        helpers.extend(
            [
                "def _dump_body(val: Any) -> Any:",
                "    if isinstance(val, BaseModel):",
                "        return val.model_dump(exclude_none=True)",
                "    return val",
                "",
                "",
            ]
        )
    if any(len(f.source_path) > 1 for f in fields):
        helpers.extend(
            [
                "def _nested_get(d: dict[str, Any], k0: str, k1: str) -> Any:",
                "    sub = d.get(k0)",
                "    return sub.get(k1) if isinstance(sub, dict) else None",
                "",
                "",
            ]
        )
    if any(f.py_type == "list[str]" for f in fields):
        helpers.extend(
            [
                "def _as_str_list(val: Any) -> list[str]:",
                "    return [str(x) for x in val] if isinstance(val, list) else []",
                "",
                "",
            ]
        )
    if any(f.py_type == "list[int]" for f in fields):
        helpers.extend(
            [
                "def _as_int_list(val: Any) -> list[int]:",
                "    return [int(x) for x in val] if isinstance(val, list) else []",
                "",
                "",
            ]
        )
    if any(f.py_type == "list[float]" for f in fields):
        helpers.extend(
            [
                "def _as_float_list(val: Any) -> list[float]:",
                "    return [float(x) for x in val] if isinstance(val, list) else []",
                "",
                "",
            ]
        )
    if any(f.py_type == "list[bool]" for f in fields):
        helpers.extend(
            [
                "def _as_bool_list(val: Any) -> list[bool]:",
                "    return [bool(x) for x in val] if isinstance(val, list) else []",
                "",
                "",
            ]
        )
    if any(f.py_type == "list[dict[str, Any]]" for f in fields):
        helpers.extend(
            [
                "def _as_dict_list(val: Any) -> list[dict[str, Any]]:",
                "    return [dict(x) for x in val if isinstance(x, dict)]"
                " if isinstance(val, list) else []",
                "",
                "",
            ]
        )
    if any(f.py_type == "str | None" for f in fields):
        helpers.extend(
            [
                "def _opt_str(val: Any) -> str | None:",
                "    return str(val) if val is not None else None",
                "",
                "",
            ]
        )
    if any(f.py_type == "int | None" for f in fields):
        helpers.extend(
            [
                "def _opt_int(val: Any) -> int | None:",
                "    return int(val) if val is not None else None",
                "",
                "",
            ]
        )
    if any(f.py_type == "float | None" for f in fields):
        helpers.extend(
            [
                "def _opt_float(val: Any) -> float | None:",
                "    return float(val) if val is not None else None",
                "",
                "",
            ]
        )
    if any(f.py_type == "bool | None" for f in fields):
        helpers.extend(
            [
                "def _opt_bool(val: Any) -> bool | None:",
                "    return bool(val) if val is not None else None",
                "",
                "",
            ]
        )
    return helpers


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

    pascal = _to_pascal_case(name)
    model_name = f"{pascal}Response"
    item_model_name = f"{pascal}Item"
    params = _collect_tool_params(tool_spec)
    projection = _projection_for_tool(tool_spec)

    nested_input_classes: list[list[str]] = []
    nested_body_names: set[str] = set()
    needs_literal = False
    for p in params:
        n_info = _nested_input_model_info(pascal, p)
        if n_info is not None:
            nested_input_classes.append(n_info[1])
            nested_body_names.add(str(p["name"]))
        p_type, _, _ = _python_type_and_default(p, pascal)
        if "Literal[" in p_type:
            needs_literal = True

    typing_syms = ["Any"]
    if params:
        typing_syms.insert(0, "Annotated")
    if needs_literal:
        typing_syms.append("Literal")
    typing_import = f"from typing import {', '.join(sorted(typing_syms))}"

    lines: list[str] = [
        "from __future__ import annotations",
        "",
        typing_import,
        "",
        "from fastmcp.tools import tool",
        "from mcp.types import ToolAnnotations",
        "from pydantic import BaseModel, Field",
        "",
        "from src.deps import ApiClient, request_json",
        "",
        "",
    ]

    lines.extend(
        _helper_functions_needed(projection.fields, has_nested_body=bool(nested_body_names))
    )
    for cls_lines in nested_input_classes:
        lines.extend(cls_lines)

    if projection.kind == "legacy_fallback":
        lines.extend(
            [
                f"class {model_name}(BaseModel):",
                f'    """Concise structured output for {name}."""',
                "",
                '    id: str = Field(default="", description="Primary resource identifier.")',
                '    title: str = Field(default="", description="Short resource summary.")',
                '    status: str = Field(default="ok", description="Operational status.")',
                '    severity: str = Field(default="unknown", description="Severity tier.")',
                "    data: dict[str, Any] = Field(",
                "        default_factory=dict,",
                '        description="Normalized upstream response payload.",',
                "    )",
                "",
                "",
            ]
        )
    elif projection.kind == "collection":
        lines.extend(
            [
                f"class {item_model_name}(BaseModel):",
                f'    """Projected summary item for {name}."""',
                "",
            ]
        )
        for pf in projection.fields:
            lines.extend(_render_field_decl(pf))
        lines.extend(
            [
                "",
                "",
                f"class {model_name}(BaseModel):",
                f'    """Paginated projected collection output for {name}."""',
                "",
                f"    items: list[{item_model_name}] = Field(",
                "        default_factory=list,",
                '        description="Projected high-signal items.",',
                "    )",
                "    next_cursor: str | None = Field(",
                "        default=None,",
                '        description="Opaque cursor for fetching the next page.",',
                "    )",
                "    total_returned: int = Field(",
                "        default=0,",
                '        description="Number of items returned in this page.",',
                "    )",
                "",
                "",
            ]
        )
    else:
        lines.extend(
            [
                f"class {model_name}(BaseModel):",
                f'    """Concise projected output for {name}."""',
                "",
            ]
        )
        for pf in projection.fields:
            lines.extend(_render_field_decl(pf))
        lines.extend(["", ""])

    lines.extend(
        [
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
    )

    for p in params:
        p_name = p["name"]
        py_type, default_repr, _ = _python_type_and_default(p, pascal)
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
            val_expr = (
                f"_dump_body({bp['name']})" if bp["name"] in nested_body_names else bp["name"]
            )
            call_lines.append(f'            {json.dumps(bp["wire_name"])}: {val_expr},')
        call_lines.append("        },")
    call_lines.append("    )")
    lines.extend(call_lines)

    if projection.kind == "legacy_fallback":
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
    elif projection.kind == "collection":
        coll_key_lit = json.dumps(projection.collection_key or "items")
        cursor_key_lit = json.dumps(projection.cursor_key or "next_cursor")
        lines.extend(
            [
                "    if isinstance(raw, list):",
                "        raw_items: list[Any] = raw",
                "        next_cur: str | None = None",
                "    else:",
                "        envelope: dict[str, Any] = dict(raw)",
                f"        nested_list = envelope.get({coll_key_lit})",
                "        raw_items = (",
                "            nested_list",
                "            if isinstance(nested_list, list)",
                "            else ([envelope] if envelope else [])",
                "        )",
                f"        cur_val = envelope.get({cursor_key_lit})",
                "        next_cur = str(cur_val) if cur_val is not None else None",
                "    projected_items = [",
                f"        {item_model_name}(",
            ]
        )
        for pf in projection.fields:
            lines.append(f"            {pf.py_name}={_render_value_expr(pf, 'entry')},")
        lines.extend(
            [
                "        )",
                "        for entry in raw_items",
                "        if isinstance(entry, dict)",
                "    ]",
                f"    return {model_name}(",
                "        items=projected_items,",
                "        next_cursor=next_cur,",
                "        total_returned=len(projected_items),",
                "    )",
                "",
            ]
        )
    else:
        lines.append("    payload: dict[str, Any] = dict(raw)")
        lines.append(f"    return {model_name}(")
        for pf in projection.fields:
            lines.append(f"        {pf.py_name}={_render_value_expr(pf, 'payload')},")
        lines.append("    )")
        lines.append("")

    return "\n".join(lines)


def _sample_item_payload(fields: tuple[ProjectedField, ...]) -> dict[str, Any]:
    body: dict[str, Any] = {}
    for pf in fields:
        if len(pf.source_path) == 1:
            body[pf.source_path[0]] = pf.sample_value
        else:
            k0, k1 = pf.source_path[0], pf.source_path[1]
            sub = body.setdefault(k0, {})
            if isinstance(sub, dict):
                sub[k1] = pf.sample_value
    if not body:
        body = {"id": "INC-1", "status": "ok"}
    return body


def _py_literal(val: Any, indent: int = 4) -> str:
    """Format a JSON-compatible Python value as a ruff-clean multi-line Python literal."""
    pad = " " * indent
    inner_pad = " " * (indent + 4)
    if isinstance(val, dict):
        if not val:
            return "{}"
        entries = [
            f"{inner_pad}{json.dumps(str(k))}: {_py_literal(v, indent + 4)},"
            for k, v in val.items()
        ]
        return "{\n" + "\n".join(entries) + f"\n{pad}}}"
    if isinstance(val, list):
        if not val:
            return "[]"
        items = [f"{inner_pad}{_py_literal(v, indent + 4)}," for v in val]
        return "[\n" + "\n".join(items) + f"\n{pad}]"
    if isinstance(val, bool):
        return "True" if val else "False"
    if val is None:
        return "None"
    if isinstance(val, str):
        return json.dumps(val)
    return repr(val)


def render_unit_tests(manifest: dict[str, Any]) -> str:
    """Synthesize comprehensive respx unit tests covering happy, sparse, and HTTP error paths."""
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
        "from src.auth import iter_manifest_auth_env_vars, load_manifest",
        "from src.server import mcp",
        "",
        "",
        "@pytest.fixture(autouse=True)",
        "def _seed_test_env(monkeypatch: pytest.MonkeyPatch) -> None:",
        "    manifest = load_manifest()",
        "    for env_var in iter_manifest_auth_env_vars(manifest):",
        '        monkeypatch.setenv(env_var, "test-secret-token")',
        '    base_url_env = manifest.get("upstream", {}).get("base_url_env")',
        "    if base_url_env:",
        '        monkeypatch.setenv(base_url_env, "https://api.test.internal/v1")',
        "",
    ]

    for tool_spec in tools:
        t_name = str(tool_spec["name"])
        t_pascal = _to_pascal_case(t_name)
        params = _collect_tool_params(tool_spec)
        sample_args: dict[str, Any] = {}
        for p in params:
            _, _, sample_val = _python_type_and_default(p, t_pascal)
            sample_args[p["name"]] = sample_val

        projection = _projection_for_tool(tool_spec)
        item_payload = _sample_item_payload(projection.fields)
        args_literal = _py_literal(sample_args, indent=4)

        if projection.kind == "collection":
            coll_key = projection.collection_key or "items"
            cur_key = projection.cursor_key or "next_cursor"
            envelope_payload = {coll_key: [item_payload], cur_key: "cur-next"}
            env_lit = _py_literal(envelope_payload, indent=4)
            list_lit = _py_literal([item_payload], indent=4)
            lines.extend(
                [
                    "",
                    "@respx.mock",
                    f"async def test_{t_name}_happy_and_error_paths() -> None:",
                    f"    args: dict[str, object] = {args_literal}",
                    f"    env_body: dict[str, object] = {env_lit}",
                    f"    list_body: list[object] = {list_lit}",
                    "    async with Client(mcp) as client:",
                    "        respx.route().mock(return_value=httpx.Response(200, json=env_body))",
                    f'        result = await client.call_tool("{t_name}", args)',
                    "        assert result.is_error is False",
                    "        assert result.structured_content is not None",
                    "",
                    "        respx.route().mock(return_value=httpx.Response(200, json=list_body))",
                    f'        list_res = await client.call_tool("{t_name}", args)',
                    "        assert list_res.is_error is False",
                    "",
                    "        respx.route().mock(return_value=httpx.Response(200, json={}))",
                    f'        sparse_res = await client.call_tool("{t_name}", args)',
                    "        assert sparse_res.is_error is False",
                    "",
                    "        for status_code in (401, 404, 429, 500):",
                    '            err = httpx.Response(status_code, json={"error": "failed"})',
                    "            respx.route().mock(return_value=err)",
                    "            with pytest.raises(ToolError):",
                    f'                await client.call_tool("{t_name}", args)',
                    "",
                ]
            )
        else:
            body_lit = _py_literal(item_payload, indent=4)
            lines.extend(
                [
                    "",
                    "@respx.mock",
                    f"async def test_{t_name}_happy_and_error_paths() -> None:",
                    f"    args: dict[str, object] = {args_literal}",
                    f"    mock_body: dict[str, object] = {body_lit}",
                    "    async with Client(mcp) as client:",
                    "        respx.route().mock(return_value=httpx.Response(200, json=mock_body))",
                    f'        result = await client.call_tool("{t_name}", args)',
                    "        assert result.is_error is False",
                    "        assert result.structured_content is not None",
                    "",
                    "        respx.route().mock(return_value=httpx.Response(200, json={}))",
                    f'        sparse_res = await client.call_tool("{t_name}", args)',
                    "        assert sparse_res.is_error is False",
                    "",
                    "        for status_code in (401, 404, 429, 500):",
                    '            err = httpx.Response(status_code, json={"error": "failed"})',
                    "            respx.route().mock(return_value=err)",
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
        if k.endswith("_env") and isinstance(v, str) and v not in env_vars:
            env_vars.append(v)
    named_schemes = manifest.get("auth_schemes", {})
    if isinstance(named_schemes, dict):
        for sub_cfg in named_schemes.values():
            if isinstance(sub_cfg, dict):
                for k, v in sub_cfg.items():
                    if k.endswith("_env") and isinstance(v, str) and v not in env_vars:
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
            "- **Runtime:** Python 3.12 + FastMCP 4.x",
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
