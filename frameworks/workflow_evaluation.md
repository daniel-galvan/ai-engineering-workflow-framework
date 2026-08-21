---
title: Workflow Evaluation
version: 0.3.0
status: Pilot
owner: Engineering
last_updated: 2026-08-21
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
| Control fidelity | Did the run follow explicit instructions, consume supplied inputs, and stay within the approved plan? | Input Register, assigned/consumed inputs, decisions, plan-conformance record |
| Reasoning quality | Are material conclusions traceable, calibrated, and responsive to contradictions? | Evidence, claims, assumptions, decisions |
| Engineering quality | Did the work reach the declared implementation, review, validation, release, or handoff outcome? | Plan, diff, review, validation, operational evidence |
| Efficiency | Did the run avoid unnecessary retries, duplicated investigation, workers, and human burden? | Duration, usage, retry/correction counts, worker summaries |
| Task outcome | Did the run move the work item forward? | Solved / Partially Solved / Plan Only / Blocked / Incorrect |

Rate each dimension `met`, `partial`, `not_met`, or `not_applicable`. A low cost or short run is not a quality result by
itself. A completed worker graph does not prove the diagnosis, implementation, or release was correct.

Record `workflow_execution` and `task_outcome` separately at every terminal or blocked handoff. Workflow execution is
`completed`, `incomplete`, or `blocked`; it measures whether the selected graph finished. Task outcome is exactly one
of `solved`, `partially_solved`, `plan_only`, `blocked`, or `incorrect`; it measures the engineering value delivered to
the work item. Do not use a numeric score: the named outcome is clearer and auditable.

Record human burden separately from automated efficiency:

| Interaction | Measure | Interpretation |
| --- | --- | --- |
| Clarifications | Count | Missing context or decisions that remained after bounded discovery. |
| Approvals | Count | Expected control points; not automatically workflow friction. |
| Manual corrections | Count | User intervention needed to correct a workflow result or process error. |
| Reruns | Count | User-requested or operator-initiated reruns, with the reason recorded. |
| Human review effort | Minutes | Human time spent reviewing workflow output, including required control-point review. |

Record control failures and timing explicitly. Zero means the run was checked and none were found; `Unknown` means the
run did not expose enough evidence to assess the measure.

| Control or timing measure | Measure | Interpretation |
| --- | --- | --- |
| Instruction violations | Count | Explicit user or framework instructions contradicted by the workflow. |
| Authoritative inputs ignored | Count | Current decisions or constraints assigned to a worker but not consumed. |
| Supplied inputs not consumed | Count | Material available inputs left unused without an accepted disposition. |
| Unapproved plan deviations | Count | Remediation changes that departed from the approved plan without replanning. |
| Worker elapsed time | Per worker | Start-to-terminal duration from provider data or recorded timestamps. |
| Worker wait time | Per worker | Time queued or waiting on dependencies/runtime when exposed. |

## Comparison Rules

Compare runs only when their complexity tags, lifecycle, profile, required evidence, and recorded model-policy baseline
ID are sufficiently similar. Review at least five real runs before changing a role's model or effort policy. A policy
change needs a documented quality gain, regression, or efficiency result—not a theoretical preference.

The first pilot questions are:

1. Did each required role produce the expected quality across profiles?
2. Did a model or effort setting measurably improve evidence, review, or validation outcomes?
3. Which worker, handoff, or gate created avoidable rework or human intervention?
4. Did a change improve the workflow without reducing engineering quality?

Record any proposed policy change as a decision with the compared runs and their evidence references.
