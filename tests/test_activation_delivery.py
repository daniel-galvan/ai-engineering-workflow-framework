"""Replay shortened delivery, listing-only trace rejection and bounded activation repair."""

import hashlib
import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import prepare_run as prepare
from scripts import runtime_checks
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
                    self.assertIn(f"Keep every run-created file, including scratch drafts and temporary output, inside {run['artifact_root']}", policy)
                    self.assertIn("do not write them to a separate temporary directory", policy)
                    self.assertIn("ancestors up to the assigned repository root", policy)
                    self.assertIn("Do not recursively search parent directory trees", policy)
                    self.assertIn("Run filename discovery in a separate tool result from content reads or searches", policy)
                    self.assertIn("do not search unassigned runs/ archives", policy)
                    self.assertIn(policy, runtime.activation_message(packet, {"objective": "Inspect assigned source"}))

    def test_worker_instructions_separate_source_checkout_from_artifact_repository(self):
        worktree = self.root / "linked-worktree"
        worktree.mkdir()
        with patch.object(prepare, "resolve_repository_paths", return_value=(self.root, worktree)):
            run = prepare.prepare_run(worktree, "SEPARATE-1", "techops_issue_remediation", None, False,
                                      input_manifest=self.root / "inputs.json")
        packets = json.loads(Path(run["activation_packet_bundle"]["path"]).read_text())["packets"]
        for packet in packets.values():
            instructions = packet["repository_instructions"]
            self.assertIn(f"Use {worktree} as the source checkout", instructions)
            self.assertIn(f"Use {self.root / '.thoughts' / 'SEPARATE-1'} for current-run workflow artifacts", instructions)
            self.assertIn("do not use it as the source checkout when paths differ", instructions)

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

    def test_planning_documenter_receives_auditable_artifact_write_policy(self):
        packet = json.loads(Path(self.bundle["path"]).read_text())["packets"]["documenter"]
        message = runtime.activation_message(packet, {"objective": "Write the assigned planning artifacts"})
        self.assertIn("For planning artifact writes, use apply_patch only", message)
        self.assertIn("Do not use embedded Python or shell file writes", message)
        self.assertIn("append your own populated `handoff` row to both", message)
        self.assertIn("selected playbook, closest alternative, and rationale", message)

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
        self.assertLess(len(receipt["activation_message"]), len(dispatch.read_text()))
        packet = json.loads(Path(self.bundle["path"]).read_text())["packets"]["current_state_investigator"]
        self.assertEqual(receipt["launch_arguments"], {
            "fork_turns": "none", "model": packet["model"], "reasoning_effort": packet["effort"],
        })
        self.assertEqual(dispatch.read_text(), runtime.activation_message(packet, assignment))
        self.assertEqual(receipt["dispatch_file_sha256"], hashlib.sha256(dispatch.read_bytes()).hexdigest())
        self.assertIn(receipt["dispatch_file_sha256"], receipt["activation_message"])
        self.assertIn(packet["run_id"], receipt["activation_message"])
        self.assertIn("this bootstrap is self-contained", receipt["activation_message"])
        self.assertLess(receipt["activation_message"].index("Use only this chat and current-run artifacts"),
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
            "Latest turn started at": "2026-10-12T20:01:02Z", "Latest turn completed at": "2026-10-12T20:01:03Z",
            "Latest turn status": "completed", "Thread status": "idle"}
        source = self.root / "child.jsonl"
        rows = [{"timestamp": DISPATCH, "type": "session_meta", "payload": {"id": CHILD}},
            {"timestamp": "2026-10-12T20:01:00Z", "type": "response_item", "payload": {
                "type": "custom_tool_call", "name": "exec", "call_id": "read-contract",
                "input": f'const r = await tools.exec_command({{cmd:"cat {dispatch}"}}); text(r.output);'}},
            {"timestamp": "2026-10-12T20:01:01Z", "type": "response_item", "payload": {
                "type": "custom_tool_call_output", "call_id": "read-contract",
                "output": [{"type": "input_text", "text": dispatch.read_text()}]}}]
        contract = packet.get("worker_contract", {})
        if contract.get("result_hash_required"):
            fields = json.loads((prepare.ROOT / "templates/finalization_packet.json").read_text())["worker_results"][0]
            result = {"run_id": packet["run_id"], "worker_result": {
                **dict.fromkeys(fields, "Synthetic evidence blocker"),
                "Worker": "feature-context", "Outcome": "blocked"},
                "evidence": [], "claims": [], "decisions": [], "actions": []}
            if contract.get("planning_disposition_required"):
                result.update(plan_readiness="awaiting_input", implementation_plan_action="omit")
            response = {"output": "Synthetic worker response.", "result": result}
            if contract.get("asset_inventory"):
                response["asset_manifest"] = {}
            rows.extend([
                {"timestamp": "2026-10-12T20:01:02Z", "type": "turn_context", "payload": {
                    "turn_id": "00000000-0000-0000-0000-000000000004", "model": packet["model"],
                    "effort": packet["effort"]}},
                {"timestamp": "2026-10-12T20:01:03Z", "type": "response_item", "payload": {
                    "type": "message", "role": "assistant", "phase": "final_answer",
                    "content": [{"type": "output_text", "text": json.dumps(response)}]}}])
        source.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
        return export_worker_trace(ledger, source, "current_state_investigator", observation,
                                   run_id=packet["run_id"], artifact_root=self.artifacts)

    def test_bootstrap_prescribes_a_separate_literal_instruction_read(self):
        path = self.artifacts / "activation instructions.txt"
        notice = runtime.dispatch_notice({"required_prefix": "Coordinator initialization: complete",
            "agent": "current_state_investigator", "model": "model", "effort": "high", "run_id": "ITEM-1"},
            "instructions", path)
        command = notice.split("Read it with this separate literal command: ", 1)[1].split("\n", 1)[0]
        self.assertEqual(runtime_checks._read_targets(command), [str(path.resolve())])
        self.assertIn("Use only this chat and current-run artifacts", notice)
        self.assertNotIn("Follow higher-priority host memory instructions", notice)
        self.assertIn("Do not search the artifact directory", notice)
        self.assertIn("Use separate tool calls for verification and the complete instruction read", notice)
        self.assertIn("max_output_tokens to at least 12; truncated output is not delivery", notice)
        large = runtime.dispatch_notice({"required_prefix": "Coordinator initialization: complete",
            "agent": "current_state_investigator", "model": "model", "effort": "high", "run_id": "ITEM-1"},
            "x" * 13001, path)
        commands = large.split("do not omit or change any part:\n", 1)[1].split("\nUse separate tool calls", 1)[0].splitlines()
        self.assertEqual([runtime_checks._dispatch_segment(command)[1:] for command in commands],
                         [(0, 6000), (6000, 12000), (12000, 13001)])
        self.assertTrue(all(runtime_checks._read_targets(command) == [str(path.resolve())] for command in commands))
        self.assertTrue(all("'\"'\"'" not in command for command in commands))
        path.write_text("x" * 13001)
        actual = "".join(subprocess.run(shlex.split(command), check=True, capture_output=True, text=True).stdout
                         for command in commands)
        self.assertEqual(actual, path.read_text())
        forged = shlex.split(commands[0])
        forged[0] = "/tmp/python3"
        self.assertIsNone(runtime_checks._dispatch_segment(shlex.join(forged)))

    def test_live_opaque_dispatch_requires_paired_instruction_read_before_inventory(self):
        trace = self.instruction_trace()
        role = "current_state_investigator"
        event = {"Thread ID": CHILD, "Last dispatch at": DISPATCH}
        sessions = self.root / "codex" / "sessions"
        sessions.mkdir(parents=True)
        source = sessions / ("rollout-" + CHILD + ".jsonl")
        rows = [{"timestamp": DISPATCH, "type": "session_meta", "payload": {"id": CHILD}},
                {"timestamp": "2026-10-12T20:01:00Z", "type": "response_item", "payload": trace["tool_trace"][0]},
                {"timestamp": "2026-10-12T20:01:01Z", "type": "response_item", "payload": trace["tool_trace"][1]}]
        def write_rows():
            source.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
        write_rows()
        with patch.dict(os.environ, {"CODEX_HOME": str(sessions.parent)}):
            proof = runtime_checks.live_dispatch_binding(event, role, self.artifacts, trace["run_id"],
                                                         "2026-10-12T20:02:00Z")
            self.assertEqual(proof.get("dispatch_file"), trace["spawn"]["dispatch_file"])
            self.assertEqual(runtime_checks.live_dispatch_binding(event, role, self.artifacts, trace["run_id"],
                                                                 "2026-10-12T20:01:00Z"), {})
            self.assertEqual(runtime_checks.live_dispatch_binding(event, "reviewer", self.artifacts, trace["run_id"],
                                                                 "2026-10-12T20:02:00Z"), {})
            rows[2]["payload"] = {**rows[2]["payload"], "output": "truncated"}
            write_rows()
            self.assertEqual(runtime_checks.live_dispatch_binding(event, role, self.artifacts, trace["run_id"],
                                                                 "2026-10-12T20:02:00Z"), {})

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

    def test_separate_dispatch_segments_require_complete_ordered_paired_outputs(self):
        trace = self.instruction_trace()
        path = trace["spawn"]["dispatch_file"]
        content = Path(path).read_text()
        rows = []
        for index, start in enumerate(range(0, len(content), 900)):
            end = min(start + 900, len(content))
            code = f"print(open({path!r}).read()[{start}:{end}],end='')"
            command = shlex.join(["python3", "-c", code])
            call = f"part-{index}"
            rows.extend([{"type": "custom_tool_call", "name": "exec", "call_id": call,
                          "input": 'text(await tools.exec_command(' + json.dumps({"cmd": command}) + '));'},
                         {"type": "custom_tool_call_output", "call_id": call,
                          "output": [{"type": "input_text", "text": content[start:end]}]}])
        trace["tool_trace"] = rows
        self.assertEqual(runtime.observed_dispatch_binding(trace, self.artifacts)["dispatch_file"], path)
        self.assertEqual(runtime.context_trace_errors(trace), [])
        sessions = self.root / "codex-segmented" / "sessions"
        sessions.mkdir(parents=True)
        source = sessions / ("rollout-" + CHILD + ".jsonl")
        native_rows = [{"timestamp": DISPATCH, "type": "session_meta", "payload": {"id": CHILD}}]
        native_rows.extend({"timestamp": "2026-10-12T20:01:00Z", "type": "response_item", "payload": row} for row in rows)
        source.write_text("\n".join(json.dumps(row) for row in native_rows) + "\n")
        with patch.dict(os.environ, {"CODEX_HOME": str(sessions.parent)}):
            proof = runtime_checks.live_dispatch_binding({"Thread ID": CHILD, "Last dispatch at": DISPATCH},
                "current_state_investigator", self.artifacts, trace["run_id"], "2026-10-12T20:02:00Z")
            self.assertEqual(proof.get("dispatch_file"), path)
        for mutate in ("missing", "reordered", "truncated", "wrong_pair", "duplicate_id"):
            invalid = json.loads(json.dumps(trace))
            if mutate == "missing": invalid["tool_trace"] = invalid["tool_trace"][:-2]
            if mutate == "reordered": invalid["tool_trace"] = invalid["tool_trace"][2:4] + invalid["tool_trace"][:2] + invalid["tool_trace"][4:]
            if mutate == "truncated": invalid["tool_trace"][1]["output"][0]["text"] = "Warning: truncated output"
            if mutate == "wrong_pair": invalid["tool_trace"][1]["call_id"] = "other"
            if mutate == "duplicate_id": invalid["tool_trace"][2]["call_id"] = invalid["tool_trace"][0]["call_id"]
            self.assertEqual(runtime.observed_dispatch_binding(invalid, self.artifacts), {}, mutate)
        trace["tool_trace"][1]["output"][0]["text"] += "\n" + ARCHIVE
        self.assertIn("forbidden_context_reference:archived_artifact", runtime.context_trace_errors(trace))

    def test_literal_command_loop_requires_complete_ordered_instruction_delivery(self):
        trace = self.instruction_trace()
        path = trace["spawn"]["dispatch_file"]
        content = Path(path).read_text()
        commands, output = [], []
        for start in range(0, len(content), 900):
            end = min(start + 900, len(content))
            commands.append(shlex.join(["python3", "-c", f"print(open({path!r}).read()[{start}:{end}],end='')"]))
            output.append({"type": "input_text", "text": content[start:end]})
        source = ("const cmds = " + json.dumps(commands) + ";\nfor (const cmd of cmds) {\n"
                  "const r = await tools.exec_command({cmd,workdir:" + json.dumps(str(self.root)) + "});\n"
                  "text(r.output);\n}\n")
        trace["tool_trace"] = [
            {"type": "custom_tool_call", "name": "exec", "call_id": "loop", "input": source},
            {"type": "custom_tool_call_output", "call_id": "loop", "output": output}]
        self.assertEqual([args["cmd"] for _, args in runtime_checks._tool_operations(trace["tool_trace"][0])], commands)
        self.assertEqual(runtime.observed_dispatch_binding(trace, self.artifacts)["dispatch_file"], path)
        self.assertEqual(runtime.context_trace_errors(trace), [])
        for change in ("missing_output", "reordered_output", "truncated_output", "wrong_pair", "mutable_list",
                       "mutated_command", "shadowed_tool", "extra_operation", "missing_command"):
            changed = json.loads(json.dumps(trace))
            if change == "missing_output": changed["tool_trace"][1]["output"].pop()
            elif change == "reordered_output": changed["tool_trace"][1]["output"][:2] = output[1::-1]
            elif change == "truncated_output": changed["tool_trace"][1]["output"][0]["text"] = "Warning: truncated output"
            elif change == "wrong_pair": changed["tool_trace"][1]["call_id"] = "another"
            elif change == "mutable_list": changed["tool_trace"][0]["input"] = source.replace("const cmds", "let cmds")
            elif change == "mutated_command": changed["tool_trace"][0]["input"] = source.replace("const r =", "cmd = 'other'; const r =")
            elif change == "shadowed_tool": changed["tool_trace"][0]["input"] = source.replace("const cmd of", "const tools of")
            elif change == "extra_operation": changed["tool_trace"][0]["input"] += 'await tools.exec_command({cmd:"cat ' + ARCHIVE + '"});'
            elif change == "missing_command": changed["tool_trace"][0]["input"] = source.replace(json.dumps(commands), json.dumps(commands[1:]))
            with self.subTest(change=change):
                self.assertEqual(runtime.observed_dispatch_binding(changed, self.artifacts), {})
        trace["tool_trace"][1]["output"].append({"type": "input_text", "text": ARCHIVE})
        self.assertIn("forbidden_context_reference:archived_artifact", runtime.context_trace_errors(trace))

    def test_parallel_literal_command_batch_requires_complete_ordered_output(self):
        trace = self.instruction_trace()
        path = trace["spawn"]["dispatch_file"]
        content = Path(path).read_text()
        commands, output = [], []
        for index, start in enumerate(range(0, len(content), 900)):
            end = min(start + 900, len(content))
            commands.append(shlex.join(["python3", "-c", f"print(open({path!r}).read()[{start}:{end}],end='')"]))
            output.append({"type": "input_text", "text": f"COMMAND {index + 1}\n{content[start:end]}"})
        source = ("const cmds = " + json.dumps(commands) + ";\n"
                  "const rs = await Promise.all(cmds.map(cmd => tools.exec_command({cmd,workdir:"
                  + json.dumps(str(self.root)) + ",max_output_tokens:2500,yield_time_ms:10000})));\n"
                  "for (let i=0;i<rs.length;i++) { text(`COMMAND ${i+1}\\n${rs[i].output}`); }\n")
        trace["tool_trace"] = [
            {"type": "custom_tool_call", "name": "exec", "call_id": "batch", "input": source},
            {"type": "custom_tool_call_output", "call_id": "batch", "output": output}]
        self.assertEqual([args["cmd"] for _, args in runtime_checks._tool_operations(trace["tool_trace"][0])], commands)
        self.assertEqual(runtime.observed_dispatch_binding(trace, self.artifacts)["dispatch_file"], path)
        self.assertEqual(runtime.context_trace_errors(trace), [])
        for change in ("missing", "reordered", "truncated", "wrong_pair", "mutation", "extra", "shadow", "wrong_output"):
            changed = json.loads(json.dumps(trace))
            if change == "missing": changed["tool_trace"][1]["output"].pop()
            elif change == "reordered": changed["tool_trace"][1]["output"][:2] = output[1::-1]
            elif change == "truncated": changed["tool_trace"][1]["output"][0]["text"] = "Warning: truncated output"
            elif change == "wrong_pair": changed["tool_trace"][1]["call_id"] = "other"
            elif change == "mutation": changed["tool_trace"][0]["input"] = source.replace("const rs", "cmds.reverse(); const rs")
            elif change == "extra": changed["tool_trace"][0]["input"] += 'await tools.exec_command({cmd:"cat ' + ARCHIVE + '"});'
            elif change == "shadow": changed["tool_trace"][0]["input"] = source.replace("const cmds", "const Promise").replace("cmds.map", "Promise.map")
            elif change == "wrong_output": changed["tool_trace"][0]["input"] = source.replace("rs[i].output", "rs[0].output")
            with self.subTest(change=change):
                self.assertEqual(runtime.observed_dispatch_binding(changed, self.artifacts), {})
        trace["tool_trace"][1]["output"].append({"type": "input_text", "text": ARCHIVE})
        self.assertIn("forbidden_context_reference:archived_artifact", runtime.context_trace_errors(trace))

    def test_filename_filter_end_anchor_is_not_shell_expansion_or_archive_content(self):
        command = "rg --files -g 'AGENTS.md' -g '*.md' .thoughts/ITEM-1 . | rg '(^|/)(AGENTS\\.md|plan\\.md)$'"
        trace = self.trace(command, ARCHIVE)
        self.assertTrue(runtime._listing_command(command))
        self.assertEqual(runtime.context_trace_errors(trace), [])
        for suffix in ("HOME", "{ROOT}", "(cat secret)", "?"):
            self.assertFalse(runtime._listing_command(command.replace("$", "$" + suffix)))
        for unsafe in ("find . $'-exec' cat secret ';'", "find . $'\\x2dexec' cat secret ';'"):
            self.assertFalse(runtime._listing_command(unsafe))
            self.assertFalse(runtime._listing_command("bash -c " + shlex.quote(unsafe)))
        trace = self.trace(command + "; cat " + ARCHIVE, ARCHIVE)
        self.assertIn("forbidden_context_reference:archived_artifact", runtime.context_trace_errors(trace))

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

    def test_planning_rejects_direct_writes_for_response_contracts(self):
        trace = self.instruction_trace()
        worker_packet = json.loads(Path(self.bundle["path"]).read_text())["packets"]["current_state_investigator"]
        output = worker_packet["worker_contract"]["output"]
        result = worker_packet["worker_contract"]["result"]
        packet_path = Path(self.run["finalization_packet"])
        packet = json.loads(packet_path.read_text())
        packet["identity"]["Lifecycle"] = "planning"
        packet_path.write_text(json.dumps(packet))
        trace["tool_trace"].append({"type": "custom_tool_call", "name": "functions.apply_patch",
            "input": "*** Begin Patch\n*** Update File: src/service.go\n@@\n-old\n+new\n*** End Patch"})
        self.assertIn("planning_source_write_not_authorized", runtime.trace_errors(trace))
        trace["tool_trace"][-1]["input"] = ("*** Begin Patch\n*** Add File: " + output
                                               + "\n+current-run analysis\n*** End Patch")
        self.assertIn("planning_write_target_not_assigned", runtime.trace_errors(trace))
        trace["tool_trace"][-1]["input"] = ("*** Begin Patch\n*** Add File: " + result
                                               + "\n+current-run result\n*** End Patch")
        self.assertIn("planning_write_target_not_assigned", runtime.trace_errors(trace))
        trace["tool_trace"][-1]["input"] = ("*** Begin Patch\n*** Add File: " + str(self.artifacts / "finalization_packet.json")
                                               + "\n+changed control record\n*** End Patch")
        self.assertIn("planning_write_target_not_assigned", runtime.trace_errors(trace))
        commands = ["printf plan > " + output, "printf plan > " + result,
                    "printf plan > 1", "printf plan >&1",
                    "printf plan > src/service.go", "tee src/service.go", "cp note.md src/service.go",
                    "sed -i 's/old/new/' src/service.go", "git apply source.patch",
                    "python3 -c \"from pathlib import Path; Path('src/service.go').write_text('new')\""]
        for command in commands:
            with self.subTest(command=command):
                current = json.loads(json.dumps(trace))
                current["tool_trace"].append({"tool": "exec_command", "arguments": {"cmd": command}})
                errors = runtime.trace_errors(current)
                if command in {"printf plan >&1"}:
                    self.assertFalse(any(error.startswith("planning_source_write") for error in errors))
                elif command in {"printf plan > " + output, "printf plan > " + result}:
                    self.assertIn("planning_source_write_not_authorized", errors)
                else:
                    self.assertIn("planning_source_write_not_authorized", errors)

        relative_output = Path(output).relative_to(self.root.resolve())
        relative = json.loads(json.dumps(trace))
        relative["tool_trace"].append({"tool": "exec_command", "arguments": {
            "cmd": "printf plan > " + str(relative_output), "workdir": "."}})
        self.assertIn("planning_source_write_not_authorized", runtime.trace_errors(relative))

    def test_planning_keeps_assigned_sentry_file_outputs_writable(self):
        run = prepare.prepare_run(self.root, "SENTRY-1", "sentry_issue_remediation", None, False,
                                  input_manifest=self.root / "inputs.json")
        artifact_root = Path(run["artifact_root"])
        bundle = json.loads(Path(run["activation_packet_bundle"]["path"]).read_text())
        role = "sentry_current_state_investigator"
        packet = bundle["packets"][role]
        dispatch = artifact_root / "activation_context_sentry.txt"
        message = runtime.activation_message(packet, {"objective": "Review the assigned current evidence"})
        runtime.dispatch_message(packet, message, dispatch)
        spawn = {"dispatch_file": str(dispatch),
                 "dispatch_file_sha256": hashlib.sha256(dispatch.read_bytes()).hexdigest(),
                 "agent": role, "binding_agent": role}
        output = packet["worker_contract"]["output"]
        trace = {"run_id": packet["run_id"], "spawn": spawn, "tool_trace": [
            {"tool": "apply_patch", "arguments": {"patch":
                "*** Begin Patch\n*** Add File: " + output + "\n+assigned Sentry output\n*** End Patch"}}]}
        self.assertEqual(runtime_checks.planning_permission_errors(trace), [])
        trace["tool_trace"] = [{"tool": "exec_command", "arguments": {
            "cmd": "printf evidence > " + output}}]
        self.assertEqual(runtime_checks.planning_permission_errors(trace), [])

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
