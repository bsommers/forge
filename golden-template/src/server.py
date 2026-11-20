from __future__ import annotations

import copy
import json
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
import pydantic_core
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.lifespan import lifespan
from fastmcp.server.middleware.response_limiting import ResponseLimitingMiddleware
from fastmcp.server.providers import FileSystemProvider
from fastmcp.tools import InputRequiredToolResult, Tool, ToolResult
from mcp.types import TextContent

from src.auth import build_auth_from_manifest, load_manifest

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    import mcp.types as mt
    from fastmcp.server.middleware.middleware import CallNext, MiddlewareContext


class StderrJsonFormatter(logging.Formatter):
    """Structured JSON logs emitted strictly to stderr per MCP 2026-07-28 & SEP-2577."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_stderr_logging() -> None:
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(StderrJsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())


configure_stderr_logging()
logger = logging.getLogger("forged_mcp")


def _wire_json_len(value: Any) -> int:
    """Measure conservative ensure_ascii=True wire length (prevents \\uXXXX surrogate blowups)."""
    return len(json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode("utf-8"))


def _slice_lists_proportionally(node: Any, keep_ratio: float) -> tuple[Any, bool]:
    """Slice list cardinalities while keeping >= 1 element on non-empty lists for outputSchema."""
    sliced_any = False
    if isinstance(node, list):
        if len(node) > 1:
            target_len = max(1, int(len(node) * keep_ratio))
            if target_len < len(node):
                node = node[:target_len]
                sliced_any = True
        new_items: list[Any] = []
        for item in node:
            updated_item, child_sliced = _slice_lists_proportionally(item, keep_ratio)
            new_items.append(updated_item)
            sliced_any = sliced_any or child_sliced
        return new_items, sliced_any

    if isinstance(node, dict):
        out: dict[str, Any] = {}
        for k, v in node.items():
            updated_v, child_sliced = _slice_lists_proportionally(v, keep_ratio)
            out[k] = updated_v
            sliced_any = sliced_any or child_sliced
        if sliced_any:
            if "truncated" in out and isinstance(out["truncated"], bool):
                out["truncated"] = True
            if "total_returned" in out and isinstance(out["total_returned"], int):
                list_vals = [v for v in out.values() if isinstance(v, list)]
                if len(list_vals) == 1:
                    out["total_returned"] = len(list_vals[0])
        return out, sliced_any

    return node, False


def _truncate_structured_strings(value: Any, max_str_bytes: int, suffix: str) -> Any:
    """Recursively bound string values inside structuredContent while preserving schema types."""
    if isinstance(value, str):
        encoded = value.encode("utf-8")
        if len(encoded) <= max_str_bytes:
            return value
        suffix_bytes = suffix.encode("utf-8")
        keep = max(0, max_str_bytes - len(suffix_bytes))
        return encoded[:keep].decode("utf-8", errors="ignore") + suffix
    if isinstance(value, dict):
        return {
            k: _truncate_structured_strings(v, max_str_bytes, suffix)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_truncate_structured_strings(item, max_str_bytes, suffix) for item in value]
    return value


def bound_structured_content(
    payload: dict[str, Any],
    *,
    budget_bytes: int,
    suffix: str = " ...[truncated]",
) -> dict[str, Any]:
    """Dual-axis structured payload bounding (Pattern MCP-003 / NIST SC-5).

    Pass 1 (Cardinality Axis): Binary-search list slicing (defeats 3,000-item short-ID bypass).
    Pass 2 (String Byte Axis): Proportional UTF-8 string truncation on character boundaries.
    Pass 3 (Fail-Closed Guard): Raise ToolError if irreducible scalars still exceed budget_bytes.
    """
    current = copy.deepcopy(payload)
    if _wire_json_len(current) <= budget_bytes:
        return current

    low, high = 0.0, 1.0
    best_sliced: dict[str, Any] | None = None
    for _ in range(14):
        mid = (low + high) / 2.0
        candidate, did_slice = _slice_lists_proportionally(current, mid)
        if not did_slice and mid < 0.01:
            break
        if isinstance(candidate, dict) and _wire_json_len(candidate) <= budget_bytes:
            best_sliced = candidate
            low = mid
        else:
            high = mid

    if best_sliced is not None:
        return best_sliced

    min_sliced, _ = _slice_lists_proportionally(current, 0.0)
    current = dict(min_sliced)
    if _wire_json_len(current) <= budget_bytes:
        return current

    str_limit = max(64, budget_bytes // 2)
    while str_limit >= 16:
        str_candidate = _truncate_structured_strings(current, str_limit, suffix)
        if isinstance(str_candidate, dict) and _wire_json_len(str_candidate) <= budget_bytes:
            return str_candidate
        str_limit //= 2

    raise ToolError(
        f"Upstream structured response exceeded {budget_bytes}-byte safety budget after "
        "collection slicing and string bounding; narrow query filters or reduce limit."
    )


class ForgeResponseLimitingMiddleware(ResponseLimitingMiddleware):
    """Preserves MCP 2026-07-28 outputSchema while dual-axis bounding oversized tool payloads."""

    async def on_list_tools(
        self,
        context: MiddlewareContext[mt.ListToolsRequest],
        call_next: CallNext[mt.ListToolsRequest, Sequence[Tool]],
    ) -> Sequence[Tool]:
        return await call_next(context)

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        if not self._limits_tool(context.message.name):
            return await call_next(context)

        result = await call_next(context)
        if isinstance(result, InputRequiredToolResult) or not isinstance(result, ToolResult):
            return result

        serialized = pydantic_core.to_json(result, fallback=str)
        if len(serialized) <= self.max_size:
            return result

        logger.warning(
            "Tool %r response exceeds size limit (%d > %d bytes); applying dual-axis bounding",
            context.message.name,
            len(serialized),
            self.max_size,
        )

        if isinstance(result.structured_content, dict):
            # Budget half of max_size for structured_content and half for TextContent JSON mirror
            budget = max(256, (self.max_size - 256) // 2)
            bounded_sc = bound_structured_content(
                result.structured_content,
                budget_bytes=budget,
            )
            text_json = json.dumps(bounded_sc, separators=(",", ":"))
            return ToolResult(
                content=[TextContent(type="text", text=text_json)],
                structured_content=bounded_sc,
                meta=result.meta,
                is_error=result.is_error,
            )

        texts = [b.text for b in result.content if isinstance(b, TextContent)]
        raw_text = "\n\n".join(texts) if texts else serialized.decode("utf-8", errors="replace")
        return self._truncate_to_result(raw_text, meta=result.meta, is_error=result.is_error)


MANIFEST: dict[str, Any] = load_manifest()
TOOLS_DIR = Path(__file__).resolve().parent / "tools"
TOOLS_PROVIDER = FileSystemProvider(root=TOOLS_DIR, reload=False)


@lifespan
async def server_lifespan(_server: FastMCP) -> AsyncIterator[dict[str, Any]]:
    if TOOLS_PROVIDER.failed_files:
        raise RuntimeError(
            f"Refusing startup due to broken tool modules: {TOOLS_PROVIDER.failed_files}"
        )

    upstream = MANIFEST.get("upstream", {})
    base_url_env = str(upstream.get("base_url_env", ""))
    base_url = (
        os.environ.get(base_url_env, "").strip() if base_url_env else ""
    ) or str(upstream.get("default_base_url", "https://localhost"))
    timeout_sec = float(upstream.get("timeout_seconds", 15.0))
    auth_handler = build_auth_from_manifest(MANIFEST)

    limits = httpx.Limits(max_keepalive_connections=20, max_connections=50)
    transport = httpx.AsyncHTTPTransport(retries=2)

    async with httpx.AsyncClient(
        base_url=base_url,
        auth=auth_handler,
        timeout=httpx.Timeout(timeout_sec),
        limits=limits,
        transport=transport,
        headers={
            "Accept": "application/json",
            "User-Agent": f"forged-mcp/{MANIFEST['server_name']}-{MANIFEST['version']}",
        },
    ) as http_client:
        logger.info("Initialized stateless upstream HTTP pool for %s", MANIFEST["server_name"])
        yield {"http_client": http_client, "manifest": MANIFEST}


def create_server() -> FastMCP:
    server = FastMCP(
        name=str(MANIFEST["server_name"]),
        version=str(MANIFEST.get("version", "0.1.0")),
        instructions=str(MANIFEST.get("description", "")),
        providers=[TOOLS_PROVIDER],
        lifespan=server_lifespan,
    )
    max_bytes = int(MANIFEST.get("upstream", {}).get("max_response_bytes", 32_768))
    server.add_middleware(ForgeResponseLimitingMiddleware(max_size=max_bytes))
    return server


mcp = create_server()


def main() -> None:
    os.environ.setdefault("FASTMCP_CHECK_FOR_UPDATES", "off")
    transport_mode = os.environ.get("MCP_TRANSPORT", "stdio").lower()
    if transport_mode == "http":
        port = int(os.environ.get("PORT", "8000"))
        mcp.run(transport="http", host="0.0.0.0", port=port)  # noqa: S104
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
