---
title: Sentry Issue Remediation Run Prompt
version: 0.4.7
status: Pilot
owner: Engineering
last_updated: 2026-08-27
depends_on:
  - ../contracts/workflow_execution.md
---

# Sentry Issue Remediation Run Prompt

Fill only the run-specific fields. The shared contract and selected playbook own execution behavior. Prompt preparation
must preserve all supplied context and place explicit decisions in the authoritative confirmed-input section.
Populate the prompt only from the current user request, references explicitly named for this run, and facts retrieved
from those references. Do not search for or add memory-derived facts, related tickets, past plans, historical work
records, or `.thoughts` paths unless the user explicitly asks to include them. Use `None` for unused optional fields.

Prompt-preparation rules:

- Treat all user-supplied prose, including context written before the preparation request, as input to classify into the
  fields below.
- Preserve explicit decisions as authoritative constraints.
- Treat possible causes and suspected fault locations as unverified hints.
- Map an explicit flow `A emits or sends to B; B returns a response to A` as `event_origin_repository: A` and
  `downstream_or_return_path: B -> A`. Do not infer these roles from a “primary code repository” label.
- Set `candidate_fault_repository` from the stated suspected fault location; otherwise use `Unknown`. Never swap it with
  the event-origin repository just because it is the primary or execution repository.
- Populate the full framework Git commit and require a clean framework worktree for comparable evaluation runs.

