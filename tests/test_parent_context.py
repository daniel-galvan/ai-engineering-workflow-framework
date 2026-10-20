"""Native parent context boundaries before preparation and worker activation."""

import json
import tempfile
import unittest
from pathlib import Path

from scripts.prepare_run import prepare_run
from scripts.provider_runtime import parent_context_audit
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
