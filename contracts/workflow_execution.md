---
title: Workflow Execution Contract
version: 0.1
status: Pilot
provider_independent: true
owner: Engineering
last_updated: 2026-08-10
---

# Workflow Execution Contract

> Define the smallest shared contract required to execute engineering work with reusable playbooks, roles, skills, tools, and workers.

This contract is the seam between the workflow definition and the platform that executes it. A provider may implement the contract differently, but it must preserve the same inputs, outputs, evidence expectations, and completion semantics.

The contract is intentionally small. It supports sequential, parallel, and
conditional playbooks without requiring a general orchestration backend or a
live work-item connector.

---

# Vocabulary

| Term              | Meaning                                                                                                                                               |
| ----------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| Work item         | The normalized request being handled, such as a Jira Story, bug, incident, or upgrade.                                                                |
| Workflow run      | One execution of a playbook for one work item.                                                                                                        |
| Playbook          | A scenario-specific workflow made of stages, roles, skills, gates, and outputs.                                                                       |
| Stage             | A meaningful unit of work inside a playbook.                                                                                                          |
| Role              | A reusable responsibility and reasoning boundary.                                                                                                     |
| Skill             | A reusable capability required to perform work.                                                                                                       |
| Tool              | A concrete operation available to a worker.                                                                                                           |
| Model profile     | The model and reasoning configuration selected for a worker.                                                                                          |
| Worker            | One execution instance combining a role, skills, tools, model profile, and inputs. A worker may be a human, AI subagent, or step in a single session. |
| Artifact          | A durable output such as a map, decision, code change, test result, or handoff.                                                                       |
| Evidence          | A source-backed observation used to support or challenge a claim.                                                                                     |
| Gate              | A condition that must be satisfied before a stage or transition can proceed.                                                                          |
| Adapter           | A provider-specific implementation at a defined seam, such as Jira, Git, or an AI platform.                                                           |
| Execution profile | A named selection of worker graph, investigation depth, and validation scope.                                                                         |
| Lifecycle         | How far a workflow run may proceed, such as planning or remediation.                                                                                  |

Skills describe what capability is needed. Tools describe how that capability is performed. Model profiles describe how much reasoning and execution capacity is assigned. These concepts must not be merged.

The canonical role ID is the role filename without `.md`, such as `current_state_investigator` or `repository_integrator`.

---

# Pilot Tool IDs

These provider-neutral tool IDs cover the current pilot workflows. Providers
map them to concrete capabilities.

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

# Pilot Model Profiles

Model profiles describe intent and reasoning capacity without naming a provider-specific model.

| Profile              | Meaning                                                                                |
| -------------------- | -------------------------------------------------------------------------------------- |
| `standard_reasoning` | Normal analysis and execution for bounded work.                                        |
| `deep_reasoning`     | Extended analysis for cross-repository, architectural, operational, or high-risk work. |

Provider adapters map these profiles to available models and provider-specific effort settings. The mapping must be recorded when a worker runs.

---

# Work Item Contract

Every workflow begins with a normalized work item. The source may be Jira, another work tracker, a document, or manual input.

| Field                 | Required    | Description                                                              |
| --------------------- | ----------- | ------------------------------------------------------------------------ |
| `id`                  | Yes         | Stable identifier within the source system.                              |
| `source_system`       | Yes         | Jira, GitHub Issues, Linear, Markdown, or another source.                |
| `type`                | Yes         | Story, bug, task, incident, upgrade, migration, vulnerability, or other. |
| `title`               | Yes         | Short statement of the requested outcome.                                |
| `description`         | Yes         | Available problem or request context.                                    |
| `acceptance_criteria` | Recommended | Conditions supplied by the requester.                                    |
| `priority`            | Recommended | Source priority or urgency.                                              |
| `status`              | Recommended | Current source-system status.                                            |
| `links`               | Optional    | Related work items, pull requests, documents, dashboards, and incidents. |
| `repositories`        | Optional    | Source, destination, or affected repositories.                           |
| `constraints`         | Optional    | Runtime, ownership, compliance, release, or timing constraints.          |

Missing fields become explicit unknowns. They are never silently invented.

---

# Workflow Run Contract

Each run records:

