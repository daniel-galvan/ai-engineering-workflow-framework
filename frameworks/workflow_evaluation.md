---
title: Workflow Evaluation
version: 0.4.3
status: Pilot
owner: Engineering
last_updated: 2026-08-26
depends_on:
  - ../contracts/workflow_execution.md
  - ../contracts/claims.md
  - ../templates/work_record.md
---

# Workflow Evaluation

> Measure whether a workflow run followed the framework and produced a useful engineering outcome.

Evaluation is opt-in, not a delivery gate, and does not replace software validation. Complete it only when the request
explicitly declares an evaluation or benchmark run. Normal workflow runs omit evaluation telemetry and use the work
record only for engineering evidence and execution status.

## Pilot Method

Use the Worker Execution Ledger and Worker Result Summary for per-worker role, model, effort, usage, outcome, and
confidence. Do not copy that data into a second table. Add the aggregate metrics and rubric below to the work record.
Use `Unknown` when the runtime does not expose token or credit usage; never estimate it. Coordinator-observed
activation, terminal, and elapsed timestamps are required. Use activation as start and `Unavailable` for provider queue
time when the runtime exposes no separate value.

Every evaluation MUST identify its evaluation run ID, framework commit, prompt template revision, playbook version, and
role-policy baseline ID. It must also record requested and executed profile, lifecycle, provider/model configuration,
and relevant repository revisions. Use the provider run ID when no independent experiment ID was supplied.
Plugin-backed evaluations MUST record the installed plugin name and version; manual runs record
`Not applicable`. The execution-repository `.codex/agents/` runtime view is optional, but the resolved provider
configuration source and status are mandatory. Missing reproducibility identity makes Process quality and Efficiency no
better than `partial`.

| Dimension | Question | Evidence |
| --- | --- | --- |
| Process quality | Did the requested profile, workers, dependencies, fan-in, and gates run as required? | Workflow state, ledgers, runtime-closure record |
| Control fidelity | Did the run follow explicit instructions, consume supplied inputs, and stay within the approved plan? | Input Register, assigned/consumed inputs, decisions, plan-conformance record |
| Reasoning quality | Are material conclusions traceable, calibrated, and responsive to contradictions? | Evidence, claims, assumptions, decisions |
| Engineering quality | Did the work reach the declared implementation, review, validation, release, or handoff outcome? | Plan, diff, review, validation, operational evidence |
| Efficiency | Did the run avoid unnecessary retries, duplicated investigation, workers, and human burden? | Duration, usage, retry/correction counts, worker summaries |
| Engineering outcome | Did the run move the work item forward? | Solved / Partially Solved / Plan Only / Blocked / Incorrect |

Rate each dimension `met`, `partial`, `not_met`, or `not_applicable`. A low cost or short run is not a quality result by
itself. A completed worker graph does not prove the diagnosis, implementation, or release was correct.

Record `workflow_outcome` and `engineering_outcome` separately at every terminal or blocked handoff. Workflow outcome is
`completed`, `incomplete`, or `blocked`; it measures whether the selected graph finished. Engineering outcome is exactly
one of `solved`, `partially_solved`, `plan_only`, `blocked`, or `incorrect`; it measures the engineering value delivered
to the work item. Do not use a numeric score: the named outcome is clearer and auditable.

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
| Coordination errors | Count | Pre-provider command, quoting, routing, ledger, or orchestration errors and retries. |
| Post-closure polls | Count | Wait or status calls after the corresponding handle was released; included in coordination errors. |
| Handoff revisions | Count | Returns to the same final Documenter after its first terminal result. |
| Post-finalization Coordinator edits | Count | Direct Coordinator edits after Documenter terminal; must be zero. |
| Prompt conformance | Pass / Fail | Canonical template revision and missing or altered required fields. |
| Repository evidence eligibility | Per repository | Branch, revision, user-selected ref, release mapping, and accepted/caveated/rejected status. |
| Memory facts admitted | Count | Unassigned memory or historical facts/citations that entered current-run outputs; must be zero. |
| Artifact volume | Count and bytes | Durable artifacts produced by the run. |
| Finding-to-plan ratio | Findings / change sets / plans | Whether distinct findings produced shared or duplicate remediation plans. |

