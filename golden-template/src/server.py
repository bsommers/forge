from __future__ import annotations

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


class ForgeResponseLimitingMiddleware(ResponseLimitingMiddleware):
    """Preserves MCP 2026-07-28 outputSchema while bounding oversized tool payloads."""

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
            "Tool %r response exceeds size limit (%d > %d bytes); truncating structured fields",
            context.message.name,
            len(serialized),
            self.max_size,
        )

        if isinstance(result.structured_content, dict):
            # Budget half of max_size for structured_content and half for TextContent JSON mirror
            budget = max(256, (self.max_size - 256) // 2)
            str_limit = max(64, budget // 2)
            truncated_sc: dict[str, Any] = result.structured_content
            while str_limit >= 16:
                candidate = _truncate_structured_strings(
                    result.structured_content,
                    str_limit,
                    " ...[truncated]",
                )
                if isinstance(candidate, dict):
                    truncated_sc = candidate
                text_json = json.dumps(truncated_sc)
                if len(text_json.encode("utf-8")) <= budget:
                    return ToolResult(
                        content=[TextContent(type="text", text=text_json)],
                        structured_content=truncated_sc,
                        meta=result.meta,
                        is_error=result.is_error,
                    )
                str_limit //= 2

            text_json = json.dumps(truncated_sc)
            return ToolResult(
                content=[TextContent(type="text", text=text_json)],
                structured_content=truncated_sc,
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
