"""Purpose-based guidance routing preserves provenance without requiring early asset review."""

import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts import asset_manifest, prepare_run
from scripts.validate_worker_runtime import activation_message


class EngineeringGuidance(unittest.TestCase):
    def test_all_playbooks_deliver_snapshot_references_and_defer_guidance_contents(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory).resolve()
            guide = repository / "engineering.md"
            contents = "# Tests\nRun only focused checks.\n# Deployment\nINTERNAL_GUIDANCE_CONTENT\n"
            guide.write_text(contents)
            supplied = {"schema_version": 1, "status": "explicit", "inputs": [
                {"Input ID": "GUIDE", "Input or artifact": "Engineering reference",
                 "Source or path": str(guide), "Authority": "User", "Status": "Readable; content deferred",
                 "Classification": "engineering guidance"},
            ]}
            for index, playbook in enumerate(("feature_delivery", "techops_issue_remediation",
                    "sentry_issue_remediation", "technical_spike", "vulnerability_investigation")):
                with self.subTest(playbook=playbook):
                    run = prepare_run.prepare_run(repository, f"ITEM-{index}", playbook, None, False,
                        input_data=supplied, started_at=datetime.now(timezone.utc).isoformat(), timebox_minutes=20,
                        primary_question="Which source boundary needs investigation?"
                        if playbook == "technical_spike" else None)
                    manifest = json.loads(Path(run["run_input_manifest"]["path"]).read_text())
                    row = next(row for row in manifest["inputs"] if row["Input ID"] == "GUIDE")
                    self.assertEqual(row["Original source path"], str(guide))
                    self.assertEqual(Path(row["path"]).read_text(), contents)
                    self.assertEqual(row["sha256"], hashlib.sha256(contents.encode()).hexdigest())
                    self.assertIn("otherwise defer", row["Expected use"])
                    self.assertNotIn("Asset source", row)
                    packets = json.loads(Path(run["activation_packet_bundle"]["path"]).read_text())["packets"]
                    for role, packet in packets.items():
                        with self.subTest(role=role):
                            delivered = next(item for item in packet["run_input_manifest"]["inputs"]
                                             if item["Input ID"] == "GUIDE")
                            self.assertEqual(delivered, row)
                            message = activation_message(packet, {"objective": "Inspect assigned scope"})
                            self.assertIn(row["path"], message)
                            self.assertIn("Read only relevant sections", message)
                            self.assertIn("Documenter uses accepted findings", message)
                            self.assertNotIn("INTERNAL_GUIDANCE_CONTENT", message)

    def test_guidance_does_not_block_asset_gate_but_product_specification_does(self):
        manifest = {"schema_version": 1, "status": "passed", "work_item": "ITEM-1", "sources": [{
            "source_id": "JIRA", "input_id": "ISSUE", "kind": "jira_issue_attachments",
            "locator": "Jira ITEM-1 attachments", "requiredness": "required", "discovery_status": "empty",
            "discovery_method": "Query attachment collection", "limitation": "No attachments",
            "remote_link_inventory": {"status": "empty", "method": "Query remote links", "locators": []},
            "asset_ids": [], "evidence_refs": ["EV-1"],
        }], "assets": [], "gate": {
            "inventory_complete": True, "all_assets_accounted_for": True, "all_available_assets_reviewed": True,
            "all_material_assets_linked": True, "reviewed_before_plan": True,
            "unresolved_asset_ids": [], "blocking_source_ids": [],
        }}
        inputs = {
            "ISSUE": {"Input or artifact": "Jira ITEM-1", "Classification": "work item"},
            "GUIDE": {"Source or path": "/engineering.md", "Authority": "User-supplied context",
                      "Classification": "engineering guidance", "Asset source": True},
        }

        def errors():
            return asset_manifest.validate_asset_manifest(manifest, work_item="ITEM-1", expected_inputs=inputs,
                expected_input_ids=inputs, expected_evidence_ids=["EV-1"], require_jira_source=True,
                require_passed=True)

        self.assertEqual(errors(), [])
        inputs["SPEC"] = {"Source or path": "/requirements.md", "Classification": "supporting artifact",
                          "Authority": "User-supplied context", "Asset source": True}
        self.assertIn("declared asset source input SPEC is missing from asset_manifest sources", errors())
        del inputs["SPEC"]["Asset source"]
        self.assertIn("input SPEC requires Asset source: true for supplied artifact", errors())
