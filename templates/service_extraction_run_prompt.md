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

Use this format for every Service Extraction and Stabilization session. For a first run, fill the work item, execution
repository, profile, lifecycle, and scenario fields only. The shared contract and selected playbook own worker
selection, coordination, recovery, and fan-in.

First-use summary:
- Provide the work item, playbook, profile, lifecycle, execution repository, and optional scenario inputs.
- The run initializes or recovers the work record, activates the required workers, and follows the playbook gates.
- Planning is read-only; explicit implementation approval is required before remediation.
- Results are stored under `<execution-repository>/.thoughts/<WORK-ITEM-ID>/`; create the implementation plan only after
  planning fan-in.
- The prompt-preparation step extracts and preserves all supplied context; the user does not need to repeat it in
  canonical fields.
- Put direct user decisions and non-negotiable constraints in the confirmed-input section; workers must not reopen them
  as clarification questions.

```text
Run the Service Extraction and Stabilization playbook.

Work item: <JIRA-STORY-ID-OR-URL>
Playbook: <PATH-TO>/ai-engineering-workflow-framework/playbooks/service_extraction.md
Canonical run template: templates/service_extraction_run_prompt.md

Execution profile: deep
Lifecycle: planning

Execution repository (required; durable artifact root):
<ABSOLUTE-PATH-TO-EXECUTION-REPOSITORY>

Durable artifacts (derived; do not replace these paths):
- Work record: <execution-repository>/.thoughts/<WORK-ITEM-ID>/work_record.md
- Implementation plan: create <execution-repository>/.thoughts/<WORK-ITEM-ID>/implementation_plan.md
  only when the playbook reaches `ready_for_implementation`.

Provider/runtime configuration (optional; omit if unavailable):
<PATH-TO-EXECUTION-REPOSITORY-PROVIDER-CONFIGURATION>

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
- Verify every explicitly named path before reporting its existence or absence;
  inspect hidden entries, regular files, symlinks, and symlink targets.
- The active Coordinator activates the required workers and records their
  envelopes. If delegation is unavailable, stop without claiming profile success.
- Planning is read-only. Remediation reuses planning artifacts, activates the
  delivery graph before edits, and executes the approved plan end-to-end.

Repositories and working directories:
- Source: <ABSOLUTE-PATH-OR-UNKNOWN>
- Destination: <ABSOLUTE-PATH-OR-UNKNOWN>

Confirmed user decisions and constraints (authoritative; do not reopen):
- <NONE-OR-DECISION-OR-CONSTRAINT>

Service extraction context (unverified until reconciled):
- Capability or service: <NAME-OR-UNKNOWN>
- Desired destination boundary: <DESCRIPTION-OR-UNKNOWN>
- Required behavior and acceptance criteria: <DESCRIPTION-OR-UNKNOWN>
- Known contracts, data, events, runtime, deployment, or ownership constraints: <DESCRIPTION-OR-NONE>
- Related tickets, pull requests, or documents: <NONE-OR-REFERENCES>
- Explicit non-goals: <NONE-OR-DESCRIPTION>

Additional supplied context (preserve and classify):
- <NONE-OR-DESCRIPTION-OR-REFERENCE>

Additional run-specific constraints or approvals:
- <NONE-OR-ENTER-CONSTRAINT>

Follow the shared execution contract, selected playbook profile, lifecycle,
provider configuration, and handoff format.
```
