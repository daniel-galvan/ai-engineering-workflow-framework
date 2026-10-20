"""Exercise shipped entrypoints from a clean local package, without live workers."""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PackagedLifecycle(unittest.TestCase):
    def package(self, directory):
        package = Path(directory) / "package"
        shutil.copytree(ROOT, package, symlinks=True,
                        ignore=shutil.ignore_patterns(".git", ".thoughts", "__pycache__"))
        for args in (("init", "-q"), ("config", "user.name", "Package fixture"),
                     ("config", "user.email", "fixture@example.invalid"), ("add", "."),
                     ("commit", "-qm", "Synthetic package snapshot")):
            subprocess.run(["git", "-C", str(package), *args], check=True, capture_output=True)
        return package

    def test_shipped_parent_context_gate_blocks_before_artifacts_and_rechecks_activation(self):
        with tempfile.TemporaryDirectory() as directory:
            package = self.package(directory)
            repository = Path(directory) / "repository"
            repository.mkdir()
            source = Path(directory) / "parent.jsonl"
            rows = [{"type": "session_meta", "payload": {"id": "00000000-0000-0000-0000-000000000001"}},
                    {"type": "turn_context", "payload": {"turn_id": "00000000-0000-0000-0000-000000000002"}}]
            forbidden = {"type": "response_item", "payload": {"type": "custom_tool_call", "name": "exec",
                "input": 'await tools.exec_command({"cmd":"cat /repo/.codex/memories/MEMORY.md"})'}}

            def save(events):
                source.write_text("".join(json.dumps(row) + "\n" for row in events))

            def command(script, *args, expected=0):
                result = subprocess.run([sys.executable, str(package / "scripts" / script), *map(str, args)],
                                        cwd=package, capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
                return json.loads(result.stdout)

            save(rows + [forbidden])
            blocked = command("run_preflight.py", "--provider-session", source, expected=2)
            self.assertEqual(blocked["reason"], "parent_context_nonconformant")
            self.assertFalse((repository / ".thoughts").exists())
            inputs = repository / "inputs.json"
            inputs.write_text(json.dumps({"inputs": [{"Input ID": "IN-001", "Input or artifact": "Current issue",
                "Source or path": "User", "Authority": "User", "Status": "Verified"}]}))
            prepare = ("--execution-repository", repository, "--work-item", "ITEM-1", "--playbook",
                       "feature_delivery", "--input-manifest", inputs, "--provider-session", source)
            self.assertIn("parent_context_nonconformant", command("prepare_run.py", *prepare, expected=2)["reason"])
            self.assertFalse((repository / ".thoughts").exists())
            save(rows)
            self.assertEqual(command("run_preflight.py", "--provider-session", source)["status"], "passed")
            run = command("prepare_run.py", *prepare)
            packet = Path(run["finalization_packet"])
            before = packet.read_bytes()
            activation = ("--activation-packet-bundle", run["activation_packet_bundle"]["path"],
                          "--expected-agent", "current_state_investigator", "--expected-bundle-sha256",
                          run["activation_packet_bundle"]["sha256"])
            self.assertEqual(command("validate_worker_runtime.py", *activation)["status"], "allowed")
            save(rows + [forbidden])
            rejected = command("validate_worker_runtime.py", *activation, expected=2)
            self.assertTrue(any("parent_context_nonconformant" in error for error in rejected["errors"]))
            self.assertEqual(packet.read_bytes(), before)

    def test_shipped_commands_register_analysis_and_publish_closed_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            package = self.package(directory)

            def command(script, *args, expected=0):
                result = subprocess.run([sys.executable, str(package / "scripts" / script), *map(str, args)],
                                        cwd=package, capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
                return result.stdout

            command("run_preflight.py")
            for playbook, worker, recover in (
                    (playbook, worker, recover)
                    for playbook, worker in (("techops_issue_remediation", "issue-evidence"),
                                             ("feature_delivery", "feature-context"))
                    for recover in (False, "missing", "malformed")):
                with self.subTest(playbook=playbook, recover=recover):
                    repository = Path(directory) / (playbook + str(recover))
                    repository.mkdir()
                    inputs = repository / "inputs.json"
                    inputs.write_text(json.dumps({"inputs": [{"Input ID": "IN-001",
                        "Input or artifact": "Synthetic current issue", "Source or path": "User",
                        "Authority": "User", "Status": "Registered"}]}))
                    run = json.loads(command("prepare_run.py", "--execution-repository", repository,
                        "--work-item", "ITEM-1", "--playbook", playbook, "--input-manifest", inputs))
                    root = Path(run["artifact_root"])
                    packet = Path(run["finalization_packet"])
                    assignment = root / "assignment.json"
                    assignment.write_text(json.dumps({"objective": "Inspect the supplied synthetic issue"}))
                    activation = root / "activation.txt"
                    guarded = json.loads(command("validate_worker_runtime.py", "--activation-packet-bundle",
                        run["activation_packet_bundle"]["path"], "--expected-agent", "current_state_investigator",
                        "--expected-bundle-sha256", run["activation_packet_bundle"]["sha256"],
                        "--assignment", assignment, "--dispatch-file", activation))
                    self.assertIn("continue in this same turn", guarded["activation_message"])
                    contract = run["worker_contracts"]["current_state_investigator"]
                    template = json.loads((package / "templates/finalization_packet.json").read_text())
                    worker_result = json.dumps({"run_id": run["run_id"], "worker_result": {
                        **dict.fromkeys(template["worker_results"][0], "Synthetic current evidence"),
                        "Worker": worker, "Outcome": "complete"}})
                    if not recover:
                        Path(contract["result"]).write_text(worker_result)
                    elif recover == "malformed":
                        Path(contract["result"]).write_text(json.dumps({"run_id": run["run_id"]}))
                    start = datetime.fromisoformat(run["runtime_evidence"]["run_started_at"].replace("Z", "+00:00"))
                    stamp = lambda seconds: (start + timedelta(seconds=seconds)).isoformat()
                    event = lambda seconds, kind, **payload: {
                        "timestamp": stamp(seconds), "type": kind, "payload": payload}
                    parent_id = "00000000-0000-0000-0000-000000000001"
                    child_id = "00000000-0000-0000-0000-000000000002"
                    handle = "/root/context"
                    parent = root / "parent.jsonl"
                    parent.write_text("\n".join(json.dumps(row) for row in [
                        event(0, "session_meta", id=parent_id),
                        event(1, "response_item", type="function_call", namespace="collaboration",
                            name="spawn_agent", call_id="spawn", arguments=json.dumps({
                                "task_name": "context", "message": guarded["activation_message"],
                                **guarded["launch_arguments"]})),
                        event(1, "event_msg", item={"type": "SubAgentActivity", "kind": "started",
                            "agent_path": handle, "agent_thread_id": child_id}),
                        event(5, "response_item", type="function_call", namespace="collaboration",
                            name="list_agents", call_id="inventory", arguments="{}"),
                        event(6, "response_item", type="function_call_output", call_id="inventory",
                            output=json.dumps({"agents": [{"agent_name": handle,
                                                           "agent_status": {"completed": "Done"}}]}))]) + "\n")
                    child = root / "child.jsonl"
                    child.write_text("\n".join(json.dumps(row) for row in [
                        event(1, "session_meta", id=child_id),
                        event(2, "response_item", type="function_call", name="exec_command", call_id="read",
                            arguments=json.dumps({"cmd": "cat " + str(activation), "workdir": str(repository)})),
                        event(3, "response_item", type="function_call_output", call_id="read",
                            output=activation.read_text())]) + "\n")
                    trace = root / "trace.json"
                    collector = ("--provider-session", parent, "--parent-thread-id", parent_id,
                                 "--started-at", run["runtime_evidence"]["run_started_at"],
                                 "--ledger", run["runtime_evidence"]["ledger"])
                    command("worker_runtime_evidence.py", *collector, "--worker-session", child,
                            "--agent", "current_state_investigator", "--trace", trace, expected=2 if recover else 0)
                    if recover:
                        rejected_bytes = trace.read_bytes()
                        corrected_activation = root / "activation_corrected.txt"
                        recovery = ("--activation-packet-bundle", run["activation_packet_bundle"]["path"],
                                    "--expected-agent", "current_state_investigator", "--expected-bundle-sha256",
                                    run["activation_packet_bundle"]["sha256"], "--assignment", assignment,
                                    "--rejected-trace", trace, "--provider-handle", handle,
                                    "--last-dispatch-at", stamp(1), "--provider-status", "completed")
                        corrected = json.loads(command("validate_worker_runtime.py", *recovery,
                                                       "--dispatch-file", corrected_activation))
                        repeated = command("validate_worker_runtime.py", *recovery, "--dispatch-file",
                                           root / "activation_forbidden.txt", expected=2)
                        self.assertIn("activation_repair_limit_reached", repeated)
                        with parent.open("a") as stream:
                            for row in (
                                event(8, "response_item", type="function_call", namespace="collaboration",
                                    name="followup_task", call_id="correction", arguments=json.dumps({
                                        "target": handle, "message": corrected["activation_message"]})),
                                event(12, "response_item", type="function_call", namespace="collaboration",
                                    name="list_agents", call_id="corrected_inventory", arguments="{}"),
                                event(13, "response_item", type="function_call_output", call_id="corrected_inventory",
                                    output=json.dumps({"agents": [{"agent_name": handle,
                                                                   "agent_status": {"completed": "Done"}}]}))):
                                stream.write(json.dumps(row) + "\n")
                        with child.open("a") as stream:
                            for row in (
                                event(9, "response_item", type="function_call", name="exec_command",
                                    call_id="corrected_read", arguments=json.dumps({
                                        "cmd": "cat " + str(corrected_activation), "workdir": str(repository)})),
                                event(10, "response_item", type="function_call_output", call_id="corrected_read",
                                    output=corrected_activation.read_text())):
                                stream.write(json.dumps(row) + "\n")
                        Path(contract["result"]).write_text(worker_result)
                        trace = root / "corrected_trace.json"
                        command("worker_runtime_evidence.py", *collector, "--worker-session", child,
                                "--agent", "current_state_investigator", "--trace", trace)
                        self.assertEqual((root / "trace.json").read_bytes(), rejected_bytes)
                    command("merge_techops_result.py", "--packet", packet, "--agent",
                            "current_state_investigator", "--trace", trace)
                    accepted = json.loads(packet.read_text())
                    self.assertEqual(accepted["runtime_audits"][0]["Worker"], worker)
                    self.assertEqual(accepted["worker_results"][0]["Outcome"], "complete")
                    closure = root / "runtime_closure.json"
                    if recover:
                        Path(run["runtime_evidence"]["ledger"]).unlink()
                        failure_source = ("--provider-session", parent, "--parent-thread-id", parent_id)
                    else:
                        command("worker_runtime_evidence.py", *collector, "--closure", closure)
                        failure_source = ()
                    command("finalize_work_record.py", "--packet", packet, "--workflow-failure",
                            "Synthetic later control failure", *failure_source, expected=2)
                    self.assertTrue(Path(run["runtime_evidence"]["ledger"]).is_file())
                    self.assertTrue(closure.is_file())
                    receipt = json.loads((root / "finalization_failure.json").read_text())
                    self.assertEqual(receipt["runtime_closure"], "terminal")
                    response = root / "handoff_response.md"
                    emitted = command("finalize_work_record.py", "--packet", packet,
                                      "--publish-response", response)
                    self.assertEqual(emitted.encode(), response.read_bytes())
                    self.assertEqual(json.loads((root / "handoff_delivery.json").read_text())["status"], "verified")

    def test_sentry_shipped_commands_publish_plan_and_indispensable_evidence_blocker(self):
        with tempfile.TemporaryDirectory() as directory:
            package = self.package(directory)

            def command(script, *args):
                result = subprocess.run([sys.executable, str(package / "scripts" / script), *map(str, args)],
                                        cwd=package, capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result.stdout

            preflight = json.loads(command("run_preflight.py"))
            for name, result_key, expected_state in (
                ("sentry_deterministic_finalization.json", "fix_design_result", "ready_for_implementation"),
                ("sentry_runtime_regressions.json", "valid_awaiting_fix_design_result", "awaiting_input")):
                with self.subTest(state=expected_state):
                    repository = Path(directory) / expected_state
                    repository.mkdir()
                    for args in (("init", "-q"), ("config", "user.name", "Repository fixture"),
                                 ("config", "user.email", "fixture@example.invalid")):
                        subprocess.run(["git", "-C", str(repository), *args], check=True, capture_output=True)
                    (repository / "README.md").write_text("Synthetic source baseline\n")
                    for args in (("add", "."), ("commit", "-qm", "Synthetic source baseline")):
                        subprocess.run(["git", "-C", str(repository), *args], check=True, capture_output=True)
                    inputs = repository / "inputs.json"
                    inputs.write_text(json.dumps({"inputs": [{"Input ID": "IN-001",
                        "Input or artifact": "Synthetic occurrence", "Source or path": "User",
                        "Authority": "User", "Status": "Registered"}]}))
                    run = json.loads(command("prepare_run.py", "--execution-repository", repository,
                        "--work-item", "ITEM-1", "--playbook", "sentry_issue_remediation",
                        "--input-manifest", inputs))
                    root = Path(run["artifact_root"])
                    fixture = json.loads((package / "tests/fixtures" / name).read_text())
                    fix = fixture[result_key]
                    fix["worker_handle"] = "/root/fix_design"
                    fix["inputs_consumed"].append("IN-001")
                    start = datetime.fromisoformat(run["runtime_evidence"]["run_started_at"].replace("Z", "+00:00"))
                    stamp = lambda seconds: (start + timedelta(seconds=seconds)).isoformat()
                    event = lambda seconds, kind, **payload: {
                        "timestamp": stamp(seconds), "type": kind, "payload": payload}
                    parent_id = "00000000-0000-0000-0000-000000000001"
                    parent = root / "parent.jsonl"
                    rows = [event(0, "session_meta", id=parent_id)]
                    traces = []
                    for index, (worker, role) in enumerate((
                        ("evidence-topology", "sentry_current_state_investigator"),
                        ("fix-design", "sentry_solution_architect")), 1):
                        assignment = root / (worker + "_assignment.json")
                        assignment.write_text(json.dumps({"objective": "Complete the assigned synthetic Sentry analysis"}))
                        activation = root / (worker + "_activation.txt")
                        guarded = json.loads(command("validate_worker_runtime.py", "--activation-packet-bundle",
                            run["activation_packet_bundle"]["path"], "--expected-agent", role,
                            "--expected-bundle-sha256", run["activation_packet_bundle"]["sha256"],
                            "--assignment", assignment, "--dispatch-file", activation))
                        handle = "/root/" + worker.replace("-", "_")
                        child_id = f"00000000-0000-0000-0000-{index + 1:012d}"
                        offset = index * 10
                        rows.extend([
                            event(offset, "response_item", type="function_call", namespace="collaboration",
                                name="spawn_agent", arguments=json.dumps({"task_name": handle.rsplit("/", 1)[-1],
                                    "message": guarded["activation_message"], **guarded["launch_arguments"]})),
                            event(offset, "event_msg", item={"type": "SubAgentActivity", "kind": "started",
                                "agent_path": handle, "agent_thread_id": child_id}),
                            event(offset + 4, "response_item", type="function_call", namespace="collaboration",
                                name="list_agents", call_id=worker, arguments="{}"),
                            event(offset + 5, "response_item", type="function_call_output", call_id=worker,
                                output=json.dumps({"agents": [{"agent_name": "/root/" + previous.replace("-", "_"),
                                    "agent_status": {"completed": "Done"}}
                                    for previous in ("evidence-topology", "fix-design")[:index]]}))])
                        if worker == "fix-design":
                            rows.insert(-2, event(offset + 0.5, "response_item", type="function_call",
                                namespace="collaboration", name="followup_task", arguments=json.dumps({
                                    "target": handle, "message": "Your exact provider handle is " + handle
                                    + "; record it in the Fix Design result before completing the assignment."})))
                        parent.write_text("\n".join(map(json.dumps, rows)) + "\n")
                        child = root / (worker + ".jsonl")
                        child.write_text("\n".join(json.dumps(row) for row in [
                            event(offset, "session_meta", id=child_id),
                            event(offset + 1, "response_item", type="function_call", name="exec_command",
                                call_id="read", arguments=json.dumps({"cmd": "cat " + str(activation)})),
                            event(offset + 2, "response_item", type="function_call_output", call_id="read",
                                output=activation.read_text())]) + "\n")
                        if worker == "evidence-topology":
                            (root / "normalized_evidence.md").write_text(fixture["normalized_evidence"])
                        else:
                            (root / "fix_design_result.json").write_text(json.dumps(fix))
                        trace = root / (worker + "_trace.json")
                        command("worker_runtime_evidence.py", "--provider-session", parent,
                            "--parent-thread-id", parent_id, "--started-at", run["runtime_evidence"]["run_started_at"],
                            "--ledger", run["runtime_evidence"]["ledger"], "--worker-session", child,
                            "--agent", role, "--trace", trace)
                        traces.extend(("--worker-trace", worker + "=" + str(trace)))
                    command("worker_runtime_evidence.py", "--provider-session", parent,
                        "--parent-thread-id", parent_id, "--started-at", run["runtime_evidence"]["run_started_at"],
                        "--ledger", run["runtime_evidence"]["ledger"], "--closure", root / "runtime_closure.json")
                    command("finalize_sentry_planning.py", "--artifact-root", root,
                        "--evidence-handle", "/root/evidence_topology", "--coordinator-model-effort",
                        "Not exposed / Not exposed", "--framework-revision", preflight["framework_revision"],
                        "--framework-status", "clean", "--repository", "Execution=" + str(repository), *traces)
                    packet = json.loads((root / "finalization_packet.json").read_text())
                    self.assertEqual(packet["identity"]["State"], expected_state)
                    self.assertEqual((root / "implementation_plan.md").exists(), expected_state == "ready_for_implementation")
                    response = root / "handoff_response.md"
                    emitted = command("finalize_work_record.py", "--packet", root / "finalization_packet.json",
                                      "--publish-response", response)
                    self.assertEqual(emitted.encode(), response.read_bytes())
                    self.assertEqual(json.loads((root / "handoff_delivery.json").read_text())["status"], "verified")

    def test_clean_package_preflight_preparation_audits_and_terminal_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory) / "package"
            shutil.copytree(ROOT, package, symlinks=True,
                            ignore=shutil.ignore_patterns(".git", ".thoughts", "__pycache__"))
            for args in (("init", "-q"), ("config", "user.name", "Package fixture"),
                         ("config", "user.email", "fixture@example.invalid"), ("add", "."),
                         ("commit", "-qm", "Synthetic package snapshot")):
                subprocess.run(["git", "-C", str(package), *args], check=True, capture_output=True)
            source = Path(directory) / "parent.jsonl"
            source.write_text(json.dumps({"type": "session_meta", "payload": {
                "id": "00000000-0000-0000-0000-000000000001"}}) + "\n" +
                json.dumps({"type": "turn_context", "payload": {
                "turn_id": "00000000-0000-0000-0000-000000000002"}}) + "\n" +
                "\n".join(json.dumps({"type": "response_item", "payload": {
                "role": role, "content": [{"text": text}]}}) for role, text in (
                ("developer", "begin the first final answer with Developer Workflows skills are available"),
                ("user", "Run the Sentry playbook"))))
            blocked = subprocess.run([sys.executable, "scripts/run_preflight.py", "--provider-session", str(source)],
                                     cwd=package, capture_output=True, text=True, timeout=60)
            self.assertEqual(blocked.returncode, 0, blocked.stdout + blocked.stderr)
            self.assertEqual(json.loads(blocked.stdout)["status"], "passed")
            self.assertIn("presentation_notice", json.loads(blocked.stdout))
            self.assertFalse((package / ".thoughts").exists())
            for args in (
                ("scripts/run_preflight.py",),
                ("scripts/prepare_run.py", "--self-test"),
                ("scripts/finalize_sentry_planning.py", "--self-test"),
                ("-m", "unittest", "tests.test_context_operation_audit", "tests.test_recovery",
                 "tests.test_planning_recovery", "tests.test_feature_delivery_continuation",
                 "tests.test_shared_runtime_acceptance", "tests.test_sentry_failure",
                 "tests.test_handoff_instruction_conflict", "tests.test_sentry_acceptance", "tests.test_sentry_handoff",
                 "tests.test_python_maintenance", "tests.test_validation_modules", "tests.test_review_regressions"),
                ("scripts/finalize_work_record.py", "--self-test"),
            ):
                result = subprocess.run([sys.executable, *args], cwd=package, capture_output=True,
                                        text=True, timeout=60)
                self.assertEqual(result.returncode, 0, " ".join(args) + "\n" +
                                 (result.stdout + result.stderr)[-4000:])
