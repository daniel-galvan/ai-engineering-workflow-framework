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
        result_contract = packet.get("worker_contract") or {}
        if result_contract.get("result_hash_required"):
            from scripts.merge_techops_result import FEATURE_WORKERS, WORKERS
            workers = FEATURE_WORKERS if playbook == "feature_delivery" else WORKERS
            fields = json.loads((preparation.ROOT / "templates/finalization_packet.json").read_text())["worker_results"][0]
            result = {"run_id": run["run_id"], "worker_result": {
                **dict.fromkeys(fields, "Synthetic evidence blocker"),
                "Worker": workers[role][0], "Outcome": "blocked"}}
            if result_contract.get("planning_disposition_required"):
                result.update(plan_readiness="awaiting_input", implementation_plan_action="omit")
            Path(result_contract["result"]).write_text(json.dumps(result))
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

    def test_merger_registers_passed_trace_with_result_atomically(self):
        from scripts.merge_techops_result import merge_result
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.fixture(directory, "techops_issue_remediation", "current_state_investigator")
            run, root, role, *_ = fixture
            source = Path(run["worker_contracts"][role]["result"])
            template = json.loads((preparation.ROOT / "templates/finalization_packet.json").read_text())
            source.write_text(json.dumps({"run_id": run["run_id"], "worker_result": {
                **dict.fromkeys(template["worker_results"][0], "Current evidence"),
                "Worker": "issue-evidence", "Outcome": "complete"}}))
            trace, ledger = self.export(fixture)
            Path(run["runtime_evidence"]["ledger"]).write_text(json.dumps(ledger))
            path = root / "trace.json"
            path.write_text(json.dumps(trace))
            packet_path = root / "finalization_packet.json"
            before = packet_path.read_bytes()
            trace["spawn"]["agent"] = "dependency_analyst"
            path.write_text(json.dumps(trace))
            with self.assertRaises(ValueError):
                merge_result(packet_path, role, trace=path)
            self.assertEqual(packet_path.read_bytes(), before)
            trace["spawn"]["agent"] = role
            path.write_text(json.dumps(trace))
            merge_result(packet_path, role, trace=path)
            packet = json.loads(packet_path.read_text())
            self.assertEqual(packet["runtime_audits"][0]["Worker"], "issue-evidence")
            self.assertEqual(packet["worker_results"][0]["Outcome"], "complete")
            merge_result(packet_path, role, trace=path)
            self.assertEqual(len(json.loads(packet_path.read_text())["runtime_audits"]), 1)

    def test_malformed_result_is_a_rejected_trace_eligible_for_bounded_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.fixture(directory, "techops_issue_remediation", "dependency_analyst")
            run, root, role, *_ = fixture
            Path(run["worker_contracts"][role]["result"]).write_text(json.dumps({"run_id": run["run_id"]}))
            trace, ledger = self.export(fixture)
            Path(run["runtime_evidence"]["ledger"]).write_text(json.dumps(ledger))
            self.assertEqual(trace["audit"]["status"], "rejected")
            self.assertTrue(any("worker_result_summary_schema_invalid" in error
                                for error in trace["audit"]["errors"]))
            self.assertEqual(runtime.rejected_result_errors(trace, trace["spawn"]["provider_handle"],
                                                          trace["last_dispatch_at"]), [])

    def test_missing_result_is_a_rejected_trace_eligible_for_bounded_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.fixture(directory, "techops_issue_remediation", "dependency_analyst")
            run, root, role, *_ = fixture
            bindings = json.loads((root / "role_bindings.json").read_text())
            Path(bindings["worker_contracts"][role]["result"]).unlink()
            trace, ledger = self.export(fixture)
            Path(run["runtime_evidence"]["ledger"]).write_text(json.dumps(ledger))
            self.assertEqual(trace["audit"]["status"], "rejected")
            self.assertIn("worker_result_artifact_changed:" + role, trace["audit"]["errors"])
            self.assertEqual(runtime.rejected_result_errors(trace, trace["spawn"]["provider_handle"],
                                                          trace["last_dispatch_at"]), [])
            rejected = root / "missing_result_trace.json"
            rejected.write_text(json.dumps(trace))
            for status, expected in (("completed", 0), ("running", 2)):
                checked = subprocess.run([sys.executable, str(preparation.ROOT / "scripts/validate_worker_runtime.py"),
                    "--transition", "replace", "--provider-status", status, "--rejected-trace", str(rejected),
                    "--provider-handle", trace["spawn"]["provider_handle"],
                    "--last-dispatch-at", trace["last_dispatch_at"]], capture_output=True, text=True)
                self.assertEqual(checked.returncode, expected, checked.stdout + checked.stderr)
            notice = runtime.dispatch_notice({"required_prefix": "Coordinator initialization: complete",
                "agent": role, "model": "model", "effort": "high", "run_id": run["run_id"]},
                "instructions", root / "activation.txt")
            self.assertIn("continue in this same turn through the full typed assignment", notice)
            self.assertIn("A bootstrap acknowledgment is not completion", notice)

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
                        contract = run.get("worker_contracts", {}).get(role, {})
                        worker = contract.get("worker") or contract.get("worker_id")
                        if worker:
                            row["Worker"] = worker
                            self.assertEqual(finalizer._worker_runtime_audit_errors({"runtime_audits": [row]},
                                             root / "finalization_packet.json", {worker}), [])
                        if contract.get("result_hash_required"):
                            output = Path(contract["result"])
                            output.write_text(output.read_text() + "\n")
                            errors = finalizer._worker_runtime_audit_errors({"runtime_audits": [row]},
                                root / "finalization_packet.json", {row["Worker"]})
                            self.assertIn("worker_result_artifact_changed:" + role, errors)

    def test_closure_accounts_for_rejected_spawn_without_accepting_its_analysis(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.fixture(directory)
            run, root, role, time, event, parent, _, _ = fixture
            rejected_child = "00000000-0000-0000-0000-000000000099"
            parent.extend([
                event(11, "response_item", type="function_call", namespace="collaboration", name="spawn_agent",
                      call_id="rejected", arguments=json.dumps({"task_name": "rejected"})),
                event(12, "event_msg", item={"type": "SubAgentActivity", "kind": "started",
                      "agent_path": "/root/rejected", "agent_thread_id": rejected_child}),
                event(13, "response_item", type="function_call_output", call_id="rejected", output=""),
                event(14, "event_msg", item={"type": "SubAgentActivity", "kind": "completed",
                      "agent_path": "/root/rejected"})])
            trace, ledger = self.export(fixture)
            Path(run["runtime_evidence"]["ledger"]).write_text(json.dumps(ledger))
            trace_path = root / "accepted_trace.json"
            trace_path.write_text(json.dumps(trace))
            accepted = {**trace["status_observation"], "Provider status": "completed", "Worker": role,
                        "Trace path": str(trace_path)}
            packet = {"runtime_audits": [accepted], "terminal_observations": [accepted]}
            errors = finalizer._worker_runtime_audit_errors(packet, root / "finalization_packet.json", {role})
            self.assertIn("terminal_closure_worker_handle_mismatch", errors)
            rejected = {**accepted, "Provider handle": "/root/rejected", "Thread ID": rejected_child,
                        "Last dispatch at": time(11), "Latest turn started at": time(11),
                        "Latest turn completed at": time(14)}
            packet["terminal_observations"].append(rejected)
            self.assertEqual(finalizer._worker_runtime_audit_errors(packet, root / "finalization_packet.json", {role}), [])
            rejected["Last dispatch at"] = time(0)
            self.assertIn("terminal_closure_worker_audit_stale", finalizer._worker_runtime_audit_errors(
                packet, root / "finalization_packet.json", {role}))

    def test_native_inventory_exports_selected_worker_without_manual_timestamps(self):
        for playbook in CASES:
            with self.subTest(playbook=playbook), tempfile.TemporaryDirectory() as directory:
                fixture = self.fixture(directory, playbook, CASES[playbook][0])
                run, root, role, time, event, parent, _, _ = fixture
                parent.extend([
                    event(20, "response_item", type="function_call", namespace="collaboration", name="list_agents",
                          call_id="inventory", arguments="{}"),
                    event(21, "response_item", type="function_call_output", call_id="inventory", output=json.dumps({
                        "agents": [{"agent_name": "/root/worker", "agent_status": {"completed": "Done"}},
                                   {"agent_name": "/root/other", "agent_status": "running"}]}))])
                _, ledger = self.export(fixture)
                trace = export_worker_trace(ledger, root / "child.jsonl", role, run_id=run["run_id"], artifact_root=root)
                self.assertEqual(trace["audit"], {"status": "passed", "errors": []})
                self.assertEqual(trace["status_observation"]["Observed at"], time(21))
                self.assertEqual(trace["status_observation"]["Status source"], "list_agents")
                result = subprocess.run([sys.executable, str(preparation.ROOT / "scripts/worker_runtime_evidence.py"),
                    "--provider-session", str(root / "parent.jsonl"), "--parent-thread-id", PARENT,
                    "--started-at", run["runtime_evidence"]["run_started_at"], "--ledger", str(root / "ledger.json"),
                    "--worker-session", str(root / "child.jsonl"), "--agent", role,
                    "--trace", str(root / "native_trace.json")], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(json.loads((root / "native_trace.json").read_text())["audit"]["status"], "passed")

    def test_workflow_failure_collects_closure_from_every_native_handle(self):
        for status in ({"completed": "Done"}, "running"):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as directory:
                fixture = self.fixture(directory, "techops_issue_remediation", "current_state_investigator")
                run, root, role, time, event, parent, _, _ = fixture
                parent.extend([
                    event(20, "response_item", type="function_call", namespace="collaboration", name="spawn_agent",
                        call_id="rejected", arguments=json.dumps({"task_name": "rejected"})),
                    event(20, "event_msg", item={"type": "SubAgentActivity", "kind": "started",
                        "agent_path": "/root/rejected", "agent_thread_id": "00000000-0000-0000-0000-000000000003"}),
                    event(21, "response_item", type="function_call", namespace="collaboration", name="list_agents",
                        call_id="inventory", arguments="{}"),
                    event(22, "response_item", type="function_call_output", call_id="inventory", output=json.dumps({
                        "agents": [{"agent_name": "/root/worker", "agent_status": status},
                                   {"agent_name": "/root/rejected", "agent_status": {"completed": "Rejected"}}]}))])
                _, ledger = self.export(fixture)
                Path(run["runtime_evidence"]["ledger"]).write_text(json.dumps(ledger))
                result = subprocess.run([sys.executable, str(preparation.ROOT / "scripts/finalize_work_record.py"),
                    "--packet", str(root / "finalization_packet.json"), "--workflow-failure", "Synthetic control failure"],
                    capture_output=True, text=True)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                closure = json.loads((root / "runtime_closure.json").read_text())
                receipt = json.loads((root / "finalization_failure.json").read_text())
                if isinstance(status, dict):
                    self.assertEqual(receipt["runtime_closure"], "terminal")
                    self.assertEqual({row["Provider handle"] for row in closure["terminal_observations"]},
                                     {"/root/worker", "/root/rejected"})
                    self.assertIn("provider closure verified for every activated handle", result.stdout)
                    self.assertIn("runtime terminal", result.stdout)
                    self.assertNotIn("runtime closure unverified", result.stdout)
                    for missing in (False, True):
                        (root / "runtime_closure.json").write_text("not valid JSON")
                        if missing:
                            (root / "runtime_closure.json").unlink()
                        report = finalizer.failure_handoff(root / "finalization_packet.json", "Synthetic failure")
                        self.assertIn("runtime closure unverified", report)
                        self.assertNotIn("provider closure verified", report)
                else:
                    self.assertEqual(receipt["runtime_closure"], "unverified")
                    self.assertEqual(closure["runtime_closure"][0]["Runtime status"], "Blocked")
                    self.assertNotIn("terminal_observations", closure)

    def test_native_inventory_never_uses_an_older_terminal_status(self):
        for problem in ("absent", "missing", "active", "stale", "unmapped"):
            with self.subTest(problem=problem), tempfile.TemporaryDirectory() as directory:
                fixture = self.fixture(directory)
                run, root, role, time, *_ = fixture
                _, ledger = self.export(fixture)
                completed = {"Observed at": time(20), "raw_response": {"agents": [
                    {"agent_name": "/root/worker", "agent_status": {"completed": "Done"}}]}}
                latest = json.loads(json.dumps(completed))
                if problem == "missing": latest["raw_response"]["agents"] = []
                if problem == "active": latest["raw_response"]["agents"][0]["agent_status"] = "running"
                if problem == "stale": latest["Observed at"] = time(0)
                ledger["inventories"] = [] if problem == "absent" else [completed, latest]
                if problem == "unmapped": ledger["thread_mappings"] = {}
                with self.assertRaises(ValueError):
                    export_worker_trace(ledger, root / "child.jsonl", role, run_id=run["run_id"], artifact_root=root)

    def test_explicit_incomplete_receipt_is_not_silently_repaired(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.fixture(directory)
            run, root, role, time, *_ = fixture
            _, ledger = self.export(fixture)
            ledger["inventories"] = [{"Observed at": time(20), "raw_response": {"agents": [
                {"agent_name": "/root/worker", "agent_status": {"completed": "Done"}}]}}]
            observation = dict(fixture[-1])
            del observation["Observed at"]
            with self.assertRaisesRegex(ValueError, "terminal_observation_timestamp_invalid"):
                export_worker_trace(ledger, root / "child.jsonl", role, observation,
                                    run_id=run["run_id"], artifact_root=root)

    def test_ordinary_result_joins_spawn_handle_without_a_message(self):
        for playbook in CASES:
            with self.subTest(playbook=playbook), tempfile.TemporaryDirectory() as directory:
                fixture = self.fixture(directory, playbook, CASES[playbook][0])
                _, _, _, time, _, parent, _, status = fixture
                del parent[5:]
                status["Latest turn started at"] = time(1)
                trace, ledger = self.export(fixture)
                self.assertEqual(len(ledger["events"]), 1)
                self.assertEqual(trace["last_dispatch_at"], time(1))
                self.assertEqual(trace["spawn"]["provider_handle"], "/root/worker")
                self.assertEqual(trace["audit"], {"status": "passed", "errors": []})

    def test_unconsumed_handle_message_does_not_reuse_spawn_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.fixture(directory, "techops_issue_remediation")
            _, _, _, time, _, parent, _, status = fixture
            parent[5]["payload"].update(name="send_message", arguments=json.dumps({
                "target": "/root/worker", "message": "Your provider handle is /root/worker"}))
            status["Latest turn started at"] = time(1)
            with self.assertRaisesRegex(ValueError, "terminal_observation_latest_turn_stale"):
                self.export(fixture)

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

    def test_message_delivery_does_not_start_an_idle_worker_interval(self):
        for operation, expected_seconds in (("send_message", 3), ("followup_task", 8)):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as directory:
                fixture = self.fixture(directory)
                fixture[5][5]["payload"]["name"] = operation
                parent = fixture[1] / "parent.jsonl"
                parent.write_text("\n".join(json.dumps(row) for row in fixture[5]) + "\n")
                ledger = read_runtime_events(parent, PARENT, fixture[0]["runtime_evidence"]["run_started_at"])
                self.assertEqual(ledger["timing"]["worker_active_seconds"], expected_seconds)
                self.assertEqual(ledger["events"][-1]["Operation"], operation)

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
