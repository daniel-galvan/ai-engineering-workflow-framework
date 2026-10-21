#!/usr/bin/env python3
"""Stage Coordinator-owned handoff identity after accepted current-run fan-in."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from pathlib import Path


def stage(packet_path: Path, *, coordinator_model_effort: str, prompt_conformance: str,
          state: str | None = None, engineering_outcome: str | None = None) -> dict[str, object]:
    root = packet_path.resolve().parent
    try:
        from runtime_checks import prepared_package_errors
    except ModuleNotFoundError:
        from scripts.runtime_checks import prepared_package_errors
    package_errors = prepared_package_errors(root)
    if package_errors:
        raise ValueError(";".join(package_errors))
    packet = json.loads(packet_path.read_text())
    bindings_path = root / "role_bindings.json"
    bindings = json.loads(bindings_path.read_text())
    identity = packet.get("identity")
    if not isinstance(identity, dict) or identity.get("Lifecycle") not in {"planning", "remediation"}:
        raise ValueError("supported_lifecycle_required")
    lifecycle = identity["Lifecycle"]
    playbook = Path(str(identity.get("Playbook / version", "")).split(" / ", 1)[0]).stem.lower()
    if bindings.get("playbook") != playbook:
        raise ValueError("prepared_playbook_mismatch")
    if bindings.get("run_id") != identity.get("Run ID"):
        raise ValueError("prepared_run_id_mismatch")
    if lifecycle == "remediation":
        if playbook not in {"feature_delivery", "techops_issue_remediation", "sentry_issue_remediation"}:
            raise ValueError("remediation_packet_staging_unsupported:" + playbook)
        if state is not None:
            raise ValueError("remediation_state_is_derived")
        if engineering_outcome not in {"solved", "partially_solved", "blocked"}:
            raise ValueError("remediation_engineering_outcome_required")
        state = "blocked" if engineering_outcome == "blocked" else "handoff"
        engineering_state = "blocked" if state == "blocked" else "implemented"
        workflow_outcome = "blocked" if state == "blocked" else "in_progress"
    elif playbook == "techops_issue_remediation":
        if engineering_outcome is not None:
            raise ValueError("techops_engineering_outcome_not_applicable")
        if state not in {"ready_for_implementation", "awaiting_input", "blocked"}:
            raise ValueError("techops_coordinator_state_required")
        state_outcomes = {
            "ready_for_implementation": ("designed", "completed", "plan_only"),
            "awaiting_input": ("understood", "completed", "partially_solved"),
            "blocked": ("unknown", "blocked", "blocked"),
        }
        engineering_state, workflow_outcome, engineering_outcome = state_outcomes[state]
    elif playbook == "feature_delivery":
        if engineering_outcome is not None:
            raise ValueError("feature_delivery_engineering_outcome_not_applicable")
        if state is not None:
            raise ValueError("feature_delivery_state_comes_from_accepted_disposition")
        if str(packet.get("playbook_selection", {}).get("Primary goal", "")).strip().lower() != "implementation planning":
            raise ValueError("feature_implementation_planning_required")
        disposition = packet.get("planning_disposition", {})
        if not isinstance(disposition, dict):
            raise ValueError("feature_planning_disposition_required")
        pair = (disposition.get("plan_readiness"), disposition.get("implementation_plan_action"))
        if pair == ("ready_for_implementation", "create"):
            state = "ready_for_implementation"
            engineering_state, workflow_outcome, engineering_outcome = ("designed", "completed", "plan_only")
        elif pair in {("awaiting_input", "create_draft"), ("awaiting_input", "omit")}:
            state = "awaiting_input"
            engineering_state, workflow_outcome, engineering_outcome = ("understood", "completed", "partially_solved")
        else:
            raise ValueError("feature_planning_disposition_invalid")
    else:
        raise ValueError("planning_packet_staging_unsupported:" + playbook)
    profile = str(identity.get("Requested profile", "")).strip().lower()
    if profile not in {"standard", "deep"}:
        raise ValueError("requested_profile_invalid")
    if not coordinator_model_effort.strip():
        raise ValueError("coordinator_model_effort_required")
    if prompt_conformance != "pass":
        raise ValueError("prompt_conformance_pass_required")
    prompt_identity = str(identity.get("Prompt template / revision / conformance", ""))
    if prompt_identity.endswith(" / pending"):
        prompt_identity = prompt_identity.removesuffix(" / pending") + " / pass"
    elif not prompt_identity.endswith(" / pass"):
        raise ValueError("prompt_conformance_identity_invalid")

    candidate = json.loads(json.dumps(packet))
    candidate_identity = candidate["identity"]
    candidate_identity.update({
        "Activated profile": profile,
        "Executed profile": profile,
        "Profile status": "executed",
        "State": state,
        "Engineering state": engineering_state,
        "Workflow outcome": workflow_outcome,
        "Engineering outcome": engineering_outcome,
        "Coordinator model/effort": coordinator_model_effort.strip(),
        "Prompt template / revision / conformance": prompt_identity,
    })
    if lifecycle == "remediation":
        candidate_identity["Engineering outcome"] = engineering_outcome
        _delivery_synchronization(candidate)
        if playbook == "feature_delivery":
            try:
                from planning_contracts import _feature_delivery_remediation_errors
            except ModuleNotFoundError:
                from scripts.planning_contracts import _feature_delivery_remediation_errors
            errors = _feature_delivery_remediation_errors(candidate, packet_path, pre_handoff=True)
        elif playbook == "techops_issue_remediation":
            try:
                from planning_contracts import _techops_remediation_contract_errors
            except ModuleNotFoundError:
                from scripts.planning_contracts import _techops_remediation_contract_errors
            errors = _techops_remediation_contract_errors(candidate, packet_path, pre_handoff=True)
        else:
            errors = sentry_remediation_errors(candidate, packet_path, bindings, pre_handoff=True)
        if errors:
            raise ValueError(";".join(dict.fromkeys(errors)))
    else:
        _validate_current_fan_in(candidate, packet_path, bindings, playbook, profile)
        _passed_synchronization(candidate)
    _atomic_json(packet_path, candidate)
    return {"status": "staged", "playbook": playbook, "state": state,
            "accepted_workers": [row["Worker"] for row in candidate.get("worker_results", [])
                                 if isinstance(row, dict) and row.get("Worker") in {
                                     "feature-context", "impact-analysis", "repository-integration", "feature-design",
                                     "planning-review", "implement", "review", "validate"}
                                 and row.get("Outcome") in {"complete", "blocked", "failed"}]}


def _delivery_synchronization(packet: dict) -> None:
    required = {"implement", "review", "validate"}
    rows = [row for row in packet.get("worker_results", []) if isinstance(row, dict)
            and row.get("Worker") in required]
    if {row.get("Worker") for row in rows} != required:
        raise ValueError("feature_delivery_remediation_results_incomplete")
    packet["synchronization"] = [row for row in packet.get("synchronization", [])
                                 if not isinstance(row, dict) or row.get("Stage") != "Delivery fan-in"]
    outcomes = "; ".join(f"{row['Worker']}={row['Outcome']}" for row in rows)
    packet["synchronization"].append({
        "Stage": "Delivery fan-in",
        "Workers launched": ", ".join(sorted(required)),
        "Launch mode / exception": "Current-run provider dispatch ledger",
        "Worker outcomes": outcomes,
        "Results summarized": "Accepted typed results and Coordinator audits registered",
        "Barrier status": "Passed; current-run traces, immutable results, review, validation, and delivery gates checked",
    })


def sentry_remediation_errors(packet: dict, packet_path: Path, bindings: dict, *,
                              pre_handoff: bool = False, require_documenter: bool = False) -> list[str]:
    """Require Sentry's approved plan, three accepted delivery results, and current-run audits."""
    root = packet_path.parent.resolve()
    identity = packet.get("identity", {})
    if identity.get("Lifecycle") != "remediation" or identity.get("Profile status") != "executed":
        return ["sentry_remediation_profile_not_executed"]
    if (identity.get("Requested profile") != identity.get("Activated profile")
            or identity.get("Requested profile") != identity.get("Executed profile")):
        return ["sentry_remediation_profiles_must_match"]
    outcome = identity.get("Engineering outcome")
    state = identity.get("State")
    if outcome not in {"solved", "partially_solved", "blocked"}:
        return ["sentry_remediation_engineering_outcome_required"]
    blocked_snapshot = state == "blocked" and identity.get("Workflow outcome") == "blocked"
    if not blocked_snapshot and (
            state != ("blocked" if outcome == "blocked" else "handoff" if pre_handoff else "completed")
            or identity.get("Workflow outcome") != ("blocked" if outcome == "blocked" else
                                                      "in_progress" if pre_handoff else "completed")):
        return ["sentry_remediation_handoff_state_invalid"]
    reentry = packet.get("reentry", {})
    plan = root / "implementation_plan.md"
    if (not reentry.get("Prior run ID") or reentry.get("Prior run ID") == identity.get("Run ID")
            or reentry.get("Approved plan") != str(plan.resolve()) or not plan.is_file()
            or reentry.get("Approved plan SHA256") != hashlib.sha256(plan.read_bytes()).hexdigest()):
        return ["sentry_approved_plan_changed_or_reentry_incomplete"]
    try:
        from validation.api import checked
        from validation.finalization import validate_sentry_artifacts
    except ModuleNotFoundError:
        from scripts.validation.api import checked
        from scripts.validation.finalization import validate_sentry_artifacts
    try:
        checked(validate_sentry_artifacts, root, allow_unreleased=True)
    except ValueError as error:
        return ["sentry_remediation_plan_or_evidence_invalid:" + str(error)]

    try:
        from merge_techops_result import FEATURE_REMEDIATION_WORKERS, merged_result_errors
        from planning_contracts import (FEATURE_DELIVERY_LEDGER_FIELDS, FEATURE_DELIVERY_RESULT_FIELDS,
                                        ROLE_AGENTS, _worker_runtime_audit_errors)
    except ModuleNotFoundError:
        from scripts.merge_techops_result import FEATURE_REMEDIATION_WORKERS, merged_result_errors
        from scripts.planning_contracts import (FEATURE_DELIVERY_LEDGER_FIELDS, FEATURE_DELIVERY_RESULT_FIELDS,
                                                ROLE_AGENTS, _worker_runtime_audit_errors)
    errors = []
    evidence_ids = {row.get("Evidence ID") for row in packet.get("evidence", []) if isinstance(row, dict)}
    completed = set()
    required_workers = dict(FEATURE_REMEDIATION_WORKERS)
    if require_documenter:
        required_workers["documenter"] = ("handoff", "HD")
    for agent, (worker, _) in required_workers.items():
        ledgers = [row for row in packet.get("workers", []) if isinstance(row, dict)
                   and row.get("Worker") == worker]
        results = [row for row in packet.get("worker_results", []) if isinstance(row, dict)
                   and row.get("Worker") == worker]
        if len(ledgers) != 1 or len(results) != 1:
            errors.append("sentry_remediation_current_result_required:" + worker)
            continue
        ledger, result = ledgers[0], results[0]
        if ROLE_AGENTS.get(ledger.get("Role"), str(ledger.get("Role", "")).lower()) != agent:
            errors.append("sentry_remediation_worker_role_mismatch:" + worker)
        if any(not str(ledger.get(field, "")).strip() for field in FEATURE_DELIVERY_LEDGER_FIELDS):
            errors.append("sentry_remediation_worker_ledger_incomplete:" + worker)
        if any(not str(result.get(field, "")).strip() for field in FEATURE_DELIVERY_RESULT_FIELDS):
            errors.append("sentry_remediation_worker_result_incomplete:" + worker)
        allowed = {"complete", "blocked"} if identity.get("Engineering outcome") == "blocked" else {"complete"}
        if ledger.get("Outcome") != result.get("Outcome") or result.get("Outcome") not in allowed:
            errors.append("sentry_remediation_worker_outcome_invalid:" + worker)
        refs = set(re.findall(r"\bE-[A-Za-z0-9_-]+\b", str(result.get("Evidence / claim refs", ""))))
        if not refs or not refs <= evidence_ids:
            errors.append("sentry_remediation_worker_evidence_required:" + worker)
        if result.get("Outcome") in {"complete", "blocked"}:
            completed.add(worker)
    if errors:
        return errors
    errors.extend(merged_result_errors(packet, bindings, root))
    errors.extend(_worker_runtime_audit_errors(packet, packet_path, completed))
    return list(dict.fromkeys(errors))


