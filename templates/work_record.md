---

title: Engineering Work Record
version: 0.4.15
status: Pilot
owner: Engineering
last_updated: 2026-08-27
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
Worker outputs cite the provider worker/result handle; framework preflight evidence cites the Coordinator/provider
observation. Reserve `Current user` for inputs actually supplied by the user.

| Input ID | Input or artifact | Source or path | Classification | Authority | Status / worker |
| --- | --- | --- | --- | --- | --- |
| IN-001 | | | Decision / Constraint / Observation / Hypothesis / Artifact / Conflict | Current user decision / Approved decision / Supporting evidence | Assigned / Consumed / Unavailable / Conflicting / Out of scope |

---

# Path Verification

Before reporting that an explicitly named repository, provider configuration, artifact, or evidence path is absent,
record a direct path check. Include hidden entries and symlinks when inspecting directories, and verify symlink targets.
An empty filtered search is not evidence that a path is absent.

| Path | Purpose | Expected type | Observed status | Symlink/content check | Checked at | Evidence or command |
| --- | --- | --- | --- | --- | --- | --- |
| | | File / Directory / Symlink / Other | Exists / Absent / Empty / Inaccessible / Broken symlink / Unknown | | | |

---

# Repository Evidence Eligibility

Record every checkout before using its contents as evidence. An undeclared feature branch cannot establish baseline,
production, or current-main behavior.

| Repository role | Declared path | Resolved path | Branch / detached | Full revision | Clean status | Git identity | User-selected ref | Release mapping | Evidence eligibility |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Execution / Primary / Additional / Source / Destination | | | | | Clean / Dirty | | Yes / No | Verified / Unknown / Mismatch | Accepted / Caveated / Rejected |

---

# Run and Evaluation Identity

| Field | Value |
| --- | --- |
| Run ID | |
| Evaluation run ID | Explicit evaluation/benchmark runs only; otherwise `Not applicable` |
| Playbook / version | Canonical playbook path / independent document version |
| Framework commit / status | Full Git commit / Clean or Dirty |
| Plugin package / version | Installed plugin name/version, or `Not applicable` for manual runs |
| Provider/runtime configuration | Optional execution-repository `.codex/agents/` path, or `Not provided` |
| Provider configuration source/status | Resolved bundled definition or work-graph source / `resolved`, `absent`, or `blocked` |
| Prompt template / revision / conformance | Canonical path / independent document version / `pass` or `fail` with missing required fields |
| Role-policy baseline ID | Provider baseline ID or `Not applicable` |
| Role binding manifest | `.thoughts/<WORK-ITEM-ID>/role_bindings.json` or `Not applicable` for a non-Codex provider |
| Provider / model configuration | Provider name / Worker Execution Ledger |
| Coordinator model/effort | Active parent-session model / effort; do not infer from Orchestrator agent configuration |
| Requested profile | `standard` / `deep` |
| Activated profile | `standard` / `deep` / `None` |
| Executed profile | `standard` / `deep` / `None` |
| Profile status | `requested` / `in_progress` / `executed` / `not_executed` / `blocked` |
| Lifecycle | `planning` / `remediation` |
| Internal mode | `discovery` / `investigation` / `delivery` / `stabilization` / `review`; not a run input |
| Internal depth | `quick` / `standard` / `deep`; not a run input |
| State | `intake` / `classified` / `in_progress` / `awaiting_input` / `blocked` / `ready_for_implementation` / `implementation` / `code_review` / `validation` / `handoff` / `completed` |
| Engineering state | `unknown` / `understood` / `designed` / `approved` / `implemented` / `validated` / `released` / `stabilized` / `not_applicable` |
| Workflow outcome | `completed` / `incomplete` / `blocked`; process result, not engineering correctness |
| Engineering outcome | `solved` / `partially_solved` / `plan_only` / `blocked` / `incorrect` |
| Current stage | |
| Internal owner | Person, team, worker, or runtime responsible for the workflow state |
| Next-action owner | Person, team, worker, or operator able to complete the next action |
| User action | What the user needs to do, or `Nothing technical.` |
| Next action | |

# Run Isolation and Finalization

| Field | Value |
| --- | --- |
| Concurrent-run decision | Read-only shared revision / Isolated managed worktree / `run_already_active` / Not applicable |
| Active related run or work item | None / ID and artifact root |
| Related-run check | Provider-visible tasks and sibling artifact roots; method, RFC 3339 timestamp, and result / Detection unavailable |
| Durable artifact root | `.thoughts/<WORK-ITEM-ID>/` |
| Final reconciliation | Pending / Passed / Failed; state, artifacts, outcomes, and runtime closure agree |
| Finalization schema | Pending / Passed / Failed; required terminal fields and playbook artifact set are present |

Use the lifecycle, workflow-state, engineering-state, workflow-outcome, and engineering-outcome terms from
`../contracts/workflow_execution.md`. A completed worker graph awaiting evidence or a decision uses state
`awaiting_input`, workflow outcome `completed`, and engineering outcome `partially_solved`; it is not `blocked`. Use
`plan_only` only when the run produced a usable implementation plan.

# Durable Artifacts

When the selected playbook requires an implementation plan, planning runs that reach `ready_for_implementation` must
produce and link it. The plan is the execution source for a later session; this work record remains the context,
evidence, decision, and worker ledger.

| Artifact | Path | Status | Purpose |
| --- | --- | --- | --- |
| Implementation plan | [implementation_plan.md](implementation_plan.md) | Create only after required planning workers complete and before `ready_for_implementation`; otherwise do not create | Approved-scope implementation and validation instructions |

