---
title: Workflow Evaluation
version: 0.2.0
status: Pilot
owner: Engineering
last_updated: 2026-08-11
depends_on:
  - ../contracts/workflow_execution.md
  - ../contracts/claims.md
  - ../templates/work_record.md
---

# Workflow Evaluation

> Measure whether a workflow run followed the framework and produced a useful engineering outcome.

Evaluation is not a delivery gate and does not replace software validation. Complete it at a terminal handoff, blocked
handoff, or deliberate pilot review. It evaluates the workflow; the work record remains the source of evidence.

## Pilot Method

Use the Worker Execution Ledger and Worker Result Summary for per-worker role, model, effort, usage, outcome, and
confidence. Do not copy that data into a second table. Add the aggregate metrics and rubric below to the work record.
Use `Unknown` when the runtime does not expose a value; never estimate tokens or credits.

| Dimension | Question | Evidence |
| --- | --- | --- |
| Process quality | Did the requested profile, workers, dependencies, fan-in, and gates run as required? | Workflow state, ledgers, runtime-closure record |
| Reasoning quality | Are material conclusions traceable, calibrated, and responsive to contradictions? | Evidence, claims, assumptions, decisions |
| Engineering quality | Did the work reach the declared implementation, review, validation, release, or handoff outcome? | Plan, diff, review, validation, operational evidence |
| Efficiency | Did the run avoid unnecessary retries, duplicated investigation, workers, and human burden? | Duration, usage, retry/correction counts, worker summaries |
| Task outcome | Did the run move the work item forward? | Solved / partial / plan / blocked / wrong / no action |

Rate each dimension `met`, `partial`, `not_met`, or `not_applicable`. A low cost or short run is not a quality result by
itself. A completed worker graph does not prove the diagnosis, implementation, or release was correct.

Record `workflow_execution` and `task_outcome` separately at every terminal or blocked handoff. Workflow execution is
`completed`, `incomplete`, or `blocked`; it measures whether the selected graph finished. Task outcome measures the
engineering value delivered to the work item. Do not use a numeric score: the named outcome is clearer and auditable.

Record human burden separately from automated efficiency:

| Interaction | Count | Interpretation |
| --- | --- | --- |
| Clarifications requested | | Missing context or decisions that remained after bounded discovery. |
| Decisions requested | | Product, scope, ownership, or incompatible-alternatives decisions. |
| Approvals requested | | Expected control points; not automatically workflow friction. |
| Manual corrections | | User intervention needed to correct a workflow result or process error. |
| Manual reruns | | User-requested reruns, with the reason recorded. |

## Comparison Rules

Compare runs only when their complexity tags, lifecycle, profile, and required evidence are sufficiently similar. Review
at least five real runs before changing a role's model or effort policy. A policy change needs a documented quality
gain, regression, or efficiency result—not a theoretical preference.

The first pilot questions are:

1. Did each required role produce the expected quality across profiles?
2. Did a model or effort setting measurably improve evidence, review, or validation outcomes?
3. Which worker, handoff, or gate created avoidable rework or human intervention?
4. Did a change improve the workflow without reducing engineering quality?

Record any proposed policy change as a decision with the compared runs and their evidence references.
