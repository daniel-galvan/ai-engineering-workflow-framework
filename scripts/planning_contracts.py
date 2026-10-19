#!/usr/bin/env python3
"""Planning acceptance contracts shared by preparation, workers, and publication."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

try:
    from run_input_manifest import load_manifest
except ModuleNotFoundError:  # Support both script and package entrypoints.
    from scripts.run_input_manifest import load_manifest

try:
    from asset_manifest import (
        ASSET_MANIFEST_FILENAME,
        asset_gate_errors,
        asset_plan_errors,
        validate_asset_manifest,
    )
except ModuleNotFoundError:  # Support both script and package entrypoints.
    from scripts.asset_manifest import (
        ASSET_MANIFEST_FILENAME,
        asset_gate_errors,
        asset_plan_errors,
        validate_asset_manifest,
    )

try:
    from specification_assessment import (
        REPORT_NAME,
        assessment_report_errors,
        coverage_mapping_errors,
        coverage_readiness_errors,
    )
except ModuleNotFoundError:  # Support both script and package entrypoints.
    from scripts.specification_assessment import (
        REPORT_NAME,
        assessment_report_errors,
        coverage_mapping_errors,
        coverage_readiness_errors,
    )

try:
    from review_evidence import (
        applicability_errors,
        completed_review_errors,
        review_report_errors,
        validation_report_errors,
        plan_design_errors,
        plan_review_coverage_errors,
        draft_plan_errors,
    )
except ModuleNotFoundError:  # Support both script and package entrypoints.
    from scripts.review_evidence import (
        applicability_errors,
        completed_review_errors,
        review_report_errors,
        validation_report_errors,
        plan_design_errors,
        plan_review_coverage_errors,
        draft_plan_errors,
    )

try:
    from runtime_checks import (
        terminal_observation_errors,
        techops_check_errors,
        trace_errors,
        trace_identity_errors,
    )
except ModuleNotFoundError:
    from scripts.runtime_checks import (
        terminal_observation_errors,
        techops_check_errors,
        trace_errors,
        trace_identity_errors,
    )

try:
    from worker_runtime_evidence import dispatch_audit_errors, latest_worker_dispatch
except ModuleNotFoundError:
    from scripts.worker_runtime_evidence import dispatch_audit_errors, latest_worker_dispatch


try:
    from packet_schema import shape_errors as _shape_errors
except ModuleNotFoundError:
    from scripts.packet_schema import shape_errors as _shape_errors


try:
    from workflow_policy import TECHNICAL_SPIKE_DISPOSITIONS
except ModuleNotFoundError:
    from scripts.workflow_policy import TECHNICAL_SPIKE_DISPOSITIONS


try:
    from work_record_format import _feature_asset_manifest, _runtime_closed, _material_rows
except ModuleNotFoundError:
    from scripts.work_record_format import _feature_asset_manifest, _runtime_closed, _material_rows


try:
    pass
except ModuleNotFoundError:
    pass


ROOT = Path(__file__).resolve().parents[1]
PACKET_TEMPLATE = ROOT / "templates" / "finalization_packet.json"
REFERENCE_ID = re.compile(r"\b[A-Za-z][A-Za-z0-9_]*-[A-Za-z0-9][A-Za-z0-9_-]*\b")
TECHNICAL_SPIKE_RANGE_REFERENCE = re.compile(
    r"\b[A-Za-z][A-Za-z0-9_]*-\d+\s*(?:-|\.\.|[–—]|through|to)\s*"
    r"(?:[A-Za-z][A-Za-z0-9_]*-)?\d+\b",
    re.IGNORECASE,
)
TECHNICAL_SPIKE_PRIMARY_GOALS = {
    "execute technical spike",
    "review technical spike",
}
TECHNICAL_SPIKE_PROFILES = {"standard", "deep"}
TECHNICAL_SPIKE_REASONING_TABLES = (
    (
        "evidence", "Evidence", "Evidence ID",
        ("Evidence ID", "Source", "Summary", "Confidence", "Uncertainty", "Status"),
    ),
    (
        "claims", "Claims", "Claim ID",
        ("Claim ID", "Claim", "Evidence refs", "Confidence", "Uncertainty", "Status"),
    ),
    (
        "decisions", "Decision Log", "Decision ID",
        ("Decision ID", "Decision", "Claim refs", "Owner", "Status"),
    ),
    (
        "actions", "Action Log", "Action ID",
        ("Action ID", "Action", "Decision ref", "Owner", "Status"),
    ),
)
TECHNICAL_SPIKE_UNRESOLVED_WORKER_REF = "to be normalized"
TECHNICAL_SPIKE_GENERIC_EVIDENCE_SUMMARY = re.compile(
    r"^current-run\s+(?:verified\s+)?(?:evidence\s+)?observation"
    r"(?:\s+retained\s+in\s+(?:the\s+)?analytical\s+artifact)?\.?$",
    re.IGNORECASE,
)
TECHNICAL_SPIKE_REQUIRED_WORKERS = {
    ("standard", "execute technical spike"): {"spike-context", "spike-investigation", "handoff"},
    ("deep", "execute technical spike"): {
        "spike-context", "spike-investigation", "repository-integration", "spike-review", "handoff",
    },
    ("standard", "review technical spike"): {"spike-context", "spike-assessment", "handoff"},
    ("deep", "review technical spike"): {
        "spike-context", "spike-assessment", "repository-integration", "handoff",
    },
}
TECHNICAL_SPIKE_WORKER_ROLES = {
    ("standard", "execute technical spike"): {
        "spike-context": "current_state_investigator",
        "spike-investigation": "solution_architect",
        "handoff": "documenter",
    },
    ("deep", "execute technical spike"): {
        "spike-context": "current_state_investigator",
        "spike-investigation": "solution_architect",
        "repository-integration": "repository_integrator",
        "spike-review": "reviewer",
        "handoff": "documenter",
    },
    ("standard", "review technical spike"): {
        "spike-context": "current_state_investigator",
        "spike-assessment": "reviewer",
        "handoff": "documenter",
    },
    ("deep", "review technical spike"): {
        "spike-context": "current_state_investigator",
        "spike-assessment": "reviewer",
        "repository-integration": "repository_integrator",
        "handoff": "documenter",
    },
}
FEATURE_DELIVERY_WORKER_ROLES = {
    ("standard", "planning"): {
        "feature-context": "current_state_investigator",
        "impact-analysis": "dependency_analyst",
        "feature-design": "solution_architect",
        "handoff": "documenter",
    },
    ("deep", "planning"): {
        "feature-context": "current_state_investigator",
        "impact-analysis": "dependency_analyst",
        "repository-integration": "repository_integrator",
        "feature-design": "solution_architect",
        "planning-review": "reviewer",
        "handoff": "documenter",
    },
}
FEATURE_DELIVERY_LEDGER_FIELDS = (
    "Assigned inputs",
    "Mode",
    "Depth",
    "Skills",
    "Tools",
    "Capacity",
    "Configured model/effort",
    "Provider-observed model/effort",
    "Usage",
    "Depends on",
    "Outcome",
    "Confidence",
)
FEATURE_DELIVERY_RESULT_FIELDS = (
    "Outcome",
    "Confidence",
    "Unique contribution",
    "Evidence / claim refs",
    "Uncertainties / blockers",
    "Actual model/effort",
    "Usage/credits",
)
AGENT_ROLE_LABELS = {
    "orchestrator": "Orchestrator",
    "current_state_investigator": "Current-State Investigator",
    "dependency_analyst": "Dependency Analyst",
    "repository_integrator": "Repository Integrator",
    "solution_architect": "Solution Architect",
    "reviewer": "Reviewer",
    "implementer": "Implementer",
    "tester": "Tester",
    "documenter": "Documenter",
}
ROLE_AGENTS = {
    **{label: agent for agent, label in AGENT_ROLE_LABELS.items()},
    "Current-State Investigator / Sentry Evidence": "current_state_investigator",
    "Evidence topology": "sentry_current_state_investigator",
    "Failure topology": "sentry_dependency_analyst",
    "Repository integration": "sentry_repository_integrator",
    "Fix design": "sentry_solution_architect",
}


def _technical_spike_reasoning_graph_errors(packet: dict[str, object]) -> list[str]:
    specs = (
        ("evidence", "Evidence ID", "evidence"),
        ("claims", "Claim ID", "claim"),
        ("decisions", "Decision ID", "decision"),
        ("actions", "Action ID", "action"),
    )
    records: dict[str, dict[str, dict[str, object]]] = {}
    errors: list[str] = []
    for field, identity_field, label in specs:
        rows = _material_rows(packet.get(field), identity_field)
        ids = [str(row.get(identity_field, "")).strip() for row in rows]
        for duplicate in sorted({value for value in ids if ids.count(value) > 1}):
            errors.append(f"Technical Spike packet contains duplicate {label} {duplicate}")
        records[field] = {str(row.get(identity_field, "")).strip(): row for row in rows}
    if not all(records.values()):
        return errors

    evidence_used: set[str] = set()
    claims_used: set[str] = set()
    decisions_used: set[str] = set()
    links = (
        ("claims", "Evidence refs", "evidence", "evidence", evidence_used),
        ("decisions", "Claim refs", "claims", "claim", claims_used),
        ("actions", "Decision ref", "decisions", "decision", decisions_used),
    )
    for source, ref_field, target, target_label, used in links:
        for source_id, row in records[source].items():
            refs = set(REFERENCE_ID.findall(str(row.get(ref_field, ""))))
            if source == "actions" and len(refs) != 1:
                errors.append(f"Technical Spike packet {source_id} must reference exactly one decision")
            elif not refs:
                errors.append(f"Technical Spike packet {source_id} has no {target_label} refs")
            for ref in refs:
                if ref not in records[target]:
                    errors.append(f"Technical Spike packet {source_id} references missing {target_label} {ref}")
                else:
                    used.add(ref)
    for label, rows, used in (
        ("evidence", records["evidence"], evidence_used),
        ("claim", records["claims"], claims_used),
        ("decision", records["decisions"], decisions_used),
    ):
        for orphan in sorted(set(rows) - used):
            parent = {
                "evidence": "a claim's Evidence refs",
                "claim": "a decision's Claim refs",
                "decision": "an action's Decision ref",
            }[label]
            errors.append(
                f"Technical Spike packet contains orphaned {label} {orphan}; add {orphan} to {parent} "
                f"or remove the {label} row and all report references"
            )
    return errors


def _planning_runtime_closure_errors(
    packet: dict[str, object], closure: list[dict[str, object]],
) -> list[str]:
    identity = packet.get("identity", {})
    if not isinstance(identity, dict):
        return []
    playbook = Path(str(identity.get("Playbook / version", "")).split(" / ", 1)[0]).stem.lower()
    state = str(identity.get("State", "")).strip().lower()
    if not ((playbook == "technical_spike" and state == "completed") or
            (playbook in {"feature_delivery", "techops_issue_remediation"}
             and state in {"awaiting_input", "ready_for_implementation", "completed"})):
        return []
    if playbook == "technical_spike" and _technical_spike_missing_workers(packet):
        return []
    completed_workers = {
        str(row.get("Worker", "")).strip().lower()
        for row in packet.get("worker_results", [])
        if isinstance(row, dict) and str(row.get("Outcome", "")).strip().lower() == "complete"
    }
    if not completed_workers or not _runtime_closed(closure):
        return []
    # ponytail: closure has no worker-to-handle mapping; count is the minimum gate until that schema exists.
    released_handles = {
        handle.strip().lower()
        for row in closure
        if isinstance(row, dict)
        for handle in re.split(r",|;|<br\s*/?>", str(row.get("Completed worker handles", "")))
        if handle.strip().lower() not in {"", "none", "unknown", "unavailable"}
    }
    if len(released_handles) < len(completed_workers):
        workers = ", ".join(sorted(completed_workers))
        return [
            f"{playbook} runtime closure is incomplete: released "
            f"provider handles released={len(released_handles)}; completed workers={len(completed_workers)} "
            f"({workers}); include every completed worker handle in runtime_closure.json"
        ]
    return []


def _technical_spike_missing_workers(packet: dict[str, object]) -> set[str]:
    identity = packet.get("identity", {})
    selection = packet.get("playbook_selection", {})
    if not isinstance(identity, dict) or not isinstance(selection, dict):
        return set()
    required = TECHNICAL_SPIKE_REQUIRED_WORKERS.get((
        str(identity.get("Executed profile", "")).strip().lower(),
        str(selection.get("Primary goal", "")).strip().lower(),
    ))
    if not required:
        return set()
    complete = {
        str(row.get("Worker", "")).strip().lower()
        for row in packet.get("worker_results", [])
        if isinstance(row, dict) and str(row.get("Outcome", "")).strip().lower() == "complete"
    }
    return required - complete


def _technical_spike_worker_contract_errors(
    packet: dict[str, object], *, publishing: bool = False,
) -> list[str]:
    identity = packet.get("identity", {})
    selection = packet.get("playbook_selection", {})
    if not isinstance(identity, dict) or not isinstance(selection, dict):
        return []
    contract = TECHNICAL_SPIKE_WORKER_ROLES.get((
        str(identity.get("Executed profile", "")).strip().lower(),
        str(selection.get("Primary goal", "")).strip().lower(),
    ))
    if not contract:
        return []
    rows_by_worker: dict[str, list[dict[str, object]]] = {}
    results_by_worker: dict[str, list[dict[str, object]]] = {}
    for row in packet.get("workers", []):
        if isinstance(row, dict):
            rows_by_worker.setdefault(str(row.get("Worker", "")).strip().lower(), []).append(row)
    for row in packet.get("worker_results", []):
        if isinstance(row, dict):
            results_by_worker.setdefault(str(row.get("Worker", "")).strip().lower(), []).append(row)
    errors = []
    for worker, expected_role in contract.items():
        if publishing and worker == "handoff":
            continue
        rows = rows_by_worker.get(worker, [])
        if len(rows) > 1:
            errors.append(f"Technical Spike worker {worker} must have exactly one execution-ledger row")
        elif not rows:
            errors.append(f"Technical Spike worker {worker} is missing its execution-ledger row")
        else:
            raw_role = str(rows[0].get("Role", "")).strip()
            actual_role = ROLE_AGENTS.get(raw_role, raw_role.lower())
            if actual_role != expected_role:
                errors.append(
                    f"Technical Spike worker {worker} requires role {expected_role}; received {actual_role or 'empty'}"
                )
        results = results_by_worker.get(worker, [])
        if len(results) > 1:
            errors.append(f"Technical Spike worker {worker} must have exactly one worker-result row")
        elif not results:
            errors.append(f"Technical Spike worker {worker} is missing its worker-result row")
        if rows and results:
            ledger_outcome = str(rows[0].get("Outcome", "")).strip().lower()
            result_outcome = str(results[0].get("Outcome", "")).strip().lower()
            if ledger_outcome != result_outcome:
                errors.append(
                    f"Technical Spike worker {worker} outcome mismatch: execution ledger is "
                    f"{ledger_outcome or 'empty'}; worker result is {result_outcome or 'empty'}"
                )
    return errors


def _feature_asset_artifact_path(value: object, root: Path) -> Path | None:
    text = str(value).strip()
    if text.startswith("[") and "](" in text and text.endswith(")"):
        text = text.split("](", 1)[1][:-1]
    if not text:
        return None
    path = Path(text)
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _feature_expected_inputs(packet: dict[str, object], root: Path) -> tuple[dict[str, object], list[str]]:
    packet_rows = {
        str(row.get("Input ID")): row
        for row in packet.get("inputs", [])
        if isinstance(row, dict) and str(row.get("Input ID", "")).strip()
    }
    metadata = packet.get("run_input_manifest")
    identity = packet.get("identity")
    reference = metadata.get("path") if isinstance(metadata, dict) else None
    if not reference and isinstance(identity, dict):
        reference = identity.get("Run input manifest")
    if not reference or str(reference).strip().lower() in {"none", "not applicable"}:
        return packet_rows, ["Feature Delivery requires run_input_manifest metadata for asset source reconciliation"]
    path = Path(str(reference))
    path = path if path.is_absolute() else root / path
    if not path.is_file():
        return packet_rows, [f"Feature Delivery requires readable run_inputs.json for asset source reconciliation: {path}"]
    expected_hash = metadata.get("sha256") if isinstance(metadata, dict) else None
    if not expected_hash and isinstance(identity, dict):
        expected_hash = identity.get("Run input manifest hash")
    if not isinstance(expected_hash, str) or not expected_hash.strip():
        return packet_rows, ["Feature Delivery requires the run_inputs.json content hash for asset source reconciliation"]
    try:
        actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        return packet_rows, [f"Feature Delivery cannot hash run_inputs.json for asset source reconciliation: {error}"]
    if actual_hash != expected_hash:
        return packet_rows, ["Feature Delivery run_inputs.json hash does not match finalization metadata"]
    if isinstance(identity, dict) and identity.get("Run input manifest hash") not in {None, "", actual_hash}:
        return packet_rows, ["Feature Delivery identity input hash does not match finalization metadata"]
    try:
        value = load_manifest(path, explicit=False)
    except (OSError, ValueError) as error:
        return packet_rows, [f"Feature Delivery cannot read run_inputs.json for asset source reconciliation: {error}"]
    if value.get("status") != "explicit":
        return packet_rows, ["Feature Delivery run_inputs.json must have status explicit for asset source reconciliation"]
    expected_ids = metadata.get("input_ids") if isinstance(metadata, dict) else None
    actual_ids = [str(row.get("Input ID")) for row in value["inputs"]]
    if not isinstance(expected_ids, list) or [str(item) for item in expected_ids] != actual_ids:
        return packet_rows, ["Feature Delivery run_inputs.json input IDs do not match finalization metadata"]
    prepared_rows = {
        str(row.get("Input ID")): row
        for row in value["inputs"]
        if isinstance(row, dict) and str(row.get("Input ID", "")).strip()
    }
    missing = sorted(set(prepared_rows) - set(packet_rows))
    extra = sorted(set(packet_rows) - set(prepared_rows))
    errors = []
    for input_id in set(prepared_rows) & set(packet_rows):
        for field in ("Source or path", "Authority", "Input or artifact", "path", "sha256", "paths", "sha256_by_path"):
            if packet_rows[input_id].get(field) != prepared_rows[input_id].get(field):
                errors.append(f"Feature Delivery packet input {input_id} differs from run_inputs.json: {field}")
    if missing:
        errors.append("Feature Delivery finalization packet dropped run inputs: " + ", ".join(missing))
    if extra:
        errors.append("Feature Delivery finalization packet added undeclared run inputs: " + ", ".join(extra))
    return prepared_rows, errors


def _feature_delivery_asset_contract_errors(packet: dict[str, object]) -> list[str]:
    identity = packet.get("identity", {})
    if not isinstance(identity, dict):
        return []
    playbook = Path(str(identity.get("Playbook / version", "")).split(" / ", 1)[0]).stem.lower()
    if playbook != "feature_delivery":
        return []
    lifecycle = str(identity.get("Lifecycle", "")).strip().lower()
    state = str(identity.get("State", "")).strip().lower()
    if not ((lifecycle == "planning" and state in {"ready_for_implementation", "awaiting_input", "completed"})
            or (lifecycle == "remediation" and state in {"awaiting_input", "completed", "handoff", "blocked"})):
        return []

    errors: list[str] = []
    manifest_path, manifest = _feature_asset_manifest(packet)
    if manifest is None:
        return [f"Feature Delivery requires a valid {ASSET_MANIFEST_FILENAME}: {manifest_path}"]
    root = manifest_path.parent.resolve()
    input_rows, input_errors = _feature_expected_inputs(packet, root)
    errors.extend(input_errors)
    evidence_ids = {
        str(row.get("Evidence ID"))
        for row in packet.get("evidence", [])
        if isinstance(row, dict) and str(row.get("Evidence ID", "")).strip()
    }
    claim_evidence_ids = {
        reference
        for row in packet.get("claims", [])
        if isinstance(row, dict)
        for reference in REFERENCE_ID.findall(str(row.get("Evidence refs", "")))
    }
    errors.extend(validate_asset_manifest(
        manifest,
        work_item=str(packet.get("work_item", {}).get("ID", "")),
        expected_input_ids=input_rows,
        expected_inputs=input_rows,
        expected_evidence_ids=evidence_ids,
        material_claim_evidence_ids=claim_evidence_ids,
        require_jira_source=True,
        require_passed=state in {"ready_for_implementation", "completed"},
    ))
    design_path = root / "feature_design_result.json"
    if design_path.is_file():
        try:
            design = json.loads(design_path.read_text())
        except (OSError, json.JSONDecodeError) as error:
            errors.append(f"Feature Delivery cannot read {design_path.name}: {error}")
        else:
            asset_gate = design.get("asset_gate", {}) if isinstance(design, dict) else {}
            if isinstance(asset_gate, dict):
                for field, manifest_field in (("asset_count", "assets"), ("source_count", "sources")):
                    rows = manifest.get(manifest_field)
                    if field in asset_gate and isinstance(rows, list) and asset_gate[field] != len(rows):
                        errors.append(
                            f"Feature Delivery {design_path.name} asset_gate.{field} "
                            f"must equal asset_manifest.json {manifest_field} count "
                            f"({len(rows)})"
                        )
    durable_paths = {
        _feature_asset_artifact_path(row.get("Path"), root)
        for row in packet.get("durable_artifacts", [])
        if isinstance(row, dict)
    }
    if manifest_path.resolve() not in durable_paths:
        errors.append("Feature Delivery finalization must register asset_manifest.json as a durable artifact")
    handoff = packet.get("handoff", {})
    handoff_paths = {
        _feature_asset_artifact_path(value, root)
        for value in handoff.get("artifacts", [])
    } if isinstance(handoff, dict) and isinstance(handoff.get("artifacts"), list) else set()
    if manifest_path.resolve() not in handoff_paths:
        errors.append("Feature Delivery finalization must link asset_manifest.json in the Final Handoff")
    selection = packet.get("playbook_selection", {})
    assessment = isinstance(selection, dict) and str(selection.get("Primary goal", "")).strip().lower() == (
        "specification assessment"
    )
    if assessment:
        report_path = root / REPORT_NAME
        design_path = root / "feature_design.md"
        design_text = design_path.read_text() if design_path.is_file() else None
        if design_text is None:
            errors.append("Feature Delivery specification assessment requires reviewed feature_design.md")
        if not report_path.is_file():
            errors.append(f"Feature Delivery specification assessment requires {REPORT_NAME}")
        else:
            result = str(handoff.get("workflow_result", "")) if isinstance(handoff, dict) else ""
            material_ids = tuple(
                str(asset.get("asset_id", "")) for asset in manifest.get("assets", [])
                if isinstance(asset, dict) and asset.get("relevance") == "material"
            )
            errors.extend(assessment_report_errors(
                report_path.read_text(), result, material_ids, reviewed_coverage_text=design_text,
            ))
        if report_path.resolve() not in durable_paths:
            errors.append(f"Feature Delivery finalization must register {REPORT_NAME}")
        if report_path.resolve() not in handoff_paths:
            errors.append(f"Feature Delivery finalization must link {REPORT_NAME} in the Final Handoff")
        if (root / "implementation_plan.md").is_file():
            errors.append("Feature Delivery specification assessment must not create implementation_plan.md")
    elif state in {"ready_for_implementation", "completed"}:
        plan_path = root / "implementation_plan.md"
        if not plan_path.is_file():
            errors.append(f"Feature Delivery {state} requires implementation_plan.md")
        else:
            errors.extend(asset_plan_errors(plan_path.read_text(), manifest))
            errors.extend(applicability_errors(plan_path.read_text()))
    elif state == "awaiting_input" and (root / "implementation_plan.md").is_file():
        errors.extend(draft_plan_errors((root / "implementation_plan.md").read_text()))
        errors.extend(asset_plan_errors((root / "implementation_plan.md").read_text(), manifest))
        for name in ("implementation_plan.md", "clarification_brief.md"):
            if (root / name).resolve() not in durable_paths or (root / name).resolve() not in handoff_paths:
                errors.append(f"Partial planning handoff must register and link {name}")
        if not (root / "clarification_brief.md").is_file():
            errors.append("Draft partial plan requires clarification_brief.md")
    return list(dict.fromkeys(errors))


def _feature_delivery_packet_contract_errors(
    packet: dict[str, object], *, pre_handoff: bool = False,
) -> list[str]:
    identity = packet.get("identity", {})
    if not isinstance(identity, dict):
        return []
    playbook = Path(str(identity.get("Playbook / version", "")).split(" / ", 1)[0]).stem.lower()
    if playbook != "feature_delivery":
        return []
    if str(identity.get("Lifecycle", "")).strip().lower() == "remediation":
        root_value = packet.get("finalization", {}).get("Durable artifact root", "")
        root = Path(str(root_value)).resolve()
        registered = {
            target for row in packet.get("durable_artifacts", [])
            if isinstance(row, dict) and (target := _feature_asset_artifact_path(row.get("Path"), root)) is not None
        }
        linked = {
            target for value in packet.get("handoff", {}).get("artifacts", [])
            if (target := _feature_asset_artifact_path(value, root)) is not None
        }
        errors = completed_review_errors(identity, root, registered_paths=registered, handoff_paths=linked)
        if identity.get("State") in {"handoff", "completed", "blocked", "awaiting_input"}:
            errors.extend(_feature_delivery_remediation_errors(packet, root / "finalization_packet.json"))
        return errors
    if str(identity.get("Lifecycle", "")).strip().lower() != "planning":
        return []

    state = str(identity.get("State", "")).strip().lower()
    if state not in {"ready_for_implementation", "awaiting_input", "completed"}:
        return []

    errors: list[str] = []
    disposition = packet.get("planning_disposition")
    if disposition is not None:
        if (not isinstance(disposition, dict)
                or not all(isinstance(disposition.get(key), str) for key in ("plan_readiness", "implementation_plan_action"))
                or (disposition.get("plan_readiness"),
                disposition.get("implementation_plan_action")) not in {
                ("ready_for_implementation", "create"), ("awaiting_input", "create_draft"), ("awaiting_input", "omit")}):
            errors.append("feature_planning_disposition_invalid")
        elif not pre_handoff:
            if disposition["plan_readiness"] != state:
                errors.append("feature_planning_disposition_state_mismatch")
            plan = Path(str(packet["finalization"]["Durable artifact root"])) / "implementation_plan.md"
            if disposition["implementation_plan_action"] == "create_draft" and not plan.is_file():
                errors.append("feature_partial_draft_plan_required")
            if disposition["implementation_plan_action"] == "omit" and plan.exists():
                errors.append("feature_omitted_plan_present")
    title = str(packet.get("work_item", {}).get("Title", "")).strip()
    if not title or title.lower().startswith("unknown"):
        errors.append("Feature Delivery finalization requires the recovered work-item title")
    profiles = [str(identity.get(field, "")).strip().lower() for field in (
        "Requested profile", "Activated profile", "Executed profile",
    )]
    invalid_profiles = sorted({profile for profile in profiles if profile not in {"standard", "deep"}})
    if invalid_profiles:
        errors.append(
            "Feature Delivery profiles must be standard or deep; received "
            + ", ".join(invalid_profiles)
        )
        return errors
    if len(set(profiles)) != 1:
        errors.append("Feature Delivery Requested, Activated, and Executed profiles must match")
    if str(identity.get("Profile status", "")).strip().lower() != "executed":
        errors.append("Feature Delivery terminal planning requires Profile status executed")

    expected_outcomes = {
        "ready_for_implementation": (
            "completed", "solved" if str(packet.get("playbook_selection", {}).get("Primary goal", "")).strip().lower()
            == "specification assessment" else "plan_only"
        ),
        "awaiting_input": ("completed", "partially_solved"),
    }.get(state)
    if expected_outcomes:
        workflow_outcome, engineering_outcome = expected_outcomes
        if str(identity.get("Workflow outcome", "")).strip().lower() != workflow_outcome:
            errors.append(
                f"Feature Delivery {state} requires Workflow outcome {workflow_outcome}"
            )
        if str(identity.get("Engineering outcome", "")).strip().lower() != engineering_outcome:
            errors.append(
                f"Feature Delivery {state} requires Engineering outcome {engineering_outcome}"
            )

    profile = profiles[2]
    contract = dict(FEATURE_DELIVERY_WORKER_ROLES[(profile, "planning")])
    if pre_handoff:
        contract.pop("handoff", None)
    rows_by_worker: dict[str, list[dict[str, object]]] = {}
    for row in packet.get("workers", []):
        if isinstance(row, dict):
            worker = str(row.get("Worker", "")).strip().lower()
            if worker:
                rows_by_worker.setdefault(worker, []).append(row)
    result_rows_by_worker: dict[str, list[dict[str, object]]] = {}
    for row in packet.get("worker_results", []):
        if isinstance(row, dict):
            worker = str(row.get("Worker", "")).strip().lower()
            if worker:
                result_rows_by_worker.setdefault(worker, []).append(row)
    if profile == "standard" and (
        "repository-integration" in rows_by_worker or "repository-integration" in result_rows_by_worker
    ):
        contract["repository-integration"] = "repository_integrator"

    missing_ledgers = sorted(worker for worker in contract if not rows_by_worker.get(worker))
    if missing_ledgers:
        errors.append(
            "Feature Delivery handoff requires execution-ledger rows for: "
            + ", ".join(missing_ledgers)
        )
    missing_results = sorted(worker for worker in contract if not result_rows_by_worker.get(worker))
    if missing_results:
        errors.append(
            "Feature Delivery handoff requires terminal results for: "
            + ", ".join(missing_results)
        )

    for worker, expected_role in contract.items():
        ledger_rows = rows_by_worker.get(worker, [])
        if len(ledger_rows) > 1:
            errors.append(f"Feature Delivery worker {worker} must have exactly one execution-ledger row")
        if ledger_rows:
            row = ledger_rows[0]
            raw_role = str(row.get("Role", "")).strip()
            actual_role = ROLE_AGENTS.get(raw_role, raw_role.lower())
            if actual_role != expected_role:
                errors.append(
                    f"Feature Delivery worker {worker} requires role {expected_role}; "
                    f"received {actual_role or 'empty'}"
                )
            missing_fields = [field for field in FEATURE_DELIVERY_LEDGER_FIELDS if not str(row.get(field, "")).strip()]
            if missing_fields:
                errors.append(
                    f"Feature Delivery worker {worker} requires populated execution-ledger fields: "
                    + ", ".join(missing_fields)
                )
            if str(row.get("Outcome", "")).strip().lower() != "complete":
                errors.append(
                    f"Feature Delivery worker {worker} ledger outcome must be complete; "
                    f"received {row.get('Outcome', '') or 'empty'}"
                )

        result_rows = result_rows_by_worker.get(worker, [])
        if len(result_rows) > 1:
            errors.append(f"Feature Delivery worker {worker} must have exactly one worker-result row")
        if result_rows:
            result = result_rows[0]
            missing_fields = [field for field in FEATURE_DELIVERY_RESULT_FIELDS if not str(result.get(field, "")).strip()]
            if missing_fields:
                errors.append(
                    f"Feature Delivery worker {worker} requires populated worker-result fields: "
                    + ", ".join(missing_fields)
                )
            if str(result.get("Outcome", "")).strip().lower() != "complete":
                errors.append(
                    f"Feature Delivery worker {worker} result outcome must be complete; "
                    f"received {result.get('Outcome', '') or 'empty'}"
                )
            if ledger_rows and str(result.get("Outcome", "")).strip().lower() != str(
                ledger_rows[0].get("Outcome", "")
            ).strip().lower():
                errors.append(f"Feature Delivery worker {worker} ledger/result outcomes must match")
    bindings = root / "role_bindings.json" if (root := Path(str(
        packet.get("finalization", {}).get("Durable artifact root", "")))).is_absolute() else None
    if not pre_handoff and bindings and bindings.is_file():
        if json.loads(bindings.read_text()).get("runtime_evidence"):
            errors.extend(_worker_runtime_audit_errors(packet, root / "finalization_packet.json", {
                row.get("Worker") for row in packet.get("worker_results", []) if row.get("Outcome") == "complete"
            }))
    return errors


def _feature_delivery_remediation_errors(
    packet: dict[str, object], packet_path: Path, *, pre_handoff: bool = False,
) -> list[str]:
    """Validate Coordinator-owned delivery evidence, including partial validation results."""
    identity = packet.get("identity", {})
    errors = []
    profiles = [identity.get(field) for field in ("Requested profile", "Activated profile", "Executed profile")]
    if len(set(profiles)) != 1 or profiles[0] not in {"standard", "deep"}:
        errors.append("feature_delivery_remediation_profiles_must_match")
    if identity.get("Lifecycle") != "remediation" or identity.get("Profile status") != "executed":
        errors.append("feature_delivery_remediation_state_required")
    if identity.get("Engineering outcome") not in {"solved", "partially_solved", "blocked"}:
        errors.append("feature_delivery_remediation_engineering_outcome_required")
    if identity.get("State") not in {"handoff", "completed", "blocked", "awaiting_input"}:
        errors.append("feature_delivery_remediation_handoff_state_required")
    if identity.get("State") != "completed" and identity.get("Workflow outcome") == "completed":
        errors.append("feature_delivery_remediation_nonterminal_workflow_completed")
    roles = {"implement": "implementer", "review": "reviewer", "validate": "tester"}
    if not pre_handoff:
        roles["handoff"] = "documenter"
    results = packet.get("worker_results", [])
    workers = packet.get("workers", [])
    for worker, role in roles.items():
        ledgers = [row for row in workers if isinstance(row, dict) and row.get("Worker") == worker]
        envelopes = [row for row in results if isinstance(row, dict) and row.get("Worker") == worker]
        if len(ledgers) != 1 or len(envelopes) != 1:
            errors.append(f"feature_delivery_terminal_worker_required:{worker}")
            continue
        ledger, result = ledgers[0], envelopes[0]
        actual_role = ROLE_AGENTS.get(ledger.get("Role"), ledger.get("Role"))
        if actual_role != role:
            errors.append(f"feature_delivery_worker_role_mismatch:{worker}")
        if any(not str(ledger.get(field, "")).strip() for field in FEATURE_DELIVERY_LEDGER_FIELDS):
            errors.append(f"feature_delivery_worker_ledger_incomplete:{worker}")
        if any(not str(result.get(field, "")).strip() for field in FEATURE_DELIVERY_RESULT_FIELDS):
            errors.append(f"feature_delivery_worker_result_incomplete:{worker}")
        if ledger.get("Outcome") != "complete" or result.get("Outcome") != "complete":
            errors.append(f"feature_delivery_worker_not_complete:{worker}")
        evidence_ids = {row.get("Evidence ID") for row in packet.get("evidence", []) if isinstance(row, dict)}
        refs = set(re.findall(r"\bE-[A-Za-z0-9_-]+\b", str(result.get("Evidence / claim refs", ""))))
        if not refs or not refs <= evidence_ids:
            errors.append(f"feature_delivery_worker_evidence_required:{worker}")
    fan_in = [row for row in packet.get("synchronization", []) if isinstance(row, dict)
              and row.get("Barrier status", "").lower() == "passed"
              and {"implement", "review", "validate"} <= set(re.findall(
                  r"[a-z][a-z-]+", str(row.get("Workers launched", ""))))
              and str(row.get("Results summarized", "")).strip()]
    if not fan_in:
        errors.append("feature_delivery_coordinator_fan_in_required")
    root = packet_path.parent
    try:
        errors.extend(plan_design_errors((root / "implementation_plan.md").read_text(),
                                        require_complete=identity.get("Engineering outcome") == "solved"))
    except OSError:
        errors.append("feature_delivery_approved_plan_required")
    try:
        review_text = (root / "code_review.md").read_text()
        errors.extend(review_report_errors(review_text, require_accepted=identity.get("State") != "blocked"))
        errors.extend(plan_review_coverage_errors((root / "implementation_plan.md").read_text(), review_text))
    except OSError:
        review_text = ""
        errors.append("feature_delivery_code_review_required")
    try:
        validation_text = (root / "validation_report.md").read_text()
    except OSError:
        validation_text = ""
    if not validation_text.strip():
        errors.append("feature_delivery_validation_report_required")
    else:
        execution_rows = [row for row in packet.get("repositories", []) if isinstance(row, dict)
                          and str(row.get("Repository role", "")).lower() in {"execution", "execution repository"}]
        if len(execution_rows) != 1 or not execution_rows[0].get("Resolved path"):
            errors.append("feature_delivery_validation_execution_repository_required")
        else:
            errors.extend(validation_report_errors(validation_text, review_text,
                                                   require_solved=identity.get("Engineering outcome") == "solved",
                                                   expected_repository=Path(execution_rows[0]["Resolved path"]),
                                                   require_accepted=identity.get("State") != "blocked"))
    if not pre_handoff:
        registered = {_feature_asset_artifact_path(row.get("Path"), root)
                      for row in packet.get("durable_artifacts", []) if isinstance(row, dict)}
        linked = {_feature_asset_artifact_path(value, root) for value in packet.get("handoff", {}).get("artifacts", [])}
        for name in ("code_review.md", "validation_report.md"):
            if (root / name).resolve() not in registered or (root / name).resolve() not in linked:
                errors.append(f"feature_delivery_handoff_report_reference_required:{name}")
    completed = {row.get("Worker") for row in results if isinstance(row, dict) and row.get("Outcome") == "complete"}
    if pre_handoff:
        completed.discard("handoff")
        packet = {**packet, "runtime_audits": [row for row in packet.get("runtime_audits", [])
                                               if isinstance(row, dict) and row.get("Worker") != "handoff"]}
        handles = {row.get("Provider handle") for row in packet["runtime_audits"]}
        packet["terminal_observations"] = [row for row in packet.get("terminal_observations", [])
                                            if isinstance(row, dict) and row.get("Provider handle") in handles]
    errors.extend(_worker_runtime_audit_errors(packet, packet_path, completed))
    if identity.get("State") == "completed" and any(
        "context-unverified" in str(row.get("Uncertainties / blockers", "")) for row in results
    ):
        errors.append("feature_delivery_context_unverified_prevents_completion")
    return list(dict.fromkeys(errors))


def feature_delivery_pre_handoff_errors(packet_path: Path) -> list[str]:
    """Reject incomplete assessment or remediation evidence before activating Documenter."""
    try:
        packet = json.loads(packet_path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        return [f"Feature Delivery pre-handoff packet unavailable or invalid: {error}"]
    if not isinstance(packet, dict):
        return ["Feature Delivery pre-handoff packet must be an object"]
    identity = packet.get("identity", {})
    selection = packet.get("playbook_selection", {})
    if not isinstance(identity, dict) or not isinstance(selection, dict):
        return ["Feature Delivery pre-handoff identity or selection invalid"]
    if Path(str(identity.get("Playbook / version", "")).split(" / ", 1)[0]).stem.lower() != "feature_delivery":
        return []
    remediation = identity.get("Lifecycle") == "remediation"
    planning = not remediation and str(selection.get("Primary goal", "")).strip().lower() == "implementation planning"
    errors = _shape_errors(packet, json.loads(PACKET_TEMPLATE.read_text()), "packet")
    if errors:
        return errors
    root = packet_path.parent.resolve()
    if Path(str(packet["finalization"]["Durable artifact root"])).resolve() != root:
        errors.append("Feature Delivery pre-handoff artifact root must match packet directory")
        return errors
    _, input_errors = _feature_expected_inputs(packet, root)
    errors.extend(input_errors)
    errors.extend(asset_gate_errors(
        root / ASSET_MANIFEST_FILENAME, root / "run_inputs.json", str(packet["work_item"]["ID"]),
    ))
    if planning:
        errors.extend(error.replace("Technical Spike", "Feature Delivery")
                      for error in _technical_spike_reasoning_graph_errors(packet))
        for name in ("feature_context.md", "impact_analysis.md", "feature_design.md"):
            if not (root / name).is_file():
                errors.append(f"Feature Delivery pre-handoff requires {name}")
        candidate = json.loads(json.dumps(packet))
        candidate["identity"].update({"State": "awaiting_input", "Workflow outcome": "completed",
                                      "Engineering outcome": "partially_solved"})
        errors.extend(_feature_delivery_packet_contract_errors(candidate, pre_handoff=True))
        errors.extend(_worker_runtime_audit_errors(packet, packet_path, {
            row.get("Worker") for row in packet.get("worker_results", [])
            if row.get("Outcome") == "complete" and row.get("Worker") != "handoff"
        }))
        _, manifest = _feature_asset_manifest(packet)
        if manifest:
            errors.extend(validate_asset_manifest(manifest, expected_evidence_ids={
                row.get("Evidence ID") for row in packet.get("evidence", [])
            }))
        return list(dict.fromkeys(errors))
    if remediation:
        errors.extend(_feature_delivery_remediation_errors(packet, packet_path, pre_handoff=True))
        return list(dict.fromkeys(errors))
    profile = str(identity.get("Requested profile", "")).strip().lower()
    artifacts = ["feature_context.md", "impact_analysis.md", "feature_design.md"]
    if profile == "deep":
        artifacts.extend(["repository_integration.md", "planning_review.md"])
    for name in artifacts:
        path = root / name
        if not path.is_file():
            errors.append(f"Feature Delivery pre-handoff requires {name}")
        elif name == "feature_design.md":
            try:
                design_text = path.read_text()
                errors.extend(coverage_mapping_errors(design_text, name))
                handoff = packet.get("handoff", {})
                result = str(handoff.get("workflow_result", "")) if isinstance(handoff, dict) else ""
                errors.extend(coverage_readiness_errors(design_text, result, name))
            except OSError as error:
                errors.append(f"Feature Delivery pre-handoff cannot read {name}: {error}")
    errors.extend(_feature_assessment_reference_errors(packet))
    return list(dict.fromkeys(errors))


def _feature_assessment_reference_errors(packet: dict[str, object]) -> list[str]:
    identity = packet.get("identity", {})
    selection = packet.get("playbook_selection", {})
    if (not isinstance(identity, dict) or not isinstance(selection, dict)
            or Path(str(identity.get("Playbook / version", "")).split(" / ", 1)[0]).stem.lower()
            != "feature_delivery" or str(selection.get("Primary goal", "")).strip().lower()
            != "specification assessment"):
        return []
    errors = []
    for row in packet.get("durable_artifacts", []):
        if (isinstance(row, dict) and "coverage" in str(row.get("Artifact", "")).lower()
                and Path(str(row.get("Path", ""))).name == "work_record.md"):
            errors.append("Feature Delivery coverage mapping cannot point to work_record.md; use feature_design.md")
    for row in packet.get("evidence", []):
        if (isinstance(row, dict) and re.search(
            r"work_record\.md\s+(?:specification\s+)?coverage", str(row.get("Source", "")), re.IGNORECASE,
        )):
            errors.append("Feature Delivery evidence cannot cite a coverage section in rendered work_record.md")
    handoff = packet.get("handoff", {})
    if isinstance(handoff, dict) and re.search(
        r"\bno\b[^.]{0,120}\bfinalizer invocation\b", str(handoff.get("execution", "")), re.IGNORECASE,
    ):
        errors.append("Feature Delivery handoff cannot claim no finalizer invocation after finalization")
    return errors


def _technical_spike_packet_evidence_quality_errors(packet: dict[str, object]) -> list[str]:
    errors = []
    for index, row in enumerate(packet.get("evidence", [])):
        if not isinstance(row, dict):
            continue
        summary = re.sub(r"\s+", " ", str(row.get("Summary", ""))).strip()
        if TECHNICAL_SPIKE_GENERIC_EVIDENCE_SUMMARY.fullmatch(summary):
            evidence_id = str(row.get("Evidence ID", "row")).strip() or f"row {index + 1}"
            errors.append(
                f"Technical Spike packet Evidence {evidence_id} has a generic placeholder Summary; "
                "preserve the source-specific observation"
            )
    return errors


def _technical_spike_candidate_reference_errors(packet: dict[str, object]) -> list[str]:
    references: list[tuple[str, object]] = []
    for index, row in enumerate(packet.get("durable_artifacts", [])):
        if isinstance(row, dict):
            references.append((f"packet.durable_artifacts[{index}].Path", row.get("Path", "")))
    handoff = packet.get("handoff", {})
    if isinstance(handoff, dict):
        for index, value in enumerate(handoff.get("artifacts", [])):
            references.append((f"packet.handoff.artifacts[{index}]", value))

    errors = []
    for field, value in references:
        text = str(value).strip()
        if text.startswith("[") and "](" in text and text.endswith(")"):
            text = text.split("](", 1)[1][:-1]
        if Path(text).name == "spike_report.candidate.md":
            errors.append(
                "Technical Spike packet must reference published spike_report.md before candidate "
                f"publication: {field}"
            )
    return errors


def _technical_spike_report_artifact_errors(packet: dict[str, object], packet_path: Path) -> list[str]:
    expected = (packet_path.parent / "spike_report.md").resolve()
    for row in packet.get("durable_artifacts", []):
        if not isinstance(row, dict):
            continue
        value = str(row.get("Path", "")).strip()
        if value.startswith("[") and "](" in value and value.endswith(")"):
            value = value.split("](", 1)[1][:-1]
        if value:
            path = Path(value)
            if not path.is_absolute():
                path = packet_path.parent / path
            if path.resolve() == expected:
                return []
    return [
        "Technical Spike packet must predeclare durable artifact spike_report.md before report publication"
    ]


def _technical_spike_packet_contract_errors(
    packet: dict[str, object], *, pre_release: bool,
) -> list[str]:
    identity = packet.get("identity", {})
    selection = packet.get("playbook_selection", {})
    if not isinstance(identity, dict) or not isinstance(selection, dict):
        return []
    playbook = Path(str(identity.get("Playbook / version", "")).split(" / ", 1)[0]).stem.lower()
    if playbook != "technical_spike":
        return []

    errors: list[str] = []
    primary_goal = str(selection.get("Primary goal", "")).strip().lower()
    if primary_goal not in TECHNICAL_SPIKE_PRIMARY_GOALS:
        errors.append(
            "Technical Spike Primary goal must be Execute technical spike or Review technical spike"
        )

    state = str(identity.get("State", "")).strip().lower()
    profiles = [
        str(identity.get(field, "")).strip().lower()
        for field in ("Requested profile", "Activated profile", "Executed profile")
    ]
    if state in {"handoff", "completed"}:
        invalid_profiles = sorted({profile for profile in profiles if profile not in TECHNICAL_SPIKE_PROFILES})
        if invalid_profiles:
            errors.append(
                "Technical Spike profiles must be standard or deep; received "
                + ", ".join(invalid_profiles)
            )
        elif len(set(profiles)) != 1:
            errors.append("Technical Spike Requested, Activated, and Executed profiles must match")

        missing_tables = []
        incomplete_rows = []
        for field, label, identity_field, required_fields in TECHNICAL_SPIKE_REASONING_TABLES:
            rows = _material_rows(packet.get(field), identity_field)
            if not rows:
                missing_tables.append(label)
                continue
            for index, row in enumerate(rows, start=1):
                missing_fields = [name for name in required_fields if not str(row.get(name, "")).strip()]
                if missing_fields:
                    incomplete_rows.append(f"{label} row {index}: {', '.join(missing_fields)}")
        if missing_tables:
            errors.append(
                "Technical Spike finalization packet requires populated rows for: "
                + ", ".join(missing_tables)
            )
        if incomplete_rows:
            errors.append(
                "Technical Spike finalization packet contains incomplete reasoning rows: "
                + "; ".join(incomplete_rows)
            )
        errors.extend(_technical_spike_packet_evidence_quality_errors(packet))
        errors.extend(_technical_spike_reasoning_graph_errors(packet))
        for row in packet.get("worker_results", []):
            if not isinstance(row, dict):
                continue
            refs = str(row.get("Evidence / claim refs", "")).strip().lower()
            if refs.startswith(TECHNICAL_SPIKE_UNRESOLVED_WORKER_REF):
                worker = str(row.get("Worker", "")).strip() or "row"
                errors.append(
                    f"Technical Spike worker result {worker} Evidence / claim refs must be finalized"
                )
            grouped = TECHNICAL_SPIKE_RANGE_REFERENCE.search(refs)
            if grouped:
                worker = str(row.get("Worker", "")).strip() or "row"
                errors.append(
                    f"Technical Spike worker result {worker} Evidence / claim refs must use exact IDs; "
                    f"grouped/range reference {grouped.group(0)!r} is not allowed"
                )

        handoff = packet.get("handoff", {})
        if isinstance(handoff, dict):
            for field in ("established", "best_current_explanations"):
                for index, item in enumerate(handoff.get(field, [])):
                    grouped = TECHNICAL_SPIKE_RANGE_REFERENCE.search(str(item))
                    if grouped:
                        errors.append(
                            f"Technical Spike handoff {field}[{index}] must use exact IDs; "
                            f"grouped/range reference {grouped.group(0)!r} is not allowed"
                        )

    prompt_identity = str(identity.get("Prompt template / revision / conformance", "")).split(" / ", 2)
    conformance = prompt_identity[2].strip().lower() if len(prompt_identity) == 3 else ""
    if not re.fullmatch(r"(?:pass|fail|fail(?::|;).+)", conformance, re.IGNORECASE):
        errors.append("Technical Spike prompt conformance must be pass or fail:<missing fields>")

    workflow_outcome = str(identity.get("Workflow outcome", "")).strip().lower()
    if pre_release and state == "handoff" and workflow_outcome == "completed":
        errors.append(
            "Technical Spike pre-release State handoff requires a non-completed Workflow outcome"
        )

    if primary_goal in TECHNICAL_SPIKE_PRIMARY_GOALS and state in {"handoff", "completed"}:
        handoff = packet.get("handoff", {})
        result = str(handoff.get("workflow_result", "") if isinstance(handoff, dict) else "").strip()
        if result not in TECHNICAL_SPIKE_DISPOSITIONS[primary_goal]:
            errors.append(
                "Technical Spike handoff Workflow result must be exactly one of: "
                + ", ".join(TECHNICAL_SPIKE_DISPOSITIONS[primary_goal])
            )
    return errors


def _canonicalize_technical_spike_worker_ids(
    packet: dict[str, object], manifest: dict[str, object],
) -> None:
    identity = packet.get("identity", {})
    playbook = str(manifest.get("playbook", ""))
    if isinstance(identity, dict):
        playbook = playbook or Path(
            str(identity.get("Playbook / version", "")).split(" / ", 1)[0]
        ).stem
    if playbook != "technical_spike":
        return
    # Accept only provider-form composites declared by the Technical Spike
    # worker contract; arbitrary worker aliases remain validation errors.
    aliases = {"documenter": "handoff"}
    for worker_roles in TECHNICAL_SPIKE_WORKER_ROLES.values():
        aliases.update({f"{worker}/{role}": worker for worker, role in worker_roles.items()})
    for field in ("workers", "worker_results"):
        rows = packet.get(field, [])
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            worker = str(row.get("Worker", "")).strip().lower()
            if worker in aliases:
                row["Worker"] = aliases[worker]


def _techops_planning_contract_errors(
    packet: dict[str, object], packet_path: Path, *, pre_handoff: bool = False, table_projection: bool = False,
) -> list[str]:
    identity = packet.get("identity", {})
    if (Path(str(identity.get("Playbook / version", "")).split(" / ", 1)[0]).stem
            != "techops_issue_remediation" or identity.get("Lifecycle") != "planning"):
        return []
    completed = {str(row.get("Worker")) for row in packet.get("worker_results", [])
                 if row.get("Outcome") == "complete"}
    ready_plan = identity.get("Engineering outcome") == "plan_only" or identity.get("State") == "ready_for_implementation"
    if "fix-design" not in completed and not ready_plan:
        return []  # Early source-access blocks have no design to accept.
    errors = techops_check_errors(packet.get("techops_checks"), {
        str(row.get("Evidence ID")) for row in packet.get("evidence", [])
    })
    if ready_plan:
        required = {"issue-evidence", "failure-path", "fix-design"}
        if not pre_handoff:
            required.add("handoff")
        if identity.get("Executed profile") == "deep":
            required.update({"repository-integration", "planning-review"})
        if not required <= completed:
            errors.append("techops_planning_workers_incomplete")
    if pre_handoff:
        completed.discard("handoff")
        packet = {**packet, "runtime_audits": [row for row in packet.get("runtime_audits", [])
                                               if isinstance(row, dict) and row.get("Worker") != "handoff"],
                  "terminal_observations": []}
    errors.extend(_worker_runtime_audit_errors(packet, packet_path, completed))
    bindings = packet_path.parent / "role_bindings.json"
    if bindings.is_file():
        try:
            from merge_techops_result import merged_result_errors
        except ModuleNotFoundError:
            from scripts.merge_techops_result import merged_result_errors
        try:
            errors.extend(merged_result_errors(packet, json.loads(bindings.read_text()), packet_path.parent,
                                              table_projection=table_projection))
        except (OSError, ValueError, TypeError, AttributeError) as error:
            errors.append("worker_result_source_invalid:" + str(error))
    return list(dict.fromkeys(errors))


def _worker_runtime_audit_errors(
    packet: dict[str, object], packet_path: Path, completed: set[str],
) -> list[str]:
    """Shared trace and fan-in proof for TechOps planning and Feature Delivery remediation."""
    errors = []
    audits = packet.get("runtime_audits", [])
    if not isinstance(audits, list) or any(not isinstance(row, dict) for row in audits):
        return ["worker_runtime_audits_invalid"]
    if {row.get("Worker") for row in audits} != completed or len(audits) != len(completed):
        errors.append("worker_runtime_audits_incomplete")
    errors.extend(terminal_observation_errors(audits, [str(row.get("Provider handle")) for row in audits]))
    errors.extend(dispatch_audit_errors(packet, packet_path))
    observations = packet.get("terminal_observations", [])
    if isinstance(observations, list) and observations:
        dispatches = {row.get("Provider handle"): row.get("Last dispatch at") for row in audits}
        manifest_path = packet_path.parent / "role_bindings.json"
        try:
            manifest = json.loads(manifest_path.read_text()) if manifest_path.is_file() else {}
            ledger_path = manifest.get("runtime_evidence", {}).get("ledger")
            if ledger_path:
                ledger = json.loads(Path(ledger_path).read_text())
                for handle in {event["Provider handle"] for event in ledger["events"]}:
                    dispatches[handle] = latest_worker_dispatch(ledger, handle)["Last dispatch at"]
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            errors.append("terminal_closure_dispatch_evidence_invalid:" + str(error))
        if {row.get("Provider handle") for row in observations if isinstance(row, dict)} != set(dispatches):
            errors.append("terminal_closure_worker_handle_mismatch")
        for row in observations:
            if isinstance(row, dict) and row.get("Last dispatch at") != dispatches.get(row.get("Provider handle")):
                errors.append("terminal_closure_worker_audit_stale")
    for row in audits:
        worker = str(row.get("Worker", ""))
        if row.get("Provider status") != "completed":
            errors.append(f"fan_in_requires_completed_status:{worker}")
        trace_path = str(row.get("Trace path", "")).strip()
        if not trace_path:
            retrieval = str(row.get("Trace retrieval", "")).strip()
            result = next((item for item in packet.get("worker_results", []) if item.get("Worker") == worker), {})
            if (not retrieval.startswith("unavailable:") or len(retrieval) <= len("unavailable:")
                    or "context-unverified" not in str(result.get("Uncertainties / blockers", ""))):
                errors.append(f"worker_trace_retrieval_evidence_required:{worker}")
            continue
        source = Path(trace_path)
        source = source if source.is_absolute() else packet_path.parent / source
        if source.resolve().parent != packet_path.parent.resolve():
            errors.append(f"worker_trace_outside_current_run:{worker}")
            continue
        try:
            trace = json.loads(source.read_text())
            if not isinstance(trace, dict):
                raise ValueError("trace must be an object")
            if not isinstance(trace.get("tool_trace"), list):
                errors.append(f"worker_tool_trace_required:{worker}")
            errors.extend(trace_errors(trace, require_freshness=True))
            errors.extend(trace_identity_errors(trace, packet_path.parent, worker,
                                                row.get("Provider handle"), row.get("Thread ID")))
            if trace.get("last_dispatch_at") != row.get("Last dispatch at"):
                errors.append(f"worker_trace_stale:{worker}")
            if not any(event.get("action") == "fan_in" and event.get("provider_status") == "completed"
                       for event in trace.get("events", []) if isinstance(event, dict)):
                errors.append(f"worker_fan_in_guard_receipt_required:{worker}")
        except (OSError, ValueError, TypeError) as error:
            errors.append(f"worker_trace_invalid:{worker}:{error}")
    return list(dict.fromkeys(errors))
