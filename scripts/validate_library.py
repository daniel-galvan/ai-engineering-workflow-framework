#!/usr/bin/env python3
"""Static consistency checks for the workflow-framework pilot."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import tomllib
from contextlib import redirect_stdout
from collections import Counter
from io import StringIO
from pathlib import Path

try:
    from run_input_manifest import load_manifest
except ModuleNotFoundError:  # Imported as scripts.validate_library from the repository root.
    from scripts.run_input_manifest import load_manifest


ROOT = Path(__file__).resolve().parents[1]
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
RFC3339_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)
REFERENCE_ID = re.compile(r"\b[A-Za-z][A-Za-z0-9_]*-[A-Za-z0-9][A-Za-z0-9_-]*\b")
MODEL_BASELINE_ID = "codex-role-policy-v20260827032839"
POLICY_EFFORTS = {
    "Light": "low",
    "Medium": "medium",
    "High": "high",
    "Extra High": "xhigh",
    "Max": "max",
    "Ultra": "ultra",
}
MAX_MARKDOWN_PROSE_WIDTH = 120
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
SKILLS = {
    path.stem for path in (ROOT / "skills").glob("*.md") if path.stem != "README"
}
TEMPLATES = list((ROOT / "templates").glob("*_run_prompt.md"))
INVARIANT = "The shared contract and selected playbook own lifecycle, worker activation,"
MATURITY = {"not_exercised", "exercising"}
EXERCISE_COMBINATIONS = (
    "standard + planning",
    "deep + planning",
    "standard + remediation",
    "deep + remediation",
)
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

ROLE_AGENT_ALIASES = {
    "Orchestrator": ("orchestrator",),
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
_ALLOW_UNRELEASED = False


def fail(message: str) -> None:
    if _WORK_RECORD_ERRORS is not None:
        _WORK_RECORD_ERRORS.append(message)
        return
    print(f"FAIL: {message}")
    raise SystemExit(1)


def table_cells(line: str) -> list[str]:
    content = line.strip()[1:-1]
    cells: list[str] = []
    current: list[str] = []
    index = 0
    while index < len(content):
        if content[index:index + 2] == r"\|":
            current.append("|")
            index += 2
            continue
        if content[index] == "|":
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(content[index])
        index += 1
    cells.append("".join(current).strip())
    return cells


def is_table_row(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|")


def frontmatter(text: str) -> list[str]:
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        return []
    try:
        return lines[1 : lines.index("---", 1)]
    except ValueError:
        return []


def frontmatter_value(path: Path, field: str) -> str | None:
    prefix = f"{field}:"
    return next(
        (line.split(":", 1)[1].strip() for line in frontmatter(path.read_text()) if line.startswith(prefix)),
        None,
    )


def markdown_table(text: str, heading: str) -> list[dict[str, str]]:
    lines = text.splitlines()
    try:
        start = lines.index(heading) + 1
    except ValueError:
        return []
    while start < len(lines) and not is_table_row(lines[start]):
        if lines[start].startswith("#"):
            return []
        start += 1
    if start + 1 >= len(lines):
        return []
    headers = table_cells(lines[start])
    separator = table_cells(lines[start + 1])
    if len(headers) != len(separator) or not all("-" in cell for cell in separator):
        return []
    rows = []
    for line in lines[start + 2 :]:
        if not is_table_row(line):
            break
        cells = table_cells(line)
        if len(headers) != len(cells):
            return []
        rows.append(dict(zip(headers, cells, strict=True)))
    return rows


def fenced_section(text: str, heading: str) -> str:
    match = re.search(rf"^{re.escape(heading)}\s*\n+```text\s*\n(.*?)\n```", text, re.MULTILINE | re.DOTALL)
    return match.group(1) if match else ""


def _artifact_path(value: str, record_path: Path) -> Path | None:
    value = value.strip()
    if value.lower() in EMPTY_ARTIFACT_VALUES:
        return None
    if value.startswith("[") and "](" in value and value.endswith(")"):
        value = value.split("](", 1)[1][:-1]
    candidate = Path(value)
    return candidate.resolve() if candidate.is_absolute() else (record_path.parent / candidate).resolve()


def current_artifact_errors(
    rows: list[dict[str, str]], record_path: Path, artifact_root_value: str, *, require_files: bool = True
) -> list[str]:
    errors = []
    if not artifact_root_value.strip():
        return [f"{record_path}: Durable Artifacts requires a durable artifact root"]
    root = Path(artifact_root_value.strip())
    if not root.is_absolute():
        return [f"{record_path}: durable artifact root must be absolute"]
    root = root.resolve()
    if not rows:
        return [f"{record_path}: Durable Artifacts must contain populated rows"]
    for row in rows:
        artifact = row.get("Artifact", "").strip() or "unnamed"
        target = _artifact_path(row.get("Path", ""), record_path)
        if target is None:
            errors.append(f"{record_path}: durable artifact {artifact} has no path")
            continue
        if not target.is_relative_to(root):
            errors.append(f"{record_path}: durable artifact {artifact} escapes the current artifact root")
        elif target.parent != root:
            errors.append(f"{record_path}: durable artifact {artifact} must be a current-run root file, not an archive")
        if require_files and not target.is_file() and not (
            target.name == "work_record.md" and target.parent == record_path.parent
        ):
            errors.append(f"{record_path}: durable artifact {artifact} does not exist: {target}")
    return errors


def reasoning_record_errors(text: str) -> list[str]:
    errors = []
    tables = (
        ("evidence", "# Evidence", "Evidence ID"),
        ("claim", "# Claims", "Claim ID"),
        ("decision", "# Decision Log", "Decision ID"),
        ("action", "# Action Log", "Action ID"),
    )
    records = {}
    for label, heading, key in tables:
        rows = markdown_table(text, heading)
        ids = [row.get(key, "") for row in rows if row.get(key, "")]
        for duplicate in sorted(value for value, count in Counter(ids).items() if count > 1):
            errors.append(f"duplicate {label} {duplicate}")
        records[label] = {row.get(key, ""): row for row in rows if row.get(key, "")}
    evidence, claims, decisions, actions = (records[label] for label, _, _ in tables)

    if not all((evidence, claims, decisions, actions)):
        errors.append("must contain populated Evidence, Claims, Decision Log, and Action Log tables")
        return errors

    evidence_used = set()
    claims_used = set()
    decisions_used = set()
    for evidence_id, row in evidence.items():
        if not row.get("Source") or row["Source"] in {"Unknown", "None"}:
            errors.append(f"{evidence_id} has no source")
    for claim_id, row in claims.items():
        refs = set(REFERENCE_ID.findall(row.get("Evidence refs", "")))
        if not refs:
            errors.append(f"{claim_id} has no evidence refs")
        for ref in refs:
            if ref not in evidence:
                errors.append(f"{claim_id} references missing evidence {ref}")
            else:
                evidence_used.add(ref)
    for decision_id, row in decisions.items():
        refs = set(REFERENCE_ID.findall(row.get("Claim refs", "")))
        if not refs:
            errors.append(f"{decision_id} has no claim refs")
        for ref in refs:
            if ref not in claims:
                errors.append(f"{decision_id} references missing claim {ref}")
            else:
                claims_used.add(ref)
    for action_id, row in actions.items():
        refs = set(REFERENCE_ID.findall(row.get("Decision ref", "")))
        if len(refs) != 1:
            errors.append(f"{action_id} must reference exactly one decision")
        for ref in refs:
            if ref not in decisions:
                errors.append(f"{action_id} references missing decision {ref}")
            else:
                decisions_used.add(ref)

    for label, records, used in (
        ("evidence", evidence, evidence_used),
        ("claim", claims, claims_used),
        ("decision", decisions, decisions_used),
    ):
        for orphan in sorted(set(records) - used):
            errors.append(f"orphaned {label} {orphan}")
    return errors


def sentry_contract_delta_errors(text: str) -> list[str]:
    lines = text.splitlines()
    heading_index = next(
        (index for index, line in enumerate(lines) if re.fullmatch(r"#{1,6}\s+Contract Delta\s*", line)),
        None,
    )
    if heading_index is None:
        return ["normalized evidence requires a Contract Delta heading at any Markdown heading level"]
    table_index = heading_index + 1
    while table_index < len(lines) and not lines[table_index].strip():
        table_index += 1
    if table_index >= len(lines) or not is_table_row(lines[table_index]):
        return ["contract delta heading must be followed by a Markdown table header"]
    expected_headers = ("Boundary", "Representation", "Field identity / coordinate space", "Evidence refs")
    headers = table_cells(lines[table_index])
    if tuple(headers) != expected_headers:
        return [f"contract delta table headers must be: {' | '.join(expected_headers)}"]
    if table_index + 1 >= len(lines) or not is_table_row(lines[table_index + 1]):
        return ["contract delta table requires a Markdown separator row immediately after the header"]
    separator = table_cells(lines[table_index + 1])
    if len(separator) != len(headers) or not all(
        "-" in cell and set(cell) <= {"-", ":"} for cell in separator
    ):
        return ["contract delta table requires a Markdown separator row immediately after the header"]
    rows = []
    for line_number, line in enumerate(lines[table_index + 2:], table_index + 3):
        if not is_table_row(line):
            break
        cells = table_cells(line)
        if len(cells) != len(headers):
            return [f"contract delta row {line_number} has {len(cells)} cells; expected {len(headers)}"]
        rows.append(dict(zip(headers, cells, strict=True)))
    if not rows:
        return ["contract delta table requires five populated boundary rows"]
    required = {"Baseline", "Outbound", "Destination input", "Return", "Semantic input equivalence"}
    boundaries = [row.get("Boundary", "") for row in rows]
    errors = []
    for duplicate, count in Counter(boundaries).items():
        if duplicate and count > 1:
            errors.append(f"contract delta contains duplicate boundary: {duplicate}")
    by_boundary = {row.get("Boundary", ""): row for row in rows}
    for boundary in sorted(required - set(by_boundary)):
        errors.append(f"contract delta is missing boundary: {boundary}")
    for boundary in required & set(by_boundary):
        row = by_boundary[boundary]
        for field in ("Representation", "Field identity / coordinate space", "Evidence refs"):
            if not row.get(field, "").strip():
                errors.append(f"contract delta {boundary} is missing {field}")
    semantic = by_boundary.get("Semantic input equivalence", {}).get("Representation", "").lower()
    if semantic and semantic not in {"equivalent", "not_equivalent", "not_established"}:
        errors.append("contract delta Semantic input equivalence has an invalid representation")
    return errors


def _sentry_contract_delta_rows(text: str) -> dict[str, dict[str, str]]:
    """Return the validated Contract Delta rows for semantic boundary checks."""
    if sentry_contract_delta_errors(text):
        return {}
    lines = text.splitlines()
    heading_index = next(
        (index for index, line in enumerate(lines) if re.fullmatch(r"#{1,6}\s+Contract Delta\s*", line)),
        None,
    )
    if heading_index is None:
        return {}
    table_index = heading_index + 1
    while table_index < len(lines) and not lines[table_index].strip():
        table_index += 1
    rows: list[dict[str, str]] = []
    for line in lines[table_index + 2 :]:
        if not is_table_row(line):
            break
        cells = table_cells(line)
        if len(cells) != 4:
            return {}
        rows.append(dict(zip(
            ("Boundary", "Representation", "Field identity / coordinate space", "Evidence refs"),
            cells,
            strict=True,
        )))
    return {row["Boundary"]: row for row in rows}


def sentry_upstream_boundary_errors(
    normalized_evidence: str, fix_design: dict[str, object], *, require_plan: bool
) -> list[str]:
    """Ensure a field-loss delta cannot be finalized as a downstream-only fix."""
    if not require_plan or fix_design.get("plan_readiness") != "ready_for_implementation":
        return []
    rows = _sentry_contract_delta_rows(normalized_evidence)
    if not rows:
        return []
    delta_fields = ("Representation", "Field identity / coordinate space")
    baseline = " ".join(rows.get("Baseline", {}).get(field, "") for field in delta_fields).lower()
    outbound = " ".join(rows.get("Outbound", {}).get(field, "") for field in delta_fields).lower()
    destination = " ".join(rows.get("Destination input", {}).get(field, "") for field in delta_fields).lower()
    field_keyed = any(
        marker in baseline for marker in ("field-keyed", "field keyed", "link_title", "link_summary")
    )
    scalar_loss = any(
        marker in value
        for value in (outbound, destination)
        for marker in ("scalar", "message-only", "identity lost", "no field identity", "no outbound")
    )
    if not (field_keyed and scalar_loss):
        return []

    plan = fix_design.get("plan")
    contract = fix_design.get("interface_contract")
    boundary_rows = plan.get("exact_boundaries") if isinstance(plan, dict) else None
    has_upstream_boundary = False
    if isinstance(boundary_rows, list):
        for row in boundary_rows:
            if not isinstance(row, dict):
                continue
            repository = str(row.get("repository", "")).lower()
            symbols = " ".join(str(value) for value in row.get("files_symbols", [])).lower()
            boundary_text = f"{repository} {symbols}"
            if "fanmgmt" in boundary_text and any(
                marker in symbols
                for marker in ("publisher", "workflow.py", "_publish_to_eos", "serializer", "request")
            ):
                has_upstream_boundary = True
                break
    request_shape = str(contract.get("request_shape", "")).lower() if isinstance(contract, dict) else ""
    adds_field_keyed_request = any(
        marker in request_shape
        for marker in ("field-keyed", "field keyed", "text_fields", "link_title", "link_summary")
    ) and not re.search(
        r"\bno\s+(?:inbound\s+)?request|\b(?:no|without)\s+.*(?:field|title|summary)",
        request_shape,
    )
    if has_upstream_boundary and adds_field_keyed_request:
        return []
    return [
        "ready fix design must address the observed upstream field-preservation delta: "
        "include the producer boundary and an affirmative field-keyed request change"
    ]


def fix_design_result_errors(
    data: object, *, required_input_markers: tuple[str, ...] = (), require_plan: bool = False
) -> list[str]:
    if not isinstance(data, dict):
        return ["fix_design_result.json must contain one object"]
    errors = []
    required = {
        "worker_id",
        "worker_handle",
        "outcome",
        "plan_readiness",
        "implementation_plan_action",
        "inputs_consumed",
        "context_conformance",
        "configuration_conformance",
        "checks_performed",
        "checks_remaining",
        "supported_remediation_boundary",
        "supported_intended_change",
        "interface_change",
        "interface_contract",
        "blocking_unknowns",
        "confidence",
    }
    missing = sorted(
        field for field in required
        if field not in data and (field != "confidence" or require_plan)
    )
    if missing:
        errors.append(f"fix design result is missing fields: {', '.join(missing)}")
        return errors
    readiness = data["plan_readiness"]
    action = data["implementation_plan_action"]
    if readiness not in READINESS_ACTIONS:
        errors.append(f"invalid plan_readiness: {readiness}")
    elif action != READINESS_ACTIONS[readiness]:
        errors.append(f"{readiness} requires implementation_plan_action: {READINESS_ACTIONS[readiness]}")
    if data["outcome"] != "complete":
        errors.append("fix design outcome must be complete before finalization")
    for field in ("worker_id", "worker_handle", "configuration_conformance"):
        if not isinstance(data[field], str) or not data[field].strip():
            errors.append(f"fix design {field} must be a non-empty string")
    if isinstance(data["worker_handle"], str) and data["worker_handle"].strip().lower() in {
        "not exposed", "unknown", "none", "not applicable",
    }:
        errors.append("fix design worker_handle must contain the exact activation handle")
    if (
        not isinstance(data["inputs_consumed"], list)
        or not data["inputs_consumed"]
        or not all(isinstance(value, str) and value.strip() for value in data["inputs_consumed"])
    ):
        errors.append("fix design inputs_consumed must be a non-empty list")
    elif required_input_markers and not any(
        marker in value for value in data["inputs_consumed"] for marker in required_input_markers
    ):
        errors.append(
            "fix design inputs_consumed must include " + " or ".join(required_input_markers)
        )
    if data["context_conformance"] != "pass":
        errors.append("fix design context_conformance must pass")
    for field in ("supported_remediation_boundary", "supported_intended_change"):
        if not isinstance(data[field], str):
            errors.append(f"fix design {field} must be a string")
    for field in ("checks_performed", "checks_remaining", "blocking_unknowns"):
        if not isinstance(data[field], list):
            errors.append(f"fix design {field} must be a list")
    if not isinstance(data["interface_change"], bool):
        errors.append("fix design interface_change must be true or false")
    confidence = data.get("confidence")
    if confidence is not None or require_plan:
        if not isinstance(confidence, dict):
            errors.append("fix design confidence must be an object with level, basis, and limits")
        else:
            for field in ("level", "basis", "limits"):
                if not isinstance(confidence.get(field), str) or not confidence[field].strip():
                    errors.append(f"fix design confidence {field} must be a non-empty string")
    if errors:
        return errors
    boundary = data["supported_remediation_boundary"]
    intended_change = data["supported_intended_change"]
    blockers = data["blocking_unknowns"]
    interface_change = data["interface_change"]
    interface_contract = data["interface_contract"]
    if bool(boundary.strip()) != bool(intended_change.strip()):
        errors.append("supported remediation boundary and intended change must be provided together")
    if readiness == "ready_for_implementation":
        if "clarification_brief" in data:
            errors.append("ready fix design must omit clarification_brief")
        if not isinstance(boundary, str) or not boundary.strip():
            errors.append("ready fix design requires a supported remediation boundary")
        if not isinstance(intended_change, str) or not intended_change.strip():
            errors.append("ready fix design requires a supported intended change")
        if blockers:
            errors.append("ready fix design cannot retain blocking_unknowns")
        if interface_change:
            if not isinstance(interface_contract, dict):
                errors.append("ready interface change requires interface_contract")
            else:
                for field in INTERFACE_CONTRACT_FIELDS:
                    value = interface_contract.get(field)
                    if not isinstance(value, str) or not value.strip():
                        errors.append(f"interface_contract {field} must be a non-empty string")
                request_shape = str(interface_contract.get("request_shape", "")).lower()
                response_shape = str(interface_contract.get("response_shape", "")).lower()
                field_keyed = any(
                    marker in request_shape
                    for marker in ("field-keyed", "field keyed", "text_fields", "link_title", "link_summary")
                )
                local_extents = "extent" in response_shape and any(
                    marker in response_shape for marker in ("field", "local", "source")
                )
                explicit_identity = (
                    "field" in response_shape
                    and any(marker in response_shape for marker in ("property", "key", "identity", "qualified"))
                    and "no new response property" not in response_shape
                    and "unqualified" not in response_shape
                )
                if field_keyed and local_extents and not explicit_identity:
                    errors.append(
                        "field-local multi-field extents require explicit response-side field identity"
                    )
        elif interface_contract is not None:
            errors.append("non-interface change requires interface_contract: null")
        plan = data.get("plan")
        if require_plan and not isinstance(plan, dict):
            errors.append("ready fix design requires structured plan content")
        elif isinstance(plan, dict):
            missing_plan_fields = [field for field in SENTRY_PLAN_FIELDS if field not in plan]
            if missing_plan_fields:
                errors.append("ready fix design plan is missing fields: " + ", ".join(missing_plan_fields))
            for field in ("title", "root_cause"):
                if field in plan and (not isinstance(plan[field], str) or not plan[field].strip()):
                    errors.append(f"ready fix design plan {field} must be a non-empty string")
            for field in set(SENTRY_PLAN_FIELDS) - {"title", "root_cause", "residual_uncertainty"}:
                if field in plan and not isinstance(plan[field], list):
                    errors.append(f"ready fix design plan {field} must be a list")
            for field in ("ordered_steps", "completion_criteria"):
                if field in plan and isinstance(plan[field], list) and not plan[field]:
                    errors.append(f"ready fix design plan {field} must not be empty")
    elif readiness == "awaiting_input":
        if "plan" in data:
            errors.append("awaiting_input fix design must omit plan")
        if not data["checks_performed"]:
            errors.append("awaiting_input requires at least one performed discriminating check")
        if not blockers:
            errors.append("awaiting_input requires at least one structured blocking unknown")
        for index, blocker in enumerate(blockers, start=1):
            if not isinstance(blocker, dict):
                errors.append(f"blocking unknown {index} must be an object")
                continue
            decision_type = blocker.get("decision_type")
            implications = blocker.get("fix_implications")
            evidence_refs = blocker.get("evidence_refs")
            contradicting_refs = blocker.get("contradicting_evidence_refs")
            observed_competing = blocker.get("observed_competing_boundaries")
            if decision_type not in BLOCKING_DECISION_TYPES:
                errors.append(f"blocking unknown {index} has invalid decision_type")
            if not isinstance(blocker.get("question"), str) or not blocker["question"].strip():
                errors.append(f"blocking unknown {index} requires a question")
            if not isinstance(blocker.get("unavailable_reason"), str) or not blocker["unavailable_reason"].strip():
                errors.append(f"blocking unknown {index} requires an unavailable_reason")
            if (
                not isinstance(implications, list)
                or not all(isinstance(value, str) for value in implications)
                or len({value.strip() for value in implications if value.strip()}) < 2
            ):
                errors.append(f"blocking unknown {index} must identify at least two materially different fixes")
            if (
                not isinstance(evidence_refs, list)
                or not evidence_refs
                or not all(isinstance(value, str) and value.strip() for value in evidence_refs)
            ):
                errors.append(f"blocking unknown {index} requires evidence_refs")
            if blocker.get("invalidates_supported_change") is True and (
                not isinstance(contradicting_refs, list)
                or not contradicting_refs
                or not all(isinstance(value, str) and value.strip() for value in contradicting_refs)
            ):
                errors.append(
                    f"blocking unknown {index} that invalidates a supported change requires "
                    "contradicting_evidence_refs"
                )
            if blocker.get("invalidates_supported_change") is True:
                if not isinstance(observed_competing, list) or not observed_competing:
                    errors.append(
                        f"blocking unknown {index} that invalidates a supported change requires at least one "
                        "observed_competing_boundary"
                    )
                else:
                    for competing_index, competing in enumerate(observed_competing, start=1):
                        if not isinstance(competing, dict):
                            errors.append(
                                f"blocking unknown {index} observed_competing_boundary {competing_index} "
                                "must be an object"
                            )
                            continue
                        for field in ("boundary", "observation"):
                            if not isinstance(competing.get(field), str) or not competing[field].strip():
                                errors.append(
                                    f"blocking unknown {index} observed_competing_boundary {competing_index} "
                                    f"requires {field}"
                                )
                        competing_refs = competing.get("evidence_refs")
                        if (
                            not isinstance(competing_refs, list)
                            or not competing_refs
                            or not all(isinstance(value, str) and value.strip() for value in competing_refs)
                        ):
                            errors.append(
                                f"blocking unknown {index} observed_competing_boundary {competing_index} "
                                "requires evidence_refs"
                            )
        if boundary and intended_change and not all(
            isinstance(blocker, dict) and blocker.get("invalidates_supported_change") is True
            for blocker in blockers
        ):
            errors.append(
                "awaiting_input cannot defer an established boundary and intended change without evidence that each "
                "blocker invalidates the supported change"
            )
        clarification = data.get("clarification_brief")
        if not isinstance(clarification, dict):
            errors.append("awaiting_input requires a structured clarification_brief")
        else:
            for field in ("confirmed_facts", "feasible_options"):
                values = clarification.get(field)
                if (
                    not isinstance(values, list)
                    or not values
                    or not all(isinstance(value, str) and value.strip() for value in values)
                ):
                    errors.append(f"clarification_brief {field} must be a non-empty list of strings")
            for field in ("strongest_hypothesis", "recommendation", "plain_language_next_action"):
                if not isinstance(clarification.get(field), str) or not clarification[field].strip():
                    errors.append(f"clarification_brief {field} must be a non-empty string")
    serialized = json.dumps(data, sort_keys=True)
    for marker in PROHIBITED_CONTEXT_MARKERS:
        if marker in serialized:
            errors.append(f"fix design result contains prohibited context marker: {marker}")
    return errors


def _contains_hypothesis(value: object) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in {"hypothesis", "hypotheses"} and nested:
                return True
            if _contains_hypothesis(nested):
                return True
    elif isinstance(value, list):
        return any(_contains_hypothesis(item) for item in value)
    return False


def validate_sentry_artifacts(root: Path) -> None:
    errors: list[str] = []
    packet_path = root / "finalization_packet.json"
    run_inputs_path = root / "run_inputs.json"
    packet: dict[str, object] = {}
    if packet_path.is_file():
        try:
            candidate = json.loads(packet_path.read_text())
        except (json.JSONDecodeError, OSError):
            candidate = {}
        if isinstance(candidate, dict):
            packet = candidate
    metadata = packet.get("run_input_manifest")
    if metadata is not None or run_inputs_path.is_file():
        if not isinstance(metadata, dict):
            errors.append("finalization_packet.json is missing run_input_manifest metadata")
        else:
            declared = Path(str(metadata.get("path", "")))
            if declared.name != "run_inputs.json":
                errors.append("run_input_manifest metadata must reference run_inputs.json")
            if not run_inputs_path.is_file():
                errors.append("run_inputs.json is missing")
            else:
                import hashlib

                if hashlib.sha256(run_inputs_path.read_bytes()).hexdigest() != str(metadata.get("sha256", "")):
                    errors.append("run_input_manifest hash does not match finalization metadata")
                else:
                    try:
                        run_inputs = load_manifest(run_inputs_path, explicit=False)
                    except ValueError as error:
                        errors.append(str(error))
                    else:
                        if run_inputs.get("status") != "explicit":
                            errors.append("run_input_manifest_required")
                        expected_ids = [str(value) for value in metadata.get("input_ids", [])]
                        actual_ids = [str(row["Input ID"]) for row in run_inputs["inputs"]]
                        if expected_ids != actual_ids:
                            errors.append("run_input_manifest metadata does not match its inputs")
                        packet_ids = {
                            str(row.get("Input ID", "")) for row in packet.get("inputs", [])
                            if isinstance(row, dict)
                        }
                        missing = [value for value in actual_ids if value not in packet_ids]
                        if missing:
                            errors.append("finalization packet dropped run inputs: " + ", ".join(missing))
    evidence = root / "normalized_evidence.md"
    evidence_text = ""
    design = root / "fix_design_result.json"
    if not evidence.is_file():
        errors.append("normalized_evidence.md is missing")
    else:
        evidence_text = evidence.read_text()
        errors.extend(sentry_contract_delta_errors(evidence_text))
        for marker in PROHIBITED_CONTEXT_MARKERS:
            if marker in evidence_text:
                errors.append(f"normalized evidence contains prohibited context marker: {marker}")
    if not design.is_file():
        errors.append("fix_design_result.json is missing")
    else:
        try:
            result = json.loads(design.read_text())
        except (json.JSONDecodeError, OSError) as error:
            errors.append(f"invalid fix_design_result.json: {error}")
        else:
            manifest_path = root / "role_bindings.json"
            require_plan = False
            if manifest_path.is_file():
                try:
                    manifest = json.loads(manifest_path.read_text())
                except (json.JSONDecodeError, OSError):
                    manifest = {}
                require_plan = "standard_planning_finalization" in manifest.get("worker_contracts", {})
            errors.extend(fix_design_result_errors(
                result,
                required_input_markers=SENTRY_EVIDENCE_INPUT_MARKERS,
                require_plan=require_plan,
            ))
            if isinstance(result, dict):
                errors.extend(sentry_upstream_boundary_errors(
                    evidence_text, result, require_plan=require_plan
                ))
    if errors:
        fail(f"{root}: " + "\nFAIL: ".join(errors))
    if _ALLOW_UNRELEASED:
        return
    packet_path = root / "finalization_packet.json"
    closure_path = root / "runtime_closure.json"
    if packet_path.is_file() and closure_path.is_file():
        try:
            packet = json.loads(packet_path.read_text())
            closure = json.loads(closure_path.read_text())
        except (json.JSONDecodeError, OSError):
            return
        closure_rows = closure.get("runtime_closure", [])
        released = bool(closure_rows) and all(
            isinstance(row, dict)
            and str(row.get("Runtime status", "")).strip().lower() == "released"
            and str(row.get("Remaining active handles", "")).strip().lower() in {"none", "0"}
            for row in closure_rows
        )
        terminal_packet = (
            str(packet.get("handoff", {}).get("workflow_result", "")).strip()
            and str(packet.get("finalization", {}).get("Final reconciliation", ""))
            .strip()
            .lower()
            .startswith("passed")
        )
        if released and terminal_packet:
            record = root / "work_record.md"
            if not record.is_file():
                fail(f"{root}: released terminal artifact set requires work_record.md")
            validate_work_record(record, require_terminal=True)


def validate_normalized_evidence(path: Path) -> None:
    if not path.is_file():
        fail(f"normalized evidence does not exist: {path}")
    errors = sentry_contract_delta_errors(path.read_text())
    if errors:
        fail(f"{path}: " + "\nFAIL: ".join(errors))


def model_observation_unavailable(value: str) -> bool:
    normalized = " ".join(value.strip().lower().split())
    return any(
        normalized == prefix
        or normalized.startswith(f"{prefix};")
        or normalized.startswith(f"{prefix}:")
        for prefix in MODEL_OBSERVATION_UNAVAILABLE_PREFIXES
    )


def terminal_semantics_errors(identity: dict[str, str]) -> list[str]:
    errors = []
    enums = {
        "Requested profile": PROFILES,
        "Activated profile": PROFILES | {"None"},
        "Executed profile": PROFILES | {"None"},
        "Profile status": PROFILE_STATUSES,
        "Lifecycle": LIFECYCLES,
        "State": TERMINAL_STATES,
        "Workflow outcome": WORKFLOW_OUTCOMES,
        "Engineering outcome": ENGINEERING_OUTCOMES,
    }
    for field, allowed in enums.items():
        if identity.get(field) not in allowed:
            errors.append(f"invalid {field}: {identity.get(field, '')}")
    state = identity.get("State")
    workflow_outcome = identity.get("Workflow outcome")
    if state in {"completed", "ready_for_implementation", "awaiting_input"} and workflow_outcome != "completed":
        errors.append(f"state {state} requires Workflow outcome completed")
    if state == "blocked" and workflow_outcome != "blocked":
        errors.append("state blocked requires Workflow outcome blocked")
    return errors


def _plugin_version_refresh_error() -> str | None:
    completed = subprocess.run(
        ["git", "-C", str(ROOT), "status", "--porcelain", "--untracked-files=all"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode:
        return None
    changed = [line[3:] for line in completed.stdout.splitlines() if len(line) > 3]
    if not any(path != str(PLUGIN_MANIFEST.relative_to(ROOT)) for path in changed):
        return None
    previous = subprocess.run(
        ["git", "-C", str(ROOT), "show", f"HEAD:{PLUGIN_MANIFEST.relative_to(ROOT)}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if previous.returncode:
        return None
    try:
        previous_version = json.loads(previous.stdout)["version"]
        current_version = json.loads(PLUGIN_MANIFEST.read_text())["version"]
    except (json.JSONDecodeError, KeyError):
        return None
    if previous_version == current_version:
        return "plugin build metadata must change when bundled package content changes"
    return None


def frontmatter_value_at_revision(revision: str, path: Path, field: str) -> str | None:
    try:
        relative = path.relative_to(ROOT)
    except ValueError:
        return frontmatter_value(path, field)
    completed = subprocess.run(
        ["git", "-C", str(ROOT), "show", f"{revision}:{relative}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode:
        return frontmatter_value(path, field)
    prefix = f"{field}:"
    for line in completed.stdout.splitlines():
        if line.startswith(prefix):
            return line.split(":", 1)[1].strip()
    return None


def _validate_work_record(path: Path, require_terminal: bool = False) -> str:
    if not path.is_file():
        fail(f"work record does not exist: {path}")
        return ""
    if path.stat().st_size > LARGE_WORK_RECORD_BYTES:
        print(
            f"WARNING: {path} is unusually large; remove duplicated evidence when safe",
            file=sys.stderr,
        )
    text = path.read_text()
    identity = {
        row.get("Field", ""): row.get("Value", "")
        for row in markdown_table(text, "# Run and Evaluation Identity")
    }
    if identity.get("State") not in TERMINAL_STATES:
        if require_terminal:
            fail(f"{path}: work record is not terminal or lacks Run and Evaluation Identity")
        return ""
    for error in reasoning_record_errors(text):
        fail(f"{path}: {error}")
    selection = markdown_table(text, "# Playbook Selection")
    required_selection = {
        "Primary evidence",
        "Primary goal",
        "Selected playbook",
        "Closest alternative",
        "Why this playbook",
    }
    if (
        not selection
        or not required_selection.issubset(selection[0])
        or any(not selection[0].get(field) for field in required_selection)
    ):
        fail(f"{path}: Playbook Selection must record the selected playbook, closest alternative, and rationale")
    empty_selection = {"none", "none selected", "unknown", "not applicable", "n/a"}
    for field in required_selection:
        if selection and selection[0].get(field, "").strip().lower() in empty_selection:
            fail(f"{path}: Playbook Selection {field} must contain run-specific evidence")
    required_identity = (
        "Run ID",
        "Playbook / version",
        "Framework commit / status",
        "Plugin package / version",
        "Provider/runtime configuration",
        "Provider configuration source/status",
        "Prompt template / revision / conformance",
        "Role-policy baseline ID",
        "Role binding manifest",
        "Provider / model configuration",
        "Coordinator model/effort",
        "Requested profile",
        "Activated profile",
        "Executed profile",
        "Profile status",
        "Lifecycle",
        "State",
        "Engineering state",
        "Workflow outcome",
        "Engineering outcome",
    )
    missing = [field for field in required_identity if not identity.get(field)]
    if missing:
        fail(f"{path}: missing evaluation identity: {', '.join(missing)}")
    for field in required_identity:
        identity.setdefault(field, "")
    unresolved = [
        field
        for field in required_identity
        if "`" in identity[field] or ("<" in identity[field] and ">" in identity[field])
    ]
    if unresolved:
        fail(f"{path}: unresolved Run Identity placeholders: {', '.join(unresolved)}")
    for error in terminal_semantics_errors(identity):
        fail(f"{path}: {error}")
    evaluation_run_id = identity.get("Evaluation run ID", "Not applicable")
    evaluation_run = evaluation_run_id != "Not applicable"
    if evaluation_run and evaluation_run_id in {"Unknown", "None"}:
        fail(f"{path}: Evaluation run ID must identify the evaluated run")
    if evaluation_run and identity["Role-policy baseline ID"] in {"Unknown", "None", "Not applicable"}:
        fail(f"{path}: Role-policy baseline ID must identify the evaluated baseline")
    baseline_id = identity["Role-policy baseline ID"]
    if baseline_id != "Not applicable" and ("/" in baseline_id or baseline_id.endswith(".md")):
        fail(f"{path}: Role-policy baseline ID must be an identifier, not a path")
    prompt_by_playbook = {
        "feature_delivery": "templates/feature_delivery_run_prompt.md",
        "techops_issue_remediation": "templates/techops_issue_run_prompt.md",
        "sentry_issue_remediation": "templates/sentry_issue_run_prompt.md",
        "vulnerability_investigation": "templates/vulnerability_issue_run_prompt.md",
    }
    playbook_name = Path(identity["Playbook / version"].split(" / ", 1)[0]).stem
    provider_model = identity["Provider / model configuration"].strip()
    codex_run = (
        provider_model.lower().startswith("codex")
        or baseline_id != "Not applicable"
        or identity["Role binding manifest"] != "Not applicable"
    )
    if " / " not in provider_model:
        fail(f"{path}: Provider / model configuration must identify the provider and its ledger")
    coordinator_model = identity["Coordinator model/effort"].strip()
    if codex_run and not re.fullmatch(
        r"\S+ / (?:none|minimal|low|medium|high|xhigh|max|ultra)", coordinator_model, re.IGNORECASE
    ):
        fail(
            f"{path}: Coordinator model/effort received {coordinator_model!r}; expected "
            "'<active model> / <active effort>'"
        )
    framework_identity = identity["Framework commit / status"]
    if not re.fullmatch(r"[0-9a-fA-F]{40} / (?:Clean|Dirty)", framework_identity):
        fail(
            f"{path}: Framework commit / status received {framework_identity!r}; "
            "expected '<40-character Git SHA> / <Clean|Dirty>'"
        )
    plugin_identity = identity["Plugin package / version"]
    if plugin_identity != "Not applicable" and not re.fullmatch(r"[^\s/]+ / \S+", plugin_identity):
        fail(f"{path}: Plugin package / version must contain an exact package and version")
    manifest: dict[str, object] | None = None
    if codex_run:
        if baseline_id != MODEL_BASELINE_ID:
            fail(f"{path}: Codex runs must use current Role-policy baseline ID {MODEL_BASELINE_ID}")
        manifest_value = identity["Role binding manifest"]
        manifest_path = Path(manifest_value)
        if not manifest_path.is_absolute():
            manifest_path = path.parent / manifest_path.name
        if not manifest_path.is_file():
            fail(f"{path}: role binding manifest does not exist: {manifest_path}")
        try:
            manifest = json.loads(manifest_path.read_text())
        except (json.JSONDecodeError, OSError) as error:
            fail(f"{path}: invalid role binding manifest: {error}")
            manifest = {}
        if manifest.get("baseline_id") != baseline_id:
            fail(f"{path}: role binding manifest baseline does not match Run Identity")
        if manifest.get("playbook") != playbook_name:
            fail(f"{path}: role binding manifest playbook does not match Run Identity")
        for agent, binding in manifest.get("bindings", {}).items():
            definition = Path(binding.get("definition", ""))
            if not definition.is_file():
                fail(f"{path}: role binding definition does not exist for {agent}: {definition}")
                continue
            try:
                definition_data = tomllib.loads(definition.read_text())
            except (OSError, tomllib.TOMLDecodeError) as error:
                fail(f"{path}: invalid role binding definition for {agent}: {error}")
                continue
            if (
                binding.get("model") != definition_data.get("model")
                or binding.get("effort") != definition_data.get("model_reasoning_effort")
            ):
                fail(f"{path}: role binding manifest differs from provider definition for {agent}")
    expected_prompt = prompt_by_playbook.get(playbook_name)
    if expected_prompt:
        prompt_identity = identity["Prompt template / revision / conformance"].split(" / ", 2)
        framework_revision, framework_status = framework_identity.split(" / ", 1)
        expected_version = (
            frontmatter_value_at_revision(framework_revision, ROOT / expected_prompt, "version")
            if framework_status == "Clean"
            else frontmatter_value(ROOT / expected_prompt, "version")
        )
        if len(prompt_identity) != 3 or prompt_identity[0] != expected_prompt:
            fail(f"{path}: Prompt template must match {expected_prompt} for {playbook_name}")
        elif prompt_identity[1] != expected_version:
            fail(f"{path}: Prompt template revision must be {expected_version} for {playbook_name}")
        elif not re.fullmatch(r"(?:pass|fail(?:[:;].+)?)", prompt_identity[2], re.IGNORECASE):
            fail(f"{path}: Prompt template conformance must be pass or fail with details")
    finalization = {
        row.get("Field", ""): row.get("Value", "")
        for row in markdown_table(text, "# Run Isolation and Finalization")
    }
    repositories = markdown_table(text, "# Repository Evidence Eligibility")
    if not repositories or any(not row.get("Full revision") for row in repositories):
        fail(f"{path}: every relevant repository must record its full revision")
    work_item = {
        row.get("Field", ""): row.get("Value", "")
        for row in markdown_table(text, "# Work Item")
    }
    if not RFC3339_TIMESTAMP.fullmatch(work_item.get("Last Updated", "")):
        fail(f"{path}: Work Item Last Updated must be an RFC 3339 timestamp")
    required_tables = {
        "# Worker Execution Ledger": (
            "Worker",
            "Role",
            "Configured model/effort",
        ),
        "# Worker Runtime Closure": (
            "Run or stage",
            "Receipt owner",
            "Completed worker handles",
            "Runtime status",
        ),
        "# Worker Result Summary": (
            "Worker",
            "Outcome",
            "Confidence",
            "Unique contribution",
        ),
    }
    table_rows = {}
    for heading, fields in required_tables.items():
        rows = markdown_table(text, heading)
        table_rows[heading] = rows
        if not rows or any(not row.get(field) for row in rows for field in fields):
            fail(f"{path}: {heading} must contain populated terminal rows")
    for row in table_rows["# Worker Runtime Closure"]:
        receipt_owner = row.get("Receipt owner", "").strip()
        if receipt_owner != "Coordinator":
            fail(
                f"{path}: runtime closure Receipt owner received {receipt_owner!r}; expected 'Coordinator'"
            )
        if row.get("Runtime status", "").strip().lower() == "released":
            if row.get("Remaining active handles", "").strip().lower() not in {"none", "0"}:
                fail(f"{path}: released runtime closure must have no active handles")
            closure_evidence = row.get("Closure evidence or blocker", "").strip().lower()
            if "provider" not in closure_evidence or not any(word in closure_evidence for word in ("release", "close")):
                fail(f"{path}: released runtime closure requires provider release evidence")
            handles = [
                value.strip().lower()
                for value in re.split(r",|;|<br\s*/?>", row.get("Completed worker handles", ""))
            ]
            if codex_run and any(
                handle != "none"
                and not re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", handle)
                for handle in handles
            ):
                fail(
                    f"{path}: Completed worker handles received {row.get('Completed worker handles', '')!r}; "
                    "expected bare provider UUIDs separated by commas or semicolons"
                )
            missing_handles = [handle for handle in handles if handle and handle not in closure_evidence]
            if missing_handles:
                fail(
                    f"{path}: Closure evidence or blocker must identify completed handles: "
                    f"{', '.join(missing_handles)}"
                )
    runtime_released = bool(table_rows["# Worker Runtime Closure"]) and all(
        row.get("Runtime status", "").strip().lower() == "released"
        and row.get("Remaining active handles", "").strip().lower() in {"none", "0"}
        for row in table_rows["# Worker Runtime Closure"]
    )
    if runtime_released:
        reconciliation = finalization.get("Final reconciliation", "").strip().lower()
        stale = any(token in reconciliation for token in ("pending", "unknown", "in progress"))
        stale = stale or ("active" in reconciliation and "no active" not in reconciliation)
        if stale:
            fail(f"{path}: released runtime closure cannot retain pending final reconciliation")
        if finalization.get("Finalization schema", "").strip().lower() != "passed":
            fail(f"{path}: released runtime closure requires Finalization schema Passed")
        for row in markdown_table(text, "# Worker Synchronization"):
            barrier = row.get("Barrier status", "").strip().lower()
            stale = any(token in barrier for token in ("pending", "unknown", "in progress"))
            stale = stale or ("active" in barrier and "no active" not in barrier)
            if stale:
                fail(f"{path}: released runtime closure cannot retain pending synchronization barrier")
        for row in markdown_table(text, "# Durable Artifacts"):
            artifact_name = re.sub(r"[_-]+", " ", row.get("Artifact", "").strip().lower())
            if "runtime closure" in artifact_name and row.get("Status", "").strip().lower() != "released":
                fail(f"{path}: released runtime closure requires the runtime-closure artifact status Released")
        for row in table_rows["# Worker Result Summary"]:
            blockers = row.get("Uncertainties / blockers", "").strip().lower()
            if re.search(r"runtime closure pending", blockers):
                fail(f"{path}: released runtime closure cannot retain pending worker-result closure text")
    if identity["Workflow outcome"] == "completed" and not _ALLOW_UNRELEASED:
        for row in table_rows["# Worker Runtime Closure"]:
            if row.get("Runtime status", "").strip().lower() != "released":
                fail(f"{path}: completed workflow requires released runtime closure")
            if row.get("Remaining active handles", "").strip().lower() not in {"none", "0"}:
                fail(f"{path}: completed workflow requires zero active handles")
    worker_rows = table_rows["# Worker Execution Ledger"]
    result_rows = table_rows["# Worker Result Summary"]
    if playbook_name == "sentry_issue_remediation" and codex_run:
        ledger_by_worker = {row.get("Worker", "").strip().lower(): row for row in worker_rows}
        for row in result_rows:
            outcome = row.get("Outcome", "").strip().lower()
            if outcome not in WORKER_OUTCOMES:
                fail(f"{path}: invalid worker result outcome: {outcome}")
            worker_key = row.get("Worker", "").strip().lower()
            ledger_row = ledger_by_worker.get(worker_key)
            if ledger_row and outcome != ledger_row.get("Outcome", "").strip().lower():
                fail(f"{path}: Worker Result Summary outcome must match the execution ledger for {row.get('Worker', '')}")
            if worker_key not in {"coordinator", "orchestrator"}:
                actual = row.get("Actual model/effort", "").strip().lower()
                if actual in UNOBSERVED_MODEL_VALUES:
                    fail(
                        f"{path}: Codex worker result must record provider-observed model/effort or an explicit "
                        f"unavailable marker for {row.get('Worker', '')}"
                    )
                if ledger_row and actual != ledger_row.get("Provider-observed model/effort", "").strip().lower():
                    fail(f"{path}: Worker Result Summary model/effort must match the execution ledger for {row.get('Worker', '')}")
    for row in worker_rows:
        outcome = row.get("Outcome", "").strip().lower()
        if "Outcome" in row and outcome not in WORKER_OUTCOMES:
            fail(f"{path}: invalid worker outcome: {outcome}")
        if codex_run and row.get("Worker", "").strip().lower() not in {"coordinator", "orchestrator"}:
            role = row.get("Role", "").strip()
            agent = SENTRY_ROLE_AGENTS.get(role) if playbook_name == "sentry_issue_remediation" else None
            if not agent:
                aliases = ROLE_AGENT_ALIASES.get(role, ())
                agent = aliases[0] if aliases else None
            binding = manifest.get("bindings", {}).get(agent) if manifest and agent else None
            if not binding:
                fail(f"{path}: activated worker role has no resolved binding: {role or row.get('Worker', '')}")
                continue
            configured = row.get("Configured model/effort", "").strip().lower()
            expected = f"{binding['model']} / {binding['effort']}".lower()
            if configured != expected:
                fail(
                    f"{path}: {row.get('Worker', role)} configured model/effort received {configured!r}; "
                    f"expected {expected!r}"
                )
            observed = row.get("Provider-observed model/effort", "").strip().lower()
            if observed in UNOBSERVED_MODEL_VALUES:
                fail(
                    f"{path}: Codex worker ledger must record provider-observed model/effort or an explicit "
                    f"unavailable marker for {row.get('Worker', role)}"
                )
            elif not model_observation_unavailable(observed) and observed != configured:
                fail(f"{path}: {row.get('Worker', role)} provider-observed model/effort must match configured model/effort")
    fix_worker_rows = [
        row for row in worker_rows
        if SENTRY_ROLE_AGENTS.get(row.get("Role", "").strip()) == "sentry_solution_architect"
    ]
    handoff_text = fenced_section(text, "# Final Handoff")
    analytical_contract_failure = (
        identity["State"] == "blocked"
        and "analytical contract failure" in handoff_text.lower()
    )
    if playbook_name == "sentry_issue_remediation" and fix_worker_rows and analytical_contract_failure:
        if not any(row.get("Outcome", "").strip().lower() == "failed" for row in fix_worker_rows):
            fail(f"{path}: failed Fix Design contract must record worker outcome failed")
    elif playbook_name == "sentry_issue_remediation" and fix_worker_rows:
        if any(row.get("Outcome", "").strip().lower() != "complete" for row in fix_worker_rows):
            fail(f"{path}: Sentry Fix Design worker outcome must be complete; use plan_readiness for awaiting_input")
        fix_result_path = path.parent / "fix_design_result.json"
        if not fix_result_path.is_file():
            fail(f"{path}: completed Sentry Fix Design requires fix_design_result.json")
        else:
            fix_result: object = {}
            try:
                fix_result = json.loads(fix_result_path.read_text())
            except (json.JSONDecodeError, OSError) as error:
                fail(f"{path}: invalid fix_design_result.json: {error}")
                fix_result = {}
            require_plan = bool(
                manifest
                and "standard_planning_finalization" in manifest.get("worker_contracts", {})
            )
            for error in fix_design_result_errors(
                fix_result,
                required_input_markers=SENTRY_EVIDENCE_INPUT_MARKERS,
                require_plan=require_plan,
            ):
                fail(f"{path}: {error}")
            evidence_path = path.parent / "normalized_evidence.md"
            if isinstance(fix_result, dict) and evidence_path.is_file():
                for error in sentry_upstream_boundary_errors(
                    evidence_path.read_text(), fix_result, require_plan=require_plan
                ):
                    fail(f"{path}: {error}")
            if not isinstance(fix_result, dict):
                fix_result = {}
            if _contains_hypothesis(fix_result):
                if not re.search(r"^Best current explanations:\s*$", handoff_text, re.MULTILINE):
                    fail(f"{path}: Final Handoff must include Best current explanations when Fix Design returns a hypothesis")
            readiness = fix_result.get("plan_readiness")
            expected_identity = {
                "ready_for_implementation": {
                    "State": "ready_for_implementation",
                    "Workflow outcome": "completed",
                    "Engineering outcome": "plan_only",
                },
                "awaiting_input": {
                    "State": "awaiting_input",
                    "Workflow outcome": "completed",
                    "Engineering outcome": "partially_solved",
                },
            }.get(readiness, {})
            for field, expected in expected_identity.items():
                if identity.get(field) != expected:
                    fail(f"{path}: Fix Design {readiness} requires {field} {expected}")
            plan = path.parent / "implementation_plan.md"
            clarification = path.parent / "clarification_brief.md"
            if readiness == "ready_for_implementation":
                if not plan.is_file():
                    fail(f"{path}: ready Fix Design requires implementation_plan.md")
                elif fix_result.get("interface_change"):
                    contract_rows = markdown_table(plan.read_text(), "# Interface Contract")
                    interface_contract = fix_result.get("interface_contract", {})
                    plan_fields = {
                        "Surface": "surface",
                        "Request shape": "request_shape",
                        "Response shape": "response_shape",
                        "Absence semantics": "absence_semantics",
                        "Compatibility / precedence": "compatibility_precedence",
                        "Rollout": "rollout",
                    }
                    if len(contract_rows) != 1 or any(not contract_rows[0].get(field) for field in plan_fields):
                        fail(
                            f"{path}: # Interface Contract received {len(contract_rows)} parseable rows; expected one "
                            "populated row with Surface, Request shape, Response shape, Absence semantics, "
                            "Compatibility / precedence, and Rollout; escape field-internal pipes as \\|"
                        )
                    elif isinstance(interface_contract, dict) and all(key in interface_contract for key in plan_fields.values()) and any(
                        contract_rows[0][field] != interface_contract[key] for field, key in plan_fields.items()
                    ):
                        fail(f"{path}: implementation plan Interface Contract must match fix_design_result.json")
                if clarification.exists():
                    fail(f"{path}: ready Fix Design cannot retain clarification_brief.md")
            elif readiness == "awaiting_input":
                if not clarification.is_file():
                    fail(f"{path}: awaiting Fix Design requires clarification_brief.md")
                if plan.exists():
                    fail(f"{path}: awaiting Fix Design cannot retain implementation_plan.md")
            completed_handles = " ".join(
                row.get("Completed worker handles", "") for row in table_rows["# Worker Runtime Closure"]
            )
            worker_handle = fix_result.get("worker_handle")
            if isinstance(worker_handle, str) and worker_handle.strip() and worker_handle not in completed_handles:
                fail(f"{path}: Fix Design worker_handle is absent from runtime closure")
        evidence_path = path.parent / "normalized_evidence.md"
        if not evidence_path.is_file():
            fail(f"{path}: completed Sentry Fix Design requires normalized_evidence.md")
        else:
            evidence_text = evidence_path.read_text()
            for marker in PROHIBITED_CONTEXT_MARKERS:
                if marker in evidence_text:
                    fail(f"{path}: normalized evidence contains prohibited context marker: {marker}")
            for error in sentry_contract_delta_errors(evidence_text):
                fail(f"{path}: {error}")
    for row in markdown_table(text, "# Input Register"):
        if "worker" in row.get("Input or artifact", "").lower() and "user" in row.get("Source or path", "").lower():
            fail(f"{path}: worker-produced inputs must cite the provider worker/result handle, not the user")
    for row in markdown_table(text, "# Evidence"):
        if "preflight" in " ".join(row.values()).lower() and "user" in row.get("Source", "").lower():
            fail(f"{path}: preflight evidence must cite the Coordinator/provider observation, not the user")
    if evaluation_run:
        evaluation_tables = {
            "# Evaluation Run Continuation Ledger": ("Sequence", "Type", "New input IDs", "Recorded at"),
            "# Evaluation Worker Activation Ledger": (
                "Sequence",
                "Worker",
                "Provider handle",
                "Action",
                "Input IDs",
                "Observed at",
                "Outcome or error",
            ),
        }
        for heading, fields in evaluation_tables.items():
            rows = markdown_table(text, heading)
            if not rows or any(not row.get(field) for row in rows for field in fields):
                fail(f"{path}: {heading} must contain populated evaluation rows")
        for heading, timestamp_field in (
            ("# Evaluation Run Continuation Ledger", "Recorded at"),
            ("# Evaluation Worker Activation Ledger", "Observed at"),
        ):
            for row in markdown_table(text, heading):
                if not RFC3339_TIMESTAMP.fullmatch(row[timestamp_field]):
                    fail(f"{path}: {heading} {timestamp_field} must be RFC 3339")
        timing_rows = markdown_table(text, "## Evaluation Worker Timing Ledger")
        timing_fields = ("Worker", "Provider handle", "Activated", "Started", "Terminal", "Elapsed")
        if not timing_rows or any(not row.get(field) for row in timing_rows for field in timing_fields):
            fail(f"{path}: Evaluation Worker Timing Ledger must contain populated timing rows")
        for row in timing_rows:
            for field in ("Activated", "Started", "Terminal"):
                if not RFC3339_TIMESTAMP.fullmatch(row[field]):
                    fail(f"{path}: Evaluation Worker Timing Ledger {field} must be RFC 3339")
            if row["Elapsed"].lower() in {"terminal", "released", "unknown", "unavailable"}:
                fail(f"{path}: Evaluation Worker Timing Ledger Elapsed must be a duration, not a state")

    handoff = fenced_section(text, "# Final Handoff")
    required_handoff = (
        "Workflow result:",
        "- State:",
        "- Workflow outcome:",
        "- Engineering outcome:",
        "- Implementation plan:",
        "What we established:",
        "Next action:",
        "- Owner:",
        "- Action:",
        "- Complete when:",
        "Artifacts:",
        "Execution:",
        "Provenance:",
    )
    positions = [handoff.find(label) for label in required_handoff]
    if not handoff or any(position < 0 for position in positions) or positions != sorted(positions):
        fail(f"{path}: Final Handoff must contain the canonical ordered labels")
    if re.search(r"^Workflow result:\s*Workflow result:", handoff, re.MULTILINE | re.IGNORECASE):
        fail(f"{path}: Final Handoff must contain exactly one Workflow result prefix")
    for label, field in (
        ("- State:", "State"),
        ("- Workflow outcome:", "Workflow outcome"),
        ("- Engineering outcome:", "Engineering outcome"),
    ):
        value = re.search(rf"^{re.escape(label)}\s*(.+)$", handoff, re.MULTILINE)
        if not value or value.group(1).strip() != identity[field]:
            fail(f"{path}: Final Handoff {field} must match Run Identity")
    runtime_value = "released" if all(
        row.get("Runtime status", "").strip().lower() == "released"
        for row in table_rows["# Worker Runtime Closure"]
    ) else "not released"
    execution = re.search(r"^Execution:\s*(.*?)\nProvenance:", handoff, re.MULTILINE | re.DOTALL)
    if not execution or f"runtime {runtime_value}" not in " ".join(execution.group(1).lower().split()):
        fail(f"{path}: Final Handoff runtime must match Worker Runtime Closure")
    if playbook_name == "sentry_issue_remediation" and codex_run:
        for error in current_artifact_errors(
            markdown_table(text, "# Durable Artifacts"),
            path,
            finalization.get("Durable artifact root", ""),
        ):
            fail(error)
        if handoff:
            in_artifacts = False
            for line in handoff.splitlines():
                if line == "Artifacts:":
                    in_artifacts = True
                    continue
                if in_artifacts and line.startswith("Execution:"):
                    break
                if in_artifacts and line.startswith("- "):
                    target = _artifact_path(line[2:], path)
                    if target is None:
                        fail(f"{path}: Final Handoff contains an empty artifact path")
                    elif not target.is_file() and not (
                        target.name == "work_record.md" and target.parent == path.parent
                    ):
                        fail(f"{path}: Final Handoff artifact does not exist: {target}")
        if not _ALLOW_UNRELEASED and runtime_value == "released" and execution:
            if "validation passed" not in " ".join(execution.group(1).lower().split()):
                fail(f"{path}: released Sentry handoff must report validation passed")
    return handoff


def validate_work_record(path: Path, require_terminal: bool = False) -> str:
    global _WORK_RECORD_ERRORS
    if _WORK_RECORD_ERRORS is not None:
        raise RuntimeError("nested work-record validation")
    errors: list[str] = []
    _WORK_RECORD_ERRORS = errors
    try:
        handoff = _validate_work_record(path, require_terminal)
    finally:
        _WORK_RECORD_ERRORS = None
    if errors:
        fail("\nFAIL: ".join(errors))
    return handoff


def self_test_reasoning_records() -> None:
    assert table_cells(r"| Field | message \| link_title \| link_summary |") == [
        "Field", "message | link_title | link_summary"
    ]
    valid = """# Playbook Selection
