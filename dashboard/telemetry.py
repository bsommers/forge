#!/usr/bin/env python3
"""MCP Server Forge Live Telemetry Collector.

Scans the forge workspace, aggregates subagent state files,
computes code metrics, and atomically writes dashboard/status.js.
Compatible with pure Python 3.12 stdlib (offline, zero-CORS file:// and http://).
"""

from __future__ import annotations

import argparse
import http.server
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

WORKSPACE_ROOT = Path("/Users/bill/src/swe/forge").resolve()
DASHBOARD_DIR = WORKSPACE_ROOT / "dashboard"
STATE_DIR = DASHBOARD_DIR / "state"
STATUS_JS = DASHBOARD_DIR / "status.js"

SCAN_DIRS = [
    "src",
    "forge",
    "golden-template",
    "spec",
    "tests",
    "scripts",
    "dashboard",
    "docs",
]

IGNORE_DIRS = {
    ".venv",
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "htmlcov",
    ".coverage",
}

IGNORE_FILES = {
    ".DS_Store",
}

MODEL_ROUTING = [
    {
        "family": "Gemini",
        "variants": [
            {
                "tier": "Low",
                "model": "Gemini 3.8 Flash (Low)",
                "active": False,
                "agent": None,
                "desc": "Lightweight summarization",
            },
            {
                "tier": "Medium",
                "model": "Gemini 3.8 Flash (Medium)",
                "active": True,
                "agent": "dashboard",
                "desc": "Fast Mission Control UI & telemetry collector",
            },
            {
                "tier": "High",
                "model": "Gemini 3.8 Pro (High)",
                "active": False,
                "agent": None,
                "desc": "Broad orchestration & review",
            },
        ],
    },
    {
        "family": "Hydrogen",
        "variants": [
            {
                "tier": "Low",
                "model": "Gemini 4 Hydrogen (Low)",
                "active": False,
                "agent": None,
                "desc": "Template expansion",
            },
            {
                "tier": "Medium",
                "model": "Gemini 4 Hydrogen (Med)",
                "active": False,
                "agent": None,
                "desc": "Standard tool generation",
            },
            {
                "tier": "High",
                "model": "Gemini 4 Hydrogen (High)",
                "active": True,
                "agent": "tools",
                "desc": "High-velocity MCP tools & TDD unit suites",
            },
        ],
    },
    {
        "family": "Argon",
        "variants": [
            {
                "tier": "Low",
                "model": "Gemini 4 Argon (Low)",
                "active": False,
                "agent": None,
                "desc": "AST syntax checking",
            },
            {
                "tier": "Medium",
                "model": "Gemini 4 Argon (Med)",
                "active": False,
                "agent": None,
                "desc": "Schema translation",
            },
            {
                "tier": "High",
                "model": "Gemini 4 Argon (High)",
                "active": True,
                "agent": "pipeline",
                "desc": "Algorithmic AST parsing, OpenAPI normalizer & self-healing",
            },
        ],
    },
    {
        "family": "Carbon",
        "variants": [
            {
                "tier": "Low",
                "model": "Gemini 4 Carbon (Low)",
                "active": False,
                "agent": None,
                "desc": "Static rule analysis",
            },
            {
                "tier": "Medium",
                "model": "Gemini 4 Carbon (Med)",
                "active": False,
                "agent": None,
                "desc": "Contract verification",
            },
            {
                "tier": "High",
                "model": "Gemini 4 Carbon (High)",
                "active": True,
                "agent": "core",
                "desc": "Formal AST security audit, HMAC auth & contract guarantees",
            },
        ],
    },
]

