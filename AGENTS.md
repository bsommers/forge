# AGENTS.md — MCP Server Forge (`2026-07-28`)

## 1. What This Repository Is
**MCP Server Forge** transforms OpenAPI 3.x YAML/JSON specifications into hardened, stateless **FastMCP 4.x** servers compliant with **Model Context Protocol Specification `2026-07-28`** (`SEP-2575` `server/discover`, `SEP-2567` sessionless Streamable HTTP, `SEP-2577` deprecations, and JSON Schema `2020-12` `outputSchema`/`structuredContent`). It includes both the 5-stage Forge host pipeline (`forge/`) and a live reference forged server (`acme-incidents` in `src/`).

## 2. Commands (Run from Repository Root)
- **Single-command 5-gate verification (run first; `PASS` = done):**
  ```bash
  .venv/bin/python scripts/validate_mcp.py
  ```
- **Install / sync environment:** `uv sync`
- **All tests + branch coverage:** `.venv/bin/python -m pytest --cov=src/tools --cov=forge --cov-branch`
- **Single test file:** `.venv/bin/python -m pytest tests/forge/test_ingest_openapi.py -q`
- **Lint & strict typecheck:** `.venv/bin/python -m ruff check src forge respx scripts tests dashboard && .venv/bin/python -m mypy src forge respx`
- **Normalize OpenAPI -> `forge-manifest.json`:** `.venv/bin/python -m forge.ingest_openapi --spec spec/acme-incidents.openapi.yaml --name acme-incidents`
- **Forge a server locally (offline, no Docker required, with OSCAL 1.1.2 SSP emission):**
  ```bash
  .venv/bin/python -m forge.orchestrator --spec spec/acme-incidents.openapi.yaml --name acme-incidents --output-dir /tmp/forged-acme --local --emit-oscal
  ```
- **Re-render Khazad-dûm SVG + PNG visuals:** `python3 -s scripts/render-graphics.py`
- **Refresh live build dashboard snapshot:** `.venv/bin/python dashboard/telemetry.py --once`

## 3. Architecture Map
- `forge/` — Host pipeline: `ingest_openapi.py` (Stage 1 normalizer + cycle-safe/relative `$ref`s + `x-mcp-workflows`), `projection.py` (deterministic high-signal field ranker + `allOf`/`oneOf` flattening), `workflows.py` (DAG multi-endpoint workflow compiler + `client_profiles` budgeter), `codegen.py` (local projected tool, workflow, & test synthesizer), `sandbox.py` (macOS `sandbox-exec` / Linux `bwrap` host-agent kernel confinement), `oscal_attestation.py` (Stage 5 OSCAL `1.1.2` SSP/SAR/POA&M emitter), `orchestrator.py` (Stages 2–5 Docker, `--local`, & kernel-sandboxed `--execution-mode agent` runner), `AGENT_SYSTEM_PROMPT.md`.
- `golden-template/` — Immutable Golden Template baseline cloned during Stage 2 (`stage_workspace`).
- `src/` — Active forged FastMCP server: `auth.py` (env-bound `httpx.Auth`), `deps.py` (`Depends(get_http_client)` + `request_json`), `server.py` (`FileSystemProvider` + `ForgeResponseLimitingMiddleware`), `tools/*.py` (stateless domain `@tool` modules).
- `respx/` — First-party strictly-typed offline `httpx` transport mock package used by contract and unit suites.
- `scripts/validate_mcp.py` — 5-gate deterministic verifier (Ruff, Mypy `--strict`, AST `SEP-2577` audit, Pytest `>=85%` branch coverage, subprocess `stdio` `server/discover`).
- `spec/` — OpenAPI 3.1 specifications (`acme-incidents.openapi.yaml`, `cloud-billing.openapi.json`).
- `dashboard/` — Local zero-CORS HTML Mission Control dashboard (`index.html`, `telemetry.py`, `status.js`).
- `docs/` — Living docs (`ARCHITECTURE.md`, `SECURE_DESIGN_PATTERNS.md`, `PURPOSE.md`, `HOWTO.md`, `ROADMAP.md`, `plans/01..03`, `brochure.md`, `index.html`, `user-guide/`).

## 4. Non-Negotiable Invariants & Contracts
1. **Token Passthrough Prohibition:** Upstream credentials MUST come exclusively from server-bound env vars via `src/auth.py`; never forward MCP client auth headers upstream.
2. **AST Gate on `src/tools/*.py`:** Never import `os`, `sys`, `subprocess`, `socket`, `shutil`, `pathlib`, `ctypes`, `pickle`, or `importlib`, and never call `print()`, `open()`, `eval()`, `exec()`, `.sample()`, `.list_roots()`, or `.set_logging_level()` inside `src/tools/`.
3. **Manifest Parity:** Every tool in `forge-manifest.json` (`<= 15` max) must match `@tool(name=..., title=..., annotations=ToolAnnotations(...))`, return an explicit Pydantic `BaseModel` (`outputSchema` with zero external `$ref`s), and inject `client: ApiClient`.
4. **Locked vs. Writable Split:** During Stage 3 generation, only `src/tools/*.py`, `tests/unit/*.py`, and `README.md` are agent-writable; keep `src/{auth,deps,server}.py`, `tests/contract/`, and `scripts/validate_mcp.py` synchronized with `golden-template/`.

## 5. Known Pitfalls & Quirks
- **`mcp==2.3.0` `x-mcp-header` union types:** `mcp` drops any tool from `tools/list` if a parameter carrying `json_schema_extra={"x-mcp-header": "..."}` emits `anyOf` (such as `str | None`). Declare optional `x-mcp-header` parameters as `Annotated[str, Field(default="", ...)] = ""` and treat `""` as omitted.
- **FastMCP `ResponseLimitingMiddleware` & `outputSchema`:** Base `ResponseLimitingMiddleware.on_list_tools` strips `output_schema=None`. Always use `ForgeResponseLimitingMiddleware` in `src/server.py`, which preserves `outputSchema` and truncates string values inside `structured_content`.
- **Async DI lifespan safety:** `get_http_client` in `src/deps.py` must stay `async def` so FastMCP's dependency injector does not re-enter the lifespan `httpx.AsyncClient` context manager.

## 6. Verification & Doc Sync Before Commit
1. Run `.venv/bin/python scripts/validate_mcp.py` and `.venv/bin/python -m pytest`.
2. If counts, flags, or modules change, re-run `python3 -s scripts/render-graphics.py` and verify `tests/forge/test_docs_alignment.py` passes.
3. Living docs: `README.md`, `docs/{README,PURPOSE,ARCHITECTURE,HOWTO,brochure}.md`, `docs/user-guide/*.md`, `docs/index.html`. Historical initial design blueprints: `docs/coding_agent_system_prompt_mcp_2026_07_28.md`, `docs/python_fastmcp_golden_template_repository (1).md`, `docs/stage_1_normalizer_stage_2_5_orchestrator.md`.
