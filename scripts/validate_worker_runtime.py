#!/usr/bin/env python3
"""Validate worker binding delivery and unsafe runtime transitions."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
V40_RUNTIME_FIXTURE = ROOT / "tests" / "fixtures" / "v40_sentry_worker_runtime.json"
ACTIVE_STATUSES = {"pending_init", "running", "in_progress", "awaiting_dependency"}
TERMINAL_STATUSES = {"completed", "failed", "stopped", "interrupted", "cancelled"}
DESTRUCTIVE_TRANSITIONS = {"interrupt", "close", "replace"}


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
    return errors


def self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="workflow-worker-runtime-") as directory:
        root = Path(directory)
        definition = root / "worker.toml"
        definition.write_text('developer_instructions = "Do bounded work."\nmodel = "gpt-test"\n')
        packet = root / "worker.json"
        packet.write_text(json.dumps({"packets": {"test_worker": {
            "required_prefix": "Coordinator initialization: complete",
            "agent": "test_worker",
            "definition": str(definition),
            "definition_sha256": hashlib.sha256(definition.read_bytes()).hexdigest(),
            "developer_instructions": "Do bounded work.",
            "model": "gpt-test",
            "effort": "low",
        }}}) + "\n")
        packet_sha256 = hashlib.sha256(packet.read_bytes()).hexdigest()
        assert activation_packet_errors(packet, "test_worker", packet_sha256) == []
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
