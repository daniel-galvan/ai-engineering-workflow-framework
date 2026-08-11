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
canonical template from [templates/](templates/) into the session prompt.
Choose the playbook using [PLAYBOOK_CATALOG.md](PLAYBOOK_CATALOG.md).

For a new run, fill only:

- work item or issue URL;
- execution profile and lifecycle;
- execution repository;
- playbook-specific context and evidence; and
- additional repositories or constraints when applicable.

Omit the continuation section for a new run. The current session is the
Coordinator by default. Use the target repository's `.codex/agents/` path only
when it has been installed and verified.

Start with `planning` for investigation, diagnosis, design, and a proposed
implementation plan. Use `remediation` only after the plan exists and explicit
implementation approval has been given.

## Ask Codex to prepare the prompt

From the target-repository session, ask Codex to fill the existing template:

```text
Read SETUP.md, README.md, OPERATING_GUIDE.md, PLAYBOOK_CATALOG.md, the selected
playbook, and its canonical run-template file from the framework checkout.
For [WORK ITEM], prepare a first-use run prompt by filling that existing
template. Do not invent a new format, execute the workflow, modify files, or
commit changes. Mark missing information as Unknown and identify anything I
must review before running it.
```

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