| Field          | Description                                                                          |
| -------------- | ------------------------------------------------------------------------------------ |
| `run_id`       | Unique identifier for this execution.                                                |
| `work_item_id` | Identifier of the normalized work item.                                              |
| `playbook`     | Canonical playbook identifier.                                                       |
| `profile`      | Requested execution profile selected for this run.                                  |
| `lifecycle`    | Maximum run scope, such as `planning` or `remediation`.                              |
| `executed_profile` | Profile actually executed after worker activation and fan-in.                    |
| `profile_status` | `requested`, `in_progress`, `executed`, `not_executed`, or `blocked`.               |
| `mode`         | Discovery, investigation, delivery, stabilization, review, or another declared mode. |
| `effort`       | Quick, standard, or deep.                                                            |
| `state`        | Current workflow lifecycle state.                                                    |
| `workers`      | Selected workers and their dependencies.                                             |
| `gates`        | Required conditions and their status.                                                |
| `artifacts`    | Durable outputs produced during the run.                                             |
| `next_action`  | The smallest safe next action.                                                       |
| `owner`        | Person or team responsible for the current state.                                    |

---

# Worker Contract

Each worker must have a stable identifier and an explicit execution profile.

| Field              | Required           | Description                                                                                                          |
| ------------------ | ------------------ | -------------------------------------------------------------------------------------------------------------------- |
| `id`               | Yes                | Unique worker identifier within the workflow run.                                                                    |
| `role`             | Yes                | Canonical role identifier.                                                                                           |
| `mode`             | Yes                | Mode in which this worker operates.                                                                                  |
| `effort`           | Yes                | Provider-neutral worker depth: quick, standard, or deep. It does not select the provider model or reasoning setting. |
| `skills`           | Yes                | Canonical skill identifiers selected for this worker.                                                                |
| `tools`            | Yes                | Allowed concrete tool identifiers. An empty list means no tools are available.                                       |
| `model_profile`    | Yes for AI workers | Provider-neutral model and reasoning profile.                                                                        |
| `inputs`           | Yes                | Artifacts or facts the worker may consume.                                                                           |
| `outputs`          | Yes                | Artifacts or decisions the worker must produce.                                                                      |
| `depends_on`       | Yes                | Worker or gate dependencies. Use an empty list when none exist.                                                      |
| `parallelism`      | Yes                | `sequential`, `parallel`, `conditional`, or `continuous`.                                                            |
| `approval`         | Yes                | Whether human approval is required before the worker proceeds or publishes side effects.                             |
| `exit_criteria`    | Yes                | Evidence-based condition for completion.                                                                             |
| `failure_behavior` | Yes                | How errors, uncertainty, missing inputs, and blocked work are recorded.                                              |
| `usage`            | Recommended        | Provider-reported execution usage, such as input/output tokens, duration, or credits. Unknown values remain unknown. |

Illustrative profile:

```yaml
worker:
  id: source-understanding
  role: current_state_investigator
  mode: investigation
  effort: deep
  skills:
    - work_item_context
    - repository_exploration
    - architecture_mapping
  tools:
    - repository_search
    - repository_read
    - history_read
  model_profile: deep_reasoning
  inputs:
    - normalized_work_item
    - source_repository
  outputs:
    - current_state_summary
    - evidence_register
    - unknowns
  depends_on:
    - initialize
  parallelism: sequential
  approval: none
  exit_criteria: current state, evidence, and unknowns are documented
  failure_behavior: record the error, preserve partial findings, and mark the worker blocked
```

The example is a contract illustration, not a requirement to introduce a configuration language yet.

Provider-reported usage is observational metadata, not a worker input. A
provider adapter may populate it after execution. Workers must not estimate
credits when the provider does not expose them.

## Worker Result Envelope

Every worker returns one compact result envelope in addition to its durable
artifacts. The envelope is the unit consumed by the Orchestrator at fan-in.

| Field              | Required    | Description                                                     |
| ------------------ | ----------- | --------------------------------------------------------------- |
| `worker_id`        | Yes         | Worker that produced the result.                                |
| `outcome`          | Yes         | One of the shared worker outcomes.                              |
| `summary`          | Yes         | The worker's unique contribution in a few sentences.            |
| `inputs_consumed`  | Yes         | Artifacts or facts actually used.                               |
| `outputs_produced` | Yes         | Artifacts, decisions, or validation results produced.           |
| `evidence_refs`    | Recommended | Sources supporting the result.                                  |
| `uncertainties`    | Yes         | Remaining unknowns, conflicts, or confidence limits.            |
| `next_consumer`    | Recommended | Worker, gate, or human decision that should consume the result. |
| `model_effort`     | Recommended | Actual model and reasoning effort, when exposed.                |
| `usage`            | Recommended | Provider-reported tokens, duration, credits, or `Unknown`.      |
| `errors_blockers`  | Yes         | Errors, blockers, or `None`.                                    |

