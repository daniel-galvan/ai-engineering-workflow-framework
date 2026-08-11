---
title: Feature Delivery Run Prompt
version: 0.1
status: Pilot
owner: Engineering
last_updated: 2026-08-04
depends_on:
  - ../contracts/workflow_execution.md
  - ../playbooks/feature_delivery.md
---

# Feature Delivery Run Prompt

Use this format for every Feature Delivery session. For a first run, fill the
work item, execution repository, profile, lifecycle, and scenario fields only.
The shared contract and selected playbook own worker selection, coordination,
recovery, and fan-in.

```text
Run the Feature Delivery playbook.

Work item: <JIRA-TICKET-ID-OR-URL>
Execution profile: standard
Lifecycle: planning

Playbook:
<PATH-TO>/ai-engineering-workflow-framework/playbooks/feature_delivery.md

Execution repository (required; durable artifact root):
<ABSOLUTE-PATH-TO-TARGET-REPOSITORY>

Durable artifacts (derived; do not replace these paths):
- Work record: <execution-repository>/.thoughts/<WORK-ITEM-ID>/work_record.md
- Implementation plan: create <execution-repository>/.thoughts/<WORK-ITEM-ID>/implementation_plan.md
  only when the playbook reaches `ready_for_implementation`.

Provider/runtime configuration (optional; omit if unavailable):
<PATH-TO-TARGET-REPOSITORY-PROVIDER-CONFIGURATION>

Coordination:
- The current session is the Coordinator.
- Use a configured Orchestrator agent only when the runtime supports nested
  delegation. Otherwise, the current session activates workers and completes
  fan-in directly.

Continuation (omit this entire section for a new investigation):
- Run type: Planning follow-up / Interrupted profile recovery / Remediation re-entry
- Previous work record, plan, or handoff: <ABSOLUTE-PATH-OR-REFERENCE>
- New evidence, decision, constraint, or recovery reason: <DESCRIPTION>
- Approval reference: <REQUIRED-FOR-REMEDIATION-OR-NONE>

Run invariants:
- The shared contract and selected playbook own lifecycle, worker activation,
  recovery, fan-in, and handoff behavior; do not redefine them here.
- The active Coordinator activates the required workers and records their
  envelopes. If delegation is unavailable, stop without claiming profile success.
- Planning is read-only. Remediation reuses planning artifacts, activates the
  delivery graph before edits, and executes the approved plan end-to-end.

Additional repositories and working directories (optional; the execution
repository is already declared):
- <REPOSITORY-OR-DIRECTORY-OR-NONE>

Known Jira context (unverified until recovered):
- Immediate parent: <UNKNOWN-OR-URL>
- Ancestor Story, Epic, or Initiative: <UNKNOWN-OR-URLS>
- Relevant siblings or linked work: <NONE-OR-URLS>
- Related documents, pull requests, or decisions: <NONE-OR-REFERENCES>

Feature context and constraints (unverified until reconciled):
- Desired outcome: <DESCRIPTION-OR-UNKNOWN>
- Expected behavior or acceptance criteria: <DESCRIPTION-OR-UNKNOWN>
- Suspected repository, component, owner, or rollout: <HINT-OR-NONE>
- Explicit non-goals: <NONE-OR-DESCRIPTION>
- Constraints, dependencies, or release timing: <NONE-OR-DESCRIPTION>

Additional run-specific constraints or approvals:
- <NONE-OR-ENTER-CONSTRAINT>

Follow the shared execution contract, selected playbook profile, lifecycle,
provider configuration, and handoff format.
```
