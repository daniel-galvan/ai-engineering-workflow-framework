---
title: TechOps Issue Remediation Run Prompt
version: 0.1
status: Pilot
owner: Engineering
last_updated: 2026-08-10
depends_on:
  - ../contracts/workflow_execution.md
  - ../playbooks/techops_issue_remediation.md
---

# TechOps Issue Remediation Run Prompt

Use this format for every TechOps Issue Remediation session. For a first run, fill the work item, execution repository,
profile, lifecycle, and scenario evidence only. The shared contract and selected playbook own worker selection,
coordination, recovery, and fan-in.

First-use summary:
- Provide the work item, playbook, profile, lifecycle, execution repository, and optional scenario inputs.
- The run initializes or recovers the work record, activates the required workers, and follows the playbook gates.
- Planning is read-only; explicit implementation approval is required before remediation.
- Results are stored under `<execution-repository>/.thoughts/<WORK-ITEM-ID>/`; create the implementation plan only after
  planning fan-in.
- The prompt-preparation step extracts and preserves all supplied context; the
  user does not need to repeat it in canonical fields.
- Put direct user decisions and non-negotiable constraints in the confirmed-input section; workers must not reopen them
  as clarification questions.

```text
Run the TechOps Issue Remediation playbook.

Work item: <TECHOPS-JIRA-ID-OR-URL>
Playbook: <PATH-TO>/ai-engineering-workflow-framework/playbooks/techops_issue_remediation.md
Canonical run template: templates/techops_issue_run_prompt.md

Execution profile: standard
Lifecycle: planning
The selected execution profile is mandatory; do not silently downgrade it.

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
- The active Coordinator activates required workers, collects result envelopes,
  and reports blocked delegation without claiming profile success.
- Planning is read-only. Remediation reuses planning artifacts, activates the
  delivery graph before edits, and executes the approved plan end-to-end.

Confirmed user decisions and constraints (authoritative; do not reopen):
- <NONE-OR-DECISION-OR-CONSTRAINT>

Reported issue context (unverified until reconciled):
- Report source: Zendesk / Help Desk / Operations / Other
- Reported behavior and impact: <DESCRIPTION-OR-UNKNOWN>
- Expected behavior: <DESCRIPTION-OR-UNKNOWN>
- Reproduction steps, timing, inputs, and frequency: <DESCRIPTION-OR-UNKNOWN>
- Suspected system, repository, component, owner, or first-loss point: <HINT-OR-NONE>

Supporting evidence and artifacts:
- Attachments, screenshots, recordings, transcripts, JSON, logs, traces, or exports: <NONE-OR-ABSOLUTE-PATHS>
- Related Jira issues, incidents, dashboards, runbooks, pull requests, or prior fixes: <NONE-OR-REFERENCES>
- Redaction, privacy, or access constraints: <NONE-OR-DESCRIPTION>

Additional supplied context (preserve and classify):
- <NONE-OR-DESCRIPTION-OR-REFERENCE>

Additional repositories and working directories (optional; the execution
repository is already declared):
- <REPOSITORY-OR-DIRECTORY-OR-NONE>

Additional run-specific constraints or approvals:
- <NONE-OR-ENTER-CONSTRAINT>

Follow the shared execution contract, selected playbook profile, lifecycle,
provider configuration, and handoff format.
```
