---

title: Codex Provider Adapter
version: 0.4.9
status: Pilot
owner: Engineering
provider: codex
last_updated: 2026-09-01
---

# Codex Provider Adapter

The complete operating guide is [`../OPERATING_GUIDE.md`](../OPERATING_GUIDE.md). For local clone, execution-repository,
symlink, and prompt setup, see [`../SETUP.md`](../SETUP.md).

## Agent Definitions

The canonical Codex model and effort mapping is defined in
[`codex/model_effort_policy.md`](codex/model_effort_policy.md).

Custom agent definitions are stored in [`codex/agents/`](codex/agents/). An execution repository MAY expose these files
under `.codex/agents/` using symlinks or another provider-specific installation mechanism. The framework/plugin remains
the source of truth; the execution repository contains only an optional runtime view.

Verify the runtime view before using it or reporting it as unavailable. Check the directory itself, list hidden entries,
inspect both regular files and symlinks, and verify symlink targets. An empty filtered search is not evidence that
`.codex/agents/` is absent; distinguish absent, empty, inaccessible, no matching entries, and broken symlink in the work
record.

Sentry uses specialized agents only where its investigation differs from the generic role: orchestration, Sentry
evidence, failure topology, repository integration, and fix design. It reuses the generic Implementer, Reviewer, Tester,
and Documenter so delivery policy has one source of truth. Successful Standard planning is narrower: after Evidence
Topology and Fix Design, packaged code renders the ready plan and terminal artifacts without a Documenter activation.

The active Codex session is the Coordinator and performs the Orchestrator role unless the runtime explicitly supports
nested delegation for a coordinator agent. Agent TOML files configure workers; they do not create delegation capability.
If nested delegation is not available, the active session must invoke the required workers directly and complete fan-in
and release completed worker handles before reporting profile success or starting a new lifecycle run.

The default Codex execution records this explicitly as `Coordinator execution: active parent session; no dedicated
Coordinator worker spawned`. The role binding remains available for providers that do create a coordinator child, but a
TOML definition alone never creates a task.

The Coordinator alone performs plugin preflight and run preparation. Activate every delegated worker with
`fork_context: false` or the provider-equivalent fresh-context option. Its typed activation packet MUST begin with
`Coordinator initialization: complete` and MUST prohibit rerunning the launcher skill, `run_preflight.py`, or
`prepare_run.py`. A worker consumes only its provider role, assignment, and named current-run inputs. It does not
inherit the Coordinator transcript or initialize the run again.

`prepare_run.py` writes a hashed role envelope for every resolved binding and records the packet paths plus
`worker_runtime_guard` in `role_bindings.json`. Validate the selected envelope before spawning and include it unchanged
in the worker message before the typed assignment. This is the binding-delivery fallback when the in-task runtime does
not expose `agent_role` or `agent_path`; observed metadata must match when present. Run the same guard before interrupt,
close, replacement, or fan-in transitions. It rejects destructive transitions while a worker remains active.

Before worker activation, `prepare_run.py` also copies and hashes the current-run input manifest as `run_inputs.json`.
Supplied context, decisions, and named artifacts remain authoritative; live runtime evidence is additive unless the user
explicitly requests live-only analysis. A missing explicit manifest must stop the run before activation.

Use only Codex's in-task `spawn_agent`/collaboration runtime for delegated workers. Never use `create_thread`,
`fork_thread`, or `send_message_to_thread`: those operations create or control user-owned tasks. Check for the
in-task runtime before `prepare_run.py`; if unavailable, stop with `worker_runtime_unavailable` without creating a task
or starting the worker graph.

Record the actual model and reasoning effort used by each worker in the work record. Also record provider-reported usage
or credits when available. If the enterprise workspace does not expose a recommended model or usage value, record the
limitation and do not estimate it.

Treat a completed preflight process with exit status 0 as passed even when the app hides its stdout. Do not rerun a
successful preflight solely to recover a missing display payload; retry only after timeout, nonzero exit, or an
objectively malformed result whose status cannot be determined.

For Standard planning, release every activated analytical worker and run the
`standard_planning_finalization.finalizer` recorded in `role_bindings.json`, passing each conditional worker handle with
`--completed-worker` only when that conditional worker activated; omit skipped conditional workers and let the
finalizer record `not_applicable`. Provider-role aliases for the implicit Evidence/Fix workers are accepted only when
their handles match those results. Do not activate a Documenter or use pre-release rendering for either readiness
result. The
finalizer creates `implementation_plan.md` for `ready_for_implementation/create` or `clarification_brief.md` for
`awaiting_input/omit`. Keep the final Documenter active while running the packaged finalizer in `--pre-release` mode
with a pending closure probe only for Documenter-owned Deep-planning and remediation paths. Release that worker only
after the check passes; then record exact provider closure and run the finalizer normally.
Evidence Topology and Fix Design receive prepared contracts and exact output paths from `role_bindings.json`. Each
writes only its assigned artifact; the Coordinator validates those files rather than reconstructing their payloads.

Framework tool IDs are provider-neutral capability classes, not literal Codex tool names. Use the
`provider_tool_mapping` emitted in `role_bindings.json`: repository reads, searches, history, builds, tests, and local
runtime inspection use `exec_command`; artifact and approved repository writes use `apply_patch`; connected runtime,
work-item, and scanner tools remain conditional. A worker MUST NOT search `ALL_TOOLS` for a literal framework tool ID
or report the capability unavailable merely because that name is absent. Report a capability unavailable only after
its mapped concrete operation is absent or an attempted in-scope operation fails.

Reference mapping from framework skills to Codex capabilities.

| Skill ID | Codex capability examples |
| --- | --- |
| `work_item_context` | Connected work-item context or supplied artifacts |
| `workflow_planning` | `update_plan`, `implement-plan` |
| `repository_exploration` | `codebase-locator`, `research-codebase`, `codebase-analyzer` |
| `dependency_mapping` | `codebase-analyzer`, `codebase-pattern-finder` |
| `architecture_mapping` | `zoom-out`, `research-codebase` |
| `destination_integration` | `research-codebase`, `codebase-pattern-finder` |
| `build_and_test` | repository execution, `diagnose` |
| `operational_readiness` | repository execution, `diagnose` |
| `failure_diagnosis` | `diagnose`, repository execution |
| `work_record_maintenance` | `apply_patch` |

The exact provider-neutral tool-ID mapping is generated by `scripts/prepare_run.py` and recorded in each run's
`role_bindings.json`; the table above maps broader skill IDs and does not replace that run manifest.
