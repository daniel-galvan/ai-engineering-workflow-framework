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
FEATURE_REMEDIATION_WORKERS = {
    "implementer": ("implement", "IM"),
    "reviewer": ("review", "RV"),
    "tester": ("validate", "TE"),
}
TABLES = {"evidence": "Evidence ID", "claims": "Claim ID", "decisions": "Decision ID", "actions": "Action ID"}
PREFIXES = {"evidence": "E", "claims": "CL", "decisions": "DE", "actions": "A"}


def merged_result_errors(packet: dict, manifest: dict, root: Path, *, table_projection: bool = False) -> list[str]:
    """Accepted analytical records remain owned by their producing workers."""
    terminal_outcomes = {"complete", "blocked"} if manifest.get("lifecycle") == "remediation" else {"complete"}
    completed = {row.get("Worker") for row in packet.get("worker_results", [])
                 if row.get("Outcome") in terminal_outcomes}
    errors = []
    workers = _workers_for(manifest)
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
    workers = _workers_for(bindings)
    if bindings.get("playbook") not in {"techops_issue_remediation", "feature_delivery", "sentry_issue_remediation"} or agent not in workers:
        raise ValueError("analytical_binding_required")
    if not isinstance(result, dict):
        raise ValueError("worker_result_object_required")
    lifecycle = packet["identity"].get("Lifecycle", "")
    if lifecycle not in {"", "planning", "remediation"}:
        raise ValueError("worker_result_lifecycle_unsupported")
    if lifecycle == "remediation" and bindings.get("playbook") not in {
            "techops_issue_remediation", "feature_delivery", "sentry_issue_remediation"}:
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
                # The owning worker may repair links without rewriting accepted findings.
                reference_field = {"claims": "Evidence refs", "decisions": "Claim refs",
                                   "actions": "Decision ref"}.get(table)
                if (reference_field is None or
                        {k: v for k, v in existing[row[key]].items() if k != reference_field} !=
                        {k: v for k, v in row.items() if k != reference_field}):
                    errors.append(f"worker_result_row_conflict:{row[key]}")
            existing[row[key]] = row
        packet[table] = list(existing.values())
    if not summary_errors:
        packet["worker_results"] = [row for row in packet.get("worker_results", [])
                                    if row.get("Worker") and row["Worker"] != worker] + [summary]
    known_ids = {row[key] for table, key in TABLES.items() for row in packet.get(table, [])}
    known_ids.update(row[key] for table, key in TABLES.items() if isinstance(result.get(table), list)
                     for row in result[table] if isinstance(row, dict) and isinstance(row.get(key), str))
    for table, field, target in (("claims", "Evidence refs", "evidence"),
                                 ("decisions", "Claim refs", "claims"),
                                 ("actions", "Decision ref", "decisions")):
        allowed = {row[TABLES[target]] for row in packet[target]}
        for row in packet[table]:
            for reference in re.findall(r"\b[A-Za-z][A-Za-z0-9_]*-[A-Za-z0-9][A-Za-z0-9_-]*\b",
                                        row.get(field, "")):
                if reference not in allowed:
                    errors.append(f"worker_result_reference_type_invalid:{table}:{row[TABLES[table]]}:{field}:{reference}:expected_{target}_id")
    for rows in (packet["worker_results"], packet["claims"], packet["decisions"], packet["actions"]):
        for row in rows:
            for field, value in row.items():
                if "ref" in field.lower() and isinstance(value, str):
                    for reference in re.findall(r"\b(?:E|CL|DE|A)-[A-Za-z0-9_]+-[A-Za-z0-9_-]+", value):
                        if reference not in known_ids:
                            errors.append(f"worker_result_reference_unresolved:{reference}")
    if (lifecycle != "remediation" and
            (contract.get("planning_disposition_required") or "plan_readiness" in result
             or "implementation_plan_action" in result)):
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


def _workers_for(bindings: dict) -> dict[str, tuple[str, str]]:
    if (bindings.get("playbook") in {"techops_issue_remediation", "feature_delivery", "sentry_issue_remediation"}
            and bindings.get("lifecycle") == "remediation"):
        return FEATURE_REMEDIATION_WORKERS
    return FEATURE_WORKERS if bindings.get("playbook") == "feature_delivery" else WORKERS


