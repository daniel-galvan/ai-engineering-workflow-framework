#!/usr/bin/env python3
"""Merge a prepared TechOps analytical result without retyping its evidence."""

import argparse
import json
import re
import tempfile
from pathlib import Path


WORKERS = {
    "current_state_investigator": ("issue-evidence", "ISS"),
    "dependency_analyst": ("failure-path", "FP"),
    "repository_integrator": ("repository-integration", "RI"),
    "solution_architect": ("fix-design", "FD"),
    "reviewer": ("planning-review", "PR"),
}
TABLES = {"evidence": "Evidence ID", "claims": "Claim ID", "decisions": "Decision ID", "actions": "Action ID"}
PREFIXES = {"evidence": "E", "claims": "CL", "decisions": "DE", "actions": "A"}


def merge_result(packet_path: Path, agent: str) -> None:
    root = packet_path.parent.resolve()
    bindings = json.loads((root / "role_bindings.json").read_text())
    if bindings.get("playbook") != "techops_issue_remediation" or agent not in WORKERS:
        raise ValueError("techops_analytical_binding_required")
    contract = bindings["worker_contracts"][agent]
    result_path = Path(contract["result"])
    if result_path.resolve().parent != root:
        raise ValueError("worker_result_outside_current_run")
    result = json.loads(result_path.read_text())
    packet = json.loads(packet_path.read_text())
    if packet["identity"].get("Lifecycle", "") not in {"", "planning"}:
        raise ValueError("techops_planning_packet_required")
    if result.get("run_id") != packet["identity"]["Run ID"]:
        raise ValueError("worker_result_run_mismatch")
    worker, namespace = WORKERS[agent]
    summary = result["worker_result"]
    if summary.get("Worker") != worker or summary.get("Outcome") not in {"complete", "failed", "blocked"}:
        raise ValueError("worker_result_identity_or_outcome_invalid")
    template = json.loads((Path(__file__).resolve().parents[1] / "templates/finalization_packet.json").read_text())
    required = set(template["worker_results"][0])
    if not required <= summary.keys() or any(not str(summary[key]).strip() for key in required):
        raise ValueError("worker_result_summary_incomplete")
    for table, key in TABLES.items():
        incoming = result.get(table, [])
        if not isinstance(incoming, list):
            raise ValueError(f"worker_result_table_invalid:{table}")
        ids = set()
        for row in incoming:
            if not isinstance(row, dict):
                raise ValueError(f"worker_result_row_invalid:{table}")
            identity = row.get(key, "")
            if (not set(template[table][0]) <= row.keys() or not isinstance(identity, str)
                    or not re.fullmatch(rf"{PREFIXES[table]}-{namespace}-[A-Za-z0-9_-]+", identity)
                    or identity in ids):
                raise ValueError(f"worker_result_row_invalid:{table}")
            ids.add(identity)
        packet[table] = [row for row in packet.get(table, [])
                         if row.get(key) and not row[key].startswith(f"{PREFIXES[table]}-{namespace}-")] + incoming
    packet["worker_results"] = [row for row in packet.get("worker_results", [])
                                if row.get("Worker") and row["Worker"] != worker] + [summary]
    if "techops_checks" in result:
        if agent != "solution_architect":
            raise ValueError("techops_checks_owner_invalid")
        try:
            from validate_worker_runtime import techops_check_errors
        except ModuleNotFoundError:
            from scripts.validate_worker_runtime import techops_check_errors
        errors = techops_check_errors(result["techops_checks"], {row["Evidence ID"] for row in packet["evidence"]})
        if errors:
            raise ValueError(";".join(errors))
        packet["techops_checks"] = result["techops_checks"]
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
    args = parser.parse_args()
    try:
        merge_result(args.packet, args.agent)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        print(json.dumps({"status": "blocked", "reason": str(error)}))
        return 2
    print(json.dumps({"status": "merged", "agent": args.agent}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
