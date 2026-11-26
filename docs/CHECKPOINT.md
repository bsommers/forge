---
status: IN PROGRESS — needs resume (queued: 1 forge v2.0.1 CI fix -> A security-controls M2 -> B security-assurance M3 Action -> C wild OpenAPI benchmark)
next: `.venv/bin/python -m pytest tests/forge/test_host_agent_mode.py -q`
depends: [security-controls, secure-design-patterns, security-assurance]
---

# Session Checkpoint — MCP Server Forge `v2.0.0` & 4-Repo Assurance Ecosystem

**Status:** IN PROGRESS — needs resume after `/compact` to execute the user-approved queue **`1 -> A -> B -> C`** below.

**User Instruction (Verbatim):**
> `"1, then A,B,C, but first, let's checkpoint and compact"`

---

## Done (with evidence)

### 1. `bsommers/forge` (`/Users/bill/src/swe/forge` — Active Workspace, [`v2.0.0`](https://github.com/bsommers/forge/releases/tag/v2.0.0))
- **Milestone `M5` (`W5.1`–`W5.2`, [Plan 03](plans/03-wild-openapi-resilience-composite-tools-and-hardened-bounds.md)):**
  - **`W5.1` (`forge/workflows.py`, `forge/ingest_openapi.py`, `forge/codegen.py`, `forge/orchestrator.py`):** Declarative `x-mcp-workflows` + `--workflows` multi-endpoint `@tool` compiler (`asyncio.gather()` fan-out waves + sequential `$steps.<id>.<path>` joins + per-step `RouteDispatchAuth`) and role-partitioned `<= 15`-tool `client_profiles` (`--toolset-budget`).
  - **`W5.2` (`forge/sandbox.py`, `scripts/validate_mcp.py`, `forge/oscal_attestation.py`):** macOS XNU Seatbelt (`sandbox-exec`) & Linux `bubblewrap` (`bwrap`) host-agent confinement (`--sandbox-policy auto|required|off`), `--fixtures-dir` Recorded Contract Fixture Replay with exact JSONPath schema-drift diagnostics, and closure of **`POAM-FORGE-W5.2`** (`NIST SC-39` -> `satisfied`, `0` open POA&Ms).
- **Local & Pages Evidence:**
  - `.venv/bin/python scripts/validate_mcp.py` -> `[PASS]` (all 5 gates locally)
  - `.venv/bin/python -m pytest -q` -> `63 passed`
  - `.venv/bin/python -m ruff check src forge respx scripts tests dashboard && .venv/bin/python -m mypy src forge respx scripts/validate_mcp.py` -> `0` issues
  - GitHub Pages workflow (`pages.yml` on `main`, run `45622271732`) -> **`✓` green**

### 2. `bsommers/security-controls` (`/Users/bill/src/swe/security-controls`, [`v1.1.0`](https://github.com/bsommers/security-controls/releases/tag/v1.1.0) @ `9fe95c6`)
- **Milestone `M1` (`RS-1`–`RS-4`, GitHub Milestone `#1` closed, GitHub Actions CI `✓` green on `main` & `v1.1.0`):**
  - **`RS-1` (`src/security_controls/full_index.py`, `scripts/spike_ingest_oscal.py`):** Compiled all **`1,189` controls & enhancements** (`322` base + `867` enhancements = `1,007` active + `182` withdrawn across `20` groups) + 4 SP 800-53B baselines from `usnistgov/oscal-content@v1.1.0` (`Rev. 5.1.1`) into `catalog/sp800-53-r5-upd1/full-index.json` (**`298.91 KiB`**, **`33.55 ms`** median compile, **`2.0–2.26 ms`** cold load, `0` mismatches vs. `core-controls.json`).
  - **`RS-2` & `RS-3` (`schema/cosis-overlay.schema.json`, `schema/oscal_profile_schema.json`, `src/security_controls/oscal.py`):** Two-layer `[NIST-DRAFT]` vs. `MCP-001..008` provenance + verbatim NIST OSCAL `1.1.2` `oscal_profile_schema.json` validation (`5 / 5` single + composite profiles passing with `0` errors) + `hypothesis` monotonicity fuzzing (`13 passed`, `mypy --strict` `0` issues).
  - **`RS-4` (`src/security_controls/assessor.py`, `docs/adr/0001-oscal-ingestion-and-attestation-boundary.md`):** Deterministic SP 800-53A Forge assessor (`100%` technical `P1` coverage; `AT-3`, `PE-3`, `PM-9`, `PS-6` quarantined as `human-attestation-required`).