For multiple findings, distinguish finding identity from remediation identity. Assign one `change_set_id` and one
implementation plan when affected files, intended changes, validation, owner, rollout, and rollback are the same.

| Change set ID | Findings / work items | Affected files | Intended change | Validation | Owner | Plan path |
| --- | --- | --- | --- | --- | --- | --- |
| | | | | | | |

---

# Worker Execution Ledger

`Mode`, `Worker depth`, and `Capacity classification` are internal audit metadata. The user-facing run choices are
Lifecycle and Profile. Keep configured model and effort separate from provider-observed values.

Record every worker or subagent that materially contributes to the work.

| Worker | Role | Assigned inputs | Mode | Depth | Skills | Tools | Capacity | Configured model/effort | Provider-observed model/effort | Usage | Depends on | Outcome | Confidence |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| | | IN-### | | | | | | | | | | | |

Record provider-reported usage or credits when available. Use `Unknown` when the execution surface does not expose them;
never estimate credit consumption. For model and effort, retain the exact
configured binding and record provider-observed values when returned. If
applied telemetry is unavailable, use an explicit
`Not exposed; ...` marker; never relabel the
configured binding or treat a self-reported model or effort as provider-observed telemetry.
Normal runs do not collect activation or timing ledgers. Explicit evaluation or benchmark runs append
`evaluation_work_record_addendum.md`.

# Worker Synchronization

For every stage that launches multiple workers, record the fan-in barrier.

| Stage | Workers launched | Launch mode / exception | Worker outcomes | Results summarized | Barrier status |
| --- | --- | --- | --- | --- | --- |
| | | Parallel / Sequential: reason | | Yes / No | Open / Passed |

The workflow cannot be marked complete while a required worker or barrier is still active.

Before activation, record each worker's assigned Input IDs. Reconcile them with the result envelope's
`inputs_consumed`; an omitted authoritative input makes the result incomplete. Record outputs, approvals, and failure or
blocked details in the timeline or relevant section below.

Each activation packet must include a compact manifest for every assigned Input ID: short value, source, authority, and
expected use. An ID without its value is not delivered context.

# Delivery Activation Gate

For every remediation run, record this gate at re-entry. Complete the first
six checks before the first source, configuration, dependency, or
infrastructure change. A downstream worker may wait for a dependency, but it
must remain in the current run's worker execution record. Evaluate the Completion
barrier before final handoff.

| Check | Required evidence | Status |
| --- | --- | --- |
| Remediation re-entry | Re-entry with the same profile and `lifecycle: remediation` | Pending / Passed / Blocked |
| Implementation approval | Approval type, owner, scope, decision, and reference | Pending / Passed / Blocked |
| Approved plan | Existing approved `implementation_plan.md` | Pending / Passed / Blocked |
| Delivery graph | Worker IDs, roles, dependencies, and states | Pending / Passed / Blocked |
| Implementer authority | Delegated Implementer authorized for the approved scope | Pending / Passed / Blocked |
| Coordinator restriction | Coordinator does not edit or substitute for delivery workers | Pending / Passed / Blocked |
| Completion barrier | Implementer, Reviewer, Tester, Documenter, fan-in, runtime closure | Pending / Passed / Blocked |

No source change is permitted while any of the first six checks is `Pending` or
`Blocked`. A remediation run cannot be reported complete while the Completion
barrier is `Pending` or `Blocked`.

# Implementation Conformance Check

Before the first source change, the delegated Implementer records a
plan-conformance manifest. Every proposed file maps to an approved plan step,
an existing implementation or reuse target, an intended change, and validation.
Every new table, model, fixture, runtime abstraction, or dependency maps to an
explicit plan step.

| Check | Required evidence | Status |
| --- | --- | --- |
| Plan-conformance manifest | Files, plan steps, reuse targets, changes, validation | Pending / Passed / Blocked |
| Boundary compliance | No unmapped or explicitly forbidden implementation pattern | Pending / Passed / Blocked |

If the manifest exposes an unmapped change, a contradictory boundary, or a
replacement of the approved design, stop before editing with
`replanning_required`. The Reviewer checks this manifest against the current
diff before accepting the implementation.

# Worker Runtime Closure

Record the provider-handle closure barrier separately from result fan-in. `terminal` means the result was collected;
`released` means the provider no longer counts the worker against runtime capacity.
Record exact provider-returned handles and provider close/release confirmations. Role names or circular statements that
all workers were released are not closure evidence.

| Run or stage | Receipt owner | Completed worker handles | Runtime status | Remaining active handles | Closure evidence or blocker |
| --- | --- | --- | --- | --- | --- |
| | Coordinator | | Pending / Released / Unknown / Blocked | | |

Do not start a new lifecycle run while the previous run has active handles. Reuse its durable artifacts after closure;
do not reuse live worker handles.

# Worker Result Summary

Record one compact result for every worker that reached a terminal outcome. Summarize each worker's unique contribution;
do not copy full reports here.

| Worker | Outcome | Confidence | Unique contribution | Evidence / claim refs | Uncertainties / blockers | Actual model/effort | Usage/credits |
| --- | --- | --- | --- | --- | --- | --- | --- |
| | | | | | | | |

The final handoff presents the shared outcome; this worker summary remains in the durable record. Use `Unknown` for
unavailable model, token, or credit data.

# Final Handoff

```text
Workflow result: <plain-language outcome>

- State: <canonical state>
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
