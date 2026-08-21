---
title: Feature Delivery Playbook
version: 0.3.0
status: Pilot
maturity: exercising
exercise_scope: standard + planning; deep + planning; standard + remediation; deep + remediation
validation_summary: all combinations exercised; mixed reliability; not delivery-validated
owner: Engineering
last_updated: 2026-08-21
depends_on:
  - ../contracts/workflow_execution.md
  - ../contracts/claims.md
  - ../frameworks/investigation.md
  - ../strategies/collaborative.md
  - ../skills/work_item_context.md
  - ../templates/work_record.md
  - ../templates/implementation_plan.md
  - ../templates/feature_delivery_run_prompt.md
  - ../examples/feature_delivery.md
---

# Feature Delivery Playbook

> Turn a Jira feature or improvement within an active initiative into an
> evidence-backed implementation plan, then deliver it through an approved
> remediation lifecycle.

## Use When

Use this playbook for a planned new capability or improvement whose primary source is a Jira ticket. It supports tickets
that are incomplete when parent initiative context, selected sibling work, linked decisions, and repository evidence can
recover the missing context.

Do not use it for a production failure with Sentry evidence or a security finding. A feature that moves an existing
capability into an independently operated destination uses the source-to-destination scenario below.

## Default

- Execution profile: `standard`
- Lifecycle: `planning`
- Mode: `investigation`

Planning is read-only. It produces an implementation plan only when planning fan-in passes and the feature is ready for
implementation.

Use [`templates/feature_delivery_run_prompt.md`](../templates/feature_delivery_run_prompt.md) for every run. The prompt
supplies scenario inputs; this playbook owns process, worker activation, gates, and handoff behavior.

## Jira Context Recovery

The `feature-context` worker owns Jira context recovery for the run. It reads:

1. the ticket for task-specific scope and explicit requirements;
2. the immediate parent work item for the immediate outcome;
3. ancestor Stories, Epics, or Initiatives for the broader objective and sequencing;
4. selected siblings only when they share a dependency, component, release, direct link, or explicit precedent; and
5. linked documents, pull requests, and repository evidence.

Parent and sibling material is evidence, not automatic scope. The ticket's explicit requirements remain authoritative
for the ticket. Record conflicts, inferences, and unknowns in the work record.

The worker classifies context as `sufficient_for_planning`, `partially_recovered`, or `clarification_required`. A
clarification-required run may complete discovery and hand off focused questions, but it must not create
`implementation_plan.md` or claim implementation readiness.

## Execution Profiles and Lifecycle

The profile selects independent evidence and review. It does not change the model or effort assigned to a role by the
provider policy.

| Profile | Use when | Planning behavior |
| --- | --- | --- |
| `standard` | Known initiative, bounded feature, and one credible repository or component | Recovers context, maps current behavior and impact, designs the smallest feature slice, and documents the plan. Repository integration is conditional. |
| `deep` | Cross-repository work, source-to-destination delivery, unclear ownership, public contract, persistence, rollout, security, or disputed requirements | Adds mandatory repository integration and independent planning review. |

| Lifecycle | Behavior |
| --- | --- |
| `planning` | Recover context, investigate, design, and stop at `ready_for_implementation`. No source or external-system changes. |
| `remediation` | Execute the approved plan through implementation, review, validation, stabilization, and handoff. |

The valid combinations are `standard + planning`, `deep + planning`, `standard + remediation`, and `deep + remediation`.
The shared execution contract governs immutable lifecycle, approval, interrupted-run recovery, fan-in, and
worker-runtime closure.

## Continuation and Re-entry

- A planning follow-up may clarify or extend evidence but cannot implement.
- A remediation re-entry requires explicit approval, the existing work record and implementation plan, required worker
  activation, fan-in, and closure of the prior run's worker handles.
- An interrupted run uses the canonical prompt with `Interrupted profile recovery`: preserve completed artifacts,
  activate only missing required workers, and complete fan-in. A wait timeout or `running` status is not worker
  unavailability: keep the worker active and do not close it or start a replacement. For a worker confirmed stopped or
  failed, close its original handle and make one fresh replacement attempt. If it also fails, stop with the
  worker-specific runtime-unavailable reason; never substitute the Coordinator or call the requested profile successful.
- Missing approval blocks delivery workers only. It does not prevent remaining planning workers from resolving context
  or design questions.
