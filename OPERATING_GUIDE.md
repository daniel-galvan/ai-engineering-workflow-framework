---

title: AI-assisted Software Engineering Workflow Framework Operating Guide
version: 0.1
status: Pilot
owner: Engineering
last_updated: 2026-08-10
---

# AI-assisted Software Engineering Workflow Framework Operating Guide

This is the practical overview of the complete framework. It describes an
AI-assisted engineering workflow framework, not a collection of isolated prompts.

## Introduction and responsibility

The framework assists engineering work; it does not replace the engineer. The
user defines the goal and scope, supplies or approves context, interprets
worker results, adjusts the workflow, makes decisions, grants approvals, and
is solely responsible for use of the tool and resulting changes.

This is an evolving pilot. Its workflows, roles, profiles, and provider
adapters have known limitations and must be improved through real exercises.
Quality is more important than quantity: a larger worker graph, higher token
usage, or greater effort does not guarantee a better outcome. Role quality is
profile-independent; profiles change execution depth and coordination, not the
quality contract of an individual role.

The framework also requires three safeguards: treat AI output as evidence rather
than authority, keep uncertainty visible, and use explicit scope, approval,
independent review, validation, privacy, and security controls before changes
are accepted.

## Purpose

Turn an engineering work item into an evidence-backed outcome through reusable
workflows, roles, skills, tools, workers, validation, and durable context.

It supports Jira Stories, bugs, incidents, TechOps issues, features, upgrades,
migrations, new projects, vulnerabilities, and special workflows.

## Core principles

* Investigate before implementing.
* Prefer evidence over assumptions.
* Keep the smallest practical scope.
* Separate facts, inferences, hypotheses, and unknowns.
* Reuse roles and skills instead of creating monolithic prompts.
* Preserve context in a durable work record.
* Use incremental changes, gates, validation, and explicit handoffs.
* Keep provider-specific behavior behind adapters.
* Evolve the framework through exercised pilots rather than speculative design.

## Architecture

```text
Work item
  → Playbook
    → Stages and gates
      → Workers
        → Role + Skills + Tools + Model profile + Effort
          → Provider adapter
            → Provider agent/model execution
              → Evidence, artifacts, validation, and work record
```

### Building blocks

| Building block | Responsibility |
|---|---|
| Framework | Shared investigation-first engineering method |
| Contract | Common vocabulary, lifecycle, claims, evidence, workers, gates, and outcomes |
| Strategy | Coordination and parallelization approach |
| Role | Reusable responsibility and reasoning boundary |
| Skill | Reusable provider-neutral capability |
| Tool | Concrete allowed operation |
| Playbook | Scenario-specific stages, dependencies, and outputs |
| Provider adapter | Mapping to Codex or another execution platform |
| Work record | Durable context, evidence, decisions, errors, and handoff |

See [PLAYBOOK_CATALOG.md](PLAYBOOK_CATALOG.md) for the current scenario
selection guide and worker graphs.

## Roles

The current role catalog is:

* `orchestrator`
* `current_state_investigator`
* `dependency_analyst`
* `solution_architect`
* `repository_integrator`
* `implementer`
* `reviewer`
* `tester`
* `documenter`

Roles define responsibilities. They do not define provider, model, tool
implementation, or fixed execution order.

## Skills

Current reusable skills cover:

* work-item context recovery;
* workflow planning;
* repository exploration;
* dependency mapping;
* architecture mapping;
* destination integration;
* code migration;
* build and test;
* operational readiness;
* work-record maintenance; and
* failure diagnosis.

Skills define inputs, outputs, completion criteria, and safety boundaries.

## Workers and subagents

A worker is one execution instance. It combines a role, selected skills, tools,
model profile, effort, inputs, outputs, dependencies, parallelism, approval,
exit criteria, and failure behavior.

The same worker contract can be executed by a human, one AI session, or a
provider-specific subagent.

Parallel workers require a fan-in barrier: the Orchestrator waits for all
required workers, records their outcomes, summarizes their results, and only
then closes the stage. Runtime closure is a second barrier: completed worker
handles must be released before the run is closed or a new lifecycle run is
started. Active handles mean the workflow runtime is still occupied.

## Model and effort

Mode, execution profile, worker depth, and provider reasoning effort are
separate:

* Mode describes the work: discovery, investigation, delivery, stabilization,
  or review.
* Execution profile selects the playbook's worker graph: `standard` or `deep`.
* Worker depth is the provider-neutral effort requested for an individual
  worker: `quick`, `standard`, or `deep`.
* Model profile describes provider-neutral capacity: `standard_reasoning` or
  `deep_reasoning`.
* Provider adapters map each role to its concrete model and reasoning setting.

For the current Codex pilot, Feature Delivery, TechOps Issue Remediation,
Service Extraction, and Sentry
use the same role-quality policy. Most roles use `gpt-5.6-luna`; Solution
Architect uses `gpt-5.6-terra` with Light effort. Profiles choose which roles
run; they do not change a role's model or provider reasoning effort. The
canonical mapping is in
[providers/codex/model_effort_policy.md](providers/codex/model_effort_policy.md).

## Current playbooks

Document status remains `Pilot` while the framework is in progress. Playbook
maturity is explicit: `not_exercised` or `exercising`. `exercising` means that
real work is being used to test the playbook; the validated scope is recorded
separately. Remediation is not validated until a compliant delivery run
activates the required delivery workers, completes Code Review and validation,
and records fan-in.

Current playbooks include:

* Vulnerability Investigation — exercising; planning exercised
* Service Extraction and Stabilization — not exercised
* Feature Delivery — exercising; planning exercised
* TechOps Issue Remediation — exercising; not yet exercised
* Sentry Issue Remediation — exercising; Standard and Deep planning validated