### 3. `bsommers/security-assurance` (`/Users/bill/src/swe/security-assurance`, [`v1.1.0`](https://github.com/bsommers/security-assurance/releases/tag/v1.1.0) @ `ec28b92`)
- Closed **`POAM-FORGE-W5.2`** (`NIST SC-39` -> `satisfied`, **`0` open technical POA&M items**) across `oscal/*.json` and `docs/rendered/acme-incidents-SSP.md` (`7 passed`, GitHub Actions OPA + OSCAL CI **`✓` green** on `main` & `v1.1.0`).

### 4. `bsommers/secure-design-patterns` (`/Users/bill/src/swe/secure-design-patterns` @ `0232495`)
- Clean on `main`, GitHub Actions CI **`✓` green** (`11 passed`, `mypy --strict` `0` issues).

---

## Failed / blocked (with root cause)

- **Remote tag CI failure on `bsommers/forge` `v2.0.0` (`ubuntu-latest`, run `45622272315`, step `"Run 5-Gate MCP 2026-07-28 Verification Harness"`):**
  - **Root cause:** In [test_host_agent_mode.py](../tests/forge/test_host_agent_mode.py) (`test_t7_tamper_detection_aborts_and_restores_locked_files`), `invoke_host_agent` now defaults to `sandbox_policy="auto"`. Inside Antigravity's outer macOS Seatbelt sandbox, nested `sandbox-exec` returns `outer_sandbox_detected=True` (`available=False`), so `rogue_agent.py` reached the secondary SHA-256 `TamperDetectionError` layer. On `ubuntu-latest` (and bare macOS), `bwrap` / `sandbox-exec` IS `available=True`, so the **OS kernel mount (`--ro-bind`) blocks `rogue_agent.py` first** (`EROFS` / `EPERM` -> `RuntimeError: Host coding agent exited with code 1`) before `src/auth.py` can be modified to trigger `TamperDetectionError` — and potentially in `test_t8` on Linux `bwrap`, check how `bwrap` mounts `.venv` symlink target outside `workspace` if `workspace/.venv` symlinks to `REPO_ROOT/.venv` (`--ro-bind / /` covers `/home/runner/...`, while `/tmp` `tmpfs` needs careful check if `workspace` is under `/tmp`!).
  - **Exact fix queued as Step 1 below.**

---

## Bugs fixed & key gotchas learned (do not reintroduce)

1. **FastMCP 4.x `@tool` decorator return type:** `@tool(...)` in `fastmcp.tools` returns the `async def` coroutine function directly (call `await mod.tool_name(...)`, NOT `mod.tool_name.fn(...)`).
2. **NIST Metaschema ECMA-262 `\p{...}` regex escapes in `oscal_profile_schema.json`:** Official NIST OSCAL `1.1.2` JSON Schemas contain `\p{L}`, `\p{N}`, `\p{Z}`, `\P{C}` Unicode property escapes that raise `re.PatternError: bad escape \p` in Python's stdlib `re`. Keep NIST JSON Schema files byte-identical and wrap `Draft7Validator` via `jsonschema.validators.extend` with `_translate_ecma_pattern()` (see `security_controls/oscal.py`).
3. **`usnistgov/oscal-content` version tags:** `v1.1.0` = exact SP 800-53 Rev. 5 Update 1 (`5.1.1`, `1,189` controls: `322` base + `867` enhancements, `1,007` active + `182` withdrawn); `v1.2.0` = `5.1.1+u2` (`1,193` controls); `main` = `5.2.0` (`1,196` controls).
4. **Linux `bwrap` & `/tmp` workspaces (`forge/sandbox.py`):** Mounting `--tmpfs /tmp` wipes `/tmp` inside the namespace before subsequent binds; any script/state paths under `/tmp` outside `workspace` must be explicitly bound (`--ro-bind` / `--bind`) and `workspace` must be `--ro-bind`ed after `--tmpfs /tmp` followed by the 3 `:rw` target binds (`src/tools`, `tests/unit`, `README.md`).
5. **Sandbox & approval note:** Sibling repos `/Users/bill/src/swe/{security-controls,security-assurance,secure-design-patterns}` lie outside the active workspace `/Users/bill/src/swe/forge`. Prepare files inside `<appDataDir>/brain/<conversation-id>/scratch/` in Standard Sandbox Mode (`BypassSandbox: false`) first, then sync/test outside `/Users/bill/src/swe/forge` in minimal single commands (`BypassSandbox: true`, re-approved per session after reset).

