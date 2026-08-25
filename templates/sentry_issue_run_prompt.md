---
title: Sentry Issue Remediation Run Prompt
version: 0.3.2
status: Pilot
owner: Engineering
last_updated: 2026-08-25
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

Issue: <SENTRY-ISSUE-ID-OR-URL>
Playbook: <PATH-TO>/ai-engineering-workflow-framework/playbooks/sentry_issue_remediation.md
Framework revision (required for evaluation runs): <FULL-GIT-COMMIT>
Framework worktree status: clean

Execution profile: standard
Lifecycle: planning
The selected execution profile is mandatory; do not silently downgrade it.

Execution repository (required; durable artifact root):
<ABSOLUTE-PATH-TO-EXECUTION-REPOSITORY>

If the session runs in a managed worktree of this repository, use that worktree for source operations but keep every
durable `.thoughts/<SENTRY-ISSUE-ID>/` artifact under the declared execution-repository path above.

Provider/runtime configuration (required for Codex evaluation runs; otherwise optional):
<PATH-TO-EXECUTION-REPOSITORY-PROVIDER-CONFIGURATION>

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
- Resolve each named provider agent definition and pass its exact configured model and reasoning effort explicitly when
  the spawn API would otherwise inherit Coordinator settings. Do not adapt or escalate those values. If a required
  definition cannot be resolved or bound, stop with `provider_configuration_unavailable`; do not use inherited defaults.
- Downstream workers consume their provider role, typed assignment, and relevant artifacts. Do not instruct them to
  reread the complete playbook or core contracts.
- For Standard planning, activate one final Documenter after analytical fan-in. An initialization acknowledgement does
  not satisfy final handoff.
- The evidence worker exclusively owns raw Sentry queries and initial repository topology. The Coordinator must not
  pre-query Sentry or duplicate that investigation; request only the latest event first (`limit: 1` when supported).
- Before that worker starts, Standard initialization is limited to turn-start capture, framework/repository/path
  verification, authoritative-input registration, the minimal work-record skeleton, and worker configuration/activation.
  Do not search candidate source, history, tests, or Sentry during initialization.
- Capture the turn-start timestamp before initialization. Count the Coordinator as a logical worker and actual instance,
  not as an activation attempt, and include Coordinator and Documenter elapsed time in final metrics.
- Before worker activation, record the concurrent-run decision. Read-only planning may share a clean revision. When
  another run is active, remediation or any writer requires a separate managed worktree and artifact root. Stop with
  `run_already_active` for the same work item unless this is an explicit continuation or recovery run.
- Every activation packet must include each assigned Input ID's short value, source, authority, and expected use. An ID
  without its value is not a delivered input; reconcile all assigned IDs with `inputs_consumed`.
- Count every successful worker activation, including the final Documenter. Treat a malformed call rejected before
  activation as a coordination error. Invalid metrics still report every authoritative duration that is available.
- Use provider session start and terminal events for worker timing when available; worker-authored artifact timestamps
  are not provider terminal times.
- Use RFC 3339 timestamps with `Z` or a numeric offset. Do not invent or normalize malformed provider timestamps; mark
  metrics invalid and name the missing or unreconciled field.
- For Standard planning, create one minimal work-record skeleton, retain intermediate ledgers in Coordinator state, and
  let the final Documenter perform the next artifact update. Once activated, the Documenter is the sole artifact writer.
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
- If final verification finds a documentation inconsistency, return it to the same Documenter; the Coordinator must not
  edit finalized artifacts after that worker returns.
- Keep the final Documenter live until content, counts, timing, and byte totals pass verification. Send corrections to
  that same handle and close it only after the revised terminal result passes.
- Before release, reconcile the final artifact and answer with the runtime ledger. Workflow state, profile status,
  workflow/task outcome, plan action, worker outcomes, active handles, counts, artifact bytes, runtime closure, and
  metrics validity must agree; return stale `pending` or `active` values to the same Documenter for correction.
- Use canonical Sentry artifacts: `normalized_evidence.md`, and `clarification_brief.md` when the result is
  `awaiting_input`; create `implementation_plan.md` only when the readiness gate allows it.
- The fix-design result must set `plan_readiness` and `implementation_plan_action`. `awaiting_input` means `omit` and
  produces a Clarification Brief; only `ready_for_implementation` permits the Documenter to create a plan.

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
Include the contract's compact `Run metrics:` and `Worker timing:` lines in the final answer; do not replace them with
a work-record link or report coordinator-observed values as `Unknown`. Include coordination errors, handoff revisions,
artifact bytes after the last correction, and metrics validity. Reserve `plan_only` for a run that produced a usable
implementation plan; otherwise use `partially_solved` for useful incomplete diagnosis.
```
