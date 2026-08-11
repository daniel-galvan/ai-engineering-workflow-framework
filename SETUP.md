---
title: AI-assisted Software Engineering Workflow Framework Setup
version: 0.1
status: Pilot
owner: Engineering
last_updated: 2026-08-11
---

# Setup

This guide prepares the framework for local use. The framework is the source
of truth; a target repository is where the work is investigated and where the
durable `.thoughts/<WORK-ITEM-ID>/` record is created.

## Clone the framework

```bash
git clone https://github.com/daniel-galvan/ai-engineering-workflow-framework.git
cd ai-engineering-workflow-framework
```

Do not run engineering work from the framework checkout unless the framework
itself is the target. Run the workflow in the repository being investigated,
or provide that repository's absolute path in the run prompt.

## Prepare a target repository

Choose the target repository before creating the prompt. For a monorepo, use
the Git checkout root as the execution repository and list the relevant
component paths as additional working directories.

The execution repository determines the durable artifact location:

```text
<target-repository>/.thoughts/<WORK-ITEM-ID>/work_record.md
```

Additional repositories, evidence folders, screenshots, logs, and payloads are
inputs to the run; they are not replacements for the execution repository.

## Codex agent setup

Codex users may expose the framework's provider agents in the target
repository. From the framework checkout, use explicit paths:

```bash
FRAMEWORK_DIR="/absolute/path/to/ai-engineering-workflow-framework"
TARGET_REPO="/absolute/path/to/target-repository"

mkdir -p "$TARGET_REPO/.codex/agents"
for agent_file in "$FRAMEWORK_DIR/providers/codex/agents"/*.toml; do
  agent_name="$(basename "$agent_file")"
  ln -s "$agent_file" "$TARGET_REPO/.codex/agents/$agent_name"
done
```

The symlinks are a local runtime view, not a second source of truth. Keep the
framework agent files in the framework repository. If the target repository
already has `.codex/agents/`, inspect existing entries before adding links.

The links are useful because they:

- let Codex discover the provider-specific workers from the target-repository
  session;
- keep one authoritative copy of each agent definition in the framework;
- make agent policy updates available to target repositories without copying
  or manually synchronizing files; and
- keep provider configuration local to the developer's machine rather than
  adding runtime-specific files to the target repository's source history.

The links do not grant permissions, create delegation capability, or force a
worker to run. The playbook and runtime still determine whether a worker is
required, available, activated, and completed.

Read [providers/codex.md](providers/codex.md) and the
[Codex model and effort policy](providers/codex/model_effort_policy.md) for
the current provider mapping. If the provider runtime cannot use nested
delegation, the active Codex session remains the Coordinator and must complete
worker fan-in and runtime closure itself.

## Create and run a prompt

Start the Codex session from the target repository, then copy the matching
canonical template from the framework checkout into the session prompt. The
target-repository session does not automatically know where the framework
checkout is, so use absolute paths when asking it to prepare a prompt.

These terms have specific meanings:

| Term | Meaning | Example |
| --- | --- | --- |
| Framework checkout | Local clone of this repository; source of the guides, playbooks, roles, skills, contracts, and templates | `/absolute/path/to/ai-engineering-workflow-framework` |
| Target/execution repository | Code checkout where the session starts and where `.thoughts/<WORK-ITEM-ID>/` is created; usually the repository expected to contain the fix | `/absolute/path/to/target-repository` |
| Additional repository | Another checkout needed for evidence or cross-repository analysis; it does not own the work record for this run | `/absolute/path/to/additional-repository` |
| Work item | The stable identifier or URL for the thing being worked on | `TECHOPS-12345`, `PROJ-123`, `SENTRY-ISSUE-123`, or a Jira/Sentry URL |
| Playbook | The scenario workflow selected from [PLAYBOOK_CATALOG.md](PLAYBOOK_CATALOG.md) | `TechOps Issue Remediation` |
| Canonical run template | The matching file under the framework checkout's `templates/` directory | `templates/techops_issue_run_prompt.md` |

