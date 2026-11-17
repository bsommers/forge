# Purpose & Threat Model

<p align="center">
  <img src="assets/logo.svg" alt="MCP Server Forge Hero Banner" width="100%" />
</p>

## Problem Statement

Enterprise teams adopting the **Model Context Protocol (`2026-07-28`)** routinely wrap internal REST APIs with hand-written or naively LLM-generated MCP servers. In practice, ad-hoc wrappers fail along four predictable fault lines:

1. **Credential Passthrough & SSRF Leaks:** Forwarding raw client `Authorization` headers upstream violates the MCP Token Passthrough Prohibition, while unvalidated external `$ref` URIs in OpenAPI schemas expose build and runtime hosts to SSRF and recursive expansion DoS.
2. **Context Window Blowout:** Dumping 40+ auto-generated endpoints or multi-megabyte upstream JSON blobs into tool responses exhausts LLM token budgets and degrades tool-selection accuracy.
3. **Deprecated Session State (`SEP-2575` / `SEP-2567` / `SEP-2577`):** Servers written against legacy stateful MCP sessions (`initialize`, `Mcp-Session-Id`, `ping`, `ctx.sample()`, `ctx.list_roots()`, `logging/setLevel`) break under modern stateless `server/discover` negotiation or corrupt `stdio` frames with stray `print()` calls.
4. **Unverified Agent Code:** Letting a coding agent edit its own `pyproject.toml`, auth layer, or contract test suite enables reward hacking — passing tests by weakening assertions rather than fixing broken tools.

---

## Solution

**MCP Server Forge** treats server generation like a Dwarven master-foundry: **deterministic infrastructure is forged once and locked in stone (`:ro`), while AI synthesis is confined strictly to stateless tool adapters (`:rw`) verified behind five offline quality gates.**

<p align="center">
  <img src="assets/khazad-dum-pipeline.png" alt="The Five Great Forge Chambers of MCP Server Forge" width="100%" />
</p>

1. **Smelt (Stage 1 — `forge/ingest_openapi.py`):** Normalizes OpenAPI 3.x YAML/JSON into `forge-manifest.json`, inlining local `$ref`s (`<= 25` depth), blocking external `$ref` URIs, slicing domains to `<= 15` tools via `--tag-filter`, and deriving `ToolAnnotations` from HTTP semantics.
2. **Mold (Stage 2 — `golden-template/`):** Clones the hardened FastMCP 4.x Golden Template (`src/auth.py`, `src/deps.py`, `src/server.py`, `tests/contract/test_forge_contract.py`, `scripts/validate_mcp.py`) and locks all security-critical files read-only.
3. **Hammer (Stage 3 — `forge/orchestrator.py` & `forge/codegen.py`):** Synthesizes pure async `@tool` modules (`src/tools/*.py`), Pydantic `2020-12` `outputSchema` models, and `respx` unit tests (`tests/unit/*.py`) — either inside a privilege-dropped Docker container or deterministically via `--local`.
4. **Temper (Stage 4 — `scripts/validate_mcp.py`):** Runs Ruff + Bandit (`S`) + `T20` print ban, `mypy --strict`, AST security & `SEP-2577` deprecation audit, `pytest` (`>= 85%` branch coverage), and live subprocess `stdio` `server/discover` (`2026-07-28`) verification with up to 3 self-healing retries.
5. **Seal (Stage 5 — `forge-release-artifacts.json`):** Emits `mcpServers` client config snippets and PR governance labels flagging mutating or destructive tools (`requires_appsec_destructive_signoff`) for human-in-the-loop review.

---

## Goals

1. **Zero-Trust Security Boundaries** — Enforce env-bound upstream auth, forbid `os`/`subprocess`/`open`/`eval` in `src/tools/`, and run verification with `--network=none`.
2. **Strict MCP `2026-07-28` Compliance** — Guarantee stateless `server/discover` negotiation, deterministic `tools/list` ordering, JSON Schema `2020-12` `outputSchema` + `structuredContent`, and RFC 9110 `x-mcp-header` validation.
3. **Context-Window Discipline** — Cap each server at `<= 15` tools and bound serialized tool outputs (`32,768` bytes default) via `ForgeResponseLimitingMiddleware` without stripping `outputSchema`.
4. **Deterministic Offline Verification** — Every generated server must compile, lint, typecheck, achieve `>= 85%` branch coverage (`100%` on reference tools), and pass subprocess `stdio` discovery with zero live network access.

