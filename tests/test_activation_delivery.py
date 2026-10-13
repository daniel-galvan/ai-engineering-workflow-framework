"""Replay shortened delivery, listing-only trace rejection and bounded activation repair."""

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts import prepare_run as prepare
from scripts import validate_worker_runtime as runtime


ARCHIVE = ".thoughts/ITEM-1/runs/prior/notes.md"
HANDLE = "/root/context"
CHILD = "00000000-0000-0000-0000-000000000002"
DISPATCH = "2026-10-12T20:00:00Z"


class ActivationDelivery(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        inputs = self.root / "inputs.json"
        inputs.write_text(json.dumps({"inputs": [{"Input ID": "IN-001", "Input or artifact": "Jira ITEM-1",
            "Source or path": "Current request", "Authority": "User", "Status": "Verified"}]}))
        self.run = prepare.prepare_run(self.root, "ITEM-1", "feature_delivery", None, False, input_manifest=inputs)
        self.artifacts = Path(self.run["artifact_root"])
        self.bundle = self.run["activation_packet_bundle"]

    def command(self, *args):
        return subprocess.run([sys.executable, str(runtime.ROOT / "scripts/validate_worker_runtime.py"),
                               *map(str, args)], capture_output=True, text=True)

    def test_compact_message_preserves_the_complete_hashed_contract(self):
        assignment = {"objective": "Reverify supplied findings only", "input_paths": []}
        source = self.root / "assignment.json"
        source.write_text(json.dumps(assignment))
        dispatch = self.artifacts / "activation_context_1.txt"
        args = ["--activation-packet-bundle", self.bundle["path"], "--expected-agent", "current_state_investigator",
                "--expected-bundle-sha256", self.bundle["sha256"], "--assignment", source, "--dispatch-file", dispatch]
        result = self.command(*args)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        receipt = json.loads(result.stdout)
        self.assertLess(len(receipt["activation_message"]), 1200)
        packet = json.loads(Path(self.bundle["path"]).read_text())["packets"]["current_state_investigator"]
        self.assertEqual(dispatch.read_text(), runtime.activation_message(packet, assignment))
        self.assertEqual(receipt["dispatch_file_sha256"], hashlib.sha256(dispatch.read_bytes()).hexdigest())
        self.assertIn(receipt["dispatch_file_sha256"], receipt["activation_message"])
        self.assertIn(packet["run_id"], receipt["activation_message"])
        outbound = self.root / "outbound.txt"
        outbound.write_text(receipt["activation_message"])
        self.assertEqual(self.command(*args, "--activation-message", outbound).returncode, 0)
        outbound.write_text("Shortened dispatch")
        rejected = self.command(*args, "--activation-message", outbound)
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("activation_message_mismatch", rejected.stdout)
        before = dispatch.read_bytes()
        source.write_text(json.dumps({"objective": "Different assignment"}))
        self.assertEqual(self.command(*args).returncode, 2)
        self.assertEqual(dispatch.read_bytes(), before)

    def test_dispatch_file_cannot_escape_the_active_root(self):
        packet = json.loads(Path(self.bundle["path"]).read_text())["packets"]["current_state_investigator"]
        with self.assertRaisesRegex(ValueError, "outside_current_run"):
            runtime.dispatch_message(packet, "Full instructions", self.root / "outside.txt")
        self.assertFalse((self.root / "outside.txt").exists())

    def trace(self, command, output):
        return {"spawn": {"observed_agent_role": "dependency_analyst"}, "tool_trace": [
            {"tool": "exec_command", "arguments": {"cmd": command}, "result": {"output": output}}]}

    def test_archive_names_from_listing_are_not_archive_content_reads(self):
        command = '/usr/local/bin/bash -lc "rg --files .thoughts/ITEM-1 | head -40; find . -name AGENTS.md -print"'
        trace = self.trace(command, ARCHIVE + "\nAGENTS.md\n")
        self.assertEqual(runtime.context_trace_errors(trace), [])
        legacy = {"tool_trace": [{"tool": "exec_command", "arguments": {
            "cmd": '/usr/local/bin/bash -lc "pwd && rg --files .thoughts/ITEM-1 | rg \'role|impact|plan\'"',
            "output": ARCHIVE}}]}
        self.assertEqual(runtime.context_trace_errors(legacy), [])
        for command in (f"cat {ARCHIVE}", f"rg approval {ARCHIVE}",
                        f"rg --files .thoughts/ITEM-1 | xargs cat", f"find . -exec cat {ARCHIVE} ';'"):
            with self.subTest(command=command):
                self.assertIn("forbidden_context_reference:archived_artifact",
                              runtime.context_trace_errors(self.trace(command, ARCHIVE)))
        self.assertIn("forbidden_context_reference:archived_artifact",
                      runtime.context_trace_errors({"tool_trace": [{"output": ARCHIVE}]}))
        unknown = self.trace("rg --files .", ARCHIVE)
        unknown["tool_trace"][0]["tool"] = "unknown_tool"
        self.assertIn("forbidden_context_reference:archived_artifact", runtime.context_trace_errors(unknown))

    def test_listing_exception_never_masks_memory_access(self):
        trace = self.trace("rg --files .", "/Users/example/.codex/memories/MEMORY.md")
        self.assertIn("forbidden_context_reference:memory_path", runtime.context_trace_errors(trace))
        trace = self.trace("rg --files .", "/Users/example/.codex/memories/notes.md")
        self.assertIn("forbidden_context_reference:memory_directory", runtime.context_trace_errors(trace))

    def test_call_id_listing_classification_does_not_hide_a_later_read(self):
        trace = {"tool_trace": [
            {"type": "function_call", "name": "exec_command", "call_id": "list", "arguments": '{"cmd":"rg --files ."}'},
            {"type": "function_call_output", "call_id": "list", "output": ARCHIVE},
        ]}
        self.assertEqual(runtime.context_trace_errors(trace), [])
        trace["tool_trace"].append({"type": "function_call_output", "call_id": "read", "output": ARCHIVE})
        self.assertIn("forbidden_context_reference:archived_artifact", runtime.context_trace_errors(trace))

    def rejected_trace(self):
        run_id = json.loads(Path(self.run["finalization_packet"]).read_text())["identity"]["Run ID"]
        trace = {"run_id": run_id, "thread_id": CHILD, "last_dispatch_at": DISPATCH,
            "spawn": {"agent": "current_state_investigator", "provider_handle": HANDLE, "thread_id": CHILD,
                      "activation_packet_delivered": False, "activation_message_conformance": "failed",
                      "expected_message_sha256": hashlib.sha256(b"Complete guarded message").hexdigest(),
                      "observed_message_sha256": hashlib.sha256(b"Shortened message").hexdigest()},
            "tool_trace": [], "status_observation": {
                "Provider handle": HANDLE, "Thread ID": CHILD, "Provider status": "completed",
                "Last dispatch at": DISPATCH, "Observed at": "2026-10-12T20:01:00Z", "Status source": "read_thread",
                "Latest turn started at": DISPATCH, "Latest turn completed at": "2026-10-12T20:00:30Z",
                "Latest turn status": "completed", "Thread status": "idle"},
            "events": [{"action": "fan_in", "provider_status": "completed", "guard_result": "blocked"}]}
        trace["audit"] = {"status": "rejected", "errors": runtime.trace_errors(trace, require_freshness=True)}
        path = self.artifacts / "context_rejected_trace.json"
        path.write_text(json.dumps(trace))
        return path, trace

    def test_one_completed_activation_repair_is_allowed_and_persisted(self):
        path, trace = self.rejected_trace()
        args = ["--transition", "replace", "--provider-status", "completed", "--rejected-trace", path,
                "--provider-handle", HANDLE, "--last-dispatch-at", DISPATCH]
        allowed = self.command(*args)
        self.assertEqual(allowed.returncode, 0, allowed.stdout + allowed.stderr)
        packet = json.loads(Path(self.run["finalization_packet"]).read_text())
        self.assertEqual(packet["activation_repairs"]["current_state_investigator"]["Attempt"], 1)
        self.assertEqual(json.loads(path.read_text()), trace)
        blocked = self.command(*args)
        self.assertEqual(blocked.returncode, 2)
        self.assertIn("activation_repair_limit_reached", blocked.stdout)

    def test_activation_repair_requires_real_mismatch_evidence_and_terminal_status(self):
        path, trace = self.rejected_trace()
        args = ["--transition", "replace", "--provider-status", "running", "--rejected-trace", path,
                "--provider-handle", HANDLE, "--last-dispatch-at", DISPATCH]
        self.assertEqual(self.command(*args).returncode, 2)
        trace["spawn"]["observed_message_sha256"] = trace["spawn"]["expected_message_sha256"]
        path.write_text(json.dumps(trace))
        args[3] = "completed"
        self.assertIn("activation_rejection_evidence_required", self.command(*args).stdout)
        self.assertNotIn("activation_repairs", json.loads(Path(self.run["finalization_packet"]).read_text()))


if __name__ == "__main__":
    unittest.main()