def _coordinator_worker_row(packet: dict, agent: str, result: dict, trace: dict, bindings: dict) -> dict:
    """Record worker metadata only from accepted result, prepared dispatch, and provider trace."""
    try:
        from runtime_checks import _tool_operations, _verified_dispatch_content
    except ModuleNotFoundError:
        from scripts.runtime_checks import _tool_operations, _verified_dispatch_content
    content = _verified_dispatch_content(trace)
    if not content:
        raise ValueError("worker_dispatch_assignment_unverified:" + agent)
    try:
        assignment = json.loads(content.split("\nTyped assignment:\n", 1)[1])
    except (ValueError, IndexError) as error:
        raise ValueError("worker_dispatch_assignment_invalid:" + agent) from error
    worker = str(result.get("worker_result", {}).get("Worker", ""))
    audit = next((row for row in packet.get("runtime_audits", []) if row.get("Worker") == worker), None)
    if not isinstance(audit, dict) or audit.get("Provider status") not in {"completed", "idle"}:
        raise ValueError("worker_provider_observation_required:" + worker)
    launch = trace.get("launch", {})
    configured = bindings.get("bindings", {}).get(agent, {})
    model, effort = launch.get("model"), launch.get("reasoning_effort")
    if not isinstance(model, str) or not isinstance(effort, str):
        raise ValueError("worker_launch_binding_unavailable:" + worker)
    if (model, effort) != (configured.get("model"), configured.get("effort")):
        raise ValueError("worker_launch_binding_mismatch:" + worker)
    runtime = next((row for row in reversed(trace.get("runtime_configurations", []))
                    if isinstance(row, dict)), {})
    activation = trace.get("activation_metadata", {})
    if not isinstance(activation, dict):
        activation = {}
    observed_model = runtime.get("model") or activation.get("model")
    observed_effort = runtime.get("effort") or activation.get("effort")
    if isinstance(observed_model, str) and isinstance(observed_effort, str):
        observed_model_effort = f"{observed_model} / {observed_effort}"
    elif observed_model or observed_effort:
        observed_model_effort = (
            f"Not exposed; partial provider telemetry model={observed_model or 'unavailable'}, "
            f"effort={observed_effort or 'unavailable'}; explicit launch binding {model} / {effort}"
        )
    else:
        observed_model_effort = f"Not exposed; explicit launch binding {model} / {effort}"
    inputs = assignment.get("input_paths", [])
    contract = bindings.get("worker_contracts", {}).get(agent, {})
    summary = result.get("worker_result", {})
    tools = []
    for item in trace.get("tool_trace", []):
        for name, _ in _tool_operations(item):
            if name not in tools:
                tools.append(name)
    return {
        "Worker": worker,
        "Role": agent,
        "Assigned inputs": "; ".join(inputs) if inputs else "None recorded in typed assignment",
        "Mode": str(packet.get("identity", {}).get("Lifecycle", "planning")),
        "Depth": str(packet.get("identity", {}).get("Requested profile", "Unknown")),
        "Skills": "Prepared role contract: " + Path(str(contract.get("contract", "Unknown"))).name,
        "Tools": ", ".join(tools) if tools else "No tool operations recorded in current worker trace",
        "Capacity": "Not exposed by provider",
        "Configured model/effort": f"{configured.get('model')} / {configured.get('effort')}",
        "Provider-observed model/effort": observed_model_effort,
        "Usage": "Not exposed by provider",
        "Depends on": "Current-run inputs listed in the typed assignment",
        "Outcome": summary.get("Outcome", "Unknown"),
        "Confidence": summary.get("Confidence", "Unknown"),
    }


def _register_coordinator_worker(packet: dict, agent: str, result: dict, trace: dict, bindings: dict) -> None:
    row = _coordinator_worker_row(packet, agent, result, trace, bindings)
    rows = packet.setdefault("workers", [])
    matches = [index for index, current in enumerate(rows) if current.get("Worker") == row["Worker"]]
    if len(matches) > 1:
        raise ValueError("coordinator_worker_ledger_duplicate:" + row["Worker"])
    if matches:
        current = rows[matches[0]]
        if current.get("Role") != agent:
            raise ValueError("coordinator_worker_ledger_conflict:" + row["Worker"])
        # A validated follow-up can revise the accepted result for this role.
        # Keep the ledger aligned with the latest accepted result; every dispatch
        # remains independently represented in runtime_audits.
        rows[matches[0]] = row
    else:
        rows.append(row)


