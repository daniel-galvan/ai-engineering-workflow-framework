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
   report the preflight reason and `preflight_elapsed_ms`.
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
7. Populate the canonical template from supplied and discoverable context. When the prompt requires current-run-only
   evidence, do not read memory, historical `.thoughts` artifacts, or prior-run citations at any later stage. The
   execution repository's `.codex/agents/`
   runtime view is optional. If absent, resolve the bundled provider definitions or selected work-graph model/effort
   binding; record the source and status, and never inherit unverified Coordinator settings. Preserve template field
   names, use `Unknown` or `None` for unavailable values, and ask only for a business, scope, ownership, or approval
   decision that bounded discovery cannot resolve.
8. Execute the selected playbook. Default to `planning`; use `remediation` only when an implementation plan exists and
   the user has explicitly approved implementation. Treat an invocation that says start as a new run. Archive prior
   terminal artifacts under `.thoughts/<WORK-ITEM-ID>/runs/<PRIOR-RUN-ID>/` before initializing a fresh canonical
   record.
   Reuse current artifacts only when the user explicitly says continue or resume. Record the installed plugin
   name/version in Run Identity; manual runs use `Not applicable`. Populate evaluation identity and telemetry only when
   the request explicitly declares an evaluation or benchmark run.
9. Before terminal or blocked handoff, ensure the work record uses the canonical required sections and run
   `python3 <packaged-framework-root>/scripts/validate_library.py`
   `<execution-repository>/.thoughts/<WORK-ITEM-ID>/work_record.md`.
   A nonzero result is a handoff failure: return the record to the same Documenter, correct it, and do not claim
   finalization passed. Use the contract's canonical human-readable handoff and omit Run Metrics and Worker Timing for
   normal runs. The plugin does not override any canonical contract, playbook, template, role, skill, or provider
   policy.
