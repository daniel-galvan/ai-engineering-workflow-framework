---
title: Sentry Issue Remediation Playbook
version: 0.4.10
status: Pilot
maturity: exercising
exercise_scope: standard + planning; deep + planning; standard + remediation; deep + remediation
validation_summary: all combinations exercised; mixed reliability; not delivery-validated
owner: Engineering
last_updated: 2026-08-31
depends_on:
  - ../frameworks/investigation.md
  - ../strategies/collaborative.md
  - ../contracts/workflow_execution.md
  - ../contracts/claims.md
  - ../templates/sentry_work_record.md
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

- For `live_sentry`: a stable Sentry issue URL or identifier, access to the relevant Sentry organization and project,
  and one or more relevant repository checkouts or working directories
- For `supplied_occurrence`: the current-run occurrence artifact and one or more relevant repository checkouts or
  working directories; live Sentry identity and access are optional
- For `mixed`: the `live_sentry` inputs plus the current-run occurrence artifact

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

Also distinguish the event emitter, comparison owner, baseline producer, deployed route owner, candidate divergence
owner, and confirmed defect owner. Sentry attribution proves the event-emission point, not the underlying defect owner.
A local checkout that rejects the observed production event establishes a revision or deployment mismatch; it does not
exclude that service from the deployed path until release or deployment mapping is verified.

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

`standard` is bounded by its worker graph and evidence rules. Its pilot target is 10-12 minutes when triage ends
`awaiting_input`, and 15-17 minutes when cross-repository analysis produces a complete implementation plan. If provider
latency or a worker runtime exceeds the applicable target, record the duration and critical-path cause; do not
compensate by skipping a required worker or claiming completion early.

For Standard, target evidence-worker activation within 60 seconds of turn start. Validate completed normalized evidence
before activating Fix Design; Standard does not parallelize those two dependent stages. After Fix Design returns either
`awaiting_input/omit` or `ready_for_implementation/create`, release every activated analytical worker and use the
packaged deterministic Standard finalizer. Do not activate a Documenter for either Standard planning result.

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
profile. The requested profile is immutable for the run. A different profile requires a new explicit user request;
uncertainty may increase one worker's effort without changing the run profile.

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
6. reuse completed planning artifacts and activate `implement`, `review`, and `validate` before source changes;
7. wait for every required result envelope and complete fan-in before closing the remediation stage; and
8. activate final `handoff` after delivery fan-in;
9. complete the shared worker-runtime closure barrier before closing the prior run or starting another lifecycle run;
   and
10. report the remediation run's lifecycle, worker activation, fan-in, and runtime-closure status.

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

- `standard + planning`: Coordinator initialization, `evidence-topology`, and `fix-design`, followed by deterministic
  finalization for either readiness result. The `fix-design` worker performs bounded failure analysis before designing
  the fix or returning a structured clarification brief.
- `deep + planning`: all standard planning workers plus `failure-topology` and mandatory `repository-integration`.
- `standard + remediation`: reuse completed standard planning artifacts, activate `implement`, `review`, and `validate`
  after approval, then activate final `handoff` after delivery fan-in.
- `deep + remediation`: reuse completed deep planning artifacts, activate `implement`, `review`, and `validate` after
  approval, then activate final `handoff` after delivery fan-in.

## Profile Execution

The shared execution contract defines profile execution, fan-in, and no-downgrade semantics. For this playbook:

- `standard` activates the standard planning worker set.
- `deep` activates the standard planning worker set plus `failure-topology` and mandatory `repository-integration`.
- The Orchestrator waits for every required worker before completing diagnosis or fix design.
- The final handoff uses the shared human-readable template; detailed worker results remain in the work record.

## Worker Profiles

The standard planning profile has two active analytical roles. Packaged code renders either the implementation plan or
clarification brief. The Solution Architect performs bounded failure analysis and fix design in that profile. Deep adds
an independent Failure Topology Analyst and mandatory Repository Integrator. Repository
Integrator remains conditional for standard.

