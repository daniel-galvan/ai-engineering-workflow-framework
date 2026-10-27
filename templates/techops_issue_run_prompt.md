---
title: TechOps Issue Remediation Run Prompt
version: 0.5.32
status: Pilot
owner: Engineering
last_updated: 2026-10-26
depends_on:
  - ../contracts/workflow_execution.md
  - ../playbooks/techops_issue_remediation.md
---

# TechOps Issue Remediation Run Prompt

## Minimal launch

For a new TechOps planning run, send this to Codex:

```text
$ai-engineering-workflows:run Run the TechOps Issue Remediation playbook.

Work item: <TECHOPS-JIRA-ID-OR-URL>
Playbook: playbooks/techops_issue_remediation.md
```

That is enough to start. Omit `Execution profile` and `Lifecycle` to use the TechOps defaults: `standard` and
`planning`. The current task's main Git repository is the execution repository and artifact root unless the user names a
different repository. The installed package supplies the framework and provider definitions.

The active run skill and shared contract own preflight, source-access gates, input-manifest creation, worker selection,
artifact placement, validation, and handoff. Do not copy framework commands, worker lists, internal paths, or evaluation
metadata into an ordinary run prompt.

## Optional user context

Add only information the user actually knows and considers relevant. These fields are optional; omit them when they do
not apply.

- `Execution profile: deep` when the investigation crosses systems, ownership is unclear, or the failure is
  intermittent.
- `Lifecycle: remediation` only for an approved remediation re-entry with its existing plan and approval.
- `Execution repository: <absolute path>` only when the current repository is not the source repository.
- Unanswered material user decisions carried from the current request, if any.
- Code-scope or repository hints, confirmed decisions and constraints, unanswered material user decisions, reported and
  expected behavior, reproduction details, supporting artifacts, or additional context.

Unanswered material user decisions carried from the current request are asked and resolved in this run when needed. Do
not invent unknown details or ask the user to prepare framework-generated manifests or worker instructions.

## Evaluation-only fields

Use this extension only when the user explicitly declares a versioned evaluation. Normal runs do not need these fields.

```text
Evaluation run ID: <UNIQUE-ID>
Framework revision (required for evaluation runs): <FULL-GIT-COMMIT>
Framework worktree status: clean
Execution repository: <ABSOLUTE-PATH>
Provider/runtime configuration (optional execution-repository runtime view): <REPRODUCIBLE-SOURCE>
Execution profile: standard
Lifecycle: planning
Confirmed user decisions and constraints (authoritative; do not reopen): <DECISIONS-OR-NONE>
Intended ref: <USER-SELECTED-REF-OR-UNKNOWN>
Workflow outcome: <OUTCOME>
Engineering outcome: <OUTCOME>
Additional supplied context (preserve and classify): <CONTEXT-OR-NONE>
```

For a versioned evaluation, compare the populated prompt with this template, record `prompt_conformance` and the
template revision, and stop with `run_prompt_nonconformant` if a required evaluation field is missing or altered.