def _validate_current_fan_in(packet: dict, packet_path: Path, bindings: dict, playbook: str, profile: str) -> None:
    workers = {str(row.get("Worker")) for row in packet.get("worker_results", [])
               if isinstance(row, dict) and row.get("Worker") and row.get("Outcome") == "complete"}
    ledger_workers = {str(row.get("Worker")) for row in packet.get("workers", [])
                      if isinstance(row, dict) and row.get("Worker") and row.get("Outcome") == "complete"}
    if workers != ledger_workers:
        raise ValueError("coordinator_worker_ledger_mismatch")
    if playbook == "techops_issue_remediation":
        required = {"issue-evidence", "failure-path", "fix-design"}
        if profile == "deep":
            required.update({"repository-integration", "planning-review"})
        if not required <= workers:
            raise ValueError("techops_planning_workers_incomplete")
        try:
            from planning_contracts import _techops_planning_contract_errors
        except ModuleNotFoundError:
            from scripts.planning_contracts import _techops_planning_contract_errors
        errors = _techops_planning_contract_errors(packet, packet_path, pre_handoff=True)
    else:
        try:
            from planning_contracts import feature_delivery_pre_handoff_errors
        except ModuleNotFoundError:
            from scripts.planning_contracts import feature_delivery_pre_handoff_errors
        errors = feature_delivery_pre_handoff_errors(packet_path)
        required = {"feature-context", "impact-analysis", "feature-design"}
        if profile == "deep":
            required.update({"repository-integration", "planning-review"})
        if not required <= workers:
            errors.append("feature_delivery_planning_workers_incomplete")
    if errors:
        raise ValueError(";".join(dict.fromkeys(errors)))


