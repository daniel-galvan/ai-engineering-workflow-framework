---
title: Service Extraction and Stabilization Playbook
version: 0.1
status: Pilot
maturity: not_exercised
owner: Engineering
last_updated: 2026-08-10
depends_on:
  - ../frameworks/investigation.md
  - ../strategies/collaborative.md
  - ../contracts/workflow_execution.md
  - ../templates/work_record.md
  - ../templates/implementation_plan.md
  - ../templates/service_extraction_run_prompt.md
---

# Service Extraction and Stabilization

> Establish an independently buildable, runnable, deployable, and maintainable
> service from capability code currently coupled to another system.

## Purpose

Use this playbook to decouple a capability into an independently owned service.
It covers discovery, boundary design, destination integration, approved
extraction, validation, coexistence or cutover, and handoff. It does not turn
later feature work in the new service into extraction work.

The goal is not to copy files. The goal is to establish a clear service seam,
an operational path to production, and evidence that the destination can evolve
independently.

## When To Use

Use when an existing capability is coupled to a source repository, application,
or service and a destination service boundary must become independently
buildable, deployable, maintainable, and owned.

Use another playbook for a database-only, infrastructure-only, or deployment-
only migration; a normal feature, bug, or upgrade in an existing service; or a
temporary code copy with no independent-service goal.

## Required Inputs

- Jira Story or equivalent work item;
- source and destination repositories or workspaces;
- capability being extracted;
- desired outcome and acceptance criteria; and
- known runtime, deployment, ownership, data, event, and contract constraints.

Missing inputs are explicit unknowns. They are never silently inferred.

## Default Execution

The default is `deep + planning`. Service extraction normally has
cross-repository, ownership, deployment, or operational uncertainty.

| Execution profile | Use when | Planning behavior |
| --- | --- | --- |
| `standard` | Bounded extraction with known source, destination, ownership, and runtime | Runs source, dependency, design, destination-integration, and continuous documentation workers. |
| `deep` | New service repository, unclear coupling or ownership, data/event contracts, new deployment, cutover, or disputed boundary | Runs the standard graph plus an independent planning review before the plan is accepted. |

| Lifecycle | Behavior |
| --- | --- |
| `planning` | Investigate, design, integrate, and create an implementation plan; stop at `ready_for_implementation`. No source or external-system changes. |
| `remediation` | Execute the approved plan through extraction, review, validation, stabilization, and handoff after explicit approval. |

Use [`templates/service_extraction_run_prompt.md`](../templates/service_extraction_run_prompt.md)
as the canonical session-prompt format. The prompt supplies scenario data; it
does not redefine the process.

## Continuation, Re-entry, and Recovery

The shared execution contract governs immutable lifecycle, remediation re-entry,
and interrupted-profile recovery. For this playbook:

- A planning follow-up may clarify the plan but cannot extract code.
- A remediation re-entry requires explicit approval, the same profile, the
  existing work record and implementation plan, required-worker activation,
  result envelopes, fan-in, and worker-runtime closure for the prior run before
  source changes.
- An interrupted run uses the canonical prompt with `Interrupted profile
  recovery`: preserve completed artifacts, activate only missing required
  workers, and complete fan-in.
- Missing implementation approval blocks delivery workers only. It must not
  stop remaining planning workers from completing the service design.
- Missing required activation or fan-in is `blocked` or `not_executed`; it is
  never a successful profile execution.

## Worker Graph

The playbook owns this graph. Generic role documents and provider agents supply
reusable responsibilities and runtime settings; they do not override it.