- If the required graph cannot start, use `not_executed`. If it starts but activation, fan-in, or runtime closure
  remains incomplete, use `blocked`; it is never successful profile execution.

## Worker Graph

| Worker | Role | Skills | Tools | Activation / dependency |
| --- | --- | --- | --- | --- |
| `initialize` | `orchestrator` | `work_item_context`, `workflow_planning`, `work_record_maintenance` | `work_item_read`, `work_record_read`, `work_record_write` | First |
| `feature-context` | `current_state_investigator` | `work_item_context`, `repository_exploration`, `architecture_mapping` | `work_item_read`, `repository_read`, `repository_search`, `history_read`, `artifact_write` | Required; after `initialize` |
| `impact-analysis` | `dependency_analyst` | `dependency_mapping`, `architecture_mapping` | `repository_read`, `repository_search`, `history_read`, `dependency_inspect`, `artifact_write` | Required; after `feature-context` |
| `repository-integration` | `repository_integrator` | `destination_integration`, `architecture_mapping`, `operational_readiness` | `repository_read`, `repository_search`, `history_read`, `build_run`, `test_run`, `artifact_write` | Required for `deep`; conditional for `standard`; after `feature-context` |
| `feature-design` | `solution_architect` | `architecture_mapping`, `workflow_planning` | `artifact_write`, `work_record_write` | After `impact-analysis` and any required integration analysis |
| `planning-review` | `reviewer` | `architecture_mapping`, `operational_readiness` | `repository_read`, `diff_review`, `artifact_write` | Deep only; after `feature-design` |
| `implement` | `implementer` | `code_migration`, `build_and_test` | `repository_read`, `repository_write`, `build_run`, `test_run`, `work_record_write` | Remediation only; approval plus completed planning fan-in |
| `review` | `reviewer` | `architecture_mapping`, `build_and_test`, `operational_readiness` | `repository_read`, `diff_review`, `test_run`, `artifact_write` | After `implement` |
| `validate` | `tester` | `build_and_test`, `operational_readiness` | `build_run`, `test_run`, `runtime_observe`, `artifact_write` | After `review` |
| `handoff` | `documenter` | `work_record_maintenance` | `work_record_read`, `work_record_write`, `artifact_write` | Continuous after `initialize` |

Required worker sets:

- `standard + planning`: `initialize`, `feature-context`, `impact-analysis`, `feature-design`, and continuous `handoff`.
  `repository-integration` is added when the context crosses a repository, service, ownership, deployment, persistence,
  or public-contract seam.
- `deep + planning`: standard planning workers plus mandatory `repository-integration` and `planning-review`.
- `standard + remediation`: reuse completed standard planning artifacts, then activate `implement`, `review`,
  `validate`, and `handoff` after approval.
- `deep + remediation`: reuse completed deep planning artifacts, then activate `implement`, `review`, `validate`, and
  `handoff` after approval.

An existing capability moving into an independently operated destination always uses `deep`; it is never a standard
feature run.

The delivery sequence is `implement` ↔ `review` → `validate` → `handoff`. Do not start additional discovery workers
after approval unless new evidence contradicts the approved plan or expands scope.

## Worker Outputs and Non-duplication

- `feature-context` owns raw Jira hierarchy, sibling, linked-work, and initial repository-context recovery. Downstream
  workers consume its context artifact.
- `impact-analysis` owns dependency, data-flow, contract, and regression-scope analysis.
- `repository-integration` owns cross-repository, ownership, deployment, and operational reconciliation when activated.
- `feature-design` owns the smallest implementation design and acceptance criteria traceability.
- `planning-review` independently challenges scope, assumptions, rollout, and validation only for `deep`.
- `handoff` records all results, synchronization, model/effort, usage, credits, and next action in the durable work
  record.

For `deep`, start `impact-analysis` and `repository-integration` in parallel after `feature-context`. Each consumes the
context artifact and repeats upstream discovery only for a recorded discrepancy.

## Source-to-Destination Feature Delivery

This source-to-destination feature delivery scenario uses `deep` for moving an existing capability from a source
repository, application, or service into an independently buildable, runnable, deployable, maintainable, and owned
destination. It is still one feature delivery flow, not a separate playbook.

The run prompt MUST identify the source, destination, capability, acceptance criteria, and known runtime, deployment,
ownership, data, event, and contract constraints. The execution repository remains the durable-artifact root; source
and destination repositories are evidence and code locations, not artifact roots.

