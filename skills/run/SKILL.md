---
name: run
description: >-
  Select and run the canonical AI Engineering Workflow Framework playbook for a work item. Use only when explicitly
  invoked to start a framework run.
---

# Run an AI Engineering Workflow

1. Treat the active installed `SKILL.md` location as authoritative. Derive the package root from that file
   (`Path(active_SKILL.md).parents[2]`); do not open or search a user-supplied cache path. A versioned path in the
   prompt is only a declared identity to compare, never an instruction to `sed`, `find`, `rg`, or search another cache
   version. Do not ask the user for a framework checkout path.
2. The first framework tool call after this skill is loaded MUST be package preflight. Before it, do not read memory,
   `PLAYBOOK_CATALOG.md`, any playbook, contract, provider definition, template, validator, sibling `.thoughts` root,
   or plugin cache directory. Run:
   `python3 <framework-root>/scripts/run_preflight.py`. The script derives the package root from its own location; do
   not construct or pass a separate framework-root argument.
   Pass `--declared-framework-revision <FULL-SHA>` when the prompt declares one, and pass
   `--declared-plugin-path <prompt-path>` only when the prompt contains an explicit versioned plugin path. A missing,
   stale, or different path is `plugin_revision_mismatch`; do not search another cache version or silently substitute
   a checkout. A dirty or mismatched framework is `framework_revision_mismatch`. Stop before worker activation and
   report the preflight reason and `preflight_elapsed_ms`. Treat a completed process with exit status 0 as a passed
   preflight even when the app hides stdout; do not rerun it solely because the JSON payload is not visible. Retry only
   after a timeout, nonzero exit, or an objectively malformed result whose status cannot be determined.
3. On a preflight block, create one minimal canonical blocked work record, populate its required Evidence, Claims,
   Decision Log, and Action Log chain in one pass, and run the validator once. Do not progressively rewrite the record,
   load the full playbook, query external systems, or activate workers. Record `worker_activation_attempts: 0` and the
   preflight reason in the handoff.
4. Treat the current working directory as the execution repository unless the user explicitly names another repository.
5. When the prompt supplies an existing playbook, use it directly and do not read `PLAYBOOK_CATALOG.md`; record the
   primary evidence, primary goal, closest alternative, and selection rationale from the supplied playbook and request.
   Read the catalog only when no playbook was supplied or the supplied path is unavailable or materially contradicted by
   the evidence. Make the requested profile and lifecycle explicit; when omitted, record the playbook defaults
   (`standard` + `planning`) before worker activation.
6. Relative to the verified packaged framework root, read the selected playbook, `contracts/workflow_execution.md`,
   `contracts/claims.md`, and the canonical run template declared by the playbook. Load the Codex provider adapter and
   model policy only when provider configuration is needed.
7. Run `scripts/prepare_run.py` with the execution repository, work item, selected playbook name, and optional verified
   runtime-agent directory (`--runtime-agents <path>`). Use `--continuation` only
   when the user explicitly says continue or resume. This one step
   archives a prior terminal run, creates the artifact root and minimal work record, and writes `role_bindings.json`.
   Treat that manifest as the spawn source of truth: pass each activated worker's exact model and effort, record its
   baseline ID and `provider_tool_mapping`, and stop if a required binding is absent. Framework tool IDs are abstract
   capability classes, not literal Codex tool names. Tell each worker to use the manifest's concrete mapping and never
   search `ALL_TOOLS` for a literal framework tool ID or block merely because that name is absent. A capability is
   unavailable only when its mapped operation is absent or an attempted in-scope operation fails. The active main
   session remains the Orchestrator with its
   already-selected model and effort; do not claim that the Orchestrator agent TOML changed the parent session.
   Record that active parent-session model and effort exactly as `Coordinator model/effort` so repeated-run comparisons
   expose Coordinator configuration differences.
   The Coordinator is the only role that performs package preflight and run preparation. Activate every delegated
   worker with `fork_context: false` or the provider-equivalent fresh-context option. Start its packet with
   `Coordinator initialization: complete` and explicitly prohibit rerunning this skill, `run_preflight.py`, or
   `prepare_run.py`. Workers must use the current task's in-task `spawn_agent`/collaboration runtime. Never use
   `create_thread`, `fork_thread`, or `send_message_to_thread` for workers. Verify the in-task runtime before
   `prepare_run.py`; when unavailable, stop with `worker_runtime_unavailable` without creating user-owned tasks.
