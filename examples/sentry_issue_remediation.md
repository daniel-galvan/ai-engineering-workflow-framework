---
title: Sentry Issue Remediation Example
version: 0.3.2
status: Pilot
owner: Engineering
last_updated: 2026-07-30
depends_on:
  - ../playbooks/sentry_issue_remediation.md
  - ../templates/sentry_issue_run_prompt.md
  - ../templates/implementation_plan.md
  - ../contracts/workflow_execution.md
---

# Sentry Issue Remediation Example

> Example of turning a Sentry issue into an evidence-backed diagnosis and
> approval-gated remediation plan.

## Example Scenario

Sentry reports a production error in one repository, but the fault may exist in another repository, service, or monorepo
component. The workflow records the Sentry event, release mapping or gap, repository topology, code path, proposed fix,
regression test, and validation plan.

## Example Inputs

| Item | Example |
| --- | --- |
| Sentry issue | `<SENTRY-ISSUE-ID-OR-URL>` |
| Execution repository | Local checkout where the workflow starts and stores artifacts |
| Event-origin repository | `<REPORTING-REPOSITORY>` |
| Candidate fault repository | `<REPOSITORY-OR-UNKNOWN>` |
| Candidate component | `<COMPONENT-OR-UNKNOWN>` |
| Downstream or return path | `<PATH-OR-UNKNOWN>` |
| Confirmed decisions and constraints | Source-of-truth rules, scope, or non-goals; authoritative |
| Additional repositories and assets | Relevant local checkouts and evidence folders |
| Supporting artifacts | Payload JSON, logs, screenshots, traces, or reproduction fixtures |

## Run Format

Use the canonical [`templates/sentry_issue_run_prompt.md`](../templates/sentry_issue_run_prompt.md) template. Fill in
the issue, repositories, topology hypothesis, optional artifacts, profile, and lifecycle. Do not copy the playbook
process into the prompt.

For a normal first investigation, use:

```text
Playbook: playbooks/sentry_issue_remediation.md
Canonical run template: templates/sentry_issue_run_prompt.md
Execution profile: standard
Lifecycle: planning
```

Use `deep` when ownership, causality, repository boundaries, concurrency, security, data impact, or deployment
responsibility remains uncertain.

Use the configured Sentry MCP integration. Do not request or use `SENTRY_AUTH_TOKEN` when MCP provides the connection.

Standard planning is bounded and latest-event-first. A different local checkout revision, an unavailable Sentry release
lookup, a high event count, or missing database access is recorded as a limitation when it is not material to the
candidate fix. The workflow does not inspect every occurrence by default. It may use one older representative event or
persisted rows only when the latest event and source evidence cannot answer a material question.

## Expected Work Record and Artifacts

Recover or create:

```text
<execution-repository>/.thoughts/<SENTRY-ISSUE-ID>/work_record.md
```

Create `implementation_plan.md` under the same execution repository only after all required planning workers complete
and the workflow reaches `ready_for_implementation`. The evidence worker owns raw Sentry queries and publishes
normalized evidence. The Solution Architect designs the fix. The Documenter persists the implementation plan and links
it from the work record.

## Planning Follow-up and Remediation Re-entry

Clarifying questions do not change the planning lifecycle. If implementation is approved, start or explicitly record a
new remediation run using the same profile and work record, set `Lifecycle: remediation`, re-read the playbook and
implementation plan, activate the required remediation workers, and complete fan-in before source changes. Do not
replace this re-entry with a generic `implement-plan` workflow.

If the worker graph is interrupted before the selected profile completes, use the canonical run template with
`Interrupted profile recovery`. Reuse completed artifacts, activate the missing required workers, wait for fan-in, and
report the recovered profile status before claiming diagnosis or fix design complete.

## Safety Boundary

Planning makes no source or external-system changes. Do not update Sentry status, modify Jira, or implement code without
explicit approval. The remediation lifecycle executes only the approved implementation plan.

## Expected Handoff

The final handoff should report:

- requested, activated, and executed profile;
- profile status, required-worker activation, and fan-in status;
- verified repository and component scope;
- evidence-backed root cause and residual uncertainty;
- proposed source and regression-test changes;
- validation plan and unavailable or inconclusive checks;
- implementation-plan path and status; and
- next owner and smallest safe next action. The next action names the owner, file or system, required decision or
  action, and completion condition in plain language.
