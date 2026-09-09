---
title: Technical Spike Playbook
version: 0.1.10
status: Pilot
maturity: exercising
supported_lifecycles: planning
exercise_scope: standard + planning; deep + planning
default_timebox_minutes: 35
default_success_criterion: "Report verified evidence, unknowns, options, and a recommendation or unresolved decision."
validation_summary: deep review failed; corrective controls regression-covered; live rerun pending
owner: Engineering
last_updated: 2026-09-08
depends_on:
  - ../contracts/workflow_execution.md
  - ../contracts/claims.md
  - ../integrations/jira.md
  - ../frameworks/investigation.md
  - ../strategies/collaborative.md
  - ../skills/work_item_context.md
  - ../templates/work_record.md
  - ../templates/spike_report.md
  - ../templates/technical_spike_run_prompt.md
  - ../examples/technical_spike.md
---

# Technical Spike Playbook

> Answer or assess one bounded technical question with explicit evidence, experiments, options, and uncertainty.

## Use When

Use this playbook when the primary goal is learning needed for a later decision: feasibility, current behavior, an
integration boundary, a technology choice, an operational unknown, or review of an existing Spike report.

Do not use it to create an implementation plan, design and deliver an already-defined feature, remediate a production
failure, or investigate a known security finding. A request for an implementation plan belongs to Feature Delivery;
an existing Spike remains supporting evidence and does not become the source of truth or imply implementation readiness.

## Defaults and Objectives

- Execution profile: `standard`
- Lifecycle: `planning`
- Mode: `investigation`
- Requested outcome: `technical_answer`
- Objective: `execute_spike`
- Default timebox: `35` minutes end-to-end. The runner records the actual start timestamp and uses this value when no
  run-specific override is supplied.
- Baseline success criterion: Report verified evidence, unknowns, options, and a recommendation or unresolved decision.
  A run-specific criterion may override this when the question needs one.

Supported objectives:

- `execute_spike`: investigate one question within the declared timebox or evidence budget. Record Playbook Selection
  `Primary goal` exactly as `Execute technical spike`.
- `review_spike`: assess an existing Spike's question, method, evidence, conclusions, and remaining unknowns. Record
  Playbook Selection `Primary goal` exactly as `Review technical spike`.

This playbook is planning-only. It never enters remediation, never changes production source or external systems, and
never creates `implementation_plan.md`. A later Feature Delivery run decides whether accepted Spike evidence is
sufficient for implementation planning.

Use [`templates/technical_spike_run_prompt.md`](../templates/technical_spike_run_prompt.md) for every run. The shared
contract and selected playbook own lifecycle, worker activation, recovery, fan-in, and handoff behavior.

## Worker Graph

The Coordinator performs initialization directly; never activate or delegate an `initialize` worker.
Activate one final Documenter after analytical fan-in.

| Worker | Role | Skills | Tools | Activation / dependency |
| --- | --- | --- | --- | --- |
| `spike-context` | `current_state_investigator` | `work_item_context`, `repository_exploration`, `architecture_mapping` | `work_item_read`, `repository_read`, `repository_search`, `history_read`, `artifact_write` | Required; after Coordinator initialization |
| `spike-investigation` | `solution_architect` | `architecture_mapping`, `dependency_mapping` | `repository_read`, `repository_search`, `history_read`, `dependency_inspect`, `build_run`, `test_run`, `artifact_write` | Required for `execute_spike`; after `spike-context` |
| `spike-assessment` | `reviewer` | `architecture_mapping`, `operational_readiness` | `repository_read`, `repository_search`, `diff_review`, `build_run`, `test_run`, `artifact_write` | Required for `review_spike`; after `spike-context` |
| `repository-integration` | `repository_integrator` | `destination_integration`, `architecture_mapping`, `operational_readiness` | `repository_read`, `repository_search`, `history_read`, `dependency_inspect`, `build_run`, `test_run`, `artifact_write` | Deep only; after `spike-context` |
| `spike-review` | `reviewer` | `architecture_mapping`, `operational_readiness` | `repository_read`, `diff_review`, `artifact_write` | Deep `execute_spike` only; after analytical fan-in |
| `handoff` | `documenter` | `work_record_maintenance` | `work_record_read`, `work_record_write`, `artifact_write` | Required once after applicable fan-in |

