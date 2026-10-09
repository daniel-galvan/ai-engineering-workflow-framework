---

title: Codex Provider Adapter
version: 0.5.20
status: Pilot
owner: Engineering
provider: codex
last_updated: 2026-10-08
---

# Codex Provider Adapter

Concrete launcher, worker activation, runtime closure, and connector operations are defined here. Shared workflow
semantics remain in the [execution contract](../contracts/workflow_execution.md); Jira source policy remains in
[the Jira integration](../integrations/jira.md).

The complete operating guide is [`../OPERATING_GUIDE.md`](../OPERATING_GUIDE.md). For local clone, execution-repository,
symlink, and prompt setup, see [`../SETUP.md`](../SETUP.md).

## Launcher and Package Preflight

Before initialization, a plugin-backed launcher MUST make package and framework preflight its first framework tool call.
It MUST derive the package root from the active installed skill, verify its catalog and manifest, compare any declared
framework revision, and check framework clean status before loading memory, cache directories, the selected playbook,
contracts, provider definitions, templates, or sibling artifacts. A stale plugin path or an unavailable, dirty, or
mismatched framework stops the run with the corresponding preflight reason; the launcher MUST NOT search another cache
version, silently substitute a checkout, activate workers, query external systems, or load the complete framework to
explain the block. A blocked preflight reports `preflight_elapsed_ms` and `worker_activation_attempts: 0` without
creating an artifact root or work record.
The process exit status is authoritative: a completed preflight with exit status 0 is passed even when stdout is hidden
by the host application. The launcher MUST NOT rerun a successful preflight solely to recover a missing display payload.

Pin the preflight-resolved packaged framework root for the entire run; if it disappears or changes, stop with
`plugin_revision_mismatch` instead of discovering another installed package.