```text
Run the Sentry Issue Remediation playbook.

Work item: <STABLE-WORK-ITEM-ID-OR-URL>
Evidence source: <live_sentry|supplied_occurrence|mixed>
Sentry issue: <SENTRY-ISSUE-ID-OR-URL-OR-NOT-PROVIDED>
Playbook: <PATH-TO>/ai-engineering-workflow-framework/playbooks/sentry_issue_remediation.md
Framework revision (required for evaluation runs): <FULL-GIT-COMMIT>
Framework worktree status: clean
Execution profile: standard
Lifecycle: planning
The selected execution profile is mandatory; do not silently downgrade it.

Execution repository (required; durable artifact root):
<ABSOLUTE-PATH-TO-EXECUTION-REPOSITORY>

If the session runs in a managed worktree of this repository, use that worktree for source operations but keep every
durable `.thoughts/<WORK-ITEM-ID>/` artifact under the declared execution-repository path above.

Provider/runtime configuration (optional execution-repository runtime view; use `Not provided` when absent):
<PATH-TO-EXECUTION-REPOSITORY-PROVIDER-CONFIGURATION-OR-Not-provided>

Continuation (omit this entire section for a new investigation):
- Run type: Planning follow-up / Interrupted profile recovery / Remediation re-entry
- Previous work record, plan, or handoff: <ABSOLUTE-PATH-OR-REFERENCE>
- New evidence, decision, constraint, or recovery reason: <DESCRIPTION>
- Approval reference: <REQUIRED-FOR-REMEDIATION-OR-NONE>

Runtime bootstrap:
- Compare this populated prompt with the canonical template. Record `prompt_conformance` and stop with
  `run_prompt_nonconformant` when a required field is missing or altered.
- Before acting, read the selected playbook plus `contracts/workflow_execution.md` and `contracts/claims.md` from the
  same framework checkout. Load another referenced framework document only when the active stage or worker needs it;
  templates and examples are not runtime instructions.
- The shared contract and selected playbook own lifecycle, worker activation, recovery, fan-in, and handoff behavior.
- Preserve all supplied context. Current explicit user decisions and constraints are authoritative and must not be
  reopened or overridden by historical conclusions.
- The requested profile and lifecycle are mandatory. Planning is read-only; remediation requires explicit approval and
  a passed Delivery Activation Barrier before edits.
- The Coordinator must activate the required workers without substituting for them and report actual worker outcomes,
  fan-in, and runtime closure. Never claim successful execution when the required graph is incomplete.
- Verify the framework revision and clean status before loading instructions. Stop with `framework_revision_mismatch`
  and regenerate the prompt if the checkout differs or is dirty. Do not create, switch, or detach another framework
  worktree to make a stale prompt match.
- Pin the preflight-resolved packaged framework root for the entire run. If that root disappears or changes, stop with
  `plugin_revision_mismatch`; do not discover or switch to another installed plugin package.
- The execution-repository `.codex/agents/` path is an optional runtime view. When it is absent, resolve each named
  provider agent definition from the bundled framework/plugin or selected work-graph binding.
- After preflight, run packaged `scripts/prepare_run.py` once to archive a prior terminal run, initialize the current
  record, and write `role_bindings.json`. Pass each manifest definition's exact configured model and effort explicitly.
  Immediately inspect each provider activation's returned model, effort, and fresh-context metadata against the manifest
  when the runtime exposes those values. If applied model/effort telemetry is unavailable, record `Not exposed; ...`
  together with the exact explicit launch binding; unavailable telemetry alone is not a mismatch. A returned mismatch or
  rejected binding is a configuration-conformance failure and must not reach fan-in. Do not adapt, escalate, or inherit
  Coordinator values. If a required definition cannot be
  resolved or bound, stop with `provider_configuration_unavailable`; do not use inherited defaults.
- Activate every delegated worker with `fork_context: false` or the provider-equivalent fresh-context option. Start
  every packet with `Coordinator initialization: complete` and prohibit the worker from running the launcher skill,
  `run_preflight.py`, or `prepare_run.py`. Use only the current task's in-task `spawn_agent`/collaboration runtime.
  Never use `create_thread`, `fork_thread`, or `send_message_to_thread` for workers. Verify the in-task runtime before
  `prepare_run.py`; stop with `worker_runtime_unavailable` when it is absent.
- Downstream workers consume their provider role, typed assignment, and relevant artifacts. Do not instruct them to
  reread the complete playbook or core contracts.
- Active artifacts are direct children of the current `.thoughts/<WORK-ITEM-ID>/` root. Do not recursively search or
  reuse `runs/` archives unless this is an explicit continuation or recovery run.
- For Standard planning, activate one final Documenter after analytical fan-in. An initialization acknowledgement does
  not satisfy final handoff.
- The Coordinator performs Standard initialization directly; never spawn or delegate an `initialize` worker.
- The evidence worker exclusively owns raw Sentry queries and initial repository topology. The Coordinator must not
  pre-query Sentry or duplicate that investigation. When `Sentry issue` supplies a stable ID or URL, resolve it directly
  before any project or issue search. If direct resolution fails, allow one justified fallback and stop.
  Request the latest event first (`limit: 1` when supported). For Standard, allow one tool-discovery call.
  Allow at most three Sentry data queries, 30 seconds per query, and 90 seconds total. Never enumerate projects or fan
  out across organizations and
  datasets. When only a supplied occurrence exists, use it without broad Sentry discovery.
- Before that worker starts, Standard initialization is limited to turn-start capture, framework/repository/path
  verification, authoritative-input registration, the minimal work-record skeleton, and worker configuration/activation.
  Do not search candidate source, history, tests, or Sentry during initialization.
- Before worker activation, record the concurrent-run decision. Read-only planning may share a clean revision. When
  another run is active, remediation or any writer requires a separate managed worktree and artifact root. Stop with
  `run_already_active` for the same work item unless this is an explicit continuation or recovery run.
- Before recording no active related run, check provider-visible active tasks and sibling work-item artifact roots.
  Record the method and timestamp; when neither is available, record `Unknown; detection unavailable`, not `None`.
- Every activation packet must include each assigned Input ID's short value, source, authority, and expected use. An ID
  without its value is not a delivered input; reconcile all assigned IDs with `inputs_consumed`.
- When a user supplies a relative framework artifact reference, preserve it and include the verified canonical path in
  the same input manifest. Do not report the relative reference unavailable when the canonical artifact is delivered.
- Do not poll a released handle. Count any post-closure poll as a coordination error and report it separately.
- For Standard planning, create one minimal work-record skeleton. Start the evidence worker after initialization;
  validate completed `normalized_evidence.md`, then activate Fix Design with that exact artifact. Retain intermediate
  ledgers in Coordinator state. Once activated, the final Documenter is the
  sole artifact writer for the finalized artifact set.
- Pass Fix Design the exact validated `normalized_evidence.md` path as a required upstream artifact and every original
  supporting artifact path. Do not activate it while normalized evidence is absent or still being written; do not replace either with a
  Coordinator-written summary.
- Require normalized evidence to contain the playbook's canonical Contract Delta table with its Markdown separator,
  exact five boundary rows, and evidence references. Accept any Markdown heading level for `Contract Delta`.
- Select `live_sentry` from an explicit Sentry issue URL or separately identified Sentry issue ID. When this Sentry
  playbook is selected and the prompt describes the occurrence as a Sentry issue, treat a Sentry-shaped work-item key as
  a candidate issue ID and attempt direct resolution once without search. On success use `live_sentry` or `mixed`; on
  failure retain `supplied_occurrence`. Never declare the key non-Sentry before the direct attempt.
- Require Evidence Topology to run `validate_library.py --normalized-evidence <artifact-path>` before returning. A
  producer-format repair within the initial activation does not consume the analytical correction allowance.
- During planning, run a unit or integration test only when one existing focused command can change the diagnosis,
  owning boundary, or readiness. First record the hypothesis, discriminating outcomes, disposition change, and runner
  availability. Otherwise put the regression and remaining suites in the implementation plan.
- For Standard, activate Repository Integrator only for one recorded cross-repository question, the local evidence that
  can answer it, and the exact ownership, readiness, or scope disposition that will change. If that disposition cannot
  be stated or the question requires production state, skip it. Record both gate answers; missing production state that
  local source cannot supply fails the gate.
- Before any repository becomes evidence, record its role, branch, full revision, clean status, selected ref, release
  mapping, and evidence eligibility. Reject undeclared feature-branch behavior as baseline or production evidence.
- Quarantine any provider-required memory pass. Reject a worker result when unassigned memory or historical material
  appears in its artifact, citation, claim, hypothesis, decision, or conclusion; self-attestation is insufficient.
- Separate event emitter, comparison owner, baseline producer, deployed route owner, candidate divergence owner, and
  confirmed defect owner. A local checkout mismatch does not exclude a deployed service without release mapping.
- Pass the final Documenter one immutable finalized packet. It populates `templates/finalization_packet.json` as the
  structured `finalization_packet.json`; it does not select, normalize, or reinterpret state, readiness, outcomes,
  worker results, or artifact actions. While that worker remains active, the Coordinator runs packaged
  `scripts/finalize_work_record.py --pre-release` against a pending closure probe and returns any error to the same
  worker. After the pre-release check passes, release the worker, write exact provider closure rows to
  `runtime_closure.json`, then run the finalizer normally; neither role patches terminal Markdown by hand.
- If finalization finds inconsistencies, return the aggregated error to the same Documenter once; the Coordinator must
  not edit the packet or rendered record. If the corrected packet still fails, stop within two minutes with
  `finalization_contract_failure`, preserve the error and artifacts, and release all handles.
- Before release, reconcile the final artifact and answer with the durable record. Workflow state, profile status,
  workflow/engineering outcome, plan action, worker outcomes, active handles, artifacts, and runtime closure must agree;
  return stale `pending` or `active` values to the same Documenter for correction.
- Finalization must retain the contract's required terminal fields and playbook artifact set. Keep `state`,
  `engineering_state`, `workflow_outcome`, and `engineering_outcome` distinct and copy their exact values to the final
  answer as `Workflow outcome` and `Engineering outcome`; matching artifact counts alone do not pass.
- Use canonical Sentry artifacts: `normalized_evidence.md`, `fix_design_result.json`, and `clarification_brief.md` when
  the result is `awaiting_input`; create `implementation_plan.md` only when the readiness gate allows it.
- The fix-design result must be one structured JSON object containing the shared identity, input, conformance, checks,
  supported boundary/change, `interface_change`, `interface_contract`, `plan_readiness`,
  `implementation_plan_action`, and blocking-unknown fields. For an interface change, the contract must state the exact
  surface, request and response shapes, absence semantics, compatibility precedence, and rollout. The Documenter
  persists it verbatim as `fix_design_result.json` and copies the contract into the plan.
- `awaiting_input` means `omit` and produces a Clarification Brief. Every blocker must identify its decision type,
  question, unavailable reason, evidence, and at least two materially different fix implications. Do not defer an
  established boundary and intended change unless every blocker is evidenced to invalidate that change. Any blocker
  marked `invalidates_supported_change: true` must include `contradicting_evidence_refs` to observed current-run
  evidence for a materially different boundary or fix; a missing observation is not contradictory evidence. Only
  `ready_for_implementation` permits the Documenter to create a plan.
- Validate each terminal envelope before fan-in. Return an invalid enum or readiness/action pair to the same worker;
  never normalize or silently repair it in Coordinator state. Send each analytical worker at most one aggregated
  correction. If its corrected result still fails, stop with `analytical_contract_failure`, preserve the errors and
  artifacts, and release all handles; do not resume or replace that worker.
- After an analytical contract failure, mechanically finalize the packet, closure receipt, and authoritative work
  record with packaged `finalize_work_record.py --analytical-failure` and its required runtime, framework, and evidence
  arguments before answering. The final response must be copied from that finalized record.

Additional repositories and working directories (optional; the execution
repository is already declared):
- Path: <REPOSITORY-OR-DIRECTORY-OR-NONE>
  Intended ref: <USER-SELECTED-BRANCH-REVISION-OR-UNKNOWN>

Confirmed user decisions and constraints (authoritative; do not reopen):
- <NONE-OR-DECISION-OR-CONSTRAINT>

Initial topology hypothesis:
- Event-origin repository: <REPOSITORY-OR-UNKNOWN>
- Candidate fault repository: <REPOSITORY-OR-UNKNOWN>
- Candidate fault component: <COMPONENT-OR-UNKNOWN>
- Downstream or return path: <PATH-OR-UNKNOWN>

Reporter context and investigation hints (optional; unverified until reconciled):
- Observed symptom: <SYMPTOM-OR-NONE>
- Expected behavior: <EXPECTED-BEHAVIOR-OR-UNKNOWN>
- Suspected flow, owner, file, or component: <HINT-OR-NONE>
- Reproduction clues or known edge cases: <HINT-OR-NONE>
- Known exclusions or related links: <HINT-OR-NONE>

Additional supplied context (preserve and classify):
- <NONE-OR-DESCRIPTION-OR-REFERENCE>

Optional supporting artifacts:
- <NONE-OR-ABSOLUTE-PATH>

Integration:
- Use the playbook's configured Sentry MCP integration.
- Do not request or use SENTRY_AUTH_TOKEN.
- Do not load a token-based Sentry skill when the configured MCP integration is available.

Additional run-specific constraints or approvals:
- For `planning`: no source or external-system changes.
- For `remediation`: execute only the approved implementation plan after the
  explicit approval gate and required-worker fan-in; do not update external
  systems without separate approval.
- <NONE-OR-ENTER-CONSTRAINT>

Follow the selected playbook and its required dependencies.

At handoff, report requested/executed profile, profile status,
required-worker activation, fan-in status, and runtime-closure status.
If analytical workers returned hypotheses, include `Best current explanations`: the strongest hypothesis and up to two
alternatives, with confidence and one short reason each. Use common words, short sentences, and explain framework terms.
Use the contract's canonical human-readable handoff. Do not include Run Metrics or Worker Timing unless this prompt
explicitly declares an evaluation or benchmark run. Reserve `plan_only` for a run that produced a usable implementation
plan; otherwise use `partially_solved` for useful incomplete diagnosis. Preserve distinct `Workflow outcome` and
`Engineering outcome` fields. Use the exact ordered labels and canonical enum spellings from the contract, including
`State`, `Workflow outcome`, `Engineering outcome`, and `Implementation plan`. Copy artifact paths exactly.
```