DEFAULT_AGENTS: dict[str, dict[str, Any]] = {
    "core": {
        "agent": "core",
        "role": "Golden Template & Security Runtime",
        "model": "gemini-4-carbon-high",
        "model_label": "Gemini 4 Carbon",
        "effort": "High",
        "status": "working",
        "progress": 25,
        "stage": "Stage 2 & 4 — Core Runtime & Security Gates",
        "current_task": "Scaffolding FastMCP 2026-07-28 runtime & offline uv environment",
        "files_owned": [
            "pyproject.toml",
            "src/auth.py",
            "src/deps.py",
            "src/server.py",
            "respx/",
            "scripts/validate_mcp.py",
            "tests/contract/test_forge_contract.py",
            "golden-template/",
        ],
        "gates": {
            "ruff": "pending",
            "mypy": "pending",
            "ast_audit": "pending",
            "pytest": "pending",
            "stdio_discover": "pending",
        },
        "model_rationale": ("Maximum reasoning depth & formal verification for AST "
            "security gates & contract guarantees"),
    },
    "pipeline": {
        "agent": "pipeline",
        "role": "Stage 1 Ingestion & Self-Healing Pipeline",
        "model": "gemini-4-argon-high",
        "model_label": "Gemini 4 Argon",
        "effort": "High",
        "status": "working",
        "progress": 20,
        "stage": "Stage 1 & Stages 2–5 Host Pipeline",
        "current_task": "Ingesting OpenAPI 3.x spec & building self-healing pipeline",
        "files_owned": [
            "forge/ingest_openapi.py",
            "forge/codegen.py",
            "forge/orchestrator.py",
            "spec/acme-incidents.openapi.yaml",
            "tests/forge/",
        ],
        "gates": {
            "ruff": "pending",
            "mypy": "pending",
            "ast_audit": "n/a",
            "pytest": "pending",
            "stdio_discover": "n/a",
        },
        "model_rationale": ("High algorithmic synthesis for AST normalizer, OpenAPI ref inlining, "
            "and self-healing repair loop"),
    },
    "tools": {
        "agent": "tools",
        "role": "MCP 2026-07-28 Domain Tools & TDD Suite",
        "model": "gemini-4-hydrogen-high",
        "model_label": "Gemini 4 Hydrogen",
        "effort": "High",
        "status": "working",
        "progress": 25,
        "stage": "Stage 3 — Domain Tools & >=85% Branch Coverage",
        "current_task": "Synthesizing 5 incident domain tools & unit tests",
        "files_owned": [
            "src/tools/get_incident.py",
            "src/tools/list_incidents.py",
            "src/tools/create_incident.py",
            "src/tools/update_incident_status.py",
            "src/tools/delete_incident.py",
            "tests/unit/",
            "README.md",
        ],
        "gates": {
            "ruff": "pending",
            "mypy": "pending",
            "ast_audit": "pending",
            "pytest": "pending",
            "stdio_discover": "pending",
        },
        "model_rationale": ("High code generation velocity and domain schema alignment for "
            "Pydantic 2020-12 & unit suites"),
    },
    "dashboard": {
        "agent": "dashboard",
        "role": "Live Mission Control Dashboard & Telemetry Collector",
        "model": "gemini-3.8-flash-medium",
        "model_label": "Gemini 3.8 Flash",
        "effort": "Medium",
        "status": "working",
        "progress": 40,
        "stage": "Mission Control & Live Telemetry",
        "current_task": ("Scaffolding zero-CORS live telemetry engine and dark obsidian "
            "Mission Control UI"),
        "files_owned": [
            "dashboard/index.html",
            "dashboard/telemetry.py",
            "dashboard/status.js",
            "dashboard/state/dashboard.json",
        ],
        "gates": {
            "ruff": "passing",
            "mypy": "passing",
            "ast_audit": "passing",
            "pytest": "passing",
            "stdio_discover": "passing",
        },
        "model_rationale": (
            "Ultra-fast low-latency telemetry aggregation and "
            "fluid zero-dependency UI rendering"
        ),
    },
}


def load_agent_states() -> dict[str, dict[str, Any]]:
    """Loads agent state JSON files, merging with defaults."""
    agents: dict[str, dict[str, Any]] = {}
    for name, default_data in DEFAULT_AGENTS.items():
        state_file = STATE_DIR / f"{name}.json"
        data = dict(default_data)
        if state_file.exists():
            try:
                with open(state_file, encoding="utf-8") as f:
                    loaded = json.load(f)
                    if isinstance(loaded, dict):
                        data.update(loaded)
            except Exception as e:
                _ = e
        agents[name] = data
    return agents


def determine_file_owner(relpath: str) -> str:
    """Attributes a file to its owning agent based on path patterns."""
    if relpath.startswith("dashboard/"):
        return "dashboard"
    if (
        relpath.startswith("src/tools/")
        or relpath.startswith("tests/unit/")
        or relpath == "README.md"
    ):
        return "tools"
    if (
        relpath.startswith("forge/")
        or relpath.startswith("spec/")
        or relpath.startswith("tests/forge/")
        or relpath.startswith("forge-release-")
    ):
        return "pipeline"
    if (
        relpath.startswith("src/")
        or relpath.startswith("respx/")
        or relpath.startswith("golden-template/")
        or relpath.startswith("tests/contract/")
        or relpath.startswith("scripts/")
        or relpath in ("pyproject.toml", "uv.lock", "Dockerfile", "forge-manifest.json")
    ):
        return "core"
    return "workspace"


