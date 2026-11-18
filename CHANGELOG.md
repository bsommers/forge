# Changelog

All notable changes to **MCP Server Forge** are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [v1.2.0] - 2026-11-18

### Added
- **Milestone M1 — High-Signal `2xx` Response Schema Projection (`forge/ingest_openapi.py`, `forge/projection.py`, `forge/codegen.py`):**
  - Preserves resolved OpenAPI `200`/`201`/`202` `application/json` `response_schema` definitions, `x-mcp-fields` dotted-path allowlists, and `--max-output-fields` (`1..20`, default `8`) in `forge-manifest.json`.
  - Ranks and trims bloated 100-field upstream payloads down to top-`N` high-signal scalar/flattened fields (`commander.name -> commander`) and synthesizes typed `<Tool>Item` + `<Tool>Response` (`items`, `next_cursor`, `total_returned`) envelopes for paginated collections—eliminating raw `data: dict[str, Any]` passthrough in `--local` mode.
- **Milestone M2 — Docker-Free Host-Agent Mode & SHA-256 Lock Guard (`forge/orchestrator.py`):**
  - Adds `--execution-mode agent` and `--agent-cmd` (`{prompt_file}`, `{workspace}`) seeded from M1 projected tools and verified across up to 3 `scripts/validate_mcp.py` self-healing iterations without requiring Docker.
  - Enforces `0444` read-only permissions and pre/post SHA-256 digest checks (`snapshot_locked_digests`, `enforce_and_verify_locked_digests`, `TamperDetectionError`) with automatic baseline restoration if any locked Golden Template file is touched.
- **Milestone Roadmap & Plan 01 (`docs/ROADMAP.md`, `docs/plans/01-high-signal-codegen-and-agent-refinement.md`):**
  - Added `M0`–`M3` roadmap, gap matrix, and exhaustive test suites `tests/forge/test_schema_projection.py` and `tests/forge/test_host_agent_mode.py`.

## [v1.0.0] - 2026-11-17

### Added
- **Stage 1 OpenAPI 3.x Normalizer (`forge/ingest_openapi.py`):**
  - Parses YAML and JSON OpenAPI 3.x specifications into deterministic `forge-manifest.json` files targeting MCP `2026-07-28`.
  - Inlines internal `#/components/...` `$ref` pointers (depth cap `<= 25`, RFC 6901 `~0`/`~1` unescaping) and rejects external `$ref` URIs to prevent SSRF and schema DoS.
  - Enforces a `<= 15` tool context budget per server with `--tag-filter` domain slicing.
  - Infers `ToolAnnotations` (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`) from HTTP verb semantics and extracts 6 upstream authentication modes (`none`, `bearer`, `basic`, `api_key_header`, `api_key_query`, `oauth2_client_credentials`).
- **Hardened FastMCP 4.x Golden Template (`src/`, `golden-template/`):**
  - `src/auth.py`: Server-bound `httpx.Auth` factory enforcing the MCP `2026-07-28` Token Passthrough Prohibition.
  - `src/deps.py`: Lifespan `httpx.AsyncClient` injection via `Depends(get_http_client)` (`ApiClient`) hidden from LLM-facing `inputSchema`, plus `request_json()` mapping upstream HTTP `401`/`403`/`404`/`429`/`5xx` and network timeouts to actionable `ToolError` (`isError: true`).
  - `src/server.py`: Structured `stderr` JSON logging (`SEP-2577` compliant), `FileSystemProvider` zero-circular-import tool discovery, and `ForgeResponseLimitingMiddleware` preserving JSON Schema `2020-12` `outputSchema` while bounding oversized payloads (`32,768` bytes default).
  - `respx/`: Strictly-typed first-party offline `httpx` transport mock library supporting `@respx.mock`, route matchers, call history inspection, and dynamic response overrides without network access.
- **Stages 2–5 Self-Healing Orchestrator & Deterministic Synthesizer (`forge/orchestrator.py`, `forge/codegen.py`):**
  - Supports both hardened Docker container sandboxing (`--cap-drop=ALL`, `:ro` root mount with `:rw` overlays on `src/tools/`, `tests/unit/`, `README.md`, and `--network=none` Stage 4 validation) and `--local` (`--execution-mode local`) deterministic offline code generation.
  - Up to `MAX_HEAL_ITERATIONS = 3` automated self-healing retries fed by validator diagnostics.
  - Stage 5 `forge-release-artifacts.json` emission with `mcpServers` client configuration and `requires_appsec_destructive_signoff` governance metadata.
- **Reference Acme Incident Management MCP Server (`src/tools/*.py`) & Specs (`spec/`):**
  - 5 stateless MCP `2026-07-28` tools (`get_incident`, `list_incidents`, `create_incident` with RFC 9110 `x-mcp-header: Idempotency-Key`, `update_incident_status`, `delete_incident`).
  - Sample OpenAPI 3.1 specifications (`spec/acme-incidents.openapi.yaml` and `spec/cloud-billing.openapi.json`).
- **5-Gate Verification Suite (`scripts/validate_mcp.py`, `tests/`):**
  - Ruff + Bandit (`S`) + print ban (`T20`), `mypy --strict`, AST security & `SEP-2577` deprecation audit, `pytest` contract/unit/pipeline suite (`100.0%` branch coverage on `src/tools/`), and live subprocess `PythonStdioTransport` `server/discover` (`2026-07-28`) verification.
- **Khazad-dûm Forge Visual Kit, Live Build Dashboard & Documentation Suite:**
  - Deterministic Khazad-dûm Dwarven Forge SVG + PNG generator (`scripts/render-graphics.py`), illustrated forge artworks (`docs/assets/`), GitHub Pages interactive showcase (`docs/index.html`), live build telemetry dashboard (`dashboard/index.html`), and 5-chapter User Guide (`docs/user-guide/`).

### Security
- Enforced MCP `2026-07-28` Token Passthrough Prohibition via server-bound `httpx.Auth` environment variable resolution (`src/auth.py`).
- Blocked external `$ref` SSRF vectors and bounded local `$ref` recursion depth (`<= 25`) in `forge/ingest_openapi.py`.
- Enforced static AST bans on unsafe imports (`os`, `sys`, `subprocess`, `socket`, `shutil`, `pathlib`, `ctypes`, `pickle`, `importlib`), builtins (`eval`, `exec`, `compile`, `open`, `__import__`, `print`), `SEP-2577` deprecated methods, and prompt-injection docstrings in `scripts/validate_mcp.py`.
- Added Stage 5 `requires_appsec_destructive_signoff` governance metadata for mutating/destructive tools (`forge-release-artifacts.json`).

### Verified
- `.venv/bin/python scripts/validate_mcp.py` -> **PASS** (all 5 gates: Ruff, `mypy --strict`, AST/SEP-2577 audit, Pytest `>=85%` branch coverage gate with `100.0%` achieved on `src/tools/`, and subprocess `stdio` `server/discover` on MCP `2026-07-28`).
