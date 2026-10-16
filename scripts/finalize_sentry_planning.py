#!/usr/bin/env python3
"""Deterministically finalize a successful Standard Sentry planning run."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from contextlib import redirect_stdout
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path

try:
    from finalize_work_record import finalize, register_pending_delivery
    from normalize_fix_design_result import normalize_artifact_root
    from work_record_format import render_compact, snapshot_bytes, snapshot_name
except ModuleNotFoundError:
    from scripts.finalize_work_record import finalize, register_pending_delivery
    from scripts.normalize_fix_design_result import normalize_artifact_root
    from scripts.work_record_format import render_compact, snapshot_bytes, snapshot_name
try:
    from run_input_manifest import load_manifest
except ModuleNotFoundError:  # Imported as scripts.finalize_sentry_planning from the repository root.
    from scripts.run_input_manifest import load_manifest
try:
    from runtime_checks import (
        trace_errors,
        trace_identity_errors,
        terminal_observation_errors,
        prepared_package_errors,
    )
    from worker_runtime_evidence import dispatch_audit_errors
except ModuleNotFoundError:  # Imported as scripts.finalize_sentry_planning from the repository root.
    from scripts.runtime_checks import (
        trace_errors,
        trace_identity_errors,
        terminal_observation_errors,
        prepared_package_errors,
    )
    from scripts.worker_runtime_evidence import dispatch_audit_errors


try:
    from work_record_format import _cell, _material_rows
except ModuleNotFoundError:
    from scripts.work_record_format import _cell, _material_rows


try:
    from validation.api import checked, record_validation_output
    from validation.finalization import validate_sentry_artifacts
except ModuleNotFoundError:
    from scripts.validation.api import checked, record_validation_output
    from scripts.validation.finalization import validate_sentry_artifacts


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "validate_library.py"
PLAN_TEMPLATE = ROOT / "templates" / "implementation_plan.md"
V34_FIXTURE = ROOT / "tests" / "fixtures" / "sentry_deterministic_finalization.json"
V36_FIXTURE = ROOT / "tests" / "fixtures" / "sentry_finalization_regression.json"
V37_V38_FIXTURE = ROOT / "tests" / "fixtures" / "sentry_runtime_regressions.json"
WORKER_BINDINGS = {
    "evidence-topology": ("sentry_current_state_investigator", "Evidence topology"),
    "repository-integration": ("sentry_repository_integrator", "Repository integration"),
    "fix-design": ("sentry_solution_architect", "Fix design"),
}
WORKER_SPEC_ALIASES = {
    "current_state_investigator": "evidence-topology",
    "sentry_current_state_investigator": "evidence-topology",
    "repository_integrator": "repository-integration",
    "sentry_repository_integrator": "repository-integration",
    "solution_architect": "fix-design",
    "sentry_solution_architect": "fix-design",
}
CONDITIONAL_WORKERS = ("repository-integration",)
UUID_PATTERN = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
INTERFACE_FIELDS = (
    ("Surface", "surface"),
    ("Request shape", "request_shape"),
    ("Response shape", "response_shape"),
    ("Absence semantics", "absence_semantics"),
    ("Compatibility / precedence", "compatibility_precedence"),
    ("Rollout", "rollout"),
)


def _table(headers: tuple[str, ...], rows: list[dict[str, object]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend(
        "| " + " | ".join(_cell(row.get(header, "")) for header in headers) + " |"
        for row in rows
    )
    return "\n".join(lines)


def _bullets(values: object, *, empty: str = "None recorded.") -> str:
    if not isinstance(values, list) or not values:
        return empty
    return "\n".join(f"- {value}" for value in values)


def _git(repository: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repository), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def _repository_row(role: str, declared: Path) -> dict[str, object]:
    resolved = declared.resolve()
    revision = _git(resolved, "rev-parse", "HEAD")
    branch = _git(resolved, "branch", "--show-current") or "detached"
    dirty = bool(_git(resolved, "status", "--porcelain"))
    return {
        "Repository role": role,
        "Declared path": str(declared),
        "Resolved path": str(resolved),
        "Branch / detached": branch,
        "Full revision": revision,
        "Clean status": "Dirty" if dirty else "Clean",
        "User-selected ref": "Current checkout",
        "Release mapping": "Not established",
        "Evidence eligibility": "Current-checkout source evidence; production mapping remains explicit",
    }


def _parse_repository(value: str) -> tuple[str, Path]:
    role, separator, path = value.partition("=")
    if not separator or not role.strip() or not path.strip():
        raise ValueError("repository must use ROLE=/absolute/path")
    resolved = Path(path).resolve()
    if not resolved.is_dir():
        raise ValueError(f"repository does not exist: {resolved}")
    return role.strip(), resolved


def _plan_version() -> str:
    match = re.search(r"^version:\s*(\S+)\s*$", PLAN_TEMPLATE.read_text(), re.MULTILINE)
    if not match:
        raise ValueError("implementation_plan_template_version_unavailable")
    return match.group(1)


def _numbered_step(value: object, index: int) -> tuple[str, str]:
    text = str(value).strip()
    match = re.match(r"^(\d+)\.\s*(.*)$", text)
    return (match.group(1), match.group(2)) if match else (str(index), text)


def render_plan(
    fix: dict[str, object], packet: dict[str, object], repositories: list[dict[str, object]]
) -> str:
    plan = fix.get("plan")
    if not isinstance(plan, dict):
        raise ValueError("ready Fix Design requires a structured plan payload")
    title = str(plan.get("title", "")).strip()
    if not title:
        raise ValueError("ready Fix Design plan requires a title")

    interface = fix.get("interface_contract")
    if fix.get("interface_change") is True:
        if not isinstance(interface, dict):
            raise ValueError("interface_change requires interface_contract")
        interface_row = {header: interface.get(field, "") for header, field in INTERFACE_FIELDS}
    else:
        interface_row = {header: "Not applicable" for header, _ in INTERFACE_FIELDS}

    boundaries = plan.get("exact_boundaries", [])
    source_rows: list[dict[str, object]] = []
    if isinstance(boundaries, list):
        for boundary in boundaries:
            if not isinstance(boundary, dict):
                continue
            source_rows.append({
                "Repository": boundary.get("repository", ""),
                "Files or symbols": "<br>".join(str(item) for item in boundary.get("files_symbols", [])),
                "Intended change": "Apply the shared smallest intended change within this boundary.",
                "Compatibility constraints": "See the exact Interface Contract and compatibility rules.",
            })
    if not source_rows:
        source_rows.append({
            "Repository": "Supported boundary",
            "Files or symbols": fix["supported_remediation_boundary"],
            "Intended change": fix["supported_intended_change"],
            "Compatibility constraints": "See Interface Contract",
        })

    tests = plan.get("regression_test_strategy", [])
    test_rows = [
        {
            "Level": "Regression" if index == 1 else "Focused / contract",
            "Test or check": value,
            "Expected result": "The supported contract behavior is demonstrated without changing legacy semantics.",
            "Owner": "Implementer / Tester",
            "Availability / result": "Planned; not run during planning",
        }
        for index, value in enumerate(tests if isinstance(tests, list) else [], start=1)
    ] or [{
        "Level": "Focused",
        "Test or check": "Execute the Fix Design validation strategy.",
        "Expected result": "The intended change and compatibility behavior are demonstrated.",
        "Owner": "Tester",
        "Availability / result": "Planned; not run during planning",
    }]

    steps = plan.get("ordered_steps", [])
    step_rows = []
    for index, value in enumerate(steps if isinstance(steps, list) else [], start=1):
        number, activity = _numbered_step(value, index)
        step_rows.append({
            "Step": number,
            "Activity": activity,
            "Owner": "Implementer / Tester / Reviewer as applicable",
            "Dependency or approval gate": "Approved plan; prior step complete",
            "Status": "Pending",
        })
    if not step_rows:
        raise ValueError("ready Fix Design plan requires ordered_steps")

    risks = plan.get("risks", []) if isinstance(plan.get("risks"), list) else []
    rollback = plan.get("rollback", []) if isinstance(plan.get("rollback"), list) else []
    monitoring = plan.get("monitoring", []) if isinstance(plan.get("monitoring"), list) else []
    risk_rows = []
    for index, risk in enumerate(risks):
        risk_rows.append({
            "Risk or impact": risk,
            "Mitigation": "Preserve compatibility constraints and validate before rollout.",
            "Rollback action": rollback[index] if index < len(rollback) else "Use the documented rollback sequence.",
            "Monitoring or follow-up": (
                monitoring[index] if index < len(monitoring) else "Use the documented monitoring plan."
            ),
            "Owner": "Implementation owner",
        })
    if not risk_rows:
        risk_rows.append({
            "Risk or impact": "Residual uncertainty remains.",
            "Mitigation": str(plan.get("residual_uncertainty", "Reconfirm before implementation.")),
            "Rollback action": "Revert the bounded change.",
            "Monitoring or follow-up": "Validate the supported boundary after release.",
            "Owner": "Implementation owner",
        })

    checks_remaining = fix.get("checks_remaining", [])
    open_questions = _bullets(checks_remaining, empty="- No blocking questions; approval remains required.")
    completion = plan.get("completion_criteria", [])
    completion_lines = (
        "\n".join(f"- [ ] {item}" for item in completion)
        if completion
        else "- [ ] Supported change validated."
    )
    repo_names = ", ".join(str(row["Resolved path"]) for row in repositories)
    work_item = packet["work_item"]["ID"]
    metadata = _table(("Field", "Value"), [
        {"Field": "Work item", "Value": work_item},
        {"Field": "Change set ID", "Value": work_item},
        {"Field": "Playbook", "Value": packet["identity"]["Playbook / version"]},
        {"Field": "Requested profile", "Value": "standard"},
        {"Field": "Executed profile", "Value": "standard"},
        {"Field": "Lifecycle", "Value": "planning"},
        {"Field": "Affected repositories", "Value": repo_names},
        {"Field": "Plan status", "Value": "Ready for implementation; approval pending"},
        {"Field": "Approval reference", "Value": "Not recorded"},
        {"Field": "Portable handoff", "Value": "Not required for current planning handoff"},
        {"Field": "Last updated", "Value": packet["work_item"]["Last Updated"]},
    ])

    return f"""---
