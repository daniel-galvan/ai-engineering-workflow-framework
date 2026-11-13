import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from scripts import prepare_run
from scripts import runtime_checks
from scripts.prepare_worker_response import prepare_response, validate_response
from scripts.review_evidence import PLAN_FIXTURE, REVIEW_FIXTURE
from scripts.merge_techops_result import WORKERS, merge_result
from scripts.provider_runtime import read_runtime_events
from scripts.worker_runtime_evidence import export_worker_trace, worker_final_response
from scripts.validate_worker_runtime import activation_message, dispatch_message
from scripts.workflow_policy import WORKER_RESPONSE_SUBMITTED


PARENT = "00000000-0000-0000-0000-000000000001"
CHILD = "00000000-0000-0000-0000-000000000002"
TURN = "00000000-0000-0000-0000-000000000003"
CORRECTION_TURN = "00000000-0000-0000-0000-000000000004"
HANDLE = "/root/current_state_investigator"


class WorkerResponseMaterialization(unittest.TestCase):
    def test_review_collector_rejects_unstructured_candidate_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "finalization_packet.json").write_text('{}')
            at = "2026-11-02T20:00:00Z"
            stage = root / ".worker_responses" / "reviewer" / hashlib.sha256(at.encode()).hexdigest()[:16]
            stage.mkdir(parents=True)
            fields = f"Repository: {root}\nBase revision: abc1234\nCandidate SHA256: {'a' * 64}\nUntracked candidate files: two files\n"
            response = json.dumps({"output": REVIEW_FIXTURE.replace("## Scope\n", "## Scope\n" + fields), "result": {}})
            (stage / "result.json").write_text('{}')
            (stage / "output.md").write_text(json.loads(response)["output"])
            (stage / "response.json").write_text(response)
            receipt = {"dispatch_at": at}
            for field, name, hash_field in (("path", "result.json", "sha256"),
                    ("output_path", "output.md", "output_sha256"), ("response_path", "response.json", "response_sha256")):
                path = stage / name
                receipt[field] = str(path)
                receipt[hash_field] = hashlib.sha256(path.read_bytes()).hexdigest()
            trace = {"trace_retrieval": str(root / "session.jsonl"), "last_dispatch_at": at,
                     "status_observation": {"Observed at": "2026-11-02T20:05:00Z"}, "result_artifact": receipt}
            bindings = {"playbook": "techops_issue_remediation", "lifecycle": "remediation",
                        "worker_contracts": {"reviewer": {"result_hash_required": True}}}
            with patch("scripts.worker_runtime_evidence.worker_final_response", return_value=response), \
                 patch("scripts.merge_techops_result.validated_result"):
                errors = runtime_checks.result_artifact_errors(trace, bindings, root, "reviewer")
            self.assertTrue(any("Untracked candidate files must be a JSON array" in error for error in errors), errors)

    def test_accepted_remediation_review_checks_plan_coverage_before_handoff(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packet = root / "finalization_packet.json"
            packet.write_text(json.dumps({"identity": {"Run ID": "run"}}))
            (root / "role_bindings.json").write_text(json.dumps({"run_id": "run", "lifecycle": "remediation",
                "playbook": "techops_issue_remediation", "source_checkout": str(root)}))
            (root / "implementation_plan.md").write_text(PLAN_FIXTURE)
            fields = f"Repository: {root}\nBase revision: abc1234\nCandidate SHA256: {'a' * 64}\nUntracked candidate files: []\n"
            valid_review = REVIEW_FIXTURE.replace("## Scope\n", "## Scope\n" + fields)
            response = {"result": {}, "output": valid_review}
            with patch("scripts.prepare_worker_response.validated_result"), \
                 patch("scripts.review_evidence.candidate_fingerprint", return_value="a" * 64):
                self.assertEqual(json.loads(validate_response(packet, "reviewer", response)), response)
                response["output"] = valid_review.replace("Candidate SHA256: " + "a" * 64, "Candidate SHA256: " + "b" * 64)
                with self.assertRaisesRegex(ValueError, "fingerprint does not match"):
                    validate_response(packet, "reviewer", response)
                response["output"] = valid_review.replace("Untracked candidate files: []", "Untracked candidate files: two files")
                with self.assertRaisesRegex(ValueError, "Untracked candidate files must be a JSON array"):
                    validate_response(packet, "reviewer", response)
                for invalid in ('["../outside"]', '["/absolute"]', '["a", "a"]', '[1]'):
                    response["output"] = valid_review.replace("Untracked candidate files: []", "Untracked candidate files: " + invalid)
                    with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, "Untracked candidate files must be a JSON array"):
                        validate_response(packet, "reviewer", response)
                response["output"] = valid_review.replace("Asset-only edit preserves publication", "Renamed behavior")
                with self.assertRaisesRegex(ValueError, "review_plan_coverage_invalid.*review omits"):
                    validate_response(packet, "reviewer", response)
                response["output"] = valid_review.replace("| Source path trace | pass |", "| Source path trace | verified |")
                with self.assertRaisesRegex(ValueError, "review_plan_coverage_invalid.*validation row 1 has invalid result"):
                    validate_response(packet, "reviewer", response)
                response["output"] = REVIEW_FIXTURE.replace("Asset-only edit preserves publication", "Renamed behavior")
                response["output"] = response["output"].replace("Disposition: accepted", "Disposition: changes_required")
                self.assertEqual(json.loads(validate_response(packet, "reviewer", response)), response)

    def test_response_builder_checks_schema_and_serializes_without_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            inputs = repository / "inputs.json"
            inputs.write_text(json.dumps({"schema_version": 1, "status": "explicit", "inputs": [{
                "Input ID": "IN-001", "Input or artifact": "Current request", "Source or path": "User",
                "Authority": "User", "Classification": "request", "Expected use": "Investigate", "Status": "Verified"}]}))
            run = prepare_run.prepare_run(repository, "ITEM-1", "techops_issue_remediation", None, False,
                                          input_manifest=inputs)
            packet_path = Path(run["finalization_packet"])
            original_packet = packet_path.read_bytes()
            schema = json.loads((prepare_run.ROOT / "templates/finalization_packet.json").read_text())
            result = {"run_id": run["run_id"], "worker_result": {
                **dict.fromkeys(schema["worker_results"][0], "Current evidence"),
                "Worker": "issue-evidence", "Outcome": "complete"},
                "evidence": [{**dict.fromkeys(schema["evidence"][0], "Observed"), "Evidence ID": "E-ISS-001"}],
                "claims": [], "decisions": [], "actions": [],
                "integration_decision": {"decision": "not_required", "reason": "One component", "evidence_refs": "E-ISS-001"}}
            result_path, output_path = repository / "draft.json", repository / "draft.md"
            result_path.write_text(json.dumps(result))
            output_path.write_text('A quote: " and a newline\n')
            response = json.loads(prepare_response(packet_path, "current_state_investigator", result_path, output_path))
            self.assertEqual(response, {"output": output_path.read_text(), "result": result})
            command = [sys.executable, str(prepare_run.ROOT / "scripts/prepare_worker_response.py"),
                       "--packet", str(packet_path), "--agent", "current_state_investigator", "--response-stdin"]
            checked = subprocess.run(command, input=json.dumps(response), text=True, capture_output=True)
            self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
            self.assertEqual(json.loads(checked.stdout), response)
            session = repository / 'worker.jsonl'
            shell = ("cat <<'RESPONSE' | " + ' '.join(command) + '\n'
                     + json.dumps(response) + '\nRESPONSE')
            rows = [
                {'type': 'session_meta', 'timestamp': '2026-11-01T00:00:00Z', 'payload': {'id': CHILD}},
                {'type': 'turn_context', 'timestamp': '2026-11-01T00:00:01Z', 'payload': {'turn_id': TURN}},
                {'type': 'event_msg', 'timestamp': '2026-11-01T00:00:02Z', 'payload': {'type': 'item_completed',
                    'item': {'type': 'CommandExecution', 'command': ['/bin/bash', '-lc', shell],
                             'status': 'completed', 'exit_code': 0, 'aggregated_output': checked.stdout}}},
                {'type': 'response_item', 'timestamp': '2026-11-01T00:00:03Z', 'payload': {
                    'type': 'message', 'role': 'assistant', 'phase': 'final_answer',
                    'content': [{'type': 'output_text', 'text': WORKER_RESPONSE_SUBMITTED}]}},
            ]
            def submitted(events):
                session.write_text(''.join(json.dumps(row) + '\n' for row in events))
                return worker_final_response(session, '2026-11-01T00:00:00Z', '2026-11-01T00:00:04Z',
                                             turn_id=TURN, packet_path=packet_path,
                                             agent='current_state_investigator', builder=Path(command[1]))
            self.assertEqual(json.loads(submitted(rows)), response)
            warned = json.loads(json.dumps(rows))
            warning = ("WARNING: proceeding, even though we could not create PATH aliases: "
                       "Operation not permitted (os error 1)\n")
            warned[2]['payload']['item']['aggregated_output'] = warning + checked.stdout
            self.assertEqual(json.loads(submitted(warned)), response)
            warned[2]['payload']['item']['aggregated_output'] = "unexpected warning\n" + checked.stdout
            with self.assertRaisesRegex(ValueError, 'submission_invalid'):
                submitted(warned)
            presented = json.loads(json.dumps(rows))
            presented[-1]['payload']['content'][0]['text'] = '  ' + WORKER_RESPONSE_SUBMITTED + '.\n'
            self.assertEqual(json.loads(submitted(presented)), response)
            direct = json.loads(json.dumps(rows))
            direct[2]['payload']['item']['command'][-1] = (' '.join(command) + " <<'RESPONSE'\n"
                                                          + json.dumps(response) + '\nRESPONSE')
            self.assertEqual(json.loads(submitted(direct)), response)
            for argument, value in (("--agent current_state_investigator", "--agent reviewer"),
                                    (str(packet_path), str(repository / "other.json"))):
                changed = json.loads(json.dumps(rows))
                changed[2]['payload']['item']['command'][-1] = shell.replace(argument, value)
                with self.subTest(argument=argument), self.assertRaisesRegex(ValueError, 'submission_invalid'):
                    submitted(changed)
            changed = json.loads(json.dumps(rows))
            changed[2]['payload']['item']['command'][0] = '/bin/echo'
            with self.assertRaisesRegex(ValueError, 'submission_invalid'):
                submitted(changed)
            for field, value in (('exit_code', 1), ('aggregated_output', '{broken')):
                changed = json.loads(json.dumps(rows))
                changed[2]['payload']['item'][field] = value
                with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'submission_invalid'):
                    submitted(changed)
            with self.assertRaisesRegex(ValueError, 'submission_missing'):
                submitted([rows[0], rows[1], rows[3]])
            missing_decision = {**response, "result": dict(response["result"])}
            del missing_decision["result"]["integration_decision"]
            rejected = subprocess.run(command, input=json.dumps(missing_decision), text=True, capture_output=True)
            self.assertEqual(rejected.returncode, 2)
            self.assertIn("techops_integration_decision_required", json.loads(rejected.stdout)["reason"])
            malformed = subprocess.run(command, input='{broken', text=True, capture_output=True)
            self.assertEqual(malformed.returncode, 2)
            self.assertEqual(json.loads(malformed.stdout)["status"], "invalid")
            self.assertEqual(packet_path.read_bytes(), original_packet)
            del result["worker_result"]["Confidence"]
            result_path.write_text(json.dumps(result))
            with self.assertRaisesRegex(ValueError, "worker_result_summary_schema_invalid"):
                prepare_response(packet_path, "current_state_investigator", result_path, output_path)
            result_path.write_text('{"run_id": "a", "run_id": "b"}')
            with self.assertRaises(ValueError):
                prepare_response(packet_path, "current_state_investigator", result_path, output_path)
            self.assertEqual(packet_path.read_bytes(), original_packet)

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
                "Worker": worker, "Outcome": "complete"}, "evidence": [
                    {**dict.fromkeys(schema["evidence"][0], "Current observation"), "Evidence ID": "E-ISS-001"}],
                "integration_decision": {"decision": "not_required", "reason": "One component", "evidence_refs": "E-ISS-001"},
                "claims": [],
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
            self.assertIn("Do not write the assigned output or result files directly", contract["result_instructions"])
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
                "integration_decision": {"decision": "not_required", "reason": "One component",
                                         "evidence_refs": evidence_id},
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
                event(7, "event_msg", {"item": {"type": "SubAgentActivity", "kind": "completed",
                    "agent_path": HANDLE}}),
                event(8.5, "response_item", {"type": "function_call", "namespace": "collaboration",
                    "name": "followup_task", "call_id": "correction",
                    "arguments": json.dumps({"target": HANDLE, "message": "Repair the response envelope"})}),
                event(8.75, "response_item", {"type": "function_call_output", "call_id": "correction",
                    "output": "Correction delivered"}),
                event(11, "event_msg", {"item": {"type": "SubAgentActivity", "kind": "completed",
                    "agent_path": HANDLE}}),
                event(12, "response_item", {"type": "function_call", "namespace": "collaboration",
                    "name": "list_agents", "call_id": "inventory", "arguments": "{}"}),
                event(13, "response_item", {"type": "function_call_output", "call_id": "inventory",
                    "output": json.dumps({"agents": [{"agent_name": HANDLE,
                        "agent_status": {"completed": "Completed"}}]})}),
            ]
            parent.write_text("\n".join(json.dumps(row) for row in parent_rows) + "\n")

            activation_read = dispatch_file.read_text()
            sessions = root / ".codex" / "sessions"
            sessions.mkdir(parents=True)
            child = sessions / f"rollout-{CHILD}.jsonl"
            child_rows = [
                event(0, "session_meta", {"id": CHILD}),
                event(2, "response_item", {"type": "function_call", "name": "exec_command",
                    "call_id": "binding-read", "arguments": json.dumps({"cmd": "cat " + str(dispatch_file)})}),
                event(3, "response_item", {"type": "function_call_output", "call_id": "binding-read",
                    "output": activation_read}),
                event(4.25, "turn_context", {"turn_id": TURN, "model": packet["model"], "effort": packet["effort"]}),
                event(5, "response_item", {"type": "custom_tool_call", "name": "exec", "call_id": "input-read",
                    "input": "const r = await tools.exec_command(" + json.dumps({
                        "cmd": "cat " + str(root / "run_inputs.json")}) + "); text(r);"}),
                event(6, "response_item", {"type": "custom_tool_call_output", "call_id": "input-read",
                    "output": (root / "run_inputs.json").read_text()}),
                event(8, "response_item", {"type": "message", "role": "assistant", "phase": "final_answer",
                    "content": [{"type": "output_text", "text": json.dumps({
                        "output": "Stale pre-correction response.", "result": result})}]}),
                event(9.25, "turn_context", {"turn_id": CORRECTION_TURN, "model": packet["model"],
                    "effort": packet["effort"]}),
                event(10, "response_item", {"type": "message", "role": "assistant", "phase": "final_answer",
                    "content": [{"type": "output_text", "text": response}]}),
            ]
            builder_command = [sys.executable, contract["response_builder"], "--packet", run["finalization_packet"],
                               "--agent", role, "--response-stdin"]
            preview = subprocess.run(builder_command, input=response, text=True, capture_output=True)
            self.assertEqual(preview.returncode, 0, preview.stdout + preview.stderr)
            shell = ' '.join(builder_command) + " <<'RESPONSE'\n" + response + "\nRESPONSE"
            child_rows.insert(-1, event(9.5, "event_msg", {"type": "item_completed", "item": {
                "type": "CommandExecution", "command": ["/bin/bash", "-lc", shell],
                "status": "completed", "exit_code": 0, "aggregated_output": (
                    "WARNING: proceeding, even though we could not create PATH aliases: "
                    "Operation not permitted (os error 1)\n" + preview.stdout)}}))
            child_rows[-1]["payload"]["content"][0]["text"] = WORKER_RESPONSE_SUBMITTED
            child.write_text("\n".join(json.dumps(row) for row in child_rows) + "\n")

            latest_turn_start = base + timedelta(seconds=9.25)
            provider_turn_start = datetime.fromtimestamp(int(latest_turn_start.timestamp()), timezone.utc)
            observed_at = (base + timedelta(seconds=14)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            dispatch_at = (base + timedelta(seconds=8.5)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            completed_at = (base + timedelta(seconds=10)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            observation = {"Provider handle": HANDLE, "Thread ID": CHILD, "Provider status": "idle",
                "Observed at": observed_at, "Status source": "read_thread", "Last dispatch at": dispatch_at,
                "Latest turn started at": provider_turn_start.isoformat().replace("+00:00", "Z"),
                "Latest turn ID": CORRECTION_TURN, "Latest turn completed at": completed_at,
                "Latest turn status": "completed", "Thread status": "idle"}
            provider_response = {"thread": {"id": CHILD, "status": {"type": "idle"}}, "turns": [{
                "id": CORRECTION_TURN, "status": "completed", "startedAt": provider_turn_start.timestamp(),
                "completedAt": (base + timedelta(seconds=10)).timestamp()}]}
            parent_rows.extend([
                event(13.1, "response_item", {"type": "custom_tool_call", "name": "exec", "call_id": "status",
                    "input": "const r = await tools.mcp__codex_app__read_thread(" + json.dumps({
                        "threadId": CHILD, "turnLimit": 1, "includeOutputs": False})
                        + "); text(JSON.stringify(r.content[0].text));"}),
                event(14, "response_item", {"type": "custom_tool_call_output", "call_id": "status", "output": [
                    {"type": "input_text", "text": "Script completed\nWall time 0.1 seconds\nOutput:\n"},
                    {"type": "input_text", "text": json.dumps(json.dumps(provider_response))}]}),
            ])
            parent.write_text("\n".join(json.dumps(row) for row in parent_rows) + "\n")
            ledger = read_runtime_events(parent, PARENT, run["runtime_evidence"]["run_started_at"])
            trace = export_worker_trace(ledger, child, role, run_id=run["run_id"], artifact_root=root)
            self.assertEqual(trace["audit"]["status"], "passed", trace["audit"]["errors"])
            self.assertNotIn("forbidden_context_reference:session_log", trace["audit"]["errors"])
            self.assertEqual(trace["status_observation"]["Latest turn ID"], CORRECTION_TURN)
            with self.assertRaisesRegex(ValueError, "worker_final_response_turn_id_required"):
                worker_final_response(child, trace["last_dispatch_at"], observed_at,
                                      observation["Latest turn started at"])
            with self.assertRaisesRegex(ValueError, "worker_final_response_turn_context_mismatch"):
                worker_final_response(child, trace["last_dispatch_at"], observed_at,
                                      observation["Latest turn started at"], turn_id=TURN)
            self.assertNotEqual(Path(trace["result_artifact"]["path"]), result_path)
            self.assertEqual(json.loads(Path(trace["result_artifact"]["path"]).read_text()), result)
            self.assertEqual(Path(trace["result_artifact"]["output_path"]).read_text(), narrative)
            self.assertFalse(output_path.exists())
            self.assertFalse(result_path.exists())

            unrelated = sessions / "unrelated.jsonl"
            unrelated_rows = list(child_rows)
            unrelated_rows[0] = event(0, "session_meta", {"id": "unrelated-thread"})
            unrelated.write_text("\n".join(json.dumps(row) for row in unrelated_rows) + "\n")
            mismatched = {**trace, "trace_retrieval": str(unrelated)}
            errors = runtime_checks.trace_errors(mismatched, require_freshness=True)
            self.assertIn("worker_trace_session_mismatch", errors)
            self.assertIn("forbidden_context_reference:session_log",
                          runtime_checks.context_trace_errors(mismatched))

            Path(run["runtime_evidence"]["ledger"]).write_text(json.dumps(ledger))
            trace_path = root / "trace.json"
            trace_path.write_text(json.dumps(trace))
            packet_path = Path(run["finalization_packet"])
            merge_result(packet_path, role, trace=trace_path)
            self.assertEqual(output_path.read_text(), narrative)
            self.assertEqual(json.loads(result_path.read_text()), result)
            self.assertEqual(json.loads(packet_path.read_text())["worker_results"][0]["Worker"], worker)
            self.assertEqual(json.loads(packet_path.read_text())["workers"][0]["Tools"], "exec_command")


if __name__ == "__main__":
    unittest.main()
