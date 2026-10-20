import json
from datetime import datetime, timedelta
from pathlib import Path

from scripts import provider_runtime, validate_worker_runtime
from scripts.worker_runtime_evidence import export_worker_trace


PARENT = "00000000-0000-0000-0000-000000000101"
CHILD = "00000000-0000-0000-0000-000000000102"
_DISPATCH_COUNTS = {}


def stage_worker_response(run, role, result, output="Synthetic worker response."):
    """Build a fresh provider trace around one final response for merger tests."""
    root = Path(run["artifact_root"])
    key = (run["run_id"], role)
    count = _DISPATCH_COUNTS.get(key, 0)
    dispatch_seconds = 1 + count * 20
    bundle = json.loads(Path(run["activation_packet_bundle"]["path"]).read_text())
    packet = bundle["packets"][role]
    activation = root / "activation.txt"
    message = validate_worker_runtime.dispatch_message(
        packet, validate_worker_runtime.activation_message(packet, {"objective": "Return the current result"}), activation)
    base = datetime.fromisoformat(run["prepared_at"].replace("Z", "+00:00"))

    def event(seconds, kind, **payload):
        return {"timestamp": (base + timedelta(seconds=seconds)).isoformat(), "type": kind, "payload": payload}

    bindings = json.loads((root / "role_bindings.json").read_text())
    parent_context = bindings.get("parent_context")
    parent_thread_id = parent_context["parent_thread_id"] if parent_context else PARENT
    parent = (Path(parent_context["provider_session"]) if parent_context
              else root / "worker_response_parent.jsonl")
    if parent.exists():
        parent_rows = [json.loads(line) for line in parent.read_text().splitlines()]
        if (not parent_rows or parent_rows[0].get("type") != "session_meta"
                or parent_rows[0].get("payload", {}).get("id") != parent_thread_id):
            raise ValueError("fixture_parent_session_mismatch")
    else:
        parent_rows = [event(0, "session_meta", id=parent_thread_id)]
    parent_rows.extend([
        event(1, "response_item", type="function_call", namespace="collaboration", name="spawn_agent",
              call_id="spawn", arguments=json.dumps({"task_name": "worker", "message": message,
                  "fork_turns": "none", "model": packet["model"], "reasoning_effort": packet["effort"]})),
        event(1, "event_msg", item={"type": "SubAgentActivity", "kind": "started",
              "agent_path": "/root/worker", "agent_thread_id": CHILD}),
        event(2, "response_item", type="function_call_output", call_id="spawn", output=""),
        event(4, "event_msg", item={"type": "SubAgentActivity", "kind": "completed", "agent_path": "/root/worker"}),
    ])
    if count:
        parent_rows.extend([
            event(dispatch_seconds, "response_item", type="function_call", namespace="collaboration",
                  name="followup_task", call_id="followup", arguments=json.dumps({
                      "target": "/root/worker", "message": "Return the current corrected result"})),
            event(dispatch_seconds + 1, "response_item", type="function_call_output", call_id="followup", output=""),
            event(dispatch_seconds + 4, "event_msg", item={"type": "SubAgentActivity", "kind": "completed",
                  "agent_path": "/root/worker"}),
        ])
    parent.write_text("\n".join(json.dumps(row) for row in parent_rows) + "\n")

    child = root / "worker_response_child.jsonl"
    child_rows = [
        event(0, "session_meta", id=CHILD),
        event(dispatch_seconds + 1, "response_item", type="custom_tool_call", call_id="binding", name="exec",
              input='await tools.exec_command(' + json.dumps({"cmd": "cat " + str(activation)}) + ')'),
        event(dispatch_seconds + 2, "response_item", type="custom_tool_call_output", call_id="binding", output=activation.read_text()),
        event(dispatch_seconds + 2, "turn_context", turn_id="00000000-0000-0000-0000-000000000103",
              model=packet["model"], effort=packet["effort"]),
        event(dispatch_seconds + 3, "response_item", type="message", role="assistant", phase="final_answer",
              content=[{"type": "output_text", "text": json.dumps({"output": output, "result": result,
                  **({"asset_manifest": {}} if packet.get("worker_contract", {}).get("asset_inventory") else {})})}]),
    ]
    child.write_text("\n".join(json.dumps(row) for row in child_rows) + "\n")

    stamp = lambda seconds: (base + timedelta(seconds=seconds)).isoformat()
    observation = {"Provider handle": "/root/worker", "Thread ID": CHILD, "Provider status": "idle",
        "Observed at": stamp(dispatch_seconds + 5), "Status source": "read_thread", "Last dispatch at": stamp(dispatch_seconds),
        "Latest turn started at": stamp(dispatch_seconds + 2), "Latest turn completed at": stamp(dispatch_seconds + 3),
        "Latest turn status": "completed", "Thread status": "idle"}
    ledger = provider_runtime.read_runtime_events(parent, parent_thread_id, run["runtime_evidence"]["run_started_at"])
    trace = export_worker_trace(ledger, child, role, observation, run_id=run["run_id"], artifact_root=root)
    Path(run["runtime_evidence"]["ledger"]).write_text(json.dumps(ledger))
    trace_path = root / "worker_response_trace.json"
    trace_path.write_text(json.dumps(trace))
    _DISPATCH_COUNTS[key] = count + 1
    return trace_path, trace