| Worker                   | Role                         | Mode          | Default effort | Skills                                                                                                                | Tools                                                                                                         | Activation / depends on                                                    |
| ------------------------ | ---------------------------- | ------------- | -------------- | --------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| `evidence-topology`      | `current_state_investigator` | investigation | standard       | `work_item_context`, `repository_exploration`, `architecture_mapping`, `failure_diagnosis`, `work_record_maintenance` | `work_item_read`, `runtime_observe`, `repository_read`, `repository_search`, `history_read`, `artifact_write` | Required; Coordinator initialization                                      |
| `failure-topology`       | `dependency_analyst`         | investigation | standard       | `dependency_mapping`, `destination_integration`, `architecture_mapping`, `failure_diagnosis`                          | `repository_read`, `repository_search`, `history_read`, `dependency_inspect`, `artifact_write`                | Deep only; after `evidence-topology`                                       |
| `repository-integration` | `repository_integrator`      | investigation | standard       | `destination_integration`, `architecture_mapping`, `operational_readiness`                                            | `repository_read`, `repository_search`, `history_read`, `artifact_write`                                      | Required for `deep`; conditional for `standard`; after `evidence-topology` |
| `fix-design`             | `solution_architect`         | investigation | standard       | `failure_diagnosis`, `architecture_mapping`, `workflow_planning`                                                      | `repository_read`, `repository_search`, `test_run`                                                            | Required; after validated evidence in standard; after `failure-topology` and integrator in deep |
| `implement`              | `implementer`                | delivery      | standard       | `failure_diagnosis`, `build_and_test`                                                                                 | `repository_read`, `repository_write`, `build_run`, `test_run`, `work_record_write`                           | Approval plus `fix-design`                                                 |
| `review`                 | `reviewer`                   | review        | standard       | `architecture_mapping`, `build_and_test`, `operational_readiness`                                                     | `repository_read`, `diff_review`, `test_run`, `artifact_write`                                                | `implement`                                                                |
| `validate`               | `tester`                     | review        | standard       | `build_and_test`, `operational_readiness`                                                                             | `build_run`, `test_run`, `runtime_observe`, `artifact_write`                                                  | `review`                                                                   |
| `handoff`                | `documenter`                 | stabilization | quick          | `work_record_maintenance`                                                                                             | `work_record_read`, `work_record_write`, `artifact_write`                                                     | Deep and remediation finalization                                           |

The delivery profile is `implement` ↔ `review` → `validate`. No additional discovery workers are started after approval
unless new evidence contradicts the diagnosis or expands the approved scope.

The Coordinator performs initialization directly; never activate or delegate an `initialize` worker.

This delivery sequence is valid only inside an explicitly activated `remediation` run. The presence of an existing
`implementation_plan.md` is not evidence that remediation workers ran in the current run.

For either Standard planning readiness result, use deterministic finalization after analytical fan-in. Activate one
final Documenter only for Deep planning and remediation. An initialization acknowledgement is not a final handoff. The
Documenter records provider-reported model, effort, usage, and credits when available.

When workers run in parallel, the Orchestrator follows the shared contract's fan-in semantics: it waits for all required
workers, collects their result envelopes, and summarizes them before the stage or workflow can finish. Active worker
threads keep the workflow `in_progress`.

## Worker Results

Workers use the shared result envelope defined in the execution contract. Sentry-specific requirements are:

- The Coordinator activates every delegated worker with fresh context (`fork_context: false` or provider equivalent).
  Every packet starts with `Coordinator initialization: complete`; workers do not rerun the launcher, preflight, run
  preparation, or edit the work record.
- `evidence-topology` owns raw Sentry queries for the run.
- When the prompt supplies a stable Sentry issue ID or URL, resolve that issue directly before any project or issue
  search, then request the latest issue event first (`limit: 1` when supported). If direct resolution fails, perform at
  most one justified fallback search and stop with bounded uncertainty; do not enumerate projects or fan out across
  organizations and datasets.
- Downstream workers consume normalized evidence artifacts.
- Fix Design writes one canonical JSON result to its assigned `fix_design_result.json` path after receiving the exact
  activation handle. The Coordinator validates that file and does not reconstruct it from a worker message.
- A ready Standard result includes complete structured `plan` content. An `awaiting_input` result includes a complete
  structured `clarification_brief`. Packaged code renders the selected artifact; no model translates or paraphrases it.
- Workers repeat Sentry or repository analysis only when they identify and record a specific discrepancy.
- On Deep and remediation paths, the Documenter records every worker result, blocker, synchronization state, model,
  effort, usage, and credits when available.

For `deep`, start `failure-topology` and `repository-integration` in parallel after `evidence-topology`. Both consume
the normalized evidence artifact and repeat raw queries only for a recorded discrepancy.