For this scenario:

- `feature-context` records the current source behavior, entry points, interfaces, tests, configuration, datastores,
  queues, events, external APIs, observability, deployment assumptions, and ownership.
- `impact-analysis` maps callers, consumers, shared code, data and event ownership, authentication, configuration,
  secrets, deployment, and rollback coupling. It classifies each dependency as move, remain external, adapt, share
  temporarily, remove, or unknown.
- `repository-integration` verifies destination conventions and runs the smallest safe build or test baseline before
  design. An unavailable baseline is not a planning blocker; a failing baseline is a plan input when its repair is
  feasible.
- `feature-design` defines the smallest independently deployable vertical slice that satisfies authoritative outcomes.
  It records the source-to-destination seam, ownership, compatibility, coexistence or cutover, rollback, and deferred
  work; it must not substitute a thin adapter or partial path for the required end state.

The implementation plan records source and destination revisions, the selected seam, every dependency disposition,
migration slices, contracts, validation, operations, coexistence or cutover, rollback, and completion criteria. During
remediation, preserve migrated behavior unless an approved feature change says otherwise. The plan-conformance manifest
must map each changed file to the approved step and reject private replacement persistence, hard-coded runtime fixtures,
parallel replacement implementations, and prohibited source dependencies.

## Stages

### Stage 0 — Initialize

Create or recover:

```text
<execution-repository>/.thoughts/<WORK-ITEM-ID>/work_record.md
```

Record profile, lifecycle, execution repository, known repository paths, constraints, existing artifacts, and explicit
non-goals. Do not create an implementation plan during initialization.

### Stage 1 — Recover Feature Context

Recover the Jira context ladder and map the smallest relevant current-state surface. Record each source as verified,
inferred, contradicted, or unknown. Select related siblings narrowly; do not scan an entire initiative without an
evidence-based reason.

If context is `clarification_required`, produce a focused clarification packet: what is missing, why it prevents
implementation readiness, the evidence already recovered, and the smallest question for the owner. Before the packet is
handed off, continue bounded impact, integration, and design discovery where repository evidence can reduce the unknown
or frame feasible solutions. Record options, tradeoffs, recommendation, and the decision owner in the work record's
Clarification Brief. Use `awaiting_input` with reason `clarification_required`; do not call this a blocker unless an
external dependency prevents the bounded research.

