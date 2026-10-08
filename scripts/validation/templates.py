"""Deterministic templates validation rules."""

from __future__ import annotations

from .common import (
    CODEX_POLICY,
    EVALUATION_ADDENDUM,
    IMPLEMENTATION_HANDOFF_TEMPLATE,
    INVARIANT,
    ROOT,
    TEMPLATES,
    WORKFLOW_CONTRACT,
    WORKFLOW_EVALUATION,
    fail,
)


def validate_run_prompt_basics() -> None:
    for path in TEMPLATES:
        text = path.read_text()
        if INVARIANT not in text:
            fail(f"{path.relative_to(ROOT)} is missing the shared run invariants")
        if "Confirmed user decisions and constraints (authoritative; do not reopen):" not in text:
            fail(f"{path.relative_to(ROOT)} is missing the authoritative-input section")
        if "Additional supplied context (preserve and classify):" not in text:
            fail(f"{path.relative_to(ROOT)} is missing the additional-context section")
        for phrase in (
            "Do not search for or add memory-derived facts",
            "`.thoughts` paths",
            "Use `None` for unused optional fields",
        ):
            if phrase not in text:
                fail(f"{path.relative_to(ROOT)} is missing explicit prompt-input admission: {phrase}")
        bootstrap_phrases = (
            "Current explicit user decisions and constraints are authoritative",
            "Delivery Activation Barrier",
            "Never claim successful execution when the required graph is incomplete.",
            "Reserve `plan_only`",
        )
        if path.name == "sentry_issue_run_prompt.md":
            bootstrap_phrases += (
                "prepared worker contracts as the compact runtime surface",
                "do not hydrate the complete playbook",
                "Deep planning and remediation retain",
            )
        else:
            bootstrap_phrases += (
                "Before acting, read the selected playbook plus `contracts/workflow_execution.md` and `contracts/claims.md`",
                "templates and examples are not runtime instructions.",
            )
        for phrase in bootstrap_phrases:
            if phrase not in text:
                fail(f"{path.relative_to(ROOT)} is missing runtime bootstrap rule: {phrase}")


def validate_work_record_template() -> None:
    work_record_template = (ROOT / "templates/work_record.md").read_text()
    if "| Engineering state |" not in work_record_template:
        fail("templates/work_record.md is missing engineering state")
    if "| Approval type |" not in work_record_template:
        fail("templates/work_record.md is missing approval type")
    if "# Path Verification" not in work_record_template:
        fail("templates/work_record.md is missing path verification")
    if "# Input Register" not in work_record_template:
        fail("templates/work_record.md is missing input provenance")
    if "| Input ID |" not in work_record_template or "assigned Input ID" not in work_record_template:
        fail("templates/work_record.md is missing input assignment tracking")
    if "evaluation_work_record_addendum.md" not in work_record_template:
        fail("templates/work_record.md is missing the optional evaluation boundary")
    if not EVALUATION_ADDENDUM.is_file():
        fail("templates/evaluation_work_record_addendum.md is missing")
    if "# Delivery Activation Gate" not in work_record_template:
        fail("templates/work_record.md is missing the delivery activation gate")
    if "# Implementation Conformance Check" not in work_record_template:
        fail("templates/work_record.md is missing implementation conformance")
    if "| Internal owner |" not in work_record_template:
        fail("templates/work_record.md is missing internal-owner handoff guidance")
    if "| Next-action owner |" not in work_record_template:
        fail("templates/work_record.md is missing next-action-owner handoff guidance")
    if "| User action |" not in work_record_template:
        fail("templates/work_record.md is missing user-action handoff guidance")
    for phrase in (
        "# Playbook Selection",
        "| Primary evidence | Primary goal | Selected playbook | Closest alternative | Why this playbook |",
        "| Workflow outcome |",
        "| Engineering outcome |",
    ):
        if phrase not in work_record_template:
            fail(f"templates/work_record.md is missing outcome/classification field: {phrase}")
    for phrase in (
        "# Run Summary",
        "| Playbook / version |",
        "| Framework commit / status |",
        "| Plugin package / version |",
    ):
        if phrase not in work_record_template:
            fail(f"templates/work_record.md is missing evaluation identity: {phrase}")
    for phrase in (
        "# Workflow Receipts",
        "finalization_packet.json",
        "role_bindings.json",
        "runtime_closure.json",
        "finalization_snapshot.<sha256>.json",
        "compact manifest for every assigned Input ID",
    ):
        if phrase not in work_record_template:
            fail(f"templates/work_record.md is missing run-isolation/finalization control: {phrase}")


