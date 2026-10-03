"""Structural evidence gates; source correctness remains an independent review obligation."""

from __future__ import annotations

import argparse
import json
import re
import tempfile
from pathlib import Path


PLAN_COLUMNS = (
    "Behavior", "Authority / condition", "Applicability evidence", "Counterexample check / result",
    "Disposition", "Planned action / exclusion",
)
REVIEW_COLUMNS = (
    "Behavior", "Applicability evidence", "Caller / producer", "Consumer / contract", "Lifecycle / invariant",
    "Counterexample check / result", "Regression evidence", "Result",
)
VALIDATION_COLUMNS = ("Check", "Result", "Environment / revision", "What it proves", "Remaining limits")
PLACEHOLDERS = {"", "unknown", "todo", "tbd", "pending", "not applicable", "none"}


def _section(text: str, heading: str) -> str:
    match = re.search(rf"^{re.escape(heading)}\s*\n(.*?)(?=^#{{1,2}} |\Z)", text, re.M | re.S)
    return match.group(1).strip() if match else ""


def _rows(text: str, heading: str, columns: tuple[str, ...]) -> tuple[list[list[str]], list[str]]:
    lines = [line.strip() for line in _section(text, heading).splitlines() if line.strip().startswith("|")]
    rows = [
        [cell.strip().replace(r"\|", "|") for cell in re.split(r"(?<!\\)\|", line.strip("|"))]
        for line in lines
    ]
    if (len(rows) < 3 or tuple(rows[0]) != columns or len(rows[1]) != len(columns)
            or any(not re.fullmatch(r":?-{3,}:?", cell) for cell in rows[1])):
        return [], [f"{heading} requires its exact table header and populated evidence rows"]
    errors = []
    for index, row in enumerate(rows[2:], 1):
        if len(row) != len(columns) or any(not cell for cell in row):
            errors.append(f"{heading} row {index} requires all {len(columns)} columns")
    return [row for row in rows[2:] if len(row) == len(columns)], errors


def _heading_errors(text: str, headings: tuple[str, ...]) -> list[str]:
    return [
        f"requires exactly one {heading}"
        for heading in headings
        if len(re.findall(rf"^{re.escape(heading)}\s*$", text, re.M)) != 1
    ]


def applicability_errors(text: str) -> list[str]:
    heading = "# Behavior Applicability"
    errors = _heading_errors(text, (heading,))
    rows, row_errors = _rows(text, heading, PLAN_COLUMNS)
    errors.extend(row_errors)
    for index, row in enumerate(rows, 1):
        disposition = row[4]
        if disposition not in {"required", "conditional", "deferred", "excluded", "unverified"}:
            errors.append(f"applicability row {index} has invalid disposition")
        elif disposition == "unverified":
            errors.append(f"ready plan cannot contain unverified applicability row {index}")
        if any(row[column].strip("`").lower() in PLACEHOLDERS for column in (0, 1, 2, 3, 5)):
            errors.append(f"applicability row {index} requires authority, evidence, observed check and consequence")
    return errors


def review_report_errors(text: str, *, require_accepted: bool = False) -> list[str]:
    headings = (
        "# Code Review", "## Scope", "## Behavior Review", "## Findings", "## Validation",
        "## Reconciliation and Next Action",
    )
    errors = _heading_errors(text, headings)
    for heading in ("## Scope", "## Findings", "## Reconciliation and Next Action"):
        if not _section(text, heading):
            errors.append(f"review requires evidence under {heading}")
    dispositions = re.findall(r"^Disposition:\s*(.+)$", text, re.M)
    disposition = dispositions[0].strip() if len(dispositions) == 1 else ""
    if disposition not in {"accepted", "changes_required", "replanning_required", "blocked"}:
        errors.append("review requires one valid Disposition")
    if require_accepted and disposition != "accepted":
        errors.append("completed delivery requires accepted code review")
    rows, row_errors = _rows(text, "## Behavior Review", REVIEW_COLUMNS)
    errors.extend(row_errors)
    for index, row in enumerate(rows, 1):
        result = row[7]
        if result not in {"verified", "defect", "unverified"}:
            errors.append(f"behavior review row {index} has invalid result")
        if disposition == "accepted":
            if result != "verified":
                errors.append(f"accepted review cannot contain {result} behavior row {index}")
            if any(cell.strip("`").lower() in PLACEHOLDERS for cell in row[:7]):
                errors.append(f"accepted behavior row {index} requires concrete lifecycle and counterexample evidence")
    validation, validation_errors = _rows(text, "## Validation", VALIDATION_COLUMNS)
    errors.extend(validation_errors)
    for index, row in enumerate(validation, 1):
        if row[1] not in {"pass", "fail", "blocked", "deferred", "not_applicable"}:
            errors.append(f"validation row {index} has invalid result")
        if disposition == "accepted" and row[1] in {"fail", "blocked"}:
            errors.append(f"accepted review has unresolved validation row {index}; resolve or record Tester deferral")
        if row[1] in {"deferred", "not_applicable"} and row[4].lower() in PLACEHOLDERS:
            errors.append(f"validation row {index} requires a deferral or non-applicability reason")
    if "Create `code_review.md` in the active run root" in text:
        errors.append("review still contains template instructions")
    return errors


