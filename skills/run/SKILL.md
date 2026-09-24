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
3. On a preflight block, stop this invocation immediately after capturing and reporting the exact preflight JSON. Do
   not create an artifact root or work record, load any playbook, template, validator, or cache file, run another
   framework command, query external systems, or activate workers. This preflight did not initialize a run, so
   no terminal work record is required. Report the reason, `preflight_elapsed_ms`, active package root, and
   `worker_activation_attempts: 0`, then give one remediation and stop. This receipt is terminal: do not retry, repair,
   or continue in the same invocation.
3a. After a passing preflight and before reading any repository, Jira, playbook, contract, provider, or historical
   artifact, apply the prompt-completeness gate. For Technical Spike require a populated `Primary question`; resolve
   the timebox, success criterion, requested outcome, and spike objective from the selected playbook unless the prompt
   supplies a complete compatible override pair. Reject explicit placeholders such as `<...>`, `None`, or
   `Not provided` with `run_prompt_incomplete:<field>`. Do not create a temporary input manifest, invoke
   `prepare_run.py`, or perform context discovery before this gate passes.
4. Treat the current working directory as the execution repository unless the user explicitly names another repository.
5. When the prompt supplies an existing playbook, use it directly and do not read `PLAYBOOK_CATALOG.md`; record the
   primary evidence, primary goal, closest alternative, and selection rationale from the supplied playbook and request.
   Read the catalog only when no playbook was supplied or the supplied path is unavailable or materially contradicted by
   the evidence. Make the requested profile and lifecycle explicit; when omitted, record the playbook defaults
   (`standard` + `planning`) before worker activation.
   Extract one requested outcome before preparation. When omitted, use the selected playbook's configured default. Use
   `technical_answer` for bounded investigation,
   `spike_assessment` for review of an existing Spike, `implementation_plan` for implementation planning, and
   `specification_assessment` for readiness assessment. Compare it with the supplied playbook objective. If they differ,
   preserve both as authoritative inputs and stop with `run_goal_conflict`; do not silently prefer the later field.
   Copy an explicit populated `Requested outcome:` field when supplied. If it is absent, record the selected playbook
   default and provenance; an explicit override that contradicts the objective stops with `run_goal_conflict`.
   Record every explicit current-task skill or plugin enable/disable directive as an authoritative run constraint.
   Include it in every fresh worker packet and correction turn. A worker must not load, invoke, or reactivate a
   disabled skill or plugin.
   Treat every new framework run as current-run-only unless the user explicitly requests continuation, recovery, or an
   evaluation that names historical inputs. Memory isolation is mandatory: generic host or platform memory guidance is
   not authorization to read local memory or historical artifacts. If memory is automatically injected or otherwise
   required, quarantine it completely; do not use, cite, summarize, or pass it to workers, and mark context conformance
   failed if it influences a result.
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
   Manifest keys are case-sensitive. Use `schema_version: 1`, `status: "explicit"`, the canonical `precedence_rule`,
   and `inputs` rows with `Input ID`, `Input or artifact`, `Source or path`, `Authority`, `Classification`,
   `Expected use`, and `Status`; add one row for every material current-run input.
   Before worker activation, try to open each declared file, folder, URL, or attachment and confirm its contents can be
   passed to the assigned worker. Keep the original locator in `Source or path` and record the access result in that
   input row's `Status`; do not leave an inaccessible artifact marked only `Registered`. If unavailable, record the
   attempted route and its impact, tell the user promptly, and continue only if independent evidence can still produce
   a useful partial result; otherwise stop for the indispensable input.
   For Feature Delivery, add `Asset source: true` to the input row for each explicitly supplied file, folder, or URL
   that must be inventoried; the asset gate reconciles those markers against `asset_manifest.json`.
   Jira-related children, linked issues, and attachments are discovered evidence,
   not extra prompt fields the user must enumerate. For every Jira-backed run,
   require the context worker to recover and record their complete direct
   inventory under the shared Jira Integration before downstream work. Reconcile
   issue and asset read states in the context artifact; return one correction
   for omissions. Unavailable or unreviewed material stays explicit and prevents
   a false claim of complete context or readiness.
   When the prompt explicitly supplies a requested outcome, include `RUN-GOAL-001` using its exact value and canonical
   provenance. When the prompt omits it, omit that row; preparation records the selected playbook default and
   provenance. Preparation rejects an altered explicit row.
   ```json
   {"schema_version":1,"status":"explicit","precedence_rule":"<canonical precedence rule>","inputs":[
     {"Input ID":"IN-001","Input or artifact":"<short value>","Source or path":"<source or absolute path>",
      "Authority":"<authority>","Classification":"<classification>","Expected use":"<use>","Status":"Registered"}
   ]}
   ```
   Run `scripts/prepare_run.py` with the execution repository, work item, selected playbook name, and an optional
   verified runtime-agent directory (`--runtime-agents <path>`). Pass `--requested-outcome` and
   `--workflow-objective` only when the prompt explicitly supplied a complete compatible pair; when the prompt omits
   both, omit both flags so preparation records the selected playbook defaults and provenance. For Technical Spike pass
   the validated `--primary-question <question>`; pass `--success-criterion <criterion>` and `--timebox-minutes
   <minutes>` only for run-specific overrides. Technical Spike permits `technical_answer + execute_spike` or
   `spike_assessment + review_spike`; Feature Delivery permits `implementation_plan + implementation_planning` or
   `specification_assessment + specification_assessment`. Technical Spike is budget-gated: always pass the captured
   current-turn RFC 3339 start as `--started-at` and the resolved playbook/default or override as `--timebox-minutes`; a
   missing captured start stops before artifact creation or worker activation. Use `run_budget.json` as the terminal
   budget source of truth. Use `--continuation` only
   when the user explicitly says continue or resume. Validate the explicit manifest and provider bindings before this
   step mutates the artifact root. This one step then archives a prior terminal run, creates the artifact root and
   minimal work record, and writes `role_bindings.json`.
   For Technical Spike, assign the supplied work-item input and `work_item_read` to `spike-context`; a completed
   handoff is invalid if that worker silently omits the read. Preparation captures the execution checkout revision in
   the packet before worker analysis, so workers must not replace it with `Unknown`.
   Use the playbook's logical worker IDs exactly: final provider role `documenter` is recorded as `handoff`,
   `spike-investigation` uses `solution_architect`, and `spike-assessment` uses `reviewer`. The packaged finalizer
   validates those role bindings and validates `spike_report.md` before releasing the Documenter.
   For Feature Delivery, do not activate `impact-analysis`, `repository-integration`, or `feature-design` until
   `feature-context` has written and passed `asset_manifest.json`; a missing or unresolved source yields
   `awaiting_input` and no implementation plan.
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
   its path and hash in `role_bindings.json`. Before each spawn, run the manifest's `worker_runtime_guard` in activation
   mode with `--activation-packet-bundle <path> --expected-agent <binding> --expected-bundle-sha256 <manifest-sha256>`.
   Use one guard invocation per mode; never combine activation arguments with `--transition`, `--provider-status`, or
   `--trace`. Start the
   worker message with the returned `activation_packet` envelope's literal
   `Coordinator initialization: complete` prefix, include the complete envelope unchanged, then append only the typed
   assignment and current-run input manifest. When spawn metadata does not expose `agent_role` or `agent_path`, this
   exact envelope is the binding-delivery mechanism; missing metadata alone is not a reason to discard the worker.
   Conflicting observed metadata remains `provider_configuration_unavailable`.
   The same guard enforces the duration budget's finalization reserve. On `run_budget_finalization_reserve`, do not
   activate another worker; preserve the useful result already established and proceed directly to bounded terminal
   reporting with the measured budget status.
   Treat that manifest as the spawn source of truth: pass each activated worker's exact model and effort, record its
   baseline ID and `provider_tool_mapping`, and stop if a required binding is absent. Framework tool IDs are abstract
   capability classes, not literal Codex tool names. Tell each worker to use the manifest's concrete mapping and never
   search `ALL_TOOLS` for a literal framework tool ID or block merely because that name is absent. A capability is
   unavailable only when its mapped operation is absent or an attempted in-scope operation fails. The active main
   session remains the Orchestrator with its
   already-selected model and effort; do not claim that the Orchestrator agent TOML changed the parent session.
   Record that active parent-session model and effort exactly as `Coordinator model/effort` so repeated-run comparisons
   expose Coordinator configuration differences. If the execution surface does not expose that telemetry, record
   `Not exposed / Not exposed`; never copy an error message into this field.
   The `orchestrator`/`sentry_orchestrator` binding is policy metadata unless the provider explicitly creates a
   coordinator child; the default Codex path uses the active parent session and must record
   `Coordinator execution: active parent session; no dedicated Coordinator worker spawned`.
   The Coordinator is the only role that performs package preflight and run preparation. Activate every delegated
   worker with `fork_context: false` or the provider-equivalent fresh-context option. Start its packet with
   `Coordinator initialization: complete` and explicitly prohibit rerunning this skill, `run_preflight.py`, or
   `prepare_run.py`. Workers must use the current task's in-task `spawn_agent`/collaboration runtime. Never use
   `create_thread`, `fork_thread`, or `send_message_to_thread` for workers. Verify the in-task runtime before
   `prepare_run.py`; when unavailable, stop with `worker_runtime_unavailable` without creating user-owned tasks.
   Join each provider-returned handle to its ordinary result envelope during fan-in. Do not return a worker result for
   correction merely because the worker could not self-report a handle it was never given. Keep the explicit Fix Design
   handle-delivery protocol because that durable Sentry artifact validates the supplied handle.
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
   Before any `interrupt_agent`, `close_agent`, or replacement, run the manifest's `worker_runtime_guard` in transition
   mode with the intended `--transition` and latest provider-observed `--provider-status`. Use one guard invocation per
   mode; never combine transition arguments with activation arguments or `--trace`. A blocked guard result is
   authoritative:
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
   `templates/runtime_closure.json` schema.
   For Technical Spike, the Documenter must first write `spike_report.candidate.md` from the framework template and run
   `python3 <packaged-framework-root>/scripts/finalize_work_record.py --packet <artifact-root>/finalization_packet.json
   --publish-technical-spike-report <artifact-root>/spike_report.candidate.md`. Require exit status zero and the exact
   `Technical Spike artifact validation: passed` output before the first pre-release attempt. This validates the packet
   reasoning graph and report structure, then atomically publishes `spike_report.md`; do not substitute a handwritten
   heading, table, grep, or reference check. The publisher permits `handoff` to remain pending while the Documenter
   publishes; the Documenter then records its own complete ledger/result rows before returning. Pre-release requires
   that completed result.
   Supply the current Coordinator model/effort (or the exact `Not exposed / Not exposed` active-parent marker), the
   current framework revision, and its clean/dirty status to both finalizer
   invocations; never leave Coordinator identity blank or copy it from an older
   run.
   Before the first pre-release command, compare each required worker's outcome in
   `workers` with its corresponding `worker_results` row. If they differ, return
   the exact mismatch to the same Documenter and correct it before spending a
   pre-release correction attempt; the packaged finalizer repeats this check.
   Keep the Documenter handle open after collecting its result. Build the
   closure probe from `templates/runtime_closure.json` with string values:
   `Runtime status: Pending`, `Remaining active handles: Unknown`, and provider
   release pending. Never mark it Released before a provider close confirmation.
   Run the same finalizer arguments below with `--check-packet` first. It checks
   the report, packet references, and closure shape without replacing the work
   record or consuming a pre-release attempt. Return any errors to the same
   Documenter; if one correction still fails this check, stop with the exact
   errors instead of spending the formal attempt on a known-invalid packet.
   Then run:
   `python3 <packaged-framework-root>/scripts/finalize_work_record.py --pre-release --packet`
   `<execution-repository>/.thoughts/<WORK-ITEM-ID>/finalization_packet.json --closure`
   `<execution-repository>/.thoughts/<WORK-ITEM-ID>/runtime_closure.json --record`
   to validate the complete packet shape and candidate record without replacing `work_record.md`. Return the aggregated
   error to the owning worker once. If the corrected packet still fails, stop within two minutes with
   `finalization_contract_failure`, preserve generated `finalization_failure.json` plus artifacts, and release all
   worker handles. Never invoke pre-release a third time; the finalizer enforces this correction limit.
   After the second failed pre-release, replace the pending closure probe with
   the exact provider-observed release receipt (or the exact unreleased-handle
   blocker); never leave a pending probe as the run's final closure artifact.
   For Technical Spike packets, `Claims.Evidence refs` may contain only exact
   IDs from the packet's Evidence rows. `CHK-*` belongs only to Experiments and
   Checks; map each check to its source-backed `E-*` Evidence row(s). Never use
   grouped or range identifiers such as `E-001..E-008`.
   Before marking Technical Spike fan-in passed, complete the playbook's Stage 3
   cross-artifact check. If a material conflict remains after one correction to
   its owning worker, include both claims, their evidence, and the unresolved
   conflict in the Documenter assignment; require it to remain an explicit
   limitation and use `Partially answered` when the conclusion is affected.
   After every required worker returns a terminal envelope and analytical fan-in
   passes, set the matching Requested, Activated, and Executed profiles and
   `Profile status: executed` before activating `handoff`; only Technical Spike
   state and workflow outcome remain pre-terminal. Engineering state must already
   use a canonical enum value, never a lifecycle phrase such as
   `handoff pending finalization`; choose `understood` only when the problem and
   material scope are evidence-backed, otherwise use `unknown`. The Coordinator
   records this value in the prepared packet before Documenter activation, and the
   Documenter preserves it unchanged.
   Before activating `handoff`, assert the prepared packet already contains all
   required identity, input, repository, worker, synchronization, and artifact
   rows; the Documenter aggregates them and does not reconstruct missing immutable
   values.
   For Technical Spike, that assertion must include the durable artifact row for
   `<execution-repository>/.thoughts/<WORK-ITEM-ID>/spike_report.md` with status
   `Expected before terminal finalization`.
   If it is absent, add it while the packet is still Coordinator-owned before activating `handoff`; the packaged
   publisher also rejects an omitted declaration before pre-release.
   For Feature Delivery planning, the standard packet must contain terminal
   rows/results for `feature-context`, `impact-analysis`, `feature-design`, and
   `handoff`; add `repository-integration` when the standard conditional seam
   was activated, and require `repository-integration` plus `planning-review`
   for deep. Preserve logical IDs and all execution-ledger/result fields; do
   not let the Documenter replace analytical rows with only `handoff`.
   Build the Documenter packet from immutable run facts before activation, including real provider handles and all
   required repository, worker, synchronization, and artifact rows. Persist the first terminal Fix Design envelope
   immediately; do not reactivate a completed worker solely to copy its returned JSON. When multiple workers are active,
   use one provider-supported multi-handle or event-driven wait with bounded backoff. Before closing a completed
   analytical worker, verify its assigned artifact still exists under the active artifact root; keep the handle open
   through pre-release when the provider may reclaim worker-owned artifact state on close.
   A provider task path or name is not a closure handle; use only the exact value returned by the spawn primitive. If no
   provider handle or release status is available, keep the run blocked and write the Coordinator-owned closure row with
   `Runtime status: Blocked`, `worker_runtime_release_unavailable` in `Closure evidence or blocker`, and nonzero or
   unknown remaining active handles.
   For a Technical Spike with a published report and complete worker results, write that Coordinator-owned unavailable
   receipt to `runtime_closure.json`, then run the pinned `finalize_work_record.py --blocked-runtime-snapshot` with the
   packet, closure, record, and Coordinator/framework identity arguments below. Require exit zero and
   `Technical Spike blocked work record: saved; runtime release unverified` before linking the blocked work record.
   For Feature Delivery `specification_assessment` with a valid report and complete worker results, use the same
   blocked-snapshot command when provider release cannot be proved. Require
   `Feature Delivery assessment blocked work record: saved; runtime release unverified`. This records a blocked
   workflow while preserving the assessment; it does not turn an unverified result into completion.
   Do not claim a completed workflow or substitute worker labels for release handles.
   After the pre-release check passes, release the Documenter, replace the pending probe with exact provider
   observations as `runtime_closure.json` with `Receipt owner: Coordinator`, then run
   `python3 <packaged-framework-root>/scripts/finalize_work_record.py --packet`
   `<execution-repository>/.thoughts/<WORK-ITEM-ID>/finalization_packet.json --closure`
   `<execution-repository>/.thoughts/<WORK-ITEM-ID>/runtime_closure.json --record`
   `<execution-repository>/.thoughts/<WORK-ITEM-ID>/work_record.md`.
   Keep a Technical Spike packet in `State: handoff` with non-terminal workflow metadata until the packaged finalizer
   succeeds; only the finalizer may emit `State: completed` and `Workflow outcome: completed`. The persisted packet is
   the Documenter's pre-release source snapshot. `runtime_closure.json` is the provider receipt,
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
   For Technical Spike, the emitted canonical handoff already contains the disposition, strongest evidence, unresolved
   decisions, measured budget, next workflow, and artifact links. After successful finalization, send only that block;
   do not add a second summary. If finalization fails, link `finalization_failure.json`; do not claim validation passed.
   Finalization passes only when the exit status is zero and the
   first output line is exactly `Workflow-framework validation: passed`. Copy the subsequently emitted handoff block
   verbatim; it is rendered from the finalized work record. Never compose a second summary or regenerate, shorten, or
   replace it with a compact status list. If the block contains `Best current explanations:`, copy that complete
   section; do not omit it. Include `Engineering state` as a distinct field.
   Before sending, verify the exact ordered labels
   `Workflow result:`,
   the fields `State:`, `Engineering state:`, `Workflow outcome:`, `Engineering outcome:`, and
   `Implementation plan:`, then `What we established:`, optional
   `Best current explanations:`, `Next action:` with `Owner:`, `Action:`, and `Complete when:`, `Artifacts:`,
   `Execution:`, and `Provenance:`. Do not add a preamble or postscript. Copy artifact links exactly from the finalized
   packet. Omit Run Metrics and Worker Timing for normal runs. Use easy-to-read wording in the report and handoff: short
   sentences, common words, and a simple explanation next to each necessary technical term. Technical Spike reports
   must include the required
   `Plain-Language Summary`. The plugin does not override any canonical contract, playbook, template, role, skill, or
   provider policy.