| Primary evidence | Primary goal | Selected playbook | Closest alternative | Why this playbook |
| --- | --- | --- | --- | --- |
| Review comments | Improve controls | Feature Delivery | TechOps | Planned framework improvement |
# Repository Evidence Eligibility
| Repository role | Full revision |
| --- | --- |
| Execution | abcdef123456 |
# Run and Evaluation Identity
| Field | Value |
| --- | --- |
| Run ID | run-001 |
| Evaluation run ID | evaluation-001 |
| Playbook / version | playbooks/feature_delivery.md / 0.4.0 |
| Framework commit / status | 0123456789abcdef0123456789abcdef01234567 / Dirty |
| Plugin package / version | ai-engineering-workflows / 0.2.1 |
| Provider/runtime configuration | Not provided |
| Provider configuration source/status | bundled provider definitions / resolved |
| Prompt template / revision / conformance | templates/feature_delivery_run_prompt.md / 0.4.3 / pass |
| Role-policy baseline ID | codex-role-policy-v20260827032839 |
| Role binding manifest | role_bindings.json |
| Provider / model configuration | Codex / Worker Execution Ledger |
| Coordinator model/effort | gpt-5.6-luna / medium |
| Requested profile | standard |
| Activated profile | standard |
| Executed profile | standard |
| Profile status | executed |
| Lifecycle | remediation |
| State | completed |
| Engineering state | validated |
| Workflow outcome | completed |
| Engineering outcome | solved |
# Worker Execution Ledger
| Worker | Role | Configured model/effort | Provider-observed model/effort | Usage |
| --- | --- | --- | --- | --- |
| Coordinator | Orchestrator | active session | active session | Unknown |
# Work Item
| Field | Value |
| --- | --- |
| Last Updated | 2026-08-26T00:00:00Z |
# Run Isolation and Finalization
| Field | Value |
| --- | --- |
| Concurrent-run decision | Isolated run |
| Related-run check | No related run reused |
| Final reconciliation | Passed; runtime closure released with no active handles |
| Finalization schema | Passed |
# Durable Artifacts
| Artifact | Path | Status | Purpose |
| --- | --- | --- | --- |
| runtime_closure.json | runtime_closure.json | Released | Provider receipt |
# Evaluation Run Continuation Ledger
| Sequence | Type | Trigger or new evidence | New input IDs | Previous terminal state | Recorded at | Outcome |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Initial | Request | IN-001 | None | 2026-08-26T00:00:00Z | completed |
# Evaluation Worker Activation Ledger
| Sequence | Continuation | Worker | Provider handle | Action | Input IDs | Observed at | Outcome or error |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 1 | Coordinator | coordinator | spawn | IN-001 | 2026-08-26T00:00:00Z | completed |
## Evaluation Worker Timing Ledger
| Worker | Provider handle | Activated | Started | Terminal | Elapsed |
| --- | --- | --- | --- | --- | --- |
| Coordinator | coordinator | 2026-08-26T00:00:00Z | 2026-08-26T00:00:00Z | 2026-08-26T00:00:01Z | PT1S |
# Worker Runtime Closure
| Run or stage | Receipt owner | Completed worker handles | Runtime status | Remaining active handles | Closure evidence or blocker |
| --- | --- | --- | --- | --- | --- |
| Final | Coordinator | 01a04174-7f58-7a12-b91d-9d171c43f012 | Released | None | provider release confirmation for 01a04174-7f58-7a12-b91d-9d171c43f012 |
# Worker Result Summary
| Worker | Outcome | Confidence | Unique contribution |
| --- | --- | --- | --- |
| Coordinator | completed | High | Finalized record |
# Evidence
| Evidence ID | Source |
| --- | --- |
| evidence-001 | test.log |
# Claims
| Claim ID | Evidence refs |
| --- | --- |
| claim-001 | evidence-001 |
# Decision Log
| Decision ID | Claim refs |
| --- | --- |
| decision-001 | claim-001 |
# Action Log
| Action ID | Decision ref |
| --- | --- |
| action-001 | decision-001 |
# Final Handoff
```text
Workflow result: Completed test run

- State: completed
- Workflow outcome: completed
- Engineering outcome: solved
- Implementation plan: omitted; test fixture

What we established:
- Validator controls passed.

Next action:
- Owner: Test owner
- Action: Retain the fixture.
- Complete when: The self-test passes.

Artifacts:
- work_record.md

Execution: standard/remediation; validation passed; workers complete; runtime released; source or external changes none.
Provenance: plugin ai-engineering-workflows 0.2.1; framework revision
0123456789abcdef0123456789abcdef01234567 (dirty); playbook feature_delivery 0.4.0.
```
"""
    assert reasoning_record_errors(valid) == []
    invalid = valid.replace("| claim-001 | evidence-001 |", "| claim-001 | evidence-999 |")
    assert "claim-001 references missing evidence evidence-999" in reasoning_record_errors(invalid)
    assert "orphaned evidence evidence-001" in reasoning_record_errors(invalid)
    contract_delta = """# Contract Delta