title: Engineering Implementation Plan
version: {_plan_version()}
status: Pilot
owner: Engineering
last_updated: {packet['work_item']['Last Updated']}
depends_on:
  - ./work_record.md
  - ./normalized_evidence.md
  - ./fix_design_result.json
---

# Engineering Implementation Plan

## {title}

This is an approval-gated planning artifact. It does not authorize source-code or external-system changes.

# Metadata

{metadata}

# 1. Scope and Baseline

## In scope

{_bullets(plan.get('scope'))}

## Explicit exclusions

{_bullets(plan.get('exclusions'))}

Supported remediation boundary: {fix['supported_remediation_boundary']}

# 2. Root Cause and Behavior Contract

Root cause or best-supported explanation: {plan.get('root_cause', '')}

Supported intended change: {fix['supported_intended_change']}

Residual uncertainty: {plan.get('residual_uncertainty', 'None recorded.')}

# Interface Contract

{_table(tuple(header for header, _ in INTERFACE_FIELDS), [interface_row])}

# 3. Source Change Plan

## Smallest intended change

{_bullets(plan.get('smallest_intended_change'))}

## Compatibility and absence rules

{_bullets(plan.get('compatibility_and_absence'))}

{_table(('Repository', 'Files or symbols', 'Intended change', 'Compatibility constraints'), source_rows)}

# 4. Test and Validation Plan

{_table(('Level', 'Test or check', 'Expected result', 'Owner', 'Availability / result'), test_rows)}

# 5. Ordered Execution Plan

{_table(('Step', 'Activity', 'Owner', 'Dependency or approval gate', 'Status'), step_rows)}

# 6. Risk and Operations

## Rollout

{_bullets(plan.get('rollout'))}

## Rollback

{_bullets(plan.get('rollback'))}

## Monitoring

{_bullets(plan.get('monitoring'))}

{_table(('Risk or impact', 'Mitigation', 'Rollback action', 'Monitoring or follow-up', 'Owner'), risk_rows)}

# 7. Completion Criteria

{completion_lines}

# Open Questions and Decisions