Provider-specific model, effort, and agent mappings are supplied by the selected provider adapter. The Orchestrator
MUST pass each named definition's exact model and reasoning effort when the runtime would otherwise inherit its own
settings. This explicit configuration binding is required; a different value is an adaptive escalation and control
failure.

## Effort Escalation

Use the provider adapter's deep-effort setting for a worker when evidence shows:

- multiple repositories or services are involved;
- the failure is intermittent or concurrency-related;
- data loss, corruption, security, or financial impact is possible;
- the stack trace does not identify a credible code path;
- the fix changes a public contract or persistence behavior; or
- rollback and operational validation are non-trivial.

Do not choose high effort merely because the task involves code. Model capability and uncertainty determine the
appropriate setting. Worker effort escalation does not activate the `deep` graph or change requested, activated, or
executed profile.

## Implementation Plan

The planning lifecycle must produce an implementation plan before reaching `ready_for_implementation`. Create it from
[`templates/implementation_plan.md`](../templates/implementation_plan.md) at:

```text
<execution-repository>/.thoughts/<WORK-ITEM-ID>/implementation_plan.md
```

The plan is a design artifact, not authorization to change source code. It is the execution source for the remediation
lifecycle and must contain the template's scope, root cause and contract, source changes, test and validation plan,
ordered execution steps, risks and operations, and completion criteria. The `work_record.md` must link to the plan
before the workflow reaches `ready_for_implementation`. The plan must state when a step is skipped, unavailable, or
inconclusive; no worker may silently replace a failed or unavailable step with an unsupported claim of success.

Fix Design controls plan creation through its result envelope. When
`plan_readiness: awaiting_input`, it MUST set `implementation_plan_action: omit`;
Fix Design records a structured Clarification Brief and the packaged finalizer MUST NOT create a conditional plan.
Only `plan_readiness: ready_for_implementation` with action `create`
permits the plan artifact.

For Standard planning, evidence owns event details, Fix Design owns hypotheses and the proposed boundary, the work
record owns decisions and execution state, and the plan owns only the selected change, gates, and validation. Reference
the owning artifact instead of repeating it. Normal runs have no byte-count field or hard size gate; the validator may
emit a non-blocking internal warning for an unusually large work record. For Standard planning,
`scripts/finalize_sentry_planning.py` stages and validates the complete terminal artifact set, then publishes it
transactionally. It uses `scripts/finalize_work_record.py` to render the terminal record in that staged set.
Deep and remediation Documenter-owned paths retain the structured packet and pre-release flow.

## Execution Flow

### Stage 0 — Initialize

The active Orchestrator runs first. It may be the current main session or a provider-specific coordinator agent with
worker-delegation capability. A provider coordinator child must not be used when the runtime does not support nested
delegation; in that case, the current main session owns the worker fan-out directly.

For Standard Sentry planning, initialization is limited to capturing turn start, verifying framework and repository
identity/status, registering authoritative inputs, resolving the durable-artifact root, creating the minimal work-record
skeleton, resolving the evidence worker configuration, and activating that worker. Candidate-source searches, history
searches, tests, Sentry queries, and technical diagnosis before activation are control failures.
The launcher and prepared worker contracts are the compact Standard runtime surface; do not hydrate the complete
playbook, generic work-record template, workflow execution contract, or claims contract before preparation.

The Orchestrator creates the work record, selects the execution profile and lifecycle, declares worker dependencies,
and records `profile_status: requested` before spawning the first investigation worker. It activates a final Documenter
only for Deep planning or remediation after analytical fan-in.

Initialize the run identity before the first worker. Populate evaluation identity and detailed continuation, activation,
and timing ledgers only when the request explicitly declares an evaluation or benchmark run.

For a versioned evaluation run, the launcher preflight verifies the prompt's framework Git revision against the
checkout containing this playbook before loading it. Manual runs perform the same check before reading this playbook.
Stop with `framework_revision_mismatch` when HEAD differs or the framework worktree is dirty; regenerate the prompt
from a clean revision instead of running against moving instructions. Record `preflight_elapsed_ms` and
`worker_activation_attempts: 0` for this blocked path. A stale plugin path stops with
`plugin_revision_mismatch`; do not search another cache version or silently substitute a checkout. Do not create,
switch, or detach another framework worktree to make a stale prompt match.

