---
title: Technical Spike Run Prompt
version: 0.1.6
status: Pilot
owner: Engineering
last_updated: 2026-09-07
depends_on:
  - ../contracts/workflow_execution.md
  - ../playbooks/technical_spike.md
---

# Technical Spike Run Prompt

Fill only the run-specific fields. The shared contract and selected playbook own execution behavior. Prompt preparation
must preserve all supplied context and place explicit decisions in the authoritative confirmed-input section. Populate
the prompt only from the current user request, references explicitly named for this run, and facts retrieved from those
references. Do not search for or add memory-derived facts, related tickets, past plans, historical work records, or
`.thoughts` paths unless the user explicitly asks to include them. Use `None` for unused optional fields.

```text
Run the Technical Spike playbook.

Work item: <JIRA-TICKET-ID-OR-URL-OR-STABLE-ID>
Playbook: <PATH-TO>/ai-engineering-workflow-framework/playbooks/technical_spike.md
Framework revision (required for evaluation runs): <FULL-GIT-COMMIT>
Framework worktree status: clean
Execution profile: standard
Lifecycle: planning
Requested outcome: technical_answer
Spike objective: execute_spike

Use `technical_answer + execute_spike` to investigate a bounded technical question. Use
`spike_assessment + review_spike` to assess an existing Spike report or document. A request for
`implementation_plan` belongs to Feature Delivery and conflicts with this playbook. Record Playbook Selection
`Primary goal` exactly as `Execute technical spike` or `Review technical spike`.

Execution repository (required; durable artifact root):
<ABSOLUTE-PATH-TO-EXECUTION-REPOSITORY>

Provider/runtime configuration (optional execution-repository runtime view; use `Not provided` when absent):
<PATH-TO-EXECUTION-REPOSITORY-PROVIDER-CONFIGURATION-OR-Not-provided>

Continuation (omit this entire section for a new investigation):
- Run type: Spike follow-up / Interrupted profile recovery
- Previous work record or Spike report: <ABSOLUTE-PATH-OR-REFERENCE>
- New evidence, decision, constraint, or recovery reason: <DESCRIPTION>

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
  authority `Explicit user outcome`, and classification `requested outcome`. Never infer it from `Spike objective`.
- The requested profile and planning lifecycle are mandatory. The Delivery Activation Barrier is not applicable:
  Technical Spike never enters remediation or changes production source or external systems.
- The Coordinator must activate the required workers without substituting for them and report actual worker outcomes,
  fan-in, and runtime closure. Never claim successful execution when the required graph is incomplete.
- Workers receive prepared role envelopes and typed stage assignments. Do not make them reread the complete framework
  contract, run skill, prompt template, or examples.

Spike question and bounds:
- Primary question: <ONE-DECISION-RELEVANT-TECHNICAL-QUESTION>
- Assessment criteria or control domains: <NONE-OR-LIST-OF-CRITERIA>
- Timebox or evidence budget: <REQUIRED-END-TO-END-DURATION; PREPARE WITH --STARTED-AT AND --TIMEBOX-MINUTES>
- Success criterion: <WHAT-EVIDENCE-WOULD-ANSWER-OR-MATERIALLY-NARROW-THE-QUESTION>
- Explicit non-goals: <NONE-OR-DESCRIPTION>

Prompt-completeness gate: Primary question, timebox or evidence budget, success criterion, Requested outcome, and Spike
objective are mandatory populated values. Pass the question and criterion to preparation as `--primary-question` and
`--success-criterion`. Do not invoke the launcher, create a temporary manifest, query Jira, or read repositories until
all five values are present and non-placeholder.

Review target (required for `review_spike`; otherwise `None`):
- Existing Spike report or document: <URL-OR-ABSOLUTE-PATH-OR-NONE>
- Claimed conclusion or recommendation: <DESCRIPTION-OR-UNKNOWN>

Comparison reference (optional for `execute_spike`; otherwise `None`):
- Existing Spike report or document: <URL-OR-ABSOLUTE-PATH-OR-NONE>
- Comparison rule: Establish findings and a recommendation independently, then record agreements, contradictions,
  or omissions. Never use the reference as the answer or as the investigation's source of truth.

Additional repositories and working directories (optional; the execution repository is already declared):
- Path: <REPOSITORY-OR-DIRECTORY-OR-NONE>
  Intended ref: <USER-SELECTED-BRANCH-REVISION-OR-UNKNOWN>

Confirmed user decisions and constraints (authoritative; do not reopen):
- <NONE-OR-DECISION-OR-CONSTRAINT>

Known Jira context (unverified until recovered):
- Immediate parent: <UNKNOWN-OR-URL>
- Ancestor Story, Epic, or Initiative: <UNKNOWN-OR-URLS>
- Relevant siblings or linked work: <NONE-OR-URLS>
- Related documents, pull requests, or decisions: <NONE-OR-REFERENCES>

Evidence and experiment hints (unverified until reconciled):
- Suspected repositories, components, services, or owners: <HINT-OR-NONE>
- Candidate checks, experiments, logs, metrics, or test commands: <HINT-OR-NONE>
- Constraints, dependencies, privacy boundaries, or environment limits: <NONE-OR-DESCRIPTION>

Optional supporting artifacts:
- <NONE-OR-ABSOLUTE-PATHS>

Additional supplied context (preserve and classify):
- <NONE-OR-DESCRIPTION-OR-REFERENCE>

Additional run-specific constraints or approvals:
- <NONE-OR-ENTER-CONSTRAINT>

Follow the selected playbook and its required dependencies.

At handoff, use the contract's canonical human-readable template. Do not include Run Metrics or Worker Timing unless
this prompt explicitly declares an evaluation or benchmark run. Reserve `plan_only` for a run that produced a usable
implementation plan; Technical Spike never does. Preserve distinct `Workflow outcome` and `Engineering outcome`
fields. Set `Implementation plan` to `Not created; Technical Spike produces spike_report.md` and link the completed
`spike_report.md`.

Make `spike_report.md` self-contained with compact direct repository/document evidence. Final response must name the
disposition, strongest evidence, unresolved decisions, exact next workflow, measured budget status, and link
`spike_report.md` plus terminal `work_record.md`. On finalization failure, link `finalization_failure.json` instead of
claiming terminal validation passed.

For `execute_spike`, keep `Review target` as `None`. An existing Spike is a comparison reference only and may be read
after independent findings and a recommendation are established. For `review_spike`, the existing Spike is the review
target and `Comparison reference` is `None`.

For `execute_spike`, choose exactly one `Workflow result`: `Question answered`, `Partially answered`, or `Inconclusive`.
For `review_spike`, choose exactly one: `Accepted`, `Changes required`, or `Inconclusive`.
```