def _write_text(path: Path, value: str) -> None:
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(value)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


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
    workers = _workers_for(bindings)
    if bindings.get("playbook") not in {"techops_issue_remediation", "feature_delivery", "sentry_issue_remediation"} or agent not in workers:
        raise ValueError("analytical_binding_required")
    if agent in _pending_rejections(root):
        raise ValueError("worker_result_recovery_authorization_required:" + agent)
    contract = bindings["worker_contracts"][agent]
    canonical_result_path = Path(contract["result"])
    if canonical_result_path.resolve().parent != root:
        raise ValueError("worker_result_outside_current_run")
    canonical_output_path = Path(contract["output"])
    if canonical_output_path.resolve().parent != root:
        raise ValueError("worker_output_outside_current_run")
    asset_manifest_output = None
    if contract.get("asset_inventory"):
        asset_manifest_output = Path(contract["asset_inventory"]["output"])
        if asset_manifest_output.resolve().parent != root:
            raise ValueError("worker_asset_manifest_outside_current_run")
    packet = json.loads(packet_path.read_text())
    worker, _ = workers[agent]
    trace_value, output, asset_manifest = None, None, None
    if contract.get("result_hash_required"):
        audit = next((row for row in packet.get("runtime_audits", []) if row.get("Worker") == worker), None)
        trace_path = trace or (Path(audit["Trace path"]) if audit and audit.get("Trace path") else None)
        if trace_path is None:
            raise ValueError("worker_result_trace_required:" + worker)
        if not trace_path.is_absolute():
            execution_repository_path = trace_path.resolve()
            trace_path = execution_repository_path if execution_repository_path.exists() else root / trace_path
        trace_path = trace_path.resolve()
        if trace_path.parent != root:
            raise ValueError("worker_trace_outside_current_run:" + worker)
        try:
            from planning_contracts import worker_audit_record
        except ModuleNotFoundError:
            from scripts.planning_contracts import worker_audit_record
        audit = worker_audit_record(packet_path, worker, trace_path)
        packet["runtime_audits"] = [row for row in packet.get("runtime_audits", [])
                                    if row.get("Worker") != worker] + [audit]
        trace_value = json.loads(trace_path.read_text())
        try:
            from runtime_checks import result_artifact_errors
        except ModuleNotFoundError:
            from scripts.runtime_checks import result_artifact_errors
        errors = result_artifact_errors(trace_value, bindings, root, agent)
        if errors:
            raise ValueError(";".join(errors))
        receipt = trace_value["result_artifact"]
        staged_result_path = Path(receipt["path"])
        staged_output_path = Path(receipt["output_path"])
        if staged_result_path.resolve().parent.parent.parent != (root / ".worker_responses").resolve():
            raise ValueError("worker_result_outside_current_run")
        result = json.loads(staged_result_path.read_text())
        output = staged_output_path.read_text()
        if contract.get("asset_inventory"):
            asset_manifest_path = Path(receipt["asset_manifest_path"])
            if asset_manifest_path.resolve().parent != staged_result_path.resolve().parent:
                raise ValueError("worker_asset_manifest_outside_current_run")
            asset_manifest = asset_manifest_path.read_text()
    else:
        if not canonical_result_path.is_file():
            raise ValueError("worker_result_source_missing:" + worker)
        result = json.loads(canonical_result_path.read_text())
    if contract.get("result_hash_required"):
        ledger = bindings.get("runtime_evidence", {}).get("ledger")
        if not ledger or not Path(ledger).is_file():
            raise ValueError("worker_runtime_ledger_required:" + worker)
    packet = validated_result(packet, result, bindings, agent)
    if trace_value is not None:
        _register_coordinator_worker(packet, agent, result, trace_value, bindings)
    if output is not None:
        _write_text(canonical_output_path, output)
        _write_text(canonical_result_path, json.dumps(result, indent=2, ensure_ascii=False) + "\n")
        if asset_manifest is not None:
            _write_text(asset_manifest_output, asset_manifest)
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
    parser.add_argument("--agent", required=True,
                        help="Prepared provider role from role_bindings.json")
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
