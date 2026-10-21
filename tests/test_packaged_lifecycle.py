"""Exercise shipped entrypoints from a clean local package, without live workers."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from scripts.provider_runtime import related_run_status_projection_source


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
            stamp = datetime.now().astimezone().isoformat()
            rows = [{"timestamp": stamp, "type": "session_meta", "payload": {"id": "00000000-0000-0000-0000-000000000001"}},
                    {"timestamp": stamp, "type": "turn_context", "payload": {"turn_id": "00000000-0000-0000-0000-000000000002"}}]
            forbidden = {"timestamp": stamp, "type": "response_item", "payload": {"type": "custom_tool_call", "name": "exec",
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
            rejected = command("prepare_run.py", *prepare, "--lifecycle", "remediation", expected=2)
            self.assertIn("lifecycle_conflict", rejected["reason"])
            self.assertFalse((repository / ".thoughts").exists())
            run = command("prepare_run.py", *prepare, "--lifecycle", "planning")
            self.assertEqual(run["lifecycle"], "planning")
            packet = Path(run["finalization_packet"])
            before = packet.read_bytes()
            self.assertEqual(json.loads(before)["identity"]["Lifecycle"], "planning")
            activation = ("--activation-packet-bundle", run["activation_packet_bundle"]["path"],
                          "--expected-agent", "current_state_investigator", "--expected-bundle-sha256",
                          run["activation_packet_bundle"]["sha256"])
            self.assertEqual(command("validate_worker_runtime.py", *activation)["status"], "allowed")
            save(rows + [forbidden])
            rejected = command("validate_worker_runtime.py", *activation, expected=2)
            self.assertTrue(any("parent_context_nonconformant" in error for error in rejected["errors"]))
            self.assertEqual(packet.read_bytes(), before)
            collector = ("--provider-session", source, "--parent-thread-id", rows[0]["payload"]["id"],
                         "--started-at", run["runtime_evidence"]["run_started_at"],
                         "--ledger", run["runtime_evidence"]["ledger"])
            rejected = command("worker_runtime_evidence.py", *collector, "--parent-thread-id",
                               "00000000-0000-0000-0000-000000000099", expected=2)
            self.assertEqual(rejected["reason"], "runtime_dispatch_parent_mismatch")
            alternate = Path(directory) / "alternate.jsonl"
            alternate.write_bytes(source.read_bytes())
            rejected = command("worker_runtime_evidence.py", *collector, "--provider-session", alternate, expected=2)
            self.assertEqual(rejected["reason"], "runtime_dispatch_provider_session_mismatch")
            self.assertFalse(Path(run["runtime_evidence"]["ledger"]).exists())
            with source.open("a") as stream:
                stream.write(json.dumps({"timestamp": datetime.now().astimezone().isoformat(), "type": "turn_context", "payload": {
                    "turn_id": "00000000-0000-0000-0000-000000000003"}}) + "\n")
            rejected = command("validate_worker_runtime.py", *activation, expected=2)
            self.assertTrue(any("parent_context_turn_mismatch" in error for error in rejected["errors"]))
            self.assertEqual(packet.read_bytes(), before)

    def test_shipped_prepare_requires_correlated_terminal_status_before_stale_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            package = self.package(directory)
            repository = Path(directory) / "repository"
            repository.mkdir()
            subprocess.run(["git", "-C", str(repository), "init", "-q"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(repository), "config", "user.name", "Fixture"],
                           check=True, capture_output=True)
            subprocess.run(["git", "-C", str(repository), "config", "user.email", "fixture@example.invalid"],
                           check=True, capture_output=True)
            subprocess.run(["git", "-C", str(repository), "commit", "--allow-empty", "-qm", "Initial fixture"],
                           check=True, capture_output=True)

            parent_id, turn_id, child_id = ("00000000-0000-0000-0000-000000000001",
                                            "00000000-0000-0000-0000-000000000002",
                                            "00000000-0000-0000-0000-000000000003")
            stamp = datetime.now().astimezone().isoformat()
            parent = Path(directory) / "parent.jsonl"
            core_events = [
                {"timestamp": stamp, "type": "session_meta", "payload": {"id": parent_id}},
                {"timestamp": stamp, "type": "turn_context", "payload": {"turn_id": turn_id}},
            ]
            input_manifest = Path(directory) / "inputs.json"
            input_manifest.write_text(json.dumps({"inputs": [{"Input ID": "IN-001",
                "Input or artifact": "Current synthetic issue", "Source or path": "User",
                "Authority": "User", "Status": "Registered"}]}))

            def save_parent(status):
                events = list(core_events)
                if status is not None:
                    call_id = "related-run-status"
                    projection = related_run_status_projection_source("ITEM-1", parent_id, (child_id,))
                    events.extend([
                        {"timestamp": stamp, "type": "response_item", "payload": {
                            "type": "custom_tool_call", "name": "exec", "call_id": call_id, "input": projection}},
                        {"timestamp": stamp, "type": "response_item", "payload": {
                            "type": "custom_tool_call_output", "call_id": call_id,
                            "output": [{"type": "text", "text": json.dumps([
                                {"id": child_id, "status": status}])}]}}])
                parent.write_text("".join(json.dumps(row) + "\n" for row in events))

            def command(*args, expected=0):
                result = subprocess.run([sys.executable, str(package / "scripts" / "prepare_run.py"), *map(str, args)],
                                        cwd=package, capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
                return json.loads(result.stdout)

            base = ("--execution-repository", repository, "--work-item", "ITEM-1", "--playbook",
                    "techops_issue_remediation", "--input-manifest", input_manifest, "--provider-session", parent)
            save_parent(None)
            prior = command(*base)
            root = Path(prior["artifact_root"])
            prior_run_id = prior["run_id"]
            work_record = root / "work_record.md"
            record = work_record.read_text()
            state_row = next(line for line in record.splitlines() if line.startswith("| State |"))
            work_record.write_text(record.replace(state_row, "| State | in_progress |"))
            ledger = root / "runtime_dispatches.json"
            ledger.write_text(json.dumps({"thread_mappings": {"/root/prior_worker": child_id},
                "events": [{"Operation": "spawn_agent", "Provider handle": "/root/prior_worker",
                            "Thread ID": child_id}], "failed_dispatches": []}))
            before = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}

            save_parent("running")
            blocked = command(*base, "--archive-stale-run", expected=2)
            self.assertIn("stale_run_related_task_active:" + child_id, blocked["reason"])
            self.assertIn("| State | in_progress |", work_record.read_text())
            self.assertEqual(before, {path.relative_to(root): path.read_bytes()
                                      for path in root.rglob("*") if path.is_file()})

            save_parent("completed")
            prepared = command(*base, "--archive-stale-run")
            self.assertNotEqual(prepared["run_id"], prior_run_id)
            archived = Path(prepared["archived_prior_run"])
            archived_ledger = json.loads((archived / "runtime_dispatches.json").read_text())
            self.assertEqual(archived_ledger["thread_mappings"], {"/root/prior_worker": child_id})
            self.assertIn("| State | in_progress |", (archived / "work_record.md").read_text())

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
                    namespace = "FC" if playbook == "feature_delivery" else "ISS"
                    evidence = {"Evidence ID": f"E-{namespace}-001", "Source": "Synthetic issue",
                        "Summary": "Current synthetic issue evidence", "Confidence": "High",
                        "Uncertainty": "None", "Status": "Verified"}
                    worker_result = {"run_id": run["run_id"], "worker_result": {
                        **dict.fromkeys(template["worker_results"][0], "Synthetic current evidence"),
                        "Worker": worker, "Outcome": "complete", "Evidence / claim refs": evidence["Evidence ID"]},
                        "evidence": [evidence], "claims": [], "decisions": [], "actions": []}
                    asset_manifest = {"schema_version": 1, "status": "passed", "work_item": "ITEM-1",
                        "sources": [{"source_id": "SRC-JIRA", "input_id": "IN-001",
                            "kind": "jira_issue_attachments", "locator": "Jira ITEM-1 attachments",
                            "requiredness": "required", "discovery_status": "empty",
                            "discovery_method": "Read the complete Jira attachment inventory",
                            "remote_link_inventory": {"status": "empty", "method": "Read Jira remote links for ITEM-1",
                                "locators": []}, "limitation": "No synthetic Jira attachments were supplied.",
                            "asset_ids": [], "evidence_refs": [evidence["Evidence ID"]]}], "assets": [],
                        "gate": {"inventory_complete": True, "all_assets_accounted_for": True,
                            "all_available_assets_reviewed": True, "all_material_assets_linked": True,
                            "reviewed_before_plan": True, "unresolved_asset_ids": [], "blocking_source_ids": []}}
                    response = {"output": "Synthetic current evidence", "result": worker_result}
                    if contract.get("asset_inventory"):
                        response["asset_manifest"] = asset_manifest
                    response_text = json.dumps(response)
                    if recover == "malformed":
                        response_text = '{"run_id": "' + run["run_id"] + '"'
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
                    child_rows = [
                        event(1, "session_meta", id=child_id),
                        event(2, "response_item", type="function_call", name="exec_command", call_id="read",
                            arguments=json.dumps({"cmd": "cat " + str(activation), "workdir": str(repository)})),
                        event(3, "response_item", type="function_call_output", call_id="read",
                            output=activation.read_text()),
                        event(4, "turn_context", turn_id="00000000-0000-0000-0000-000000000003",
                            model=guarded["launch_arguments"]["model"],
                            effort=guarded["launch_arguments"]["reasoning_effort"])]
                    if recover != "missing":
                        child_rows.append(event(5, "response_item", type="message", role="assistant",
                            phase="final_answer", content=[{"type": "output_text", "text": response_text}]))
                    child.write_text("\n".join(json.dumps(row) for row in child_rows) + "\n")
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
                                    output=corrected_activation.read_text()),
                                event(11, "turn_context", turn_id="00000000-0000-0000-0000-000000000004",
                                    model=guarded["launch_arguments"]["model"],
                                    effort=guarded["launch_arguments"]["reasoning_effort"]),
                                event(12, "response_item", type="message", role="assistant", phase="final_answer",
                                    content=[{"type": "output_text", "text": json.dumps(response)}])):
                                stream.write(json.dumps(row) + "\n")
                        trace = root / "corrected_trace.json"
                        command("worker_runtime_evidence.py", *collector, "--worker-session", child,
                                "--agent", "current_state_investigator", "--trace", trace)
                        self.assertEqual((root / "trace.json").read_bytes(), rejected_bytes)
                    exported = json.loads(packet.read_text())
                    self.assertEqual(exported["runtime_audits"][0]["Worker"], worker)
                    self.assertFalse(any(row.get("Worker") == worker and row.get("Outcome") == "complete"
                                         for row in exported.get("worker_results", [])))
                    if recover is False:
                        # Reproduce a missing Coordinator audit while preserving the passed worker trace.
                        exported["runtime_audits"] = []
                        packet.write_text(json.dumps(exported))
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

    def test_sentry_shipped_commands_publish_plan_blocker_and_complete_remediation(self):
        with tempfile.TemporaryDirectory() as directory:
            package = self.package(directory)

            def command(script, *args, expected=0):
                result = subprocess.run([sys.executable, str(package / "scripts" / script), *map(str, args)],
                                        cwd=package, capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
                return result.stdout

            preflight = json.loads(command("run_preflight.py"))
            for name, result_key, expected_state, recover in (
                ("sentry_deterministic_finalization.json", "fix_design_result", "ready_for_implementation", False),
                ("sentry_runtime_regressions.json", "valid_awaiting_fix_design_result", "awaiting_input", False),
                ("sentry_deterministic_finalization.json", "fix_design_result", "ready_for_implementation", True),
                ("sentry_runtime_regressions.json", "valid_awaiting_fix_design_result", "awaiting_input", True)):
                case = expected_state + ("-recovered" if recover else "")
                with self.subTest(state=expected_state, recover=recover), patch.dict(os.environ, {
                        "CODEX_THREAD_ID": "00000000-0000-0000-0000-000000000001",
                        "CODEX_HOME": str(Path(directory) / "native" / case)}):
                    repository = Path(directory) / case
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
                    parent_id = "00000000-0000-0000-0000-000000000001"
                    turn_id = "00000000-0000-0000-0000-000000000099"
                    parent = Path(os.environ["CODEX_HOME"]) / "sessions" / ("parent-" + parent_id + ".jsonl")
                    parent.parent.mkdir(parents=True)
                    parent_start = datetime.now().astimezone().isoformat()
                    parent.write_text("\n".join(json.dumps(row) for row in [
                        {"timestamp": parent_start, "type": "session_meta", "payload": {"id": parent_id}},
                        {"timestamp": parent_start, "type": "turn_context", "payload": {"turn_id": turn_id}}]) + "\n")
                    native_preflight = json.loads(command("run_preflight.py"))
                    self.assertEqual(native_preflight["parent_context"]["provider_session"], str(parent.resolve()))
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
                    rows = [{"timestamp": parent_start, "type": "session_meta", "payload": {"id": parent_id}},
                            {"timestamp": parent_start, "type": "turn_context", "payload": {"turn_id": turn_id}}]
                    traces = []
                    rejected_bytes = None
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
                        if recover and index == 1:
                            failed_handle = "/root/failed_original"
                            failed_id = "00000000-0000-0000-0000-000000000998"
                            rows.extend([
                                event(1, "response_item", type="function_call", namespace="collaboration", name="spawn_agent",
                                    arguments=json.dumps({"task_name": "failed_original", "message": guarded["activation_message"],
                                                          **guarded["launch_arguments"]})),
                                event(1, "event_msg", item={"type": "SubAgentActivity", "kind": "started",
                                    "agent_path": failed_handle, "agent_thread_id": failed_id}),
                                event(4, "event_msg", item={"type": "SubAgentActivity", "kind": "failed", "agent_path": failed_handle}),
                                event(5, "response_item", type="function_call", namespace="collaboration", name="list_agents",
                                    call_id="failed-inventory", arguments="{}"),
                                event(6, "response_item", type="function_call_output", call_id="failed-inventory",
                                    output=json.dumps({"agents": [{"agent_name": failed_handle, "agent_status": {"failed": "Synthetic failure"}}]}))])
                            parent.write_text("\n".join(map(json.dumps, rows)) + "\n")
                            child = root / "failed-original.jsonl"
                            child.write_text("\n".join(json.dumps(row) for row in [
                                event(1, "session_meta", id=failed_id),
                                event(2, "response_item", type="function_call", name="exec_command", call_id="bootstrap",
                                    arguments=json.dumps({"cmd": "cat " + str(activation)})),
                                event(3, "response_item", type="function_call_output", call_id="bootstrap", output=activation.read_text())]) + "\n")
                            rejected = root / "failed-original-trace.json"
                            command("worker_runtime_evidence.py", "--provider-session", parent, "--parent-thread-id", parent_id,
                                "--started-at", run["runtime_evidence"]["run_started_at"], "--ledger", run["runtime_evidence"]["ledger"],
                                "--worker-session", child, "--agent", role, "--trace", rejected, expected=2)
                            rejected_bytes = rejected.read_bytes()
                            activation = root / (worker + "_replacement_activation.txt")
                            guarded = json.loads(command("validate_worker_runtime.py", "--activation-packet-bundle",
                                run["activation_packet_bundle"]["path"], "--expected-agent", role, "--expected-bundle-sha256",
                                run["activation_packet_bundle"]["sha256"], "--assignment", assignment, "--dispatch-file", activation,
                                "--rejected-trace", rejected, "--provider-handle", failed_handle, "--last-dispatch-at", stamp(1),
                                "--provider-status", "failed"))
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
                                    for previous in ("evidence-topology", "fix-design")[:index]] +
                                    ([{"agent_name": "/root/failed_original", "agent_status": {"failed": "Synthetic failure"}}] if recover else [])}))])
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
                    with parent.open("a") as stream:
                        stream.write(json.dumps(event(26, "response_item", type="function_call", name="exec_command",
                            arguments=json.dumps({"cmd": "cat " + str(root / "normalized_evidence.md")}))) + "\n")
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
                    if recover:
                        self.assertEqual(rejected.read_bytes(), rejected_bytes)
                        closure = json.loads((root / "runtime_closure.json").read_text())
                        self.assertEqual({row["Provider handle"]: row["Provider status"] for row in closure["terminal_observations"]}[
                            "/root/failed_original"], "failed")
                    if expected_state == "ready_for_implementation" and not recover:
                        plan_before = (root / "implementation_plan.md").read_bytes()
                        planning_packet = json.loads(Path(run["finalization_packet"]).read_text())
                        planning_actions = planning_packet["actions"]
                        planning_selection = planning_packet["playbook_selection"]
                        remediation = json.loads(command("prepare_run.py", "--execution-repository", repository,
                            "--work-item", "ITEM-1", "--playbook", "sentry_issue_remediation",
                            "--input-manifest", inputs, "--continuation", "--remediation-reentry",
                            "--approval-reference", "Synthetic explicit approval"))
                        self.assertEqual(remediation["lifecycle"], "remediation")
                        self.assertEqual(remediation["archived_prior_run"],
                                         str(root / "runs" / packet["identity"]["Run ID"]))
                        self.assertEqual((root / "implementation_plan.md").read_bytes(), plan_before)
                        self.assertEqual(
                            json.loads(Path(remediation["finalization_packet"]).read_text())["actions"], planning_actions)
                        reentry_selection = json.loads(
                            Path(remediation["finalization_packet"]).read_text())["playbook_selection"]
                        for field in ("Primary evidence", "Primary goal", "Selected playbook", "Closest alternative", "Why this playbook"):
                            self.assertEqual(reentry_selection[field], planning_selection[field], field)
                        self.assertEqual(remediation["worker_contracts"]["standard_planning_finalization"]["owner"],
                                         "Coordinator")
                        self.assertTrue({"implementer", "reviewer", "tester"} <=
                                        remediation["worker_contracts"].keys())
                        activation_bundle = json.loads(
                            Path(remediation["activation_packet_bundle"]["path"]).read_text())
                        for role in ("implementer", "reviewer", "tester", "documenter"):
                            with self.subTest(remediation_activation_contract=role):
                                self.assertEqual(
                                    activation_bundle["packets"][role]["worker_contract"],
                                    remediation["worker_contracts"][role],
                                )
                        assignment = root / "remediation-implementer-assignment.json"
                        assignment.write_text(json.dumps({"objective": "Implement the approved Sentry plan",
                            "input_paths": [str(root / "implementation_plan.md"),
                                            str(root / "normalized_evidence.md")]}))
                        activation = json.loads(command("validate_worker_runtime.py", "--activation-packet-bundle",
                            remediation["activation_packet_bundle"]["path"], "--expected-agent", "implementer",
                            "--expected-bundle-sha256", remediation["activation_packet_bundle"]["sha256"],
                            "--assignment", assignment, "--dispatch-file", root / "implementer-activation.txt"))
                        self.assertEqual(activation["status"], "allowed")
                        source_guard = command("validate_worker_runtime.py", "--before-source-change",
                            remediation["finalization_packet"], "--implementer-handle", "/root/implement",
                            "--provider-status", "running", expected=2)
                        self.assertIn("remediation_not_activated", source_guard)

                        remediation_start = datetime.fromisoformat(
                            remediation["runtime_evidence"]["run_started_at"].replace("Z", "+00:00"))
                        def remediation_event(offset, kind, **payload):
                            return {"timestamp": (remediation_start + timedelta(seconds=offset)).isoformat(),
                                    "type": kind, "payload": payload}

                        live_handles = []
                        live_threads = {}
                        role_dispatches = {}
                        for index, role in enumerate(("implementer", "reviewer", "tester"), 1):
                            handle = "/root/" + {"implementer": "implement", "reviewer": "review",
                                                "tester": "validate"}[role]
                            assignment_path = root / ("remediation-" + role + "-assignment.json")
                            assignment_path.write_text(json.dumps({"objective": "Complete the approved Sentry delivery role",
                                "input_paths": [str(root / "implementation_plan.md")] }))
                            dispatch_path = root / ("remediation-" + role + "-activation.txt")
                            guarded = json.loads(command("validate_worker_runtime.py", "--activation-packet-bundle",
                                remediation["activation_packet_bundle"]["path"], "--expected-agent", role,
                                "--expected-bundle-sha256", remediation["activation_packet_bundle"]["sha256"],
                                "--assignment", assignment_path, "--dispatch-file", dispatch_path))
                            thread = f"00000000-0000-0000-0000-{index + 10:012d}"
                            rows.extend([
                                remediation_event(index * 2, "response_item", type="function_call",
                                    namespace="collaboration", name="spawn_agent", call_id="remediation-" + role,
                                    arguments=json.dumps({"task_name": handle.rsplit("/", 1)[-1],
                                        "message": guarded["activation_message"], **guarded["launch_arguments"]})),
                                remediation_event(index * 2 + 1, "event_msg", item={"type": "SubAgentActivity",
                                    "kind": "started", "agent_path": handle,
                                    "agent_thread_id": thread}),
                            ])
                            live_handles.append(handle)
                            live_threads[role] = thread
                            role_dispatches[role] = (dispatch_path, guarded, index * 2)
                        rows.extend([
                            remediation_event(8, "response_item", type="function_call", namespace="collaboration",
                                name="list_agents", call_id="remediation-inventory", arguments="{}"),
                            remediation_event(9, "response_item", type="function_call_output",
                                call_id="remediation-inventory", output=json.dumps({"agents": [
                                    {"agent_name": handle, "agent_status": {"running": "Active"}}
                                    for handle in live_handles]})),
                        ])
                        parent.write_text("\n".join(map(json.dumps, rows)) + "\n")
                        collected = json.loads(command("worker_runtime_evidence.py", "--provider-session", parent,
                            "--parent-thread-id", parent_id, "--started-at",
                            remediation["runtime_evidence"]["run_started_at"], "--ledger",
                            remediation["runtime_evidence"]["ledger"]))
                        self.assertEqual(collected["profile_activation"]["status"], "activated")
                        source_guard = json.loads(command("validate_worker_runtime.py", "--before-source-change",
                            remediation["finalization_packet"], "--implementer-handle", "/root/implement",
                            "--provider-status", "running"))
                        self.assertEqual(source_guard["status"], "allowed")
                        template = json.loads((package / "templates/finalization_packet.json").read_text())
                        delivery = (
                            ("implementer", "implement", "IM", "Implemented the approved Sentry plan."),
                            ("reviewer", "review", "RV", "Approved the exact implementation candidate."),
                            ("tester", "validate", "TE", "Focused regression passed for the exact candidate."),
                        )
                        child_sessions = []
                        for agent, worker, namespace, narrative in delivery:
                            role = agent
                            dispatch_path, guarded, dispatch_offset = role_dispatches[role]
                            evidence_id = f"E-{namespace}-001"
                            summary = {key: "Synthetic accepted Sentry delivery result" for key in
                                       template["worker_results"][0]}
                            summary.update({"Worker": worker, "Outcome": "complete",
                                            "Evidence / claim refs": evidence_id})
                            evidence = {key: "Synthetic Sentry delivery evidence" for key in template["evidence"][0]}
                            evidence["Evidence ID"] = evidence_id
                            claim = {key: "Synthetic Sentry delivery claim" for key in template["claims"][0]}
                            claim.update({"Claim ID": f"CL-{namespace}-001", "Claim": narrative,
                                "Evidence refs": evidence_id, "Confidence": "High",
                                "Uncertainty": "Synthetic evidence exercises the accepted delivery contract.",
                                "Status": "Supported"})
                            result = {"run_id": remediation["run_id"], "worker_result": summary,
                                      "evidence": [evidence], "claims": [claim], "decisions": [], "actions": []}
                            binding = json.loads(Path(remediation["activation_packet_bundle"]["path"]).read_text())[
                                "packets"][agent]
                            child = root / (worker + "-response.jsonl")
                            read = 'await tools.exec_command(' + json.dumps({"cmd": "cat " + str(dispatch_path)}) + ')'
                            child.write_text("\n".join(json.dumps(item) for item in [
                                remediation_event(0, "session_meta", id=live_threads[agent]),
                                remediation_event(dispatch_offset + 2, "response_item", type="custom_tool_call",
                                    call_id="binding-read", name="exec", input=read),
                                remediation_event(dispatch_offset + 3, "response_item", type="custom_tool_call_output",
                                    call_id="binding-read", output=dispatch_path.read_text()),
                                remediation_event(dispatch_offset + 3.5, "turn_context", turn_id=str(UUID(int=404)),
                                    model=binding["model"], effort=binding["effort"]),
                                remediation_event(dispatch_offset + 4, "response_item", type="message", role="assistant",
                                    phase="final_answer", content=[{"type": "output_text", "text": json.dumps({
                                        "output": narrative, "result": result})}]),
                            ]) + "\n")
                            child_sessions.append((agent, worker, child))
                        for index, (agent, worker, child) in enumerate(child_sessions, 1):
                            rows.append(remediation_event(10 + index, "event_msg", item={
                                "type": "SubAgentActivity", "kind": "completed",
                                "agent_path": "/root/" + worker}))
                        rows.extend([
                            remediation_event(99, "response_item", type="function_call", namespace="collaboration",
                                name="list_agents", call_id="remediation-terminal-inventory", arguments="{}"),
                            remediation_event(100, "response_item", type="function_call_output",
                                call_id="remediation-terminal-inventory", output=json.dumps({"agents": [
                                    {"agent_name": handle, "agent_status": {"completed": "Done"}}
                                    for handle in [*live_handles, "/root/evidence_topology", "/root/fix_design"]]})),
                        ])
                        parent.write_text("\n".join(map(json.dumps, rows)) + "\n")
                        for agent, worker, child in child_sessions:
                            trace = root / (worker + "-trace.json")
                            command("worker_runtime_evidence.py", "--provider-session", parent,
                                "--parent-thread-id", parent_id, "--started-at",
                                remediation["runtime_evidence"]["run_started_at"], "--ledger",
                                remediation["runtime_evidence"]["ledger"], "--worker-session", child,
                                "--agent", agent, "--trace", trace)
                            merged = subprocess.run([sys.executable, str(package / "scripts/merge_techops_result.py"),
                                "--packet", remediation["finalization_packet"], "--agent", agent,
                                "--trace", trace],
                                cwd=package, capture_output=True, text=True, timeout=60)
                            self.assertEqual(merged.returncode, 0, merged.stdout + merged.stderr)
                        staged = json.loads(command("stage_documenter_packet.py", "--packet",
                            remediation["finalization_packet"], "--coordinator-model-effort",
                            "Not exposed / Not exposed", "--prompt-conformance", "pass",
                            "--engineering-outcome", "solved"))
                        self.assertEqual(staged["status"], "staged")
                        self.assertEqual(staged["state"], "handoff")
                        remediation_bindings = json.loads((root / "role_bindings.json").read_text())
                        documenter_assignment = root / "remediation-documenter-assignment.json"
                        documenter_assignment.write_text(json.dumps({
                            "objective": "Complete the handoff from accepted delivery results",
                            "input_paths": [str(root / "finalization_packet.json"), str(root / "implementation_plan.md")],
                        }))
                        documenter_dispatch = root / "remediation-documenter-activation.txt"
                        documenter_activation = json.loads(command("validate_worker_runtime.py",
                            "--activation-packet-bundle", remediation["activation_packet_bundle"]["path"],
                            "--expected-agent", "documenter", "--expected-bundle-sha256",
                            remediation["activation_packet_bundle"]["sha256"], "--assignment", documenter_assignment,
                            "--dispatch-file", documenter_dispatch))
                        self.assertEqual(documenter_activation["status"], "allowed")
                        documenter_handle = "/root/documenter"
                        documenter_thread = "00000000-0000-0000-0000-000000000040"
                        rows.extend([
                            remediation_event(110, "response_item", type="function_call", namespace="collaboration",
                                name="spawn_agent", call_id="remediation-documenter",
                                arguments=json.dumps({"task_name": "documenter",
                                    "message": documenter_activation["activation_message"],
                                    **documenter_activation["launch_arguments"]})),
                            remediation_event(111, "event_msg", item={"type": "SubAgentActivity", "kind": "started",
                                "agent_path": documenter_handle, "agent_thread_id": documenter_thread}),
                        ])
                        template = json.loads((package / "templates/finalization_packet.json").read_text())
                        packet = json.loads(Path(remediation["finalization_packet"]).read_text())
                        documenter_binding = remediation_bindings["bindings"]["documenter"]
                        documenter_observed = ("Not exposed; explicitly launched with "
                            + documenter_binding["model"] + " / " + documenter_binding["effort"])
                        documenter_evidence = {key: "Synthetic Documenter handoff evidence"
                            for key in template["evidence"][0]}
                        documenter_evidence.update({"Evidence ID": "E-HD-001",
                            "Source": "Current-run handoff artifacts",
                            "Summary": "Documenter persisted the accepted Sentry remediation handoff.",
                            "Confidence": "High", "Uncertainty": "No additional handoff uncertainty.",
                            "Status": "Verified"})
                        documenter_worker = {key: "Synthetic Documenter execution record"
                            for key in template["workers"][0]}
                        documenter_worker.update({"Worker": "handoff", "Role": "Documenter",
                            "Assigned inputs": "Accepted implement, review, and validation results",
                            "Mode": "Delegated", "Depth": "Standard", "Skills": "work_record_maintenance",
                            "Tools": "work_record_read, work_record_write, artifact_write",
                            "Configured model/effort": documenter_binding["model"] + " / " + documenter_binding["effort"],
                            "Provider-observed model/effort": documenter_observed, "Outcome": "complete",
                            "Confidence": "High"})
                        documenter_result = {key: "Synthetic Documenter handoff result"
                            for key in template["worker_results"][0]}
                        documenter_result.update({"Worker": "handoff", "Outcome": "complete",
                            "Confidence": "High", "Unique contribution": "Persisted the accepted handoff and linked artifacts.",
                            "Evidence / claim refs": "E-HD-001", "Actual model/effort": documenter_observed})
                        documenter_claim = {key: "Synthetic Documenter claim" for key in template["claims"][0]}
                        documenter_claim.update({"Claim ID": "CL-HD-001",
                            "Claim": "The handoff links the accepted implementation and validation artifacts.",
                            "Evidence refs": "E-HD-001", "Confidence": "High",
                            "Uncertainty": "Synthetic handoff evidence is limited to this packaged lifecycle test.",
                            "Status": "Supported"})
                        documenter_decision = {key: "Synthetic Documenter decision" for key in template["decisions"][0]}
                        documenter_decision.update({"Decision ID": "DE-HD-001",
                            "Decision": "Accept the current-run implementation, review, validation, and handoff evidence.",
                            "Claim refs": "; ".join([*(f"CL-{namespace}-001" for _, _, namespace, _ in delivery),
                                                       "CL-HD-001"]),
                            "Owner": "Coordinator", "Status": "Accepted"})
                        documenter_action = {key: "Synthetic Documenter action" for key in template["actions"][0]}
                        documenter_action.update({"Action ID": "A-HD-001",
                            "Action": "Complete the documented release checks.", "Decision ref": "DE-HD-001",
                            "Owner": "Service owner", "Status": "Planned"})
                        packet["evidence"].append(documenter_evidence)
                        packet["claims"].append(documenter_claim)
                        packet["decisions"].append(documenter_decision)
                        packet["actions"].append(documenter_action)
                        packet["workers"].append(documenter_worker)
                        packet["worker_results"].append(documenter_result)
                        packet["handoff"].update({
                            "workflow_result": "The approved Sentry correction passed focused validation and is ready for handoff.",
                            "implementation_plan": str(root / "implementation_plan.md"),
                            "established": ["The accepted Sentry plan was implemented and validated."],
                            "best_current_explanations": [],
                            "next_action": {"owner": "Service owner", "action": "Complete the documented release checks.",
                                "complete_when": "The approved change is released and monitored."},
                            "artifacts": [str(root / "implementation_plan.md")],
                            "execution": "Standard remediation completed; provider closure follows pre-release.",
                            "provenance": "Framework revision " + preflight["framework_revision"]
                                + "; sentry_issue_remediation"})
                        Path(remediation["finalization_packet"]).write_text(json.dumps(packet, indent=2) + "\n")
                        documenter_child = root / "remediation-documenter-response.jsonl"
                        documenter_child.write_text("\n".join(json.dumps(item) for item in [
                            remediation_event(0, "session_meta", id=documenter_thread),
                            remediation_event(112, "response_item", type="function_call", name="exec_command",
                                call_id="documenter-binding-read", arguments=json.dumps({"cmd": "cat " + str(documenter_dispatch)})),
                            remediation_event(113, "response_item", type="function_call_output",
                                call_id="documenter-binding-read", output=documenter_dispatch.read_text()),
                            remediation_event(114, "turn_context", turn_id=str(UUID(int=405)),
                                model=documenter_binding["model"], effort=documenter_binding["effort"]),
                            remediation_event(116, "response_item", type="message", role="assistant",
                                phase="final_answer", content=[{"type": "output_text",
                                    "text": "The assigned handoff fields and artifacts are complete."}]),
                        ]) + "\n")
                        rows.extend([
                            remediation_event(121, "event_msg", item={"type": "SubAgentActivity", "kind": "completed",
                                "agent_path": documenter_handle}),
                            remediation_event(130, "response_item", type="function_call", namespace="collaboration",
                                name="list_agents", call_id="remediation-documenter-inventory", arguments="{}"),
                            remediation_event(131, "response_item", type="function_call_output",
                                call_id="remediation-documenter-inventory", output=json.dumps({"agents": [
                                    {"agent_name": handle, "agent_status": {"completed": "Done"}}
                                    for handle in [*live_handles, documenter_handle,
                                        "/root/evidence_topology", "/root/fix_design"]]})),
                        ])
                        parent.write_text("\n".join(map(json.dumps, rows)) + "\n")
                        documenter_trace = root / "documenter-trace.json"
                        command("worker_runtime_evidence.py", "--provider-session", parent,
                            "--parent-thread-id", parent_id, "--started-at",
                            remediation["runtime_evidence"]["run_started_at"], "--ledger",
                            remediation["runtime_evidence"]["ledger"], "--worker-session", documenter_child,
                            "--agent", "documenter", "--trace", documenter_trace)
                        packet = json.loads(Path(remediation["finalization_packet"]).read_text())
                        self.assertIn("handoff", {row["Worker"] for row in packet["worker_results"]})
                        self.assertIn("handoff", {row["Worker"] for row in packet["runtime_audits"]})

                        closure = root / "runtime_closure.json"
                        record = root / "work_record.md"
                        command("worker_runtime_evidence.py", "--provider-session", parent,
                            "--parent-thread-id", parent_id, "--started-at",
                            remediation["runtime_evidence"]["run_started_at"], "--ledger",
                            remediation["runtime_evidence"]["ledger"], "--pending-closure", closure)
                        finalizer_identity = ("--coordinator-model-effort", "Not exposed / Not exposed",
                            "--framework-revision", preflight["framework_revision"], "--framework-status", "clean")
                        command("finalize_work_record.py", "--packet", remediation["finalization_packet"],
                            "--closure", closure, "--record", record, "--check-packet", *finalizer_identity)
                        command("finalize_work_record.py", "--packet", remediation["finalization_packet"],
                            "--closure", closure, "--record", record, "--pre-release", *finalizer_identity)

                        rows.extend([
                            remediation_event(299, "response_item", type="function_call", namespace="collaboration",
                                name="list_agents", call_id="remediation-post-prerelease-inventory", arguments="{}"),
                            remediation_event(300, "response_item", type="function_call_output",
                                call_id="remediation-post-prerelease-inventory", output=json.dumps({"agents": [
                                    {"agent_name": handle, "agent_status": {"completed": "Done"}}
                                    for handle in [*live_handles, documenter_handle,
                                        "/root/evidence_topology", "/root/fix_design"]]})),
                        ])
                        parent.write_text("\n".join(map(json.dumps, rows)) + "\n")
                        command("worker_runtime_evidence.py", "--provider-session", parent,
                            "--parent-thread-id", parent_id, "--started-at",
                            remediation["runtime_evidence"]["run_started_at"], "--ledger",
                            remediation["runtime_evidence"]["ledger"], "--closure", closure)
                        command("finalize_work_record.py", "--packet", remediation["finalization_packet"],
                            "--closure", closure, "--record", record, *finalizer_identity)
                        response = root / "handoff_response.md"
                        emitted = command("finalize_work_record.py", "--packet",
                            remediation["finalization_packet"], "--publish-response", response)
                        self.assertEqual(emitted.encode(), response.read_bytes())
                        delivery_receipt = json.loads((root / "handoff_delivery.json").read_text())
                        self.assertEqual(delivery_receipt["status"], "verified")
                        self.assertEqual(delivery_receipt["scope"],
                            "prepared response bytes; actual chat delivery is not observable by this CLI")

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
                                        text=True, timeout=180)
                self.assertEqual(result.returncode, 0, " ".join(args) + "\n" +
                                 (result.stdout + result.stderr)[-4000:])