The Service Extraction playbook is for establishing an independently buildable,
runnable, deployable, and maintainable service from an existing capability.
It is not a generic label for every migration and should not be reused for a
normal feature after extraction is complete.

The Feature Delivery playbook turns a Jira feature or improvement into a
verified scope, acceptance-criteria traceability, implementation plan, and
approved delivery workflow. It recovers thin-ticket context from the immediate
parent and ancestor hierarchy, selected siblings, linked decisions, and
repository evidence without treating that context as automatically inherited
scope.

The TechOps Issue Remediation playbook turns a support- or operations-reported
Jira issue into normalized report evidence, a reproduction and failure-path
analysis, repository ownership, a minimal remediation plan, and an approved
delivery workflow. Attachments are first-class evidence but must be reconciled
with current repository and runtime evidence.

The Sentry Issue Remediation playbook turns Sentry evidence into a
verified diagnosis, minimal fix, implementation plan, regression-test plan,
validation plan, and handoff. Standard and Deep planning are validated. The
remediation lifecycle remains unvalidated. Sentry is an integration source;
its MCP operations do not replace repository evidence or testing.

## Service Extraction workflow

The default is `deep + planning`:

```text
Initialize
  → Understand source
        → Analyze dependencies and boundary
      → Design service
        → Integrate destination
          → Planning review (Deep only)
            → Ready for implementation
```

The Documenter runs continuously. Explicit approval and `lifecycle: remediation`
are required before extraction, review, validation, stabilization, or cutover.
Use the canonical
[`service_extraction_run_prompt.md`](templates/service_extraction_run_prompt.md)
to start or resume a run.

For migrated code, the preferred change order is:

1. imports and namespaces;
2. registration and routing;
3. adapters and integration boundaries;
4. configuration and deployment wiring;
5. focused tests and documentation;
6. behavior changes only with explicit approval.

## Work records

Every work item declares one execution repository. It is the checkout in which
the session starts and the durable-artifact root; it is not a claim that the
root cause is in that repository. For a cross-repository investigation, choose
the most likely primary checkout, declare the other repositories as additional
working directories, and preserve the same artifact root for that run.

The work record and implementation plan are derived paths, not additional
user choices:

```text
<execution-repository>/.thoughts/<WORK-ITEM-ID>/work_record.md
```

The record contains scope, facts, assumptions, unknowns, evidence, decisions,
risks, errors, blockers, worker history, validation, next actions, and handoff
state. It is the durable source of truth for resuming work.

Create `implementation_plan.md` only after required planning fan-in passes and
the workflow reaches `ready_for_implementation`.

For a new run, the active session is the Coordinator. A configured provider
Orchestrator may be used only when the runtime actually supports nested
delegation; otherwise the active session starts workers, completes fan-in, and
closes their handles. Codex users may expose the framework's agent definitions
in `<execution-repository>/.codex/agents/`; omit the provider configuration
from the prompt when that runtime view is unavailable.

Continuation data is only for follow-up, recovery, or approved remediation
re-entry. Supply the prior work-record/plan path, new evidence or recovery
reason, and approval reference when remediation is requested. Worker lists are
derived from the selected playbook and prior work record; users do not enter
them manually.

### Run-input guide

| Case | Use when | Fill in | Omit |
| --- | --- | --- | --- |
| New planning run | First investigation of a work item | Work item, profile, lifecycle `planning`, one execution repository, evidence, additional repositories, and constraints | Continuation and approval reference |
| Planning follow-up | New evidence or a resolved product decision changes planning | Prior work record/plan and the new evidence or decision | Approval reference unless also entering remediation |
| Interrupted recovery | A required worker, fan-in, or runtime step did not finish | Prior work record/plan and the specific recovery reason | Worker lists; the Coordinator derives them |
| Remediation re-entry | Planning passed and implementation is explicitly approved | Lifecycle `remediation`, prior work record/plan, and approval reference | New planning inputs unless they changed |

For every case, the current session is the Coordinator by default. Use a
target repository's `.codex/agents/` path only when that runtime view has been
installed and verified; otherwise omit provider configuration. Never use the
framework repository or an evidence folder as the execution repository merely
because it contains a playbook or attachments.

Provider-reported usage should be recorded per worker when available:

* actual model;
* actual reasoning effort;
* tokens or duration, if exposed;
* credits, if exposed; and
* `Unknown` when unavailable.

Credits must not be estimated.

## When to use the framework

Use it when work has meaningful uncertainty, dependencies, risk, multiple
stages, cross-repository impact, operational concerns, or a need for durable
handoff.

Typical inputs are Jira tickets, pull requests, repositories, architecture
documents, incidents, logs, tests, and previous work records.

## When not to use the full workflow

Do not use the full worker graph for a trivial one-file change, simple wording
update, or narrow task with no meaningful investigation or coordination. Use a
smaller role/skill set or a direct session.

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

## Special workflows

A new uncommon workflow is valid when it still declares the common contract:
purpose, inputs, stages, roles, skills, tools, workers, artifacts, evidence,
gates, approvals, failure behavior, terminal outcomes, and work-record rules.
It may add domain-specific stages but must not bypass the shared lifecycle.

## Extension approach

When adding capability:

1. Reuse an existing role or skill when possible.
2. Add a new skill only when the capability is reusable.
3. Add a playbook when the scenario has distinct stages and gates.
4. Add a provider mapping only for provider-specific execution behavior.
5. Exercise the change against a real work item.
6. Record gaps and simplify after the pilot.

## Current status

The framework is a working pilot foundation. The Service Extraction and
Stabilization workflow, Codex agent mapping, model/effort policy, and work
record are implemented and ready for full-pilot execution. Stability claims
remain provisional until the implementation and validation phases are exercised
against the real Jira Story.