def validate_planning_and_evaluation_templates() -> None:
    workflow_contract = WORKFLOW_CONTRACT.read_text()
    implementation_plan_template = (ROOT / "templates" / "implementation_plan.md").read_text()
    if "The plan does not authorize implementation" not in implementation_plan_template:
        fail("templates/implementation_plan.md is missing the delivery activation rule")
    if not WORKFLOW_EVALUATION.exists():
        fail("frameworks/experimental/workflow_evaluation.md is missing")
    workflow_evaluation = WORKFLOW_EVALUATION.read_text()
    for heading in ("# Workflow Evaluation", "## Pilot Method", "## Comparison Rules"):
        if heading not in workflow_evaluation:
            fail(f"frameworks/experimental/workflow_evaluation.md is missing {heading}")
    if "recorded role-policy baseline" not in workflow_evaluation:
        fail("frameworks/experimental/workflow_evaluation.md is missing baseline comparison control")
    evaluation_addendum = EVALUATION_ADDENDUM.read_text()
    if "# Workflow Evaluation" not in evaluation_addendum:
        fail("templates/evaluation_work_record_addendum.md is missing workflow evaluation")
    for phrase in (
        "Engineering outcome",
        "Clarifications",
        "Approvals",
        "Manual corrections",
        "Reruns",
        "Human review effort",
        "Control fidelity",
        "Instruction violations",
        "Authoritative inputs ignored",
        "Supplied inputs not consumed",
        "Unapproved plan deviations",
        "Worker elapsed time",
        "Worker wait time",
        "Failed spawns",
        "Handle discrepancies",
        "Replacement workers",
        "Artifact count",
        "Finding-to-plan ratio",
    ):
        if phrase not in workflow_evaluation:
            fail(f"frameworks/experimental/workflow_evaluation.md is missing outcome/burden metric: {phrase}")
        if phrase != "Finding-to-plan ratio" and phrase not in evaluation_addendum:
            fail(f"templates/evaluation_work_record_addendum.md is missing outcome/burden metric: {phrase}")

    for phrase in (
        "MUST NOT manually reproduce or edit the handle",
        "elapsed wall time remains terminal minus activation",
        "one provider handle through finalization",
        "Normal runs MUST NOT include `Run metrics` or `Worker timing`",
        "Provenance: plugin <package and version, or Not applicable>",
        "Use easy-to-read wording",
    ):
        if phrase not in workflow_contract:
            fail(f"contracts/workflow_execution.md is missing runtime integrity rule: {phrase}")

    for prompt_template in TEMPLATES:
        prompt_text = prompt_template.read_text()
        for phrase in ("canonical human-readable", "Run Metrics", "Worker Timing"):
            if phrase not in prompt_text:
                fail(f"{prompt_template.relative_to(ROOT)} is missing canonical handoff instruction: {phrase}")


def validate_evaluation_timing_and_toolchain() -> None:
    workflow_evaluation = WORKFLOW_EVALUATION.read_text()
    if "reported wall time omits Coordinator or documentation" not in workflow_evaluation:
        fail("experimental workflow evaluation is missing complete wall-time evaluation")
    if "reconstructed from worker-stage estimates" not in workflow_evaluation:
        fail("experimental workflow evaluation is missing direct wall-time evaluation")

    implementation_plan = (ROOT / "templates" / "implementation_plan.md").read_text()
    if "Exact tool, version, source, executable path or approved isolated-bootstrap method" not in implementation_plan:
        fail("templates/implementation_plan.md is missing exact toolchain prerequisites")


