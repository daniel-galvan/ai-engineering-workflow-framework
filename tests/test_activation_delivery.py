"""Replay shortened delivery, listing-only trace rejection and bounded activation repair."""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts import prepare_run as prepare
from scripts import validate_worker_runtime as runtime
from scripts.worker_runtime_evidence import export_worker_trace


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
        self.dispatch_number = 0

    def command(self, *args):
        return subprocess.run([sys.executable, str(runtime.ROOT / "scripts/validate_worker_runtime.py"),
                               *map(str, args)], capture_output=True, text=True)

    def test_every_playbook_delivers_bounded_repository_instruction_lookup(self):
        for index, playbook in enumerate(("feature_delivery", "techops_issue_remediation", "sentry_issue_remediation")):
            run = prepare.prepare_run(self.root, f"SCOPE-{index}", playbook, None, False,
                                      input_manifest=self.root / "inputs.json")
            packets = json.loads(Path(run["activation_packet_bundle"]["path"]).read_text())["packets"]
            for agent, packet in packets.items():
                with self.subTest(playbook=playbook, agent=agent):
                    policy = packet["repository_instructions"]
                    self.assertIn("ancestors up to the assigned repository root", policy)
                    self.assertIn("Do not recursively search parent directory trees", policy)
                    self.assertIn("Run filename discovery in a separate tool result from content reads or searches", policy)
                    self.assertIn("do not search unassigned runs/ archives", policy)
                    self.assertIn(policy, runtime.activation_message(packet, {"objective": "Inspect assigned source"}))

    def test_every_role_receives_coordinator_owned_handle_policy(self):
        for index, playbook in enumerate(("feature_delivery", "techops_issue_remediation", "sentry_issue_remediation")):
            run = prepare.prepare_run(self.root, f"IDENTITY-{index}", playbook, None, False,
                                      input_manifest=self.root / "inputs.json")
            packets = json.loads(Path(run["activation_packet_bundle"]["path"]).read_text())["packets"]
            for agent, packet in packets.items():
                with self.subTest(playbook=playbook, agent=agent):
                    message = runtime.activation_message(packet, {"objective": "Inspect assigned inputs"})
                    self.assertIn("Do not send a post-spawn message solely to supply that handle", message)
                    self.assertIn("A missing worker-authored handle is not a correction condition", message)
                    self.assertIn("explicit Sentry Fix Design handle-delivery protocol", message)
                    self.assertIn("Every later message remains a dispatch requiring fresh consumption evidence", message)

    def test_missing_instruction_input_is_rejected_before_dispatch(self):
        instructions = self.root / ".thoughts/AGENTS.md"
        source = self.root / "assignment.json"
        source.write_text(json.dumps({"objective": "Inspect current inputs", "input_paths": [str(instructions)]}))
        dispatch = self.artifacts / "activation_context.txt"
        args = ("--activation-packet-bundle", self.bundle["path"], "--expected-agent", "current_state_investigator",
                "--expected-bundle-sha256", self.bundle["sha256"], "--assignment", source, "--dispatch-file", dispatch)
        rejected = self.command(*args)
        self.assertEqual(rejected.returncode, 2, rejected.stdout + rejected.stderr)
        self.assertIn("assigned_instruction_file_missing", rejected.stdout)
        self.assertFalse(dispatch.exists())
        instructions.write_text("# Local instructions\n")
        self.assertEqual(self.command(*args).returncode, 0)

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
        self.assertEqual(receipt["launch_arguments"], {
            "fork_turns": "none", "model": packet["model"], "reasoning_effort": packet["effort"],
        })
        self.assertEqual(dispatch.read_text(), runtime.activation_message(packet, assignment))
        self.assertEqual(receipt["dispatch_file_sha256"], hashlib.sha256(dispatch.read_bytes()).hexdigest())
        self.assertIn(receipt["dispatch_file_sha256"], receipt["activation_message"])
        self.assertIn(packet["run_id"], receipt["activation_message"])
        self.assertIn("this bootstrap is self-contained", receipt["activation_message"])
        self.assertLess(receipt["activation_message"].index("do not search memory"),
                        receipt["activation_message"].index(packet["run_id"]))
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

    def instruction_trace(self, locator=ARCHIVE, authorization=None, objective="Verify current source findings"):
        bundle_path = Path(self.bundle["path"])
        bundle = json.loads(bundle_path.read_text())
        packet = bundle["packets"]["current_state_investigator"]
        if authorization:
            packet["run_input_manifest"]["inputs"].append(authorization)
        packet["run_input_manifest"]["inputs"].append({
            "Input ID": "REC-001", "Source or path": locator,
            "Expected use": "Preserve previous records without reading them"})
        bundle_path.write_text(json.dumps(bundle))
        digest = hashlib.sha256(bundle_path.read_bytes()).hexdigest()
        bindings_path = self.artifacts / "role_bindings.json"
        bindings = json.loads(bindings_path.read_text())
        bindings["activation_packet_bundle"]["sha256"] = digest
        bindings_path.write_text(json.dumps(bindings))
        assignment = self.root / "assignment.json"
        assignment.write_text(json.dumps({"objective": objective}))
        self.dispatch_number += 1
        dispatch = self.artifacts / f"activation_context_{self.dispatch_number}.txt"
        result = self.command("--activation-packet-bundle", bundle_path,
                              "--expected-agent", "current_state_investigator",
                              "--expected-bundle-sha256", digest, "--assignment", assignment,
                              "--dispatch-file", dispatch)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        receipt = json.loads(result.stdout)
        ledger = {"thread_mappings": {HANDLE: CHILD}, "events": [
            {"Provider handle": HANDLE, "Last dispatch at": DISPATCH, "Operation": "spawn_agent",
             "Launch": {"fork_turns": "none", "model": packet["model"], "reasoning_effort": packet["effort"]}}]}
        observation = {"Provider handle": HANDLE, "Thread ID": CHILD, "Provider status": "completed",
            "Last dispatch at": DISPATCH, "Observed at": "2026-10-12T20:02:00Z", "Status source": "read_thread",
            "Latest turn started at": DISPATCH, "Latest turn status": "completed", "Thread status": "idle"}
        source = self.root / "child.jsonl"
        rows = [{"timestamp": DISPATCH, "type": "session_meta", "payload": {"id": CHILD}},
            {"timestamp": "2026-10-12T20:01:00Z", "type": "response_item", "payload": {
                "type": "custom_tool_call", "name": "exec", "call_id": "read-contract",
                "input": f'const r = await tools.exec_command({{cmd:"cat {dispatch}"}}); text(r.output);'}},
            {"timestamp": "2026-10-12T20:01:01Z", "type": "response_item", "payload": {
                "type": "custom_tool_call_output", "call_id": "read-contract",
                "output": [{"type": "input_text", "text": dispatch.read_text()}]}}]
        source.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
        return export_worker_trace(ledger, source, "current_state_investigator", observation,
                                   run_id=packet["run_id"], artifact_root=self.artifacts)

    def test_full_dispatch_read_followed_by_checksum_authenticates_delivery(self):
        trace = self.instruction_trace()
        path = trace["spawn"]["dispatch_file"]
        trace["tool_trace"][0]["input"] = 'text(await tools.exec_command(' + json.dumps({
            "cmd": f"cat {path}; shasum -a 256 {path}"}) + '));'
        self.assertEqual(runtime.observed_dispatch_binding(trace, self.artifacts)["dispatch_file"], path)
        trace["tool_trace"][0]["input"] = trace["tool_trace"][0]["input"].replace("; shasum", " && shasum")
        self.assertEqual(runtime.observed_dispatch_binding(trace, self.artifacts)["dispatch_file"], path)
        trace["tool_trace"][1]["output"][0]["text"] = "Truncated output"
        self.assertEqual(runtime.observed_dispatch_binding(trace, self.artifacts), {})
        self.assertEqual(runtime._read_targets(f"cat {path}; shasum -a 256 other.txt"), [])
        self.assertEqual(runtime._read_targets(f"cat {path}; shasum -a 256 {path}; cat {ARCHIVE}"), [])

    def test_complete_chunked_dispatch_is_authenticated_without_exempting_extra_output(self):
        trace = self.instruction_trace()
        path = trace["spawn"]["dispatch_file"]
        content = Path(path).read_text()
        command = (f"python3 - <<'PY'\np={path!r}\ns=open(p).read()\n"
                   "for i in range(0,len(s),9000): print(f'---CHUNK {i}---\\n{s[i:i+9000]}')\nPY")
        trace["tool_trace"][0]["input"] = 'text(await tools.exec_command(' + json.dumps({"cmd": command}) + '));'
        output = "".join(f"---CHUNK {i}---\n{content[i:i+9000]}\n" for i in range(0, len(content), 9000))
        trace["tool_trace"][1]["output"][0]["text"] = output
        self.assertEqual(runtime.observed_dispatch_binding(trace, self.artifacts)["dispatch_file"], path)
        self.assertEqual(runtime.context_trace_errors(trace), [])
        trace["tool_trace"][1]["output"][0]["text"] = output + "\n" + ARCHIVE
        self.assertIn("forbidden_context_reference:archived_artifact", runtime.context_trace_errors(trace))
        for invalid in (output[:-20], output.replace("---CHUNK 9000---", "---CHUNK 9001---")):
            trace["tool_trace"][1]["output"][0]["text"] = invalid
            self.assertEqual(runtime.observed_dispatch_binding(trace, self.artifacts), {})
        trace["tool_trace"][1]["output"][0]["text"] = output
        trace["tool_trace"][1]["call_id"] = "wrong-call"
        self.assertEqual(runtime.observed_dispatch_binding(trace, self.artifacts), {})
        self.assertEqual(runtime._read_targets(command.replace("range(0,", "range(1,")), [])
        self.assertEqual(runtime._read_targets(command.replace("9000]}')", "9000]}'); print(open('extra').read())")), [])

    def test_file_count_and_listing_do_not_count_as_archive_reads(self):
        command = "wc -l -c .thoughts/ITEM-1/activation.txt && rg --files .thoughts/ITEM-1"
        trace = self.trace(command, "3 120 .thoughts/ITEM-1/activation.txt\n" + ARCHIVE)
        self.assertEqual(runtime.context_trace_errors(trace), [])
        trace = self.trace(command + "; cat " + ARCHIVE, ARCHIVE)
        self.assertIn("forbidden_context_reference:archived_artifact", runtime.context_trace_errors(trace))
        self.assertFalse(runtime._listing_command("wc --files0-from=paths && rg --files .thoughts/ITEM-1"))
        self.assertFalse(runtime._listing_command("wc -l -c " + ARCHIVE))

    def test_truncated_current_reads_with_final_listing_are_not_archived_content(self):
        trace = self.instruction_trace()
        source = self.artifacts / "current.json"
        source.write_text('{"current": true}\n')
        command = f"cat {source}; cat {source}; rg --files {self.artifacts}"
        trace["tool_trace"].extend([
            {"type": "custom_tool_call", "call_id": "mixed", "name": "exec",
             "input": 'text(await tools.exec_command(' + json.dumps({"cmd": command}) + '));'},
            {"type": "custom_tool_call_output", "call_id": "mixed", "output":
             "Warning: truncated output\n...\n" + ARCHIVE}])
        self.assertEqual(runtime.context_trace_errors(trace), [])
        trace["tool_trace"][-2]["input"] = trace["tool_trace"][-2]["input"].replace(
            f"cat {source}; rg", f"cat {ARCHIVE}; rg")
        self.assertIn("forbidden_context_reference:archived_artifact", runtime.context_trace_errors(trace))
        self.assertEqual(runtime._read_targets(f"cat {source}; echo hidden; rg --files ."), [])

    def test_planning_does_not_grant_permission_to_execute_product_checks(self):
        trace = self.instruction_trace(objective="Run focused product tests before returning")
        packet_path = Path(self.run["finalization_packet"])
        packet = json.loads(packet_path.read_text())
        packet["identity"]["Lifecycle"] = "planning"
        packet_path.write_text(json.dumps(packet))
        for command, operation in (("bazel test //product:test", "test_run"),
                                   ("bazel build //product:bin", "build_run"),
                                   ("go test ./...", "test_run"), ("npm run build", "build_run"),
                                   ("python3 -m unittest product_tests", "test_run")):
            with self.subTest(command=command):
                current = json.loads(json.dumps(trace))
                current["tool_trace"].append({"tool": "exec_command", "arguments": {"cmd": command}})
                self.assertIn("planning_operation_not_authorized:" + operation, runtime.trace_errors(current))
        malformed = json.loads(json.dumps(trace))
        malformed["tool_trace"].append({"tool": "exec_command", "arguments": {"cmd": None}})
        self.assertIn("planning_command_invalid", runtime.trace_errors(malformed))
        trace["tool_trace"].append({"tool": "exec_command", "arguments": {"cmd": "rg 'bazel test' source.md"}})
        self.assertFalse(any("planning_operation" in error for error in runtime.trace_errors(trace)))

    def test_input_manifest_rejects_malformed_operation_authorizations(self):
        path = self.root / "inputs.json"
        original = json.loads(path.read_text())
        for value in ("test_run", ["unknown_operation"], [False]):
            current = json.loads(json.dumps(original))
            current["inputs"][0]["Authorized operations"] = value
            path.write_text(json.dumps(current))
            with self.assertRaisesRegex(ValueError, "authorized_operations_invalid"):
                prepare.load_manifest(path, explicit=True)

    def test_explicit_test_permission_does_not_authorize_builds(self):
        authorization = {"Input ID": "AUTH-001", "Classification": "execution authorization",
                         "Authority": "User", "Status": "Approved", "Authorized operations": ["test_run"]}
        trace = self.instruction_trace(authorization=authorization)
        path = Path(self.run["finalization_packet"])
        packet = json.loads(path.read_text()); packet["identity"]["Lifecycle"] = "planning"
        path.write_text(json.dumps(packet))
        trace["tool_trace"].append({"tool": "exec_command", "arguments": {"cmd": "bazel test //product:test"}})
        self.assertFalse(any("planning_operation" in error for error in runtime.trace_errors(trace)))
        trace["tool_trace"][-1]["arguments"]["cmd"] = "bazel build //product:bin"
        self.assertIn("planning_operation_not_authorized:build_run", runtime.trace_errors(trace))

    def test_prepared_dispatch_export_and_audit_allow_preservation_metadata(self):
        trace = self.instruction_trace()
        self.assertEqual(trace["audit"], {"status": "passed", "errors": []})
        self.assertEqual(runtime.trace_errors(trace, require_freshness=True), [])
        trace["tool_trace"][1]["output"][0]["text"] = "provider warning\n" + trace["tool_trace"][1]["output"][0]["text"]
        self.assertEqual(runtime.context_trace_errors(trace), [])
        trace["tool_trace"][1]["output"][0]["text"] += "\ncat " + ARCHIVE
        self.assertIn("forbidden_context_reference:archived_artifact", runtime.context_trace_errors(trace))
        trace = self.instruction_trace()
        for operation in (f"cat {ARCHIVE}", f"*** Add File: {ARCHIVE}", f"*** Delete File: {ARCHIVE}"):
            with self.subTest(operation=operation):
                changed = json.loads(json.dumps(trace))
                changed["tool_trace"].append({"type": "custom_tool_call", "input": operation})
                self.assertIn("forbidden_context_reference:archived_artifact", runtime.context_trace_errors(changed))

    def test_verified_instruction_output_never_exempts_memory_references(self):
        trace = self.instruction_trace(ARCHIVE + " /Users/example/.codex/memories/notes.md")
        self.assertIn("forbidden_context_reference:memory_directory", trace["audit"]["errors"])

    def test_dispatch_metadata_exception_requires_exact_current_proof(self):
        trace = self.instruction_trace()
        for change in ("hash", "run", "content", "input", "extra-output", "bundle"):
            with self.subTest(change=change):
                changed = json.loads(json.dumps(trace))
                if change == "hash":
                    changed["spawn"]["dispatch_file_sha256"] = "0" * 64
                elif change == "run":
                    changed["run_id"] = "prior-run"
                elif change == "content":
                    changed["tool_trace"][1]["output"][0]["text"] = changed["tool_trace"][1]["output"][0]["text"].replace(
                        "Coordinator initialization: complete", "Coordinator initialization: altered", 1)
                elif change == "input":
                    changed["tool_trace"][0]["input"] = changed["tool_trace"][1]["output"][0]["text"]
                elif change == "extra-output":
                    changed["tool_trace"].append({"output": ARCHIVE})
                else:
                    Path(self.bundle["path"]).write_text("{}")
                self.assertIn("forbidden_context_reference:archived_artifact", runtime.context_trace_errors(changed))

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

    def test_recovery_preserves_packet_when_it_is_the_worker_output(self):
        path, trace = self.rejected_trace()
        packet_path = Path(self.run["finalization_packet"])
        saved = packet_path.read_bytes()
        bundle_path = Path(self.bundle["path"])
        bundle = json.loads(bundle_path.read_text())
        bundle["packets"]["current_state_investigator"]["worker_contract"]["output"] = str(packet_path)
        bundle_path.write_text(json.dumps(bundle))
        assignment = self.artifacts / "retry.json"
        assignment.write_text(json.dumps({"objective": "Read complete binding and preserve accepted findings"}))
        corrected = self.command("--activation-packet-bundle", os.path.relpath(bundle_path),
            "--expected-agent", "current_state_investigator",
            "--expected-bundle-sha256", hashlib.sha256(bundle_path.read_bytes()).hexdigest(),
            "--assignment", assignment, "--dispatch-file", self.artifacts / "retry.txt",
            "--provider-status", "completed", "--rejected-trace", path,
            "--provider-handle", HANDLE, "--last-dispatch-at", DISPATCH)
        self.assertEqual(corrected.returncode, 0, corrected.stdout + corrected.stderr)
        self.assertEqual(packet_path.with_name("finalization_packet.rejected.json").read_bytes(), saved)
        current = json.loads(packet_path.read_text())
        self.assertIn("current_state_investigator", current.pop("activation_repairs"))
        self.assertEqual(current, json.loads(saved))
        self.assertEqual(json.loads(path.read_text()), trace)

    def test_one_completed_activation_repair_is_allowed_and_persisted(self):
        path, trace = self.rejected_trace()
        recovery = ["--provider-status", "completed", "--rejected-trace", path,
                    "--provider-handle", HANDLE, "--last-dispatch-at", DISPATCH]
        allowed = self.command("--transition", "replace", *recovery)
        self.assertEqual(allowed.returncode, 0, allowed.stdout + allowed.stderr)
        self.assertNotIn("activation_repairs", json.loads(Path(self.run["finalization_packet"]).read_text()))
        assignment = self.artifacts / "retry.json"
        assignment.write_text(json.dumps({"objective": "Read complete guarded instructions"}))
        bundle = self.run["activation_packet_bundle"]
        activation = ["--activation-packet-bundle", bundle["path"], "--expected-agent", "current_state_investigator",
            "--expected-bundle-sha256", bundle["sha256"], "--assignment", assignment,
            "--dispatch-file", self.artifacts / "retry.txt", *recovery]
        before = Path(self.run["finalization_packet"]).read_bytes()
        assignment.write_text(json.dumps({"objective": "Read complete guarded instructions",
                                         "input_paths": [str(self.artifacts.parent / "AGENTS.md")]}))
        rejected = self.command(*activation)
        self.assertEqual(rejected.returncode, 2, rejected.stdout + rejected.stderr)
        self.assertIn("assigned_instruction_file_missing", rejected.stdout)
        self.assertEqual(Path(self.run["finalization_packet"]).read_bytes(), before)
        self.assertFalse((self.artifacts / "retry.txt").exists())
        assignment.write_text(json.dumps({"objective": "Read complete guarded instructions"}))
        corrected = self.command(*activation)
        self.assertEqual(corrected.returncode, 0, corrected.stdout + corrected.stderr)
        packet = json.loads(Path(self.run["finalization_packet"]).read_text())
        self.assertEqual(packet["activation_repairs"]["current_state_investigator"]["Attempt"], 1)
        self.assertEqual(json.loads(path.read_text()), trace)
        blocked = self.command(*activation)
        self.assertEqual(blocked.returncode, 2)
        self.assertIn("activation_repair_limit_reached", blocked.stdout)

    def test_rejected_activation_can_use_its_recorded_expected_role(self):
        path, trace = self.rejected_trace()
        trace["spawn"]["expected_agent"] = trace["spawn"].pop("agent")
        trace["audit"]["errors"] = runtime.trace_errors(trace, require_freshness=True)
        path.write_text(json.dumps(trace))
        allowed = self.command("--transition", "replace", "--provider-status", "completed",
            "--rejected-trace", path, "--provider-handle", HANDLE, "--last-dispatch-at", DISPATCH)
        self.assertEqual(allowed.returncode, 0, allowed.stdout + allowed.stderr)
        self.assertNotIn("activation_repairs", json.loads(Path(self.run["finalization_packet"]).read_text()))

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
