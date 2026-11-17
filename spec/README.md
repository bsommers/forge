# MCP Server Forge Specifications (`spec/`)

This directory contains canonical OpenAPI 3.1.0 inputs used by Stage 1 (`forge/ingest_openapi.py`) and end-to-end orchestration (`forge/orchestrator.py`), along with pointers to the architectural specifications in [`docs/`](../docs/).

## OpenAPI 3.1.0 Input Specifications

| File | Format | Auth Scheme | Operations | Tags | Purpose |
| :--- | :--- | :--- | :--- | :--- | :--- |
| [`acme-incidents.openapi.yaml`](./acme-incidents.openapi.yaml) | YAML | HTTP Bearer (`bearerAuth`) | `get_incident`, `list_incidents`, `create_incident`, `update_incident_status`, `delete_incident` | `incidents` | Reference specification matching the Acme Incident Management MCP server (`https://api.acme.internal/v1`). |
| [`cloud-billing.openapi.json`](./cloud-billing.openapi.json) | JSON | API Key Header (`X-Billing-Key`) | `list_invoices`, `get_budget`, `upsert_budget`, `dismiss_cost_alert` | `invoices`, `budgets`, `alerts` | Multi-tag JSON specification exercising `--tag-filter`, internal `$ref` dereferencing, and `x-mcp-header` parameter mirroring. |

## Architecture & Protocol Design Documents

- [`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md) — End-to-end 5-stage system architecture and MCP `2026-07-28` (`SEP-2575`, `SEP-2567`, `SEP-2577`) compliance matrix.
- [`docs/PURPOSE.md`](../docs/PURPOSE.md) — Problem statement, threat model, goals, non-goals, and architectural trade-offs.
- [`docs/user-guide/README.md`](../docs/user-guide/README.md) — 5-chapter comprehensive User Guide.
- [`docs/python_fastmcp_golden_template_repository (1).md`](../docs/python_fastmcp_golden_template_repository%20(1).md) — Locked FastMCP v4.2 Golden Template (`src/auth.py`, `src/deps.py`, `src/server.py`, `tests/contract/test_forge_contract.py`, `scripts/validate_mcp.py`).
- [`docs/stage_1_normalizer_stage_2_5_orchestrator.md`](../docs/stage_1_normalizer_stage_2_5_orchestrator.md) — Stage 1 OpenAPI normalizer (`forge/ingest_openapi.py`) and Stages 2–5 self-healing orchestrator (`forge/orchestrator.py`).
- [`docs/coding_agent_system_prompt_mcp_2026_07_28.md`](../docs/coding_agent_system_prompt_mcp_2026_07_28.md) — Sandboxed coding agent system prompt (`forge/AGENT_SYSTEM_PROMPT.md`).