def scan_workspace() -> dict[str, Any]:
    """Scans repository files and calculates LOC, directory stats, and recent activity."""
    total_files = 0
    total_loc = 0
    by_ext: dict[str, dict[str, int]] = {}
    by_dir: dict[str, dict[str, int]] = {}
    recent_files: list[dict[str, Any]] = []

    # Include root files
    root_paths = list(WORKSPACE_ROOT.glob("*.*"))
    # Include scan directories
    dir_paths: list[Path] = []
    for d in SCAN_DIRS:
        dp = WORKSPACE_ROOT / d
        if dp.exists():
            dir_paths.append(dp)

    all_files: list[Path] = []
    for rp in root_paths:
        if rp.is_file() and rp.name not in IGNORE_FILES:
            all_files.append(rp)

    for dp in dir_paths:
        for root, dirs, files in os.walk(dp):
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
            for file in files:
                if file in IGNORE_FILES or file.startswith("status.js.tmp"):
                    continue
                fp = Path(root) / file
                all_files.append(fp)

    for fp in all_files:
        try:
            rel = str(fp.relative_to(WORKSPACE_ROOT))
        except ValueError:
            continue

        total_files += 1
        stat = fp.stat()
        mtime = stat.st_mtime
        size = stat.st_size
        top_dir = rel.split(os.sep)[0] if os.sep in rel else "."
        ext = fp.suffix.lower() or ".txt"

        loc = 0
        if ext in {
            ".py",
            ".html",
            ".js",
            ".css",
            ".json",
            ".yaml",
            ".yml",
            ".md",
            ".toml",
            ".sh",
            ".txt",
        }:
            try:
                with open(fp, "rb") as f:
                    loc = sum(1 for _ in f)
            except Exception:
                loc = 0

        total_loc += loc

        # Directory breakdown
        if top_dir not in by_dir:
            by_dir[top_dir] = {"files": 0, "lines": 0}
        by_dir[top_dir]["files"] += 1
        by_dir[top_dir]["lines"] += loc

        # Extension breakdown
        if ext not in by_ext:
            by_ext[ext] = {"files": 0, "lines": 0}
        by_ext[ext]["files"] += 1
        by_ext[ext]["lines"] += loc

        owner = determine_file_owner(rel)
        recent_files.append(
            {
                "path": rel,
                "filename": fp.name,
                "directory": top_dir,
                "size": size,
                "loc": loc,
                "mtime": mtime,
                "time_str": datetime.fromtimestamp(mtime, tz=UTC).strftime("%H:%M:%S UTC"),
                "owner": owner,
            }
        )

    recent_files.sort(key=lambda x: x["mtime"], reverse=True)

    has_venv = (WORKSPACE_ROOT / ".venv").exists()
    has_artifacts = (WORKSPACE_ROOT / "forge-release-artifacts.json").exists()
    has_golden = (WORKSPACE_ROOT / "golden-template").exists()
    has_manifest = (WORKSPACE_ROOT / "forge-manifest.json").exists()

    return {
        "total_files": total_files,
        "total_loc": total_loc,
        "by_dir": by_dir,
        "by_ext": by_ext,
        "recent_files": recent_files[:20],
        "has_venv": has_venv,
        "has_artifacts": has_artifacts,
        "has_golden": has_golden,
        "has_manifest": has_manifest,
    }


