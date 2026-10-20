#!/usr/bin/env python3
"""Validate worker binding delivery and unsafe runtime transitions."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path


# Same-name aliases preserve compatibility exports and make that intent explicit to static analyzers.
try:
    from runtime_checks import (
        prepared_package_errors,
        worker_binding,
        trace_identity_errors as trace_identity_errors,
        activation_message,
        dispatch_message,
        dispatch_notice,
        delivery_start_errors,
        transition_error,
        rejected_result_errors,
        terminal_observation_errors as terminal_observation_errors,
        techops_check_errors as techops_check_errors,
        _trace_strings as _trace_strings,
        _listing_command as _listing_command,
        _listing_outputs as _listing_outputs,
        _verified_dispatch_content as _verified_dispatch_content,
        _authorized_read as _authorized_read,
        _literal_argument as _literal_argument,
        _tool_operations as _tool_operations,
        _python_read_targets as _python_read_targets,
        _read_targets as _read_targets,
        _read_output_prefixes as _read_output_prefixes,
        observed_dispatch_binding as observed_dispatch_binding,
        _instruction_contents as _instruction_contents,
        _ancestor_instruction_reads as _ancestor_instruction_reads,
        context_trace_errors as context_trace_errors,
        trace_errors,
    )
except ModuleNotFoundError:
    from scripts.runtime_checks import (
        prepared_package_errors,
        worker_binding,
        trace_identity_errors as trace_identity_errors,
        activation_message,
        dispatch_message,
        dispatch_notice,
        delivery_start_errors,
        transition_error,
        rejected_result_errors,
        terminal_observation_errors as terminal_observation_errors,
        techops_check_errors as techops_check_errors,
        _trace_strings as _trace_strings,
        _listing_command as _listing_command,
        _listing_outputs as _listing_outputs,
        _verified_dispatch_content as _verified_dispatch_content,
        _authorized_read as _authorized_read,
        _literal_argument as _literal_argument,
        _tool_operations as _tool_operations,
        _python_read_targets as _python_read_targets,
        _read_targets as _read_targets,
        _read_output_prefixes as _read_output_prefixes,
        observed_dispatch_binding as observed_dispatch_binding,
        _instruction_contents as _instruction_contents,
        _ancestor_instruction_reads as _ancestor_instruction_reads,
        context_trace_errors as context_trace_errors,
        trace_errors,
    )


try:
    from runtime_checks import (
        ACTIVE_STATUSES as ACTIVE_STATUSES,
        TERMINAL_STATUSES as TERMINAL_STATUSES,
        DESTRUCTIVE_TRANSITIONS as DESTRUCTIVE_TRANSITIONS,
        TRACE_METADATA_KEYS as TRACE_METADATA_KEYS,
        FORBIDDEN_CONTEXT_PATTERNS,
    )
except ModuleNotFoundError:
    from scripts.runtime_checks import (
        ACTIVE_STATUSES as ACTIVE_STATUSES,
        TERMINAL_STATUSES as TERMINAL_STATUSES,
        DESTRUCTIVE_TRANSITIONS as DESTRUCTIVE_TRANSITIONS,
        TRACE_METADATA_KEYS as TRACE_METADATA_KEYS,
        FORBIDDEN_CONTEXT_PATTERNS,
    )


try:
    from runtime_checks import TECHOPS_CHECKS as TECHOPS_CHECKS, THOUGHT_PATH as THOUGHT_PATH
except ModuleNotFoundError:
    from scripts.runtime_checks import TECHOPS_CHECKS as TECHOPS_CHECKS, THOUGHT_PATH as THOUGHT_PATH


ROOT = Path(__file__).resolve().parents[1]
V40_RUNTIME_FIXTURE = ROOT / "tests" / "fixtures" / "sentry_worker_runtime.json"
V41_CONTEXT_TRACE_FIXTURE = ROOT / "tests" / "fixtures" / "sentry_context_trace.json"
DELIVERY_WORKERS = {"implement": "implementer", "review": "reviewer", "validate": "tester", "handoff": "documenter"}


def _pending_rejections(root: Path) -> dict:
    ledger_path = root / "runtime_dispatches.json"
    if not ledger_path.exists():
        return {}
    ledger = json.loads(ledger_path.read_text())
    current = json.loads((root / "finalization_packet.json").read_text())["identity"]["Run ID"]
    pending = ledger.get("rejected_results", {})
    if not isinstance(pending, dict):
        raise ValueError("worker_rejection_receipt_invalid")
    for receipt in pending.values():
        path = Path(receipt["trace"])
        if (receipt["run_id"] != current or path.resolve().parent != root.resolve()
                or hashlib.sha256(path.read_bytes()).hexdigest() != receipt["sha256"]):
            raise ValueError("worker_rejection_receipt_invalid")
    return pending


def _recovery_errors(path: Path, role: str, handle: str, dispatch: str, provider_status: str) -> list[str]:
    try:
        trace = json.loads(path.read_text())
        current = json.loads((path.parent / "finalization_packet.json").read_text())
        bindings = json.loads((path.parent / "role_bindings.json").read_text())
        role = worker_binding(bindings, role)
        if (trace.get("run_id") != current["identity"]["Run ID"]
                or worker_binding(bindings, trace["spawn"].get("agent") or trace["spawn"].get("expected_agent")) != role):
            return ["rejected_result_current_binding_required"]
        errors = rejected_result_errors(trace, handle, dispatch)
        try:
            from provider_runtime import launch_binding_errors
        except ModuleNotFoundError:
            from scripts.provider_runtime import launch_binding_errors
        if "launch_errors" in trace and trace["launch_errors"] != launch_binding_errors(trace, path.parent, role):
            errors.append("rejected_result_launch_errors_mismatch")
        error = transition_error("replace", provider_status, rejected_result=not errors)
        if error:
            errors.append(error)
        if role in current.get("activation_repairs", {}):
            errors.append("activation_repair_limit_reached")
        return errors
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        return ["rejected_result_trace_invalid:" + str(error)]


def activation_packet_errors(path: Path, expected_agent: str, expected_sha256: str,
                             *, rejected_trace_sha256: str | None = None,
                             recovery_required: dict | None = None) -> list[str]:
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
    errors: list[str] = prepared_package_errors(path.parent) if (path.parent / "role_bindings.json").is_file() else []
    try:
        bindings_path = path.parent / "role_bindings.json"
        parent = json.loads(bindings_path.read_text()).get("parent_context") if bindings_path.is_file() else None
        if parent:
            try:
                from provider_runtime import parent_context_audit
            except ModuleNotFoundError:
                from scripts.provider_runtime import parent_context_audit
            current = parent_context_audit(Path(parent["provider_session"]), artifact_root=path.parent,
                input_paths=tuple(parent["input_paths"]), expected_thread_id=parent["parent_thread_id"])
            if current["status"] != "passed":
                errors.append("parent_context_nonconformant:" + ";".join(current["errors"]))
            if current["turn_id"] != parent["turn_id"]:
                errors.append("parent_context_turn_mismatch:expected=" + parent["turn_id"]
                              + ";received=" + current["turn_id"] + ";prepare the current continuation")
            if parent["run_id"] != packet.get("run_id"):
                errors.append("parent_context_run_mismatch")
    except (OSError, ValueError, KeyError, TypeError, AttributeError, StopIteration) as error:
        errors.append("parent_context_evidence_invalid:" + str(error))
    failure_path = path.parent / "finalization_failure.json"
    if failure_path.is_file():
        try:
            failure = json.loads(failure_path.read_text())
            recovery = False
            bindings_path = path.parent / "role_bindings.json"
            if expected_agent == "documenter" and rejected_trace_sha256 and bindings_path.is_file():
                bindings = json.loads(bindings_path.read_text())
                receipt = bindings.get("handoff_recovery", {})
                current_identity = json.loads((path.parent / "finalization_packet.json").read_text())["identity"]
                recovery = (bindings.get("playbook") == "techops_issue_remediation"
                            and current_identity.get("Lifecycle") == "planning"
                            and receipt.get("run_id") == failure.get("run_id") == packet.get("run_id")
                            and receipt.get("failure_sha256") == hashlib.sha256(failure_path.read_bytes()).hexdigest())
            if failure.get("status") == "failed" and (
                    (failure.get("stage") == "workflow" and not recovery)
                    or int(failure.get("attempt_count", 0)) >= 2):
                errors.append("worker_activation_requires_planning_recovery")
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            errors.append("worker_activation_failure_receipt_invalid")
    try:
        for role, receipt in _pending_rejections(path.parent).items():
            if role != expected_agent or receipt["sha256"] != rejected_trace_sha256:
                errors.append("worker_activation_rejected_result_pending:" + role)
                if recovery_required is not None and not recovery_required:
                    recovery_required.update({
                        "agent": role, "rejected_trace": receipt["trace"],
                        "provider_handle": receipt["Provider handle"], "last_dispatch_at": receipt["Last dispatch at"],
                        "required_options": ["--rejected-trace", "--provider-handle", "--last-dispatch-at", "--provider-status"],
                        "next_action": "Run corrected activation with these options and a fresh terminal provider status.",
                    })
    except (OSError, ValueError, TypeError, KeyError) as error:
        errors.append("worker_rejection_receipt_invalid:" + str(error))
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
    if "run_id" in packet or "finalization_packet" in packet:
        current_path = path.parent / "finalization_packet.json"
        try:
            current = json.loads(current_path.read_text())
            if (not packet.get("run_id") or packet["run_id"] != current["identity"]["Run ID"]
                    or packet.get("finalization_packet") != str(current_path.resolve())):
                errors.append("worker_run_identity_mismatch")
            if packet.get("lifecycle") and packet["lifecycle"] != current["identity"].get("Lifecycle"):
                errors.append("worker_lifecycle_mismatch:expected=" + packet["lifecycle"]
                              + ";received=" + str(current["identity"].get("Lifecycle")))
        except (OSError, ValueError, KeyError, TypeError):
            errors.append("worker_run_identity_unavailable")
    elif isinstance(contract, dict) and "run_id" in str(contract.get("result_instructions", "")):
        errors.append("worker_run_identity_not_delivered")
    if isinstance(contract, dict) and "output" in contract:
        for field in ("output", "result", "implementation_plan"):
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
                    from planning_contracts import feature_delivery_pre_handoff_errors
                except ModuleNotFoundError:  # Imported as scripts.validate_worker_runtime from the repository root.
                    from scripts.planning_contracts import feature_delivery_pre_handoff_errors
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
                            from planning_contracts import _techops_planning_contract_errors
                        except ModuleNotFoundError:
                            from scripts.planning_contracts import _techops_planning_contract_errors
                        errors.extend(_techops_planning_contract_errors(planning, packet_path, pre_handoff=True))
                except (OSError, ValueError, TypeError, AttributeError):
                    errors.append("techops_pre_handoff_packet_invalid")
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
    parser.add_argument("--before-source-change", type=Path)
    parser.add_argument("--implementer-handle")
    parser.add_argument("--rejected-trace", type=Path)
    parser.add_argument("--provider-handle")
    parser.add_argument("--last-dispatch-at")
    parser.add_argument("--trace", type=Path)
    parser.add_argument("--require-freshness", action="store_true")
    parser.add_argument("--assignment", type=Path)
    parser.add_argument("--activation-message", type=Path)
    parser.add_argument("--dispatch-file", type=Path,
                        help="Save complete guarded instructions and return a compact canonical launch message")
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
            args.transition or (args.provider_status and not (args.before_source_change or args.activation_packet_bundle)),
            args.before_source_change,
        )
    )
    if selected_modes > 1:
        parser.error("activation, transition, trace and before-source-change modes are mutually exclusive")
    if args.implementer_handle and not args.before_source_change:
        parser.error("--implementer-handle requires --before-source-change")
    if args.require_freshness and not args.trace:
        parser.error("--require-freshness requires --trace")
    if any((args.rejected_trace, args.provider_handle, args.last_dispatch_at)) and (
            not (args.transition == "replace" or args.activation_packet_bundle)
            or not all((args.rejected_trace, args.provider_handle, args.last_dispatch_at, args.provider_status))):
        parser.error("recovery requires activation or replace, rejected trace, provider handle, dispatch and status")
    if args.rejected_trace and args.activation_packet_bundle and not (args.assignment and args.dispatch_file):
        parser.error("corrected activation requires --assignment and --dispatch-file")
    if args.dispatch_file and not args.assignment:
        parser.error("--dispatch-file requires --assignment in activation mode")
    if (args.assignment or args.activation_message or args.dispatch_file) and not args.activation_packet_bundle:
        parser.error("--assignment, --activation-message and --dispatch-file require activation mode")
    if args.before_source_change:
        if not args.implementer_handle or not args.provider_status:
            parser.error("--before-source-change requires --implementer-handle and --provider-status")
        errors = delivery_start_errors(args.before_source_change.resolve(), args.implementer_handle, args.provider_status)
    elif args.trace:
        try:
            context_details = []
            errors = trace_errors(json.loads(args.trace.read_text()), require_freshness=args.require_freshness,
                                  context_details=context_details)
            if context_details:
                result["context_violations"] = context_details
        except (OSError, ValueError, TypeError) as error:
            errors = [f"tool_trace_invalid:{error}"]
    elif args.activation_packet_bundle or args.expected_agent or args.expected_bundle_sha256:
        if not args.activation_packet_bundle or not args.expected_agent or not args.expected_bundle_sha256:
            parser.error(
                "--activation-packet-bundle, --expected-agent, and --expected-bundle-sha256 are required together"
            )
        errors = []
        rejection_hash = None
        if args.rejected_trace:
            if args.rejected_trace.resolve().parent != args.activation_packet_bundle.resolve().parent:
                errors.append("rejected_result_current_run_required")
            else:
                errors.extend(_recovery_errors(args.rejected_trace, args.expected_agent, args.provider_handle,
                                               args.last_dispatch_at, args.provider_status))
                if not errors:
                    rejection_hash = hashlib.sha256(args.rejected_trace.read_bytes()).hexdigest()
        if not errors:
            recovery_required = {}
            errors = activation_packet_errors(args.activation_packet_bundle.resolve(), args.expected_agent,
                args.expected_bundle_sha256, rejected_trace_sha256=rejection_hash, recovery_required=recovery_required)
            if recovery_required:
                result["recovery_required"] = recovery_required
        if not errors:
            bundle = json.loads(args.activation_packet_bundle.read_text())
            packet = bundle["packets"][args.expected_agent]
            result["launch_arguments"] = {
                "fork_turns": "none", "model": packet["model"], "reasoning_effort": packet["effort"],
            }
            if args.assignment:
                try:
                    message = activation_message(packet, json.loads(args.assignment.read_text()))
                    expected = dispatch_notice(packet, message, args.dispatch_file) if args.dispatch_file else message
                    if args.activation_message and args.activation_message.read_text() != expected:
                        raise ValueError("activation_message_mismatch")
                    if args.dispatch_file:
                        message = dispatch_message(packet, message, args.dispatch_file)
                        if rejection_hash:
                            quarantine = []
                            contract = packet.get("worker_contract", {})
                            for output in dict.fromkeys(contract.get(field) for field in ("output", "result")
                                                        if contract.get(field)):
                                target = Path(output)
                                root = args.activation_packet_bundle.resolve().parent
                                if target.resolve().parent != root or target.is_symlink():
                                    raise ValueError("recovery_output_outside_current_run")
                                if target.exists():
                                    rejected = target.with_name(target.stem + ".rejected" + target.suffix)
                                    if rejected.is_symlink() or rejected.exists() and rejected.read_bytes() != target.read_bytes():
                                        raise ValueError("recovery_rejected_output_conflict")
                                    quarantine.append((target, rejected))
                            current_path = args.activation_packet_bundle.parent / "finalization_packet.json"
                            current = json.loads(current_path.read_text())
                            for target, rejected in quarantine:
                                if target.resolve() == current_path.resolve():
                                    rejected.write_bytes(target.read_bytes())
                                else:
                                    target.replace(rejected)
                            current.setdefault("activation_repairs", {})[args.expected_agent] = {
                                "Attempt": 1, "Provider handle": args.provider_handle,
                                "Last dispatch at": args.last_dispatch_at, "Rejected trace SHA256": rejection_hash,
                                "Corrected dispatch SHA256": hashlib.sha256(args.dispatch_file.read_bytes()).hexdigest()}
                            with tempfile.NamedTemporaryFile("w", dir=current_path.parent, delete=False) as stream:
                                temporary = Path(stream.name)
                                json.dump(current, stream, indent=2)
                                stream.write("\n")
                            try:
                                temporary.replace(current_path)
                            finally:
                                temporary.unlink(missing_ok=True)
                            result["recovery_authorization"] = current["activation_repairs"][args.expected_agent]
                        result["dispatch_file"] = str(args.dispatch_file.resolve())
                        result["dispatch_file_sha256"] = hashlib.sha256(args.dispatch_file.read_bytes()).hexdigest()
                    result["activation_message"] = message
                    result["activation_message_sha256"] = hashlib.sha256(message.encode()).hexdigest()
                except (OSError, ValueError, TypeError) as error:
                    errors.append(f"activation_assignment_invalid:{error}")
            elif args.activation_message:
                errors.append("activation_message_requires_assignment")
            else:
                result["activation_packet"] = packet
    elif args.transition or args.provider_status:
        if not args.transition or not args.provider_status:
            parser.error("--transition and --provider-status are required together")
        errors = []
        if args.rejected_trace:
            try:
                trace = json.loads(args.rejected_trace.read_text())
                errors = rejected_result_errors(trace,
                                                args.provider_handle, args.last_dispatch_at)
                current = json.loads((args.rejected_trace.parent / "finalization_packet.json").read_text())
                if (not trace.get("run_id") or trace["run_id"] != current["identity"]["Run ID"]
                        or any(pattern.search(str(args.rejected_trace.resolve()))
                               for label, pattern in FORBIDDEN_CONTEXT_PATTERNS if label == "archived_artifact")):
                    errors.append("rejected_result_current_run_required")
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
                errors = [f"rejected_result_trace_invalid:{error}"]
        error = transition_error(args.transition, args.provider_status,
                                 rejected_result=bool(args.rejected_trace) and not errors)
        if error:
            errors.append(error)
        if not errors and args.rejected_trace:
            role = (trace["spawn"].get("binding_agent") or trace["spawn"].get("agent")
                    or trace["spawn"].get("expected_agent"))
            errors.extend(_recovery_errors(args.rejected_trace, role, args.provider_handle,
                                           args.last_dispatch_at, args.provider_status))
            if not errors:
                result["next_action"] = (
                    "Run corrected activation with --activation-packet-bundle, --expected-agent, "
                    "--expected-bundle-sha256, --assignment, --dispatch-file and the same --rejected-trace, "
                    "--provider-handle, --last-dispatch-at plus a fresh terminal --provider-status. "
                    "This transition check does not consume the recovery attempt or authorize an ordinary activation."
                )
    else:
        parser.error("choose --activation-packet-bundle, --transition, --trace, or --self-test")
    if errors:
        result.update(status="blocked", errors=errors)
        print(json.dumps(result, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