---

## State that may have changed

- **Active Workspace (`/Users/bill/src/swe/forge`):** Branch `main`, clean working tree, `0` stashes, `0` background tasks or subagents.
- **Sibling Repositories:**
  - `/Users/bill/src/swe/security-controls`: `main` clean @ `9fe95c6` (`v1.1.0`; git-ignored `input/*.json` upstream NIST files cached on disk).
  - `/Users/bill/src/swe/security-assurance`: `main` clean @ `ec28b92` (`v1.1.0`).
  - `/Users/bill/src/swe/secure-design-patterns`: `main` clean @ `0232495`.

---

## Next steps (exact user-approved queue: `1 -> A -> B -> C`)

1. **Step 1 — `forge v2.0.1` (`ubuntu-latest` CI Green Fix):**
   - Inspect/reproduce Linux `bwrap` behavior in `tests/forge/test_host_agent_mode.py` (`test_t7` & `test_t8`) and `forge/sandbox.py`:
     - In `test_t7`, test the secondary SHA-256 `TamperDetectionError` layer explicitly with `sandbox_policy="off"`, AND test `sandbox_policy="auto"` asserting `(TamperDetectionError, RuntimeError)` while `src/auth.py` stays byte-identical.
     - Ensure `build_linux_bwrap_command` preserves parent temp directory readability/writability for `tmp_path` helper args in `test_t8`.
   - Bump `pyproject.toml` + `golden-template/pyproject.toml` + `CHANGELOG.md` to `2.0.1`, run `.venv/bin/python scripts/validate_mcp.py && .venv/bin/python -m pytest -q`, commit, tag `v2.0.1`, push, publish release `v2.0.1`, and verify `gh run list --repo bsommers/forge` turns **`✓` green**!
2. **Step A — `security-controls` Milestone `M2` (`v1.2.0`): Official NIST Component & SAR Schema Gate:**
   - Fetch official NIST OSCAL `1.1.2` `oscal_component_schema.json` and `oscal_assessment-results_schema.json` into `/Users/bill/src/swe/security-controls/schema/`.
   - Extend `security_controls.oscal` and `security_controls.assessor` to emit schema-verified OSCAL `1.1.2` `component-definition` and `assessment-results` JSON documents over the 1,189-control `full-index.json`, validate against verbatim NIST v1.1.2 schemas (`0` errors), update `ROADMAP.md` (`M2` -> `done`), tag & release `v1.2.0`, and verify CI green.
3. **Step B — `security-controls` / `security-assurance` Milestone `M3` (`v1.3.0` / `v1.2.0`): Reusable CI ATO Gate Action:**
   - Build a SHA-pinned composite GitHub Action (`action.yml` in `bsommers/security-assurance`) + cross-repo CLI gate consuming `forge` + `security-controls` + `secure-design-patterns` to run 5-gate verification, `opa eval` (`manifest_guard`, `ssp_gate`), and upload OSCAL `1.1.2` SSP/SAR/POA&M bundles; wire a self-test job in `.github/workflows/ci.yml`, update `security-controls` `ROADMAP.md` (`M3` -> `done`), tag & release, and verify CI green.
4. **Step C — Real-World Wild OpenAPI Benchmark (`forge` `v2.1.0` / `spec/` & `tests/forge/`):**
   - Vendor or slice a gnarled real-world 60–100+ operation OpenAPI 3.x spec (cyclic `$ref`s, `allOf`/`oneOf`, mixed auth schemes, multi-tag shards + composite `forge-workflows.yaml`), run `forge.orchestrator --auto-split-tags --workflows ... --emit-oscal --local`, benchmark `client_profiles` (`<= 15` tools/profile) + zero-POA&M OSCAL `1.1.2` attestation end-to-end, document empirical benchmark metrics, commit, push, and verify all 4 repos' CI runs are **`✓` green**.
