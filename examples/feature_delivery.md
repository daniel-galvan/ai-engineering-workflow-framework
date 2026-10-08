---
title: Feature Delivery Example
version: 0.5.20
status: Pilot
owner: Engineering
last_updated: 2026-10-08
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

## Rare Case with a Simpler Existing Behavior

An Epic requests that scheduled exports use current source data, while customized exports preserve their saved data.
A Story also requests a conflict when an administrator changes the source during another administrator's save.
Existing code already compares the requested data with the source and persists a classification.

Source inspection proves the race can occur, but does not establish its frequency. Supplied owner context says this is
normally a single-administrator workflow. Record that as reported exposure, not a measured percentage. Compare the
existing classification and recovery with adding revision tracking, new migrations, and conflict handling. Ask the
owner which observable behavior is required in that race, and explain the extra work needed for stronger handling.

| Evidence or decision | Disposition and effect |
| --- | --- |
| Current-source and customized-export requirements are explicit | Keep both in required Coverage and validate the normal flows first. |
| Concurrent-edit conflict is an explicit Story criterion | Retain it as required until the owner confirms a change; rarity alone cannot remove it. |
| Owner accepts existing classification for that race and explicitly removes conflict handling | Record the exact accepted limitation and reconcile affected criteria; no revision-tracking work is required for this case. |
| Source inspection shows the new export path can publish private data | Address the safety failure even with rare exposure; document the supported trigger and smallest safe repair. |
| A separate existing recovery weakness does not affect the requested export behavior | Record a follow-up and its non-impact rationale; preserve the current Story boundary. |

For implementation planning, cite the existing comparator, persistence enum, and colocated tests to reuse. The Reviewer
checks the simplest design against the required behavior and accepted limitation. Once those checks pass, proceed to
handoff; a new hypothetical timing sequence alone does not justify reopening the decision.

## Continuation with an Accepted Compatibility Rule

A previous Story established that an unfamiliar stored export mode uses saved content. Its accepted decision, decoder,
and unit test agree. A later Story changes source resolution, but a derived plan incorrectly says unfamiliar stored
modes must fail. The current requirements do not change the compatibility decision.

The receiving session verifies those sources, corrects the derived wording, and reports: "This preserves the accepted
compatibility rule and existing test. No new product decision is needed for this part." It does not ask "keep or change
the rule?", invent a user-interface reproduction, or require a new end-to-end test solely for that unchanged conversion.
This does not waive validation of the new source-resolution behavior or the overall implementation approval gate.

| Continuation evidence | Expected disposition |
| --- | --- |
| Accepted decision, current decoder, and existing unit test agree | Preserve accepted behavior; correct the derived plan; no new product approval for this rule. |
| Current requirement explicitly replaces the old compatibility rule | Record the conflict and affected behavior; obtain a decision if the applicable authority remains unresolved. |
| Code implements a fallback, but no accepted decision supports it | Do not infer product approval from code alone; resolve material uncertainty through bounded checks. |
| A new supported path makes the old fallback expose private data | Reopen the safety conclusion and find the smallest safe repair; prior acceptance does not dismiss new evidence. |
| The rule is settled, but implementation approval is pending | Keep source changes paused for overall approval, not another compatibility question. |
| A hypothetical same-clock collision suggests stronger version tracking | Check the actual consumer and observable failure first; add stronger handling only for a verified requirement. |

Review only changed requirements, repository state, and affected decisions against the saved baseline. Additional checks
must identify which unresolved decision they can change. The expected result is a narrow continuation review, not a new
planning investigation.
