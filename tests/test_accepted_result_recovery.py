"""Exercise recovery bounds without altering an actual TechOps run."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import accepted_result_recovery as recovery


class AcceptedResultRecovery(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.role = "current_state_investigator"
        self.handle = "/root/issue"
        self.old_time = "2026-11-02T19:00:00Z"
        self.new_time = "2026-11-02T20:00:00Z"
        self.worker = {"Worker": "issue-evidence", "Outcome": "complete"}
        self.write("result.json", {"run_id": "ITEM-1", "worker_result": self.worker})
        (self.root / "output.md").write_text("Accepted evidence")
        self.write("staged.json", {"run_id": "ITEM-1", "worker_result": self.worker})
        (self.root / "staged.md").write_text("Accepted evidence")
        self.write("trace.json", {"last_dispatch_at": self.old_time, "result_artifact": {
            "path": str(self.root / "staged.json"), "sha256": recovery.digest(self.root / "staged.json"),
            "output_path": str(self.root / "staged.md"), "output_sha256": recovery.digest(self.root / "staged.md")}})
        audit = {"Worker": "issue-evidence", "Provider handle": self.handle, "Thread ID": "child",
                 "Trace path": str(self.root / "trace.json"), "Last dispatch at": self.old_time}
        packet = {"identity": {"Run ID": "ITEM-1", "Lifecycle": "planning"},
                  "worker_results": [self.worker], "runtime_audits": [audit]}
        self.write("snapshot.json", packet)
        self.write("finalization_packet.json", packet)
        snapshot_hash = recovery.digest(self.root / "snapshot.json")
        self.write("finalization_failure.json", {"status": "failed", "stage": "workflow", "reported_by": "Coordinator",
            "run_id": "ITEM-1", "runtime_closure": "terminal", "packet_snapshot": str(self.root / "snapshot.json"),
            "snapshot_sha256": snapshot_hash, "packet_sha256": snapshot_hash})
        self.write("role_bindings.json", {"playbook": "techops_issue_remediation", "lifecycle": "planning",
            "handoff_recovery": {"run_id": "ITEM-1", "failure_sha256": recovery.digest(self.root / "finalization_failure.json")},
            "worker_contracts": {self.role: {"worker_id": "issue-evidence", "output": str(self.root / "output.md"),
                                             "result": str(self.root / "result.json")}}})
        self.write("runtime_dispatches.json", {"thread_mappings": {self.handle: "child"},
            "events": [{"Provider handle": self.handle, "Operation": "followup_task", "Last dispatch at": self.new_time}]})
        self.write("runtime_closure.json", {"terminal_observations": [{"Provider handle": self.handle,
            "Provider status": "idle", "Last dispatch at": self.new_time}]})
        for target in ("scripts.runtime_checks.trace_errors", "scripts.runtime_checks.trace_identity_errors",
                       "scripts.runtime_checks.terminal_observation_errors",
                       "scripts.planning_contracts.terminal_closure_dispatch_errors",
                       "scripts.worker_runtime_evidence.dispatch_audit_errors"):
            mock = patch(target, return_value=[])
            mock.start()
            self.addCleanup(mock.stop)

    def write(self, name, value):
        (self.root / name).write_text(json.dumps(value))

    def read(self, name):
        return json.loads((self.root / name).read_text())

    def authorize(self):
        return recovery.authorize(self.root, self.role, self.handle, "idle")

    def test_authorizes_only_terminal_bound_accepted_result_once(self):
        grant = self.authorize()
        self.assertEqual(grant["handle"], self.handle)
        packet = self.read("finalization_packet.json")
        packet["accepted_result_refreshes"] = {self.role: grant}
        self.write("finalization_packet.json", packet)
        with self.assertRaisesRegex(ValueError, "limit_reached"):
            self.authorize()

    def test_rejects_changed_failure_snapshot_result_trace_and_status(self):
        cases = [("finalization_failure.json", lambda p: p.write_text("{}")),
                 ("snapshot.json", lambda p: p.write_text("{}")),
                 ("result.json", lambda p: p.write_text("{}")),
                 ("trace.json", lambda p: p.write_text("{}")),
                 ("runtime_closure.json", lambda p: p.write_text('{"terminal_observations": []}'))]
        for name, mutate in cases:
            with self.subTest(name=name):
                path = self.root / name
                original = path.read_bytes()
                mutate(path)
                with self.assertRaises(ValueError):
                    self.authorize()
                path.write_bytes(original)

    def test_rejects_wrong_role_handle_or_nonterminal_state(self):
        for role, handle, status in [("implementer", self.handle, "idle"),
                                      (self.role, "/root/other", "idle"),
                                      (self.role, self.handle, "running")]:
            with self.subTest(role=role, handle=handle, status=status), self.assertRaises(ValueError):
                recovery.authorize(self.root, role, handle, status)

    def test_rejects_missing_or_changed_attestation_and_changed_result(self):
        grant = self.authorize()
        content = "guarded assignment"
        grant["dispatch_sha256"] = hashlib.sha256(content.encode()).hexdigest()
        packet = self.read("finalization_packet.json")
        packet["accepted_result_refreshes"] = {self.role: grant}
        self.write("finalization_packet.json", packet)
        self.write("new.json", self.read("staged.json"))
        (self.root / "new.md").write_text("Accepted evidence")
        response = {"run_id": "ITEM-1", "thread_id": "child", "spawn": {"provider_handle": self.handle},
                    "last_dispatch_at": "2026-11-02T21:00:00Z", "result_artifact": {
                        "path": str(self.root / "new.json"), "output_path": str(self.root / "new.md")}}
        with patch("scripts.runtime_checks._verified_dispatch_content", return_value=content):
            with self.assertRaisesRegex(ValueError, "unattested"):
                recovery.verify_response(self.root, self.role, response)
            (self.root / "new.md").write_text("Accepted evidence\n\n" + recovery.ATTESTATION)
            recovery.verify_response(self.root, self.role, response)
            # The collector may safely revalidate after the merger publishes the attested output.
            (self.root / "output.md").write_text((self.root / "new.md").read_text())
            recovery.verify_response(self.root, self.role, response)
            self.write("new.json", {"run_id": "ITEM-1", "changed": True})
            with self.assertRaisesRegex(ValueError, "unattested"):
                recovery.verify_response(self.root, self.role, response)
        with patch("scripts.runtime_checks._verified_dispatch_content", return_value="changed"):
            with self.assertRaisesRegex(ValueError, "dispatch_mismatch"):
                recovery.verify_response(self.root, self.role, response)


if __name__ == "__main__":
    unittest.main()