Required worker sets:

- `standard + execute_spike`: `spike-context`, `spike-investigation`, and final `handoff`.
- `deep + execute_spike`: standard workers plus `repository-integration` and independent `spike-review`.
- `standard + review_spike`: `spike-context`, `spike-assessment`, and final `handoff`.
- `deep + review_spike`: standard review workers plus `repository-integration`.

For Deep runs, start the objective's analytical worker and `repository-integration` in parallel after `spike-context`.
Each owns a distinct question and repeats upstream discovery only for a recorded discrepancy.

## Stages

### Stage 0 — Initialize

Create or recover:

```text
<execution-repository>/.thoughts/<WORK-ITEM-ID>/work_record.md
```

Prompt-completeness gate: before any manifest, repository, or Jira work, validate that the prompt contains a populated
primary question. Use this playbook's default timebox and baseline success criterion unless the prompt supplies an
override. Missing or placeholder run-specific values stop the run with a focused request; do not create temporary
inputs or begin discovery. Record the objective, one primary question, the resolved timebox, and the resolved success
criterion.
The runner represents the bounded evidence budget through the captured `--started-at` plus the playbook default or
run-specific `--timebox-minutes`; it must never invent an open-ended investigation. Record evidence sources, execution
repository, constraints, non-goals, and the resolved success criterion.

Before worker activation, classify the decision context as confirmed facts, assumptions or hypotheses, open decisions,
and recommended defaults. Discoverable facts belong to the workers; ask the user only for a material business, scope,
ownership, or incompatible-alternatives decision that bounded discovery cannot resolve. If no decision remains, record
`Not applicable` in the report.

### Stage 1 — Frame the Spike

Recover the Jira item and only the hierarchy, links, documents, or repository context needed to interpret the question.
Apply the [Jira Integration](../integrations/jira.md) when Jira is supplied. Separate verified facts, assumptions,
conflicts, and unknowns. An Epic or related feature provides context, not automatic Spike scope.
When a work-item identifier is supplied, `spike-context` must consume that input through `work_item_read` before
repository analysis. If the capability is unavailable, record the normalized unavailable result and preserve the
supplied identifier; do not silently omit the work-item read.

For `review_spike`, identify the exact report or document under review and its claimed conclusion. Missing review
material is indispensable-evidence failure, not authority to recreate the Spike from unrelated context.

For `execute_spike`, keep any existing Spike or design document as an optional comparison reference, not a review
target. Establish the current-run findings and recommendation from independent evidence before reading or comparing
the reference. A reference may reveal agreement, contradiction, or omission; it does not define the answer.

### Stage 2 — Investigate or Assess

For `execute_spike`, run the smallest checks or disposable experiments that can distinguish the credible answers.
Choose the highest observable or public seam that can falsify the hypothesis. Record the seam, hypothesis, command or
method, expected discriminating outcomes, actual result, limitations, and evidence reference. Prefer behavior-level
checks over implementation-coupled checks; tests and benchmarks are allowed when they do not require production-source
changes. Keep any generated Spike artifacts inside the current `.thoughts/<WORK-ITEM-ID>/` root.

For `review_spike`, test whether the question is precise, the scope and method fit the question, evidence supports the
claims, material alternatives were considered, limitations are visible, and the recommendation follows from the
findings. Run a focused check only when it can change the assessment.

Stop when the question is answered, the review disposition is stable, the declared budget is exhausted, or
indispensable evidence is unavailable. Do not expand into adjacent services or repositories merely because they may be
related; record them as follow-up unless they can change the primary conclusion.
Component or service names do not establish team ownership. Preserve explicit user-owned scope, and mark ownership as
unknown when current evidence does not establish it.

For a duration budget, use prepared `run_budget.json`. Report exactly `within_budget`,
`exhausted_with_useful_result`, `exceeded_during_finalization`, or `stopped_by_indispensable_evidence`; do not use
`Completed` as a substitute for measured deadline status. An already exhausted duration blocks before worker
activation. The worker runtime guard reserves the last ten percent, capped at two minutes, for reporting and
finalization; once that reserve begins, do not activate another analytical or Documenter worker.