{open_questions}
"""


def render_clarification_brief(fix: dict[str, object], run_inputs: dict | None = None) -> str:
    clarification = fix.get("clarification_brief")
    if not isinstance(clarification, dict):
        raise ValueError("awaiting_input requires a structured clarification_brief")
    confirmed = clarification.get("confirmed_facts")
    options = clarification.get("feasible_options")
    if not isinstance(confirmed, list) or not confirmed:
        raise ValueError("clarification_brief confirmed_facts must be a non-empty list")
    if not isinstance(options, list) or not options:
        raise ValueError("clarification_brief feasible_options must be a non-empty list")
    for field in ("strongest_hypothesis", "recommendation", "plain_language_next_action"):
        if not isinstance(clarification.get(field), str) or not clarification[field].strip():
            raise ValueError(f"clarification_brief {field} must be a non-empty string")
    correlation = []
    for row in (run_inputs or {}).get("inputs", []):
        for occurrence in row.get("Occurrence correlation", []):
            correlation.append(str(row["Input ID"]) + ": " + "; ".join(f"{key}={value}" for key, value in occurrence.items()))
    correlation_block = ("\n## Occurrence correlation\n\n" + _bullets(correlation)
        + "\n\nThese keys describe the supplied occurrence. Confirm the receiver route and environment; "
          "do not assume it is the same occurrence as the latest Sentry event.\n") if correlation else ""
    return f"""# Clarification Brief

## Confirmed current-run facts

{_bullets(confirmed)}

## Best current explanation

{clarification['strongest_hypothesis']}

## Feasible options

{_bullets(options)}

## Recommendation

{clarification['recommendation']}

## Smallest next action

