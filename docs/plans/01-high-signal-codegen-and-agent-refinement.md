# Plan 01 — High-Signal Schema Projection & Host-Agent Semantic Refinement (M1 & M2)

- **Status:** `open`
- **Target Milestones:** `M1 (v1.1.0)` and `M2 (v1.2.0)` in [`../ROADMAP.md`](../ROADMAP.md)
- **Recommended First Task:** Task 1 (`forge/ingest_openapi.py` `2xx` response schema & `x-mcp-fields` extraction)

[← Back to Roadmap](../ROADMAP.md) · [← Back to Project README](../../README.md)

---

## 1. Goal

Close the quality gap between instant `--local` deterministic code generation (`forge/codegen.py`) and hand/agent-curated domain tools (`src/tools/*.py`). After **M1**, `--local` mode deterministically projects bloated 100-field OpenAPI `2xx` schemas down to a concise, strictly-typed 6–8 field Pydantic `BaseModel` (plus typed `items` + `next_cursor` envelopes for list endpoints) with **zero** raw `data: dict[str, Any]` passthrough. After **M2**, `--execution-mode agent` (`--agent-cmd`) lets users run a local CLI coding agent on top of M1's scaffold—without requiring Docker—while cryptographically enforcing the Golden Template's read-only security boundary via SHA-256 lock digests and the 5-gate `validate_mcp.py` self-healing loop.

---

## 2. Motivation (Measured from `v1.0.0`)

- **Observed Limitation in `v1.0.0` (`forge/codegen.py:167-178, 256-263`):**
  1. `forge/ingest_openapi.py` extracts `parameters` and `request_body_schema`, but discards `op["responses"]["200" | "201"]`.
  2. Consequently, `forge/codegen.py` emits a static 5-field model (`id`, `title`, `status`, `severity`, `data: dict[str, Any]`) and sets `data=payload`.
  3. On a realistic 100-field enterprise REST payload (~`14 KiB` per item, or `350 KiB` for 25 items), `data=payload` floods the LLM context window with low-signal audit/internal fields until `ForgeResponseLimitingMiddleware` hard-truncates strings at `32,768` bytes—whereas hand/agent-tuned tools in `src/tools/*.py` (`get_incident.py`, `list_incidents.py`) project **only 4–6 high-signal fields** (~`220 bytes` per item, a **>95% token reduction**).
- **Operational Friction in Stage 3:** Getting semantic field flattening (e.g., `commander.name -> commander: str | None`) and domain enum validation currently requires building and running a Docker container (`mcp-forge-agent:latest`) or editing `src/tools/*.py` manually after `--local`.

---

## 3. Current → Proposed Architecture

```
CURRENT (v1.0.0 --local):
  OpenAPI 3.x ──► ingest_openapi.py (drops responses) ──► codegen.py
                                                           └── emits {id, title, status, severity, data: dict[str, Any]}

PROPOSED (M1 v1.1.0 + M2 v1.2.0):
  OpenAPI 3.x ──► ingest_openapi.py
                    └── emits response_schema + x_mcp_fields
                          │
                          ▼
                  projection.py (Deterministic Ranker, --max-output-fields=8)
                    ├── Object endpoint ──► 6..8 top-ranked typed scalar/flattened fields (no raw data dict)
                    └── List endpoint   ──► items: list[<ItemSummary>] + next_cursor + total_returned
                          │
                          ├── [--execution-mode local] ──► validate_mcp.py (5 Gates) ──► DONE
                          │
                          └── [--execution-mode agent --agent-cmd "..."]
                                ├── 1. Snapshot SHA-256 + chmod 0444 on locked Golden Template paths
                                ├── 2. Run host CLI agent on src/tools/, tests/unit/, README.md
                                ├── 3. Verify SHA-256 lock digests (abort on tamper)
                                └── 4. Run 3-iteration validate_mcp.py self-healing loop ──► DONE
```

---

## 4. Contracts & Interfaces

### 4.1 `forge-manifest.json` Tool Entry Additions (`forge/ingest_openapi.py`)

Each item in `manifest["tools"]` adds two optional, backward-compatible keys (all internal `$ref`s already resolved by `_resolve_local_refs`):

```python
class ManifestToolSpec(TypedDict, total=False):
    name: str
    title: str
    method: str
    path: str
    description: str
    annotations: dict[str, bool]
    required_params: list[str]
    parameters: list[dict[str, Any]]
    request_body_schema: dict[str, Any] | None
    # NEW in M1:
    response_schema: dict[str, Any] | None      # Extracted from first 200/201/202 application/json response
    x_mcp_fields: list[str] | None              # Optional OpenAPI extension `x-mcp-fields` explicit allowlist
    max_output_fields: int                      # Default 8 (configurable via --max-output-fields)
```

