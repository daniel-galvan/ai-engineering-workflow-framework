"""Native identity resolution uses controlled metadata, never this editing chat's history."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.provider_runtime import current_parent_session
from tests import test_packaged_lifecycle as packaging


PARENT = "00000000-0000-0000-0000-000000000001"
TURN = "00000000-0000-0000-0000-000000000002"


class NativeParentSession(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home = self.root / "native"
        self.sessions = self.home / "sessions"
        self.sessions.mkdir(parents=True)
        environment = patch.dict(os.environ, {"CODEX_HOME": str(self.home), "CODEX_THREAD_ID": PARENT})
        environment.start()
        self.addCleanup(environment.stop)

    def record(self, name, stamp="2026-10-20T00:00:00Z", turn=TURN, identity=PARENT):
        path = self.sessions / (name + "-" + PARENT + ".jsonl")
        rows = [{"type": "session_meta", "payload": {"id": identity}},
                {"timestamp": stamp, "type": "turn_context", "payload": {"turn_id": turn}},
                {"timestamp": stamp, "type": "response_item", "payload": {"role": "user", "content": [
                    {"type": "input_text", "text": "Controlled current planning request; no prior analysis."}]}}]
        path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
        return path

    def test_reopened_old_filename_wins_by_native_current_turn_metadata(self):
        current = self.record("2026-10-13-reopened")
        stale = self.record("2026-10-20-new-name", "2026-10-19T00:00:00Z")
        self.record("wrong-header", identity="00000000-0000-0000-0000-000000000099")
        self.assertEqual(current_parent_session(), current.resolve())
        self.assertEqual(current_parent_session(current), current.resolve())
        with self.assertRaisesRegex(ValueError, "provider_current_session_mismatch"):
            current_parent_session(stale)
        with current.open("a") as stream:
            stream.write('{"timestamp":')
        self.assertEqual(current_parent_session(), current.resolve())

    def test_missing_ambiguous_and_invalid_native_identity_are_blockers(self):
        with self.assertRaisesRegex(ValueError, "provider_current_session_unavailable"):
            current_parent_session()
        self.record("first")
        self.record("duplicate")
        with self.assertRaisesRegex(ValueError, "provider_current_session_ambiguous"):
            current_parent_session()
        with patch.dict(os.environ, {"CODEX_THREAD_ID": "not-a-native-identity"}):
            with self.assertRaisesRegex(ValueError, "provider_current_identity_invalid"):
                current_parent_session()

    def test_shipped_entrypoints_bind_native_parent_without_a_caller_supplied_path(self):
        package = packaging.PackagedLifecycle().package(str(self.root))
        source = self.record("reopened")
        repository = self.root / "repository"
        repository.mkdir()
        inputs = self.root / "inputs.json"
        inputs.write_text(json.dumps({"inputs": [{"Input ID": "IN-001", "Input or artifact": "Current synthetic issue",
            "Source or path": "User", "Authority": "User", "Status": "Verified"}]}))

        def command(script, *arguments, expected=0):
            result = subprocess.run([sys.executable, str(package / "scripts" / script), *map(str, arguments)],
                                    cwd=package, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
            return json.loads(result.stdout)

        preflight = command("run_preflight.py")
        self.assertEqual(preflight["parent_context"]["provider_session"], str(source.resolve()))
        arguments = ("--execution-repository", repository, "--playbook", "feature_delivery", "--input-manifest", inputs)
        prepared = command("prepare_run.py", *arguments, "--work-item", "ITEM-1")
        bindings = json.loads(Path(prepared["role_binding_manifest"]).read_text())
        self.assertEqual(bindings["parent_context"]["turn_id"], TURN)
        self.assertEqual(bindings["parent_context"]["parent_thread_id"], PARENT)
        with source.open("a") as stream:
            stream.write(json.dumps({"timestamp": "2026-10-20T00:00:01Z", "type": "response_item", "payload": {
                "type": "custom_tool_call", "name": "exec", "input":
                'await tools.exec_command({cmd:"cat /repo/.codex/memories/MEMORY.md"})'}}) + "\n")
        rejected = command("run_preflight.py", expected=2)
        self.assertEqual(rejected["reason"], "parent_context_nonconformant")
        rejected = command("prepare_run.py", *arguments, "--work-item", "ITEM-2", expected=2)
        self.assertIn("parent_context_nonconformant", rejected["reason"])
        self.assertFalse((repository / ".thoughts/ITEM-2").exists())

    def test_shipped_entrypoints_block_missing_native_records_before_artifact_writes(self):
        package = packaging.PackagedLifecycle().package(str(self.root))
        repository = self.root / "repository"
        repository.mkdir()
        for script, arguments in (("run_preflight.py", ()), ("prepare_run.py", (
                "--execution-repository", str(repository), "--work-item", "ITEM-1", "--playbook", "techops_issue_remediation"))):
            result = subprocess.run([sys.executable, str(package / "scripts" / script), *arguments],
                                    cwd=package, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertEqual(json.loads(result.stdout)["reason"], "provider_current_session_unavailable")
        self.assertFalse((repository / ".thoughts").exists())

    def test_overlapping_fragments_retain_control_metadata_once_and_exclude_analysis(self):
        from scripts.provider_runtime import read_runtime_events
        earlier = self.record("earlier")
        def event(second, kind, **payload):
            return {"timestamp": f"2026-10-20T00:00:0{second}Z", "type": kind, "payload": payload}
        control = [event(1, "response_item", type="function_call", namespace="collaboration", name="spawn_agent",
                         call_id="spawn", arguments=json.dumps({"task_name": "worker", "message": "Current assignment"})),
                   event(1, "event_msg", item={"type": "SubAgentActivity", "kind": "started", "agent_path": "/root/worker",
                                               "agent_thread_id": "00000000-0000-0000-0000-000000000099"}),
                   event(2, "event_msg", item={"type": "SubAgentActivity", "kind": "completed", "agent_path": "/root/worker"}),
                   event(3, "response_item", type="function_call_output", call_id="unrelated-analysis",
                         output="PRIVATE_ANALYSIS_MUST_NOT_BE_IMPORTED")]
        with earlier.open("a") as stream:
            stream.write("\n".join(json.dumps(row) for row in control) + "\n")
        current = self.record("current", "2026-10-20T00:00:04Z")
        current_rows = [json.loads(line) for line in current.read_text().splitlines()]
        with current.open("w") as stream:
            stream.write("\n".join(json.dumps(row) for row in [current_rows[0], *control, *current_rows[1:],
                event(5, "response_item", type="function_call", namespace="collaboration", name="list_agents", call_id="inventory", arguments="{}"),
                event(6, "response_item", type="function_call_output", call_id="inventory", output=json.dumps({
                    "agents": [{"agent_name": "/root/worker", "agent_status": {"completed": "Done"}}]}))]) + "\n")
        ledger = read_runtime_events(current, PARENT, "2026-10-20T00:00:00Z", (earlier,))
        self.assertEqual(len(ledger["events"]), 1)
        self.assertEqual(len(ledger["inventories"]), 1)
        self.assertEqual(ledger["timing"]["open_worker_intervals"], 0)
        self.assertNotIn("PRIVATE_ANALYSIS_MUST_NOT_BE_IMPORTED", json.dumps(ledger))

    def test_a_new_fragment_without_turn_metadata_cannot_fall_back_to_an_old_turn(self):
        self.record("old")
        incomplete = self.sessions / ("new-" + PARENT + ".jsonl")
        incomplete.write_text(json.dumps({"timestamp": "2026-10-20T00:00:01Z", "type": "session_meta",
                                          "payload": {"id": PARENT}}) + "\n")
        with self.assertRaisesRegex(ValueError, "provider_current_turn_unavailable"):
            current_parent_session()

    def test_an_offline_packet_cannot_bypass_parent_binding_when_used_in_a_native_chat(self):
        from scripts.prepare_run import prepare_run
        from scripts.runtime_checks import prepared_package_errors
        source = self.record("current")
        repository = self.root / "repository"
        repository.mkdir()
        with patch.dict(os.environ, {"CODEX_THREAD_ID": "", "CODEX_SESSION_ID": ""}):
            prepared = prepare_run(repository, "ITEM-1", "techops_issue_remediation", None, False)
        root = Path(prepared["artifact_root"])
        before = Path(prepared["finalization_packet"]).read_bytes()
        self.assertTrue(any(error.startswith("parent_context_binding_required") for error in prepared_package_errors(root)))
        self.assertEqual(Path(prepared["finalization_packet"]).read_bytes(), before)
        continued = prepare_run(repository, "ITEM-1", "techops_issue_remediation", None, True)
        self.assertEqual(continued["run_id"], prepared["run_id"])
        self.assertEqual(prepared_package_errors(root), [])
        self.assertEqual(json.loads(Path(continued["role_binding_manifest"]).read_text())["parent_context"]["provider_session"], str(source.resolve()))

    def test_self_checks_isolate_and_restore_the_native_environment_even_on_failure(self):
        from scripts.self_check import run_self_check
        from types import SimpleNamespace
        before = {key: os.environ.get(key) for key in ("CODEX_THREAD_ID", "CODEX_SESSION_ID")}
        def scenario():
            self.assertNotIn("CODEX_THREAD_ID", os.environ)
            self.assertNotIn("CODEX_SESSION_ID", os.environ)
            os.environ["CODEX_SESSION_ID"] = "Synthetic identity must not leak"
            raise ValueError("Synthetic self-check failure")
        with patch("scripts.self_check.importlib.import_module", return_value=SimpleNamespace(self_test=scenario)):
            with self.assertRaisesRegex(ValueError, "Synthetic self-check failure"):
                run_self_check("synthetic")
        self.assertEqual({key: os.environ.get(key) for key in before}, before)

    def test_reopening_invalidates_old_source_for_acceptance_and_closure_until_continuation(self):
        from scripts.prepare_run import prepare_run
        from scripts.provider_runtime import validate_prepared_provider_source
        from scripts.runtime_checks import prepared_package_errors
        earlier = self.record("old")
        repository = self.root / "repository"
        repository.mkdir()
        run = prepare_run(repository, "ITEM-1", "techops_issue_remediation", None, False)
        bindings = json.loads(Path(run["role_binding_manifest"]).read_text())
        self.record("new", "2026-10-20T00:00:01Z", "00000000-0000-0000-0000-000000000003")
        self.assertTrue(any("provider_current_session_mismatch" in error
                            for error in prepared_package_errors(Path(run["artifact_root"]))))
        with self.assertRaisesRegex(ValueError, "provider_current_session_mismatch"):
            validate_prepared_provider_source(bindings, earlier, PARENT, run["runtime_evidence"]["run_started_at"])
        continued = prepare_run(repository, "ITEM-1", "techops_issue_remediation", None, True)
        self.assertEqual(continued["run_id"], run["run_id"])
        self.assertEqual(prepared_package_errors(Path(run["artifact_root"])), [])

    def test_reopening_cannot_clear_a_prior_parent_context_violation(self):
        self.continuation_context_violation(reopened=True)

    def test_a_later_turn_in_the_same_file_cannot_clear_a_prior_parent_context_violation(self):
        self.continuation_context_violation(reopened=False)

    def continuation_context_violation(self, *, reopened):
        from scripts.prepare_run import prepare_run
        earlier = self.record("earlier")
        repository = self.root / "repository"
        repository.mkdir()
        run = prepare_run(repository, "ITEM-1", "techops_issue_remediation", None, False)
        packet, bindings = Path(run["finalization_packet"]), Path(run["role_binding_manifest"])
        before = packet.read_bytes(), bindings.read_bytes()
        with earlier.open("a") as stream:
            stream.write(json.dumps({"timestamp": "2026-10-20T00:00:01Z", "type": "response_item", "payload": {
                "type": "custom_tool_call", "name": "exec", "input":
                'await tools.exec_command({cmd:"cat /repo/.codex/memories/MEMORY.md"})'}}) + "\n")
            if not reopened:
                stream.write(json.dumps({"timestamp": "2026-10-20T00:00:02Z", "type": "turn_context",
                    "payload": {"turn_id": "00000000-0000-0000-0000-000000000003"}}) + "\n")
        if reopened:
            self.record("current", "2026-10-20T00:00:02Z", "00000000-0000-0000-0000-000000000003")
        with self.assertRaisesRegex(ValueError, "continuation_parent_context_nonconformant"):
            prepare_run(repository, "ITEM-1", "techops_issue_remediation", None, True)
        self.assertEqual((packet.read_bytes(), bindings.read_bytes()), before)


if __name__ == "__main__":
    unittest.main()