Before setting `clarification_required`, consume every supplied artifact and
material user context and apply the shared
[Evidence-to-Hypothesis Gate](../contracts/workflow_execution.md#evidence-to-hypothesis-gate).
The context result must state the strongest supported interpretation of the
feature, the executed check and result in `checks_performed`, any unavailable
checks in `checks_remaining`, and the plain-language decision or action that
remains. Do not defer a runnable source or test check to the user.

### Stage 2 — Analyze Impact and Integration

Trace the code path, module seam, data, contracts, configuration, tests, ownership, and operational implications
necessary for the proposed feature. Run Repository Integrator when the activation rules require it.

When a required product, behavior, contract, or rollout decision remains unknown, analyze the existing implementation
enough to identify the feasible options and their impact before escalating to the owner.

### Stage 3 — Design the Feature Slice

Design the smallest change that satisfies verified acceptance criteria. Keep facts, inferences, hypotheses, and
unresolved decisions separate. Map every acceptance criterion to a planned code, test, configuration, documentation, or
explicitly deferred action.

For a clarification-required run, design does not create an implementation plan. It frames one or more supported
solutions, recommends one when evidence permits, and identifies the smallest decision that would make planning ready.

The feature-design result must list the context and artifacts consumed,
confirmed acceptance facts, assumptions or hypotheses, feasible feature
options, recommendation, `checks_performed`, `checks_remaining`, and the next
action. A generic request for more product detail is not a sufficient
clarification result when the repository can answer part of the question.

### Stage 4 — Review, Plan, and Handoff

For `deep`, the Planning Reviewer challenges the design before the plan is accepted. After all required planning workers
return terminal envelopes, fan-in passes, and context is sufficient for planning, the Documenter creates:

```text
<execution-repository>/.thoughts/<WORK-ITEM-ID>/implementation_plan.md
```

The plan is not authorization to make changes. If context remains `clarification_required`, do not create it; hand off
`awaiting_input` with the clarification packet and Clarification Brief instead.

Apply the shared [planning-readiness rule][planning-readiness]. Remaining code, dependency, configuration, test,
environment, operational, rollout, or validation work belongs in the plan when a feasible sequence exists; it is not a
planning blocker by itself.

If `planning-review` exhausts its one recovery attempt, stop with `profile_status: blocked` and reason
`planning_review_runtime_unavailable`. Do not create an implementation plan or offer a Coordinator-only plan as a
deep-profile alternative.

### Stage 5 — Approved Remediation

Before source changes, activate and record `implement`, `review`, `validate`, and continuous `handoff` with their
declared dependencies. The Coordinator must not perform those roles itself. If this graph is unavailable, stop as
`remediation_not_activated`; do not edit source.

Then continue the approved plan through every in-scope implementation step, review the diff, and run the validation
ladder. In-scope review findings return to `implement` until the Reviewer accepts the affected diff; they are not a
handoff report or a new approval gate. A completed slice is `in_progress`, not a new approval gate. Reopen planning only
when new evidence invalidates scope, acceptance criteria, or the selected design; otherwise stop only for a genuine
blocker.

### Stage 6 — Stabilize and Handoff

Record validation, rollout or release steps, rollback, monitoring, ownership, residual risks, and next action. Release
completed worker handles only after their terminal envelopes and artifacts are preserved.

## Implementation Plan Requirements

When created, the plan must include:

1. ticket, parent/initiative context, selected siblings, and source map;
2. verified objective, in-scope and out-of-scope behavior, and acceptance criteria traceability;
3. affected repositories, modules, contracts, configuration, and ownership;
4. ordered source, test, configuration, documentation, rollout, and applicable migration changes;
5. validation ladder, including focused regression tests and applicable CI;
6. risks, compatibility, rollback, monitoring, and release evidence; and
7. completion criteria and unresolved assumptions.

For source-to-destination delivery, include source and destination revisions, the seam, every dependency disposition,
destination baseline result, coexistence or cutover, and rollback.

## Gates

| Gate | Pass condition |
| --- | --- |
| Context recovered | Jira sources, conflicts, assumptions, and unknowns are recorded. |
| Clarification framed | When needed, bounded discovery, feasible options, recommendation, and the smallest decision request are recorded. |
| Planning context sufficient | Outcome, affected surface, and observable acceptance conditions are supported. |
| Impact understood | Relevant code, dependencies, contracts, tests, and operational implications are known or explicitly blocked. |
| Source-to-destination ready | When applicable, source behavior, destination baseline, dependency dispositions, seam, ownership, and rollback are recorded. |
| Design ready | Smallest feature slice and acceptance traceability are documented. |
| Implementation ready | Required planning fan-in passed and `implementation_plan.md` exists. |
| Approval ready | Explicit implementation approval and remediation re-entry are recorded. |
| Validation ready | Review findings are resolved or accepted and validation results are preserved. |
| Handoff ready | Release, rollback, monitoring, ownership, residual risk, and next action are explicit. |

## Required Handoff Output

The final handoff reports:

1. shared outcome: feature objective, context sufficiency, verified scope, and next action. The next action must name
   the owner, location, and completion condition in plain language;
2. parent/initiative and selected-sibling context, including conflicts and clarification questions;
3. implementation-plan path/status, planned change, acceptance traceability, validation, rollout, and rollback;
4. Worker result ledger: one compact row per activated worker and each required worker without a terminal envelope,
   using the shared contract's ledger fields; plus requested, activated, and executed profile, fan-in, and
   runtime-closure status; and
5. remaining risks, blockers, owner, and follow-up work.

For source-to-destination delivery, also report the verified seam, dependency dispositions, destination baseline,
coexistence or cutover, rollback, and operational ownership.

Also include the shared Human-Readable Handoff block: `What happened`, `What this means`, `Internal owner`,
`What you need to do`, and `To continue`. If no technical user action is needed, say `Nothing technical.`

Do not imply that implementation, validation, or release completed when the workflow stopped at a planning,
clarification, approval, environment, or worker gate.

## Related Documents

- [`../templates/feature_delivery_run_prompt.md`](../templates/feature_delivery_run_prompt.md)
- [`../templates/work_record.md`](../templates/work_record.md)
- [`../templates/implementation_plan.md`](../templates/implementation_plan.md)
- [`../examples/feature_delivery.md`](../examples/feature_delivery.md)

[planning-readiness]: ../contracts/workflow_execution.md#planning-readiness-and-implementation-work
