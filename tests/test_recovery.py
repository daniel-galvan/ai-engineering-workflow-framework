"""Compose preparation, worker identity, rejected trace recovery and early handoff."""

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from scripts import prepare_run as prepare
from scripts import validate_worker_runtime as runtime
from scripts.merge_techops_result import merge_result
from tests.worker_response_support import stage_worker_response


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
        self.preparation_count = 0
        self.inputs = self.root / "inputs.json"
        self.inputs.write_text(json.dumps({"schema_version": 1, "status": "explicit",
            "precedence_rule": prepare.DEFAULT_PRECEDENCE_RULE,
            "inputs": [{"Input ID": "IN-001", "Input or artifact": "Current issue",
                        "Source or path": "Current request", "Authority": "User",
                        "Classification": "work item", "Expected use": "Investigate", "Status": "Registered"}]}))

    def prepare(self, continuation=False, archive=False):
        start = datetime.fromisoformat(START.replace("Z", "+00:00")) + timedelta(microseconds=self.preparation_count)
        self.preparation_count += 1
        with patch.object(prepare, "datetime", wraps=datetime) as clock:
            clock.now.return_value = start
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
        trace_path, _ = stage_worker_response(run, "current_state_investigator", result)
        merge_result(packet_path, "current_state_investigator", trace=trace_path)
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
                 "namespace": "collaboration", "name": "spawn_agent", "arguments": json.dumps({"task_name": "evidence",
                    "fork_turns": "none", "model": "gpt-6-luna", "reasoning_effort": "high"})}},
                {"timestamp": "2026-10-09T20:00:11Z", "type": "event_msg", "payload": {"item": {
                 "type": "SubAgentActivity", "kind": "started", "agent_path": HANDLE, "agent_thread_id": CHILD}}}]
        parent.write_text("".join(json.dumps(row) + "\n" for row in rows))
        child = self.root / "child.jsonl"
        rows = [{"timestamp": START, "type": "session_meta", "payload": {"id": CHILD}},
                {"timestamp": "2026-10-09T20:01:00Z", "type": "response_item", "payload": {
                 "type": "custom_tool_call", "input": "find .thoughts/ISSUE-1/runs -type f"}},
                {"timestamp": "2026-10-09T20:01:20Z", "type": "turn_context", "payload": {
                 "turn_id": "00000000-0000-0000-0000-000000000004", "model": "gpt-6-luna", "effort": "high"}},
                {"timestamp": "2026-10-09T20:01:30Z", "type": "response_item", "payload": {
                 "type": "message", "role": "assistant", "phase": "final_answer",
                 "content": [{"type": "output_text", "text": json.dumps({"output": "Rejected archived evidence",
                     "result": {"run_id": json.loads(Path(run["finalization_packet"]).read_text())[
                         "identity"]["Run ID"], "worker_result": {"Worker": "issue-evidence",
                         "Outcome": "complete"}, "evidence": []}})}]}}]
        child.write_text("".join(json.dumps(row) + "\n" for row in rows))
        observation = root / "observation.json"
        observation.write_text(json.dumps({"Provider handle": HANDLE, "Thread ID": CHILD,
            "Provider status": "completed", "Last dispatch at": DISPATCH, "Observed at": "2026-10-09T20:02:00Z",
            "Status source": "read_thread", "Latest turn started at": "2026-10-09T20:01:20Z",
            "Latest turn completed at": "2026-10-09T20:01:30Z",
            "Latest turn status": "completed", "Thread status": "idle",
            "Binding evidence": {"activation_packet_delivered": True}}))
        trace = root / "issue_evidence_trace.json"
        exported = self.command("worker_runtime_evidence.py", "--provider-session", parent,
            "--parent-thread-id", PARENT, "--started-at", START, "--ledger", root / "runtime_dispatches.json",
            "--worker-session", child, "--observation", observation, "--agent", "current_state_investigator",
            "--trace", trace)
        self.assertEqual(exported.returncode, 2, exported.stdout + exported.stderr)
        self.assertIn("forbidden_context_reference:archived_artifact", exported.stdout)
        violation = json.loads(exported.stdout)["context_violations"][0]
        self.assertEqual(violation["error"], "forbidden_context_reference:archived_artifact")
        self.assertEqual(violation["trace_path"], ["tool_trace", "0", "input"])
        self.assertIn(".thoughts/ISSUE-1/runs", violation["reference"])
        self.assertNotIn("command", violation)
        self.assertEqual(json.loads(trace.read_text())["audit"]["context_violations"][0], violation)
        self.assertTrue((root / "runtime_dispatches.json").is_file())
        return trace

    def test_exported_trace_preserves_completed_result_hash(self):
        run = self.prepare()
        trace = json.loads(self.rejected_trace(run).read_text())
        receipt = trace["result_artifact"]
        staged = Path(receipt["path"])
        self.assertNotEqual(staged, Path(run["worker_contracts"]["current_state_investigator"]["result"]))
        self.assertEqual(receipt["sha256"], hashlib.sha256(staged.read_bytes()).hexdigest())

    def test_recovery_rejects_manually_added_launch_errors(self):
        run = self.prepare()
        trace = self.rejected_trace(run)
        value = json.loads(trace.read_text())
        value["launch_errors"].append("assignment_scope_violation: manually inserted")
        value["audit"]["errors"] = runtime.trace_errors(value, require_freshness=True)
        trace.write_text(json.dumps(value))
        result = self.command("validate_worker_runtime.py", "--transition", "replace",
            "--provider-status", "completed", "--rejected-trace", trace,
            "--provider-handle", HANDLE, "--last-dispatch-at", DISPATCH)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("rejected_result_launch_errors_mismatch", result.stdout)

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
        rejected["audit"]["errors"] = []
        trace.write_text(json.dumps(rejected))
        self.assertEqual(self.command("validate_worker_runtime.py", *command).returncode, 2)
        rejected["audit"] = {"status": "passed", "errors": []}
        trace.write_text(json.dumps(rejected))
        self.assertEqual(self.command("validate_worker_runtime.py", *command).returncode, 2)

    def test_prepared_worker_names_resolve_for_every_playbook(self):
        for index, playbook in enumerate(sorted(prepare.PLAYBOOKS)):
            with self.subTest(playbook=playbook):
                run = prepare.prepare_run(self.root, "CASE-" + str(index), playbook, None, False,
                    input_manifest=self.inputs,
                    primary_question="Which boundary owns this behavior?" if playbook == "technical_spike" else None,
                    started_at=datetime.now(UTC).isoformat() if playbook == "technical_spike" else None)
                for role in run["bindings"]:
                    self.assertEqual(runtime.worker_binding(run, role), role)
                for role, contract in run.get("worker_contracts", {}).items():
                    if not isinstance(contract, dict):
                        continue
                    worker = contract.get("worker") or contract.get("worker_id")
                    if worker:
                        bound = runtime.worker_binding(run, worker)
                        self.assertIn(bound, run["bindings"])
                        if role in run["bindings"]:
                            self.assertEqual(bound, role)

    def test_replacement_transition_resolves_logical_worker_roles(self):
        run = self.prepare()
        trace = self.rejected_trace(run)
        value = json.loads(trace.read_text())
        value["spawn"]["agent"] = "issue-evidence"
        value["spawn"].pop("binding_agent", None)
        value["audit"]["errors"] = runtime.trace_errors(value, require_freshness=True)
        trace.write_text(json.dumps(value))
        allowed = self.command("validate_worker_runtime.py", "--transition", "replace",
            "--provider-status", "completed", "--rejected-trace", trace,
            "--provider-handle", HANDLE, "--last-dispatch-at", DISPATCH)
        self.assertEqual(allowed.returncode, 0, allowed.stdout + allowed.stderr)

    def test_replacement_transition_does_not_authorize_an_ordinary_activation(self):
        run = self.prepare()
        trace = self.rejected_trace(run)
        bundle = run["activation_packet_bundle"]
        transition = self.command("validate_worker_runtime.py", "--transition", "replace",
            "--provider-status", "completed", "--rejected-trace", trace,
            "--provider-handle", HANDLE, "--last-dispatch-at", DISPATCH)
        self.assertEqual(transition.returncode, 0, transition.stdout + transition.stderr)
        self.assertIn("corrected activation", json.loads(transition.stdout)["next_action"])
        assignment = self.root / "retry.json"
        assignment.write_text(json.dumps({"objective": "Reverify rejected evidence"}))
        dispatch = Path(run["artifact_root"]) / "retry.txt"
        activation = ["--activation-packet-bundle", bundle["path"], "--expected-agent", "current_state_investigator",
            "--expected-bundle-sha256", bundle["sha256"], "--assignment", assignment, "--dispatch-file", dispatch]
        blocked = self.command("validate_worker_runtime.py", *activation)
        self.assertEqual(blocked.returncode, 2)
        self.assertFalse(dispatch.exists())
        guidance = json.loads(blocked.stdout)["recovery_required"]
        self.assertEqual(guidance["rejected_trace"], str(trace.resolve()))
        self.assertEqual(guidance["provider_handle"], HANDLE)
        self.assertIn("--provider-status", guidance["required_options"])
        corrected = self.command("validate_worker_runtime.py", *activation, "--rejected-trace", trace,
            "--provider-handle", HANDLE, "--last-dispatch-at", DISPATCH, "--provider-status", "completed")
        self.assertEqual(corrected.returncode, 0, corrected.stdout + corrected.stderr)
        self.assertTrue(dispatch.is_file())
        repeated = self.command("validate_worker_runtime.py", *activation, "--rejected-trace", trace,
            "--provider-handle", HANDLE, "--last-dispatch-at", DISPATCH, "--provider-status", "completed")
        self.assertEqual(repeated.returncode, 2)
        self.assertIn("activation_repair_limit_reached", repeated.stdout)

    def test_recovery_does_not_overwrite_a_different_rejected_output(self):
        run = self.prepare()
        rejected_path = self.rejected_trace(run)
        bundle = run["activation_packet_bundle"]
        packet = json.loads(Path(bundle["path"]).read_text())["packets"]["current_state_investigator"]
        output = Path(packet["worker_contract"]["output"])
        output.write_text("New rejected output")
        archived = output.with_name(output.stem + ".rejected" + output.suffix)
        archived.write_text("Earlier rejected output")
        assignment = self.root / "correction.json"
        assignment.write_text(json.dumps({"objective": "Reverify current evidence"}))
        guarded = self.command("validate_worker_runtime.py", "--activation-packet-bundle", bundle["path"],
            "--expected-agent", "current_state_investigator", "--expected-bundle-sha256", bundle["sha256"],
            "--assignment", assignment, "--dispatch-file", Path(run["artifact_root"]) / "correction.txt",
            "--rejected-trace", rejected_path, "--provider-handle", HANDLE, "--last-dispatch-at", DISPATCH,
            "--provider-status", "completed")
        self.assertEqual(guarded.returncode, 2)
        self.assertIn("recovery_rejected_output_conflict", guarded.stdout)
        self.assertEqual(output.read_text(), "New rejected output")
        self.assertEqual(archived.read_text(), "Earlier rejected output")

    def test_fresh_replacement_preserves_rejected_activity_and_can_merge_current_result(self):
        run = self.prepare()
        rejected_path = self.rejected_trace(run)
        bundle = run["activation_packet_bundle"]
        assignment = self.root / "corrected_assignment.json"
        assignment.write_text(json.dumps({"objective": "Reverify the rejected evidence", "input_paths": []}))
        envelope = json.loads(Path(bundle["path"]).read_text())["packets"]["current_state_investigator"]
        outputs = [Path(envelope["worker_contract"][field]) for field in ("output", "result")]
        for output in outputs:
            output.write_text("Rejected analytical output")
        guarded = self.command("validate_worker_runtime.py", "--activation-packet-bundle", bundle["path"],
            "--expected-agent", "current_state_investigator", "--expected-bundle-sha256", bundle["sha256"],
            "--assignment", assignment, "--dispatch-file", Path(run["artifact_root"]) / "activation_corrected.txt",
            "--rejected-trace", rejected_path, "--provider-handle", HANDLE, "--last-dispatch-at", DISPATCH,
            "--provider-status", "completed")
        self.assertEqual(guarded.returncode, 0, guarded.stdout + guarded.stderr)
        for output in outputs:
            self.assertFalse(output.exists())
            self.assertEqual(output.with_name(output.stem + ".rejected" + output.suffix).read_text(),
                             "Rejected analytical output")
        rejected_bytes = rejected_path.read_bytes()
        parent = self.root / "parent.jsonl"
        dispatch = "2026-10-09T20:03:00Z"
        fresh_handle = "/root/evidence_retry"
        fresh_child = "00000000-0000-0000-0000-000000000003"
        with parent.open("a") as stream:
            stream.write(json.dumps({"timestamp": dispatch, "type": "response_item", "payload": {
                "type": "function_call", "namespace": "collaboration", "name": "spawn_agent",
                "arguments": json.dumps({"task_name": "evidence_retry", "message": json.loads(guarded.stdout)["activation_message"],
                    "fork_turns": "none", "model": "gpt-6-luna", "reasoning_effort": "high"})}}) + "\n")
            stream.write(json.dumps({"timestamp": dispatch, "type": "event_msg", "payload": {"item": {
                "type": "SubAgentActivity", "kind": "started", "agent_path": fresh_handle,
                "agent_thread_id": fresh_child}}}) + "\n")
        child = self.root / "fresh_child.jsonl"
        contract_path = Path(run["artifact_root"]) / "activation_corrected.txt"
        template = json.loads((ROOT / "templates/finalization_packet.json").read_text())
        result = {"run_id": envelope["run_id"], "worker_result": {
            **dict.fromkeys(template["worker_results"][0], "Reverified current-run evidence"),
            "Worker": "issue-evidence", "Outcome": "complete"}, "evidence": []}
        child.write_text("\n".join(json.dumps(row) for row in [
            {"timestamp": dispatch, "type": "session_meta", "payload": {"id": fresh_child}},
            {"timestamp": "2026-10-09T20:03:30Z", "type": "response_item", "payload": {
                "type": "custom_tool_call", "call_id": "contract", "input":
                'await tools.exec_command(' + json.dumps({"cmd": "cat " + str(contract_path)}) + ')'}},
            {"timestamp": "2026-10-09T20:03:31Z", "type": "response_item", "payload": {
                "type": "custom_tool_call_output", "call_id": "contract", "output": contract_path.read_text()}},
            {"timestamp": "2026-10-09T20:03:32Z", "type": "turn_context", "payload": {
                "turn_id": "00000000-0000-0000-0000-000000000005", "model": "gpt-6-luna", "effort": "high"}},
            {"timestamp": "2026-10-09T20:03:33Z", "type": "response_item", "payload": {
                "type": "message", "role": "assistant", "phase": "final_answer",
                "content": [{"type": "output_text", "text": json.dumps({
                    "output": "Corrected current-run evidence", "result": result})}]}}
        ]) + "\n")
        root = rejected_path.parent
        observation_path = root / "observation.json"
        observation = json.loads(observation_path.read_text())
        observation.update({"Provider handle": fresh_handle, "Thread ID": fresh_child,
                            "Last dispatch at": dispatch, "Latest turn started at": "2026-10-09T20:03:32Z",
                            "Latest turn completed at": "2026-10-09T20:03:33Z",
                            "Observed at": "2026-10-09T20:04:00Z"})
        observation.pop("Binding evidence")
        observation_path.write_text(json.dumps(observation))
        corrected_path = root / "corrected_issue_evidence_trace.json"
        exported = self.command("worker_runtime_evidence.py", "--provider-session", parent,
            "--parent-thread-id", PARENT, "--started-at", START, "--ledger", root / "runtime_dispatches.json",
            "--worker-session", child, "--observation", observation_path,
            "--agent", "current_state_investigator", "--trace", corrected_path)
        self.assertEqual(exported.returncode, 0, exported.stdout + exported.stderr)
        corrected = json.loads(corrected_path.read_text())
        self.assertEqual(corrected["audit"]["status"], "passed")
        self.assertEqual(len(corrected["tool_trace"]), 2)
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
        packet_path = Path(run["finalization_packet"])
        packet = json.loads(packet_path.read_text())
        self.assertEqual(packet["runtime_audits"][0]["Trace path"], str(corrected_path))
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
