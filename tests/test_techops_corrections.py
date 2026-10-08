"""Regressions for native status reads and TechOps blocked publication."""

import copy
import json
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

    def test_techops_label(self):
        packet = {"identity": {"Playbook / version": "playbooks/techops_issue_remediation.md / 0.5.3"},
                  "playbook_selection": {"Primary goal": "Issue remediation"}}
        self.assertEqual(finalizer._blocked_snapshot_label(packet), "TechOps planning")


if __name__ == "__main__":
    unittest.main()
