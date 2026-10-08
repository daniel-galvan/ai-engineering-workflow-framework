"""Deterministic roles validation rules."""

from __future__ import annotations

from .common import (
    CODEX_AGENT_DIR,
    ROOT,
    fail,
)


def validate_activation_roles(agent_configs: dict) -> None:
    for agent_name in ("orchestrator", "sentry_orchestrator"):
        instructions = agent_configs[agent_name].get("developer_instructions", "")
        for phrase in (
            "A `wait_agent` timeout is a polling boundary, not a worker failure.",
            "do not call `close_agent`",
            "coordinator_interrupted_after_wait_timeout",
            "A wait timeout or `running` status is",
        ):
            if phrase not in instructions:
                fail(f"{agent_name}.toml is missing safe wait/recovery rule: {phrase}")
        for phrase in (
            "An implementation approval received during a planning conversation",
            "Coordinator-only",
            "Never report remediation complete after",
            "An `in_progress`, `running`, or `awaiting_dependency` status is intermediate",
            "No action is required from the user.",
        ):
            if phrase not in instructions:
                fail(f"{agent_name}.toml is missing remediation barrier rule: {phrase}")
        if "Memory isolation is mandatory for new runs" not in instructions:
            fail(f"{agent_name}.toml is missing memory isolation")

    for agent_name, phrases in {
        "implementer": (
            "delegated current-run Implementer",
            "Delivery Activation Barrier",
            "workflow violation",
            "plan-conformance manifest",
            "replanning_required",
        ),
        "reviewer": (
            "delegated Reviewer inspected the current",
            "accepted delivery review",
            "plan-conformance manifest",
            "contracts/code_review.md",
            "unchanged payload builders",
            "atomic persistence alone",
            "Trigger -> Violated contract -> Concrete impact",
            "scripts/review_evidence.py",
        ),
        "tester": (
            "delegated Reviewer returns `accepted`",
            "terminal result",
        ),
        "documenter": (
            "completed handoff",
            "Activation Barrier shows terminal",
        ),
    }.items():
        instructions = agent_configs[agent_name].get("developer_instructions", "")
        for phrase in phrases:
            if phrase not in instructions:
                fail(f"{agent_name}.toml is missing remediation barrier rule: {phrase}")


def validate_repository_readiness_role(agent_configs: dict) -> None:
    sentry_repository_integrator = agent_configs["sentry_repository_integrator"].get(
        "developer_instructions", ""
    )
    for phrase in (
        "failing or unavailable build or test baseline",
        "do not return `blocked` merely because",
    ):
        if phrase not in sentry_repository_integrator:
            fail(f"sentry_repository_integrator.toml is missing planning-readiness rule: {phrase}")


def validate_delivery_roles() -> None:
    role_requirements = {
        "orchestrator.md": ("Delivery Activation Barrier", "does not implement", "An active worker status is not a handoff"),
        "implementer.md": ("delegated worker", "workflow violation"),
        "reviewer.md": ("delegated Implementer returns a terminal", "accepted delivery review"),
        "tester.md": ("delegated Reviewer accepts the current diff", "terminal result"),
        "documenter.md": ("remediation handoff records terminal Implementer", "runtime closure"),
    }
    for filename, phrases in role_requirements.items():
        role_text = (ROOT / "roles" / filename).read_text()
        for phrase in phrases:
            if phrase not in role_text:
                fail(f"roles/{filename} is missing remediation barrier rule: {phrase}")


def validate_documenter_role() -> None:
    documenter_role = (ROOT / "roles" / "documenter.md").read_text()
    documenter_agent = (CODEX_AGENT_DIR / "documenter.toml").read_text()
    for phrase in ("canonical human-readable", "evaluation or benchmark run", "Provenance:"):
        if phrase not in documenter_role:
            fail(f"Documenter role is missing conditional handoff rule: {phrase}")
        if phrase not in documenter_agent:
            fail(f"Documenter instructions are missing conditional handoff rule: {phrase}")

    for path in (
        ROOT / "skills" / "run" / "SKILL.md",
        CODEX_AGENT_DIR / "orchestrator.toml",
        CODEX_AGENT_DIR / "sentry_orchestrator.toml",
        CODEX_AGENT_DIR / "documenter.toml",
    ):
        text = path.read_text()
        for phrase in ("Workflow result:", "What we established:", "Next action:", "Complete when:", "Provenance:"):
            if phrase not in text:
                fail(f"{path.relative_to(ROOT)} is missing final-summary label: {phrase}")


