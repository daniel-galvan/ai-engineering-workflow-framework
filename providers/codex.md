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
record; this pre-initialization block is not an assessment disposition.

For Sentry Issue Remediation with an explicit issue ID or URL, apply the
[Sentry source-access gate](../integrations/sentry.md#source-access-gate) at the same pre-initialization boundary.
Read the exact issue and latest event; use the same `source_access_receipt.py` blocked path when required access fails.
Pass the successful route and observations to Evidence Topology. Do not substitute supplied logs for required live
access without the user's explicit selection of an offline investigation. Do not probe optional sources.

## Same-Session Decision Gate

When bounded discovery leaves a material user decision, the active parent Coordinator MUST ask it in this run's chat
with `functions.request_user_input` and wait for the answer. Ask at most three concise questions with enough
context to choose; do not use `request_user_input_async`, `send_message_to_thread`, or another chat to bypass the wait.
While the answer is pending, keep the run at `awaiting_input` and do not start dependent work or finalize/publish a
completed handoff. Record the answer in the current-run decision record, route it to the owning worker if its result
changes, and resume the same run. If the blocking tool is unavailable, ask in this chat and leave the run open until
the user replies; never report the pending question as completed. Missing access or external evidence uses the blocked
path rather than a user-decision question.

Before Documenter activation or finalization, audit the originating request, intake, and accepted Decision and
uncertainty rows for unanswered user-owned choices. Carry explicit unanswered questions into a fresh run as pending
inputs. A Coordinator-owned `planning interpretation`, recommendation, or assumption cannot settle a user-owned choice.
Current-code evidence shows existing behavior, not the user's desired behavior. Keep a material choice open and invoke
the gate unless an explicit current user decision or bounded evidence resolves it.

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

For Codex collaboration, `spawn_agent` may return only the collaboration task handle. That result identifies the
worker; it is not missing-configuration evidence. Reconcile the native parent-session `spawn_agent` call arguments
with its correlated `SubAgentActivity` `started` event, using the prepared runtime-evidence collector. The call records
the requested model, effort, and `fork_turns`; the start event maps the handle and thread UUID and reports model/effort
when exposed. Compare every reported value with the binding. Record unavailable applied telemetry as `Not exposed;`
with the exact launch arguments. Never interrupt a worker solely because the spawn result contains only its handle;
an explicit rejection or a returned mismatch still blocks acceptance.

## Model Capacity Recovery

Treat the explicit provider error `Selected model is at capacity` as a transient availability failure. Preserve its
exact text, affected parent or worker handle, Run ID, dispatch identity, observed status, failure time, and retry due
time in current-run evidence. For consecutive capacity failures of the same affected operation, wait 3 minutes after
the first failure, 5 minutes after the second, and 10 minutes after the third and each later failure. Reset this
backoff only after that operation successfully resumes. Honor cancellation and any existing run deadline.

Before each retry, refresh the affected parent and every dispatched worker's provider status. Collect work that
finished during the wait; do not dispatch again while execution is active or its status is unknown. Retry the same
model and effort on the existing handle when supported. Preserve the Run ID, accepted results, rejected traces,
dispatch ledger, and analytical correction count. Capacity retries do not consume the analytical correction
allowance. A successful message acknowledgement alone does not prove resumed execution; verify a new turn or
provider-observed consumption. Use supported continuation preparation to rebind an interrupted parent turn.

Apply this policy only to an explicit capacity error, not to an observation timeout, missing acknowledgement,
authentication failure, context violation, or rejected analytical result. Do not silently switch models, lower effort,
create a fresh run, or claim completion during backoff. Record each retry and its outcome. A changed model requires
explicit authorization and the ordinary binding checks.

An active Coordinator may wait using the host's interruptible wait mechanism and continue observing workers. If the
parent turn itself fails, it cannot wake or retry itself: recovery requires a still-running authorized supervisor or
a supported host retry mechanism. Without one, report the capacity error, next retry delay, known worker statuses,
and the exact same-chat resume action; do not promise an automatic retry. Refresh every activated handle and use
supported failure finalization when execution can no longer continue. Terminal worker status alone is not complete
runtime closure or publication.

## Runtime Closure

Every close/release instruction below uses the applicable provider route. When no close operation exists,
collect the fresh Terminal snapshot after pre-release instead of issuing a nonexistent close command.
For a provider with an explicit close/release operation, preserve its exact returned handle and release confirmation;
use `Runtime status: Released` only after all run workers are released and no active handles remain.
For Codex collaboration runtimes without a close operation, collect fresh status reads after pre-release and the last
correction/follow-up. Use `Runtime status: Terminal` only when these reads account for every activated worker, including
Documenter. The snapshot may combine live inventory and targeted reads; one inventory call need not retain every
completed worker. When `list_agents` omits a worker, try `read_thread` or `wait_threads` using its provider-observed
thread ID. Preserve the mapping to the exact spawn identifier from provider metadata; never guess an ID.

Distinguish message delivery from execution: `send_message` does not start an idle worker. Use `followup_task`
with the guarded activation message to start that worker's correction turn and refresh the dispatch ledger.
Verify that a new turn started; an acknowledgement alone does not prove execution. For an active turn, steering
through `send_message` still requires evidence of consumption before acceptance. Provider JSONL records file operations
as `custom_tool_call`/`custom_tool_call_output` or `function_call`/`function_call_output`,
not the app UI's `fileChange`.

An explicit `collab tool failed: agent thread limit reached` rejects the dispatch; it does not start a correction.
Refresh the ledger and targeted worker status, preserve completed results, and stop dispatch retries in this
invocation. Do not interrupt completed workers to free capacity or substitute `send_message` for a failed
`followup_task`. Collect fresh closure and use supported workflow-failure finalization when required correction
cannot execute; never leave the invocation at an unpublished narrative failure. Model-capacity backoff does not
apply to this different provider error.

A targeted closure read must show no active or pending thread and an inactive latest turn started at or after the
last dispatch.
For a correction delivered during an active turn, an earlier start is valid only with provider-observed
`Latest turn completed at` at or after the dispatch, `Dispatch consumed: true`, and
`Dispatch consumption evidence` identifying
the accepted corrected result. A completion timestamp alone does not prove that a queued correction was consumed.
Before requesting another turn, check for a provider-recorded corrected artifact write after the message and validate
that result against the specific requested correction. Record its tool-call identity, dispatch relationship, artifact
hash, and validation result as consumption
evidence; then refresh the same worker's status. Do not redispatch merely because its turn started before the message.
An empty or missing dispatch acknowledgement is unresolved, not an explicit provider failure. Preserve the attempted
dispatch and require mapped child execution plus a fresh terminal observation before fan-in. Explicit provider errors
remain failures; an empty acknowledgement or historical completion alone cannot authorize acceptance.
Export all worker activity from its first dispatch in the current run, preserving authenticated binding reads and
pre-correction context violations. Freshness still uses the latest dispatch. A failed required follow-up or message
blocks result export and successful finalization; a previous successful dispatch cannot substitute for it.
Failure closure still records current provider-observed inactivity after the attempted dispatch.
Missing inventory entries, historical completion events and worker self-attestation alone do not establish
terminal status.
If
no supported targeted read can verify a worker, retain the blocked receipt.

Add `terminal_observations` to `runtime_closure.json`: one row per exact spawn identifier with `Provider handle`,
`Provider status`, `Last dispatch at`, `Observed at`, and `Status source` (`list_agents`, `read_thread`, or
`wait_threads`). Targeted rows also carry `Thread ID`, `Latest turn started at`, `Latest turn status`, and `Thread
status`. Preserve the provider's exact inactive status: completed, idle, failed, stopped, interrupted, or cancelled.
`read_thread` with `notLoaded` may qualify only with an inactive latest turn and no newer dispatch. Worker result
acceptance still requires completed execution. Preserve the raw response in current-run evidence. Do
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

TechOps planning and Feature Delivery analytical agents may be configured read-only. Their prepared contracts require
one strict JSON final answer containing `output` and `result`; Feature `feature-context` also returns `asset_manifest`.
The packaged trace exporter snapshots that answer per dispatch, and the validated result merger writes the assigned
files only after acceptance. Do not ask these workers to write files or pre-create their result paths.

Framework tool IDs are provider-neutral capability classes, not literal Codex tool names. Use the
`provider_tool_mapping` emitted in `role_bindings.json`: repository reads, searches, history, builds, tests, and local
runtime inspection use `exec_command`; artifact and approved repository writes use `apply_patch`; connected runtime,
work-item, and scanner tools remain conditional. A worker MUST NOT search `ALL_TOOLS` for a literal framework tool ID
or report the capability unavailable merely because that name is absent. Report a capability unavailable only after
its mapped concrete operation is absent or an attempted in-scope operation fails.

## Worker Identity and Correction Observations

For ordinary results, the Coordinator joins the provider-returned spawn handle during fan-in. Do not send a
post-spawn message solely to supply that handle or request one from the worker. A missing worker-authored
handle is not a correction condition. Preserve the explicit Sentry Fix Design handle-delivery protocol when
its durable artifact requires the supplied handle. Every later message remains a dispatch requiring fresh
consumption evidence; do not ignore it or roll its timestamp back to the spawn.

A collaboration task handle is not a Codex thread UUID. Retain the exact spawn handle for collaboration operations;
use thread-read tools only with a provider-returned or verified mapped UUID. When no mapping/export exists, record
that specific capability absence once rather than repeatedly passing a task path to read_thread.
For prepared Sentry, TechOps, and Feature Delivery runs that declare `runtime_evidence`, use
`runtime_evidence.collector` to extract this run's provider events into
`runtime_evidence.ledger`. Read only the verified current parent session, never memory or prior runs:

Preflight and preparation resolve this record from `CODEX_THREAD_ID` (or `CODEX_SESSION_ID`) and native turn metadata.
Use their `parent_context.provider_session` and `parent_context.parent_thread_id`; an explicit source must match.
Same-chat continuation retains earlier current-run control metadata automatically. It imports no analytical outputs.

```bash
python3 <collector> --provider-session <current-parent-rollout.jsonl> \
  --parent-thread-id <verified-current-task-UUID> --started-at <prepared-run-start> --ledger <prepared-ledger>
```

Use `runtime_evidence.run_started_at` as the prepared run start. The collector verifies the parent identity,
extracts exact spawn/follow-up/message timestamps, preserves live
inventory responses unchanged and maps child UUIDs from `SubAgentActivity` metadata. Earlier bound fragments supply
current-run dispatch and status metadata across reopening; a Coordinator does not need to assemble that history.
Use those UUIDs for targeted
`read_thread`/`wait_threads` calls when live inventory omits a child. A metadata mapping proves identity, not current
completion. Sync after every dispatch and fresh inventory read; copy `Last dispatch at` from the latest matching
event, never from an earlier clock sample. Use the canonical binding key as the collector's `--agent` value, such as
`sentry_current_state_investigator`; do not substitute a stage label. After completion, call `list_agents`, then export
with `--worker-session`, `--agent`, and `--trace`, omitting `--observation`. The collector derives the selected worker's
receipt and observation time from the latest native inventory, even when other workers are still active. It rejects a
missing, active, or stale selected worker; it never falls back to an older inventory. When the worker is omitted, use
`--observation` with a fresh targeted read, including `Observed at` from that actual read and the required thread/turn
fields. Do not use turn completion time as observation time or fabricate binding flags.
`--worker-session` is the absolute native worker JSONL path, not the child UUID or collaboration handle. Locate
only filenames matching the verified `thread_mappings` UUID under `$CODEX_HOME/sessions` (default
`~/.codex/sessions`); select the record for the dispatched turn, not an older fragment. Do not read unrelated records
or guess the rollout timestamp. The exporter verifies the record's thread identity and dispatch-scoped turn.
 The collector fills an omitted `Last dispatch at` from its verified
ledger, rejects a conflicting value, and authenticates delivery through a paired read of the complete dispatch file.
A missing or malformed export is a collection failure, not proof that the worker failed. Before replacement, reconcile
metadata once through this collector without repeating analysis; preserve prior rejected traces and use a new trace
path. If collection still fails, report the framework blocker promptly instead of starting another analytical worker.
The finalizer compares audits with current provider events and rejects
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

For every required Jira read, including the launcher source-access probe, apply
[Transient Read Recovery](../integrations/jira.md#transient-read-recovery) before reporting a transient failure as
unavailable. Use the host's interruptible wait for backoff and retain pending tool handles through observation
timeouts. Bind this policy in Jira worker assignments along with the connector and operation. It does not authorize
retrying writes or replacing an active worker.

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
