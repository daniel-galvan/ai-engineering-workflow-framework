---
title: AI-assisted Software Engineering Workflow Framework Setup
version: 0.1
status: Pilot
owner: Engineering
last_updated: 2026-08-12
---

# Setup

This guide prepares the framework for local use. The framework is the source of truth. The execution repository is where
the session starts and where the durable `.thoughts/<WORK-ITEM-ID>/` record is created; code repositories and evidence
folders may be listed separately as investigation inputs.

## Clone the framework

```bash
git clone https://github.com/daniel-galvan/ai-engineering-workflow-framework.git
cd ai-engineering-workflow-framework
```

Do not start engineering work from the framework checkout unless the framework itself is the code repository being
investigated. Start the session in the execution repository and provide the absolute paths of the primary and additional
code repositories in the run prompt.

## Prepare the execution repository

Choose the execution repository before creating the prompt and start the Codex session there. For a monorepo, use the
Git checkout root as the execution repository and list relevant component paths as additional working directories.

The execution repository determines the durable artifact location:

```text
<execution-repository>/.thoughts/<WORK-ITEM-ID>/work_record.md
```

Additional repositories, evidence folders, screenshots, logs, and payloads are inputs to the run; they are not artifact
roots.

## Codex agent setup

Codex users may expose the framework's provider agents in the execution repository. From the framework checkout, use
explicit paths:

```bash
FRAMEWORK_DIR="/absolute/path/to/ai-engineering-workflow-framework"
EXECUTION_REPO="/absolute/path/to/execution-repository"

mkdir -p "$EXECUTION_REPO/.codex/agents"
for agent_file in "$FRAMEWORK_DIR/providers/codex/agents"/*.toml; do
  agent_name="$(basename "$agent_file")"
  ln -s "$agent_file" "$EXECUTION_REPO/.codex/agents/$agent_name"
done
```

The symlinks are a local runtime view, not a second source of truth. Keep the framework agent files in the framework
repository. If the execution repository already has `.codex/agents/`, inspect existing entries before adding links.

Verify the runtime view with a directory listing that preserves symlinks. For example:

```bash
AGENT_DIR="$EXECUTION_REPO/.codex/agents"
test -d "$AGENT_DIR" && ls -la "$AGENT_DIR"
find "$AGENT_DIR" -maxdepth 1 \( -type f -o -type l \) -print
for agent_file in "$AGENT_DIR"/*.toml; do
  [ -e "$agent_file" ] || [ -L "$agent_file" ] || continue
  if [ -L "$agent_file" ] && [ ! -e "$agent_file" ]; then
    echo "Broken symlink: $agent_file"
    exit 1
  fi
done
```

Do not conclude that the directory or configuration is absent from an empty `find -type f` result: symlinks are not
regular files. Record whether the path is absent, empty, inaccessible, has no matching entries, or contains broken
links.

The links are useful because they:

- let Codex discover the provider-specific workers from the execution-repository
  session;
- keep one authoritative copy of each agent definition in the framework;
- make agent policy updates available to execution repositories without copying
  or manually synchronizing files; and
- keep provider configuration local to the developer's machine rather than
  adding runtime-specific files to the code repository's source history.

The links do not grant permissions, create delegation capability, or force a worker to run. The playbook and runtime
still determine whether a worker is required, available, activated, and completed.

Read [providers/codex.md](providers/codex.md) and the [Codex model and effort
policy](providers/codex/model_effort_policy.md) for the current provider mapping. If the provider runtime cannot use
nested delegation, the active Codex session remains the Coordinator and must complete worker fan-in and runtime closure
itself.

## Create and run a prompt

Start the Codex session from the execution repository, then copy the matching canonical template from the framework
checkout into the session prompt. The execution-repository session does not automatically know where the framework
checkout is, so use absolute paths when asking it to prepare a prompt.

These terms have specific meanings:

