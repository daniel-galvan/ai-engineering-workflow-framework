---
title: TechOps Issue Remediation Example
version: 0.5.33
status: Pilot
owner: Engineering
last_updated: 2026-10-27
depends_on:
  - ../playbooks/techops_issue_remediation.md
  - ../templates/techops_issue_run_prompt.md
  - ../templates/implementation_plan.md
  - ../contracts/workflow_execution.md
---

# TechOps Issue Remediation Example

> Example of investigating a detailed support- or operations-reported issue
> without treating the report or its attachments as proof of the root cause.

## Example Scenario

A TechOps Jira issue reports that a user-visible action did not produce the expected result. The ticket includes
screenshots, a payload export, and an approximate timestamp, but the responsible repository is unknown.

## Example Inputs

| Item | Example |
| --- | --- |
| Work item | `<TECHOPS-JIRA-ID-OR-URL>` |
| Execution repository | Current main checkout root; use the monorepo root when applicable, omitted from the ordinary prompt |
| Primary code scope | `<PROJECT-PATH-OR-UNKNOWN>` |
| Additional code scopes | `<OTHER-PROJECT-OR-REPOSITORY-PATHS-AND-WHY-OR-NONE>` |
| Reported behavior | `<DESCRIPTION>` |
| Expected behavior | `<DESCRIPTION>` |
| Supporting artifacts | `<SCREENSHOT-LOG-JSON-OR-TRANSCRIPT-PATHS-OR-NONE>` |
| Related work | `<JIRA-PR-RUNBOOK-OR-NONE>` |

## Plugin Invocation

Start the Codex task from the main checkout root, using the monorepo root when applicable, and invoke the installed
plugin. Supply known code scope and any separately supplied supporting artifacts; the launcher loads the canonical
input schema and provider definitions. Durable records belong in the resolved main checkout, while source operations
use the active equivalent worktree.

```text
$ai-engineering-workflows:run Run the TechOps Issue Remediation playbook.

Work item: <TECHOPS-JIRA-ID-OR-URL>
Playbook: playbooks/techops_issue_remediation.md
Primary code scope: <PROJECT-PATH-OR-UNKNOWN>
Supporting artifacts: <SCREENSHOT-LOG-JSON-OR-TRANSCRIPT-PATHS-OR-NONE>
```

For this new planning run, omit profile and lifecycle to use `standard` + `planning`. Add `Execution profile: deep` when
ownership crosses systems or repositories, the first-loss point is unclear, the failure is intermittent, or the impact
and rollback are non-trivial. The current repository and installed provider definitions are the defaults.

## Run-Input Examples

The current main checkout root is resolved automatically; omit an execution-repository path from an ordinary prompt. If
the likely fault later involves another project or repository, add it as an additional code scope and state why.

For an approved remediation re-entry, keep the same artifact root and add only the continuation information that
changed:

```text
Use $ai-engineering-workflows:run.
Work item: <TECHOPS-JIRA-ID-OR-URL>
Playbook: playbooks/techops_issue_remediation.md
Lifecycle: remediation
Execution profile: <PREVIOUS-RUN-PROFILE>
Continuation:
- Run type: Remediation re-entry
- Previous work record, plan, or handoff: /projects/primary-service/.thoughts/<WORK-ITEM-ID>/implementation_plan.md
- New evidence, decision, constraint, or recovery reason: Explicit implementation approval received
- Approval reference: <USER-APPROVAL-MESSAGE-OR-REFERENCE>
```

Do not manually provide completed or required worker lists. The Coordinator derives them from the selected profile and
preserved work record.

## Expected Planning Outcome

The work record is created at:

```text
<execution-repository>/.thoughts/<WORK-ITEM-ID>/work_record.md
```

The workflow records normalized report evidence, reproduction status, the first concrete divergence or its limitation,
ownership, supported diagnosis, confidence, and a regression and validation strategy. It creates
`implementation_plan.md` only after required planning fan-in passes.

## Approved Delivery

Explicit remediation approval starts a new remediation run using the same profile, work record, and implementation plan:

```text
Implement → Code Review → Validate → Handoff
```

The Coordinator continues through all approved in-scope steps. A new approval is needed only when evidence changes the
approved scope or design, or a genuine blocker requires a decision.

## Expected Handoff

Report the symptom, evidence, reproduction status, first-loss point, affected codebase, diagnosis confidence,
implementation-plan status, validation, rollback/monitoring considerations, worker ledger, residual risks, owner, and
next action.