8. Populate the canonical template from supplied and discoverable context. When the prompt requires current-run-only
   evidence, do not read memory, historical `.thoughts` artifacts, or prior-run citations at any later stage. The
   execution repository's `.codex/agents/`
   runtime view is optional. If absent, resolve the bundled provider definitions or selected work-graph model/effort
   binding; record the source and status, and never inherit unverified Coordinator settings. Active artifacts are direct
   children of the current `.thoughts/<WORK-ITEM-ID>/` root; do not search or reuse `runs/` archives unless the user
   explicitly requests continuation or recovery. Preserve template field
   names, use `Unknown` or `None` for unavailable values, and ask only for a business, scope, ownership, or approval
   decision that bounded discovery cannot resolve.
9. Execute the selected playbook. Default to `planning`; use `remediation` only when an implementation plan exists and
   the user has explicitly approved implementation. Treat an invocation that says start as a new run. Reuse current
   artifacts only when the user explicitly says continue or resume. Record the installed plugin
   name/version in Run Identity; manual runs use `Not applicable`. Populate evaluation identity and telemetry only when
   the request explicitly declares an evaluation or benchmark run.
10. Before terminal or blocked handoff, require the final Documenter to populate the prepared
   `finalization_packet.json` skeleton without changing its flat schema. Before activation, pass every required template
   field and the prompt template's frontmatter version; a framework commit is not a prompt-template revision. While that
   Documenter remains active, create a pending closure probe using the
   `templates/runtime_closure.json` schema and run:
   `python3 <packaged-framework-root>/scripts/finalize_work_record.py --pre-release --packet`
   `<execution-repository>/.thoughts/<WORK-ITEM-ID>/finalization_packet.json --closure`
   `<execution-repository>/.thoughts/<WORK-ITEM-ID>/runtime_closure.json --record`
   to validate the complete packet shape and candidate record without replacing `work_record.md`. Return the aggregated
   error to the owning worker and repeat.
   After the pre-release check passes, release the Documenter, replace the pending probe with exact provider
   observations as `runtime_closure.json` with `Receipt owner: Coordinator`, then run
   `python3 <packaged-framework-root>/scripts/finalize_work_record.py --packet`
   `<execution-repository>/.thoughts/<WORK-ITEM-ID>/finalization_packet.json --closure`
   `<execution-repository>/.thoughts/<WORK-ITEM-ID>/runtime_closure.json --record`
   `<execution-repository>/.thoughts/<WORK-ITEM-ID>/work_record.md`.
   The persisted packet is the Documenter's pre-release source snapshot. `runtime_closure.json` is the provider receipt,
   and the rendered `work_record.md` is the authoritative terminal state; do not require the source packet to be
   rewritten after provider release.
   Pin the preflight-resolved packaged framework root for the entire run. If it disappears or changes, stop with
   `plugin_revision_mismatch`; do not discover or switch to another installed package. A nonzero result is a handoff
   failure. Return packet, path, table, rendering, or closure errors to the same Documenter. Return errors naming Fix
   Design technical content, worker identity, readiness, blockers, diagnosis, or remediation boundary to the owning
   Fix Design worker before resuming the Documenter; never patch Markdown or technical fields by hand.
   Treat finalizer errors as self-contained received/expected corrections. Do not read or search validator source unless
   an error lacks an expected value or contradicts the documented packet contract.
   Finalization passes only when the exit status is zero and the
   first output line is exactly `Workflow-framework validation: passed`. Copy the subsequently emitted handoff block
   verbatim; do not regenerate or replace it with a compact status list. Before sending, verify the exact ordered labels
   `Workflow result:`,
   the fields `State:`, `Workflow outcome:`, `Engineering outcome:`, and `Implementation plan:`, then
   `What we established:`, optional
   `Best current explanations:`, `Next action:` with `Owner:`, `Action:`, and `Complete when:`, `Artifacts:`,
   `Execution:`, and `Provenance:`. Copy artifact links exactly from the finalized packet. Omit Run Metrics and Worker
   Timing for normal runs. The plugin does not override any canonical contract, playbook, template, role, skill, or
   provider policy.
