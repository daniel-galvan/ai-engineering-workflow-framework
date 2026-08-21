---
title: TechOps Issue Remediation Run Prompt
version: 0.3.0
status: Pilot
owner: Engineering
last_updated: 2026-08-19
depends_on:
  - ../contracts/workflow_execution.md
  - ../playbooks/techops_issue_remediation.md
---

# TechOps Issue Remediation Run Prompt

Fill only the run-specific fields. The shared contract and selected playbook own execution behavior. Prompt preparation
must preserve all supplied context and place explicit decisions in the authoritative confirmed-input section.

```text
Run the TechOps Issue Remediation playbook.

Work item: <TECHOPS-JIRA-ID-OR-URL>
Playbook: <PATH-TO>/ai-engineering-workflow-framework/playbooks/techops_issue_remediation.md

Execution profile: standard
Lifecycle: planning
The selected execution profile is mandatory; do not silently downgrade it.

Execution repository (required; durable artifact root):
<ABSOLUTE-PATH-TO-EXECUTION-REPOSITORY>

Provider/runtime configuration (optional; omit if unavailable):
<PATH-TO-EXECUTION-REPOSITORY-PROVIDER-CONFIGURATION>

Continuation (omit this entire section for a new investigation):
- Run type: Planning follow-up / Interrupted profile recovery / Remediation re-entry
- Previous work record, plan, or handoff: <ABSOLUTE-PATH-OR-REFERENCE>
- New evidence, decision, constraint, or recovery reason: <DESCRIPTION>
- Approval reference: <REQUIRED-FOR-REMEDIATION-OR-NONE>

Runtime bootstrap:
- Before acting, read the selected playbook plus `contracts/workflow_execution.md` and `contracts/claims.md` from the
  same framework checkout. Load another referenced framework document only when the active stage or worker needs it;
  templates and examples are not runtime instructions.
- The shared contract and selected playbook own lifecycle, worker activation, recovery, fan-in, and handoff behavior.
- Preserve all supplied context. Current explicit user decisions and constraints are authoritative and must not be
  reopened or overridden by historical conclusions.
- The requested profile and lifecycle are mandatory. Planning is read-only; remediation requires explicit approval and
  a passed Delivery Activation Barrier before edits.
- The Coordinator must activate the required workers without substituting for them and report actual worker outcomes,
  fan-in, and runtime closure. Never claim successful execution when the required graph is incomplete.

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

Follow the selected playbook and its required dependencies.
```
