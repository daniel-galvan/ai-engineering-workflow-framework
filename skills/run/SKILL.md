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
   Record every explicit current-task skill or plugin enable/disable directive as an authoritative run constraint.
   Include it in every fresh worker packet and correction turn. A worker must not load, invoke, or reactivate a
   disabled skill or plugin.
   Treat every new framework run as current-run-only unless the user explicitly requests continuation, recovery, or an
   evaluation that names historical inputs. After preflight, do not read memory or prior-run artifacts for convenience;
   if higher-priority runtime instructions force a memory pass, quarantine it from evidence, decisions, and worker
   input.
   Before analytical fan-in, audit each provider tool trace when exposed with
   `python3 <framework-root>/scripts/validate_worker_runtime.py --trace <current-run-trace.json>`.
   Treat `forbidden_context_reference:*` or `context_conformance_failed` as contamination and do not fan in that
   result. If no trace is exposed, record context conformance as `context-unverified` and do not imply an
   independently audited pass. The Pilot Standard finalizer may continue with the worker's self-attested result when
   every other contract gate passes; trace-unavailable evidence is never stronger than self-attestation.
6. For Standard Sentry planning, do not hydrate the complete playbook, generic work-record template, execution contract,
   or claims contract before preparation. Read only the selected playbook frontmatter needed for identity/version; this
   launcher plus the prepared worker contracts and binding manifest are the compact runtime surface. For every other
   playbook/profile/lifecycle, relative to the verified packaged framework root, read the selected playbook,
   `contracts/workflow_execution.md`, `contracts/claims.md`, and its canonical run template once. Do not also read a
   checkout copy or restart a document from line 1 after reading an earlier range. Load the Codex provider adapter and
   model policy only when provider configuration is needed.
7. Before preparation, create a run-specific JSON input manifest from every material detail in the current request:
   explicit decisions and constraints, observed reports, hypotheses, repository paths, and named supporting artifacts.
   Use stable Input IDs and include each item's short value, source/path, authority, classification, expected use, and
   status. Use `apply_patch` to create the temporary JSON file when no manifest file already exists, preferably outside
   the execution repository (for example under `/tmp`) so preparation cannot make the source checkout appear dirty.
   The manifest has top-level `schema_version: 1`, `status: "explicit"`, a non-empty `inputs` list, and the canonical
   `precedence_rule`; if that key is omitted, preparation applies the canonical default, while an explicit empty value
   remains invalid. Pass the file to `scripts/prepare_run.py` with
   `--input-manifest <path>`. The helper copies and hashes it as
   `<execution-repository>/.thoughts/<WORK-ITEM-ID>/run_inputs.json`; if the prepared result reports
   `run_input_manifest_status: generated_minimum`, stop with `run_input_manifest_required` before activating a worker.
   Run `scripts/prepare_run.py` with the execution repository, work item, selected playbook name, and optional verified
   runtime-agent directory (`--runtime-agents <path>`). Use `--continuation` only
   when the user explicitly says continue or resume. Validate the explicit manifest and provider bindings before this
   step mutates the artifact root. This one step then archives a prior terminal run, creates the artifact root and
   minimal work record, and writes `role_bindings.json`.
   Capture the current turn start before checking provider-visible tasks. If a new `Start` returns
   `existing_run_not_terminal`, check provider-visible tasks and worker handles. Exclude the task created for the
   current invocation: a task created at or after the captured current turn start is the current run and MUST NOT be
   classified as a related run. A provider-visible task can block startup only when it predates the current turn and is
   independently active. When the prior
   task is idle and no active handle or artifact writer remains, rerun once with `--archive-stale-run`; this preserves
   every stale artifact under `runs/stale-<timestamp>/` and creates a fresh run. If activity is present or cannot be
   verified, stop with `run_already_active`. Do not tell the user to request continuation when they requested a new run.
   Copy `provider_configuration_source_status` from its result into Run Identity; do not infer provider status from a
   `find -type f` result because a valid runtime view may consist of symlinked definitions.
   Preparation also writes exact role envelopes to the direct-child `worker_activation_packets.json` bundle and records
   its path and hash in `role_bindings.json`. Before each spawn, run the manifest's `worker_runtime_guard` with
   `--activation-packet-bundle <path> --expected-agent <binding> --expected-bundle-sha256 <manifest-sha256>`. Start the
   worker message with the returned `activation_packet` envelope's literal
   `Coordinator initialization: complete` prefix, include the complete envelope unchanged, then append only the typed
   assignment and current-run input manifest. When spawn metadata does not expose `agent_role` or `agent_path`, this
   exact envelope is the binding-delivery mechanism; missing metadata alone is not a reason to discard the worker.
   Conflicting observed metadata remains `provider_configuration_unavailable`.
   Treat that manifest as the spawn source of truth: pass each activated worker's exact model and effort, record its
   baseline ID and `provider_tool_mapping`, and stop if a required binding is absent. Framework tool IDs are abstract
   capability classes, not literal Codex tool names. Tell each worker to use the manifest's concrete mapping and never
   search `ALL_TOOLS` for a literal framework tool ID or block merely because that name is absent. A capability is
   unavailable only when its mapped operation is absent or an attempted in-scope operation fails. The active main
   session remains the Orchestrator with its
   already-selected model and effort; do not claim that the Orchestrator agent TOML changed the parent session.
   Record that active parent-session model and effort exactly as `Coordinator model/effort` so repeated-run comparisons
   expose Coordinator configuration differences.
   The `orchestrator`/`sentry_orchestrator` binding is policy metadata unless the provider explicitly creates a
   coordinator child; the default Codex path uses the active parent session and must record
   `Coordinator execution: active parent session; no dedicated Coordinator worker spawned`.
   The Coordinator is the only role that performs package preflight and run preparation. Activate every delegated
   worker with `fork_context: false` or the provider-equivalent fresh-context option. Start its packet with
   `Coordinator initialization: complete` and explicitly prohibit rerunning this skill, `run_preflight.py`, or
   `prepare_run.py`. Workers must use the current task's in-task `spawn_agent`/collaboration runtime. Never use
   `create_thread`, `fork_thread`, or `send_message_to_thread` for workers. Verify the in-task runtime before
   `prepare_run.py`; when unavailable, stop with `worker_runtime_unavailable` without creating user-owned tasks.
