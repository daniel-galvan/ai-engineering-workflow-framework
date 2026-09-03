---
title: Compact Sentry Work Record
version: 0.4.16
status: Pilot
---

# Engineering Work Record

# Work Item

| Field | Value |
| --- | --- |
| ID | |
| Title | |
| Last Updated | |

# Playbook Selection

| Primary evidence | Primary goal | Selected playbook | Closest alternative | Why this playbook |
| --- | --- | --- | --- | --- |
| | | Sentry Issue Remediation | | |

# Input Register

| Input ID | Input or artifact | Source or path | Authority | Status |
| --- | --- | --- | --- | --- |
| | | | | |

# Repository Evidence Eligibility

| Repository role | Declared path | Resolved path | Branch / detached | Full revision | Clean status | User-selected ref | Release mapping | Evidence eligibility |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Execution | | | | | | | | |

# Run and Evaluation Identity

| Field | Value |
| --- | --- |
| Run ID | |
| Evaluation run ID | Not applicable |
| Playbook / version | playbooks/sentry_issue_remediation.md / 0.4.16 |
| Framework commit / status | |
| Plugin package / version | |
| Provider/runtime configuration | Not provided |
| Provider configuration source/status | |
| Prompt template / revision / conformance | templates/sentry_issue_run_prompt.md / 0.4.16 / pending |
| Role-policy baseline ID | |
| Role binding manifest | role_bindings.json |
| Provider / model configuration | Codex / Worker Execution Ledger |
| Coordinator model/effort | Active parent-session model / effort |
| Requested profile | standard |
| Activated profile | None |
| Executed profile | None |
| Profile status | requested |
| Lifecycle | planning |
| State | intake |
| Engineering state | unknown |
| Workflow outcome | incomplete |
| Engineering outcome | partially_solved |
| Current stage | initialization |
| Internal owner | Coordinator |
| Next-action owner | Coordinator |
| User action | Nothing technical. |
| Next action | Activate evidence-topology. |

# Run Isolation and Finalization

| Field | Value |
| --- | --- |
| Concurrent-run decision | |
| Active related run or work item | |
| Related-run check | |
| Durable artifact root | |
| Final reconciliation | Pending |
| Finalization schema | Pending |

# Durable Artifacts

| Artifact | Path | Status | Purpose |
| --- | --- | --- | --- |
| Role bindings | `role_bindings.json` | Created | Exact worker model and effort source |
| Finalization packet | `finalization_packet.json` | Pending | Structured input for deterministic terminal rendering |
| Runtime closure receipt | `runtime_closure.json` | Pending | Provider-observed handle release rows |
| Normalized evidence | `normalized_evidence.md` | Pending | Current-run evidence |
| Fix design result | `fix_design_result.json` | Pending | Canonical readiness and artifact action |

# Worker Execution Ledger

| Worker | Role | Assigned inputs | Mode | Depth | Skills | Tools | Capacity | Configured model/effort | Provider-observed model/effort | Elapsed | Wait | Usage | Depends on | Outcome | Confidence |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| | | | | | | | | | | | | | | | |

# Worker Synchronization

| Stage | Workers launched | Launch mode / exception | Worker outcomes | Results summarized | Barrier status |
| --- | --- | --- | --- | --- | --- |
| | | | | | Open |

# Worker Runtime Closure

| Run or stage | Receipt owner | Completed worker handles | Runtime status | Remaining active handles | Closure evidence or blocker |
| --- | --- | --- | --- | --- | --- |
| Current run | Coordinator | None | Pending | None | Workers not activated |

# Worker Result Summary

| Worker | Outcome | Confidence | Unique contribution | Evidence / claim refs | Uncertainties / blockers | Actual model/effort | Usage/credits |
| --- | --- | --- | --- | --- | --- | --- | --- |
| | | | | | | | |

# Evidence

| Evidence ID | Source | Summary | Confidence | Uncertainty | Status |
| --- | --- | --- | --- | --- | --- |
| | | | | | |

# Claims

| Claim ID | Claim | Evidence refs | Confidence | Uncertainty | Status |
| --- | --- | --- | --- | --- | --- |
| | | | | | |

# Decision Log

| Decision ID | Decision | Claim refs | Owner | Status |
| --- | --- | --- | --- | --- |
| | | | | |

# Action Log

| Action ID | Action | Decision ref | Owner | Status |
| --- | --- | --- | --- | --- |
| | | | | |

# Final Handoff

```text
Workflow result: Pending

- State: intake
- Workflow outcome: incomplete
- Engineering outcome: partially_solved
- Implementation plan: omitted; investigation is incomplete

What we established:
- Pending current-run evidence.

Next action:
- Owner: Coordinator
- Action: Activate the evidence worker.
- Complete when: The worker returns a terminal result.

Artifacts:
- work_record.md

Execution: standard/planning; validation pending; workers incomplete; runtime not released;
source or external changes none.
Provenance: plugin pending; framework revision pending; playbook sentry_issue_remediation 0.4.16.
```
