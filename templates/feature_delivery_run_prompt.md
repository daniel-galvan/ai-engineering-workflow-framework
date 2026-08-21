---
title: Feature Delivery Run Prompt
version: 0.2.0
status: Pilot
owner: Engineering
last_updated: 2026-08-19
depends_on:
  - ../contracts/workflow_execution.md
  - ../playbooks/feature_delivery.md
---

# Feature Delivery Run Prompt

Use this format for every Feature Delivery session. For a first run, fill the work item, execution repository, profile,
lifecycle, and scenario fields only. The shared contract and selected playbook own worker selection, coordination,
recovery, and fan-in.

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
- For a feature that moves an existing capability into an independently operated destination, provide the
  source-to-destination scenario fields and select `deep`.

```text
Run the Feature Delivery playbook.

Work item: <JIRA-TICKET-ID-OR-URL>
Playbook: <PATH-TO>/ai-engineering-workflow-framework/playbooks/feature_delivery.md
Canonical run template: templates/feature_delivery_run_prompt.md

Execution profile: standard
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
- The current session is Coordinator-only and must not edit source or substitute
  for the Implementer, Reviewer, or Tester. Before edits, record the Delivery
  Activation Barrier; if it cannot pass, stop without changing source.
- Do not report remediation complete until the Implementer, Reviewer, Tester,
  and Documenter return the required terminal results and fan-in and runtime
  closure are recorded.

Additional repositories and working directories (optional; the execution
repository is already declared):
- <REPOSITORY-OR-DIRECTORY-OR-NONE>

Source-to-destination feature scenario (omit for a normal feature; requires `deep`):
- Source: <ABSOLUTE-PATH-OR-UNKNOWN>
- Destination: <ABSOLUTE-PATH-OR-UNKNOWN>
- Capability: <NAME-OR-UNKNOWN>
- Desired destination seam: <DESCRIPTION-OR-UNKNOWN>
- Known contracts, data, events, runtime, deployment, or ownership constraints: <DESCRIPTION-OR-NONE>

Use `Unknown` only when unavailable. Missing source or destination information prevents implementation readiness, but
does not prevent bounded planning discovery.

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

Follow the shared execution contract, selected playbook profile, lifecycle,
provider configuration, and handoff format.
```