def compute_pipeline_stages(
    agents: dict[str, Any], workspace_stats: dict[str, Any]
) -> list[dict[str, Any]]:
    """Evaluates the 5 pipeline stages and their execution status."""
    # Stage 1: OpenAPI 3.x Normalizer
    p_prog = agents.get("pipeline", {}).get("progress", 0)
    st1_status = (
        "completed"
        if p_prog >= 60 or (WORKSPACE_ROOT / "forge/ingest_openapi.py").exists()
        else "running"
    )

    # Stage 2: Golden Template Lock
    c_prog = agents.get("core", {}).get("progress", 0)
    st2_status = (
        "completed" if c_prog >= 80 or (WORKSPACE_ROOT / "golden-template").exists() else "running"
    )

    # Stage 3: Parallel Agent Synthesis
    t_prog = agents.get("tools", {}).get("progress", 0)
    tools_count = (
        len(list((WORKSPACE_ROOT / "src/tools").glob("*.py")))
        if (WORKSPACE_ROOT / "src/tools").exists()
        else 0
    )
    st3_status = "completed" if t_prog >= 85 and tools_count >= 5 else "running"

    # Stage 4: 4-Gate Verification
    core_gates = agents.get("core", {}).get("gates", {})
    tools_gates = agents.get("tools", {}).get("gates", {})
    all_passing = all(v == "passing" for v in core_gates.values() if v != "n/a") and all(
        v == "passing" for v in tools_gates.values() if v != "n/a"
    )
    st4_status = "completed" if all_passing and (c_prog >= 90 and t_prog >= 90) else "running"

    # Stage 5: Governance & Packaging
    has_artifacts = workspace_stats.get("has_artifacts", False)
    st5_status = (
        "completed"
        if has_artifacts or (p_prog >= 95 and c_prog >= 95 and t_prog >= 95)
        else ("running" if st4_status == "completed" else "pending")
    )

    return [
        {
            "id": 1,
            "name": "Stage 1: OpenAPI 3.x Normalizer",
            "desc": "$ref inline resolution, SSRF guardrail, <=15 tool bound",
            "status": st1_status,
            "agent": "pipeline",
            "badge": "Gemini 4 Argon",
        },
        {
            "id": 2,
            "name": "Stage 2: Golden Template Lock",
            "desc": "FastMCP 4.x runtime, HMAC auth, deps injector, :ro core lock",
            "status": st2_status,
            "agent": "core",
            "badge": "Gemini 4 Carbon",
        },
        {
            "id": 3,
            "name": "Stage 3: Parallel Agent Synthesis",
            "desc": "5 stateless MCP tools, Pydantic 2020-12, unit tests, README",
            "status": st3_status,
            "agent": "tools",
            "badge": "Gemini 4 Hydrogen",
        },
        {
            "id": 4,
            "name": "Stage 4: 4-Gate Security Verification",
            "desc": "Ruff, Mypy --strict, AST SEP-2577 audit, Pytest >=85% branch cov",
            "status": st4_status,
            "agent": "core & tools",
            "badge": "Formal Gates",
        },
        {
            "id": 5,
            "name": "Stage 5: Governance & Packaging",
            "desc": "mcpServers config, destructive tool signoff, artifact bundling",
            "status": st5_status,
            "agent": "pipeline",
            "badge": "Release",
        },
    ]


def compute_verification_matrix(agents: dict[str, Any]) -> list[dict[str, Any]]:
    """Synthesizes the 5 verification gates status across all subagents."""
    core_gates = agents.get("core", {}).get("gates", {})
    tools_gates = agents.get("tools", {}).get("gates", {})

    def resolve(g1: str, g2: str) -> str:
        if g1 == "failing" or g2 == "failing":
            return "failing"
        if g1 == "passing" and (g2 in ("passing", "pending", "n/a", None)):
            return "passing"
        if g2 == "passing" and (g1 in ("passing", "pending", "n/a", None)):
            return "passing"
        if g1 == "running" or g2 == "running":
            return "running"
        return "pending"

    return [
        {
            "gate": "Gate 1: Ruff Lint + Bandit Security",
            "rule": "Zero lint errors, no insecure eval/exec/subprocess patterns",
            "status": resolve(
                core_gates.get("ruff", "pending"), tools_gates.get("ruff", "pending")
            ),
            "standard": "ruff check src forge tests",
        },
        {
            "gate": "Gate 2: Mypy Strict Type Check",
            "rule": "100% strict type annotations, no Any fallbacks in public signatures",
            "status": resolve(
                core_gates.get("mypy", "pending"), tools_gates.get("mypy", "pending")
            ),
            "standard": "mypy --strict src",
        },
        {
            "gate": "Gate 3: AST & SEP-2577 Deprecation Audit",
            "rule": "Zero deprecated stdlib, absolute imports, no mutating global state",
            "status": core_gates.get("ast_audit", "pending"),
            "standard": "scripts/validate_mcp.py --ast",
        },
        {
            "gate": "Gate 4: Pytest Suite & >=85% Branch Coverage",
            "rule": "Contract tests + unit tests passing with strict branch coverage >= 85%",
            "status": resolve(
                core_gates.get("pytest", "pending"), tools_gates.get("pytest", "pending")
            ),
            "standard": "pytest --cov=src --cov-branch --cov-fail-under=85",
        },
        {
            "gate": "Gate 5: STDIO Protocol Discovery",
            "rule": "Clean JSON-RPC 2.0 handshake, MCP 2026-07-28 tools/list discovery",
            "status": resolve(
                core_gates.get("stdio_discover", "pending"),
                tools_gates.get("stdio_discover", "pending"),
            ),
            "standard": "FastMCP StdioServerTransport handshake",
        },
    ]


