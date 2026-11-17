# MCP Server Forge User Guide

[← Back to Project README](../../README.md) · [Documentation Hub](../README.md) · [Interactive Showcase](../index.html)

<p align="center">
  <img src="../assets/logo.svg" alt="MCP Server Forge Banner" width="100%" />
</p>

Welcome to the **MCP Server Forge (`2026-07-28`) User Guide**. This five-chapter manual covers installation, forging new MCP servers from OpenAPI 3.x specs, authoring stateless FastMCP 4.x tools, complete CLI and manifest references, and troubleshooting.

---

## Table of Contents

1. **[Chapter 1 — Getting Started & Bootstrap Workflow](01-getting-started.md)**
   - Prerequisites, repository setup (`uv sync`), the `init -> verify -> run` sequence, and running the reference `acme-incidents` server over `stdio` and Streamable HTTP.
2. **[Chapter 2 — Forging Servers from OpenAPI 3.x](02-forging-servers.md)**
   - Stage 1 normalization, `$ref` SSRF protection, `--tag-filter` slicing (`<= 15` tools), local deterministic mode (`--local`) vs. hardened Docker mode, and Stage 5 AppSec governance artifacts.
3. **[Chapter 3 — Authoring MCP `2026-07-28` Tools & Tests](03-mcp-2026-07-28-authoring.md)**
   - Stateless `SEP-2575` rules, `Depends(get_http_client)`, typed Pydantic `2020-12` `outputSchema`, `ToolAnnotations`, RFC 9110 `x-mcp-header` rules, AST security gates, and `@respx.mock` testing.
4. **[Chapter 4 — CLI, Manifest & Environment Reference](04-cli-and-config-reference.md)**
   - Complete flag tables for `forge.ingest_openapi`, `forge.orchestrator`, `scripts/validate_mcp.py`, and `dashboard/telemetry.py`, plus `forge-manifest.json` schema, environment variables, and exit codes.
5. **[Chapter 5 — Troubleshooting & FAQ](05-troubleshooting-and-faq.md)**
   - Symptom-to-fix playbook for common schema, auth, AST audit, `x-mcp-header`, and Docker sandboxing errors.

---

## Visual Overview of the Five Forge Chambers

<p align="center">
  <img src="../assets/khazad-dum-pipeline.png" alt="The Five Forge Chambers of MCP Server Forge" width="100%" />
</p>
