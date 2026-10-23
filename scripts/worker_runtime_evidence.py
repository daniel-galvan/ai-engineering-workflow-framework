#!/usr/bin/env python3
"""Extract current-run worker identities and dispatch times from provider events."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from pathlib import Path


try:
    from provider_runtime import (
        timestamp,
        provider_json_value as provider_json_value,
        read_runtime_events,
        dispatched_worker_handles,
        latest_worker_dispatch,
        runtime_configurations,
        launch_binding_errors,
        worker_binding,
        strict_json_loads,
        validate_prepared_provider_source,
    )
except ModuleNotFoundError:
    from scripts.provider_runtime import (
        timestamp,
        provider_json_value as provider_json_value,
        read_runtime_events,
        dispatched_worker_handles,
        latest_worker_dispatch,
        runtime_configurations,
        launch_binding_errors,
        worker_binding,
        strict_json_loads,
        validate_prepared_provider_source,
    )


UUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")


def worker_final_response(source: Path, dispatch_at: str, observed_at: str,
                          turn_started_at: str | None = None, *, turn_id: str | None = None) -> str:
    """Read the latest assistant final answer from the dispatched worker turn."""
    with source.open() as stream:
        rows = [json.loads(line) for line in stream if line.strip()]
    if not rows or not isinstance(rows[0], dict) or rows[0].get("type") != "session_meta":
        raise ValueError("worker_trace_session_mismatch")
    after, before = timestamp(dispatch_at), timestamp(observed_at)
    turns = [row for row in rows if isinstance(row, dict) and row.get("type") == "turn_context"
             and timestamp(row["timestamp"]) <= before]
    if not turns:
        raise ValueError("worker_final_response_turn_context_required")
    latest = max(turns, key=lambda row: timestamp(row["timestamp"]))
    if turn_id is not None:
        # Thread metadata rounds start times; the turn ID is the precise session join.
        matching = [row for row in turns if row.get("payload", {}).get("turn_id") == turn_id]
        if len(matching) != 1 or matching[0] is not latest:
            raise ValueError("worker_final_response_turn_context_mismatch")
        started = timestamp(latest["timestamp"])
    elif turn_started_at:
        started = timestamp(turn_started_at)
        if started != timestamp(latest["timestamp"]):
            raise ValueError("worker_final_response_turn_context_mismatch")
    else:
        started = timestamp(latest["timestamp"])
    started = max(started, after)
    messages = [row for row in rows if isinstance(row, dict) and row.get("type") == "response_item"
                and started <= timestamp(row["timestamp"]) <= before
                and isinstance(row.get("payload"), dict)
                and row["payload"].get("type") == "message"
                and row["payload"].get("role") == "assistant"
                and row["payload"].get("phase") in {"final", "final_answer"}]
    if not messages:
        raise ValueError("worker_final_response_missing")
    content = messages[-1]["payload"].get("content")
    if not isinstance(content, list):
        raise ValueError("worker_final_response_invalid")
    parts = [item.get("text") for item in content
             if isinstance(item, dict) and item.get("type") == "output_text" and isinstance(item.get("text"), str)]
    if len(parts) != len(content) or not parts:
        raise ValueError("worker_final_response_invalid")
    return "".join(parts)


def _materialize_worker_response(root: Path, role: str, dispatch_at: str, response: str,
                                 contract: dict) -> dict:
    """Save one immutable, dispatch-scoped response snapshot for acceptance."""
    try:
        value = strict_json_loads(response)
    except (json.JSONDecodeError, ValueError) as error:
        raise ValueError("worker_final_response_json_invalid") from error
    allowed = {"output", "result"} | ({"asset_manifest"} if contract.get("asset_inventory") else set())
    if (not isinstance(value, dict) or set(value) - allowed or not isinstance(value.get("output"), str)
            or not value["output"].strip() or not isinstance(value.get("result"), dict)):
        raise ValueError("worker_final_response_schema_invalid")
    digest = hashlib.sha256(dispatch_at.encode()).hexdigest()[:16]
    directory = root / ".worker_responses" / role / digest
    directory.mkdir(parents=True, exist_ok=True)
    artifacts = {"path": ("result.json", json.dumps(value["result"], indent=2, ensure_ascii=False) + "\n"),
                 "output_path": ("output.md", value["output"]),
                 "response_path": ("response.json", response)}
    if contract.get("asset_inventory"):
        if not isinstance(value.get("asset_manifest"), dict):
            raise ValueError("worker_asset_manifest_response_required")
        artifacts["asset_manifest_path"] = (
            "asset_manifest.json", json.dumps(value["asset_manifest"], indent=2, ensure_ascii=False) + "\n")
    for name, content in artifacts.values():
        path = directory / name
        if path.exists() and path.read_bytes() != content.encode():
            raise ValueError("worker_response_snapshot_conflict:" + role)
    receipt = {}
    for field, (name, content) in artifacts.items():
        path = directory / name
        raw = content.encode()
        if not path.exists():
            try:
                with path.open("xb") as stream:
                    stream.write(raw)
            except BaseException:
                path.unlink(missing_ok=True)
                raise
        receipt[field] = str(path.resolve())
        receipt[field.replace("_path", "_sha256") if field.endswith("_path") else "sha256"] = hashlib.sha256(raw).hexdigest()
    receipt["dispatch_at"] = dispatch_at
    return receipt


def export_worker_trace(ledger: dict, source: Path, agent: str, observation: dict | None = None, *, run_id: str | None = None, artifact_root: Path | None = None) -> dict:
    """Export tool activity only, using the exact parent mapping and fresh status receipt."""
    try:
        from runtime_checks import terminal_observation_errors, trace_errors, observed_dispatch_binding
    except ModuleNotFoundError:
        from scripts.runtime_checks import terminal_observation_errors, trace_errors, observed_dispatch_binding
    if observation is None:
        with source.open() as stream:
            thread = json.loads(next(stream))["payload"]["id"]
        handles = [handle for handle, child in ledger["thread_mappings"].items() if child == thread]
        if len(handles) != 1:
            raise ValueError("worker_trace_thread_mismatch")
        observation = _native_terminal_observations(ledger, handles)[0]
    thread = observation["Thread ID"]
    handle = observation["Provider handle"]
    if ledger["thread_mappings"].get(handle) != thread:
        raise ValueError("worker_trace_thread_mismatch")
    dispatch = latest_worker_dispatch(ledger, handle)
    dispatches = [row for row in ledger["events"] if row.get("Provider handle") == handle]
    if "Last dispatch at" not in observation:
        observation = {**observation, "Last dispatch at": dispatch["Last dispatch at"]}
    if observation.get("Last dispatch at") != dispatch["Last dispatch at"]:
        raise ValueError("worker_trace_dispatch_mismatch: received=" + str(observation.get("Last dispatch at"))
                         + "; expected=" + str(dispatch["Last dispatch at"]))
    errors = terminal_observation_errors([observation], [handle], require_completed=False)
    if errors:
        raise ValueError(";".join(errors))
    tool_trace = []
    # A correction cannot erase earlier binding reads or analytical activity in this run.
    audit_started_at = min(timestamp(value["Last dispatch at"]) for value in dispatches)
    with source.open() as stream:
        first = json.loads(next(stream))
        if first.get("type") != "session_meta" or first.get("payload", {}).get("id") != thread:
            raise ValueError("worker_trace_session_mismatch")
        for line in stream:
            row = json.loads(line)
            if timestamp(row["timestamp"]) < audit_started_at:
                continue
            if timestamp(row["timestamp"]) > timestamp(observation["Observed at"]):
                continue
            payload = row.get("payload", {})
            if row.get("type") == "response_item" and payload.get("type") in {
                    "function_call", "function_call_output", "custom_tool_call", "custom_tool_call_output"}:
                tool_trace.append(payload)
    binding = observation.get("Binding evidence", {})
    if not isinstance(binding, dict):
        raise ValueError("worker_trace_binding_evidence_invalid: expected JSON object, received " + type(binding).__name__)
    if artifact_root is not None:
        binding = {key: value for key, value in binding.items()
                   if key != "activation_packet_delivered"}
    contract_dispatch = next((value for value in reversed(dispatches) if value.get("Dispatch file")), {})
    if contract_dispatch:
        dispatch = {**dispatch, **{key: contract_dispatch[key] for key in
                                  ("Dispatch file", "Dispatch SHA256", "Binding agent")}}
    if dispatch.get("Dispatch file"):
        binding = {**binding, "dispatch_file": dispatch["Dispatch file"],
                   "dispatch_file_sha256": dispatch["Dispatch SHA256"], "binding_agent": dispatch["Binding agent"]}
    activation_dispatch = next((row for row in dispatches if row.get("Operation") == "spawn_agent"), {})
    activation_metadata = {
        target: activation_dispatch[field]
        for target, field in (("model", "Observed model"), ("effort", "Observed effort"))
        if isinstance(activation_dispatch.get(field), str)
    }
    fan_in_status = "completed" if observation["Provider status"] in {"completed", "idle"} else observation["Provider status"]
    result = {"schema_version": 1, "worker": agent, "thread_id": thread,
              "launch": activation_dispatch.get("Launch", {}), "activation_metadata": activation_metadata,
              "runtime_configurations": runtime_configurations(source, thread, observation["Observed at"]),
              "last_dispatch_at": dispatch["Last dispatch at"],
              "spawn": dict(binding, agent=agent, provider_handle=handle, thread_id=thread),
              "tool_trace": tool_trace,
              "events": [{"action": "fan_in", "provider_status": fan_in_status, "guard_result": "allowed"}],
              "trace_retrieval": str(source.resolve()), "status_observation": observation}
    if run_id is not None:
        result["run_id"] = run_id
    if artifact_root is not None and not result["spawn"].get("dispatch_file"):
        result["spawn"].update(observed_dispatch_binding(result, artifact_root))
    launch_errors = launch_binding_errors(result, artifact_root, agent, ledger) if artifact_root else []
    result["launch_errors"] = launch_errors
    response_errors = []
    if artifact_root is not None and (artifact_root / "role_bindings.json").is_file():
        bindings = json.loads((artifact_root / "role_bindings.json").read_text())
        contract = bindings.get("worker_contracts", {}).get(worker_binding(bindings, agent), {})
        if contract.get("result_hash_required"):
            try:
                response = worker_final_response(source, dispatch["Last dispatch at"], observation["Observed at"],
                                                 observation.get("Latest turn started at"),
                                                 turn_id=observation.get("Latest turn ID"))
                result["result_artifact"] = _materialize_worker_response(
                    artifact_root, worker_binding(bindings, agent), dispatch["Last dispatch at"], response, contract)
            except (OSError, ValueError, KeyError, TypeError) as error:
                message = str(error)
                if message.startswith("worker_final_response") or message.startswith("worker_asset_manifest_response"):
                    message += ":" + worker_binding(bindings, agent)
                response_errors.append(message)
    result["worker_response_errors"] = response_errors
    context_details = []
    errors = trace_errors(result, require_freshness=True, context_details=context_details)
    if errors:
        result["events"][0]["guard_result"] = "blocked"
        errors = trace_errors(result, require_freshness=True)
    result["audit"] = {"status": "rejected" if errors else "passed", "errors": errors}
    if context_details:
        result["audit"]["context_violations"] = context_details
    return result


def dispatch_audit_errors(packet: dict, packet_path: Path, *, closure_only: bool = False) -> list[str]:
    bindings = packet_path.parent / "role_bindings.json"
    if not bindings.is_file():
        return []
    try:
        manifest = json.loads(bindings.read_text())
        contract = manifest.get("runtime_evidence")
        if not contract:
            return []  # Existing packets retain their previous validation contract.
        ledger = Path(contract["ledger"])
        if ledger.resolve().parent != packet_path.parent.resolve():
            raise ValueError("runtime_dispatch_ledger_outside_current_run")
        saved = json.loads(ledger.read_text())
        validate_prepared_provider_source(manifest, Path(saved["provider_session"]), saved["parent_thread_id"],
                                          saved["run_started_at"])
        current = read_runtime_events(Path(saved["provider_session"]), saved["parent_thread_id"],
                                      saved["run_started_at"], tuple(Path(value) for value in saved.get("identity_sessions", [])))
        if (saved["events"] != current["events"] or saved["thread_mappings"] != current["thread_mappings"]
                or saved["inventories"] != current["inventories"]
                or saved.get("failed_dispatches", []) != current.get("failed_dispatches", [])):
            raise ValueError("runtime_dispatch_ledger_stale")
        errors = []
        for audit in packet.get("runtime_audits", []):
            handle = audit.get("Provider handle")
            latest = latest_worker_dispatch(current, handle, include_failed=closure_only)["Last dispatch at"]
            if audit.get("Last dispatch at") != latest:
                errors.append(f"runtime_audit_dispatch_mismatch:{audit.get('Worker')}")
            if audit.get("Thread ID") and audit["Thread ID"] != current["thread_mappings"].get(handle):
                errors.append(f"runtime_audit_thread_mismatch:{audit.get('Worker')}")
            if contract.get("launch_binding_required") and audit.get("Worker"):
                try:
                    from runtime_checks import worker_binding
                except ModuleNotFoundError:
                    from scripts.runtime_checks import worker_binding
                role = worker_binding(manifest, audit["Worker"])
                expected = manifest["bindings"][role]
                launch = next((row.get("Launch", {}) for row in current["events"]
                    if row.get("Provider handle") == handle and row.get("Operation") == "spawn_agent"), {})
                if (launch.get("fork_turns") != "none" or launch.get("model") != expected["model"]
                        or launch.get("reasoning_effort") != expected["effort"]):
                    errors.append("worker_launch_binding_mismatch:" + role)
        return errors
    except (OSError, ValueError, KeyError, TypeError, AttributeError, StopIteration) as error:
        return [f"runtime_dispatch_evidence_invalid:{error}"]


def _native_terminal_observations(ledger: dict, handles: list[str], *, require_terminal: bool = True) -> list[dict]:
    """Select the latest provider status for each handle from inventory or targeted thread reads."""
    try:
        from runtime_checks import terminal_observation_errors
    except ModuleNotFoundError:
        from scripts.runtime_checks import terminal_observation_errors
    inventories = ledger.get("inventories", [])
    probes = ledger.get("status_probes", [])
    if not inventories and not probes:
        raise ValueError("terminal_provider_inventory_required")
    inventory = inventories[-1] if inventories else None
    agents = ({row["agent_name"]: row["agent_status"] for row in inventory["raw_response"]["agents"]}
              if inventory else {})
    observations = []
    for handle in handles:
        dispatch = latest_worker_dispatch(ledger, handle, include_failed=True)["Last dispatch at"]
        status = agents.get(handle)
        if isinstance(status, dict) and len(status) == 1:
            status = next(iter(status))
        row = {"Provider handle": handle, "Provider status": status,
            "Thread ID": ledger["thread_mappings"][handle], "Status source": "list_agents",
            "Last dispatch at": dispatch, "Observed at": inventory["Observed at"] if inventory else dispatch}
        candidates = [probe for probe in probes if isinstance(probe, dict)
                      and probe.get("Provider handle") == handle
                      and timestamp(probe.get("Attempted at", "")) >= timestamp(dispatch)]
        if candidates:
            latest = max(candidates, key=lambda probe: timestamp(probe.get("Observed at", "")))
            if handle not in agents or timestamp(latest["Observed at"]) > timestamp(row["Observed at"]):
                targeted = latest.get("terminal_observation")
                row = (targeted if isinstance(targeted, dict) else {
                    "Provider handle": handle, "Provider status": None,
                    "Thread ID": ledger["thread_mappings"][handle], "Status source": latest.get("Operation"),
                    "Last dispatch at": dispatch, "Observed at": latest.get("Observed at")})
        observations.append(row)
    errors = terminal_observation_errors(observations, handles, require_completed=False)
    if not handles or (require_terminal and errors):
        raise ValueError("terminal_inventory_unverified:" + ";".join(errors))
    return observations


def terminal_closure(ledger: dict) -> dict:
    """Project latest native status evidence into the canonical Terminal receipt."""
    handles = dispatched_worker_handles(ledger)
    if not handles:
        mappings = ledger.get("thread_mappings", {})
        timing = ledger.get("timing", {})
        if not isinstance(mappings, dict) or mappings:
            raise ValueError("runtime_zero_dispatch_has_worker_identity")
        if not isinstance(timing, dict) or timing.get("open_worker_intervals") != 0:
            raise ValueError("runtime_zero_dispatch_has_open_worker_intervals")
        return {"runtime_closure": [{"Run or stage": "Current run", "Receipt owner": "Coordinator",
            "Completed worker handles": "None dispatched", "Runtime status": "Terminal",
            "Remaining active handles": "0",
            "Closure evidence or blocker": "verified current provider ledger shows no worker handles were activated"}],
            "terminal_observations": []}
    observations = _native_terminal_observations(ledger, handles)
    observed_at = max(row["Observed at"] for row in observations)
    return {"runtime_closure": [{"Run or stage": "Current run", "Receipt owner": "Coordinator",
        "Completed worker handles": "; ".join(handles), "Runtime status": "Terminal", "Remaining active handles": "0",
        "Closure evidence or blocker": "provider status snapshot " + observed_at + ": "
            + "; ".join(row["Provider handle"] + "=" + str(row["Provider status"]) for row in observations)}],
        "terminal_observations": observations}


def blocked_runtime_closure(ledger: dict, blocker: str) -> dict:
    """Record unavailable closure only when the latest provider evidence is insufficient."""
    handles = dispatched_worker_handles(ledger)
    if not handles:
        raise ValueError("blocked_runtime_closure_requires_dispatched_handles")
    reason = str(blocker).strip()
    if not reason:
        raise ValueError("blocked_runtime_closure_reason_required")
    observations = []
    if ledger.get("inventories"):
        try:
            from runtime_checks import terminal_observation_errors
        except ModuleNotFoundError:
            from scripts.runtime_checks import terminal_observation_errors
        observations = _native_terminal_observations(ledger, handles, require_terminal=False)
        errors = terminal_observation_errors(observations, handles, require_completed=False)
        if not errors:
            raise ValueError("worker_runtime_terminal_receipt_available: use --closure")
        inventory = ledger["inventories"][-1]
        detail = f"; latest provider inventory {inventory['Observed at']} is insufficient: " + ", ".join(errors)
    else:
        detail = "; terminal provider inventory unavailable"
    probes = ledger.get("status_probes", [])
    if not isinstance(probes, list):
        raise ValueError("targeted_worker_status_probes_invalid")
    missing_handles = {row["Provider handle"] for row in observations
                       if not isinstance(row.get("Provider status"), str) or not row["Provider status"].strip()}
    if not observations:
        missing_handles = set(handles)
    for handle in sorted(missing_handles):
        dispatch = latest_worker_dispatch(ledger, handle, include_failed=True)
        dispatch_at = timestamp(dispatch["Last dispatch at"])
        attempts = [row for row in probes if isinstance(row, dict)
                    and row.get("Provider handle") == handle
                    and row.get("Result") in {"returned", "unavailable", "unverifiable"}
                    and timestamp(row.get("Attempted at", "")) >= dispatch_at]
        if not attempts:
            raise ValueError("targeted_worker_status_failure_evidence_required:" + handle)
        latest = max(attempts, key=lambda row: (timestamp(row["Attempted at"]), timestamp(row["Observed at"])))
        if latest["Result"] not in {"unavailable", "unverifiable"}:
            raise ValueError("targeted_worker_status_returned: refresh inventory or use terminal observation:" + handle)
        detail += f"; targeted {latest['Operation']} was {latest['Result']} for {handle} at {latest['Observed at']}"
        if latest.get("Reason"):
            detail += "; " + latest["Reason"]
    if not reason.lower().startswith("worker_runtime_release_unavailable:"):
        reason = "worker_runtime_release_unavailable: " + reason
    return {"runtime_closure": [{
        "Run or stage": "Current run", "Receipt owner": "Coordinator",
        "Completed worker handles": "Unknown", "Runtime status": "Blocked",
        "Remaining active handles": "Unknown",
        "Closure evidence or blocker": reason + detail + "; dispatched handles: " + "; ".join(handles),
    }]}


def register_worker_audit(packet_path: Path, agent: str, trace_path: Path) -> None:
    """Register passed TechOps/Feature receipts without accepting analytical content."""
    root = packet_path.parent.resolve()
    bindings = json.loads((root / "role_bindings.json").read_text())
    if (bindings.get("playbook") not in {"techops_issue_remediation", "feature_delivery", "sentry_issue_remediation"}
            or (bindings.get("playbook") == "sentry_issue_remediation"
                and bindings.get("lifecycle") != "remediation")):
        return  # Sentry retains its finalizer-owned audit assembly.
    try:
        from planning_contracts import worker_audit_record
        from validate_worker_runtime import prepared_package_errors, _pending_rejections
        from provider_runtime import DELIVERY_WORKERS
    except ModuleNotFoundError:
        from scripts.planning_contracts import worker_audit_record
        from scripts.validate_worker_runtime import prepared_package_errors, _pending_rejections
        from scripts.provider_runtime import DELIVERY_WORKERS
    errors = prepared_package_errors(root)
    if errors:
        raise ValueError(";".join(errors))
    role = worker_binding(bindings, agent)
    if role in _pending_rejections(root):
        raise ValueError("worker_result_recovery_authorization_required:" + role)
    contract = bindings.get("worker_contracts", {}).get(role, {})
    worker = contract.get("worker_id") or contract.get("worker") or next(
        (worker for worker, binding in DELIVERY_WORKERS.items() if binding == role), role)
    audit = worker_audit_record(packet_path, worker, trace_path)
    packet = json.loads(packet_path.read_text())
    packet["runtime_audits"] = [row for row in packet.get("runtime_audits", [])
                                if row.get("Worker") != worker] + [audit]
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


def activate_verified_remediation(packet_path: Path, ledger: dict) -> dict | None:
    """Advance remediation identity only after the current provider evidence passes its launch gate."""
    bindings_path = packet_path.parent / "role_bindings.json"
    if not bindings_path.is_file():
        return None
    bindings = json.loads(bindings_path.read_text())
    if (bindings.get("playbook") not in {"feature_delivery", "techops_issue_remediation", "sentry_issue_remediation"}
            or bindings.get("lifecycle") != "remediation"):
        return None
    packet = json.loads(packet_path.read_text())
    identity = packet.get("identity", {})
    requested = identity.get("Requested profile")
    if (requested not in {"standard", "deep"} or identity.get("Lifecycle") != "remediation"
            or identity.get("Profile status") != "requested" or identity.get("State") != "in_progress"):
        return None
    if not ledger.get("inventories"):
        return {"status": "pending", "errors": ["delivery_activation_fresh_inventory_required"]}

    inventory = ledger["inventories"][-1]
    statuses = {}
    for row in inventory.get("raw_response", {}).get("agents", []):
        status = row.get("agent_status")
        if isinstance(status, dict) and len(status) == 1:
            status = next(iter(status))
        statuses[row.get("agent_name")] = str(status).strip().lower().replace(" ", "_")
    active = {"pending_init", "running", "in_progress", "awaiting_dependency"}
    candidates = [row for row in ledger.get("events", [])
                  if row.get("Operation") == "spawn_agent" and row.get("Binding agent") == "implementer"
                  and row.get("Provider handle") in statuses and statuses[row["Provider handle"]] in active]
    if len(candidates) != 1:
        return {"status": "pending", "errors": ["delivery_worker_live_activation_required:implement"]}

    candidate = json.loads(json.dumps(packet))
    candidate["identity"]["Activated profile"] = requested
    candidate["identity"]["Profile status"] = "in_progress"
    with tempfile.NamedTemporaryFile("w", dir=packet_path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(candidate, stream, indent=2)
            stream.write("\n")
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        try:
            from runtime_checks import delivery_start_errors
        except ModuleNotFoundError:
            from scripts.runtime_checks import delivery_start_errors
        handle = candidates[0]["Provider handle"]
        errors = delivery_start_errors(temporary, handle, statuses[handle])
        if errors:
            return {"status": "pending", "errors": errors}
        temporary.replace(packet_path)
        return {"status": "activated", "profile": requested,
                "provider_handle": handle, "inventory_at": inventory.get("Observed at")}
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider-session", type=Path, required=True)
    parser.add_argument("--identity-session", type=Path, action="append", default=[],
                        help="Exact earlier parent fragment; read current-run control metadata, not analytical outputs")
    parser.add_argument("--parent-thread-id", required=True)
    parser.add_argument("--started-at", required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--worker-session", type=Path,
                        help="Absolute native worker JSONL path, not a thread UUID or collaboration handle")
    parser.add_argument("--observation", type=Path, help="Targeted receipt; omit to use the latest native inventory")
    parser.add_argument("--agent")
    parser.add_argument("--trace", type=Path)
    parser.add_argument("--closure", type=Path, help="Build a Terminal receipt from the current native provider inventory")
    parser.add_argument("--pending-closure", type=Path, help="Create an unverified closure probe before pre-release")
    parser.add_argument("--blocked-closure", type=Path,
                        help="Build a Coordinator Blocked receipt when current provider closure cannot be verified")
    parser.add_argument("--blocker", help="Concrete reason terminal provider status or release could not be verified")
    args = parser.parse_args()
    closure_modes = [args.closure, args.pending_closure, args.blocked_closure]
    if sum(path is not None for path in closure_modes) > 1:
        parser.error("pending, Blocked, and Terminal closure are separate modes")
    if bool(args.blocked_closure) != bool(args.blocker):
        parser.error("--blocked-closure requires --blocker, and --blocker is only valid with --blocked-closure")
    closure_path = args.closure or args.pending_closure or args.blocked_closure
    if closure_path and any((args.worker_session, args.observation, args.agent, args.trace)):
        parser.error("closure collection and trace export are separate modes")
    if any((args.worker_session, args.observation, args.agent, args.trace)) and not all(
            (args.worker_session, args.agent, args.trace)):
        parser.error("trace export requires --worker-session, --agent and --trace")
    try:
        identity_sessions = list(args.identity_session)
        bindings_path = args.ledger.parent / "role_bindings.json"
        if bindings_path.is_file():
            bindings = json.loads(bindings_path.read_text())
            validate_prepared_provider_source(bindings, args.provider_session, args.parent_thread_id, args.started_at)
            contract = bindings.get("runtime_evidence", {})
            identity_sessions = [Path(value) for value in contract.get("identity_sessions", [])] + identity_sessions
            expected = contract.get("ledger")
            if expected and args.ledger.resolve() != Path(expected).resolve():
                raise ValueError("runtime_dispatch_ledger_mismatch:expected=" + str(expected)
                                 + ";received=" + str(args.ledger.resolve()))
        result = read_runtime_events(args.provider_session, args.parent_thread_id, args.started_at,
                                     tuple(dict.fromkeys(identity_sessions)))
        if args.ledger.exists():
            pending = json.loads(args.ledger.read_text()).get("rejected_results", {})
            if pending:
                packet = json.loads((args.ledger.parent / "finalization_packet.json").read_text())
                if any(row["run_id"] != packet["identity"]["Run ID"] for row in pending.values()):
                    raise ValueError("worker_rejection_receipt_run_mismatch")
                result["rejected_results"] = pending
        if closure_path:
            if closure_path.resolve().parent != args.ledger.resolve().parent:
                raise ValueError("runtime_closure_outside_current_run")
            if args.pending_closure and closure_path.exists():
                previous = json.loads(closure_path.read_text())
                if (previous.get("terminal_observations") or not previous.get("runtime_closure")
                        or any(row.get("Runtime status") != "Pending" for row in previous["runtime_closure"])):
                    raise ValueError("runtime_pending_closure_would_replace_evidence")
            if args.blocked_closure and closure_path.exists():
                previous = json.loads(closure_path.read_text())
                if (previous.get("terminal_observations") or not previous.get("runtime_closure")
                        or any(row.get("Runtime status") != "Pending" for row in previous["runtime_closure"])):
                    raise ValueError("runtime_blocked_closure_would_replace_evidence")
            receipt = (terminal_closure(result) if args.closure else
                       blocked_runtime_closure(result, args.blocker) if args.blocked_closure else
                       {"runtime_closure": [{
                           "Run or stage": "Current run", "Receipt owner": "Coordinator",
                           "Completed worker handles": "Unknown", "Runtime status": "Pending",
                           "Remaining active handles": "Unknown",
                           "Closure evidence or blocker": "Pending final provider observation after pre-release"}]})
            closure_path.write_text(json.dumps(receipt, indent=2) + "\n")
        packet_path = args.ledger.parent / "finalization_packet.json"
        if args.trace:
            if args.trace.resolve().parent != args.ledger.resolve().parent:
                raise ValueError("worker_trace_outside_current_run")
            run_id = json.loads(packet_path.read_text())["identity"]["Run ID"] if packet_path.is_file() else None
            observation = json.loads(args.observation.read_text()) if args.observation else None
            if observation is not None and "terminal_observations" in observation:
                with args.worker_session.open() as stream:
                    thread = json.loads(next(stream))["payload"]["id"]
                observation = next(row for row in observation["terminal_observations"] if row["Thread ID"] == thread)
            trace = export_worker_trace(result, args.worker_session, args.agent,
                                        observation, run_id=run_id, artifact_root=args.trace.parent)
            if args.trace.is_file():
                saved = json.loads(args.trace.read_text())
                if saved.get("audit", {}).get("status") == "rejected" and saved != trace:
                    raise ValueError("worker_trace_rejected_evidence_requires_new_path")
            args.trace.write_text(json.dumps(trace, indent=2) + "\n")
            try:
                from runtime_checks import worker_binding
            except ModuleNotFoundError:
                from scripts.runtime_checks import worker_binding
            bindings_path = args.trace.parent / "role_bindings.json"
            if bindings_path.is_file():
                role = worker_binding(json.loads(bindings_path.read_text()), args.agent)
                pending = json.loads(args.ledger.read_text()).get("rejected_results", {}) if args.ledger.exists() else {}
                if any(receipt["run_id"] != run_id for receipt in pending.values()):
                    raise ValueError("worker_rejection_receipt_run_mismatch")
                if trace["audit"]["status"] == "rejected":
                    pending.setdefault(role, {"trace": str(args.trace.resolve()), "run_id": run_id,
                                             "sha256": hashlib.sha256(args.trace.read_bytes()).hexdigest(),
                                             "Provider handle": trace["spawn"]["provider_handle"],
                                             "Last dispatch at": trace["last_dispatch_at"]})
                elif role in pending:
                    repair = json.loads(packet_path.read_text()).get("activation_repairs", {}).get(role, {})
                    same_turn = (pending[role]["Last dispatch at"] == trace["last_dispatch_at"]
                                 and pending[role]["Provider handle"] == trace["spawn"]["provider_handle"])
                    if same_turn or repair.get("Rejected trace SHA256") == pending[role]["sha256"]:
                        pending.pop(role)
                result["rejected_results"] = pending
        args.ledger.write_text(json.dumps(result, indent=2) + "\n")
        if args.trace and trace["audit"]["errors"]:
            print(json.dumps({"status": "blocked", "errors": trace["audit"]["errors"],
                              "trace": str(args.trace), "ledger": str(args.ledger),
                              "context_violations": trace["audit"].get("context_violations", [])}))
            return 2
        if args.trace and (args.trace.parent / "role_bindings.json").is_file():
            try:
                register_worker_audit(packet_path, args.agent, args.trace)
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
                reason = str(error)
                recovery_gate = reason.startswith("worker_result_recovery_authorization_required:")
                context_failure = reason.startswith("parent_context_nonconformant")
                print(json.dumps({"status": "blocked",
                    "phase": "parent_context_nonconformant" if context_failure else
                        "worker_recovery_gate" if recovery_gate else "coordinator_audit_registration",
                    "worker_trace_status": "passed", "worker_result_disposition": "not_merged",
                    "required_action": "terminate_invocation_with_workflow_failure" if context_failure else
                        "complete_bounded_recovery_before_merging" if recovery_gate else
                        "correct_coordinator_receipt_then_retry_collection_or_merge",
                    "trace": str(args.trace), "ledger": str(args.ledger), "reason": reason}))
                return 2
        profile_activation = activate_verified_remediation(packet_path, result) if packet_path.is_file() else None
    except (OSError, ValueError, KeyError, TypeError, AttributeError, StopIteration) as error:
        print(json.dumps({"status": "blocked", "reason": str(error)}))
        return 2
    output = {"status": "recorded", "ledger": str(args.ledger),
              "thread_mappings": result["thread_mappings"], "dispatch_count": len(result["events"])}
    if profile_activation is not None:
        output["profile_activation"] = profile_activation
    print(json.dumps(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
