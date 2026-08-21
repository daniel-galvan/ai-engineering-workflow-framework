---
title: Sentry Issue Remediation Playbook
version: 0.2.0
status: Pilot
maturity: exercising
validation_scope: standard + planning; deep + planning
known_unvalidated_scope: standard + remediation; deep + remediation
owner: Engineering
last_updated: 2026-08-10
depends_on:
  - ../frameworks/investigation.md
  - ../strategies/collaborative.md
  - ../contracts/workflow_execution.md
  - ../contracts/claims.md
  - ../templates/work_record.md
  - ../templates/implementation_plan.md
  - ../templates/sentry_issue_run_prompt.md
  - ../skills/failure_diagnosis.md
  - ../integrations/sentry.md
---

# Sentry Issue Remediation

> Turn a Sentry issue into an evidence-backed diagnosis, minimal code fix,
> regression test, validation result, and controlled handoff.

## Purpose

Diagnose and remediate production failures reported by Sentry while preserving the distinction between observed runtime
evidence, repository behavior, hypotheses, implementation, and validation.

## When To Use

Use this playbook when a Sentry issue may require:

- root-cause investigation;
- repository and code-path analysis;
- a bug fix or defensive correction;
- a regression test;
- production-risk assessment; or
- rollout, monitoring, and handoff decisions.

## When Not To Use

Use another workflow when:

- the issue is only noise and requires no code investigation;
- the work is a normal planned feature;
- the issue is only a performance or capacity investigation with no fix scope;
- no repository or fault boundary can be established after Sentry and repository evidence is collected; or
- the work is a broad incident requiring incident-command procedures.

## Required Inputs

- Sentry issue URL or issue identifier
- MCP access to the relevant Sentry organization and project
- One or more relevant repository checkouts or working directories

## Recommended Inputs

- Sentry organization and project, when not derivable from the issue URL
- Related Sentry events and occurrence history
- Logs, traces, dashboards, and deployment information
- Jira or equivalent work item
- Recent pull requests and releases
- Existing tests and reproduction steps
- Reporter context and investigation hints, clearly labeled as unverified input

The workflow derives the repository and deployed revision from Sentry issue, event, release, tag, deployment, and local
repository evidence. A release name is not treated as an exact commit until it is reconciled with repository history,
but a release-to-checkout mismatch or an unavailable Sentry release lookup is normally a traceability caveat, not a
planning blocker. Continue against the best available checkout, record the mismatch, and make exact release verification
a pre-implementation or validation step when it matters.

Standard planning is bounded: use the latest event as the primary occurrence, and inspect an older representative event
only when the latest event is insufficient, inconsistent, or the symptom may vary by occurrence. Never exhaustively
inspect a high-volume issue by default. Treat persisted-row inspection as conditional on the diagnosis depending on
database state and the required access being available. Missing or conflicting evidence becomes an explicit unknown.
Before asking the user for a decision, use bounded repository and contract discovery to frame feasible options when it
can reduce the uncertainty. Reserve `blocked` for unavailable access, environment, indispensable evidence, or a safety
risk; otherwise use `awaiting_input` with a plain-language clarification brief and the smallest decision request.

## Repository and Event Topology

The reporting repository is not necessarily the fault repository. Record these roles explicitly when they differ:

| Topology field               | Meaning                                           |
| ---------------------------- | ------------------------------------------------- |
| `event_origin_repository`    | Repository that emitted or reported the event     |
| `candidate_fault_repository` | Repository that may contain the cause             |
| `candidate_fault_component`  | Package, service, or subsystem suspected          |
| `downstream_or_return_path`  | Later systems or callbacks affected by the result |

The initial topology is a hypothesis unless the run prompt explicitly records a confirmed topology decision. Verify
hypotheses with Sentry evidence, release metadata, repository history, event payloads, queues, callbacks, and tests. Do
not infer event origin or candidate fault ownership from a field named “primary code repository.” Do not inspect or
modify an unrelated project merely because it exists in the same monorepo. Code changes are limited to the verified
fault boundary unless an expanded scope is approved.