For a first run, the target repository is normally also the execution
repository. If the likely fault is in another checkout, keep the session and
work record in the chosen execution repository and list the other checkout as
an additional repository. Do not use the framework checkout or an evidence
folder as the execution repository just because it contains the playbook or
attachments.

For a new run, fill only:

- work item or issue URL;
- execution profile and lifecycle;
- execution repository;
- selected playbook and its canonical template path;
- playbook-specific context and evidence; and
- additional repositories or constraints when applicable.

Omit the continuation section for a new run. The current session is the
Coordinator by default, so there is normally no Coordinator field to fill in.
Use the target repository's `.codex/agents/` path only when it has been
installed and verified.

Start with `planning` for investigation, diagnosis, design, and a proposed
implementation plan. Use `remediation` only after the plan exists and explicit
implementation approval has been given.

## Ask Codex to prepare the prompt

From a session started in the target repository, give Codex the framework
checkout path, target/execution repository path, work item, selected playbook,
and canonical template path. For example:

```text
I am preparing a first-use run prompt. Do not execute the workflow, modify
files, or commit changes.

Framework checkout:
/absolute/path/to/ai-engineering-workflow-framework

Target/execution repository (the current session starts here and owns the
durable .thoughts artifact):
/absolute/path/to/target-repository

Work item:
TECHOPS-12345 (https://your-company.atlassian.net/browse/TECHOPS-12345)

Selected playbook:
TechOps Issue Remediation

Canonical run template:
/absolute/path/to/ai-engineering-workflow-framework/templates/techops_issue_run_prompt.md

Additional repositories or assets:
NONE

Read these files from the framework checkout using their absolute paths:
- /absolute/path/to/ai-engineering-workflow-framework/SETUP.md
- /absolute/path/to/ai-engineering-workflow-framework/README.md
- /absolute/path/to/ai-engineering-workflow-framework/OPERATING_GUIDE.md
- /absolute/path/to/ai-engineering-workflow-framework/PLAYBOOK_CATALOG.md
- /absolute/path/to/ai-engineering-workflow-framework/playbooks/techops_issue_remediation.md
- /absolute/path/to/ai-engineering-workflow-framework/templates/techops_issue_run_prompt.md

Fill the existing canonical template for this work item. Do not invent a new
format. For a new run, use lifecycle `planning` and omit the template's entire
Continuation section. Mark unavailable information as `Unknown` or `None`,
preserve the template's field names, and return the completed prompt followed
by a short list of anything I must review before running it.
```

Replace the example paths, work item, playbook, and additional inputs with the
ones for the actual run. The work item is not a description such as “fix the
bug”; it is the identifier or URL that anchors the work record, Jira/Sentry
lookup, and handoff. If the issue is a Jira ticket, use its key and URL. If it
is a Sentry issue, use its issue ID or URL. If it is another engineering task,
use its stable ticket, incident, or work-item identifier.

The request above is only a prompt-preparation request. It is not the workflow
run itself. After reviewing the generated prompt, paste that prompt into the
target-repository session to execute the selected playbook.

### Prompt-preparation checklist

Before asking Codex to fill the template, verify:

1. You know the absolute path of the framework checkout.
2. You know the absolute path of the checkout where the session will run and
   where the work record must be saved.
3. You have the stable work-item ID or URL.
4. You selected the playbook from the catalog and its matching template.
5. You listed other repositories and asset folders separately from the
   execution repository.
6. You stated whether this is a new run or a continuation. For a new run,
   omit `Continuation` rather than filling it with `NONE`.

If any value is unavailable, tell Codex to use `Unknown` or `None` in the
existing template and flag it for review. Do not silently substitute the
framework checkout, an attachment folder, or the current directory for the
execution repository.

Review the generated prompt before running it. The user remains responsible
for the selected repository, scope, permissions, lifecycle, profile, and
approvals.

## Verify the framework

From the framework checkout:

```bash
python3 scripts/validate_library.py
```

The validator checks document versions, playbook maturity, template
consistency, provider mappings, and configuration syntax.
