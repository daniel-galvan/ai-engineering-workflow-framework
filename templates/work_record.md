---

title: Engineering Work Record
version: 0.1
status: Pilot
owner: Engineering
last_updated: 2026-08-04
depends_on:

  - ../contracts/workflow_execution.md
---

# Engineering Work Record

> Living document for tracking the context, evidence, decisions, changes, issues, and next steps for a unit of engineering work.

This document should be updated continuously throughout the work.

It is intended to allow another engineer (or AI assistant) to resume the work with minimal additional context.

---

# Work Item

| Field | Value |
| --- | --- |
| Identifier | |
| Source system | Jira / GitHub Issues / Linear / Markdown / Manual |
| Title | |
| Type | Story / Bug / Task / Incident / Upgrade / Migration / Vulnerability / Other |
| Source repository | |
| Destination repository | |
| Branch or change reference | |
| Requesting team or owner | |
| Work owner | |
| Started | |
| Last Updated | |

---

# Objective

Describe the desired outcome of the work.

Examples:

* Triage a reported issue.
* Extract a service into a new repository.
* Identify and fix the root cause of a production issue.
* Deliver a new feature.
* Assess a dependency, code, infrastructure, or data change.

Record explicit non-goals when the work could expand into adjacent work.

---

# Workflow State

| Field | Value |
| --- | --- |
| Playbook | |
| Requested profile | Standard / Deep |
| Executed profile | Standard / Deep / Not executed |
| Profile status | Requested / In progress / Executed / Not executed / Blocked |
| Lifecycle | Planning / Remediation |
| Mode | Discovery / Investigation / Delivery / Stabilization / Review |
| Effort | Quick / Standard / Deep |
| State | Intake / Classified / In Progress / Awaiting Input / Blocked / Ready for Implementation / Implementation / Validation / Completed |
| Outcome | In progress / Completed / No action / Duplicate / Not a bug / Deferred |
| Current stage | |
| Current owner | |
| Next action | |

Use the lifecycle and outcome terms from `../contracts/workflow_execution.md`.

# Durable Artifacts

When the selected playbook requires an implementation plan, planning runs that
reach `ready_for_implementation` must produce and link it. The plan is the
execution source for a later session; this work record remains the context,
evidence, decision, and worker ledger.

| Artifact | Path | Status | Purpose |
| --- | --- | --- | --- |
| Implementation plan | [implementation_plan.md](implementation_plan.md) | Create only after required planning workers complete and before `ready_for_implementation`; otherwise do not create | Approved-scope implementation and validation instructions |

---

# Worker Execution Ledger

Record every worker or subagent that materially contributes to the work.

| Worker | Role | Mode | Effort | Skills | Tools | Model profile | Actual model/effort | Usage/credits | Depends on | Outcome |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| | | | | | | | | | | |

Record provider-reported usage or credits when available. Use `Unknown` when
the execution surface does not expose them; never estimate credit consumption.

# Worker Synchronization

For every stage that launches multiple workers, record the fan-in barrier.

| Stage | Workers launched | Worker outcomes | Results summarized | Barrier status |
| --- | --- | --- | --- | --- |
| | | | Yes / No | Open / Passed |

The workflow cannot be marked complete while a required worker or barrier is
still active.

For each worker, record the inputs consumed, outputs produced, approvals, and failure or blocked details in the timeline or the relevant section below.

# Worker Runtime Closure

Record the provider-handle closure barrier separately from result fan-in.
`terminal` means the result was collected; `released` means the provider no
longer counts the worker against runtime capacity.

| Run or stage | Completed worker handles | Runtime status | Remaining active handles | Closure evidence or blocker |
| --- | --- | --- | --- | --- |
| | | Pending / Released / Unknown / Blocked | | |

Do not start a new lifecycle run while the previous run has active handles.
Reuse its durable artifacts after closure; do not reuse live worker handles.

# Worker Result Summary

Record one compact result for every worker that reached a terminal outcome.
Summarize each worker's unique contribution; do not copy full reports here.

| Worker | Outcome | Unique contribution | Evidence or artifact | Uncertainties / blockers | Actual model/effort | Usage/credits |
| --- | --- | --- | --- | --- | --- | --- |
| | | | | | | |

The final handoff should present the shared outcome first and this worker
summary second. Use `Unknown` for unavailable model, token, or credit data.

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

Document assumptions separately from facts.

Each assumption should eventually be:

* Verified
* Refuted
* Removed

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

| Claim or observation | Source | Observed at | Worker | Status | Notes |
| --- | --- | --- | --- | --- | --- |
| | | | | Verified / Inferred / Hypothesized / Contradicted / Unknown | |

Include links to:

* Jira
* Pull requests
* Documentation
* Logs
* Screenshots
* Scanner reports

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

Use this section when a decision remains after bounded discovery. The workflow
state is `awaiting_input` with reason `clarification_required`, unless a true
external blocker prevented research or option framing.

| Decision needed | Evidence researched | Feasible options and tradeoffs | Recommendation | Smallest question and owner |
| --- | --- | --- | --- | --- |
| | | | | |

Do not use a clarification brief to invent requirements or authorize an
implementation plan.

---

# Decision Log

| Date | Decision | Evidence | Reason |
| ---- | -------- | -------- | ------ |
|      |          |          |        |

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
