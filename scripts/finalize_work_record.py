#!/usr/bin/env python3
"""Validate a structured packet and atomically render a terminal work record."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Same-name aliases preserve compatibility exports and make that intent explicit to static analyzers.
try:
    from run_input_manifest import load_manifest as load_manifest
except ModuleNotFoundError:  # Imported as scripts.finalize_work_record from the repository root.
    from scripts.run_input_manifest import load_manifest as load_manifest

try:
    from asset_manifest import (
        ASSET_MANIFEST_FILENAME as ASSET_MANIFEST_FILENAME,
        asset_gate_errors as asset_gate_errors,
        asset_plan_errors as asset_plan_errors,
        validate_asset_manifest as validate_asset_manifest,
    )
except ModuleNotFoundError:  # Imported as scripts.finalize_work_record from the repository root.
    from scripts.asset_manifest import (
        ASSET_MANIFEST_FILENAME as ASSET_MANIFEST_FILENAME,
        asset_gate_errors as asset_gate_errors,
        asset_plan_errors as asset_plan_errors,
        validate_asset_manifest as validate_asset_manifest,
    )

try:
    from specification_assessment import (
        NO_PLAN_MESSAGE,
        REPORT_NAME as REPORT_NAME,
        assessment_report_errors as assessment_report_errors,
        coverage_mapping_errors as coverage_mapping_errors,
        coverage_readiness_errors as coverage_readiness_errors,
    )
except ModuleNotFoundError:  # Imported as scripts.finalize_work_record from the repository root.
    from scripts.specification_assessment import (
        NO_PLAN_MESSAGE,
        REPORT_NAME as REPORT_NAME,
        assessment_report_errors as assessment_report_errors,
        coverage_mapping_errors as coverage_mapping_errors,
        coverage_readiness_errors as coverage_readiness_errors,
    )

try:
    from review_evidence import (
        PLAN_FIXTURE as PLAN_FIXTURE,
        REVIEW_FIXTURE as REVIEW_FIXTURE,
        applicability_errors as applicability_errors,
        completed_review_errors as completed_review_errors,
        delivery_evidence_fixture as delivery_evidence_fixture,
        review_report_errors as review_report_errors,
        validation_report_errors as validation_report_errors,
        plan_design_errors as plan_design_errors,
        plan_review_coverage_errors as plan_review_coverage_errors,
        draft_plan_errors as draft_plan_errors,
    )
except ModuleNotFoundError:  # Imported as scripts.finalize_work_record from the repository root.
    from scripts.review_evidence import (
        PLAN_FIXTURE as PLAN_FIXTURE,
        REVIEW_FIXTURE as REVIEW_FIXTURE,
        applicability_errors as applicability_errors,
        completed_review_errors as completed_review_errors,
        delivery_evidence_fixture as delivery_evidence_fixture,
        review_report_errors as review_report_errors,
        validation_report_errors as validation_report_errors,
        plan_design_errors as plan_design_errors,
        plan_review_coverage_errors as plan_review_coverage_errors,
        draft_plan_errors as draft_plan_errors,
    )

try:
    from runtime_checks import (
        terminal_observation_errors,
        techops_check_errors as techops_check_errors,
        trace_errors,
        prepared_package_errors,
        trace_identity_errors,
    )
except ModuleNotFoundError:
    from scripts.runtime_checks import (
        terminal_observation_errors,
        techops_check_errors as techops_check_errors,
        trace_errors,
        prepared_package_errors,
        trace_identity_errors,
    )

try:
    from worker_runtime_evidence import dispatch_audit_errors
except ModuleNotFoundError:
    from scripts.worker_runtime_evidence import dispatch_audit_errors


try:
    from packet_schema import shape_errors as _shape_errors
except ModuleNotFoundError:
    from scripts.packet_schema import shape_errors as _shape_errors


try:
    from workflow_policy import (
        PROMPT_TEMPLATES,
        FEATURE_ASSESSMENT_DISPOSITIONS,
        TECHNICAL_SPIKE_DISPOSITIONS,
        NO_ACTIVE_HANDLES,
    )
except ModuleNotFoundError:
    from scripts.workflow_policy import (
        PROMPT_TEMPLATES,
        FEATURE_ASSESSMENT_DISPOSITIONS,
        TECHNICAL_SPIKE_DISPOSITIONS,
        NO_ACTIVE_HANDLES,
    )


try:
    from work_record_format import (
        _feature_asset_manifest as _feature_asset_manifest,
        _explanation_text,
        _artifact_link,
        _relative_artifact_path as _relative_artifact_path,
        _artifact_rows_for_record as _artifact_rows_for_record,
        _feature_asset_section as _feature_asset_section,
        _cell as _cell,
        _table as _table,
        _mapping_table as _mapping_table,
        _section as _section,
        _runtime_closed,
        snapshot_bytes,
        snapshot_name,
        render_compact,
        render_handoff,
        render as render,
        _material_rows,
    )
except ModuleNotFoundError:
    from scripts.work_record_format import (
        _feature_asset_manifest as _feature_asset_manifest,
        _explanation_text,
        _artifact_link,
        _relative_artifact_path as _relative_artifact_path,
        _artifact_rows_for_record as _artifact_rows_for_record,
        _feature_asset_section as _feature_asset_section,
        _cell as _cell,
        _table as _table,
        _mapping_table as _mapping_table,
        _section as _section,
        _runtime_closed,
        snapshot_bytes,
        snapshot_name,
        render_compact,
        render_handoff,
        render as render,
        _material_rows,
    )


try:
    from validation.frontmatter import document_version as _frontmatter_version
except ModuleNotFoundError:
    from scripts.validation.frontmatter import document_version as _frontmatter_version


try:
    from planning_contracts import (
        _canonicalize_technical_spike_worker_ids,
        _feature_assessment_reference_errors,
        _feature_asset_artifact_path as _feature_asset_artifact_path,
        _feature_delivery_asset_contract_errors,
        _feature_delivery_packet_contract_errors,
        _feature_delivery_remediation_errors as _feature_delivery_remediation_errors,
        _feature_expected_inputs as _feature_expected_inputs,
        _planning_runtime_closure_errors,
        _technical_spike_candidate_reference_errors,
        _technical_spike_missing_workers,
        _technical_spike_packet_contract_errors,
        _technical_spike_packet_evidence_quality_errors as _technical_spike_packet_evidence_quality_errors,
        _technical_spike_reasoning_graph_errors as _technical_spike_reasoning_graph_errors,
        _technical_spike_report_artifact_errors,
        _technical_spike_worker_contract_errors,
        _techops_planning_contract_errors,
        _worker_runtime_audit_errors as _worker_runtime_audit_errors,
        feature_delivery_pre_handoff_errors as feature_delivery_pre_handoff_errors,
    )
except ModuleNotFoundError:
    from scripts.planning_contracts import (
        _canonicalize_technical_spike_worker_ids,
        _feature_assessment_reference_errors,
        _feature_asset_artifact_path as _feature_asset_artifact_path,
        _feature_delivery_asset_contract_errors,
        _feature_delivery_packet_contract_errors,
        _feature_delivery_remediation_errors as _feature_delivery_remediation_errors,
        _feature_expected_inputs as _feature_expected_inputs,
        _planning_runtime_closure_errors,
        _technical_spike_candidate_reference_errors,
        _technical_spike_missing_workers,
        _technical_spike_packet_contract_errors,
        _technical_spike_packet_evidence_quality_errors as _technical_spike_packet_evidence_quality_errors,
        _technical_spike_reasoning_graph_errors as _technical_spike_reasoning_graph_errors,
        _technical_spike_report_artifact_errors,
        _technical_spike_worker_contract_errors,
        _techops_planning_contract_errors,
        _worker_runtime_audit_errors as _worker_runtime_audit_errors,
        feature_delivery_pre_handoff_errors as feature_delivery_pre_handoff_errors,
    )


try:
    from planning_contracts import (
        REFERENCE_ID as REFERENCE_ID,
        TECHNICAL_SPIKE_RANGE_REFERENCE as TECHNICAL_SPIKE_RANGE_REFERENCE,
        TECHNICAL_SPIKE_PRIMARY_GOALS as TECHNICAL_SPIKE_PRIMARY_GOALS,
        TECHNICAL_SPIKE_PROFILES as TECHNICAL_SPIKE_PROFILES,
        TECHNICAL_SPIKE_REASONING_TABLES as TECHNICAL_SPIKE_REASONING_TABLES,
        TECHNICAL_SPIKE_UNRESOLVED_WORKER_REF as TECHNICAL_SPIKE_UNRESOLVED_WORKER_REF,
        TECHNICAL_SPIKE_GENERIC_EVIDENCE_SUMMARY as TECHNICAL_SPIKE_GENERIC_EVIDENCE_SUMMARY,
        TECHNICAL_SPIKE_REQUIRED_WORKERS as TECHNICAL_SPIKE_REQUIRED_WORKERS,
        TECHNICAL_SPIKE_WORKER_ROLES as TECHNICAL_SPIKE_WORKER_ROLES,
        FEATURE_DELIVERY_WORKER_ROLES as FEATURE_DELIVERY_WORKER_ROLES,
        FEATURE_DELIVERY_LEDGER_FIELDS as FEATURE_DELIVERY_LEDGER_FIELDS,
        FEATURE_DELIVERY_RESULT_FIELDS as FEATURE_DELIVERY_RESULT_FIELDS,
        AGENT_ROLE_LABELS,
        ROLE_AGENTS,
    )
except ModuleNotFoundError:
    from scripts.planning_contracts import (
        REFERENCE_ID as REFERENCE_ID,
        TECHNICAL_SPIKE_RANGE_REFERENCE as TECHNICAL_SPIKE_RANGE_REFERENCE,
        TECHNICAL_SPIKE_PRIMARY_GOALS as TECHNICAL_SPIKE_PRIMARY_GOALS,
        TECHNICAL_SPIKE_PROFILES as TECHNICAL_SPIKE_PROFILES,
        TECHNICAL_SPIKE_REASONING_TABLES as TECHNICAL_SPIKE_REASONING_TABLES,
        TECHNICAL_SPIKE_UNRESOLVED_WORKER_REF as TECHNICAL_SPIKE_UNRESOLVED_WORKER_REF,
        TECHNICAL_SPIKE_GENERIC_EVIDENCE_SUMMARY as TECHNICAL_SPIKE_GENERIC_EVIDENCE_SUMMARY,
        TECHNICAL_SPIKE_REQUIRED_WORKERS as TECHNICAL_SPIKE_REQUIRED_WORKERS,
        TECHNICAL_SPIKE_WORKER_ROLES as TECHNICAL_SPIKE_WORKER_ROLES,
        FEATURE_DELIVERY_WORKER_ROLES as FEATURE_DELIVERY_WORKER_ROLES,
        FEATURE_DELIVERY_LEDGER_FIELDS as FEATURE_DELIVERY_LEDGER_FIELDS,
        FEATURE_DELIVERY_RESULT_FIELDS as FEATURE_DELIVERY_RESULT_FIELDS,
        AGENT_ROLE_LABELS,
        ROLE_AGENTS,
    )


try:
    from validation.api import checked, validate_package, record_validation_output
    from validation.finalization import validate_normalized_evidence, validate_sentry_artifacts
    from validation.playbooks import technical_spike_report_errors
except ModuleNotFoundError:
    from scripts.validation.api import checked, validate_package, record_validation_output
    from scripts.validation.finalization import validate_normalized_evidence, validate_sentry_artifacts
    from scripts.validation.playbooks import technical_spike_report_errors


try:
    from packet_schema import _validate_shapes, normalize_runtime_closure
    from work_record_format import expand_work_record
except ModuleNotFoundError:
    from scripts.packet_schema import _validate_shapes, normalize_runtime_closure
    from scripts.work_record_format import expand_work_record


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "validate_library.py"
PACKET_TEMPLATE = ROOT / "templates" / "finalization_packet.json"
CLOSURE_TEMPLATE = ROOT / "templates" / "runtime_closure.json"
PLUGIN_MANIFEST = ROOT / ".codex-plugin" / "plugin.json"
V22_FIXTURE = ROOT / "tests" / "fixtures" / "sentry_planning.json"
V28_STABILIZATION_FIXTURE = ROOT / "tests" / "fixtures" / "sentry_stabilization.json"
V29_CONTRACT_FAILURE_FIXTURE = ROOT / "tests" / "fixtures" / "sentry_contract_failure.json"
V31_FIX_DESIGN_FIXTURE = ROOT / "tests" / "fixtures" / "sentry_fix_design_contract.json"
V34_FINALIZATION_FIXTURE = ROOT / "tests" / "fixtures" / "sentry_deterministic_finalization.json"
UUID_PATTERN = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
MODEL_EFFORT_PATTERN = re.compile(
    r"^\s*(\S+)\s*/\s*(none|minimal|low|medium|high|xhigh|max|ultra)(?:\s*;.*)?$", re.IGNORECASE
)
UNAVAILABLE_COORDINATOR_MODEL_EFFORT = "Not exposed / Not exposed"
ROLE_LABELS = {
    **AGENT_ROLE_LABELS,
    "evidence-topology": "Evidence topology",
    "fix-design": "Fix design",
    "failure-topology": "Failure topology",
    "repository-integration": "Repository integration",
    "handoff": "Documenter",
    "sentry_current_state_investigator": "Evidence topology",
    "sentry_solution_architect": "Fix design",
    "sentry_repository_integrator": "Repository integration",
}
FINALIZATION_STATUS_FILENAME = "finalization_failure.json"
TECHOPS_STATE_RESULT_TOKENS = {
    "ready for implementation", "completed", "blocked", "awaiting input", "plan only", "handoff",
    "ready with explicit follow ups", "ready for approval", "designed", "implemented", "validated",
}
ANALYTICAL_FAILURE_STAGES = {
    "evidence_topology": {
        "binding": "sentry_current_state_investigator",
        "worker": "evidence-topology",
        "role": "Evidence topology",
        "validation_stage": "Evidence validation",
        "implementation_plan": "omitted; normalized evidence failed validation",
        "established": "Evidence Topology produced an artifact, but its required contract validation failed.",
        "claim": "Fix Design cannot start from invalid normalized evidence.",
        "action": "Correct the evidence contract before retrying planning.",
        "complete_when": "Normalized evidence passes before Fix Design activation.",
    },
    "repository_integration": {
        "binding": "sentry_repository_integrator",
        "worker": "repository-integration",
        "role": "Repository integration",
        "validation_stage": "Repository integration validation",
        "implementation_plan": "omitted; repository-integration result failed validation",
        "established": "Normalized evidence passed, but the Repository Integration result failed its terminal contract.",
        "claim": "Fix Design cannot consume an invalid repository-integration result.",
        "action": "Correct the repository-integration result contract and resume from existing evidence.",
        "complete_when": "Repository Integration passes before Fix Design activation.",
    },
    "fix_design": {
        "binding": "sentry_solution_architect",
        "worker": "fix-design",
        "role": "Fix design",
        "validation_stage": "Fix design validation",
        "implementation_plan": "omitted; Fix Design result failed envelope validation",
        "established": "Normalized evidence passed and Fix Design returned, but its terminal envelope failed validation.",
        "claim": "The existing Fix Design output cannot enter fan-in until its result envelope passes validation.",
        "action": "Correct the Fix Design result envelope and finalize the existing analytical outputs.",
        "complete_when": "The existing Fix Design result passes without rerunning completed analytical workers.",
    },
}


def _append_unique_artifact(rows: list[dict[str, object]], row: dict[str, object]) -> None:
    path = str(row["Path"])
    if not any(str(existing.get("Path", "")) == path for existing in rows):
        rows.append(row)




def _normalize_model_effort(value: object) -> object:
    match = MODEL_EFFORT_PATTERN.fullmatch(str(value))
    return f"{match.group(1)} / {match.group(2).lower()}" if match else value


def _normalize_coordinator_model_effort(value: object) -> object:
    text = str(value).strip().lower()
    if "not exposed" in text or "packet-input error" in text:
        return UNAVAILABLE_COORDINATOR_MODEL_EFFORT
    return _normalize_model_effort(value)


def _is_run_context_evidence(row: object) -> bool:
    if not isinstance(row, dict):
        return False
    source = str(row.get("Source", "")).strip().lower()
    return any(
        marker in source
        for marker in ("current user", "user request", "run constraint", "clean-run constraint")
    )


def _normalize_playbook_identity(value: object) -> object:
    parts = str(value).split(" / ", 1)
    if len(parts) != 2 or parts[0].endswith(".md"):
        return value
    supplied = parts[0].strip().lower().replace(" ", "_")
    for path in (ROOT / "playbooks").glob("*.md"):
        title = re.search(r"^title:\s*(.+)$", path.read_text(), re.MULTILINE)
        names = {path.stem.lower()}
        if title:
            names.add(title.group(1).strip().lower().replace(" ", "_"))
        if supplied in names:
            return f"playbooks/{path.name} / {parts[1].strip()}"
    return value


def _normalize_plugin_identity(value: object) -> object:
    supplied = str(value).strip()
    if supplied.lower() == "not applicable" or " / " in supplied:
        return supplied
    match = re.fullmatch(r"([^\s/]+)\s+(\S+)", supplied)
    return f"{match.group(1)} / {match.group(2)}" if match else value


def _normalize_prompt_identity(value: object) -> object:
    parts = str(value).split(" / ", 2)
    if len(parts) != 3:
        return value
    conformance = parts[2].strip().lower()
    if conformance in {"conformant", "passed", "success"} or conformance.startswith("pass:"):
        parts[2] = "pass"
    return " / ".join(parts)


def _prepared_manifest(packet_path: Path | None) -> tuple[dict[str, object], Path | None]:
    if packet_path is None:
        return {}, None
    path = packet_path.parent / "role_bindings.json"
    if not path.is_file():
        return {}, None
    try:
        return json.loads(path.read_text()), path
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid_role_binding_manifest:{path}:{error}") from error


def _normalize_packet(
    packet: dict[str, object], closure: dict[str, object], packet_path: Path | None = None,
    budget_status: str | None = None,
) -> None:
    packet["terminal_observations"] = closure.get("terminal_observations", [])
    manifest, manifest_path = _prepared_manifest(packet_path)
    _canonicalize_technical_spike_worker_ids(packet, manifest)
    identity = packet.get("identity", {})
    if isinstance(identity, dict):
        playbook = str(manifest.get("playbook", ""))
        if playbook:
            playbook_path = ROOT / "playbooks" / f"{playbook}.md"
            prompt_path = ROOT / "templates" / PROMPT_TEMPLATES[playbook]
            plugin = json.loads(PLUGIN_MANIFEST.read_text())
            conformance = str(identity.get("Prompt template / revision / conformance", "")).split(" / ")[-1]
            identity.update({
                "Playbook / version": f"playbooks/{playbook}.md / {_frontmatter_version(playbook_path)}",
                "Plugin package / version": f"{plugin['name']} / {plugin['version']}",
                "Prompt template / revision / conformance": (
                    f"templates/{prompt_path.name} / {_frontmatter_version(prompt_path)} / {conformance}"
                ),
                "Role binding manifest": str(manifest_path),
                "Coordinator execution": "active parent session; no dedicated Coordinator worker spawned",
            })
            for field, value in (
                ("Provider/runtime configuration", manifest.get("provider_runtime_configuration")),
                ("Provider configuration source/status", manifest.get("provider_configuration_source_status")),
                ("Role-policy baseline ID", manifest.get("baseline_id")),
                ("Run input manifest", manifest.get("run_input_manifest", {}).get("path")),
                ("Run input manifest hash", manifest.get("run_input_manifest", {}).get("sha256")),
            ):
                if value:
                    identity[field] = value
        framework = str(identity.get("Framework commit / status", ""))
        revision = re.search(r"[0-9a-fA-F]{40}", framework)
        status = re.search(r"\b(Clean|Dirty)\b", framework, re.IGNORECASE)
        if revision and status:
            identity["Framework commit / status"] = f"{revision.group(0)} / {status.group(1).title()}"
        identity["Playbook / version"] = _normalize_playbook_identity(identity.get("Playbook / version", ""))
        identity["Plugin package / version"] = _normalize_plugin_identity(
            identity.get("Plugin package / version", "")
        )
        identity["Prompt template / revision / conformance"] = _normalize_prompt_identity(
            identity.get("Prompt template / revision / conformance", "")
        )
        identity["Coordinator model/effort"] = _normalize_coordinator_model_effort(
            identity.get("Coordinator model/effort", "")
        )
        profiles = [str(identity.get(field, "")).strip().lower() for field in (
            "Requested profile", "Activated profile", "Executed profile"
        )]
        if (
            str(identity.get("Profile status", "")).strip().lower() in {"conformant", "passed"}
            and len(set(profiles)) == 1
            and profiles[0] in {"standard", "deep"}
        ):
            identity["Profile status"] = "executed"
    ledger_by_worker: dict[str, dict[str, object]] = {}
    bindings = manifest.get("bindings", {})
    for row in packet.get("workers", []):
        if not isinstance(row, dict):
            continue
        raw_role = str(row.get("Role", "")).strip()
        agent = raw_role if raw_role in bindings else ROLE_AGENTS.get(raw_role)
        role = raw_role.lower()
        if role in ROLE_LABELS:
            row["Role"] = ROLE_LABELS[role]
        binding = bindings.get(agent, {}) if agent else {}
        row["Configured model/effort"] = (
            f"{binding['model']} / {binding['effort']}" if binding
            else _normalize_model_effort(row.get("Configured model/effort", ""))
        )
        ledger_by_worker[str(row.get("Worker", "")).strip().lower()] = row
    for row in packet.get("worker_results", []):
        if not isinstance(row, dict):
            continue
        ledger = ledger_by_worker.get(str(row.get("Worker", "")).strip().lower())
        if ledger:
            row["Actual model/effort"] = ledger.get("Provider-observed model/effort", "")
    durable_artifacts = packet.get("durable_artifacts", [])
    if isinstance(durable_artifacts, list):
        normalized_artifacts = [
            row for row in durable_artifacts
            if not isinstance(row, dict)
            or not str(row.get("Status", "")).strip().lower().startswith(
                ("omitted", "not created", "prohibited")
            )
        ]
        if budget_status:
            for row in normalized_artifacts:
                artifact_name = re.sub(r"[_-]+", " ", str(row.get("Artifact", "")).lower())
                if artifact_name == "run budget":
                    row["Status"] = budget_status
        if playbook == "technical_spike" and packet_path is not None:
            report = (packet_path.parent / "spike_report.md").resolve()
            for row in normalized_artifacts:
                if Path(str(row.get("Path", ""))).name == "spike_report.md" and report.is_file():
                    row["Status"] = "Published"
        packet["durable_artifacts"] = normalized_artifacts
    evidence = packet.get("evidence")
    if isinstance(evidence, list):
        packet["evidence"] = [row for row in evidence if not _is_run_context_evidence(row)]
    normalize_runtime_closure(closure)
    handoff = packet.get("handoff")
    if isinstance(handoff, dict):
        handoff["workflow_result"] = re.sub(
            r"^\s*Workflow result:\s*", "", str(handoff.get("workflow_result", "")), flags=re.IGNORECASE
        )
        if isinstance(identity, dict):
            playbook_name = Path(str(identity.get("Playbook / version", "")).split(" / ", 1)[0]).stem
            selection = packet.get("playbook_selection", {})
            primary_goal = str(selection.get("Primary goal", "")).strip().lower() if isinstance(selection, dict) else ""
            dispositions = TECHNICAL_SPIKE_DISPOSITIONS.get(primary_goal) if playbook_name == "technical_spike" else None
            result = str(handoff.get("workflow_result", "")).strip()
            worker_results = packet.get("worker_results", [])
            if (
                str(identity.get("State", "")).strip().lower() == "handoff"
                and dispositions
                and result in dispositions
                and isinstance(worker_results, list)
                and worker_results
                and not _technical_spike_missing_workers(packet)
            ):
                identity.update({
                    "State": "completed",
                    "Workflow outcome": "completed",
                    "Engineering outcome": dispositions[result],
                })
            plugin = str(identity.get("Plugin package / version", "")).replace(" / ", " ")
            framework = str(identity.get("Framework commit / status", "")).split(" / ", 1)
            playbook = str(identity.get("Playbook / version", "")).split(" / ", 1)
            if len(framework) == 2 and len(playbook) == 2:
                handoff["provenance"] = (
                    f"plugin {plugin}; framework revision {framework[0]} ({framework[1].lower()}); "
                    f"playbook {Path(playbook[0]).stem} {playbook[1]}."
                )


def _validate_handoff(
    packet: dict[str, object], *, publishing: bool = False, check_provenance: bool = True,
) -> None:
    handoff = packet.get("handoff", {})
    if not isinstance(handoff, dict):
        raise ValueError("packet.handoff must be an object")
    for field in ("workflow_result", "implementation_plan", "execution", "provenance"):
        if not str(handoff.get(field, "")).strip():
            raise ValueError(f"packet.handoff.{field} must be a non-empty string")
    identity = packet.get("identity", {})
    if isinstance(identity, dict):
        playbook = Path(str(identity.get("Playbook / version", "")).split(" / ", 1)[0]).stem
        if playbook == "techops_issue_remediation" and (
            re.sub(r"[_-]+", " ", str(handoff["workflow_result"]).strip().lower())
            in TECHOPS_STATE_RESULT_TOKENS | {"partially answered", "answered"}
        ):
            raise ValueError("TechOps workflow_result requires a plain-language work summary, not a state token")
        provenance = str(handoff["provenance"]).lower()
        framework_revision = str(identity.get("Framework commit / status", "")).split(" / ", 1)[0].lower()
        playbook = str(identity.get("Playbook / version", "")).split(" / ", 1)[0]
        if check_provenance and framework_revision and framework_revision not in provenance:
            raise ValueError("packet.handoff.provenance must contain the framework revision")
        if check_provenance and playbook and Path(playbook).stem.lower() not in provenance:
            raise ValueError("packet.handoff.provenance must contain the playbook name")
        selection = packet.get("playbook_selection", {})
        primary_goal = str(selection.get("Primary goal", "")).strip().lower() if isinstance(selection, dict) else ""
        playbook_name = Path(playbook).stem.lower()
        if (
            playbook_name == "feature_delivery"
            and str(identity.get("Lifecycle", "")).strip().lower() == "planning"
            and primary_goal == "specification assessment"
        ):
            state = str(identity.get("State", "")).strip().lower()
            allowed = FEATURE_ASSESSMENT_DISPOSITIONS.get(state)
            result = str(handoff["workflow_result"]).strip()
            if allowed and result not in allowed:
                raise ValueError(
                    f"Feature Delivery specification assessment state {state} requires Workflow result exactly one of: "
                    + ", ".join(sorted(allowed))
                )
            if allowed and str(handoff["implementation_plan"]).strip() != NO_PLAN_MESSAGE:
                raise ValueError(f"Feature Delivery specification assessment Implementation plan must be {NO_PLAN_MESSAGE}")
        if playbook_name == "technical_spike":
            lifecycle = str(identity.get("Lifecycle", "")).strip().lower()
            state = str(identity.get("State", "")).strip().lower()
            if lifecycle != "planning":
                raise ValueError("Technical Spike supports planning lifecycle only")
            if str(handoff["implementation_plan"]).strip() != (
                "Not created; Technical Spike produces spike_report.md"
            ):
                raise ValueError(
                    "Technical Spike implementation plan must be exactly "
                    "Not created; Technical Spike produces spike_report.md"
                )
            if state not in {"blocked", "awaiting_input", "handoff", "completed"}:
                raise ValueError("Technical Spike state must be blocked, awaiting_input, handoff, or completed")
            if state != "completed" and str(identity.get("Workflow outcome", "")).strip().lower() == "completed":
                raise ValueError("Technical Spike non-completed state cannot have Workflow outcome completed")
            if state in {"handoff", "completed"}:
                if (
                    str(identity.get("Profile status", "")).strip().lower() != "executed"
                    or len({
                        str(identity.get(field, "")).strip().lower()
                        for field in ("Requested profile", "Activated profile", "Executed profile")
                    }) != 1
                ):
                    raise ValueError(
                        "Technical Spike handoff requires Profile status executed and matching profiles"
                    )
                missing_workers = _technical_spike_missing_workers(packet)
                if publishing:
                    missing_workers.discard("handoff")
                if missing_workers:
                    raise ValueError(
                        "Technical Spike handoff requires terminal results for: "
                        + ", ".join(sorted(missing_workers))
                    )
                worker_contract_errors = _technical_spike_worker_contract_errors(
                    packet, publishing=publishing,
                )
                if worker_contract_errors:
                    raise ValueError("\n".join(worker_contract_errors))
                context_worker = next(
                    (
                        row for row in packet.get("workers", [])
                        if isinstance(row, dict)
                        and str(row.get("Worker", "")).strip().lower() == "spike-context"
                    ),
                    None,
                )
                if not context_worker or "work_item_read" not in str(
                    context_worker.get("Tools", "")
                ).lower():
                    raise ValueError(
                        "Technical Spike handoff requires spike-context to record work_item_read"
                    )
                dispositions = TECHNICAL_SPIKE_DISPOSITIONS.get(primary_goal)
                if dispositions is None:
                    raise ValueError(
                        "Technical Spike Primary goal must be Execute technical spike or Review technical spike"
                    )
                result = str(handoff["workflow_result"]).strip()
                if result not in dispositions:
                    raise ValueError(
                        "Technical Spike handoff requires Workflow result exactly one of: "
                        + ", ".join(dispositions)
                    )
            if state == "completed":
                result = str(handoff["workflow_result"]).strip()
                expected_engineering = dispositions.get(result)
                if expected_engineering is None:
                    raise ValueError(
                        "Technical Spike completed run requires Workflow result exactly one of: "
                        + ", ".join(dispositions)
                    )
                if str(identity.get("Workflow outcome", "")).strip() != "completed":
                    raise ValueError("Technical Spike completed run requires Workflow outcome completed")
                if str(identity.get("Engineering outcome", "")).strip() != expected_engineering:
                    raise ValueError(
                        f"Technical Spike disposition {result} requires Engineering outcome {expected_engineering}"
                    )
    next_action = handoff.get("next_action", {})
    if not isinstance(next_action, dict):
        raise ValueError("packet.handoff.next_action must be an object")
    for field in ("owner", "action", "complete_when"):
        if not str(next_action.get(field, "")).strip():
            raise ValueError(f"packet.handoff.next_action.{field} must be a non-empty string")
    established = handoff.get("established", [])
    if not established:
        raise ValueError("packet.handoff.established must contain at least one human-readable finding")
    for index, item in enumerate(established):
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"packet.handoff.established[{index}] must be a non-empty string")
        if "\n" in item:
            raise ValueError(
                f"packet.handoff.established[{index}] must be one human-readable sentence, not a multiline block"
            )
        if re.fullmatch(r"[A-Z]+-\d+", item.strip()):
            raise ValueError(
                f"packet.handoff.established[{index}] received internal ID {item!r}; "
                "expected a human-readable finding"
            )
    for index, item in enumerate(handoff.get("best_current_explanations", [])):
        if not isinstance(item, (str, dict)):
            raise ValueError(
                f"packet.handoff.best_current_explanations[{index}] must be text or a structured explanation"
            )
    artifacts = handoff.get("artifacts", [])
    if not artifacts:
        raise ValueError("packet.handoff.artifacts must contain at least one artifact")
    for index, item in enumerate(artifacts):
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"packet.handoff.artifacts[{index}] must be a non-empty path or Markdown link")


def _validate_pre_release_state(packet: dict[str, object]) -> None:
    identity = packet.get("identity", {})
    if not isinstance(identity, dict):
        return
    playbook = str(identity.get("Playbook / version", "")).split(" / ", 1)[0].lower()
    playbook = playbook.replace(" ", "_")
    if "techops_issue_remediation" in playbook and identity.get("Lifecycle") == "planning":
        if identity.get("State") not in {"ready_for_implementation", "awaiting_input", "blocked"}:
            raise ValueError("TechOps planning State must be ready_for_implementation, awaiting_input, or blocked; "
                             "received=" + str(identity.get("State")) + "; return to Documenter before pre-release")
        if identity.get("Workflow outcome") not in {"completed", "blocked"}:
            raise ValueError("TechOps planning Workflow outcome must be completed or blocked; received="
                             + str(identity.get("Workflow outcome")))
    if "technical_spike" in playbook and str(identity.get("State", "")).strip().lower() == "completed":
        raise ValueError("Technical Spike pre-release packet must keep State handoff until finalizer succeeds")
    if ("feature_delivery" in playbook and identity.get("Lifecycle") == "remediation"
            and identity.get("State") == "completed"):
        raise ValueError("Feature Delivery remediation pre-release must keep State handoff until finalizer succeeds")


def _reconcile_runtime_state(packet: dict[str, object], closure: list[dict[str, object]]) -> None:
    packet["runtime_closure"] = closure
    # Finalization owns this field; a second copy in identity can contradict publication.
    packet.get("identity", {}).pop("Finalization schema", None)
    finalization = packet.get("finalization")
    closed = _runtime_closed(closure)
    blocked_snapshot = (
        str(packet.get("identity", {}).get("State", "")).lower() == "blocked"
        and bool(closure)
        and all(str(row.get("Runtime status", "")).lower() == "blocked" for row in closure)
    )
    if blocked_snapshot:
        if isinstance(finalization, dict):
            finalization["Finalization schema"] = "Passed for blocked work record"
        for row in packet.get("durable_artifacts", []):
            name = Path(str(row.get("Path", ""))).name
            if name == "work_record.md":
                row["Status"] = "Blocked snapshot"
            elif name == "runtime_closure.json":
                row["Status"] = "Unverified"
    if closed or blocked_snapshot:
        handoff = packet.get("handoff", {})
        execution = re.sub(
            r"(?:awaiting|pending)\s+(?:Coordinator\s+)?packet validation"
            r"(?:\s+and\s+(?:packaged\s+)?finalization)?|"
            r"(?:awaiting|pending)\s+(?:packaged\s+)?finalization",
            "finalization validation passed", str(handoff.get("execution", "")), flags=re.IGNORECASE,
        )
        handoff["execution"] = execution
    if not closed:
        return
    identity = packet.get("identity", {})
    if (Path(str(identity.get("Playbook / version", "")).split(" / ", 1)[0]).stem == "feature_delivery"
            and identity.get("Lifecycle") == "remediation" and identity.get("State") == "handoff"):
        if any("context-unverified" in str(row.get("Uncertainties / blockers", ""))
               for row in packet.get("worker_results", [])):
            raise ValueError("feature_delivery_context_unverified_prevents_completion")
        identity.update({"State": "completed", "Workflow outcome": "completed"})
    runtime_status = "Released" if all(
        str(row.get("Runtime status", "")).lower() == "released" for row in closure
    ) else "Terminal"
    if isinstance(finalization, dict):
        reconciliation = str(finalization.get("Final reconciliation", "")).lower()
        stale = any(token in reconciliation for token in ("pending", "unknown", "in progress"))
        stale = stale or ("active" in reconciliation and "no active" not in reconciliation)
        if stale and "failed" not in reconciliation:
            finalization["Final reconciliation"] = (
                "Passed; runtime closure released with no active handles" if runtime_status == "Released"
                else "Passed; runtime closure terminal with no active turns"
            )
        finalization["Finalization schema"] = "Passed"
    if runtime_status == "Terminal" and isinstance(finalization, dict):
        finalization["Final reconciliation"] = re.sub(
            r"runtime(?: closure)? released", "runtime closure terminal",
            str(finalization.get("Final reconciliation", "")), flags=re.IGNORECASE,
        )
    for row in packet.get("durable_artifacts", []):
        if not isinstance(row, dict):
            continue
        artifact_name = re.sub(r"[_-]+", " ", str(row.get("Artifact", "")).lower())
        if "runtime closure" in artifact_name:
            row["Status"] = runtime_status
    for row in packet.get("worker_results", []):
        if not isinstance(row, dict):
            continue
        blockers = str(row.get("Uncertainties / blockers", ""))
        if re.fullmatch(r"\s*runtime closure pending(?: coordinator receipt)?\s*", blockers, re.IGNORECASE):
            row["Uncertainties / blockers"] = "None"
    for row in packet.get("synchronization", []):
        if not isinstance(row, dict):
            continue
        barrier = str(row.get("Barrier status", "")).lower()
        stale = any(token in barrier for token in ("pending", "unknown", "in progress"))
        stale = stale or ("active" in barrier and "no active" not in barrier)
        if stale and "failed" not in barrier:
            row["Barrier status"] = f"Passed; runtime closure {runtime_status.lower()}"
        elif runtime_status == "Terminal":
            row["Barrier status"] = re.sub(
                r"runtime closure released", "runtime closure terminal", str(row.get("Barrier status", "")),
                flags=re.IGNORECASE,
            )
    handoff = packet.get("handoff")
    if isinstance(handoff, dict):
        execution = str(handoff.get("execution", ""))
        execution = re.sub(
            r"state(?:\s*:\s*|\s+)(?:remains\s+)?handoff(?:\s+pending packaged finalizer)?",
            "finalization validation passed",
            execution,
            flags=re.IGNORECASE,
        )
        execution = re.sub(
            r"workflow remains\s+(?:in_progress|handoff)(?:\s+pending(?:\s+packaged)?\s+finalizer)?",
            "terminal bookkeeping finalized",
            execution,
            flags=re.IGNORECASE,
        )
        execution = re.sub(
            r"pre-release and terminal release not run",
            "pre-release validation and terminal finalization passed",
            execution,
            flags=re.IGNORECASE,
        )
        if str(packet.get("identity", {}).get("State", "")).strip().lower() == "completed":
            execution = re.sub(
                r"workflow\s+outcome\s*:\s*(?:incomplete|in_progress|handoff|pending|blocked|unknown)",
                "workflow outcome: completed",
                execution,
                flags=re.IGNORECASE,
            )
        execution = re.sub(
            r"(?:pending(?:\s+(?:packaged\s+|Coordinator\s+)?finalizer)|"
            r"(?:packaged\s+|Coordinator\s+)?finalizer\s+pending)",
            "finalization validation passed",
            execution,
            flags=re.IGNORECASE,
        )
        execution = re.sub(
            r"runtime\s+(?:closure\s+is\s+)?(?:pending/unknown|pending|unknown|active|in progress|not released)(?:\s+Coordinator)?",
            "runtime released",
            execution,
            flags=re.IGNORECASE,
        )
        if runtime_status == "Terminal":
            execution = re.sub(r"runtime(?: closure)? released", "runtime terminal", execution, flags=re.IGNORECASE)
        handoff["execution"] = execution
        next_action = handoff.get("next_action")
        if isinstance(next_action, dict):
            next_action["action"] = re.sub(
                r"^Run pre-release finalizer, create (?:the )?runtime closure receipt, and\s+",
                "",
                str(next_action.get("action", "")),
                flags=re.IGNORECASE,
            )
            next_action["complete_when"] = re.sub(
                r"^Final reconciliation and finalization schema are no longer Pending and\s+",
                "",
                str(next_action.get("complete_when", "")),
                flags=re.IGNORECASE,
            )




def _finalization_status(packet_path: Path) -> tuple[Path, dict[str, object]]:
    path = packet_path.parent / FINALIZATION_STATUS_FILENAME
    if not path.is_file():
        return path, {}
    try:
        value = json.loads(path.read_text())
        return path, value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return path, {}


def _record_pre_release(
    packet_path: Path, status: str, errors: list[str], previous: dict[str, object],
) -> dict[str, object]:
    path = packet_path.parent / FINALIZATION_STATUS_FILENAME
    now = datetime.now(timezone.utc)
    attempts = int(previous.get("attempt_count", 0)) + (status == "failed")
    first = previous.get("first_attempt_at") or now.isoformat().replace("+00:00", "Z")
    value = {
        "schema_version": 1,
        "status": status,
        "attempt_count": attempts,
        "correction_allowed": status == "failed" and attempts == 1,
        "first_attempt_at": first,
        "last_attempt_at": now.isoformat().replace("+00:00", "Z"),
        "shutdown_deadline": (
            (now + timedelta(minutes=2)).isoformat().replace("+00:00", "Z")
            if status == "failed" and attempts >= 2 else None
        ),
        "errors": errors,
        "historical_errors": list(dict.fromkeys(previous.get("historical_errors", []) + previous.get("errors", []))),
    }
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    return value


def _record_terminal_failure(
    packet_path: Path, errors: list[str], previous: dict[str, object],
) -> Path:
    path = packet_path.parent / FINALIZATION_STATUS_FILENAME
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    value = {
        "schema_version": 1,
        "status": "failed",
        "phase": "terminal",
        "terminal_failure": True,
        "attempt_count": int(previous.get("attempt_count", 0)),
        "correction_allowed": False,
        "first_attempt_at": previous.get("first_attempt_at") or now,
        "last_attempt_at": now,
        "shutdown_deadline": previous.get("shutdown_deadline"),
        "errors": errors,
        "historical_errors": list(dict.fromkeys(previous.get("historical_errors", []) + previous.get("errors", []))),
    }
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    return path


def _resolved_run_budget_status(value: dict[str, object]) -> str:
    if value.get("status") in {
        "exhausted_with_useful_result",
        "stopped_by_indispensable_evidence",
        "exceeded_during_finalization",
    }:
        return str(value["status"])
    deadline = datetime.fromisoformat(str(value["deadline_at"]).replace("Z", "+00:00"))
    return "within_budget" if datetime.now(timezone.utc) <= deadline else "exceeded_during_finalization"


def _update_run_budget(packet_path: Path) -> str | None:
    path = packet_path.parent / "run_budget.json"
    if not path.is_file():
        return None
    value = json.loads(path.read_text())
    value["status"] = _resolved_run_budget_status(value)
    value["last_checked_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    return str(value["status"])


def _sync_spike_report_budget(
    packet_path: Path, packet: dict[str, object], status: str | None,
    updated_at: str | None = None,
    report_path: Path | None = None,
) -> None:
    if not status and not updated_at:
        return
    identity = packet.get("identity", {})
    playbook = Path(str(identity.get("Playbook / version", "")).split(" / ", 1)[0]).stem
    if playbook != "technical_spike":
        return
    report = report_path or packet_path.parent / "spike_report.md"
    if not report.is_file():
        return
    original = report.read_text()
    updated = original
    if status:
        updated, _ = re.subn(
            r"^\| Budget status \|[^|]*\|$",
            f"| Budget status | {status} |",
            updated,
            flags=re.MULTILINE,
        )
    if updated_at:
        updated, _ = re.subn(
            r"^last_updated:\s*\S+\s*$",
            f"last_updated: {updated_at}",
            updated,
            flags=re.MULTILINE,
        )
        updated, _ = re.subn(
            r"^\| Last updated \|[^|]*\|$",
            f"| Last updated | {updated_at} |",
            updated,
            flags=re.MULTILINE,
        )
    run_budget = packet_path.parent / "run_budget.json"
    if run_budget.is_file():
        try:
            timebox = json.loads(run_budget.read_text()).get("timebox_minutes")
        except (OSError, json.JSONDecodeError):
            timebox = None
        if isinstance(timebox, (int, float)) and not isinstance(timebox, bool) and timebox > 0:
            updated = re.sub(
                r"^(\| Timebox or evidence budget \|)([^|]*)(\|)$",
                lambda match: (
                    f"{match.group(1)} {match.group(2).strip()}; {timebox:g} minutes {match.group(3)}"
                    if not re.search(r"\b\d+\s*(?:minutes?|mins?)\b", match.group(2), re.IGNORECASE)
                    else match.group(0)
                ),
                updated,
                flags=re.MULTILINE,
            )
    if updated != original:
        report.write_text(updated)


def _technical_spike_report_errors(
    packet_path: Path, packet: dict[str, object], budget_status: str | None,
    report_path: Path | None = None,
) -> list[str]:
    identity = packet.get("identity", {})
    selection = packet.get("playbook_selection", {})
    if not isinstance(identity, dict) or not isinstance(selection, dict):
        return []
    playbook = Path(str(identity.get("Playbook / version", "")).split(" / ", 1)[0]).stem
    state = str(identity.get("State", "")).strip().lower()
    if playbook != "technical_spike" or state not in {"handoff", "completed"}:
        return []
    report = report_path or packet_path.parent / "spike_report.md"
    if not report.is_file():
        return ["Technical Spike handoff requires spike_report.md"]
    manifest = packet.get("run_input_manifest")
    manifest_path = manifest.get("path") if isinstance(manifest, dict) else None
    if not manifest_path and isinstance(identity, dict):
        manifest_path = identity.get("Run input manifest")
    if manifest_path and str(manifest_path).strip().lower() not in {"none", "not applicable"}:
        manifest_path = Path(str(manifest_path))
        if not manifest_path.is_absolute():
            manifest_path = packet_path.parent / manifest_path
        manifest_path = manifest_path.resolve()
    else:
        manifest_path = None
    revisions = []
    for row in packet.get("repositories", []):
        if not isinstance(row, dict):
            continue
        revision = str(row.get("Full revision", "")).strip()
        if re.fullmatch(r"[0-9a-fA-F]{40}", revision):
            revisions.append(revision)
    return technical_spike_report_errors(
        report.read_text(), str(selection.get("Primary goal", "")),
        str(identity.get("Executed profile", "")), str(packet.get("handoff", {}).get("workflow_result", "")),
        budget_status, manifest_path, tuple(revisions),
    )


def publish_technical_spike_report(packet_path: Path, candidate_path: Path) -> None:
    checked(validate_package)
    packet_path = packet_path.resolve()
    candidate_path = candidate_path.resolve()
    if candidate_path.parent != packet_path.parent or candidate_path.name != "spike_report.candidate.md":
        raise ValueError("Technical Spike report candidate must be spike_report.candidate.md beside the packet")
    packet = json.loads(packet_path.read_text())
    shape_errors = _shape_errors(packet, json.loads(PACKET_TEMPLATE.read_text()), "packet")
    if shape_errors:
        raise ValueError("packet_schema_invalid: " + "; ".join(shape_errors))
    playbook = Path(str(packet["identity"]["Playbook / version"]).split(" / ", 1)[0]).stem
    if playbook != "technical_spike":
        raise ValueError("--publish-technical-spike-report requires a Technical Spike packet")
    errors = _technical_spike_report_artifact_errors(packet, packet_path)
    errors.extend(_technical_spike_candidate_reference_errors(packet))
    errors.extend(_technical_spike_packet_contract_errors(packet, pre_release=True))
    try:
        _validate_handoff(packet, publishing=True)
    except ValueError as error:
        errors.append(str(error))
    budget_status = None
    budget_path = packet_path.parent / "run_budget.json"
    if budget_path.is_file():
        budget_status = _resolved_run_budget_status(json.loads(budget_path.read_text()))
    _sync_spike_report_budget(
        packet_path, packet, budget_status, report_path=candidate_path,
    )
    errors.extend(_technical_spike_report_errors(
        packet_path, packet, budget_status, report_path=candidate_path,
    ))
    errors = list(dict.fromkeys(errors))
    if errors:
        raise ValueError("\n".join(errors))
    candidate_path.replace(packet_path.parent / "spike_report.md")
    print("Technical Spike artifact validation: passed")


def _prepare_blocked_runtime_snapshot(
    packet: dict[str, object], closure: dict[str, object], packet_path: Path,
    budget_status: str | None,
) -> None:
    identity = packet["identity"]
    playbook = Path(str(identity["Playbook / version"]).split(" / ", 1)[0]).stem
    assessment = (
        playbook == "feature_delivery"
        and str(packet["playbook_selection"]["Primary goal"]).strip().lower() == "specification assessment"
        and identity["State"] in {"awaiting_input", "ready_for_implementation"}
    )
    planning = (
        playbook == "feature_delivery"
        and str(packet["playbook_selection"]["Primary goal"]).strip().lower() == "implementation planning"
        and identity["State"] == "ready_for_implementation"
        and identity["Engineering outcome"] == "plan_only"
    )
    remediation = (playbook == "feature_delivery" and identity.get("Lifecycle") == "remediation"
                   and identity["State"] in {"handoff", "blocked", "awaiting_input"})
    techops_workers = {"issue-evidence", "failure-path", "fix-design", "handoff"}
    if identity.get("Executed profile") == "deep":
        techops_workers.update({"repository-integration", "planning-review"})
    techops_completed = {
        row.get("Worker") for row in packet.get("worker_results", []) if row.get("Outcome") == "complete"
    }
    techops_planning = (
        playbook == "techops_issue_remediation"
        and identity.get("Lifecycle") == "planning"
        and identity["State"] == "ready_for_implementation"
        and identity["Engineering outcome"] == "plan_only"
        and techops_workers <= techops_completed
        and all(row.get("Outcome") in {"complete", "not_applicable"} for row in packet.get("worker_results", []))
        and (packet_path.parent / "implementation_plan.md").is_file()
    )
    if not ((playbook == "technical_spike" and identity["State"] == "handoff")
            or assessment or planning or remediation or techops_planning):
        raise ValueError("blocked runtime snapshot requires a supported planning or remediation packet")
    rows = closure["runtime_closure"]
    if not rows or any(
        row["Receipt owner"] != "Coordinator"
        or str(row["Runtime status"]).strip().lower() != "blocked"
        or NO_ACTIVE_HANDLES.fullmatch(str(row["Remaining active handles"]).strip())
        or "worker_runtime_release_unavailable" not in str(row["Closure evidence or blocker"]).lower()
        for row in rows
    ):
        raise ValueError(
            "blocked runtime snapshot requires a Coordinator-owned receipt with Runtime status Blocked, "
            "worker_runtime_release_unavailable in Closure evidence or blocker, and nonzero or unknown active handles"
        )
    if assessment or planning or remediation:
        errors = _feature_delivery_packet_contract_errors(packet)
        errors.extend(_feature_delivery_asset_contract_errors(packet))
    elif techops_planning:
        errors = []  # Shared shape, handoff, and work-record validators apply below.
    else:
        errors = _technical_spike_packet_contract_errors(packet, pre_release=True)
        errors.extend(_technical_spike_report_errors(packet_path, packet, budget_status))
    try:
        # Provenance is canonicalized below; validate its content after normalization.
        _validate_handoff(packet, check_provenance=False)
    except ValueError as error:
        errors.append(str(error))
    if errors:
        raise ValueError("\n".join(dict.fromkeys(errors)))
    if assessment or planning or remediation or techops_planning:
        if assessment:
            expected_results = FEATURE_ASSESSMENT_DISPOSITIONS[identity["State"]]
            if str(packet["handoff"]["workflow_result"]).strip() not in expected_results:
                raise ValueError("Feature Delivery assessment result does not match its readiness state")
        identity.update({"State": "blocked", "Workflow outcome": "blocked"})
    else:
        primary_goal = str(packet["playbook_selection"]["Primary goal"]).strip().lower()
        result = str(packet["handoff"]["workflow_result"]).strip()
        identity.update({
            "State": "blocked", "Workflow outcome": "blocked",
            "Engineering outcome": TECHNICAL_SPIKE_DISPOSITIONS[primary_goal][result],
        })
    packet["finalization"].update({
        "Final reconciliation": "Blocked; provider runtime release unverified",
        "Finalization schema": "Passed for blocked work record",
    })
    execution = re.sub(
        r"(?i)(?:state remains handoff|workflow remains in_progress)[^;.]*",
        "", str(packet["handoff"]["execution"]),
    ).rstrip(" .;")
    packet["handoff"]["execution"] = (
        execution + "; provider release unavailable; workflow blocked pending provider receipt"
    )
    for artifact in packet["durable_artifacts"]:
        name = Path(str(artifact.get("Path", ""))).name
        if name == "work_record.md":
            artifact["Status"] = "Blocked snapshot"
        elif name == "runtime_closure.json":
            artifact["Status"] = "Unverified"


def _blocked_snapshot_label(packet: dict[str, object]) -> str:
    name = Path(str(packet['identity']['Playbook / version']).split(' / ', 1)[0]).stem
    if name == "technical_spike":
        return "Technical Spike"
    if name == "techops_issue_remediation":
        return "TechOps planning"
    goal = str(packet["playbook_selection"]["Primary goal"]).strip().lower()
    if packet["identity"].get("Lifecycle") == "remediation":
        return "Feature Delivery remediation"
    return "Feature Delivery assessment" if goal == "specification assessment" else "Feature Delivery implementation planning"


def finalize(
    packet_path: Path,
    closure_path: Path,
    record_path: Path,
    *,
    pre_release: bool = False,
    check_only: bool = False,
    blocked_runtime_snapshot: bool = False,
    coordinator_model_effort: str | None = None,
    framework_revision: str | None = None,
    framework_status: str | None = None,
) -> None:
    package_errors = prepared_package_errors(packet_path.parent) if (packet_path.parent / "role_bindings.json").is_file() else []
    if package_errors:
        raise ValueError(";".join(package_errors))
    status_path, previous_status = _finalization_status(packet_path)
    pre_release = pre_release or check_only
    if pre_release and not check_only and previous_status.get("status") == "failed" and int(
        previous_status.get("attempt_count", 0)
    ) >= 2:
        raise ValueError(
            f"finalization_contract_failure:correction_limit_reached;receipt={status_path}"
        )
    packet = json.loads(packet_path.read_text())
    closure = json.loads(closure_path.read_text())
    if not isinstance(closure, dict) or not isinstance(closure.get("runtime_closure"), list) or any(
            not isinstance(row, dict) for row in closure["runtime_closure"]):
        raise ValueError("runtime_closure_invalid: expected runtime_closure rows")
    budget_status = _update_run_budget(packet_path)
    errors: list[str] = []
    packet_ready = False
    supplied_identity = (coordinator_model_effort, framework_revision, framework_status)
    if any(supplied_identity) and not all(supplied_identity):
        errors.append(
            "coordinator_model_effort, framework_revision, and framework_status must be supplied together"
        )
    elif all(supplied_identity):
        packet["identity"]["Coordinator model/effort"] = coordinator_model_effort
        packet["identity"]["Framework commit / status"] = (
            f"{framework_revision} / {framework_status.title()}"
        )
    if not errors:
        try:
            _validate_shapes(packet, closure)
            if pre_release:
                _validate_pre_release_state(packet)
            if blocked_runtime_snapshot:
                _prepare_blocked_runtime_snapshot(packet, closure, packet_path, budget_status)
            errors.extend(_technical_spike_packet_contract_errors(packet, pre_release=pre_release))
            _normalize_packet(packet, closure, packet_path, budget_status)
            _sync_spike_report_budget(packet_path, packet, budget_status)
            packet_ready = True
        except (KeyError, TypeError, ValueError) as error:
            errors.append(str(error))
    if packet_ready:
        errors.extend(_technical_spike_packet_contract_errors(packet, pre_release=pre_release))
        errors.extend(_feature_delivery_packet_contract_errors(packet))
        errors.extend(_feature_delivery_asset_contract_errors(packet))
        errors.extend(_feature_assessment_reference_errors(packet))
        errors.extend(_techops_planning_contract_errors(packet, packet_path))
        errors.extend(_technical_spike_report_errors(packet_path, packet, budget_status))
        try:
            _validate_handoff(packet)
        except ValueError as error:
            errors.append(str(error))
        if not pre_release:
            errors.extend(_planning_runtime_closure_errors(packet, closure["runtime_closure"]))
            terminal_handles = [handle.strip() for row in closure["runtime_closure"]
                                if str(row.get("Runtime status", "")).lower() == "terminal"
                                for handle in re.split(r",|;", str(row.get("Completed worker handles", "")))]
            if terminal_handles:
                errors.extend(terminal_observation_errors(closure.get("terminal_observations"), terminal_handles, require_completed=False))
            # Both workflows use the same two-phase packet protocol and native status reads.
            if terminal_handles and Path(str(packet["identity"]["Playbook / version"]).split(" / ", 1)[0]).stem in {"techops_issue_remediation", "feature_delivery"}:
                try:
                    pre_release_receipt = json.loads((packet_path.parent / "pre_release_check.json").read_text())
                    if not isinstance(pre_release_receipt, dict):
                        raise ValueError
                    if (pre_release_receipt.get("status") != "passed" or
                            pre_release_receipt.get("packet_sha256") != hashlib.sha256(packet_path.read_bytes()).hexdigest()):
                        raise ValueError
                    pre_release_at = pre_release_receipt["validated_at"]
                    pre_release_time = datetime.fromisoformat(str(pre_release_at).replace("Z", "+00:00"))
                    if pre_release_time.tzinfo is None:
                        raise ValueError
                except (OSError, ValueError, KeyError, TypeError):
                    errors.append("terminal_closure_requires_current_passed_pre_release")
                    pre_release_at = None
                if pre_release_at and isinstance(closure.get("terminal_observations"), list):
                    for row in closure.get("terminal_observations", []):
                        try:
                            if datetime.fromisoformat(str(row["Observed at"]).replace("Z", "+00:00")) < pre_release_time:
                                errors.append("terminal_observation_predates_pre_release")
                        except (KeyError, ValueError, TypeError):
                            pass  # The shared observation validator reports malformed timestamps.
        try:
            _reconcile_runtime_state(packet, closure["runtime_closure"])
            if (packet["identity"].get("Lifecycle") == "remediation"
                    and packet["identity"].get("State") == "completed"):
                errors.extend(_feature_delivery_packet_contract_errors(packet))
        except (KeyError, TypeError, ValueError) as error:
            errors.append(str(error))
        if not pre_release and not errors:
            finalized_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            if isinstance(packet.get("work_item"), dict):
                packet["work_item"]["Last Updated"] = finalized_at
            _sync_spike_report_budget(packet_path, packet, None, updated_at=finalized_at)
    if packet_ready:
        try:
            packet["runtime_receipt"] = str(closure_path.resolve().relative_to(record_path.parent.resolve()))
            rendered = render_compact(packet)
        except (KeyError, TypeError, ValueError) as error:
            errors.append(str(error))
            rendered = ""
    else:
        rendered = ""
    record_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot = record_path.parent / snapshot_name(packet) if rendered else None
    snapshot_existed = snapshot.is_file() if snapshot else False
    published = False
    if snapshot:
        content = snapshot_bytes(packet)
        if snapshot.is_symlink() or (snapshot_existed and snapshot.read_bytes() != content):
            raise ValueError("existing workflow-state snapshot is not an intact regular file")
        if not snapshot_existed:
            with snapshot.open("xb") as handle:
                handle.write(content)
    with tempfile.NamedTemporaryFile("w", dir=record_path.parent, suffix=".md", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(rendered)
    try:
        result = None
        if rendered:
            try:
                checked(validate_package)
                result = record_validation_output(temporary, allow_unreleased=pre_release)
            except ValueError as error:
                errors.append(str(error))
        errors = list(dict.fromkeys(errors))
        if errors:
            if check_only:
                raise ValueError("packet_precheck_failed:" + "\n".join(errors))
            if pre_release:
                status = _record_pre_release(packet_path, "failed", errors, previous_status)
                prefix = "finalization_contract_failure:" if status["attempt_count"] >= 2 else ""
                raise ValueError(prefix + "\n".join(errors) + f"\nreceipt={status_path}")
            terminal_status = _record_terminal_failure(packet_path, errors, previous_status)
            raise ValueError("\n".join(errors) + f"\nreceipt={terminal_status}")
        if pre_release and not check_only:
            (packet_path.parent / "pre_release_check.json").write_text(json.dumps({
                "status": "passed", "packet_sha256": hashlib.sha256(packet_path.read_bytes()).hexdigest(),
                "validated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }, indent=2) + "\n")
        if not check_only:
            status_path.unlink(missing_ok=True)
        if not pre_release:
            temporary.replace(record_path)
            published = True
        if result:
            if not pre_release and not check_only:
                register_pending_delivery(packet_path, result.split("Workflow-framework validation: passed\n", 1)[1])
            # Keep the validator's canonical success line first on every publication route.
            print(result, end="")
            if blocked_runtime_snapshot:
                label = _blocked_snapshot_label(packet)
                print(f"{label} blocked work record: saved; runtime release unverified")
    finally:
        temporary.unlink(missing_ok=True)
        if snapshot and not snapshot_existed and not published:
            snapshot.unlink(missing_ok=True)


def prepare_analytical_failure(
    packet_path: Path,
    closure_path: Path,
    record_path: Path,
    *,
    reason: str,
    failure_stage: str,
    completed_handles: list[str],
    coordinator_model_effort: str,
    framework_revision: str,
    framework_status: str,
    evidence_artifact: Path | None,
) -> None:
    stage = ANALYTICAL_FAILURE_STAGES[failure_stage]
    packet = json.loads(packet_path.read_text())
    artifact_root = packet_path.parent
    execution_repository = artifact_root.parent.parent
    manifest_path = artifact_root / "role_bindings.json"
    manifest = json.loads(manifest_path.read_text())
    if not closure_path.is_file():
        raise ValueError("analytical_failure_runtime_closure_unverified: save a verified Terminal or release receipt; "
                         "otherwise use --workflow-failure without inventing closure")
    closure = json.loads(closure_path.read_text())
    if not isinstance(closure, dict):
        raise ValueError("analytical_failure_runtime_closure_invalid: expected an object")
    closure_rows = closure.get("runtime_closure", [])
    if not isinstance(closure_rows, list) or any(not isinstance(row, dict) for row in closure_rows):
        raise ValueError("analytical_failure_runtime_closure_invalid: expected runtime_closure rows")
    if not _runtime_closed(closure_rows):
        raise ValueError("analytical_failure_runtime_closure_unverified: use --workflow-failure")
    recorded_handles = {handle.strip() for row in closure_rows for handle in
                        re.split(r"[,;]", str(row.get("Completed worker handles", "")))}
    if not set(completed_handles) <= recorded_handles:
        raise ValueError("analytical_failure_closure_handle_mismatch: retain the exact provider handles")
    if any(str(row.get("Runtime status", "")).lower() == "terminal" for row in closure_rows):
        errors = terminal_observation_errors(closure.get("terminal_observations", []), sorted(recorded_handles), require_completed=False)
        errors.extend(dispatch_audit_errors({"runtime_audits": closure.get("terminal_observations", [])}, packet_path, closure_only=True))
        if errors:
            raise ValueError(";".join(errors))
    closure_state = "terminal" if any(str(row.get("Runtime status", "")).lower() == "terminal"
                                      for row in closure_rows) else "released"
    prior_handoff = json.loads(json.dumps(packet.get("handoff", {})))
    binding = manifest["bindings"][stage["binding"]]
    artifact_created = evidence_artifact is not None and evidence_artifact.is_file()
    if failure_stage != "evidence_topology" and not artifact_created:
        raise ValueError(f"evidence_artifact_required:{failure_stage}")
    evidence_source = str(evidence_artifact) if artifact_created else "Worker runtime receipt"
    failure_kind = "contract" if artifact_created else "runtime"
    if artifact_created:
        implementation_plan = stage["implementation_plan"]
        established = stage["established"]
        claim = stage["claim"]
        action = stage["action"]
        complete_when = stage["complete_when"]
        unique_contribution = f"Returned {stage['role']} output before terminal contract validation failed"
    else:
        implementation_plan = "omitted; Evidence Topology produced no normalized evidence artifact"
        established = "Evidence Topology ended without producing its assigned normalized evidence artifact."
        claim = "Fix Design cannot start because normalized evidence was not produced."
        action = "Correct the worker activation or runtime failure, then retry Evidence Topology."
        complete_when = "Evidence Topology produces contract-valid normalized evidence."
        unique_contribution = "No contract-valid artifact was produced before the terminal runtime failure"
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    work_item = str(packet["work_item"]["ID"])
    git_revision = subprocess.run(
        ["git", "-C", str(execution_repository), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    git_branch = subprocess.run(
        ["git", "-C", str(execution_repository), "branch", "--show-current"],
        capture_output=True, text=True, check=True,
    ).stdout.strip() or "detached"
    git_status = subprocess.run(
        ["git", "-C", str(execution_repository), "status", "--porcelain"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    packet["work_item"].update({"Title": work_item, "Last Updated": now})
    packet["playbook_selection"].update({
        "Primary evidence": (
            "Current Sentry occurrence and normalized evidence"
            if artifact_created else "Current Sentry occurrence and provider runtime receipt"
        ),
        "Primary goal": "Evidence-backed Sentry remediation planning",
        "Selected playbook": "sentry_issue_remediation",
        "Closest alternative": "feature_delivery",
        "Why this playbook": "The run investigates a reported Sentry occurrence before implementation.",
    })
    if not _material_rows(packet.get("inputs"), "Input ID"):
        packet["inputs"] = [{
            "Input ID": "IN-001", "Input or artifact": "Current Sentry occurrence",
            "Source or path": evidence_source, "Authority": "Current-run evidence",
            "Status": "Consumed" if artifact_created else "Observed",
        }]
    if not _material_rows(packet.get("repositories"), "Repository role"):
        packet["repositories"] = [{
            "Repository role": "Execution", "Declared path": str(execution_repository),
            "Resolved path": str(execution_repository), "Branch / detached": git_branch,
            "Full revision": git_revision, "Clean status": "Dirty" if git_status else "Clean",
            "User-selected ref": "Current checkout", "Release mapping": "Unknown",
            "Evidence eligibility": "Accepted for current-run repository evidence",
        }]
    prompt_identity = str(packet["identity"]["Prompt template / revision / conformance"])
    if prompt_identity.endswith(" / pending"):
        prompt_identity = prompt_identity.removesuffix(" / pending") + " / pass"
    packet["identity"].update({
        "Framework commit / status": f"{framework_revision} / {framework_status.title()}",
        "Prompt template / revision / conformance": prompt_identity,
        "Coordinator model/effort": coordinator_model_effort,
        "Requested profile": "standard", "Activated profile": "standard", "Executed profile": "standard",
        "Profile status": "blocked", "Lifecycle": "planning", "State": "blocked",
        "Engineering state": "unknown", "Workflow outcome": "blocked", "Engineering outcome": "blocked",
    })
    packet["finalization"].update({
        "Concurrent-run decision": "Current isolated run", "Active related run or work item": "None",
        "Related-run check": "Completed during initialization", "Durable artifact root": str(artifact_root),
        "Final reconciliation": (
            f"Passed; analytical_{failure_kind}_failure at {failure_stage} preserved and runtime {closure_state}"
        ),
        "Finalization schema": "Passed",
    })
    artifacts = _material_rows(packet.get("durable_artifacts"), "Artifact")
    failure_artifacts = [
        {"Artifact": "Role bindings", "Path": str(manifest_path), "Status": "Created",
         "Purpose": "Exact worker bindings"},
        {"Artifact": "Finalization packet", "Path": str(packet_path), "Status": "Created",
         "Purpose": "Structured terminal input"},
        {"Artifact": "Runtime closure", "Path": str(closure_path), "Status": closure_state.title(),
         "Purpose": "Provider closure receipt"},
        {"Artifact": "Work record", "Path": str(record_path), "Status": "Created",
         "Purpose": "Authoritative terminal handoff"},
    ]
    if artifact_created:
        failure_artifacts.insert(0, {
            "Artifact": "Normalized evidence", "Path": str(evidence_artifact), "Status": "Preserved",
            "Purpose": "Current-run analytical evidence",
        })
    for artifact in failure_artifacts:
        _append_unique_artifact(artifacts, artifact)
    packet["durable_artifacts"] = artifacts
    configured = f"{binding['model']} / {binding['effort']}"
    normalized_handles = list(dict.fromkeys(completed_handles))
    worker_handle = ", ".join(normalized_handles) if normalized_handles else "None"
    workers = _material_rows(packet.get("workers"), "Worker")
    failed_worker = next(
        (row for row in workers if str(row.get("Worker", "")).strip() == stage["worker"]), None
    )
    if failed_worker:
        failed_worker["Outcome"] = "failed"
        failed_worker["Confidence"] = "High"
    else:
        workers.append({
            "Worker": stage["worker"], "Role": stage["role"], "Assigned inputs": "IN-001",
            "Mode": "investigation", "Depth": "standard", "Skills": "Bounded Sentry analysis",
            "Tools": "Mapped provider operations", "Capacity": "one worker", "Configured model/effort": configured,
            "Provider-observed model/effort": configured, "Usage": "Provider telemetry unavailable",
            "Depends on": "Coordinator initialization", "Outcome": "failed", "Confidence": "High",
        })
    packet["workers"] = workers
    synchronization = _material_rows(packet.get("synchronization"), "Stage")
    failure_synchronization = {
        "Stage": stage["validation_stage"], "Workers launched": stage["worker"],
        "Launch mode / exception": "Sequential Standard activation", "Worker outcomes": "failed",
        "Results summarized": "Yes", "Barrier status": f"Failed: {reason}",
    }
    existing_stage = next((row for row in synchronization if row.get("Stage") == stage["validation_stage"]), None)
    if existing_stage is not None:
        existing_stage.update(failure_synchronization)
    else:
        synchronization.append(failure_synchronization)
    packet["synchronization"] = synchronization
    worker_results = _material_rows(packet.get("worker_results"), "Worker")
    failed_result = next(
        (row for row in worker_results if str(row.get("Worker", "")).strip() == stage["worker"]), None
    )
    evidence_id, claim_id = f"E-FAIL-{failure_stage}", f"C-FAIL-{failure_stage}"
    result_row = {
        "Worker": stage["worker"], "Outcome": "failed", "Confidence": "High",
        "Unique contribution": unique_contribution,
        "Evidence / claim refs": f"{evidence_id} / {claim_id}", "Uncertainties / blockers": reason,
        "Actual model/effort": configured, "Usage/credits": "Provider telemetry unavailable",
    }
    if failed_result:
        failed_result.update(result_row)
    else:
        worker_results.append(result_row)
    packet["worker_results"] = worker_results
    failure_rows = {
    "evidence": ("Evidence ID", {
        "Evidence ID": evidence_id, "Source": evidence_source,
        "Summary": f"{stage['role']} failed its terminal {failure_kind}: {reason}", "Confidence": "High",
        "Uncertainty": "None", "Status": "Verified",
    }),
    "claims": ("Claim ID", {"Claim ID": claim_id, "Claim": claim,
        "Evidence refs": evidence_id, "Confidence": "High", "Uncertainty": "None", "Status": "Supported"}),
    "decisions": ("Decision ID", {"Decision ID": f"D-FAIL-{failure_stage}",
        "Decision": "Stop after the bounded analytical correction and preserve artifacts.",
        "Claim refs": claim_id, "Owner": "Coordinator", "Status": "Applied"}),
    "actions": ("Action ID", {"Action ID": f"A-FAIL-{failure_stage}", "Action": action,
        "Decision ref": f"D-FAIL-{failure_stage}", "Owner": "Framework maintainer", "Status": "Proposed"}),
    }
    for field, (key, row) in failure_rows.items():
        rows = _material_rows(packet.get(field), key)
        previous = next((value for value in rows if value[key] == row[key]), None)
        if previous is not None:
            previous.update(row)
        else:
            rows.append(row)
        packet[field] = rows
    contributions = list(prior_handoff.get("established", []))
    contributions.extend(str(row["Unique contribution"]) for row in worker_results
                         if row.get("Outcome") == "complete" and row.get("Unique contribution"))
    explanation = {"explanation": reason, "confidence": "high", "reason": (
        "The packaged validator reproduced the failure."
        if artifact_created else "The provider runtime receipt recorded the failure.")}
    explanations = list(prior_handoff.get("best_current_explanations", []))
    if explanation not in explanations:
        explanations.append(explanation)
    packet["handoff"] = {
        "workflow_result": f"Planning stopped on analytical {failure_kind} failure",
        "implementation_plan": implementation_plan,
        "established": list(dict.fromkeys(contributions + [established])),
        "best_current_explanations": explanations,
        "next_action": {"owner": "Framework maintainer", "action": action,
                        "complete_when": complete_when},
        "artifacts": list(dict.fromkeys(list(prior_handoff.get("artifacts", []))
                          + ([str(evidence_artifact)] if artifact_created else []) + [str(record_path)])),
        "execution": (
            f"standard/planning; finalization validation passed; analytical {failure_kind} failed; "
            f"workers incomplete; source changes none; runtime {closure_state}"
        ),
        "provenance": (
            f"plugin {packet['identity']['Plugin package / version']}; framework revision {framework_revision} "
            f"({framework_status.lower()}); playbook {packet['identity']['Playbook / version']}."
        ),
    }
    packet_path.write_text(json.dumps(packet, indent=2) + "\n")
    finalize(packet_path, closure_path, record_path)


def self_test() -> None:
    try:
        from self_check import run_self_check
    except ModuleNotFoundError:
        from scripts.self_check import run_self_check
    run_self_check("finalize_work_record", "self_test")


def collect_failure_closure(packet_path: Path, provider_session: Path | None = None,
                            parent_thread_id: str | None = None) -> str:
    """Retain provider closure even when analytical finalization cannot proceed."""
    root = packet_path.parent
    bindings_path = root / "role_bindings.json"
    if not bindings_path.is_file():
        return "unverified"
    bindings = json.loads(bindings_path.read_text())
    if bindings.get("playbook") not in {"techops_issue_remediation", "feature_delivery"}:
        return "unverified"
    ledger_path = Path(bindings.get("runtime_evidence", {}).get("ledger", root / "runtime_dispatches.json"))
    try:
        from worker_runtime_evidence import read_runtime_events, terminal_closure
        from provider_runtime import validate_prepared_provider_source
    except ModuleNotFoundError:
        from scripts.worker_runtime_evidence import read_runtime_events, terminal_closure
        from scripts.provider_runtime import validate_prepared_provider_source
    try:
        if ledger_path.resolve().parent != root.resolve():
            raise ValueError("runtime_dispatch_ledger_outside_current_run")
        if provider_session is None and not ledger_path.is_file() and bindings.get("parent_context"):
            parent = bindings["parent_context"]
            provider_session, parent_thread_id = Path(parent["provider_session"]), parent["parent_thread_id"]
        if provider_session is not None:
            if not parent_thread_id:
                raise ValueError("provider_parent_thread_id_required")
            validate_prepared_provider_source(bindings, provider_session, parent_thread_id,
                                              bindings["runtime_evidence"]["run_started_at"])
            current = read_runtime_events(provider_session, parent_thread_id,
                bindings["runtime_evidence"]["run_started_at"],
                tuple(Path(value) for value in bindings["runtime_evidence"].get("identity_sessions", [])))
        else:
            if not ledger_path.is_file():
                raise ValueError("runtime_dispatch_ledger_missing: supply current provider session and parent thread ID")
            saved = json.loads(ledger_path.read_text())
            validate_prepared_provider_source(bindings, Path(saved["provider_session"]), saved["parent_thread_id"],
                                              saved["run_started_at"])
            current = read_runtime_events(Path(saved["provider_session"]), saved["parent_thread_id"],
                saved["run_started_at"], tuple(Path(p) for p in saved.get("identity_sessions", [])))
        ledger_path.write_text(json.dumps(current, indent=2) + "\n")
        closure = terminal_closure(current)
        state = "terminal"
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        state = "unverified"
        if (root / "runtime_closure.json").exists():
            return state
        closure = {"runtime_closure": [{"Run or stage": "Current run", "Receipt owner": "Coordinator",
            "Completed worker handles": "Unknown", "Runtime status": "Blocked", "Remaining active handles": "Unknown",
            "Closure evidence or blocker": "Provider closure collection failed: " + str(error)}]}
    (root / "runtime_closure.json").write_text(json.dumps(closure, indent=2) + "\n")
    return state


def failure_handoff(packet_path: Path, reason: str) -> str:
    """Report saved work provisionally without publishing or certifying a terminal record."""
    packet_path = packet_path.resolve()
    try:
        packet = json.loads(packet_path.read_text())
    except (OSError, UnicodeError, json.JSONDecodeError):
        packet = {}
    if not isinstance(packet, dict):
        packet = {}
    identity = packet.get("identity", {})
    handoff = packet.get("handoff", {})
    identity = identity if isinstance(identity, dict) else {}
    handoff = handoff if isinstance(handoff, dict) else {}
    def value(key: str, fallback: str) -> str:
        item = handoff.get(key)
        return item.strip() if isinstance(item, str) and item.strip() else fallback
    def items(key: str) -> list[str]:
        entries = handoff.get(key, [])
        return [entry for entry in entries if isinstance(entry, str) and entry.strip()] if isinstance(entries, list) else []
    # Documenter may fail before populating handoff; preserve recorded analytical content.
    results = packet.get("worker_results", [])
    results = [row for row in results if isinstance(row, dict)] if isinstance(results, list) else []
    design = next((row for row in results if row.get("Worker") == "fix-design"), {})
    fallback_summary = str(design.get("Unique contribution", "")).strip() or (
        "No accepted worker result was recorded for this run."
        if not any(row.get("Outcome") == "complete" for row in results)
        else "Recorded worker findings are available; no consolidated work summary was recorded."
    )
    summary = value("workflow_result", fallback_summary)
    if re.sub(r"[_-]+", " ", summary.lower()) in TECHOPS_STATE_RESULT_TOKENS:
        summary = next(iter(items("established")), fallback_summary)
    established = ["Provisional saved findings follow; failed finalization has not validated these claims."] + items("established")
    root = packet_path.parent
    audits = packet.get("runtime_audits", [])
    audits = audits if isinstance(audits, list) else []
    traces = [Path(row["Trace path"]) for row in audits
              if isinstance(row, dict) and isinstance(row.get("Trace path"), str)]
    traces.extend(sorted(root.glob("*trace*.json")))
    for source in dict.fromkeys(traces):
        source = source if source.is_absolute() else root / source
        try:
            if source.resolve().parent != root.resolve():
                continue
            trace = json.loads(source.read_text())
            if not (root / "role_bindings.json").is_file():
                continue
            identity_errors = trace_identity_errors(trace, root, "sentry_current_state_investigator",
                                                    trace["spawn"]["provider_handle"], trace.get("thread_id"))
            dispatch_errors = dispatch_audit_errors({"runtime_audits": [trace.get("status_observation", {})]}, packet_path)
            if (trace.get("run_id") != identity.get("Run ID") or trace.get("audit", {}).get("status") != "passed"
                    or identity_errors or dispatch_errors or trace_errors(trace, require_freshness=True)):
                continue
            evidence = root / "normalized_evidence.md"
            if evidence.resolve().parent != root.resolve():
                continue
            checked(validate_normalized_evidence, evidence)
            facts = re.search(r"^#{1,6} Confirmed Facts\s*\n(.*?)(?=^#{1,6} |\Z)",
                              evidence.read_text(), re.M | re.S)
            if facts:
                established.extend("Provisional artifact statement (not verified worker output): " + line[2:] for line in facts[1].splitlines()
                                   if line.startswith("- ") and line[2:] not in established)
                if summary == fallback_summary:
                    summary = "Provisional evidence text is preserved; its attribution to the worker output is unverified."
                break
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue  # Unaccepted artifacts remain linked below without promoting their contents.
    if not items("established"):
        for row in results:
            contribution = row.get("Unique contribution")
            if isinstance(contribution, str) and contribution.strip():
                established.append("Recorded " + str(row.get("Worker", "worker")) + ": " + contribution)
            blockers = row.get("Uncertainties / blockers", [])
            if isinstance(blockers, list):
                established.extend("Recorded limitation: " + item for item in blockers
                                   if isinstance(item, str) and item.strip())
        for row in packet.get("claims", []) if isinstance(packet.get("claims"), list) else []:
            if isinstance(row, dict) and isinstance(row.get("Claim"), str) and row["Claim"].strip():
                established.append("Recorded claim " + str(row.get("Claim ID", "")) + ": " + row["Claim"]
                                   + "; confidence: " + str(row.get("Confidence", "Unknown"))
                                   + "; uncertainty: " + str(row.get("Uncertainty", "Unknown")))
        for row in packet.get("actions", []) if isinstance(packet.get("actions"), list) else []:
            if isinstance(row, dict) and isinstance(row.get("Action"), str) and row["Action"].strip():
                established.append("Recorded proposed action (not authorization): " + row["Action"]
                                   + "; owner: " + str(row.get("Owner", "Unknown")))
    next_action = handoff.get("next_action", {})
    if isinstance(next_action, dict):
        action = "; ".join(f"{key}: {next_action[key]}" for key in ("owner", "action", "complete_when")
                           if isinstance(next_action.get(key), str) and next_action[key].strip())
        if action:
            established.append("Recorded engineering next action (not implementation authorization): " + action)
    root = packet_path.parent
    artifacts = []
    saved_paths = []
    try:
        bindings = json.loads((root / "role_bindings.json").read_text())
        accepted = {row.get("Worker") for row in results if row.get("Outcome") == "complete"}
        missing = []
        for contract in bindings.get("worker_contracts", {}).values():
            worker = contract.get("worker_id") or contract.get("worker")
            if worker and worker not in accepted:
                missing.append(worker)
            for field in ("output", "result"):
                saved = Path(str(contract.get(field, "")))
                saved = saved if saved.is_absolute() else root / saved
                if saved.is_file() and saved.resolve().parent == root.resolve():
                    saved_paths.append(str(saved))
                    if worker not in accepted:
                        established.append("Unaccepted worker artifact retained for audit only: " + str(saved))
        if missing:
            established.append("Prepared workers without an accepted result: " + ", ".join(dict.fromkeys(missing)))
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    for saved in traces + [root / "runtime_closure.json"]:
        saved = saved if saved.is_absolute() else root / saved
        if saved.is_file() and saved.resolve().parent == root.resolve():
            saved_paths.append(str(saved))
    for saved in root.glob("*.rejected.*"):
        if saved.is_file() and saved.resolve().parent == root.resolve():
            saved_paths.append(str(saved))
            established.append("Rejected artifact retained for audit only: " + str(saved))
    for row in packet.get("durable_artifacts", []) if isinstance(packet.get("durable_artifacts"), list) else []:
        if isinstance(row, dict) and isinstance(row.get("Path"), str):
            saved = Path(row["Path"])
            saved = saved if saved.is_absolute() else root / saved
            try:
                if saved.resolve().parent == root.resolve() and saved.is_file():
                    saved_paths.append(str(saved))
            except (OSError, ValueError):
                pass
    for item in dict.fromkeys(items("artifacts") + saved_paths + [str(packet_path)]):
        try:
            artifacts.append(_artifact_link(item, root))
        except (OSError, ValueError):
            established.append("Unrenderable recorded artifact reference: " + repr(item))
    receipt = root / FINALIZATION_STATUS_FILENAME
    if receipt.is_file():
        artifacts.append(str(receipt))
    artifacts.append(str(root / "handoff_failure.md"))
    explanations = []
    recorded = handoff.get("best_current_explanations", [])
    for item in recorded if isinstance(recorded, list) else []:
        try:
            explanations.append(_explanation_text(item))
        except ValueError:
            explanations.append("Malformed recorded explanation (unverified): " + str(item))
    plan = root / "implementation_plan.md"
    plan_status = str(plan) if plan.is_file() else "Not created; resolve the recorded workflow failure and missing deliverables."
    provenance = "; ".join(str(identity[key]) for key in
                           ("Plugin package / version", "Framework commit / status", "Playbook / version")
                           if identity.get(key)) or "Not available"
    provisional = {
        "identity": {"State": "blocked", "Engineering state": "unknown", "Workflow outcome": "blocked",
                     "Engineering outcome": "blocked"},
        "runtime_closure": [], "finalization": {"Durable artifact root": str(root)},
        "handoff": {
            "workflow_result": "Finalization failed. Provisional work summary: " + summary,
            "implementation_plan": value("implementation_plan", plan_status),
            "established": established, "best_current_explanations": explanations,
            "next_action": {"owner": "Workflow Coordinator / framework maintainer",
                            "action": "Correct the recorded failure and reconcile fresh provider evidence within this run where permitted; "
                                      "then rerun finalization. A fresh investigation is not automatically required. " + reason,
                            "complete_when": "The packaged finalizer exits zero and emits its canonical validated handoff."},
            "artifacts": artifacts,
            "execution": "Terminal publication failed; reported work is provisional. Recorded engineering state: "
                         + str(identity.get("Engineering state") or "unknown")
                         + ". Recorded execution (unverified): " + value("execution", "Not available"),
            "provenance": "Recorded, not verified: " + value("provenance", provenance),
        },
    }
    _, receipt = _finalization_status(packet_path)
    if receipt.get("runtime_closure") == "terminal":
        try:
            closure = json.loads((root / "runtime_closure.json").read_text())["runtime_closure"]
            if _runtime_closed(closure):
                provisional["runtime_closure"] = closure
                provisional["handoff"]["execution"] += "; provider closure verified for every activated handle."
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            pass  # Failure reporting must remain available when the saved closure cannot be read.
    if receipt.get("validation_performed") is False:
        provisional["handoff"]["workflow_result"] = "Workflow stopped on a Coordinator-reported control failure. " + (
            "Provisional work summary: " + summary)
        provisional["handoff"]["execution"] = provisional["handoff"]["execution"].replace(
            "Terminal publication failed", "Validated terminal publication was not performed")
    heading = ("Workflow-framework handoff: failed; control failure reported by Coordinator\n\n"
               if receipt.get("validation_performed") is False else "Workflow-framework validation: failed\n\n")
    return heading + render_handoff(provisional).removeprefix("```text\n").removesuffix("```")


def register_pending_delivery(packet_path: Path, report: str) -> None:
    content = report.encode()
    root = packet_path.parent
    (root / "handoff_response.md").write_bytes(content)
    record = root / "work_record.md"
    receipt = {"status": "pending", "run_id": json.loads(packet_path.read_text()).get("identity", {}).get("Run ID", "Unavailable"),
               "canonical_sha256": hashlib.sha256(content).hexdigest(),
               "record_sha256": hashlib.sha256(record.read_bytes()).hexdigest() if record.is_file() else None,
               "scope": "Prepared-response verification is required; actual chat delivery is not observable by this CLI"}
    path = root / "handoff_delivery.json"
    if path.is_file():
        try:
            previous = json.loads(path.read_text())
        except ValueError:
            previous = {}
        previous = previous if isinstance(previous, dict) else {}
        if previous.get("status") == "verified" and all(previous.get(key) == receipt[key]
                for key in ("run_id", "canonical_sha256", "record_sha256")):
            return
    path.write_text(json.dumps(receipt, indent=2) + "\n")


def _save_failure_handoff(packet_path: Path, report: str) -> None:
    content = (report.rstrip("\n") + "\n").encode()
    (packet_path.parent / "handoff_failure.md").write_bytes(content)
    status_path, status = _finalization_status(packet_path)
    if status.get("status") == "failed":
        status["handoff_sha256"] = hashlib.sha256(content).hexdigest()
        status["handoff_packet_sha256"] = hashlib.sha256(packet_path.read_bytes()).hexdigest()
        status_path.write_text(json.dumps(status, indent=2) + "\n")
    register_pending_delivery(packet_path, content.decode())


def verify_presentation(canonical: bytes, proposed: bytes, prefix: bytes = b"", suffix: bytes = b"") -> None:
    """Keep canonical content exact while permitting explicitly recorded surrounding text."""
    expected = prefix + canonical + suffix
    if proposed.removesuffix(b"\n") != expected.removesuffix(b"\n"):
        raise ValueError("handoff_response_mismatch: preserve the canonical report and declared surrounding text exactly")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", type=Path)
    parser.add_argument("--closure", type=Path)
    parser.add_argument("--record", type=Path)
    parser.add_argument("--pre-release", action="store_true")
    parser.add_argument("--check-packet", action="store_true")
    parser.add_argument("--blocked-runtime-snapshot", action="store_true")
    parser.add_argument("--publish-technical-spike-report", type=Path)
    parser.add_argument("--workflow-failure")
    parser.add_argument("--provider-session", type=Path, help="Current parent record for workflow-failure closure collection")
    parser.add_argument("--parent-thread-id", help="Provider identity for the workflow-failure parent record")
    parser.add_argument("--analytical-failure")
    parser.add_argument("--analytical-failure-stage", choices=tuple(ANALYTICAL_FAILURE_STAGES))
    parser.add_argument("--completed-handle", action="append", default=[])
    parser.add_argument("--coordinator-model-effort")
    parser.add_argument("--framework-revision")
    parser.add_argument("--framework-status", choices=("clean", "dirty"))
    parser.add_argument("--evidence-artifact", type=Path)
    parser.add_argument("--verify-response", type=Path)
    parser.add_argument("--publish-response", type=Path, help="Verify and emit the prepared response without rewriting it")
    parser.add_argument("--presentation-prefix", type=Path, help="UTF-8 text required before the canonical report")
    parser.add_argument("--presentation-suffix", type=Path, help="UTF-8 text required after the canonical report")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if (args.provider_session or args.parent_thread_id) and not (
            args.workflow_failure and args.provider_session and args.parent_thread_id):
        parser.error("--provider-session and --parent-thread-id require each other and --workflow-failure")
    if args.publish_response:
        if args.verify_response:
            parser.error("publish-response and verify-response are separate modes")
        args.verify_response = args.publish_response
    if (args.presentation_prefix or args.presentation_suffix) and not args.verify_response:
        parser.error("presentation text requires --verify-response or --publish-response")
    if args.self_test:
        self_test()
        return 0
    if args.packet and (args.workflow_failure or args.verify_response):
        _, status = _finalization_status(args.packet.resolve())
        failure_report = args.workflow_failure or args.verify_response and status.get("status") == "failed"
        package_errors = prepared_package_errors(args.packet.resolve().parent, check_parent_context=not failure_report)
        if package_errors:
            if args.verify_response:
                (args.packet.resolve().parent / "handoff_delivery.json").unlink(missing_ok=True)
            print(json.dumps({"status": "blocked", "errors": package_errors}))
            return 2
    if args.verify_response:
        if not args.packet or any((args.workflow_failure, args.analytical_failure, args.pre_release,
                                   args.check_packet, args.blocked_runtime_snapshot, args.publish_technical_spike_report)):
            parser.error("--verify-response requires --packet and cannot be combined with another mode")
        try:
            packet_path = args.packet.resolve()
            _, status = _finalization_status(packet_path)
            if status.get("status") == "failed":
                source = packet_path.parent / "handoff_failure.md"
                if source.samefile(args.verify_response) and not args.publish_response:
                    raise ValueError("handoff_response_self_comparison: provide the actual proposed response file")
                canonical = source.read_bytes()
                if hashlib.sha256(canonical).hexdigest() != status.get("handoff_sha256"):
                    raise ValueError("handoff_canonical_content_changed: rerun the failure reporter")
                if hashlib.sha256(packet_path.read_bytes()).hexdigest() != status.get("handoff_packet_sha256"):
                    raise ValueError("handoff_packet_changed: rerun the failure reporter")
            else:
                record = args.record or packet_path.parent / "work_record.md"
                if record.resolve().parent != packet_path.parent:
                    raise ValueError("handoff_record_outside_current_run")
                expanded = expand_work_record(record.read_text(), packet_path.parent)
                recorded_id = re.search(r"^\| Run ID \| ([^|]+) \|$", expanded, re.M)
                current_id = json.loads(packet_path.read_text())["identity"]["Run ID"]
                if not recorded_id or recorded_id[1].strip() != current_id:
                    raise ValueError("handoff_record_run_mismatch")
                checked(validate_package)
                identity = json.loads(packet_path.read_text())["identity"]
                if ("sentry_issue_remediation" in str(identity.get("Playbook / version", ""))
                        and identity.get("Workflow outcome") == "completed"):
                    checked(validate_sentry_artifacts, packet_path.parent)
                canonical = record_validation_output(record).split("Workflow-framework validation: passed\n", 1)[1].encode()
            proposed = args.verify_response.read_bytes()
            prefix = args.presentation_prefix.read_bytes() if args.presentation_prefix else b""
            suffix = args.presentation_suffix.read_bytes() if args.presentation_suffix else b""
            prefix.decode("utf-8")
            suffix.decode("utf-8")
            verify_presentation(canonical, proposed, prefix, suffix)
            receipt = {"status": "verified", "run_id": json.loads(packet_path.read_text())["identity"]["Run ID"],
                       "canonical_sha256": hashlib.sha256(canonical).hexdigest(),
                       "presentation_prefix": prefix.decode("utf-8"),
                       "presentation_suffix": suffix.decode("utf-8"),
                       "proposed_sha256": hashlib.sha256(proposed).hexdigest(),
                       "proposed_response": str(args.verify_response.resolve()),
                       "record_sha256": hashlib.sha256(record.read_bytes()).hexdigest() if
                           (record := packet_path.parent / "work_record.md").is_file() else None,
                       "comparison_policy": "Exact UTF-8 canonical report plus declared prefix/suffix with one optional terminal LF; internal whitespace is significant",
                       "scope": "prepared response bytes; actual chat delivery is not observable by this CLI"}
            (packet_path.parent / "handoff_delivery.json").write_text(json.dumps(receipt, indent=2) + "\n")
            if args.publish_response:
                print(proposed.decode(), end="")
                print("Final-response instruction: send the emitted stdout unchanged as your final answer; "
                      "do not summarize it or replace it with a link. The receipt verifies prepared bytes only.",
                      file=sys.stderr)
            else:
                print(json.dumps(receipt, sort_keys=True))
        except (OSError, ValueError, KeyError, TypeError, IndexError, subprocess.CalledProcessError) as error:
            (args.packet.parent / "handoff_delivery.json").unlink(missing_ok=True)
            print(json.dumps({"status": "blocked", "reason": str(error)}, sort_keys=True))
            return 2
        return 0
    if args.workflow_failure:
        if (not args.packet or args.pre_release or args.check_packet or args.blocked_runtime_snapshot
                or args.publish_technical_spike_report or args.analytical_failure):
            parser.error("--workflow-failure requires --packet and cannot be combined with another mode")
        try:
            packet_path = args.packet.resolve()
            # This receipt reports failure; it never certifies activation, readiness or runtime release.
            closure_state = collect_failure_closure(packet_path, args.provider_session, args.parent_thread_id)
            _, previous = _finalization_status(packet_path)
            packet = json.loads(packet_path.read_text())
            frozen = snapshot_bytes(packet)
            snapshot = packet_path.parent / snapshot_name(packet)
            if snapshot.exists() and snapshot.read_bytes() != frozen:
                raise ValueError("workflow_failure_snapshot_conflict")
            if not snapshot.exists():
                with snapshot.open("xb") as stream:
                    stream.write(frozen)
            receipt = {**previous, "schema_version": 1, "status": "failed", "stage": "workflow",
                       "run_id": packet["identity"]["Run ID"],
                       "reported_by": "Coordinator", "validation_performed": False,
                       "packet_snapshot": str(snapshot),
                       "snapshot_sha256": hashlib.sha256(frozen).hexdigest(),
                       "errors": [args.workflow_failure],
                       "historical_errors": list(dict.fromkeys(previous.get("historical_errors", [])
                                                               + previous.get("errors", []))),
                       "blocker_owner": "Coordinator", "runtime_closure": closure_state,
                       "observed_at": datetime.now(timezone.utc).isoformat(),
                       "packet_sha256": hashlib.sha256(packet_path.read_bytes()).hexdigest()}
            (packet_path.parent / FINALIZATION_STATUS_FILENAME).write_text(json.dumps(receipt, indent=2) + "\n")
            report = failure_handoff(packet_path, args.workflow_failure)
            _save_failure_handoff(packet_path, report)
            print(report)
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            print(json.dumps({"status": "blocked", "reason": str(error)}, sort_keys=True))
            print(failure_handoff(args.packet, args.workflow_failure))
        return 2
    if args.blocked_runtime_snapshot and (args.pre_release or args.publish_technical_spike_report or args.analytical_failure):
        parser.error("--blocked-runtime-snapshot cannot be combined with another finalization mode")
    if args.check_packet and (args.pre_release or args.blocked_runtime_snapshot or args.publish_technical_spike_report
                              or args.analytical_failure):
        parser.error("--check-packet cannot be combined with another finalization mode")
    if args.publish_technical_spike_report:
        if not args.packet:
            parser.error("--publish-technical-spike-report requires --packet")
        try:
            publish_technical_spike_report(
                args.packet, args.publish_technical_spike_report,
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, OSError) as error:
            print(json.dumps({"status": "blocked", "reason": str(error)}, sort_keys=True))
            return 2
        return 0
    if not args.packet or not args.closure or not args.record:
        parser.error("--packet, --closure, and --record are required")
    try:
        if args.analytical_failure:
            if not all((args.analytical_failure_stage, args.coordinator_model_effort,
                        args.framework_revision, args.framework_status)):
                parser.error(
                    "--analytical-failure requires --analytical-failure-stage, --coordinator-model-effort, "
                    "--framework-revision, and --framework-status"
                )
            if args.analytical_failure_stage != "evidence_topology" and not args.evidence_artifact:
                parser.error("--evidence-artifact is required after Evidence Topology")
            prepare_analytical_failure(
                args.packet.resolve(), args.closure.resolve(), args.record.resolve(),
                reason=args.analytical_failure, failure_stage=args.analytical_failure_stage,
                completed_handles=args.completed_handle,
                coordinator_model_effort=args.coordinator_model_effort,
                framework_revision=args.framework_revision, framework_status=args.framework_status,
                evidence_artifact=args.evidence_artifact.resolve() if args.evidence_artifact else None,
            )
        else:
            finalize(
                args.packet.resolve(), args.closure.resolve(), args.record.resolve(),
                pre_release=args.pre_release,
                check_only=args.check_packet,
                blocked_runtime_snapshot=args.blocked_runtime_snapshot,
                coordinator_model_effort=args.coordinator_model_effort,
                framework_revision=args.framework_revision,
                framework_status=args.framework_status,
            )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, OSError, subprocess.CalledProcessError) as error:
        print(json.dumps({"status": "blocked", "reason": str(error)}, sort_keys=True))
        if not args.pre_release and not args.check_packet and _finalization_status(args.packet.resolve())[1].get("status") != "failed":
            # Preparation failed before validation; use the existing control-failure receipt and preserved packet.
            return subprocess.run([sys.executable, __file__, "--packet", str(args.packet.resolve()),
                                   "--workflow-failure", str(error)]).returncode
        if not args.pre_release and not args.check_packet:
            report = failure_handoff(args.packet.resolve(), str(error))
            try:
                _save_failure_handoff(args.packet.resolve(), report)
            except OSError as write_error:
                print(json.dumps({"status": "blocked", "reason": "failure_handoff_save_failed:" + str(write_error)}))
            print(report)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
