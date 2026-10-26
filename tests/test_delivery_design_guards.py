"""Check design necessity, complete-solution limits and independent delivery activation."""

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.review_evidence import (
    PLAN_FIXTURE, REVIEW_FIXTURE, applicability_errors, plan_design_errors, plan_review_coverage_errors,
)
from scripts.validate_worker_runtime import delivery_start_errors


ROOT = Path(__file__).resolve().parents[1]


class DeliveryDesignGuards(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.plan = self.root / "implementation_plan.md"
        self.plan.write_text(PLAN_FIXTURE)
        self.path = self.root / "finalization_packet.json"
        self.packet = {"identity": {"Playbook / version": "playbooks/feature_delivery.md / 0.5.31",
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


if __name__ == "__main__":
    unittest.main()
