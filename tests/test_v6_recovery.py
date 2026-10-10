"""Compose preparation, worker identity, rejected trace recovery and early handoff."""

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts import prepare_run as prepare
from scripts import validate_worker_runtime as runtime
from scripts.merge_techops_result import merge_result


ROOT = Path(__file__).resolve().parents[1]
PARENT = "00000000-0000-0000-0000-000000000001"
CHILD = "00000000-0000-0000-0000-000000000002"
START = "2026-10-09T20:00:00Z"
DISPATCH = "2026-10-09T20:00:10Z"
HANDLE = "/root/evidence"


class V6Recovery(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.inputs = self.root / "inputs.json"
        self.inputs.write_text(json.dumps({"schema_version": 1, "status": "explicit",
            "precedence_rule": prepare.DEFAULT_PRECEDENCE_RULE,
            "inputs": [{"Input ID": "IN-001", "Input or artifact": "Current issue",
                        "Source or path": "Current request", "Authority": "User",
                        "Classification": "work item", "Expected use": "Investigate", "Status": "Registered"}]}))

    def prepare(self, continuation=False, archive=False):
        return prepare.prepare_run(self.root, "ISSUE-1", "techops_issue_remediation", None, continuation,
                                   archive_stale_run=archive, input_manifest=self.inputs)

    def command(self, script, *arguments):
        return subprocess.run([sys.executable, str(ROOT / "scripts" / script), *map(str, arguments)],
                              capture_output=True, text=True)

    def test_fresh_archive_activation_merge_and_continuation_share_identity(self):
        prior = self.prepare()
        prior_id = json.loads(Path(prior["finalization_packet"]).read_text())["identity"]["Run ID"]
        run = self.prepare(archive=True)
        packet_path = Path(run["finalization_packet"])
        packet = json.loads(packet_path.read_text())
        self.assertNotEqual(packet["identity"]["Run ID"], prior_id)
        self.assertTrue(list((packet_path.parent / "runs").iterdir()))
        bundle = run["activation_packet_bundle"]
        assignment = self.root / "assignment.json"
        assignment.write_text(json.dumps({"objective": "Read current issue", "input_paths": [str(self.inputs)]}))
        guarded = self.command("validate_worker_runtime.py", "--activation-packet-bundle", bundle["path"],
                               "--expected-agent", "current_state_investigator", "--expected-bundle-sha256",
                               bundle["sha256"], "--assignment", assignment)
        self.assertEqual(guarded.returncode, 0, guarded.stdout + guarded.stderr)
        envelope = json.loads(json.loads(guarded.stdout)["activation_message"].splitlines()[1])
        self.assertEqual(envelope["run_id"], packet["identity"]["Run ID"])
        self.assertEqual(envelope["finalization_packet"], str(packet_path))
        self.assertNotIn("/runs/", envelope["finalization_packet"])
        template = json.loads((ROOT / "templates/finalization_packet.json").read_text())
        result = {"run_id": envelope["run_id"], "worker_result": {
            **dict.fromkeys(template["worker_results"][0], "Current-run evidence"),
            "Worker": "issue-evidence", "Outcome": "complete"}, "evidence": []}
        Path(envelope["worker_contract"]["result"]).write_text(json.dumps(result))
        merge_result(packet_path, "current_state_investigator")
        self.assertEqual(json.loads(packet_path.read_text())["worker_results"][0]["Worker"], "issue-evidence")
        continued = self.prepare(continuation=True)
        messages = json.loads(Path(continued["activation_packet_bundle"]["path"]).read_text())["packets"]
        self.assertTrue(all(row["run_id"] == envelope["run_id"] for row in messages.values()))

    def test_activation_rejects_missing_and_wrong_run_identity(self):
        run = self.prepare()
        path = Path(run["activation_packet_bundle"]["path"])
        original = json.loads(path.read_text())
        for identity in (None, "wrong-run"):
            bundle = json.loads(json.dumps(original))
            envelope = bundle["packets"]["current_state_investigator"]
            if identity is None:
                del envelope["run_id"]
                del envelope["finalization_packet"]
            else:
                envelope["run_id"] = identity
            path.write_text(json.dumps(bundle))
            errors = runtime.activation_packet_errors(path, "current_state_investigator",
                                                      hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertTrue(any("worker_run_identity" in error for error in errors), errors)

    def rejected_trace(self, run):
        root = Path(run["finalization_packet"]).parent
        parent = self.root / "parent.jsonl"
        rows = [{"timestamp": START, "type": "session_meta", "payload": {"id": PARENT}},
                {"timestamp": DISPATCH, "type": "response_item", "payload": {"type": "function_call",
                 "namespace": "collaboration", "name": "spawn_agent", "arguments": '{"task_name":"evidence"}'}},
                {"timestamp": "2026-10-09T20:00:11Z", "type": "event_msg", "payload": {"item": {
                 "type": "SubAgentActivity", "kind": "started", "agent_path": HANDLE, "agent_thread_id": CHILD}}}]
        parent.write_text("".join(json.dumps(row) + "\n" for row in rows))
        child = self.root / "child.jsonl"
        rows = [{"timestamp": START, "type": "session_meta", "payload": {"id": CHILD}},
                {"timestamp": "2026-10-09T20:01:00Z", "type": "response_item", "payload": {
                 "type": "custom_tool_call", "input": "find .thoughts/ISSUE-1/runs -type f"}}]
        child.write_text("".join(json.dumps(row) + "\n" for row in rows))
        observation = root / "observation.json"
        observation.write_text(json.dumps({"Provider handle": HANDLE, "Thread ID": CHILD,
            "Provider status": "completed", "Last dispatch at": DISPATCH, "Observed at": "2026-10-09T20:02:00Z",
            "Status source": "read_thread", "Latest turn started at": DISPATCH,
            "Latest turn status": "completed", "Thread status": "idle",
            "Binding evidence": {"activation_packet_delivered": True}}))
        trace = root / "issue_evidence_trace.json"
        exported = self.command("worker_runtime_evidence.py", "--provider-session", parent,
            "--parent-thread-id", PARENT, "--started-at", START, "--ledger", root / "runtime_dispatches.json",
            "--worker-session", child, "--observation", observation, "--agent", "current_state_investigator",
            "--trace", trace)
        self.assertEqual(exported.returncode, 2, exported.stdout + exported.stderr)
        self.assertIn("forbidden_context_reference:archived_artifact", exported.stdout)
        self.assertTrue((root / "runtime_dispatches.json").is_file())
        return trace

    def test_exported_rejection_allows_only_matching_completed_task_replacement(self):
        run = self.prepare()
        trace = self.rejected_trace(run)
        rejected = json.loads(trace.read_text())
        self.assertEqual(rejected["audit"]["status"], "rejected")
        self.assertEqual(rejected["events"][0]["guard_result"], "blocked")
        self.assertEqual(rejected["audit"]["errors"], runtime.trace_errors(rejected, require_freshness=True))
        command = ["--transition", "replace", "--provider-status", "completed", "--rejected-trace", trace,
                   "--provider-handle", HANDLE, "--last-dispatch-at", DISPATCH]
        allowed = self.command("validate_worker_runtime.py", *command)
        self.assertEqual(allowed.returncode, 0, allowed.stdout + allowed.stderr)
        for field, wrong in ((3, "running"), (7, "/root/other"), (9, START)):
            bad = list(command)
            bad[field] = wrong
            blocked = self.command("validate_worker_runtime.py", *bad)
            self.assertEqual(blocked.returncode, 2, blocked.stdout + blocked.stderr)
        blocked = self.command("validate_worker_runtime.py", "--transition", "replace", "--provider-status", "completed")
        self.assertEqual(blocked.returncode, 2)
        rejected["run_id"] = "old-run"
        trace.write_text(json.dumps(rejected))
        self.assertEqual(self.command("validate_worker_runtime.py", *command).returncode, 2)
        rejected["run_id"] = json.loads(Path(run["finalization_packet"]).read_text())["identity"]["Run ID"]
        rejected["tool_trace"] = []
        rejected["audit"]["errors"] = runtime.trace_errors(rejected, require_freshness=True)
        trace.write_text(json.dumps(rejected))
        self.assertEqual(self.command("validate_worker_runtime.py", *command).returncode, 2)
        rejected["audit"] = {"status": "passed", "errors": []}
        trace.write_text(json.dumps(rejected))
        self.assertEqual(self.command("validate_worker_runtime.py", *command).returncode, 2)

    def test_corrected_turn_excludes_rejected_activity_and_can_merge_current_result(self):
        run = self.prepare()
        rejected_path = self.rejected_trace(run)
        rejected_bytes = rejected_path.read_bytes()
        parent = self.root / "parent.jsonl"
        dispatch = "2026-10-09T20:03:00Z"
        with parent.open("a") as stream:
            stream.write(json.dumps({"timestamp": dispatch, "type": "response_item", "payload": {
                "type": "function_call", "namespace": "collaboration", "name": "followup_task",
                "arguments": '{"target":"evidence","message":"Reverify current-run evidence"}'}}) + "\n")
        child = self.root / "child.jsonl"
        with child.open("a") as stream:
            stream.write(json.dumps({"timestamp": "2026-10-09T20:03:30Z", "type": "response_item",
                "payload": {"type": "custom_tool_call", "input": "rg -n symbol current-source"}}) + "\n")
        root = rejected_path.parent
        observation_path = root / "observation.json"
        observation = json.loads(observation_path.read_text())
        observation.update({"Last dispatch at": dispatch, "Latest turn started at": dispatch,
                            "Observed at": "2026-10-09T20:04:00Z"})
        observation_path.write_text(json.dumps(observation))
        corrected_path = root / "corrected_issue_evidence_trace.json"
        exported = self.command("worker_runtime_evidence.py", "--provider-session", parent,
            "--parent-thread-id", PARENT, "--started-at", START, "--ledger", root / "runtime_dispatches.json",
            "--worker-session", child, "--observation", observation_path,
            "--agent", "current_state_investigator", "--trace", corrected_path)
        self.assertEqual(exported.returncode, 0, exported.stdout + exported.stderr)
        corrected = json.loads(corrected_path.read_text())
        self.assertEqual(corrected["audit"]["status"], "passed")
        self.assertEqual(len(corrected["tool_trace"]), 1)
        self.assertEqual(runtime.trace_errors(corrected, require_freshness=True), [])
        self.assertEqual(rejected_path.read_bytes(), rejected_bytes)
        overwrite = self.command("worker_runtime_evidence.py", "--provider-session", parent,
            "--parent-thread-id", PARENT, "--started-at", START, "--ledger", root / "runtime_dispatches.json",
            "--worker-session", child, "--observation", observation_path,
            "--agent", "current_state_investigator", "--trace", rejected_path)
        self.assertEqual(overwrite.returncode, 2)
        self.assertIn("requires_new_path", overwrite.stdout)
        self.assertEqual(rejected_path.read_bytes(), rejected_bytes)
        bundle = json.loads(Path(run["activation_packet_bundle"]["path"]).read_text())
        envelope = bundle["packets"]["current_state_investigator"]
        template = json.loads((ROOT / "templates/finalization_packet.json").read_text())
        result = {"run_id": envelope["run_id"], "worker_result": {
            **dict.fromkeys(template["worker_results"][0], "Reverified current-run evidence"),
            "Worker": "issue-evidence", "Outcome": "complete"}}
        Path(envelope["worker_contract"]["result"]).write_text(json.dumps(result))
        merge_result(Path(envelope["finalization_packet"]), "current_state_investigator")
        self.assertEqual(json.loads(Path(envelope["finalization_packet"]).read_text())[
            "worker_results"][0]["Outcome"], "complete")

    def test_binding_receipt_error_describes_expected_json_type(self):
        run = self.prepare()
        trace = self.rejected_trace(run)
        root = trace.parent
        observation_path = root / "observation.json"
        observation = json.loads(observation_path.read_text())
        observation["Binding evidence"] = "Envelope delivered"
        observation_path.write_text(json.dumps(observation))
        exported = self.command("worker_runtime_evidence.py", "--provider-session", self.root / "parent.jsonl",
            "--parent-thread-id", PARENT, "--started-at", START, "--ledger", root / "runtime_dispatches.json",
            "--worker-session", self.root / "child.jsonl", "--observation", observation_path,
            "--agent", "current_state_investigator", "--trace", trace)
        self.assertEqual(exported.returncode, 2)
        self.assertIn("expected JSON object, received str", exported.stdout)
        self.assertNotIn("Traceback", exported.stderr)

    def test_early_failure_keeps_rejected_artifacts_without_blank_claims_or_false_release(self):
        run = self.prepare()
        packet = Path(run["finalization_packet"])
        before = packet.read_bytes()
        trace = self.rejected_trace(run)
        contract = run["worker_contracts"]["current_state_investigator"]
        Path(contract["output"]).write_text("Rejected narrative; must not become a diagnosis")
        Path(contract["result"]).write_text('{"run_id":"not-provided"}')
        report = self.command("finalize_work_record.py", "--packet", packet,
                              "--workflow-failure", "forbidden_context_reference:archived_artifact")
        self.assertEqual(report.returncode, 2, report.stderr)
        for phrase in ("No accepted worker result", "Prepared workers without an accepted result",
                       "Unaccepted worker artifact", "runtime closure unverified", str(trace), contract["output"],
                       contract["result"], "handoff_failure.md", "Recorded engineering state: unknown"):
            self.assertIn(phrase, report.stdout)
        for phrase in ("Recorded proposed action", "owner: ;", "state: .", "runtime not released",
                       "inspect the recorded fix design", "Rejected narrative", "Tip:"):
            self.assertNotIn(phrase, report.stdout)
        self.assertEqual(packet.read_bytes(), before)
        saved = (packet.parent / "handoff_failure.md").read_text()
        self.assertEqual(saved.strip(), report.stdout.strip())
        response = self.root / "proposed_response.md"
        response.write_text(saved)
        canonical = packet.parent / "handoff_failure.md"
        self.assertEqual(subprocess.run(["cmp", "-s", canonical, response]).returncode, 0)
        for altered in ("Tip: unrelated skill\n" + saved, saved + "Additional summary\n"):
            response.write_text(altered)
            self.assertNotEqual(subprocess.run(["cmp", "-s", canonical, response]).returncode, 0)


if __name__ == "__main__":
    unittest.main()