The summary must describe the worker's unique contribution, not repeat the
entire input artifact. A downstream worker must consume the envelope and
referenced artifacts rather than independently repeating the same investigation
unless it is checking a stated discrepancy.

---

# Modes and Effort

Modes and effort are separate dimensions.

## Modes

| Mode            | Meaning                                                                           |
| --------------- | --------------------------------------------------------------------------------- |
| `discovery`     | Establish feasibility, scope, options, and risks. Implementation is not expected. |
| `investigation` | Establish an evidence-backed understanding and recommendation.                    |
| `delivery`      | Implement and validate an approved change.                                        |
| `stabilization` | Reduce operational risk after extraction, migration, upgrade, or release.         |
| `review`        | Independently assess correctness, risk, and readiness.                            |

## Worker Effort

| Effort     | Meaning                                                          |
| ---------- | ---------------------------------------------------------------- |
| `quick`    | Small scope, few dependencies, narrow validation.                |
| `standard` | Normal sprint-sized work with bounded dependencies.              |
| `deep`     | Cross-repository, architectural, operational, or high-risk work. |

`discovery` is a mode, not an effort level. A discovery run may be quick, standard, or deep.

Worker effort is separate from the execution profile and from provider
reasoning effort. The playbook selects the execution profile; the provider
adapter applies the role's model and reasoning policy. A profile must not
silently lower the quality policy of a role.

## Execution Profiles and Lifecycle

Execution profile and lifecycle are independent dimensions:

| Dimension         | Selects                                                 | Example values            |
| ----------------- | ------------------------------------------------------- | ------------------------- |
| Execution profile | Worker graph, investigation depth, and validation scope | `standard`, `deep`        |
| Lifecycle         | How far the run may proceed                             | `planning`, `remediation` |

The profile answers “how much investigation is appropriate?” The lifecycle
answers “how far may this run proceed?” A `deep` planning run investigates
more thoroughly but still stops before implementation. A standard remediation
run may implement after the required approval gate.

Every profile must preserve the shared safety, evidence, work-record, approval,
and fan-in requirements. Provider adapters map the selected profile to concrete
model and effort settings without changing the lifecycle gates.

## Profile Execution Semantics

The requested profile is an execution requirement, not descriptive metadata.
At initialization, the Orchestrator records the requested profile and its
required workers. Before completing the run, it records the executed profile
and profile status.

The Orchestrator must not silently downgrade a profile to a smaller worker
graph. If required delegation is unavailable, the run is `not_executed` or
`blocked`; it is not a successful execution of the requested profile.

`requested` means the graph has not started, `in_progress` means required
workers are active or awaiting fan-in, and `executed` means all required
workers returned terminal envelopes and fan-in passed. `not_executed` means
the graph could not start. `blocked` means it started but cannot reach its next
gate. Escalation is a new recorded profile selection, never a profile status.

Set `profile_status: executed` only after every required worker returns a
terminal envelope and required fan-in passes. If a required worker was
activated but does not return a terminal envelope, set `profile_status:
blocked` and record the worker-specific runtime reason. A Coordinator cannot
replace a required independent worker. A different profile is a new,
explicitly requested run; it does not complete the original profile.

## Clarification Framing

An incomplete requirement or unresolved decision is not automatically a
blocker. Before requesting clarification, the Orchestrator must use the
available planning workers for bounded discovery of the current implementation,
contracts, tests, repository history, and related work when that evidence can
reduce the uncertainty.

If a decision still prevents implementation readiness, the Solution Architect
must record a Clarification Brief in the work record, with alternatives
summarized in `Alternatives Considered`: the decision needed, evidence
researched, one or more feasible options, tradeoffs and validation impact,
recommendation, and the smallest question and owner needed to proceed.

Use state `awaiting_input` with reason `clarification_required` for this
decision gap. Use `blocked` only when an unavailable environment, permission,
or indispensable evidence prevents bounded discovery or meaningful option
framing. Proposed options are not authorization to implement and do not permit
creating an implementation plan before the planning gate passes.

## Lifecycle Continuation and Re-entry

The selected lifecycle is immutable for one workflow run. A conversation may
continue, but a planning run does not become a remediation run merely because
the user asks a follow-up question or says to continue.

