---

title: Engineering Work Record
version: 0.5.4
status: Pilot
owner: Engineering
last_updated: 2026-10-08
depends_on:

  - ../contracts/workflow_execution.md
  - ../contracts/claims.md
---

# Engineering Work Record

> Living document for tracking context, evidence, decisions, changes, issues, and next steps for a unit of engineering
> work.

This document should be updated continuously throughout the work.

It is intended to allow another engineer (or AI assistant) to resume the work with minimal additional context.

---

# Work Item

| Field | Value |
| --- | --- |
| Identifier | |
| Source system | Jira / GitHub Issues / Linear / Markdown / Manual |
| Title | |
| Type | Story / Bug / Task / Incident / Upgrade / Vulnerability / Other |
| Execution repository | |
| Source repository | |
| Destination repository | |
| Branch or change reference | |
| Requesting team or owner | |
| Work owner | |
| Started | |
| Last Updated | RFC 3339 timestamp of this record's most recent durable change |

---

# Playbook Selection

Record this before activating the worker graph. It explains the classification; it is not another user input or
approval.

| Primary evidence | Primary goal | Selected playbook | Closest alternative | Why this playbook |
| --- | --- | --- | --- | --- |
| | | | | |

---

# Objective

Describe the desired outcome of the work.

Examples:

* Triage a reported issue.
* Identify and fix the root cause of a production issue.
* Deliver a new feature.
* Assess a dependency, code, infrastructure, or data change.

Record explicit non-goals when the work could expand into adjacent work.

---

# Input Register

Record every material user-supplied input before workers use it. Historical
plans, work records, and worker conclusions are supporting evidence unless the
current run explicitly adopts them as a decision. Do not promote a hypothesis
to an authority or approval gate.
Worker outputs cite the provider worker/result handle joined by the Coordinator at fan-in; framework preflight evidence
cites the Coordinator/provider observation. Reserve `Current user` for inputs actually supplied by the user.

| Input ID | Input or artifact | Source or path | Classification | Authority | Status / worker |
| --- | --- | --- | --- | --- | --- |
| IN-001 | | | Decision / Constraint / Observation / Hypothesis / Artifact / Conflict | Current user decision / Approved decision / Supporting evidence | Assigned / Consumed / Unavailable / Conflicting / Out of scope |

---

# Asset Inventory and Review

Link `asset_manifest.json` and summarize the asset gate, material findings, and unresolved limitations.
Keep individual inventory and review rows in the manifest.
The manifest still records `inventory_complete`, `all_assets_accounted_for`, `all_available_assets_reviewed`,
`all_material_assets_linked`, and `reviewed_before_plan`; unavailable, permission-denied, or unreviewed assets remain
explicit limitations. Material assets require evidence references in the approved plan.

# Path Verification

Before reporting that an explicitly named repository, provider configuration, artifact, or evidence path is absent,
record a direct path check. Include hidden entries and symlinks when inspecting directories, and verify symlink targets.
An empty filtered search is not evidence that a path is absent.

| Path | Purpose | Expected type | Observed status | Symlink/content check | Checked at | Evidence or command |
| --- | --- | --- | --- | --- | --- | --- |
| | | File / Directory / Symlink / Other | Exists / Absent / Empty / Inaccessible / Broken symlink / Unknown | | | |

---

# Repository Baseline

Record relevant repository revisions and evidence eligibility; retain full checkout observations in the packet.

| Repository role | Declared path | Full revision | Evidence eligibility |
| --- | --- | --- | --- |
| | | | |

# Run Summary

| Field | Value |
| --- | --- |
| Run ID | |
| Playbook / version | Canonical playbook path / independent document version |
| Framework commit / status | Full Git commit / Clean or Dirty |
| Plugin package / version | Installed plugin name/version, or `Not applicable` for manual runs |
| Requested profile | `standard` / `deep` |
| Executed profile | `standard` / `deep` / `None` |
| Lifecycle | `planning` / `remediation` |
| State | `intake` / `classified` / `in_progress` / `awaiting_input` / `blocked` / `ready_for_implementation` / `implementation` / `code_review` / `validation` / `handoff` / `completed` |
| Engineering state | `unknown` / `understood` / `designed` / `approved` / `implemented` / `validated` / `released` / `stabilized` / `not_applicable` |
| Workflow outcome | `completed` / `incomplete` / `blocked`; process result, not engineering correctness |
| Engineering outcome | `solved` / `partially_solved` / `plan_only` / `blocked` / `incorrect` |
| Current stage | |
| Internal owner | Person, team, worker, or runtime responsible for the workflow state |
| Next-action owner | Person, team, worker, or operator able to complete the next action |
| User action | What the user needs to do, or `Nothing technical.` |
| Next action | |
| Runtime status | Pending / Released / Terminal / Blocked |