For Jira-backed Feature Delivery, run the [Jira source-access
gate](../integrations/jira.md#feature-delivery-source-access-gate)
after package preflight and prompt-completeness checks, before full framework loading, input-manifest creation,
preparation, or worker activation. Try the direct Atlassian MCP connector first when available; Rovo is an app-backed
alternative. Bind the successful connector and exact-key issue-read operation to `feature-context`.
If the permitted source routes fail, emit the packaged `scripts/source_access_receipt.py` receipt with the source,
attempted operation, safe provider code, and current-turn start. Exit status 2 with a JSON `status: blocked` receipt is
a block, not a parser error. Report its fields and one access-restoration action. Create no artifact root or work
record; this pre-initialization block is not an assessment disposition. Do not probe optional sources for other
playbooks.

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

## Worker Activation

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

## Runtime Closure

Every close/release instruction below uses the applicable provider route. When no close operation exists,
collect the fresh Terminal snapshot after pre-release instead of issuing a nonexistent close command.
For a provider with an explicit close/release operation, preserve its exact returned handle and release confirmation;
use `Runtime status: Released` only after all run workers are released and no active handles remain.
For Codex collaboration runtimes without a close operation, collect fresh status reads after pre-release and the last
correction/follow-up. Use `Runtime status: Terminal` only when these reads account for every activated worker, including
Documenter. The snapshot may combine live inventory and targeted reads; one inventory call need not retain every
completed worker. When `list_agents` omits a worker, try `read_thread` or `wait_threads` using its provider-observed
thread ID. Preserve the mapping to the exact spawn identifier from provider metadata; never guess an ID. A targeted read
must show no active or pending thread and a completed latest turn started at or after the last dispatch. For a
correction delivered during an active turn, an earlier start is valid only with provider-observed `Latest turn
completed at` at or after the dispatch, `Dispatch consumed: true`, and `Dispatch consumption evidence` identifying
the accepted corrected result. A completion timestamp alone does not prove that a queued correction was consumed.
Missing
inventory entries, historical completion events and worker self-attestation alone do not establish terminal status. If
no supported targeted read can verify a worker, retain the blocked receipt.

Add `terminal_observations` to `runtime_closure.json`: one row per exact spawn identifier with `Provider handle`,
`Provider status`, `Last dispatch at`, `Observed at`, and `Status source` (`list_agents`, `read_thread`, or
`wait_threads`). Targeted rows also carry `Thread ID`, `Latest turn started at`, `Latest turn status`, and `Thread
status`. Use the normalized completed or idle status only from the provider response; `read_thread` with `notLoaded` may
qualify only with a completed latest turn and no newer dispatch. Preserve the raw response in current-run evidence. Do
not dispatch follow-ups during collection; a later follow-up invalidates that worker's observation and requires another
read. Record `provider status snapshot <RFC3339 timestamp>: <identifier>=completed; ...` in closure evidence. `Remaining
active handles: 0` means no active worker turns; it does not assert capacity release or handle destruction.
If neither closure route is verifiable, use the Coordinator-owned `Blocked` receipt with
`worker_runtime_release_unavailable` and unknown/nonzero remaining active handles. Do not ask the user to obtain an
unsupported close receipt; name the missing provider status/release capability and its adapter owner.

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

## Worker Identity and Correction Observations

A collaboration task handle is not a Codex thread UUID. Retain the exact spawn handle for collaboration operations;
use thread-read tools only with a provider-returned or verified mapped UUID. When no mapping/export exists, record
that specific capability absence once rather than repeatedly passing a task path to read_thread.
For prepared TechOps runs, use `runtime_evidence.collector` to extract this run's provider events into
`runtime_evidence.ledger`. Read only the verified current parent session, never memory or prior runs:

```bash
python3 <collector> --provider-session <current-parent-rollout.jsonl> \
  --parent-thread-id <verified-current-task-UUID> --started-at <prepared-run-start> --ledger <prepared-ledger>
```

Use `runtime_evidence.run_started_at` as the prepared run start. The collector verifies the parent identity,
extracts exact spawn/follow-up/message timestamps, preserves live
inventory responses unchanged and maps child UUIDs from `SubAgentActivity` metadata. Use those UUIDs for targeted
`read_thread`/`wait_threads` calls when live inventory omits a child. A metadata mapping proves identity, not current
completion. Sync after every dispatch and fresh inventory read; copy `Last dispatch at` from the latest matching
event, never from an earlier clock sample. The finalizer compares audits with current provider events and rejects
stale or edited ledgers. If this provider event route is unavailable, record that concrete capability failure once;
do not substitute invented times, shortened messages labeled raw, or historical completion for fresh closure.

For every follow-up, preserve the actual provider event time in the Coordinator dispatch ledger. That ledger
owns Last dispatch at in worker audits and closure observations. Invalidate the affected prior status/trace observation
in both records; after the correction ends, obtain a fresh provider observation and reconcile both records from it.
Revalidate the packet before collecting final closure evidence. If a worker is absent from inventory and no supported
lookup exists, retain Unknown/Blocked evidence; do not copy a historical observation or edit its time to appear fresh.

## Source Routing

For equivalent connected-source reads, try a configured direct MCP operation first, then an app-backed connector if
the direct operation is absent or fails. A tool exposed through an MCP namespace can still be an app-backed route;
select by the underlying connector, not the tool name alone. Use a browser only where the workflow allows it, never
to bypass a connector authentication or permission failure. Record the operation and route used.

## Jira Work-Item Read Mapping

For Jira-backed Feature Delivery, the Coordinator passes the connector and successful exact-key issue-read operation
to `feature-context`. The worker MUST use that connector first for every Jira scope. Discover its read-only operations
once and use the narrowest matching operation for each scope. If a required scope is absent, the worker may try one
distinct app-backed route only after a successful exact-key issue read there; record the connector used per scope and
any remaining unavailable scope. Do not silently switch to Rovo after a direct Atlassian MCP probe. The direct
Atlassian route may expose `mcp__atlassian__getJiraIssue`; use its available sibling operations for child searches,
remote links, history, and attachments, without assuming names or access. A resource lookup is not an issue read.

When Rovo is the bound connector, use these Codex operations for the shared
[Work-Item Read Contract](../contracts/workflow_execution.md#work-item-read-contract). Skills and playbooks consume
the normalized result rather than the connector payload.

| Shared scope | Codex operation | Boundary |
| --- | --- | --- |
| `item` | `mcp__codex_apps__atlassian_rovo_getjiraissue` | Read the exact `cloudId` plus issue key/ID with only the fields needed for the request. |
| `hierarchy` | `mcp__codex_apps__atlassian_rovo_getjiraissue` and bounded `mcp__codex_apps__atlassian_rovo_searchjiraissuesusingjql` | Read selected parent/ancestors by exact key; page through direct children only when the evidence question requires collection coverage. |
| `selected_links` | `mcp__codex_apps__atlassian_rovo_getjiraissue` and `mcp__codex_apps__atlassian_rovo_getjiraissueremoteissuelinks` | Read selected links with their reasons; inventory the complete direct-link collection only when the evidence question requires collection coverage. |
| `history` | `mcp__codex_apps__atlassian_rovo_getjiraissue` | Read selected comments, changelog, or attachment collections for in-scope issues; retrieve required asset contents through the configured connector. |
| `write_metadata` | `mcp__codex_apps__atlassian_rovo_getvisiblejiraprojects`, `mcp__codex_apps__atlassian_rovo_getjiraprojectissuetypesmetadata`, `mcp__codex_apps__atlassian_rovo_getjiraissuetypemetawithfields`, and `mcp__codex_apps__atlassian_rovo_gettransitionsforjiraissue` | Read live project, issue-type, field, allowed-value, or transition metadata only; this scope never performs a write. |

On Rovo, use `mcp__codex_apps__atlassian_rovo_searchjiraissuesusingjql` for bounded identity resolution and direct-child
enumeration when collection coverage is required, even when the Epic key is known. On other connectors, use the bound
route's equivalent. Query by exact
parent key (or the Jira instance's Epic-link field), bound the page size, and follow pagination until the collection
is complete or record `partial`. Do not substitute an unbounded project/board scan or natural-language cross-product
search. `cloudId` must come from configured provider context and must never be hardcoded or guessed.

If the connector is unavailable, use authoritative supplied context when present; otherwise return the shared
`unavailable` state. Preserve `not_found`, `empty`, `permission_denied`, `partial`, `stale`, and `conflict` rather than
coercing them to successful context. `work_item_read` MUST NOT invoke Jira create, edit, transition, comment, worklog,
or other write operations; approved writes use a separate capability and gate.

When attachment inventory is selected or required by the playbook, return an explicit complete, empty, partial,
unavailable, or permission-denied collection. For comments/changelog-only history, retain the normalized assets list
and record attachment inventory as not requested; do not imply an empty collection. Do not report a screenshot as
consumed from its filename,
description, or attachment count; the downstream asset manifest requires the stable locator and review result for each
available attachment.

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
