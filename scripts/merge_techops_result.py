#!/usr/bin/env python3
"""Merge a prepared TechOps or Feature Delivery analytical result without retyping evidence."""

import argparse
import copy
import json
import re
import tempfile
from pathlib import Path


try:
    from packet_schema import shape_errors
except ModuleNotFoundError:
    from scripts.packet_schema import shape_errors


WORKERS = {
    "current_state_investigator": ("issue-evidence", "ISS"),
    "dependency_analyst": ("failure-path", "FP"),
    "repository_integrator": ("repository-integration", "RI"),
    "solution_architect": ("fix-design", "FD"),
    "reviewer": ("planning-review", "PR"),
}
FEATURE_WORKERS = {
    "current_state_investigator": ("feature-context", "FC"),
    "dependency_analyst": ("impact-analysis", "IA"),
    "repository_integrator": ("repository-integration", "RI"),
    "solution_architect": ("feature-design", "FD"),
    "reviewer": ("planning-review", "PR"),
}
TABLES = {"evidence": "Evidence ID", "claims": "Claim ID", "decisions": "Decision ID", "actions": "Action ID"}
PREFIXES = {"evidence": "E", "claims": "CL", "decisions": "DE", "actions": "A"}


def merged_result_errors(packet: dict, manifest: dict, root: Path, *, table_projection: bool = False) -> list[str]:
    """Accepted analytical records remain owned by their producing workers."""
    completed = {row.get("Worker") for row in packet.get("worker_results", []) if row.get("Outcome") == "complete"}
    errors = []
    workers = FEATURE_WORKERS if manifest.get("playbook") == "feature_delivery" else WORKERS
    for agent, (worker, _) in workers.items():
        contract = manifest.get("worker_contracts", {}).get(agent, {})
        if worker not in completed or not contract.get("result"):
            continue
        source = Path(contract["result"])
        if source.resolve().parent != root.resolve() or not source.is_file():
            errors.append("worker_result_source_missing:" + worker)
            continue
        result = json.loads(source.read_text())
        for table, key in TABLES.items():
            current = {row.get(key): row for row in packet.get(table, [])}
            for row in result.get(table, []):
                expected = ({name: str(value).replace("\n", "<br>").strip() for name, value in row.items()}
                            if table_projection else row)
                if current.get(row.get(key)) != expected:
                    errors.append("worker_owned_record_changed:" + worker + ":" + table + ":" + str(row.get(key)))
    return errors


def validated_result(packet: dict, result: dict, bindings: dict, agent: str) -> dict:
    """Apply the shared analytical contract in memory before audit or durable acceptance."""
    packet = copy.deepcopy(packet)
    workers = FEATURE_WORKERS if bindings.get("playbook") == "feature_delivery" else WORKERS
    if bindings.get("playbook") not in {"techops_issue_remediation", "feature_delivery"} or agent not in workers:
        raise ValueError("analytical_binding_required")
    if not isinstance(result, dict):
        raise ValueError("worker_result_object_required")
    if packet["identity"].get("Lifecycle", "") not in {"", "planning"}:
        raise ValueError("techops_planning_packet_required")
    if result.get("run_id") != packet["identity"]["Run ID"]:
        raise ValueError("worker_result_run_mismatch")
    worker, namespace = workers[agent]
    contract = bindings["worker_contracts"][agent]
    summary = result.get("worker_result")
    template = json.loads((Path(__file__).resolve().parents[1] / "templates/finalization_packet.json").read_text())
    required = set(template["worker_results"][0])
    errors = []
    summary_errors = shape_errors(summary, template["worker_results"][0], "worker_result")
    if summary_errors:
        errors.extend(["worker_result_summary_schema_invalid", *summary_errors])
    valid_tables = set()
    for table in TABLES:
        incoming = result.get(table, [])
        table_errors = shape_errors(incoming, template[table], table)
        if table_errors:
            label = "table" if not isinstance(incoming, list) else "row"
            errors.extend([f"worker_result_{label}_invalid:{table}", *table_errors])
        else:
            valid_tables.add(table)
    if not summary_errors:
        if summary.get("Worker") != worker or summary.get("Outcome") not in {"complete", "failed", "blocked"}:
            errors.append("worker_result_identity_or_outcome_invalid")
        if any(not summary[key].strip() for key in required):
            errors.append("worker_result_summary_incomplete")
    for table, key in TABLES.items():
        if table not in valid_tables:
            continue
        incoming = result.get(table, [])
        ids = set()
        for row in incoming:
            identity = row.get(key, "")
            if (not re.fullmatch(rf"{PREFIXES[table]}-{namespace}-[A-Za-z0-9_-]+", identity)
                    or identity in ids):
                errors.append(f"worker_result_row_invalid:{table}")
            ids.add(identity)
        existing_rows = [row for row in packet.get(table, []) if row.get(key)]
        existing = {row[key]: row for row in existing_rows}
        if len(existing) != len(existing_rows):
            errors.append(f"worker_result_existing_ids_duplicate:{table}")
        for row in incoming:
            if row[key] in existing and existing[row[key]] != row:
                errors.append(f"worker_result_row_conflict:{row[key]}")
            existing[row[key]] = row
        packet[table] = list(existing.values())
    if not summary_errors:
        packet["worker_results"] = [row for row in packet.get("worker_results", [])
                                    if row.get("Worker") and row["Worker"] != worker] + [summary]
    known_ids = {row[key] for table, key in TABLES.items() for row in packet.get(table, [])}
    known_ids.update(row[key] for table, key in TABLES.items() if isinstance(result.get(table), list)
                     for row in result[table] if isinstance(row, dict) and isinstance(row.get(key), str))
    for rows in (packet["worker_results"], packet["claims"], packet["decisions"], packet["actions"]):
        for row in rows:
            for field, value in row.items():
                if "ref" in field.lower() and isinstance(value, str):
                    for reference in re.findall(r"\b(?:E|CL|DE|A)-[A-Za-z0-9_]+-[A-Za-z0-9_-]+", value):
                        if reference not in known_ids:
                            errors.append(f"worker_result_reference_unresolved:{reference}")
    if contract.get("planning_disposition_required") or "plan_readiness" in result or "implementation_plan_action" in result:
        pair = (result.get("plan_readiness"), result.get("implementation_plan_action"))
        if (bindings.get("playbook") != "feature_delivery" or agent != "solution_architect"
                or not all(isinstance(value, str) for value in pair)
                or pair not in {("ready_for_implementation", "create"), ("awaiting_input", "create_draft"),
                                ("awaiting_input", "omit")}):
            errors.append("feature_planning_disposition_invalid")
        else:
            packet["planning_disposition"] = {key: result[key] for key in ("plan_readiness", "implementation_plan_action")}
    if "techops_checks" in result or (
            bindings.get("playbook") == "techops_issue_remediation" and agent == "solution_architect"
            and isinstance(summary, dict) and summary.get("Outcome") == "complete"):
        if agent != "solution_architect" or bindings.get("playbook") != "techops_issue_remediation":
            errors.append("techops_checks_owner_invalid")
        try:
            from validate_worker_runtime import techops_check_errors
        except ModuleNotFoundError:
            from scripts.validate_worker_runtime import techops_check_errors
        errors.extend(techops_check_errors(result.get("techops_checks"), {row["Evidence ID"] for row in packet["evidence"]}))
        packet["techops_checks"] = result.get("techops_checks")
    if errors:
        raise ValueError("; ".join(dict.fromkeys(errors)))
    return packet