| Worker | Role | Skills | Tools | Activation / dependency |
| --- | --- | --- | --- | --- |
| `initialize` | `orchestrator` | `work_item_context`, `workflow_planning`, `work_record_maintenance` | `work_item_read`, `work_record_read`, `work_record_write` | First |
| `source-understanding` | `current_state_investigator` | `work_item_context`, `repository_exploration`, `architecture_mapping` | `repository_read`, `repository_search`, `history_read`, `artifact_write` | After `initialize` |
| `dependency-analysis` | `dependency_analyst` | `dependency_mapping`, `architecture_mapping` | `repository_read`, `repository_search`, `history_read`, `dependency_inspect`, `artifact_write` | After `source-understanding` |
| `service-design` | `solution_architect` | `architecture_mapping`, `workflow_planning` | `artifact_write`, `work_record_write` | After `dependency-analysis` |
| `destination-integration` | `repository_integrator` | `destination_integration`, `operational_readiness` | `repository_read`, `repository_search`, `history_read`, `artifact_write` | After `service-design` |
| `planning-review` | `reviewer` | `architecture_mapping`, `operational_readiness` | `repository_read`, `diff_review`, `artifact_write` | Deep only; after `destination-integration` |
| `implement` | `implementer` | `code_migration`, `build_and_test` | `repository_read`, `repository_write`, `build_run`, `test_run`, `work_record_write` | Remediation only; approval plus completed planning fan-in |
| `review` | `reviewer` | `architecture_mapping`, `build_and_test`, `operational_readiness` | `repository_read`, `diff_review`, `test_run`, `artifact_write` | After `implement` |
| `validate` | `tester` | `build_and_test`, `operational_readiness` | `build_run`, `test_run`, `runtime_observe`, `artifact_write` | After `review` |
| `handoff` | `documenter` | `work_record_maintenance` | `work_record_read`, `work_record_write`, `artifact_write` | Continuous after `initialize` |

Required worker sets:

- `standard + planning`: `initialize`, `source-understanding`,
  `dependency-analysis`, `service-design`, `destination-integration`, and
  continuous `handoff`.
- `deep + planning`: all standard planning workers plus `planning-review`.
- `standard + remediation`: reuse completed standard planning artifacts, then
  activate `implement`, `review`, `validate`, and `handoff` after approval.
- `deep + remediation`: reuse completed deep planning artifacts, then activate
  `implement`, `review`, `validate`, and `handoff` after approval.

The provider adapter maps each generic role to model and reasoning effort. A
profile selects workers and validation depth; it does not silently change a
role's quality policy.

## Work Record and Implementation Plan

Use the prompt's declared `Execution repository` as the durable-artifact root:

```text
<execution-repository>/.thoughts/<WORK-ITEM-ID>/work_record.md
```

Source and destination repositories are investigation targets, not artifact
roots. Do not infer the artifact root from the playbook location or repository
list.

Do not create `implementation_plan.md` during initialization. The Documenter
creates it from [`templates/implementation_plan.md`](../templates/implementation_plan.md)
only after all required planning workers return terminal envelopes, fan-in is
complete, and the workflow is ready for implementation:

```text
<execution-repository>/.thoughts/<WORK-ITEM-ID>/implementation_plan.md
```

The plan must identify source and destination revisions, the selected service
seam, moved/adapted/retained dependencies, migration slices, contracts,
coexistence or cutover, rollback, validation, operations, and completion
criteria.

## Execution Flow

### Stage 0 — Initialize

The Orchestrator records the work item, requested profile, lifecycle, worker
graph, scope, non-goals, acceptance criteria, source and destination context,
constraints, unknowns, and the next gate. It creates or recovers only the work
record and starts the continuous Documenter.

### Stage 1 — Understand the Source

`source-understanding` documents current behavior, entry points, public
interfaces, tests, configuration, datastores, queues, events, external APIs,
observability, deployment assumptions, and ownership. Separate facts,
inferences, hypotheses, and unknowns.

### Stage 2 — Analyze Dependencies and Boundary

`dependency-analysis` maps upstream callers, downstream consumers, shared
libraries and models, data and event ownership, authentication, configuration,
secrets, deployment, and rollback coupling. Classify every material dependency
as move, remain external, adapt, share temporarily, remove, or unknown.

### Stage 3 — Design the Service

`service-design` defines the smallest safe destination seam: responsibilities,
interfaces, data and event ownership, failure and retry behavior, compatibility,
versioning, migration slices, coexistence, rollback, and explicitly deferred
features. It compares direct extraction, shared-library-first, strangler, and
deferral when relevant.

### Stage 4 — Integrate the Destination

