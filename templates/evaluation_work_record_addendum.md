---
title: Evaluation Work Record Addendum
version: 0.1.0
status: Experimental / Deferred
owner: Engineering
last_updated: 2026-08-27
---

# Evaluation Run Continuation Ledger

Use only for an explicitly declared evaluation or benchmark run. A continuation adds only its new input IDs and worker
activity; it MUST NOT retroactively assign those inputs to an earlier activation.

| Sequence | Type | Trigger or new evidence | New input IDs | Previous terminal state | Recorded at | Outcome |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Initial / Continuation | | IN-### / None | None / state | RFC 3339 | |

# Evaluation Worker Activation Ledger

Record provider-observed actions; never reconstruct missing timestamps or counts.

| Sequence | Continuation | Worker | Provider handle | Action | Input IDs | Observed at | Outcome or error |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 1 | | | spawn / resume / send / wait / close | IN-### / None | RFC 3339 | |

## Evaluation Worker Timing Ledger

| Worker | Provider handle | Activated | Started | Terminal | Elapsed | Queue / dependency wait | Spawn attempts | Replacement or duplicate reason |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| | | | | | | | | |

# Workflow Evaluation

Complete only for the explicitly declared evaluation or benchmark run. Do not copy these fields into normal work
records.

| Complexity tags | Duration | Worker retries | Worker corrections | Review cycles | Validation failures |
| --- | --- | --- | --- | --- | --- |
| Bounded / Cross-repository / High-risk / Unknown | | | | | |

| Logical workers | Actual instances | Activation attempts | Failed spawns | Handle discrepancies | Replacement workers | Artifact count |
| --- | --- | --- | --- | --- | --- | --- |
| | | | | | | |

| Findings | Change sets | Plans | Duplicate plans |
| --- | --- | --- | --- |
| | | | |

| Human interaction | Measure | Evidence / reason |
| --- | --- | --- |
| Clarifications | Count | |
| Approvals | Count | |
| Manual corrections | Count | |
| Reruns | Count | |
| Human review effort | Minutes | |

| Control or timing measure | Measure | Evidence / reason |
| --- | --- | --- |
| Instruction violations | Count | |
| Authoritative inputs ignored | Count | |
| Supplied inputs not consumed | Count | |
| Unapproved plan deviations | Count | |
| Worker elapsed time | Per worker | Evaluation Worker Timing Ledger |
| Worker wait time | Per worker | Evaluation Worker Timing Ledger |
| Coordination errors | Count | Pre-provider command, quoting, routing, ledger, or orchestration errors and retries |
| Post-closure polls | Count | Wait or status calls after handle release |
| Handoff revisions | Count | Returns to the final Documenter after its first terminal result |
| Post-finalization Coordinator edits | Count | Direct edits after Documenter terminal; must be zero |
| Metrics status | Valid / Invalid | Timestamp, count, and timing reconciliation |

| Dimension | Rating | Evidence / notes |
| --- | --- | --- |
| Process quality | Met / Partial / Not met / Not applicable | |
| Control fidelity | Met / Partial / Not met / Not applicable | |
| Reasoning quality | Met / Partial / Not met / Not applicable | |
| Engineering quality | Met / Partial / Not met / Not applicable | |
| Efficiency | Met / Partial / Not met / Not applicable | |
| Engineering outcome | Solved / Partially Solved / Plan Only / Blocked / Incorrect | |