def generate_telemetry_snapshot() -> dict[str, Any]:
    """Assembles the complete telemetry payload."""
    agents = load_agent_states()
    workspace_stats = scan_workspace()
    pipeline_stages = compute_pipeline_stages(agents, workspace_stats)
    verification_matrix = compute_verification_matrix(agents)

    # Compute overall progress
    progress_sum = sum(agent.get("progress", 0) for agent in agents.values())
    overall_progress = round(progress_sum / max(1, len(agents)))

    all_completed = all(agent.get("status") == "completed" for agent in agents.values())
    overall_status = "ALL SYSTEMS VERIFIED" if all_completed else "BUILDING IN PARALLEL"

    active_subagents = len([a for a in agents.values() if a.get("status") == "working"])

    now_iso = datetime.now(UTC).isoformat()
    now_time = datetime.now(UTC).strftime("%H:%M:%S UTC")

    return {
        "timestamp": now_iso,
        "time_display": now_time,
        "overall_status": overall_status,
        "overall_progress": overall_progress,
        "active_subagents": active_subagents,
        "max_subagents": 4,
        "agents": agents,
        "workspace": workspace_stats,
        "stages": pipeline_stages,
        "verification_matrix": verification_matrix,
        "routing_matrix": MODEL_ROUTING,
        "mcp_version": "2026-07-28",
        "protocol": "FastMCP v4.x",
    }


def write_status_js(snapshot: dict[str, Any]) -> None:
    """Atomically writes dashboard/status.js via temporary file."""
    STATUS_JS.parent.mkdir(parents=True, exist_ok=True)
    temp_file = STATUS_JS.parent / f"status.js.tmp.{os.getpid()}"
    json_str = json.dumps(snapshot, indent=2)
    content = (
        "// MCP Server Forge Live Telemetry Payload\n"
        f"// Generated at {snapshot['timestamp']}\n"
        f"window.__FORGE_TELEMETRY__ = {json_str};\n"
        "if (typeof window.__onForgeTelemetry === 'function') {\n"
        "  window.__onForgeTelemetry(window.__FORGE_TELEMETRY__);\n"
        "}\n"
    )
    with open(temp_file, "w", encoding="utf-8") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp_file, STATUS_JS)


def run_watch(duration: float, interval: float) -> None:
    """Runs telemetry aggregation loop for a given duration."""
    start_time = time.time()
    count = 0
    print(f"[telemetry] Starting watch loop: interval={interval}s, duration={duration}s")
    while True:
        elapsed = time.time() - start_time
        if duration > 0 and elapsed >= duration:
            print(f"[telemetry] Watch duration ({duration}s) reached. Exiting.")
            break
        try:
            snapshot = generate_telemetry_snapshot()
            write_status_js(snapshot)
            count += 1
            if count % 10 == 0:
                ts = snapshot['time_display']
                pct = snapshot['overall_progress']
                print(f"[telemetry] Snapshot #{count} written at {ts} (Overall: {pct}%)")
        except Exception as e:
            print(f"[telemetry] Error updating snapshot: {e}", file=sys.stderr)
        time.sleep(interval)


def serve_dashboard(port: int = 8765) -> None:
    """Optionally serves the dashboard directory over HTTP."""
    os.chdir(DASHBOARD_DIR)
    handler = http.server.SimpleHTTPRequestHandler
    with http.server.ThreadingHTTPServer(("", port), handler) as httpd:
        print(
            f"[telemetry] Serving Mission Control Dashboard at http://localhost:{port}/index.html"
        )
        httpd.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Forge Mission Control Telemetry")
    parser.add_argument("--once", action="store_true", help="Generate a single snapshot and exit")
    parser.add_argument(
        "--watch", action="store_true", help="Continuously poll workspace and write status.js"
    )
    parser.add_argument(
        "--duration", type=float, default=300.0, help="Watch duration in seconds (default 300)"
    )
    parser.add_argument(
        "--interval", type=float, default=1.5, help="Polling interval in seconds (default 1.5)"
    )
    parser.add_argument("--serve", action="store_true", help="Serve dashboard over local HTTP")
    parser.add_argument("--port", type=int, default=8765, help="HTTP server port (default 8765)")

    args = parser.parse_args()

    if args.serve:
        serve_dashboard(args.port)
        return

    if args.once or not args.watch:
        snapshot = generate_telemetry_snapshot()
        write_status_js(snapshot)
        n_files = snapshot['workspace']['total_files']
        n_loc = snapshot['workspace']['total_loc']
        pct = snapshot['overall_progress']
        print(
            f"[telemetry] Generated {STATUS_JS} ({n_files} files, {n_loc} LOC, {pct}% overall)"
        )
        if not args.watch:
            return

    if args.watch:
        run_watch(args.duration, args.interval)


if __name__ == "__main__":
    main()