## Non-Goals

- **Not a dynamic runtime OpenAPI proxy** — Runtime proxies expose raw upstream payloads and lack curated Pydantic projections or per-tool unit tests. Forge generates explicit, auditable Python code checked into Git.
- **Not a stateful workflow engine** — Per `SEP-2575` and `SEP-2567`, cross-request session globals are forbidden; pagination cursors and idempotency keys pass explicitly as tool inputs and outputs.
- **Not an unbounded API dump** — Specs with `> 15` operations are intentionally rejected unless sliced by domain (`--tag-filter`).

---

## Users and Stakeholders

| Audience | How They Interact | Primary Need |
|----------|-------------------|--------------|
| **Platform & AI Engineers** | Run `python -m forge.orchestrator` on internal OpenAPI specs | Turn REST services into production FastMCP 4.x servers in minutes |
| **Application Security (AppSec)** | Review `forge-release-artifacts.json` & locked contract gates | Guarantee no credential passthrough, shell access, or unreviewed `DELETE` tools |
| **AI Coding Agents / MCP Clients** | Connect via `stdio` or Streamable HTTP (`server/discover`) | Concise, typed `structuredContent`, deterministic schemas, actionable `ToolError`s |
| **SRE & Incident Commanders** | Use the reference `acme-incidents` MCP server (`src/`) | Triage, create, update, and resolve operational incidents safely from an LLM assistant |

---

## Success Criteria

- [x] Stage 1 rejects external `$ref` URIs and `$ref` depth `> 25` with `SpecNormalizationError`.
- [x] Stage 2–3 isolates writable paths strictly to `src/tools/`, `tests/unit/`, and `README.md`.
- [x] Stage 4 passes all 5 deterministic gates (`ruff`, `mypy --strict`, AST `SEP-2577` audit, `pytest >= 85%` branch coverage, and subprocess `stdio` `server/discover` `2026-07-28`).
- [x] Stage 5 flags any `destructiveHint: true` tool (`delete_incident`) with `requires_appsec_destructive_signoff: true`.

---

## Relationship to Other Systems

```
  ╔═════════════════════════╗
  ║  OpenAPI 3.x YAML/JSON  ║  (spec/acme-incidents.openapi.yaml, cloud-billing.openapi.json)
  ╚════════════╤════════════╝
               │  Stage 1: forge.ingest_openapi
               ▼
  ┌─────────────────────────────────────────────────────────────────────┐
  │                       MCP SERVER FORGE                              │
  │  forge-manifest.json ──► Golden Template (:ro) + Synthesis (:rw)    │
  │                      ──► 5-Gate Validator ──► Release Governance    │
  └───────────────────────────┬──────────────────────────┬──────────────┘
                              │                          │
          MCP 2026-07-28      ▼                          ▼  Lifespan httpx Pool
  ╔═══════════════════════════════╗          ╔══════════════════════════╗
  ║  Claude / Antigravity / IDEs  ║          ║  Upstream REST Services  ║
  ║  (server/discover + tools)    ║          ║  (Bearer / APIKey / OAuth║
  ╚═══════════════════════════════╝          ╚══════════════════════════╝
```

---

## Trade-offs Made

- **Compile-time code generation over runtime OpenAPI proxying**: Chose ahead-of-time Python synthesis (`src/tools/*.py`) over generic runtime schema translation so every tool has explicit Pydantic models, AST security auditing, and `>= 85%` branch-covered unit tests. Cost: re-running Forge when upstream OpenAPI contracts change.
- **15-tool hard ceiling per server**: Chose `MAX_TOOLS_PER_SERVER = 15` over exposing monolithic 100-endpoint specs because LLM tool-routing precision drops sharply past ~15 tools. Cost: large APIs require one `--tag-filter` invocation per domain.
- **`ForgeResponseLimitingMiddleware` string-field truncation over plain-text fallback**: Base FastMCP `ResponseLimitingMiddleware` strips `outputSchema` on `tools/list` so truncated plain-text responses do not fail client schema validation. Subclassing it to truncate oversized string fields inside `structured_content` preserves JSON Schema `2020-12` `outputSchema` while still enforcing `max_response_bytes`.
