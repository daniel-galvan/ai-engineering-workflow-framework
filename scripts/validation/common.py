"""Deterministic common validation rules."""

from __future__ import annotations

from pathlib import Path
import re
try:
    from asset_manifest import ASSET_MANIFEST_FILENAME
except ModuleNotFoundError:
    from scripts.asset_manifest import ASSET_MANIFEST_FILENAME


ROOT = Path(__file__).resolve().parents[2]

REFERENCE_ID = re.compile(r"\b[A-Za-z][A-Za-z0-9_]*-[A-Za-z0-9][A-Za-z0-9_-]*\b")

REFERENCE_PREFIX = r"[A-Za-z][A-Za-z0-9_]*(?:-[A-Za-z0-9_]+)*-"

REFERENCE_ENDPOINT = rf"{REFERENCE_PREFIX}\d+"

RANGE_REFERENCE = re.compile(
    rf"\b{REFERENCE_ENDPOINT}\s+(?:through|to)\s+(?:{REFERENCE_PREFIX})?\d+\b"
    rf"|\b{REFERENCE_ENDPOINT}\s*(?:\.\.|[–—])\s*(?:{REFERENCE_PREFIX})?\d+\b"
    rf"|\b{REFERENCE_ENDPOINT}-{REFERENCE_ENDPOINT}\b",
    re.IGNORECASE,
)

URL_REFERENCE = re.compile(r"https?://[^\s|`<>]+", re.IGNORECASE)

TECHNICAL_SPIKE_SOURCE_LOCATOR = re.compile(
    r"https?://[^\s|`<>]+"
    r"|(?:^|[\s`(])(?:/|\./|[A-Za-z0-9_.-]+/)[^\s|`<>]+"
    r"|(?<![-\w])[A-Z][A-Z0-9_]+-\d+\b"
    r"|\b[0-9a-f]{7,40}\b"
    r"|`[^`]+`",
    re.IGNORECASE,
)

EXTERNAL_DOCUMENT_URL = re.compile(
    r"https?://[^\s|`<>]*(?:confluence|/wiki(?:/|$)|notion|(?:drive|docs)\.google|/documents?(?:/|$))[^\s|`<>]*",
    re.IGNORECASE,
)

EXTERNAL_DOCUMENT_MARKER = re.compile(
    r"\b(?:confluence|wiki|notion|google\s+drive|drive|document)\b",
    re.IGNORECASE,
)

FORBIDDEN_REPORT_CONTEXT_PATTERNS = (
    ("memory_path", re.compile(r"(?i)(?:^|[/\\])memory\.md(?:$|[/\\])")),
    ("memory_directory", re.compile(r"(?i)(?:^|[/\\])\.codex[/\\]memories(?:$|[/\\])")),
    ("rollout_summary", re.compile(r"(?i)(?:^|[/\\])rollout_summaries(?:$|[/\\])")),
    ("archived_artifact", re.compile(r"(?i)(?:^|[/\\])\.thoughts[/\\][^/\\]+[/\\]runs[/\\]")),
    ("memory_citation", re.compile(r"(?i)<oai-mem-citation>")),
)

STALE_FINALIZER_REFERENCE = (
    r"pending(?:\s+(?:packaged\s+|Coordinator\s+)?finalizer)"
    r"|(?:packaged\s+|Coordinator\s+)?finalizer\s+pending"
)

NO_ACTIVE_HANDLES = re.compile(
    r"^(?:none|0)(?:\s+(?:observed|confirmed) after close request)?$", re.IGNORECASE
)

MODEL_BASELINE_ID = "codex-role-policy-gpt61-sol-luna-orchestrator-v20261001"

POLICY_EFFORTS = {
    "Light": "low",
    "Medium": "medium",
    "High": "high",
    "Extra High": "xhigh",
    "Max": "max",
    "Ultra": "ultra",
}

LARGE_WORK_RECORD_BYTES = 64 * 1024

INTERFACE_CONTRACT_FIELDS = (
    "surface",
    "request_shape",
    "response_shape",
    "absence_semantics",
    "compatibility_precedence",
    "rollout",
)

SENTRY_PLAN_FIELDS = (
    "title",
    "scope",
    "exclusions",
    "root_cause",
    "residual_uncertainty",
    "exact_boundaries",
    "smallest_intended_change",
    "compatibility_and_absence",
    "regression_test_strategy",
    "ordered_steps",
    "rollout",
    "rollback",
    "monitoring",
    "risks",
    "completion_criteria",
)

