"""Regressions for the planning-to-delivery continuation and handoff seams."""

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import prepare_run as preparation
import finalize_work_record as finalizer
import validate_worker_runtime as runtime
from run_input_manifest import load_manifest
from review_evidence import REVIEW_FIXTURE


class FeatureDeliveryContinuation(unittest.TestCase):
    def inputs(self, root):
        source = root / "inputs.json"
        source.write_text(json.dumps({"inputs": [{
            "Input ID": "PLAN-001", "Input or artifact": "Approved plan",
            "Source or path": str(root / "plan.md"), "Authority": "Approved user decision",
            "Status": "Registered", "Asset source": True,
        }]}))
        return source

    def test_input_snapshot_survives_output_edits_and_continuation_hash_is_current(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "plan.md").write_text("approved version\n")
            source = self.inputs(root)
            result = preparation.prepare_run(root, "ITEM-1", "feature_delivery", None, False,
                                             input_manifest=source)
            manifest_path = Path(result["run_input_manifest"]["path"])
            saved = load_manifest(manifest_path)
            snapshot = Path(saved["inputs"][0]["path"])
            self.assertNotEqual(snapshot, root / "plan.md")
            (root / "plan.md").write_text("updated output\n")
            self.assertEqual(snapshot.read_text(), "approved version\n")
            result = preparation.prepare_run(root, "ITEM-1", "feature_delivery", None, True,
                                             input_manifest=manifest_path)
            packet = json.loads(Path(result["finalization_packet"]).read_text())
            digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
            self.assertEqual(packet["identity"]["Run input manifest hash"], digest)
            self.assertEqual(packet["run_input_manifest"]["sha256"], digest)
            self.assertEqual(packet["inputs"], load_manifest(manifest_path)["inputs"])
            _, errors = finalizer._feature_expected_inputs(packet, manifest_path.parent)
            self.assertEqual(errors, [])
            packet["identity"]["Run input manifest hash"] = "0" * 64
            self.assertTrue(finalizer._feature_expected_inputs(packet, manifest_path.parent)[1])
            packet["identity"]["Run input manifest hash"] = digest
            packet["inputs"][0]["Authority"] = "Changed without an input observation"
            self.assertTrue(finalizer._feature_expected_inputs(packet, manifest_path.parent)[1])

    def test_reentry_requires_approval_preserves_history_and_resets_delivery_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "plan.md").write_text("approved plan\n")
            result = preparation.prepare_run(root, "ITEM-2", "feature_delivery", None, False,
                                             input_manifest=self.inputs(root))
            artifact_root = Path(result["artifact_root"])
            packet_path = artifact_root / "finalization_packet.json"
            prior = json.loads(packet_path.read_text())
            prior["identity"].update({"Lifecycle": "planning", "State": "ready_for_implementation",
                                      "Requested profile": "deep", "Workflow outcome": "completed"})
            prior["decisions"] = [{"Decision": "Keep accepted compatibility rule"}]
            packet_path.write_text(json.dumps(prior))
            (artifact_root / "implementation_plan.md").write_text("Approved plan\n")
            (artifact_root / "runtime_closure.json").write_text(json.dumps({"runtime_closure": [{
                "Run or stage": "planning", "Receipt owner": "Coordinator",
                "Completed worker handles": "/root/handoff", "Runtime status": "Released",
                "Remaining active handles": "None", "Closure evidence or blocker": "Provider close confirmed release of /root/handoff",
            }]}))
            with self.assertRaisesRegex(ValueError, "approval_reference_required"):
                preparation.prepare_run(root, "ITEM-2", "feature_delivery", None, True,
                                        input_manifest=Path(result["run_input_manifest"]["path"]), remediation_reentry=True)
            old_bytes = packet_path.read_bytes()
            closure_path = artifact_root / "runtime_closure.json"
            closed_bytes = closure_path.read_bytes()
            closure_path.write_text(closed_bytes.decode().replace('"Released"', '"Blocked"'))
            with self.assertRaisesRegex(ValueError, "prior_worker_runtime_closure_required"):
                preparation.prepare_run(root, "ITEM-2", "feature_delivery", None, True,
                                        input_manifest=Path(result["run_input_manifest"]["path"]),
                                        remediation_reentry=True, approval_reference="Explicit user approval")
            self.assertEqual(packet_path.read_bytes(), old_bytes)
            self.assertFalse((artifact_root / "runs").exists())
            closure_path.write_bytes(closed_bytes)
            result = preparation.prepare_run(root, "ITEM-2", "feature_delivery", None, True,
                                             input_manifest=Path(result["run_input_manifest"]["path"]),
                                             remediation_reentry=True, approval_reference="User approval in current turn")
            current = json.loads(packet_path.read_text())
            archived = Path(result["archived_prior_run"])
            self.assertEqual((archived / "finalization_packet.json").read_bytes(), old_bytes)
            self.assertNotEqual(current["identity"]["Run ID"], prior["identity"]["Run ID"])
            self.assertEqual(current["identity"]["Lifecycle"], "remediation")
            self.assertEqual(current["identity"]["Profile status"], "requested")
            self.assertEqual(current["identity"]["Engineering outcome"], "unknown")
            self.assertEqual(current["identity"]["Requested profile"], "deep")
            self.assertEqual(current["decisions"], prior["decisions"])
            self.assertEqual(current["worker_results"], [])
            self.assertEqual((artifact_root / "implementation_plan.md").read_text(), "Approved plan\n")
            self.assertFalse((artifact_root / "runtime_closure.json").exists())
            current_run_id = current["identity"]["Run ID"]
            result = preparation.prepare_run(root, "ITEM-2", "feature_delivery", None, True,
                                             input_manifest=Path(result["run_input_manifest"]["path"]))
            followed = json.loads(packet_path.read_text())
            self.assertEqual(followed["identity"]["Run ID"], current_run_id)
            self.assertEqual(followed["identity"]["Lifecycle"], "remediation")
            self.assertEqual(result["workflow_objective"], "feature_implementation")

    def test_documenter_guard_rejects_planning_packet_for_prepared_remediation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "plan.md").write_text("approved plan\n")
            result = preparation.prepare_run(root, "ITEM-3", "feature_delivery", None, False,
                                             input_manifest=self.inputs(root))
            bindings_path = Path(result["role_binding_manifest"])
            bindings = json.loads(bindings_path.read_text())
            bindings["lifecycle"] = "remediation"
            bindings_path.write_text(json.dumps(bindings))
            packet_path = Path(result["finalization_packet"])
            packet = json.loads(packet_path.read_text())
            packet["identity"]["Lifecycle"] = "planning"
            packet_path.write_text(json.dumps(packet))
            bundle = result["activation_packet_bundle"]
            self.assertIn("feature_delivery_packet_lifecycle_mismatch",
                          runtime.activation_packet_errors(Path(bundle["path"]), "documenter", bundle["sha256"]))

    def delivery_packet(self, root):
        packet = {"identity": {"Playbook / version": "playbooks/feature_delivery.md / 0.5.2",
                               "Lifecycle": "remediation", "State": "handoff",
                               "Requested profile": "deep", "Activated profile": "deep", "Executed profile": "deep",
                               "Profile status": "executed", "Workflow outcome": "in_progress",
                               "Engineering outcome": "partially_solved"},
                  "finalization": {"Durable artifact root": str(root)},
                  "workers": [], "worker_results": [], "runtime_audits": [],
                  "synchronization": [{"Stage": "Delivery fan-in", "Workers launched": "implement, review, validate",
                                       "Barrier status": "Passed", "Results summarized": "Review accepted; database unverified"}],
                  "evidence": [{"Evidence ID": "E-001"}], "terminal_observations": []}
        for index, (worker, role) in enumerate((('implement', 'implementer'), ('review', 'reviewer'), ('validate', 'tester'))):
            packet["workers"].append({**{field: "Recorded" for field in finalizer.FEATURE_DELIVERY_LEDGER_FIELDS},
                                      "Worker": worker, "Role": role, "Outcome": "complete"})
            packet["worker_results"].append({**{field: "Recorded" for field in finalizer.FEATURE_DELIVERY_RESULT_FIELDS},
                                             "Worker": worker, "Outcome": "complete", "Evidence / claim refs": "E-001",
                                             "Uncertainties / blockers": "context-unverified; database unverified"})
            packet["runtime_audits"].append({"Worker": worker, "Provider handle": f"/root/{worker}",
                                           "Provider status": "completed", "Last dispatch at": "2026-10-07T23:40:00Z",
                                           "Observed at": "2026-10-07T23:50:00Z", "Status source": "list_agents",
                                           "Trace retrieval": "unavailable: provider export returned permission_denied"})
        (root / "code_review.md").write_text(REVIEW_FIXTURE)
        (root / "validation_report.md").write_text("Unit tests passed; database concurrency unverified.\n")
        return packet

    def test_remediation_gate_requires_workers_review_validation_fan_in_and_audits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packet = self.delivery_packet(root)
            path = root / "finalization_packet.json"
            self.assertEqual(finalizer._feature_delivery_remediation_errors(packet, path, pre_handoff=True), [])
            for field in ("worker_results", "workers", "synchronization", "runtime_audits"):
                broken = copy.deepcopy(packet)
                broken[field] = []
                with self.subTest(field=field):
                    self.assertTrue(finalizer._feature_delivery_remediation_errors(broken, path, pre_handoff=True))
            (root / "code_review.md").write_text(REVIEW_FIXTURE.replace("Disposition: accepted", "Disposition: changes_required"))
            self.assertTrue(finalizer._feature_delivery_remediation_errors(packet, path, pre_handoff=True))
            (root / "code_review.md").write_text(REVIEW_FIXTURE)
            unverified = copy.deepcopy(packet)
            unverified["identity"].update({"State": "completed", "Workflow outcome": "completed"})
            self.assertIn("feature_delivery_context_unverified_prevents_completion",
                          finalizer._feature_delivery_remediation_errors(unverified, path, pre_handoff=True))
            (root / "validation_report.md").unlink()
            self.assertTrue(finalizer._feature_delivery_remediation_errors(packet, path, pre_handoff=True))


if __name__ == "__main__":
    unittest.main()
