---
title: Feature Delivery Run Prompt
version: 0.3.2
status: Pilot
owner: Engineering
last_updated: 2026-08-21
depends_on:
  - ../contracts/workflow_execution.md
  - ../playbooks/feature_delivery.md
---

# Feature Delivery Run Prompt

Fill only the run-specific fields. The shared contract and selected playbook own execution behavior. Prompt preparation
must preserve all supplied context and place explicit decisions in the authoritative confirmed-input section.
Populate the prompt only from the current user request, references explicitly named for this run, and facts retrieved
from those references. Do not search for or add memory-derived facts, related tickets, past plans, historical work
records, or `.thoughts` paths unless the user explicitly asks to include them. Use `None` for unused optional fields.

```text
Run the Feature Delivery playbook.

Work item: <JIRA-TICKET-ID-OR-URL>
Playbook: <PATH-TO>/ai-engineering-workflow-framework/playbooks/feature_delivery.md

Execution profile: standard
Lifecycle: planning

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

Additional repositories and working directories (optional; the execution
repository is already declared):
- <REPOSITORY-OR-DIRECTORY-OR-NONE>

Confirmed user decisions and constraints (authoritative; do not reopen):
- <NONE-OR-DECISION-OR-CONSTRAINT>

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

Optional supporting artifacts:
- <NONE-OR-ABSOLUTE-PATHS>

Additional supplied context (preserve and classify):
- <NONE-OR-DESCRIPTION-OR-REFERENCE>

Additional run-specific constraints or approvals:
- <NONE-OR-ENTER-CONSTRAINT>

Follow the selected playbook and its required dependencies.

At handoff, include the contract's compact `Run metrics:` and `Worker timing:` lines in the final answer; do not replace
them with a work-record link or report coordinator-observed values as `Unknown`. Include coordination errors and
handoff revisions, artifact bytes after the last correction, and metrics validity. Reserve `plan_only` for a run that produced
a usable implementation plan; otherwise use `partially_solved` for useful incomplete planning.
```
