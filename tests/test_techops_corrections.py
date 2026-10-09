"""Regressions for native status reads and TechOps blocked publication."""

import copy
import json
import io
import subprocess
from contextlib import redirect_stdout
from unittest.mock import patch
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import finalize_work_record as finalizer
import validate_worker_runtime as runtime


class TechOpsCorrections(unittest.TestCase):
    def test_targeted_terminal_reads_cover_omitted_workers(self):
        observations = [{
            "Provider handle": f"/root/{worker}", "Provider status": "completed",
            "Last dispatch at": "2026-10-07T23:40:00Z", "Observed at": "2026-10-07T23:53:10Z",
            "Status source": "read_thread", "Thread ID": f"00000000-0000-0000-0000-{index:012d}",
            "Latest turn started at": "2026-10-07T23:40:01Z", "Latest turn status": "completed",
            "Thread status": "notLoaded",
        } for index, worker in enumerate(("evidence", "failure", "integration", "design", "handoff"))]
        handles = [row["Provider handle"] for row in observations]
        self.assertEqual(runtime.terminal_observation_errors(observations, handles), [])
        self.assertTrue(runtime.terminal_observation_errors(observations[2:], handles))
        stale = copy.deepcopy(observations)
        stale[0]["Last dispatch at"] = "2026-10-07T23:54:00Z"
        self.assertTrue(runtime.terminal_observation_errors(stale, handles))
        running = copy.deepcopy(observations)
        running[0]["Provider status"] = "running"
        self.assertTrue(runtime.terminal_observation_errors(running, handles))
        unavailable = copy.deepcopy(observations)
        unavailable[0]["Status source"] = "historical completion"
        self.assertTrue(runtime.terminal_observation_errors(unavailable, handles))
        historical = copy.deepcopy(observations)
        historical[0]["Latest turn started at"] = "2026-10-07T23:39:00Z"
        self.assertTrue(runtime.terminal_observation_errors(historical, handles))
        queued = copy.deepcopy(observations)
        queued[0]["Thread status"] = "inProgress"
        self.assertTrue(runtime.terminal_observation_errors(queued, handles))
        precise = copy.deepcopy(observations)
        precise[0]["Last dispatch at"] = "2026-10-07T23:40:01.900Z"
        self.assertEqual(runtime.terminal_observation_errors(precise, handles), [])

    def test_planning_checks_require_supported_evidence(self):
        checks = [{"Check": name, "Status": "passed", "Evidence refs": "E-001",
                   "Detail": "Current-run owning worker evidence"} for name in runtime.TECHOPS_CHECKS]
        self.assertEqual(runtime.techops_check_errors(checks, {"E-001"}), [])
        self.assertTrue(runtime.techops_check_errors(checks[:-1], {"E-001"}))
        checks[0]["Evidence refs"] = "E-999"
        self.assertTrue(runtime.techops_check_errors(checks, {"E-001"}))

    def test_missing_trace_retrieval_is_not_an_audit(self):
        packet = {
            "identity": {"Playbook / version": "playbooks/techops_issue_remediation.md / 0.5.3",
                         "Lifecycle": "planning"},
            "worker_results": [{"Worker": "fix-design", "Outcome": "complete"}],
            "evidence": [{"Evidence ID": "E-001"}],
            "techops_checks": [{"Check": name, "Status": "passed", "Evidence refs": "E-001",
                                "Detail": "Owning worker evidence"} for name in runtime.TECHOPS_CHECKS],
            "runtime_audits": [{"Worker": "fix-design", "Provider handle": "/root/design",
                                "Provider status": "completed", "Last dispatch at": "2026-10-07T23:40:00Z",
                                "Observed at": "2026-10-07T23:53:10Z", "Status source": "list_agents"}],
        }
        errors = finalizer._techops_planning_contract_errors(packet, Path("/tmp/finalization_packet.json"))
        self.assertIn("worker_trace_retrieval_evidence_required:fix-design", errors)
        packet["runtime_audits"][0]["Trace retrieval"] = "unavailable: read_thread returned permission_denied"
        packet["worker_results"][0]["Uncertainties / blockers"] = "context-unverified"
        self.assertEqual(finalizer._techops_planning_contract_errors(packet, Path("/tmp/packet.json")), [])

        with tempfile.TemporaryDirectory(prefix="techops-audit-") as directory:
            packet_path = Path(directory) / "packet.json"
            trace_path = packet_path.with_name("trace.json")
            packet["runtime_audits"][0]["Trace path"] = str(trace_path)
            trace = {"spawn": {"activation_packet_delivered": True}, "tool_trace": [],
                     "last_dispatch_at": "2026-10-07T23:40:00Z"}
            trace_path.write_text(json.dumps(trace))
            self.assertIn("worker_fan_in_guard_receipt_required:fix-design",
                          finalizer._techops_planning_contract_errors(packet, packet_path))
            trace["events"] = [{"action": "fan_in", "provider_status": "completed"}]
            trace["tool_trace"] = [{"tool": "exec_command", "arguments": {"cmd": "cat /tmp/.codex/memories/MEMORY.md"}}]
            trace_path.write_text(json.dumps(trace))
            self.assertTrue(any("forbidden_context_reference" in error
                                for error in finalizer._techops_planning_contract_errors(packet, packet_path)))
            trace["tool_trace"] = []
            trace["last_dispatch_at"] = "2026-10-07T23:39:00Z"
            trace_path.write_text(json.dumps(trace))
            self.assertIn("worker_trace_stale:fix-design",
                          finalizer._techops_planning_contract_errors(packet, packet_path))

    def test_blocked_publication_has_one_schema_status(self):
        packet = {
            "identity": {"State": "blocked", "Finalization schema": "Pending"},
            "finalization": {"Finalization schema": "Pending"}, "durable_artifacts": [],
            "handoff": {"execution": "no source changes; awaiting Coordinator packet validation and packaged finalization; runtime not released"},
        }
        finalizer._reconcile_runtime_state(packet, [{"Runtime status": "Blocked"}])
        self.assertNotIn("Finalization schema", packet["identity"])
        self.assertEqual(packet["finalization"]["Finalization schema"], "Passed for blocked work record")
        self.assertNotIn("awaiting Coordinator", packet["handoff"]["execution"])
        self.assertIn("runtime not released", packet["handoff"]["execution"])

    def test_techops_summary_is_not_a_readiness_token(self):
        packet = {"identity": {"Playbook / version": "playbooks/techops_issue_remediation.md / 0.5.20"},
                  "handoff": {"workflow_result": "The source stages edits; a draft-only persistence plan is proposed; production is unverified.",
                              "implementation_plan": "/tmp/implementation_plan.md", "execution": "planning only",
                              "provenance": "techops_issue_remediation", "established": ["The callback stages edits."],
                              "artifacts": ["/tmp/plan.md"],
                              "next_action": {"owner": "Coordinator", "action": "Reconcile runtime proof",
                                              "complete_when": "Fresh worker observations are available"}}}
        finalizer._validate_handoff(packet, check_provenance=False)
        for token in ("ready_for_implementation", "Ready for implementation", "blocked", "designed", "plan_only"):
            with self.subTest(token=token):
                packet["handoff"]["workflow_result"] = token
                with self.assertRaisesRegex(ValueError, "plain-language work summary"):
                    finalizer._validate_handoff(packet, check_provenance=False)
        packet["identity"]["Playbook / version"] = "playbooks/feature_delivery.md / 0.5.20"
        finalizer._validate_handoff(packet, check_provenance=False)

    def test_terminal_failure_preserves_work_summary_without_publishing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packet_path = root / "finalization_packet.json"
            packet = {"identity": {"Engineering state": "designed"}, "handoff": {
                "workflow_result": "Source stages metadata; a draft-save plan is proposed; production remains unverified.",
                "implementation_plan": str(root / "implementation_plan.md"),
                "established": ["The update path carries name, description and subject."],
                "best_current_explanations": [{"explanation": "Dialog update was staged", "confidence": "medium",
                                               "reason": "Source trace only"}],
                "next_action": {"owner": "Engineering", "action": "Confirm Save sequence", "complete_when": "Fresh read agrees"},
                "artifacts": [str(root / "fix_design.md")], "execution": "No source changes or tests",
                "provenance": "fixture; not independently audited"}}
            packet_path.write_text(json.dumps(packet))
            record = root / "work_record.md"
            record.write_text("prepared skeleton\n")
            before = packet_path.read_bytes()
            receipt = root / "finalization_failure.json"
            receipt.write_text(json.dumps({"status": "failed", "errors": ["terminal_observation_stale"]}))
            output = io.StringIO()
            arguments = ["finalizer", "--packet", str(packet_path), "--closure", str(root / "runtime_closure.json"),
                         "--record", str(record)]
            with patch.object(sys, "argv", arguments), patch.object(finalizer, "finalize", side_effect=ValueError("terminal_observation_stale")), redirect_stdout(output):
                self.assertEqual(finalizer.main(), 2)
            text = output.getvalue()
            for label in ("Workflow-framework validation: failed", "Workflow result:", "Engineering state:",
                          "What we established:", "Best current explanations:", "Next action:", "Complete when:",
                          "Artifacts:", "Execution:", "Provenance:"):
                self.assertIn(label, text)
            for detail in ("name, description and subject", "Dialog update was staged", "confidence: medium",
                           "Confirm Save sequence", "terminal_observation_stale", str(receipt)):
                self.assertIn(detail, text)
            self.assertNotIn("Workflow-framework validation: passed", text)
            self.assertNotIn("Tip: Developer Workflows", text)
            self.assertIn("unverified", text)
            self.assertEqual(record.read_text(), "prepared skeleton\n")
            self.assertEqual(packet_path.read_bytes(), before)
            for flag in ("--check-packet", "--pre-release"):
                with patch.object(sys, "argv", arguments + [flag]), patch.object(finalizer, "finalize", side_effect=ValueError("failure")), redirect_stdout(io.StringIO()) as feedback:
                    self.assertEqual(finalizer.main(), 2)
                self.assertNotIn("What we established:", feedback.getvalue())
            packet["handoff"]["workflow_result"] = "Ready for implementation"
            packet_path.write_text(json.dumps(packet))
            failed_summary = finalizer.failure_handoff(packet_path, "invalid result token")
            self.assertIn("Provisional work summary: The update path", failed_summary)
            self.assertNotIn("Provisional work summary: Ready for implementation", failed_summary)
            packet_path.write_text("[]")
            self.assertIn("No usable work summary", finalizer.failure_handoff(packet_path, "invalid packet"))
            packet["handoff"]["artifacts"].append("invalid\0path")
            packet_path.write_text(json.dumps(packet))
            self.assertIn("Unrenderable recorded artifact", finalizer.failure_handoff(packet_path, "invalid artifact"))
            packet["handoff"]["artifacts"].pop()
            packet_path.write_text("not JSON")
            self.assertIn("validation: failed", finalizer.failure_handoff(packet_path, "invalid JSON"))
            # Exercise the real CLI failure route, without mocked publication.
            packet_path.write_text(json.dumps(packet))
            result = subprocess.run([sys.executable, str(finalizer.ROOT / "scripts/finalize_work_record.py"),
                                     *arguments[1:]], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn("What we established:", result.stdout)
            self.assertEqual(record.read_text(), "prepared skeleton\n")

    def test_followup_requires_matching_fresh_audit_and_closure(self):
        audit = {"Worker": "handoff", "Provider handle": "/root/handoff", "Provider status": "completed",
                 "Last dispatch at": "2026-10-09T02:23:38Z", "Observed at": "2026-10-09T02:18:00Z",
                 "Status source": "list_agents", "Trace path": "",
                 "Trace retrieval": "unavailable: no provider thread UUID mapping"}
        packet = {"runtime_audits": [audit], "worker_results": [{"Worker": "handoff",
                  "Uncertainties / blockers": "context-unverified"}],
                  "terminal_observations": [{**audit, "Last dispatch at": "2026-10-09T02:19:39Z"}]}
        path = Path("/tmp/packet.json")
        errors = finalizer._worker_runtime_audit_errors(packet, path, {"handoff"})
        self.assertIn("terminal_closure_worker_audit_stale", errors)
        self.assertIn("terminal_observation_stale:/root/handoff", errors)
        audit["Observed at"] = "2026-10-09T02:25:00Z"
        packet["terminal_observations"] = [dict(audit)]
        self.assertEqual(finalizer._worker_runtime_audit_errors(packet, path, {"handoff"}), [])
        # Thread tools require an actual UUID even when the collaboration handle is valid.
        audit.update({"Status source": "read_thread", "Thread ID": "/root/handoff"})
        self.assertIn("terminal_observation_thread_id_required:/root/handoff",
                      runtime.terminal_observation_errors([audit], ["/root/handoff"]))

    def test_techops_label(self):
        packet = {"identity": {"Playbook / version": "playbooks/techops_issue_remediation.md / 0.5.3"},
                  "playbook_selection": {"Primary goal": "Issue remediation"}}
        self.assertEqual(finalizer._blocked_snapshot_label(packet), "TechOps planning")


if __name__ == "__main__":
    unittest.main()