### 4.2 Deterministic Field Signal Ranker (`forge/projection.py` — New Module)

```python
from dataclasses import dataclass
from typing import Literal

@dataclass(frozen=True)
class ProjectedField:
    py_name: str               # Valid snake_case Python identifier (e.g., "commander_name")
    source_path: tuple[str, ...]  # Extraction path in upstream JSON (e.g., ("commander", "name"))
    py_type: str               # "str" | "int" | "float" | "bool" | "str | None" | "int | None" | ...
    default_repr: str          # e.g., '""', "None", "0", "False"
    description: str           # Sanitized <= 120 char field description

@dataclass(frozen=True)
class ResponseProjection:
    kind: Literal["object", "collection", "status_ack"]
    fields: tuple[ProjectedField, ...]          # Capped at 1 <= len(fields) <= max_output_fields
    collection_key: str | None = None           # e.g., "incidents", "invoices", "items", or None for root array
    cursor_key: str | None = None               # e.g., "next_cursor", "next_page_token"

def project_response_schema(
    response_schema: dict[str, Any] | None,
    *,
    method: str,
    x_mcp_fields: list[str] | None = None,
    max_output_fields: int = 8,
) -> ResponseProjection: ...
```

**Deterministic Scoring Rules (`project_response_schema`):**
1. **Explicit Override First**: If `x_mcp_fields` is provided on the OpenAPI operation (supports dotted paths like `"commander.name"`), select those exact fields in declared order up to `max_output_fields`.
2. **Low-Signal Blocklist (Excluded Automatically)**: Drop fields matching `(raw_html|html_body|stack_trace|debug_blob|avatar_b64|binary|_*|metadata_raw|audit_trail_full)` or unbounded nested `object`/`array` blobs lacking scalar leaf summaries.
3. **Priority Tier Scoring** (ties broken alphabetically for 100% determinism):
   - **Tier 1 (`+100`) — Identity**: `id`, `*_id`, `uid`, `key`, `slug`, `number`
   - **Tier 2 (`+85`) — Human Label**: `title`, `name`, `summary`, `subject`, `display_name`
   - **Tier 3 (`+75`) — Operational State**: `status`, `state`, `phase`, `severity`, `priority`, `outcome`, `deleted`
   - **Tier 4 (`+60`) — Ownership & Quantitative Signal**: `commander.name`, `assignee.name`, `owner`, `service`, `amount`, `total`, `currency`, `count`
   - **Tier 5 (`+45`) — Temporal**: `updated_at`, `created_at`, `resolved_at`, `due_date`
   - **Tier 6 (`+20`) — Remaining required scalar fields**, then remaining optional scalar fields (`string`, `integer`, `number`, `boolean`).
4. **1-Level Nested Object Flattening**: Nested objects exposing `.name`, `.id`, or `.email` (such as `commander: {id, name, avatar_url, ...}`) flatten cleanly to `commander_name: str | None` without pulling in the full nested dictionary.
5. **Collection & Pagination Detection**: If `response_schema` is `type: "array"` or an object containing a primary array property (`items`, `results`, `data`, or `<noun>s`) alongside optional `next_cursor`/`cursor`/`next_page_token`, emit `kind="collection"` generating both `<Tool>Item(BaseModel)` (`<= max_output_fields` fields) and `<Tool>Response(BaseModel)` (`items: list[<Tool>Item]`, `next_cursor: str | None = None`, `total_returned: int`).
6. **Legacy Manifest Fallback**: When `response_schema` is `None` or defines zero properties (e.g., `204 No Content` or `DELETE` ack), emit `kind="status_ack"` (`id: str`, `status: str`, `deleted: bool` for `DELETE`).

### 4.3 Host-Agent Execution & Cryptographic Lock Guard (`forge/orchestrator.py` — M2)

```python
LOCKED_RELATIVE_PATHS: tuple[str, ...] = (
    "pyproject.toml",
    "Dockerfile",
    "forge-manifest.json",
    "respx",
    "src/auth.py",
    "src/deps.py",
    "src/server.py",
    "tests/contract",
    "scripts/validate_mcp.py",
)

class TamperDetectionError(RuntimeError):
    """Raised when a host-mode coding agent modifies or deletes a locked Golden Template path."""

def snapshot_locked_digests(workspace_dir: Path) -> dict[str, str]: ...
def enforce_and_verify_locked_digests(workspace_dir: Path, baseline: dict[str, str]) -> None: ...
def invoke_host_agent(workspace_dir: Path, agent_cmd: str, prompt_text: str, timeout_sec: float = 300.0) -> None: ...
```

