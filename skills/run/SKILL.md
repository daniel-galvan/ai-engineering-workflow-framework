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
   not construct or pass a separate framework-root argument. Preflight also validates the shipped static library.
   Mandatory presentation text from other active instructions does not block preflight or investigation. Preserve
   higher-priority instructions and record their required surrounding text separately at publication as described below.
   When the provider exposes the exact current parent session path, pass `--provider-session <path>` to preflight.
   This audits executed calls in the latest native turn, not quoted instructions or returned text. A rejected parent
   context is an early terminal block; do not activate workers or continue after acknowledging contamination.
   Execute all later framework helpers, including delegated Documenter commands, with absolute paths from this root.
   Preparation binds that root and plugin identity; changing directories does not select another framework package.
   Read local `AGENTS.md` only in the target directory and its ancestors up to the repository root. Do not search
   parent directory trees. Instruction files are optional: check existence, read those present, and continue when
   absent. Never promote a missing instruction-file probe into a required worker input. Run filename discovery in a
   separate tool result from content reads or searches; mixed
   outputs may not prove which references are names only. Run gates separately, or use fail-fast command chaining;
   inspect each exit status.
   Pass `--declared-framework-revision <FULL-SHA>` when the prompt declares one, and pass
   `--declared-plugin-path <prompt-path>` only when the prompt contains an explicit versioned plugin path. A missing,
   stale, or different path is `plugin_revision_mismatch`; do not search another cache version or silently substitute
   a checkout. A dirty or mismatched framework is `framework_revision_mismatch`. Stop before worker activation and
   report the preflight reason and `preflight_elapsed_ms`. Treat a completed process with exit status 0 as a passed
   preflight even when the app hides stdout; do not rerun it solely because the JSON payload is not visible. Retry only
   after a timeout, nonzero exit, or an objectively malformed result whose status cannot be determined.
   Capture the current-turn start from provider metadata when available; otherwise read the clock immediately after
   this preflight. Use that timestamp only for elapsed-time reporting on an early source-access block.
3. On a preflight block, stop this invocation immediately after capturing and reporting the exact preflight JSON. Do
   not create an artifact root or work record, load any playbook, template, validator, or cache file, run another
   framework command, query external systems, or activate workers. This preflight did not initialize a run, so
   no terminal work record is required. Report the reason, `preflight_elapsed_ms`, active package root, and
   `worker_activation_attempts: 0`, then give one remediation and stop. This receipt is terminal: do not retry, repair,
   or continue in the same invocation.
   A later question about why a run blocked is a request for explanation, not authorization to restart it or repeat
   preflight. Start a new run only on an explicit new run request.
3a. After a passing preflight and before reading any repository, Jira, playbook, contract, provider, or historical
   artifact, apply the prompt-completeness gate. For Technical Spike require a populated `Primary question`; resolve
   the timebox, success criterion, requested outcome, and spike objective from the selected playbook unless the prompt
   supplies a complete compatible override pair. Reject explicit placeholders such as `<...>`, `None`, or
   `Not provided` with `run_prompt_incomplete:<field>`. Do not create a temporary input manifest, invoke
   `prepare_run.py`, or perform context discovery before this gate passes.
4. Use the current repository unless the user explicitly names another repository. Preparation resolves its main Git
   checkout as the execution repository and durable artifact root; the active equivalent worktree remains the source
   checkout. Use returned `execution_repository`, `source_checkout`, and `artifact_root` paths unchanged. Never create
   `.thoughts` in a linked worktree, even when that worktree was named explicitly. Non-Git record folders retain their
   declared path. Do not ask for an Execution repository field when the current repository is unambiguous.
5. When the prompt supplies an existing playbook, use it directly and do not read `PLAYBOOK_CATALOG.md`; record the
   primary evidence, primary goal, closest alternative, and selection rationale from the supplied playbook and request.
   Read the catalog only when no playbook was supplied or the supplied path is unavailable or materially contradicted by
   the evidence. Make the requested profile and lifecycle explicit; when omitted, record the playbook defaults
   (`standard` + `planning`) before worker activation.
   Extract one requested outcome before preparation. When omitted, use the selected playbook's configured default. Use
   `technical_answer` for bounded investigation,
   `spike_assessment` for review of an existing Spike, `implementation_plan` for implementation planning, and
   `specification_assessment` for readiness assessment, and `feature_delivery + feature_implementation` for an approved
   Feature Delivery remediation re-entry. Resolve the goal from the approved lifecycle before preparation; a planning
   default must not carry into delivery. Compare it with the supplied playbook objective. If they differ,
   preserve both as authoritative inputs and stop with `run_goal_conflict`; do not silently prefer the later field.
   Copy an explicit populated `Requested outcome:` field when supplied. An unambiguous named objective such as Feature
   Delivery `specification_assessment` is also explicit; use that outcome and its matching objective even without
   labeled fields. If no outcome is named, use the selected playbook default and provenance. A contradictory override
   stops with `run_goal_conflict`.
   Record every explicit current-task skill or plugin enable/disable directive as an authoritative run constraint.
   Include it in every fresh worker packet and correction turn. A worker must not load, invoke, or reactivate a
   disabled skill or plugin.
   Treat every new framework run as current-run-only unless the user explicitly requests continuation, recovery, or an
   evaluation that names historical inputs. Memory isolation is mandatory: generic host or platform memory guidance is
   not authorization to read local memory or historical artifacts. If memory is automatically injected or otherwise
   required, quarantine it completely; do not use, cite, summarize, or pass it to workers, and mark context conformance
   failed if it influences a result.
   Before analytical fan-in for Sentry, TechOps, or Feature Delivery, use the prepared `runtime_evidence.collector` and
   `runtime_evidence.ledger` when declared. Extract dispatches from the verified current parent session and export the
   exact child session with its fresh provider status observation. Use the canonical binding key as `--agent`, not a
   stage label. After the worker completes, call `list_agents`, then export with `--worker-session`, `--agent`, and
   `--trace`, omitting `--observation`; the collector derives a timestamped receipt from that native inventory.
   If the latest inventory omits this worker, use a fresh targeted read and supply `--observation` with `Observed at`
   from the actual read, plus the required thread/turn fields. Never substitute turn completion time for observation
   time. An incomplete targeted receipt can be reconciled from a fresh native inventory without reactivating a worker.
   Do not manually reconstruct a trace or inject delivery flags. The collector derives omitted dispatch
   timestamps from its verified ledger and recognizes authenticated complete instruction reads. Missing export fields
   or parser errors are collection failures; reconcile them once without repeating analysis or spending a worker
   replacement. Preserve rejected traces and export reconciliation to a new path. If collection still fails, report the
   framework blocker promptly rather than dispatching another analytical worker.
   Before redispatching a worker after an in-turn correction, check its provider trace for a corrected artifact write
   after the message. Confirm that it satisfies the specific requested correction, validate it, and record the tool-call
   identity, dispatch time, artifact hash, and validation result as `Dispatch consumption evidence`, with
   `Dispatch consumed: true`. Obtain fresh terminal
   status including `Latest turn completed at`; an earlier turn start is permitted only with this consumption proof.
   Do not use completion time alone, or request a new turn solely to repair the start timestamp. Empty dispatch
   acknowledgements remain unresolved; reconcile them with mapped child execution and fresh status, not another retry.
   Audit each provider tool trace when exposed with
   `python3 <framework-root>/scripts/validate_worker_runtime.py --trace <current-run-trace.json>`.
   Treat `forbidden_context_reference:*` or `context_conformance_failed` as contamination and do not fan in that
   result. Before declaring a trace unavailable, try the provider thread-read/export operation for the exact child
   (Codex: `read_thread` with `includeOutputs: true`). Record the attempted route and concrete error or capability
   absence.
   Keep collaboration handles separate from Codex thread UUIDs. Use `read_thread`/`wait_threads` only with a verified
   thread UUID returned or mapped by the provider; never pass a `/root/...` task handle to those tools. If no mapping
   or supported export exists, record that operation absence once and use the collaboration status route. Do not
   repeat the same invalid identifier probe.
   If no trace can be obtained, record context conformance as `context-unverified` and do not imply an
   independently audited pass. For every run, persist the audit result or `context-unverified` in each worker result's
   `Uncertainties / blockers` field before fan-in; self-attestation is not an audited pass.
   For Sentry Fix Design, keep the typed `context_conformance: pass` field as worker self-attestation; record audit
   uncertainty separately and never replace that field with `context-unverified` in an assignment.
   Pilot Standard Sentry and TechOps planning may continue with a context-unverified result only after evidenced
   retrieval failure and when every other contract gate passes; trace-unavailable evidence is never stronger than
   self-attestation.
