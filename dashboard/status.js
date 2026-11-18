// MCP Server Forge Live Telemetry Payload
// Generated at 2026-11-18T22:19:42.286803+00:00
window.__FORGE_TELEMETRY__ = {
  "timestamp": "2026-11-18T22:19:42.286803+00:00",
  "time_display": "22:19:42 UTC",
  "overall_status": "ALL SYSTEMS VERIFIED",
  "overall_progress": 100,
  "active_subagents": 0,
  "max_subagents": 4,
  "agents": {
    "core": {
      "agent": "core",
      "role": "Golden Template & Security Runtime",
      "model": "gemini-4-carbon-high",
      "model_label": "Gemini 4 Carbon",
      "effort": "High",
      "status": "completed",
      "progress": 100,
      "stage": "Stage 2 & 4 \u2014 Core Runtime & Security Gates",
      "current_task": "All 5 verification gates passed across root runtime, offline respx, and golden-template/",
      "files_owned": [
        "pyproject.toml",
        "src/auth.py",
        "src/deps.py",
        "src/server.py",
        "respx/",
        "scripts/validate_mcp.py",
        "tests/contract/test_forge_contract.py",
        "golden-template/"
      ],
      "gates": {
        "ruff": "passed",
        "mypy": "passed",
        "ast_audit": "passed",
        "pytest": "passed",
        "stdio_discover": "passed"
      },
      "model_rationale": "Maximum reasoning depth & formal verification for AST security gates & contract guarantees",
      "updated_at": "2026-11-17T03:07:45Z"
    },
    "pipeline": {
      "agent": "pipeline",
      "role": "OpenAPI Normalizer & Stage 2\u20135 Orchestrator",
      "model": "gemini-4-argon-high",
      "model_label": "Gemini 4 Argon",
      "effort": "High",
      "status": "completed",
      "progress": 100,
      "stage": "Stage 1 & Stages 2\u20135 Host Pipeline",
      "current_task": "All Stage 1 normalizer, Stages 2\u20135 orchestrator, local codegen, and pytest gates passed",
      "files_owned": [
        "forge/__init__.py",
        "forge/AGENT_SYSTEM_PROMPT.md",
        "forge/ingest_openapi.py",
        "forge/codegen.py",
        "forge/orchestrator.py",
        "spec/README.md",
        "spec/acme-incidents.openapi.yaml",
        "spec/cloud-billing.openapi.json",
        "tests/forge/"
      ],
      "gates": {
        "ruff": "passed",
        "mypy": "passed",
        "ast_audit": "passed",
        "pytest": "passed",
        "stdio_discover": "passed"
      },
      "model_rationale": "High algorithmic synthesis for AST normalizer, OpenAPI ref inlining, and self-healing repair loop",
      "updated_at": "2026-11-17T03:06:00Z"
    },
    "tools": {
      "agent": "tools",
      "role": "MCP 2026-07-28 Domain Tools & TDD Suite",
      "model": "gemini-4-hydrogen-high",
      "model_label": "Gemini 4 Hydrogen",
      "effort": "High",
      "status": "completed",
      "progress": 100,
      "stage": "Stage 3 \u2014 Domain Tools & >=85% Branch Coverage Tests",
      "current_task": "All 5 MCP 2026-07-28 domain tools, unit tests (100% branch coverage), README.md, and all verification gates passing",
      "files_owned": [
        "src/tools/get_incident.py",
        "src/tools/list_incidents.py",
        "src/tools/create_incident.py",
        "src/tools/update_incident_status.py",
        "src/tools/delete_incident.py",
        "tests/unit/__init__.py",
        "tests/unit/test_tools.py",
        "tests/unit/test_auth_and_deps.py",
        "README.md"
      ],
      "gates": {
        "ruff": "passed",
        "mypy": "passed",
        "ast_audit": "passed",
        "pytest": "passed",
        "stdio_discover": "passed"
      },
      "model_rationale": "High code generation velocity and domain schema alignment for Pydantic 2020-12 & unit suites",
      "updated_at": "2026-11-17T03:04:55Z"
    },
    "dashboard": {
      "agent": "dashboard",
      "role": "Live Mission Control Dashboard & Telemetry Collector",
      "model": "gemini-3.8-flash-medium",
      "model_label": "Gemini 3.8 Flash",
      "effort": "Medium",
      "status": "completed",
      "progress": 100,
      "stage": "Mission Control & Live Telemetry",
      "current_task": "Mission Control Dashboard live and actively streaming telemetry via background watcher",
      "files_owned": [
        "dashboard/index.html",
        "dashboard/telemetry.py",
        "dashboard/status.js",
        "dashboard/state/dashboard.json"
      ],
      "gates": {
        "ruff": "passing",
        "mypy": "passing",
        "ast_audit": "passing",
        "pytest": "passing",
        "stdio_discover": "passing"
      },
      "model_rationale": "Ultra-fast low-latency telemetry aggregation and fluid zero-dependency UI rendering",
      "updated_at": "2026-11-17T02:42:15Z"
    }
  },
  "workspace": {
    "total_files": 110,
    "total_loc": 16886,
    "by_dir": {
      ".": {
        "files": 10,
        "lines": 1070
      },
      "src": {
        "files": 10,
        "lines": 872
      },
      "forge": {
        "files": 6,
        "lines": 2159
      },
      "golden-template": {
        "files": 17,
        "lines": 1793
      },
      "spec": {
        "files": 3,
        "lines": 472
      },
      "tests": {
        "files": 12,
        "lines": 1837
      },
      "scripts": {
        "files": 2,
        "lines": 2236
      },
      "dashboard": {
        "files": 7,
        "lines": 2837
      },
      "docs": {
        "files": 43,
        "lines": 3610
      }
    },
    "by_ext": {
      ".md": {
        "files": 24,
        "lines": 3813
      },
      ".txt": {
        "files": 5,
        "lines": 549
      },
      ".toml": {
        "files": 2,
        "lines": 149
      },
      ".json": {
        "files": 8,
        "lines": 527
      },
      ".py": {
        "files": 41,
        "lines": 9339
      },
      ".typed": {
        "files": 1,
        "lines": 0
      },
      ".yaml": {
        "files": 1,
        "lines": 215
      },
      ".html": {
        "files": 2,
        "lines": 1685
      },
      ".js": {
        "files": 1,
        "lines": 609
      },
      ".png": {
        "files": 14,
        "lines": 0
      },
      ".svg": {
        "files": 11,
        "lines": 0
      }
    },
    "recent_files": [
      {
        "path": "golden-template/pyproject.toml",
        "filename": "pyproject.toml",
        "directory": "golden-template",
        "size": 1538,
        "loc": 71,
        "mtime": 1795040380.3400097,
        "time_str": "22:19:40 UTC",
        "owner": "core"
      },
      {
        "path": "pyproject.toml",
        "filename": "pyproject.toml",
        "directory": ".",
        "size": 1741,
        "loc": 78,
        "mtime": 1795040379.1637661,
        "time_str": "22:19:39 UTC",
        "owner": "core"
      },
      {
        "path": "CHANGELOG.md",
        "filename": "CHANGELOG.md",
        "directory": ".",
        "size": 6276,
        "loc": 51,
        "mtime": 1795040364.479316,
        "time_str": "22:19:24 UTC",
        "owner": "workspace"
      },
      {
        "path": "AGENTS.md",
        "filename": "AGENTS.md",
        "directory": ".",
        "size": 5473,
        "loc": 47,
        "mtime": 1795040362.8957794,
        "time_str": "22:19:22 UTC",
        "owner": "workspace"
      },
      {
        "path": "docs/ARCHITECTURE.md",
        "filename": "ARCHITECTURE.md",
        "directory": "docs",
        "size": 19102,
        "loc": 288,
        "mtime": 1795040360.777885,
        "time_str": "22:19:20 UTC",
        "owner": "workspace"
      },
      {
        "path": "docs/plans/01-high-signal-codegen-and-agent-refinement.md",
        "filename": "01-high-signal-codegen-and-agent-refinement.md",
        "directory": "docs",
        "size": 17471,
        "loc": 234,
        "mtime": 1795040359.6693454,
        "time_str": "22:19:19 UTC",
        "owner": "workspace"
      },
      {
        "path": "docs/ROADMAP.md",
        "filename": "ROADMAP.md",
        "directory": "docs",
        "size": 5949,
        "loc": 49,
        "mtime": 1795040357.9506738,
        "time_str": "22:19:17 UTC",
        "owner": "workspace"
      },
      {
        "path": "docs/user-guide/02-forging-servers.md",
        "filename": "02-forging-servers.md",
        "directory": "docs",
        "size": 6649,
        "loc": 159,
        "mtime": 1795040356.597185,
        "time_str": "22:19:16 UTC",
        "owner": "workspace"
      },
      {
        "path": "docs/user-guide/04-cli-and-config-reference.md",
        "filename": "04-cli-and-config-reference.md",
        "directory": "docs",
        "size": 7287,
        "loc": 130,
        "mtime": 1795040355.208463,
        "time_str": "22:19:15 UTC",
        "owner": "workspace"
      },
      {
        "path": ".coverage",
        "filename": ".coverage",
        "directory": ".",
        "size": 69632,
        "loc": 487,
        "mtime": 1795040332.0862916,
        "time_str": "22:18:52 UTC",
        "owner": "workspace"
      },
      {
        "path": "forge/codegen.py",
        "filename": "codegen.py",
        "directory": "forge",
        "size": 27160,
        "loc": 701,
        "mtime": 1795040286.0675747,
        "time_str": "22:18:06 UTC",
        "owner": "pipeline"
      },
      {
        "path": "forge/projection.py",
        "filename": "projection.py",
        "directory": "forge",
        "size": 14169,
        "loc": 394,
        "mtime": 1795040282.8744056,
        "time_str": "22:18:02 UTC",
        "owner": "pipeline"
      },
      {
        "path": "tests/forge/test_schema_projection.py",
        "filename": "test_schema_projection.py",
        "directory": "tests",
        "size": 10290,
        "loc": 263,
        "mtime": 1795040173.528135,
        "time_str": "22:16:13 UTC",
        "owner": "pipeline"
      },
      {
        "path": "forge/orchestrator.py",
        "filename": "orchestrator.py",
        "directory": "forge",
        "size": 20676,
        "loc": 591,
        "mtime": 1795040168.133505,
        "time_str": "22:16:08 UTC",
        "owner": "pipeline"
      },
      {
        "path": "tests/forge/test_host_agent_mode.py",
        "filename": "test_host_agent_mode.py",
        "directory": "tests",
        "size": 4153,
        "loc": 110,
        "mtime": 1795040084.9639647,
        "time_str": "22:14:44 UTC",
        "owner": "pipeline"
      },
      {
        "path": "forge/__init__.py",
        "filename": "__init__.py",
        "directory": "forge",
        "size": 559,
        "loc": 19,
        "mtime": 1795040081.66075,
        "time_str": "22:14:41 UTC",
        "owner": "pipeline"
      },
      {
        "path": "tests/forge/test_ingest_openapi.py",
        "filename": "test_ingest_openapi.py",
        "directory": "tests",
        "size": 13320,
        "loc": 362,
        "mtime": 1795039718.513723,
        "time_str": "22:08:38 UTC",
        "owner": "pipeline"
      },
      {
        "path": "spec/cloud-billing.openapi.json",
        "filename": "cloud-billing.openapi.json",
        "directory": "spec",
        "size": 6747,
        "loc": 238,
        "mtime": 1795039626.7637362,
        "time_str": "22:07:06 UTC",
        "owner": "pipeline"
      },
      {
        "path": "spec/acme-incidents.openapi.yaml",
        "filename": "acme-incidents.openapi.yaml",
        "directory": "spec",
        "size": 6724,
        "loc": 215,
        "mtime": 1795039624.3902924,
        "time_str": "22:07:04 UTC",
        "owner": "pipeline"
      },
      {
        "path": "forge/ingest_openapi.py",
        "filename": "ingest_openapi.py",
        "directory": "forge",
        "size": 13995,
        "loc": 344,
        "mtime": 1795039598.8533425,
        "time_str": "22:06:38 UTC",
        "owner": "pipeline"
      }
    ],
    "has_venv": true,
    "has_artifacts": true,
    "has_golden": true,
    "has_manifest": true
  },
  "stages": [
    {
      "id": 1,
      "name": "Stage 1: OpenAPI 3.x Normalizer",
      "desc": "$ref inline resolution, SSRF guardrail, <=15 tool bound",
      "status": "completed",
      "agent": "pipeline",
      "badge": "Gemini 4 Argon"
    },
    {
      "id": 2,
      "name": "Stage 2: Golden Template Lock",
      "desc": "FastMCP 4.x runtime, HMAC auth, deps injector, :ro core lock",
      "status": "completed",
      "agent": "core",
      "badge": "Gemini 4 Carbon"
    },
    {
      "id": 3,
      "name": "Stage 3: Parallel Agent Synthesis",
      "desc": "5 stateless MCP tools, Pydantic 2020-12, unit tests, README",
      "status": "completed",
      "agent": "tools",
      "badge": "Gemini 4 Hydrogen"
    },
    {
      "id": 4,
      "name": "Stage 4: 4-Gate Security Verification",
      "desc": "Ruff, Mypy --strict, AST SEP-2577 audit, Pytest >=85% branch cov",
      "status": "running",
      "agent": "core & tools",
      "badge": "Formal Gates"
    },
    {
      "id": 5,
      "name": "Stage 5: Governance & Packaging",
      "desc": "mcpServers config, destructive tool signoff, artifact bundling",
      "status": "completed",
      "agent": "pipeline",
      "badge": "Release"
    }
  ],
  "verification_matrix": [
    {
      "gate": "Gate 1: Ruff Lint + Bandit Security",
      "rule": "Zero lint errors, no insecure eval/exec/subprocess patterns",
      "status": "pending",
      "standard": "ruff check src forge tests"
    },
    {
      "gate": "Gate 2: Mypy Strict Type Check",
      "rule": "100% strict type annotations, no Any fallbacks in public signatures",
      "status": "pending",
      "standard": "mypy --strict src"
    },
    {
      "gate": "Gate 3: AST & SEP-2577 Deprecation Audit",
      "rule": "Zero deprecated stdlib, absolute imports, no mutating global state",
      "status": "passed",
      "standard": "scripts/validate_mcp.py --ast"
    },
    {
      "gate": "Gate 4: Pytest Suite & >=85% Branch Coverage",
      "rule": "Contract tests + unit tests passing with strict branch coverage >= 85%",
      "status": "pending",
      "standard": "pytest --cov=src --cov-branch --cov-fail-under=85"
    },
    {
      "gate": "Gate 5: STDIO Protocol Discovery",
      "rule": "Clean JSON-RPC 2.0 handshake, MCP 2026-07-28 tools/list discovery",
      "status": "pending",
      "standard": "FastMCP StdioServerTransport handshake"
    }
  ],
  "routing_matrix": [
    {
      "family": "Gemini",
      "variants": [
        {
          "tier": "Low",
          "model": "Gemini 3.8 Flash (Low)",
          "active": false,
          "agent": null,
          "desc": "Lightweight summarization"
        },
        {
          "tier": "Medium",
          "model": "Gemini 3.8 Flash (Medium)",
          "active": true,
          "agent": "dashboard",
          "desc": "Fast Mission Control UI & telemetry collector"
        },
        {
          "tier": "High",
          "model": "Gemini 3.8 Pro (High)",
          "active": false,
          "agent": null,
          "desc": "Broad orchestration & review"
        }
      ]
    },
    {
      "family": "Hydrogen",
      "variants": [
        {
          "tier": "Low",
          "model": "Gemini 4 Hydrogen (Low)",
          "active": false,
          "agent": null,
          "desc": "Template expansion"
        },
        {
          "tier": "Medium",
          "model": "Gemini 4 Hydrogen (Med)",
          "active": false,
          "agent": null,
          "desc": "Standard tool generation"
        },
        {
          "tier": "High",
          "model": "Gemini 4 Hydrogen (High)",
          "active": true,
          "agent": "tools",
          "desc": "High-velocity MCP tools & TDD unit suites"
        }
      ]
    },
    {
      "family": "Argon",
      "variants": [
        {
          "tier": "Low",
          "model": "Gemini 4 Argon (Low)",
          "active": false,
          "agent": null,
          "desc": "AST syntax checking"
        },
        {
          "tier": "Medium",
          "model": "Gemini 4 Argon (Med)",
          "active": false,
          "agent": null,
          "desc": "Schema translation"
        },
        {
          "tier": "High",
          "model": "Gemini 4 Argon (High)",
          "active": true,
          "agent": "pipeline",
          "desc": "Algorithmic AST parsing, OpenAPI normalizer & self-healing"
        }
      ]
    },
    {
      "family": "Carbon",
      "variants": [
        {
          "tier": "Low",
          "model": "Gemini 4 Carbon (Low)",
          "active": false,
          "agent": null,
          "desc": "Static rule analysis"
        },
        {
          "tier": "Medium",
          "model": "Gemini 4 Carbon (Med)",
          "active": false,
          "agent": null,
          "desc": "Contract verification"
        },
        {
          "tier": "High",
          "model": "Gemini 4 Carbon (High)",
          "active": true,
          "agent": "core",
          "desc": "Formal AST security audit, HMAC auth & contract guarantees"
        }
      ]
    }
  ],
  "mcp_version": "2026-07-28",
  "protocol": "FastMCP v4.x"
};
if (typeof window.__onForgeTelemetry === 'function') {
  window.__onForgeTelemetry(window.__FORGE_TELEMETRY__);
}
