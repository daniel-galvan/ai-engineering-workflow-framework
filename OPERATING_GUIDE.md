---

title: AI-assisted Software Engineering Workflow Framework Operating Guide
version: 0.4.0
status: Pilot
owner: Engineering
last_updated: 2026-08-25
---

# AI-assisted Software Engineering Workflow Framework Operating Guide

This guide explains how to run and resume a workflow. For the framework overview, roles, skills, and architecture, see
the [README](README.md); for scenario selection and worker graphs, see the [Playbook Catalog](PLAYBOOK_CATALOG.md).

## Responsibilities and safeguards

The framework assists engineering work; it does not replace the engineer. The user owns scope, context, decisions,
approvals, and the resulting changes. Treat AI output as evidence rather than authority, keep uncertainty visible, and
use explicit scope, approval, independent review, validation, privacy, and security controls.

This is an evolving pilot. More workers, tokens, or effort do not guarantee a better outcome; profiles change evidence
and coordination depth, not a role's quality contract.

## Workers and subagents

A worker is one execution instance. It combines a role, selected skills, tools, internal metadata, inputs, outputs,
dependencies, parallelism, approval, exit criteria, and failure behavior.

The same worker contract can be executed by a human, one AI session, or a provider-specific subagent.

Parallel workers require a fan-in barrier: the Orchestrator waits for all required workers, records their outcomes,
summarizes their results, and only then closes the stage. Runtime closure is a second barrier: completed worker handles
must be released before the run is closed or a new lifecycle run is started. Active handles mean the workflow runtime is
still occupied. A wait timeout is only a polling boundary; it is not worker failure and does not authorize closing an
active worker or starting a replacement.

## Profile and provider role policy

For a normal run, choose only:

| Choice | Values | Answers |
| --- | --- | --- |
| Lifecycle | `planning`, `remediation` | How far may this run proceed? |
| Profile | `standard`, `deep` | Which worker graph and independent coverage must run? |

The provider role policy selects the model and reasoning effort for each role. It is advanced configuration, not a
third normal run choice. For the current Codex pilot, profiles choose which roles run; they do not change a role's
model or reasoning effort. The canonical mapping is in
[providers/codex/model_effort_policy.md](providers/codex/model_effort_policy.md).

`mode`, provider-neutral worker depth, and provider-neutral capacity classification remain internal worker metadata.
They support provider adapters and audit records; users do not select them in a canonical run prompt.

## Work records

Every work item declares one execution repository. It is the checkout in which the session starts and the
durable-artifact root; it is not a claim that the root cause is in that repository. For a cross-repository
investigation, choose the most likely primary checkout, declare the other repositories as additional working
directories, and preserve the same artifact root for that run.

The work record and implementation plan are derived paths, not additional user choices:

```text
<execution-repository>/.thoughts/<WORK-ITEM-ID>/work_record.md
```

The record contains scope, facts, assumptions, unknowns, evidence, decisions, risks, errors, blockers, worker history,
validation, next actions, and handoff state. It is the durable source of truth for resuming work.

The work record distinguishes workflow state from engineering state, and workflow outcome from engineering outcome.
State says what is happening or established; outcome says whether the graph completed and what value reached the work
item. A blocked run can therefore preserve an approved plan without falsely implying that remediation completed.

