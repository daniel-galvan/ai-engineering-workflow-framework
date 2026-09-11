---
title: Feature Delivery Run Prompt
version: 0.5.1
status: Pilot
owner: Engineering
last_updated: 2026-09-07
depends_on:
  - ../contracts/workflow_execution.md
  - ../playbooks/feature_delivery.md
  - ../templates/asset_manifest.json
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
Framework revision (required for evaluation runs): <FULL-GIT-COMMIT>
Framework worktree status: clean
Execution profile: standard
Lifecycle: planning
Requested outcome: implementation_plan
Planning objective: implementation_planning

Use `implementation_plan + implementation_planning` to design a feature. Use
`specification_assessment + specification_assessment` to judge an existing Spike, proposal, or specification. For
`specification_assessment`, record Playbook Selection `Primary goal` exactly as `Specification assessment`; do not
infer readiness from the ability to list future work.

Execution repository (required; durable artifact root):
<ABSOLUTE-PATH-TO-EXECUTION-REPOSITORY>

Provider/runtime configuration (optional execution-repository runtime view; use `Not provided` when absent):
<PATH-TO-EXECUTION-REPOSITORY-PROVIDER-CONFIGURATION-OR-Not-provided>

Continuation (omit this entire section for a new investigation):
- Run type: Planning follow-up / Interrupted profile recovery / Remediation re-entry
- Previous work record, plan, or handoff: <ABSOLUTE-PATH-OR-REFERENCE>
- New evidence, decision, constraint, or recovery reason: <DESCRIPTION>
- Approval reference: <REQUIRED-FOR-REMEDIATION-OR-NONE>

Runtime bootstrap:
- For a versioned evaluation, compare this populated prompt with the canonical template. Record `prompt_conformance` and
  stop with `run_prompt_nonconformant` when a required field is missing or altered.
- Before acting, read the selected playbook plus `contracts/workflow_execution.md` and `contracts/claims.md` from the
  same framework checkout. Load another referenced framework document only when the active stage or worker needs it;
  templates and examples are not runtime instructions.
- The shared contract and selected playbook own lifecycle, worker activation, recovery, fan-in, and handoff behavior.
- Preserve all supplied context. Current explicit user decisions and constraints are authoritative and must not be
  reopened or overridden by historical conclusions.
- Compare the requested outcome with the selected objective before preparation. Stop with `run_goal_conflict` when
  they disagree; do not drop either instruction or silently prefer the later field.
- Copy the explicit `Requested outcome:` line into input-manifest row `RUN-GOAL-001` with source `Current user request`,
  authority `Explicit user outcome`, and classification `requested outcome`. Never infer it from `Planning objective`.
- The requested profile and lifecycle are mandatory. Planning is read-only; remediation requires explicit approval and
  a passed Delivery Activation Barrier before edits.
- The Coordinator must activate the required workers without substituting for them and report actual worker outcomes,
  fan-in, and runtime closure. Never claim successful execution when the required graph is incomplete.
- Before activating downstream planning workers, `feature-context` must create `asset_manifest.json` from a complete
  Jira attachment/history read and every declared asset source. A Jira description or attachment filename is not an
  asset review.
- Feature Delivery requires the explicit current-run input manifest; a generated-minimum manifest cannot establish the
  complete set of additional asset sources.

Additional repositories and working directories (optional; the execution
repository is already declared):
- Path: <REPOSITORY-OR-DIRECTORY-OR-NONE>
  Intended ref: <USER-SELECTED-BRANCH-REVISION-OR-UNKNOWN>

Additional asset sources (optional; every entry is inventoried, not silently ignored):
- Source ID: <OPTIONAL-ID>
  Path or URL: <ABSOLUTE-FILE-OR-FOLDER-PATH-OR-URL>
  Intended use: <DESCRIPTION>
  Corresponding input row: `Asset source: true`

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

Optional supporting artifacts (each file or folder is an asset source and must be inventoried):
- <NONE-OR-ABSOLUTE-PATHS>

For every listed artifact, add a corresponding current-run input row with `Asset source: true`; do not hide an asset
source in free-form context.

Additional supplied context (preserve and classify):
- <NONE-OR-DESCRIPTION-OR-REFERENCE>

Additional run-specific constraints or approvals:
- <NONE-OR-ENTER-CONSTRAINT>

Follow the selected playbook and its required dependencies.

Asset gate:
- Enumerate the complete Jira attachment inventory, including an explicit empty/unavailable result.
- Recursively enumerate every declared folder, including hidden entries and symlinks; enumerate every declared file or
  URL individually.
- Review every available asset with the appropriate method. Images and screenshots require visual inspection or
  rendered reading, not metadata-only review.
- Record source IDs, asset IDs, locators, availability, observations, review status, relevance, disposition, and
  evidence references in `asset_manifest.json`.
- Do not create `implementation_plan.md` or report `ready_for_implementation` until the asset manifest status is
  `passed`; unresolved retrieval or review becomes `awaiting_input`.

At handoff, use the contract's canonical human-readable template. Do not include Run Metrics or Worker Timing unless
this prompt explicitly declares an evaluation or benchmark run. Reserve `plan_only` for a run that produced a usable
implementation plan; otherwise use `partially_solved` for useful incomplete planning. Preserve distinct
`Workflow outcome` and `Engineering outcome` fields.

For `specification_assessment`, choose exactly one `Workflow result`:
- `Ready for implementation`
- `Ready with explicit follow-ups`
- `Not ready for implementation`

Map the first two to `ready_for_implementation`; map the last to `awaiting_input` with
`implementation_plan_action: omit` and a Clarification Brief. A follow-up is non-blocking only when it cannot materially
change scope, ownership, architecture, security or privacy controls, acceptance criteria, or validation strategy.
```
