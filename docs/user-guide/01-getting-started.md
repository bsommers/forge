# Chapter 1 — Getting Started & Bootstrap Workflow

[← Back to User Guide](README.md) · [← Back to Project README](../../README.md)

<p align="center">
  <img src="../assets/khazad-dum-hero.png" alt="Great Forge Hall of MCP Server Forge" width="100%" />
</p>

## Table of Contents

- [Prerequisites](#prerequisites)
- [Installation Scopes](#installation-scopes)
- [Bootstrap Sequence: Sync → Verify → Run](#bootstrap-sequence-sync--verify--run)
- [Connecting an MCP Client (`mcpServers`)](#connecting-an-mcp-client-mcpservers)
- [What Next?](#what-next)

---

## Prerequisites

| Tool | Minimum Version | Required For |
|------|-----------------|--------------|
| **Python** | `3.12+` | FastMCP 4.x runtime, Forge normalizer, and 5-gate validator |
| **`uv`** | `0.5+` | Deterministic virtualenv & package management |
| **Docker** | `24.0+` *(optional)* | Required only for `--execution-mode docker`; `--local` runs natively without Docker |

---

## Installation Scopes

### 1. Project Workspace Setup (Recommended)

```bash
git clone https://github.com/bsommers/forge.git
cd forge
uv sync
```

### 2. Offline / Air-Gapped Cache Sync

If working inside a network-restricted environment with a pre-warmed `uv` cache:

```bash
uv sync --offline
```

### 3. Global CLI Tool Install (`uv tool`)

To expose `mcp-server` on your user `$PATH` (`~/.local/bin`):

```bash
uv tool install --editable .
```

---

## Bootstrap Sequence: Sync → Verify → Run

### Step 1: Run the 5-Gate Verification Harness

Before running or modifying tools, verify the workspace passes every MCP `2026-07-28` gate:

```bash
.venv/bin/python scripts/validate_mcp.py
```

Expected output:

```text
==> [Gate] Ruff Lint & Security: .../python -m ruff check src tests
==> [Gate] Mypy Strict Typecheck: .../python -m mypy src
==> [Gate] AST Security, SEP-2577 Deprecation & Docstring Audit
==> [Gate] Pytest Contract + Unit & Branch Coverage: .../python -m pytest --cov=src/tools --cov-branch --cov-fail-under=85
==> [Gate] Subprocess STDIO Discovery & Frame Hygiene (MCP 2026-07-28)

[PASS] All MCP Server Forge (2026-07-28) verification gates succeeded.
```

### Step 2: Start the Reference `acme-incidents` Server

```bash
export ACME_API_TOKEN="demo-secret-token"
export ACME_BASE_URL="https://api.acme.internal/v1"

# Default STDIO mode (newline-delimited UTF-8 JSON-RPC)
.venv/bin/mcp-server

# Or sessionless Streamable HTTP mode on port 8000
MCP_TRANSPORT=http PORT=8000 .venv/bin/mcp-server
```

---

## Connecting an MCP Client (`mcpServers`)

Add the server to your Claude Desktop, Antigravity (`mcp_config.json`), or Cursor MCP settings:

```json
{
  "mcpServers": {
    "acme-incidents": {
      "command": "uv",
      "args": ["--directory", "/path/to/forge", "run", "mcp-server"],
      "env": {
        "ACME_BASE_URL": "https://api.acme.internal/v1",
        "ACME_API_TOKEN": "${ACME_API_TOKEN}"
      }
    }
  }
}
```

---

## What Next?

- Forge a brand-new server from OpenAPI in **[Chapter 2 — Forging Servers from OpenAPI 3.x](02-forging-servers.md)**.
- Write custom stateless tools in **[Chapter 3 — Authoring MCP `2026-07-28` Tools & Tests](03-mcp-2026-07-28-authoring.md)**.
