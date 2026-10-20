"""Native parent context boundaries before preparation and worker activation."""

import json
import shlex
import tempfile
import textwrap
import unittest
from pathlib import Path

from scripts.prepare_run import prepare_run
from scripts.provider_runtime import (
    parent_context_audit,
    prior_run_status_thread_ids,
    related_run_status_projection_source,
    stale_run_status_errors,
    strict_json_loads,
)
from scripts.worker_runtime_evidence import strict_json_loads as worker_strict_json_loads
from scripts.validate_worker_runtime import activation_packet_errors


PARENT = "00000000-0000-0000-0000-000000000001"
TURN = "00000000-0000-0000-0000-000000000002"
CHILD = "00000000-0000-0000-0000-000000000003"


class ParentContext(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "parent.jsonl"
        self.rows = [{"type": "session_meta", "timestamp": "2026-10-01T00:00:00Z",
                      "payload": {"id": PARENT}},
                     {"type": "turn_context", "timestamp": "2026-10-01T00:00:01Z",
                      "payload": {"turn_id": TURN}}]

    def call(self, name, **arguments):
        return {"type": "response_item", "timestamp": "2026-10-01T00:00:02Z",
                "payload": {"type": "function_call", "name": name, "arguments": json.dumps(arguments)}}

    def command_execution(self, command, *, exit_code=1, output="", status=None, parsed_cmd=None):
        argv = shlex.split(command)
        query_path = argv[-1]
        query = argv[2]
        return {"type": "event_msg", "timestamp": "2026-10-01T00:00:03Z",
                "payload": {"type": "item_completed", "item": {
                    "type": "CommandExecution", "id": "exec-00000000-0000-0000-0000-000000000001",
                    "command": ["/bin/bash", "-lc", command],
                    "status": status if status is not None else ("failed" if exit_code else "completed"),
                    "exit_code": exit_code, "aggregated_output": output,
                    "parsed_cmd": parsed_cmd if parsed_cmd is not None else [
                        {"type": "search", "cmd": command, "query": query, "path": query_path}],
                }}}

    def audit(self, **kwargs):
        self.source.write_text("".join(json.dumps(row) + "\n" for row in self.rows))
        return parent_context_audit(self.source, **kwargs)

    def test_actual_memory_read_is_rejected_but_quotes_and_prior_turn_are_ignored(self):
        memory = "/repo/.codex/memories/MEMORY.md"
        self.rows.insert(1, {"type": "turn_context", "timestamp": "2026-09-30T23:59:00Z",
                             "payload": {"turn_id": CHILD}})
        self.rows.insert(2, self.call("exec_command", cmd="cat " + memory))
        self.rows.extend([self.call("spawn_agent", message="Do not read " + memory),
            {"type": "response_item", "timestamp": "2026-10-01T00:00:02Z",
             "payload": {"type": "function_call_output", "output": "cat " + memory}},
            self.call("exec_command", cmd="cat start_prompt.md")])
        self.assertEqual(self.audit()["status"], "passed")
        self.rows.append(self.call("exec_command", cmd="rg -n issue " + memory))
        result = self.audit()
        self.assertEqual(result["turn_id"], TURN)
        self.assertIn("forbidden_context_reference:memory_path", result["errors"])

    def test_verified_no_match_memory_probe_is_distinct_from_a_memory_read(self):
        memory = "/Users/example/.codex/memories/MEMORY.md"
        command = "rg -n 'ECHO-2806|planning' " + memory
        self.rows.extend([self.call("exec_command", cmd=command), self.command_execution(command)])
        result = self.audit()
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["empty_memory_probes"], 1)
        self.assertNotIn("forbidden_context_reference:memory_path", result["errors"])

    def test_verified_case_insensitive_probe_accepts_native_basename_path(self):
        memory = "/Users/example/.codex/memories/MEMORY.md"
        query = "ECHO-2806|Issue Remediation|issue_remediation"
        command = "rg -n -i " + shlex.quote(query) + " " + memory
        parsed = [{"type": "search", "cmd": command, "query": query, "path": "MEMORY.md"}]
        self.rows.extend([self.call("exec_command", cmd=command),
                          self.command_execution(command, parsed_cmd=parsed)])
        result = self.audit()
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["empty_memory_probes"], 1)

        forged = self.command_execution(command, parsed_cmd=[
            {"type": "search", "cmd": command, "query": query, "path": "/tmp/MEMORY.md"}])
        self.rows = self.rows[:2] + [self.call("exec_command", cmd=command), forged]
        result = self.audit()
        self.assertEqual(result["empty_memory_probes"], 0)
        self.assertIn("forbidden_context_reference:memory_path", result["errors"])

    def test_memory_search_is_not_exempt_without_exact_native_no_match_evidence(self):
        memory = "/Users/example/.codex/memories/MEMORY.md"
        command = "rg -n issue " + memory
        variants = (
            None,
            self.command_execution(command, exit_code=0),
            self.command_execution(command, output="matched text"),
            self.command_execution(command, status="completed"),
            self.command_execution(command, parsed_cmd=[
                {"type": "search", "query": "issue", "path": "MEMORY.md"},
                {"type": "search", "query": "issue", "path": "MEMORY.md"},
            ]),
        )
        for observation in variants:
            with self.subTest(observation=observation is not None):
                self.rows = self.rows[:2] + [self.call("exec_command", cmd=command)]
                if observation is not None:
                    self.rows.append(observation)
                result = self.audit()
                self.assertEqual(result["empty_memory_probes"], 0)
                self.assertTrue(any(error.startswith("forbidden_context_reference:memory_")
                                    for error in result["errors"]))

        piped = command + " | head -20"
        self.rows = self.rows[:2] + [self.call("exec_command", cmd=piped), self.command_execution(piped)]
        self.assertTrue(any(error.startswith("forbidden_context_reference:memory_")
                            for error in self.audit()["errors"]))

    def test_approved_continuity_read_is_allowed_but_write_and_unassigned_read_are_not(self):
        artifact = self.root / ".thoughts" / "ITEM-1"
        archived = str(artifact / "runs" / "prior" / "decisions.md")
        self.rows.append(self.call("exec_command", cmd="cat " + archived))
        self.assertEqual(self.audit(artifact_root=artifact, input_paths=(archived,))["status"], "passed")
        self.assertEqual(self.audit(artifact_root=artifact)["status"], "rejected")
        self.rows[-1] = self.call("exec_command", cmd="echo changed > " + archived)
        self.assertEqual(self.audit(artifact_root=artifact, input_paths=(archived,))["status"], "rejected")

    def test_parent_can_observe_its_workers_and_explicit_continuity_threads(self):
        self.rows.append({"type": "event_msg", "timestamp": "2026-10-01T00:00:02Z",
            "payload": {"item": {"type": "SubAgentActivity",
            "kind": "started", "agent_thread_id": CHILD}}})
        self.rows.extend([self.call("mcp__codex_app__read_thread", threadId=CHILD),
                          self.call("mcp__codex_app__read_thread", threadId=TURN)])
        self.assertIn("parent_unassigned_thread_read:" + TURN, self.audit()["errors"])
        self.assertEqual(self.audit(input_paths=("codex://threads/" + TURN,))["status"], "passed")
        self.rows.append(self.call("mcp__codex_app__wait_threads", targets=[{"threadId": PARENT}]))
        self.assertIn("parent_unassigned_thread_read:" + PARENT, self.audit()["errors"])
        self.rows.append(self.call("mcp__codex_app__list_threads", limit=10))
        self.assertIn("parent_unassigned_thread_discovery", self.audit()["errors"])

    def test_only_one_exact_redacted_related_run_status_projection_is_allowed(self):
        artifact_root = self.root / ".thoughts" / "ECHO-2806"
        projection = related_run_status_projection_source(artifact_root.name, PARENT)
        status_call = {"type": "response_item", "payload": {
            "type": "custom_tool_call", "name": "exec", "call_id": "status-call", "input": projection}}
        status_output = {"type": "response_item", "payload": {
            "type": "custom_tool_call_output", "call_id": "status-call",
            "output": [{"type": "text", "text": "[]"}]}}
        self.rows.extend([status_call, status_output])

        result = self.audit(artifact_root=artifact_root)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["verified_related_run_status_probes"], 1)
        self.assertEqual(result["related_run_status_rows"], [])
        self.assertIn("parent_unassigned_thread_discovery", self.audit()["errors"])

        self.rows.extend([
            {"type": "response_item", "payload": {
                "type": "custom_tool_call", "name": "exec", "call_id": "status-call-2", "input": projection}},
            {"type": "response_item", "payload": {
                "type": "custom_tool_call_output", "call_id": "status-call-2",
                "output": [{"type": "text", "text": "[]"}]}}])
        result = self.audit(artifact_root=artifact_root)
        self.assertIn("parent_unassigned_thread_discovery", result["errors"])
        self.assertEqual(result["verified_related_run_status_probes"], 1)

        self.rows = self.rows[:2] + [{"type": "response_item", "payload": {
            "type": "custom_tool_call", "name": "exec",
            "call_id": "bad-status-call",
            "input": projection.replace("text(JSON.stringify(related));", "text(response.content[0].text);")}}]
        result = self.audit(artifact_root=artifact_root)
        self.assertIn("parent_unassigned_thread_discovery", result["errors"])

        self.rows = self.rows[:2] + [status_call, status_output,
            self.call("mcp__codex_app__read_thread", threadId=CHILD)]
        result = self.audit(artifact_root=artifact_root)
        self.assertIn("parent_unassigned_thread_read:" + CHILD, result["errors"])

    def test_related_status_probe_requires_correlated_minimal_output(self):
        artifact_root = self.root / ".thoughts" / "ECHO-2806"
        artifact_root.mkdir(parents=True)
        (artifact_root / "runtime_dispatches.json").write_text(json.dumps({
            "thread_mappings": {"/root/prior-worker": CHILD}, "events": [], "failed_dispatches": [],
        }))
        projection = related_run_status_projection_source(artifact_root.name, PARENT, (CHILD,))
        call = {"type": "response_item", "payload": {
            "type": "custom_tool_call", "name": "exec", "call_id": "status-call", "input": projection}}
        output = {"type": "response_item", "payload": {
            "type": "custom_tool_call_output", "call_id": "status-call",
            "output": [{"type": "text", "text": json.dumps([
                {"id": CHILD, "status": "completed", "hostId": "local", "kind": "codex",
                 "updatedAt": "2026-10-01T00:00:00Z"}])}]}}
        self.rows.extend([call, output])
        result = self.audit(artifact_root=artifact_root)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["related_run_thread_ids"], [CHILD])

        self.rows = self.rows[:2] + [call]
        self.assertIn("parent_related_run_status_output_missing", self.audit(artifact_root=artifact_root)["errors"])

        self.rows = self.rows[:2] + [call, {"type": "response_item", "payload": {
            **output["payload"], "call_id": "another-call"}}]
        self.assertIn("parent_related_run_status_output_missing", self.audit(artifact_root=artifact_root)["errors"])

        for unsafe in (
            [{"id": CHILD, "status": "completed", "summary": "private task content"}],
            [{"id": CHILD, "status": "running"}],
        ):
            with self.subTest(unsafe=unsafe):
                self.rows = self.rows[:2] + [call, {"type": "response_item", "payload": {
                    "type": "custom_tool_call_output", "call_id": "status-call",
                    "output": [{"type": "text", "text": json.dumps(unsafe)}]}}]
                result = self.audit(artifact_root=artifact_root)
                if "summary" in unsafe[0]:
                    self.assertIn("parent_related_run_status_output_invalid", result["errors"])
                else:
                    self.assertEqual(result["status"], "passed")
                    self.assertEqual(stale_run_status_errors(result, "active"),
                                     ["stale_run_related_task_active:" + CHILD])

        duplicate_status = ('[{"id":"' + CHILD + '","status":"running","status":"completed"}]')
        self.rows = self.rows[:2] + [call, {"type": "response_item", "payload": {
            "type": "custom_tool_call_output", "call_id": "status-call",
            "output": [{"type": "text", "text": duplicate_status}]}}]
        self.assertIn("parent_related_run_status_output_invalid", self.audit(artifact_root=artifact_root)["errors"])

    def test_stale_archive_status_requires_all_known_workers_to_be_terminal(self):
        context = {
            "verified_related_run_status_probes": 1,
            "related_run_status_probe_attempts": 1,
            "related_run_status_rows": [{"id": CHILD, "status": "completed"}],
            "related_run_thread_ids": [CHILD],
            "prior_run_dispatch_ledger_present": True,
        }
        self.assertEqual(stale_run_status_errors(context, "active"), [])
        active = {**context, "related_run_status_rows": [{"id": CHILD, "status": "running"}]}
        self.assertEqual(stale_run_status_errors(active, "active"), ["stale_run_related_task_active:" + CHILD])
        missing = {**context, "related_run_status_rows": []}
        self.assertEqual(stale_run_status_errors(missing, "active"), ["stale_run_worker_status_missing:" + CHILD])
        missing_ledger = {**context, "prior_run_dispatch_ledger_present": False}
        self.assertEqual(stale_run_status_errors(missing_ledger, "active"), ["stale_run_dispatch_ledger_required"])
        self.assertEqual(stale_run_status_errors(None, "active"), ["stale_run_status_probe_required"])

    def test_prior_worker_identity_collection_fails_closed_on_malformed_receipts(self):
        self.assertIs(worker_strict_json_loads, strict_json_loads)
        with self.assertRaisesRegex(ValueError, "NaN"):
            strict_json_loads('{"value":NaN}')

        artifact_root = self.root / ".thoughts" / "ITEM-1"
        artifact_root.mkdir(parents=True)
        ledger = artifact_root / "runtime_dispatches.json"
        ledger.write_text(json.dumps({"thread_mappings": {},
            "events": [{"Operation": "spawn_agent", "Provider handle": "/root/worker"}],
            "failed_dispatches": []}))
        with self.assertRaisesRegex(ValueError, "stale_run_thread_identity_invalid"):
            prior_run_status_thread_ids(artifact_root, PARENT)

        ledger.write_text(json.dumps({"thread_mappings": {}, "events": [],
            "failed_dispatches": [{"Operation": "spawn_agent", "Provider handle": "/root/worker",
                                   "Status": "failed"}]}))
        self.assertEqual(prior_run_status_thread_ids(artifact_root, PARENT), ())

        ledger.write_text('{"thread_mappings":{"/root/worker":"' + CHILD + '","/root/worker":"' +
                          PARENT + '"},"events":[],"failed_dispatches":[]}')
        with self.assertRaisesRegex(ValueError, "stale_run_thread_identity_invalid"):
            prior_run_status_thread_ids(artifact_root, "00000000-0000-0000-0000-000000000004")

    def test_shipped_status_projection_matches_the_audit_allowlist(self):
        skill = (Path(__file__).resolve().parents[1] / "skills" / "run" / "SKILL.md").read_text()
        section = skill.split("this exact projection", 1)[1]
        snippet = section.split("```javascript\n", 1)[1].split("\n   ```", 1)[0]
        prior_id = "00000000-0000-0000-0000-000000000004"
        expected = related_run_status_projection_source("ECHO-2806", PARENT, (prior_id,))
        expected = expected.replace(json.dumps(PARENT), '"PARENT-THREAD-UUID"')
        expected = expected.replace(json.dumps([prior_id]), '["PRIOR-WORKER-THREAD-UUID"]')
        self.assertEqual(textwrap.dedent(snippet).strip(), expected)

    def test_missing_turn_wrong_parent_and_unparsed_calls_cannot_pass(self):
        with self.assertRaisesRegex(ValueError, "parent_mismatch"):
            self.audit(expected_thread_id=CHILD)
        self.rows.pop()
        with self.assertRaisesRegex(ValueError, "current_turn_unavailable"):
            self.audit()
        self.rows.append({"type": "turn_context", "payload": {"turn_id": TURN}})
        self.rows.append({"type": "response_item", "payload": {"type": "custom_tool_call",
            "input": "await tools.exec_command(argumentsFromElsewhere)"}})
        self.assertIn("parent_tool_arguments_unavailable", self.audit()["errors"])

    def test_literal_const_tool_arguments_are_audited_but_dynamic_values_fail_closed(self):
        patch = ("*** Begin Patch\n*** Add File: " + str(self.root / ".thoughts" / "ITEM-1" / "runs" /
                 "current" / "receipt.json") + "\n+{}\n*** End Patch")
        self.rows.append({"type": "response_item", "payload": {"type": "custom_tool_call", "name": "exec",
            "input": "const patch = " + json.dumps(patch) + "; await tools.apply_patch(patch);"}})
        result = self.audit(artifact_root=self.root / ".thoughts" / "ITEM-1")
        self.assertNotIn("parent_tool_arguments_unavailable", result["errors"])
        self.assertIn("forbidden_context_reference:archived_artifact", result["errors"])

        self.rows[-1]["payload"]["input"] = "const patch = buildPatch(); await tools.apply_patch(patch);"
        self.assertIn("parent_tool_arguments_unavailable", self.audit()["errors"])

        for source in (
            "const patch = 'safe' + 'unreviewed'; await tools.apply_patch(patch);",
            "const command = 'cat ' + '/repo/.codex/memories/MEMORY.md'; "
            "await tools.exec_command({cmd: command});",
            "const patch = 'safe'\n+ 'unreviewed'; await tools.apply_patch(patch);",
        ):
            self.rows[-1]["payload"]["input"] = source
            self.assertIn("parent_tool_arguments_unavailable", self.audit()["errors"])

        self.rows[-1]["payload"]["input"] = "const patch = 'safe'\nawait tools.apply_patch(patch);"
        self.assertEqual(self.audit()["status"], "passed")

        for source in (
            "const patch = 'safe'; patch = buildPatch(); await tools.apply_patch(patch);",
            "const patch = 'safe'; { let patch = buildPatch(); } await tools.apply_patch(patch);",
            "const patch = 'safe'; function apply(patch) { tools.apply_patch(patch); }",
            "const patch = 'safe'; const target = { apply(patch) { tools.apply_patch(patch); } };",
        ):
            self.rows[-1]["payload"]["input"] = source
            self.assertIn("parent_tool_arguments_unavailable", self.audit()["errors"])

    def test_preparation_accepts_literal_const_manifest_creation(self):
        inputs = self.root / "inputs.json"
        inputs.write_text(json.dumps({"inputs": [{"Input ID": "IN-001", "Input or artifact": "Current issue",
            "Source or path": "User", "Authority": "User", "Status": "Verified"}]}))
        patch = ("*** Begin Patch\n*** Add File: " + str(self.root / "inputs.json") + "\n+{}\n*** End Patch")
        self.rows.append({"type": "response_item", "payload": {"type": "custom_tool_call", "name": "exec",
            "input": "const patch = " + json.dumps(patch) + "; await tools.apply_patch(patch);"}})
        self.assertEqual(self.audit()["status"], "passed")
        run = prepare_run(self.root, "ITEM-1", "feature_delivery", None, False,
                          input_manifest=inputs, provider_session=self.source)
        self.assertEqual(run["status"], "prepared")

    def test_preparation_is_transactional_and_activation_rechecks_later_reads(self):
        inputs = self.root / "inputs.json"
        inputs.write_text(json.dumps({"inputs": [{"Input ID": "IN-001", "Input or artifact": "Current issue",
            "Source or path": "User", "Authority": "User", "Status": "Verified"}]}))
        self.rows.append(self.call("exec_command", cmd="cat /repo/.codex/memories/MEMORY.md"))
        self.audit()
        with self.assertRaisesRegex(ValueError, "parent_context_nonconformant"):
            prepare_run(self.root, "ITEM-1", "feature_delivery", None, False,
                        input_manifest=inputs, provider_session=self.source)
        self.assertFalse((self.root / ".thoughts").exists())
        self.rows.pop()
        self.audit()
        run = prepare_run(self.root, "ITEM-1", "feature_delivery", None, False,
                          input_manifest=inputs, provider_session=self.source)
        bundle = run["activation_packet_bundle"]
        check = lambda: activation_packet_errors(Path(bundle["path"]), "current_state_investigator", bundle["sha256"])
        self.assertEqual(check(), [])
        self.rows.append(self.call("exec_command", cmd="cat /repo/.codex/memories/MEMORY.md"))
        self.audit()
        self.assertTrue(any(error.startswith("parent_context_nonconformant") for error in check()))
        self.rows.append({"type": "turn_context", "timestamp": "2026-10-01T00:00:03Z",
                          "payload": {"turn_id": CHILD}})
        self.audit()
        self.assertTrue(any(error.startswith("parent_context_turn_mismatch:expected=" + TURN)
                            for error in check()))


if __name__ == "__main__":
    unittest.main()
