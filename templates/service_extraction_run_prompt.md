---
title: Service Extraction and Stabilization Run Prompt
version: 0.1
status: Pilot
owner: Engineering
last_updated: 2026-07-31
depends_on:
  - ../contracts/workflow_execution.md
  - ../playbooks/service_extraction.md
---

# Service Extraction and Stabilization Run Prompt

Use this format for every Service Extraction and Stabilization session. Fill
only the scenario fields. The selected playbook, shared contract, and provider
agent configuration define execution behavior.

```text
Run the Service Extraction and Stabilization playbook.

Work item: <JIRA-STORY-ID-OR-URL>
Execution profile: deep
Lifecycle: planning

Playbook:
<PATH-TO>/ai/engineering-workflow-library/playbooks/service_extraction.md

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
- Source: <ABSOLUTE-PATH-OR-UNKNOWN>
- Destination: <ABSOLUTE-PATH-OR-UNKNOWN>

Service extraction context (unverified until reconciled):
- Capability or service: <NAME-OR-UNKNOWN>
- Desired destination boundary: <DESCRIPTION-OR-UNKNOWN>
- Required behavior and acceptance criteria: <DESCRIPTION-OR-UNKNOWN>
- Known contracts, data, events, runtime, deployment, or ownership constraints: <DESCRIPTION-OR-NONE>
- Related tickets, pull requests, or documents: <NONE-OR-REFERENCES>
- Explicit non-goals: <NONE-OR-DESCRIPTION>

Additional run-specific constraints or approvals:
- <NONE-OR-ENTER-CONSTRAINT>

Follow the shared execution contract, selected playbook profile, lifecycle,
provider configuration, and handoff format.
```
