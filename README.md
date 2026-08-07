# AI Engineering Workflow Library

Provider-neutral, evidence-driven playbooks, roles, skills, and execution
contracts for AI-assisted software engineering.

The library is designed to act as an engineering operating system: it turns a
work item into a traceable workflow with investigation, design, implementation,
independent review, validation, durable context, and an honest handoff.

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

## Quick start

1. Choose the playbook that matches the primary evidence and goal in
   [PLAYBOOK_CATALOG.md](PLAYBOOK_CATALOG.md).
2. Copy the matching canonical run template from [templates/](templates/) into
   the Codex session prompt. Fill in the work-item ID, execution repository,
   lifecycle, profile, and run-specific context. Do not invent a second prompt
   format.
3. Run from the repository being investigated or provide its absolute path.
   The durable record belongs in that repository:
   `.thoughts/<WORK-ITEM-ID>/work_record.md`.
4. Start with `planning` for read-only discovery, diagnosis, design, and an
   implementation plan. Create `implementation_plan.md` only after required
   worker fan-in and the planning gate pass.
5. After explicit approval, run `remediation`. The approved plan covers the
   complete delivery sequence: implement, Code Review, fix in-scope findings,
   re-review, validate, and hand off.

The shared rules are in
[contracts/workflow_execution.md](contracts/workflow_execution.md). The
practical explanation is [OPERATING_GUIDE.md](OPERATING_GUIDE.md).

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
| Contract | Common lifecycle, worker, evidence, gate, and handoff semantics |
| Strategy | Coordination and parallelization approach |
| Role | Reusable responsibility and reasoning boundary |
| Skill | Reusable provider-neutral capability |
| Playbook | Scenario-specific stages, dependencies, and outputs |
| Provider adapter | Mapping to Codex or another execution platform |
| Work record | Durable facts, decisions, errors, evidence, and next steps |

## Current playbooks

| Playbook | Use for | Current maturity |
|---|---|---|
| [Feature Delivery](playbooks/feature_delivery.md) | Jira features and improvements | Planning exercised |
| [Sentry Issue Remediation](playbooks/sentry_issue_remediation.md) | Production issues backed by Sentry evidence | Planning validated; remediation pending |
| [Vulnerability Investigation](playbooks/vulnerability_investigation.md) | Scanner findings, advisories, CVEs, and security risk | Planning exercised |
| [Service Extraction and Stabilization](playbooks/service_extraction.md) | Creating an independently operated service from an existing capability | Not exercised |

Choose the specialized playbook first; add a new playbook only when existing
stages, gates, and artifacts cannot express the scenario cleanly.

## Repository map

```text
contracts/       shared execution semantics
examples/        complete, safe usage examples
frameworks/      reusable engineering method
integrations/    external evidence and work-item sources
playbooks/       scenario workflows
providers/       platform adapters and agent definitions
roles/           reusable responsibilities
scripts/         deterministic library validation
skills/          provider-neutral capabilities
strategies/      coordination approaches
templates/       canonical prompts and durable work artifacts
```

Codex users should read [providers/codex.md](providers/codex.md) and
[providers/codex/model_effort_policy.md](providers/codex/model_effort_policy.md).
The provider adapter is the source of truth for Codex model and effort
selection; prompt text does not override a pinned agent configuration.

## Quality and evolution

Run the library validator after changes:

```bash
python3 scripts/validate_library.py
```

The pilot is intentionally incremental. Document facts and limitations in the
work record, exercise changes against real work items, and simplify after each
pilot. See [CONTRIBUTING.md](CONTRIBUTING.md) for extension rules and
[ROADMAP.md](ROADMAP.md) for planned coverage.

## Versioning

All versioned library documents are currently `0.1`. Ordinary pilot edits do
not change a document version. A version changes only when an explicit named
release or version update is requested.

## Status

This is an evolving pilot foundation, not a guarantee of correct code or
production readiness. A playbook is not considered delivery-validated until
its required implementation, Code Review, validation, fan-in, and runtime
closure have been exercised successfully.