To move from `planning` to `remediation`, the Orchestrator must create or
explicitly record a new lifecycle run or re-entry event that:

1. preserves the existing work record and approved implementation plan;
2. records explicit implementation approval;
3. selects `lifecycle: remediation` without silently changing the profile;
4. re-reads the playbook, work record, and implementation plan;
5. records `profile_status: requested` for the remediation run;
6. activates every required delivery worker before source changes, reusing
   completed planning artifacts rather than rerunning planning workers;
7. waits for required result envelopes and completes fan-in; and
8. reports the new run's requested lifecycle, activated workers, and fan-in
   status.

If any condition is missing, the workflow remains in planning or stops with
state `awaiting_input` and reason `approval_required`, or state `blocked` and
reason `remediation_not_activated`. A generic implementation workflow must not
replace the selected playbook's remediation worker graph.

Before the first source change, the Orchestrator records the activated delivery
workers, their dependencies, and the required `implement → review
→ validate → handoff` path in the work record. The Coordinator does not act as
the Implementer, Reviewer, or Tester. If the required remediation graph cannot
be activated, do not edit source; stop with
`profile_status: blocked` and reason `remediation_not_activated`.

## Approved Remediation Continuity

One explicit remediation approval authorizes every in-scope step in the
approved implementation plan: implementation, review, validation,
stabilization, and handoff. It does not require approval after each planned
implementation slice. A partial slice leaves the run `in_progress`; the
Orchestrator continues the ordered worker graph until the plan is complete.

Pause for a new user decision only when new evidence invalidates the approved
scope or design, a required step exceeds that scope, an unapproved external or
irreversible action is required, or a genuine environment, permission, or
validation blocker prevents progress. Ordinary remaining plan steps, worker
handoffs, and focused per-slice checks are not approval gates.

## Delivery Code Review Loop

Code Review is a gate, not a final report. The Reviewer records one disposition:
`accepted`, `changes_required`, `replanning_required`, or `blocked`.

`changes_required` findings within approved scope return to the Implementer in
the same remediation run. The Implementer fixes them, records the result, and
the Reviewer rechecks the affected diff before validation begins. No new user
approval is required. `replanning_required` is reserved for evidence that
invalidates the approved scope or design; `blocked` is reserved for a genuine
external, environment, permission, or validation blocker. Numeric priority is
evidence of urgency, not a substitute for this disposition.

## Interrupted Profile Recovery

An incomplete required-worker graph is not a completed diagnosis or plan. The
canonical run prompt must support an `Interrupted profile recovery` continuation
that:

1. preserves the same work record, profile, lifecycle, and completed artifacts;
2. records completed workers, missing workers, and the recovery reason;
3. reuses completed result envelopes unless a specific discrepancy requires a
   rerun;
4. activates every incomplete required worker for the selected profile;
5. waits for all required result envelopes and completes fan-in; and
6. reports the recovered requested/executed profile, worker activation, fan-in,
   and next gate.

For an individual required worker that does not return a terminal envelope,
recovery closes its original handle, confirms that it no longer consumes
runtime capacity, and makes one fresh replacement attempt. It reuses completed
artifacts and does not repeat successful work. If the replacement also fails,
stop with `profile_status: blocked` and reason
`<normalized-worker-id>_runtime_unavailable`. Do not create an implementation plan, invent a
Coordinator-only review, or present a lower profile as completion of the
requested profile.

The approval gate applies to delivery workers. Missing implementation approval
must not prevent remaining planning workers from completing diagnosis and fix
design. If recovery delegation is unavailable, remain `blocked` or
`not_executed`; do not substitute a generic workflow or claim success.

## Durable Artifact Root

The prompt's `Execution repository` is the repository where the workflow is
started. It is the durable-artifact root for that run:

```text
<execution-repository>/.thoughts/<WORK-ITEM-ID>/
```

The `work_record.md`, worker artifacts, and any implementation plan belong
there. Repositories listed for investigation are target repositories, not
artifact roots. A worker must not place durable workflow files in a target
repository merely because it is the suspected fault repository or appears
first in the topology.

The execution repository must be explicit in the canonical run prompt. If it
is missing or ambiguous, stop with `blocked` and request the smallest missing
path; do not infer it from the playbook location or target-repository list.

---

# Parallelism Semantics

