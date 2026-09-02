---
title: Workflow Execution Guidance
version: 0.4.15
status: Pilot
owner: Engineering
last_updated: 2026-08-21
depends_on:
  - ./workflow_execution.md
---

# Workflow Execution Guidance

> Explain the execution contract without creating additional requirements or gates.

The [workflow execution contract](workflow_execution.md) is authoritative. Load this guidance only when an active role
or stage needs an example or an explanation of internal metadata.

## Roles and Provider Metadata

Skills describe capabilities; tools describe concrete operations. Mode, worker depth, and capacity classification are
separate internal dimensions recorded for provider adapters and auditability. Users select the execution profile and
lifecycle, not these internal fields.

The `orchestrator` role owns workflow coordination. The Coordinator is the active runtime performing that role. A
provider may use a dedicated worker, or the main session may perform both responsibilities when nested delegation is
unavailable. Canonical role IDs use the role filename without `.md`.

The default Codex execution mode is the active parent session as Coordinator; the `orchestrator` and
`sentry_orchestrator` provider definitions are policy metadata and do not create a child task by themselves. Record the
execution mode explicitly and record the parent session's actual model and reasoning effort.

### Modes

| Mode | Meaning |
| --- | --- |
| `discovery` | Establish feasibility, scope, options, and risks. Implementation is not expected. |
| `investigation` | Establish an evidence-backed understanding and recommendation. |
| `delivery` | Implement and validate an approved change. |
| `stabilization` | Reduce operational risk after upgrade or release. |
| `review` | Independently assess correctness, risk, and readiness. |

### Provider-Neutral Worker Depth

| Depth | Meaning |
| --- | --- |
| `quick` | Small scope, few dependencies, and narrow validation. |
| `standard` | Normal bounded engineering work. |
| `deep` | Cross-repository, architectural, operational, or high-risk work. |

Mode, worker depth, execution profile, and provider reasoning effort are different concepts. The playbook selects the
worker graph; the provider adapter applies the role's model and reasoning policy.

### Capacity Classifications

| Capacity class | Meaning |
| --- | --- |
| `standard_reasoning` | Normal analysis and execution for bounded work. |
| `deep_reasoning` | Extended analysis for cross-repository, architectural, operational, or high-risk work. |

Provider adapters map these classifications to available models and provider-specific effort settings and record the
resolved values when a worker runs.

## Illustrative Worker Profile

This example shows the contract fields. It is not a required configuration format.

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
    - IN-001
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