def completed_review_errors(
    identity: dict[str, str], root: Path, *,
    registered_paths: set[Path] | None = None, handoff_paths: set[Path] | None = None,
) -> list[str]:
    playbook = Path(str(identity.get("Playbook / version", "")).split(" / ", 1)[0]).stem
    if (playbook != "feature_delivery" or identity.get("Lifecycle") != "remediation"
            or identity.get("State") != "completed"):
        return []
    path = root / "code_review.md"
    try:
        errors = review_report_errors(path.read_text(), require_accepted=True)
    except OSError as error:
        return [f"completed Feature Delivery requires readable code_review.md: {error}"]
    if registered_paths is not None and path.resolve() not in registered_paths:
        errors.append("completed Feature Delivery must register code_review.md as a durable artifact")
    if handoff_paths is not None and path.resolve() not in handoff_paths:
        errors.append("completed Feature Delivery must link code_review.md in Final Handoff")
    return errors


PLAN_FIXTURE = (
    "# Behavior Applicability\n"
    "| " + " | ".join(PLAN_COLUMNS) + " |\n| " + " | ".join(["---"] * 6) + " |\n"
    "| Advance asset version | ITEM-1 current asset requirement | repo/assets.py:10 | "
    "Compared unchanged upload consumer; version must change | required | Update version atomically |\n"
)
REVIEW_FIXTURE = (
    "# Code Review\n## Scope\nRepo candidate HEAD abc1234 / base def5678, worktree fingerprint sha256:example.\n"
    "Disposition: accepted\n## Behavior Review\n| " + " | ".join(REVIEW_COLUMNS)
    + " |\n| " + " | ".join(["---"] * 8) + " |\n"
    "| Asset-only edit preserves publication | ITEM-1 and unchanged review contract | api.upload | "
    "review payload omits assets | Published remains editable; version advances | "
    "Compared payload and UI lock: no review submission; pending would strand edit | "
    "tests/assets.py:20 version and published assertions | verified |\n"
    "## Findings\nNo confirmed candidate defects.\n## Validation\n| "
    + " | ".join(VALIDATION_COLUMNS) + " |\n| " + " | ".join(["---"] * 5) + " |\n"
    "| Source path trace | pass | candidate abc1234 plus worktree | no orphan pending state | Runtime deferred |\n"
    "## Reconciliation and Next Action\nPlan reconciled; Tester owns runtime tests. Release readiness not assessed.\n"
)


def self_test() -> None:
    assert applicability_errors(PLAN_FIXTURE) == []
    assert review_report_errors(REVIEW_FIXTURE, require_accepted=True) == []
    for value in ("unverified", "bogus"):
        assert applicability_errors(PLAN_FIXTURE.replace("| required |", f"| {value} |"))
    assert applicability_errors(PLAN_FIXTURE.replace("repo/assets.py:10", "Unknown"))
    assert applicability_errors("# Behavior Applicability\n")
    for result in ("defect", "unverified", "bogus"):
        assert review_report_errors(REVIEW_FIXTURE.replace("| verified |", f"| {result} |"))
    assert review_report_errors(REVIEW_FIXTURE.replace("review payload omits assets", "Unknown"))
    assert review_report_errors(REVIEW_FIXTURE.replace("## Scope\n", "## Scope\n## Scope\n"))
    assert review_report_errors(REVIEW_FIXTURE.replace("Disposition: accepted", "Disposition: blocked"),
                                require_accepted=True)
    for result in ("fail", "blocked"):
        assert review_report_errors(REVIEW_FIXTURE.replace("| pass |", f"| {result} |"))
    defect = REVIEW_FIXTURE.replace("Disposition: accepted", "Disposition: changes_required").replace(
        "| verified |", "| defect |",
    )
    assert review_report_errors(defect) == []
    assert review_report_errors(defect, require_accepted=True)
    # A source-review acceptance does not claim deferred runtime validation passed.
    deferred = REVIEW_FIXTURE.replace("| pass |", "| deferred |")
    assert review_report_errors(deferred) == []
    assert review_report_errors(deferred.replace("Runtime deferred", "None"))
    assert review_report_errors(REVIEW_FIXTURE.replace("## Behavior Review", "## Omitted"))
    assert review_report_errors(REVIEW_FIXTURE.replace("## Findings\nNo confirmed candidate defects.", "## Findings"))
    assert applicability_errors(PLAN_FIXTURE.replace("# Behavior Applicability", "# Omitted"))
    for disposition in ("conditional", "excluded", "deferred"):
        assert applicability_errors(PLAN_FIXTURE.replace("| required |", f"| {disposition} |")) == []
    identity = {"Playbook / version": "playbooks/feature_delivery.md / 0.5.4",
                "Lifecycle": "remediation", "State": "completed"}
    with tempfile.TemporaryDirectory(prefix="review-evidence-") as directory:
        root = Path(directory)
        assert completed_review_errors(identity, root)
        assert completed_review_errors({**identity, "State": "in_progress"}, root) == []
        assert completed_review_errors({**identity, "Lifecycle": "planning"}, root) == []
        report = root / "code_review.md"
        report.write_text(defect)
        assert completed_review_errors(identity, root)
        report.write_text(REVIEW_FIXTURE)
        assert completed_review_errors(identity, root) == []
        assert len(completed_review_errors(identity, root, registered_paths=set(), handoff_paths=set())) == 2
        assert completed_review_errors(identity, root, registered_paths={report.resolve()},
                                       handoff_paths={report.resolve()}) == []


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--plan", type=Path)
    group.add_argument("--review", type=Path)
    group.add_argument("--self-test", action="store_true")
    parser.add_argument("--require-accepted", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        print("review_evidence self-test: passed")
    else:
        try:
            value = (args.plan or args.review).read_text()
            errors = applicability_errors(value) if args.plan else review_report_errors(
                value, require_accepted=args.require_accepted,
            )
        except OSError as error:
            errors = [str(error)]
        print(json.dumps({"status": "failed" if errors else "passed", "errors": errors}))
        raise SystemExit(bool(errors))
