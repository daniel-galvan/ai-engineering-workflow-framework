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
READY_RESULTS = {"Ready for implementation", "Ready with explicit follow-ups"}
TEMPLATE_INSTRUCTION_MARKERS = (
    "Create `.thoughts/<WORK-ITEM-ID>/specification_assessment.md`",
    "State what work was assessed",
    "Link the primary work item or specification",
    "One row per distinct requested outcome",
    "Separate confirmed gaps from unsupported possibilities",
    "State why the coverage table supports the exact result",
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


def coverage_readiness_errors(text: str, workflow_result: str, artifact: str) -> list[str]:
    if workflow_result in READY_RESULTS and any(row[3] != "Covered" for row in _coverage_rows(text) if len(row) > 3):
        return [f"{artifact} ready result requires covered requirements"]
    return []


def assessment_report_errors(
    text: str, workflow_result: str, material_asset_ids: tuple[str, ...] = (),
    reviewed_coverage_text: str | None = None,
) -> list[str]:
    errors = []
    for heading in REQUIRED_HEADINGS:
        count = len(re.findall(rf"^{re.escape(heading)}\s*$", text, re.MULTILINE))
        if not count:
            errors.append(f"{REPORT_NAME} requires {heading}")
        elif count > 1:
            errors.append(f"{REPORT_NAME} has duplicate heading {heading}")
    if any(marker in text for marker in TEMPLATE_INSTRUCTION_MARKERS):
        errors.append(f"{REPORT_NAME} contains template instructions")
    for heading in REQUIRED_HEADINGS[1:]:
        if heading == "## Coverage":
            continue
        section = re.search(rf"^{re.escape(heading)}\s*\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
        if section and not any(
            line.strip() and not line.startswith("Workflow result:") for line in section.group(1).splitlines()
        ):
            errors.append(f"{REPORT_NAME} requires content under {heading}")
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
    errors.extend(coverage_readiness_errors(text, workflow_result, REPORT_NAME))
    if reviewed_coverage_text is not None and coverage != _coverage_rows(reviewed_coverage_text):
        errors.append(f"{REPORT_NAME} must match reviewed coverage in feature_design.md")
    return errors


def self_test() -> None:
    valid = (
        "# Specification Assessment\n## Question and Result\nAssessed ITEM-1 against its Stories.\n"
        "Workflow result: Ready for implementation\n## Source and Asset Baseline\n"
        "ITEM-1 and asset_manifest.json reviewed.\n## Coverage\n"
        "| Requirement / behavior | Story coverage | Evidence | Status | Test / dependency | Gap or follow-up | Owner |\n"
        "| --- | --- | --- | --- | --- | --- | --- |\n"
        "| Outcome A | ABC-2 | E-001 | Covered | Check A / ABC-1 | None | Team |\n"
        "## Gaps, Risks, and Decisions\nNo gaps.\n## Disposition and Next Action\nProceed to planning.\n"
    )
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
    assert "template instructions" in " ".join(assessment_report_errors(
        valid.replace("## Question and Result", "## Question and Result\nState what work was assessed"),
        "Ready for implementation",
    ))
    assert "duplicate heading" in " ".join(assessment_report_errors(
        valid + "\n## Gaps, Risks, and Decisions\n", "Ready for implementation",
    ))
    assert "reviewed coverage" in " ".join(assessment_report_errors(
        valid, "Ready for implementation", reviewed_coverage_text=valid.replace("| Covered |", "| Partial |"),
    ))
    assert "requires content under ## Question and Result" in " ".join(assessment_report_errors(
        valid.replace("Assessed ITEM-1 against its Stories.\n", ""), "Ready for implementation",
    ))
    assert "feature_design.md ready result" in " ".join(coverage_readiness_errors(
        valid.replace("| Covered |", "| Partial |"), "Ready for implementation", "feature_design.md",
    ))


if __name__ == "__main__":
    self_test()
    print("specification_assessment self-test: passed")