For Standard planning, initialization writes only a minimal work-record skeleton. On a preflight block, populate the
required reasoning tables once and validate the blocked record once; do not progressively repair the artifact. After a
successful activation, the Coordinator keeps intermediate worker state in runtime and passes it to the deterministic
Standard finalizer or, for Deep/remediation, the final Documenter. It does not progressively rewrite the record between
analytical workers. Evaluation timing remains limited to an explicitly declared experimental evaluation or benchmark
run.

After preflight, run packaged `scripts/prepare_run.py` once with the execution repository, work item, playbook name,
and optional verified runtime-agent directory. Its `role_bindings.json` output is the worker spawn source of truth. A
fresh run archives prior terminal artifacts before creating the new record; only an explicit continuation reuses the
current record. The helper starts Sentry runs from `templates/sentry_work_record.md`; use the full work-record template
only as reference for an uncommon section instead of copying it wholesale.

Use the prompt's declared `Execution repository` as the durable-artifact root. Code repositories listed for Sentry
investigation must not receive the work record or worker artifacts.

Recover or create:

```text
<execution-repository>/.thoughts/<WORK-ITEM-ID>/work_record.md
```

Do not create `implementation_plan.md` during initialization. Create it after all required planning workers have
returned terminal result envelopes, fan-in is complete, and the workflow is ready for implementation. Normal release
drift, a missing older event sample, or unavailable persisted rows do not prevent plan creation when the candidate fault
path and proposed fix are otherwise supported. Until the planning gate passes, the work record must state why the plan
has not been created and give the recovery or decision needed.

Record the issue, repository, revision, scope, owner, acceptance criteria, unknowns, and safety constraints.

Before worker activation, record whether another run uses the same execution repository or work item. Standard planning
may share a clean read-only revision. When another run is active, remediation or any run with source or artifact writers
requires a separate managed worktree and durable run root. A concurrent run for the same Sentry issue stops with
`run_already_active` unless this is an explicit continuation or recovery run.

Record the repository/event topology and any optional supporting artifacts.

### Stage 1 — Collect Sentry Evidence

The `evidence-topology` worker exclusively owns raw Sentry queries and initial repository topology for the run. The
Orchestrator does not pre-query Sentry or duplicate repository exploration. Use MCP to inspect the issue and request
only the latest event first (`limit: 1` when supported).
Classify the evidence source before querying: `live_sentry` requires a stable issue ID or URL; `supplied_occurrence`
uses the current-run artifact without broad Sentry discovery; `mixed` uses both. An explicit Sentry issue URL or a
separately identified Sentry issue ID selects live lookup. When this Sentry playbook is explicitly selected and the
prompt describes the reported occurrence as a Sentry issue, a Sentry-shaped work-item key is a candidate issue ID:
attempt direct resolution once, without search. If it resolves, use `live_sentry` or `mixed`; if it does not, retain
`supplied_occurrence` and the bounded uncertainty. Never state that the key is not a Sentry identifier before attempting
that direct resolution. Standard planning permits
one tool discovery call and at most three Sentry data queries total: direct issue resolution, latest event, and one
justified discriminating follow-up. Stop each query after 30 seconds and stop Sentry investigation after 90 seconds
total. Return the bounded partial result when a limit is reached; a timeout does not authorize broader searches.
Bound initial source mapping to the reporting repository's stack or culprit entry, outbound endpoint, and direct return
boundary required by fix design. Do not inspect an additional repository's internal compatibility or deployment path in
this stage; that belongs to Repository Integrator when its activation gate passes.
Capture:

- issue title, status, priority, occurrence count, and latest event;
- culprit, stack context, environment, release, and timestamp;
- affected users and frequency, when available;
- tags, breadcrumbs, request context, and related event context when needed; and
- uncertainty, missing data, and possible PII.

Use an older representative event only when the latest event is insufficient, inconsistent, or the symptom may vary by
occurrence. Do not inspect every event in a high-volume issue by default. Record the selected event IDs and the reason
for any additional sample.

The evidence worker MUST write one canonical `normalized_evidence.md` artifact containing the full material field values
and source references needed to preserve field-local distinctions. It includes the Sentry facts, latest event as the
primary occurrence, any justified representative sample, initial repository/revision mapping, initial topology,
code-path entry point, source references, and unresolved boundary questions. Standard Fix Design starts only after this
artifact exists and passes artifact validation. It consumes the exact normalized artifact path and must not repeat raw
Sentry queries except for a named discrepancy.

