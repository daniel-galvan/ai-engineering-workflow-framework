"""Validate the minimum useful content of a Feature Delivery assessment."""

from __future__ import annotations

import re


REPORT_NAME = "specification_assessment.md"
NO_PLAN_MESSAGE = "Not created; specification assessment produces specification_assessment.md"
REQUIRED_HEADINGS = (
    "# Specification Assessment",
    "## Question and Result",
    "## Source and Asset Baseline",
    "## Coverage",
    "## Gaps, Risks, and Decisions",
    "## Disposition and Next Action",
)


def _coverage_rows(text: str) -> list[list[str]]:
    section = re.search(r"^## Coverage\s*\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    rows = [] if section is None else [
        [cell.strip() for cell in line.strip().strip("|").split("|")]
        for line in section.group(1).splitlines() if line.strip().startswith("|")
    ]
    if (len(rows) < 3 or len(rows[0]) != 7 or rows[0][0] != "Requirement / behavior"
            or len(rows[1]) != 7 or any(not re.fullmatch(r":?-{3,}:?", cell) for cell in rows[1])):
        return []
    return rows[2:]


def coverage_mapping_errors(text: str, artifact: str) -> list[str]:
    """Check the shared seven-column mapping before and after handoff."""
    coverage = _coverage_rows(text)
    errors = []
    if not coverage:
        errors.append(f"{artifact} requires a populated requirement-to-Story coverage row")
    for index, row in enumerate(coverage, start=1):
        if len(row) != 7 or any(not cell for cell in row):
            errors.append(f"{artifact} coverage row {index} requires all seven columns")
        elif row[3] not in {"Covered", "Partial", "Missing", "Conflicting"}:
            errors.append(f"{artifact} coverage row {index} has invalid Status: {row[3]}")
    return errors


def assessment_report_errors(
    text: str, workflow_result: str, material_asset_ids: tuple[str, ...] = (),
) -> list[str]:
    errors = [
        f"{REPORT_NAME} requires {heading}" for heading in REQUIRED_HEADINGS
        if not re.search(rf"^{re.escape(heading)}\s*$", text, re.MULTILINE)
    ]
    if "asset_manifest.json" not in text:
        errors.append(f"{REPORT_NAME} must link asset_manifest.json")
    for asset_id in material_asset_ids:
        if not re.search(rf"(?<![A-Za-z0-9_-]){re.escape(asset_id)}(?![A-Za-z0-9_-])", text):
            errors.append(f"{REPORT_NAME} must account for material asset {asset_id}")
    result = re.search(r"^Workflow result:\s*(.+)$", text, re.MULTILINE)
    if not result or result.group(1).strip() != workflow_result:
        errors.append(f"{REPORT_NAME} Workflow result must match the Final Handoff")
    coverage = _coverage_rows(text)
    errors.extend(coverage_mapping_errors(text, REPORT_NAME))
    if workflow_result in {"Ready for implementation", "Ready with explicit follow-ups"} and any(
        len(row) < 4 or row[3] != "Covered" for row in coverage
    ):
        errors.append(f"{REPORT_NAME} ready result requires covered requirements")
    return errors


def self_test() -> None:
    valid = "\n".join(REQUIRED_HEADINGS[:2]) + "\nWorkflow result: Ready for implementation\n" + (
        "\n".join(REQUIRED_HEADINGS[2:4]) + "\n"
        "| Requirement / behavior | Story coverage | Evidence | Status | Test / dependency | Gap or follow-up | Owner |\n"
        "| --- | --- | --- | --- | --- | --- | --- |\n"
        "| Outcome A | ABC-2 | E-001 | Covered | Check A / ABC-1 | None | Team |\n"
    ) + "\n".join(REQUIRED_HEADINGS[4:]) + "\nasset_manifest.json\n"
    assert assessment_report_errors(valid, "Ready for implementation") == []
    assert "coverage row" in " ".join(assessment_report_errors(valid.replace("| Covered |", "| |"), "Ready for implementation"))
    assert "invalid Status" in " ".join(assessment_report_errors(
        valid.replace("| Covered |", "| Covered in intent |"), "Ready for implementation",
    ))
    assert "ready result" in " ".join(assessment_report_errors(
        valid.replace("| Covered |", "| Missing |"), "Ready for implementation",
    ))
    assert "material asset ASSET-1" in " ".join(assessment_report_errors(
        valid, "Ready for implementation", ("ASSET-1",),
    ))
    assert assessment_report_errors(
        valid.replace("| Covered |", "| Missing |").replace(
            "Workflow result: Ready for implementation", "Workflow result: Not ready for implementation",
        ), "Not ready for implementation",
    ) == []
    assert coverage_mapping_errors("## Coverage\n" + valid.split("## Coverage\n", 1)[1].split("## Gaps", 1)[0],
                                   "feature_design.md") == []
    assert "coverage row" in " ".join(coverage_mapping_errors(
        "## Coverage\n" + valid.split("## Coverage\n", 1)[1].split("## Gaps", 1)[0].replace(
            "| Covered |", "| |",
        ), "feature_design.md",
    ))
    assert "requires a populated" in " ".join(coverage_mapping_errors(
        valid.replace("| --- |", "| invalid |"), "feature_design.md",
    ))


if __name__ == "__main__":
    self_test()
    print("specification_assessment self-test: passed")