| Term | Meaning | Example |
| --- | --- | --- |
| Framework checkout | Local clone of this repository; source of the guides, playbooks, roles, skills, contracts, and templates | `/absolute/path/to/ai-engineering-workflow-framework` |
| Execution repository | Code checkout where the session starts and where `.thoughts/<WORK-ITEM-ID>/` is created | `/absolute/path/to/execution-repository` |
| Primary code repository | Repository most likely to contain the affected code; it may be the execution repository | `/absolute/path/to/primary-code-repository` |
| Additional repository | Another checkout needed for evidence or cross-repository analysis; it does not own the work record for this run | `/absolute/path/to/additional-repository` |
| Work item | The stable identifier or URL for the thing being worked on | `TECHOPS-12345`, `PROJ-123`, `SENTRY-ISSUE-123`, or a Jira/Sentry URL |
| Playbook | The scenario workflow selected from [PLAYBOOK_CATALOG.md](PLAYBOOK_CATALOG.md) | `TechOps Issue Remediation` |
| Canonical run template | The matching file under the framework checkout's `templates/` directory | `templates/techops_issue_run_prompt.md` |

For a first run, the primary code repository is normally also the execution repository. If the likely fault is in
another checkout, keep the session and work record in the chosen execution repository and list that checkout as the
primary or an additional repository. Do not use the framework checkout or an evidence folder as the execution repository
just because it contains the playbook or attachments.

For a new run, fill only:

- work item or issue URL;
- execution profile and lifecycle;
- execution repository;
- playbook and its matching canonical template path;
- provider/runtime configuration when the execution repository's
  `.codex/agents/` directory is installed and verified;
- playbook-specific context and evidence; and
- additional repositories or constraints when applicable.

Omit the continuation section for a new run. The current session is the Coordinator by default, so there is normally no
Coordinator field to fill in. Use the execution repository's `.codex/agents/` path only when it has been installed and
verified.

Start with `planning` for investigation, diagnosis, design, and a proposed implementation plan. Use `remediation` only
after the plan exists and explicit implementation approval has been given.

## Ask Codex to prepare the prompt

From a session started in the execution repository, give Codex the framework checkout path, execution repository path,
primary code repository if different, work item, selected playbook, and canonical template path. Use the matching
example below and replace its scenario-specific values.

Replace the example paths, work item, playbook, and additional inputs with the ones for the actual run. The work item is
not a description such as “fix the bug”; it is the identifier or URL that anchors the work record, Jira/Sentry lookup,
and handoff. If the issue is a Jira ticket, use its key and URL. If it is a Sentry issue, use its issue ID or URL. If it
is another engineering task, use its stable ticket, incident, or work-item identifier.

Separate direct user decisions and non-negotiable constraints from
investigation hints. Put decisions in the template's authoritative confirmed
section so workers do not reopen them as clarification questions. Put possible
causes, suspected flows, and topology guesses in the unverified context
section. Codex must classify all prose supplied with the preparation request,
including comments written before the request; preserve every material detail
in a canonical field or the template's additional-context field. You do not
need to restate the same information in the generated prompt. For Sentry, map
an explicit flow
`A emits or sends to B; B returns a response to A` as event origin `A` and
return path `B -> A`. Use the stated suspected fault location for the candidate
fault repository; do not infer or swap topology roles from the primary code
repository path.

These requests only prepare prompts; they do not run a workflow. Review the generated prompt, then paste it into the
execution-repository session to execute the selected playbook.

### TechOps Issue Remediation

```text
I am preparing a first-use run prompt. Do not execute the workflow, modify
files, or commit changes.

Framework checkout:
/absolute/path/to/ai-engineering-workflow-framework

Execution repository (the current session starts here and owns the
durable .thoughts artifact):
/absolute/path/to/execution-repository

Provider/runtime configuration:
/absolute/path/to/execution-repository/.codex/agents/

Primary code repository:
SAME AS EXECUTION REPOSITORY

Work item:
TECHOPS-12345 (https://your-company.atlassian.net/browse/TECHOPS-12345)

Playbook: playbooks/techops_issue_remediation.md
Canonical run template: templates/techops_issue_run_prompt.md

Execution profile: standard
Lifecycle: planning

Additional repositories or assets:
NONE

Read these files relative to the framework checkout:
- SETUP.md
- OPERATING_GUIDE.md
- PLAYBOOK_CATALOG.md
- playbooks/techops_issue_remediation.md
- templates/techops_issue_run_prompt.md

Fill the existing canonical template for this work item. Do not invent a new
format. For a new run, use lifecycle `planning` and omit the template's entire
Continuation section. Mark unavailable information as `Unknown` or `None`,
preserve the template's field names, and return the completed prompt followed
by a short list of anything I must review before running it.
```

### Vulnerability Investigation

