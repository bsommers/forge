from __future__ import annotations

import json
import re
from typing import Any

import httpx
import pytest
import respx
from fastmcp import Client

from src.auth import load_manifest
from src.server import TOOLS_PROVIDER, mcp

MCP_SPEC_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
FORGE_SNAKE_CASE_RE = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")
RFC9110_TCHAR_RE = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
SENSITIVE_PARAM_RE = re.compile(
    r"(password|passwd|secret|token|api_?key|authorization|credential|ssn)",
    re.IGNORECASE,
)


@pytest.fixture(autouse=True)
def _mock_manifest_env(monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = load_manifest()
    auth = manifest.get("auth", {})
    for key, val in auth.items():
        if key.endswith("_env") and isinstance(val, str):
            monkeypatch.setenv(val, "test-dummy-credential-value")
    base_url_env = manifest.get("upstream", {}).get("base_url_env")
    if base_url_env:
        monkeypatch.setenv(base_url_env, "https://api.test.internal/v1")


def _assert_no_external_refs(schema: Any, context: str) -> None:
    """MCP 2026-07-28: Schemas MUST NOT reference external $ref URIs."""
    if isinstance(schema, dict):
        ref = schema.get("$ref")
        if isinstance(ref, str) and not ref.startswith("#"):
            raise AssertionError(f"{context} contains forbidden external $ref URI: {ref}")
        for val in schema.values():
            _assert_no_external_refs(val, context)
    elif isinstance(schema, list):
        for item in schema:
            _assert_no_external_refs(item, context)


def _validate_x_mcp_headers(tool_name: str, input_schema: dict[str, Any]) -> None:
    """MCP 2026-07-28 x-mcp-header constraints for Streamable HTTP header mirroring."""
    seen_headers: set[str] = set()
    props: dict[str, Any] = input_schema.get("properties", {})
    for prop_name, prop_schema in props.items():
        if not isinstance(prop_schema, dict) or "x-mcp-header" not in prop_schema:
            continue
        header_val = prop_schema["x-mcp-header"]
        assert isinstance(header_val, str) and header_val, (
            f"{tool_name}.{prop_name}: x-mcp-header MUST be a non-empty string."
        )
        assert RFC9110_TCHAR_RE.match(header_val), (
            f"{tool_name}.{prop_name}: x-mcp-header '{header_val}' violates RFC 9110 tchar syntax."
        )
        lowered = header_val.lower()
        assert lowered not in seen_headers, (
            f"{tool_name}: duplicate case-insensitive x-mcp-header '{header_val}'."
        )
        seen_headers.add(lowered)
        prop_type = prop_schema.get("type")
        if prop_type is None and isinstance(prop_schema.get("anyOf"), list):
            non_null = [
                opt.get("type")
                for opt in prop_schema["anyOf"]
                if isinstance(opt, dict) and opt.get("type") != "null"
            ]
            if len(non_null) == 1:
                prop_type = non_null[0]
        assert prop_type in {"string", "integer", "boolean"}, (
            f"{tool_name}.{prop_name}: x-mcp-header only permits "
            f"string/integer/boolean, got {prop_type}."
        )
        assert not SENSITIVE_PARAM_RE.search(prop_name), (
            f"{tool_name}.{prop_name}: x-mcp-header MUST NOT be applied to sensitive parameters."
        )


async def test_modern_2026_07_28_protocol_and_deterministic_ordering() -> None:
    """Server MUST negotiate MCP 2026-07-28 via server/discover with deterministic tool order."""
    async with Client(mcp) as client:
        assert client.protocol_version == "2026-07-28"
        assert not TOOLS_PROVIDER.failed_files, (
            f"Broken tool files in src/tools/: {TOOLS_PROVIDER.failed_files}"
        )
        first_order = [t.name for t in await client.list_tools()]
        second_order = [t.name for t in await client.list_tools()]
        assert first_order == second_order, (
            "tools/list ordering MUST be deterministic across calls."
        )


async def test_manifest_tools_schemas_and_annotations() -> None:
    """Verify tool names, schemas, hidden DI, external $refs, x-mcp-header, and ToolAnnotations."""
    manifest = load_manifest()
    expected_tools = {t["name"]: t for t in manifest.get("tools", [])}

    async with Client(mcp) as client:
        registered = await client.list_tools()

    assert len(registered) <= 15, f"Context budget exceeded: {len(registered)} tools > 15 max."
    registered_map = {t.name: t for t in registered}
    assert set(expected_tools.keys()) == set(registered_map.keys()), (
        f"Registered tools {set(registered_map)} != manifest tools {set(expected_tools)}"
    )

    for name, tool_def in registered_map.items():
        assert MCP_SPEC_NAME_RE.match(name) and FORGE_SNAKE_CASE_RE.match(name), (
            f"Tool '{name}' must satisfy MCP 1..128 char rules and verb_noun snake_case."
        )
        assert tool_def.description and len(tool_def.description.strip()) >= 15, (
            f"Tool '{name}' requires a clear description (>= 15 chars)."
        )

        input_schema: dict[str, Any] = (
            tool_def.input_schema
            if hasattr(tool_def, "input_schema")
            else getattr(tool_def, "inputSchema", {})
        )
        assert isinstance(input_schema, dict) and input_schema.get("type") == "object"
        _assert_no_external_refs(input_schema, f"{name}.inputSchema")
        _validate_x_mcp_headers(name, input_schema)

        output_schema = (
            tool_def.output_schema
            if hasattr(tool_def, "output_schema")
            else getattr(tool_def, "outputSchema", None)
        )
        assert isinstance(output_schema, dict), (
            f"Tool '{name}' MUST define a typed return annotation so outputSchema is generated."
        )
        _assert_no_external_refs(output_schema, f"{name}.outputSchema")

        schema_props = input_schema.get("properties", {})
        assert "client" not in schema_props, f"Tool '{name}' leaked DI 'client' into inputSchema!"
        for req_param in expected_tools[name].get("required_params", []):
            assert req_param in schema_props, (
                f"Tool '{name}' missing required manifest parameter '{req_param}'."
            )

        expected_ann = expected_tools[name].get("annotations", {})
        if expected_ann:
            assert tool_def.annotations is not None, f"Tool '{name}' is missing ToolAnnotations."
            ann_dump = tool_def.annotations.model_dump(by_alias=True, exclude_none=True)
            for ann_key, ann_val in expected_ann.items():
                assert ann_dump.get(ann_key) is ann_val, (
                    f"Tool '{name}' annotation {ann_key}={ann_dump.get(ann_key)} "
                    f"!= manifest {ann_val}."
                )


@respx.mock
async def test_structured_output_and_response_size_guard() -> None:
    """Tools must return valid structuredContent + TextContent and obey max_response_bytes."""
    manifest = load_manifest()
    max_bytes = int(manifest.get("upstream", {}).get("max_response_bytes", 32_768))
    huge_title = "X" * (max_bytes * 2)
    respx.route().mock(
        return_value=httpx.Response(
            200,
            json={"id": "INC-1", "title": "Database spike", "severity": "sev2", "status": "open"},
        )
    )

    first_tool = manifest["tools"][0]
    sample_args = {p: "INC-1" for p in first_tool.get("required_params", [])}

    async with Client(mcp) as client:
        ok_result = await client.call_tool(first_tool["name"], sample_args)
        assert ok_result.is_error is False
        assert ok_result.structured_content is not None
        assert len(ok_result.content) >= 1

        # Verify oversized upstream payload is truncated by ResponseLimitingMiddleware
        respx.route().mock(
            return_value=httpx.Response(200, json={"id": "INC-1", "title": huge_title})
        )
        bounded = await client.call_tool(first_tool["name"], sample_args)
        serialized = json.dumps(bounded.structured_content or "") + "".join(
            block.text for block in bounded.content if hasattr(block, "text")
        )
        assert len(serialized.encode("utf-8")) <= max_bytes * 2
