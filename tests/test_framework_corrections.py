"""Regressions for evidence preservation, recovery identity and runtime auditing."""

import hashlib
import json
import subprocess
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import finalize_work_record as finalizer
from scripts import prepare_run as prepare
from scripts import run_preflight as preflight
from scripts import validate_worker_runtime as runtime
from scripts.merge_techops_result import merge_result
from scripts.worker_runtime_evidence import read_runtime_events


class FrameworkCorrections(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.repository = Path(temporary.name)
        self.inputs = self.repository / "inputs.json"
        self.inputs.write_text(json.dumps({"inputs": [{
            "Input ID": "IN-001", "Input or artifact": "Jira ITEM-1",
            "Source or path": "Current request", "Authority": "User", "Status": "Verified",
        }]}))
        self.run = prepare.prepare_run(self.repository, "ITEM-1", "feature_delivery", None, False,
                                       input_manifest=self.inputs)
        self.root = Path(self.run["artifact_root"])
        self.packet_path = Path(self.run["finalization_packet"])
        self.packet = json.loads(self.packet_path.read_text())
        template = json.loads(finalizer.PACKET_TEMPLATE.read_text())
        self.evidence = {**dict.fromkeys(template["evidence"][0], "Observed"), "Evidence ID": "E-FC-001"}
        self.result = {"run_id": self.packet["identity"]["Run ID"], "worker_result": {
            **dict.fromkeys(template["worker_results"][0], "Recorded"),
            "Worker": "feature-context", "Outcome": "complete"}, "evidence": [self.evidence]}
        self.source = Path(self.run["worker_contracts"]["current_state_investigator"]["result"])

    def merge(self):
        self.source.write_text(json.dumps(self.result))
        merge_result(self.packet_path, "current_state_investigator")

    def test_empty_result_preserves_evidence_and_conflicts_do_not_mutate_packet(self):
        self.merge()
        saved = self.packet_path.read_bytes()
        self.result["evidence"] = []
        self.merge()
        self.assertEqual(saved, self.packet_path.read_bytes())
        self.result["evidence"] = [{**self.evidence, "Source": "Changed"}]
        with self.assertRaisesRegex(ValueError, "row_conflict"):
            self.merge()
        self.assertEqual(saved, self.packet_path.read_bytes())

    def test_bad_types_and_dangling_references_fail_before_mutation(self):
        saved = self.packet_path.read_bytes()
        for value, reason in ((["E-FC-001"], "schema_invalid"), ("E-FC-404", "reference_unresolved")):
            self.result["worker_result"]["Evidence / claim refs"] = value
            with self.assertRaisesRegex(ValueError, reason):
                self.merge()
            self.assertEqual(saved, self.packet_path.read_bytes())
        self.result["worker_result"]["Evidence / claim refs"] = "E-FC-001"
        self.merge()
        self.assertEqual(finalizer._shape_errors(json.loads(self.packet_path.read_text()),
                                                json.loads(finalizer.PACKET_TEMPLATE.read_text()), "packet"), [])

    def test_wrong_framework_checkout_is_rejected_before_any_write(self):
        path = self.root / "role_bindings.json"
        bindings = json.loads(path.read_text())
        bindings["framework_package"]["root"] = str(self.repository / "another-framework")
        path.write_text(json.dumps(bindings))
        saved = self.packet_path.read_bytes()
        with self.assertRaisesRegex(ValueError, "prepared_framework_package_mismatch"):
            self.merge()
        with self.assertRaisesRegex(ValueError, "prepared_framework_package_mismatch"):
            finalizer.finalize(self.packet_path, self.root / "absent.json", self.root / "work_record.md")
        bundle = self.run["activation_packet_bundle"]
        self.assertTrue(any("prepared_framework_package_mismatch" in error for error in
                            runtime.activation_packet_errors(Path(bundle["path"]),
                                                             "current_state_investigator", bundle["sha256"])))
        self.assertEqual(saved, self.packet_path.read_bytes())

    def test_recovery_uses_frozen_failure_proof_after_packet_reconciliation(self):
        self.packet["identity"].update({"State": "in_progress", "Requested profile": "standard"})
        self.packet_path.write_text(json.dumps(self.packet))
        (self.root / "runtime_closure.json").write_text(json.dumps({"runtime_closure": [{
            "Run or stage": "planning", "Receipt owner": "Coordinator", "Completed worker handles": "None",
            "Runtime status": "Released", "Remaining active handles": "None",
            "Closure evidence or blocker": "No worker was started"}]}))
        result = subprocess.run([sys.executable, str(finalizer.ROOT / "scripts/finalize_work_record.py"),
                                 "--packet", str(self.packet_path), "--workflow-failure", "contract_failure"],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        receipt = json.loads((self.root / "finalization_failure.json").read_text())
        snapshot = Path(receipt["packet_snapshot"])
        saved = snapshot.read_bytes()
        self.packet["work_item"]["Title"] = "Reconciled title"
        self.packet_path.write_text(json.dumps(self.packet))
        recovered = prepare.prepare_run(self.repository, "ITEM-1", "feature_delivery", None, True,
            input_manifest=self.inputs, planning_recovery=True, approval_reference="User requests recovery")
        self.assertNotEqual(recovered["run_id"], self.packet["identity"]["Run ID"])
        self.assertEqual(snapshot.read_bytes(), saved)

    def dispatch_trace(self, assigned):
        packet = json.loads(Path(self.run["activation_packet_bundle"]["path"]).read_text())["packets"][
            "current_state_investigator"]
        path = self.root / "activation_context.txt"
        message = runtime.activation_message(packet, {"objective": "Read assigned inputs", "input_paths": assigned})
        runtime.dispatch_message(packet, message, path)
        return {"run_id": packet["run_id"], "spawn": {"agent": packet["agent"], "dispatch_file": str(path),
                "dispatch_file_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}, "tool_trace": []}

    def test_assigned_archive_read_is_allowed_but_writes_and_unassigned_backup_reads_fail(self):
        archive = str(self.repository / ".thoughts/2967_v1/decision.md")
        trace = self.dispatch_trace([archive])
        for command, allowed in ((f"cat {archive}", True), (f"rm {archive}", False),
                                 (f"cat {archive.replace('decision.md', 'unassigned.md')}", False),
                                 (f"cat {archive} {archive}.bak", False)):
            trace["tool_trace"] = [{"tool": "exec_command", "arguments": {"cmd": command}}]
            self.assertEqual(runtime.context_trace_errors(trace) == [], allowed, command)

    def test_rebinding_keeps_immutable_dispatch_proof_valid(self):
        old_cache = self.repository / "old-cache"
        new_cache = self.repository / "new-cache"
        old_cache.mkdir()
        new_cache.mkdir()
        for cache in (old_cache, new_cache):
            shutil.copyfile(prepare.BUNDLED_AGENTS / "current_state_investigator.toml",
                            cache / "current_state_investigator.toml")
        self.run = prepare.prepare_run(self.repository, "ITEM-1", "feature_delivery", old_cache, True,
                                       input_manifest=self.inputs)
        trace = self.dispatch_trace([])
        content = Path(trace["spawn"]["dispatch_file"]).read_text()
        shutil.rmtree(old_cache)
        rebound = prepare.prepare_run(self.repository, "ITEM-1", "feature_delivery", new_cache, True,
                                      input_manifest=self.inputs)
        self.assertNotEqual(self.run["activation_packet_bundle"]["sha256"],
                            rebound["activation_packet_bundle"]["sha256"])
        self.assertEqual(runtime._verified_dispatch_content(trace), content)

    def test_archive_deduplicates_bytes_and_retry_preserves_the_existing_snapshot(self):
        history = self.root / "history"
        history.mkdir()
        for name in ("read-a.json", "read-b.json", "read-c.json"):
            (history / name).write_bytes(b"Identical historical read\n")
        archive = prepare._archive_recovery(self.root, self.run["run_id"])
        manifest = json.loads((archive / "archive_manifest.json").read_text())
        rows = [row for row in manifest["files"] if row["path"].startswith("history/")]
        self.assertEqual(len(rows), 3)
        self.assertEqual(len({row["snapshot"] for row in rows}), 1)
        self.assertFalse((archive / "history").exists())
        self.assertEqual((archive / rows[0]["snapshot"]).read_bytes(), b"Identical historical read\n")
        saved = (archive / "archive_manifest.json").read_bytes()
        self.assertEqual(prepare._archive_recovery(self.root, self.run["run_id"]), archive)
        (history / "read-a.json").write_text("Changed\n")
        with self.assertRaisesRegex(ValueError, "prior_run_archive_exists"):
            prepare._archive_recovery(self.root, self.run["run_id"])
        self.assertEqual((archive / "archive_manifest.json").read_bytes(), saved)

    def test_terminal_failure_prevents_another_worker_dispatch(self):
        (self.root / "finalization_failure.json").write_text(json.dumps({
            "status": "failed", "stage": "workflow", "run_id": self.run["run_id"]}))
        bundle = self.run["activation_packet_bundle"]
        self.assertIn("worker_activation_requires_planning_recovery", runtime.activation_packet_errors(
            Path(bundle["path"]), "current_state_investigator", bundle["sha256"]))

    def test_static_package_defect_fails_preflight_before_work(self):
        (self.repository / ".codex-plugin").mkdir()
        (self.repository / ".codex-plugin/plugin.json").write_text('{"version":"1.0.0"}')
        (self.repository / "PLAYBOOK_CATALOG.md").write_text("# Catalog\n")
        (self.repository / "scripts").mkdir()
        (self.repository / "scripts/validate_library.py").write_text('raise SystemExit("Bad shipped contract")\n')
        with patch.object(preflight, "_git", side_effect=lambda root, *args: (
                0, "a" * 40 if args[0] == "rev-parse" else "", "")), \
                patch.object(preflight, "_reused_plugin_build_identity", return_value=(False, "1.0.0")):
            result = preflight.preflight(self.repository)
        self.assertEqual(result["reason"], "framework_package_validation_failed")
        self.assertIn("Bad shipped contract", result["detail"])

    def test_assigned_provider_read_output_keeps_authorization(self):
        archive = str(self.repository / ".thoughts/2967_v1/decision.md")
        trace = self.dispatch_trace([archive])
        trace["tool_trace"] = [
            {"type": "function_call", "name": "exec_command", "call_id": "read-1",
             "arguments": json.dumps({"cmd": "cat " + archive})},
            {"type": "function_call_output", "call_id": "read-1", "output": archive},
        ]
        self.assertEqual(runtime.context_trace_errors(trace), [])
        trace["tool_trace"][0]["arguments"] = json.dumps({"cmd": "rm " + archive})
        self.assertIn("forbidden_context_reference:archived_artifact", runtime.context_trace_errors(trace))

    def test_renamed_backup_is_rejected_without_a_verified_dispatch(self):
        trace = {"tool_trace": [{"tool": "exec_command", "arguments": {
            "cmd": "cat /repo/.thoughts/2967_v1/decision.md"}}]}
        self.assertIn("forbidden_context_reference:archived_artifact", runtime.context_trace_errors(trace))

    def test_authorized_read_wrapper_cannot_hide_a_write(self):
        archive = str(self.repository / ".thoughts/2967_v1/decision.md")
        trace = self.dispatch_trace([archive])
        read = 'await tools.exec_command(' + json.dumps({"cmd": "cat " + archive}) + ')'
        trace["tool_trace"] = [{"type": "custom_tool_call", "input": read}]
        self.assertEqual(runtime.context_trace_errors(trace), [])
        trace["tool_trace"][0]["input"] = read + '; await tools.apply_patch("Delete ' + archive + '")'
        self.assertIn("forbidden_context_reference:archived_artifact", runtime.context_trace_errors(trace))

    def test_tampered_terminal_snapshot_cannot_authorize_recovery(self):
        self.packet["identity"].update({"State": "in_progress", "Requested profile": "standard"})
        self.packet_path.write_text(json.dumps(self.packet))
        frozen = finalizer.snapshot_bytes(self.packet)
        snapshot = self.root / finalizer.snapshot_name(self.packet)
        snapshot.write_bytes(frozen + b" ")
        (self.root / "runtime_closure.json").write_text('{}')
        (self.root / "finalization_failure.json").write_text(json.dumps({
            "status": "failed", "stage": "workflow", "run_id": self.run["run_id"],
            "packet_snapshot": str(snapshot), "snapshot_sha256": hashlib.sha256(frozen).hexdigest()}))
        saved = self.packet_path.read_bytes()
        with self.assertRaisesRegex(ValueError, "requires_terminal_invocation"):
            prepare.prepare_run(self.repository, "ITEM-1", "feature_delivery", None, True,
                input_manifest=self.inputs, planning_recovery=True, approval_reference="User requests recovery")
        self.assertEqual(self.packet_path.read_bytes(), saved)

    def test_failed_followup_is_not_counted_as_worker_execution(self):
        parent, child = "00000000-0000-0000-0000-000000000001", "00000000-0000-0000-0000-000000000002"
        def event(second, kind, **payload):
            return {"timestamp": f"2026-10-12T00:00:{second:02d}Z", "type": kind, "payload": payload}
        rows = [event(0, "session_meta", id=parent), event(1, "event_msg", item={
            "type": "SubAgentActivity", "kind": "started", "agent_path": "/root/worker", "agent_thread_id": child}),
            event(3, "event_msg", item={"type": "SubAgentActivity", "kind": "completed", "agent_path": "/root/worker"}),
            event(5, "response_item", type="function_call", namespace="collaboration", name="followup_task",
                  call_id="failed", arguments=json.dumps({"target": "/root/worker"})),
            event(6, "response_item", type="function_call_output", call_id="failed", output="Worker unavailable"),
            event(9, "response_item", type="message", content=[])]
        source = self.repository / "provider.jsonl"
        source.write_text("".join(json.dumps(row) + "\n" for row in rows))
        ledger = read_runtime_events(source, parent, "2026-10-12T00:00:00Z")
        self.assertEqual(ledger["timing"]["worker_active_seconds"], 2)
        self.assertEqual(len(ledger["failed_dispatches"]), 1)
        self.assertEqual(ledger["events"], [])

    def test_reused_worker_time_includes_followup_without_a_second_spawn(self):
        parent, child = "00000000-0000-0000-0000-000000000001", "00000000-0000-0000-0000-000000000002"
        def event(second, kind, **payload):
            return {"timestamp": f"2026-10-12T00:00:{second:02d}Z", "type": kind, "payload": payload}
        rows = [event(0, "session_meta", id=parent), event(1, "event_msg", item={
            "type": "SubAgentActivity", "kind": "started", "agent_path": "/root/worker", "agent_thread_id": child}),
            event(3, "event_msg", item={"type": "SubAgentActivity", "kind": "completed", "agent_path": "/root/worker"}),
            event(5, "response_item", type="function_call", namespace="collaboration", name="followup_task",
                  arguments=json.dumps({"target": "/root/worker"})),
            event(9, "event_msg", item={"type": "SubAgentActivity", "kind": "completed", "agent_path": "/root/worker"})]
        source = self.repository / "provider.jsonl"
        source.write_text("".join(json.dumps(row) + "\n" for row in rows))
        ledger = read_runtime_events(source, parent, "2026-10-12T00:00:00Z")
        self.assertEqual(ledger["timing"]["worker_active_seconds"], 6)
        self.assertEqual(ledger["timing"]["no_worker_active_seconds"], 3)
