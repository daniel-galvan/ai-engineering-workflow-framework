---
title: Feature Delivery Example
version: 0.5.2
status: Pilot
owner: Engineering
last_updated: 2026-09-23
depends_on:
  - ../playbooks/feature_delivery.md
  - ../templates/feature_delivery_run_prompt.md
  - ../templates/implementation_plan.md
  - ../templates/specification_assessment.md
  - ../templates/asset_manifest.json
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
| Jira attachments and supporting asset sources | Complete attachment inventory plus explicitly marked file/folder/URL inputs |
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
fan-in passes. The current run must also contain a passed `asset_manifest.json` covering the complete Jira attachment
inventory and every declared supporting source.

When ready, create:

```text
<execution-repository>/.thoughts/<WORK-ITEM-ID>/implementation_plan.md
```

The implementation plan carries an Asset Baseline naming each material asset, its observation, evidence, and planning
consequence.

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

## Completed Spike Results and Epic Story Coverage

Use `specification_assessment + specification_assessment` when the question is whether Stories produced by a completed
Spike collectively cover their Epic. For example, an Epic has a completed Spike whose outputs are four implementation
Stories. That relationship is a starting input, not proof that the Story set is complete. Do not execute another broad
Spike or treat the completed Spike as the new review target.

The short run-specific request is:

```text
Run Feature Delivery specification_assessment for <EPIC-ID>. Assess whether the Stories produced by the completed
Spike cover the Epic's required behavior and are ready for implementation.
```

The plugin's canonical launcher supplies the objective pair, playbook path, repository, and other required fields. The
playbook discovers the Jira hierarchy, attachments, history, linked sources, and repository evidence; the user need
not copy them into the request. The completed Spike may have no standalone write-up: record that limitation, then
review the Stories and their acceptance criteria directly rather than assuming `Done` means complete coverage.

Deliver `asset_manifest.json`, `work_record.md`, and `specification_assessment.md`. The assessment maps each Epic
requirement, edge case, and cross-Story dependency to a Story, evidence, status, gap, and owner. It identifies any
missing or conflicting acceptance and validation conditions. If all material requirements are covered, use
`Ready for implementation` or `Ready with explicit follow-ups`; otherwise use `Not ready for implementation` and a
Clarification Brief. Both outcomes are useful results. Do not create `implementation_plan.md` on this route. A later
Story-level or Epic-level implementation-planning run is separate. Only a newly isolated technical unknown warrants a
new Spike.