SENTRY_EVIDENCE_INPUT_MARKERS = ("UPSTREAM-001", "normalized_evidence.md")

JIRA_INTEGRATION = ROOT / "integrations" / "jira.md"

JIRA_FIXTURE = ROOT / "tests" / "fixtures" / "jira_adapter_contract.json"

WORK_ITEM_READ_FIXTURE = ROOT / "tests" / "fixtures" / "work_item_read_contract.json"

JIRA_REQUIRED_HEADINGS = (
    "## Source boundary",
    "## Read path",
    "## Adapter Contract",
    "## Attachment and Asset Inventory",
    "## Context recovery order",
    "## Evidence normalization",
    "## Retrieval result states",
    "## Freshness and reconciliation",
    "## Write boundary",
)

SKILLS = {
    path.stem for path in (ROOT / "skills").glob("*.md") if path.stem != "README"
}

TEMPLATES = list((ROOT / "templates").glob("*_run_prompt.md"))

INVARIANT = "The shared contract and selected playbook own lifecycle, worker activation,"

MATURITY = {"not_exercised", "exercising"}

WORKFLOW_CONTRACT = ROOT / "contracts" / "workflow_execution.md"

WORKFLOW_GUIDANCE = ROOT / "contracts" / "workflow_execution_guidance.md"

WORKFLOW_VOCABULARY = ROOT / "contracts" / "workflow_vocabulary.md"

PORTABLE_HANDOFF_CONTRACT = ROOT / "contracts" / "portable_implementation_handoff.md"

CLAIMS_CONTRACT = ROOT / "contracts" / "claims.md"

WORKFLOW_EVALUATION = ROOT / "frameworks" / "experimental" / "workflow_evaluation.md"

EVALUATION_ADDENDUM = ROOT / "templates" / "evaluation_work_record_addendum.md"

CODEX_POLICY = ROOT / "providers" / "codex" / "model_effort_policy.md"

CODEX_ADAPTER = ROOT / "providers" / "codex.md"

CODEX_AGENT_DIR = ROOT / "providers" / "codex" / "agents"

IMPLEMENTATION_HANDOFF_TEMPLATE = ROOT / "templates" / "implementation_handoff.md"

SENTRY_WORK_RECORD_TEMPLATE = ROOT / "templates" / "sentry_work_record.md"

FINALIZATION_PACKET_TEMPLATE = ROOT / "templates" / "finalization_packet.json"

ASSET_MANIFEST_TEMPLATE = ROOT / "templates" / ASSET_MANIFEST_FILENAME

RUNTIME_CLOSURE_TEMPLATE = ROOT / "templates" / "runtime_closure.json"

RUN_SKILL = ROOT / "skills" / "run" / "SKILL.md"

RUN_PREFLIGHT = ROOT / "scripts" / "run_preflight.py"

PREPARE_RUN = ROOT / "scripts" / "prepare_run.py"

WORKER_RUNTIME_GUARD = ROOT / "scripts" / "validate_worker_runtime.py"

FINALIZE_WORK_RECORD = ROOT / "scripts" / "finalize_work_record.py"

FINALIZE_SENTRY_PLANNING = ROOT / "scripts" / "finalize_sentry_planning.py"

NORMALIZE_FIX_DESIGN_RESULT = ROOT / "scripts" / "normalize_fix_design_result.py"

PLUGIN_MANIFEST = ROOT / ".codex-plugin" / "plugin.json"

SENTRY_FIX_DESIGN_CONTRACT = ROOT / "templates" / "sentry_fix_design_result_contract.json"

SENTRY_NORMALIZED_EVIDENCE_CONTRACT = ROOT / "templates" / "sentry_normalized_evidence_contract.md"

V36_SENTRY_FINALIZATION_FIXTURE = ROOT / "tests" / "fixtures" / "v36_sentry_finalization_regression.json"

V34_SENTRY_FINALIZATION_FIXTURE = ROOT / "tests" / "fixtures" / "v34_sentry_deterministic_finalization.json"

V37_V38_RUNTIME_FIXTURE = ROOT / "tests" / "fixtures" / "v37_v38_sentry_runtime_regressions.json"

V40_RUNTIME_FIXTURE = ROOT / "tests" / "fixtures" / "v40_sentry_worker_runtime.json"

V28_STABILIZATION_FIXTURE = ROOT / "tests" / "fixtures" / "v28_sentry_stabilization.json"

