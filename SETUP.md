---
title: AI-assisted Software Engineering Workflow Framework Setup
version: 0.5.20
status: Pilot
owner: Engineering
last_updated: 2026-10-08
---

# Setup

This guide prepares the framework for local use. The framework is the source of truth. Durable records belong in the
main execution repository under `.thoughts/<WORK-ITEM-ID>/`; an active worktree supplies source code and revision
evidence. Other code repositories and evidence folders may be listed separately as investigation inputs.

Install the [launcher plugin](#codex-launcher-plugin) and invoke it directly. Local agent views are optional; the
installed plugin supplies its provider definitions.

## Clone the framework

```bash
git clone https://github.com/daniel-galvan/ai-engineering-workflow-framework.git
cd ai-engineering-workflow-framework
```

Do not start engineering work from the framework checkout unless the framework itself is the code repository being
investigated. Start the session in the repository being investigated and supply other repository paths when relevant.

## Prepare the execution repository

Start the Codex session in the repository being investigated. The current repository is the default; specify another
execution repository only when needed. Preparation resolves its main Git checkout for durable artifacts and uses an
active equivalent worktree for source operations. For a monorepo, start at the checkout root and list relevant component
paths as additional working directories. See the
[artifact-root contract](contracts/workflow_execution.md#durable-artifact-root).

The execution repository determines the durable artifact location:

```text
<execution-repository>/.thoughts/<WORK-ITEM-ID>/work_record.md
```

Additional repositories, evidence folders, screenshots, logs, and payloads are inputs to the run; they are not artifact
roots.

<a id="optional-codex-launcher-plugin"></a>

## Codex launcher plugin

The Codex plugin is the normal launch path. The installed package includes the canonical catalog, playbooks, contracts,
skills, provider guidance, definitions, and templates. The [local agent view](#codex-agent-setup) remains optional.

The plugin-specific files are deliberately small:

| Path | Purpose |
| --- | --- |
| `.codex-plugin/plugin.json` | Plugin identity, coordinated release plus build suffix, capabilities, and skill root |
| `.agents/plugins/marketplace.json` | Local marketplace identity and repository-relative plugin source |
| `skills/run/SKILL.md` | Explicit workflow launcher and package preflight sequence |
| `skills/run/agents/openai.yaml` | Codex display metadata and explicit-invocation policy |
| `scripts/run_preflight.py` | Fail-fast package, Git revision, and cleanliness validation |
| `scripts/prepare_run.py` | Fresh-run archival, immutable input-manifest capture, work-record initialization, and exact Codex role bindings |
| `scripts/run_input_manifest.py` | Input-manifest schema, precedence, hashing, and continuation merge helpers |
| `scripts/validate_worker_runtime.py` | Hashed role-envelope validation and active-worker transition guard |
| `templates/sentry_work_record.md` | Compact initial and terminal record surface for Sentry runs |

The plugin base version and versioned framework documents share the coordinated library release. The plugin's
`+codex.<timestamp>` suffix identifies the installed package build; Git identifies the source snapshot. See the
[version policy](CONTRIBUTING.md#version-policy).

### Install or update

Add the repository marketplace once, then install the plugin from the framework checkout:

```bash
FRAMEWORK_DIR="/absolute/path/to/ai-engineering-workflow-framework"
codex plugin marketplace add "$FRAMEWORK_DIR"
codex plugin add ai-engineering-workflows@ai-engineering-workflow-framework
```

Plugin installation is user-global, not execution-repository-scoped. Start a new Codex task from the chosen execution
repository after installation, then explicitly invoke the launcher with the work item:

```text
Use $ai-engineering-workflows:run.
Work item: <stable ID or URL>
```

The plugin uses the framework snapshot bundled with its installed version. After any tracked repository content change,
update the cache-busting suffix in `.codex-plugin/plugin.json` before packaging or installing the snapshot. Run the
framework validator and preflight self-test, then rerun the `codex plugin add` command above. Reusing build metadata
fails validation or preflight with `plugin_build_identity_reused`. Start a new task to load the updated package. Record
the installed plugin name/version in plugin-backed work records.
The launcher performs a package/revision/clean-status preflight before loading the catalog or playbook. Do not paste a
versioned plugin-cache `SKILL.md` path into a plugin run; the active installed skill is authoritative. If an explicit
old or different plugin path is supplied, the run stops immediately with `plugin_revision_mismatch`.

### Plugin execution examples

These examples execute the workflow directly. Start the Codex task from the execution repository, replace the
scenario-specific values, and do not include a framework checkout path; the installed plugin supplies it. The execution
repository field may be omitted when the current repository is unambiguous. Omit provider/runtime configuration to use
the bundled definitions, or supply an installed and verified local view.

#### TechOps Issue Remediation

```text
Use $ai-engineering-workflows:run.

Execution repository (main checkout for durable .thoughts artifacts):
/absolute/path/to/execution-repository

Provider/runtime configuration (optional runtime view; use `Not provided` when absent):
/absolute/path/to/execution-repository/.codex/agents/

Work item:
TECHOPS-12345 (https://your-company.atlassian.net/browse/TECHOPS-12345)

Playbook: playbooks/techops_issue_remediation.md
Execution profile: standard
Lifecycle: planning

Additional repositories or assets:
NONE
```

#### Vulnerability Investigation

```text
Use $ai-engineering-workflows:run.

Execution repository (main checkout for durable .thoughts artifacts):
/absolute/path/to/execution-repository

Provider/runtime configuration (optional runtime view; use `Not provided` when absent):
Not provided

Work item:
VULN-1234 (https://your-company.atlassian.net/browse/VULN-1234)

Playbook: playbooks/vulnerability_investigation.md
Execution profile: standard
Lifecycle: planning

Additional repositories or assets:
NONE

Optional supporting artifacts:
NONE

Additional context or constraints (optional; unverified):
NONE
```

#### Sentry Issue Remediation

```text
Use $ai-engineering-workflows:run.

Execution repository (main checkout for durable .thoughts artifacts):
/absolute/path/to/execution-repository

Provider/runtime configuration (optional runtime view; use `Not provided` when absent):
/absolute/path/to/execution-repository/.codex/agents/

Primary code repository:
/absolute/path/to/primary-code-repository

Work item:
SENTRY-ISSUE-123 (https://sentry.example.com/issues/SENTRY-ISSUE-123)

Evidence source: live_sentry
Sentry issue: https://sentry.example.com/issues/SENTRY-ISSUE-123

Playbook: playbooks/sentry_issue_remediation.md
Execution profile: standard
Lifecycle: planning

Additional repositories or assets:
- /absolute/path/to/additional-repository-or-NONE

Optional supporting artifacts:
- /absolute/path/to/payload.json-or-NONE
- /absolute/path/to/screenshot-or-NONE
```

## Codex agent setup

This optional local runtime view exposes the framework's provider agents in the execution repository. Plugin runs
resolve bundled definitions when no local view is supplied. To configure a local view, use explicit paths from the
framework checkout:

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

- let Codex discover the provider-specific workers from the execution-repository session;
- keep one authoritative copy of each agent definition in the framework;
- make agent policy updates available to execution repositories without copying or manually synchronizing files; and
- keep provider configuration local to the developer's machine rather than adding runtime-specific files to the code
  repository's source history.

The links do not grant permissions, create delegation capability, or force a worker to run. The playbook and runtime
still determine whether a worker is required, available, activated, and completed.

Read [providers/codex.md](providers/codex.md) and the [Codex model and effort
policy](providers/codex/model_effort_policy.md) for the current provider mapping. If the provider runtime cannot use
nested delegation, the active Codex session remains the Coordinator and must complete worker fan-in and runtime closure
itself.

## Run inputs and receipts

Supply the work-item ID or URL and relevant decisions, constraints, reports, hypotheses, repository paths, and artifacts
with the plugin invocation. Separate confirmed decisions from investigation hints. The launcher preserves and classifies
material context in `run_inputs.json`, copies and hashes it under `.thoughts/<WORK-ITEM-ID>/`, and passes it to the
assigned workers. You do not need to create this manifest or repeat the same context in a separate prompt.

For a new run, omit continuation fields. To continue or recover a run, provide its prior work record and the new
evidence or recovery reason. Remediation also requires an implementation plan and explicit approval. Specify repository
branches or revisions when known; a path alone does not establish baseline or production evidence.

## Use an implementation plan in another environment

When implementation needs a DevBox or another session, use the generated `implementation_handoff.md` beside the plan. It
is self-contained and does not require the framework checkout. Copy that one file to the receiving environment, start
Codex at the root of the target Git repository, and ask it to execute the approved handoff. For a monorepo, keep the
session at the repository root so sibling projects remain available. The receiving session must verify the target
repository, current default branch, starting revision, dependencies, approval, review, and validation before reporting
completion. Create the handoff only for that cross-session or cross-environment transfer, or when explicitly requested;
same-session implementation does not need one. The handoff does not select a model, effort, or provider runtime.

## Declare an evaluation or benchmark

Evaluation and benchmarking are deferred while the normal workflow stabilizes. For an intentional experimental run,
add this block to the plugin invocation:

```text
Run this as an explicit evaluation run.        # or: Run this as a benchmark evaluation.
Evaluation run ID: <UNIQUE-ID>
Framework revision: <FULL-GIT-COMMIT>
Framework worktree status: clean
Role-policy baseline ID: <BASELINE-ID>
Record provider-observed timing and usage when available; never estimate missing values.
```

Use a new evaluation run ID for every attempt. Keep the prompt, framework commit, playbook version, profile, lifecycle,
provider/model configuration, and relevant repository revisions constant when comparing attempts. Evaluation telemetry
uses `templates/evaluation_work_record_addendum.md`; normal runs omit it.

## Verify the framework

From the framework checkout:

```bash
python3 scripts/validate_library.py
```

The validator checks document versions, Markdown table structure, playbook maturity, template consistency, provider
mappings, Codex policy/TOML alignment, and configuration syntax.