{clarification['plain_language_next_action']}
{correlation_block}
"""


def _binding(manifest: dict[str, object], agent: str, observed: dict | None = None) -> tuple[str, str]:
    value = manifest.get("bindings", {}).get(agent)
    if not isinstance(value, dict):
        raise ValueError(f"missing role binding: {agent}")
    model_effort = f"{value['model']} / {value['effort']}"
    actual = f"{observed['model']} / {observed['effort']}" if observed else (
        f"Not exposed; configured binding {value['model']} / {value['effort']}")
    return model_effort, actual


def _released_closure(path: Path, handles: list[str]) -> dict[str, object]:
    if path.is_file():
        closure = json.loads(path.read_text())
        rows = closure.get("runtime_closure", [])
        completed = {handle.strip() for row in rows if isinstance(row, dict)
                     for handle in re.split(r"[,;]", str(row.get("Completed worker handles", "")))}
        if rows and all(handle in completed for handle in handles) and all(
            isinstance(row, dict) and str(row.get("Runtime status", "")).lower() in {"released", "terminal"}
            and str(row.get("Remaining active handles", "")).lower() in {"none", "0"}
            for row in rows
        ):
            return closure
        raise ValueError("existing runtime closure does not confirm every worker released or terminal")
    bindings = path.parent / "role_bindings.json"
    if bindings.is_file() and json.loads(bindings.read_text()).get("runtime_evidence"):
        raise ValueError("prepared_runtime_closure_receipt_required")
    joined = "; ".join(handles)
    return {"runtime_closure": [{
        "Run or stage": "Standard Sentry planning",
        "Receipt owner": "Coordinator",
        "Completed worker handles": joined,
        "Runtime status": "Released",
        "Remaining active handles": "None",
        "Closure evidence or blocker": f"Provider release confirmed for completed handles: {joined}.",
    }]}


def _completed_workers(
    evidence_handle: str, fix_handle: str, worker_specs: list[str]
) -> dict[str, str]:
    workers = {"evidence-topology": evidence_handle}
    for value in worker_specs:
        worker, separator, handle = value.partition("=")
        worker = worker.strip().lower()
        handle = handle.strip()
        canonical_worker = WORKER_SPEC_ALIASES.get(worker, worker)
        if not separator or canonical_worker not in WORKER_BINDINGS:
            raise ValueError(
                "completed_worker must use a known WORKER=HANDLE: "
                + ", ".join(WORKER_BINDINGS)
            )
        if canonical_worker in {"evidence-topology", "fix-design"}:
            expected = evidence_handle if canonical_worker == "evidence-topology" else fix_handle
            if handle != expected:
                raise ValueError(f"{canonical_worker} alias handle must match its implicit result handle")
            continue
        if canonical_worker in workers:
            raise ValueError(f"duplicate completed worker: {canonical_worker}")
        workers[canonical_worker] = handle
    workers["fix-design"] = fix_handle
    for worker, handle in workers.items():
        if not isinstance(handle, str) or not (UUID_PATTERN.fullmatch(handle)
                or re.fullmatch(r"/root(?:/[a-z0-9_]+)+", handle)):
            raise ValueError(f"{worker} result is missing its exact provider handle")
    if len(set(workers.values())) != len(workers):
        raise ValueError("completed workers must use distinct provider handles")
    return workers


def _trace_audit(completed_workers: dict[str, str], trace_specs: list[str],
                 *, artifact_root: Path | None = None) -> dict[str, object]:
    """Validate supplied provider traces and report unavailable traces explicitly."""
    if artifact_root is None and trace_specs:
        artifact_root = Path(trace_specs[0].partition("=")[2]).expanduser().resolve().parent
    prepared = bool(artifact_root and (artifact_root / "role_bindings.json").is_file()
                    and json.loads((artifact_root / "role_bindings.json").read_text()).get("runtime_evidence"))
    if not trace_specs and not prepared:
        return {
            "status": "unavailable",
            "note": "provider trace audit unavailable; worker self-attestation not independently verified",
            "workers": {},
        }
    audited: dict[str, str] = {}
    configurations = {}
    runtime_audits = []
    for spec in trace_specs:
        worker, separator, raw_path = spec.partition("=")
        worker = worker.strip()
        path = Path(raw_path.strip()).expanduser().resolve()
        if not separator or worker not in completed_workers:
            raise ValueError("worker_trace must use a completed WORKER=/absolute/path")
        if worker in audited:
            raise ValueError(f"duplicate worker trace: {worker}")
        if not path.is_file():
            raise ValueError(f"worker_trace_unavailable:{worker}:{path}")
        if prepared and path.parent != artifact_root:
            raise ValueError(f"worker_trace_outside_current_run:{worker}")
        trace = json.loads(path.read_text())
        errors = trace_errors(trace, require_freshness=prepared)
        if prepared:
            role = WORKER_BINDINGS.get(worker, (worker, ""))[0]
            errors.extend(trace_identity_errors(trace, artifact_root, role, completed_workers[worker]))
            runtime_audits.append({**trace.get("status_observation", {}), "Worker": worker,
                                  "Provider handle": completed_workers[worker],
                                  "Last dispatch at": trace.get("last_dispatch_at"), "Trace path": str(path)})
        if errors:
            raise ValueError(f"worker_trace_audit_failed:{worker}:{','.join(errors)}")
        audited[worker] = "passed"
        configurations[worker] = next(iter(reversed(trace.get("runtime_configurations", []))), None)
    missing = [worker for worker in completed_workers if worker not in audited]
    if prepared:
        closure_path = artifact_root / "runtime_closure.json"
        closure = json.loads(closure_path.read_text()) if closure_path.is_file() else {}
        observations = closure.get("terminal_observations", [])
        if any(row.get("Runtime status", "").lower() == "terminal" for row in closure.get("runtime_closure", [])):
            selected = [row for row in observations if row.get("Provider handle") in completed_workers.values()]
            errors = terminal_observation_errors(selected, list(completed_workers.values()))
            errors.extend(dispatch_audit_errors({"runtime_audits": selected}, artifact_root / "finalization_packet.json"))
            if errors:
                raise ValueError(";".join(errors))
        for worker in missing:
            observation = next((row for row in observations if row.get("Provider handle") == completed_workers[worker]), {})
            errors = terminal_observation_errors([observation], [completed_workers[worker]])
            if errors:
                raise ValueError(";".join(errors))
            runtime_audits.append({**observation, "Worker": worker, "Provider handle": completed_workers[worker]})
        errors = dispatch_audit_errors({"runtime_audits": runtime_audits}, artifact_root / "finalization_packet.json")
        if errors:
            raise ValueError(";".join(errors))
    if missing:
        return {
            "status": "partial",
            "note": "provider trace audit partial; unavailable for " + ", ".join(missing),
            "workers": audited,
            "configurations": configurations,
            "runtime_audits": runtime_audits,
        }
    return {
        "status": "passed",
        "note": "provider trace audit passed for every completed worker",
        "workers": audited,
        "configurations": configurations,
        "runtime_audits": runtime_audits,
    }


def _load_run_inputs(artifact_root: Path, packet: dict[str, object]) -> dict[str, object]:
    metadata = packet.get("run_input_manifest")
    if not isinstance(metadata, dict):
        raise ValueError("run_input_manifest_required")
    declared_path = Path(str(metadata.get("path", "")))
    path = declared_path if declared_path.is_absolute() else artifact_root / declared_path
    path = path.resolve()
    canonical = (artifact_root / "run_inputs.json").resolve()
    if path != canonical:
        # Transactional finalization stages copy the manifest under a temporary
        # artifact root while preserving the original absolute provenance path.
        if path.name != "run_inputs.json":
            raise ValueError("run_input_manifest_must_be_current_run_artifact")
        path = canonical
    if not path.is_file():
        raise ValueError(f"run_input_manifest_unavailable:{path}")
    if hashlib.sha256(path.read_bytes()).hexdigest() != str(metadata.get("sha256", "")):
        raise ValueError("run_input_manifest_hash_mismatch")
    manifest = load_manifest(path, explicit=False)
    if manifest.get("status") != "explicit":
        raise ValueError("run_input_manifest_required")
    expected_ids = [str(value) for value in metadata.get("input_ids", [])]
    actual_ids = [str(row["Input ID"]) for row in manifest["inputs"]]
    if expected_ids != actual_ids:
        raise ValueError("run_input_manifest_metadata_mismatch")
    return manifest


def _merge_input_rows(
    packet: dict[str, object], run_inputs: dict[str, object], evidence_path: Path, fix_path: Path
) -> None:
    rows = _material_rows(packet.get("inputs"), "Input ID")
    by_id = {str(row["Input ID"]): row for row in rows}
    for row in run_inputs["inputs"]:
        input_id = str(row["Input ID"])
        if input_id not in by_id:
            rows.append(dict(row))
            by_id[input_id] = rows[-1]
    for row in (
        {"Input ID": "UPSTREAM-001", "Input or artifact": "Normalized evidence",
         "Source or path": str(evidence_path), "Authority": "Validated current-run worker output",
         "Status": "Consumed"},
        {"Input ID": "UPSTREAM-002", "Input or artifact": "Fix Design result",
         "Source or path": str(fix_path), "Authority": "Validated current-run worker output",
         "Status": "Consumed"},
    ):
        if row["Input ID"] not in by_id:
            rows.append(row)
            by_id[row["Input ID"]] = row
    packet["inputs"] = rows


def _validate_input_consumption(run_inputs: dict[str, object], fix: dict[str, object]) -> None:
    consumed = fix.get("inputs_consumed")
    if not isinstance(consumed, list):
        raise ValueError("fix_design_inputs_consumed_missing")
    consumed_text = " ".join(str(value) for value in consumed)
    missing = [
        str(row["Input ID"])
        for row in run_inputs["inputs"]
        if str(row["Input ID"]) not in consumed_text
    ]
    if missing:
        raise ValueError("fix_design_missing_inputs:" + ",".join(missing))


def _finalize_standard_sentry_in_place(
    artifact_root: Path,
    *,
    execution_repository: Path,
    evidence_handle: str,
    coordinator_model_effort: str,
    framework_revision: str,
    framework_status: str,
    repository_specs: list[str],
    completed_worker_specs: list[str] | None = None,
    worker_trace_specs: list[str] | None = None,
    audit_root: Path | None = None,
) -> None:
    artifact_root = artifact_root.resolve()
    packet_path = artifact_root / "finalization_packet.json"
    record_path = artifact_root / "work_record.md"
    evidence_path = artifact_root / "normalized_evidence.md"
    evidence_contract_path = artifact_root / "normalized_evidence_contract.md"
    fix_path = artifact_root / "fix_design_result.json"
    fix_contract_path = artifact_root / "fix_design_result_contract.json"
    manifest_path = artifact_root / "role_bindings.json"
    closure_path = artifact_root / "runtime_closure.json"
    plan_path = artifact_root / "implementation_plan.md"
    clarification_path = artifact_root / "clarification_brief.md"
    for required in (packet_path, evidence_path, fix_path, manifest_path):
        if not required.is_file():
            raise ValueError(f"required artifact is missing: {required}")
    if not re.fullmatch(r"[0-9a-fA-F]{40}", framework_revision):
        raise ValueError("framework_revision must be a 40-character Git SHA")
    if coordinator_model_effort != "Not exposed / Not exposed" and not re.fullmatch(
        r"\S+\s*/\s*(?:none|minimal|low|medium|high|xhigh|max|ultra)", coordinator_model_effort
    ):
        raise ValueError("coordinator_model_effort must use '<model> / <effort>' or 'Not exposed / Not exposed'")

    packet = json.loads(packet_path.read_text())
    fix = json.loads(fix_path.read_text())
    manifest = json.loads(manifest_path.read_text())
    run_inputs = _load_run_inputs(artifact_root, packet)
    readiness = fix.get("plan_readiness")
    action = fix.get("implementation_plan_action")
    if (readiness, action) not in {
        ("ready_for_implementation", "create"),
        ("awaiting_input", "omit"),
    }:
        raise ValueError(
            "deterministic Standard finalization requires ready_for_implementation/create "
            "or awaiting_input/omit"
        )
    awaiting_input = readiness == "awaiting_input"
    fix_handle = str(fix.get("worker_handle", "")).strip()
    _validate_input_consumption(run_inputs, fix)
    completed_workers = _completed_workers(
        evidence_handle, fix_handle, completed_worker_specs or []
    )
    trace_audit = _trace_audit(completed_workers, worker_trace_specs or [], artifact_root=audit_root or artifact_root)
    packet["runtime_audits"] = trace_audit.get("runtime_audits", [])
    handles = list(completed_workers.values())
    closure = _released_closure(closure_path, handles)
    closure_state = "terminal" if any(row["Runtime status"].lower() == "terminal"
                                      for row in closure["runtime_closure"]) else "released"

    repositories = _material_rows(packet.get("repositories"), "Repository role")
    for spec in repository_specs or ([] if repositories else [f"Execution={execution_repository}"]):
        role, path = _parse_repository(spec)
        row = _repository_row(role, path)
        existing = next((value for value in repositories if Path(value["Resolved path"]).resolve() == path.resolve()), None)
        if existing is None:
            repositories.append(row)
        elif existing["Full revision"] != row["Full revision"] or existing["Clean status"] != row["Clean status"]:
            raise ValueError("repository_baseline_changed:" + str(path))

    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    work_item = str(packet["work_item"]["ID"])
    packet["work_item"].update({
        "Title": str(packet["work_item"].get("Title", "")).strip() or work_item,
        "Last Updated": now,
    })
    if not all(str(packet["playbook_selection"].get(field, "")).strip() for field in packet["playbook_selection"]):
        packet["playbook_selection"] = {
            "Primary evidence": "Validated normalized Sentry evidence and canonical Fix Design result",
            "Primary goal": "Produce an evidence-backed, approval-gated Sentry remediation plan",
            "Selected playbook": "sentry_issue_remediation",
            "Closest alternative": "feature_delivery",
            "Why this playbook": "The run diagnoses a reported Sentry-related failure before implementation.",
        }
    _merge_input_rows(packet, run_inputs, evidence_path, fix_path)
    packet["repositories"] = repositories
    prompt_identity = str(packet["identity"]["Prompt template / revision / conformance"])
    if prompt_identity.endswith(" / pending"):
        prompt_identity = prompt_identity.removesuffix(" / pending") + " / pass"
    packet["identity"].update({
        "Run ID": str(packet["identity"].get("Run ID", "")).strip()
        or f"{work_item}-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}",
        "Framework commit / status": f"{framework_revision} / {framework_status.title()}",
        "Prompt template / revision / conformance": prompt_identity,
        "Coordinator model/effort": coordinator_model_effort,
        "Requested profile": "standard", "Activated profile": "standard", "Executed profile": "standard",
        "Profile status": "executed", "Lifecycle": "planning",
        "State": "awaiting_input" if awaiting_input else "ready_for_implementation",
        "Engineering state": "understood" if awaiting_input else "designed",
        "Workflow outcome": "completed",
        "Engineering outcome": "partially_solved" if awaiting_input else "plan_only",
        "Run input manifest": str(artifact_root / "run_inputs.json"),
        "Coordinator execution": "active parent session; no dedicated Coordinator worker spawned",
    })
    packet["finalization"].update({
        "Concurrent-run decision": str(packet["finalization"].get("Concurrent-run decision", "")).strip()
        or "Current isolated run",
        "Active related run or work item": str(
            packet["finalization"].get("Active related run or work item", "")
        ).strip()
        or "None",
        "Related-run check": str(packet["finalization"].get("Related-run check", "")).strip()
        or "Completed during initialization",
        "Durable artifact root": str(artifact_root),
        "Final reconciliation": (
            f"Passed; analytical fan-in complete and runtime {closure_state}; " + str(trace_audit["note"])
        ),
        "Finalization schema": "Passed",
    })

    bindings = {
        worker: _binding(manifest, WORKER_BINDINGS[worker][0], trace_audit.get("configurations", {}).get(worker))
        for worker in completed_workers
    }
    packet["workers"] = []
    packet["worker_results"] = []
    for worker in completed_workers:
        configured, observed = bindings[worker]
        role = WORKER_BINDINGS[worker][1]
        if worker == "evidence-topology":
            assigned = "Current-run inputs"
            depends_on = "Coordinator initialization"
            skills = "Bounded Sentry evidence collection"
            confidence = "High for recorded evidence; uncertainties explicit"
            contribution = "Created and validated normalized_evidence.md with explicit uncertainty and Contract Delta"
            refs = "E-001 / C-001"
            uncertainty = "See normalized_evidence.md"
        elif worker == "repository-integration":
            assigned = "Validated normalized evidence and declared repositories"
            depends_on = "Validated Evidence topology"
            skills = "Bounded cross-repository contract verification"
            confidence = "High for verified repository boundaries; uncertainties explicit"
            contribution = "Reported the conditional cross-repository integration boundary for Fix Design"
            refs = "E-001 / C-001"
            uncertainty = "See normalized_evidence.md and Fix Design checks remaining"
        else:
            assigned = "UPSTREAM-001 and every activated analytical result"
            depends_on = "Validated analytical inputs"
            skills = "Bounded remediation design"
            fix_confidence = fix.get("confidence", {})
            confidence_level = (
                str(fix_confidence.get("level", "")).strip()
                if isinstance(fix_confidence, dict)
                else ""
            )
            confidence = (
                f"{confidence_level.title()} for the Fix Design disposition"
                if confidence_level
                else "Confidence recorded in fix_design_result.json"
            )
            contribution = (
                str(fix["supported_intended_change"])
                if str(fix["supported_intended_change"]).strip()
                else "Established the indispensable evidence needed to select a remediation boundary"
            )
            refs = "E-002 / C-001; C-002"
            uncertainty = (
                "See blocking_unknowns and clarification_brief"
                if awaiting_input
                else "No blocking unknowns; remaining checks are plan gates"
            )
        worker_trace_status = str(trace_audit["workers"].get(worker, "not supplied"))
        uncertainty = f"{uncertainty}; provider trace audit {worker_trace_status}"
        packet["workers"].append({
            "Worker": worker, "Role": role, "Assigned inputs": assigned,
            "Mode": "investigation", "Depth": "standard", "Skills": skills,
            "Tools": "Mapped provider operations", "Capacity": "one in-task worker",
            "Configured model/effort": configured, "Provider-observed model/effort": observed,
            "Usage": "Provider telemetry unavailable", "Depends on": depends_on,
            "Outcome": "complete", "Confidence": confidence,
        })
        packet["worker_results"].append({
            "Worker": worker, "Outcome": "complete", "Confidence": confidence,
            "Unique contribution": contribution, "Evidence / claim refs": refs,
            "Uncertainties / blockers": uncertainty, "Actual model/effort": observed,
            "Usage/credits": "Provider telemetry unavailable",
        })
    for worker in CONDITIONAL_WORKERS:
        if worker in completed_workers:
            continue
        configured, observed = _binding(manifest, WORKER_BINDINGS[worker][0])
        role = WORKER_BINDINGS[worker][1]
        packet["workers"].append({
            "Worker": worker,
            "Role": role,
            "Assigned inputs": "Conditional gate inputs",
            "Mode": "conditional",
            "Depth": "standard",
            "Skills": "Bounded cross-repository contract verification",
            "Tools": "Mapped provider operations",
            "Capacity": "one in-task worker",
            "Configured model/effort": configured,
            "Provider-observed model/effort": observed,
            "Usage": "Provider telemetry unavailable",
            "Depends on": "Validated Evidence topology",
            "Outcome": "not_applicable",
            "Confidence": "Not assessed",
        })
        packet["worker_results"].append({
            "Worker": worker,
            "Outcome": "not_applicable",
            "Confidence": "Not assessed",
            "Unique contribution": "Not activated; the Standard conditional gate did not require it.",
            "Evidence / claim refs": "None",
            "Uncertainties / blockers": "No provider handle exists because the worker was not activated.",
            "Actual model/effort": observed,
            "Usage/credits": "Provider telemetry unavailable",
        })
    worker_names = "; ".join(completed_workers)
    worker_outcomes = "; ".join("complete" for _ in completed_workers)
    skipped = [worker for worker in CONDITIONAL_WORKERS if worker not in completed_workers]
    if skipped:
        worker_names = "; ".join([worker_names, *[f"{worker} (not activated)" for worker in skipped]])
        worker_outcomes = "; ".join([worker_outcomes, *["not_applicable" for _ in skipped]])
    packet["synchronization"] = [{
        "Stage": "Standard analytical fan-in", "Workers launched": worker_names,
        "Launch mode / exception": "Dependency-ordered activation", "Worker outcomes": worker_outcomes,
        "Results summarized": f"Yes; canonical artifacts consumed; {trace_audit['note']}",
        "Barrier status": f"Passed; runtime closure {closure_state}; {trace_audit['note']}",
    }]
    packet["evidence"] = [
        {"Evidence ID": "E-001", "Source": str(evidence_path),
         "Summary": "Validated current-run normalized evidence establishes the observed topology and uncertainty.",
         "Confidence": "High", "Uncertainty": "See normalized evidence", "Status": "Verified"},
        {"Evidence ID": "E-002", "Source": str(fix_path),
         "Summary": (
             "Validated Fix Design records the supported remediation boundary: "
             + str(fix["supported_remediation_boundary"])
             if str(fix["supported_remediation_boundary"]).strip()
             else "Validated Fix Design records that indispensable evidence is required before selecting a boundary."
         ),
         "Confidence": "High", "Uncertainty": "Design artifact, not runtime behavior; see Fix Design checks remaining",
         "Status": "Verified"},
    ]
    if awaiting_input:
        blockers = fix.get("blocking_unknowns", [])
        first_blocker = blockers[0] if isinstance(blockers, list) and blockers else {}
        question = str(first_blocker.get("question", "")).strip() if isinstance(first_blocker, dict) else ""
        packet["claims"] = [
            {"Claim ID": "C-001", "Claim": "The current-run evidence does not establish one remediation boundary.",
             "Evidence refs": "E-001; E-002", "Confidence": "High",
             "Uncertainty": "The indispensable observation is recorded in Fix Design.", "Status": "Supported"},
            {"Claim ID": "C-002", "Claim": question or "Indispensable evidence is required before implementation planning.",
             "Evidence refs": "E-002", "Confidence": "High", "Uncertainty": "Awaiting the named evidence.",
             "Status": "Supported"},
        ]
        packet["decisions"] = [{
            "Decision ID": "D-001",
            "Decision": "Omit the implementation plan and request only the indispensable evidence.",
            "Claim refs": "C-001; C-002", "Owner": "Coordinator", "Status": "Applied",
        }]
        packet["actions"] = [{
            "Action ID": "A-001",
            "Action": question or "Provide the indispensable evidence recorded by Fix Design.",
            "Decision ref": "D-001", "Owner": "Work-item owner and evidence owners", "Status": "Open",
        }]
    else:
        packet["claims"] = [
            {"Claim ID": "C-001", "Claim": str(fix["supported_remediation_boundary"]),
             "Evidence refs": "E-001; E-002", "Confidence": "High", "Uncertainty": "Explicit in source artifacts",
             "Status": "Supported"},
            {"Claim ID": "C-002", "Claim": str(fix["supported_intended_change"]),
             "Evidence refs": "E-002", "Confidence": "High", "Uncertainty": "Validation remains planned",
             "Status": "Supported"},
        ]
        packet["decisions"] = [{
            "Decision ID": "D-001",
            "Decision": "Create an approval-gated implementation plan for the supported change.",
            "Claim refs": "C-001; C-002", "Owner": "Coordinator", "Status": "Applied",
        }]
        packet["actions"] = [{
            "Action ID": "A-001", "Action": "Review and approve the implementation plan before remediation.",
            "Decision ref": "D-001", "Owner": "Work-item owner", "Status": "Proposed",
        }]

    if awaiting_input:
        plan_path.unlink(missing_ok=True)
        clarification_path.write_text(render_clarification_brief(fix, run_inputs))
    else:
        clarification_path.unlink(missing_ok=True)
        plan_path.write_text(render_plan(fix, packet, repositories))
    packet["durable_artifacts"] = [
        {"Artifact": "Role bindings", "Path": str(manifest_path), "Status": "Created",
         "Purpose": "Exact worker bindings"},
        {"Artifact": "Run input manifest", "Path": str(artifact_root / "run_inputs.json"),
         "Status": "Explicit and verified",
         "Purpose": "Immutable current-run context, decisions, and supporting artifacts"},
        {"Artifact": "Normalized evidence", "Path": str(evidence_path), "Status": "Created and validated",
         "Purpose": "Current-run evidence"},
        *([{"Artifact": "Normalized evidence contract", "Path": str(evidence_contract_path),
            "Status": "Prepared and consumed", "Purpose": "Assigned Evidence Topology output contract"}]
          if evidence_contract_path.is_file() else []),
        {"Artifact": "Fix design result", "Path": str(fix_path), "Status": "Created and validated",
         "Purpose": "Canonical design result"},
        *([{"Artifact": "Fix design result contract", "Path": str(fix_contract_path),
            "Status": "Prepared and consumed", "Purpose": "Assigned Fix Design output contract"}]
          if fix_contract_path.is_file() else []),
        *([{"Artifact": "Clarification brief", "Path": str(clarification_path),
            "Status": "Created", "Purpose": "Smallest indispensable evidence request"}]
          if awaiting_input else []),
        {"Artifact": "Implementation plan", "Path": str(plan_path),
         "Status": "Omitted by awaiting_input/omit" if awaiting_input else "Ready for implementation; approval pending",
         "Purpose": "Not created until the remediation boundary is established" if awaiting_input
         else "Approval-gated implementation design"},
        {"Artifact": "Finalization packet", "Path": str(packet_path), "Status": "Created",
         "Purpose": "Structured terminal input"},
        {"Artifact": "Runtime closure", "Path": str(closure_path), "Status": closure_state.title(),
         "Purpose": "Provider runtime closure receipt"},
        {"Artifact": "Work record", "Path": str(record_path), "Status": "Created",
         "Purpose": "Authoritative terminal handoff"},
    ]
    confidence = fix.get("confidence", {})
    confidence_basis = confidence.get("basis", "") if isinstance(confidence, dict) else ""
    if awaiting_input:
        clarification = fix["clarification_brief"]
        blockers = fix.get("blocking_unknowns", [])
        first_blocker = blockers[0] if isinstance(blockers, list) and blockers else {}
        question = str(first_blocker.get("question", "")).strip() if isinstance(first_blocker, dict) else ""
        explanations = [{
            "explanation": str(clarification["strongest_hypothesis"]),
            "confidence": str(confidence.get("level", "medium")) if isinstance(confidence, dict) else "medium",
            "reason": str(confidence_basis),
        }]
        packet["handoff"] = {
            "workflow_result": "Awaiting indispensable evidence",
            "implementation_plan": "omitted; Fix Design returned awaiting_input/omit",
            "established": [str(value) for value in clarification["confirmed_facts"]],
            "best_current_explanations": explanations,
            "next_action": {
                "owner": "Work-item owner and named evidence owners",
                "action": str(clarification["plain_language_next_action"]),
                "complete_when": (
                    f"Source-backed evidence answers this question: {question}"
                    if question
                    else "Source-backed evidence selects one remediation boundary."
                ),
            },
            "artifacts": [str(record_path), str(evidence_path), str(fix_path), str(clarification_path)],
            "execution": (
                "standard/planning; analytical validation passed; deterministic clarification rendering passed; "
                f"source changes none; runtime {closure_state}; {trace_audit['note']}"
            ),
            "provenance": (
                f"plugin {packet['identity']['Plugin package / version']}; framework revision {framework_revision} "
                f"({framework_status}); playbook {packet['identity']['Playbook / version']}."
            ),
        }
    else:
        plan = fix["plan"]
        residual = plan.get("residual_uncertainty", "") if isinstance(plan, dict) else ""
        packet["handoff"] = {
            "workflow_result": "Ready for implementation",
            "implementation_plan": f"created at {plan_path}; approval pending; no source or external changes made",
            "established": [str(fix["supported_remediation_boundary"]), str(fix["supported_intended_change"])],
            "best_current_explanations": ([{"explanation": str(confidence_basis), "confidence": "high",
                                            "reason": str(residual)}] if confidence_basis else []),
            "next_action": {"owner": "Work-item owner", "action": "Review and explicitly approve the implementation plan.",
                            "complete_when": "Implementation approval is recorded before a remediation run begins."},
            "artifacts": [str(record_path), str(evidence_path), str(fix_path), str(plan_path)],
            "execution": (
                "standard/planning; analytical validation passed; deterministic rendering passed; "
                f"source changes none; runtime {closure_state}; {trace_audit['note']}"
            ),
            "provenance": (
                f"plugin {packet['identity']['Plugin package / version']}; framework revision {framework_revision} "
                f"({framework_status}); playbook {packet['identity']['Playbook / version']}."
            ),
        }

    closure_path.write_text(json.dumps(closure, indent=2) + "\n")
    packet_path.write_text(json.dumps(packet, indent=2) + "\n")
    checked(validate_sentry_artifacts, artifact_root, allow_unreleased=True)
    finalize(packet_path, closure_path, record_path)


def _replace_file(path: Path, content: bytes) -> None:
    with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(content)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def finalize_standard_sentry(
    artifact_root: Path,
    *,
    evidence_handle: str,
    coordinator_model_effort: str,
    framework_revision: str,
    framework_status: str,
    repository_specs: list[str],
    completed_worker_specs: list[str] | None = None,
    worker_trace_specs: list[str] | None = None,
) -> None:
    artifact_root = artifact_root.resolve()
    required_names = (
        "finalization_packet.json",
        "normalized_evidence.md",
        "fix_design_result.json",
        "role_bindings.json",
    )
    for name in required_names:
        if not (artifact_root / name).is_file():
            raise ValueError(f"required artifact is missing: {artifact_root / name}")

    output_names = (
        "fix_design_result.json",
        "implementation_plan.md",
        "clarification_brief.md",
        "finalization_packet.json",
        "runtime_closure.json",
        "work_record.md",
        "handoff_response.md",
        "handoff_delivery.json",
    )
    with tempfile.TemporaryDirectory(prefix="workflow-sentry-stage-") as directory:
        stage_root = (Path(directory) / "artifacts").resolve()
        stage_root.mkdir()
        stage_names = set(required_names) | set(output_names) | {
            "normalized_evidence_contract.md",
            "fix_design_result_contract.json",
            "run_inputs.json",
        }
        for name in stage_names:
            source = artifact_root / name
            if source.is_file():
                shutil.copyfile(source, stage_root / name)
        with redirect_stdout(StringIO()):
            normalize_artifact_root(stage_root)
            _finalize_standard_sentry_in_place(
                stage_root,
                execution_repository=artifact_root.parent.parent,
                evidence_handle=evidence_handle,
                coordinator_model_effort=coordinator_model_effort,
                framework_revision=framework_revision,
                framework_status=framework_status,
                repository_specs=repository_specs,
                completed_worker_specs=completed_worker_specs,
                worker_trace_specs=worker_trace_specs,
                audit_root=artifact_root,
            )

        stage_prefix = str(stage_root)
        canonical_prefix = str(artifact_root)
        candidates = {
            name: (
                (stage_root / name).read_text().replace(stage_prefix, canonical_prefix).encode()
                if (stage_root / name).is_file()
                else None
            )
            for name in output_names
        }
        # Rebase the normalized snapshot before hashing; staging paths are not durable provenance.
        staged_record = (stage_root / "work_record.md").read_text()
        snapshot_reference = re.search(r"<!-- workflow-state: (finalization_snapshot\.[0-9a-f]{64}\.json) -->", staged_record)
        snapshot = json.loads((stage_root / snapshot_reference.group(1)).read_text().replace(
            stage_prefix, canonical_prefix,
        ))
        name = snapshot_name(snapshot)
        candidates = {name: snapshot_bytes(snapshot), **candidates}
        candidates["work_record.md"] = render_compact(snapshot).encode()
        output_names += (name,)
        originals = {
            name: (artifact_root / name).read_bytes() if (artifact_root / name).is_file() else None
            for name in output_names
        }
        try:
            for name, content in candidates.items():
                if content is None:
                    (artifact_root / name).unlink(missing_ok=True)
                else:
                    _replace_file(artifact_root / name, content)
            package_errors = prepared_package_errors(artifact_root)
            if package_errors:
                raise ValueError(";".join(package_errors))
            checked(validate_sentry_artifacts, artifact_root)
            validation = record_validation_output(artifact_root / "work_record.md")
            register_pending_delivery(artifact_root / "finalization_packet.json",
                                      validation.split("Workflow-framework validation: passed\n", 1)[1])
        except Exception:
            for name, content in originals.items():
                target = artifact_root / name
                if content is None:
                    target.unlink(missing_ok=True)
                else:
                    _replace_file(target, content)
            raise
        print(validation, end="")


def self_test() -> None:
    try:
        from self_check import run_self_check
    except ModuleNotFoundError:
        from scripts.self_check import run_self_check
    run_self_check("finalize_sentry_planning", "self_test")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", type=Path)
    parser.add_argument("--evidence-handle")
    parser.add_argument("--coordinator-model-effort")
    parser.add_argument("--framework-revision")
    parser.add_argument("--framework-status", choices=("clean", "dirty"))
    parser.add_argument("--provider-release-confirmed", action="store_true")
    parser.add_argument("--repository", action="append", default=[], metavar="ROLE=/ABSOLUTE/PATH")
    parser.add_argument("--completed-worker", action="append", default=[], metavar="WORKER=HANDLE")
    parser.add_argument("--worker-trace", action="append", default=[], metavar="WORKER=/ABSOLUTE/PATH")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not all((args.artifact_root, args.evidence_handle, args.coordinator_model_effort,
                args.framework_revision, args.framework_status)):
        parser.error(
            "--artifact-root, --evidence-handle, --coordinator-model-effort, --framework-revision, "
            "and --framework-status are required"
        )
    if not args.provider_release_confirmed and not (args.artifact_root / "runtime_closure.json").is_file():
        parser.error("runtime_closure.json is required; --provider-release-confirmed applies only to explicit release")
    try:
        finalize_standard_sentry(
            args.artifact_root,
            evidence_handle=args.evidence_handle,
            coordinator_model_effort=args.coordinator_model_effort,
            framework_revision=args.framework_revision,
            framework_status=args.framework_status,
            repository_specs=args.repository,
            completed_worker_specs=args.completed_worker,
            worker_trace_specs=args.worker_trace,
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, OSError, subprocess.CalledProcessError) as error:
        print(json.dumps({"status": "blocked", "reason": str(error)}, sort_keys=True))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
