from __future__ import annotations

from typing import Annotated, Any

import httpx
from fastmcp.dependencies import CurrentContext, Depends
from fastmcp.exceptions import ToolError
from fastmcp.server.context import Context


async def get_http_client(ctx: Context = CurrentContext()) -> httpx.AsyncClient:  # noqa: B008
    """Resolve the process-lifespan HTTP client without exposing it in JSON Schema."""
    lifespan_ctx: dict[str, Any] = ctx.lifespan_context
    client = lifespan_ctx.get("http_client")
    if not isinstance(client, httpx.AsyncClient):
        raise ToolError("Server HTTP client is unavailable; lifespan was not initialized.")
    return client


# Type alias used by agent-generated tools in src/tools/*.py
ApiClient = Annotated[httpx.AsyncClient, Depends(get_http_client)]


async def request_json(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | list[Any] | None = None,
) -> Any:
    """Execute an upstream HTTP call and map failures to actionable MCP ToolErrors."""
    clean_params = {k: v for k, v in (params or {}).items() if v is not None}
    try:
        response = await client.request(
            method=method.upper(),
            url=path,
            params=clean_params or None,
            json=json_body,
        )
        response.raise_for_status()
    except httpx.TimeoutException as exc:
        raise ToolError(
            f"Upstream API timed out on {method.upper()} {path}. "
            "Try narrowing query filters or retrying."
        ) from exc
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status in (401, 403):
            raise ToolError(
                f"Upstream authorization failed (HTTP {status}) for {path}. "
                "Check server credentials/scopes."
            ) from exc
        if status == 404:
            raise ToolError(
                f"Resource not found (HTTP 404) at {path}. Verify the identifier exists."
            ) from exc
        if status == 429:
            retry_after = exc.response.headers.get("Retry-After", "unknown")
            raise ToolError(
                f"Upstream rate limit exceeded (HTTP 429). "
                f"Wait before retrying (Retry-After: {retry_after})."
            ) from exc
        snippet = exc.response.text[:300].strip()
        raise ToolError(
            f"Upstream API error (HTTP {status}) on {method.upper()} {path}: {snippet}"
        ) from exc
    except httpx.RequestError as exc:
        raise ToolError(
            f"Upstream network error on {method.upper()} {path}: {type(exc).__name__}"
        ) from exc

    if response.status_code == 204 or not response.content:
        return {"status": "success", "http_status": response.status_code}
    return response.json()
