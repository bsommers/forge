# Plan 03 — Wild OpenAPI Resilience, Dual-Axis Payload Bounding, Composite Workflows & Kernel Sandboxing (M4 & M5)

- **Status:** `open`
- **Target Milestones:** `M4 (v1.4.0)` & `M5 (v2.0.0)` in [`../ROADMAP.md`](../ROADMAP.md)
- **Companion Security Catalog:** [`../SECURE_DESIGN_PATTERNS.md`](../SECURE_DESIGN_PATTERNS.md) (`MCP-001`–`MCP-008`) & [`bsommers/secure-design-patterns`](https://github.com/bsommers/secure-design-patterns)
- **Recommended First Task:** Task 1 (`W4.1` Cycle-Safe & Path-Confined `$ref` Resolver in `forge/ingest_openapi.py`)

[← Back to Roadmap](../ROADMAP.md) · [Secure Design Patterns](../SECURE_DESIGN_PATTERNS.md) · [← Back to Project README](../../README.md)

---

## 1. Goal & Skeptical Diagnosis

Eliminate the six structural failure modes where **MCP Server Forge (`v1.3.0`)** breaks down against messy production OpenAPI 3.x specifications, uncurated enterprise REST surfaces, and adversarial or high-cardinality upstream responses:

| # | Skeptical Failure Mode (`v1.3.0` Reality) | Root Cause Location | Mitigating Pattern | Target |
|---|-------------------------------------------|---------------------|--------------------|:------:|
| **F1** | **Recursive & Multi-File OpenAPI `$ref` Crashes** — Valid cyclic graphs (`User.manager -> User`, `Comment.replies -> Comment[]`) hit `depth > 25` and abort Stage 1; split relative specs (`./common.yaml#/Error`) are rejected alongside `http://` SSRF URIs. | `forge/ingest_openapi.py` (`_resolve_local_refs`) | **`MCP-004`** Cycle-Safe & Path-Confined Schema Normalization | **M4 (`W4.1`)** |
| **F2** | **Polymorphic Erasure & Heuristic Payload Blindness** — `allOf`/`oneOf`/`anyOf` schemas lack direct `properties` and degrade to `{id, status}` stubs; `projection.py` boosts audit metadata (`id`, `status`, `*_at`) ahead of nested data carriers (`rows`, `series`, `datapoints`). | `forge/projection.py` (`project_response_schema`, `score_field`) | **`MCP-004`** Polymorphic Merge & Data-Carrier Priority | **M4 (`W4.2`)** |
| **F3** | **Lossy `requestBody` Scalar Coercion** — `codegen.py` maps `POST`/`PUT` `number`, `array` (`list[str]`), and nested `object` request fields to `str`, causing `422 Unprocessable Entity` against strict upstream JSON APIs. | `forge/codegen.py` (`_param_annotation`) | **`MCP-004` / `MCP-007`** Fidelity-Preserving Input Models | **M4 (`W4.3`)** |
| **F4** | **High-Cardinality Short-String Budget Bypass** — `ForgeResponseLimitingMiddleware` only truncates individual strings `>= 16` bytes; a 3,000-element array of 10-byte IDs (`~150 KiB`) sails past `max_response_bytes = 32,768` untouched. | `src/server.py` & `golden-template/src/server.py` | **`MCP-003`** Dual-Axis Structured Payload Bounding | **M4 (`W4.4`)** |
| **F5** | **"1 Endpoint = 1 Chatty Tool" & Cross-Shard Context Bloat** — Wrapping raw CRUD forces 6–10 sequential LLM round-trips for a single triage question, and mounting 5 `--auto-split-tags` shards simultaneously re-exposes 60+ tools in one client context. | `forge/ingest_openapi.py` & `forge/codegen.py` | **`MCP-005`** Composite Intent Workflows & Active Toolset Budgets | **M5 (`W5.1`)** |
| **F6** | **AST Lint Mistaken for OS Isolation & Synthetic Mock Drift** — `validate_mcp.py` AST rules are static lint checks (not kernel containment in host `--execution-mode agent`), and generated `respx` mocks mirror the spec even when production APIs drift. | `forge/orchestrator.py` & `scripts/validate_mcp.py` | **`MCP-008`** Kernel Sandboxing & Recorded Contract Replay | **M5 (`W5.2`)** |

---

## 2. Non-Goals

- **Dynamic Upstream Auth Forwarding:** Forge will never forward MCP client `Authorization` headers upstream (`MCP-001` Token Passthrough Prohibition remains absolute).
- **Remote Network `$ref` Fetching:** Stage 1 will support path-confined local relative file `$ref`s (`./schemas/problem.yaml#/Problem`), **never** `http://` or `https://` network fetches (preserving offline determinism and SSRF immunity).
- **Unbounded Arbitrary Code Generation in Composite Workflows:** Declarative `x-mcp-workflows` steps compile strictly to `request_json` fan-out/join graphs over `ApiClient`, never `eval()` or unconstrained Python scripts.

---

## 3. Contracts & Interfaces

### 3.1 Cycle-Safe & Path-Confined `$ref` Resolution (`W4.1` — `forge/ingest_openapi.py`)

```python
def resolve_schema_refs(
    node: Any,
    root_doc: dict[str, Any],
    *,
    spec_root_dir: Path,
    current_doc_path: Path,
    ancestor_refs: frozenset[str] = frozenset(),
    doc_cache: dict[Path, dict[str, Any]] | None = None,
) -> Any:
    """Resolve internal '#/...' and path-confined relative file '$ref' pointers safely.

    Security & Termination Contracts (Pattern MCP-004):
    1. Any '$ref' containing a URI scheme ('http://', 'https://', 'file://') raises SpecNormalizationError (CWE-918 SSRF).
    2. Any relative file path resolving outside 'spec_root_dir.resolve()' raises SpecNormalizationError (CWE-22 Path Traversal).
    3. When canonical_ref ('<rel_file>#/<json_pointer>') is already in 'ancestor_refs', break the cycle deterministically
       by returning '{"type": "object", "properties": {"id": {"type": "string"}}, "x-mcp-cycle-broken": True}' instead of recursing.
    """
```

### 3.2 Polymorphic Merge & Data-Carrier Ranking (`W4.2` — `forge/projection.py`)

```python
def flatten_composed_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Normalize OpenAPI 3.x allOf / oneOf / anyOf / nullable schemas before field ranking.

    Contracts:
    - 'allOf': Deep-merge 'properties' in declaration order and union 'required' sets.
    - 'oneOf' / 'anyOf' (2-branch nullable '[T, {"type": "null"}]'): Unwrap to T with 'nullable=True'.
    - 'oneOf' / 'anyOf' (multi-variant objects with optional 'discriminator'): Emit merged common + discriminator
      summary properties (capped by 'max_fields') rather than falling back to empty properties.
    """
```

- **Data-Carrier Priority Boost (`score_field`):** Fields named `rows`, `columns`, `series`, `datapoints`, `entries`, `events`, `line_items`, `findings`, or `metrics` (or `array` properties whose items carry typed scalar/object schemas) receive `+75` priority score (above `+60` audit timestamps `*_at`), ensuring nested tabular/time-series payloads are never dropped in favor of boilerplate metadata.

### 3.3 Rich `requestBody` Type Synthesis (`W4.3` — `forge/ingest_openapi.py` & `forge/codegen.py`)

Extend parameter manifest entries with recursive JSON Schema subset metadata for body properties:
- `type: "number"` -> `float` (`Annotated[float, Field(...)]`)
- `type: "string"` + `enum: [...]` (`<= 12` literals) -> `Literal[...]`
- `type: "array"` + `items` -> `list[str] | list[int] | list[float] | list[ <NestedInputModel> ]` (bounded with `max_length=100`)
- `type: "object"` + `properties` -> generated `<ToolPascal><FieldPascal>Input(BaseModel)` with `extra="forbid"`

### 3.4 Dual-Axis `ForgeResponseLimitingMiddleware` (`W4.4` — `src/server.py` & `golden-template/src/server.py`)

```python
class ForgeResponseLimitingMiddleware(Middleware):
    """Enforce max_size across BOTH collection cardinality and string byte length while keeping outputSchema intact."""

    max_size: int = 32_768
    truncation_suffix: str = "... [truncated]"
```

**Two-Pass Algorithm (Pattern `MCP-003`):**
1. **Pass 1 — Collection Cardinality Slicing (Schema-Valid):** If `len(serialized_bytes) > max_size` and `structured_content` contains `list` values (top-level envelope `items` or nested `list` fields with `len > 1`), binary-search or proportionally slice list lengths down (`items[:k]`, minimum `1` item when non-empty) so `outputSchema` array item types (`list[IncidentItem]`, `list[int]`, `list[str]`) remain 100% valid without corrupting non-string elements. If the model declares `truncated: bool` or `next_cursor: str | None`, set `truncated = True` if present in schema.
2. **Pass 2 — Recursive String Byte Shrinking:** If still `> max_size`, shrink individual strings (`>= 16` UTF-8 bytes) proportionally as in `v1.3.0`.
3. **Pass 3 — Hard Fallback Guard:** If an irreducible non-string scalar grid still exceeds `max_size`, raise `ToolError("Upstream response exceeded 32768-byte context safety budget after list/string bounding; narrow query filters or limit.")` rather than emitting unbounded context or invalid `structuredContent`.

### 3.5 Composite Workflow Tools & Active Toolset Profiles (`W5.1` — `forge/workflows.py` & `forge/orchestrator.py`)

```yaml
# Optional sidecar: forge-workflows.yaml (or OpenAPI root 'x-mcp-workflows')
workflows:
  - name: triage_incident
    title: Triage Incident Context
    description: Fetch incident details, recent timeline events, and active on-call responder in one call.
    readOnlyHint: true
    steps:
      - id: incident
        operationId: getIncident
      - id: timeline
        operationId: listIncidentTimeline
        params:
          incident_id: "$steps.incident.id"
          limit: 10
    project:
      id: "$steps.incident.id"
      title: "$steps.incident.title"
      status: "$steps.incident.status"
      commander: "$steps.incident.commander.name"
      recent_events: "$steps.timeline.items"
```

- Compiles into a single stateless `@tool` using `asyncio.gather` where steps have independent inputs and sequential awaits where `$steps.<prev>` data dependencies exist.
- Adds `--toolset-budget <N>` (default `15`) to `run_sharded_forge_pipeline` so `forge-suite-artifacts.json` groups shards into named **Client Profiles** (`incident-triage`, `billing-readonly`, `admin-ops`), each strictly `<= 15` active tools rather than dumping 60+ tools into a single `mcpServers` block.

### 3.6 Kernel Host Sandbox & Contract Replay (`W5.2` — `forge/sandbox.py` & `tests/contract/`)

- **`forge/sandbox.py`:** Wraps host `--execution-mode agent` subprocess execution in OS-native kernel isolation when Docker is unavailable:
  - **macOS:** `sandbox-exec -p <seatbelt_profile>` denying `(deny file-write*)` everywhere except `<workspace>/src/tools`, `<workspace>/tests/unit`, `<workspace>/README.md`, and `/tmp`, while denying unintended host credential reads (`~/.ssh`, `~/.aws`, `~/.config/gh`).
  - **Linux:** `bwrap --ro-bind / / --bind <workspace>/src/tools ... --unshare-net` (when offline agent or replay fixture is used).
- **Contract Fixture Replay (`--fixtures-dir`):** Validates generated Pydantic `outputSchema` models and projections against captured anonymized production JSON responses (or OpenAPI `components.examples` / `content.application/json.examples`) during Gate 4 so spec-vs-reality drift fails at build time.

---

## 4. Exhaustive Pre-Build Test Matrix

| Case ID | Tier | Scenario | Expected Outcome |
|---------|------|----------|------------------|
| **M4-T1** | `unit` | Self-referential `User.manager -> #/components/schemas/User` & mutual `Node <-> Edge` `$ref` cycles | `ingest_openapi` terminates in `< 50ms`, marks cycle stub `{"id": str}`, zero `RecursionError` or depth failure |
| **M4-T2** | `security` | Relative `$ref: "../outside.yaml#/Secret"` and `$ref: "https://evil.example/s.yaml"` | Both rejected with `SpecNormalizationError`; confined `./common/pagination.yaml#/CursorPage` succeeds |
| **M4-T3** | `unit` | `allOf` (`BaseResource` + `MetricSeries` with `datapoints: array`) & `oneOf` nullable union | Merged schema retains `id`, `name`, `datapoints`; `datapoints` ranks in top projected fields |
| **M4-T4** | `integration` | `POST /alerts` with `threshold: number`, `tags: list[str]`, `routing: {team_id: str, escalate: bool}` | `--local` forged tool emits typed `float`, `list[str]`, and `CreateAlertRoutingInput(BaseModel)` passing `mypy --strict` |
| **M4-T5** | `unit` / `torture` | Tool returns `items` with `3,000` short 10-byte IDs (`~150 KiB` JSON, zero strings `>= 16` bytes) | `ForgeResponseLimitingMiddleware` slices `items` cardinality so serialized payload `<= 32,768` bytes while validating against `outputSchema` |
| **M5-T1** | `integration` | `forge-workflows.yaml` 3-endpoint `triage_incident` join (`GET /incidents/{id}` + `timeline` + `oncall`) | Single MCP tool call executes pooled upstream requests (`asyncio.gather` on fan-out) and returns unified Pydantic model |
| **M5-T2** | `unit` | 45-endpoint spec with `--auto-split-tags --toolset-budget 15` | Emits partitioned `client_profiles` in `forge-suite-artifacts.json` where every profile mounts `<= 15` total tools |
| **M5-T3** | `security` | Host agent attempts write to `src/auth.py` under `forge/sandbox.py` OS wrapper + SHA-256 guard | Kernel sandbox blocks write (`EPERM`) *and* `LockedWorkspaceDigest` stands as secondary defense-in-depth |
| **M5-T4** | `contract` | Recorded upstream JSON fixture contains undocumented `null` on spec-required scalar field | Contract replay flags schema drift with exact JSONPath diagnostic before deployment |

---

## 5. Dependency-Ordered Implementation Tasks

### Milestone M4 (`v1.4.0` — Wild OpenAPI & Payload Bounding)
1. **Task 1 (`W4.1`):** Replace depth-counter `_resolve_local_refs` in `forge/ingest_openapi.py` with `ancestor_refs` cycle-breaking + `spec_root_dir.resolve()` confined relative file `$ref` loading (`tests/forge/test_cyclic_and_relative_refs.py`).
2. **Task 2 (`W4.2`):** Add `flatten_composed_schema()` (`allOf`/`oneOf`/`anyOf`) and data-carrier array boosting in `forge/projection.py` (`tests/forge/test_polymorphic_projection.py`).
3. **Task 3 (`W4.3`):** Upgrade `forge/ingest_openapi.py` body property extraction and `forge/codegen.py` input model synthesis for `float`, `Literal`, `list[T]`, and nested `BaseModel` inputs (`tests/forge/test_complex_request_body.py`).
4. **Task 4 (`W4.4`):** Upgrade `ForgeResponseLimitingMiddleware` in both `src/server.py` and `golden-template/src/server.py` with Pass 1 collection cardinality slicing + Pass 3 hard budget fallback (`tests/unit/test_response_bounding.py`).

### Milestone M5 (`v2.0.0` — Composite Intent Workflows & Kernel Sandboxing)
5. **Task 5 (`W5.1`):** Implement `forge/workflows.py` (`x-mcp-workflows` / `forge-workflows.yaml` multi-call compiler) and active `client_profiles` budgeting (`<= 15` tools/profile) in `forge/orchestrator.py`.
6. **Task 6 (`W5.2`):** Implement `forge/sandbox.py` (macOS `sandbox-exec` / Linux `bwrap` profiles) and `--fixtures-dir` recorded payload replay in `scripts/validate_mcp.py`.
