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

Use this format for every Feature Delivery session. Fill only the scenario
fields. The selected playbook, shared contract, and provider agent
configuration define execution behavior.

```text
Run the Feature Delivery playbook.

Work item: <JIRA-TICKET-ID-OR-URL>
Execution profile: standard
Lifecycle: planning

Playbook:
<PATH-TO>/ai/engineering-workflow-library/playbooks/feature_delivery.md

Execution repository (durable artifact root):
<ABSOLUTE-PATH-TO-REPOSITORY-WHERE-THIS-PROMPT-IS-EXECUTED>

Work record:
<EXECUTION-REPOSITORY>/.thoughts/<WORK-ITEM-ID>/work_record.md

Implementation plan (create only at `ready_for_implementation`):
<EXECUTION-REPOSITORY>/.thoughts/<WORK-ITEM-ID>/implementation_plan.md

Continuation:
- Run type: New investigation / Planning follow-up / Interrupted profile recovery / Remediation re-entry
- Previous run or handoff: <NONE-OR-REFERENCE>
- Existing artifacts to reuse: <NONE-OR-ABSOLUTE-PATHS>
- Completed workers: <NONE-OR-WORKER-LIST>
- Required workers for this continuation: <NONE-OR-WORKER-LIST>
- Recovery reason: <NONE-OR-REASON>
- Approval reference: <NONE-OR-REFERENCE>

Provider/runtime configuration:
<OPTIONAL-PROVIDER-AGENT-CONFIGURATION-PATH>

Coordinator:
<PROVIDER-ORCHESTRATOR-AGENT-OR-CURRENT-SESSION>

Run invariants:
- The shared contract and selected playbook own lifecycle, worker activation,
  recovery, fan-in, and handoff behavior; do not redefine them here.
- The active Coordinator activates the required workers and records their
  envelopes. If delegation is unavailable, stop without claiming profile success.
- Planning is read-only. Remediation reuses planning artifacts, activates the
  delivery graph before edits, and executes the approved plan end-to-end.

Repositories and working directories:
- <REPOSITORY-OR-DIRECTORY-1>
- <REPOSITORY-OR-DIRECTORY-2>

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
