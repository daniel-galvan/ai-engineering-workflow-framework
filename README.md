# AI-assisted Software Engineering Workflow Framework

> [!WARNING]
> **Work in progress — pilot, not fully validated.** Use with care, verify all outputs, and protect sensitive data.
> You are responsible for its use and resulting decisions or changes.

Provider-neutral, evidence-driven playbooks, roles, skills, and execution contracts for AI-assisted software
engineering. The Codex plugin bundles these components and provides the normal launch path.

The framework turns a work item into a traceable workflow with investigation, design, implementation, independent
review, validation, durable context, and an honest, human-readable handoff.

Every terminal handoff reports the workflow outcome—whether the selected graph completed—and the engineering outcome—
what value the run delivered to the work item—as separate fields.

## Core promise

AI-assisted engineering where every material conclusion is traceable from [evidence](contracts/claims.md) to claim,
decision, and action. Workers and provider adapters support that reasoning chain.

> [!IMPORTANT]
> **Current explicit user decisions take precedence over historical AI conclusions.** A current explicit user decision
> or constraint is authoritative; workers must not silently override it or reopen it as unresolved because a prior
> worker concluded otherwise. Historical artifacts are supporting evidence unless the current user input or an
> explicitly identified approved decision adopts them. If direct evidence conflicts with the decision, present the
> conflict and ask explicitly for a new decision. See
> [Authoritative Run Inputs](contracts/workflow_execution.md#authoritative-run-inputs).

## Introduction

This framework is a tool for engineers, not a replacement for them. The user sets the goal and scope, provides context,
interprets results, adjusts the workflow, makes decisions, grants approval, and remains solely responsible for how the
tool is used and for the resulting changes.

The project is an evolving pilot with known gaps and many opportunities for improvement. It favors quality over
quantity: more workers, tokens, or effort do not automatically produce a better result. Role quality should remain
consistent across execution profiles; profiles change the evidence and coordination depth, not the standard expected
from a role.

Three further principles are essential:

- AI output is evidence to assess, not authority to trust; uncertainty and unknowns must remain visible.
- Human approval, independent review, and executable validation are control points, not optional ceremony.
- Scope, permissions, privacy, and security remain explicit; the workflow must not expose sensitive data or make
  irreversible changes without authorization.

## What it covers

Use it for work with meaningful uncertainty, dependencies, risk, or coordination needs, including:

- Jira features, improvements, bugs, and TechOps issues;
- Sentry production failures;
- vulnerability and scanner findings; and
- special workflows that need distinct stages or gates.

Do not use the full worker graph for a trivial, well-bounded change. Use the smallest role and skill set that provides
enough evidence and validation.

## Quick start

1. Install or update the [Codex launcher plugin](SETUP.md#codex-launcher-plugin).
2. Start a new Codex task in the repository being investigated. Durable records go to its main checkout; an active
   equivalent worktree supplies source code and revision evidence.
3. Explicitly invoke the launcher with the work item and relevant context:

   ```text
   Use $ai-engineering-workflows:run.
   Work item: <stable ID or URL>
   ```

   Add the playbook, profile, lifecycle, goal, repositories, or constraints when needed. The launcher selects a playbook
   when omitted and records its defaults; some scenarios require additional inputs, such as a Spike's primary question.
   See [plugin execution examples](SETUP.md#plugin-execution-examples).
4. Review the planning result. Answers, reports, assessments, and implementation plans depend on the selected goal.
5. For a delivery playbook, approve the implementation plan explicitly before entering `remediation`.

The installed plugin supplies the framework package, provider definitions, and run contracts. A local `.codex/agents/`
view is optional.

## First-use view

The user-facing model is intentionally small:

| Question | Answer |
| --- | --- |
| What playbook do I use? | Choose the most specialized playbook for the work item's primary evidence and goal in [PLAYBOOK_CATALOG.md](PLAYBOOK_CATALOG.md). |
| What do I provide? | Work-item ID or URL, lifecycle, profile, and relevant context. The current repository is the default; specify another execution repository when needed. |
| What happens first? | Package preflight and required input/source gates pass before preparation, worker activation, and fan-in. |
| What may I approve? | Scope and design approvals are conditional. Implementation approval is required before remediation. Release approval is required for deployment, cutover, or another external operational write. See the [human control model](contracts/workflow_execution.md#human-control-model). |
| Where do results go? | The main execution repository's `.thoughts/<WORK-ITEM-ID>/` contains `work_record.md` and goal-specific artifacts. An implementation plan is created only at `ready_for_implementation`; its portable handoff is optional. |

Users normally make only two execution choices:

| Choice | Meaning |
| --- | --- |
| Lifecycle | `planning` is read-only; `remediation` may implement an explicitly approved plan. |
| Profile | `standard` or `deep`; it selects the required worker graph and independent coverage. |

The selected playbook and provider role policy derive workers, skills, tools, models, and reasoning effort. Actual
model and effort values belong in the worker ledger, not in a first-use run prompt.

The execution repository's `.codex/agents/` runtime view is optional. When it is absent, resolve provider definitions
from the bundled framework/plugin or the selected work-graph binding. Versioned evaluations still require a resolved,
reproducible provider configuration source; never inherit unverified Coordinator settings.

The shared rules are in [contracts/workflow_execution.md](contracts/workflow_execution.md). Vocabulary,
portable-handoff rules, and non-normative execution guidance are linked from that core and loaded only when needed. The
evidence-to-action reasoning model is [contracts/claims.md](contracts/claims.md);
[OPERATING_GUIDE.md](OPERATING_GUIDE.md) explains normal operation.

## Architecture

### User-facing flow

```text
Work item + goal + context
  -> explicitly invoke the plugin launcher
    -> select playbook, profile, and lifecycle
      -> planning: answer, report, assessment, or implementation plan
        -> approved implementation plan + supported remediation lifecycle
          -> implementation, Code Review, validation, and handoff
```

Technical Spike ends in planning. A specification assessment also ends with its assessment rather than an
implementation plan.

### Codex plugin execution flow

```text
Installed plugin + explicit request
  -> package preflight and required input/source gates
    -> prepare repository paths, inputs, work record, and role bindings
      -> Coordinator activates the selected worker graph
        -> roles + skills + tools + provider model policy
          -> fan-in, review, and validation
            -> runtime closure and finalization
              -> human-readable handoff and durable artifact receipts
```

The launcher routes into the provider-neutral framework; it does not redefine its roles, playbooks, or contracts.
Source operations use the resolved source checkout. Durable records and receipts stay in the main execution repository.

| Building block | Purpose |
| --- | --- |
| Plugin launcher | Explicit entry point, bundled package discovery, preflight, and execution routing |
| Framework | Shared investigation-first engineering method |
| Contract | Common lifecycle, worker, claims, evidence, decisions, gates, and handoff semantics |
| Strategy | Coordination and parallelization approach |
| Role | Reusable responsibility and reasoning boundary |
| Skill | Reusable provider-neutral capability |
| Playbook | Scenario-specific stages, dependencies, and outputs |
| Provider adapter | Mapping to Codex or another execution platform |
| Work record | Durable facts, decisions, errors, evidence, and next steps |

## Current playbooks

### Delivery playbooks

These support read-only planning and approved remediation.

| Playbook | Use for |
| --- | --- |
| [Feature Delivery](playbooks/feature_delivery.md) | Jira features, improvements, and specification assessments |
| [TechOps Issue Remediation](playbooks/techops_issue_remediation.md) | Support- and operations-reported Jira issues |
| [Sentry Issue Remediation](playbooks/sentry_issue_remediation.md) | Production issues backed by Sentry evidence |
| [Vulnerability Investigation](playbooks/vulnerability_investigation.md) | Scanner findings, advisories, CVEs, and security risk |

### Investigation playbooks

[Technical Spike](playbooks/technical_spike.md) answers bounded technical questions or reviews an existing Spike.
It supports planning only and produces a Spike report; delivery requires a separate delivery-playbook run.

Exercise state and worker graphs are maintained in [PLAYBOOK_CATALOG.md](PLAYBOOK_CATALOG.md). Add another playbook only
when the existing stages, gates, and artifacts cannot express the scenario cleanly.

## Guides and examples

Use this reading path:

1. [Setup](SETUP.md) — install the plugin and start a run.
2. [Operating Guide](OPERATING_GUIDE.md) — responsibilities, lifecycle, work records, and usage rules.
3. [Playbook Catalog](PLAYBOOK_CATALOG.md) — choose a scenario and see its worker graph.
4. [Templates](templates/) — canonical plugin input schemas and durable artifact formats.
5. [Examples](examples/) — follow a safe, generic scenario guide for each current playbook.
6. [Contributing](CONTRIBUTING.md) — extend the framework without duplicating contracts, roles, skills, or provider
   behavior.

## Repository map

```text
.agents/plugins/ Codex marketplace metadata
.codex-plugin/   Codex plugin manifest
contracts/       shared execution and reasoning semantics
examples/        safe, generic scenario guides
frameworks/      reusable engineering method
  experimental/  deferred, opt-in methods excluded from normal runs
integrations/    external evidence and work-item sources
playbooks/       scenario workflows
providers/       platform adapters and agent definitions
  codex/agents/  packaged Codex worker definitions
roles/           reusable responsibilities
scripts/         preflight, preparation, evidence collection, validation, and finalization
  validation/    domain modules for library, contract, playbook, provider, and finalization checks
skills/          provider-neutral capabilities
  run/           explicit Codex plugin launcher
    agents/      launcher display and invocation metadata
strategies/      coordination approaches
templates/       canonical prompts and durable work artifacts
tests/           regression unit tests
  fixtures/      synthetic/redacted historical regression evidence
framework_manifest.json  generated canonical version inventory
PLAYBOOK_CATALOG.md      playbook selection, worker graphs, and generated exercise state
```

The Codex plugin is a thin package over this repository; it does not duplicate framework behavior. See the
[launcher setup](SETUP.md#codex-launcher-plugin) for package layout, installation, and update requirements;
[`skills/run/SKILL.md`](skills/run/SKILL.md) for execution controls; and [providers/codex.md](providers/codex.md) plus
[the model and effort policy](providers/codex/model_effort_policy.md) for provider behavior.

## Quality and evolution

Run the framework validator after changes:

```bash
python3 scripts/validate_library.py
python3 scripts/validate_library.py /path/to/.thoughts/WORK-ITEM/work_record.md
```

The optional path validates a terminal work record's identity, playbook-selection evidence, repository revisions, and
evidence-to-action references.

Document facts and limitations in the work record. Exercise changes against real work items, then simplify. See
[CONTRIBUTING.md](CONTRIBUTING.md) and [ROADMAP.md](ROADMAP.md).

Evaluation and benchmarking are deliberately deferred from the normal workflow while the pilot stabilizes. Ordinary
runs keep only core execution, provenance, outcome, and artifact controls. Add the evaluation addendum only when a
prompt explicitly declares an evaluation or benchmark; it must not be used to retrofit telemetry that the run did not
observe. See the [experimental evaluation guide](frameworks/experimental/workflow_evaluation.md) and
[`evaluation_work_record_addendum.md`](templates/evaluation_work_record_addendum.md).

## Versioning

Versioned documents and the plugin base version share one coordinated release number. Canonical document dates record
the release update date; Git revisions and the plugin build suffix identify the snapshot used by a run.
[framework_manifest.json](framework_manifest.json) provides the current release and version inventory. See the
[version policy](CONTRIBUTING.md#version-policy) for source metadata, regeneration, and validation rules. Matching
versions do not establish cross-revision compatibility or successful live exercise.

## Status

This is an evolving pilot foundation, not a guarantee of correct code or production readiness. A playbook is not
considered delivery-validated until its required implementation, Code Review, validation, fan-in, and runtime closure
have been exercised successfully.
