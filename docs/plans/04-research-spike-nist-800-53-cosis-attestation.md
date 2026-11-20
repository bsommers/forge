# Plan 04 — Research Spike: NIST SP 800-53r5 Update 1 & COSIS Use-Case Control Attestation (`Milestone M3.5`)

- **Status:** `open` *(Immediate Next Milestone ahead of `M4`)*
- **GitHub Milestone:** [`M3.5: Research Spike — NIST SP 800-53r5 Upd1 & COSIS Control Attestation`](https://github.com/bsommers/forge/milestone/4)
- **Companion Controls Repo:** [`bsommers/security-controls`](https://github.com/bsommers/security-controls) (`Milestone M1` Research Spike)
- **Companion Patterns Repo:** [`bsommers/secure-design-patterns`](https://github.com/bsommers/secure-design-patterns) (`MCP-001`–`MCP-008`)
- **Companion OSCAL SSP + OPA/Rego Assurance Hub:** [`bsommers/security-assurance`](https://github.com/bsommers/security-assurance) (Live reference OSCAL `1.1.2` SSP/SAR/POA&M + 3 Rego v1 policy suites for `acme-incidents`)

[← Back to Roadmap](../ROADMAP.md) · [Secure Design Patterns](../SECURE_DESIGN_PATTERNS.md) · [← Back to Project README](../../README.md)

---

## 1. Spike Goal

Conduct a time-boxed **Research Spike** bridging **MCP Server Forge** Stage 4–5 verification outputs (`scripts/validate_mcp.py` + `forge-release-artifacts.json`) with our standalone **[`bsommers/security-controls`](https://github.com/bsommers/security-controls)** library anchored to:
1. **[NIST SP 800-53 Rev. 5, Update 1 (Final)](https://csrc.nist.gov/pubs/sp/800/53/r5/upd1/final)** (20 control families, OSCAL `1.1.2`), and
2. **[NIST COSIS Use Cases](https://csrc.nist.gov/projects/cosis/use-cases)** (*SP 800-53 Control Overlays for Super Intelligence Systems*: `UC-GEN`, `UC-PRED`, `UC-AGENT-SINGLE`, `UC-AGENT-MULTI`, `UC-DEV`).

---

## 2. Research Questions & Hypotheses

| ID | Question | Falsifiable Hypothesis | Exit Artifact |
|----|----------|------------------------|---------------|
| **S1.1** | Which `UC-AGENT-SINGLE`, `UC-AGENT-MULTI`, and `UC-DEV` controls can Stage 5 attest deterministically without human review? | Technical controls (`AC-6`, `AC-6(1)`, `AC-6(10)`, `CM-2`, `CM-5`, `CM-7`, `SA-8`, `SA-11`, `SC-5`, `SC-7`, `SC-39`, `SI-7(1)`, `SI-10`, `SR-3`) map 1:1 to deterministic Stage 1–4 gates, while organizational controls (`AT-3`, `PE-3`, `PM-9`, `PS-6`) must emit `human_attestation_required`. | `forge-oscal-assessment.json` prototype |
| **S1.2** | How do `M4` wild-OpenAPI & dual-axis bounding upgrades (`W4.1`–`W4.4`) change control satisfaction under SP 800-53A? | Without `W4.4` cardinality slicing, `SC-5` (*Denial-of-Service Protection*) is only `partially-satisfied` against high-cardinality short-string arrays; `W4.4` closes `SC-5` to `satisfied`. | Pre/post `M4` control delta matrix |
| **S1.3** | Can `forge-release-artifacts.json` embed a valid NIST OSCAL `1.1.2` `component-definition` / `assessment-results` block with zero external runtime dependencies? | Using `security-controls`'s UUIDv5 deterministic OSCAL emitter adds `< 25 ms` to Stage 5 and validates cleanly against NIST's official `oscal_complete_schema.json`. | ADR + Go/No-Go gate before `M4` |

---

## 3. Spike Tasks & Verification

1. **Task 1 (`RS-1` / `RS-3` in `security-controls`):** Validate full `usnistgov/oscal-content` SP 800-53r5 catalog indexing (`< 150 ms`) and verify exported COSIS profiles against NIST's official `oscal_profile_schema.json`.
2. **Task 2 (`S1.1`–`S1.3` in `forge`):** Prototype a deterministic Stage 5 `--emit-oscal` flag mapping the 5-gate verifier results + `MCP-001..008` controls to NIST COSIS `UC-AGENT-SINGLE` + `UC-DEV` overlays, with zero LLM self-grading.
3. **Task 3 (Decision Gate):** Record findings in an ADR and feed exact `SC-5` / `SI-10` / `CM-7` acceptance assertions directly into **Milestone M4 (`Plan 03`)**.