**CLI Surface Uniformity (`forge.ingest_openapi` & `forge.orchestrator`):**
- `forge.ingest_openapi`: adds `--max-output-fields INT` (default `8`, bounds `1..20`).
- `forge.orchestrator`:
  - adds `--max-output-fields INT` (default `8`, bounds `1..20`)
  - expands `--execution-mode` choices to `("docker", "local", "agent")`
  - adds `--agent-cmd STR` (command template receiving `{prompt_file}` and `{workspace}`, e.g. `"claude --print -p {prompt_file}"`)

---

## 5. Global Constraints

1. **Zero New Runtime Dependencies**: `forge/projection.py` and `LockedWorkspaceDigest` use Python 3.12 stdlib (`hashlib`, `stat`, `shutil`, `dataclasses`) + existing `pydantic`/`fastmcp`.
2. **100% Determinism (`engineering-for-determinism`)**: Running `forge.orchestrator --local` twice on the same OpenAPI spec must produce byte-identical `src/tools/*.py` and `tests/unit/test_tools.py`.
3. **AST & Strict Mypy Compliance**: Every synthesized tool module from `codegen.py` must pass `mypy --strict`, `ruff check`, `audit_tools_ast()`, and achieve `>= 85%` branch coverage out of the box.
4. **Backward Compatibility**: Existing `forge-manifest.json` files without `response_schema` continue to synthesize and pass all 39 existing tests without modification.

---

## 6. Exhaustive Pre-Build Test Matrix

| Case ID | Tier | Scenario | Input | Expected Outcome |
|---------|------|----------|-------|------------------|
| **T1** | `unit` | 100-field bloated object schema | OpenAPI `200` schema with 100 mixed scalar/nested/blob properties | Projects exactly `8` deterministic top-ranked fields; `data: dict[str, Any]` absent |
| **T2** | `unit` | `x-mcp-fields` explicit allowlist | Operation with `x-mcp-fields: ["id", "commander.name", "severity"]` | Emits exact 3 fields (`id`, `commander_name`, `severity`) in order |
| **T3** | `unit` | Paginated collection schema | `200` schema `{incidents: [{...30 fields...}], next_cursor: string}` | Emits `ListIncidentsItem` (`<= 8` fields) + `ListIncidentsResponse` (`items`, `next_cursor`, `total_returned`) handling both dict-envelope and raw-list upstream payloads |
| **T4** | `unit` | `204 No Content` / `DELETE` endpoint | `DELETE /incidents/{id}` with empty `204` response | Emits concise `status_ack` model (`id`, `deleted: bool`, `status`) |
| **T5** | `unit` | Low-signal & sensitive/binary field filtering | Schema with `raw_html`, `debug_blob`, `stack_trace`, `_internal` | All blocklisted fields excluded even when total fields `< max_output_fields` |
| **T6** | `integration` | End-to-end `--local` forge on 100-field spec | Synthetic 100-field OpenAPI YAML -> `run_forge_pipeline(..., execution_mode="local")` | Passes all 5 `validate_mcp.py` gates; `outputSchema` has `<= 8` properties and zero `additionalProperties` catch-all |
| **T7** | `security` | Host-agent locked-file tamper attempt | Mock `--agent-cmd` script modifies `src/auth.py` or `tests/contract/test_forge_contract.py` | Raises `TamperDetectionError`, restores Golden Template file from baseline, and never marks validation passed |
| **T8** | `integration` | Host-agent self-healing retry loop | Mock `--agent-cmd` emits syntax/type error on Attempt 1, fixes it using validator diagnostics on Attempt 2 | Iteration 1 fails Gate 2, Iteration 2 passes all 5 gates and emits `forge-release-artifacts.json` |

---

## 7. Dependency-Ordered Implementation Tasks

### Task 1: Extract `2xx` Response Schemas & `x-mcp-fields` in Stage 1 (`M1` / `W1.1`)
- **Files:** modify `forge/ingest_openapi.py`, `spec/acme-incidents.openapi.yaml`, `spec/cloud-billing.openapi.json`; test `tests/forge/test_ingest_openapi.py`
- **Produces:** `response_schema`, `x_mcp_fields`, and `--max-output-fields` in `normalize_openapi_to_manifest()`
- [ ] Write failing unit tests in `tests/forge/test_ingest_openapi.py` for `200`/`201` `application/json` schema extraction, `204` empty response handling, `x-mcp-fields` validation, and `--max-output-fields` bounds (`1..20`)
- [ ] Implement `_extract_response_schema(op)` in `forge/ingest_openapi.py` (reusing resolved local `$ref` tree)
- [ ] Verify: `.venv/bin/python -m pytest tests/forge/test_ingest_openapi.py -q && .venv/bin/python -m mypy forge`

