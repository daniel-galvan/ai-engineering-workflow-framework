---
title: TechOps Issue Remediation Playbook
version: 0.5.20
status: Pilot
maturity: exercising
supported_lifecycles: planning, remediation
exercise_scope: standard + planning; deep + planning; standard + remediation; deep + remediation
exercise_status_standard_planning: exercised
exercise_status_deep_planning: pending
exercise_status_standard_remediation: exercised
exercise_status_deep_remediation: pending
validation_summary: prior exercise scope retained; tiered Jira retrieval not live-validated
owner: Engineering
last_updated: 2026-10-08
depends_on:
  - ../contracts/workflow_execution.md
  - ../contracts/claims.md
  - ../integrations/jira.md
  - ../frameworks/investigation.md
  - ../strategies/collaborative.md
  - ../skills/work_item_context.md
  - ../skills/failure_diagnosis.md
  - ../templates/work_record.md
  - ../templates/implementation_plan.md
  - ../templates/techops_issue_run_prompt.md
  - ../examples/techops_issue_remediation.md
---

# TechOps Issue Remediation

> Turn a support- or operations-reported Jira issue into an evidence-backed
> diagnosis, minimal remediation plan, and approved delivery workflow.

## Use When

Use this playbook for TechOps or comparable Jira issues reported through Zendesk, Help Desk, operations, or support
channels when the primary evidence is the issue report, comments, attachments, logs, payloads, screenshots, or
recordings.

Do not use it when Sentry is the primary evidence source, the issue is a security finding, or the work is a planned
feature within an initiative. Use the more specialized playbook.

## Inputs and Evidence

Required inputs:

- Jira issue and comments;
- execution repository; and
- known repository, system, owner, or reproduction hints when available.

Optional evidence includes attachments, screenshots, recordings, transcripts, JSON, logs, traces, exports, prior
incidents, dashboards, runbooks, pull requests, and related resolved tickets.

The evidence question is what reported behavior diverges from the current implementation. Read the exact issue and
report-bearing comments; recover parent/hierarchy only for unresolved scope or dependencies, links for a named prior
fix or shared failure path, and changelog for status/delivery conflicts. Select attachments or remote links when the
report references them or they can resolve the diagnosis. A self-contained bug does not require a sibling roster.
Record each expansion reason and stop when the report, failure boundary, and material constraints are established.

`issue-evidence` owns evidence normalization. Record each artifact's source, timestamp when available, redaction status,
and limitations. Treat an attachment as evidence, not proof of current code or runtime behavior.

## Default Execution

- Execution profile: `standard`
- Lifecycle: `planning`
- Mode: `investigation`

Planning is read-only. It creates `implementation_plan.md` only after required fan-in passes and the diagnosis explains
the reported symptom. The shared contract owns lifecycle, approvals, state transitions, recovery, fan-in, and runtime
closure.

Use [`../templates/techops_issue_run_prompt.md`](../templates/techops_issue_run_prompt.md) for every run.

## Execution Profiles and Lifecycle

| Profile | Use when | Planning behavior |
| --- | --- | --- |
| `standard` | Detailed report, one credible system or repository, and bounded failure path | Normalize issue evidence, trace reproduction/signals and the first concrete divergence, design the smallest fix, and document the plan. Repository integration is conditional. |
| `deep` | Cross-repository ownership, unclear first-loss point, intermittent behavior, data/security risk, disputed diagnosis, or non-trivial rollout | Adds mandatory repository integration and independent planning review. |

| Lifecycle | Behavior |
| --- | --- |
| `planning` | Investigate, diagnose, and design; stop at `ready_for_implementation` without source or external-system changes. |
| `remediation` | Execute the approved plan through implementation, Code Review, validation, stabilization, and handoff. |

## Worker Graph

The Coordinator performs initialization directly; never activate or delegate an `initialize` worker.
Activate one final Documenter after analytical fan-in.

| Worker | Role | Skills | Tools | Activation / dependency |
| --- | --- | --- | --- | --- |
| `issue-evidence` | `current_state_investigator` | `work_item_context`, `repository_exploration`, `failure_diagnosis` | `work_item_read`, `repository_read`, `repository_search`, `history_read`, `runtime_observe`, `artifact_write` | Required; after Coordinator initialization |
| `failure-path` | `dependency_analyst` | `failure_diagnosis`, `dependency_mapping`, `architecture_mapping` | `repository_read`, `repository_search`, `history_read`, `dependency_inspect`, `artifact_write` | Required; after `issue-evidence` |
| `repository-integration` | `repository_integrator` | `destination_integration`, `architecture_mapping`, `operational_readiness` | `repository_read`, `repository_search`, `history_read`, `artifact_write` | Required for `deep`; conditional for `standard`; after `issue-evidence` |
| `fix-design` | `solution_architect` | `failure_diagnosis`, `architecture_mapping`, `workflow_planning` | `artifact_write`, `work_record_write` | After `failure-path` and any required integration analysis |
| `planning-review` | `reviewer` | `architecture_mapping`, `operational_readiness` | `repository_read`, `diff_review`, `artifact_write` | Deep only; after `fix-design` |
| `implement` | `implementer` | `failure_diagnosis`, `build_and_test` | `repository_read`, `repository_write`, `build_run`, `test_run`, `work_record_write` | Remediation only; approval plus completed planning fan-in |
| `review` | `reviewer` | `architecture_mapping`, `build_and_test`, `operational_readiness` | `repository_read`, `diff_review`, `test_run`, `artifact_write` | After `implement` |
| `validate` | `tester` | `build_and_test`, `operational_readiness` | `build_run`, `test_run`, `runtime_observe`, `artifact_write` | After `review` |
| `handoff` | `documenter` | `work_record_maintenance` | `work_record_read`, `work_record_write`, `artifact_write` | Required once after applicable fan-in |

