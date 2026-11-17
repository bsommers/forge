# Chapter 5 — Troubleshooting & FAQ

[← Chapter 4: CLI & Config Reference](04-cli-and-config-reference.md) · [User Guide Index](README.md) · [← Back to Project README](../../README.md)

## Table of Contents

- [Troubleshooting Symptoms & Fixes](#troubleshooting-symptoms--fixes)
- [Frequently Asked Questions (FAQ)](#frequently-asked-questions-faq)

---

## Troubleshooting Symptoms & Fixes

### 1. `AssertionError: Tool '<name>' MUST define a typed return annotation so outputSchema is generated`
- **Symptom**: `tests/contract/test_forge_contract.py` fails on `output_schema` being `None`.
- **Root Causes**:
  1. The `@tool` function returns `dict[str, Any]` or lacks a return type annotation instead of returning a `pydantic.BaseModel` subclass.
  2. Stock FastMCP `ResponseLimitingMiddleware` was used instead of `ForgeResponseLimitingMiddleware` (stock `ResponseLimitingMiddleware.on_list_tools` clears `output_schema=None`).
- **Fix**: Annotate an explicit `BaseModel` return type on the tool function and keep `ForgeResponseLimitingMiddleware` in `src/server.py`.

### 2. Registered tools mismatch (`Registered tools != manifest tools`) when using `x-mcp-header`
- **Symptom**: A tool decorated with `json_schema_extra={"x-mcp-header": "..."}` is missing from `await client.list_tools()`.
- **Root Cause**: `mcp==2.3.0` validates `x-mcp-header` properties strictly for `"type"` in `{"string", "integer", "boolean"}`. Optional union types (`str | None`) emit `anyOf` without a top-level `"type"` key.
- **Fix**: Use `Annotated[str, Field(default="", json_schema_extra={"x-mcp-header": "Idempotency-Key"})] = ""` and treat empty string `""` as omitted.

### 3. `SpecNormalizationError: External $ref URIs are forbidden by MCP 2026-07-28 security guidelines`
- **Symptom**: `forge.ingest_openapi` aborts on `$ref: "https://..."` or `$ref: "./common.yaml#/..."`.
- **Fix**: Bundle external OpenAPI fragments into `#/components/schemas/...` inside a single self-contained OpenAPI file before running Stage 1.

### 4. `RuntimeError: Refusing startup due to broken tool modules`
- **Symptom**: Server refuses to boot during `server_lifespan`, listing `TOOLS_PROVIDER.failed_files`.
- **Fix**: Run `.venv/bin/python -m mypy src` and `.venv/bin/python -m pytest` to inspect the syntax or import error in the listed `src/tools/*.py` module.

### 5. `stdio` client hangs or reports malformed JSON-RPC frame
- **Symptom**: MCP client over `stdio` disconnects with JSON parse errors.
- **Root Cause**: Something wrote non-JSON text to `stdout` (`print(...)` or a third-party logger attached to `sys.stdout`).
- **Fix**: All logging must route through `logging.getLogger(...)` (configured by `configure_stderr_logging()` to emit JSON exclusively to `sys.stderr`). Gate 1 (`ruff` `T20`) and Gate 3 (`audit_tools_ast`) block `print()` in `src/tools/`.

---

## Frequently Asked Questions (FAQ)

### Why is `MAX_TOOLS_PER_SERVER` capped at 15?
Empirical agent evaluations show tool-selection accuracy and prompt-cache hit rates degrade rapidly when a single MCP server advertises dozens of overlapping endpoints. Splitting large OpenAPI specs with `--tag-filter` keeps each MCP server focused, fast, and cache-friendly.

### Can I run MCP Server Forge without Docker or an LLM API key?
Yes. Pass `--local` (or `--execution-mode local`) to `python -m forge.orchestrator`. It uses the deterministic synthesizer in `forge/codegen.py` and runs `scripts/validate_mcp.py` in your local Python environment with zero network calls.

### Why does `dashboard/index.html` load `status.js` via `<script>` tags instead of `fetch('status.json')`?
Modern browsers block `fetch()` against sibling `file://` URLs under same-origin CORS rules. Injecting `<script src="./status.js?t=...">` works natively on **both** `file://` and `http://localhost` with zero server setup.
