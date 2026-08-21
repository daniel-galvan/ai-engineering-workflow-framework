---

title: Codex Provider Adapter
version: 0.3.0
status: Pilot
owner: Engineering
provider: codex
last_updated: 2026-08-11
---

# Codex Provider Adapter

The complete operating guide is [`../OPERATING_GUIDE.md`](../OPERATING_GUIDE.md). For local clone, execution-repository,
symlink, and prompt setup, see [`../SETUP.md`](../SETUP.md).

## Agent Definitions

The canonical Codex model and effort mapping is defined in
[`codex/model_effort_policy.md`](codex/model_effort_policy.md).

Custom agent definitions are stored in [`codex/agents/`](codex/agents/). For an execution repository, expose these files
under `.codex/agents/` using symlinks or another provider-specific installation mechanism. The framework is the source
of truth; the execution repository contains only the runtime view.

Verify the runtime view before using it or reporting it as unavailable. Check the directory itself, list hidden entries,
inspect both regular files and symlinks, and verify symlink targets. An empty filtered search is not evidence that
`.codex/agents/` is absent; distinguish absent, empty, inaccessible, no matching entries, and broken symlink in the work
record.

Sentry uses specialized agents only where its investigation differs from the generic role: orchestration, Sentry
evidence, failure topology, repository integration, and fix design. It reuses the generic Implementer, Reviewer, Tester,
and Documenter so delivery policy has one source of truth.

The active Codex session is the Coordinator and performs the Orchestrator role unless the runtime explicitly supports
nested delegation for a coordinator agent. Agent TOML files configure workers; they do not create delegation capability.
If nested delegation is not available, the active session must invoke the required workers directly and complete fan-in
and release completed worker handles before reporting profile success or starting a new lifecycle run.

Record the actual model and reasoning effort used by each worker in the work record. Also record provider-reported usage
or credits when available. If the enterprise workspace does not expose a recommended model or usage value, record the
limitation and do not estimate it.

Reference mapping from framework skills to Codex capabilities.

| Skill ID | Codex capability examples |
| --- | --- |
| `work_item_context` | Connected work-item context or supplied artifacts |
| `workflow_planning` | `update_plan`, `implement-plan` |
| `repository_exploration` | `codebase-locator`, `research-codebase`, `codebase-analyzer` |
| `dependency_mapping` | `codebase-analyzer`, `codebase-pattern-finder` |
| `architecture_mapping` | `zoom-out`, `research-codebase` |
| `destination_integration` | `research-codebase`, `codebase-pattern-finder` |
| `code_migration` | `apply_patch`, `implement-plan` |
| `build_and_test` | repository execution, `diagnose` |
| `operational_readiness` | repository execution, `diagnose` |
| `failure_diagnosis` | `diagnose`, repository execution |
| `work_record_maintenance` | `apply_patch` |
