#!/usr/bin/env python3
"""Extract current-run worker identities and dispatch times from provider events."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path


UUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")


def timestamp(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("provider_event_timestamp_requires_timezone")
    return result


def read_runtime_events(path: Path, parent_thread_id: str, started_at: str) -> dict:
    if not UUID.fullmatch(parent_thread_id):
        raise ValueError("parent_thread_id_invalid")
    started = timestamp(started_at)
    with path.open() as stream:
        first = json.loads(next(stream))
        if first.get("type") != "session_meta" or first.get("payload", {}).get("id") != parent_thread_id:
            raise ValueError("provider_session_parent_mismatch")
        events, mappings, inventories = [], {}, []
        pending_spawn = None
        inventory_pending = False
        observed_until = started
        active, intervals = {}, []
        for line in stream:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                if not line.endswith("\n"):
                    break  # The provider may still be appending the last event.
                raise ValueError("provider_session_event_invalid") from None
            if timestamp(row["timestamp"]) < started:
                continue
            observed_until = max(observed_until, timestamp(row["timestamp"]))
            payload = row.get("payload", {})
            item = payload.get("item", {})
            if row.get("type") == "event_msg" and item.get("type") == "SubAgentActivity":
                handle = item.get("agent_path")
                if item.get("kind") == "started":
                    active.setdefault(handle, timestamp(row["timestamp"]))
                elif item.get("kind") == "completed" and handle in active:
                    intervals.append((active.pop(handle), timestamp(row["timestamp"])))
            if (row.get("type") == "event_msg" and item.get("type") == "SubAgentActivity"
                    and item.get("kind") == "started"):
                handle, thread = item.get("agent_path"), item.get("agent_thread_id")
                if not isinstance(handle, str) or not isinstance(thread, str) or not UUID.fullmatch(thread):
                    raise ValueError("provider_worker_identity_invalid")
                if handle in mappings and mappings[handle] != thread:
                    raise ValueError("provider_worker_identity_conflict")
                mappings[handle] = thread
                if pending_spawn is not None and handle.rsplit("/", 1)[-1] == pending_spawn[0]:
                    events.append({**pending_spawn[1], "Provider handle": handle, "Thread ID": thread})
                    pending_spawn = None
            if row.get("type") != "response_item":
                continue
            if payload.get("type") == "function_call" and payload.get("namespace") == "collaboration":
                operation = payload.get("name")
                inventory_pending = operation == "list_agents"
                if operation not in {"spawn_agent", "followup_task", "send_message"}:
                    continue
                arguments = json.loads(payload["arguments"])
                event = {"Operation": operation, "Last dispatch at": row["timestamp"]}
                if operation == "spawn_agent":
                    if pending_spawn is not None or not isinstance(arguments.get("task_name"), str):
                        raise ValueError("provider_spawn_identity_unresolved")
                    pending_spawn = (arguments["task_name"], event)
                    continue
                target = arguments.get("target")
                matches = [handle for handle in mappings if target in {handle, handle.rsplit("/", 1)[-1]}]
                if len(matches) != 1:
                    raise ValueError("provider_dispatch_handle_unmapped")
                handle = matches[0]
                events.append({**event, "Provider handle": handle, "Thread ID": mappings[handle]})
            elif payload.get("type") == "function_call_output" and inventory_pending:
                raw = json.loads(payload["output"])
                if isinstance(raw, dict) and isinstance(raw.get("agents"), list):
                    inventories.append({"Observed at": row["timestamp"], "Status source": "list_agents",
                                        "raw_response": raw})
                inventory_pending = False
    intervals.extend((start, observed_until) for start in active.values())
    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    worker_seconds = sum((end - start).total_seconds() for start, end in merged)
    elapsed = (observed_until - started).total_seconds()
    return {"schema_version": 1, "parent_thread_id": parent_thread_id, "run_started_at": started_at,
            "timing": {"observed_until": observed_until.isoformat(), "elapsed_seconds": elapsed,
                       "worker_active_seconds": worker_seconds, "no_worker_active_seconds": elapsed - worker_seconds,
                       "open_worker_intervals": len(active)},
            "provider_session": str(path.resolve()), "events": events,
            "thread_mappings": mappings, "inventories": inventories}


def export_worker_trace(ledger: dict, source: Path, agent: str, observation: dict) -> dict:
    """Export tool activity only, using the exact parent mapping and fresh status receipt."""
    try:
        from validate_worker_runtime import terminal_observation_errors, trace_errors
    except ModuleNotFoundError:
        from scripts.validate_worker_runtime import terminal_observation_errors, trace_errors
    thread = observation["Thread ID"]
    handle = observation["Provider handle"]
    if ledger["thread_mappings"].get(handle) != thread:
        raise ValueError("worker_trace_thread_mismatch")
    dispatches = [row for row in ledger["events"] if row["Provider handle"] == handle]
    if not dispatches or observation.get("Last dispatch at") != dispatches[-1]["Last dispatch at"]:
        raise ValueError("worker_trace_dispatch_mismatch")
    errors = terminal_observation_errors([observation], [handle])
    if errors:
        raise ValueError(";".join(errors))
    tool_trace = []
    with source.open() as stream:
        first = json.loads(next(stream))
        if first.get("type") != "session_meta" or first.get("payload", {}).get("id") != thread:
            raise ValueError("worker_trace_session_mismatch")
        for line in stream:
            row = json.loads(line)
            if timestamp(row["timestamp"]) < timestamp(dispatches[-1]["Last dispatch at"]):
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
    result = {"schema_version": 1, "worker": agent, "thread_id": thread,
              "last_dispatch_at": dispatches[-1]["Last dispatch at"],
              "spawn": dict(binding, agent=agent, provider_handle=handle, thread_id=thread),
              "tool_trace": tool_trace,
              "events": [{"action": "fan_in", "provider_status": "completed", "guard_result": "allowed"}],
              "trace_retrieval": str(source.resolve()), "status_observation": observation}
    errors = trace_errors(result, require_freshness=True)
    if errors:
        result["events"][0]["guard_result"] = "blocked"
        errors = trace_errors(result, require_freshness=True)
    result["audit"] = {"status": "rejected" if errors else "passed", "errors": errors}
    return result


def dispatch_audit_errors(packet: dict, packet_path: Path) -> list[str]:
    bindings = packet_path.parent / "role_bindings.json"
    if not bindings.is_file():
        return []
    try:
        contract = json.loads(bindings.read_text()).get("runtime_evidence")
        if not contract:
            return []  # Existing packets retain their previous validation contract.
        ledger = Path(contract["ledger"])
        if ledger.resolve().parent != packet_path.parent.resolve():
            raise ValueError("runtime_dispatch_ledger_outside_current_run")
        saved = json.loads(ledger.read_text())
        if contract.get("run_started_at") and saved["run_started_at"] != contract["run_started_at"]:
            raise ValueError("runtime_dispatch_run_start_mismatch")
        current = read_runtime_events(Path(saved["provider_session"]), saved["parent_thread_id"],
                                      saved["run_started_at"])
        if (saved["events"] != current["events"] or saved["thread_mappings"] != current["thread_mappings"]
                or saved["inventories"] != current["inventories"]):
            raise ValueError("runtime_dispatch_ledger_stale")
        latest = {row["Provider handle"]: row["Last dispatch at"] for row in current["events"]}
        errors = []
        for audit in packet.get("runtime_audits", []):
            handle = audit.get("Provider handle")
            if handle not in latest or audit.get("Last dispatch at") != latest[handle]:
                errors.append(f"runtime_audit_dispatch_mismatch:{audit.get('Worker')}")
            if audit.get("Thread ID") and audit["Thread ID"] != current["thread_mappings"].get(handle):
                errors.append(f"runtime_audit_thread_mismatch:{audit.get('Worker')}")
        return errors
    except (OSError, ValueError, KeyError, TypeError, AttributeError, StopIteration) as error:
        return [f"runtime_dispatch_evidence_invalid:{error}"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider-session", type=Path, required=True)
    parser.add_argument("--parent-thread-id", required=True)
    parser.add_argument("--started-at", required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--worker-session", type=Path)
    parser.add_argument("--observation", type=Path)
    parser.add_argument("--agent")
    parser.add_argument("--trace", type=Path)
    args = parser.parse_args()
    if any((args.worker_session, args.observation, args.agent, args.trace)) and not all(
            (args.worker_session, args.observation, args.agent, args.trace)):
        parser.error("trace export requires --worker-session, --observation, --agent and --trace")
    try:
        result = read_runtime_events(args.provider_session, args.parent_thread_id, args.started_at)
        if args.trace:
            if args.trace.resolve().parent != args.ledger.resolve().parent:
                raise ValueError("worker_trace_outside_current_run")
            trace = export_worker_trace(result, args.worker_session, args.agent,
                                        json.loads(args.observation.read_text()))
            packet_path = args.trace.parent / "finalization_packet.json"
            if packet_path.is_file():
                trace["run_id"] = json.loads(packet_path.read_text())["identity"]["Run ID"]
            if args.trace.is_file():
                saved = json.loads(args.trace.read_text())
                if saved.get("audit", {}).get("status") == "rejected" and saved != trace:
                    raise ValueError("worker_trace_rejected_evidence_requires_new_path")
            args.trace.write_text(json.dumps(trace, indent=2) + "\n")
        args.ledger.write_text(json.dumps(result, indent=2) + "\n")
        if args.trace and trace["audit"]["errors"]:
            print(json.dumps({"status": "blocked", "errors": trace["audit"]["errors"],
                              "trace": str(args.trace), "ledger": str(args.ledger)}))
            return 2
    except (OSError, ValueError, KeyError, TypeError, AttributeError, StopIteration) as error:
        print(json.dumps({"status": "blocked", "reason": str(error)}))
        return 2
    print(json.dumps({"status": "recorded", "ledger": str(args.ledger),
                      "thread_mappings": result["thread_mappings"], "dispatch_count": len(result["events"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