def validate_coordination_and_delivery_roles() -> None:
    documenter_role = (ROOT / "roles/documenter.md").read_text()
    documenter_agent = (CODEX_AGENT_DIR / "documenter.toml").read_text()
    orchestrator_role = (ROOT / "roles" / "orchestrator.md").read_text()
    orchestrator_agent = (CODEX_AGENT_DIR / "orchestrator.toml").read_text()
    if "runtime-managed worktree" not in orchestrator_role:
        fail("roles/orchestrator.md is missing managed-worktree resolution")
    for phrase in ("managed worktree", "Never cd back to the original checkout", "stop as blocked"):
        if phrase not in orchestrator_agent:
            fail(f"providers/codex/agents/orchestrator.toml is missing worktree control: {phrase}")

    for phrase in ("do not", "spawn an initialize worker"):
        if phrase not in orchestrator_agent:
            fail(f"providers/codex/agents/orchestrator.toml is missing bounded-remediation control: {phrase}")
    for phrase in (
        "never activate or delegate an `initialize` worker",
        "Documenter after analytical fan-in",
    ):
        if phrase not in orchestrator_agent:
            fail(f"providers/codex/agents/orchestrator.toml is missing shared worker-ownership control: {phrase}")

    for phrase in (
        "canonical human-readable format",
        "evaluation or benchmark run",
        "required finalization fields",
    ):
        if phrase not in orchestrator_agent:
            fail(f"providers/codex/agents/orchestrator.toml is missing final-handoff control: {phrase}")
    for phrase in (
        "concurrent-run decision",
        "IDs without values are not delivered",
        "final artifact and answer",
        "Return stale `pending` or",
    ):
        if phrase not in orchestrator_agent:
            fail(f"providers/codex/agents/orchestrator.toml is missing run-integrity control: {phrase}")
    for phrase in (
        "prompt_conformance",
        "run_prompt_nonconformant",
        "evidence_eligibility",
        "including that Documenter",
        "Never patch its artifacts directly",
        "provider_configuration_unavailable",
        "implementation_plan_action",
        "Specification assessment",
    ):
        if phrase not in orchestrator_agent:
            fail(f"providers/codex/agents/orchestrator.toml is missing conformance gate: {phrase}")
    for phrase in (
        "canonical human-readable template",
        "next-action ownership",
        "required finalization fields",
    ):
        if phrase not in orchestrator_role.lower():
            fail(f"roles/orchestrator.md is missing final-handoff ownership: {phrase}")

    for relative, phrases in {
        "providers/codex/agents/implementer.toml": ("Required regression tests are part of implementation", "missing assertions"),
        "providers/codex/agents/tester.toml": ("missing runnable assertions", "Release Follow-up", "candidate"),
        "providers/codex/agents/orchestrator.toml": ("do not leave it as user homework", "Any test/fixture/source edit"),
        "providers/codex/agents/documenter.toml": ("validation_report.md coverage", "Close passed automated checks"),
        "contracts/workflow_execution.md": ("## Delivery Test Completion", "Any source, test or fixture change"),
    }.items():
        content = (ROOT / relative).read_text()
        for phrase in phrases:
            if phrase.lower() not in content.lower():
                fail(f"{relative} is missing test-completion control: {phrase}")

    tester_role = (ROOT / "roles" / "tester.md").read_text()
    tester_agent = (CODEX_AGENT_DIR / "tester.toml").read_text()
    for phrase in ("smallest proving set", "baseline comparison was not performed"):
        if phrase not in tester_role:
            fail(f"roles/tester.md is missing bounded validation control: {phrase}")
    for phrase in ("required local proof first", "known-missing default executables"):
        if phrase not in tester_agent:
            fail(f"providers/codex/agents/tester.toml is missing bounded validation control: {phrase}")

    for text, label in (
        (documenter_role, "roles/documenter.md"),
        (documenter_agent, "providers/codex/agents/documenter.toml"),
    ):
        if "compact execution delta" not in text or "60 seconds" not in text:
            fail(f"{label} is missing bounded remediation documentation control")