Derive instance, activation, error, and revision counts from the chronological activation ledger. A successful `spawn`
is one activation attempt. A `resume` or `send` on an existing handle is not another instance or attempt; a rejected
provider action is a coordination error, even if the retry succeeds. Every continuation adds a chronological row with
its new inputs and trigger. Do not retroactively assign continuation inputs to earlier activations.

If coordinator-observed wall time, worker elapsed time, actual instances, activation attempts, or activation outcomes
are missing, Process quality and Efficiency cannot be rated `met`. Record the missing-metrics control failure rather
than treating unavailable provider telemetry as the reason.

Process quality and Efficiency also cannot be rated `met` when reported wall time omits Coordinator or documentation
time, is reconstructed from worker-stage estimates instead of turn timestamps, or when a worker's activation and
terminal times were observable but recorded as `Unknown` or `Unavailable`.

When the turn-start timestamp is missing and no provider timestamp covers the complete turn, required metrics are
`invalid`. A shortened stage window must not be reported as wall time, and the run cannot claim metrics or process
conformance. Artifact bytes must be recomputed after the final handoff revision.

Process quality cannot be rated `met` when the Coordinator changes a technical worker's diagnosis, remediation
boundary, or readiness disposition without returning it for technical review, or when a handoff worker completed before
final fan-in and was not updated afterward.

Process quality and Efficiency cannot be rated `met` when the Coordinator duplicates delegated technical
investigation, counts itself as a worker activation attempt, omits its own or the Documenter's timing, or edits a final
Documenter artifact instead of returning the inconsistency. Process quality also cannot be `met` when
`awaiting_input` after completed fan-in is reported as a blocked workflow or engineering outcome.

Process quality and Efficiency also cannot be rated `met` when configured worker model or effort was replaced by
Coordinator inheritance, workers reread the complete framework without a named ambiguity, or a worker repeats verified
source mapping without a recorded discrepancy. The same applies when provider session timestamps were available but
worker-authored timestamps were used, the Coordinator and final Documenter edited the same artifact concurrently, or
artifact size targets were exceeded without recording the bytes and reason.

Process quality cannot be rated `met` when a result that failed `context_conformance` entered fan-in, a required worker
ran after provider configuration could not be resolved or bound, the Documenter created a plan after Fix Design returned
`implementation_plan_action: omit`, or a conditional Repository Integrator ran without both local-source answerability
and a decision-changing question.

Process quality cannot be rated `met` when a versioned run used a nonconformant prompt, an undeclared feature branch
established baseline/production/current-main behavior, unassigned memory material entered an artifact or citation, a
successful Documenter activation was omitted from activation attempts, or the Coordinator edited an artifact after
Documenter terminal. Invalid metrics must still report every authoritative measurement that is available.

Process quality cannot be rated `met` when the terminal record omits a required finalization field or playbook artifact,
the final answer substitutes one canonical state field for another, or a post-closure poll is omitted from coordination
errors.

Efficiency cannot be rated `met` when Evidence and Repository Integration answer the same question without a recorded
discrepancy, or when Repository Integration runs after normalized evidence already answered its activation question.

Efficiency cannot be rated `met` when planning runs unit or integration tests that cannot change the diagnosis,
ownership, or readiness, or spends time repairing a test environment that remediation can validate later.

Process quality cannot be rated `met` when `plan_only` is reported without a usable implementation plan, or when the
named next-action owner cannot access or perform the requested action.

A duplicate plan has the same affected files, intended changes, validation, owner, rollout, and rollback as another
plan. Different vulnerability identifiers, rules, functions, reachability, or risk do not by themselves require
different remediation plans.

## Comparison Rules

Compare runs only when their complexity tags, lifecycle, profile, required evidence, and recorded role-policy baseline
ID are sufficiently similar. Review at least five real runs before changing a role's model or effort policy. A policy
change needs a documented quality gain, regression, or efficiency result—not a theoretical preference.

The first pilot questions are:

1. Did each required role produce the expected quality across profiles?
2. Did a model or effort setting measurably improve evidence, review, or validation outcomes?
3. Which worker, handoff, or gate created avoidable rework or human intervention?
4. Did a change improve the workflow without reducing engineering quality?

Record any proposed policy change as a decision with the compared runs and their evidence references.