The work-item URL is the primary lookup target. Provide optional local artifacts or investigation hints only when they
add information; the workflow retrieves and reconciles the scanner, advisory, severity, and component details when the
configured integrations make them available.

Replace the scenario-specific values with those for the actual investigation:

```text
I am preparing a first-use run prompt. Do not execute the workflow, modify
files, or commit changes.

Framework checkout:
/absolute/path/to/ai-engineering-workflow-framework

Execution repository (the current session starts here and owns the
durable .thoughts artifact):
/absolute/path/to/execution-repository

Provider/runtime configuration:
/absolute/path/to/execution-repository/.codex/agents/

Primary code repository:
SAME AS EXECUTION REPOSITORY

Work item:
VULN-1234 (https://your-company.atlassian.net/browse/VULN-1234)

Playbook: playbooks/vulnerability_investigation.md
Canonical run template: templates/vulnerability_issue_run_prompt.md

Execution profile: standard
Lifecycle: planning

Additional repositories or assets:
- NONE

Optional supporting artifacts:
- NONE

Additional context or constraints (optional; unverified):
- NONE

Read these files relative to the framework checkout:
- SETUP.md
- OPERATING_GUIDE.md
- PLAYBOOK_CATALOG.md
- playbooks/vulnerability_investigation.md
- templates/vulnerability_issue_run_prompt.md

Fill the existing canonical template for this work item. Do not invent a new
format. For a new run, use lifecycle `planning` and omit the template's entire
Continuation section. Mark unavailable information as `Unknown` or `None`,
preserve the template's field names, and return the completed prompt followed
by a short list of anything I must review before running it.
```

### Sentry Issue Remediation

The Sentry issue is the primary lookup target. Provide repository topology, possible fault locations, and supporting
artifacts only when they are known; the workflow must reconcile them with Sentry evidence and current source.

```text
I am preparing a first-use run prompt. Do not execute the workflow, modify
files, or commit changes.

Framework checkout:
/absolute/path/to/ai-engineering-workflow-framework

Execution repository (the current session starts here and owns the
durable .thoughts artifact):
/absolute/path/to/execution-repository

Provider/runtime configuration:
/absolute/path/to/execution-repository/.codex/agents/

Primary code repository:
/absolute/path/to/primary-code-repository

Work item:
SENTRY-ISSUE-123 (https://sentry.example.com/issues/SENTRY-ISSUE-123)

Playbook: playbooks/sentry_issue_remediation.md
Canonical run template: templates/sentry_issue_run_prompt.md

Execution profile: standard
Lifecycle: planning

Additional repositories or assets:
- /absolute/path/to/additional-repository-or-NONE

Optional supporting artifacts:
- /absolute/path/to/payload.json-or-NONE
- /absolute/path/to/screenshot-or-NONE

Additional context or investigation hints (optional; unverified):
- Event-origin repository: <REPOSITORY-OR-UNKNOWN>
- Candidate fault repository or component: <REPOSITORY-OR-COMPONENT-OR-UNKNOWN>
- Suspected flow or symptom: <DESCRIPTION-OR-NONE>
- Known exclusions or related links: <DESCRIPTION-OR-NONE>

Integration:
- Use the playbook's configured Sentry MCP integration.
- Do not request or use SENTRY_AUTH_TOKEN.

Read these files relative to the framework checkout:
- SETUP.md
- OPERATING_GUIDE.md
- PLAYBOOK_CATALOG.md
- playbooks/sentry_issue_remediation.md
- templates/sentry_issue_run_prompt.md

Fill the existing canonical template for this work item. Do not invent a new
format. For a new run, use lifecycle `planning` and omit the template's entire
Continuation section. Mark unavailable information as `Unknown` or `None`,
preserve the template's field names, and return the completed prompt followed
by a short list of anything I must review before running it.
```

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

If any value is unavailable, tell Codex to use `Unknown` or `None` in the existing template and flag it for review. Do
not silently substitute the framework checkout, an attachment folder, or the current directory for the execution
repository.

Review the generated prompt before running it. The user remains responsible for the selected repository, scope,
permissions, lifecycle, profile, and approvals.

## Verify the framework

From the framework checkout:

```bash
python3 scripts/validate_library.py
```

The validator checks document versions, Markdown table structure, playbook maturity, template consistency, provider
mappings, Codex policy/TOML alignment, and configuration syntax.