def merge_result(packet_path: Path, agent: str, *, trace: Path | None = None) -> None:
    root = packet_path.parent.resolve()
    try:
        from validate_worker_runtime import prepared_package_errors, _pending_rejections
    except ModuleNotFoundError:
        from scripts.validate_worker_runtime import prepared_package_errors, _pending_rejections
    errors = prepared_package_errors(root)
    if errors:
        raise ValueError(";".join(errors))
    bindings = json.loads((root / "role_bindings.json").read_text())
    workers = FEATURE_WORKERS if bindings.get("playbook") == "feature_delivery" else WORKERS
    if bindings.get("playbook") not in {"techops_issue_remediation", "feature_delivery"} or agent not in workers:
        raise ValueError("analytical_binding_required")
    if agent in _pending_rejections(root):
        raise ValueError("worker_result_recovery_authorization_required:" + agent)
    contract = bindings["worker_contracts"][agent]
    result_path = Path(contract["result"])
    if result_path.resolve().parent != root:
        raise ValueError("worker_result_outside_current_run")
    result = json.loads(result_path.read_text())
    packet = json.loads(packet_path.read_text())
    worker, _ = workers[agent]
    if trace is not None:
        try:
            from planning_contracts import worker_audit_record
        except ModuleNotFoundError:
            from scripts.planning_contracts import worker_audit_record
        audit = worker_audit_record(packet_path, worker, trace)
        packet["runtime_audits"] = [row for row in packet.get("runtime_audits", [])
                                    if row.get("Worker") != worker] + [audit]
    if contract.get("result_hash_required"):
        audit = next((row for row in packet.get("runtime_audits", []) if row.get("Worker") == worker), None)
        ledger = bindings.get("runtime_evidence", {}).get("ledger")
        if audit is None and ledger and Path(ledger).is_file():
            raise ValueError("worker_result_audit_required:" + worker
                             + ": Coordinator must rerun this merger with --trace <passed-current-run-trace>; "
                               "missing Coordinator audit bookkeeping is not a worker rejection")
        if audit is not None:
            try:
                from runtime_checks import result_artifact_errors
            except ModuleNotFoundError:
                from scripts.runtime_checks import result_artifact_errors
            trace_path = Path(audit.get("Trace path", ""))
            trace_path = trace_path if trace_path.is_absolute() else root / trace_path
            if trace_path.resolve().parent != root:
                raise ValueError("worker_trace_outside_current_run:" + worker)
            errors = result_artifact_errors(json.loads(trace_path.read_text()), bindings, root, agent)
            if errors:
                raise ValueError(";".join(errors))
    packet = validated_result(packet, result, bindings, agent)
    with tempfile.NamedTemporaryFile("w", dir=root, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(packet, stream, indent=2)
            stream.write("\n")
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        temporary.replace(packet_path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--agent", choices=tuple(WORKERS), required=True)
    parser.add_argument("--trace", type=Path, help="Validate and register the completed worker trace atomically with its result")
    args = parser.parse_args()
    try:
        merge_result(args.packet, args.agent, trace=args.trace)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        print(json.dumps({"status": "blocked", "reason": str(error)}))
        return 2
    print(json.dumps({"status": "merged", "agent": args.agent}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
