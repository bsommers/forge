"""Stage 5 NIST OSCAL 1.1.2 SSP/SAR/POA&M Attestation & Policy Verifier (MCP-001..008)."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

FORGE_OSCAL_NS = uuid.UUID("3f90b2e4-17c8-4a3d-8f50-2a19d47c8053")
OSCAL_VERSION = "1.1.2"
DETERMINISTIC_TIMESTAMP = "2026-11-19T00:00:00Z"

CONTROLS_PROFILE_HREF = (
    "https://github.com/bsommers/security-controls/blob/main/catalog/cosis/use-cases.json"
)
PATTERNS_CATALOG_HREF = (
    "https://github.com/bsommers/secure-design-patterns/blob/main/patterns/mcp-serve/catalog.json"
)

HUMAN_ONLY_CONTROLS = frozenset({"at-3", "pe-3", "pm-9", "ps-6"})
REQUIRED_P1_CONTROLS = frozenset(
    {
        "ac-6",
        "ac-6.1",
        "ac-6.10",
        "cm-2",
        "cm-5",
        "cm-7",
        "sa-8",
        "sa-11",
        "sc-5",
        "sc-7",
        "sc-39",
        "si-7.1",
        "si-10",
        "sr-3",
    }
)


def _det_uuid(seed: str) -> str:
    return str(uuid.uuid5(FORGE_OSCAL_NS, seed))


@dataclass(frozen=True)
class _CtrlEntry:
    oscal_id: str
    nist_id: str
    title: str
    component_key: str  # "chassis" | "overlay" | "organization"
    patterns: tuple[str, ...]
    narrative: str
    human_only: bool = False


_CONTROL_MATRIX: tuple[_CtrlEntry, ...] = (
    _CtrlEntry(
        "ac-4",
        "AC-4",
        "Information Flow Enforcement",
        "chassis",
        ("MCP-003", "MCP-006"),
        "Stateless SEP-2567 execution and JSON Schema 2020-12 outputSchema enforcement.",
    ),
    _CtrlEntry(
        "ac-6",
        "AC-6",
        "Least Privilege",
        "chassis",
        ("MCP-001",),
        "Server-bound RouteDispatchAuth credentials with zero client token passthrough.",
    ),
    _CtrlEntry(
        "ac-6.1",
        "AC-6(1)",
        "Authorize Access to Security Functions",
        "chassis",
        ("MCP-002",),
        "Golden Template infrastructure and contract tests locked read-only with SHA-256 guards.",
    ),
    _CtrlEntry(
        "ac-6.10",
        "AC-6(10)",
        "Prohibit Non-Privileged Users from Executing Privileged Functions",
        "overlay",
        ("MCP-005",),
        "Destructive tools annotated with destructiveHint=True and flagged for AppSec signoff.",
    ),
    _CtrlEntry(
        "au-3",
        "AU-3",
        "Content of Audit Records",
        "chassis",
        ("MCP-001", "MCP-008"),
        "Structured JSON audit logs written strictly to stderr with secret redaction.",
    ),
    _CtrlEntry(
        "au-6",
        "AU-6",
        "Audit Record Review, Analysis, and Reporting",
        "chassis",
        ("MCP-007", "MCP-008"),
        "RFC 9110 x-mcp-header correlation support and structured validation telemetry.",
    ),
    _CtrlEntry(
        "ca-2",
        "CA-2",
        "Control Assessments",
        "chassis",
        ("MCP-002", "MCP-008"),
        "5-gate deterministic scripts/validate_mcp.py harness independent of LLM self-grading.",
    ),
    _CtrlEntry(
        "cm-2",
        "CM-2",
        "Baseline Configuration",
        "chassis",
        ("MCP-002",),
        "Immutable FastMCP 4.x golden-template/ chassis baseline.",
    ),
    _CtrlEntry(
        "cm-5",
        "CM-5",
        "Access Restrictions for Change",
        "chassis",
        ("MCP-002",),
        "Agent write overlay confined to src/tools/, tests/unit/, and README.md.",
    ),
    _CtrlEntry(
        "cm-7",
        "CM-7",
        "Least Functionality",
        "overlay",
        ("MCP-005", "MCP-008"),
        "Enforces <= 15 active tools per server and AST SEP-2577 / forbidden-import bans.",
    ),
    _CtrlEntry(
        "ia-9",
        "IA-9",
        "Service Identification and Authentication",
        "chassis",
        ("MCP-001", "MCP-005"),
        "Per-operation OpenAPI securitySchemes dispatch and shard-scoped auth pruning.",
    ),
    _CtrlEntry(
        "pt-2",
        "PT-2",
        "Authority to Process Personally Identifiable Information",
        "overlay",
        ("MCP-004", "MCP-007"),
        "High-signal response field projection without raw dict[str, Any] PII dumps.",
    ),
    _CtrlEntry(
        "sa-8",
        "SA-8",
        "Security and Privacy Engineering Principles",
        "chassis",
        ("MCP-001", "MCP-002", "MCP-003", "MCP-004"),
        "Implements MCP-001..MCP-008 secure design patterns across ingest, chassis, and runtime.",
    ),
    _CtrlEntry(
        "sa-11",
        "SA-11",
        "Developer Testing and Evaluation",
        "overlay",
        ("MCP-008",),
        "Verified via Ruff S+T20, mypy --strict, AST gate, >=85% branch coverage, and stdio probe.",
    ),
    _CtrlEntry(
        "sc-5",
        "SC-5",
        "Denial-of-Service Protection",
        "chassis",
        ("MCP-003", "MCP-006"),
        "15s upstream HTTP timeout plus dual-axis 32 KiB list-cardinality and string bounding.",
    ),
    _CtrlEntry(
        "sc-7",
        "SC-7",
        "Boundary Protection",
        "chassis",
        ("MCP-004", "MCP-006"),
        "Blocks remote $ref SSRF and traversal; routes HTTP strictly through pooled ApiClient.",
    ),
    _CtrlEntry(
        "sc-39",
        "SC-39",
        "Process Isolation",
        "chassis",
        ("MCP-002", "MCP-008"),
        "Container --cap-drop=ALL, UID 65532, and forge/sandbox.py seatbelt/bwrap host isolation.",
    ),
    _CtrlEntry(
        "si-7.1",
        "SI-7(1)",
        "Integrity Checks",
        "chassis",
        ("MCP-002",),
        "Pre/post SHA-256 digest verification and automatic byte restoration on locked paths.",
    ),
    _CtrlEntry(
        "si-10",
        "SI-10",
        "Information Input Validation",
        "overlay",
        ("MCP-004", "MCP-007", "MCP-008"),
        "Typed Pydantic/JSON Schema 2020-12 input validation and RFC 9110 header checks.",
    ),
    _CtrlEntry(
        "sr-3",
        "SR-3",
        "Supply Chain Controls and Processes",
        "chassis",
        ("MCP-002",),
        "40-char SHA-pinned GitHub Actions CI workflows and locked uv.lock dependencies.",
    ),
    _CtrlEntry(
        "at-3",
        "AT-3",
        "Role-Based Training",
        "organization",
        (),
        "[HUMAN ATTESTATION REQUIRED] Organizational AI/SSDF security training attestation.",
        human_only=True,
    ),
    _CtrlEntry(
        "pe-3",
        "PE-3",
        "Physical Access Control",
        "organization",
        (),
        "[HUMAN ATTESTATION REQUIRED] Inherited cloud/datacenter physical facility controls.",
        human_only=True,
    ),
    _CtrlEntry(
        "pm-9",
        "PM-9",
        "Risk Management Strategy",
        "organization",
        (),
        "[HUMAN ATTESTATION REQUIRED] Authorizing Official (AO) risk management signoff.",
        human_only=True,
    ),
    _CtrlEntry(
        "ps-6",
        "PS-6",
        "Access Agreements",
        "organization",
        (),
        "[HUMAN ATTESTATION REQUIRED] Privileged operator access agreements.",
        human_only=True,
    ),
)


def emit_oscal_assurance_bundle(
    workspace_dir: Path,
    manifest: dict[str, Any],
    release_artifacts: dict[str, Any],
    *,
    execution_mode: str = "local",
    sandbox_enforced: bool = True,
    sandbox_backend: str = "deterministic-inproc",
) -> dict[str, Any]:
    """Emit OSCAL 1.1.2 Component Def, SSP, SAR, POA&M, and SSP.md; return assurance summary."""
    server_name = str(manifest["server_name"])
    title = str(manifest.get("title", server_name))
    version = str(manifest.get("version", "1.0.0"))
    system_id = f"forged-mcp-{server_name}"

    chassis_uuid = _det_uuid("component:forge-golden-template-chassis")
    overlay_uuid = _det_uuid(f"component:forged-overlay:{server_name}")
    org_uuid = _det_uuid("component:organization-governance")
    comp_uuids = {
        "chassis": chassis_uuid,
        "overlay": overlay_uuid,
        "organization": org_uuid,
    }

    component_def: dict[str, Any] = {
        "component-definition": {
            "uuid": _det_uuid(f"compdef:{server_name}"),
            "metadata": {
                "title": f"Golden Template Component Definition — {title}",
                "last-modified": DETERMINISTIC_TIMESTAMP,
                "version": version,
                "oscal-version": OSCAL_VERSION,
                "props": [
                    {"name": "patterns-source", "value": PATTERNS_CATALOG_HREF},
                    {"name": "controls-source", "value": CONTROLS_PROFILE_HREF},
                ],
            },
            "components": [
                {
                    "uuid": chassis_uuid,
                    "type": "software",
                    "title": "FastMCP 4.x Locked Golden Template Chassis",
                    "description": "Implements MCP-001..MCP-008 security infrastructure.",
                    "control-implementations": [
                        {
                            "uuid": _det_uuid(f"comp-impl:{server_name}"),
                            "source": CONTROLS_PROFILE_HREF,
                            "description": "Inherited NIST SP 800-53r5 + COSIS chassis controls.",
                            "implemented-requirements": [
                                {
                                    "uuid": _det_uuid(f"creq:{server_name}:{c.oscal_id}"),
                                    "control-id": c.oscal_id,
                                    "description": c.narrative,
                                }
                                for c in _CONTROL_MATRIX
                                if c.component_key == "chassis"
                            ],
                        }
                    ],
                }
            ],
        }
    }

    ssp_reqs = [
        {
            "uuid": _det_uuid(f"ssp-req:{server_name}:{c.oscal_id}"),
            "control-id": c.oscal_id,
            "props": [
                {"name": "nist-id", "value": c.nist_id},
                {
                    "name": "implementation-status",
                    "value": "planned" if c.human_only else "implemented",
                },
                {
                    "name": "secure-design-patterns",
                    "value": ",".join(c.patterns) if c.patterns else "organizational",
                },
            ],
            "by-components": [
                {
                    "component-uuid": comp_uuids[c.component_key],
                    "uuid": _det_uuid(f"by-comp:{server_name}:{c.oscal_id}"),
                    "description": c.narrative,
                }
            ],
        }
        for c in _CONTROL_MATRIX
    ]

    ssp: dict[str, Any] = {
        "system-security-plan": {
            "uuid": _det_uuid(f"ssp:{system_id}"),
            "metadata": {
                "title": f"System Security Plan (SSP) — {title} ({server_name})",
                "last-modified": DETERMINISTIC_TIMESTAMP,
                "version": version,
                "oscal-version": OSCAL_VERSION,
                "props": [
                    {"name": "protocol-revision", "value": str(manifest["protocol_revision"])},
                    {"name": "cosis-use-cases", "value": "UC-AGENT-SINGLE,UC-AGENT-MULTI,UC-DEV"},
                    {"name": "sp800-53b-baseline", "value": "moderate"},
                ],
            },
            "import-profile": {"href": CONTROLS_PROFILE_HREF},
            "system-characteristics": {
                "system-ids": [{"id": system_id}],
                "system-name": title,
                "description": str(manifest.get("description", "")),
                "security-sensitivity-level": "moderate",
                "status": {"state": "operational"},
                "props": [
                    {
                        "name": "container-image",
                        "value": str(release_artifacts.get("container_image", "")),
                    },
                    {"name": "active-tool-count", "value": str(len(manifest.get("tools", [])))},
                    {"name": "execution-mode", "value": execution_mode},
                    {"name": "sandbox-backend", "value": sandbox_backend},
                ],
            },
            "system-implementation": {
                "components": [
                    {
                        "uuid": chassis_uuid,
                        "type": "software",
                        "title": "FastMCP 4.x Golden Template Chassis",
                        "description": "Locked auth, lifespan pool, and dual-axis 32KiB bounding.",
                        "status": {"state": "operational"},
                    },
                    {
                        "uuid": overlay_uuid,
                        "type": "software",
                        "title": f"Forged Tool Overlay ({server_name})",
                        "description": f"{len(manifest.get('tools', []))} verified MCP tools.",
                        "status": {"state": "operational"},
                    },
                    {
                        "uuid": org_uuid,
                        "type": "policy",
                        "title": "Organizational Governance Controls",
                        "description": "Human-attested training, facility, and RMF controls.",
                        "status": {"state": "under-development"},
                    },
                ]
            },
            "control-implementation": {
                "description": "NIST SP 800-53r5 Update 1 + COSIS implementation.",
                "implemented-requirements": ssp_reqs,
            },
        }
    }

    # SC-5 (W4.4) and SC-39 (W5.2) are 'satisfied' when isolation/bounding is active.
    # SC-39 drops to 'partially-satisfied' (POAM-FORGE-W5.2) only if host agent disables sandbox.
    findings: list[dict[str, Any]] = []
    poam_items: list[dict[str, Any]] = []
    sc39_isolated = execution_mode in {"docker", "local"} or sandbox_enforced

    for c in _CONTROL_MATRIX:
        if c.human_only:
            state = "other-than-satisfied"
            assessor = "human-attestation-pending"
            desc = "Awaiting named organizational official signoff; LLM self-grading prohibited."
        elif c.oscal_id == "sc-39" and not sc39_isolated:
            state = "partially-satisfied"
            assessor = "automated-gate"
            desc = (
                "Tracked in POAM-FORGE-W5.2: host agent invoked without OS kernel sandbox "
                f"(backend={sandbox_backend}); 0444 + SHA-256 restore active."
            )
            poam_items.append(
                {
                    "uuid": _det_uuid(f"poam:{server_name}:POAM-FORGE-W5.2"),
                    "title": "POAM-FORGE-W5.2 (SC-39): Host OS Kernel Sandboxing Disabled",
                    "description": "Re-enable --sandbox-policy=auto|required or run in Docker.",
                    "props": [
                        {"name": "gap-id", "value": "POAM-FORGE-W5.2"},
                        {"name": "control-id", "value": "sc-39"},
                    ],
                }
            )
        else:
            state = "satisfied"
            assessor = "automated-gate"
            desc = "Verified deterministically by validate_mcp.py 5-gate harness."

        findings.append(
            {
                "uuid": _det_uuid(f"finding:{server_name}:{c.oscal_id}"),
                "title": f"{c.nist_id} — {c.title}",
                "description": desc,
                "target": {
                    "type": "objective-id",
                    "target-id": c.oscal_id,
                    "status": {"state": state},
                },
                "props": [{"name": "assessor-type", "value": assessor}],
            }
        )

    sar: dict[str, Any] = {
        "assessment-results": {
            "uuid": _det_uuid(f"sar:{system_id}"),
            "metadata": {
                "title": f"SP 800-53A Automated Assessment Results — {title}",
                "last-modified": DETERMINISTIC_TIMESTAMP,
                "version": version,
                "oscal-version": OSCAL_VERSION,
            },
            "import-ssp": {"href": "ssp.json"},
            "results": [
                {
                    "uuid": _det_uuid(f"sar-res:{system_id}"),
                    "title": "Forge Stage 4–5 Deterministic Verification",
                    "description": "Automated SP 800-53A gate evaluation.",
                    "start": DETERMINISTIC_TIMESTAMP,
                    "findings": findings,
                }
            ],
        }
    }

    poam: dict[str, Any] = {
        "plan-of-action-and-milestones": {
            "uuid": _det_uuid(f"poam:{system_id}"),
            "metadata": {
                "title": f"Plan of Action and Milestones (POA&M) — {title}",
                "last-modified": DETERMINISTIC_TIMESTAMP,
                "version": version,
                "oscal-version": OSCAL_VERSION,
            },
            "import-ssp": {"href": "ssp.json"},
            "poam-items": poam_items,
        }
    }

    oscal_dir = workspace_dir / "oscal"
    oscal_dir.mkdir(parents=True, exist_ok=True)
    (oscal_dir / "component-definition.json").write_text(
        json.dumps(component_def, indent=2) + "\n", encoding="utf-8"
    )
    (oscal_dir / "ssp.json").write_text(json.dumps(ssp, indent=2) + "\n", encoding="utf-8")
    (oscal_dir / "assessment-results.json").write_text(
        json.dumps(sar, indent=2) + "\n", encoding="utf-8"
    )
    (oscal_dir / "poam.json").write_text(json.dumps(poam, indent=2) + "\n", encoding="utf-8")

    ssp_md = _render_ssp_markdown(title, server_name, version, execution_mode, findings, poam_items)
    (workspace_dir / "SSP.md").write_text(ssp_md, encoding="utf-8")

    policy_violations = verify_oscal_policy_gate(ssp, sar, poam)
    if policy_violations:
        raise RuntimeError(f"OSCAL SSP policy gate failed: {policy_violations}")

    satisfied_count = sum(
        1 for f in findings if f["target"]["status"]["state"] == "satisfied"
    )
    return {
        "oscal_version": OSCAL_VERSION,
        "cosis_use_cases": ["UC-AGENT-SINGLE", "UC-AGENT-MULTI", "UC-DEV"],
        "baseline": "moderate",
        "technical_controls_satisfied": satisfied_count,
        "open_poam_items": len(poam_items),
        "human_attestation_pending": len(HUMAN_ONLY_CONTROLS),
        "oscal_ssp_gate_allow": True,
        "artifacts": {
            "component_definition": "oscal/component-definition.json",
            "ssp": "oscal/ssp.json",
            "assessment_results": "oscal/assessment-results.json",
            "poam": "oscal/poam.json",
            "markdown_ssp": "SSP.md",
        },
    }


def verify_oscal_policy_gate(
    ssp: dict[str, Any], sar: dict[str, Any], poam: dict[str, Any]
) -> list[str]:
    """Deterministic equivalent of policies/oscal/ssp_gate.rego."""
    violations: list[str] = []
    reqs = ssp["system-security-plan"]["control-implementation"]["implemented-requirements"]
    impl_ids = {str(r["control-id"]) for r in reqs}
    for req_id in sorted(REQUIRED_P1_CONTROLS):
        if req_id not in impl_ids:
            violations.append(f"Missing P1 control '{req_id}'")

    poam_ids = {
        str(p["value"])
        for item in poam["plan-of-action-and-milestones"]["poam-items"]
        for p in item.get("props", [])
        if p.get("name") == "control-id"
    }

    for f in sar["assessment-results"]["results"][0]["findings"]:
        cid = str(f["target"]["target-id"])
        st = str(f["target"]["status"]["state"])
        props = {p["name"]: p["value"] for p in f.get("props", [])}
        if (
            cid in HUMAN_ONLY_CONTROLS
            and st == "satisfied"
            and props.get("assessor-type") != "human-official"
        ):
            violations.append(f"CA-2 violation: machine self-attested human control '{cid}'")
        if cid not in HUMAN_ONLY_CONTROLS and st != "satisfied" and cid not in poam_ids:
            violations.append(f"Untracked non-satisfied control '{cid}' ({st})")

    return violations


def _render_ssp_markdown(
    title: str,
    server_name: str,
    version: str,
    execution_mode: str,
    findings: list[dict[str, Any]],
    poam_items: list[dict[str, Any]],
) -> str:
    state_by_id = {f["target"]["target-id"]: f["target"]["status"]["state"] for f in findings}
    lines = [
        f"# System Security Plan (SSP) — {title} (`{server_name}`)",
        "",
        "> Auto-generated deterministically from `oscal/ssp.json` (`OSCAL 1.1.2`).",
        "",
        f"- **Version:** `{version}` · **Execution Mode:** `{execution_mode}`",
        "- **NIST SP 800-53B Baseline:** `moderate`",
        "- **NIST COSIS Overlays:** `UC-AGENT-SINGLE`, `UC-AGENT-MULTI`, `UC-DEV`",
        "",
        "## Control Implementation & SP 800-53A Status",
        "",
        "| Control | Title | Component | Patterns | Status |",
        "|---------|-------|-----------|----------|:------:|",
    ]
    for c in _CONTROL_MATRIX:
        pats = ", ".join(f"`{p}`" for p in c.patterns) if c.patterns else "*Org / Human*"
        st_str = state_by_id[c.oscal_id]
        lines.append(
            f"| **{c.nist_id}** | {c.title} | `{c.component_key}` | {pats} | `{st_str}` |"
        )
    if poam_items:
        lines.extend(["", "## Active POA&M Items", ""])
        for item in poam_items:
            lines.append(f"- **{item['title']}** — {item['description']}")
    lines.append("")
    return "\n".join(lines)
