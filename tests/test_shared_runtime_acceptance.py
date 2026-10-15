"""Shared receipt acceptance across prepared playbook roles; no live workers."""

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from scripts import prepare_run as preparation
from scripts import validate_worker_runtime as runtime
from scripts import finalize_work_record as finalizer
from scripts.worker_runtime_evidence import read_runtime_events, export_worker_trace

PARENT = "00000000-0000-0000-0000-000000000001"
CHILD = "00000000-0000-0000-0000-000000000002"
CASES = {
    "sentry_issue_remediation": ("sentry_current_state_investigator", "sentry_solution_architect", "documenter"),
    "feature_delivery": ("current_state_investigator", "dependency_analyst", "solution_architect",
                         "implementer", "reviewer", "tester", "documenter"),
    "techops_issue_remediation": ("current_state_investigator", "solution_architect", "documenter"),
}


class SharedRuntimeAcceptance(unittest.TestCase):
    def fixture(self, directory, playbook="feature_delivery", role="current_state_investigator", remediation=False):
        repository = Path(directory)
        inputs = repository / "inputs.json"
        inputs.write_text(json.dumps({"schema_version": 1, "status": "explicit", "inputs": [{
            "Input ID": "IN-001", "Input or artifact": "Supplied synthetic occurrence", "Source or path": "User",
            "Authority": "User", "Classification": "supplied occurrence", "Expected use": "Investigate", "Status": "Verified"}]}))
        run = preparation.prepare_run(repository, "ITEM-1", playbook, None, False, input_manifest=inputs)
        root = Path(run["artifact_root"])
        if remediation:
            from scripts.review_evidence import PLAN_FIXTURE
            final = root / "finalization_packet.json"
            prior = json.loads(final.read_text())
            prior["identity"].update({"Lifecycle": "planning", "State": "ready_for_implementation",
                                      "Requested profile": "standard", "Workflow outcome": "completed"})
            final.write_text(json.dumps(prior))
            (root / "implementation_plan.md").write_text(PLAN_FIXTURE)
            (root / "runtime_closure.json").write_text(json.dumps({"runtime_closure": [{
                "Run or stage": "planning", "Receipt owner": "Coordinator",
                "Completed worker handles": "/root/handoff", "Runtime status": "Released",
                "Remaining active handles": "None",
                "Closure evidence or blocker": "Provider close confirmed release of /root/handoff"}]}))
            run = preparation.prepare_run(repository, "ITEM-1", playbook, None, True,
                input_manifest=Path(run["run_input_manifest"]["path"]), remediation_reentry=True,
                approval_reference="Synthetic explicit user approval")
        packet = json.loads(Path(run["activation_packet_bundle"]["path"]).read_text())["packets"][role]
        contract = root / "activation.txt"
        # Test the receipt seam; lifecycle approval and stage gates have their own regression coverage.
        runtime.dispatch_message(packet, runtime.activation_message(packet, {"objective": "Inspect the supplied occurrence"}), contract)
        started = datetime.fromisoformat(run["prepared_at"].replace("Z", "+00:00"))
        time = lambda seconds: (started + timedelta(seconds=seconds)).isoformat()
        event = lambda seconds, kind, **payload: {"timestamp": time(seconds), "type": kind, "payload": payload}
        handle = "/root/worker"
        parent_rows = [event(0, "session_meta", id=PARENT),
            event(1, "response_item", type="function_call", namespace="collaboration", name="spawn_agent",
                  call_id="spawn", arguments=json.dumps({"task_name": "worker", "message": "opaque",
                    "fork_turns": "none", "model": packet["model"], "reasoning_effort": packet["effort"]})),
            event(1, "event_msg", item={"type": "SubAgentActivity", "kind": "started",
                                      "agent_path": handle, "agent_thread_id": CHILD}),
            event(2, "response_item", type="function_call_output", call_id="spawn", output=""),
            event(4, "event_msg", item={"type": "SubAgentActivity", "kind": "completed", "agent_path": handle}),
            event(5, "response_item", type="function_call", namespace="collaboration", name="followup_task",
                  call_id="followup", arguments=json.dumps({"target": handle, "message": "Publish the current result"})),
            event(6, "response_item", type="function_call_output", call_id="followup", output=""),
            event(10, "event_msg", item={"type": "SubAgentActivity", "kind": "completed", "agent_path": handle})]
        child_rows = [event(1, "session_meta", id=CHILD),
            event(2, "response_item", type="custom_tool_call", call_id="contract", name="exec",
                  input='const r = await tools.exec_command(' + json.dumps({"cmd": "cat " + str(contract)}) + '); text(r.output);'),
            event(3, "response_item", type="custom_tool_call_output", call_id="contract", output=contract.read_text()),
            event(8, "response_item", type="custom_tool_call", call_id="current", name="exec",
                  input='await tools.exec_command({cmd:"pwd"})')]
        observation = {"Provider handle": handle, "Thread ID": CHILD, "Provider status": "idle",
            "Observed at": time(20), "Status source": "read_thread", "Latest turn started at": time(5),
            "Latest turn completed at": time(10), "Latest turn status": "completed", "Thread status": "idle"}
        return run, root, role, time, event, parent_rows, child_rows, observation

    def export(self, fixture):
        run, root, role, time, event, parent_rows, child_rows, observation = fixture
        parent, child = root / "parent.jsonl", root / "child.jsonl"
        for path, rows in ((parent, parent_rows), (child, child_rows)):
            path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
        ledger = read_runtime_events(parent, PARENT, run["runtime_evidence"]["run_started_at"])
        trace = export_worker_trace(ledger, child, role, observation, run_id=run["run_id"], artifact_root=root)
        return trace, ledger

    def test_prepared_roles_keep_binding_and_pass_their_finalizer_audit_seam(self):
        for playbook, roles in CASES.items():
            for role in roles:
                with self.subTest(playbook=playbook, role=role), tempfile.TemporaryDirectory() as directory:
                    fixture = self.fixture(directory, playbook, role)
                    trace, ledger = self.export(fixture)
                    run, root, _, time, *_ = fixture
                    self.assertEqual(trace["audit"], {"status": "passed", "errors": []})
                    self.assertNotIn("activation_packet_delivered", trace["spawn"])
                    self.assertEqual(trace["last_dispatch_at"], time(5))
                    self.assertEqual(len(trace["tool_trace"]), 3)
                    trace_path = root / "trace.json"
                    trace_path.write_text(json.dumps(trace))
                    Path(run["runtime_evidence"]["ledger"]).write_text(json.dumps(ledger))
                    if playbook == "sentry_issue_remediation":
                        audited = subprocess.run([sys.executable, "-c",
                            "import json,sys; from finalize_sentry_planning import _trace_audit; "
                            "print(json.dumps(_trace_audit(json.loads(sys.argv[1]),json.loads(sys.argv[2]))))",
                            json.dumps({role: trace["spawn"]["provider_handle"]}), json.dumps([role + "=" + str(trace_path)])],
                            cwd=Path(__file__).resolve().parents[1] / "scripts", capture_output=True, text=True)
                        self.assertEqual(audited.returncode, 0, audited.stdout + audited.stderr)
                        self.assertEqual(json.loads(audited.stdout)["workers"][role], "passed")
                    else:
                        Path(run["runtime_evidence"]["ledger"]).write_text(json.dumps(ledger))
                        row = {**trace["status_observation"], "Provider status": "completed",
                               "Worker": role, "Trace path": str(trace_path)}
                        self.assertEqual(finalizer._worker_runtime_audit_errors({"runtime_audits": [row]},
                                         root / "finalization_packet.json", {role}), [])

    def test_in_turn_correction_retains_pre_correction_context(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.fixture(directory)
            _, _, _, _, event, parent, child, status = fixture
            parent[4] = event(5, "response_item", type="function_call", namespace="collaboration", name="send_message",
                              arguments=json.dumps({"target": "/root/worker", "message": "Correct the output"}))
            del parent[5:7]
            child.insert(3, event(4, "response_item", type="custom_tool_call", name="exec",
                                 input='await tools.exec_command({cmd:"cat /repo/.codex/memories/MEMORY.md"})'))
            status.update({"Latest turn started at": fixture[3](1), "Dispatch consumed": True,
                           "Dispatch consumption evidence": "Corrected artifact write and validation after dispatch"})
            trace, _ = self.export(fixture)
            self.assertIn("forbidden_context_reference:memory_directory", trace["audit"]["errors"])

    def test_previous_instruction_output_is_audited_after_contract_change(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.fixture(directory)
            run, root, role, _, event, parent, child, _ = fixture
            packet = json.loads(Path(run["activation_packet_bundle"]["path"]).read_text())["packets"][role]
            changed = root / "activation_changed.txt"
            notice = runtime.dispatch_message(packet, runtime.activation_message(packet, {"objective": "Correct output"}), changed)
            args = json.loads(parent[5]["payload"]["arguments"])
            args["message"] = notice
            parent[5]["payload"]["arguments"] = json.dumps(args)
            child.extend([event(9, "response_item", type="custom_tool_call", name="exec", call_id="new",
                input='await tools.exec_command(' + json.dumps({"cmd": "cat " + str(changed)}) + ')'),
                event(9, "response_item", type="custom_tool_call_output", call_id="new", output=changed.read_text())])
            self.assertEqual(self.export(fixture)[0]["audit"]["status"], "passed")
            child[2]["payload"]["output"] += "\n/Users/example/.codex/memories/MEMORY.md\n"
            self.assertIn("forbidden_context_reference:memory_path", self.export(fixture)[0]["audit"]["errors"])

    def test_prepared_trace_cannot_satisfy_another_role_or_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.fixture(directory)
            trace, ledger = self.export(fixture)
            run, root, *_ = fixture
            path = root / "trace.json"
            path.write_text(json.dumps(trace))
            Path(run["runtime_evidence"]["ledger"]).write_text(json.dumps(ledger))
            row = {**trace["status_observation"], "Provider status": "completed", "Worker": "reviewer", "Trace path": str(path)}
            errors = finalizer._worker_runtime_audit_errors({"runtime_audits": [row]}, root / "finalization_packet.json", {"reviewer"})
            self.assertIn("worker_trace_role_mismatch:reviewer", errors)
            for field, value, error in (("run_id", "other-run", "run"), ("thread_id", PARENT, "thread")):
                with self.subTest(field=field):
                    changed = {**trace, field: value}
                    self.assertIn("worker_trace_" + error + "_mismatch:" + fixture[2],
                        runtime.trace_identity_errors(changed, root, fixture[2], "/root/worker", CHILD))
            self.assertIn("worker_trace_handle_mismatch:" + fixture[2],
                runtime.trace_identity_errors(trace, root, fixture[2], "/root/other"))

    def test_sentry_publication_audit_rejects_wrong_role_and_failed_latest_dispatch(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.fixture(directory, "sentry_issue_remediation", "sentry_current_state_investigator")
            trace, ledger = self.export(fixture)
            run, root, role, *_ = fixture
            path = root / "trace.json"
            path.write_text(json.dumps(trace))
            Path(run["runtime_evidence"]["ledger"]).write_text(json.dumps(ledger))
            def audit(worker, handle="/root/worker"):
                return subprocess.run([sys.executable, "-c",
                    "import sys; from finalize_sentry_planning import _trace_audit; "
                    "_trace_audit({sys.argv[1]:sys.argv[2]}, [sys.argv[1]+'='+sys.argv[3]])",
                    worker, handle, str(path)], cwd=Path(__file__).resolve().parents[1] / "scripts",
                    capture_output=True, text=True)
            self.assertIn("worker_trace_role_mismatch", audit("fix-design").stderr)
            self.assertIn("worker_trace_handle_mismatch", audit("evidence-topology", "/root/other").stderr)
            stale_observation = {**trace["status_observation"], "Last dispatch at": fixture[3](1)}
            closure_path = root / "runtime_closure.json"
            closure_path.write_text(json.dumps({"runtime_closure": [{"Runtime status": "Terminal"}],
                "terminal_observations": [stale_observation]}))
            self.assertIn("runtime_audit_dispatch_mismatch", audit("evidence-topology").stderr)
            closure_path.unlink()
            fixture[5][6]["payload"]["output"] = json.dumps({"error": "correction rejected"})
            parent_path = root / "parent.jsonl"
            parent_path.write_text("\n".join(json.dumps(row) for row in fixture[5]) + "\n")
            ledger = read_runtime_events(parent_path, PARENT, run["runtime_evidence"]["run_started_at"])
            Path(run["runtime_evidence"]["ledger"]).write_text(json.dumps(ledger))
            self.assertIn("latest_worker_dispatch_failed", audit("evidence-topology").stderr)

    def test_approved_feature_remediation_roles_pass_shared_finalizer_audit(self):
        for role in ("implementer", "reviewer", "tester", "documenter"):
            with self.subTest(role=role), tempfile.TemporaryDirectory() as directory:
                fixture = self.fixture(directory, role=role, remediation=True)
                trace, ledger = self.export(fixture)
                run, root, *_ = fixture
                packet = json.loads((root / "finalization_packet.json").read_text())
                self.assertEqual(packet["identity"]["Lifecycle"], "remediation")
                trace_path = root / "trace.json"
                trace_path.write_text(json.dumps(trace))
                Path(run["runtime_evidence"]["ledger"]).write_text(json.dumps(ledger))
                audit = {**trace["status_observation"], "Provider status": "completed",
                         "Worker": role, "Trace path": str(trace_path)}
                self.assertEqual(finalizer._worker_runtime_audit_errors({"runtime_audits": [audit]},
                    root / "finalization_packet.json", {role}), [])

    def test_prepared_closure_requires_a_receipt_and_exact_handles(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.fixture(directory, "sentry_issue_remediation", "sentry_current_state_investigator")[1]
            path = root / "runtime_closure.json"
            def validate():
                return subprocess.run([sys.executable, "-c",
                    "import sys; from pathlib import Path; from finalize_sentry_planning import _released_closure; "
                    "_released_closure(Path(sys.argv[1]), ['/root/worker'])", str(path)],
                    cwd=Path(__file__).resolve().parents[1] / "scripts", capture_output=True, text=True)
            self.assertIn("prepared_runtime_closure_receipt_required", validate().stderr)
            row = {"Completed worker handles": "/root/worker_extra", "Runtime status": "Released", "Remaining active handles": "0"}
            path.write_text(json.dumps({"runtime_closure": [row]}))
            self.assertNotEqual(validate().returncode, 0)
            row["Completed worker handles"] = "/root/worker"
            path.write_text(json.dumps({"runtime_closure": [row, "malformed"]}))
            self.assertNotEqual(validate().returncode, 0)
            path.write_text(json.dumps({"runtime_closure": [row]}))
            self.assertEqual(validate().returncode, 0)

    def test_failed_in_turn_message_blocks_acceptance(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.fixture(directory)
            fixture[5][5]["payload"]["name"] = "send_message"
            fixture[5][6]["payload"]["output"] = json.dumps({"error": "message rejected"})
            with self.assertRaisesRegex(ValueError, "latest_worker_dispatch_failed"):
                self.export(fixture)

    def test_late_followup_error_preserves_observed_active_child(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.fixture(directory)
            fixture[5][6]["payload"]["output"] = json.dumps({"error": "followup rejected"})
            fixture[5].insert(6, fixture[4](5, "event_msg", item={"type": "SubAgentActivity", "kind": "started",
                "agent_path": "/root/worker", "agent_thread_id": CHILD}))
            fixture[5].pop()
            with self.assertRaisesRegex(ValueError, "latest_worker_dispatch_failed"):
                self.export(fixture)
            ledger = read_runtime_events(fixture[1] / "parent.jsonl", PARENT,
                                         fixture[0]["runtime_evidence"]["run_started_at"])
            self.assertEqual(ledger["timing"]["open_worker_intervals"], 1)

    def test_late_explicit_spawn_error_is_not_hidden_by_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.fixture(directory)
            fixture[5][3]["payload"]["output"] = json.dumps({"isError": True, "error": "spawn rejected"})
            fixture[5][:] = fixture[5][:5]
            with self.assertRaisesRegex(ValueError, "worker_trace_dispatch_unavailable"):
                self.export(fixture)
            parent = fixture[1] / "parent.jsonl"
            ledger = read_runtime_events(parent, PARENT, fixture[0]["runtime_evidence"]["run_started_at"])
            self.assertEqual(ledger["events"], [])
            self.assertEqual(ledger["failed_dispatches"][0]["Provider handle"], "/root/worker")
            self.assertEqual(ledger["thread_mappings"]["/root/worker"], CHILD)

    def test_failed_required_followup_blocks_export_and_finalizer(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.fixture(directory)
            run, root, role, time, *_ = fixture
            fixture[5][6]["payload"]["output"] = json.dumps({"isError": True, "error": "correction rejected"})
            with self.assertRaisesRegex(ValueError, "latest_worker_dispatch_failed"):
                self.export(fixture)
            ledger = read_runtime_events(root / "parent.jsonl", PARENT, run["runtime_evidence"]["run_started_at"])
            Path(run["runtime_evidence"]["ledger"]).write_text(json.dumps(ledger))
            from scripts.worker_runtime_evidence import dispatch_audit_errors
            packet = {"runtime_audits": [{"Provider handle": "/root/worker", "Last dispatch at": time(1)}]}
            self.assertIn("latest_worker_dispatch_failed", " ".join(dispatch_audit_errors(packet, root / "finalization_packet.json")))
            stale = {**ledger, "failed_dispatches": []}
            Path(run["runtime_evidence"]["ledger"]).write_text(json.dumps(stale))
            self.assertIn("runtime_dispatch_ledger_stale", " ".join(dispatch_audit_errors(packet, root / "finalization_packet.json")))

    def test_successful_retry_supersedes_failed_followup(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.fixture(directory)
            fixture[5][6]["payload"]["output"] = json.dumps({"error": "followup rejected"})
            event = fixture[4]
            fixture[5].insert(7, event(7, "response_item", type="function_call", namespace="collaboration",
                name="followup_task", call_id="retry", arguments=json.dumps({"target": "/root/worker", "message": "Retry correction"})))
            fixture[5].insert(8, event(8, "response_item", type="function_call_output", call_id="retry", output=""))
            fixture[7]["Latest turn started at"] = fixture[3](7)
            trace, ledger = self.export(fixture)
            self.assertEqual(len(ledger["failed_dispatches"]), 1)
            self.assertEqual(trace["audit"]["status"], "passed")
            self.assertEqual(trace["last_dispatch_at"], fixture[3](7))

    def test_fresh_replacement_is_not_blocked_by_the_old_failed_followup(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.fixture(directory)
            run, root, role, time, event, parent, child, _ = fixture
            parent[6]["payload"]["output"] = json.dumps({"error": "correction rejected"})
            replacement = "/root/replacement"
            thread = "00000000-0000-0000-0000-000000000003"
            parent.extend([event(11, "response_item", type="function_call", namespace="collaboration", name="spawn_agent",
                arguments=json.dumps({"task_name": "replacement", "message": "fresh assignment", "fork_turns": "none",
                    "model": json.loads((root / "role_bindings.json").read_text())["bindings"][role]["model"],
                    "reasoning_effort": json.loads((root / "role_bindings.json").read_text())["bindings"][role]["effort"]})),
                event(12, "event_msg", item={"type": "SubAgentActivity", "kind": "started",
                    "agent_path": replacement, "agent_thread_id": thread}),
                event(17, "event_msg", item={"type": "SubAgentActivity", "kind": "completed", "agent_path": replacement})])
            path = root / "parent.jsonl"
            path.write_text("\n".join(json.dumps(row) for row in parent) + "\n")
            ledger = read_runtime_events(path, PARENT, run["runtime_evidence"]["run_started_at"])
            Path(run["runtime_evidence"]["ledger"]).write_text(json.dumps(ledger))
            fresh = root / "replacement.jsonl"
            child[0]["payload"]["id"] = thread
            for row in child:
                row["timestamp"] = time(13)
            fresh.write_text("\n".join(json.dumps(row) for row in child) + "\n")
            observation = {**fixture[7], "Provider handle": replacement, "Thread ID": thread,
                "Latest turn started at": time(12), "Latest turn completed at": time(17)}
            trace = export_worker_trace(ledger, fresh, role, observation, run_id=run["run_id"], artifact_root=root)
            trace_path = root / "replacement.trace.json"
            trace_path.write_text(json.dumps(trace))
            row = {**trace["status_observation"], "Provider status": "completed", "Worker": role, "Trace path": str(trace_path)}
            self.assertEqual(finalizer._worker_runtime_audit_errors({"runtime_audits": [row]},
                root / "finalization_packet.json", {role}), [])
            self.assertEqual(len(ledger["failed_dispatches"]), 1)

    def test_latest_changed_contract_must_be_read_even_with_delivery_flag(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.fixture(directory)
            run, root, role, time, event, parent, child, status = fixture
            packet = json.loads(Path(run["activation_packet_bundle"]["path"]).read_text())["packets"][role]
            changed = root / "activation_changed.txt"
            notice = runtime.dispatch_message(packet, runtime.activation_message(packet, {"objective": "Validate changed output"}), changed)
            args = json.loads(parent[5]["payload"]["arguments"])
            args["message"] = notice
            parent[5]["payload"]["arguments"] = json.dumps(args)
            status["Binding evidence"] = {"activation_packet_delivered": True}
            trace, _ = self.export(fixture)
            self.assertIn("provider_binding_not_delivered", trace["audit"]["errors"])
            child.extend([event(9, "response_item", type="custom_tool_call", name="exec", call_id="new-contract",
                                input='await tools.exec_command(' + json.dumps({"cmd": "cat " + str(changed)}) + ')'),
                          event(9, "response_item", type="custom_tool_call_output", call_id="new-contract",
                                output=changed.read_text())])
            trace, _ = self.export(fixture)
            self.assertEqual(trace["audit"], {"status": "passed", "errors": []})
            self.assertEqual(trace["spawn"]["dispatch_file"], str(changed))

    def test_stale_completion_cannot_resolve_an_empty_acknowledgement(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.fixture(directory)
            fixture[7].update({"Latest turn started at": fixture[3](1), "Latest turn completed at": fixture[3](4)})
            with self.assertRaisesRegex(ValueError, "terminal_observation_latest_turn_stale"):
                self.export(fixture)


if __name__ == "__main__":
    unittest.main()
