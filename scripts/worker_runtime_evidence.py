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
        for line in stream:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                if not line.endswith("\n"):
                    break  # The provider may still be appending the last event.
                raise ValueError("provider_session_event_invalid") from None
            if timestamp(row["timestamp"]) < started:
                continue
            payload = row.get("payload", {})
            item = payload.get("item", {})
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
    return {"schema_version": 1, "parent_thread_id": parent_thread_id, "run_started_at": started_at,
            "provider_session": str(path.resolve()), "events": events,
            "thread_mappings": mappings, "inventories": inventories}


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
    args = parser.parse_args()
    try:
        result = read_runtime_events(args.provider_session, args.parent_thread_id, args.started_at)
        args.ledger.write_text(json.dumps(result, indent=2) + "\n")
    except (OSError, ValueError, KeyError, TypeError, AttributeError, StopIteration) as error:
        print(json.dumps({"status": "blocked", "reason": str(error)}))
        return 2
    print(json.dumps({"status": "recorded", "ledger": str(args.ledger),
                      "thread_mappings": result["thread_mappings"], "dispatch_count": len(result["events"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