### Stage 3 — Reconcile and Review

Deep execution adds repository integration and independent review. Reconcile only material disagreement. A blocked or
failed required worker receives one recovery attempt under the shared contract; do not substitute the Coordinator or a
different role.

For Deep `review_spike`, return any material repository-integration discrepancy to the same `spike-assessment` worker
once before Documenter activation. Do not start another investigation or review worker.

### Stage 4 — Report and Handoff

After required analytical workers return terminal envelopes and fan-in passes, the final Documenter creates:

```text
<execution-repository>/.thoughts/<WORK-ITEM-ID>/spike_report.md
```

The report must preserve the question, declared assessment criteria or control domains, decision context, and budget,
method, direct source evidence, experiments, findings, options, recommendation, limitations, remaining unknowns, and
exact disposition. It must also preserve any Feature Delivery handoff and, for `execute_spike`, the independent
comparison.
For every declared criterion, record evidence, assessment, gap or limitation, and the next evidence or decision. Use
`Not applicable` when no criteria were declared. It must be usable without opening every intermediate worker artifact
and must not turn follow-up work into an implementation plan.

Use these exact completed-run dispositions:

| Objective | Workflow result | State | Workflow outcome | Engineering outcome |
| --- | --- | --- | --- | --- |
| `execute_spike` | `Question answered` | `completed` | `completed` | `solved` |
| `execute_spike` | `Partially answered` | `completed` | `completed` | `partially_solved` |
| `execute_spike` | `Inconclusive` | `completed` | `completed` | `partially_solved` |
| `review_spike` | `Accepted` | `completed` | `completed` | `solved` |
| `review_spike` | `Changes required` | `completed` | `completed` | `partially_solved` |
| `review_spike` | `Inconclusive` | `completed` | `completed` | `partially_solved` |

Use `Question answered` only when the primary decision is resolved by current-run evidence. If the recommendation is
conditional on an unresolved decision or indispensable evidence gate, use `Partially answered` even when the run has a
useful architectural direction.

Use `blocked` only when runtime, permission, environment, or indispensable-evidence failure prevents the selected graph
from completing. Exhausting the declared budget with useful evidence is `Inconclusive` or `Partially answered`, not a
workflow blocker.

The final Documenter may serialize transient workflow `State: handoff`. When every recorded worker result is complete
and the workflow result is valid for the selected objective, the packaged finalizer applies the table above and emits
the terminal state and outcomes. This is deterministic lifecycle bookkeeping, not a new technical conclusion.

At handoff, use the contract's shared human-readable template. Set `Implementation plan` to `Not created; Technical
Spike produces spike_report.md`, link `spike_report.md`, name the evidence-backed conclusion and limitations, and give
one concrete next action. Since this playbook has no delivery lifecycle, it never activates `implement`, `review`,
`validate`, or final `handoff` after delivery fan-in; Feature Delivery owns any later approved delivery.

If pre-release or terminal finalization fails, preserve the exact failure receipt and report the run as blocked or
incomplete. A generated `spike_report.md` does not authorize `Question answered` or a completed terminal handoff.

## Gates

- **Question Gate:** one decision-relevant question is explicit; the playbook baseline or a run-specific success
  criterion is resolved before investigation.
- **Budget Gate:** the playbook default or a run-specific timebox/evidence limit is resolved before investigation.
- **Evidence Gate:** conclusions cite current-run evidence; unsupported certainty is prohibited.
- **Experiment Gate:** each experiment records method, expected outcomes, result, and limitation.
- **Review Gate:** `review_spike` assesses the supplied Spike rather than silently replacing it.
- **Reference Independence Gate:** `execute_spike` establishes its answer before comparing an optional reference.
- **Report Gate:** completed runs create and link `spike_report.md`; `implementation_plan.md` is absent.

## Outputs

- `work_record.md`
- `spike_report.md` for every completed run
- exact disposition and remaining uncertainty
- bounded next action or Feature Delivery handoff
