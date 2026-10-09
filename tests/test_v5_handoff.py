"""Producer/consumer, activation and terminal failure regressions from v5."""

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts import prepare_run as prepare
from scripts import validate_worker_runtime as runtime
from scripts import finalize_work_record as finalizer
from scripts.worker_runtime_evidence import export_worker_trace, read_runtime_events


ROOT = Path(__file__).resolve().parents[1]
CHILD = "00000000-0000-0000-0000-000000000002"
START = "2026-10-09T20:00:00Z"


class V5Handoff(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def prepare(self):
        manifest = self.root / "inputs.json"
        manifest.write_text(json.dumps({"schema_version": 1, "status": "explicit",
            "precedence_rule": prepare.DEFAULT_PRECEDENCE_RULE,
            "inputs": [{"Input ID": "IN-001", "Input or artifact": "Current issue",
                        "Source or path": "Current request", "Authority": "User",
                        "Classification": "work item", "Expected use": "Investigate", "Status": "Registered"}]}))
        return prepare.prepare_run(self.root, "ISSUE-1", "techops_issue_remediation", None, False,
                                   input_manifest=manifest)

    def test_prepared_documenter_contract_assigns_both_outputs(self):
        run = self.prepare()
        bundle = json.loads(Path(run["activation_packet_bundle"]["path"]).read_text())
        packet = bundle["packets"]["documenter"]
        contract = packet["worker_contract"]
        self.assertEqual(Path(contract["implementation_plan"]).name, "implementation_plan.md")
        self.assertEqual(Path(contract["output"]).name, "finalization_packet.json")
        self.assertIn("For TechOps planning", packet["developer_instructions"])
        self.assertIn("do not require Sentry", packet["developer_instructions"])
        self.assertIn("For Sentry planning, follow", packet["developer_instructions"])
        self.assertIn("create implementation_plan as well as output", contract["instructions"])
        fields = bundle["packets"]["solution_architect"]["worker_contract"]["result_instructions"]
        self.assertNotIn("plan_readiness", fields)
        self.assertIn("Work item evidence refs", bundle["packets"]["solution_architect"]["worker_contract"]["instructions"])

    def test_guard_returns_exact_payload_and_rejects_shortened_message(self):
        run = self.prepare()
        bundle = run["activation_packet_bundle"]
        assignment = self.root / "assignment.json"
        assignment.write_text(json.dumps({"objective": "Read the current issue", "input_paths": []}))
        command = [sys.executable, str(ROOT / "scripts/validate_worker_runtime.py"),
                   "--activation-packet-bundle", bundle["path"], "--expected-agent", "current_state_investigator",
                   "--expected-bundle-sha256", bundle["sha256"], "--assignment", str(assignment)]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        message = payload["activation_message"]
        self.assertEqual(payload["activation_message_sha256"], hashlib.sha256(message.encode()).hexdigest())
        envelope = json.loads(message.splitlines()[1])
        expected = json.loads(Path(bundle["path"]).read_text())["packets"]["current_state_investigator"]
        self.assertEqual(envelope, expected)
        saved = self.root / "outbound.txt"
        saved.write_text(message)
        result = subprocess.run(command + ["--activation-message", str(saved)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout)
        saved.write_text(message.replace(envelope["developer_instructions"].splitlines()[0], "shortened", 1))
        result = subprocess.run(command + ["--activation-message", str(saved)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("activation_message_mismatch", result.stdout)
        assignment.write_text(json.dumps({"objective": "handoff", "output": "packet only"}))
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("activation_assignment_invalid", result.stdout)

    def test_history_requires_distinct_patch_and_work_item_evidence(self):
        checks = [{"Check": name, "Status": "not_applicable" if name == "history_reconciliation" else "passed",
                   "Evidence refs": ["E-001"], "Detail": "Fixture has no history mismatch"}
                  for name in runtime.TECHOPS_CHECKS]
        history = next(row for row in checks if row["Check"] == "history_reconciliation")
        history.update({"Status": "passed", "Evidence refs": ["E-001", "E-002"],
                        "Commit": "abcdef012345", "Patch evidence refs": ["E-001"], "Work item": "ISSUE-2"})
        self.assertIn("techops_history_patch_and_work_item_required", runtime.techops_check_errors(checks, {"E-001", "E-002"}))
        history["Work item evidence refs"] = ["E-001"]
        self.assertIn("techops_history_distinct_sources_required", runtime.techops_check_errors(checks, {"E-001", "E-002"}))
        history["Work item evidence refs"] = ["E-002"]
        self.assertEqual(runtime.techops_check_errors(checks, {"E-001", "E-002"}), [])
        # Published Markdown must retain the proof, rather than dropping it at rendering.
        headers = ("Check", "Status", "Evidence refs", "Detail", "Commit", "Patch evidence refs", "Work item", "Work item evidence refs")
        table = finalizer._table(headers, [history])
        from scripts.validation.markdown import markdown_table
        parsed = markdown_table("# Checks\n\n" + table, "# Checks")[0]
        self.assertEqual(runtime.techops_check_errors([parsed] + [row for row in checks if row is not history], {"E-001", "E-002"}), [])

    def test_terminal_failure_preserves_prepared_run_without_documenter(self):
        run = self.prepare()
        packet_path = Path(run["finalization_packet"])
        packet = json.loads(packet_path.read_text())
        design = packet_path.parent / "fix_design.md"
        design.write_text("Recorded unapproved design")
        packet["worker_results"] = [{"Worker": "fix-design", "Outcome": "complete",
            "Unique contribution": "Proposed independent two-record Save/reload regression.",
            "Uncertainties / blockers": ["Production behavior is unverified."]}]
        packet["durable_artifacts"].append({"Artifact": "Fix design", "Path": str(design), "Status": "Accepted"})
        packet["actions"] = [{"Action": "Add the two-record regression", "Owner": "Implementer"}]
        packet["claims"] = [{"Claim ID": "CL-FD-001", "Claim": "Staged Update is a possible explanation",
                             "Confidence": "moderate", "Uncertainty": "Save action remains unverified"}]
        packet_path.write_text(json.dumps(packet))
        record = packet_path.parent / "work_record.md"
        before_packet, before_record = packet_path.read_bytes(), record.read_bytes()
        command = [sys.executable, str(ROOT / "scripts/finalize_work_record.py"), "--packet", str(packet_path),
                   "--workflow-failure", "activation_message_mismatch"]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2, result.stderr)
        for phrase in ("Workflow-framework validation: failed", "Workflow result:", "Engineering state:",
                       "What we established:", "Next action:", "Artifacts:", "Execution:", "Provenance:",
                       "two-record Save/reload", "Production behavior is unverified", "Add the two-record regression",
                       "activation_message_mismatch", "Not created", str(design)):
            self.assertIn(phrase, result.stdout)
        self.assertNotIn("Workflow-framework validation: passed", result.stdout)
        self.assertNotIn("No usable work summary", result.stdout)
        self.assertIn("confidence: moderate", result.stdout)
        self.assertIn("Save action remains unverified", result.stdout)
        self.assertEqual(record.read_bytes(), before_record)
        self.assertEqual(packet_path.read_bytes(), before_packet)
        receipt = json.loads((packet_path.parent / "finalization_failure.json").read_text())
        self.assertEqual(receipt["runtime_closure"], "unverified")
        self.assertEqual(receipt["packet_sha256"], hashlib.sha256(before_packet).hexdigest())
        self.assertEqual((packet_path.parent / "handoff_failure.md").read_text().strip(), result.stdout.strip())
        result = subprocess.run(command + ["--pre-release"], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)

    def test_exporter_and_fan_in_share_finalizer_trace_requirements(self):
        handle = "/root/evidence"
        ledger = {"thread_mappings": {handle: CHILD}, "events": [
            {"Provider handle": handle, "Thread ID": CHILD, "Last dispatch at": START}]}
        observation = {"Provider handle": handle, "Thread ID": CHILD, "Provider status": "completed",
            "Last dispatch at": START, "Observed at": "2026-10-09T20:02:00Z", "Status source": "read_thread",
            "Latest turn started at": START, "Latest turn status": "completed", "Thread status": "idle",
            "Binding evidence": {"activation_packet_delivered": True}}
        source = self.root / "child.jsonl"
        rows = [{"timestamp": START, "type": "session_meta", "payload": {"id": CHILD}},
                {"timestamp": "2026-10-09T20:01:00Z", "type": "response_item",
                 "payload": {"type": "custom_tool_call", "input": "rg -n symbol source"}},
                {"timestamp": "2026-10-09T20:01:30Z", "type": "response_item",
                 "payload": {"type": "message", "content": "Private non-tool context"}}]
        source.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
        trace = export_worker_trace(ledger, source, "current_state_investigator", observation)
        self.assertEqual(trace["last_dispatch_at"], START)
        self.assertEqual(len(trace["tool_trace"]), 1)
        self.assertEqual(runtime.trace_errors(trace, require_freshness=True), [])
        self.assertEqual(runtime.trace_errors([], require_freshness=True), ["tool_trace_invalid"])
        self.assertEqual(runtime.trace_errors({"events": None}), ["runtime_event_invalid"])
        invalid = self.root / "invalid.json"
        invalid.write_text("not JSON")
        result = subprocess.run([sys.executable, str(ROOT / "scripts/validate_worker_runtime.py"),
                                 "--trace", str(invalid), "--require-freshness"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("tool_trace_invalid", result.stdout)
        self.assertNotIn("Traceback", result.stderr)
        broken = copy.deepcopy(trace)
        del broken["last_dispatch_at"]
        self.assertIn("worker_trace_dispatch_required", runtime.trace_errors(broken, require_freshness=True))
        broken = copy.deepcopy(observation)
        broken["Latest turn status"] = "in_progress"
        with self.assertRaisesRegex(ValueError, "not_completed"):
            export_worker_trace(ledger, source, "current_state_investigator", broken)
        ledger["events"][-1]["Last dispatch at"] = "2026-10-09T20:01:00Z"
        with self.assertRaisesRegex(ValueError, "dispatch_mismatch"):
            export_worker_trace(ledger, source, "current_state_investigator", observation)

    def test_timing_counts_overlapping_workers_once(self):
        parent = "00000000-0000-0000-0000-000000000001"
        rows = [{"timestamp": START, "type": "session_meta", "payload": {"id": parent}}]
        for time, handle, kind in (("20:00:10", "/root/a", "started"),
                                   ("20:00:30", "/root/b", "started"),
                                   ("20:01:00", "/root/a", "completed"),
                                   ("20:01:30", "/root/b", "completed")):
            rows.append({"timestamp": "2026-10-09T" + time + "Z", "type": "event_msg",
                         "payload": {"item": {"type": "SubAgentActivity", "kind": kind,
                                             "agent_path": handle, "agent_thread_id": CHILD}}})
        rows.append({"timestamp": "2026-10-09T20:02:00Z", "type": "event_msg", "payload": {}})
        source = self.root / "parent.jsonl"
        source.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
        timing = read_runtime_events(source, parent, START)["timing"]
        self.assertEqual(timing["elapsed_seconds"], 120)
        self.assertEqual(timing["worker_active_seconds"], 80)
        self.assertEqual(timing["no_worker_active_seconds"], 40)
        self.assertEqual(timing["open_worker_intervals"], 0)