8. Keep the prepared Standard Sentry `work_record.md` skeleton unchanged until deterministic finalization. On other
   paths, populate the canonical template from supplied and discoverable context. When the prompt requires
   current-run-only
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
   The current-run input manifest is authoritative for supplied decisions, context, and artifacts. If a Sentry issue ID
   or live runtime source is also supplied, use it as additive evidence unless the user explicitly selected live-only
   analysis; never replace named supporting artifacts with live results. Every material input must be consumed by an
   assigned worker or explicitly marked unavailable, conflicting, or out of scope before Fix Design can reach readiness.
   For Standard Sentry planning, activate Evidence Topology first with the exact `normalized_evidence_contract` and
   output paths returned by `prepare_run.py`. Validate its completed `normalized_evidence.md`, then run any playbook-
   required conditional analytical worker. Activate Fix Design with every validated analytical input, the exact
   `fix_design_result_contract`, and its assigned `fix_design_result.json` output path. Do not parallelize these
   dependent stages. Immediately send Fix Design its provider-returned activation handle and require it to wait for
   that value before writing its envelope. The Coordinator validates the assigned file and never reconstructs its JSON
   from a worker message. Require Evidence Topology to
   run `validate_library.py --normalized-evidence <artifact-path>` before its first terminal response.
10. After analytical fan-in, run
   `python3 <packaged-framework-root>/scripts/normalize_fix_design_result.py --artifact-root`
   `<execution-repository>/.thoughts/<WORK-ITEM-ID>`. This deterministic producer-format repair runs before validation
   and does not consume the analytical correction allowance. It may only preserve equivalent values in canonical field
   types; a blocked normalization is returned to Fix Design with the other aggregated errors.
   Then run
   `python3 <packaged-framework-root>/scripts/validate_library.py --sentry-artifacts`
   `<execution-repository>/.thoughts/<WORK-ITEM-ID>` for Sentry planning. Return Evidence Topology errors to that worker
   and Fix Design schema/readiness errors to Fix Design. Send each analytical worker at most one aggregated correction.
   If its corrected result still fails, stop with `analytical_contract_failure`, preserve the validation errors and
   artifacts, and release all handles; do not make the Documenter repair upstream artifacts. Count the correction only
   after a terminal response and revalidation. Then mechanically finalize the packet, runtime closure receipt, and work
   record before answering; never leave the prepared record in `intake` or `Pending`. Run
   `finalize_work_record.py --packet <packet> --closure <closure> --record <record> --analytical-failure <error>`
   `--analytical-failure-stage <evidence_topology|repository_integration|fix_design>`
   `--completed-handle <released-handle>` once for every released analytical worker, then
   `--coordinator-model-effort <model/effort>`
   `--framework-revision <preflight-sha> --framework-status <clean|dirty>`. Pass
   `--evidence-artifact <artifact>` when normalized evidence exists; an Evidence Topology runtime failure before
   artifact creation intentionally omits it.
   When provider tool traces are exposed, pass each validated trace as
   `--worker-trace <worker>=<absolute-trace-path>`; if none are exposed, the finalizer records the audit as unavailable
   instead of implying independent context conformance. Do not load the `sentry` skill or invoke a Sentry MCP/app from
   the Coordinator before Evidence Topology activation; raw Sentry access is worker-owned.
   When Standard Sentry Fix Design returns either `ready_for_implementation/create` or `awaiting_input/omit`, do not
   activate a Documenter. Release every activated analytical handle, then run the manifest's
   `standard_planning_finalization.finalizer` (`scripts/finalize_sentry_planning.py`) exactly once with the artifact
   root, Evidence Topology handle, actual
   Coordinator model/effort, preflight framework revision/status, every relevant repository as
   `--repository 'ROLE=/absolute/path'`, and each conditional worker as
   `--completed-worker 'WORKER=UUID'`. Include only conditional workers that actually activated; omit a skipped
   conditional worker and let the finalizer record its `not_applicable` decision. Provider-role aliases for the two
   implicit workers are accepted only when their handles match the implicit Evidence/Fix results. Pass
   `--provider-release-confirmed` only after every activated analytical release succeeds.
   Before any `interrupt_agent`, `close_agent`, or replacement, run the manifest's `worker_runtime_guard` with the
   intended `--transition` and latest provider-observed `--provider-status`. A blocked guard result is authoritative:
   leave a `pending_init`, `running`, `in_progress`, or `awaiting_dependency` worker active and wait again or leave the
   run open. Never interrupt a live worker to satisfy an elapsed-time target.
   That deterministic finalizer copies the exact Fix Design disposition and, according to the validated readiness/action
   pair, creates either `implementation_plan.md` or `clarification_brief.md`. It stages and validates that artifact, the
   runtime-closure receipt, `finalization_packet.json`, and terminal `work_record.md`, then publishes the terminal set
   transactionally. It is the only Standard planning finalization writer. Do not pre-render or hand-edit generated
   Markdown, construct a candidate packet, run `finalize_work_record.py --pre-release`, or activate a documentation
   worker for either Standard planning readiness result.
   Deep planning and remediation retain their playbook-defined Documenter stage. On those paths, require the final
   Documenter to populate the prepared
   `finalization_packet.json` skeleton without changing its flat schema. Before activation, pass every required template
   field and the prompt template's frontmatter version; a framework commit is not a prompt-template revision. While that
   Documenter remains active, create a pending closure probe using the
   `templates/runtime_closure.json` schema and run:
   `python3 <packaged-framework-root>/scripts/finalize_work_record.py --pre-release --packet`
   `<execution-repository>/.thoughts/<WORK-ITEM-ID>/finalization_packet.json --closure`
   `<execution-repository>/.thoughts/<WORK-ITEM-ID>/runtime_closure.json --record`
   to validate the complete packet shape and candidate record without replacing `work_record.md`. Return the aggregated
   error to the owning worker once. If the corrected packet still fails, stop within two minutes with
   `finalization_contract_failure`, preserve the aggregated error and artifacts, and release all worker handles.
   Build the Documenter packet from immutable run facts before activation, including real provider handles and all
   required repository, worker, synchronization, and artifact rows. Persist the first terminal Fix Design envelope
   immediately; do not reactivate a completed worker solely to copy its returned JSON. When multiple workers are active,
   use one provider-supported multi-handle or event-driven wait with bounded backoff.
   After the pre-release check passes, release the Documenter, replace the pending probe with exact provider
   observations as `runtime_closure.json` with `Receipt owner: Coordinator`, then run
   `python3 <packaged-framework-root>/scripts/finalize_work_record.py --packet`
   `<execution-repository>/.thoughts/<WORK-ITEM-ID>/finalization_packet.json --closure`
   `<execution-repository>/.thoughts/<WORK-ITEM-ID>/runtime_closure.json --record`
   `<execution-repository>/.thoughts/<WORK-ITEM-ID>/work_record.md`.
   The persisted packet is the Documenter's pre-release source snapshot. `runtime_closure.json` is the provider receipt,
   and the rendered `work_record.md` is the authoritative terminal state; do not require the source packet to be
   rewritten after provider release. The finalizer mechanically owns released runtime status, final reconciliation,
   finalization-schema status, runtime-closure artifact status, and removal of obsolete finalization steps from the next
   action.
   Pin the preflight-resolved packaged framework root for the entire run. If it disappears or changes, stop with
   `plugin_revision_mismatch`; do not discover or switch to another installed package. A nonzero result is a handoff
   failure. On a deterministic Standard planning failure, stop with `finalization_contract_failure`; do not add a
   Documenter fallback or patch generated artifacts. For Documenter-owned paths, return packet, path, table, rendering,
   or closure errors to the same Documenter. Return errors naming Fix
   Design technical content, worker identity, readiness, blockers, diagnosis, or remediation boundary to the owning
   Fix Design worker before resuming the Documenter; never patch Markdown or technical fields by hand.
   Treat finalizer errors as self-contained received/expected corrections. Do not read or search validator source unless
   an error lacks an expected value or contradicts the documented packet contract.
   Finalization passes only when the exit status is zero and the
   first output line is exactly `Workflow-framework validation: passed`. Copy the subsequently emitted handoff block
   verbatim; it is rendered from the finalized work record. Do not compose a second summary or regenerate or replace it
   with a compact status list. Before sending, verify the exact ordered labels
   `Workflow result:`,
   the fields `State:`, `Workflow outcome:`, `Engineering outcome:`, and `Implementation plan:`, then
   `What we established:`, optional
   `Best current explanations:`, `Next action:` with `Owner:`, `Action:`, and `Complete when:`, `Artifacts:`,
   `Execution:`, and `Provenance:`. Copy artifact links exactly from the finalized packet. Omit Run Metrics and Worker
   Timing for normal runs. The plugin does not override any canonical contract, playbook, template, role, skill, or
   provider policy.