The artifact MUST contain this compact table, using `Not established` for unevidenced values rather than inferring them:

```text
# Contract Delta
| Boundary | Representation | Field identity / coordinate space | Evidence refs |
| --- | --- | --- | --- |
| Baseline | ... | ... | ... |
| Outbound | ... | ... | ... |
| Destination input | ... | ... | ... |
| Return | ... | ... | ... |
| Semantic input equivalence | equivalent / not_equivalent / not_established | Not applicable | ... |
```

Before returning, the evidence worker MUST run
`python3 <packaged-framework-root>/scripts/validate_library.py --normalized-evidence <artifact-path>` and correct the
artifact within its initial activation when validation fails. This producer-side check is not an analytical correction.

The Orchestrator also records and passes through each prompt-supplied artifact and material
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
sufficient. For `standard`, activate it only when one explicit cross-repository question remains, the typed assignment
names the local evidence that can answer it, and the answer can change a named
ownership, readiness, or scope disposition.
Record the question and expected disposition before activation as `answerable_by_local_source` and
`decision_expected_to_change`; both must be true. If the disposition cannot be stated or the remaining question
requires production state that local source cannot provide, skip Repository Integrator. If normalized evidence already
answered the question, skip Repository Integrator instead of repeating it.
A local/deployed revision mismatch, a Sentry release lookup failure, or missing production state that local source
cannot supply does not require this worker. Its result is an additional input to fix design, not a second copy of the
entire investigation. Its result envelope records `decision_changed` and the exact changed or unchanged disposition.

Do not require the user to repeat repository or revision information already present in the Sentry context.

### Stage 3 — Diagnose and Reproduce

In `deep`, the `failure-topology` worker owns independent diagnosis and reproduction planning. In `standard`, the
`solution_architect` owns bounded diagnosis and reproduction planning after normalized evidence passes validation.
Form competing hypotheses appropriate to the selected profile and reproduce or verify the failure with the
smallest safe test or local scenario. The `tester` owns executable validation during the remediation lifecycle. Use
Seer only as optional supporting evidence.

In planning, do not run unit or integration tests merely to establish a baseline. Run one existing focused test only
when its result can confirm or reject a leading hypothesis, identify the owning repository, or change readiness. Before
running it, record the hypothesis, expected discriminating outcomes, disposition change, and a bounded executable
preflight. If it only confirms an already-proven branch or its runner is known to be unavailable, defer it. Do not
repair environments, install missing test tools, or run broad suites. Put the focused regression and remaining suites
in the implementation plan for remediation.

The Solution Architect accepts source paths and citations already verified in normalized evidence. It does not remap
that path without a named discrepancy. In Standard, the Coordinator must verify that the terminal result consumed the
exact normalized-evidence path; if it did not, return one correction to the same worker before fan-in. When missing
indispensable evidence already selects `needs_input`, execute only the one smallest available check that could change
that disposition before returning the gate result.

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

Use engineering state `understood` when the current behavior, first observable divergence, and material uncertainty are
evidence-backed even though causal ownership remains unknown. Reserve `unknown` for a run that has not established the
current behavior or material problem scope.

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
completion criteria. For Standard ready planning, return that content as the structured `plan` field and let the
packaged finalizer persist `implementation_plan.md`; for Standard `awaiting_input`, return the structured
`clarification_brief` for the same finalizer. Deep/remediation Documenter-owned paths retain their handoff behavior. Do
not implement until the workflow reaches
`ready_for_implementation` and approval is recorded.

Fix Design returns a complete structured result with `worker_id`, `worker_handle`, `outcome`, `plan_readiness`,
`implementation_plan_action`, `inputs_consumed`, `context_conformance`, `configuration_conformance`,
`checks_performed`, `checks_remaining`, `supported_remediation_boundary`, `supported_intended_change`,
`interface_change`, `interface_contract`, `blocking_unknowns`, canonical `confidence` with `level`, `basis`, and
`limits`, complete structured `plan` content when ready, and complete structured `clarification_brief` content when
awaiting input. For an
API, event, payload, schema, or other
interface change, the contract identifies the exact surface, request and response shapes, absence semantics,
compatibility precedence, and rollout. Fix Design persists that result directly as `fix_design_result.json`.
Packaged code creates either the ready Standard plan or `awaiting_input` Clarification Brief. Fix Design does not edit
source, the work record, or any durable artifact except its assigned Fix Design result.

