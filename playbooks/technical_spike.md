---
title: Technical Spike Playbook
version: 0.1.0
status: Pilot
maturity: not_exercised
supported_lifecycles: planning
exercise_scope: standard + planning; deep + planning
validation_summary: contract and static validation only; no real run exercised
owner: Engineering
last_updated: 2026-09-04
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

Do not use it to design and deliver an already-defined feature, remediate a production failure, or investigate a known
security finding. A Spike may inform Feature Delivery later, but it does not imply implementation readiness.

## Defaults and Objectives

- Execution profile: `standard`
- Lifecycle: `planning`
- Mode: `investigation`
- Objective: `execute_spike`

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

Record the objective, one primary question, timebox or evidence budget, evidence sources, execution repository,
constraints, non-goals, and success criteria. If the question or budget is absent, stop before worker activation with a
focused request; do not invent an open-ended investigation.

### Stage 1 — Frame the Spike

Recover the Jira item and only the hierarchy, links, documents, or repository context needed to interpret the question.
Apply the [Jira Integration](../integrations/jira.md) when Jira is supplied. Separate verified facts, assumptions,
conflicts, and unknowns. An Epic or related feature provides context, not automatic Spike scope.

For `review_spike`, identify the exact report or document under review and its claimed conclusion. Missing review
material is indispensable-evidence failure, not authority to recreate the Spike from unrelated context.

### Stage 2 — Investigate or Assess

For `execute_spike`, run the smallest checks or disposable experiments that can distinguish the credible answers.
Record the hypothesis, command or method, expected discriminating outcomes, actual result, limitations, and evidence
reference. Tests and benchmarks are allowed when they do not require production-source changes. Keep any generated
Spike artifacts inside the current `.thoughts/<WORK-ITEM-ID>/` root.

For `review_spike`, test whether the question is precise, the scope and method fit the question, evidence supports the
claims, material alternatives were considered, limitations are visible, and the recommendation follows from the
findings. Run a focused check only when it can change the assessment.

Stop when the question is answered, the review disposition is stable, the declared budget is exhausted, or
indispensable evidence is unavailable. Do not expand into adjacent services or repositories merely because they may be
related; record them as follow-up unless they can change the primary conclusion.

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

The report must preserve the question, budget, method, evidence, experiments, findings, options, recommendation,
limitations, remaining unknowns, exact disposition, and any Feature Delivery handoff. It must not turn follow-up work
into an implementation plan.

Use these exact completed-run dispositions:

| Objective | Workflow result | State | Workflow outcome | Engineering outcome |
| --- | --- | --- | --- | --- |
| `execute_spike` | `Question answered` | `completed` | `completed` | `solved` |
| `execute_spike` | `Partially answered` | `completed` | `completed` | `partially_solved` |
| `execute_spike` | `Inconclusive` | `completed` | `completed` | `partially_solved` |
| `review_spike` | `Accepted` | `completed` | `completed` | `solved` |
| `review_spike` | `Changes required` | `completed` | `completed` | `partially_solved` |
| `review_spike` | `Inconclusive` | `completed` | `completed` | `partially_solved` |

Use `blocked` only when runtime, permission, environment, or indispensable-evidence failure prevents the selected graph
from completing. Exhausting the declared budget with useful evidence is `Inconclusive` or `Partially answered`, not a
workflow blocker.

At handoff, use the contract's shared human-readable template. Set `Implementation plan` to `Not created; Technical
Spike produces spike_report.md`, link `spike_report.md`, name the evidence-backed conclusion and limitations, and give
one concrete next action. Since this playbook has no delivery lifecycle, it never activates `implement`, `review`,
`validate`, or final `handoff` after delivery fan-in; Feature Delivery owns any later approved delivery.

## Gates

- **Question Gate:** one decision-relevant question and success criterion are explicit.
- **Budget Gate:** the timebox or evidence limit is explicit before investigation.
- **Evidence Gate:** conclusions cite current-run evidence; unsupported certainty is prohibited.
- **Experiment Gate:** each experiment records method, expected outcomes, result, and limitation.
- **Review Gate:** `review_spike` assesses the supplied Spike rather than silently replacing it.
- **Report Gate:** completed runs create and link `spike_report.md`; `implementation_plan.md` is absent.

## Outputs

- `work_record.md`
- `spike_report.md` for every completed run
- exact disposition and remaining uncertainty
- bounded next action or Feature Delivery handoff
