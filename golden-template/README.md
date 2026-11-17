# Hardened FastMCP Golden Template (MCP `2026-07-28`)

Locked reference template for **MCP Server Forge**, targeting the stateless **Model Context Protocol `2026-07-28`** specification (`SEP-2575` `server/discover`, `SEP-2567` sessionless Streamable HTTP, `SEP-2577` deprecations, and JSON Schema `2020-12` `outputSchema` / `structuredContent`).

## Locked Core Architecture

- `src/auth.py` — Manifest-driven `httpx.Auth` factory enforcing the MCP `2026-07-28` Token Passthrough Prohibition.
- `src/deps.py` — Lifespan-pooled `ApiClient` dependency injection (`Depends(get_http_client)`) and `request_json()` upstream HTTP-to-`ToolError` mapper.
- `src/server.py` — Structured `stderr` JSON logging, `FileSystemProvider` tool discovery, and `ForgeResponseLimitingMiddleware` enforcing `max_response_bytes` while preserving `outputSchema`.
- `scripts/validate_mcp.py` — 4-gate verification suite (`ruff`, `mypy --strict`, AST & `SEP-2577` audit, `pytest` contract + `>=85%` branch coverage, and subprocess `stdio` `2026-07-28` protocol check).
- `tests/contract/test_forge_contract.py` — Locked contract test suite validating protocol negotiation, schema safety, `x-mcp-header` compliance, and `ToolAnnotations` fidelity.

## Verification

```bash
uv run --offline python scripts/validate_mcp.py
```
