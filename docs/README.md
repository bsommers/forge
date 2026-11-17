# MCP Server Forge — Documentation Hub

<p align="center">
  <img src="assets/logo.svg" alt="MCP Server Forge Banner" width="100%" />
</p>

Welcome to the documentation hub for **MCP Server Forge** — the OpenAPI 3.x normalizer, hardened **FastMCP 4.x** Golden Template, and 5-gate self-healing orchestrator targeting **Model Context Protocol Specification `2026-07-28`**.

> **Interactive Web Showcase & Live Build Dashboard:**
> - Browse [`docs/index.html`](index.html) (or the repository's GitHub Pages site) for an interactive tool, gate, and diagram explorer.
> - Open [`../dashboard/index.html`](../dashboard/index.html) locally to view the live multi-agent build telemetry dashboard.

---

## Documentation Map

```
docs/
├── index.html                        # Accompanying GitHub Pages interactive showcase
├── .nojekyll                         # Serves assets cleanly on GitHub Pages without Jekyll
├── README.md                         # You are here: central documentation hub
├── PURPOSE.md                        # Problem statement, threat model, goals & trade-offs
├── ARCHITECTURE.md                   # 5-stage pipeline, runtime internals, Mermaid & ASCII models
├── HOWTO.md                          # Task-oriented operational recipes & debugging guide
├── brochure.md                       # Executive stakeholder showcase with Khazad-dûm visuals
├── assets/                           # Khazad-dûm Dwarven Forge SVG + PNG graphics & illustrations
│   ├── logo.{svg,png}                # 1200x380 Forge hero banner
│   ├── icon.{svg,png}                # 512x512 horned anvil & warhammer emblem
│   ├── khazad-dum-hero.png           # Illustrated Great Forge Hall banner
│   ├── dwarven-anvil-emblem.png      # Illustrated Dwarven anvil shield crest
│   ├── khazad-dum-pipeline.png       # Illustrated 5-chamber Forge cutaway
│   ├── icons/                        # Stage vector & raster badges (ingest, template, sandbox, verify, govern)
│   └── examples/                     # 1200x620 architectural & workflow schematics (.svg + .png)
└── user-guide/                       # 5-chapter comprehensive User Guide
    ├── README.md                     # User Guide table of contents & navigation
    ├── 01-getting-started.md         # Installation, bootstrap & first verification run
    ├── 02-forging-servers.md         # OpenAPI ingestion, --tag-filter, local vs Docker forging
    ├── 03-mcp-2026-07-28-authoring.md# Authoring stateless tools, x-mcp-header & respx tests
    ├── 04-cli-and-config-reference.md# Complete CLI flags, manifest schema, env vars & exit codes
    └── 05-troubleshooting-and-faq.md # Common errors, diagnostics & fixes
```

---

## Recommended Reading Order

1. **Executive Overview:** Start with the [Product Brochure](brochure.md) and [Purpose & Threat Model](PURPOSE.md) to understand why MCP `2026-07-28` servers require locked Golden Templates and deterministic gates.
2. **Hands-On Onboarding:** Follow [User Guide — Chapter 1: Getting Started](user-guide/01-getting-started.md) or [Operational How-To Recipes](HOWTO.md) to run `scripts/validate_mcp.py` and forge your first server.
3. **Deep System Design:** Read [System Architecture](ARCHITECTURE.md) for sequence diagrams, state machines, ER schemas, and middleware internals.
4. **Authoring & Reference:** Consult [Chapter 3: Authoring MCP `2026-07-28` Tools](user-guide/03-mcp-2026-07-28-authoring.md) and [Chapter 4: CLI & Configuration Reference](user-guide/04-cli-and-config-reference.md).

---

## Foundational Specification Blueprints (Historical Reference)

The three initial specification documents that seeded this repository are preserved for provenance:

- [`coding_agent_system_prompt_mcp_2026_07_28.md`](coding_agent_system_prompt_mcp_2026_07_28.md) — Historical blueprint for [`../forge/AGENT_SYSTEM_PROMPT.md`](../forge/AGENT_SYSTEM_PROMPT.md).
- [`python_fastmcp_golden_template_repository (1).md`](python_fastmcp_golden_template_repository%20(1).md) — Historical blueprint for [`../golden-template/`](../golden-template) and [`../src/`](../src).
- [`stage_1_normalizer_stage_2_5_orchestrator.md`](stage_1_normalizer_stage_2_5_orchestrator.md) — Historical blueprint for [`../forge/ingest_openapi.py`](../forge/ingest_openapi.py) and [`../forge/orchestrator.py`](../forge/orchestrator.py).
