#!/usr/bin/env python3
"""Validate the current-run inventory and review state for Feature Delivery assets."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Iterable


SCHEMA_VERSION = 1
ASSET_MANIFEST_FILENAME = "asset_manifest.json"
ASSET_MANIFEST_STATUSES = {"passed", "awaiting_input"}
SOURCE_KINDS = {"jira_issue_attachments", "directory", "file", "url", "other"}
SOURCE_STATUSES = {"complete", "empty", "unavailable", "permission_denied", "partial", "conflict"}
REQUIREDNESS = {"required", "supporting"}
ASSET_AVAILABILITY = {"available", "unavailable", "permission_denied", "redacted", "not_found"}
REVIEW_METHODS = {
    "visual_inspection", "rendered_read", "text_read", "metadata_read", "binary_inspection",
}
REVIEW_STATUSES = {
    "consumed", "reviewed_not_relevant", "unavailable", "permission_denied", "redacted",
    "conflict", "not_reviewed",
}
RELEVANCE = {"material", "non_material"}
IMAGE_KINDS = {"image", "screenshot", "photo", "diagram"}
JIRA_KEY = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")
GATE_FIELDS = (
    "inventory_complete",
    "all_assets_accounted_for",
    "all_available_assets_reviewed",
    "all_material_assets_linked",
    "reviewed_before_plan",
    "unresolved_asset_ids",
    "blocking_source_ids",
)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"asset_manifest_{field}_empty")
    return value.strip()


def _strings(value: object, field: str, *, required: bool = True) -> list[str]:
    if not isinstance(value, list) or (required and not value):
        raise ValueError(f"asset_manifest_{field}_missing")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"asset_manifest_{field}_invalid")
    return [item.strip() for item in value]


def _absolute_locator(value: str) -> str:
    return os.path.abspath(os.path.expanduser(value))


def _directory_entries(root: Path) -> tuple[set[str], list[str]]:
    """List every file or symlink, including hidden entries, without following directory symlinks."""
    entries: set[str] = set()
    walk_errors: list[str] = []

    def onerror(error: OSError) -> None:
        walk_errors.append(f"{error.__class__.__name__}: {error}")

    for current, directories, files in os.walk(
        root, topdown=True, followlinks=False, onerror=onerror,
    ):
        current_path = Path(current)
        followed_directories: list[str] = []
        for name in sorted(directories):
            candidate = current_path / name
            if candidate.is_symlink():
                entries.add(_absolute_locator(str(candidate)))
            else:
                followed_directories.append(name)
        directories[:] = followed_directories
        entries.update(
            _absolute_locator(str(current_path / name))
            for name in sorted(files)
        )
    return entries, walk_errors


def _source_assets(source: dict[str, object], assets_by_id: dict[str, dict[str, object]]) -> list[dict[str, object]]:
    return [assets_by_id[asset_id] for asset_id in source["asset_ids"] if asset_id in assets_by_id]


def _check_source_files(source: dict[str, object], assets_by_id: dict[str, dict[str, object]]) -> list[str]:
    errors: list[str] = []
    kind = source["kind"]
    locator = source["locator"]
    declared_assets = _source_assets(source, assets_by_id)
    if kind == "directory":
        root = Path(locator)
        if not root.is_dir():
            if source["discovery_status"] in {"complete", "empty"}:
                errors.append(f"asset source {source['source_id']} directory is unavailable: {locator}")
            return errors
        discovered, walk_errors = _directory_entries(root)
        if walk_errors:
            if source["discovery_status"] in {"complete", "empty"}:
                errors.append(
                    f"asset source {source['source_id']} directory inventory is incomplete: "
                    + "; ".join(walk_errors)
                )
            return errors
        if source["discovery_status"] not in {"complete", "empty"}:
            return errors
        declared = {_absolute_locator(str(asset["locator"])) for asset in declared_assets}
        if discovered != declared:
            missing = sorted(discovered - declared)
            extra = sorted(declared - discovered)
            if missing:
                errors.append(
                    f"asset source {source['source_id']} omitted directory entries: " + ", ".join(missing)
                )
            if extra:
                errors.append(
                    f"asset source {source['source_id']} declared paths outside the directory: " + ", ".join(extra)
                )
        expected_status = "empty" if not discovered else "complete"
        if source["discovery_status"] != expected_status:
            errors.append(
                f"asset source {source['source_id']} discovery_status must be {expected_status} for its contents"
            )
    elif kind == "file":
        path = Path(locator)
        exists = path.is_file() or path.is_symlink()
        if exists and len(declared_assets) != 1:
            errors.append(f"asset source {source['source_id']} must inventory exactly one file")
        if not exists and source["discovery_status"] in {"complete", "empty"}:
            errors.append(f"asset source {source['source_id']} file is unavailable: {locator}")
        if not exists or source["discovery_status"] not in {"complete", "empty"}:
            return errors
        if exists and declared_assets and _absolute_locator(str(declared_assets[0]["locator"])) != _absolute_locator(locator):
            errors.append(f"asset source {source['source_id']} asset locator does not match the file source")
    elif kind in {"url", "other"} and source["discovery_status"] in {"complete", "empty"}:
        if not declared_assets:
            errors.append(f"asset source {source['source_id']} must inventory at least one asset")
    return errors


def _expected_jira_input_ids(expected_inputs: object, work_item: str) -> set[str]:
    if not isinstance(expected_inputs, dict):
        return set()
    result = set()
    for input_id, row in expected_inputs.items():
        if not isinstance(row, dict):
            continue
        text = " ".join(str(row.get(field, "")) for field in ("Input or artifact", "Source or path"))
        if "jira" in text.lower() or "atlassian" in text.lower() or work_item in text:
            result.add(str(input_id))
    return result


def _expected_asset_input_ids(expected_inputs: object) -> set[str]:
    if not isinstance(expected_inputs, dict):
        return set()
    return {
        str(input_id)
        for input_id, row in expected_inputs.items()
        if isinstance(row, dict) and row.get("Asset source") is True
    }


def validate_asset_manifest(
    value: object,
    *,
    work_item: str | None = None,
    expected_input_ids: Iterable[str] | None = None,
    expected_inputs: dict[str, object] | None = None,
    expected_evidence_ids: Iterable[str] | None = None,
    material_claim_evidence_ids: Iterable[str] | None = None,
    require_jira_source: bool = False,
    require_passed: bool = False,
) -> list[str]:
    """Return contract errors; the caller decides whether they are fatal for its lifecycle."""
    errors: list[str] = []
    if not isinstance(value, dict):
        return ["asset_manifest must contain one object"]
    if value.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"asset_manifest schema_version must be {SCHEMA_VERSION}")
    status = value.get("status")
    if status not in ASSET_MANIFEST_STATUSES:
        errors.append("asset_manifest status must be passed or awaiting_input")
    if work_item is not None and value.get("work_item") != work_item:
        errors.append("asset_manifest work_item must match the Feature Delivery work item")

    raw_sources = value.get("sources")
    raw_assets = value.get("assets")
    if not isinstance(raw_sources, list) or not raw_sources:
        errors.append("asset_manifest sources must be a non-empty list")
        raw_sources = []
    if not isinstance(raw_assets, list):
        errors.append("asset_manifest assets must be a list")
        raw_assets = []

    sources: list[dict[str, object]] = []
    source_ids: set[str] = set()
    for index, raw in enumerate(raw_sources, start=1):
        if not isinstance(raw, dict):
            errors.append(f"asset_manifest source {index} must be an object")
            continue
        try:
            source_id = _string(raw.get("source_id"), f"source_{index}_id")
            source = {
                "source_id": source_id,
                "input_id": _string(raw.get("input_id"), f"source_{index}_input_id"),
                "kind": _string(raw.get("kind"), f"source_{index}_kind"),
                "locator": _string(raw.get("locator"), f"source_{index}_locator"),
                "requiredness": _string(raw.get("requiredness"), f"source_{index}_requiredness"),
                "discovery_status": _string(raw.get("discovery_status"), f"source_{index}_discovery_status"),
                "discovery_method": _string(raw.get("discovery_method"), f"source_{index}_discovery_method"),
                "limitation": _string(raw.get("limitation"), f"source_{index}_limitation"),
                "asset_ids": _strings(raw.get("asset_ids"), f"source_{index}_asset_ids", required=False),
                "evidence_refs": _strings(raw.get("evidence_refs"), f"source_{index}_evidence_refs"),
            }
        except ValueError as error:
            errors.append(str(error))
            continue
        if source_id in source_ids:
            errors.append(f"duplicate asset source_id {source_id}")
        source_ids.add(source_id)
        if source["kind"] not in SOURCE_KINDS:
            errors.append(f"asset source {source_id} has invalid kind")
        if source["requiredness"] not in REQUIREDNESS:
            errors.append(f"asset source {source_id} has invalid requiredness")
        if source["discovery_status"] not in SOURCE_STATUSES:
            errors.append(f"asset source {source_id} has invalid discovery_status")
        if (
            source["discovery_status"] not in {"complete", "empty"}
            and source["limitation"].lower().rstrip(".") in {"none", "no limitation"}
        ):
            errors.append(f"asset source {source_id} must record its retrieval limitation")
        if source["kind"] in {"directory", "file"} and not Path(source["locator"]).is_absolute():
            errors.append(f"asset source {source_id} filesystem locator must be absolute")
        if source["kind"] == "url" and not source["locator"].lower().startswith(("http://", "https://")):
            errors.append(f"asset source {source_id} URL locator must use http or https")
        if source["kind"] == "jira_issue_attachments":
            method = source["discovery_method"].lower()
            if not JIRA_KEY.search(source["locator"]):
                errors.append(f"asset source {source_id} Jira locator must identify an issue key")
            if "attachment" not in method or not any(word in method for word in ("read", "retriev", "inventor")):
                errors.append(f"asset source {source_id} must record an attachment retrieval/inventory method")
        sources.append(source)

    assets: list[dict[str, object]] = []
    assets_by_id: dict[str, dict[str, object]] = {}
    for index, raw in enumerate(raw_assets, start=1):
        if not isinstance(raw, dict):
            errors.append(f"asset_manifest asset {index} must be an object")
            continue
        try:
            asset_id = _string(raw.get("asset_id"), f"asset_{index}_id")
            asset = {
                "asset_id": asset_id,
                "source_id": _string(raw.get("source_id"), f"asset_{index}_source_id"),
                "name": _string(raw.get("name"), f"asset_{index}_name"),
                "kind": _string(raw.get("kind"), f"asset_{index}_kind"),
                "locator": _string(raw.get("locator"), f"asset_{index}_locator"),
                "availability": _string(raw.get("availability"), f"asset_{index}_availability"),
                "requiredness": _string(raw.get("requiredness"), f"asset_{index}_requiredness"),
                "review_method": _string(raw.get("review_method"), f"asset_{index}_review_method"),
                "review_status": _string(raw.get("review_status"), f"asset_{index}_review_status"),
                "relevance": _string(raw.get("relevance"), f"asset_{index}_relevance"),
                "observation": _string(raw.get("observation"), f"asset_{index}_observation"),
                "used_by": _strings(raw.get("used_by"), f"asset_{index}_used_by", required=False),
                "evidence_refs": _strings(raw.get("evidence_refs"), f"asset_{index}_evidence_refs", required=False),
                "disposition": _string(raw.get("disposition"), f"asset_{index}_disposition"),
            }
        except ValueError as error:
            errors.append(str(error))
            continue
        if asset_id in assets_by_id:
            errors.append(f"duplicate asset_id {asset_id}")
        assets_by_id[asset_id] = asset
        assets.append(asset)
        if asset["source_id"] not in source_ids:
            errors.append(f"asset {asset_id} references missing source {asset['source_id']}")
        if asset["availability"] not in ASSET_AVAILABILITY:
            errors.append(f"asset {asset_id} has invalid availability")
        if asset["availability"] != "available" and not asset["evidence_refs"]:
            errors.append(f"unavailable asset {asset_id} requires evidence_refs for its limitation")
        if asset["requiredness"] not in REQUIREDNESS:
            errors.append(f"asset {asset_id} has invalid requiredness")
        if asset["review_method"] not in REVIEW_METHODS:
            errors.append(f"asset {asset_id} has invalid review_method")
        if asset["review_status"] not in REVIEW_STATUSES:
            errors.append(f"asset {asset_id} has invalid review_status")
        if asset["relevance"] not in RELEVANCE:
            errors.append(f"asset {asset_id} has invalid relevance")
        if (
            str(asset["kind"]).lower() in IMAGE_KINDS
            and asset["availability"] == "available"
            and asset["review_status"] in {"consumed", "reviewed_not_relevant"}
            and asset["review_method"] not in {"visual_inspection", "rendered_read"}
        ):
            errors.append(f"image asset {asset_id} requires visual_inspection or rendered_read")
        if asset["availability"] == "available" and asset["review_status"] not in {"consumed", "reviewed_not_relevant"}:
            errors.append(f"available asset {asset_id} is not reviewed")
        if asset["relevance"] == "material":
            if asset["review_status"] != "consumed":
                errors.append(f"material asset {asset_id} must be consumed")
            if not set(asset["used_by"]) & {"feature-design", "planning-review"}:
                errors.append(f"material asset {asset_id} must reach feature-design or planning-review")
            if not asset["evidence_refs"]:
                errors.append(f"material asset {asset_id} requires evidence_refs")
        elif asset["review_status"] == "consumed" and not asset["used_by"]:
            errors.append(f"consumed non-material asset {asset_id} requires used_by")

    declared_input_ids = set(str(item) for item in (expected_input_ids or ()))
    expected_evidence = set(str(item) for item in (expected_evidence_ids or ()))
    claim_evidence = set(str(item) for item in (material_claim_evidence_ids or ()))
    jira_inputs = _expected_jira_input_ids(expected_inputs or {}, work_item or "")
    asset_inputs = _expected_asset_input_ids(expected_inputs or {})
    if not expected_inputs:
        # When only IDs are supplied, membership is the available provenance check.
        jira_inputs = set(declared_input_ids)
    source_input_ids = [str(source["input_id"]) for source in sources]
    expected_rows = expected_inputs if isinstance(expected_inputs, dict) else {}
    if expected_inputs is not None:
        for input_id in sorted(set(source_input_ids) - set(expected_rows)):
            errors.append(f"asset source input {input_id} is not declared in run_inputs.json")
    for input_id in sorted(asset_inputs - set(source_input_ids)):
        errors.append(f"declared asset source input {input_id} is missing from asset_manifest sources")
    for input_id in sorted(asset_inputs):
        if source_input_ids.count(input_id) > 1:
            errors.append(f"declared asset source input {input_id} has multiple manifest sources")
        row = expected_rows.get(input_id)
        matching = [source for source in sources if source["input_id"] == input_id]
        if isinstance(row, dict) and matching:
            expected_locator = str(row.get("path") or row.get("Source or path") or "").strip()
            if expected_locator.startswith(("/", "http://", "https://")):
                actual_locator = str(matching[0]["locator"])
                if matching[0]["kind"] in {"directory", "file"}:
                    expected_locator = _absolute_locator(expected_locator)
                    actual_locator = _absolute_locator(actual_locator)
                if actual_locator != expected_locator:
                    errors.append(
                        f"asset source {matching[0]['source_id']} locator does not match declared input {input_id}"
                    )
    for source in sources:
        if declared_input_ids and source["input_id"] not in declared_input_ids:
            errors.append(f"asset source {source['source_id']} input_id is not in run_inputs.json")
        if expected_evidence:
            missing = sorted(set(source["evidence_refs"]) - expected_evidence)
            if missing:
                errors.append(f"asset source {source['source_id']} references missing evidence: " + ", ".join(missing))
        errors.extend(_check_source_files(source, assets_by_id))
    if require_jira_source:
        jira_sources = [source for source in sources if source["kind"] == "jira_issue_attachments"]
        if len(jira_sources) != 1:
            errors.append("Feature Delivery requires exactly one Jira attachment source")
        elif declared_input_ids and jira_sources[0]["input_id"] not in jira_inputs:
            errors.append("Jira attachment source must point to the declared Jira work-item input")
    for source in sources:
        for asset_id in source["asset_ids"]:
            if asset_id not in assets_by_id:
                errors.append(f"asset source {source['source_id']} references missing asset {asset_id}")
        if len(set(source["asset_ids"])) != len(source["asset_ids"]):
            errors.append(f"asset source {source['source_id']} contains duplicate asset IDs")
    for asset in assets:
        if asset["asset_id"] not in {
            asset_id for source in sources for asset_id in source["asset_ids"]
        }:
            errors.append(f"asset {asset['asset_id']} is not linked from a source")
        if expected_evidence:
            missing = sorted(set(asset["evidence_refs"]) - expected_evidence)
            if missing:
                errors.append(f"asset {asset['asset_id']} references missing evidence: " + ", ".join(missing))
        if asset["relevance"] == "material" and not set(asset["evidence_refs"]) & claim_evidence:
            errors.append(f"material asset {asset['asset_id']} is not linked from a claim")

    unresolved_sources = [source["source_id"] for source in sources if source["discovery_status"] not in {"complete", "empty"}]
    unresolved_assets = [
        asset["asset_id"] for asset in assets
        if asset["availability"] != "available" or asset["review_status"] not in {"consumed", "reviewed_not_relevant"}
    ]
    all_accounted = not any(
        error.startswith("asset source ") and (
            "omitted directory entries" in error
            or "declared paths outside" in error
            or "discovery_status must be" in error
        )
        for error in errors
    ) and all(
        set(source["asset_ids"]) == {asset_id for asset_id, asset in assets_by_id.items() if asset["source_id"] == source["source_id"]}
        for source in sources
    )
    inventory_complete = not unresolved_sources and all_accounted
    review_complete = not unresolved_assets
    material_linked = all(
        asset["relevance"] != "material"
        or (
            asset["review_status"] == "consumed"
            and bool(asset["evidence_refs"])
            and bool(set(asset["used_by"]) & {"feature-design", "planning-review"})
        )
        for asset in assets
    )

    gate = value.get("gate")
    if not isinstance(gate, dict):
        errors.append("asset_manifest gate must be an object")
        gate = {}
    for field in GATE_FIELDS:
        if field not in gate:
            errors.append(f"asset_manifest gate is missing {field}")
    expected_gate = {
        "inventory_complete": inventory_complete,
        "all_assets_accounted_for": all_accounted,
        "all_available_assets_reviewed": review_complete,
        "all_material_assets_linked": material_linked,
        "reviewed_before_plan": gate.get("reviewed_before_plan") is True,
        "unresolved_asset_ids": unresolved_assets,
        "blocking_source_ids": unresolved_sources,
    }
    for field, expected in expected_gate.items():
        if field not in gate:
            continue
        if gate[field] != expected:
            errors.append(f"asset_manifest gate {field} does not match the inventory")

    if status == "passed":
        if unresolved_sources or unresolved_assets or not inventory_complete or not review_complete or not material_linked:
            errors.append("asset_manifest passed requires complete inventory, review, and material linkage")
        if gate.get("reviewed_before_plan") is not True:
            errors.append("asset_manifest passed requires reviewed_before_plan=true")
    elif status == "awaiting_input" and not (unresolved_sources or unresolved_assets):
        errors.append("asset_manifest awaiting_input requires an unresolved source or asset")
    if require_passed and status != "passed":
        errors.append("Feature Delivery ready_for_implementation requires asset_manifest status passed")
    return list(dict.fromkeys(errors))


def asset_plan_errors(plan_text: str, manifest: dict[str, object]) -> list[str]:
    """Ensure a ready plan names the asset gate and every material asset."""
    errors: list[str] = []
    if "# Asset Baseline" not in plan_text:
        errors.append("implementation_plan.md requires an Asset Baseline section")
    if ASSET_MANIFEST_FILENAME not in plan_text:
        errors.append("implementation_plan.md Asset Baseline must link asset_manifest.json")
    for asset in manifest.get("assets", []):
        if not isinstance(asset, dict) or asset.get("relevance") != "material":
            continue
        asset_id = str(asset.get("asset_id", ""))
        if asset_id and asset_id not in plan_text:
            errors.append(f"implementation_plan.md must account for material asset {asset_id}")
        refs = asset.get("evidence_refs", [])
        if isinstance(refs, list) and refs and not any(str(ref) in plan_text for ref in refs):
            errors.append(f"implementation_plan.md must retain evidence refs for material asset {asset_id}")
    return errors


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
        assert asset_plan_errors("# Asset Baseline\nasset_manifest.json\nE-FOLDER-001\n", manifest) == []
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
    print("asset_manifest self-test: passed")


if __name__ == "__main__":
    self_test()
