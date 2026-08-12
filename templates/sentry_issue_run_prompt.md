---
title: Sentry Issue Remediation Run Prompt
version: 0.1
status: Pilot
owner: Engineering
last_updated: 2026-07-30
depends_on:
  - ../contracts/workflow_execution.md
---

# Sentry Issue Remediation Run Prompt

Use this format for every Sentry Issue Remediation session. Fill in the
scenario fields; do not copy the playbook process into the prompt. Update this
template when the required run inputs or format change.

```text
Run the Sentry Issue Remediation playbook.

Issue: <SENTRY-ISSUE-ID-OR-URL>
Playbook: <PATH-TO>/ai-engineering-workflow-framework/playbooks/sentry_issue_remediation.md
Canonical run template: templates/sentry_issue_run_prompt.md

Execution profile: standard
Lifecycle: planning
The selected execution profile is mandatory; do not silently downgrade it.

Execution repository (required; durable artifact root):
<ABSOLUTE-PATH-TO-EXECUTION-REPOSITORY>

Durable artifacts (derived; do not replace these paths):
- Work record: <execution-repository>/.thoughts/<SENTRY-ISSUE-ID>/work_record.md
- Implementation plan: create <execution-repository>/.thoughts/<SENTRY-ISSUE-ID>/implementation_plan.md
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
- The active Coordinator activates the required workers and records their
  envelopes. If delegation is unavailable, stop without claiming profile success.
- Planning is read-only. Remediation reuses planning artifacts, activates the
  delivery graph before edits, and executes the approved plan end-to-end.

Additional repositories and working directories (optional; the execution
repository is already declared):
- <REPOSITORY-OR-DIRECTORY-OR-NONE>

Initial topology hypothesis:
- Event-origin repository: <REPOSITORY-OR-UNKNOWN>
- Candidate fault repository: <REPOSITORY-OR-UNKNOWN>
- Candidate fault component: <COMPONENT-OR-UNKNOWN>
- Downstream or return path: <PATH-OR-UNKNOWN>

Reporter context and investigation hints (optional; unverified until reconciled):
- Observed symptom: <SYMPTOM-OR-NONE>
- Expected behavior: <EXPECTED-BEHAVIOR-OR-UNKNOWN>
- Suspected flow, owner, file, or component: <HINT-OR-NONE>
- Reproduction clues or known edge cases: <HINT-OR-NONE>
- Known exclusions or related links: <HINT-OR-NONE>

Optional supporting artifacts:
- <NONE-OR-ABSOLUTE-PATH>

Integration:
- Use the playbook's configured Sentry MCP integration.
- Do not request or use SENTRY_AUTH_TOKEN.

Additional run-specific constraints or approvals:
- For `planning`: no source or external-system changes.
- For `remediation`: execute only the approved implementation plan after the
  explicit approval gate and required-worker fan-in; do not update external
  systems without separate approval.
- <NONE-OR-ENTER-CONSTRAINT>

Follow the shared execution contract, selected playbook profile, lifecycle,
provider configuration, and handoff format.

At handoff, report requested/executed profile, profile status,
required-worker activation, fan-in status, and runtime-closure status.
```
