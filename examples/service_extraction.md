---
title: Service Extraction and Stabilization Example
version: 0.1
status: Pilot
owner: Engineering
last_updated: 2026-07-31
depends_on:
  - ../frameworks/investigation.md
  - ../playbooks/service_extraction.md
  - ../contracts/workflow_execution.md
  - ../templates/work_record.md
  - ../templates/service_extraction_run_prompt.md
---

# Service Extraction and Stabilization Example

> Example of decoupling an existing capability into a new independently
> buildable and deployable service.

## Example Scenario

A Jira Story requests moving an existing capability from a monorepo or source
repository into a new destination repository. The destination must use the
migrated code, preserve required behavior, and become independently maintainable
before new feature work begins.

## Example Inputs

| Item | Example |
| --- | --- |
| Work item | Jira Story: `<JIRA-STORY-URL>` |
| Source repository | `/projects/source-repository` |
| Destination repository | `/projects/destination-repository` |
| Capability | `<SERVICE-OR-COMPONENT>` |
| Acceptance criteria | Buildable, testable, deployable, and independently owned |
| Related work | Jira tickets, pull requests, architecture and deployment docs |
| Constraints | Preserve behavior; limit changes to imports, wiring, adapters, and required configuration |

## Execution Shape

Use the
[`Service Extraction and Stabilization`](../playbooks/service_extraction.md)
playbook with the canonical
[`service_extraction_run_prompt.md`](../templates/service_extraction_run_prompt.md).
The normal run begins with `deep + planning`; remediation begins only after
explicit approval and re-entry. The planning flow is:

```text
Initialize
  → Understand source
    → Analyze dependencies and boundary
      → Design service
        → Integrate destination
          → Extract and adapt
            → Review and validate
              → Stabilize and hand off
```

Use Standard only for bounded extractions with known ownership and limited
dependencies. Use Deep by default for new repositories, cross-repository
dependencies, deployment changes, data or event contracts, or production
cutovers.

## Work Record

Recover or create:

```text
<execution-repository>/.thoughts/<WORK-ITEM-ID>/work_record.md
```

The record must preserve source and destination context, current-state
evidence, dependency and ownership analysis, boundary decisions, integration
constraints, implementation progress, validation, blockers, rollback, and
stabilization ownership.

Create `implementation_plan.md` beside the work record only after all required
planning workers complete, fan-in passes, and the workflow reaches
`ready_for_implementation`.

## Safety Boundary

Planning makes no source or external-system changes. After approved remediation
re-entry, understand source behavior and destination constraints before moving
code. Do not change behavior merely because code is being moved. Prefer this
order for migrated code:

1. imports and namespaces;
2. registration and routing;
3. adapters and integration boundaries;
4. configuration and deployment wiring;
5. focused tests and documentation; and
6. behavior changes only with explicit approval.

Do not remove the source path until coexistence, rollback, ownership, and
operational readiness are understood.

## Expected Handoff

The final handoff should report:

- extracted capability and verified source/destination boundary;
- dependency and ownership decisions;
- integration adaptations and remaining gaps;
- code and test changes;
- validation and operational evidence;
- rollback and coexistence status;
- residual risks and follow-up work; and
- next owner and smallest safe next action.