Required planning workers:

- `standard`: `issue-evidence`, `failure-path`, `fix-design`, and final `handoff`; add
  `repository-integration` when the report crosses a repository, service, deployment, ownership, or public-contract
  seam.
- `deep`: all standard workers plus mandatory `repository-integration` and `planning-review`.

The remediation sequence is `implement` ↔ `review` → `validate` → `handoff`.

## Worker Ownership and Non-duplication

- `issue-evidence` owns raw Jira, attachment, support, and prior-issue evidence.
- `failure-path` owns reproduction status, triggering conditions, competing hypotheses, first concrete divergence, and
  affected-codebase analysis.
- `repository-integration` owns cross-repository, deployment, runtime, and ownership reconciliation when activated.
- `fix-design` owns the smallest supported fix, regression-test strategy, validation plan, and rollback considerations.
- `planning-review` independently challenges diagnosis, scope, risk, and validation only for `deep`.
- `handoff` persists result envelopes, confidence, claims, decisions, actions, usage, and next action.

Downstream workers consume normalized artifacts. They repeat evidence or repository analysis only to resolve a recorded
discrepancy.

Start independent `failure-path` and conditional `repository-integration` work after `issue-evidence`; for `deep`,
dispatch in parallel is required unless a runtime or evidence dependency prevents it. Record the actual dependency when
integration must consume a completed failure-path result.

## Stages and Gates

### Stage 0 — Initialize

Create or recover:

```text
<execution-repository>/.thoughts/<WORK-ITEM-ID>/work_record.md
```

Record the issue, profile, lifecycle, execution repository, known systems, artifact locations, constraints, and explicit
non-goals. Do not create an implementation plan during initialization.

### Stage 1 — Normalize the Report

Read the issue, comments, related resolved work, and supplied artifacts before touching code. Record reported and
expected behavior, impact, affected users or systems, evidence IDs, facts, assumptions, unknowns, and redaction limits.

