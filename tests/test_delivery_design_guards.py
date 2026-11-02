"""Check design necessity, complete-solution limits and independent delivery activation."""

import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.review_evidence import (
    PLAN_FIXTURE, REVIEW_FIXTURE, applicability_errors, plan_design_errors, plan_review_coverage_errors,
    review_candidate_metadata_errors,
)
from scripts.validate_worker_runtime import _defer_downstream_rejection, delivery_dependency_errors, delivery_start_errors
from scripts.review_evidence import delivery_evidence_fixture


ROOT = Path(__file__).resolve().parents[1]


class DeliveryDesignGuards(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.plan = self.root / "implementation_plan.md"
        self.plan.write_text(PLAN_FIXTURE)
        self.path = self.root / "finalization_packet.json"
        self.packet = {"identity": {"Playbook / version": "playbooks/feature_delivery.md / 0.5.33",
            "Lifecycle": "remediation", "Run ID": "ITEM-1-delivery", "Requested profile": "standard",
            "Activated profile": "standard", "Profile status": "in_progress", "State": "in_progress"},
            "reentry": {"Prior run ID": "ITEM-1-planning", "Approval reference": "User approved plan",
                        "Approved plan": str(self.plan),
                        "Approved plan SHA256": hashlib.sha256(self.plan.read_bytes()).hexdigest()}, "workers": []}
        for worker, role in (("implement", "implementer"), ("review", "reviewer"),
                             ("validate", "tester"), ("handoff", "documenter")):
            self.packet["workers"].append({"Worker": worker, "Role": role,
                "Outcome": "in_progress" if worker == "implement" else "awaiting_dependency",
                "Assigned inputs": f"Current plan; Provider handle /root/{worker}",
                "Depends on": "Approved plan and activation" if worker == "implement" else "implement"})
        self.save()

    def save(self):
        self.path.write_text(json.dumps(self.packet))

    def errors(self, status="running", handle="/root/implement"):
        return delivery_start_errors(self.path, handle, status)

    def test_design_requires_existing_flow_comparison_and_non_placeholder_evidence(self):
        self.assertEqual(applicability_errors(PLAN_FIXTURE), [])
        missing = PLAN_FIXTURE.split("# Design Justification")[0]
        self.assertTrue(any("Design Justification" in error for error in applicability_errors(missing)))
        unsupported = PLAN_FIXTURE.replace("Checked existing timestamp; consumer requires asset version", "Unknown")
        self.assertTrue(plan_design_errors(unsupported))

    def test_external_assumption_can_be_planned_but_cannot_prove_complete_delivery(self):
        assumed = PLAN_FIXTURE.replace("| verified |", "| assumed |")
        self.assertEqual(plan_design_errors(assumed), [])
        self.assertTrue(any("remains assumed" in error for error in plan_design_errors(assumed, require_complete=True)))
        for effect in ("release_only", "follow_up", "none"):
            scoped = assumed.replace("required_for_completion", effect)
            self.assertEqual(plan_design_errors(scoped, require_complete=True), [])
        self.assertTrue(plan_design_errors(assumed.replace("required_for_completion", "Ignore")))

    def test_review_cannot_omit_a_required_or_conditional_plan_behavior(self):
        self.assertEqual(plan_review_coverage_errors(PLAN_FIXTURE, REVIEW_FIXTURE), [])
        for disposition in ("required", "conditional"):
            plan = PLAN_FIXTURE.replace("| required |", f"| {disposition} |")
            review = REVIEW_FIXTURE.replace("Asset-only edit preserves publication", "Different happy path")
            self.assertTrue(any("omits required plan" in error for error in plan_review_coverage_errors(plan, review)))
        deferred = PLAN_FIXTURE.replace("| required |", "| deferred |")
        self.assertEqual(plan_review_coverage_errors(deferred, REVIEW_FIXTURE.replace(
            "Asset-only edit preserves publication", "Different happy path")), [])

    def test_review_candidate_binding_detects_changed_files_and_wrong_checkout(self):
        repository, review, _ = delivery_evidence_fixture(self.root)
        self.assertEqual(review_candidate_metadata_errors(review, expected_repository=repository), [])
        self.assertIn("review repository must match the execution repository",
                      review_candidate_metadata_errors(review, expected_repository=self.root))
        (repository / "asset.py").write_text("version = 3\n")
        self.assertIn("review candidate fingerprint does not match the current candidate",
                      review_candidate_metadata_errors(review, expected_repository=repository))

    def test_pre_edit_requires_reentry_and_registered_independent_graph(self):
        self.assertEqual(self.errors(), [])
        original = copy.deepcopy(self.packet)
        self.packet["identity"]["Lifecycle"] = "planning"
        self.save()
        self.assertIn("feature_implementation_requires_remediation_reentry", self.errors())
        for worker in ("implement", "review", "validate", "handoff"):
            self.packet = copy.deepcopy(original)
            self.packet["workers"] = [row for row in self.packet["workers"] if row["Worker"] != worker]
            self.save()
            self.assertIn("delivery_worker_registration_required:" + worker, self.errors())
        self.packet = copy.deepcopy(original)
        self.packet["workers"][1]["Assigned inputs"] = "Provider handle /root/implement"
        self.save()
        self.assertIn("independent_delivery_handles_required", self.errors())

    def test_status_handle_and_approved_plan_change_are_blocked(self):
        self.assertTrue(self.errors(status="completed"))
        self.assertIn("implementer_handle_mismatch", self.errors(handle="/root/coordinator"))
        self.plan.write_text(PLAN_FIXTURE + "\nUnapproved schema change\n")
        self.assertTrue(any("approved_plan_changed" in error for error in self.errors()))
        self.packet["reentry"]["Approved plan SHA256"] = hashlib.sha256(self.plan.read_bytes()).hexdigest()
        self.packet["reentry"]["Approval reference"] = ""
        self.save()
        self.assertTrue(self.errors())

    def test_cli_cannot_combine_before_edit_with_activation_or_claim_a_terminal_worker_is_active(self):
        command = [sys.executable, str(ROOT / "scripts/validate_worker_runtime.py"),
                   "--before-source-change", str(self.path), "--implementer-handle", "/root/implement",
                   "--provider-status", "running"]
        allowed = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(allowed.returncode, 0, allowed.stdout + allowed.stderr)
        blocked = subprocess.run(command + ["--transition", "replace"], capture_output=True, text=True)
        self.assertEqual(blocked.returncode, 2)
        self.path.write_text("not JSON")
        blocked = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(blocked.returncode, 2)
        self.assertIn("delivery_activation_invalid", blocked.stdout)
        self.assertNotIn("Traceback", blocked.stderr)

    def test_delivery_activation_requires_accepted_upstream_review_and_current_candidate(self):
        repository, review, _ = delivery_evidence_fixture(self.root)
        bindings = {"lifecycle": "remediation", "playbook": "techops_issue_remediation",
                    "source_checkout": str(repository)}
        packet = {"worker_results": [], "runtime_audits": []}
        path = self.root / "finalization_packet.json"
        def save():
            path.write_text(json.dumps(packet))
        save()
        self.assertEqual(delivery_dependency_errors(self.root, "reviewer", bindings),
                         ["delivery_dependency_not_accepted:reviewer"])
        packet["worker_results"] = [{"Worker": "implement", "Outcome": "complete"}]
        save()
        self.assertEqual(delivery_dependency_errors(self.root, "reviewer", bindings),
                         ["delivery_dependency_audit_missing:reviewer"])
        packet["runtime_audits"] = [{"Worker": "implement"}]
        save()
        with patch(("planning_contracts" if importlib.util.find_spec("planning_contracts") else "scripts.planning_contracts") + "._worker_runtime_audit_errors", return_value=[]), \
             patch(("merge_techops_result" if importlib.util.find_spec("merge_techops_result") else "scripts.merge_techops_result") + ".merged_result_errors", return_value=[]):
            self.assertEqual(delivery_dependency_errors(self.root, "reviewer", bindings), [])
            self.assertEqual(delivery_dependency_errors(self.root, "tester", bindings),
                             ["delivery_dependency_not_accepted:tester"])
            trace = self.root / "review_trace.json"
            trace.write_text(json.dumps({"result_artifact": {"output_sha256": hashlib.sha256(review.encode()).hexdigest()}}))
            (self.root / "code_review.md").write_text(review)
            packet["worker_results"].append({"Worker": "review", "Outcome": "complete"})
            packet["runtime_audits"].append({"Worker": "review", "Trace path": str(trace)})
            save()
            self.assertEqual(delivery_dependency_errors(self.root, "tester", bindings), [])
            with patch(("planning_contracts" if importlib.util.find_spec("planning_contracts") else "scripts.planning_contracts") + "._worker_runtime_audit_errors", return_value=["worker_fan_in_rejected"]):
                self.assertIn("delivery_dependency_unverified:tester",
                              delivery_dependency_errors(self.root, "tester", bindings))
            (repository / "asset.py").write_text("version = 3\n")
            self.assertIn("delivery_review_candidate_changed", delivery_dependency_errors(self.root, "tester", bindings))
            (repository / "asset.py").write_text("version = 2\n")
            (self.root / "code_review.md").write_text(review + "changed\n")
            self.assertIn("delivery_review_output_changed", delivery_dependency_errors(self.root, "tester", bindings))
            rejected = review.replace("Disposition: accepted", "Disposition: changes_required")
            (self.root / "code_review.md").write_text(rejected)
            trace.write_text(json.dumps({"result_artifact": {"output_sha256": hashlib.sha256(rejected.encode()).hexdigest()}}))
            self.assertIn("delivery_review_not_accepted", delivery_dependency_errors(self.root, "tester", bindings))

    def test_reviewer_replacement_checks_only_accepted_implementer_dependency(self):
        repository, _, _ = delivery_evidence_fixture(self.root)
        bindings = {"lifecycle": "remediation", "playbook": "techops_issue_remediation",
                    "source_checkout": str(repository)}
        packet = {"worker_results": [{"Worker": "implement", "Outcome": "complete"},
                                     {"Worker": "review", "Outcome": "complete"}],
                  "runtime_audits": [{"Worker": "implement"}, {"Worker": "review"}],
                  "terminal_observations": [{"Worker": "review"}]}
        (self.root / "finalization_packet.json").write_text(json.dumps(packet))
        def audit(value, path, completed):
            self.assertEqual(completed, {"implement"})
            self.assertEqual([row["Worker"] for row in value["runtime_audits"]], ["implement"])
            return []
        def merged(value, manifest, root):
            self.assertEqual([row["Worker"] for row in value["worker_results"]], ["implement"])
            return []
        with patch(("planning_contracts" if importlib.util.find_spec("planning_contracts") else "scripts.planning_contracts") + "._worker_runtime_audit_errors", side_effect=audit), \
             patch(("merge_techops_result" if importlib.util.find_spec("merge_techops_result") else "scripts.merge_techops_result") + ".merged_result_errors", side_effect=merged):
            self.assertEqual(delivery_dependency_errors(self.root, "reviewer", bindings), [])

    def test_inactive_downstream_rejection_stays_pending_during_upstream_correction(self):
        handle = "/root/tester"
        thread = "00000000-0000-0000-0000-000000000003"
        dispatched, observed = "2026-10-01T00:00:00Z", "2026-10-01T00:01:00Z"
        bindings = {"lifecycle": "remediation", "playbook": "techops_issue_remediation", "bindings": {"tester": {}}}
        (self.root / "role_bindings.json").write_text(json.dumps(bindings))
        trace = self.root / "rejected.json"
        trace.write_text(json.dumps({"run_id": "ITEM-1", "thread_id": thread, "spawn": {"agent": "tester"}}))
        receipt = {"run_id": "ITEM-1", "trace": str(trace), "sha256": hashlib.sha256(trace.read_bytes()).hexdigest(),
                   "Provider handle": handle, "Last dispatch at": dispatched}
        ledger = {"provider_session": "/tmp/fixture", "parent_thread_id": thread, "run_started_at": dispatched,
                  "thread_mappings": {handle: thread}, "events": [{"Provider handle": handle,
                  "Last dispatch at": dispatched, "Operation": "spawn_agent"}], "inventories": [{"Observed at": observed,
                  "raw_response": {"agents": [{"agent_name": handle, "agent_status": {"interrupted": "Done"}}]}}]}
        ledger_path = self.root / "runtime_dispatches.json"
        ledger_path.write_text(json.dumps(ledger))
        with patch(("worker_runtime_evidence" if importlib.util.find_spec("worker_runtime_evidence") else "scripts.worker_runtime_evidence") + ".dispatch_audit_errors", return_value=[]), \
             patch("scripts.validate_worker_runtime.rejected_result_errors", return_value=[]), \
             patch(("provider_runtime" if importlib.util.find_spec("provider_runtime") else "scripts.provider_runtime") + ".read_runtime_events", side_effect=lambda *args: ledger):
            self.assertTrue(_defer_downstream_rejection(self.root, "implementer", "tester", receipt))
            self.assertTrue(_defer_downstream_rejection(self.root, "reviewer", "tester", receipt))
            self.assertFalse(_defer_downstream_rejection(self.root, "tester", "tester", receipt))
            self.assertFalse(_defer_downstream_rejection(self.root, "documenter", "tester", receipt))
            ledger["inventories"][0]["raw_response"]["agents"][0]["agent_status"] = {"running": "Active"}
            ledger_path.write_text(json.dumps(ledger))
            self.assertFalse(_defer_downstream_rejection(self.root, "implementer", "tester", receipt))
            ledger["inventories"][0]["raw_response"]["agents"][0]["agent_status"] = {"interrupted": "Done"}
            ledger["inventories"][0]["Observed at"] = "2026-09-30T23:59:00Z"
            ledger_path.write_text(json.dumps(ledger))
            self.assertFalse(_defer_downstream_rejection(self.root, "implementer", "tester", receipt))
            ledger["inventories"][0]["Observed at"] = observed
            ledger_path.write_text(json.dumps(ledger))
            with patch(("worker_runtime_evidence" if importlib.util.find_spec("worker_runtime_evidence") else "scripts.worker_runtime_evidence") + ".dispatch_audit_errors", return_value=["ledger_stale"]):
                self.assertFalse(_defer_downstream_rejection(self.root, "implementer", "tester", receipt))
            with patch("scripts.validate_worker_runtime.rejected_result_errors", return_value=["audit_invalid"]):
                self.assertFalse(_defer_downstream_rejection(self.root, "implementer", "tester", receipt))
            trace.write_text("changed")
            self.assertFalse(_defer_downstream_rejection(self.root, "implementer", "tester", receipt))


if __name__ == "__main__":
    unittest.main()