| Value         | Meaning                                                                                                         |
| ------------- | --------------------------------------------------------------------------------------------------------------- |
| `sequential`  | The worker starts only after declared dependencies complete.                                                    |
| `parallel`    | The worker may run alongside independent workers after its dependencies complete.                               |
| `conditional` | The worker may run in parallel only when the playbook or Orchestrator confirms that its inputs are independent. |
| `continuous`  | The worker starts after initialization and consumes incremental artifacts throughout the run.                   |

Dependencies describe readiness to start. Inputs describe artifacts consumed. A worker may consume outputs from another worker without being blocked from starting when the playbook explicitly supports incremental updates.

# Stage Completion and Fan-In

A stage that launches multiple workers has a fan-in barrier. The Orchestrator
must wait for every required worker to reach a terminal outcome before marking
the stage or workflow complete.

The Orchestrator must preserve each worker's result, error, blocker, and usage
metadata; summarize every worker result in the durable work record; distinguish
all worker outcomes; and keep the parent workflow `in_progress` while any
required worker is still active.

The final workflow handoff contains both a shared outcome summary and a compact
worker-result ledger. The shared summary answers what should happen next. The
worker ledger makes each contribution, outcome, limitation, and usage visible
without requiring the reader to reconstruct parallel execution from logs.

An active subagent is never evidence that a stage is complete. A workflow may
finish only after the fan-in barrier passes or a documented terminal outcome
explains why the remaining worker was not required.

## Worker Runtime Closure

Fan-in and runtime closure are separate barriers. A terminal result envelope
proves that the worker returned a result; it does not prove that the provider
released the worker handle or its capacity.

After result envelopes and artifacts are persisted, the Orchestrator must:

1. mark each completed worker terminal;
2. close or release every completed worker handle, including continuous
   handoff/documentation workers from the finished run;
3. verify that no required worker from that run remains active; and
4. record the closure status before marking the run complete or starting a new
   lifecycle run.

Never close a worker before collecting its terminal result envelope. A later
run reuses durable artifacts, not live worker handles from the previous run.
If the provider cannot expose release or active-handle status, record
`worker_runtime_release_unavailable` and keep the run `blocked` until the
provider confirms that the new run has capacity; do not silently downgrade or
claim that the run is closed.

---

# Worker Outcomes

Every worker ends in one of these outcomes:

| Outcome          | Meaning                                                                               |
| ---------------- | ------------------------------------------------------------------------------------- |
| `complete`       | Exit criteria are satisfied with recorded evidence.                                   |
| `needs_input`    | Required information is missing and work cannot proceed safely.                       |
| `blocked`        | An external dependency, environment, permission, or decision prevents progress.       |
| `failed`         | The worker attempted the work and encountered an error that requires review or retry. |
| `not_applicable` | The playbook determined that this worker is not required.                             |

Partial findings are preserved for every non-complete outcome.

---

# Workflow Lifecycle

The shared lifecycle supports both implementation and non-implementation work:

```text
intake
  → classified
  → in_progress
  → awaiting_input | blocked | ready_for_implementation
  → implementation
  → validation
  → completed
```

Valid terminal alternatives include:

```text
closed_no_action
closed_duplicate
closed_not_a_bug
deferred
```

The selected playbook may add states, but it must preserve the common meanings and record the reason for every terminal outcome.

---

# Evidence and Artifact Minimums

Every material claim should identify:

| Field         | Description                                                                 |
| ------------- | --------------------------------------------------------------------------- |
| `claim`       | The statement being made.                                                   |
| `source`      | Repository path, ticket, log, dashboard, document, command, or observation. |
| `observed_at` | When the evidence was collected.                                            |
| `worker`      | Worker that collected or asserted it.                                       |
| `status`      | Verified, inferred, hypothesized, contradicted, or unknown.                 |
| `notes`       | Context, limitations, or conflicting evidence.                              |

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

Special workflows may add domain-specific stages and artifacts. They must not bypass the shared work-item, evidence, lifecycle, or work-record rules.

---

# Pilot Validation

The first pilot is contract-compliant when the work record can answer:

- Which work item was handled?
- Which playbook and mode were selected?
- Which workers ran, with which roles, skills, tools, model profiles, and effort?
- What did each worker consume and produce?
- What was each worker's unique result, outcome, and limitation?
- Did every required fan-in barrier pass before completion?
- What evidence supports the current understanding?
- Which gates passed or failed?
- What errors, blockers, and unknowns occurred?
- Why did the workflow finish, stop, or defer?
- What is the next action and who owns it?
