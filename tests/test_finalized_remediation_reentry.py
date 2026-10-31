"""Published engineering blocks can reenter without fabricating a workflow failure."""

import hashlib
import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from scripts import prepare_run as prepare


class FinalizedRemediationReentry(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.plan = self.root / "implementation_plan.md"
        self.plan.write_text("Approved plan\n")
        self.record = self.root / "work_record.md"
        self.record.write_text("Finalized record\n")
        self.response = self.root / "outgoing.md"
        self.response.write_text("Original canonical report\n")
        self.prior = {"identity": {"Run ID": "prior", "Playbook / version": "techops_issue_remediation / 0.5.33",
            "Lifecycle": "remediation", "State": "blocked", "Requested profile": "standard"},
            "reentry": {"Approval reference": "approved", "Approved plan": str(self.plan),
                "Approved plan SHA256": hashlib.sha256(self.plan.read_bytes()).hexdigest()},
            "worker_results": [{"Worker": "implement", "Outcome": "complete"}],
            "claims": [{"Claim ID": "delivery"}]}
        self.packet = self.root / "finalization_packet.json"
        self.packet.write_text(json.dumps(self.prior))
        self.closure = {"runtime_closure": [{"Run or stage": "Current run", "Receipt owner": "Coordinator",
            "Runtime status": "Terminal", "Remaining active handles": "0", "Completed worker handles": "/root/worker",
            "Closure evidence or blocker": "Native terminal observation"}], "terminal_observations": [{
                "Provider handle": "/root/worker", "Provider status": "completed", "Status source": "list_agents",
                "Thread ID": "00000000-0000-0000-0000-000000000001", "Last dispatch operation": "spawn_agent",
                "Last dispatch at": "2026-10-01T00:00:00Z", "Observed at": "2026-10-01T00:01:00Z"}]}
        (self.root / "runtime_closure.json").write_text(json.dumps(self.closure))
        self.delivery = {"status": "verified", "run_id": "prior", "proposed_response": str(self.response),
            "record_sha256": hashlib.sha256(self.record.read_bytes()).hexdigest(),
            "canonical_sha256": hashlib.sha256(self.response.read_bytes()).hexdigest(),
            "proposed_sha256": hashlib.sha256(self.response.read_bytes()).hexdigest()}
        self.receipt = self.root / "handoff_delivery.json"
        self.receipt.write_text(json.dumps(self.delivery))
        stack = self.enterContext(ExitStack())
        try:
            import finalize_work_record as finalizer
            import review_evidence as review
        except ModuleNotFoundError:
            from scripts import finalize_work_record as finalizer, review_evidence as review
        self.proof = stack.enter_context(patch.object(finalizer, "publication_recovery_context", return_value={
            "record_sha256": self.delivery["record_sha256"], "canonical_sha256": self.delivery["canonical_sha256"]}))
        stack.enter_context(patch.object(finalizer, "recovery_canonical_report", return_value=self.response.read_bytes()))
        stack.enter_context(patch.object(review, "applicability_errors", return_value=[]))
        self.candidate = stack.enter_context(patch.object(prepare, "_recover_current_accepted_candidate",
            return_value={"status": "unaccepted", "source_already_present": True, "files": {"source": "digest"}}))
        self.planning = stack.enter_context(patch.object(prepare, "_verified_recovery_planning",
            return_value={"claims": [{"Claim ID": "accepted-planning"}]}))

    def reenter(self, approval="approved"):
        return prepare._reentry_source(self.root, approval, expected_playbook="techops_issue_remediation",
                                       source_checkout=self.root)

    def test_published_block_preserves_planning_and_candidate_without_failure_receipt(self):
        before = {p: p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        result = self.reenter()
        self.assertEqual(result["claims"], [{"Claim ID": "accepted-planning"}])
        self.assertEqual(result["_recovered_candidate"]["status"], "unaccepted")
        self.assertTrue(result["_recovered_candidate"]["source_already_present"])
        self.assertEqual(self.proof.call_args.args, (self.packet, self.record))
        self.assertFalse(Path(self.proof.call_args.kwargs["package_workspace"]).exists())
        self.assertTrue(all(p.read_bytes() == contents for p, contents in before.items()))
        self.assertFalse((self.root / "finalization_failure.json").exists())
        changed = json.loads(self.packet.read_text())
        changed["identity"]["State"] = "completed"
        self.packet.write_text(json.dumps(changed))
        self.assertIn("_recovered_candidate", self.reenter())

    def test_unverified_delivery_changed_plan_and_wrong_approval_remain_blocked(self):
        originals = {p: p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        for change in ("pending", "wrong_run", "record_hash", "canonical_hash", "response", "forged_response_receipt", "outside", "plan",
                       "active", "approval", "proof", "candidate", "planning", "closure", "failure"):
            with self.subTest(change=change):
                receipt = dict(self.delivery)
                if change == "pending": receipt["status"] = "pending"
                elif change == "wrong_run": receipt["run_id"] = "other"
                elif change in {"record_hash", "canonical_hash"}:
                    receipt["record_sha256" if change == "record_hash" else "canonical_sha256"] = "changed"
                elif change == "response": self.response.write_text("Changed report")
                elif change == "forged_response_receipt":
                    self.response.write_text("Changed report")
                    receipt["proposed_sha256"] = hashlib.sha256(self.response.read_bytes()).hexdigest()
                elif change == "outside": receipt["proposed_response"] = str(self.root.parent / "outside.md")
                elif change == "plan": self.plan.write_text("Changed plan")
                elif change == "active":
                    prior = json.loads(self.packet.read_text()); prior["identity"]["State"] = "in_progress"
                    self.packet.write_text(json.dumps(prior))
                elif change == "proof": self.proof.side_effect = ValueError("native_proof_rejected")
                elif change == "candidate": self.candidate.side_effect = ValueError("candidate_changed")
                elif change == "planning": self.planning.side_effect = ValueError("planning_changed")
                elif change == "failure": (self.root / "finalization_failure.json").write_text('{}')
                elif change == "closure":
                    closure = json.loads(json.dumps(self.closure))
                    closure["runtime_closure"][0]["Remaining active handles"] = "1"
                    (self.root / "runtime_closure.json").write_text(json.dumps(closure))
                self.receipt.write_text(json.dumps(receipt))
                with self.assertRaises(ValueError):
                    self.reenter("different" if change == "approval" else "approved")
                for p, contents in originals.items(): p.write_bytes(contents)
                (self.root / "finalization_failure.json").unlink(missing_ok=True)
                for mocked in (self.proof, self.candidate, self.planning): mocked.side_effect = None
