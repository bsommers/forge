# Chapter 4 — CLI, Manifest & Environment Reference

[← Chapter 3: Authoring Tools](03-mcp-2026-07-28-authoring.md) · [User Guide Index](README.md) · [← Back to Project README](../../README.md)

## Table of Contents

- [`python -m forge.ingest_openapi` CLI](#python--m-forgeingest_openapi-cli)
- [`python -m forge.orchestrator` CLI](#python--m-forgeorchestrator-cli)
- [`python scripts/validate_mcp.py` Gate Reference](#python-scriptsvalidate_mcppy-gate-reference)
- [`python dashboard/telemetry.py` CLI](#python-dashboardtelemetrypy-cli)
- [`python3 -s scripts/render-graphics.py` CLI](#python3--s-scriptsrender-graphicspy-cli)
- [`forge-manifest.json` Schema Reference](#forge-manifestjson-schema-reference)
- [Runtime Environment Variables](#runtime-environment-variables)
- [Exit Codes](#exit-codes)

---

## `python -m forge.ingest_openapi` CLI

Stage 1 OpenAPI 3.x YAML/JSON normalizer.

| Flag | Type | Required | Default | Description |
|------|------|:--------:|---------|-------------|
| `--spec` | `Path` | Yes | — | Path to OpenAPI 3.x `.yaml`, `.yml`, or `.json` specification |
| `--name` | `str` | Yes | — | Kebab-case MCP server identifier (e.g., `acme-incidents`) |
| `--tag-filter` | `str` | No | `None` | Include only operations tagged with `<tag>` |
| `--workflows` | `Path` | No | `None` | Optional `forge-workflows.yaml`/`.json` sidecar compiling multi-endpoint `@tool` joins |
| `--max-output-fields` | `int` | No | `8` | Maximum high-signal fields projected per tool `outputSchema` (`1..20`) |
| `--output` | `Path` | No | `stdout` | Destination file path for `forge-manifest.json` |

---

## `python -m forge.orchestrator` CLI

Stages 1–5 end-to-end self-healing orchestrator.

| Flag | Type | Required | Default | Description |
|------|------|:--------:|---------|-------------|
| `--spec` | `Path` | Yes | — | OpenAPI 3.x YAML/JSON file |
| `--name` | `str` | Yes | — | Kebab-case MCP server name |
| `--output-dir` | `Path` | Yes | — | Target directory for the generated FastMCP server repo |
| `--tag-filter` | `str` | No | `None` | Optional OpenAPI tag slice (`<= 15` tools) |
| `--workflows` | `Path` | No | `None` | Optional `forge-workflows.yaml`/`.json` sidecar for composite multi-call `@tool` joins |
| `--template-dir` | `Path` | No | `./golden-template` | Source Golden Template directory |
| `--prompt-file` | `Path` | No | `./forge/AGENT_SYSTEM_PROMPT.md` | System prompt injected into Stage 3 coding agent |
| `--max-output-fields` | `int` | No | `8` | Maximum high-signal fields projected per tool `outputSchema` (`1..20`) |
| `--toolset-budget` | `int` | No | `15` | Maximum active tools per shard and emitted `client_profiles` entry (`1..15`) |
| `--execution-mode` | `docker\|local\|agent` | No | `docker` | `docker` (containers), `local` (deterministic projection), or `agent` (host CLI + kernel sandbox + SHA-256 lock guard) |
| `--agent-cmd` | `str` | No | `""` | Host CLI command template for `--execution-mode agent` (`{prompt_file}`, `{workspace}`) |
| `--sandbox-policy` | `auto\|required\|off` | No | `auto` | OS kernel sandbox policy (`sandbox-exec` on macOS, `bwrap` on Linux) for `--execution-mode agent` |
| `--fixtures-dir` | `Path` | No | `None` | Optional directory of recorded upstream JSON fixtures replayed against schemas in Stage 4 |
| `--auto-split-tags` | `bool` | No | `False` | Partition `> 15`-tool OpenAPI specs by tag into `<= 15`-tool server shards + `client_profiles` |
| `--emit-oscal` | `bool` | No | `False` | Emit deterministic NIST OSCAL `1.1.2` `SSP`, `SAR`, `POA&M`, and `SSP.md` during Stage 5 |
| `--local` | `bool` | No | `False` | Shorthand alias for `--execution-mode local` |
| `--agent-image` | `str` | No | `mcp-forge-agent:latest` | Docker image for Stage 3 coding agent |
| `--validator-image` | `str` | No | `mcp-forge-validator:latest` | Docker image for `--network=none` Stage 4 validation |
| `--registry-prefix` | `str` | No | `ghcr.io/org` | Container registry prefix written to Stage 5 artifacts |

---

## `python scripts/validate_mcp.py` Gate Reference

Deterministic 5-gate verification harness executed in Stage 4 and local CI:

| Gate # | Gate Label | Underlying Check | Pass Threshold |
|:------:|------------|------------------|----------------|
| **1** | `Ruff Lint & Security` | `python -m ruff check src tests` | Zero lint, Bandit (`S`), `T20` print, or annotation violations |
| **2** | `Mypy Strict Typecheck` | `python -m mypy src` | Zero `--strict` + `pydantic.mypy` errors |
| **3** | `AST Security, SEP-2577 Deprecation & Docstring Audit` | `audit_tools_ast()` over `src/tools/*.py` | Zero forbidden imports/builtins, deprecated calls, or prompt injections |
| **4** | `Pytest Contract + Unit & Branch Coverage` | `python -m pytest --cov=src/tools --cov-branch --cov-fail-under=85` | 100% tests passing and `>= 85%` branch coverage on `src/tools/` |
| **5** | `Subprocess STDIO Discovery & Frame Hygiene` | `PythonStdioTransport` + `Client` | `protocol_version == "2026-07-28"` and exact manifest `tools/list` match |

---

## `python dashboard/telemetry.py` CLI

| Flag | Default | Description |
|------|---------|-------------|
| `--once` | `False` | Generate a single atomic `dashboard/status.js` snapshot and exit |
| `--watch` | `False` | Continuously update `dashboard/status.js` at `--interval` seconds |
| `--interval` | `1.5` | Poll interval in seconds during `--watch` |
| `--duration` | `300.0` | Maximum watch duration in seconds before clean exit |
| `--serve` | `False` | Optional local HTTP server serving `dashboard/` |
| `--port` | `8765` | HTTP bind port when `--serve` is passed |

---

## `python3 -s scripts/render-graphics.py` CLI

| Flag | Default | Description |
|------|---------|-------------|
| `--quiet`, `-q` | `False` | Render all 12 SVG + 12 PNG brand/example assets silently |

---

## `forge-manifest.json` Schema Reference

| Path | Type | Description |
|------|------|-------------|
| `protocol_revision` | `str` | Fixed to `"2026-07-28"` |
| `server_name` | `str` | Kebab-case server identifier |
| `title` | `str` | Human-readable server title |
| `version` | `str` | Semantic version (e.g., `"1.0.0"`) |
| `description` | `str` | Server instructions (`<= 500` chars) |
| `upstream.base_url_env` | `str` | Environment variable overriding `default_base_url` |
| `upstream.default_base_url` | `str` | Fallback upstream REST base URL |
| `upstream.timeout_seconds` | `float` | Per-request timeout in seconds (`15.0` default) |
| `upstream.max_response_bytes` | `int` | Payload cap enforced by `ForgeResponseLimitingMiddleware` (`32768` default) |
| `auth.type` | `str` | One of `none`, `bearer`, `basic`, `api_key_header`, `api_key_query`, `oauth2_client_credentials` |
| `tools[]` | `list` | `1..15` tool definitions (`name`, `title`, `method`, `path`, `description`, `annotations`, `required_params`) |

---

## Runtime Environment Variables

| Variable | Required | Default | Used By |
|----------|:--------:|---------|---------|
| `<PREFIX>_BASE_URL` (e.g. `ACME_BASE_URL`) | No | `upstream.default_base_url` | `src/server.py` (`server_lifespan`) |
| `<PREFIX>_API_TOKEN` (e.g. `ACME_API_TOKEN`) | Conditional | — | `src/auth.py` when `auth.type == "bearer"` |
| `<PREFIX>_API_KEY` | Conditional | — | `src/auth.py` when `auth.type` is `api_key_header` or `api_key_query` |
| `<PREFIX>_USERNAME` / `<PREFIX>_PASSWORD` | Conditional | — | `src/auth.py` when `auth.type == "basic"` |
| `<PREFIX>_OAUTH_TOKEN_URL` / `_CLIENT_ID` / `_CLIENT_SECRET` | Conditional | — | `src/auth.py` when `auth.type == "oauth2_client_credentials"` |
| `MCP_TRANSPORT` | No | `stdio` | `src/server.py` (`stdio` or `http`) |
| `PORT` | No | `8000` | `src/server.py` when `MCP_TRANSPORT=http` |
| `LOG_LEVEL` | No | `INFO` | `src/server.py` (`StderrJsonFormatter` level) |

---

## Exit Codes

| Exit Code | Source | Meaning |
|:---------:|--------|---------|
| `0` | All CLIs | Success / all verification gates passed |
| `1` | `scripts/validate_mcp.py`, `forge.orchestrator` | Verification gate failed or self-healing exhausted `MAX_HEAL_ITERATIONS` (`3`) |
| `2` | `argparse` CLIs | Invalid or missing required CLI flag |

Next: **[Chapter 5 — Troubleshooting & FAQ](05-troubleshooting-and-faq.md)**.
