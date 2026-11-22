---
status: COMPLETE — v1.4.0 (M0–M4 + OSCAL Stage 5) shipped across 4-repo ecosystem; M5 (v2.0.0) queued next
next: `.venv/bin/python scripts/validate_mcp.py && .venv/bin/python -m pytest -q`
depends: [security-controls, secure-design-patterns, security-assurance]
---

# Session Checkpoint — MCP Server Forge & Continuous Security Assurance Ecosystem

**Status:** COMPLETE through `v1.4.0` (`M0`–`M4` + `M3.5` NIST/OSCAL integration); all 4 public repositories clean, tested, branded with dual SVG+PNG logo kits, and pushed to `origin/main`.

---

## Done (with evidence)

### 1. `bsommers/forge` (`/Users/bill/src/swe/forge` — Active Workspace)
- **Release & Remote:** Tagged and published [`v1.4.0`](https://github.com/bsommers/forge/releases/tag/v1.4.0) on `https://github.com/bsommers/forge`.
- **Milestone `M4` (`W4.1`–`W4.4`, [Plan 03](plans/03-wild-openapi-resilience-composite-tools-and-hardened-bounds.md)):**
  - **`W4.1` (`forge/ingest_openapi.py`):** Cycle-safe `schema_ancestors` `$ref` resolution (breaks recursive object schemas such as `User.manager -> User` into `{id: str, x-mcp-cycle-broken: true}` while preserving diamond reuse) + path-confined relative YAML/JSON `$ref` loading within `spec_dir.resolve()` (rejecting `../` traversal and remote `http(s)://` SSRF).
  - **`W4.2` (`forge/projection.py`):** `flatten_composed_schema()` (`allOf` merge + nullable/polymorphic `oneOf`/`anyOf`) and data-carrier array preservation (`datapoints`, `rows`, `series`, `events` scored `78` ahead of `*_at` timestamps `45`).
  - **`W4.3` (`forge/codegen.py`, `tests/contract/test_forge_contract.py`, `golden-template/`):** Typed `requestBody` synthesis (`float`, `Literal[...]`, `list[T]`, nested `<Tool><Param>Input(BaseModel)`) and schema-driven contract test sample generation (`_sample_arg_for_schema`).
  - **`W4.4` (`src/server.py`, `golden-template/src/server.py`):** Dual-axis `bound_structured_content()` in `ForgeResponseLimitingMiddleware` (Pass 1 binary-search list-cardinality slicing + Pass 2 conservative `ensure_ascii=True` wire-JSON string truncation + Pass 3 `ToolError` fallback), closing **`POAM-FORGE-W4.4`** (`NIST SC-5` -> `satisfied`).
- **Stage 5 `--emit-oscal` (`forge/oscal_attestation.py`, `forge/orchestrator.py`, [Plan 04](plans/04-research-spike-nist-800-53-cosis-attestation.md)):**
  - Emits deterministic UUIDv5 NIST OSCAL `1.1.2` `oscal/{component-definition,ssp,assessment-results,poam}.json` + `SSP.md` and enforces `verify_oscal_policy_gate()` directly inside `forge.orchestrator --emit-oscal`.
- **Verification Evidence:**
  - `.venv/bin/python scripts/validate_mcp.py` -> `[PASS] ALL 5 MCP 2026-07-28 GATES SUCCEEDED` (`100.0%` `src/tools` branch cov).
  - `.venv/bin/python -m pytest -q` -> `57 passed`.
  - `.venv/bin/python -m ruff check src forge respx scripts tests dashboard && .venv/bin/python -m mypy src forge respx` -> `0` issues (`17` source files).

### 2. `bsommers/secure-design-patterns` (`/Users/bill/src/swe/secure-design-patterns`)
- **Remote & HEAD:** `https://github.com/bsommers/secure-design-patterns` (`main` @ `0232495`, GitHub Actions CI green).
- **Shipped:**
  - Normative `authorities/mcp-2026-07-28.json` (`13` specification & RFC authorities) + `patterns/mcp-serve/catalog.json` (`MCP-001` through `MCP-008`) validated against JSON Schema `2020-12`.
  - `5` zero-dependency runnable Python reference implementations (`patterns/mcp_serve_ref/`), including `dual_axis_bounding.py`, `cycle_safe_ref_resolver.py`, `route_dispatch_auth.py`, `optional_mcp_header.py`, and `tamper_evident_workspace.py`.
  - *"Blue-Note Prism Blueprint"* Art-Deco Cyber-Jazz SVG+PNG logo kit (`scripts/render_graphics.py`, `assets/logo.{svg,png}`, `docs/assets/{logo,icon}.{svg,png}`, `docs/assets/hero-illustration.png`).
  - **Evidence:** `pytest -q` -> `11 passed`; `mypy --strict` -> `0` issues.

### 3. `bsommers/security-controls` (`/Users/bill/src/swe/security-controls`)
- **Remote & HEAD:** `https://github.com/bsommers/security-controls` (`main` @ `45fee09`, GitHub Actions CI green).
- **Shipped:**
  - Machine-readable NIST SP 800-53 Rev. 5 Update 1 catalog (`20` control families, `45` core controls & enhancements) + **NIST COSIS** (*SP 800-53 Control Overlays for Super Intelligence Systems*, `https://csrc.nist.gov/projects/cosis/use-cases`) overlays across all `5` official use cases (`UC-GEN`, `UC-PRED`, `UC-AGENT-SINGLE`, `UC-AGENT-MULTI`, `UC-DEV`).
  - Deterministic multi-overlay resolver (`resolve_controls`) and UUIDv5 OSCAL `1.1.2` Profile compiler (`export_oscal_profile`).
  - *"20-Family Star-Dial & 5-Node COSIS Aegis"* SVG+PNG logo kit + open GitHub Milestone `#1` (`M1: v1.1.0 — Research Spike`).
  - **Evidence:** `pytest -q` -> `8 passed`; `mypy --strict` -> `0` issues.

### 4. `bsommers/security-assurance` (`/Users/bill/src/swe/security-assurance`)
- **Remote & HEAD:** `https://github.com/bsommers/security-assurance` (`main` @ `0c73c3d`, GitHub Actions OPA + OSCAL CI green).
- **Shipped:**
  - Compiles `security-controls` + `secure-design-patterns` + `forge` (`acme-incidents` `v1.4.0`) into OSCAL `1.1.2` `component-definition`, `ssp`, `assessment-results`, `poam` (`POAM-FORGE-W4.4` closed; `POAM-FORGE-W5.2` tracking `SC-39` host sandbox for `M5`), and human-readable `docs/rendered/acme-incidents-SSP.md`.
  - `3` Open Policy Agent (`Rego v1`) policy suites + unit tests (`policies/forge/manifest_guard.rego`, `policies/oscal/ssp_gate.rego`, `policies/runtime/mcp_tool_authz.rego`), `ADR-0001` (OSCAL = declarative state nouns; Rego = executable policy verbs), and *"Tri-Gate Policy Conductor"* SVG+PNG logo kit.
  - **Evidence:** `pytest -q` -> `7 passed`; `opa check --strict` & `opa test -v` -> green in CI.

---

## Failed / blocked

- **None blocked.** All gates across all four repositories pass locally and in GitHub Actions.

---

## Bugs fixed this session

1. **`ensure_ascii=True` 3x JSON surrogate-escape budget overflow (`src/server.py`, `golden-template/src/server.py`):** Measuring `json.dumps(..., ensure_ascii=False)` undercounted 4-byte UTF-8 emojis (`🔥`) that serialize to 12-byte `\ud83d\udd25` escapes on default JSON wires. Fixed `_wire_json_len()` to measure conservative `ensure_ascii=True` byte length.
2. **`_collect_tool_params` ordering in `forge/codegen.py`:** Previously `required_params` fallback ran before `request_body_schema`, coercing required body properties to `str` query parameters. Fixed by parsing `request_body_schema` before the fallback loop.
3. **Typed contract test sample synthesis (`tests/contract/test_forge_contract.py` & `golden-template/`):** Replaced hardcoded `"INC-1"` sample values with `_sample_arg_for_schema()` so `float`, `integer`, `boolean`, `array`, `object`, and `enum` parameters pass Pydantic validation during generic contract runs.
4. **Alias `$ref` loop vs. recursive object `$ref` (`forge/ingest_openapi.py`):** Added only concrete non-`$ref` targets (`"$ref" not in target`) to `schema_ancestors`, breaking real object cycles (`User.manager -> User`) while still raising `SpecNormalizationError` on degenerate alias loops (`Node -> Node`).
5. **ImageMagick MVG SVG rasterizer quirks (`scripts/render-graphics.py` & companion `render_graphics.py`):** Used explicit `width`/`height` attributes, 72-vertex `<polygon>` coordinates instead of 3-argument `rotate(deg cx cy)`, no `letter-spacing`, and explicit `-font /System/Library/Fonts/Helvetica.ttc` substitution during PNG rasterization.
6. **GitHub Pages v4 artifact permissions (`.github/workflows/pages.yml`):** Split `build` (`actions/upload-pages-artifact@v4.0.0`) and `deploy` (`actions/deploy-pages@v4.0.5` with explicit `actions: read`) so job-level `permissions:` does not strip `GITHUB_TOKEN`'s ability to read the uploaded `github-pages` artifact metadata.

---

## State that may have changed

- **4 sibling git repositories under `/Users/bill/src/swe/`:**
  - `/Users/bill/src/swe/forge` (`bsommers/forge`, active workspace)
  - `/Users/bill/src/swe/secure-design-patterns` (`bsommers/secure-design-patterns`)
  - `/Users/bill/src/swe/security-controls` (`bsommers/security-controls`)
  - `/Users/bill/src/swe/security-assurance` (`bsommers/security-assurance`)
- **Locked/Template sync:** `src/{auth,deps,server}.py`, `tests/contract/test_forge_contract.py`, and `scripts/validate_mcp.py` are byte-synchronized with `golden-template/`.
- **Architecture & value synthesis:** Documented in [SECURE_DESIGN_PATTERNS.md](SECURE_DESIGN_PATTERNS.md) and [ECOSYSTEM_VALUE_AND_RELEVANCE.md](ECOSYSTEM_VALUE_AND_RELEVANCE.md).

---

## Next steps

1. **Sanity-check baseline on resume (from `/Users/bill/src/swe/forge`):**
   ```bash
   .venv/bin/python scripts/validate_mcp.py && .venv/bin/python -m pytest -q
   ```
2. **Execute `forge` Milestone `M5` (`v2.0.0`) — Composite Workflows & Host Sandboxing ([Plan 03](plans/03-wild-openapi-resilience-composite-tools-and-hardened-bounds.md)):**
   - **`W5.1`:** Implement `x-mcp-workflows` server-side multi-call composite `@tool` joins and `client_profiles` (`<= 15` tools per task role) in `forge/ingest_openapi.py` + `forge/codegen.py`.
   - **`W5.2`:** Wrap `--execution-mode agent` subprocesses in macOS `sandbox-exec` / Linux `bwrap` inside `forge/orchestrator.py` (closing **`POAM-FORGE-W5.2`** / `NIST SC-39` in both `forge/oscal_attestation.py` and `bsommers/security-assurance`) + add `tests/fixtures/` recorded replay support.
3. **Execute `security-controls` Milestone `M1` (`v1.1.0`) — Full NIST OSCAL Catalog Research Spike (`/Users/bill/src/swe/security-controls/docs/plans/01-research-spike-oscal-cosis-automated-overlay-compilation.md`):**
   - Vendor pinned `usnistgov/oscal-content` Rev. 5.1.1 JSON (`1,189` controls + enhancements), benchmark `< 150ms` cold index load, validate emitted OSCAL `1.1.2` profiles against NIST's official `oscal_profile_schema.json`, and run property-based `hypothesis` monotonicity fuzzing (`RS-1`–`RS-4`).