Confirmed user decisions and constraints are authoritative run inputs. Reporter context may identify symptoms, expected
behavior, suspected flows, likely owners or files, reproduction clues, known exclusions, and related links. Treat the
latter as investigation leads, not as decisions or evidence. Reconcile hints with Sentry, repository, runtime, and test
evidence before using them as facts; do not reopen a confirmed decision as a clarification question.

When a confirmed input identifies a comparison source of truth, use that system's result as the expected baseline and
investigate the discrepancy in the other system. Do not ask the user to redefine the baseline or to decide that baseline
records are duplicates. Record duplicate identity or normalization as a technical hypothesis to verify, and propose
options only if the evidence shows that the implementation choice itself remains unresolved.

## Optional Supporting Artifacts

The workflow may consume exported event or payload JSON, request and response examples, screenshots, logs, trace
excerpts, deployment metadata, source-map artifacts, and reproduction fixtures.

Treat every artifact as evidence with a source, timestamp, owner, and redaction status. Do not trust an attachment over
current repository or runtime evidence without reconciliation.

## Default Execution

The default run uses:

- Execution profile: `standard`
- Lifecycle: `planning`

It performs evidence collection, failure analysis, diagnosis, fix design, and work-record maintenance, then stops at
`ready_for_implementation`.

`standard` is bounded by its worker graph and evidence rules, not by a wall-clock guarantee. If provider latency or a
worker runtime makes the run unusually long, record the duration and runtime cause; do not compensate by skipping a
required worker or claiming completion early.

The `remediation` lifecycle continues through implementation, review, validation, and stabilization after explicit
approval.

The playbook remains provider-independent. Provider adapters select the concrete model, effort, tools, and worker
runtime. A run prompt selects the profile and lifecycle; it does not redefine the workflow.

Use [`templates/sentry_issue_run_prompt.md`](../templates/sentry_issue_run_prompt.md) as the canonical session-prompt
format. Add scenario data to that template; change the template or this playbook when the format or process changes.

## Execution Profiles and Lifecycle

The execution profile and lifecycle are independent selections. The profile controls investigation depth and worker
activation. The lifecycle controls how far the run may proceed.

| Execution profile | Use when                                                                                                                | Planning behavior                                                                                                                                 |
| ----------------- | ----------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| `standard`        | Default for Sentry issue remediation                                                                                    | Runs Orchestrator, latest-event-first Sentry evidence, bounded diagnosis and solution design, and continuous documentation; Repository Integrator remains conditional. |
| `deep`            | Cross-repository uncertainty, unclear causality, concurrency, data or security risk, high impact, or disputed ownership | Adds independent failure-topology analysis, requires Repository Integrator, and produces stronger competing-hypothesis and validation planning. |

`standard` is the default and covers normal triage as well as remediation planning. There is no separate `triage`
profile. The Orchestrator may escalate from `standard` to `deep` when evidence meets the escalation criteria and must
record that decision.

| Lifecycle     | Behavior                                                                                                         |
| ------------- | ---------------------------------------------------------------------------------------------------------------- |
| `planning`    | Run investigation and fix design, then stop at `ready_for_implementation`; no source or external-system changes. |
| `remediation` | Continue through implementation, review, validation, and stabilization after the explicit approval gate.         |

The valid combinations are `standard + planning`, `deep + planning`, `standard + remediation`, and `deep + remediation`.
A remediation lifecycle never bypasses approval, validation, fan-in, or external-write gates.

## Continuation and Lifecycle Re-entry

The selected lifecycle is immutable for one run. Follow-up questions do not convert a planning run into remediation, and
a planning conversation must not invoke a generic implementation workflow.

When implementation is requested after a planning handoff, the Orchestrator must perform an explicit remediation
re-entry:

1. preserve the existing work record and implementation plan;
2. record explicit implementation approval;
3. start or record a new run with the same profile and `lifecycle: remediation`;
4. re-read this playbook, the work record, and the implementation plan;
5. record `profile_status: requested` for the remediation run;
6. reuse completed planning artifacts and activate `implement`, `review`, `validate`, and `handoff` before source
   changes;
7. wait for every required result envelope and complete fan-in before closing the remediation stage; and
8. complete the shared worker-runtime closure barrier before closing the prior run or starting another lifecycle run;
   and
9. report the remediation run's lifecycle, worker activation, fan-in, and runtime-closure status.

If new evidence contradicts or expands the approved plan, reactivate the profile's required planning workers before
implementation. If approval is missing, stop with state `awaiting_input` and reason `approval_required`. If remediation
lifecycle or required worker activation is missing, stop with state `blocked` and reason `remediation_not_activated`.

## Interrupted Profile and Fan-In Recovery

If a required worker stops, is unavailable, or its result envelope is missing, the run is incomplete. Continue with the
canonical run prompt using `Interrupted profile recovery`:

A provider wait timeout or `pending_init`/`running` status is not proof that the worker stopped. Keep that worker
active, continue waiting or request graceful finalization when supported, and do not close it or start a replacement
from the timeout alone. Apply the shared [worker wait
rules](../contracts/workflow_execution.md#worker-wait-and-termination-semantics) before starting recovery.

1. preserve the same work record, profile, lifecycle, and completed artifacts;
2. record the completed and missing workers plus the recovery reason;
3. reuse completed Sentry evidence unless a specific discrepancy requires a new query;
4. activate every incomplete required worker for the selected profile;
5. wait for all result envelopes and complete fan-in; and
6. report the recovered profile status and next gate.

The missing implementation approval blocks delivery workers only. It must not block the remaining planning workers
required to complete deep diagnosis and fix design. If the required graph cannot start, stop as `not_executed`. If it
starts but required activation or fan-in remains incomplete, stop as `blocked`; do not use a generic workflow or claim
successful profile execution.

Required worker sets are explicit:

- `standard + planning`: `initialize`, `evidence-topology`, `fix-design`, and continuous `handoff`. The `fix-design`
  worker performs bounded failure analysis before designing the fix.
- `deep + planning`: all standard planning workers plus `failure-topology` and mandatory `repository-integration`.
- `standard + remediation`: reuse completed standard planning artifacts, then activate `implement`, `review`,
  `validate`, and `handoff` after approval.
- `deep + remediation`: reuse completed deep planning artifacts, then activate `implement`, `review`, `validate`, and
  `handoff` after approval.

## Profile Execution

The shared execution contract defines profile execution, fan-in, and no-downgrade semantics. For this playbook:

- `standard` activates the standard planning worker set.
- `deep` activates the standard planning worker set plus `failure-topology` and mandatory `repository-integration`.
- The Orchestrator waits for every required worker before completing diagnosis or fix design.
- The final handoff reports requested, activated, and executed profile, profile status, worker activation, fan-in
  status, and runtime-closure status.

## Worker Profiles

The standard planning profile has two active analytical roles plus continuous documentation. The Solution Architect
performs bounded failure analysis and fix design in that profile. Deep adds an independent Failure Topology Analyst and
mandatory Repository Integrator. Repository Integrator remains conditional for standard.

| Worker                   | Role                         | Mode          | Default effort | Skills                                                                                                                | Tools                                                                                                         | Activation / depends on                                                    |
| ------------------------ | ---------------------------- | ------------- | -------------- | --------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| `initialize`             | `orchestrator`               | investigation | standard       | `work_item_context`, `workflow_planning`, `work_record_maintenance`                                                   | `work_item_read`, `work_record_read`, `work_record_write`                                                     | First; none                                                                |
| `evidence-topology`      | `current_state_investigator` | investigation | standard       | `work_item_context`, `repository_exploration`, `architecture_mapping`, `failure_diagnosis`, `work_record_maintenance` | `work_item_read`, `runtime_observe`, `repository_read`, `repository_search`, `history_read`, `artifact_write` | Required; `initialize`                                                     |
| `failure-topology`       | `dependency_analyst`         | investigation | standard       | `dependency_mapping`, `destination_integration`, `architecture_mapping`, `failure_diagnosis`                          | `repository_read`, `repository_search`, `history_read`, `dependency_inspect`, `artifact_write`                | Deep only; after `evidence-topology`                                       |
| `repository-integration` | `repository_integrator`      | investigation | standard       | `destination_integration`, `architecture_mapping`, `operational_readiness`                                            | `repository_read`, `repository_search`, `history_read`, `artifact_write`                                      | Required for `deep`; conditional for `standard`; after `evidence-topology` |
| `fix-design`             | `solution_architect`         | investigation | standard       | `failure_diagnosis`, `architecture_mapping`, `workflow_planning`                                                      | `artifact_write`, `work_record_write`                                                                         | Required after evidence in standard; after `failure-topology` and integrator in deep |
| `implement`              | `implementer`                | delivery      | standard       | `failure_diagnosis`, `build_and_test`                                                                                 | `repository_read`, `repository_write`, `build_run`, `test_run`, `work_record_write`                           | Approval plus `fix-design`                                                 |
| `review`                 | `reviewer`                   | review        | standard       | `architecture_mapping`, `build_and_test`, `operational_readiness`                                                     | `repository_read`, `diff_review`, `test_run`, `artifact_write`                                                | `implement`                                                                |
| `validate`               | `tester`                     | review        | standard       | `build_and_test`, `operational_readiness`                                                                             | `build_run`, `test_run`, `runtime_observe`, `artifact_write`                                                  | `review`                                                                   |
| `handoff`                | `documenter`                 | stabilization | quick          | `work_record_maintenance`                                                                                             | `work_record_read`, `work_record_write`, `artifact_write`                                                     | Continuous; initialized first                                              |

The delivery profile is `implement` ↔ `review` → `validate`. No additional discovery workers are started after approval
unless new evidence contradicts the diagnosis or expands the approved scope.

This delivery sequence is valid only inside an explicitly activated `remediation` run. The presence of an existing
`implementation_plan.md` is not evidence that remediation workers ran in the current run.

The Documenter runs continuously and records provider-reported model, effort, usage, and credits when available.

When workers run in parallel, the Orchestrator follows the shared contract's fan-in semantics: it waits for all required
workers, collects their result envelopes, and summarizes them before the stage or workflow can finish. Active worker
threads keep the workflow `in_progress`.

## Worker Results

Workers use the shared result envelope defined in the execution contract. Sentry-specific requirements are:

- `evidence-topology` owns raw Sentry queries for the run.
- Downstream workers consume normalized evidence artifacts.
- Workers repeat Sentry or repository analysis only when they identify and record a specific discrepancy.
- The Documenter records every worker result, blocker, synchronization state, model, effort, usage, and credits when
  available.

For `deep`, start `failure-topology` and `repository-integration` in parallel after `evidence-topology`. Both consume
the normalized evidence artifact and repeat raw queries only for a recorded discrepancy.

Provider-specific model, effort, and agent mappings are supplied by the selected provider adapter.

## Effort Escalation

Use the provider adapter's deep-effort setting for a worker when evidence shows:

- multiple repositories or services are involved;
- the failure is intermittent or concurrency-related;
- data loss, corruption, security, or financial impact is possible;
- the stack trace does not identify a credible code path;
- the fix changes a public contract or persistence behavior; or
- rollback and operational validation are non-trivial.

Do not choose high effort merely because the task involves code. Model capability and uncertainty determine the
appropriate setting.

## Implementation Plan

The planning lifecycle must produce an implementation plan before reaching `ready_for_implementation`. Create it from
[`templates/implementation_plan.md`](../templates/implementation_plan.md) at:

```text
<execution-repository>/.thoughts/<SENTRY-ISSUE-ID>/implementation_plan.md
```

The plan is a design artifact, not authorization to change source code. It is the execution source for the remediation
lifecycle and must contain the template's scope, root cause and contract, source changes, test and validation plan,
ordered execution steps, risks and operations, and completion criteria. The `work_record.md` must link to the plan
before the workflow reaches `ready_for_implementation`. The plan must state when a step is skipped, unavailable, or
inconclusive; no worker may silently replace a failed or unavailable step with an unsupported claim of success.

## Execution Flow

### Stage 0 — Initialize

The active Orchestrator runs first. It may be the current main session or a provider-specific coordinator agent with
worker-delegation capability. A provider coordinator child must not be used when the runtime does not support nested
delegation; in that case, the current main session owns the worker fan-out directly.

The Orchestrator creates the work record, selects the execution profile and lifecycle, declares worker dependencies, and
starts the continuous Documenter. It records `profile_status: requested` before spawning the first investigation worker.

Use the prompt's declared `Execution repository` as the durable-artifact root. Code repositories listed for Sentry
investigation must not receive the work record or worker artifacts.

Recover or create:

```text
<execution-repository>/.thoughts/<SENTRY-ISSUE-ID>/work_record.md
```

Do not create `implementation_plan.md` during initialization. Create it after all required planning workers have
returned terminal result envelopes, fan-in is complete, and the workflow is ready for implementation. Normal release
drift, a missing older event sample, or unavailable persisted rows do not prevent plan creation when the candidate fault
path and proposed fix are otherwise supported. Until the planning gate passes, the work record must state why the plan
has not been created and give the recovery or decision needed.

Record the issue, repository, revision, scope, owner, acceptance criteria, unknowns, and safety constraints.

Record the repository/event topology and any optional supporting artifacts.

### Stage 1 — Collect Sentry Evidence

The `evidence-topology` worker owns raw Sentry queries for the run. Use MCP to inspect the issue and latest event first.
Capture:

- issue title, status, priority, occurrence count, and latest event;
- culprit, stack context, environment, release, and timestamp;
- affected users and frequency, when available;
- tags, breadcrumbs, request context, and related event context when needed; and
- uncertainty, missing data, and possible PII.

Use an older representative event only when the latest event is insufficient, inconsistent, or the symptom may vary by
occurrence. Do not inspect every event in a high-volume issue by default. Record the selected event IDs and the reason
for any additional sample.

Publish one normalized evidence artifact containing the Sentry facts, latest event as the primary occurrence, any
justified representative sample, initial repository/revision mapping, initial topology, code-path entry point, source
references, and unresolved boundary questions. Downstream workers consume this artifact instead of repeating the same
Sentry queries.

The Orchestrator also records each prompt-supplied artifact and material
context as consumed, unavailable, conflicting, or out of scope. The original
artifact references remain available to downstream workers when the normalized
artifact omits details needed for diagnosis.

Do not print or persist secrets or unnecessary personal data.

### Stage 2 — Analyze Failure Topology

In `deep`, the `failure-topology` worker consumes the normalized evidence artifact. Trace the path from entry point to
failure outcome across repositories, queues, callbacks, dependencies, ownership, and return paths. Challenge the initial
root-cause hypothesis and record competing explanations.

In `standard`, there is no standalone failure-topology worker. The `solution_architect` performs bounded failure
analysis after the evidence stage and records only the topology needed to design the approved-scope fix.

For `deep`, activate `repository-integration` after Stage 1 regardless of whether the initial evidence appears
sufficient. For `standard`, activate it only if repository ownership, monorepo boundaries, deployment responsibility, or
the approved change scope remains uncertain. A local/deployed revision mismatch or a Sentry release lookup failure alone
does not require this worker. Its result is an additional input to fix design, not a second copy of the entire
investigation.

Do not require the user to repeat repository or revision information already present in the Sentry context.

### Stage 3 — Diagnose and Reproduce

In `deep`, the `failure-topology` worker owns independent diagnosis and reproduction planning. In `standard`, the
`solution_architect` owns bounded diagnosis and reproduction planning after consuming the normalized Sentry evidence.
Form competing hypotheses appropriate to the selected profile and reproduce or verify the failure with the smallest safe
test or local scenario. The `tester` owns executable validation during the remediation lifecycle. Use Seer only as
optional supporting evidence.

Before requesting clarification, apply the shared
[Evidence-to-Hypothesis Gate](../contracts/workflow_execution.md#evidence-to-hypothesis-gate).
The fix-design result must show which Sentry evidence, user context, and
supporting artifacts it consumed; confirmed facts; the strongest hypothesis;
the smallest local or repository check it actually executed; the result in
`checks_performed`; remaining unavailable checks in `checks_remaining`; and a
plain-language next action. Missing production payloads, release mapping, or
older events are uncertainties unless they are indispensable to a safe
decision. Do not ask for production evidence before running an available local
replay or source-level check.

The stage must conclude with:

- confirmed root cause;
- best-supported hypothesis with residual uncertainty; or
- a clarification brief with feasible next paths, recommendation, and the smallest decision owner when a product or
  design decision remains; or
- blocked diagnosis only when required evidence or an environment is unavailable, with the missing evidence and owner.

An implementation plan does not require an exact production-to-checkout SHA, comparison of every event, or persisted-row
inspection unless one of those items is material to the proposed fix. Record unresolved release mapping, event-sampling
limits, or unavailable persistence access as explicit risks and validation steps instead of turning normal production
drift into a blocker.

### Stage 4 — Design the Fix

The `solution_architect` consumes the evidence artifact and any `repository-integration` result. For `deep`, it also
consumes the independent topology result. Produce the complete implementation plan content, including the smallest safe
correction, regression-test strategy, compatibility impact, rollout, rollback, monitoring plan, execution steps, and
completion criteria. The Documenter persists it as `implementation_plan.md` and updates the work_record.md Durable
Artifacts section with a relative link to the plan. Do not implement until the workflow reaches
`ready_for_implementation` and approval is recorded.

If the evidence supports more than one credible fix, record the alternatives, tradeoffs, validation impact, and a
recommendation in the implementation plan when a safe recommendation is possible. Do not ask the user to resolve a
technical hypothesis that the workers can investigate or validate. Use the shared Clarification Brief and hand off
`awaiting_input` only when a material business, scope, ownership, or incompatible-alternatives decision remains after
bounded discovery and cannot be resolved by a recommendation. Do not create a plan only when that genuine decision
prevents a safe implementation scope.

A clarification result is incomplete if it only requests production data or
repeats an unresolved question without reporting the consumed evidence,
strongest hypothesis, `checks_performed`, and concrete next action. Record
unavailable checks in `checks_remaining`. The Coordinator must return that
result for continuation when the worker runtime supports it, or preserve the
incomplete status and limitation.

The remediation boundary is the explicit set of source files, symbols, configuration, dependencies, tests, and
operational surfaces that the proposed change may touch. The Solution Architect selects it from current evidence; the
user approves it through the implementation-approval gate. The handoff must name that scope in plain language rather
than asking the user to “select the remediation boundary.”

### Stage 5 — Re-enter Remediation and Implement

Enter this stage only after the lifecycle re-entry rules and approval gate pass. Execute only the approved
`implementation_plan.md`. Add a regression test that demonstrates the failure where practical. Avoid unrelated
refactoring and preserve existing behavior outside the confirmed cause.

### Stage 6 — Code Review and Validate

Follow the plan's review and validation steps. Review the diff independently, then run targeted tests, the relevant
broader suite, static checks, and smoke or operational checks appropriate to the risk.

In-scope review findings return to `implement` and are re-reviewed before validation. Reopen planning only when evidence
invalidates the confirmed cause or approved fix boundary.

Use the lowest validation level that can prove the claim, then escalate when risk or the repository requires it:

1. Focused unit or pure-function test.
2. Local project integration test using the repository's native test harness.
3. Repository CI, broader suite, or contract test.
4. Post-release Sentry and operational verification.

Record each level as `pass`, `fail`, `skipped`, `unavailable`, or `inconclusive`. `unavailable` and `inconclusive` are
not passes. A container or external service is introduced only when a selected validation level actually requires it.

The regression test should fail against the pre-fix behavior when practical and pass after the fix. Unavailable or
inconclusive validation is not a pass.

### Stage 7 — Stabilize and Hand Off

Complete the plan's rollout, rollback, monitoring, ownership, and follow-up requirements. Updating the Sentry issue
status is a separate human-approved action through the MCP integration.

## Gates

| Gate                 | Required condition                                                     |
| -------------------- | ---------------------------------------------------------------------- |
| Investigation ready  | Sentry evidence and a candidate source path are identified; exact production-to-checkout mapping may remain an explicit uncertainty |
| Diagnosis ready      | Root cause or best-supported hypothesis is recorded with evidence and residual uncertainty |
| Implementation ready | Fix scope, tests, risks, and rollback are approved                     |
| Validation ready     | Review findings are resolved or accepted                               |
| Handoff ready        | Validation, rollout, monitoring, ownership, and follow-up are explicit |

## Success Criteria

The workflow succeeds when:

- the Sentry evidence is recorded and redacted;
- the deployed revision and repository path are reconciled, or the unresolved mapping and its validation impact are
  explicit;
- the root cause is evidence-backed;
- the fix addresses the cause rather than only the symptom;
- regression coverage exists or its absence is justified;
- validation results are objective and preserved;
- every worker has a summarized terminal result and synchronization status;
- requested, activated, and executed profiles, including profile status, are explicit;
- residual and operational risks are explicit; and
- the work record identifies the next owner and action.

## Required Handoff Output

The final handoff is ordered as follows:

1. Shared outcome summary: status, verified scope, root cause, fix, validation, implementation-plan path and status, and
   next action. Explain the next action in plain language, name its owner, identify the file or system where it is
   performed, and state what completion looks like. Do not use unexplained phrases such as “select the remediation
   boundary.”
2. Worker result ledger: one compact row per activated worker and each required worker without a terminal envelope,
   using the shared contract's ledger fields.
3. Profile, gate, and synchronization status: distinguish requested, activated, and executed profile, then confirm that
   all required workers are terminal and all required fan-in barriers passed and the prior run's worker handles are
   released.
4. Remaining risks, blockers, clarification brief when input is required, and ownership.

Also include the shared Human-Readable Handoff block: `What happened`, `What this means`, `Internal owner`,
`What you need to do`, and `To continue`. If no technical user action is needed, say `Nothing technical.`
For a retryable worker runtime failure, `To continue` should give the exact request: `Retry the planning run.`

The handoff must not imply that implementation or validation completed when the workflow stopped at an approval or
unavailable-environment gate.

## Related Documents

- [`../templates/sentry_issue_run_prompt.md`](../templates/sentry_issue_run_prompt.md)
- [`../templates/work_record.md`](../templates/work_record.md)
- [`../templates/implementation_plan.md`](../templates/implementation_plan.md)
- [`../examples/sentry_issue_remediation.md`](../examples/sentry_issue_remediation.md)

## Terminal Outcomes

In addition to the common contract outcomes, this playbook may close as:

- `fixed_pending_release`;
- `not_reproducible`;
- `expected_behavior_noise`;
- `insufficient_evidence`; or
- `deferred_to_incident_workflow`.

Each outcome requires evidence and a reason.
