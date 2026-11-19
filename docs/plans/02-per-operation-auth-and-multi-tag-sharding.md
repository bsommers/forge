# Plan 02 — Per-Operation Auth Overrides, Multi-Tag Sharding & Hardened CI/Pages (M3)

- **Status:** `done`
- **Target Milestone:** `M3 (v1.3.0)` in [`../ROADMAP.md`](../ROADMAP.md) (GitHub Issues `#4` & `#5`)
- **Recommended First Task:** Task 1 (`RouteDispatchAuth` in `src/auth.py` + `golden-template/src/auth.py`)

[← Back to Roadmap](../ROADMAP.md) · [← Back to Project README](../../README.md)

---

## 1. Goal

Complete **Milestone M3 (`v1.3.0`)** by:
1. Supporting **per-operation OpenAPI `security` overrides** (Issue `#4` / `W3.1`)—including public `security: []` endpoints alongside multi-scheme `bearer`, `apiKey`, `basic`, and scoped `oauth2` endpoints—via a transparent `RouteDispatchAuth(httpx.Auth)` router that preserves the single lifespan `httpx.AsyncClient` pool, zero tool-signature changes, and the strict Token Passthrough Prohibition.
2. Adding **automated multi-tag suite sharding (`--auto-split-tags`)** (Issue `#5` / `W3.2`) so OpenAPI specifications with `> 15` operations compile in a single command into domain-scoped FastMCP server shards (`<= 15` tools each), each verified through `scripts/validate_mcp.py`, with a combined `forge-suite-artifacts.json` `mcpServers` bundle.
3. Shipping **hardened SHA-pinned GitHub Actions workflows** (`.github/workflows/ci.yml` and `.github/workflows/pages.yml`) to gate PRs/releases and publish the Khazad-dûm interactive showcase (`docs/index.html`) to GitHub Pages.

---

## 2. Motivation

- **Single-Scheme Limitation (`forge/ingest_openapi.py:68-111`):** `_extract_auth_config` previously inspected only `next(iter(securitySchemes.items()))`, ignoring root `security` and operation-level `op["security"]`. Real-world APIs frequently expose unauthenticated `/health` (`security: []`) or separate read vs. admin credentials (`BearerAuth` vs. `AdminApiKey`).
- **Manual Splitting Friction (`forge/ingest_openapi.py:221-225`):** Specs exceeding `MAX_TOOLS_PER_SERVER = 15` raised `SpecNormalizationError`, requiring operators to inspect tags manually and invoke `forge.orchestrator --tag-filter <tag>` in a loop.

---

## 3. Contracts & Interfaces

### 3.1 Multi-Scheme Auth Manifest & `RouteDispatchAuth` (`src/auth.py`)

```python
# forge-manifest.json additions (optional, 100% backward compatible):
{
  "auth": {"type": "bearer", "token_env": "ACME_API_TOKEN"},
  "auth_schemes": {
    "AdminKey": {"type": "api_key_header", "key_env": "ACME_ADMIN_KEY_API_KEY", "header_name": "X-Admin-Key"}
  },
  "tools": [
    {"name": "health_check", "method": "GET", "path": "/health", "auth_scheme": "none", ...},
    {"name": "purge_audit", "method": "DELETE", "path": "/admin/audit", "auth_scheme": "AdminKey", ...}
  ]
}
```

- `build_auth_handler(auth_cfg: dict[str, Any]) -> httpx.Auth | None`
- `class RouteDispatchAuth(httpx.Auth)`:
  - Matches `(request.method.upper(), request.url.path)` against compiled path templates from `manifest["tools"]` (accounting for any `base_url` path prefix such as `/v1`) or `request.extensions.get("forge_auth_scheme")`.
  - Routes `"none"` to zero credential injection, named schemes to `scheme_handlers[name]`, and unmatched routes to `default_auth`.

### 3.2 Automated Multi-Tag Sharding (`forge/ingest_openapi.py` & `forge/orchestrator.py`)

```python
def plan_openapi_shards(
    spec_path: Path,
    base_server_name: str,
    max_output_fields: int = 8,
) -> list[dict[str, Any]]: ...

def run_sharded_forge_pipeline(
    spec_path: Path,
    server_name: str,
    golden_template_dir: Path,
    system_prompt_path: Path,
    output_dir: Path,
    agent_image: str,
    validator_image: str,
    registry_prefix: str = "ghcr.io/org",
    execution_mode: str = "docker",
    agent_cmd: str = "",
    max_output_fields: int = 8,
) -> dict[str, Any]: ...
```

- Emits `<output_dir>/<shard_server_name>/` per shard (`1 <= len(tools) <= 15`) and `<output_dir>/forge-suite-artifacts.json` with merged `client_config["mcpServers"]` and `governance` rollup.

---

## 4. Exhaustive Pre-Build Test Matrix

| Case ID | Tier | Scenario | Expected Outcome |
|---------|------|----------|------------------|
| **M3-T1** | `unit` | Multi-scheme OpenAPI (`Bearer` default + `security: []` health + `X-Admin-Key` delete + scoped `OAuth2`) | Stage 1 emits `auth`, `auth_schemes`, and per-tool `auth_scheme` bindings; unknown scheme raises `SpecNormalizationError` |
| **M3-T2** | `unit` | `RouteDispatchAuth` runtime routing over pooled `httpx.AsyncClient` | `/health` sends no auth header; `/incidents/1` sends `Authorization: Bearer ...`; `/admin/audit` sends `X-Admin-Key: ...` |
| **M3-T3** | `integration` | End-to-end `--local` forge of multi-auth spec | Forged workspace passes all 5 `validate_mcp.py` gates and Stage 5 `mcpServers` exports both `*_API_TOKEN` and `*_ADMIN_KEY_API_KEY` |
| **M3-T4** | `unit` | `plan_openapi_shards` on 24-endpoint spec (3 tags + 18-op oversized single tag) | Splits deterministically into `<= 15`-tool shards (`-part1`, `-part2` on oversized tag) and prunes unused `auth_schemes` per shard |
| **M3-T5** | `integration` | `forge.orchestrator --auto-split-tags --local` on 20-endpoint spec | Forges & validates every shard (`scripts/validate_mcp.py` PASS on each) and writes merged `forge-suite-artifacts.json` |
| **M3-T6** | `security` | CI/Pages workflow audit | All `uses:` pinned to verified 40-char commit SHAs, top-level `permissions: contents: read`, `persist-credentials: false`, `timeout-minutes` set |

---

## 5. Dependency-Ordered Tasks

1. **Task 1:** Implement `build_auth_handler` & `RouteDispatchAuth` in `src/auth.py` + `golden-template/src/auth.py`, and update `validate_mcp.py` + `test_forge_contract.py` env-var seeding for `auth_schemes`.
2. **Task 2:** Upgrade `forge/ingest_openapi.py` for multi-scheme & per-operation `security` extraction + `plan_openapi_shards()`.
3. **Task 3:** Add `--auto-split-tags` and `run_sharded_forge_pipeline()` (plus `auth_schemes` Stage 5 env collection) in `forge/orchestrator.py`.
4. **Task 4:** Add `tests/forge/test_per_op_auth.py` and `tests/forge/test_multi_shard.py` (`M3-T1` through `M3-T6`).
5. **Task 5:** Add `.github/workflows/ci.yml` + `.github/workflows/pages.yml`, update docs/roadmap/changelog to `v1.3.0`, and verify all gates.