def validate_sentry_prompt_and_isolation() -> None:
    sentry_prompt = (ROOT / "templates" / "sentry_issue_run_prompt.md").read_text()
    for phrase in (
        "Framework revision",
        "framework_revision_mismatch",
        "make a stale prompt match",
        "exact configured model",
        "packaged deterministic finalizer is the sole writer",
        "initialization acknowledgement",
        "token-based Sentry skill",
        "under the declared execution-repository path",
        "evidence worker exclusively owns raw Sentry queries",
        "same Documenter",
        "Best current explanations",
        "Standard initialization is limited",
        "Repository Integrator only for one recorded cross-repository question",
        "confirmed defect owner",
        "provider_configuration_unavailable",
        "returned model, effort, and fresh-context metadata",
        "`runs/` archives",
        "Memory isolation is mandatory",
        "implementation_plan_action",
        "concurrent-run decision",
        "without its value is not a delivered input",
        "final artifact and answer",
        "canonical Sentry artifacts",
        "plugin_revision_mismatch",
        "never spawn or delegate an `initialize` worker",
        "Never semantically",
        "normalize_fix_design_result.py",
        "Implementation plan",
        "fork_context: false",
        "fix_design_result.json",
        "immutable finalized packet",
        "Work item: <STABLE-WORK-ITEM-ID-OR-URL>",
        "Sentry issue: <SENTRY-ISSUE-ID-OR-URL-OR-NOT-PROVIDED>",
        ".thoughts/<WORK-ITEM-ID>/",
        "skill or plugin enable/disable directive",
        "Pass Fix Design `UPSTREAM-001`",
        "fix_design_result_contract.json",
        "normalized_evidence_contract.md",
        "--completed-worker",
        "captured current turn start is the current run",
        "observed_competing_boundaries",
        "validate_worker_runtime.py --trace",
        "organization slug",
        "field-preservation change",
        "load the `sentry` skill",
        "Pilot Standard finalizer may continue",
    ):
        if phrase not in sentry_prompt:
            fail(f"templates/sentry_issue_run_prompt.md is missing Standard control: {phrase}")

    for path in sorted((ROOT / "templates").glob("*_run_prompt.md")):
        text = path.read_text()
        for phrase in (
            "Framework revision (required for evaluation runs)",
            "Framework worktree status: clean",
            "optional execution-repository runtime view",
            "prompt_conformance",
            "Intended ref:",
            "Workflow outcome",
            "Engineering outcome",
        ):
            if phrase not in text:
                fail(f"{path.relative_to(ROOT)} is missing run-prompt conformance control: {phrase}")