# Workflow Receipts

Keep operational details in `finalization_packet.json`, `role_bindings.json`, `runtime_closure.json`, and
`run_inputs.json`. Keep asset inventory in `asset_manifest.json` when required. Evaluation and timing details belong
only in the optional `evaluation_work_record_addendum.md` for an explicitly declared evaluation or benchmark.

The finalizer publishes a normalized `finalization_snapshot.<sha256>.json` and links it from the terminal record.
That snapshot preserves provider configuration, repository eligibility, worker assignments, synchronization,
finalization, and runtime observations without repeating their full tables here. Source receipts remain required.
Configured model/effort and Provider-observed model/effort remain distinct in the packet; self-reported model values
are not provider telemetry. Each worker receives a compact manifest for every assigned Input ID in its activation
packet, including its value, source, authority, and expected use.

Do not edit generated terminal records. Update the source packet and receipts, then rerun the finalizer. Existing
records with full operational tables remain valid under the legacy checks; do not rewrite historical records.

# Durable Artifacts

When the selected playbook requires an implementation plan, planning runs that reach `ready_for_implementation` must
produce and link it. The plan is the execution source for a later session; this work record remains the context,
evidence, and decision record; operational ledgers live in the linked snapshot.

When the selected playbook requires a different terminal artifact, add that artifact as a current-run root file and
follow the playbook's plan-creation rule. Technical Spike requires `spike_report.md` and prohibits
`implementation_plan.md`. Feature Delivery specification assessment requires `specification_assessment.md` for ready
and not-ready results and prohibits an implementation plan in that assessment run.

| Artifact | Path | Status | Purpose |
| --- | --- | --- | --- |
| Implementation plan | [implementation_plan.md](implementation_plan.md) | Create only after required planning workers complete and before `ready_for_implementation`; otherwise do not create | Approved-scope implementation and validation instructions |

For multiple findings, distinguish finding identity from remediation identity. Assign one `change_set_id` and one
implementation plan when affected files, intended changes, validation, owner, rollout, and rollback are the same.

| Change set ID | Findings / work items | Affected files | Intended change | Validation | Owner | Plan path |
| --- | --- | --- | --- | --- | --- | --- |
| | | | | | | |

---

# Delivery Activation Gate

Summarize implementation approval and activation readiness, with references to the approved plan and packet.
Keep the detailed barrier checks in the operational artifacts; required delivery gates still apply.

# Implementation Conformance Check

Link the Implementer's plan-conformance manifest and summarize any approved-scope conflict or blocker.
An unmapped change or replacement of the approved design still requires `replanning_required` before editing.

# Worker Result Summary

Record one compact result for every worker that reached a terminal outcome. Summarize each worker's unique contribution;
do not copy full reports here.

| Worker | Outcome | Confidence | Unique contribution | Evidence / claim refs | Uncertainties / blockers |
| --- | --- | --- | --- | --- | --- |
| | | | | | |

The final handoff presents the shared outcome; this worker summary retains each contribution and its limitations.
Keep model, token, and credit details in the packet.

# Final Handoff

```text
Workflow result: <plain-language outcome>

- State: <canonical state>
- Engineering state: <unknown | understood | designed | approved | implemented | validated | released | stabilized | not_applicable>
- Workflow outcome: <completed | incomplete | blocked>
- Engineering outcome: <solved | partially_solved | plan_only | blocked | incorrect>
- Implementation plan: <created path, or omitted and why>

What we established:
- <major verified finding>

Next action:
- Owner: <person or team able to act>
- Action: <specific evidence, decision, or implementation>
- Complete when: <observable completion condition>

Artifacts:
- <links>

Execution: <profile/lifecycle>; validation <result>; workers <complete/incomplete>;
runtime <released/not released>; source or external changes <none/summary>.
Provenance: plugin <package and version, or Not applicable>; framework revision <Git SHA> (<clean/dirty>);
playbook <name and independent document version>.
```

---

Evaluation runs append the separate evaluation addendum only when explicitly declared; see
`../frameworks/experimental/workflow_evaluation.md`.

---

# Work Summary

Provide a concise summary of the current understanding.

