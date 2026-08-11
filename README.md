# AI-assisted Software Engineering Workflow Framework

> [!WARNING]
> **Work in progress — pilot, not fully validated.** Use with care, verify all
> outputs, and protect sensitive data. You are responsible for its use and
> resulting decisions or changes.

Provider-neutral, evidence-driven playbooks, roles, skills, and execution
contracts for AI-assisted software engineering.

The framework turns a work
item into a traceable workflow with investigation, design, implementation,
independent review, validation, durable context, and an honest handoff.

## Introduction

This framework is a tool for engineers, not a replacement for them. The user
sets the goal and scope, provides context, interprets results, adjusts the
workflow, makes decisions, grants approval, and remains solely responsible for
how the tool is used and for the resulting changes.

The project is an evolving pilot with known gaps and many opportunities for
improvement. It favors quality over quantity: more workers, tokens, or effort
do not automatically produce a better result. Role quality should remain
consistent across execution profiles; profiles change the evidence and
coordination depth, not the standard expected from a role.

Three further principles are essential:

- AI output is evidence to assess, not authority to trust; uncertainty and
  unknowns must remain visible.
- Human approval, independent review, and executable validation are control
  points, not optional ceremony.
- Scope, permissions, privacy, and security remain explicit; the workflow must
  not expose sensitive data or make irreversible changes without authorization.

## What it covers

Use it for work with meaningful uncertainty, dependencies, risk, or coordination
needs, including:

- Jira features, improvements, bugs, and TechOps issues;
- Sentry production failures;
- vulnerability and scanner findings;
- migrations and service extraction; and
- special workflows that need distinct stages or gates.

Do not use the full worker graph for a trivial, well-bounded change. Use the
smallest role and skill set that provides enough evidence and validation.

## Setup

For cloning, target-repository selection, Codex agent links, prompt creation,
and validation, see [SETUP.md](SETUP.md).

## Quick start

1. Complete [SETUP.md](SETUP.md) for the framework, target repository, and
   provider runtime.
2. Choose the playbook that matches the primary evidence and goal in
   [PLAYBOOK_CATALOG.md](PLAYBOOK_CATALOG.md).
3. Copy the matching canonical run template from [templates/](templates/) into
   a session started in the target repository. Fill only the required
   first-run and scenario fields; do not invent a second prompt format.
4. Start with `planning` for read-only discovery, diagnosis, design, and an
   implementation plan. Create the plan only after required fan-in passes.
5. After explicit approval, run `remediation` through implementation, Code
   Review, validation, and handoff.

The shared rules are in
[contracts/workflow_execution.md](contracts/workflow_execution.md). The
evidence-to-action reasoning model is
[contracts/claims.md](contracts/claims.md). The practical explanation is
[OPERATING_GUIDE.md](OPERATING_GUIDE.md).

### Ask an AI agent to prepare a run prompt

If you are unsure which fields to provide, use the request and example in
[SETUP.md](SETUP.md#ask-codex-to-prepare-the-prompt) from a session started in
the target repository. The request explicitly supplies the absolute framework
checkout path, target/execution repository, work-item ID or URL, selected
playbook, and canonical template. It instructs the agent to fill the existing
template, mark missing information as `Unknown`, and avoid executing or
modifying the workflow.

Review the generated prompt before using it. The user remains responsible for
the selected playbook, scope, lifecycle, profile, permissions, and approvals.

## Architecture

```text
Work item
  -> canonical run template
    -> playbook and lifecycle
      -> shared execution contract
        -> orchestrator and worker graph
          -> roles + skills + tools
            -> provider adapter and model policy
              -> evidence, artifacts, validation, and work record
```

| Building block | Purpose |
|---|---|
| Framework | Shared investigation-first engineering method |
| Contract | Common lifecycle, worker, claims, evidence, decisions, gates, and handoff semantics |
| Strategy | Coordination and parallelization approach |
| Role | Reusable responsibility and reasoning boundary |
| Skill | Reusable provider-neutral capability |
| Playbook | Scenario-specific stages, dependencies, and outputs |
| Provider adapter | Mapping to Codex or another execution platform |
| Work record | Durable facts, decisions, errors, evidence, and next steps |

## Current playbooks

| Playbook | Use for | State |
|---|---|---|
| [Feature Delivery](playbooks/feature_delivery.md) | Jira features and improvements | Exercising — planning exercised; remediation not yet validated |
| [TechOps Issue Remediation](playbooks/techops_issue_remediation.md) | Support- and operations-reported Jira issues | Exercising — first planning attempt incomplete; not validated |
| [Sentry Issue Remediation](playbooks/sentry_issue_remediation.md) | Production issues backed by Sentry evidence | Exercising — Standard and Deep planning validated; remediation not yet validated |
| [Vulnerability Investigation](playbooks/vulnerability_investigation.md) | Scanner findings, advisories, CVEs, and security risk | Exercising — planning exercised; remediation not yet validated |
| [Service Extraction and Stabilization](playbooks/service_extraction.md) | Creating an independently operated service from an existing capability | Not exercised — real Jira pilot pending |

Choose the specialized playbook first; add a new playbook only when existing
stages, gates, and artifacts cannot express the scenario cleanly.

## Guides and examples

Use this reading path:

1. [Setup](SETUP.md) — clone, configure, and start a run.
2. [Operating Guide](OPERATING_GUIDE.md) — architecture, responsibilities,
   lifecycle, and usage rules.
3. [Playbook Catalog](PLAYBOOK_CATALOG.md) — choose a scenario and see its
   worker graph.
4. [Templates](templates/) — start a run with the canonical prompt and create
   the durable work record.
5. [Examples](examples/) — follow a safe, generic scenario guide for each
   current playbook.
6. [Contributing](CONTRIBUTING.md) — extend the framework without duplicating
   contracts, roles, skills, or provider behavior.

## Repository map

```text
contracts/       shared execution and reasoning semantics
examples/        safe, generic scenario guides
frameworks/      reusable engineering method
integrations/    external evidence and work-item sources
playbooks/       scenario workflows
providers/       platform adapters and agent definitions
roles/           reusable responsibilities
scripts/         deterministic framework validation
skills/          provider-neutral capabilities
strategies/      coordination approaches
templates/       canonical prompts and durable work artifacts
```

Codex users should read [providers/codex.md](providers/codex.md) and
[providers/codex/model_effort_policy.md](providers/codex/model_effort_policy.md).
The provider adapter is the source of truth for Codex model and effort
selection; prompt text does not override a pinned agent configuration.

## Quality and evolution

Run the framework validator after changes:

```bash
python3 scripts/validate_library.py
```

The pilot is intentionally incremental. Document facts and limitations in the
work record, exercise changes against real work items, and simplify after each
pilot. See [CONTRIBUTING.md](CONTRIBUTING.md) for extension rules and
[ROADMAP.md](ROADMAP.md) for planned coverage.

## Versioning

All versioned framework documents are currently `0.1`. Ordinary pilot edits do
not change a document version. A version changes only when an explicit named
release or version update is requested.

## Status

This is an evolving pilot foundation, not a guarantee of correct code or
production readiness. A playbook is not considered delivery-validated until
its required implementation, Code Review, validation, fan-in, and runtime
closure have been exercised successfully.