### Task 2: Build Deterministic Field Signal Ranker & Flattener (`M1` / `W1.2`)
- **Files:** create `forge/projection.py`; test `tests/forge/test_schema_projection.py`
- **Produces:** `ProjectedField`, `ResponseProjection`, `project_response_schema()`
- [ ] Write failing unit tests `T1`–`T5` in `tests/forge/test_schema_projection.py` (100-field trimming, `x-mcp-fields`, nested `commander.name` flattening, paginated list detection, `204` ack fallback, determinism check)
- [ ] Implement `forge/projection.py` with strict typing (`mypy --strict` clean)
- [ ] Verify: `.venv/bin/python -m pytest tests/forge/test_schema_projection.py -q && .venv/bin/python -m mypy forge`

### Task 3: Upgrade `forge/codegen.py` to Synthesize Projected Models & Branch-Complete Tests (`M1` / `W1.2` + `W1.3`)
- **Files:** modify `forge/codegen.py`; test `tests/forge/test_schema_projection.py`, `tests/forge/test_orchestrator.py`
- **Produces:** Updated `render_tool_module()` and `render_unit_tests()` emitting tailored Pydantic models, nested field extractors, collection envelopes, and unit tests achieving `>= 85%` branch coverage
- [ ] Write integration test `T6` forging a 100-field OpenAPI spec via `--local` and asserting `<= 8` `outputSchema` properties + `validate_mcp.py` pass
- [ ] Update `forge/codegen.py` to consume `project_response_schema()` and remove raw `data: dict[str, Any]` passthrough when projected fields exist
- [ ] Verify: `.venv/bin/python -m pytest tests/forge/ -q && .venv/bin/python scripts/validate_mcp.py`

### Task 4: Add `--execution-mode agent` & SHA-256 Lock Guard (`M2` / `W2.1` + `W2.2`)
- **Files:** modify `forge/orchestrator.py`; create `tests/forge/test_host_agent_mode.py`
- **Produces:** `TamperDetectionError`, `snapshot_locked_digests()`, `enforce_and_verify_locked_digests()`, `invoke_host_agent()`, CLI flags `--execution-mode agent` and `--agent-cmd`
- [ ] Write failing security & retry tests `T7` and `T8` in `tests/forge/test_host_agent_mode.py`
- [ ] Implement `0444` read-only locking (restored cleanly in `finally` blocks so workspaces remain removable), SHA-256 pre/post digest verification, and `invoke_host_agent()` seeded with M1 `synthesize_workspace_code()`
- [ ] Verify: `.venv/bin/python -m pytest tests/forge/test_host_agent_mode.py -q && .venv/bin/python -m mypy forge`

### Task 5: Synchronize Living Docs, User Guide & Alignment Tests (`M1` + `M2`)
- **Files:** modify `README.md`, `docs/ARCHITECTURE.md`, `docs/HOWTO.md`, `docs/user-guide/02-forging-servers.md`, `docs/user-guide/04-cli-and-config-reference.md`, `docs/ROADMAP.md`, `CHANGELOG.md`
- **Produces:** Updated CLI flag tables, `x-mcp-fields` authoring examples, and `done` status markers on M1/M2
- [ ] Update docs and re-run `python3 -s scripts/render-graphics.py` if stage badges change
- [ ] Verify: `.venv/bin/python scripts/validate_mcp.py && .venv/bin/python -m pytest`

---

## 8. Threat & Failure Model

| Failure / Threat | Impact | Mitigation |
|------------------|--------|------------|
| Host CLI agent runs `chmod +w` on `tests/contract/test_forge_contract.py` to weaken assertions | Reward-hacked validation pass | `snapshot_locked_digests()` records SHA-256 of all locked files on the host in memory before `invoke_host_agent()` starts; any byte or file-list change raises `TamperDetectionError` |
| `chmod 0444` leaves failed output directory undeletable on subsequent re-runs | `PermissionError` during `shutil.rmtree` in `stage_workspace()` | Restore `0644`/`0755` permissions in a `try/finally` wrapper and teach `stage_workspace()` an `onerror` chmod handler before `rmtree` |
| Upstream API returns `null` or omits a projected scalar field at runtime | `ValidationError` inside generated tool | Default projected non-identity scalar extractions defensively (`str(payload.get(...) or "")` or `Optional` with `None` default) |
| Host agent command hangs indefinitely | Pipeline stalls | Enforce `subprocess.run(..., timeout=timeout_sec)` (`300s` default) and convert `TimeoutExpired` into diagnostic retry feedback |

---

## 9. Verification Plan

```bash
# Full post-build verification gate (must pass with 0 warnings/errors):
.venv/bin/python scripts/validate_mcp.py
.venv/bin/python -m ruff check src forge respx scripts tests dashboard
.venv/bin/python -m mypy src forge respx
.venv/bin/python -m pytest --cov=src/tools --cov=forge --cov-branch
```
