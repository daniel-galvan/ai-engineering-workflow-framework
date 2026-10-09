"""Regressions for durable roots, provider events and typed TechOps results."""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import prepare_run as prepare
from scripts.merge_techops_result import merge_result
from scripts.worker_runtime_evidence import read_runtime_events, dispatch_audit_errors
from scripts.validate_worker_runtime import terminal_observation_errors
from scripts.validation.work_records import validate_work_record


PARENT = "00000000-0000-0000-0000-000000000001"
CHILD = "00000000-0000-0000-0000-000000000002"
START = "2026-10-09T03:00:00Z"


class V4Regressions(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()

    def git(self, root, *args):
        return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True,
                              text=True).stdout.strip()

    def repository(self):
        main = self.root / "main"
        main.mkdir()
        self.git(main, "init", "-q")
        self.git(main, "config", "user.email", "test@example.com")
        self.git(main, "config", "user.name", "Test")
        self.git(main, "commit", "--allow-empty", "-qm", "baseline")
        worktree = self.root / "source"
        self.git(main, "worktree", "add", "--detach", str(worktree))
        self.git(worktree, "commit", "--allow-empty", "-qm", "source revision")
        return main, worktree

    def prepare(self, repository, continuation=False):
        manifest = self.root / "inputs.json"
        manifest.write_text(json.dumps({"schema_version": 1, "status": "explicit",
            "precedence_rule": prepare.DEFAULT_PRECEDENCE_RULE,
            "inputs": [{"Input ID": "IN-001", "Input or artifact": "Current issue",
                        "Source or path": "Current request", "Authority": "User",
                        "Classification": "work item", "Expected use": "Investigation", "Status": "Registered"}]}))
        return prepare.prepare_run(repository, "ISSUE-1", "techops_issue_remediation", None,
                                   continuation, input_manifest=manifest)

    def test_main_artifacts_keep_worktree_source_revision(self):
        main, worktree = self.repository()
        with patch.object(Path, "cwd", return_value=worktree):
            result = self.prepare(main)
        self.assertEqual(result["artifact_root"], str(main / ".thoughts/ISSUE-1"))
        self.assertEqual(result["source_checkout"], str(worktree))
        packet = json.loads(Path(result["finalization_packet"]).read_text())
        self.assertEqual(packet["repositories"][0]["Full revision"], self.git(worktree, "rev-parse", "HEAD"))
        self.assertFalse((worktree / ".thoughts").exists())
        self.assertEqual(prepare.resolve_repository_paths(worktree), (main, worktree))

    def test_legacy_continuation_is_not_silently_relocated(self):
        main, worktree = self.repository()
        legacy = worktree / ".thoughts/ISSUE-1"
        legacy.mkdir(parents=True)
        (legacy / "work_record.md").write_text("legacy")
        with self.assertRaisesRegex(ValueError, "explicit_migration"):
            self.prepare(worktree, continuation=True)
        self.assertEqual((legacy / "work_record.md").read_text(), "legacy")
        self.assertFalse((main / ".thoughts").exists())

    def test_bare_main_cannot_receive_durable_artifacts(self):
        bare = self.root / "bare"
        self.git(self.root, "init", "--bare", str(bare))
        with self.assertRaisesRegex(ValueError, "main_execution_repository_unavailable"):
            self.prepare(bare)
        self.assertFalse((bare / ".thoughts").exists())

    def test_prepared_outputs_and_selective_scope(self):
        result = self.prepare(self.root)
        contracts = result["worker_contracts"]
        for agent, contract in contracts.items():
            self.assertEqual(Path(contract["output"]).parent, Path(result["artifact_root"]))
            if agent != "documenter":
                self.assertIn("result", contract)
        instructions = contracts["current_state_investigator"]["instructions"]
        self.assertIn("does not require a sibling roster", instructions)
        self.assertNotIn("Enumerate the Jira sibling summary roster", instructions)

    def provider_events(self):
        def event(time, kind, payload):
            return {"timestamp": time, "type": kind, "payload": payload}
        return [event(START, "session_meta", {"id": PARENT}),
            event("2026-10-09T03:01:00.100Z", "response_item", {"type": "function_call",
                  "namespace": "collaboration", "name": "spawn_agent", "arguments": '{"task_name":"evidence"}'}),
            event("2026-10-09T03:01:00.200Z", "event_msg", {"item": {"type": "SubAgentActivity",
                  "kind": "started", "agent_path": "/root/evidence", "agent_thread_id": CHILD}}),
            event("2026-10-09T03:02:00.900Z", "response_item", {"type": "function_call",
                  "namespace": "collaboration", "name": "send_message", "arguments": '{"target":"evidence"}'}),
            event("2026-10-09T03:03:00Z", "response_item", {"type": "function_call",
                  "namespace": "collaboration", "name": "list_agents", "arguments": '{}'}),
            event("2026-10-09T03:03:01Z", "response_item", {"type": "function_call_output",
                  "output": json.dumps({"agents": [{"agent_name": "/root/evidence", "agent_status": {"completed": "exact provider text"}}]})})]

    def provider_file(self):
        source = self.root / "provider.jsonl"
        source.write_text("".join(json.dumps(row) + "\n" for row in self.provider_events()))
        return source

    def test_provider_uuid_and_dispatches_are_not_inferred_from_labels(self):
        source = self.provider_file()
        result = read_runtime_events(source, PARENT, START)
        self.assertEqual(result["thread_mappings"], {"/root/evidence": CHILD})
        self.assertEqual(result["events"][-1]["Last dispatch at"], "2026-10-09T03:02:00.900Z")
        self.assertEqual(result["inventories"][0]["raw_response"]["agents"][0]["agent_status"],
                         {"completed": "exact provider text"})
        with self.assertRaisesRegex(ValueError, "parent_mismatch"):
            read_runtime_events(source, CHILD, START)

    def test_spawn_does_not_pair_with_an_unrelated_child_event(self):
        source = self.provider_file()
        rows = self.provider_events()
        unrelated = json.loads(json.dumps(rows[2]))
        unrelated["payload"]["item"]["agent_path"] = "/root/unrelated"
        rows.insert(2, unrelated)
        source.write_text("".join(json.dumps(row) + "\n" for row in rows) + '{"timestamp":')
        result = read_runtime_events(source, PARENT, START)
        self.assertEqual(result["events"][0]["Provider handle"], "/root/evidence")
        self.assertEqual(len(result["events"]), 2)

    def test_dispatch_audit_cannot_use_earlier_clock_or_stale_ledger(self):
        source = self.provider_file()
        ledger = self.root / "runtime_dispatches.json"
        ledger.write_text(json.dumps(read_runtime_events(source, PARENT, START)))
        (self.root / "role_bindings.json").write_text(json.dumps({"runtime_evidence": {"ledger": str(ledger)}}))
        packet = {"runtime_audits": [{"Worker": "issue-evidence", "Provider handle": "/root/evidence",
                                     "Last dispatch at": "2026-10-09T03:02:00.900Z", "Thread ID": CHILD}]}
        path = self.root / "finalization_packet.json"
        self.assertEqual(dispatch_audit_errors(packet, path), [])
        packet["runtime_audits"][0]["Last dispatch at"] = START
        self.assertIn("runtime_audit_dispatch_mismatch:issue-evidence", dispatch_audit_errors(packet, path))
        with source.open("a") as stream:
            row = self.provider_events()[3]
            row["timestamp"] = "2026-10-09T03:04:00Z"
            stream.write(json.dumps(row) + "\n")
        self.assertTrue(any("ledger_stale" in error for error in dispatch_audit_errors(packet, path)))

    def test_in_turn_correction_requires_completion_and_consumption_evidence(self):
        row = {"Provider handle": "/root/evidence", "Provider status": "completed",
               "Last dispatch at": "2026-10-09T03:02:00Z", "Observed at": "2026-10-09T03:04:00Z",
               "Status source": "read_thread", "Thread ID": CHILD, "Thread status": "notLoaded",
               "Latest turn started at": "2026-10-09T03:01:00Z", "Latest turn status": "completed",
               "Latest turn completed at": "2026-10-09T03:03:00Z", "Dispatch consumed": True,
               "Dispatch consumption evidence": "Latest provider result confirms corrected input was consumed"}
        self.assertEqual(terminal_observation_errors([row], [row["Provider handle"]]), [])
        for field, value in (("Dispatch consumption evidence", ""), ("Dispatch consumed", False),
                             ("Latest turn completed at", "2026-10-09T03:01:30Z"), ("Thread status", "inProgress")):
            bad = {**row, field: value}
            self.assertTrue(terminal_observation_errors([bad], [row["Provider handle"]]))

    def test_typed_merge_is_idempotent_and_preserves_identity(self):
        prepared = self.prepare(self.root)
        packet_path = Path(prepared["finalization_packet"])
        packet = json.loads(packet_path.read_text())
        template = json.loads((prepare.ROOT / "templates/finalization_packet.json").read_text())
        summary = dict.fromkeys(template["worker_results"][0], "Recorded current-run result")
        summary.update({"Worker": "issue-evidence", "Outcome": "complete"})
        evidence = dict.fromkeys(template["evidence"][0], "Current issue")
        evidence["Evidence ID"] = "E-ISS-001"
        result = {"run_id": packet["identity"]["Run ID"], "worker_result": summary, "evidence": [evidence]}
        result_path = Path(prepared["worker_contracts"]["current_state_investigator"]["result"])
        result_path.write_text(json.dumps(result))
        merge_result(packet_path, "current_state_investigator")
        accepted = packet_path.read_bytes()
        merge_result(packet_path, "current_state_investigator")
        self.assertEqual(packet_path.read_bytes(), accepted)
        rejected = json.loads(accepted)
        rejected["identity"]["Lifecycle"] = "remediation"
        packet_path.write_text(json.dumps(rejected))
        before_rejection = packet_path.read_bytes()
        with self.assertRaisesRegex(ValueError, "planning_packet_required"):
            merge_result(packet_path, "current_state_investigator")
        self.assertEqual(packet_path.read_bytes(), before_rejection)
        packet_path.write_bytes(accepted)
        self.assertEqual(json.loads(accepted)["identity"], packet["identity"])
        result["evidence"][0]["Evidence ID"] = "E-FP-001"
        result_path.write_text(json.dumps(result))
        with self.assertRaisesRegex(ValueError, "row_invalid"):
            merge_result(packet_path, "current_state_investigator")
        self.assertEqual(packet_path.read_bytes(), accepted)
        result["run_id"] = "another run"
        result_path.write_text(json.dumps(result))
        with self.assertRaisesRegex(ValueError, "run_mismatch"):
            merge_result(packet_path, "current_state_investigator")
        self.assertEqual(packet_path.read_bytes(), accepted)

    def test_pre_release_nonterminal_record_still_checks_reasoning_graph(self):
        from contextlib import redirect_stdout
        import io
        record = self.root / "candidate.md"
        record.write_text("# Engineering Work Record\n\n# Run and Evaluation Identity\n\n"
                          "| Field | Value |\n| --- | --- |\n| State | in_progress |\n")
        output = io.StringIO()
        with redirect_stdout(output), self.assertRaises(SystemExit):
            validate_work_record(record, allow_unreleased=True)
        self.assertIn("populated Evidence, Claims, Decision Log, and Action Log", output.getvalue())


if __name__ == "__main__":
    unittest.main()