The result uses the exact activation handle and shared terminal outcome
`complete`. String fields remain strings, list fields remain lists, and
`interface_change` remains a boolean. `inputs_consumed` MUST include either the
canonical normalized-evidence Input ID `UPSTREAM-001` or the exact validated
`normalized_evidence.md` path; the activation packet delivers both plus the
prepared `fix_design_result_contract.json` and assigned output path. Before validation, the Coordinator
runs packaged `normalize_fix_design_result.py --artifact-root <artifact-root>`.
This explicit producer-format repair may only convert equivalent representations
to canonical field types and does not consume the analytical correction
allowance; it never changes readiness, outcomes, evidence, the selected
boundary, or the intended change.

If the evidence supports more than one credible fix, record the alternatives, tradeoffs, validation impact, and a
recommendation in the implementation plan when a safe recommendation is possible. Do not ask the user to resolve a
technical hypothesis that the workers can investigate or validate. Use the shared Clarification Brief and hand off
`awaiting_input` only when a material business, scope, ownership, or incompatible-alternatives decision remains after
bounded discovery and cannot be resolved by a recommendation. Do not create a plan only when that genuine decision
prevents a safe implementation scope.

Every blocking unknown MUST name its decision type, question, unavailable reason, evidence references, and at least two
materially different fix implications. Do not return `awaiting_input` after the evidence establishes a remediation
boundary and intended change unless every blocker is evidenced to invalidate that change. A blocker marked
`invalidates_supported_change: true` MUST include `contradicting_evidence_refs` to observed current-run evidence for a
materially different boundary or fix and at least one structured `observed_competing_boundaries` entry containing the
competing boundary, an affirmative current-run observation, and its evidence refs. Missing runtime confirmation,
unavailable release mapping, and a merely possible code path are validation gates, not observed competing evidence.

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
| Implementation ready | Shared semantic readiness threshold and planning fan-in passed; plan exists |
| Validation ready     | Review findings are resolved or accepted                               |
| Handoff ready        | Validation, rollout, monitoring, ownership, and follow-up are explicit |

`Implementation ready` requires an evidence-supported owning boundary and intended change. When missing same-item,
runtime, or contract evidence could select among different causes, repositories, or fixes, keep the plan `Draft` and
return a Clarification Brief. Do not promote a plan merely because evidence collection can be written as step 1.

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
   When the cause remains uncertain, include `Best current explanations` with the strongest hypothesis and no more than
   two alternatives, each with confidence and a short reason. Include a rejected hypothesis only when it clarifies the
   result.
2. Profile, gate, and synchronization status: distinguish requested, activated, and executed profile, then confirm that
   all required workers are terminal and all required fan-in barriers passed and the prior run's worker handles are
   released.
3. Remaining risks, blockers, clarification brief when input is required, and ownership.

Use the shared Human-Readable Handoff template with distinct `Workflow outcome` and `Engineering outcome` fields. The
next-action owner must be able to access and complete the named evidence or engineering action.
For a retryable worker runtime failure, `To continue` should give the exact request: `Retry the planning run.`

When missing evidence keeps the plan Draft, name the internal owner, next-action owner, system, artifact, and completion
condition. Do not say `Nothing technical.` if the user must supply evidence, authorize access, or make a decision.

For Standard Sentry planning, use these canonical durable artifacts when applicable:

- `.thoughts/<WORK-ITEM-ID>/work_record.md`
- `.thoughts/<WORK-ITEM-ID>/normalized_evidence.md`
- `.thoughts/<WORK-ITEM-ID>/normalized_evidence_contract.md`
- `.thoughts/<WORK-ITEM-ID>/fix_design_result.json`
- `.thoughts/<WORK-ITEM-ID>/fix_design_result_contract.json`
- `.thoughts/<WORK-ITEM-ID>/clarification_brief.md` when the result is `awaiting_input`
- `.thoughts/<WORK-ITEM-ID>/implementation_plan.md` only when `plan_readiness=ready_for_implementation`

Final reconciliation validates this artifact set by name and disposition. An `awaiting_input` result without
`clarification_brief.md` fails finalization even when every other artifact is present.

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
