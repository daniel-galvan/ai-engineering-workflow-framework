import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts import prepare_run
from scripts.merge_techops_result import WORKERS, merge_result
from scripts.provider_runtime import read_runtime_events
from scripts.worker_runtime_evidence import export_worker_trace
from scripts.validate_worker_runtime import activation_message, dispatch_message


PARENT = "00000000-0000-0000-0000-000000000001"
CHILD = "00000000-0000-0000-0000-000000000002"
TURN = "00000000-0000-0000-0000-000000000003"
HANDLE = "/root/current_state_investigator"


class WorkerResponseMaterialization(unittest.TestCase):
    def test_legacy_contract_reads_the_prepared_canonical_result(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            inputs = repository / "inputs.json"
            inputs.write_text(json.dumps({"schema_version": 1, "status": "explicit", "inputs": [{
                "Input ID": "IN-001", "Input or artifact": "Current request", "Source or path": "User",
                "Authority": "User", "Classification": "supplied occurrence",
                "Expected use": "Investigate", "Status": "Verified"}]}))
            run = prepare_run.prepare_run(repository, "ITEM-1", "techops_issue_remediation", None, False,
                                          input_manifest=inputs)
            root = Path(run["artifact_root"])
            role = "current_state_investigator"
            worker, _ = WORKERS[role]
            bindings_path = root / "role_bindings.json"
            bindings = json.loads(bindings_path.read_text())
            bindings["worker_contracts"][role].pop("result_hash_required")
            bindings["worker_contracts"][role].pop("result_response")
            bindings_path.write_text(json.dumps(bindings))
            schema = json.loads((prepare_run.ROOT / "templates/finalization_packet.json").read_text())
            result = {"run_id": run["run_id"], "worker_result": {
                **dict.fromkeys(schema["worker_results"][0], "Legacy current result"),
                "Worker": worker, "Outcome": "complete"}, "evidence": [], "claims": [],
                "decisions": [], "actions": []}
            result_path = Path(bindings["worker_contracts"][role]["result"])
            result_path.write_text(json.dumps(result))
            merge_result(Path(run["finalization_packet"]), role)
            self.assertEqual(json.loads(Path(run["finalization_packet"]).read_text())[
                "worker_results"][0]["Worker"], worker)

    def test_read_only_worker_response_is_materialized_and_merged_without_prefilled_files(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            inputs = repository / "inputs.json"
            inputs.write_text(json.dumps({"schema_version": 1, "status": "explicit", "inputs": [{
                "Input ID": "IN-001", "Input or artifact": "Current request", "Source or path": "User",
                "Authority": "User", "Classification": "supplied occurrence",
                "Expected use": "Investigate", "Status": "Verified"}]}))
            run = prepare_run.prepare_run(repository, "ITEM-1", "techops_issue_remediation", None, False,
                                          input_manifest=inputs)
            root = Path(run["artifact_root"])
            role = "current_state_investigator"
            packet = json.loads(Path(run["activation_packet_bundle"]["path"]).read_text())["packets"][role]
            contract = packet["worker_contract"]
            output_path, result_path = Path(contract["output"]), Path(contract["result"])
            self.assertFalse(output_path.exists())
            self.assertFalse(result_path.exists())

            worker, namespace = WORKERS[role]
            schema = json.loads((prepare_run.ROOT / "templates/finalization_packet.json").read_text())
            evidence_id = f"E-{namespace}-001"
            result = {
                "run_id": run["run_id"],
                "worker_result": {**dict.fromkeys(schema["worker_results"][0], "Observed in the current request"),
                                  "Worker": worker, "Outcome": "complete",
                                  "Evidence / claim refs": evidence_id},
                "evidence": [{**dict.fromkeys(schema["evidence"][0], "Current request observation"),
                              "Evidence ID": evidence_id}],
                "claims": [], "decisions": [], "actions": [],
            }
            narrative = "Current-run issue evidence."
            response = json.dumps({"output": narrative, "result": result})

            base = datetime.fromisoformat(run["prepared_at"].replace("Z", "+00:00"))

            def event(seconds, kind, payload):
                stamp = (base + timedelta(seconds=seconds)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
                return {"timestamp": stamp, "type": kind, "payload": payload}

            assignment = {"objective": "Inspect the supplied issue and return the evidence result."}
            dispatch_file = root / "activation.txt"
            complete_message = dispatch_message(packet, activation_message(packet, assignment), dispatch_file)
            parent = root / "parent.jsonl"
            parent_rows = [
                event(0, "session_meta", {"id": PARENT}),
                event(1, "response_item", {"type": "function_call", "namespace": "collaboration",
                    "name": "spawn_agent", "call_id": "spawn", "arguments": json.dumps({
                        "task_name": role, "message": complete_message, "fork_turns": "none",
                        "model": packet["model"], "reasoning_effort": packet["effort"]})}),
                event(1, "event_msg", {"item": {"type": "SubAgentActivity", "kind": "started",
                    "agent_path": HANDLE, "agent_thread_id": CHILD}}),
                event(2, "response_item", {"type": "function_call_output", "call_id": "spawn", "output": ""}),
                event(9, "response_item", {"type": "function_call", "namespace": "collaboration",
                    "name": "list_agents", "call_id": "inventory", "arguments": "{}"}),
                event(10, "response_item", {"type": "function_call_output", "call_id": "inventory",
                    "output": json.dumps({"agents": [{"agent_name": HANDLE,
                        "agent_status": {"completed": "Completed"}}]})}),
            ]
            parent.write_text("\n".join(json.dumps(row) for row in parent_rows) + "\n")

            activation_read = dispatch_file.read_text()
            child = root / "child.jsonl"
            child_rows = [
                event(0, "session_meta", {"id": CHILD}),
                event(2, "response_item", {"type": "function_call", "name": "exec_command",
                    "call_id": "binding-read", "arguments": json.dumps({"cmd": "cat " + str(dispatch_file)})}),
                event(3, "response_item", {"type": "function_call_output", "call_id": "binding-read",
                    "output": activation_read}),
                event(4, "turn_context", {"turn_id": TURN, "model": packet["model"], "effort": packet["effort"]}),
                event(8, "response_item", {"type": "message", "role": "assistant", "phase": "final_answer",
                    "content": [{"type": "output_text", "text": response}]}),
            ]
            child.write_text("\n".join(json.dumps(row) for row in child_rows) + "\n")

            observed_at = (base + timedelta(seconds=11)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            dispatch_at = (base + timedelta(seconds=1)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            completed_at = (base + timedelta(seconds=8)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            observation = {"Provider handle": HANDLE, "Thread ID": CHILD, "Provider status": "idle",
                "Observed at": observed_at, "Status source": "read_thread", "Last dispatch at": dispatch_at,
                "Latest turn started at": (base + timedelta(seconds=4)).isoformat().replace("+00:00", "Z"),
                "Latest turn completed at": completed_at, "Latest turn status": "completed", "Thread status": "idle"}
            ledger = read_runtime_events(parent, PARENT, run["runtime_evidence"]["run_started_at"])
            trace = export_worker_trace(ledger, child, role, observation, run_id=run["run_id"], artifact_root=root)
            self.assertEqual(trace["audit"]["status"], "passed", trace["audit"]["errors"])
            self.assertNotEqual(Path(trace["result_artifact"]["path"]), result_path)
            self.assertEqual(json.loads(Path(trace["result_artifact"]["path"]).read_text()), result)
            self.assertEqual(Path(trace["result_artifact"]["output_path"]).read_text(), narrative)
            self.assertFalse(output_path.exists())
            self.assertFalse(result_path.exists())

            Path(run["runtime_evidence"]["ledger"]).write_text(json.dumps(ledger))
            trace_path = root / "trace.json"
            trace_path.write_text(json.dumps(trace))
            packet_path = Path(run["finalization_packet"])
            merge_result(packet_path, role, trace=trace_path)
            self.assertEqual(output_path.read_text(), narrative)
            self.assertEqual(json.loads(result_path.read_text()), result)
            self.assertEqual(json.loads(packet_path.read_text())["worker_results"][0]["Worker"], worker)


if __name__ == "__main__":
    unittest.main()