The [human control model](contracts/workflow_execution.md#human-control-model) defines scope, design, implementation,
and release approvals. Its [stop conditions](contracts/workflow_execution.md#stop-conditions) distinguish when the
workflow stops, continues bounded investigation, or asks the user.

At terminal handoff or a blocked handoff, complete the compact [workflow evaluation](frameworks/workflow_evaluation.md).
It reuses the worker ledger to compare role quality, process, engineering outcome, and efficiency across real pilot runs
before changing model or effort policy.

Create `implementation_plan.md` only after required planning fan-in passes and the workflow reaches
`ready_for_implementation`.

Create the companion `implementation_handoff.md` beside the plan only when implementation will happen in another session
or environment, or when the user explicitly requests a self-contained transfer file. Do not create one by default for
same-session implementation. The handoff is a self-contained transfer artifact: it uses repository identities and
revisions instead of source-machine paths and includes the approved scope, evidence summary, environment preflight,
ordered implementation, strict Code Review, validation, stop conditions, rollback, and final reporting requirements.

The receiving session does not need the framework checkout. Start it at the root of the target Git repository, provide
the handoff file, verify the repository, current branch, and target project path, and execute the complete handoff. For
a monorepo, remain at the repository root so sibling projects are available. A pending approval remains a stop
condition. If provider agents or delegation are unavailable, record the actual execution and do not claim framework
profile, independent-review, fan-in, or model-setting results that were not observed.

For a new run, the active session is the Coordinator. A configured provider Orchestrator may be used only when the
runtime actually supports nested delegation; otherwise the active session starts workers, completes fan-in, and closes
their handles. Codex users may expose the framework's agent definitions in `<execution-repository>/.codex/agents/`; omit
the provider configuration from the prompt when that runtime view is unavailable.

Continuation data is only for follow-up, recovery, or approved remediation re-entry. Supply the prior work-record/plan
path, new evidence or recovery reason, and approval reference when remediation is requested. Worker lists are derived
from the selected playbook and prior work record; users do not enter them manually.

### Run-input guide

| Case | Use when | Fill in | Omit |
| --- | --- | --- | --- |
| New planning run | First investigation of a work item | Work item, profile, lifecycle `planning`, one execution repository, evidence, additional repositories, and constraints | Continuation and approval reference |
| Planning follow-up | New evidence or a resolved product decision changes planning | Prior work record/plan and the new evidence or decision | Approval reference unless also entering remediation |
| Interrupted recovery | A required worker, fan-in, or runtime step did not finish | Prior work record/plan and the specific recovery reason | Worker lists; the Coordinator derives them |
| Remediation re-entry | Planning passed and implementation is explicitly approved | Lifecycle `remediation`, prior work record/plan, and approval reference | New planning inputs unless they changed |

For every case, the current session is the Coordinator by default. Use the execution repository's `.codex/agents/` path
only when that runtime view has been installed and verified; otherwise omit provider configuration. Never use the
framework repository or an evidence folder as the execution repository merely because it contains a playbook or
attachments.

Provider-reported usage should be recorded per worker when available:

* actual model;
* actual reasoning effort;
* tokens or duration, if exposed;
* credits, if exposed; and
* `Unknown` when unavailable.

Credits must not be estimated.

## When to use the framework

Use it when work has meaningful uncertainty, dependencies, risk, multiple stages, cross-repository impact, operational
concerns, or a need for durable handoff.

Typical inputs are Jira tickets, pull requests, repositories, architecture documents, incidents, logs, tests, and
previous work records.

## When not to use the full workflow

Do not use the full worker graph for a trivial one-file change, simple wording update, or narrow task with no meaningful
investigation or coordination. Use a smaller role/skill set or a direct session.

## Advantages

* Repeatable engineering process across providers and work-item types.
* Clear separation between investigation, design, implementation, and review.
* Smaller prompts and reusable capabilities.
* Parallel work without losing a shared source of truth.
* Explicit safety boundaries and approval gates.
* Better handoffs through durable evidence and decisions.
* Provider-specific model selection without contaminating playbooks.

## Tradeoffs

* More setup than a single prompt.
* Parallel workers consume additional tokens and coordination time.
* Evidence collection can expose blockers before implementation begins.
* Provider adapters require maintenance.
* Automatic model/credit accounting is not universal.
* The framework improves process quality; it does not guarantee correct code.

## Extending the framework

Follow [CONTRIBUTING.md](CONTRIBUTING.md) for extension rules. New workflows must preserve the shared contract and are
appropriate only when existing stages and gates cannot express the scenario.

## Current status

The framework remains an evolving, unvalidated pilot. See [PLAYBOOK_CATALOG.md](PLAYBOOK_CATALOG.md) for per-playbook
exercise status and [ROADMAP.md](ROADMAP.md) for planned validation.
