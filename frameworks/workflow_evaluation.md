---
title: Workflow Evaluation
version: 0.3.2
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
Use `Unknown` when the runtime does not expose token or credit usage; never estimate it. Coordinator-observed
activation, terminal, and elapsed timestamps are required. Use activation as start and `Unavailable` for provider queue
time when the runtime exposes no separate value.

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
| Failed spawns | Count | Worker activations rejected before a handle was returned. |
| Handle discrepancies | Count | Returned handles that did not match a later status or wait operation. |
| Replacement workers | Count | Replacement activations, with the reconciliation evidence and reason. |
| Artifact volume | Count and bytes | Durable artifacts produced by the run. |
| Finding-to-plan ratio | Findings / change sets / plans | Whether distinct findings produced shared or duplicate remediation plans. |

If coordinator-observed wall time, worker elapsed time, actual instances, activation attempts, or activation outcomes
are missing, Process quality and Efficiency cannot be rated `met`. Record the missing-metrics control failure rather
than treating unavailable provider telemetry as the reason.

Process quality and Efficiency also cannot be rated `met` when reported wall time omits Coordinator or documentation
time, is reconstructed from worker-stage estimates instead of turn timestamps, or when a worker's activation and
terminal times were observable but recorded as `Unknown` or `Unavailable`.

Process quality cannot be rated `met` when the Coordinator changes a technical worker's diagnosis, remediation
boundary, or readiness disposition without returning it for technical review, or when a handoff worker completed before
final fan-in and was not updated afterward.

Process quality and Efficiency cannot be rated `met` when the Coordinator duplicates delegated technical
investigation, counts itself as a worker activation attempt, omits its own or the Documenter's timing, or edits a final
Documenter artifact instead of returning the inconsistency. Process quality also cannot be `met` when
`awaiting_input` after completed fan-in is reported as a blocked workflow or task outcome.

Process quality and Efficiency also cannot be rated `met` when configured worker model or effort was replaced by
Coordinator inheritance, workers reread the complete framework without a named ambiguity, or a worker repeats verified
source mapping without a recorded discrepancy. The same applies when provider session timestamps were available but
worker-authored timestamps were used, the Coordinator and final Documenter edited the same artifact concurrently, or
artifact size targets were exceeded without recording the bytes and reason.

A duplicate plan has the same affected files, intended changes, validation, owner, rollout, and rollback as another
plan. Different vulnerability identifiers, rules, functions, reachability, or risk do not by themselves require
different remediation plans.

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