def _passed_synchronization(packet: dict) -> None:
    results = [row for row in packet.get("worker_results", []) if isinstance(row, dict)]
    workers = [str(row.get("Worker", "")) for row in results]
    packet["synchronization"] = [row for row in packet.get("synchronization", [])
                                 if not isinstance(row, dict) or row.get("Stage") != "Planning analytical fan-in"]
    packet["synchronization"].append({
        "Stage": "Planning analytical fan-in",
        "Workers launched": ", ".join(workers),
        "Launch mode / exception": "Current-run provider dispatch ledger",
        "Worker outcomes": "; ".join(f"{row['Worker']}={row['Outcome']}" for row in results),
        "Results summarized": "Yes; accepted result envelopes preserved",
        "Barrier status": "Passed; current-run traces, result artifacts, and planning gates validated",
    })


def _atomic_json(path: Path, value: dict) -> None:
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(value, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--coordinator-model-effort", required=True)
    parser.add_argument("--prompt-conformance", choices=("pass",), required=True)
    parser.add_argument("--state", choices=("ready_for_implementation", "awaiting_input", "blocked"))
    parser.add_argument("--engineering-outcome", choices=("solved", "partially_solved", "blocked"))
    args = parser.parse_args()
    try:
        result = stage(args.packet, coordinator_model_effort=args.coordinator_model_effort,
                       prompt_conformance=args.prompt_conformance, state=args.state,
                       engineering_outcome=args.engineering_outcome)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        print(json.dumps({"status": "blocked", "reason": str(error)}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
