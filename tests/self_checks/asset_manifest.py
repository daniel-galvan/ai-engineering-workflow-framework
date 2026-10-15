"""Preserved asset_manifest synthetic regression scenarios."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
from scripts.asset_manifest import (
    ASSET_MANIFEST_FILENAME,
    _supplied_asset_reference,
    asset_gate_errors,
    asset_plan_errors,
    record_asset_gate_failure,
    validate_asset_manifest,
)


def self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="asset-manifest-") as directory:
        root = Path(directory)
        (root / ".hidden.png").write_bytes(b"x")
        nested = root / "nested"
        nested.mkdir()
        (nested / "notes.txt").write_text("x")
        locators = sorted(str(path) for path in (root / ".hidden.png", nested / "notes.txt"))
        manifest = {
            "schema_version": 1,
            "status": "passed",
            "work_item": "EXAMPLE-1",
            "sources": [
                {
                    "source_id": "SRC-JIRA",
                    "input_id": "IN-001",
                    "kind": "jira_issue_attachments",
                    "locator": "Jira EXAMPLE-1 attachments",
                    "requiredness": "required",
                    "discovery_status": "empty",
                    "discovery_method": "read Jira attachment inventory",
                    "remote_link_inventory": {
                        "status": "empty", "method": "read Jira remote links for EXAMPLE-1",
                        "locators": [],
                    },
                    "limitation": "Synthetic fixture has no Jira attachments.",
                    "asset_ids": [],
                    "evidence_refs": ["E-JIRA-001"],
                },
                {
                    "source_id": "SRC-FOLDER",
                    "input_id": "IN-002",
                    "kind": "directory",
                    "locator": str(root),
                    "requiredness": "supporting",
                    "discovery_status": "complete",
                    "discovery_method": "recursive inventory including hidden entries and symlinks",
                    "limitation": "None.",
                    "asset_ids": ["ASSET-001", "ASSET-002"],
                    "evidence_refs": ["E-FOLDER-001"],
                },
            ],
            "assets": [
                {
                    "asset_id": "ASSET-001", "source_id": "SRC-FOLDER", "name": ".hidden.png",
                    "kind": "image", "locator": locators[0], "availability": "available",
                    "requiredness": "supporting", "review_method": "visual_inspection",
                    "review_status": "reviewed_not_relevant", "relevance": "non_material",
                    "observation": "Synthetic image reviewed.", "used_by": [],
                    "evidence_refs": ["E-FOLDER-001"], "disposition": "No effect on the feature plan.",
                },
                {
                    "asset_id": "ASSET-002", "source_id": "SRC-FOLDER", "name": "notes.txt",
                    "kind": "document", "locator": locators[1], "availability": "available",
                    "requiredness": "supporting", "review_method": "text_read",
                    "review_status": "reviewed_not_relevant", "relevance": "non_material",
                    "observation": "Synthetic note reviewed.", "used_by": [],
                    "evidence_refs": ["E-FOLDER-001"], "disposition": "No effect on the feature plan.",
                },
            ],
            "gate": {
                "inventory_complete": True, "all_assets_accounted_for": True,
                "all_available_assets_reviewed": True, "all_material_assets_linked": True,
                "reviewed_before_plan": True, "unresolved_asset_ids": [], "blocking_source_ids": [],
            },
        }
        inputs = {
            "IN-001": {"Input or artifact": "Work item EXAMPLE-1", "Source or path": "Jira"},
            "IN-002": {
                "Input or artifact": "Supporting folder", "Source or path": str(root), "Asset source": True,
            },
        }
        assert validate_asset_manifest(
            manifest, work_item="EXAMPLE-1", expected_input_ids=inputs, expected_inputs=inputs,
            expected_evidence_ids={"E-JIRA-001", "E-FOLDER-001"}, require_jira_source=True, require_passed=True,
        ) == []
        metadata_only = json.loads(json.dumps(manifest))
        metadata_only["assets"][0]["review_method"] = "metadata_read"
        assert any("requires visual_inspection or rendered_read" in error
                   for error in validate_asset_manifest(metadata_only))
        material = json.loads(json.dumps(manifest))
        material["assets"][1].update({
            "relevance": "material", "review_status": "consumed", "used_by": ["feature-context"],
        })
        material["gate"]["all_material_assets_linked"] = False
        assert validate_asset_manifest(
            material, work_item="EXAMPLE-1", expected_input_ids=inputs, expected_inputs=inputs,
            require_jira_source=True, require_passed=True, require_material_linkage=False,
        ) == []
        assert any("not linked from a claim" in error for error in validate_asset_manifest(
            material, work_item="EXAMPLE-1", expected_input_ids=inputs, expected_inputs=inputs,
            require_jira_source=True, require_passed=True,
        ))
        assert any("must reach feature-design" in error for error in validate_asset_manifest(
            material, material_claim_evidence_ids={"E-FOLDER-001"},
        ))
        material["assets"][1]["used_by"].append("feature-design")
        material["gate"]["all_material_assets_linked"] = True
        assert validate_asset_manifest(
            material, work_item="EXAMPLE-1", expected_input_ids=inputs, expected_inputs=inputs,
            material_claim_evidence_ids={"E-FOLDER-001"}, require_jira_source=True, require_passed=True,
        ) == []
        remote_method = json.loads(json.dumps(manifest))
        remote_method["sources"][0]["remote_link_inventory"]["method"] = "getJiraIssueRemoteIssueLinks"
        assert validate_asset_manifest(remote_method, require_jira_source=True) == []
        codex_url = "codex://threads/00000000-0000-4000-8000-000000000001"
        thread = json.loads(json.dumps(manifest))
        thread["sources"].append({
            "source_id": "SRC-THREAD", "input_id": "IN-003", "kind": "url", "locator": codex_url,
            "requiredness": "supporting", "discovery_status": "complete",
            "discovery_method": "Read the supplied Codex task", "limitation": "None",
            "asset_ids": ["ASSET-003"], "evidence_refs": ["E-THREAD-001"],
        })
        thread["assets"].append(dict(manifest["assets"][1], **{
            "asset_id": "ASSET-003", "source_id": "SRC-THREAD", "locator": codex_url,
        }))
        thread_inputs = dict(inputs, **{"IN-003": {
            "Input or artifact": "Supplied Codex task", "Source or path": codex_url, "Asset source": True,
        }})
        unmarked_thread_inputs = dict(inputs, **{"IN-003": {
            "Input or artifact": "Supplied Codex task", "Source or path": codex_url,
            "Authority": "User-supplied supporting context", "Classification": "session context",
        }})
        assert _supplied_asset_reference({
            "Source or path": "/tmp/assessment folder", "Authority": "User-supplied supporting evidence",
        })
        assert any("IN-003 requires Asset source: true" in error for error in validate_asset_manifest(
            manifest, work_item="EXAMPLE-1", expected_input_ids=unmarked_thread_inputs,
            expected_inputs=unmarked_thread_inputs, require_jira_source=True, require_passed=True,
        ))
        assert validate_asset_manifest(
            thread, work_item="EXAMPLE-1", expected_input_ids=thread_inputs, expected_inputs=thread_inputs,
            require_jira_source=True, require_passed=True,
        ) == []
        thread["sources"][-1]["locator"] = "codex://threads/another-task"
        assert any("locator does not match" in error for error in validate_asset_manifest(
            thread, work_item="EXAMPLE-1", expected_input_ids=thread_inputs, expected_inputs=thread_inputs,
            require_jira_source=True, require_passed=True,
        ))
        missing_remote = json.loads(json.dumps(manifest))
        del missing_remote["sources"][0]["remote_link_inventory"]
        assert any("remote link inventory" in error for error in validate_asset_manifest(
            missing_remote, work_item="EXAMPLE-1", expected_input_ids=inputs, expected_inputs=inputs,
            require_jira_source=True,
        ))
        limited_remote = json.loads(json.dumps(manifest))
        limited_remote["sources"][0]["remote_link_inventory"]["status"] = "unavailable"
        limited_remote["sources"][0]["limitation"] = "None"
        assert any("remote link retrieval limitation" in error for error in validate_asset_manifest(
            limited_remote, work_item="EXAMPLE-1", expected_input_ids=inputs, expected_inputs=inputs,
            require_jira_source=True,
        ))
        blocked = json.loads(json.dumps(manifest))
        blocked["status"] = "awaiting_input"
        blocked["sources"][0]["discovery_status"] = "unavailable"
        blocked["sources"][0]["remote_link_inventory"]["status"] = "unavailable"
        blocked["sources"][0]["limitation"] = "Jira issue and remote links could not be read."
        blocked["gate"]["inventory_complete"] = False
        blocked["gate"]["blocking_source_ids"] = ["SRC-JIRA"]
        assert validate_asset_manifest(
            blocked, work_item="EXAMPLE-1", expected_input_ids=inputs, expected_inputs=inputs,
            require_jira_source=True,
        ) == []
        unlisted_remote = json.loads(json.dumps(manifest))
        unlisted_remote["sources"][0]["remote_link_inventory"]["status"] = "complete"
        unlisted_remote["sources"][0]["remote_link_inventory"]["locators"] = ["https://example.test/plan"]
        assert any("remote link is missing" in error for error in validate_asset_manifest(
            unlisted_remote, work_item="EXAMPLE-1", expected_input_ids=inputs, expected_inputs=inputs,
            require_jira_source=True,
        ))
        assert asset_plan_errors("# Asset Baseline\nasset_manifest.json\nE-FOLDER-001\n", manifest) == []
        assert any("material asset ASSET-002 requires its own Asset Baseline row" in error for error in
                   asset_plan_errors("# Asset Baseline\nasset_manifest.json\nASSET-002 E-FOLDER-001\n", material))
        assert asset_plan_errors(
            "# Asset Baseline\nasset_manifest.json\n"
            "| Asset ID | Evidence refs | Observation | Planning consequence |\n"
            "| --- | --- | --- | --- |\n"
            "| ASSET-002 | E-FOLDER-001 | Prior note describes the behavior. | Test the behavior. |\n",
            material,
        ) == []
        assert asset_plan_errors(
            "## Asset Baseline\nasset_manifest.json\n"
            "| Asset ID | Evidence refs | Observation | Planning consequence |\n"
            "| --- | --- | --- | --- |\n"
            "| ASSET-002 | E-FOLDER-001 | Prior note describes the behavior. | Test the behavior. |\n"
            "# Next section\n",
            material,
        ) == []
        broken = json.loads(json.dumps(manifest))
        broken["sources"][1]["asset_ids"] = ["ASSET-001"]
        assert any("omitted directory entries" in error for error in validate_asset_manifest(broken))
        missing_source = json.loads(json.dumps(manifest))
        missing_source["sources"] = missing_source["sources"][:1]
        assert any(
            "declared asset source input IN-002" in error
            for error in validate_asset_manifest(
                missing_source, expected_input_ids=inputs, expected_inputs=inputs,
            )
        )
        with tempfile.TemporaryDirectory(prefix="asset-gate-") as gate_dir:
            gate_root = Path(gate_dir)
            manifest_path = gate_root / ASSET_MANIFEST_FILENAME
            inputs_path = gate_root / "run_inputs.json"
            inputs_path.write_text(json.dumps({
                "schema_version": 1, "status": "explicit", "inputs": [
                    {"Input ID": key, **row, "Authority": "Synthetic test", "Status": "Registered"}
                    for key, row in inputs.items()
                ],
            }))
            manifest_path.write_text(json.dumps(manifest))
            assert asset_gate_errors(manifest_path, inputs_path, "EXAMPLE-1") == []
            manifest_path.write_text(json.dumps(material))
            assert asset_gate_errors(manifest_path, inputs_path, "EXAMPLE-1") == []
            incomplete = json.loads(json.dumps(manifest))
            incomplete["status"] = "complete"
            manifest_path.write_text(json.dumps(incomplete))
            assert any("status must be passed" in error for error in asset_gate_errors(
                manifest_path, inputs_path, "EXAMPLE-1",
            ))
            invalid = json.loads(json.dumps(manifest))
            invalid["sources"][0]["remote_link_inventory"]["method"] = "Jira remote links queried"
            invalid["assets"][0]["review_method"] = "provider read"
            invalid["assets"][0]["relevance"] = "supporting"
            manifest_path.write_text(json.dumps(invalid))
            errors = asset_gate_errors(manifest_path, inputs_path, "EXAMPLE-1")
            assert any("remote link retrieval method" in error for error in errors)
            assert any("invalid review_method" in error for error in errors)
            assert any("invalid relevance" in error for error in errors)
            receipt = record_asset_gate_failure(manifest_path, "EXAMPLE-1", errors)
            assert json.loads(receipt.read_text())["errors"] == errors
    print("asset_manifest self-test: passed")