| Boundary | Representation | Field identity / coordinate space | Evidence refs |
| --- | --- | --- | --- |
| Baseline | field-keyed object | field names | evidence-001 |
| Outbound | scalar message | field identity lost | evidence-002 |
| Destination input | scalar message | no field identity | evidence-003 |
| Return | scalar result | no field identity | evidence-004 |
| Semantic input equivalence | not_equivalent | Not applicable | evidence-001, evidence-002 |
"""
    assert sentry_contract_delta_errors(contract_delta) == []
    assert "contract delta is missing boundary: Return" in sentry_contract_delta_errors(
        contract_delta.replace("| Return | scalar result | no field identity | evidence-004 |\n", "")
    )
    ready_fix = {
        "worker_id": "fix-design",
        "worker_handle": "01a04174-7f58-7a12-b91d-9d171c43f012",
        "outcome": "complete",
        "plan_readiness": "ready_for_implementation",
        "implementation_plan_action": "create",
        "inputs_consumed": ["IN-001"],
        "context_conformance": "pass",
        "configuration_conformance": "pass",
        "checks_performed": ["Compared the source-of-truth input with the outbound contract."],
        "checks_remaining": ["Verify production parity before release."],
        "supported_remediation_boundary": "Outbound contract loses one required field.",
        "supported_intended_change": "Preserve the required field across the contract.",
        "interface_change": False,
        "interface_contract": None,
        "blocking_unknowns": [],
        "confidence": {
            "level": "high",
            "basis": "The current contract comparison identifies the field loss.",
            "limits": "Production parity remains to be verified.",
        },
    }
    assert fix_design_result_errors(ready_fix) == []
    assert _contains_hypothesis({"checks_performed": [{"hypothesis": "contract loss"}]})
    assert not _contains_hypothesis({"checks_performed": ["verified fact"]})
    assert any(
        "normalized_evidence.md" in error
        for error in fix_design_result_errors(
            ready_fix, required_input_markers=SENTRY_EVIDENCE_INPUT_MARKERS
        )
    )
    ready_fix_with_evidence = {**ready_fix, "inputs_consumed": ["IN-001", "/run/normalized_evidence.md"]}
    assert fix_design_result_errors(
        ready_fix_with_evidence, required_input_markers=SENTRY_EVIDENCE_INPUT_MARKERS
    ) == []
    malformed_fix = dict(ready_fix)
    malformed_fix.pop("worker_handle")
    malformed_errors = fix_design_result_errors(malformed_fix)
    assert any("fix design result is missing fields: worker_handle" in error for error in malformed_errors)
    malformed_interface = {
        **ready_fix_with_evidence,
        "interface_change": True,
        "interface_contract": {"surface": "Event payload"},
    }
    interface_errors = fix_design_result_errors(malformed_interface)
    assert "interface_contract request_shape must be a non-empty string" in interface_errors
    assert model_observation_unavailable("Not exposed; explicit launch binding was recorded")
    assert not model_observation_unavailable("Unknown")
    overcautious_fix = {
        **ready_fix,
        "plan_readiness": "awaiting_input",
        "implementation_plan_action": "omit",
        "blocking_unknowns": [
            {
                "decision_type": "indispensable_evidence",
                "question": "Which deployed revision ran?",
                "unavailable_reason": "Release mapping is unavailable.",
                "fix_implications": ["Preserve the required field."],
                "evidence_refs": ["evidence-001"],
                "invalidates_supported_change": False,
            }
        ],
    }
    overcautious_errors = fix_design_result_errors(overcautious_fix)
    assert any("materially different fixes" in error for error in overcautious_errors)
    assert any("cannot defer an established boundary" in error for error in overcautious_errors)
    v28 = json.loads(V28_STABILIZATION_FIXTURE.read_text())
    assert fix_design_result_errors(
        v28["fix_design_result"], required_input_markers=SENTRY_EVIDENCE_INPUT_MARKERS
    ) == []
    v31 = json.loads(V31_FIX_DESIGN_FIXTURE.read_text())
    assert fix_design_result_errors(
        v31["fix_design_result"], required_input_markers=SENTRY_EVIDENCE_INPUT_MARKERS
    ) == []
    v31_missing_handle = {**v31["fix_design_result"], "worker_handle": "not exposed"}
    assert "fix design worker_handle must contain the exact activation handle" in fix_design_result_errors(
        v31_missing_handle, required_input_markers=SENTRY_EVIDENCE_INPUT_MARKERS
    )
    v31_structured_interface = {
        **v31["fix_design_result"],
        "interface_change": True,
        "interface_contract": {
            "surface": ["event", "response"],
            "request_shape": {"text_fields": []},
            "response_shape": {"infractions": []},
            "absence_semantics": "Legacy fallback",
            "compatibility_precedence": "Keyed fields win",
            "rollout": ["Consumer first", "Producer second"],
        },
    }
    structured_errors = fix_design_result_errors(
        v31_structured_interface, required_input_markers=SENTRY_EVIDENCE_INPUT_MARKERS
    )
    for field in ("surface", "request_shape", "response_shape", "rollout"):
        assert f"interface_contract {field} must be a non-empty string" in structured_errors
    v32 = json.loads(V32_FIX_DESIGN_RECOVERY_FIXTURE.read_text())
    assert "fix design inputs_consumed must be a non-empty list" in fix_design_result_errors(
        v32["malformed_fix_design_result"], required_input_markers=SENTRY_EVIDENCE_INPUT_MARKERS
    )
    invalid_v28 = {
        **v28["fix_design_result"],
        "plan_readiness": "awaiting_input",
        "implementation_plan_action": "omit",
        "blocking_unknowns": [v28["invalid_runtime_blocker"]],
    }
    assert any(
        "contradicting_evidence_refs" in error for error in fix_design_result_errors(invalid_v28)
    )
    v37_v38 = json.loads(V37_V38_RUNTIME_FIXTURE.read_text())
    assert fix_design_result_errors(
        v37_v38["valid_awaiting_fix_design_result"],
        required_input_markers=SENTRY_EVIDENCE_INPUT_MARKERS,
    ) == []
    absence_only_errors = fix_design_result_errors(
        v37_v38["invalid_absence_only_blocker"],
        required_input_markers=SENTRY_EVIDENCE_INPUT_MARKERS,
    )
    assert any(
        v37_v38["expected_absence_only_error"] in error for error in absence_only_errors
    )
    v29 = json.loads(V29_CONTRACT_FAILURE_FIXTURE.read_text())
    assert sentry_contract_delta_errors(v29["malformed_normalized_evidence"]) == [
        v29["expected_malformed_error"]
    ]
    assert sentry_contract_delta_errors(v29["valid_normalized_evidence"]) == []
    v34 = json.loads(V34_SENTRY_FINALIZATION_FIXTURE.read_text())
    assert sentry_upstream_boundary_errors(
        v34["normalized_evidence"], v34["fix_design_result"], require_plan=True
    ) == []
    downstream_only = json.loads(json.dumps(v34["fix_design_result"]))
    downstream_only["interface_contract"]["request_shape"] = (
        "No inbound request-shape change; continue consuming the existing scalar message."
    )
    assert sentry_upstream_boundary_errors(
        v34["normalized_evidence"], downstream_only, require_plan=True
    ) == [
        "ready fix design must address the observed upstream field-preservation delta: "
        "include the producer boundary and an affirmative field-keyed request change"
    ]
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "work_record.md"
        (path.parent / "role_bindings.json").write_text(json.dumps({
            "baseline_id": MODEL_BASELINE_ID,
            "playbook": "feature_delivery",
            "bindings": {
                "current_state_investigator": {
                    "definition": str(CODEX_AGENT_DIR / "current_state_investigator.toml"),
                    "model": "gpt-5.6-luna",
                    "effort": "high",
                },
            },
        }))
        path.write_text(valid)
        assert validate_work_record(path, require_terminal=True).startswith("Workflow result:")

        normal = valid.replace("| Evaluation run ID | evaluation-001 |", "| Evaluation run ID | Not applicable |")
        normal = normal.replace(
            "| Role-policy baseline ID | codex-role-policy-v20260827032839 |",
            "| Role-policy baseline ID | Not applicable |",
        )
        normal = normal.replace("| Role binding manifest | role_bindings.json |", "| Role binding manifest | Not applicable |")
        normal = normal.replace(
            "| Provider / model configuration | Codex / Worker Execution Ledger |",
            "| Provider / model configuration | Generic / Worker Execution Ledger |",
        )
        normal = normal.replace("# Evaluation Run Continuation Ledger", "# Omitted Evaluation Run Continuation Ledger")
        normal = normal.replace("# Evaluation Worker Activation Ledger", "# Omitted Evaluation Worker Activation Ledger")
        normal = normal.replace("## Evaluation Worker Timing Ledger", "## Omitted Evaluation Worker Timing Ledger")
        path.write_text(normal)
        validate_work_record(path, require_terminal=True)

        def validation_output(record: str) -> str:
            path.write_text(record)
            captured = StringIO()
            with redirect_stdout(captured):
                try:
                    validate_work_record(path, require_terminal=True)
                except SystemExit:
                    pass
                else:
                    raise AssertionError("expected validation failure")
            return captured.getvalue()

        def assert_invalid(record: str, expected: str) -> None:
            output = validation_output(record)
            assert expected in output, output

        assert_invalid(
            valid.replace("## Evaluation Worker Timing Ledger", "## Missing Evaluation Worker Timing Ledger"),
            "Evaluation Worker Timing Ledger must contain populated timing rows",
        )
        assert_invalid(
            valid.replace(
                "| runtime_closure.json | runtime_closure.json | Released | Provider receipt |",
                "| runtime_closure.json | runtime_closure.json | Pending | Provider receipt |",
            ),
            "runtime-closure artifact status Released",
        )
        assert_invalid(
            valid.replace("| Evaluation run ID | evaluation-001 |", "| Evaluation run ID | Unknown |"),
            "Evaluation run ID must identify the evaluated run",
        )
        assert_invalid(
            valid.replace("| Role-policy baseline ID | codex-role-policy-v20260827032839 |", "| Role-policy baseline ID | providers/codex/model_effort_policy.md |"),
            "Role-policy baseline ID must be an identifier, not a path",
        )
        assert_invalid(valid.replace("| TechOps |", "| None selected |"), "run-specific evidence")
        assert_invalid(
            valid.replace("templates/feature_delivery_run_prompt.md", "templates/work_record.md"),
            "Prompt template must match",
        )
        assert_invalid(
            valid.replace(
                "templates/feature_delivery_run_prompt.md / 0.4.3 / pass",
                "templates/feature_delivery_run_prompt.md / framework revision 0123456789abcdef / pass",
            ),
            "Prompt template revision must be 0.4.3",
        )
        assert_invalid(
            valid.replace(
                "provider release confirmation for 01a04174-7f58-7a12-b91d-9d171c43f012",
                "all workers released",
            ),
            "requires provider release evidence",
        )
        assert_invalid(
            valid.replace("| Final | Coordinator |", "| Final | Documenter |"),
            "runtime closure Receipt owner received 'Documenter'; expected 'Coordinator'",
        )
        assert_invalid(
            valid.replace(
                "provider release confirmation for 01a04174-7f58-7a12-b91d-9d171c43f012",
                "provider release confirmation",
            ),
            "Closure evidence or blocker must identify completed handles",
        )
        assert_invalid(
            valid.replace("| Workflow outcome | completed |", "| Workflow outcome | incomplete |", 1),
            "state completed requires Workflow outcome completed",
        )
        assert_invalid(
            valid.replace("| Profile status | executed |", "| Profile status | completed |"),
            "invalid Profile status: completed",
        )
        assert_invalid(
            valid.replace("| Workflow outcome | completed |", "| Workflow outcome | partially_solved |", 1),
            "invalid Workflow outcome: partially_solved",
        )
        assert_invalid(
            valid.replace("| Released | None |", "| Unknown | Unknown |"),
            "completed workflow requires released runtime closure",
        )
        bound_worker = valid.replace(
            "| Coordinator | Orchestrator | active session | active session | Unknown |",
            "| evidence-topology | Current-State Investigator / Sentry Evidence | gpt-5.6-luna / low | "
            "gpt-5.6-luna / low | Unknown |",
        )
        assert_invalid(bound_worker, "configured model/effort received 'gpt-5.6-luna / low'; expected 'gpt-5.6-luna / high'")
        multiple = valid.replace("| Evaluation run ID | evaluation-001 |", "| Evaluation run ID | Unknown |")
        multiple = multiple.replace(
            "| Role-policy baseline ID | codex-role-policy-v20260827032839 |",
            "| Role-policy baseline ID | providers/codex/model_effort_policy.md |",
        )
        output = validation_output(multiple)
        assert "Evaluation run ID must identify the evaluated run" in output
        assert "Role-policy baseline ID must be an identifier, not a path" in output

        legacy = path.with_name("legacy_work_record.md")
        legacy.write_text(
            "# Engineering Work Record\n\n"
            "## Identity and terminal contract\n\n"
            "| Field | Value |\n|---|---|\n| State | awaiting_input |\n"
        )
        with redirect_stdout(StringIO()):
            try:
                validate_work_record(legacy, require_terminal=True)
            except SystemExit:
                pass
            else:
                raise AssertionError("legacy compact work records must fail terminal validation")


for path in ROOT.rglob("*.md"):
    lines = path.read_text().splitlines()
    index = 0
    while index + 1 < len(lines):
        if not (is_table_row(lines[index]) and is_table_row(lines[index + 1])):
            index += 1
            continue

        header = table_cells(lines[index])
        separator = table_cells(lines[index + 1])
        is_separator = separator and all(
            "-" in cell and set(cell) <= {"-", ":"} for cell in separator
        )
        if not is_separator:
            index += 1
            continue

        relative = path.relative_to(ROOT)
        if len(header) != len(separator):
            fail(f"{relative}:{index + 2} has a table column-count mismatch")
        if not (lines[index + 1].startswith("| ") and lines[index + 1].endswith(" |")):
            fail(f"{relative}:{index + 2} has a non-portable table separator")

        row = index + 2
        while row < len(lines) and is_table_row(lines[row]):
            if len(table_cells(lines[row])) != len(header):
                fail(f"{relative}:{row + 1} has a table column-count mismatch")
            row += 1
        index = row


for path in ROOT.rglob("*.md"):
    if ".thoughts" in path.relative_to(ROOT).parts:
        continue
    text = path.read_text()
    dependency_list = False
    for line in frontmatter(text):
        if line == "depends_on:":
            dependency_list = True
            continue
        if dependency_list and line.startswith("  - "):
            dependency = line[4:]
            if not (path.parent / dependency).resolve().exists():
                fail(f"{path.relative_to(ROOT)} references missing dependency {dependency}")
            continue
        if dependency_list and line.strip():
            dependency_list = False

    in_fence = False
    for line_number, line in enumerate(text.splitlines(), start=1):
        if line.startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for target in re.findall(r"(?<!!)\[[^]]+\]\(([^)]+)\)", line):
            target = target.strip().strip("<>").split("#", 1)[0]
            if not target or re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I):
                continue
            if not (path.parent / target).resolve().exists():
                fail(f"{path.relative_to(ROOT)}:{line_number} has broken link {target}")
        if line.lstrip().startswith("|") or not line.strip():
            continue
        if re.match(r"^\s*\#{1,6}[^\s#]", line):
            fail(f"{path.relative_to(ROOT)}:{line_number} has an invalid heading marker")
        if re.match(r"^\s*\*\*#{1,6}\s", line) or re.match(
            r"^\s*#{1,6}\s+\*\*", line
        ):
            fail(f"{path.relative_to(ROOT)}:{line_number} has a malformed bold heading")
        if len(line) > MAX_MARKDOWN_PROSE_WIDTH:
            fail(
                f"{path.relative_to(ROOT)}:{line_number} prose line is "
                f"{len(line)} columns; maximum is {MAX_MARKDOWN_PROSE_WIDTH}"
            )
    if in_fence:
        fail(f"{path.relative_to(ROOT)} has an unclosed fenced block")
    version = re.search(r"^version: (.+)$", text, re.M)
    if version and not SEMVER.fullmatch(version.group(1)):
        fail(f"{path.relative_to(ROOT)} has invalid semantic version {version.group(1)!r}")

agent_configs = {}
for path in ROOT.rglob("*.toml"):
    with path.open("rb") as handle:
        config = tomllib.load(handle)
    if path.parent == CODEX_AGENT_DIR:
        agent_configs[path.stem] = config

policy_text = CODEX_POLICY.read_text()
expected_agents = {}

if f"baseline_id: {MODEL_BASELINE_ID}" not in policy_text:
    fail(f"{CODEX_POLICY.relative_to(ROOT)} has no current model-policy baseline ID")

for match in re.finditer(
    r"^\| ([^|]+) \| `([^`]+)` \| ([^|]+) \| `([^`]+)` \|$",
    policy_text,
    re.M,
):
    role, model, label, effort = (value.strip() for value in match.groups())
    if role not in ROLE_AGENT_ALIASES:
        continue
    if POLICY_EFFORTS.get(label) != effort:
        fail(f"{CODEX_POLICY.relative_to(ROOT)} maps policy effort {label} inconsistently to {effort}")
    for agent_name in ROLE_AGENT_ALIASES[role]:
        expected = (model, effort)
        previous = expected_agents.setdefault(agent_name, expected)
        if previous != expected:
            fail(f"{CODEX_POLICY.relative_to(ROOT)} maps {agent_name} inconsistently")

for match in re.finditer(
    r"^\| [^|]+ \| `([^`]+)` \| ([^|]+) \|$",
    policy_text,
    re.M,
):
    agent_name, role = (value.strip() for value in match.groups())
    if role not in ROLE_AGENT_ALIASES:
        continue
    if agent_name not in agent_configs:
        fail(f"{CODEX_POLICY.relative_to(ROOT)} references missing agent {agent_name}")
    role_agents = ROLE_AGENT_ALIASES[role]
    role_agent = role_agents[0]
    expected = expected_agents[role_agent]
    previous = expected_agents.setdefault(agent_name, expected)
    if previous != expected:
        fail(f"{CODEX_POLICY.relative_to(ROOT)} maps {agent_name} inconsistently")

missing_agents = sorted(set(agent_configs) - set(expected_agents))
undocumented_agents = sorted(set(expected_agents) - set(agent_configs))
if missing_agents:
    fail(f"Codex policy does not document agents: {', '.join(missing_agents)}")
if undocumented_agents:
    fail(f"Codex policy references missing TOML agents: {', '.join(undocumented_agents)}")

for phrase in ("nearest available", "then the parent session"):
    if phrase in policy_text:
        fail(f"{CODEX_POLICY.relative_to(ROOT)} permits unstable provider fallback: {phrase}")
for phrase in ("do not inherit Coordinator values", "provider_configuration_unavailable", "new baseline ID"):
    if phrase not in policy_text:
        fail(f"{CODEX_POLICY.relative_to(ROOT)} is missing fail-closed provider resolution: {phrase}")

for agent_name, config in agent_configs.items():
    if config.get("name") != agent_name:
        fail(f"{agent_name}.toml name does not match its filename")
    actual = (config.get("model"), config.get("model_reasoning_effort"))
    if actual != expected_agents[agent_name]:
        fail(
            f"{agent_name}.toml has {actual[0]} + {actual[1]}; "
            f"policy requires {expected_agents[agent_name][0]} + "
            f"{expected_agents[agent_name][1]}"
        )

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

for path in (ROOT / "playbooks").glob("*.md"):
    text = path.read_text()
    maturity = re.search(r"^maturity: (.+)$", text, re.M)
    if not maturity or maturity.group(1) not in MATURITY:
        fail(f"{path.relative_to(ROOT)} has no valid maturity")
    exercise_scope = re.search(r"^exercise_scope: (.+)$", text, re.M)
    if not exercise_scope or any(value not in exercise_scope.group(1) for value in EXERCISE_COMBINATIONS):
        fail(f"{path.relative_to(ROOT)} has incomplete exercise scope")
    if not re.search(r"^validation_summary: .+$", text, re.M):
        fail(f"{path.relative_to(ROOT)} has no validation summary")

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

for path in (ROOT / "playbooks").glob("*.md"):
    text = path.read_text()
    if "standard planning workers, then `implement`" in text:
        fail(f"{path.relative_to(ROOT)} reruns planning workers during remediation")
    if not re.search(r"In-scope review\s+findings return", text):
        fail(f"{path.relative_to(ROOT)} is missing the delivery review loop")
    if "canonical Human-Readable Handoff" not in text and "shared human-readable template" not in text:
        fail(f"{path.relative_to(ROOT)} is missing the canonical human-readable handoff")
    if "in parallel" not in text or not re.search(r"recorded\s+discrepancy", text):
        fail(f"{path.relative_to(ROOT)} is missing Deep parallelism or non-duplication rules")
    if "never activate or delegate an `initialize` worker" not in text:
        fail(f"{path.relative_to(ROOT)} delegates Coordinator initialization")
    final_documenter = re.search(r"Activate\s+one final Documenter after analytical fan-in", text)
    deterministic_sentry = (
        path.stem == "sentry_issue_remediation"
        and "Do not activate a Documenter for either Standard planning result" in text
        and "deterministic Standard finalizer" in text
    )
    if not final_documenter and not deterministic_sentry:
        fail(f"{path.relative_to(ROOT)} is missing final-Documenter ownership")
    if not re.search(r"final\s+`handoff`\s+after delivery fan-in", text):
        fail(f"{path.relative_to(ROOT)} is missing final remediation handoff ownership")
    if "| `initialize` |" in text:
        fail(f"{path.relative_to(ROOT)} declares an initialize worker")
    if re.search(r"(?:continuous|Continuous).*`handoff`", text):
        fail(f"{path.relative_to(ROOT)} declares a continuous handoff worker")

vulnerability_playbook = (ROOT / "playbooks" / "vulnerability_investigation.md").read_text()
for phrase in (
    "## Finding Classification and Route",
    "`dependency`",
    "`injection`",
    "`infrastructure`",
    "at least two concrete options",
    "implementation_plan: not_created",
):
    if phrase not in vulnerability_playbook:
        fail(f"playbooks/vulnerability_investigation.md is missing {phrase}")

sentry_playbook = (ROOT / "playbooks" / "sentry_issue_remediation.md").read_text()
if "Prompt-preparation rules:" not in (ROOT / "templates" / "sentry_issue_run_prompt.md").read_text():
    fail("templates/sentry_issue_run_prompt.md is missing prompt-preparation rules")
if "event_origin_repository: A" not in (ROOT / "templates" / "sentry_issue_run_prompt.md").read_text():
    fail("templates/sentry_issue_run_prompt.md is missing topology extraction rules")
for phrase in (
    "Standard planning is bounded",
    "latest event as the primary occurrence",
    "Do not inspect every",
    "A local/deployed revision mismatch",
    "The remediation boundary is the explicit set",
    "name that scope in plain language",
    "comparison source of truth",
    "Do not ask the user to redefine the baseline",
    "technical hypothesis",
):
    if phrase not in sentry_playbook:
        fail(f"playbooks/sentry_issue_remediation.md is missing {phrase}")
if "Sentry evidence and repository revision are identified" in sentry_playbook:
    fail("playbooks/sentry_issue_remediation.md still blocks on exact revision identification")

planning_readiness_reference = (
    "[planning-readiness]: "
    "../contracts/workflow_execution.md#planning-readiness-and-implementation-work"
)
for filename in (
    "feature_delivery.md",
    "techops_issue_remediation.md",
    "vulnerability_investigation.md",
):
    if planning_readiness_reference not in (ROOT / "playbooks" / filename).read_text():
        fail(f"playbooks/{filename} is missing the shared planning-readiness reference")

sentry_repository_integrator = agent_configs["sentry_repository_integrator"].get(
    "developer_instructions", ""
)
for phrase in (
    "failing or unavailable build or test baseline",
    "do not return `blocked` merely because",
):
    if phrase not in sentry_repository_integrator:
        fail(f"sentry_repository_integrator.toml is missing planning-readiness rule: {phrase}")

workflow_contract = WORKFLOW_CONTRACT.read_text()
if "## Normative Language" not in workflow_contract:
    fail("contracts/workflow_execution.md is missing normative language")
for invariant_id in range(1, 42):
    if f"`INV-{invariant_id:02d}`" not in workflow_contract:
        fail(f"contracts/workflow_execution.md is missing INV-{invariant_id:02d}")
invariant_ids = re.findall(r"\| `(INV-\d{2})` \|", workflow_contract)
for invariant_id, count in Counter(invariant_ids).items():
    if count > 1:
        fail(f"contracts/workflow_execution.md contains duplicate {invariant_id}")
if "# Pilot Conformance Checklist" not in workflow_contract:
    fail("contracts/workflow_execution.md is missing the conformance checklist")
for heading in (
    "# Human Control Model",
    "## Authoritative Run Inputs",
    "## Context Preservation and Classification",
    "## Playbook Selection",
    "## Human-Readable Handoff",
    "## Worker Wait and Termination Semantics",
    "## Stop Conditions",
    "## Explicit Path Verification",
    "## Concurrent Run Isolation",
    "## Final Handoff Reconciliation",
):
    if heading not in workflow_contract:
        fail(f"contracts/workflow_execution.md is missing {heading}")
if "MUST override a historical worker conclusion" not in workflow_contract:
    fail("contracts/workflow_execution.md is missing current-decision precedence")
if "## Delivery Code Review Loop" not in workflow_contract:
    fail("contracts/workflow_execution.md is missing the delivery review loop")
for phrase in (
    "## Planning Readiness and Implementation Work",
    "Implementation-plan work includes",
    "A true planning blocker exists only",
    "required claims established by source-backed evidence",
    "critical assumptions supported, contradicted, or explicitly accepted",
    "acceptance criteria recovered or an approved equivalent recorded",
    "no blocking unknown",
    "## Delivery Activation and Completion Barrier",
    "active delegated `implement` worker",
    "A source change made before the barrier",
    "The remediation run remains `in_progress`",
    "## Implementation Plan Conformance Check",
    "plan-conformance manifest",
    "unmapped change",
    "## Continuous Worker Progress",
    "ordinary worker transition",
    "runtime closure is recorded",
):
    if phrase not in workflow_contract:
        fail(f"contracts/workflow_execution.md is missing planning-readiness rule: {phrase}")
for phrase in (
    "Workflow outcome: <completed | incomplete | blocked>",
    "Engineering outcome: <solved | partially_solved | plan_only | blocked | incorrect>",
):
    if phrase not in workflow_contract:
        fail(f"contracts/workflow_execution.md is missing handoff result: {phrase}")
if not CLAIMS_CONTRACT.exists():
    fail("contracts/claims.md is missing")
claims_contract = CLAIMS_CONTRACT.read_text()
if "`status: assumed`" not in claims_contract:
    fail("contracts/claims.md is missing material assumption semantics")
for field in ("`assumption_owner`", "`impact_if_wrong`", "`validation_method`"):
    if field not in claims_contract:
        fail(f"contracts/claims.md is missing assumption field {field}")
if "`approval_type`" not in claims_contract:
    fail("contracts/claims.md is missing approval-type semantics")
for phrase in (
    "## Referential Integrity",
    "every action references an existing decision",
    "every evidence record names a source",
    "no evidence, claim, or decision record is orphaned",
):
    if phrase not in claims_contract:
        fail(f"contracts/claims.md is missing referential-integrity control: {phrase}")
if "Claims, Evidence, Decisions, and Actions Contract" not in workflow_contract:
    fail("contracts/workflow_execution.md is missing the claims contract reference")
if "| `confidence`       | Yes" not in workflow_contract:
    fail("contracts/workflow_execution.md is missing required worker confidence")
if "# Workflow State Machine" not in workflow_contract:
    fail("contracts/workflow_execution.md is missing the canonical state machine")
if "# Workflow State and Engineering State" not in workflow_contract:
    fail("contracts/workflow_execution.md is missing engineering-state semantics")
for phrase in (
    "A wait timeout is a polling boundary, not a worker outcome.",
    "coordinator_interrupted_after_wait_timeout",
    "activated_profile",
    "executed_profile",
    "Portable Implementation Handoff Contract](portable_implementation_handoff.md)",
    "Workflow Execution Guidance](workflow_execution_guidance.md)",
    "## Input Delivery and Consumption Gate",
    "Input IDs actually used in `inputs_consumed`",
    "Workers that share a completed dependency and do not depend on each other MUST start in parallel",
    "Deep does not authorize duplicated investigation",
    "A final handoff MUST reconcile durable artifact state",
    "A remediation run sharing an execution repository",
    "Every worker activation MUST include a compact value/source/authority manifest",
    "Evaluation identity, role-policy baseline, detailed",
    "run_already_active",
    "skill or plugin enable/disable directive",
    "current-run input manifest",
    "Live runtime evidence is additive",
    "run_inputs.json",
):
    if phrase not in workflow_contract:
        fail(f"contracts/workflow_execution.md is missing wait/profile semantics: {phrase}")
for path in (WORKFLOW_GUIDANCE, WORKFLOW_VOCABULARY, PORTABLE_HANDOFF_CONTRACT):
    if not path.exists():
        fail(f"{path.relative_to(ROOT)} is missing")
portable_handoff_contract = PORTABLE_HANDOFF_CONTRACT.read_text()
for phrase in ("# Portable Implementation Handoff Contract", "The portable handoff MUST"):
    if phrase not in portable_handoff_contract:
        fail(f"{PORTABLE_HANDOFF_CONTRACT.relative_to(ROOT)} is missing: {phrase}")
work_record_template = (ROOT / "templates" / "work_record.md").read_text()
if not RUN_SKILL.is_file():
    fail("skills/run/SKILL.md is missing")
if not RUN_PREFLIGHT.is_file():
    fail("scripts/run_preflight.py is missing")
if not PREPARE_RUN.is_file():
    fail("scripts/prepare_run.py is missing")
if not WORKER_RUNTIME_GUARD.is_file():
    fail("scripts/validate_worker_runtime.py is missing")
else:
    worker_runtime_self_test = subprocess.run(
        ["python3", str(WORKER_RUNTIME_GUARD), "--self-test"],
        capture_output=True,
        text=True,
        check=False,
    )
    if worker_runtime_self_test.returncode:
        fail(
            "scripts/validate_worker_runtime.py self-test failed: "
            + (worker_runtime_self_test.stdout + worker_runtime_self_test.stderr).strip()
        )
if not V40_RUNTIME_FIXTURE.is_file():
    fail("tests/fixtures/v40_sentry_worker_runtime.json is missing")
if not FINALIZE_WORK_RECORD.is_file():
    fail("scripts/finalize_work_record.py is missing")
if not FINALIZE_SENTRY_PLANNING.is_file():
    fail("scripts/finalize_sentry_planning.py is missing")
if not NORMALIZE_FIX_DESIGN_RESULT.is_file():
    fail("scripts/normalize_fix_design_result.py is missing")
else:
    normalizer_self_test = subprocess.run(
        ["python3", str(NORMALIZE_FIX_DESIGN_RESULT), "--self-test"],
        capture_output=True,
        text=True,
        check=False,
    )
    if normalizer_self_test.returncode:
        fail(
            "scripts/normalize_fix_design_result.py self-test failed: "
            + (normalizer_self_test.stdout + normalizer_self_test.stderr).strip()
        )
for template in (FINALIZATION_PACKET_TEMPLATE, RUNTIME_CLOSURE_TEMPLATE):
    if not template.is_file():
        fail(f"{template.relative_to(ROOT)} is missing")
    else:
        try:
            json.loads(template.read_text())
        except json.JSONDecodeError as error:
            fail(f"{template.relative_to(ROOT)} is invalid JSON: {error}")
if not SENTRY_FIX_DESIGN_CONTRACT.is_file():
    fail("templates/sentry_fix_design_result_contract.json is missing")
else:
    try:
        fix_design_contract = json.loads(SENTRY_FIX_DESIGN_CONTRACT.read_text())
    except json.JSONDecodeError as error:
        fail(f"templates/sentry_fix_design_result_contract.json is invalid JSON: {error}")
    else:
        contract_fields = set(fix_design_contract.get("required_fields", {}))
        if contract_fields != {
            "worker_id",
            "worker_handle",
            "outcome",
            "plan_readiness",
            "implementation_plan_action",
            "inputs_consumed",
            "context_conformance",
            "configuration_conformance",
            "checks_performed",
            "checks_remaining",
            "supported_remediation_boundary",
            "supported_intended_change",
            "interface_change",
            "interface_contract",
            "blocking_unknowns",
            "confidence",
        }:
            fail("templates/sentry_fix_design_result_contract.json has an invalid required-field set")
if not SENTRY_NORMALIZED_EVIDENCE_CONTRACT.is_file():
    fail("templates/sentry_normalized_evidence_contract.md is missing")
else:
    normalized_evidence_contract = SENTRY_NORMALIZED_EVIDENCE_CONTRACT.read_text()
    for phrase in (
        "## Run Scope",
        "## Source Register",
        "## Confirmed Facts",
        "## Best Current Hypotheses",
        "## Topology",
        "## Uncertainty and Checks Remaining",
        "# Contract Delta",
        "validator implementation or regression fixtures is not part",
    ):
        if phrase not in normalized_evidence_contract:
            fail(f"templates/sentry_normalized_evidence_contract.md is missing {phrase}")
if not V36_SENTRY_FINALIZATION_FIXTURE.is_file():
    fail("tests/fixtures/v36_sentry_finalization_regression.json is missing")
else:
    v36_fixture = json.loads(V36_SENTRY_FINALIZATION_FIXTURE.read_text())
    valid_v36_fix = json.loads(json.dumps(v36_fixture["fix_design_result"]))
    valid_v36_fix["confidence"] = v36_fixture["expected_confidence"]
    if fix_design_result_errors(valid_v36_fix, required_input_markers=SENTRY_EVIDENCE_INPUT_MARKERS, require_plan=True):
        fail("v36 valid field-identity regression fixture must pass Fix Design validation")
    invalid_v36_fix = json.loads(json.dumps(valid_v36_fix))
    invalid_v36_fix["interface_contract"]["response_shape"] = v36_fixture["invalid_unqualified_response_shape"]
    invalid_v36_errors = fix_design_result_errors(
        invalid_v36_fix,
        required_input_markers=SENTRY_EVIDENCE_INPUT_MARKERS,
        require_plan=True,
    )
    if v36_fixture["expected_identity_error"] not in invalid_v36_errors:
        fail("v36 unqualified-response regression fixture must fail response-side identity validation")
if not SENTRY_WORK_RECORD_TEMPLATE.is_file():
    fail("templates/sentry_work_record.md is missing")
run_skill = RUN_SKILL.read_text()
for phrase in (
    "scripts/run_preflight.py",
    "first framework tool call",
    "do not read memory",
    "plugin_revision_mismatch",
    "framework_revision_mismatch",
    "preflight_elapsed_ms",
    "one minimal canonical blocked work record",
    "derives the package root from its own location",
    "scripts/prepare_run.py",
    "role_bindings.json",
    "provider_tool_mapping",
    "literal framework tool ID",
    "fork_context: false",
    "Coordinator initialization: complete",
    "worker_runtime_unavailable",
    "`spawn_agent`",
    "Never use",
    "`create_thread`",
    "`fork_thread`",
    "`send_message_to_thread`",
    "scripts/finalize_work_record.py",
    "scripts/finalize_sentry_planning.py",
    "scripts/normalize_fix_design_result.py",
    "finalization_packet.json",
    "preflight even when the app hides stdout",
    "do not rerun it solely",
    "--pre-release",
    "--analytical-failure-stage",
    "skill or plugin enable/disable directive",
    "task created at or after the captured current turn start",
    "standard_planning_finalization.finalizer",
    "worker_activation_packets.json",
    "worker_runtime_guard",
    "Never interrupt a live worker",
    "artifact creation intentionally omits it",
    "--input-manifest",
    "run_input_manifest_required",
    "current-run input manifest",
    "active parent session; no dedicated Coordinator worker spawned",
):
    if phrase not in run_skill:
        fail(f"skills/run/SKILL.md is missing fast-preflight control: {phrase}")
if "--framework-root" in run_skill:
    fail("skills/run/SKILL.md must not pass a separately constructed framework root")
codex_adapter = CODEX_ADAPTER.read_text()
for phrase in (
    "fork_context: false",
    "Coordinator initialization: complete",
    "prepare_run.py",
    "worker_runtime_unavailable",
    "`spawn_agent`",
    "Never use `create_thread`",
    "`fork_thread`",
    "`send_message_to_thread`",
    "provider_tool_mapping",
    "literal framework tool ID",
    "hashed role envelope",
    "worker_runtime_guard",
    "run_inputs.json",
    "current-run input manifest",
):
    if phrase not in codex_adapter:
        fail(f"providers/codex.md is missing worker-isolation control: {phrase}")
if '"Receipt owner": "Coordinator"' not in RUNTIME_CLOSURE_TEMPLATE.read_text():
    fail("templates/runtime_closure.json must assign the provider receipt to the Coordinator")
for phrase in (
    "finalization_packet.json",
    "scripts/finalize_work_record.py",
    "do not patch `work_record.md`",
    "awaiting_input` is a Fix Design readiness value",
):
    if phrase not in (CODEX_AGENT_DIR / "documenter.toml").read_text():
        fail(f"providers/codex/agents/documenter.toml is missing deterministic finalization control: {phrase}")
for path in (
    CODEX_AGENT_DIR / "orchestrator.toml",
    CODEX_AGENT_DIR / "sentry_orchestrator.toml",
    ROOT / "templates" / "sentry_issue_run_prompt.md",
):
    text = path.read_text()
    for phrase in (
        "`spawn_agent`", "Never use", "`create_thread`", "`fork_thread`", "`send_message_to_thread`",
        "worker_runtime_unavailable", "current-run input manifest", "run_inputs.json",
    ):
        if phrase not in text:
            fail(f"{path.relative_to(ROOT)} is missing task-isolation control: {phrase}")
if "| Engineering state |" not in work_record_template:
    fail("templates/work_record.md is missing engineering state")
if "| Approval type |" not in work_record_template:
    fail("templates/work_record.md is missing approval type")
if "# Path Verification" not in work_record_template:
    fail("templates/work_record.md is missing path verification")
if "# Input Register" not in work_record_template:
    fail("templates/work_record.md is missing input provenance")
if "| Input ID |" not in work_record_template or "| Assigned inputs |" not in work_record_template:
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
    "# Run and Evaluation Identity",
    "| Evaluation run ID |",
    "| Playbook / version |",
    "| Framework commit / status |",
    "| Plugin package / version |",
    "| Provider/runtime configuration |",
    "| Provider configuration source/status |",
    "| Prompt template / revision / conformance |",
    "| Role-policy baseline ID |",
    "| Provider / model configuration |",
):
    if phrase not in work_record_template:
        fail(f"templates/work_record.md is missing evaluation identity: {phrase}")
for phrase in (
    "# Run Isolation and Finalization",
    "Concurrent-run decision",
    "Related-run check",
    "Final reconciliation",
    "Finalization schema",
    "compact manifest for every assigned Input ID",
):
    if phrase not in work_record_template:
        fail(f"templates/work_record.md is missing run-isolation/finalization control: {phrase}")

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
):
    if phrase not in workflow_contract:
        fail(f"contracts/workflow_execution.md is missing runtime integrity rule: {phrase}")

for prompt_template in TEMPLATES:
    prompt_text = prompt_template.read_text()
    for phrase in ("canonical human-readable", "Run Metrics", "Worker Timing"):
        if phrase not in prompt_text:
            fail(f"{prompt_template.relative_to(ROOT)} is missing canonical handoff instruction: {phrase}")

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

vulnerability_playbook = (ROOT / "playbooks" / "vulnerability_investigation.md").read_text()
for phrase in (
    "### Bounded Dependency Route",
    "shared `change_set_id`",
    "pilot soft target",
    "Routine dependency updates, upgrades, patches, and lockfile refreshes remain `standard`",
    "requested profile is immutable for the run",
    "Worker effort escalation does not activate the `deep` graph",
    "this route uses three delegated workers",
    "The Coordinator performs initialization directly",
    "pilot soft target is 10 minutes end to end",
    "Normal runs have no byte-count field or hard size gate",
    "checkout is not the execution repository",
    "not change source operations back to the original checkout",
    "identifier equality during fan-in",
    "6-8 minutes end to end",
    "Do not call a failure `pre-existing`",
):
    if phrase not in vulnerability_playbook:
        fail(f"playbooks/vulnerability_investigation.md is missing bounded-run control: {phrase}")

vulnerability_prompt = (ROOT / "templates" / "vulnerability_issue_run_prompt.md").read_text()
for phrase in (
    "owns the affected artifact",
    "Affected component root",
    "three-worker graph",
    "runtime-managed worktree",
    "Coordinator performs preflight directly",
):
    if phrase not in vulnerability_prompt:
        fail(f"templates/vulnerability_issue_run_prompt.md is missing bounded-run field: {phrase}")

for phrase in (
    "The execution repository may itself contain code",
    "Never infer the framework checkout as the",
    "resolved source-checkout path",
    "MUST NOT override an equivalent active worktree",
    "Durable artifacts MUST remain under the",
    "never under an ephemeral managed-worktree path",
    "missing tool does not authorize downloading",
):
    if phrase not in workflow_contract:
        fail(f"contracts/workflow_execution.md is missing wall-time boundary: {phrase}")

if "reported wall time omits Coordinator or documentation" not in workflow_evaluation:
    fail("experimental workflow evaluation is missing complete wall-time evaluation")
if "reconstructed from worker-stage estimates" not in workflow_evaluation:
    fail("experimental workflow evaluation is missing direct wall-time evaluation")

implementation_plan = (ROOT / "templates" / "implementation_plan.md").read_text()
if "Exact tool, version, source, executable path or approved isolated-bootstrap method" not in implementation_plan:
    fail("templates/implementation_plan.md is missing exact toolchain prerequisites")

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

sentry_playbook = (ROOT / "playbooks" / "sentry_issue_remediation.md").read_text()
if "requested profile is immutable for the run" not in sentry_playbook:
    fail("playbooks/sentry_issue_remediation.md is missing immutable-profile control")
for phrase in (
    "pilot target is 10-12 minutes",
    "15-17 minutes when cross-repository analysis",
    "deterministic finalization",
    "initialization acknowledgement",
    "exact model and reasoning effort",
    "framework_revision_mismatch",
    "make a stale prompt match",
    "minimal work-record skeleton",
    "scripts/finalize_work_record.py",
    "scripts/finalize_sentry_planning.py",
    "one smallest available check",
    "do not run unit or integration tests merely",
    "Best current explanations",
    "Normal runs have no byte-count field or hard size gate",
    "exclusively owns raw Sentry queries",
    "`limit: 1` when supported",
    "keep the plan `Draft`",
    "Reference",
    "one explicit cross-repository question",
    "canonical durable artifacts",
    "run_already_active",
    "event emitter, comparison owner, baseline producer",
    "initialization is limited",
    "never activate or delegate an `initialize` worker",
    "resolve that issue directly before any project or issue",
    "three Sentry data queries total",
    "30 seconds",
    "90 seconds",
    "supplied_occurrence",
    "fix_design_result.json",
    "# Contract Delta",
    "materially different fix implications",
    "Standard does not parallelize those two dependent stages",
    "artifact exists and passes artifact validation",
    "--normalized-evidence",
    "organization slug",
    "validate_worker_runtime.py --trace",
    "field-preservation change",
):
    if phrase not in sentry_playbook:
        fail(f"playbooks/sentry_issue_remediation.md is missing Standard control: {phrase}")
contract_example = re.search(r"```text\n(# Contract Delta\n.*?\n)```", sentry_playbook, re.DOTALL)
if not contract_example:
    fail("playbooks/sentry_issue_remediation.md is missing the canonical Contract Delta example")
elif sentry_contract_delta_errors(
    contract_example.group(1).replace(
        "equivalent / not_equivalent / not_established", "not_established"
    )
):
    fail("playbooks/sentry_issue_remediation.md contains an invalid Contract Delta example")

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
    "Quarantine any provider-required memory pass",
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

for text, label in (
    (documenter_role, "roles/documenter.md"),
    (documenter_agent, "providers/codex/agents/documenter.toml"),
):
    if "Standard Sentry planning" not in text or "Normal runs do not record byte counts or budget exceptions" not in text:
        fail(f"{label} is missing Standard Sentry artifact control")
    if (
        "runtime-managed worktrees are not" not in text
        or "artifact roots unless" not in text
        or "direct children of the declared current-run artifact" not in text
    ):
        fail(f"{label} is missing durable artifact-root control")

for phrase in ("do not patch `work_record.md`", "finish within two minutes", "sole writer", "Best current explanations"):
    if phrase not in documenter_agent:
        fail(f"providers/codex/agents/documenter.toml is missing bounded finalization control: {phrase}")

for phrase in ("pre-release source snapshot", "finalized packet", "reserve `plan_only`"):
    if phrase not in documenter_agent:
        fail(f"providers/codex/agents/documenter.toml is missing final-handoff control: {phrase}")

for phrase in ("finalization-schema result", "required artifact set by name"):
    if phrase not in documenter_agent:
        fail(f"providers/codex/agents/documenter.toml is missing terminal-schema control: {phrase}")

for phrase in ("next-action owner", "canonical human-readable handoff"):
    if phrase not in documenter_role.lower():
        fail(f"roles/documenter.md is missing final-handoff ownership: {phrase}")

for name in (
    "current_state_investigator.toml",
    "dependency_analyst.toml",
    "repository_integrator.toml",
    "solution_architect.toml",
):
    text = (CODEX_AGENT_DIR / name).read_text()
    if "quarantine it" not in text or "do not cite or import unassigned memory" not in text:
        fail(f"providers/codex/agents/{name} is missing assigned-context isolation")

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
for phrase in ("run a unit or integration test only", "discriminating outcomes", "runner availability"):
    if phrase not in solution_architect_agent:
        fail(f"providers/codex/agents/solution_architect.toml is missing planning-test gating: {phrase}")

for phrase in (
    "MUST NOT change a technical worker's diagnosis",
    "mutually conditional candidate files",
    "owning technical worker MUST perform the assigned investigation",
    "renderer is the only writer of the terminal `work_record.md`",
    "Do not add a second generic outcome field",
    "pass those exact values explicitly",
    "sole writer for its assigned non-record artifacts and packet",
    "MUST NOT reread",
    "Provider-required memory remains quarantined",
    "returned activation metadata",
    "Active-run artifacts MUST be direct children",
    "Never reduce a useful hypothesis result",
    "During planning, run a unit or integration test only",
    "Complete when",
    "Reserve `plan_only`",
    "one finalized packet",
    "context_conformance",
    "configuration_conformance",
    "run_prompt_nonconformant",
    "evidence_eligibility",
    "On Documenter-owned paths, keep the final Documenter handle live",
    "implementation_plan_action",
    "provider_configuration_unavailable",
    "Never semantically normalize",
    "Workflow-framework validation: passed",
    "fork_context: false",
    "Coordinator initialization: complete",
    "blocking_unknowns",
):
    if phrase not in workflow_contract:
        fail(f"contracts/workflow_execution.md is missing plan-readiness control: {phrase}")

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
    "Repository Evidence Eligibility",
    "Prompt template / revision / conformance",
):
    if phrase not in work_record_template:
        fail(f"templates/work_record.md is missing run-control evidence: {phrase}")
if "Post-finalization Coordinator edits" not in evaluation_addendum:
    fail("templates/evaluation_work_record_addendum.md is missing evaluation control evidence")
for phrase in (
    "initial hypothesis: an experimental baseline",
    "Orchestrator | `gpt-5.6-luna` | Extra High | `xhigh`",
    "Dependency Analyst | `gpt-5.6-luna` | High | `high`",
    "Repository Integrator | `gpt-5.6-luna` | High | `high`",
    "Solution Architect | `gpt-5.6-sol` | Light | `low`",
    "Reviewer | `gpt-5.6-sol` | Light | `low`",
):
    if phrase not in policy_text:
        fail(f"{CODEX_POLICY.relative_to(ROOT)} is missing experimental baseline: {phrase}")

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

for name in ("generic.md", "claude.md", "cursor.md", "codex.md"):
    text = (ROOT / "providers" / name).read_text()
    missing = [skill for skill in sorted(SKILLS) if f"`{skill}`" not in text]
    if missing:
        fail(f"providers/{name} is missing skill mappings: {', '.join(missing)}")

emit_handoff = "--emit-handoff" in sys.argv
_ALLOW_UNRELEASED = "--allow-unreleased" in sys.argv
raw_arguments = list(sys.argv[1:])
artifact_root = None
normalized_evidence = None
if "--sentry-artifacts" in raw_arguments:
    index = raw_arguments.index("--sentry-artifacts")
    if index + 1 >= len(raw_arguments):
        fail("--sentry-artifacts requires one artifact-root path")
    artifact_root = Path(raw_arguments[index + 1]).resolve()
    del raw_arguments[index:index + 2]
if "--normalized-evidence" in raw_arguments:
    index = raw_arguments.index("--normalized-evidence")
    if index + 1 >= len(raw_arguments):
        fail("--normalized-evidence requires one artifact path")
    normalized_evidence = Path(raw_arguments[index + 1]).resolve()
    del raw_arguments[index:index + 2]
arguments = [value for value in raw_arguments if value not in {"--self-test", "--emit-handoff", "--allow-unreleased"}]
if emit_handoff and len(arguments) != 1:
    fail("--emit-handoff requires exactly one terminal work record")
if "--self-test" in sys.argv:
    self_test_reasoning_records()
if artifact_root:
    validate_sentry_artifacts(artifact_root)
if normalized_evidence:
    validate_normalized_evidence(normalized_evidence)
handoffs = [validate_work_record(Path(argument).resolve(), require_terminal=True) for argument in arguments]
for work_record in sorted(ROOT.glob(".thoughts/*/work_record.md")):
    validate_work_record(work_record)
plugin_refresh_error = _plugin_version_refresh_error()
if plugin_refresh_error:
    fail(plugin_refresh_error)

print("Workflow-framework validation: passed")
if emit_handoff:
    print(handoffs[0])