V29_CONTRACT_FAILURE_FIXTURE = ROOT / "tests" / "fixtures" / "v29_sentry_contract_failure.json"

V31_FIX_DESIGN_FIXTURE = ROOT / "tests" / "fixtures" / "v31_sentry_fix_design_contract.json"

V32_FIX_DESIGN_RECOVERY_FIXTURE = ROOT / "tests" / "fixtures" / "v32_sentry_fix_design_recovery.json"

TERMINAL_STATES = {"awaiting_input", "blocked", "ready_for_implementation", "completed"}

ENGINEERING_STATES = {
    "unknown", "understood", "designed", "approved", "implemented", "validated", "released", "stabilized",
    "not_applicable",
}

PROFILE_STATUSES = {"requested", "in_progress", "executed", "not_executed", "blocked"}

PROFILES = {"standard", "deep"}

WORKFLOW_OUTCOMES = {"completed", "incomplete", "blocked"}

ENGINEERING_OUTCOMES = {"solved", "partially_solved", "plan_only", "blocked", "incorrect"}

WORKER_OUTCOMES = {"complete", "needs_input", "blocked", "failed", "not_applicable"}

LIFECYCLES = {"planning", "remediation"}

READINESS_ACTIONS = {
    "ready_for_implementation": "create",
    "awaiting_input": "omit",
}

FEATURE_ASSESSMENT_DISPOSITIONS = {
    "awaiting_input": {"Not ready for implementation"},
    "ready_for_implementation": {"Ready for implementation", "Ready with explicit follow-ups"},
}

TECHNICAL_SPIKE_DISPOSITIONS = {
    "execute technical spike": {
        "Question answered": "solved",
        "Partially answered": "partially_solved",
        "Inconclusive": "partially_solved",
    },
    "review technical spike": {
        "Accepted": "solved",
        "Changes required": "partially_solved",
        "Inconclusive": "partially_solved",
    },
}

BLOCKING_DECISION_TYPES = {
    "business",
    "scope",
    "ownership",
    "incompatible_alternatives",
    "indispensable_evidence",
}

PROHIBITED_CONTEXT_MARKERS = ("MEMORY.md", "/memories/", "<oai-mem-citation>")

UNOBSERVED_MODEL_VALUES = {"", "unknown", "none"}

MODEL_OBSERVATION_UNAVAILABLE_PREFIXES = ("not exposed", "provider telemetry unavailable")

EMPTY_ARTIFACT_VALUES = {"", "unknown", "none", "not applicable", "n/a"}

UNRESOLVED_INTERFACE_MARKERS = re.compile(
    # Proposal wording is allowed when the semantic contract is concrete; unresolved semantics are not.
    r"\b(?:tbd|todo|unknown|not established|to be confirmed|must be confirmed|pending)\b",
    re.IGNORECASE,
)

ROLE_AGENT_ALIASES = {
    "Orchestrator": ("orchestrator",),
    "Current-State Investigator": ("current_state_investigator",),
    "Current-State Investigator / Sentry Evidence": ("current_state_investigator",),
    "Dependency Analyst": ("dependency_analyst",),
    "Repository Integrator": ("repository_integrator",),
    "Solution Architect": ("solution_architect",),
    "Reviewer": ("reviewer",),
    "Implementer": ("implementer",),
    "Tester": ("tester",),
    "Documenter": ("documenter",),
}

SENTRY_ROLE_AGENTS = {
    "Current-State Investigator": "sentry_current_state_investigator",
    "Current-State Investigator / Sentry Evidence": "sentry_current_state_investigator",
    "Evidence topology": "sentry_current_state_investigator",
    "Dependency Analyst": "sentry_dependency_analyst",
    "Failure topology": "sentry_dependency_analyst",
    "Repository Integrator": "sentry_repository_integrator",
    "Repository integration": "sentry_repository_integrator",
    "Solution Architect": "sentry_solution_architect",
    "Fix design": "sentry_solution_architect",
    "Reviewer": "reviewer",
    "Implementer": "implementer",
    "Tester": "tester",
    "Documenter": "documenter",
    "Recovery documenter": "documenter",
}

_WORK_RECORD_ERRORS: list[str] | None = None


def fail(message: str) -> None:
    if _WORK_RECORD_ERRORS is not None:
        _WORK_RECORD_ERRORS.append(message)
        return
    print(f"FAIL: {message}")
    raise SystemExit(1)