Consume every supplied attachment, log, screenshot, payload, and repository
artifact before requesting clarification. Apply the shared
[Evidence-to-Hypothesis Gate](../contracts/workflow_execution.md#evidence-to-hypothesis-gate)
and preserve the exact input path or reference in the evidence record.

### Stage 2 — Reproduce and Trace the Failure Path

Attempt reproduction when safe and practical. If reproduction is unavailable, record the reason and preserve the
strongest indirect signals. Trace the entry point, services, queues, APIs, data changes, and observable result until the
first concrete divergence from expected behavior is identified or explicitly unknown.

Before returning `needs_input` or `blocked`, execute the smallest safe
reproduction or source check and record its command, symbol, inputs, and result
in `checks_performed`. For an original rule, text, and reachable Python path,
run the repository-native activity or test before requesting a production
trace. Record only genuinely unavailable or external checks in
`checks_remaining`; do not stop with only “more investigation is needed.”

When supplied production input reproduces the symptom in the reachable current
code path, treat it as the actionable diagnosis for the code being fixed. Do
not make deployed-revision mapping the next user action or a planning blocker;
record it as rollout verification unless it changes the target code, scope, or
safety decision.

When report behavior or success copy differs from the current checkout, the Failure Path worker performs the focused
history reconciliation in `failure_diagnosis`. Compare prior fixes with the current acceptance criteria; a prior fix
may be modified when necessary. Keep the original reported cause and the current acceptance gap separate. The run owns
any resulting diagnosis/plan correction; do not create a separate user task or approval gate for this investigation.

### Stage 3 — Reconcile Ownership and Design the Fix

Confirm the owning repository, module, service, and blast radius. Run Repository Integrator when the profile requires
it. Compare plausible causes, record supporting and contradictory evidence, and select the smallest fix that addresses
the supported cause rather than only the symptom.

The fix-design result must include consumed inputs, confirmed facts, ranked
causes when alternatives are credible, evidence references, confidence,
`checks_performed`, `checks_remaining`, remediation options, recommendation,
and a plain-language next action. The Coordinator rejects a clarification
result that omits an available local check or reports only a proposed check.

If a product or operational decision remains, perform bounded discovery, record feasible options and a recommendation,
then use `awaiting_input` with a Clarification Brief. Do not create an implementation plan until that decision is
resolved.

### Stage 4 — Review, Plan, and Handoff

For `deep`, the Planning Reviewer independently challenges the diagnosis and design. After required worker envelopes,
fan-in, and planning gates pass, the Documenter creates:

```text
<execution-repository>/.thoughts/<WORK-ITEM-ID>/implementation_plan.md
```

The accepted Fix Design result supplies four evidence-backed `techops_checks` rows: `issue_scope`,
`history_reconciliation`, `plan_dependencies`, and `regression_fixture`. Preparation delivers these requirements in the
worker activation packets; the Coordinator verifies the evidence and the finalizer rejects missing or failed checks.
Use `Status: passed`, except `not_applicable` for history when evidence establishes no report/current-code mismatch.
Each row includes `Evidence refs` and `Detail`; a commit listing alone does not pass history reconciliation.
A passed history row records `Commit`, `Patch evidence refs`, `Work item`
and `Work item evidence refs`; inspect the associated work item, not only its key in the commit message.

The Documenter contract assigns both `implementation_plan.md` and `finalization_packet.json`. TechOps readiness comes
from accepted planning checks and the Coordinator packet; it does not require Sentry disposition fields.

Read existing fixtures before choosing a regression strategy. Include any seed, state, fresh-read, delayed-response or
error support that the proposed test needs. Local regression work must not depend on unavailable deployed revisions
unless those revisions change its target, scope or safety; explain such a dependency in the plan. Runtime evidence gates
production resolution and decisions that actually require it, and may proceed alongside independent local work.

The plan records the diagnosis, evidence/claim/decision IDs, change and test steps, validation ladder, risks, rollback,
monitoring, ownership, and residual uncertainty. It is not authorization to make changes.

Apply the shared [planning-readiness rule][planning-readiness]. Remaining code, dependency, configuration, test,
environment, operational, rollout, or validation work belongs in the plan when a feasible sequence exists; it is not a
planning blocker by itself.

### Stage 5 — Approved Remediation

Explicit approval and remediation re-entry activate `implement`, `review`, and `validate` before source changes, then
activate the final `handoff` after delivery fan-in. In-scope review findings return to `implement` for repair and
re-review; they are not a new approval gate or final handoff.

### Stage 6 — Stabilize and Hand Off

Record validation, release or rollback actions, monitoring, owner, residual risk, and next action. Close worker handles
only after terminal envelopes and artifacts are preserved.

## Gates

| Gate | Pass condition |
| --- | --- |
| Report understood | Reported behavior, evidence, limits, and unknowns are recorded. |
| Failure path understood | Reproduction status and first concrete divergence are supported or explicitly unavailable. |
| Ownership reconciled | Owning repository/system and affected surface are supported. |
| Fix design ready | The recommended fix explains the evidence and includes regression and validation strategy. |
| Implementation ready | Shared semantic readiness threshold and planning fan-in passed; `implementation_plan.md` exists. |
| Approval ready | Explicit implementation approval and remediation re-entry are recorded. |
| Validation ready | Code Review is accepted and declared validation results are preserved. |
| Handoff ready | Release, rollback, monitoring, ownership, residual risk, and next action are explicit. |

## Required Handoff Output

Report:

1. issue summary, verified symptom, impact, and current outcome;
2. evidence, reproduction status, root path, first divergence, and ownership;
3. supported diagnosis, confidence, uncertainties, and considered alternatives;
4. implementation-plan path/status, change, regression, validation, rollback, and monitoring plan;
5. requested, activated, and executed profile, fan-in, and runtime-closure status; and
6. residual risks, owner, and next action. The next action must name the owner,
   location, and completion condition in plain language.

Workflow result must summarize the investigation's findings, proposed disposition/change and main limitation in
plain English. A readiness/state token such as ready_for_implementation is not a work summary; use the distinct state
fields for readiness. Finalization failure must still preserve recorded findings, confidence/alternatives, the plan
and engineering next step in the canonical provisional failure report, without claiming those records are validated.
Activation or Documenter failure also requires terminal reporting. Use the packaged finalizer's `--workflow-failure`
mode; it preserves recorded analytical content in `handoff_failure.md` even when Documenter never populated `handoff`.
A failed activation does not automatically require repeating the investigation. Keep provider turn status, task
completion, engineering readiness and runtime closure separate.

Use the shared canonical Human-Readable Handoff template. Detailed worker results remain in the work record.

## Related Documents

- [`../integrations/jira.md`](../integrations/jira.md)
- [`../templates/techops_issue_run_prompt.md`](../templates/techops_issue_run_prompt.md)
- [`../templates/work_record.md`](../templates/work_record.md)
- [`../templates/implementation_plan.md`](../templates/implementation_plan.md)
- [`../examples/techops_issue_remediation.md`](../examples/techops_issue_remediation.md)

[planning-readiness]: ../contracts/workflow_execution.md#planning-readiness-and-implementation-work