This section should allow someone to understand the work in approximately one minute.

---

# Facts

Document only verified facts.

Examples:

* Observed behavior
* Confirmed package versions
* Confirmed code paths
* Scanner output
* Repository state

Avoid interpretations.

---

# Assumptions

Material assumptions are claims with `status: assumed`, not facts. Record the same claim ID in the Claims table and use
this table to make their validation visible during planning, remediation, and recovery.

| Claim ID | Assumption | Owner | Impact if wrong | Validation method | Status |
| --- | --- | --- | --- | --- | --- |
| | | | | | Assumed / Supported / Contradicted / Unknown |

Non-material working assumptions may remain in analysis notes.

---

# Unknowns

List unanswered questions that may affect the work.

Examples:

* Missing documentation
* Unknown runtime behavior
* Pending validation
* External dependencies

---

# Evidence

| Evidence ID | Observation | Source | Observed at | Worker | Status | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| | | | | | Verified / Inferred / Hypothesized / Contradicted / Unknown | |

Include links to:

* Jira
* Pull requests
* Documentation
* Logs
* Screenshots
* Scanner reports

Use the IDs and relationships from [`../contracts/claims.md`](../contracts/claims.md).

# Claims

| Claim ID | Statement | Evidence refs | Confidence | Uncertainties | Status | Assumption owner | Impact if wrong | Validation method |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| | | | High / Medium / Low / Unknown | | Supported / Inferred / Hypothesized / Assumed / Contradicted / Unknown | Required for Assumed | Required for Assumed | Required for Assumed |

# Action Log

| Action ID | Decision ref | Action | Owner | Required gate | Status |
| --- | --- | --- | --- | --- | --- |
| | | | | | Proposed / Approved / In Progress / Completed / Blocked / Cancelled |

---

# Analysis

Summarize what the evidence currently suggests.

Include:

* Supporting evidence
* Contradicting evidence
* Confidence level

If multiple hypotheses exist, describe them.

---

# Alternatives Considered

| Option | Decision | Rationale |
| ------ | -------- | --------- |
|        |          |           |

Document every meaningful option that was considered.

## Clarification Brief

Use this section when a decision remains after bounded discovery. The workflow state is `awaiting_input` with reason
`clarification_required`, unless a true external blocker prevented research or option framing.

| Decision needed | Evidence researched | Feasible options and tradeoffs | Recommendation | Smallest question and owner |
| --- | --- | --- | --- | --- |
| | | | | |

Do not use a clarification brief to invent requirements or authorize an implementation plan.

---

# Decision Log

| Decision ID | Date | Question or scope | Claim refs | Options considered | Selected option | Rationale | Decision owner | Approval type | Approval |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| | | | | | | | | Scope / Design / Implementation / Release / Not required | Pending / Approved / Rejected / Not required |

This section should explain **why** decisions were made.

---

# Risks

Document known risks.

Examples:

* Regression risk
* Operational risk
* Security risk
* Deployment risk

---

# Errors and Blockers

Record execution errors, missing inputs, permission problems, environment failures, and external blockers.

| Date | Worker or stage | Problem | Impact | Recovery or next action | Status |
| --- | --- | --- | --- | --- | --- |
| | | | | | Open / Resolved / Accepted |

---

# Validation Plan

Describe how the recommendation will be validated.

Examples:

* Unit tests
* Integration tests
* Manual verification
* Security validation
* Performance testing

---

# Outcome / Recommendation / Closure

Describe the result of the work, including a recommendation when implementation is still pending.

Explain:

* Why it is recommended.
* Why alternatives were rejected.
* Expected impact.
* Expected risks.

If the work is not implemented, record the closure reason explicitly:

* No action required
* Duplicate
* Not a bug
* Insufficient information
* Deferred
* Blocked

---

# Open Follow-up Work

List remaining work.

Examples:

* Additional testing
* Follow-up tickets
* Technical debt
* Monitoring improvements

---

# Approvals and Handoffs

| Date | Decision or handoff | From | To | Approval or evidence | Status |
| --- | --- | --- | --- | --- | --- |
| | | | | | Pending / Accepted / Rejected |

---

# References

Related resources.

Examples:

* Jira tickets
* Documentation
* Architecture diagrams
* Previous investigations
* CVEs
* Advisories

---

# Work Timeline

Maintain a chronological log of meaningful progress.

| Date | Stage or worker | Activity | Result or artifact |
| --- | --- | --- | --- |
| | | Work started | |
