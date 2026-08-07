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
Execution profile: standard
Lifecycle: planning
The selected execution profile is mandatory; do not silently downgrade it.

Playbook:
<PATH-TO>/ai/engineering-workflow-library/playbooks/sentry_issue_remediation.md

Execution repository (durable artifact root):
<ABSOLUTE-PATH-TO-REPOSITORY-WHERE-THIS-PROMPT-IS-EXECUTED>

Work record:
<EXECUTION-REPOSITORY>/.thoughts/<SENTRY-ISSUE-ID>/work_record.md

Implementation plan (create only when the playbook reaches
`ready_for_implementation`):
<EXECUTION-REPOSITORY>/.thoughts/<SENTRY-ISSUE-ID>/implementation_plan.md

Continuation / re-entry:
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
