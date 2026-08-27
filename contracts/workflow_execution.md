---
title: Workflow Execution Contract
version: 0.4.6
status: Pilot
provider_independent: true
owner: Engineering
last_updated: 2026-08-27
---

# Workflow Execution Contract

> Define the smallest shared contract for reusable playbooks, roles, skills, tools, workers, and provider-neutral
> execution.

This contract is the seam between the workflow definition and the platform that executes it. A provider may implement
the contract differently, but it must preserve the same inputs, outputs, evidence expectations, and completion
semantics.

The contract contains shared normative behavior. Stage-specific contracts and explanatory guidance remain in linked
documents loaded only when needed. It supports sequential, parallel, and conditional playbooks without requiring a
general orchestration backend or a live work-item connector.

## Normative Language

The keywords **MUST**, **MUST NOT**, **SHOULD**, **SHOULD NOT**, and **MAY** in this document are normative. They mean
respectively: required, prohibited, recommended unless a documented reason applies, discouraged unless a documented
reason applies, and permitted.

## Document Classification

The [Workflow Invariants](#workflow-invariants), contract tables, lifecycle gates, state machine, artifact rules, and
[Pilot Conformance Checklist](#pilot-conformance-checklist) are the normative core. They define the minimum required
behavior. Rationale, provider examples, and explanations of how to satisfy a requirement are implementation guidance;
they do not create additional gates. This keeps the contract authoritative without treating its explanatory prose as a
second specification.

| Classification | Location | Purpose |
| --- | --- | --- |
| Normative core | Invariants, contract tables, lifecycle gates, state machine, artifact rules, extension rules, and conformance checklist | Defines required behavior and conformance. |
| Implementation guidance | [Workflow Execution Guidance](workflow_execution_guidance.md) and linked operating/provider guides | Explains examples and provider flexibility without changing required outcomes. |
| Normative checklist | [Pilot Conformance Checklist](#pilot-conformance-checklist) | Defines the minimum evidence required before a run may be called contract-compliant. |

Before initialization, a plugin-backed launcher MUST make package and framework preflight its first framework tool call.
It MUST derive the package root from the active installed skill, verify its catalog and manifest, compare any declared
framework revision, and check framework clean status before loading memory, cache directories, the selected playbook,
contracts, provider definitions, templates, or sibling artifacts. A stale plugin path or an unavailable, dirty, or
mismatched framework stops the run with the corresponding preflight reason; the launcher MUST NOT search another cache
version, silently substitute a checkout, activate workers, query external systems, or load the complete framework to
explain the block. A blocked preflight writes one minimal canonical work record, records
`preflight_elapsed_ms` and `worker_activation_attempts: 0`, and validates the record before handoff.
The process exit status is authoritative: a completed preflight with exit status 0 is passed even when stdout is hidden
by the host application. The launcher MUST NOT rerun a successful preflight solely to recover a missing display payload.

After preflight passes, at initialization the Coordinator MUST read the selected playbook, this contract, and the claims
contract. Other frontmatter dependencies are maintenance or stage references, not an instruction to load the complete
framework into the run context. Load a role, skill, strategy, integration, template, or example only when the active
worker or stage needs it. Templates and examples MUST NOT override the selected playbook or contracts.

The Coordinator alone performs package preflight and run preparation. It MUST activate delegated workers with fresh
provider context (`fork_context: false` or the provider-equivalent option), and every activation packet MUST begin with
`Coordinator initialization: complete`. Delegated workers MUST NOT invoke the launcher, package preflight, or run
preparation.

Delegated workers MUST run inside the current user task through the provider's subagent primitive, such as Codex
`spawn_agent`. Provider operations that create or fork user-owned tasks,
including Codex `create_thread`, `fork_thread`, and `send_message_to_thread`, MUST NOT be used as worker activation or
communication mechanisms. Before run preparation, the Coordinator MUST verify that an in-task worker/subagent runtime
is available. If it is unavailable, stop with `worker_runtime_unavailable`; do not create sidebar tasks and do not
substitute Coordinator analysis for the required graph.

The Coordinator passes typed assignments and relevant artifacts to downstream workers. Those workers MUST NOT reread
the complete playbook or core contracts by default; they load only their provider role instructions and the specific
section or template needed to resolve an ambiguity in their assigned stage. They MUST NOT search memory or historical
work records that the current run did not assign or explicitly reference unless higher-priority provider instructions
require a memory pass. Provider-required memory remains quarantined: no memory-derived fact, citation, ticket, path,
hypothesis, or conclusion may enter run evidence or influence a decision until current-run evidence independently
establishes it.

---

# Vocabulary

Canonical terms are defined in the [Workflow Vocabulary](workflow_vocabulary.md). Load that contract only when a term
needs clarification.

## Workflow Invariants

These invariants are the compact, testable surface of the detailed normative rules below. The referenced sections remain
the source of truth.

| ID | Invariant | Detailed rule |
| --- | --- | --- |
| `INV-01` | A run MUST declare one work item and one explicit execution repository. | [Work Item Contract](#work-item-contract); [Durable Artifact Root](#durable-artifact-root) |
| `INV-02` | A planning run MUST NOT modify source code or external systems. | [Workflow State Machine](#workflow-state-machine) |
| `INV-03` | A remediation run MUST have explicit implementation approval and recorded re-entry before source changes. | [Lifecycle Continuation and Re-entry](#lifecycle-continuation-and-re-entry) |
| `INV-04` | A requested execution profile MUST NOT be silently downgraded or reported as successfully executed at a lower profile. | [Profile Execution Semantics](#profile-execution-semantics) |
| `INV-05` | The Coordinator MUST NOT replace a required independent worker. | [Profile Execution Semantics](#profile-execution-semantics) |
| `INV-06` | Completion MUST require terminal envelopes for required workers and passed fan-in. | [Stage Completion and Fan-In](#stage-completion-and-fan-in) |
| `INV-07` | Runtime closure MUST be recorded before a run is closed or a new lifecycle run starts. | [Worker Runtime Closure](#worker-runtime-closure) |
| `INV-08` | Durable workflow artifacts MUST be stored under the execution repository's `.thoughts/<WORK-ITEM-ID>/`. | [Durable Artifact Root](#durable-artifact-root) |
| `INV-09` | Every material claim MUST identify evidence, confidence, uncertainty, and status. | [Evidence and Artifact Minimums](#evidence-and-artifact-minimums); [Claims Contract](claims.md) |
| `INV-10` | A decision is not approval; an action MUST have an authorizing decision and required gate. | [Evidence and Artifact Minimums](#evidence-and-artifact-minimums); [Claims Contract](claims.md) |
| `INV-11` | In-scope Code Review findings MUST return to implementation and review without requiring new approval. | [Delivery Code Review Loop](#delivery-code-review-loop) |
| `INV-12` | A handoff MUST report the actual profile, worker outcomes, limitations, artifact status, and a human-readable next action. | [Stage Completion and Fan-In](#stage-completion-and-fan-in); [Human-Readable Handoff](#human-readable-handoff); [Pilot Conformance Checklist](#pilot-conformance-checklist) |
| `INV-13` | An explicitly named path MUST be verified as a path before its existence, contents, or configuration status is reported. | [Explicit Path Verification](#explicit-path-verification) |
| `INV-14` | A current explicit user decision or constraint MUST be treated as authoritative, MUST override a historical worker conclusion, and MUST NOT be reopened as an unresolved decision. | [Authoritative Run Inputs](#authoritative-run-inputs) |
| `INV-15` | Every material detail supplied by the user MUST be preserved, classified, and either used by the workflow or explicitly recorded as unavailable, conflicting, or out of scope. | [Context Preservation and Classification](#context-preservation-and-classification) |
| `INV-16` | A worker wait timeout MUST NOT be treated as worker failure or authorize closing an active worker. | [Worker Wait and Termination Semantics](#worker-wait-and-termination-semantics) |
| `INV-17` | A portable implementation handoff MUST be self-contained, approval-gated, and based on repository identity and revision rather than source-environment paths. | [Portable Implementation Handoff Contract](portable_implementation_handoff.md) |
| `INV-18` | Material delivery changes MUST pass a strict Code Review covering relevant behavior paths, boundaries, scope, and coverage before validation is accepted. | [Delivery Code Review Loop](#delivery-code-review-loop) |
| `INV-19` | A portable implementation handoff MUST be created only for a cross-session or cross-environment transfer, or an explicit user request. | [Portable Implementation Handoff Contract](portable_implementation_handoff.md) |
| `INV-20` | Diagnosis and fix-design MUST pass the gate before clarification. | [Gate](#evidence-to-hypothesis-gate) |
| `INV-21` | Clarification MUST report executed checks. | [Gate](#evidence-to-hypothesis-gate) |
| `INV-22` | Local reproduction informs the current-code fix. | [Parity](#production-parity-prioritization) |
| `INV-23` | Planning MUST distinguish implementation-plan work from a true planning blocker. | [Planning Readiness and Implementation Work](#planning-readiness-and-implementation-work) |
| `INV-26` | Record why the playbook matches primary evidence and goal. | [Playbook Selection](#playbook-selection) |
| `INV-24` | Barrier before edits. | [Barrier](#delivery-activation-and-completion-barrier) |
| `INV-25` | Delivery gates and closure required. | [Barrier](#delivery-activation-and-completion-barrier) |
| `INV-27` | Initialization MUST load only the selected playbook and core contracts; other framework documents are loaded only when needed. | [Document Classification](#document-classification) |
| `INV-28` | Assigned worker inputs MUST be reconciled with `inputs_consumed` before accepting the result. | [Input Delivery and Consumption Gate](#input-delivery-and-consumption-gate) |
| `INV-29` | Ready independent workers MUST run in parallel when runtime capacity exists; duplicate investigation requires a recorded discrepancy. | [Parallelism Semantics](#parallelism-semantics) |
| `INV-30` | A managed worktree of the declared repository MUST be the source checkout, while durable artifacts remain under the declared repository path. | [Durable Artifact Root](#durable-artifact-root) |
| `INV-31` | After delegation, the owning technical worker MUST perform the assigned investigation; the Coordinator may repeat it only for a recorded discrepancy. | [Stage Completion and Fan-In](#stage-completion-and-fan-in) |
| `INV-32` | Provider-configured worker model and effort MUST be bound explicitly when the runtime otherwise inherits Coordinator settings. | [Profile Execution Semantics](#profile-execution-semantics) |
| `INV-33` | A final handoff MUST reconcile durable artifact state with fan-in, runtime closure, counts, timing, and engineering outcome before release. | [Final Handoff Reconciliation](#final-handoff-reconciliation) |
| `INV-34` | A remediation run sharing an execution repository with another active run MUST use an isolated managed worktree and run artifact root. | [Concurrent Run Isolation](#concurrent-run-isolation) |
| `INV-35` | Every worker activation MUST include a compact value/source/authority manifest for its assigned Input IDs. | [Input Delivery and Consumption Gate](#input-delivery-and-consumption-gate) |
| `INV-36` | A terminal work record MUST retain the required finalization fields, and the final answer MUST reproduce their canonical values without relabeling them. | [Final Handoff Reconciliation](#final-handoff-reconciliation) |
| `INV-37` | A terminal work record MUST pass the packaged framework validator before the handoff is released. | [Final Handoff Reconciliation](#final-handoff-reconciliation) |
| `INV-38` | A new run MUST start from fresh current-run artifacts; only an explicit continuation may reuse the current record. Evaluation telemetry is required only for declared evaluation runs. | [Run Identity and Continuation](#run-identity-and-continuation) |
| `INV-39` | Worker model and effort MUST come from the prepared role-binding manifest and match the activation record. | [Profile Execution Semantics](#profile-execution-semantics) |
| `INV-40` | Delegated workers MUST start in fresh context and MUST NOT repeat Coordinator initialization. | [Worker Contract](#worker-contract) |

---

# Human Control Model

The engineer owns scope, decisions, approvals, and interpretation of results. An approval is explicit only when its
type, owner, scope, and recorded decision or plan are clear. One approval may cover more than one type only when that is
recorded explicitly.

| Approval type | Controls | Required for current playbooks |
| --- | --- | --- |
| `scope` | Expanding the declared work item, repositories, operational target, or non-goal. | Conditional: every playbook when the proposed work exceeds its declared scope. |
| `design` | Selecting a material solution, architecture, security posture, or rollout alternative. | Conditional: every playbook when a material decision remains after investigation. It may be combined with implementation approval. |
| `implementation` | Source, configuration, or other remediation changes in the approved plan. | Required: every playbook before `lifecycle: remediation`. |
| `release` | Deployment, cutover, production configuration, or other external operational write. | Conditional: every playbook when its plan includes such an action; implementation approval alone is insufficient. |

```text
User -> scope approval (when needed) -> planning -> design approval (when needed)
     -> implementation plan -> implementation approval -> remediation
     -> independent review -> validation -> release approval (when needed) -> handoff
```

Planning is read-only. An approved design is not implementation approval, and implementation approval is not release
approval.

## Authoritative Run Inputs

Run prompts may contain both authoritative user inputs and unverified investigation hints. They are different kinds of
input:

| Input | Required behavior |
| --- | --- |
| Confirmed user decision or constraint | Treat it as the current decision or constraint. Do not ask the user to confirm it again or replace it with an alternative. |
| Investigation hint, hypothesis, or topology guess | Test it against source, runtime, and work-item evidence. It may be corrected or rejected. |

Workers may explain the technical consequences of an authoritative input and may report direct evidence that makes it
inconsistent with the observed system. They must not silently override it or convert it into a clarification question.
If the user must deliberately change the decision, present the conflict and ask for a new decision explicitly.

A statement such as “FanMgmt is the source of truth for comparison scenarios” is an authoritative comparison rule when
it appears in the confirmed-decisions section or run constraints. It means the workflow must treat FanMgmt's result as
the expected baseline and investigate why the rules engine differs; it must not ask whether FanMgmt rows should instead
be merged, discarded, or treated as duplicates unless the user explicitly requests that decision.

## Context Preservation and Classification

All user-supplied context is workflow input. The Coordinator and prompt-preparation step must not discard material
details because they do not fit the first obvious field or because they are not yet verified.

Classify each material detail as one or more of:

- an authoritative decision or constraint;
- an observed report or requested outcome;
- an unverified hypothesis, hint, or topology assumption;
- a supporting artifact, reference, or data source;
- an ambiguity or conflict requiring reconciliation; or
- unavailable or out of scope.

Map the detail to a canonical field when one exists. Otherwise preserve it in the run's additional context and work
record's Input Register with its source and classification. Use `Unknown` only when the information is genuinely
unavailable; do not use it to erase information the user supplied. If inputs conflict, preserve both statements,
identify the conflict, and resolve it through evidence or an explicit user decision. Never silently drop, rewrite, or
replace user context.

The prompt-preparation request may contain context before or after its formal fields. The preparation step must read all
of it and fill the canonical run template. The user must not be required to copy the same information into a second
section manually.

Historical artifacts, including prior plans, work records, and worker conclusions, are supporting evidence by default.
A current explicit user decision or constraint overrides a historical worker conclusion. A statement in a historical
artifact is authoritative only when current user input or an explicitly identified approved decision adopts it. A
worker-created hypothesis may recommend a seam or action, but MUST NOT become a mandatory gate, approval, or user
requirement without supporting evidence and a recorded decision.

## Input Delivery and Consumption Gate

Initialization MUST assign a stable Input ID to every material Input Register entry. Before activating a worker, the
Coordinator MUST record the Input IDs relevant to that worker in its `inputs` and Worker Execution Ledger entry. This
mapping is internal bookkeeping and does not require user approval.

When recovering an older work record without Input IDs, assign IDs before activating new workers. Preserve existing IDs
and never renumber them after a worker has referenced them.

Every result envelope MUST reference the Input IDs actually used in `inputs_consumed`. Before accepting a terminal
result, the Coordinator MUST reconcile assigned and consumed inputs. An assigned authoritative decision or constraint
that is neither consumed nor explicitly recorded as unavailable, conflicting, or out of scope makes the result
incomplete. Return the worker once with the missing Input IDs; never ask the user to repeat the underlying information.
If the worker cannot consume them, preserve the partial result and record the concrete runtime or access limitation.

Supporting inputs may be unused only when the worker records why they were irrelevant to its declared responsibility.
The gate checks information flow; it does not require every worker to consume every run input.

The Coordinator MUST also reconcile the worker's activity with its assigned context. Unassigned memory or historical
material that appears in an artifact, citation, claim, hypothesis, decision, or result envelope fails
`context_conformance`; that result MUST NOT enter fan-in. A provider-required memory pass does not fail conformance when
its results remain quarantined and every material conclusion is independently supported by assigned current-run
evidence. Return a contaminated worker once with the same typed inputs and require removal or current-run
reverification. If clean isolation cannot be enforced, preserve the partial result as contaminated evidence, record the
control failure, and stop at an incomplete outcome. Worker self-attestation alone does not pass this gate.

Every activation packet MUST include a compact input manifest for each assigned Input ID: the short value or fact, its
source, its authority classification, and the expected use or disposition. Assigning an ID without passing its value is
not input delivery. A worker may record an assigned input as unavailable or out of scope only when the packet includes
the input and the worker records the concrete reason it could not use it.

When an input names a relative framework artifact, the activation packet MUST preserve that user-supplied reference and
also include its verified canonical resolved path. A worker must not report the relative reference unavailable when the
resolved artifact was delivered.

## Evidence-to-Hypothesis Gate

A diagnosis or fix-design worker MUST pass this gate before returning
`needs_input`, `blocked`, or a result that would make the parent workflow enter
`awaiting_input` with reason `clarification_required`.

1. Consume every available user-supplied fact, decision, hint, and supporting
   artifact. List the paths or facts actually used in `inputs_consumed`. If an
   input cannot be read, record the access failure and its owner.
2. Perform bounded repository, contract, test, runtime, or artifact discovery
   when that evidence can reduce the uncertainty. Do not request evidence that
   the worker can obtain or evaluate locally.
3. Record confirmed facts with evidence references and confidence.
4. Record the strongest current hypothesis, its supporting evidence, confidence,
   and remaining uncertainty. If no defensible hypothesis is possible, explain
   why the available evidence cannot support one.
5. Execute the smallest safe falsification check or feedback loop that can
   confirm or reject the hypothesis. Record the command, function, fixture,
   artifact comparison, or other concrete check and its result in
   `checks_performed`. A proposed check is not a performed check. If any safe
   local or repository check is available, run it before requesting external
   evidence.
6. Record feasible options and a recommendation when a technical or design
   choice remains. Ask the user only for a business, scope, ownership, or
   incompatible-alternatives decision that bounded discovery cannot resolve.
7. State the next action in plain language, including who acts, where the action
   occurs, and what result completes it.

One supported hypothesis is sufficient for a simple issue. Record ranked
alternatives when the evidence supports more than one credible explanation.

During planning, run a unit or integration test only when an existing focused command can confirm or reject a leading
hypothesis, identify the owning boundary, or change plan readiness. Before running it, record the hypothesis, the
expected discriminating outcomes, how each outcome changes the disposition, and a bounded executable-availability
check. If the command only confirms behavior already established by source or event evidence, or its required runner is
known to be unavailable, defer it to the implementation plan. Do not repair the test environment, install tools, or run
a broader suite for triage. Put reproduction, regression, focused-suite, and broader-suite checks in the implementation
plan instead. A source or artifact comparison may satisfy the planning feedback loop.

The Coordinator MUST reject an incomplete clarification result. A result is
incomplete when it only asks for more data, says that the root cause is unknown,
repeats `Unknown` without explaining why, or gives an internal instruction
without a hypothesis, an executed check, or a concrete next action. It is also
incomplete when `checks_remaining` contains a safe local check that the worker
could have run. The Coordinator must request continuation from the worker when
possible. If the worker cannot continue, preserve its partial result and
report the runtime or access limitation; do not present the incomplete result
as a successful diagnosis or a useful clarification brief.

---

# Pilot Tool IDs

These provider-neutral tool IDs cover the current pilot workflows. Providers map them to concrete capabilities.

| Tool ID              | Meaning                                                                 |
| -------------------- | ----------------------------------------------------------------------- |
| `work_item_read`     | Read normalized work-item context.                                      |
| `work_record_read`   | Read the durable work record.                                           |
| `work_record_write`  | Append or update the durable work record.                               |
| `repository_read`    | Read repository files and metadata.                                     |
| `repository_search`  | Search repository content and symbols.                                  |
| `history_read`       | Inspect repository history and change context.                          |
| `dependency_inspect` | Inspect manifests, lockfiles, references, and dependency relationships. |
| `security_scan`      | Run or query a configured security scanner and preserve its result.     |
| `artifact_write`     | Write a durable analysis, design, decision, or validation artifact.     |
| `repository_write`   | Make an approved repository change.                                     |
| `build_run`          | Run the destination or source build.                                    |
| `test_run`           | Run tests or validation commands.                                       |
| `diff_review`        | Inspect and assess a change set.                                        |
| `runtime_observe`    | Inspect runtime, deployment, logs, metrics, traces, or health signals.  |

The tool list is an allowlist. A worker may not use an unlisted tool merely because the provider exposes it.

---

# Work Item Contract

Every workflow begins with a normalized work item. The source may be Jira, another work tracker, a document, or manual
input.

| Field                 | Required    | Description                                                              |
| --------------------- | ----------- | ------------------------------------------------------------------------ |
| `id`                  | Yes         | Stable identifier within the source system.                              |
| `source_system`       | Yes         | Jira, GitHub Issues, Linear, Markdown, or another source.                |
| `type`                | Yes         | Story, bug, task, incident, upgrade, vulnerability, or other.            |
| `title`               | Yes         | Short statement of the requested outcome.                                |
| `description`         | Yes         | Available problem or request context.                                    |
| `acceptance_criteria` | Recommended | Conditions supplied by the requester.                                    |
| `priority`            | Recommended | Source priority or urgency.                                              |
| `status`              | Recommended | Current source-system status.                                            |
| `links`               | Optional    | Related work items, pull requests, documents, dashboards, and incidents. |
| `repositories`        | Optional    | Source, destination, or affected repositories.                           |
| `constraints`         | Optional    | Runtime, ownership, compliance, release, or timing constraints.          |

Missing fields become explicit unknowns. They are never silently invented.

## Playbook Selection

Before activating a worker graph, the Coordinator MUST record the primary evidence, primary goal, selected playbook,
and closest alternative considered. The selection must explain why the chosen playbook fits better than the alternative.
This is a classification record, not another user input or approval gate.

---

# Workflow Run Contract

Each run records:

| Field          | Description                                                                          |
| -------------- | ------------------------------------------------------------------------------------ |
| `run_id`       | Unique identifier for this execution.                                                |
| `evaluation_run_id` | Unique experiment identity for comparing this evaluated run.                 |
| `work_item_id` | Identifier of the normalized work item.                                              |
| `playbook`     | Canonical playbook identifier.                                                       |
| `playbook_version` | Version from the selected playbook's front matter.                              |
| `framework_commit` | Full framework Git commit and clean or dirty status.                             |
| `plugin_package` | Installed plugin name/version, or `Not applicable` for manual runs.              |
| `provider_runtime_view` | Optional execution-repository `.codex/agents/` path, or `Not provided`.      |
| `provider_configuration` | Resolved provider-definition source and status; must not be inherited or guessed. |
| `prompt_template_revision` | Canonical prompt template path, version, and conformance result.          |
| `role_policy_baseline` | Provider role-policy baseline ID or `Not applicable`.                         |
| `provider`     | Execution provider and provider/model configuration reference.                       |
| `profile`      | Requested execution profile selected for this run.                                  |
| `lifecycle`    | Maximum run scope, such as `planning` or `remediation`.                              |
| `activated_profile` | Profile whose worker graph actually started; `None` if no graph started.          |
| `executed_profile` | Profile whose required workers and fan-in completed; `None` if no profile completed. |
| `profile_status` | `requested`, `in_progress`, `executed`, `not_executed`, or `blocked`; `not_executed` means no graph started. |
| `mode`         | Discovery, investigation, delivery, stabilization, review, or another declared mode. |
| `effort`       | Quick, standard, or deep.                                                            |
| `state`        | Current workflow lifecycle state.                                                    |
| `engineering_state` | What has been established about the work item, independently of workflow outcome. |
| `workflow_outcome` | `completed`, `incomplete`, or `blocked`; whether the selected graph actually finished. |
| `engineering_outcome` | `solved`, `partially_solved`, `plan_only`, `blocked`, or `incorrect`. |
| `workers`      | Selected workers and their dependencies.                                             |
| `gates`        | Required conditions and their status.                                                |
| `artifacts`    | Durable outputs produced during the run.                                             |
| `next_action`  | The smallest safe next action.                                                       |
| `owner`        | Person or team responsible for the current state.                                    |

---

# Worker Contract

Each worker must have a stable identifier and an explicit execution profile.

A delegated worker starts in fresh provider context after Coordinator initialization. Its activation packet begins
with `Coordinator initialization: complete`, and it MUST NOT run the launcher, package preflight, or run preparation.

| Field              | Required           | Description                                                                                                          |
| ------------------ | ------------------ | -------------------------------------------------------------------------------------------------------------------- |
| `id`               | Yes                | Unique worker identifier within the workflow run.                                                                    |
| `role`             | Yes                | Canonical role identifier.                                                                                           |
| `mode`             | Yes                | Mode in which this worker operates.                                                                                  |
| `effort`           | Yes                | Provider-neutral worker depth: quick, standard, or deep. It does not select the provider model or reasoning setting. |
| `skills`           | Yes                | Canonical skill identifiers selected for this worker.                                                                |
| `tools`            | Yes                | Allowed concrete tool identifiers. An empty list means no tools are available.                                       |
| `model_profile` | Yes for AI workers | Internal capacity class; not a normal run input. |
| `inputs`           | Yes                | Input Register IDs and artifacts assigned before activation.                                                         |
| `outputs`          | Yes                | Artifacts or decisions the worker must produce.                                                                      |
| `depends_on`       | Yes                | Worker or gate dependencies. Use an empty list when none exist.                                                      |
| `parallelism`      | Yes                | `sequential`, `parallel`, `conditional`, or `continuous`.                                                            |
| `approval`         | Yes                | Whether human approval is required before the worker proceeds or publishes side effects.                             |
| `exit_criteria`    | Yes                | Evidence-based condition for completion.                                                                             |
| `failure_behavior` | Yes                | How errors, uncertainty, missing inputs, and blocked work are recorded.                                              |
| `usage`            | Recommended        | Provider-reported execution usage, such as input/output tokens, duration, or credits. Unknown values remain unknown. |

Provider-reported usage is observational metadata, not a worker input. A provider adapter may populate it after
execution. Workers must not estimate credits when the provider does not expose them.

## Worker Result Envelope

Every worker returns one compact result envelope in addition to its durable artifacts. The envelope is the unit consumed
by the Orchestrator at fan-in.

| Field              | Required    | Description                                                     |
| ------------------ | ----------- | --------------------------------------------------------------- |
| `worker_id`        | Yes         | Worker that produced the result.                                |
| `worker_handle`    | Yes         | Exact provider-returned handle for this activation.             |
| `outcome`          | Yes         | One of the shared worker outcomes.                              |
| `summary`          | Yes         | The worker's unique contribution in a few sentences.            |
| `inputs_consumed`  | Yes         | Assigned Input IDs and artifacts used, with disposition for assigned inputs not used. |
| `outputs_produced` | Yes         | Artifacts, decisions, or validation results produced.           |
| `checks_performed` | Conditional | Checks actually run and results for diagnosis or fix design.    |
| `checks_remaining` | Conditional | Unavailable or external checks and why they remain.             |
| `evidence_refs`    | Recommended | Evidence IDs or sources supporting or challenging the result.   |
| `claim_refs`       | Recommended | Claim IDs produced or materially used by the result.            |
| `confidence`       | Yes         | `high`, `medium`, `low`, or `unknown`; confidence in the result's material claims. |
| `uncertainties`    | Yes         | Remaining unknowns, conflicts, or confidence limits.            |
| `next_consumer`    | Recommended | Worker, gate, or human decision that should consume the result. |
| `model_effort`     | Recommended | Actual model and reasoning effort, when exposed.                |
| `configuration_conformance` | Yes | Configured and provider-observed model/effort, or the exact unavailable/mismatch reason. |
| `context_conformance` | Yes | `pass` only when the worker used assigned current-run context and no prohibited historical source. |
| `plan_readiness`   | Conditional | Fix-design disposition: `ready_for_implementation` or `awaiting_input`. |
| `implementation_plan_action` | Conditional | Fix-design instruction to `create` or `omit` the implementation plan. |
| `supported_remediation_boundary` | Conditional | Fix-design boundary supported by current-run evidence. |
| `supported_intended_change` | Conditional | Fix-design change supported by current-run evidence. |
| `blocking_unknowns` | Conditional | Structured decisions or indispensable evidence that can select a materially different fix. |
| `timing`           | Yes         | Coordinator-observed activation, start, terminal, elapsed, and wait timestamps; provider timing may supplement them. |
| `usage`            | Recommended | Provider-reported tokens, duration, credits, or `Unknown`.      |
| `errors_blockers`  | Yes         | Errors, blockers, or `None`.                                    |

The summary must describe the worker's unique contribution, not repeat the entire input artifact. A downstream worker
must consume the envelope and referenced artifacts rather than independently repeating the same investigation unless it
is checking a stated discrepancy. The envelope's `outcome` is a worker outcome; it does not replace the run-level
`workflow_outcome` or `engineering_outcome`.

The Coordinator MUST validate every terminal envelope before fan-in. For Fix Design,
`ready_for_implementation` pairs only with `create`, and `awaiting_input` pairs only with `omit`. Return an invalid
enum or pair to the same worker; never normalize, reinterpret, or silently repair it in Coordinator state.
`ready_for_implementation` requires a supported remediation boundary, a supported intended change, and no blocking
unknowns. `awaiting_input` requires at least one discriminating check and a structured blocker naming its decision type,
question, unavailable reason, evidence, and at least two materially different fix implications. It MUST NOT defer an
already supported boundary and intended change unless the evidence shows that each blocker invalidates that change.

Coordinator-observed activation and terminal timestamps are always available and MUST be recorded. When the provider
does not expose a distinct start time or queue wait, use activation as start and record provider queue wait as
`Unavailable`; elapsed wall time remains terminal minus activation and MUST NOT be `Unknown`.

`confidence` must be explainable through the referenced evidence and recorded uncertainties. A `complete` outcome does
not imply high confidence. Use `unknown` when the worker cannot make a defensible confidence assessment. Material
conclusions should use the IDs from the [`Claims, Evidence, Decisions, and Actions Contract`](claims.md).

---

## Execution Profiles and Lifecycle

Execution profile and lifecycle are independent dimensions:

| Dimension         | Selects                                                 | Example values            |
| ----------------- | ------------------------------------------------------- | ------------------------- |
| Execution profile | Worker graph, investigation depth, and validation scope | `standard`, `deep`        |
| Lifecycle         | How far the run may proceed                             | `planning`, `remediation` |

The profile answers “how much investigation is appropriate?” The lifecycle answers “how far may this run proceed?” A
`deep` planning run investigates more thoroughly but still stops before implementation. A standard remediation run may
implement after the required approval gate.

Every profile must preserve the shared safety, evidence, work-record, approval, and fan-in requirements. Provider
adapters apply the provider role policy without changing lifecycle gates or the role-quality policy.

## Profile Execution Semantics

For a versioned evaluation, initialization MUST compare the populated run prompt with the selected canonical template.
Record `prompt_conformance`, the template revision, and any missing or altered required fields. A missing framework
revision, execution repository, resolved provider configuration, profile, lifecycle, or authoritative-input section
stops the run with `run_prompt_nonconformant`; an absent execution-repository `.codex/agents/` runtime view alone does
not. Claiming the expected revision does not make a structurally incomplete prompt conformant.

The requested profile is an execution requirement, not descriptive metadata. At initialization, the Orchestrator records
the requested profile and its required workers. Before completing the run, it records the executed profile and profile
status.

The Orchestrator must not silently downgrade a profile to a smaller worker graph. If required delegation is unavailable,
the run is `not_executed` or `blocked`; it is not a successful execution of the requested profile.

Before each AI-worker activation, resolve the provider agent definition and bind its configured model and reasoning
effort. The execution-repository `.codex/agents/` directory is an optional runtime view; when it is absent, use the
bundled framework/plugin provider definition or the selected work-graph binding and record that source and status. When
the spawn API inherits the Coordinator by default, pass those exact values explicitly; this is configuration binding,
not adaptive escalation. If the runtime cannot apply or verify them, record the mismatch and do not activate the worker.
Unrecorded or accepted model/effort substitution is prohibited. A run whose required worker cannot be bound stops with
`provider_configuration_unavailable`; it does not continue on inherited defaults.

`requested` means the graph has not started, `in_progress` means required workers are active or awaiting fan-in, and
`executed` means all required workers returned terminal envelopes and fan-in passed. `not_executed` means the graph
could not start. `blocked` means it started but cannot reach its next gate. Escalation is a new recorded profile
selection, never a profile status.

Set `profile_status: executed` only after every required worker returns a terminal envelope and required fan-in passes.
If a required worker was activated but does not return a terminal envelope, set `profile_status: blocked` and record the
worker-specific runtime reason. A Coordinator cannot replace a required independent worker. A different profile is a
new, explicitly requested run; it does not complete the original profile.

Record `activated_profile` when the selected worker graph starts. Record `executed_profile` only for a profile whose
required workers returned terminal envelopes and whose fan-in passed; use `None` when no profile completed. A run with
an activated graph but incomplete fan-in is `profile_status: blocked`, not `not_executed`.

## Clarification Framing

An incomplete requirement or unresolved decision is not automatically a blocker. Confirmed user decisions are not
clarification candidates. Before requesting clarification about anything else, the Orchestrator must use the available
planning workers for bounded discovery of the current implementation, contracts, tests, repository history, and related
work when that evidence can reduce the uncertainty.

For diagnosis and fix design, bounded discovery includes executing the
smallest safe local or repository check that can reduce the uncertainty. A
missing production trace or revision mapping does not justify clarification if
the current checkout and supplied inputs can first be replayed locally.

If a decision still prevents implementation readiness, the Solution Architect must record a Clarification Brief in the
work record, with alternatives summarized in `Alternatives Considered`: the decision needed, evidence researched, one or
more feasible options, tradeoffs and validation impact, recommendation, and the smallest question and owner needed to
proceed.

## Planning Readiness and Implementation Work

Planning creates an approval-gated implementation plan; it does not complete implementation, validation, deployment,
or stabilization work. A planning worker MUST classify each finding as either implementation-plan work, a risk or
validation limitation, or a true planning blocker.

Implementation-plan work includes moving or adapting dependencies, imports, configuration, infrastructure, queues,
callbacks, locks, tests, fixtures, deployment definitions, rollout, rollback, and environment setup. Existing test
failures, unavailable test tooling, missing local services, and incomplete destination behavior are plan inputs when
their impact and a safe execution sequence can be described. They MUST be recorded as ordered plan steps, validation
requirements, risks, or residual limitations; they MUST NOT by themselves prevent plan creation.

A true planning blocker exists only when a required source, destination, scope, safety constraint, or indispensable
evidence is unavailable or contradictory such that no safe, feasible plan can be written; when a user business, scope,
ownership, or incompatible-alternatives decision remains after bounded discovery; or when a required worker cannot
return a terminal result. A worker whose investigation is complete MUST return `complete` with recorded limitations,
not `blocked`, merely because implementation or validation work remains.

`ready_for_implementation` requires terminal planning fan-in and an implementation plan with:

- required claims established by source-backed evidence;
- critical assumptions supported, contradicted, or explicitly accepted as implementation risk;
- implementation scope and exclusions defined;
- acceptance criteria recovered or an approved equivalent recorded;
- a validation plan defined; and
- no blocking unknown that could select a materially different cause, boundary, or fix.

The plan must also provide a feasible sequence, risks, and explicit prerequisites. Readiness does not require source
changes, passing tests, available local tooling, provisioned infrastructure, or release approval. Implementation
approval remains the gate for performing those steps.

A prerequisite may verify an already supported change, but it MUST NOT be used to defer diagnosis or fix selection into
remediation. If missing evidence could select among materially different causes, owning repositories, source boundaries,
or fixes, the plan remains `draft` and the workflow returns a Clarification Brief. `ready_for_implementation` requires
an evidence-supported remediation boundary and intended change; a list of mutually conditional candidate files is not
a feasible implementation scope.

The Coordinator may reconcile envelopes and enforce gates, but MUST NOT change a technical worker's diagnosis, proposed
boundary, or plan-readiness disposition. Return a disputed result to the owning worker or an independent Reviewer.
The final Documenter MUST follow the owning fix-design worker's `implementation_plan_action`. When readiness is
`awaiting_input`, the action is `omit`; record a Clarification Brief and do not create a conditional implementation
plan. Only `ready_for_implementation` permits `create`.

## Production-Parity Prioritization

When a production symptom is reproduced locally with supplied production input
and a reachable current code path, treat that result as actionable diagnosis
for the current code. Exact deployed-revision mapping is a residual release
risk and rollout-verification step, not a prerequisite for the implementation
plan or a user-facing request to compare versions first, unless it changes the
target code, fix scope, or safety decision.

The next action should be to fix the current path, add the regression test,
run validation, and verify the deployed result. Record production-parity work
as a rollout or pre-release check. If the local path does not match the
reported path, or parity evidence would change the target boundary, preserve
that conflict and request the smallest required decision or evidence.

Use state `awaiting_input` with reason `clarification_required` for this decision gap. Use `blocked` only when an
unavailable environment, permission, or indispensable evidence prevents bounded discovery or meaningful option framing.
Proposed options are not authorization to implement and do not permit creating an implementation plan before the
planning gate passes.

## Stop Conditions

A stop condition stops the affected action or transition; it does not discard already collected evidence. The
Coordinator records the condition, affected claims or decisions, and smallest safe next action in the work record.

| Category | Conditions | Required behavior |
| --- | --- | --- |
| Stop immediately | Required authorization is missing; scope is unsafe or destructive; a security or privacy concern exists; or contradictory evidence invalidates a material claim or approved decision. | Do not perform the affected change or transition. Preserve evidence. Use `awaiting_input` for a needed approval or decision; otherwise use `blocked` until the risk or contradiction is resolved. |
| Continue investigation | Non-critical context, an implementation detail, or a dependency is unclear. | Continue bounded evidence collection, record the uncertainty, and do not present an unsupported material conclusion. |
| Ask the user | A business, scope, ownership, or incompatible-alternatives decision remains after bounded discovery. | Produce a Clarification Brief and enter `awaiting_input`; do not select or implement an alternative on the user's behalf. |

Contradictory evidence stops reliance on the affected claim or decision, not all investigation. The next action is to
reconcile the conflict or request the smallest necessary decision.

## Lifecycle Continuation and Re-entry

The selected lifecycle is immutable for one workflow run. A conversation may continue, but a planning run does not
become a remediation run merely because the user asks a follow-up question or says to continue.

To move from `planning` to `remediation`, the Orchestrator must create or explicitly record a new lifecycle run or
re-entry event that:

1. preserves the existing work record and approved implementation plan;
2. records explicit implementation approval;
3. selects `lifecycle: remediation` without silently changing the profile;
4. re-reads the playbook, work record, and implementation plan;
5. records `profile_status: requested` for the remediation run;
6. activates every required delivery worker before source changes, reusing completed planning artifacts rather than
   rerunning planning workers;
7. waits for required result envelopes and completes fan-in; and
8. reports the new run's requested lifecycle, activated workers, and fan-in status.

If any condition is missing, the workflow remains in planning or stops with state `awaiting_input` and reason
`approval_required`, or state `blocked` and reason `remediation_not_activated`. A generic implementation workflow must
not replace the selected playbook's remediation worker graph.

Before the first source change, the Orchestrator records the activated delivery workers, their dependencies, and the
required `implement → review → validate → handoff` path in the work record. The Coordinator does not act as the
Implementer, Reviewer, or Tester. If the required remediation graph cannot be activated, do not edit source; stop with
`profile_status: blocked` and reason `remediation_not_activated`.

Initialization and delivery preflight are Coordinator responsibilities and do not require a delegated worker unless the
selected playbook explicitly requires independent initialization analysis. Even then, the delegated worker starts after
Coordinator initialization and MUST NOT repeat package preflight or run preparation.

## Delivery Activation and Completion Barrier

Implementation approval is necessary but not sufficient to start remediation. Before any source, configuration,
dependency, or infrastructure change, the current remediation run MUST record a Delivery Activation Barrier containing:

1. the remediation re-entry event, unchanged execution profile, `lifecycle: remediation`, approved plan, and approval
   type, owner, scope, and reference;
2. the required delivery graph for the selected playbook: `implement`, `review`, `validate`, and `handoff`, with each
   worker's actual ID, role, dependency, activation state, and result state;
3. an active delegated `implement` worker authorized to edit the approved scope; and
4. the current Coordinator's explicit non-authority to edit source or substitute for the Implementer, Reviewer, or
   Tester.

The graph may execute sequentially. A downstream worker may be recorded as `awaiting_dependency`, but it must not be
omitted from the current run's worker execution record. If the required graph or active Implementer cannot be created,
stop before source changes with `profile_status: blocked` and reason `remediation_not_activated`.

The Coordinator may inspect files to coordinate work and maintain durable artifacts, but it MUST NOT implement, review,
or validate source changes. A source change made before the barrier is a workflow violation and invalidates any claim
that the remediation run executed the selected playbook.

Required implementation tools and versions MUST be recorded in the approved plan or resolved during preflight. A
missing tool does not authorize downloading or installing an unpinned replacement. An isolated bootstrap is allowed only
when the approved plan or current explicit user decision authorizes the exact tool, version, source, and isolation
method. The resolved executable path and version become typed inputs inherited by every downstream worker.

The remediation run remains `in_progress` until the Implementer returns a terminal result. It cannot enter `handoff` or
`completed` until the Reviewer returns `accepted`, the Tester returns terminal
validation results, the Documenter records the final handoff, required fan-in
passes, and runtime closure is recorded. A partial implementation is not
completion.

## Implementation Plan Conformance Check

Before the first source change, the delegated Implementer MUST record a plan-conformance manifest in the work record.
For every proposed changed file, the manifest MUST identify the approved plan step, the existing implementation or
reuse target, the intended change, and the validation that will prove it. Every new table, model, fixture, runtime
abstraction, or dependency MUST be mapped to an explicit plan step. A change that is not mapped, contradicts an
explicit plan boundary, or replaces the approved design to avoid repairing the named implementation MUST stop before
editing with `replanning_required`.

The Reviewer MUST compare the current diff with this manifest and the approved plan before reviewing behavior. A
missing manifest, unmapped change, forbidden replacement, hard-coded runtime fixture, or unresolved dependency that the
plan requires to be removed is `changes_required` or `replanning_required`, not an accepted implementation.

## Approved Remediation Continuity

One explicit remediation approval authorizes every in-scope step in the approved implementation plan: implementation,
review, validation, stabilization, and handoff. It does not require approval after each planned implementation slice. A
partial slice leaves the run `in_progress`; the Orchestrator continues the ordered worker graph until the plan is
complete.

Pause for a new user decision only when new evidence invalidates the approved scope or design, a required step exceeds
that scope, an unapproved external or irreversible action is required, or a genuine environment, permission, or
validation blocker prevents progress. Ordinary remaining plan steps, worker handoffs, and focused per-slice checks are
not approval gates.

## Continuous Worker Progress

While a remediation delivery graph is active, an `in_progress`, `running`, or `awaiting_dependency` status is an
intermediate status, not a handoff and not a request for user action. The Coordinator MUST continue polling active
workers. After an Implementer returns a terminal result, the Coordinator MUST immediately advance the same run to
Reviewer; after the Reviewer returns `accepted`, it MUST advance to Tester; after Tester validation, it MUST advance to
Documenter, fan-in, and runtime closure. It MUST NOT end the run with a final-looking status that requires the user to
say “continue” or “what next?” for an ordinary worker transition.

If the provider yields control while a worker remains active, record `in_progress`, identify the active worker and the
next automatic transition in plain language, and state `No action is required from the user.` Resume polling or
continuation when the runtime permits. A user follow-up may resume an interrupted run, but it MUST NOT be required for
normal dependency advancement.

## Delivery Code Review Loop

Code Review is a gate, not a final report. The Reviewer records one disposition: `accepted`, `changes_required`,
`replanning_required`, or `blocked`.

For every material source, configuration, or dependency change, Code Review MUST cover the approved change's:

* intended happy paths and existing behavior that must remain unchanged;
* alternate, error, empty, missing, null, boundary, and other relevant edge paths;
* affected callers, producers, consumers, contracts, persistence, and compatibility boundaries;
* regression coverage, including whether the tests would fail for the original defect where practical; and
* scope, unintended files, security or operational impact, rollback, and remaining validation gaps.

The Reviewer MUST record which dimensions were checked and any paths that could not be verified. A review that only
confirms the happy path is incomplete and MUST NOT be reported as an accepted strict review.

`changes_required` findings within approved scope return to the Implementer in the same remediation run. The Implementer
fixes them, records the result, and the Reviewer rechecks the affected diff before validation begins. No new user
approval is required. `replanning_required` is reserved for evidence that invalidates the approved scope or design;
`blocked` is reserved for a genuine external, environment, permission, or validation blocker. Numeric priority is
evidence of urgency, not a substitute for this disposition.

## Interrupted Profile Recovery

An incomplete required-worker graph is not a completed diagnosis or plan. The canonical run prompt must support an
`Interrupted profile recovery` continuation that:

1. preserves the same work record, profile, lifecycle, and completed artifacts;
2. records completed workers, missing workers, and the recovery reason;
3. reuses completed result envelopes unless a specific discrepancy requires a rerun;
4. activates every incomplete required worker for the selected profile;
5. waits for all required result envelopes and completes fan-in; and
6. reports the recovered requested/executed profile, worker activation, fan-in, and next gate.

For an individual required worker that is confirmed stopped or failed without a terminal envelope, recovery closes its
original handle only when the provider confirms that it is no longer running, then makes one fresh replacement attempt.
It reuses completed artifacts and does not repeat successful work. A wait timeout, empty wait result, or `running`
status is not confirmation that the worker stopped; it keeps the worker active and must not trigger recovery or a
duplicate worker. If the replacement also has a confirmed runtime failure, stop with `profile_status: blocked` and
reason `<normalized-worker-id>_runtime_unavailable`. Do not create an implementation plan, invent a Coordinator-only
review, or present a lower profile as completion of the requested profile.

The Coordinator MUST store the provider-returned worker handle and pass that stored value to wait, follow-up, and close
operations; it MUST NOT manually reproduce or edit the handle. A `not_found` result requires reconciliation against the
original spawn result, durable artifacts, and provider status before replacement. Record every spawn
attempt, handle discrepancy, replacement, and duplicated result.

The approval gate applies to delivery workers. Missing implementation approval must not prevent remaining planning
workers from completing diagnosis and fix design. If recovery delegation is unavailable, remain `blocked` or
`not_executed`; do not substitute a generic workflow or claim success.

## Run Identity and Continuation

Every run records its provider run ID when available. Evaluation identity, role-policy baseline, detailed
provider-action history, and timing are required only when the request explicitly declares an evaluation or benchmark
run.

`Start` creates a new run. It MUST NOT patch or consume a prior terminal run as current evidence. Before replacing the
canonical artifact root, preserve the prior terminal artifacts under `.thoughts/<WORK-ITEM-ID>/runs/<RUN-ID>/`; then
initialize a fresh canonical record. `Continue` reuses the current durable record and adds only the new inputs and
activity. When the request does not say continue, treat it as start.

Normal runs record material worker outcomes and control failures, but do not reconstruct provider metrics. Evaluation
runs additionally maintain chronological continuation, activation, and timing ledgers using provider-observed values.

## Worker Wait and Termination Semantics

A wait timeout is a polling boundary, not a worker outcome. When a provider wait returns `timed_out: true`, an empty
status, or a worker status of `pending_init` or `running`, the Coordinator MUST record the worker as active or in
progress. The Coordinator MUST continue waiting with a provider-supported timeout, use a provider-supported graceful
finalization request, or leave the run open; it MUST NOT call `close_agent`, mark the worker failed, or start a
replacement from that result alone.

The Coordinator MAY close a worker only after collecting its terminal result or after the provider explicitly confirms a
terminal failure, interruption, shutdown, or that the worker is no longer running. If a close operation reports
`previous_status: running`, the Coordinator MUST record `coordinator_interrupted_after_wait_timeout` when applicable. It
MUST NOT describe that worker as provider-failed or runtime-unavailable.

If an overall wait budget is exhausted while a required worker remains active, keep fan-in open and report the run as
blocked or in progress with the active-worker status, owner, and exact recovery action. Do not force-close a live worker
to make the run appear closed. Result collection, termination, and provider capacity release remain separate facts.

## Explicit Path Verification

An explicitly named path is any path supplied by the user, run template, derived artifact rule, worker result, or
provider configuration. Before making a claim about it, the Coordinator MUST verify the path itself and record the
result in the work record.

The verification MUST distinguish at least:

* path exists and has the expected type;
* path is absent;
* path is inaccessible or permission denied;
* path exists but is empty;
* no entries matched a particular filter; and
* a symlink exists but its target is missing or inaccessible.

Directory inspection MUST include hidden entries and symlinks. Configuration discovery MUST inspect both regular files
and symlinks, then verify symlink targets. An empty result from a filtered search MUST NOT be interpreted as evidence
that the directory or configuration is absent. If the path cannot be verified, record `Unknown` or `blocked` with the
attempted check; do not infer absence.

The work record must preserve the path, expected type, observed status, check time, and command or other evidence used
for the conclusion. This applies to the execution repository, provider configuration, code repositories, durable
artifacts, and supporting evidence paths.

---

## Durable Artifact Root

The prompt's `Execution repository` is the repository where the workflow is started. It is the durable-artifact root for
that run:

```text
<execution-repository>/.thoughts/<WORK-ITEM-ID>/
```

The `work_record.md`, worker artifacts, and any implementation plan belong there. Additional repositories listed for
investigation are not artifact roots. The execution repository may itself contain code. A worker must not choose an
artifact root merely because a repository is suspected or appears first in the topology.

The prompt path identifies both the intended repository and its durable-artifact root. During initialization, resolve a
separate source checkout before repository inspection:

* if the runtime starts inside a Git worktree of the declared execution repository, use that active worktree as the
  source checkout and remap source/component paths beneath it;
* verify equivalence from Git identity, such as the shared common Git directory or matching canonical remote, rather
  than path text alone;
* record the declared durable-artifact root and resolved source-checkout path separately; and
* if the paths refer to different repositories or equivalence cannot be established, stop with `blocked` instead of
  changing directories to the declared path.

Branch and revision evidence, scope checks, and source commands MUST come from the resolved source checkout. A prompt's
absolute source/component path MUST NOT override an equivalent active worktree. Durable artifacts MUST remain under the
prompt's declared execution repository, never under an ephemeral managed-worktree path unless that exact worktree was
explicitly declared as the execution repository.

Before using any execution, primary, additional, source, or destination repository as evidence, record its declared and
resolved path, repository role, branch or detached state, full revision, clean status, canonical Git identity, and
release/production mapping when relevant. Also record whether the current user or run prompt selected that branch or
revision and set `evidence_eligibility` to `accepted`, `caveated`, or `rejected`.

An undeclared feature branch MUST NOT establish baseline, production, or current-main behavior. Use a user-declared
clean checkout or an explicit stable ref through a read-only Git operation; otherwise reject that repository state as
behavioral evidence and record the required checkout or revision. Preserve unrelated dirty work and never switch or
reset the user's checkout merely to pass this gate.

For a bounded dependency route, the execution repository is the in-scope repository that owns the affected dependency
artifact unless the user explicitly selects a separate record repository. Never infer the framework checkout as the
execution repository merely because it contains the selected playbook.

The execution repository must be explicit in the canonical run prompt. If it is missing or ambiguous, stop with
`blocked` and request the smallest missing path; do not infer it from the playbook location or code-repository list.

# Parallelism Semantics

| Value         | Meaning                                                                                                         |
| ------------- | --------------------------------------------------------------------------------------------------------------- |
| `sequential`  | The worker starts only after declared dependencies complete.                                                    |
| `parallel`    | The worker may run alongside independent workers after its dependencies complete.                               |
| `conditional` | The worker may run in parallel only when the playbook or Orchestrator confirms that its inputs are independent. |
| `continuous`  | One worker identity starts after initialization, consumes incremental artifacts, and returns the final result.  |

Dependencies describe readiness to start. Inputs describe artifacts consumed. A worker may consume outputs from another
worker without being blocked from starting when the playbook explicitly supports incremental updates.

Workers that share a completed dependency and do not depend on each other MUST start in parallel when runtime capacity
exists. If they run sequentially, record the dependency, capacity, or provider limitation and its wait time.
Deep does not authorize duplicated investigation: each worker owns a distinct question and artifact, consumes upstream
outputs, and repeats evidence or repository analysis only for a named discrepancy recorded in its result envelope.

A continuous worker MUST keep one worker identity and, when supported, one provider handle through finalization. Do not
spawn a second final worker for the same role. If the provider cannot resume or update an active worker, activate one
final worker after fan-in instead of reserving a continuous handle for the whole run.

## Concurrent Run Isolation

Different read-only planning runs may inspect the same clean, immutable source revision. They MUST still use distinct
run artifact roots and record the shared repository and revision in each run. A run that can write source,
lockfiles, tests, generated files, or external work-item state MUST NOT share a checkout with another active run; it
requires a separate managed worktree and a distinct durable artifact root. A second run for the same work item MUST stop
with `run_already_active` until the prior run's handles and artifact writers are released, or it must use an explicit
continuation or recovery identity. The Coordinator records the isolation decision before worker activation.

Before recording `None` for an active related run, the Coordinator MUST check available provider tasks and sibling
work-item artifact roots, then record the method and timestamp. When neither can be checked, record
`Unknown; detection unavailable`, not `None`. A stale artifact root is not proof of an active writer, and a read-only
related run need not stop when its revision and artifact root are distinct.

# Stage Completion and Fan-In

A stage that launches multiple workers has a fan-in barrier. The Orchestrator must wait for every required worker to
reach a terminal outcome before marking the stage or workflow complete.

The Orchestrator must preserve each worker's result, error, blocker, and usage metadata; summarize every worker result
in the durable work record; distinguish all worker outcomes; and keep the parent workflow `in_progress` while any
required worker is still active.

After activating a technical worker, the Coordinator MUST NOT perform that worker's repository, runtime, issue-system,
or evidence investigation. It may perform minimal initialization and verify the returned artifact, and may repeat a
technical check only when a named discrepancy is recorded and returned to the owning worker.

The final workflow handoff contains the shared outcome summary below. Detailed worker results remain in the work record;
do not reproduce the worker ledger in the user-facing answer.

## Human-Readable Handoff

Every playbook uses this final-answer order. Omit conditional sections that do not apply.

```text
Workflow result: <plain-language outcome>

- State: <canonical state>
- Workflow outcome: <completed | incomplete | blocked>
- Engineering outcome: <solved | partially_solved | plan_only | blocked | incorrect>
- Implementation plan: <created path, or omitted and why>

What we established:
- <major verified finding>

Best current explanations:  # unresolved diagnosis only; strongest plus at most two alternatives
- <confidence>: <hypothesis and one-line evidence>

Next action:
- Owner: <person or team able to act>
- Action: <specific evidence, decision, or implementation>
- Complete when: <observable completion condition>

Artifacts:
- <links>

Execution: <profile/lifecycle>; validation <result>; workers <complete/incomplete>;
runtime <released/not released>; source or external changes <none/summary>.
Provenance: plugin <package and version, or Not applicable>; framework revision <Git SHA> (<clean/dirty>);
playbook <name and independent document version>.
```

`Workflow outcome: completed` means required workers reached terminal results, fan-in passed, and runtime closure was
recorded. It does not prove the diagnosis, implementation, or release was correct. `Engineering outcome` reports the
value to the engineering work item: a plan can be produced while the task remains unsolved, and a completed workflow can
reveal a wrong direction.

When analytical fan-in and runtime closure complete but the run needs a decision or evidence, use state
`awaiting_input`, `Workflow outcome: completed`, and `Engineering outcome: partially_solved`. Reserve `plan_only` for a
run that produced a usable implementation plan but did not implement it. Use
`Engineering outcome: blocked` only when an environment, permission, runtime, or indispensable-evidence failure
prevented the selected workflow from completing. Do not add a second generic outcome field that contradicts these
values.

Do not expose internal runtime terms such as `fan-in` or terminal envelope without explanation. Do not present an
internal owner as if the user must repair the agent runtime. If the next step is a retry, give the exact request.

If an analytical worker returned hypotheses, the final summary MUST show the strongest one and up to two credible
alternatives. Use short sentences, confidence labels, and the evidence for each. Show a rejected hypothesis only when it
helps explain why the run did not choose an expected fix. Never reduce a useful hypothesis result to only “root cause
unknown.”

Normal runs MUST NOT include `Run metrics` or `Worker timing` in the final answer. An explicitly declared evaluation or
benchmark run may append those blocks from provider-observed data. Never reconstruct missing timing or usage.

The final Documenter owns the implementation plan, clarification brief, and structured `finalization_packet.json`,
populated from `templates/finalization_packet.json`.
The packaged `scripts/finalize_work_record.py` renderer is the only writer of the terminal `work_record.md`. It renders
the packet into canonical Markdown, runs the packaged validator, and atomically replaces the record only after
validation passes. If rendering or validation fails, the Coordinator MUST return the exact error to the same
Documenter for a corrected packet; neither agent may patch the terminal Markdown by hand.

Keep the final Documenter handle live until artifact content, plan action, outcomes, and required artifact disposition
pass the packaged finalizer in `--pre-release` mode. Before release, provide a pending closure probe in the same schema;
the pre-release check validates the packet and candidate record without replacing `work_record.md`. Send every packet
correction to that same handle and collect the revised result. Only after the pre-release check passes, release the
handle, then write one provider-observed `runtime_closure.json` receipt. The receipt contains only the exact closure
table rows from `templates/runtime_closure.json` and is not a second interpretation of the workflow outcome.

Once the final Documenter is activated, it is the sole writer for its assigned non-record artifacts and packet. The
Coordinator invokes the renderer but MUST NOT edit the packet or rendered record.

## Final Handoff Reconciliation

Before releasing the final Documenter, the Coordinator MUST compare the final artifact and final answer with the runtime
record. The following values must agree: workflow state, profile status, workflow outcome, engineering outcome, plan
action, worker outcomes, remaining active handles, artifact paths, and runtime closure. A released handoff MUST contain
no stale `pending`, `active`, `in_progress`, or
`closure pending` value for a completed barrier. Return any mismatch to the same Documenter, collect the revised
terminal result, and repeat the comparison before release. A final answer that
contradicts the durable record is a handoff conformance failure even when the worker graph itself completed.

Before the first final Documenter activation, the Coordinator MUST pass one finalized packet containing worker
outcomes, workflow and engineering outcomes, displayed hypotheses, artifact paths, next-action owner, action,
completion condition, plugin package/version, framework Git revision/status, and playbook name/version. The packet is
immutable once passed to the Documenter. The Documenter serializes these values as structured JSON; it does not select,
normalize, reinterpret, or reconstruct them. After the Documenter returns and is released, the Coordinator invokes
`scripts/finalize_work_record.py` with the packet, closure receipt, and record paths. An inconsistent packet is a
validation error returned to the Documenter, not authority to decide a different state or outcome.

The terminal work record MUST contain the canonical `# Final Handoff` block from this contract. With
`--emit-handoff`, the standalone validator checks its ordered labels, verifies that its state and outcomes equal the Run
Identity and runtime-closure tables, and emits that block after the validation receipt. The Coordinator copies the
emitted block verbatim as the user-facing answer.

The terminal work record MUST retain, at minimum: work-item and repository identity; canonical `state`,
`engineering_state`, `workflow_outcome`, and `engineering_outcome`; run-isolation decision and related-run check;
durable artifact paths and required artifact-set disposition; worker result summaries; fan-in and runtime closure;
displayed hypotheses; ownership; next action; and final reconciliation. Explicit evaluation runs additionally retain
evaluation identity, continuation, activation, timing, and evaluation results. Empty
explanatory sections MAY be omitted. A
smaller record that omits any required terminal field fails finalization; a larger record that duplicates evidence
fails the applicable artifact budget unless the recorded exception is valid.

Before releasing a terminal or blocked handoff, the Coordinator MUST run the packaged finalizer in `--pre-release` mode
against a pending closure probe while the final Documenter handle is still active. It runs the framework validator
against the candidate record without replacing `work_record.md`. A nonzero result is a handoff conformance failure.
Return the packet and exact error to the same Documenter and repeat the pre-release check. Pin the
preflight-resolved packaged framework root for the entire run; if it disappears or changes, stop with
`plugin_revision_mismatch` instead of discovering another installed package. After releasing the final Documenter and
recording provider closure in `runtime_closure.json`, finalization passes only when the finalizer exits zero and its
first output line is exactly `Workflow-framework validation: passed`; the remaining output is the canonical handoff.

The final answer MUST copy `state`, `engineering_state`, `workflow_outcome`, and `engineering_outcome` from the
reconciled record as distinct fields. It MUST NOT relabel `state: awaiting_input` as the engineering state or otherwise
substitute one vocabulary value for another. The selected playbook's required artifact set is part of reconciliation:
an artifact count is not sufficient when a required artifact is absent.

When the workflow stops for clarification or a blocker, the next action must
name the specific decision, artifact, file, command, or owner involved. It
must explain why that action is needed and what completion looks like. “Provide
more information,” “investigate further,” and similar generic instructions are
not sufficient.

The internal owner and the user action are different fields. A blocked run may have an internal owner while requiring no
technical user action beyond asking the workflow to retry. The handoff must not end with only an internal owner or an
unexplained technical instruction.

The ledger contains one compact row per activated worker and each required worker that did not reach a terminal
envelope:

| Column | Required content |
| --- | --- |
| Worker | Worker ID and role. |
| Activation/state | Required or conditional, and activated, terminal, active, or not started. |
| Outcome and summary | Terminal outcome and the worker's unique contribution; do not repeat the shared summary. |
| Confidence and limitations | Confidence plus material uncertainty, blocker, or reason it did not run. |
| Evidence or artifact | Evidence/claim references or durable artifact path. |
| Model, effort, and usage | Actual provider values when exposed; otherwise `Unknown`. |

A required worker without a terminal envelope must appear with its reason. It keeps fan-in open or the run `blocked`; it
cannot be omitted to make a profile appear successful.

An active subagent is never evidence that a stage is complete. A workflow may finish only after the fan-in barrier
passes or a documented terminal outcome explains why the remaining worker was not required.

## Worker Runtime Closure

Fan-in and runtime closure are separate barriers. A terminal result envelope proves that the worker returned a result;
it does not prove that the provider released the worker handle or its capacity.

After result envelopes and artifacts are persisted, the Orchestrator must:

1. mark each completed worker terminal;
2. close or release every completed provider handle, including continuous handoff or documentation workers from the
   finished run;
3. verify that no required worker from that run remains active; and
4. record each exact provider handle and its provider release confirmation before marking the run complete or starting
   a new lifecycle run.

Role names, terminal envelopes, and statements such as “all workers released” are not closure evidence. The closure row
must contain the provider-returned handles, no remaining active handles, and the provider close/release confirmation.

Before starting another lifecycle or remediation run, apply the [Concurrent Run Isolation](#concurrent-run-isolation)
gate. A clean read-only planning run may remain concurrent; any run with a writer
or shared artifact writer must wait for release or use an isolated worktree and
artifact root.

Never close a worker before collecting its terminal result envelope unless the provider has explicitly confirmed a
terminal failure or that the worker is no longer running. A later run reuses durable artifacts, not live worker handles
from the previous run. If the provider cannot expose release or active-handle status, record
`worker_runtime_release_unavailable` and keep the run `blocked` until the provider confirms that the new run has
capacity; do not silently downgrade or claim that the run is closed. A force-closed active worker is a Coordinator
interruption, not evidence of provider release or worker failure.

---

# Worker Outcomes

Every worker ends in one of these outcomes:

| Outcome          | Meaning                                                                               |
| ---------------- | ------------------------------------------------------------------------------------- |
| `complete`       | Exit criteria are satisfied with recorded evidence, limitations, and planned follow-up work. |
| `needs_input`    | Required information is missing and work cannot proceed safely.                       |
| `blocked`        | An external dependency, environment, permission, or decision prevents a safe usable result at the current stage. |
| `failed`         | The worker attempted the work and encountered an error that requires review or retry. |
| `not_applicable` | The playbook determined that this worker is not required.                             |

Partial findings are preserved for every non-complete outcome.

---

# Workflow State Machine

These are the canonical workflow states. They describe where a run is now; `planning` and `remediation` remain lifecycle
values that limit how far the run may proceed.

```mermaid
flowchart TB
    intake["intake"] --> classified["classified"]
    classified --> in_progress["in_progress"]
    in_progress --> awaiting_input["awaiting_input"]
    in_progress --> blocked["blocked"]
    in_progress --> ready["ready_for_implementation"]
    awaiting_input --> in_progress
    awaiting_input --> blocked
    ready -->|approval| implementation["implementation"]
    implementation --> code_review["code_review"]
    code_review -->|changes_required| implementation
    code_review -->|accepted| validation["validation"]
    code_review -->|replanning_required| awaiting_input
    code_review --> blocked
    validation -->|in_scope_failure| implementation
    validation --> handoff["handoff"]
    validation --> blocked
    handoff --> completed["completed"]
    blocked -->|recovery| in_progress
```

| State | Meaning | Allowed continuation |
| --- | --- | --- |
| `intake` | A run was created and its execution repository and work item are being established. | `classified` |
| `classified` | Playbook, profile, lifecycle, mode, and initial constraints are selected. | `in_progress` |
| `in_progress` | A required stage or worker graph is active and has not reached its gate. | `awaiting_input`, `blocked`, or `ready_for_implementation` |
| `awaiting_input` | A human decision or missing requirement remains after bounded discovery. | `in_progress`, or `blocked` if the input cannot be obtained |
| `blocked` | An environment, permission, runtime, or indispensable-evidence problem prevents safe progress. | `in_progress` after recovery, or terminal `blocked` |
| `ready_for_implementation` | Planning fan-in passed and the implementation plan is ready; source changes are still prohibited. | `implementation` only after explicit approval, or `awaiting_input` / `blocked` |
| `implementation` | Approved source or configuration changes are being made by the Implementer. | `code_review` or `blocked` |
| `code_review` | The Reviewer is assessing the approved change. | `implementation` for in-scope findings, `validation` when accepted, `awaiting_input` for replanning, or `blocked` |
| `validation` | Tests, build, security, runtime, or other declared validation are being run. | `implementation` for an in-scope failure, `handoff` when the gate passes, or `blocked` |
| `handoff` | Results, artifacts, ownership, and next steps are being finalized. | `completed` |
| `completed` | Required gates passed or a documented terminal outcome was recorded. | None; start a new run for new scope. |

Planning normally ends at `ready_for_implementation`, `awaiting_input`, or `blocked` and must not modify source.
Remediation enters `implementation` only through explicit approval and a recorded re-entry. A failed required worker
keeps the run `in_progress` or moves it to `blocked`; it cannot be treated as successful fan-in.

`closed_no_action`, `closed_duplicate`, `closed_not_a_bug`, and `deferred` are terminal outcomes recorded with
`completed`; they are not additional normal delivery states. A playbook may add domain-specific states only when it
preserves these meanings and records every transition reason.

---

# Workflow State and Engineering State

Workflow state describes what the workflow run is doing. Engineering state describes what has been established about the
work item. They are independent: a run can be `blocked` while the work item is `approved`, or a completed planning run
can leave the work item `designed` but not approved.

Every work record MUST record both states at handoff and when recovering an interrupted run. Engineering state is not a
second state machine and does not authorize source changes.

| Engineering state | Meaning |
| --- | --- |
| `unknown` | The work item's current behavior, scope, or outcome is not yet established. |
| `understood` | The current behavior, problem, and material scope are evidence-backed. |
| `designed` | An evidence-backed implementation design or plan exists. |
| `approved` | The implementation plan is explicitly approved for remediation. |
| `implemented` | Approved source or configuration changes are complete. |
| `validated` | Declared validation passed or its limitations are explicitly recorded. |
| `released` | The approved change is deployed or otherwise externally released. |
| `stabilized` | Required post-release observation, ownership, and operational follow-up are complete. |
| `not_applicable` | The state does not apply to the selected work item or terminal outcome. |

Engineering state MAY move backward when evidence invalidates a prior conclusion. The work record MUST preserve the
reason and affected decision or claim.

---

# Evidence and Artifact Minimums

Use the [`Claims, Evidence, Decisions, and Actions Contract`](claims.md) for the durable reasoning chain. Every material
claim must identify its supporting evidence, confidence, uncertainties, and status. Every decision must identify the
claims, options, owner, and approval status. Every action must identify its authorizing decision and required gate.

Every stage must declare the artifacts it produces and the gate those artifacts satisfy.

---

# Special Workflow Extension

A special workflow is valid when it declares the same minimum contract as a normal playbook:

- purpose and entry criteria;
- work-item inputs;
- stages and dependencies;
- roles, skills, tools, and worker profiles;
- artifacts and evidence requirements;
- gates and approval points;
- failure and blocked behavior;
- terminal outcomes;
- work-record requirements.

Special workflows may add domain-specific stages and artifacts. They must not bypass the shared work-item, evidence,
lifecycle, or work-record rules.

---

# Pilot Conformance Checklist

A pilot run MUST NOT be called contract-compliant unless its work record can answer:

- Which work item was handled?
- Which playbook, lifecycle, and profile were selected?
- Which workers ran, with which roles, skills, tools, internal metadata, and observed provider settings?
- What did each worker consume and produce?
- What was each worker's unique result, outcome, and limitation?
- Did every required fan-in barrier pass before completion?
- What evidence supports the current understanding?
- Does every action, decision, claim, and evidence reference resolve to a source-backed chain without orphans?
- Which gates passed or failed?
- What errors, blockers, and unknowns occurred?
- Were all explicitly named paths verified, including symlink targets where applicable?
- Why did the workflow finish, stop, or defer?
- What is the next action and who owns it?