def validate_sentry_roles() -> None:
    sentry_orchestrator = (CODEX_AGENT_DIR / "sentry_orchestrator.toml").read_text()
    for phrase in (
        "Pass its exact",
        "binds configuration",
        "Do not instruct downstream workers to reread",
        "minimal work-record skeleton",
        "`standard_planning_finalization.finalizer`",
        "do not activate a Documenter for either readiness result",
        "must not write or",
        "token-based Sentry skill",
        "Do not say `Nothing technical.`",
        "Do not query Sentry",
        "same Documenter before closure",
        "If an analytical worker returned hypotheses",
        "make a stale prompt match",
        "one finalized packet",
        "prompt_conformance",
        "run_prompt_nonconformant",
        "evidence_eligibility",
        "Keep that Documenter handle live",
        "answerable_by_local_source",
        "implementation_plan_action",
        "provider_configuration_unavailable",
        "concurrent-run decision",
        "IDs without values are not delivered",
        "`spawnAgent` return metadata",
        "Never fan-in a worker whose provider binding was not verified",
        "direct children",
        "Inspect the worker tool trace",
        "Fix Design worker outcome is",
        "final artifact and answer",
        "run_already_active",
        "required terminal-field checklist",
        "clarification_brief.md",
        "plugin_revision_mismatch",
        "never spawn or delegate an `initialize` worker",
        "Never semantically normalize or silently",
        "normalize_fix_design_result.py",
        "Workflow-framework validation: passed",
        "fork_context: false",
        "Coordinator initialization: complete",
        "--pre-release",
        "pending closure probe",
        "analytical_contract_failure",
        "finalization_contract_failure",
        "Profile status: executed",
        "before activating Fix Design",
        "inputs_consumed",
        "--analytical-failure",
        "--analytical-failure-stage",
        "canonical `UPSTREAM-001` Input ID",
        "skill or plugin enable/disable directive",
        "captured current turn start is the current run",
        "observed_competing_boundaries",
        "worker_activation_packets.json",
        "worker_runtime_guard",
        "validate_worker_runtime.py --trace",
        "context-unverified",
        "organization identity was unavailable",
        "validated envelope fallback",
        "Never interrupt a live worker",
        "Do not load the `sentry` skill or invoke any Sentry MCP/app",
    ):
        if phrase not in sentry_orchestrator:
            fail(f"providers/codex/agents/sentry_orchestrator.toml is missing Standard control: {phrase}")

    sentry_architect = (CODEX_AGENT_DIR / "sentry_solution_architect.toml").read_text()
    for phrase in (
        "Keep the plan `Draft`",
        "Do not reread the complete playbook",
        "do not remap them unless",
        "one smallest check",
        "During planning, run a unit or integration test only",
        "expected discriminating outcomes",
        "event emitter, comparison owner, baseline producer",
        "implementation_plan_action: omit",
        "fix_design_result.json",
        "invalidates_supported_change",
        "contradicting_evidence_refs",
        "Do not run the",
        "exact activation handle",
        "includes either `UPSTREAM-001`",
        "supported_remediation_boundary` and `supported_intended_change` as strings",
        "fix_design_result_contract.json",
        "assigned `fix_design_result.json`",
        "observed_competing_boundaries",
        "field-preservation change",
        "clarification_brief",
    ):
        if phrase not in sentry_architect:
            fail(f"providers/codex/agents/sentry_solution_architect.toml is missing bounded analysis control: {phrase}")

    sentry_investigator = (CODEX_AGENT_DIR / "sentry_current_state_investigator.toml").read_text()
    for phrase in (
        "Do not reread the complete playbook",
        "reporting repository's stack/culprit entry",
        "Do not inspect an additional repository",
        "event emitter, comparison owner, baseline producer",
        "do not exclude that service from the deployed path",
        "resolve that issue directly before any project or issue",
        "# Contract Delta",
        "Coordinator initialization: complete",
        "--normalized-evidence",
        "normalized_evidence_contract.md",
        "Do not inspect `validate_library.py`",
    ):
        if phrase not in sentry_investigator:
            fail(f"providers/codex/agents/sentry_current_state_investigator.toml is missing bounded evidence control: {phrase}")


def validate_technical_roles() -> None:
    repository_integrator_agent = (CODEX_AGENT_DIR / "repository_integrator.toml").read_text()
    for phrase in ("hypothesis, discriminating outcomes", "Check runner", "defer the command"):
        if phrase not in repository_integrator_agent:
            fail(f"providers/codex/agents/repository_integrator.toml is missing planning-test gating: {phrase}")

    sentry_repository_integrator_agent = (CODEX_AGENT_DIR / "sentry_repository_integrator.toml").read_text()
    for phrase in (
        "answerable_by_local_source: true",
        "decision_expected_to_change: true",
        "concrete question",
        "expected disposition",
        "quarantine it",
        "Check runner availability",
        "decision_changed",
        "low-value integration check",
        "never return `answered`",
        "exact activation handle",
        "list of strings in `inputs_consumed`",
    ):
        if phrase not in sentry_repository_integrator_agent:
            fail(f"providers/codex/agents/sentry_repository_integrator.toml is missing Standard activation/test control: {phrase}")

    solution_architect_agent = (CODEX_AGENT_DIR / "solution_architect.toml").read_text()
    for phrase in (
        "run a unit or integration test only",
        "discriminating outcomes",
        "runner availability",
        "For a specification assessment",
        "plan_readiness: awaiting_input",
    ):
        if phrase not in solution_architect_agent:
            fail(f"providers/codex/agents/solution_architect.toml is missing planning-test gating: {phrase}")

    reviewer_agent = (CODEX_AGENT_DIR / "reviewer.toml").read_text()
    reviewer_role = (ROOT / "roles" / "reviewer.md").read_text()
    solution_architect_role = (ROOT / "roles" / "solution_architect.md").read_text()
    for text, label in (
        (reviewer_agent, "providers/codex/agents/reviewer.toml"),
        (reviewer_role, "roles/reviewer.md"),
        (solution_architect_role, "roles/solution_architect.md"),
    ):
        if "For a specification assessment" not in text or "security or privacy controls" not in text:
            fail(f"{label} is missing specification-readiness control")