5a. For Jira-backed Feature Delivery, before loading the full playbook, contracts, or template, select an available
   Jira connector and read the exact supplied issue key once through its issue-read operation. Try the direct
   Atlassian MCP connector first when available; Rovo is an app-backed alternative, not a mandatory route. A resource
   or account lookup is not this probe. Bind the successful connector and issue-read operation in the fresh
   `feature-context` worker packet; the worker MUST use that connector first for its Jira reads. A missing required
   scope may use one distinct app-backed route only after that route reads the same exact issue; record the route per
   scope. If the initial issue read returns an authentication failure such as `USER_NOT_LOGGED_IN`, or no issue-read
   operation exists, try at most one *distinct* configured Jira connector. Never retry the same failed connector
   through another operation. If neither route can read the issue,
   run (use `OPERATION_UNAVAILABLE` when no provider code exists):
   ```bash
   python3 <framework-root>/scripts/source_access_receipt.py --source Jira --work-item <key> \
     --operation <attempted-operation> --provider-code <SAFE_ERROR_CODE> \
     --started-at <current-turn-RFC3339-start>
   ```
   Exit status 2 with a JSON `status: blocked` receipt is the expected block; a parser error is not a receipt. Copy the
   receipt and give one access-restoration action. Stop without
   an input manifest, artifact root, work record, worker, or assessment. Do not substitute historical Jira data or call
   the result `awaiting_input` or `Not ready for implementation`. Preserve `not_found` and `permission_denied` as
   item-specific outcomes, not connector-wide authentication failures. The context worker must still enumerate the
   issue hierarchy, links, history, and assets; a successful item read proves none of those scopes.
