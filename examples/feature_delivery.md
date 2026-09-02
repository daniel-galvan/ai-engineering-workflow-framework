---
title: Feature Delivery Example
version: 0.4.15
status: Pilot
owner: Engineering
last_updated: 2026-08-21
depends_on:
  - ../playbooks/feature_delivery.md
  - ../templates/feature_delivery_run_prompt.md
  - ../templates/implementation_plan.md
  - ../contracts/workflow_execution.md
---

# Feature Delivery Example

> Example of turning a Jira feature or improvement into an evidence-backed,
> approval-gated delivery plan.

## Example Scenario

A Jira ticket requests a capability change but lacks enough local detail to implement safely. The workflow recovers its
immediate parent, ancestors, selected siblings, linked decisions, and repository evidence without treating that context
as automatic scope.

## Example Inputs

| Item | Example |
| --- | --- |
| Work item | `<JIRA-TICKET-ID-OR-URL>` |
| Execution repository | Local checkout where the run begins |
| Primary or additional code repositories | Affected repository checkouts |
| Parent or ancestor context | `<JIRA-URLS-OR-UNKNOWN>` |
| Related siblings or decisions | `<JIRA-URLS-OR-NONE>` |
| Desired outcome | `<DESCRIPTION-OR-UNKNOWN>` |
| Constraints and non-goals | `<DESCRIPTION-OR-NONE>` |

## Run Format

Use the canonical [`feature_delivery_run_prompt.md`](../templates/feature_delivery_run_prompt.md) template. For a
bounded feature, begin with:

```text
Playbook: playbooks/feature_delivery.md
Canonical run template: templates/feature_delivery_run_prompt.md
Execution profile: standard
Lifecycle: planning
```

Use `deep` when ownership, repositories, public contracts, persistence, rollout, or acceptance criteria remain
uncertain.

## Expected Planning Outcome

The work record is created at:

```text
<execution-repository>/.thoughts/<WORK-ITEM-ID>/work_record.md
```

When context is incomplete, perform bounded discovery and record a Clarification Brief with feasible options and a
recommendation. Do not create an implementation plan until the minimum implementable outcome is clear and planning
fan-in passes.

When ready, create:

```text
<execution-repository>/.thoughts/<WORK-ITEM-ID>/implementation_plan.md
```

## Approved Delivery

Explicit remediation approval starts a new remediation run using the same profile, work record, and implementation plan.
Reuse planning artifacts, then activate the delivery graph:

```text
Implement → Code Review → Validate → Handoff
```

The Coordinator does not perform those roles. One approval covers the entire approved plan; a new approval is needed
only if evidence changes the scope or design, or a genuine blocker requires a decision.

## Expected Handoff

Report the verified scope, implementation-plan status, delivered changes, worker ledger, validation results, release or
rollback considerations, residual risks, owner, and next action.