`destination-integration` verifies destination conventions for location,
build, dependencies, tests, runtime, deployment, configuration, secrets,
observability, CI/CD, ownership, alerts, dashboards, and runbooks. It produces
the first independently verifiable destination milestone.

For `deep`, `planning-review` independently challenges the seam, scope,
coupling assumptions, coexistence, rollback, and validation plan.

### Stage 5 — Complete Planning

The Orchestrator waits for every required planning worker and the Documenter
records the result envelopes and fan-in. Only then may the Documenter create
`implementation_plan.md` and set `ready_for_implementation`.

No plan is created and no readiness claim is made when planning workers are
blocked, failed, unavailable, or incomplete.

### Stage 6 — Re-enter Remediation and Extract

Enter only after explicit approval and the remediation re-entry requirements
pass. `implement` executes the approved plan in small vertical slices:

1. establish the destination build and test baseline;
2. move the smallest independently testable capability;
3. adapt imports, registration, adapters, routing, configuration, and
   dependencies;
4. add or preserve focused tests and required integrations;
5. keep source and destination behavior comparable while coexistence is
   required; and
6. remove temporary extraction code only after the replacement path is
   validated.

Preserve migrated business behavior. New features require explicit scope and
approval.

### Stage 7 — Code Review and Validate

`review` verifies the approved seam, scope, compatibility, destination
conventions, coexistence, rollback, and coverage. `validate` records the lowest
validation level that proves the claim, escalating as needed:

1. destination build, focused tests, and contract checks;
2. source/destination regression and integration checks;
3. deployment, smoke, observability, and operational checks; and
4. cutover or coexistence verification and post-release observation.

Every check is `pass`, `fail`, `skipped`, `unavailable`, or `inconclusive`.
Unavailable or inconclusive checks are not passes.

In-scope review findings return to `implement` and are re-reviewed before
validation. Reopen planning only when evidence invalidates the approved seam
or extraction design.

### Stage 8 — Stabilize and Hand Off

The service is complete only when it has an explicit owner, independent build
and test path, documented runtime and deployment path, known consumers,
configuration and secret ownership, observability, rollback or coexistence,
residual risks, and follow-up work. Later feature, bug, upgrade, or performance
work is separate from extraction unless required for stabilization.

## Gates

| Gate | Required condition |
| --- | --- |
| Source ready | Current behavior, entry points, runtime assumptions, and unknowns are recorded. |
| Boundary ready | Coupling, ownership, material dependencies, and risks are evidenced or explicitly blocked. |
| Design ready | The destination seam, alternatives, compatibility, coexistence, rollback, and validation strategy are clear. |
| Integration ready | Destination placement, build/runtime path, operational requirements, and adaptations are known. |
| Implementation ready | Required planning fan-in passed and `implementation_plan.md` exists. |
| Approval ready | Explicit implementation approval and remediation re-entry are recorded. |
| Validation ready | Review findings are resolved or accepted and validation results are preserved. |
| Handoff ready | Ownership, operations, rollback or coexistence, residual risk, and next action are explicit. |

## Required Handoff Output

The final handoff reports:

1. extracted capability, verified source/destination seam, and outcome;
2. implementation-plan path/status, code changes, validation, coexistence or
   cutover, rollback, and operational evidence;
3. worker result ledger plus requested/executed profile, activation, and
   fan-in and runtime-closure status; and
4. residual risks, blockers, owner, follow-up work, and next action.

The handoff must not imply implementation, validation, or cutover completed
when the workflow stopped at a planning, approval, environment, or worker gate.

## Terminal Outcomes

In addition to shared contract outcomes, this playbook may close as:

- `extraction_completed`;
- `ready_for_implementation`;
- `boundary_not_safe`;
- `destination_not_ready`;
- `deferred_to_separate_work`; or
- `insufficient_evidence`.

Each outcome requires evidence and a next action.

## Related Documents

- [`../templates/service_extraction_run_prompt.md`](../templates/service_extraction_run_prompt.md)
- [`../templates/work_record.md`](../templates/work_record.md)
- [`../templates/implementation_plan.md`](../templates/implementation_plan.md)
- [`../examples/service_extraction.md`](../examples/service_extraction.md)