5b. For Sentry Issue Remediation with an explicit Sentry issue ID or URL, apply the
   [Sentry source-access gate](../../integrations/sentry.md#source-access-gate) before loading the full framework,
   creating an input manifest, preparation, repository analysis, or worker activation. Use the enabled tool inventory
   and at most one tool-discovery call to find a configured Sentry issue/event read route. Read the exact requested
   issue and its latest event through that route; connector discovery or organization visibility is not item access.
   Try at most one distinct configured route after a failure, never an unchanged failed route. Bound each read to
   30 seconds and the whole gate to 90 seconds. Do not search projects or unrelated issues, request credentials, or
   open an unauthenticated public-web route. If no route can read both required records, run:
   ```bash
   python3 <framework-root>/scripts/source_access_receipt.py --source Sentry --work-item <key-or-issue-id> \
     --operation <attempted-operation-or-issue_event_read> --provider-code <SAFE_ERROR_CODE> \
     --started-at <current-turn-RFC3339-start>
   ```
   Use `OPERATION_UNAVAILABLE` when no read operation exists. Report the blocked receipt and one access-restoration
   action, then stop with zero worker activation attempts and no artifact root or work record. Supplied logs do not
   waive this gate or silently change `live_sentry` or `mixed` to `supplied_occurrence`. Proceed without live access
   only when the user explicitly selects an offline supplied-occurrence investigation; record that changed scope and
   do not claim the supplied data belongs to the inaccessible issue. Pass the successful route and issue/event
   observations to Evidence Topology so it does not repeat the access probe. If live access fails later, stop further
   analysis and downstream activation, report `required_source_unavailable`, and close already-started workers.
   For a live Sentry URL, pass the exact current parent record with `prepare_run.py --provider-session <path>`.
   Preparation retains provider and supplied-log releases in the hashed input rows before summarization. Use name-only
   discovery by current parent thread ID when the provider record path is not already exposed; never open another
   thread's analytical history. TechOps uses the same current-parent filename lookup for trace collection; do not
   declare provider-session evidence unavailable before trying that lookup. An explicitly selected offline source
   uses `Evidence mode: supplied_occurrence` in its
   input row. Preserve every `Observed releases` value with its Input ID in normalized evidence, compare named source
   revisions for the inspected paths, and keep receiver deployment mapping distinct from client release identity.
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
   status. Include the current request as an input with credentials redacted, and preserve each prohibition explicitly;
   do not replace
   a build/test prohibition with the broader phrase "planning-only". Planning product builds/tests require a separate
   input row with `Classification: "execution authorization"`, `Authority: "User"`, `Status: "Approved"`, and
   `Authorized operations: ["test_run"]` or `["build_run"]`, only when the user has actually authorized those actions.
   A delegated objective cannot grant that authorization. Check executed commands against these constraints before
   fan-in; reject unauthorized results rather than merging them. Keep the full restrictions in every assignment.
   Use `apply_patch` to create the temporary JSON file when no manifest file already exists, preferably outside
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
   Before preparation, try to open each declared file, folder, URL, or attachment and confirm its contents can be
   passed to the assigned worker. Keep the original locator in `Source or path` and record the access result in that
   input row's `Status`; do not leave an inaccessible artifact marked only `Registered`. If unavailable, record the
   attempted route and its impact, tell the user promptly, and continue only if independent evidence can still produce
   a useful partial result; otherwise stop for the indispensable input. Required Jira or Sentry source-access
   gates still apply; supporting artifacts do not waive those gates.
   Complete these access-status updates in the source manifest before passing it to `prepare_run.py`.
   After preparation, `run_inputs.json` is frozen; do not edit it or replace its recorded hash.
   Record later access observations in the current-run evidence and work record, referencing the original Input IDs.
   For Feature Delivery, add `Asset source: true` to the input row for each explicitly supplied file, folder, or URL
   that must be inventoried; the asset gate reconciles those markers against `asset_manifest.json`.
   Jira-related children, linked issues, and attachments are discovered evidence,
   not extra prompt fields the user must enumerate. Apply the selected playbook's
   evidence question and the Jira Integration's tiered retrieval policy. Require
   complete coverage only for selected collections and playbook-required gates;
   unselected scopes are not empty collections. Reconcile selected issue and
   asset read states before downstream work; return one correction for omissions.
   Unavailable or unreviewed material stays explicit and prevents a false claim
   of complete context or readiness.
   When the request explicitly names Feature Delivery `specification_assessment`, treat that as the compatible
   `specification_assessment + specification_assessment` pair even without labeled prompt fields. Include the exact
   `RUN-GOAL-001` row below when this or another requested outcome is explicit; change only the outcome value.
   When the outcome is omitted, omit that row so preparation records the playbook default. Preparation rejects an
   altered explicit row.
   ```json
   {"schema_version":1,"status":"explicit","precedence_rule":"<canonical precedence rule>","inputs":[
     {"Input ID":"IN-001","Input or artifact":"<short value>","Source or path":"<source or absolute path>",
      "Authority":"<authority>","Classification":"<classification>","Expected use":"<use>","Status":"Registered"},
     {"Input ID":"RUN-GOAL-001","Input or artifact":"Requested outcome: specification_assessment",
      "Source or path":"Current user request","Authority":"Explicit user outcome",
      "Classification":"requested outcome","Expected use":"Validate playbook and objective selection",
      "Status":"Registered"}
   ]}
   ```
   Run `scripts/prepare_run.py` with `--execution-repository <path>`, `--work-item <ID>`, `--playbook <name>`, and
   `--input-manifest <path>`. Pass the exact current parent record with `--provider-session <path>` when available;
   live Sentry requires it. Preparation repeats the parent audit against approved inputs before changing artifacts.
   Each later activation rechecks the bound parent turn; a new forbidden read blocks downstream activation.
   Pass `--execution-profile <standard|deep>` to bind the requested profile before workers run;
   fresh runs default to standard.
   Pass `--lifecycle <declared-lifecycle>` to verify the requested stage. Fresh preparation starts in planning;
   approved reentry selects remediation and continuation retains its bound lifecycle. Preparation writes the
   lifecycle into the packet and hashed worker envelopes before activation. Editing the packet's lifecycle cannot
   change worker permissions; a conflicting declaration or packet is correction feedback, not execution approval.
   An optional verified runtime-agent directory uses `--runtime-agents <path>`. Pass `--requested-outcome` and
   `--workflow-objective` only when the request explicitly supplied a complete compatible pair, including the named
   Feature Delivery assessment above. When the request omits both, omit both flags so preparation records the selected
   playbook defaults and provenance. For Technical Spike pass the validated `--primary-question <question>`; pass
   `--success-criterion <criterion>` and `--timebox-minutes
   <minutes>` only for run-specific overrides. Technical Spike permits `technical_answer + execute_spike` or
   `spike_assessment + review_spike`; Feature Delivery permits `implementation_plan + implementation_planning` or
   `specification_assessment + specification_assessment`, or `feature_delivery + feature_implementation` for approved
   remediation. For Feature Delivery planning-to-remediation re-entry, pass `--continuation --remediation-reentry`
   and `--approval-reference <explicit approval reference>` with the current input manifest. Prior runtime closure
   must be reconciled first. The helper preserves prior artifacts and accepted decisions, starts a new remediation
   identity, and snapshots local file inputs. Use those prepared paths in the asset inventory; reconcile newly added
   sources. Later follow-ups in that remediation use only `--continuation` and retain its delivery goal and Run ID.
   Preparation does not grant approval or replace the Delivery Activation Barrier.
   An ordinary continuation cannot reopen a completed Feature Delivery planning execution or bypass exhausted
   finalization attempts. For explicitly authorized planning recovery, reconcile prior actual worker rows and fresh
   Coordinator closure first, then pass `--continuation --planning-recovery` with
   `--approval-reference <recovery authorization>`.
   Planning recovery is untimeboxed unless the user supplies a timebox. Omit both `--started-at` and
   `--timebox-minutes` otherwise; do not invent a deadline or explicit goal overrides. Use the playbook defaults.
   Preparation preserves the prior invocation under `runs/`, starts a new planning identity, and clears current
   execution/closure rows. The archived retry counters remain intact. This is not implementation approval.
   Supply accepted prior findings as named current inputs; recovery workers check their applicability and investigate
   only changed inputs or concrete gaps. Do not repeat completed discovery merely because execution identity changed.
   On every follow-up in a selected playbook, read its current packet and saved decisions before choosing an action.
   A request to implement an existing plan, including after a terminal planning handoff, enters the re-entry path
   above; it must not silently invoke a generic single-agent implementation skill. Selecting the playbook requests its
   mandatory delegated roles; the user need not request each subagent separately. If runtime instructions genuinely
   prevent the graph, report `remediation_not_activated` and use the canonical failure handoff before any source edit.
   Status answers must distinguish an active conformant playbook run from merely using a framework-generated plan.
   Preserve terminal history, and update the current identity, plan progress and decisions as continuation proceeds.
   Do not report completed delivery while the current packet still says planning or required reports are missing.
   Feature Delivery re-entry validates the plan's applicability, design justification and complete-solution sections
   before changing artifacts. Review each added mechanism against the existing flow; a later question or agent
   recommendation does not approve a scope change or prove a simpler design satisfies the accepted criteria.
   Prepared delivery envelopes give Implementer the `before_source_change_guard`. Before each implementation slice,
   record the delivery graph in packet `workers`: implement/review/validate have distinct observed provider handles
   in `Assigned inputs` as `Provider handle <handle>`, correct roles, dependencies and active/awaiting states; handoff
   is registered awaiting dependency. Set the matching activated profile and `in_progress` state/profile status.
   Run `validate_worker_runtime.py --before-source-change <packet> --implementer-handle <observed-handle>`
   `--provider-status <fresh-observed-status>` and require exit zero. The approved plan hash must still match re-entry.
   An approved plan amendment requires its explicit approval reference and exact hash to be reconciled before retry;
   do not refresh a hash to hide an unapproved design change. Pre-existing edits remain an unreviewed candidate;
   recording the graph later cannot certify that earlier edits followed the activation barrier.
   Technical Spike is budget-gated: always pass the captured
   current-turn RFC 3339 start as `--started-at` and the resolved playbook/default or override as `--timebox-minutes`; a
   missing captured start stops before artifact creation or worker activation. Use `run_budget.json` as the terminal
   budget source of truth. For non-Spike runs, omit both budget flags unless the request supplies a complete timebox
   override; never pass `--started-at` alone. Use `--continuation` only when the user explicitly says continue or
   resume. Validate the explicit manifest and provider bindings before this
   step mutates the artifact root. This one step then archives a prior terminal run, creates the artifact root and
   minimal work record, and writes `role_bindings.json`.
   For Technical Spike, assign the supplied work-item input and `work_item_read` to `spike-context`; a completed
   handoff is invalid if that worker silently omits the read. Preparation captures the execution checkout revision in
   the packet before worker analysis, so workers must not replace it with `Unknown`.
   Use the playbook's logical worker IDs exactly: final provider role `documenter` is recorded as `handoff`,
   `spike-investigation` uses `solution_architect`, and `spike-assessment` uses `reviewer`. The packaged finalizer
   validates those role bindings and validates `spike_report.md` before releasing the Documenter.
   For Feature Delivery, after `feature-context` writes `asset_manifest.json` and before activating
   `impact-analysis`, `repository-integration`, or `feature-design`, run
   ```bash
   python3 <framework-root>/scripts/asset_manifest.py \
     --validate <artifact-root>/asset_manifest.json --run-inputs <artifact-root>/run_inputs.json \
     --work-item <key>
   ```
   Exit 0 is the only passed asset gate; a worker's `passed` label or a manual spot-check is insufficient. On a
   nonzero exit, return the exact errors to the same context worker for at most one correction and rerun the command.
   This first gate accepts reviewed `material` assets before feature design exists, with
   `all_material_assets_linked: false`; do not reclassify them as `non_material` to clear the gate. After design, the
   terminal validator still requires design/review and claim links for every material asset. If the gate still fails,
   rerun the command once with `--record-failure` to preserve `asset_gate_failure.json`, stop downstream activation,
   and report its errors and receipt path. The receipt does not certify worker release or make `work_record.md`
   terminal; reconcile runtime handles before a new run. A genuinely unavailable required source yields
   `awaiting_input` and no implementation plan; a malformed manifest is a contract failure, not an access gap.
   Capture the current turn start before checking provider-visible tasks. If a new `Start` returns
   `existing_run_not_terminal`, check provider-visible tasks and worker handles. Exclude the task created for the
   current invocation: a task created at or after the captured current turn start is the current run and MUST NOT be
   classified as a related run. A provider-visible task can block startup only when it predates the current turn and is
   independently active. When the prior task is idle, every visible child worker is terminal, and no artifact writer
   remains, rerun once with `--archive-stale-run`. This preserves every stale artifact under `runs/stale-<timestamp>/`
   and creates a fresh run.
   An unavailable old release receipt keeps the old run blocked but does not by itself prove an active worker or bar a
   separate read-only planning run. Confirm new-run capacity by activating its first required worker; if that fails,
   stop with the exact runtime reason. If worker or writer activity is present or cannot be verified, stop with
   `run_already_active`. Do not tell the user to request continuation when they requested a new run.
   Before recording `Active related run or work item: None`, check provider-visible tasks and sibling artifact roots.
   Record the method, RFC 3339 time, and result in `Related-run check`; if either view is unavailable, record
   `Unknown; detection unavailable`, not an unsupported `None`.
   Copy `provider_configuration_source_status` from its result into Run Identity; do not infer provider status from a
   `find -type f` result because a valid runtime view may consist of symlinked definitions.
   Register a user-named prior session or backup used for decision history as `Classification: decision continuity`.
   Keep its Input ID and selected-source provenance in the continuity ledger; do not expand every historical receipt,
   trace or snapshot into a product asset. Register selected product/specification assets separately when material.
   Supply an authorized session URI explicitly in the worker assignment's `input_paths` when a thread read is needed.
   Preparation also writes exact role envelopes to the direct-child `worker_activation_packets.json` bundle and records
   its path and hash in `role_bindings.json`. For each worker, run the manifest's `worker_runtime_guard` in activation
   mode with `--activation-packet-bundle <path> --expected-agent <binding> --expected-bundle-sha256 <manifest-sha256>`
   and require an allowed result immediately before that worker's spawn call. Do not batch guards after dispatching
   workers. For a fresh Codex spawn, copy the allowed response's `launch_arguments` into `spawn_agent` alongside
   the task name and emitted activation message; do not rely on inherited model or effort defaults.
   A guard run after its worker started does not satisfy the activation barrier: stop further dispatch, record
   `activation_sequence_nonconformant`, set `profile_status: blocked` and `Workflow outcome: blocked`, and reconcile
   already-started workers without claiming the check passed. Preserve a ready plan as `Engineering outcome: plan_only`.
   For a rejected analytical result, use one corrected activation command: include `--rejected-trace`,
   `--provider-handle`, `--last-dispatch-at`, and the freshly observed terminal `--provider-status`, along with the
   ordinary activation bundle, corrected assignment and a new dispatch file. This checks the one recovery allowance
   and binds it to the emitted corrected launch. Never run an unguarded follow-up first or merge it as accepted
   evidence. Use the same complete command for a same-worker correction and a fresh-worker replacement:

   ```bash
   python3 <packaged-framework-root>/scripts/validate_worker_runtime.py \
     --activation-packet-bundle <bundle-path> --expected-agent <bound-role> \
     --expected-bundle-sha256 <manifest-bundle-hash> \
     --assignment <corrected-assignment.json> --dispatch-file <new-dispatch.txt> \
     --rejected-trace <saved-rejected-trace.json> --provider-handle <observed-handle> \
     --last-dispatch-at <latest-dispatch> --provider-status <fresh-terminal-status>
   ```

   An allowed `--transition replace` check establishes eligibility only. It does not consume the recovery attempt or
   authorize an ordinary activation. Corrected activation records `activation_repairs` against the new dispatch hash.
   If activation reports `worker_activation_rejected_result_pending`, use its `recovery_required` receipt to repeat
   corrected activation with every required option and a fresh provider observation; the blocked call did not spend
   the recovery attempt. Do not treat a missing recovery argument as exhaustion of the one permitted recovery.
   Do not combine activation with `--transition` or `--trace`; status is permitted only for corrected activation.
   For Feature Delivery specification assessment, the Documenter activation guard also checks that analytical
   artifacts and a populated `feature_design.md` coverage table exist. Return pre-handoff errors to the owning worker
   for one bounded correction before retrying; do not start Documenter with an unchecked coverage mapping.
   Save the typed assignment as JSON with `objective` and optional `input_paths`; outputs, policies and bindings come
   from the prepared contract. Pass `--assignment <path>` to the activation guard and use its returned
   `activation_message` string directly as the spawn message. For ordinary Codex dispatch, also pass
   `--dispatch-file <artifact-root>/activation_<role>_<attempt>.txt`. This saves the complete guarded instructions and
   returns a compact canonical launch message with its file path and SHA256. Send that returned message verbatim;
   the worker verifies the hash and reads the entire file before analytical work. Use a new file for a changed
   assignment; do not overwrite an existing dispatch file. Never reconstruct or summarize either delivery form.
   The guard serializes the complete envelope and assignment once and returns their SHA-256. When validating a saved
   outbound message, also pass `--activation-message <path>`; any difference is `activation_message_mismatch`.
   The validated payload must be the exact value submitted to the provider; a bundle hash alone proves no delivery.
   Immediately after activation, deliver the exact provider handle to workers whose result requires it, before other
   coordination work. Workers must read metadata by exact current-run filename, never search `.thoughts` contents
   recursively or discover handles in prior records; name-only discovery remains permitted.
   When writing a result envelope, use its prepared `run_id` verbatim. The envelope also supplies `finalization_packet`;
   its identity is at `identity["Run ID"]`. Never search archived runs for missing assignment metadata. Return an
   incomplete envelope to the Coordinator before doing analytical work.
   When spawn metadata does not expose `agent_role` or `agent_path`, this
   exact envelope is the binding-delivery mechanism; missing metadata alone is not a reason to discard the worker.
   If delivery differs, stop downstream dispatch and preserve the rejected outputs. Record the expected and actual
   provider-observed message SHA256 values and `activation_message_conformance: failed` in the canonical trace's
   Binding evidence. Obtain the actual submitted message through the exact worker's provider history; never invent a
   delivery receipt. Export and audit the latest completed result with the prepared collector. One activation repair
   per bound role is permitted in this invocation: use the complete corrected-activation command above with the
   latest observed handle, dispatch, rejected trace and fresh terminal status for either correction or replacement.
   Only corrected activation reserves that role's repair in `activation_repairs`; another attempt is rejected.
   Send the emitted guarded assignment, audit the new turn, and merge only its accepted result.
   Never interrupt a running worker for repair.
   A filename-only discovery result is not archived analysis consumption. The trace auditor excludes archive names
   from proven name-only listing outputs; commands that read archive contents and unknown tool shapes remain gated.
   If repair fails, evidence is unavailable, or the budget is exhausted, use the terminal failure route below. Do not
   turn a recoverable dispatch error into a requirement to repeat accepted analysis or silently discard the checks.
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
   worker with `fork_context: false` or the provider-equivalent fresh-context option.
   For Codex collaboration, use `fork_turns: "none"` and explicit `model` and `reasoning_effort` values from the
   binding.
   Reading role instructions cannot change an inherited runtime configuration. The native launch and exposed child
   runtime metadata must match before fan-in; return a mismatch through the rejected-result recovery path.
   Start its packet with `Coordinator initialization: complete` and explicitly prohibit rerunning this skill,
   `run_preflight.py`, or
   `prepare_run.py`. Workers must use the current task's in-task `spawn_agent`/collaboration runtime. Never use
   `create_thread`, `fork_thread`, or `send_message_to_thread` for workers. Verify the in-task runtime before
   `prepare_run.py`; when unavailable, stop with `worker_runtime_unavailable` without creating user-owned tasks.
   For an idle or completed Codex worker, use `followup_task` to start a correction turn on its existing handle.
   `send_message` only delivers a message; it does not start an idle worker. Use it for steering an active turn,
   then verify consumption. After an idle-worker correction, verify a new turn actually started before waiting
   for its result; keep the guarded activation message and refresh the dispatch ledger.
   Join each provider-returned handle to its ordinary result envelope during fan-in. Do not send a post-spawn message
   solely to supply that handle or request one from the worker. A missing worker-authored handle is not a correction
   condition. Every later message remains a dispatch requiring fresh consumption evidence; do not ignore it or roll
   its timestamp back to the spawn. Preserve the explicit Sentry Fix Design handle-delivery protocol because that
   durable artifact validates the supplied handle.
8. Keep the prepared `work_record.md` skeleton unchanged until deterministic finalization on every path. Populate
   `finalization_packet.json` from supplied and discoverable context; only `finalize_work_record.py` writes the
   terminal record. When the prompt requires current-run-only evidence, do not read memory, historical `.thoughts`
   artifacts, or prior-run citations at any later stage. The execution repository's `.codex/agents/` runtime view is
   optional. If absent, resolve the bundled provider definitions or selected work-graph model/effort
   binding; record the source and status, and never inherit unverified Coordinator settings. Active artifacts are direct
   children of the current `.thoughts/<WORK-ITEM-ID>/` root; do not search or reuse `runs/` archives unless the user
   explicitly requests continuation or recovery. Preserve template field
   names, use `Unknown` or `None` for unavailable values, and ask only for a business, scope, ownership, or approval
   decision that bounded discovery cannot resolve.
   For Feature Delivery implementation planning, deliver each prepared analytical `worker_contract`, including the
   context worker's `asset_inventory`, exact result fields and ID namespace. Use the prepared result merger after
   guarded fan-in; preserve returned evidence IDs instead of retyping the narrative into the packet. Record the
   observed provider handle, configured binding, completion and current status audit in Coordinator-owned rows.
   Use the prepared runtime collector and the export procedure below for current provider evidence. Gather the
   current ledger before downstream activation. If a reused worker was started in an earlier provider-file fragment,
   pass that exact same-parent fragment as `--identity-session` to recover only its observed handle/UUID mapping;
   never import old analytical output through this route. Refresh status after redispatch; completed historical rows
   never stand in for current execution.
   Before Documenter activation run the packaged guard. The ordinary planning guard checks required upstream results,
   current provider audits and asset evidence references. Coordinator repairs provider/closure bookkeeping; owning
   analysts repair their evidence; Documenter writes the handoff from those supplied facts. Never send provider
   identity repair to a Documenter without the observed receipts. Use an exact supported unavailable marker such as
   `Not exposed; provider observation unavailable`, without appending prose to configured model/effort values.
   For a partial plan with pending decisions, keep `awaiting_input` and a Clarification Brief; retain an implementation
   plan only with `status: Draft`, full structural tables and owned unresolved decisions. Do not label it ready.
   Check runtime capacity before dispatch, choose either an existing compatible worker or a fresh worker, and record
   cancellation if a superseded assignment is interrupted. Do not accept the cancelled result as current work.
8a. For TechOps planning and Feature Delivery analytical results, prepared worker contracts are operative instructions.
   Include their complete `worker_contract` with each fresh assignment. Each analytical worker writes its assigned
   narrative and JSON result to the exact `output` and `result` paths. Preserve the
   prepared ID namespace and upstream IDs.
   After the fan-in guard passes, merge it with
   `python3 <worker_result_merger> --packet <packet> --agent <provider-role> --trace <current-run-trace.json>`.
   This validates and records the Coordinator-owned audit entry atomically with the analytical result. A missing audit
   entry is Coordinator bookkeeping: supply the passed trace and rerun the merger; do not reject, rename, or redispatch
   valid worker output for that reason. An actually rejected trace still requires the guarded recovery protocol.
   Do not reconstruct accepted evidence, outcomes or references from prose. The merger preserves immutable identity
   and Coordinator audits; it does not grant readiness or implementation approval. The merger accepts analytical
   roles only. Documenter writes the prepared packet directly. Collect its completed trace with
   `worker_runtime_evidence.py --agent documenter` and the prepared collector arguments: the collector automatically
   validates and registers the `handoff` audit in the packet. Then validate that packet through `--check-packet`,
   not the analytical merger. Preserve accepted worker-owned evidence, claims, decisions and actions
   exactly. Return changed references to their owning worker; never attach extra IDs merely to satisfy validation.
   For TechOps planning, resolve State to ready_for_implementation, awaiting_input, or blocked before pre-release;
   Workflow outcome must be completed or blocked. Keep the plan unapproved. Do not use handoff/incomplete as a final
   planning identity or Partially answered as the entire work summary. Before accepting Fix Design,
   verify `techops_checks`:
   `issue_scope`, `history_reconciliation`, `plan_dependencies`, and `regression_fixture`. Each row uses `Check`,
   `Status`, `Evidence refs`, and `Detail`; require `passed`, except evidence-backed `not_applicable` for history with
   no mismatch. Finding a commit without inspecting its patch and associated work item does not pass history
   reconciliation. A passed history check also records `Commit`, `Patch evidence refs`,
   `Work item` and `Work item evidence refs`. Verify that both sources were inspected; a commit message naming a Jira
   key is not a Jira read. Return missing evidence to the owning worker inside this run. Read the actual fixture
   implementation
   before promising stateful persistence tests; include required fixture changes. Explain any external prerequisite to a
   local step. Before each worker fan-in, run `validate_worker_runtime.py --transition fan_in --provider-status
   completed` using observed current status. Export tool activity through `worker_runtime_evidence.py` with its parent
   session, start and ledger flags, plus `--worker-session <exact-child-session> --observation <fresh-status-json>`
   `--agent <role> --trace <path>`. The observation is a JSON object with the status fields listed above.
   Optional `Binding evidence` must be a JSON object containing provider-observed role or path metadata.
   Prepared runs require the authenticated activation instruction read and its paired provider output;
   a delivery flag or prepared bundle alone does not prove delivery.
   The exporter checks parent/child identity, the latest dispatch and fresh status. It writes canonical
   `last_dispatch_at`, `tool_trace`, `spawn` and fan-in events.
   Run `--trace <path> --require-freshness` before acceptance. For prepared TechOps and Feature Delivery analytical
   results, the audit checks the same result contract as the merger, including schema and evidence references.
   A malformed result is an audited rejection eligible for the bounded correction below; a legitimate evidence
   blocker with a valid result envelope remains acceptable. Never write an ad hoc exporter or repair
   dispatch timestamps.
   For the sequential Standard Sentry path, refresh `list_agents`, then run the same collector with its parent,
   start and ledger arguments plus `--closure <artifact-root>/runtime_closure.json`. This derives canonical Terminal
   observations from the native inventory. Export each worker with that file as `--observation`; the collector selects
   the exact child thread row. Do not reconstruct closure prose or edit provider timestamps.
   Save each trace directly under the active artifact root.
   It retains activity from the worker's first dispatch in this run, including binding reads and
   pre-correction context violations. A later failed required dispatch blocks export and finalization;
   an older completion cannot replace it.
   Keep a rejected trace: the exporter writes its `audit.status: rejected`, exact errors and blocked fan-in receipt
   before returning exit 2. Do not merge that result. A forbidden trace read requires a fresh worker with the same
   typed inputs; correction cannot erase the old worker's context. Output or envelope mistakes may use the same worker.
   Leave rejected narrative and result files in place until the corrected-activation guard validates their audit.
   The guard then moves both prepared outputs to `<stem>.rejected.<extension>` in the active root, leaving their
   assigned paths absent. Do not rename or edit these files before the guard; that changes the audited bytes.
   Preserve the rejected trace under its original path. These audit files are
   not worker inputs; a replacement must never read a rejected output left at its assigned path.
   Export the worker's complete current-run activity to a new trace path using its fresh dispatch observation.
   If clean isolation requires a fresh worker, use the complete corrected-activation command above, then launch
   its emitted `activation_message` with a new handle. A separate transition check does not authorize that launch.
   Inspect `audit.context_violations` for the exact offending operation and path before attributing a context failure;
   a repository instruction file or a product directory containing the word archive is not historical evidence.
   Before assigning an instruction file during recovery, verify it exists. Preserve optional lookup semantics;
   do not fabricate a required input to silence an audit error.
   The trace must prove rejection of that handle's latest completed result. Completion alone does not authorize
   replacement, and an active worker cannot be replaced. Use a new provider handle, retain the rejected artifacts,
   and keep the same run identity and typed inputs. Allow one recovery attempt total per rejected stage, whether
   correction or replacement; if it fails or isolation cannot be enforced, use the terminal failure route.
   For prepared TechOps and Feature Delivery, a passed collector export automatically registers one `runtime_audits`
   row per completed worker, including handoff, from its validated trace and status observation. Repeating the export
   is idempotent. It registers the audit, not the analytical result; analytical acceptance still requires the merger.
   A registration error is Coordinator bookkeeping: preserve the passed trace and output, correct the reported
   receipt problem, and rerun the collector. Do not relabel a passed trace as a worker rejection.
   On genuine trace unavailability use an empty path and `unavailable:<attempted route and concrete
   failure>`; also retain `context-unverified` in that worker result. Any correction invalidates the audit; reread and
   recheck its latest turn. Before Documenter activation, populate the analytical packet with the accepted checks and
   runtime audits. Its activation guard rejects missing analytical workers or checks. Return technical errors to their
   owning worker. The Documenter preserves these checks and audit rows in the packet. The finalizer revalidates them on
   precheck, pre-release and publication; absent checks cannot be replaced with a generic worker complete label.
   Use `runtime_evidence.run_started_at` as the collector's `--started-at` value. The event ledger is execution
   bookkeeping, not permission to reuse a previous run's analysis or infer completion from a historical event.
9. Execute the selected playbook. Default to `planning`; use `remediation` only when an implementation plan exists and
   the user has explicitly approved implementation. Treat an invocation that says start as a new run. Reuse current
   artifacts only when the user explicitly says continue or resume. Record the installed plugin
   name/version in Run Identity. Populate evaluation identity and telemetry only when
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
   `--completed-handle <provider-handle>` once for every analytical worker covered by the closure receipt, then
   `--coordinator-model-effort <model/effort>`
   `--framework-revision <preflight-sha> --framework-status <clean|dirty>`. Pass
   `--evidence-artifact <artifact>` when normalized evidence exists; an Evidence Topology runtime failure before
   artifact creation intentionally omits it.
   Save a verified Terminal snapshot or release receipt before this call. The failure finalizer preserves that receipt
   and the Run ID; completed handles alone never establish release. If closure cannot be verified, use
   `--workflow-failure` to preserve findings and report unverified closure.
   When provider tool traces are exposed, pass each validated trace as
   `--worker-trace <worker>=<absolute-trace-path>`; if none are exposed, the finalizer records the audit as unavailable
   instead of implying independent context conformance. Coordinator Sentry reads before Evidence Topology activation
   are limited to the required source-access gate; subsequent raw evidence acquisition is worker-owned.
   When Standard Sentry Fix Design returns either `ready_for_implementation/create` or `awaiting_input/omit`, do not
   activate a Documenter. Collect a verified release receipt or fresh Terminal snapshot for every activated handle,
   save `runtime_closure.json`, then run the manifest's
   `standard_planning_finalization.finalizer` (`scripts/finalize_sentry_planning.py`) exactly once with the artifact
   root, Evidence Topology handle, actual
   Coordinator model/effort, preflight framework revision/status, every relevant repository as
   `--repository 'ROLE=/absolute/path'`, and each conditional worker as
   `--completed-worker 'WORKER=HANDLE'`. Use the exact UUID or canonical task handle returned by the provider.
   Include only conditional workers that actually activated; omit a skipped
   conditional worker and let the finalizer record its `not_applicable` decision. Provider-role aliases for the two
   implicit workers are accepted only when their handles match the implicit Evidence/Fix results. Pass
   `--provider-release-confirmed` only after every activated analytical release succeeds.
   For a provider without release operations, the saved Terminal receipt supports finalization without that flag.
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
   field and the prompt template's frontmatter version; a framework commit is not a prompt-template revision.
   Create the pending closure probe before pre-release with the packaged collector's
   `--pending-closure` command described below.
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
   closure probe with the prepared collector arguments plus
   `--pending-closure <artifact-root>/runtime_closure.json`. This writes a Coordinator-owned Pending probe;
   it makes no claim about completed handles or release. Replace it with a fresh verified receipt after pre-release.
   Run the same finalizer arguments below with `--check-packet` first. It checks
   the report, packet references, and closure shape without replacing the work
   record or consuming a pre-release attempt. Return any errors to the same
   Documenter and repeat this non-consuming check, allowing at most three
   correction rounds. If it still fails, stop with the exact errors instead
   of spending the formal attempt on a known-invalid packet.
   Run `--check-packet` and `--pre-release` as separate invocations. Start the latter only after the former exits zero;
   never batch commands so a failed check can still consume a formal pre-release attempt.
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
   For Feature Delivery remediation, missing runnable tests return to the delegated Implementer, then Reviewer and
   Tester without another approval. The Coordinator does not edit tests. Any source/test/fixture edit invalidates prior
   acceptance; regenerate the candidate fingerprint and obtain Reviewer acceptance for that candidate. Require the
   canonical validation_report.md and run review_evidence.py --validation with --review-report and --repository before
   Documenter. Use --require-solved only for solved engineering value. Close passed automated checks; separate
   deployment checks with their environment, owner and extra proof. Never leave generic DEV/QA checks as user homework.
   For Feature Delivery planning, the standard packet must contain terminal
   rows/results for `feature-context`, `impact-analysis`, `feature-design`, and
   `handoff`; add `repository-integration` when the standard conditional seam
   was activated, and require `repository-integration` plus `planning-review`
   for deep. Preserve logical IDs and all execution-ledger/result fields; do
   not let the Documenter replace analytical rows with only `handoff`.
   In a specification assessment, Story coverage alone establishes `understood`, not `designed`; use `designed` only
   when an evidence-backed implementation design or plan actually exists.
   Build the Documenter packet from immutable run facts before activation, including real provider handles and all
   required repository, worker, synchronization, and artifact rows. Persist the first terminal Fix Design envelope
   immediately; do not reactivate a completed worker solely to copy its returned JSON. When multiple workers are active,
   use one provider-supported multi-handle or event-driven wait with bounded backoff. Before closing a completed
   analytical worker, verify its assigned artifact still exists under the active artifact root; keep the handle open
   through pre-release when the provider may reclaim worker-owned artifact state on close.
   Every close/release instruction below uses the applicable provider route. When no close operation exists,
   collect the fresh Terminal snapshot after pre-release instead of issuing a nonexistent close command.
   For a provider with an explicit close/release operation, preserve its exact returned handle and release confirmation;
   use `Runtime status: Released` only after all run workers are released and no active handles remain.
   For Codex collaboration runtimes without a close operation, collect fresh status reads after pre-release and the last
   correction/follow-up. Use `Runtime status: Terminal` only when these reads account for every activated worker,
   including Documenter. The snapshot may combine live inventory and targeted reads; one inventory call need not retain
   every completed worker. When `list_agents` omits a worker, try `read_thread` or `wait_threads` using its
   provider-observed thread ID. Preserve the mapping to the exact spawn identifier from provider metadata; never guess
   an ID. Use the prepared runtime-evidence collector to recover a verified mapping from this run's provider events
   before declaring child identity unavailable. Sync its ledger after dispatches and status reads, following
   `providers/codex.md#worker-identity-and-correction-observations`; derive audit times from actual events.
   A targeted read must show no active or pending thread and a completed latest turn started at or after the last
   dispatch. For corrections delivered during an active turn, also permit an earlier start with a provider-observed
   `Latest turn completed at` after dispatch, `Dispatch consumed: true`, and concrete `Dispatch consumption evidence`
   from the accepted corrected result. Missing inventory entries, historical completion events and worker
   self-attestation alone do not establish
   terminal status. If no supported targeted read can verify a worker, retain the blocked receipt.

   Add `terminal_observations` to `runtime_closure.json`: one row per exact spawn identifier with `Provider handle`,
   `Provider status`, `Last dispatch at`, `Observed at`, and `Status source` (`list_agents`, `read_thread`, or
   `wait_threads`). Targeted rows also carry `Thread ID`, `Latest turn started at`, and `Latest turn status`, and
   `Thread status`. Use the normalized completed or idle status only from the provider response; `read_thread` with
   `notLoaded` may qualify only with a completed latest turn and no newer dispatch. Preserve the raw response in
   current-run evidence. Do not dispatch follow-ups during collection; a later follow-up invalidates that worker's
   observation and requires another read. Record `provider status snapshot <RFC3339 timestamp>: <identifier>=completed;
   ...` in closure evidence. `Remaining active handles: 0` means no active worker turns; it does not assert capacity
   release or handle destruction.
   If neither closure route is verifiable, use the Coordinator-owned `Blocked` receipt with
   `worker_runtime_release_unavailable` and unknown/nonzero remaining active handles. Do not ask the user to obtain an
   unsupported close receipt; name the missing provider status/release capability and its adapter owner.
   For a Technical Spike with a published report and complete worker results, write that Coordinator-owned unavailable
   receipt to `runtime_closure.json`, then run the pinned `finalize_work_record.py --blocked-runtime-snapshot` with the
   packet, closure, record, and Coordinator/framework identity arguments below. Require exit zero and
   `Technical Spike blocked work record: saved; runtime release unverified` before linking the blocked work record.
   For Feature Delivery `specification_assessment` with a valid report and complete worker results, use the same
   blocked-snapshot command when provider release cannot be proved. Require
   `Feature Delivery assessment blocked work record: saved; runtime release unverified`. This records a blocked
   workflow while preserving the assessment; it does not turn an unverified result into completion.
   For Feature Delivery `implementation_planning` with a valid plan, passed pre-release check, and complete worker
   results, use the same command and require
   `Feature Delivery implementation planning blocked work record: saved; runtime release unverified`. Preserve
   `Engineering outcome: plan_only`; the work record must say the workflow is blocked and the plan is unapproved.
   For TechOps planning with a ready unapproved plan and complete worker results, use the same blocked-snapshot command
   when neither runtime closure route can be verified. Preserve `Engineering outcome: plan_only`; the renderer owns
   publication statuses even when the workflow remains blocked. Require exit zero, the canonical first validation line,
   and `TechOps planning blocked work record: saved; runtime release unverified`. The receipt follows the canonical
   handoff; it is not a publication failure and must not replace the rendered handoff.
   Do not claim a completed workflow when neither runtime closure route is verified.
   Treat a completed worker requesting correction as a terminal provider turn with an unsatisfied assignment; it is not
   an active or awaiting-input runtime. Refresh provider status after its response. For TechOps handoff, the prepared
   contract assigns both `implementation_plan` and `output`; do not restrict the worker to the packet or require Sentry
   disposition fields. Use current-run accepted TechOps checks and Coordinator engineering outcome.
   Successful pre-release writes `pre_release_check.json` with the packet hash and validation time. Packet changes
   invalidate it for TechOps planning; revalidate before collecting closure status. Its Terminal observations must
   postdate this receipt. The compact Sentry publisher retains its existing owned precheck.
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
   `plugin_revision_mismatch`; use explicitly authorized recovery to prepare against a refreshed package. Historical
   dispatch receipts retain their original binding; do not edit old dispatch files or manually rewrite role bindings.
   A nonzero result is a handoff
   failure. On a deterministic Standard planning failure, stop with `finalization_contract_failure`; do not add a
   Documenter fallback or patch generated artifacts. Return Documenter-owned packet, path, table and rendering errors
   to the same Documenter. Dispatch timestamps, runtime-audit rows and provider closure receipts are Coordinator-owned:
   reconcile them from fresh provider evidence without redispatching Documenter solely to rewrite runtime bookkeeping.
   The finalizer also refreshes handoff provenance from the prepared identity. A continuation package change alone
   requires no Documenter follow-up. If a substantive correction requires reactivation, use the guarded activation
   protocol and prove the worker read the complete current binding before accepting its new result.
   A failed TechOps planning handoff can use explicitly requested `--continuation` and its guarded rejected-result
   correction. Preparation binds the authorization to the exact failure receipt and Run ID; exhausted finalization
   attempts and the one-repair limit still block dispatch. The guard preserves the packet and snapshots its rejected
   bytes, validates accepted upstream audits before Documenter, and requires the new handoff audit at finalization.
   A substantive handoff correction still requires its owning worker and invalidates the affected observations.
   Return errors naming Fix
   Design technical content, worker identity, readiness, blockers, diagnosis, or remediation boundary to the owning
   Fix Design worker before resuming the Documenter; never patch Markdown or technical fields by hand.
   Treat finalizer errors as self-contained received/expected corrections. Do not read or search validator source unless
   an error lacks an expected value or contradicts the documented packet contract.
   For Technical Spike, the emitted canonical handoff already contains the disposition, strongest evidence, unresolved
   decisions, measured budget, next workflow, and artifact links. After successful finalization, send only that block;
   do not add a second summary. If finalization fails, link `finalization_failure.json`; do not claim validation passed.
   A terminal publication failure emits `Workflow-framework validation: failed` and a canonical provisional handoff
   after its JSON error. Copy that complete failed handoff, including saved findings, explanations and engineering
   next steps. Its states describe failed publication; recorded engineering claims are explicitly unverified. Do not
   use the skeleton work record as terminal evidence, claim a passed receipt, or replace the report with a short
   status paragraph. Precheck/pre-release failures remain correction feedback, not user-facing terminal reports.
   If activation, upstream correction, or Documenter execution cannot be recovered within this run, always invoke
   `python3 <packaged-framework-root>/scripts/finalize_work_record.py --packet <artifact-root>/finalization_packet.json`
   `--workflow-failure <exact-reason>`. Before this failure report, reconcile every activated ledger handle, including
   rejected and replacement workers. Refresh the native inventory and collect `runtime_closure.json` through the
   packaged collector's `--closure` route. If a worker is active, follow the provider's supported stop/wait protocol
   and observe it again. If closure cannot be verified, retain a Coordinator-owned Blocked receipt with the concrete
   observation failure. Rejection does not waive closure collection. Never invent terminal observations or withhold
   the failure report when provider evidence is unavailable. TechOps and Feature Delivery failure reporting also
   reconstruct native inventory from the registered provider ledger and save a Terminal or Blocked closure receipt.
   If the ledger was never collected, pass `--provider-session <exact-current-parent-record>` and
   `--parent-thread-id <current-parent-thread-id>` to the failure command. It reconstructs the ledger from native
   dispatches and collects closure against the prepared run start. Missing provider evidence produces a concrete
   Blocked closure receipt; it cannot certify terminal closure.
   Inspect that receipt; it does not replace refreshing the provider inventory before reporting failure.
   This mode needs no invented receipt or implementation
   plan. It writes `finalization_failure.json` and `handoff_failure.md`, preserves recorded analytical contributions,
   limitations, proposed actions and existing artifacts even when `handoff` is empty, and returns exit 2 with the
   canonical
   failed handoff. Copy the complete report. It does not validate findings, overwrite the work-record skeleton or claim
   runtime release. Continue only where the recorded failure and fresh runtime evidence permit it; a fresh run is not
   automatically required. Every post-preparation exit must produce either the successful or failed canonical handoff.
   After each fan-in, check elapsed coordination time and proceed to the next eligible stage. Issue evidence can enable
   independent integration work; record the actual dependency when it must wait. Time spent preparing handoff is part
   of the run, and does not justify ending without terminal reporting.
   The provider event ledger's `timing` records elapsed time, the union of worker-active intervals and time with no
   worker active. Use these observations when reviewing delays; they are not token, cost or CPU measurements.
   Canonical success and failure report artifacts must contain only workflow content. A TechOps Workflow result is a
   plain-language work summary, never a readiness token.
   The canonical report includes its own final Not checked/Risk lines to satisfy concise-response styles; copy those
   lines unchanged. A formatting skill must not replace or shorten the report.
   Finalization writes `handoff_response.md` and a `handoff_delivery.json` receipt with `status: pending`. Work-record
   validation alone is not prepared-response verification. Complete delivery with
   `finalize_work_record.py --packet <packet> --publish-response <artifact-root>/handoff_response.md`.
   This validates and emits the prepared text directly and records `status: verified`; send that output unchanged.
   After publication, the next assistant message is the final answer containing those emitted bytes. Do not perform
   another summary pass. Publisher instructions on stderr are control messages, not part of the canonical stdout.
   If higher-priority instructions require a preamble or footer, keep the canonical artifact unchanged. Save the exact
   required UTF-8 prefix and/or suffix (including separating newlines) in current-run files. Create a separate outgoing
   response containing prefix + complete canonical bytes + suffix. Publish that outgoing file using
   `--presentation-prefix <prefix-file>` and/or `--presentation-suffix <suffix-file>`. The helper verifies exact
   composition and records the surrounding text in the delivery receipt. Do not add discretionary summaries, change
   outcomes, or claim surrounding text is canonical. Missing access, evidence, authorization, or closure still blocks
   the corresponding workflow gate; presentation requirements alone do not.
   Do not end the run with a pending delivery receipt. The preceding `Workflow-framework validation: passed` line is
   a validation diagnostic, not part of the canonical report; do not prepend it to the published response.
   Include the first `Workflow-framework handoff:` line when emitted, even on failure; it is part of the report.
   A verified prepared file is not proof that the final chat response retained that line or the remaining bytes.
   Independent proposed-response files may use `--verify-response`. Only a single terminal LF is optional; internal
   whitespace, labels and content must match. Do not introduce Markdown hard-break spaces.
   Do not silently correct apparent evidence-ID typos in the chat response. Correct the owning packet before
   successful finalization where permitted; a provisional failure report must retain its recorded text verbatim.
   The receipt retains both byte hashes and the comparison policy.
   This verifies prepared text; do not claim the CLI observed actual chat delivery.
   The proposed file must contain the intended outgoing answer; copying the canonical file to another path alone
   does not prove that the chat message used those bytes.
   For failure, compare against `handoff_failure.md`; for success, use the emitted handoff block. A comparison failure
   requires restoring the exact canonical report and any explicitly declared surrounding text.
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
   `Execution:`, and `Provenance:`. Only mandatory, separately declared presentation text may surround the report.
   Copy artifact links exactly from the finalized
   packet. Omit Run Metrics and Worker Timing for normal runs. Use easy-to-read wording in the report and handoff: short
   sentences, common words, and a simple explanation next to each necessary technical term. Technical Spike reports
   must include the required
   `Plain-Language Summary`. The plugin does not override any canonical contract, playbook, template, role, skill, or
   provider policy.
