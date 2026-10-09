#!/usr/bin/env python3
"""Validate worker binding delivery and unsafe runtime transitions."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
V40_RUNTIME_FIXTURE = ROOT / "tests" / "fixtures" / "v40_sentry_worker_runtime.json"
V41_CONTEXT_TRACE_FIXTURE = ROOT / "tests" / "fixtures" / "v41_sentry_context_trace.json"
ACTIVE_STATUSES = {"pending_init", "running", "in_progress", "awaiting_dependency"}
TERMINAL_STATUSES = {"completed", "failed", "stopped", "interrupted", "cancelled"}
DESTRUCTIVE_TRANSITIONS = {"interrupt", "close", "replace"}
TRACE_METADATA_KEYS = {
    "description", "expected_errors", "source_task", "source_thread", "fixture", "schema_version",
}
FORBIDDEN_CONTEXT_PATTERNS = (
    ("memory_path", re.compile(r"(?i)(?:^|[/\\])memory\.md(?:$|[/\\])")),
    ("memory_directory", re.compile(r"(?i)(?:^|[/\\])\.codex[/\\]memories(?:$|[/\\])")),
    ("rollout_summary", re.compile(r"(?i)(?:^|[/\\])rollout_summaries(?:$|[/\\])")),
    ("archived_artifact", re.compile(r"(?i)(?:^|[/\\])\.thoughts[/\\][^/\\]+[/\\]runs[/\\]")),
    ("memory_citation", re.compile(r"(?i)<oai-mem-citation>")),
)


def activation_packet_errors(path: Path, expected_agent: str, expected_sha256: str) -> list[str]:
    if not path.is_file():
        return ["activation_packet_unavailable"]
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha256:
        return ["activation_packet_hash_mismatch"]
    try:
        bundle = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return ["activation_packet_invalid"]
    packets = bundle.get("packets")
    if not isinstance(packets, dict) or not isinstance(packets.get(expected_agent), dict):
        return ["activation_packet_agent_unavailable"]
    packet = packets[expected_agent]
    errors: list[str] = []
    if packet.get("required_prefix") != "Coordinator initialization: complete":
        errors.append("activation_packet_prefix_invalid")
    if packet.get("agent") != expected_agent:
        errors.append("activation_packet_agent_mismatch")
    definition = Path(str(packet.get("definition", "")))
    if not definition.is_file():
        errors.append("provider_definition_unavailable")
    elif hashlib.sha256(definition.read_bytes()).hexdigest() != packet.get("definition_sha256"):
        errors.append("provider_definition_hash_mismatch")
    if not str(packet.get("developer_instructions", "")).strip():
        errors.append("provider_instructions_unavailable")
    if not packet.get("model") or not packet.get("effort"):
        errors.append("provider_binding_incomplete")
    contract = packet.get("worker_contract")
    if isinstance(contract, dict) and "output" in contract:
        for field in ("output", "result"):
            if field in contract:
                output = Path(str(contract[field]))
                if not output.is_absolute() or output.resolve().parent != path.parent.resolve():
                    errors.append(f"worker_{field}_outside_current_run")
    budget_path = path.parent / "run_budget.json"
    if budget_path.is_file():
        try:
            budget = json.loads(budget_path.read_text())
            activation_deadline = datetime.fromisoformat(
                str(budget["activation_deadline_at"]).replace("Z", "+00:00")
            )
            if activation_deadline.tzinfo is None:
                raise ValueError
            if datetime.now(UTC) >= activation_deadline.astimezone(UTC):
                errors.append("run_budget_finalization_reserve")
        except (KeyError, ValueError, json.JSONDecodeError, OSError):
            errors.append("run_budget_invalid")
    input_manifest = packet.get("run_input_manifest")
    if not isinstance(input_manifest, dict):
        errors.append("run_input_manifest_not_delivered")
    else:
        if input_manifest.get("status") != "explicit":
            errors.append("run_input_manifest_required")
        if not input_manifest.get("path") or not input_manifest.get("sha256"):
            errors.append("run_input_manifest_metadata_incomplete")
        if not isinstance(input_manifest.get("inputs"), list) or not input_manifest["inputs"]:
            errors.append("run_input_manifest_inputs_missing")
        manifest_path = Path(str(input_manifest.get("path", ""))).expanduser()
        if manifest_path.is_file():
            if hashlib.sha256(manifest_path.read_bytes()).hexdigest() != str(input_manifest.get("sha256")):
                errors.append("run_input_manifest_hash_mismatch")
        elif manifest_path:
            errors.append("run_input_manifest_unavailable")
    bindings_path = path.parent / "role_bindings.json"
    if expected_agent == "documenter" and bindings_path.is_file():
        try:
            bindings = json.loads(bindings_path.read_text())
        except (OSError, json.JSONDecodeError):
            errors.append("role_bindings_invalid")
        else:
            if isinstance(bindings, dict) and bindings.get("playbook") == "feature_delivery":
                try:
                    current = json.loads((path.parent / "finalization_packet.json").read_text())
                    if bindings.get("lifecycle") and current.get("identity", {}).get("Lifecycle") != bindings["lifecycle"]:
                        errors.append("feature_delivery_packet_lifecycle_mismatch")
                except (OSError, ValueError, TypeError, AttributeError):
                    errors.append("feature_delivery_packet_invalid")
                try:
                    from finalize_work_record import feature_delivery_pre_handoff_errors
                except ModuleNotFoundError:  # Imported as scripts.validate_worker_runtime from the repository root.
                    from scripts.finalize_work_record import feature_delivery_pre_handoff_errors
                errors.extend(feature_delivery_pre_handoff_errors(path.parent / "finalization_packet.json"))
            elif isinstance(bindings, dict) and bindings.get("playbook") == "techops_issue_remediation":
                packet_path = path.parent / "finalization_packet.json"
                try:
                    planning = json.loads(packet_path.read_text())
                    if planning.get("identity", {}).get("Lifecycle") == "planning":
                        completed = {row.get("Worker") for row in planning.get("worker_results", [])
                                     if row.get("Outcome") == "complete"}
                        required = {"issue-evidence", "failure-path", "fix-design"}
                        if planning.get("identity", {}).get("Executed profile") == "deep":
                            required.update({"repository-integration", "planning-review"})
                        if not required <= completed:
                            errors.append("techops_pre_handoff_workers_incomplete")
                        try:
                            from finalize_work_record import _techops_planning_contract_errors
                        except ModuleNotFoundError:
                            from scripts.finalize_work_record import _techops_planning_contract_errors
                        errors.extend(_techops_planning_contract_errors(planning, packet_path, pre_handoff=True))
                except (OSError, ValueError, TypeError, AttributeError):
                    errors.append("techops_pre_handoff_packet_invalid")
    return errors


def transition_error(action: str, provider_status: str) -> str | None:
    status = provider_status.strip().lower()
    if action in DESTRUCTIVE_TRANSITIONS and status in ACTIVE_STATUSES:
        return f"unsafe_{action}_while_{status}"
    if action == "close" and status not in TERMINAL_STATUSES:
        return f"close_requires_terminal_status:{status or 'unknown'}"
    if action == "replace" and status not in {"failed", "stopped", "interrupted", "cancelled"}:
        return f"replace_requires_failed_or_stopped_status:{status or 'unknown'}"
    if action == "fan_in" and status != "completed":
        return f"fan_in_requires_completed_status:{status or 'unknown'}"
    return None


def terminal_observation_errors(observations: object, handles: list[str]) -> list[str]:
    """Validate current status reads, including workers omitted by live inventory."""
    if not isinstance(observations, list) or not observations:
        return ["terminal_observations_required"]
    errors: list[str] = []
    observed: set[str] = set()
    for row in observations:
        if not isinstance(row, dict):
            errors.append("terminal_observation_invalid")
            continue
        handle = str(row.get("Provider handle", ""))
        if handle not in handles or handle in observed or not re.fullmatch(
            r"(?:[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}|/root/[a-z0-9_]+(?:/[a-z0-9_]+)*)", handle,
        ):
            errors.append(f"terminal_observation_handle_invalid:{handle}")
        observed.add(handle)
        if str(row.get("Provider status", "")).lower() not in {"completed", "idle"}:
            errors.append(f"terminal_observation_not_terminal:{handle}")
        source = str(row.get("Status source", ""))
        if source not in {"list_agents", "read_thread", "wait_threads"}:
            errors.append(f"terminal_observation_source_invalid:{handle}")
        if source in {"read_thread", "wait_threads"} and not re.fullmatch(
            r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", str(row.get("Thread ID", "")),
        ):
            errors.append(f"terminal_observation_thread_id_required:{handle}")
        try:
            if any(not re.fullmatch(
                r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})", str(row.get(field, "")),
            ) for field in ("Last dispatch at", "Observed at")):
                raise ValueError
            times = [datetime.fromisoformat(str(row[field]).replace("Z", "+00:00"))
                     for field in ("Last dispatch at", "Observed at")]
            if source in {"read_thread", "wait_threads"}:
                started = datetime.fromisoformat(str(row["Latest turn started at"]).replace("Z", "+00:00"))
                # Thread metadata exposes seconds; dispatch receipts may retain subsecond precision.
                fresh_turn = started >= times[0].replace(microsecond=0)
                if (not fresh_turn and row.get("Dispatch consumed") is True
                        and str(row.get("Dispatch consumption evidence", "")).strip()):
                    completed = datetime.fromisoformat(str(row["Latest turn completed at"]).replace("Z", "+00:00"))
                    fresh_turn = (completed.tzinfo is not None and
                                  times[0].replace(microsecond=0) <= completed <= times[1] and started <= completed)
                if started.tzinfo is None or not fresh_turn or started > times[1]:
                    errors.append(f"terminal_observation_latest_turn_stale:{handle}")
                if row.get("Latest turn status") != "completed":
                    errors.append(f"terminal_observation_latest_turn_not_completed:{handle}")
                if row.get("Thread status") not in {"idle", "notLoaded"}:
                    errors.append(f"terminal_observation_thread_not_idle:{handle}")
            if any(value.tzinfo is None for value in times):
                raise ValueError
            if times[1] < times[0]:
                errors.append(f"terminal_observation_stale:{handle}")
        except (KeyError, ValueError, TypeError):
            errors.append(f"terminal_observation_timestamp_invalid:{handle}")
    if observed != set(handles):
        errors.append("terminal_observations_incomplete")
    return list(dict.fromkeys(errors))


TECHOPS_CHECKS = {"issue_scope", "history_reconciliation", "plan_dependencies", "regression_fixture"}


def techops_check_errors(checks: object, evidence_ids: set[str]) -> list[str]:
    if not isinstance(checks, list):
        return ["techops_planning_checks_required"]
    errors: list[str] = []
    seen: set[str] = set()
    for row in checks:
        if not isinstance(row, dict):
            errors.append("techops_planning_check_invalid")
            continue
        name = str(row.get("Check", ""))
        if name not in TECHOPS_CHECKS or name in seen:
            errors.append(f"techops_planning_check_invalid:{name}")
        seen.add(name)
        status = row.get("Status")
        if status != "passed" and not (name == "history_reconciliation" and status == "not_applicable"):
            errors.append(f"techops_planning_check_not_passed:{name}")
        refs = re.findall(r"\bE-[A-Za-z0-9_-]+\b", str(row.get("Evidence refs", "")))
        if not refs or not set(refs) <= evidence_ids or not str(row.get("Detail", "")).strip():
            errors.append(f"techops_planning_check_evidence_required:{name}")
    if seen != TECHOPS_CHECKS:
        errors.append("techops_planning_checks_incomplete")
    return list(dict.fromkeys(errors))


def _trace_strings(value: object, path: tuple[str, ...] = ()):
    """Yield strings from provider tool activity, excluding fixture metadata."""
    if isinstance(value, dict):
        for key, nested in value.items():
            if str(key) in TRACE_METADATA_KEYS:
                continue
            yield from _trace_strings(nested, (*path, str(key)))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            yield from _trace_strings(nested, (*path, str(index)))
    elif isinstance(value, str):
        yield path, value


def context_trace_errors(trace: dict[str, object]) -> list[str]:
    """Reject worker traces that reference unassigned memory or archived runs."""
    if not isinstance(trace, dict):
        return ["tool_trace_invalid"]
    errors: list[str] = []
    declared = str(trace.get("context_conformance", "")).strip().lower()
    if declared in {"fail", "failed", "blocked"}:
        errors.append("context_conformance_failed")
    for _, value in _trace_strings(trace):
        for label, pattern in FORBIDDEN_CONTEXT_PATTERNS:
            if pattern.search(value):
                errors.append(f"forbidden_context_reference:{label}")
                break
    return list(dict.fromkeys(errors))


def trace_errors(trace: dict[str, object]) -> list[str]:
    errors: list[str] = []
    spawn = trace.get("spawn", {})
    if not isinstance(spawn, dict):
        return ["spawn_trace_invalid"]
    observed_role = spawn.get("observed_agent_role")
    observed_path = spawn.get("observed_agent_path")
    if not observed_role and not observed_path and not spawn.get("activation_packet_delivered"):
        errors.append("provider_binding_not_delivered")
    for event in trace.get("events", []):
        if not isinstance(event, dict) or "action" not in event:
            errors.append("runtime_event_invalid")
            continue
        error = transition_error(str(event["action"]), str(event.get("provider_status", "")))
        if error:
            errors.append(error)
    failure = trace.get("analytical_failure", {})
    if isinstance(failure, dict) and failure.get("requested") and not failure.get("artifact_created"):
        if failure.get("evidence_artifact_required"):
            errors.append("analytical_failure_artifact_absent")
    errors.extend(context_trace_errors(trace))
    return errors


def self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="workflow-worker-runtime-") as directory:
        root = Path(directory)
        definition = root / "worker.toml"
        definition.write_text('developer_instructions = "Do bounded work."\nmodel = "gpt-test"\n')
        packet = root / "worker.json"
        manifest_path = root / "run_inputs.json"
        manifest_path.write_text("{\"schema_version\": 1}\n")
        manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        packet.write_text(json.dumps({"packets": {"test_worker": {
            "required_prefix": "Coordinator initialization: complete",
            "agent": "test_worker",
            "definition": str(definition),
            "definition_sha256": hashlib.sha256(definition.read_bytes()).hexdigest(),
            "developer_instructions": "Do bounded work.",
            "model": "gpt-test",
            "effort": "low",
            "run_input_manifest": {
                "path": str(manifest_path),
                "sha256": manifest_sha256,
                "status": "explicit",
                "inputs": [{"Input ID": "USER-001", "Input or artifact": "Current context"}],
            },
        }}}) + "\n")
        packet_sha256 = hashlib.sha256(packet.read_bytes()).hexdigest()
        assert activation_packet_errors(packet, "test_worker", packet_sha256) == []
        documenter_bundle = json.loads(packet.read_text())
        documenter_bundle["packets"]["documenter"] = {
            **documenter_bundle["packets"]["test_worker"], "agent": "documenter",
        }
        packet.write_text(json.dumps(documenter_bundle))
        doc_sha256 = hashlib.sha256(packet.read_bytes()).hexdigest()
        assert activation_packet_errors(packet, "documenter", doc_sha256) == []
        (root / "role_bindings.json").write_text(json.dumps({"playbook": "feature_delivery"}))
        assert "pre-handoff packet unavailable" in " ".join(
            activation_packet_errors(packet, "documenter", doc_sha256)
        )
        (root / "role_bindings.json").write_text("{")
        assert "role_bindings_invalid" in activation_packet_errors(packet, "documenter", doc_sha256)
        (root / "role_bindings.json").write_text(json.dumps({"playbook": "techops_issue_remediation"}))
        assert "techops_pre_handoff_packet_invalid" in activation_packet_errors(packet, "documenter", doc_sha256)
        (root / "finalization_packet.json").write_text(json.dumps({
            "identity": {"Lifecycle": "planning"}, "worker_results": [],
        }))
        assert "techops_pre_handoff_workers_incomplete" in activation_packet_errors(packet, "documenter", doc_sha256)
        (root / "role_bindings.json").unlink()
        packet.write_text(json.dumps({"packets": {"test_worker": documenter_bundle["packets"]["test_worker"]}}))
        packet_sha256 = hashlib.sha256(packet.read_bytes()).hexdigest()
        (root / "run_budget.json").write_text(json.dumps({
            "activation_deadline_at": "2000-01-01T00:00:00Z",
        }))
        assert activation_packet_errors(packet, "test_worker", packet_sha256) == [
            "run_budget_finalization_reserve"
        ]
        (root / "run_budget.json").unlink()
        generated_packet = json.loads(packet.read_text())
        generated_packet["packets"]["test_worker"]["run_input_manifest"]["status"] = "generated_minimum"
        packet.write_text(json.dumps(generated_packet) + "\n")
        generated_sha256 = hashlib.sha256(packet.read_bytes()).hexdigest()
        assert activation_packet_errors(packet, "test_worker", generated_sha256) == [
            "run_input_manifest_required"
        ]
        assert activation_packet_errors(packet, "test_worker", "0" * 64) == [
            "activation_packet_hash_mismatch"
        ]
    trace = json.loads(V40_RUNTIME_FIXTURE.read_text())
    assert trace_errors(trace) == trace["expected_errors"]
    corrected = json.loads(json.dumps(trace))
    corrected["spawn"]["activation_packet_delivered"] = True
    corrected["events"] = [
        {"action": "wait", "provider_status": "running"},
        {"action": "fan_in", "provider_status": "completed"},
        {"action": "close", "provider_status": "completed"},
    ]
    corrected["analytical_failure"]["evidence_artifact_required"] = False
    assert trace_errors(corrected) == []
    context_trace = json.loads(V41_CONTEXT_TRACE_FIXTURE.read_text())
    assert trace_errors(context_trace) == context_trace["expected_errors"]
    clean_trace = json.loads(json.dumps(context_trace))
    clean_trace["tool_trace"] = [{"tool": "exec_command", "arguments": {"cmd": "rg -n 'J3V' current-run.md"}}]
    assert trace_errors(clean_trace) == []
    print("validate_worker_runtime self-test: passed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--activation-packet-bundle", type=Path)
    parser.add_argument("--expected-agent")
    parser.add_argument("--expected-bundle-sha256")
    parser.add_argument("--transition", choices=("wait", "interrupt", "close", "replace", "fan_in"))
    parser.add_argument("--provider-status")
    parser.add_argument("--trace", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    result: dict[str, object] = {"status": "allowed"}
    if args.self_test:
        self_test()
        return 0
    selected_modes = sum(
        bool(value) for value in (
            args.trace,
            args.activation_packet_bundle or args.expected_agent or args.expected_bundle_sha256,
            args.transition or args.provider_status,
        )
    )
    if selected_modes > 1:
        parser.error("activation, transition, and trace validation modes are mutually exclusive")
    if args.trace:
        errors = trace_errors(json.loads(args.trace.read_text()))
    elif args.activation_packet_bundle or args.expected_agent or args.expected_bundle_sha256:
        if not args.activation_packet_bundle or not args.expected_agent or not args.expected_bundle_sha256:
            parser.error(
                "--activation-packet-bundle, --expected-agent, and --expected-bundle-sha256 are required together"
            )
        errors = activation_packet_errors(
            args.activation_packet_bundle.resolve(), args.expected_agent, args.expected_bundle_sha256
        )
        if not errors:
            bundle = json.loads(args.activation_packet_bundle.read_text())
            result["activation_packet"] = bundle["packets"][args.expected_agent]
    elif args.transition or args.provider_status:
        if not args.transition or not args.provider_status:
            parser.error("--transition and --provider-status are required together")
        error = transition_error(args.transition, args.provider_status)
        errors = [error] if error else []
    else:
        parser.error("choose --activation-packet-bundle, --transition, --trace, or --self-test")
    if errors:
        print(json.dumps({"status": "blocked", "errors": errors}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