def validate_evaluation_and_provenance() -> None:
    policy_text = CODEX_POLICY.read_text()
    work_record_template = (ROOT / "templates/work_record.md").read_text()
    workflow_evaluation = WORKFLOW_EVALUATION.read_text()
    evaluation_addendum = EVALUATION_ADDENDUM.read_text()
    implementation_plan = (ROOT / "templates/implementation_plan.md").read_text()
    if "Coordinator changes a technical worker's diagnosis" not in workflow_evaluation:
        fail("experimental workflow evaluation is missing coordinator-authority evaluation")
    for phrase in ("duplicates delegated technical", "counts itself as a worker activation attempt", "reported as a blocked workflow"):
        if phrase not in workflow_evaluation:
            fail(f"experimental workflow evaluation is missing run-quality control: {phrase}")
    if "planning runs unit or integration tests that cannot change" not in workflow_evaluation:
        fail("experimental workflow evaluation is missing planning-test efficiency control")
    for phrase in ("Coordination errors", "Handoff revisions", "required metrics are", "`plan_only` is reported"):
        if phrase not in workflow_evaluation:
            fail(f"experimental workflow evaluation is missing metrics-validity control: {phrase}")
    for phrase in (
        "failed `context_conformance`",
        "provider configuration could not be resolved",
        "implementation_plan_action: omit",
        "local-source answerability",
        "nonconformant prompt",
        "undeclared feature branch",
        "unassigned memory material",
        "successful Documenter activation",
        "Invalid metrics must still report",
    ):
        if phrase not in workflow_evaluation:
            fail(f"experimental workflow evaluation is missing conformance evaluation: {phrase}")

    for phrase in ("Planning normally designs these checks", "focused regression that reproduces the verified failure"):
        if phrase not in implementation_plan:
            fail(f"templates/implementation_plan.md is missing test-first execution control: {phrase}")

    if "| Outcome | `in_progress`" in work_record_template:
        fail("templates/work_record.md must not duplicate canonical workflow and engineering outcomes")
    for phrase in ("Configured model/effort", "Provider-observed model/effort", "self-reported model"):
        if phrase not in work_record_template:
            fail(f"templates/work_record.md is missing model-observation distinction: {phrase}")
    if "Framework commit / status" not in work_record_template:
        fail("templates/work_record.md is missing framework-revision provenance")
    if "Plugin package / version" not in work_record_template:
        fail("templates/work_record.md is missing plugin-package provenance")
    for phrase in (
        "Repository Baseline",
        "finalization_packet.json",
    ):
        if phrase not in work_record_template:
            fail(f"templates/work_record.md is missing run-control evidence: {phrase}")
    if "Post-finalization Coordinator edits" not in evaluation_addendum:
        fail("templates/evaluation_work_record_addendum.md is missing evaluation control evidence")
    for phrase in (
        "initial hypothesis: an experimental baseline",
        "Orchestrator | `gpt-6-luna` | Extra High | `xhigh`",
        "Dependency Analyst | `gpt-6-luna` | High | `high`",
        "Repository Integrator | `gpt-6-luna` | High | `high`",
        "Solution Architect | `gpt-6.1-sol` | Light | `low`",
        "Reviewer | `gpt-6.1-sol` | Light | `low`",
    ):
        if phrase not in policy_text:
            fail(f"{CODEX_POLICY.relative_to(ROOT)} is missing experimental baseline: {phrase}")


def validate_portable_handoff_template() -> None:
    if not IMPLEMENTATION_HANDOFF_TEMPLATE.exists():
        fail("templates/implementation_handoff.md is missing")
    implementation_handoff = IMPLEMENTATION_HANDOFF_TEMPLATE.read_text()
    for heading in (
        "# Portable Implementation Handoff",
        "## Start Here",
        "## Receiving-Session Instructions",
        "## Environment Preflight",
        "## Ordered Execution Plan",
        "## Strict Code Review Requirements",
        "## Stop Conditions",
        "## Final Report",
    ):
        if heading not in implementation_handoff:
            fail(f"templates/implementation_handoff.md is missing {heading}")
    for phrase in (
        "This document is self-contained",
        "Execute the approved implementation handoff at:",
        "You are already at the root of the target repository. Follow the handoff exactly.",
        "Target project or component path",
        "sibling projects remain available",
        "Handoff status",
        "One implementation approval covers all in-scope steps",
        "implementation will happen in another session or environment",
        "Same-session implementation does not require a handoff",
        "happy paths",
        "alternate, error, empty",
        "The commands in this table are authoritative",
        "Do not claim independent review",
        "Target branch",
        "current default branch",
        "## Scope Boundaries",
    ):
        if phrase not in implementation_handoff:
            fail(f"templates/implementation_handoff.md is missing {phrase}")
    for phrase in (
        "## Requested Runtime Settings",
        "actual model, effort",
        "provider-specific agents",
        "| Target revision |",
        "`Target revision`",
        "## Scope and Exclusions",
    ):
        if phrase in implementation_handoff:
            fail(f"templates/implementation_handoff.md must not contain runtime-routing detail: {phrase}")
    if "implementation_handoff.md" not in (ROOT / "templates" / "implementation_plan.md").read_text():
        fail("templates/implementation_plan.md does not link the portable handoff")
