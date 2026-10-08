"""Structural evidence gates; source correctness remains an independent review obligation."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
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


RELEASE_COLUMNS = ("Check", "Environment / dependency", "Additional proof", "Owner / next action")
COVERAGE_COLUMNS = (
    "Criterion / behavior", "Test / check", "Result", "Evidence / environment",
    "Gap / reason", "Owner / next action",
)


def candidate_fingerprint(repository: Path, base: str, untracked: list[str]) -> str:
    """Bind review to commits, tracked edits and explicitly included new files."""
    def git(*args: str) -> bytes:
        return subprocess.check_output(["git", "-c", "core.fsmonitor=false", "-C", str(repository), *args],
                                       stderr=subprocess.PIPE)
    head = git("rev-parse", "HEAD").strip().decode()
    revision = git("rev-parse", "--verify", f"{base}^{{commit}}").strip().decode()
    files = []
    root = repository.resolve()
    if len(untracked) != len(set(untracked)):
        raise ValueError("duplicate untracked candidate file")
    available = set(git("ls-files", "--others", "--exclude-standard", "-z").decode().split("\0"))
    for name in sorted(untracked):
        path = (root / name).resolve()
        if Path(name).is_absolute() or not path.is_relative_to(root) or name not in available:
            raise ValueError(f"not an untracked candidate file: {name}")
        files.append([name, hashlib.sha256(path.read_bytes()).hexdigest()])
    content = {"base": revision, "head": head,
               "diff": hashlib.sha256(git("diff", "--binary", "--no-ext-diff", "--no-textconv", revision, "--")).hexdigest(),
               "untracked": files}
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()


def _candidate_fields(text: str) -> tuple[dict[str, str], list[str]]:
    fields = {}
    errors = []
    for name in ("Repository", "Base revision", "Candidate SHA256", "Untracked candidate files"):
        values = re.findall(rf"^{re.escape(name)}: (.+)$", text, re.M)
        if len(values) != 1:
            errors.append(f"requires exactly one {name} field")
        else:
            fields[name] = values[0].strip()
    if not re.fullmatch(r"[0-9a-f]{64}", fields.get("Candidate SHA256", "")):
        errors.append("requires a concrete Candidate SHA256")
    return fields, errors


def validation_report_errors(text: str, review_text: str, *, require_solved: bool = False,
                             expected_repository: Path | None = None, require_accepted: bool = True) -> list[str]:
    """Reconcile Tester coverage with review and independently inspect the current candidate."""
    errors = review_report_errors(review_text, require_accepted=require_accepted)
    errors.extend(_heading_errors(text, ("# Validation Report", "## Behavior Coverage", "## Release Follow-up")))
    candidate, candidate_errors = _candidate_fields(text)
    reviewed, review_errors = _candidate_fields(review_text)
    errors.extend(candidate_errors + review_errors)
    if not candidate_errors and not review_errors:
        if candidate != reviewed:
            errors.append("validation candidate must match the accepted review candidate")
        try:
            repository = Path(candidate["Repository"])
            if not repository.is_absolute():
                raise ValueError("Repository must be an absolute path")
            if expected_repository is not None and repository.resolve() != expected_repository.resolve():
                errors.append("validation repository must match the execution repository")
            untracked = json.loads(candidate["Untracked candidate files"])
            if not isinstance(untracked, list) or any(not isinstance(name, str) for name in untracked):
                raise ValueError("Untracked candidate files must be a JSON list of paths")
            if candidate_fingerprint(repository, candidate["Base revision"], untracked) != candidate["Candidate SHA256"]:
                errors.append("candidate changed since review/validation; return to Implementer, Reviewer and Tester")
        except (OSError, ValueError, subprocess.CalledProcessError) as error:
            errors.append(f"candidate verification unavailable: {error}")
    rows, row_errors = _rows(text, "## Behavior Coverage", COVERAGE_COLUMNS)
    errors.extend(row_errors)
    behaviors, behavior_errors = _rows(review_text, "## Behavior Review", REVIEW_COLUMNS)
    errors.extend(behavior_errors)
    names = [row[0] for row in rows]
    if len(names) != len(set(names)):
        errors.append("validation coverage has duplicate behaviors")
    if set(names) != {row[0] for row in behaviors}:
        errors.append("validation coverage must reconcile every reviewed behavior without extra rows")
    for index, row in enumerate(rows, 1):
        if row[2] not in {"pass", "fail", "blocked", "not_applicable"}:
            errors.append(f"coverage row {index} has invalid result; runnable gaps cannot be deferred")
        if any(row[column].strip("` ").lower() in PLACEHOLDERS for column in (0, 1, 3, 4, 5)):
            errors.append(f"coverage row {index} requires a check, evidence, reason and owner/next action")
        if require_solved and row[2] in {"fail", "blocked"}:
            errors.append(f"solved delivery cannot contain unresolved coverage row {index}")
    release = _section(text, "## Release Follow-up")
    if release != "No release checks required.":
        follow_up, follow_up_errors = _rows(text, "## Release Follow-up", RELEASE_COLUMNS)
        errors.extend(follow_up_errors)
        passed = {row[1] for row in rows if row[2] == "pass"}
        for index, row in enumerate(follow_up, 1):
            if any(cell.strip("` ").lower() in PLACEHOLDERS for cell in row):
                errors.append(f"release row {index} requires environment, additional proof and owner/next action")
            if row[0] in passed:
                errors.append(f"release row {index} repeats a passed local check")
    return list(dict.fromkeys(errors))


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


def delivery_evidence_fixture(root: Path) -> tuple[Path, str, str]:
    """Real Git candidate used by the evidence and finalization regressions."""
    repository = root / "candidate"
    repository.mkdir()
    def git(*args: str) -> str:
        return subprocess.check_output(["git", "-C", str(repository), *args], stderr=subprocess.PIPE).decode().strip()
    git("init")
    (repository / "asset.py").write_text("version = 1\n")
    git("add", "asset.py")
    git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "-c", "commit.gpgsign=false",
        "-c", "core.hooksPath=/dev/null", "commit", "-m", "baseline")
    base = git("rev-parse", "HEAD")
    (repository / "asset.py").write_text("version = 2\n")
    fields = (f"Repository: {repository}\nBase revision: {base}\n"
              f"Candidate SHA256: {candidate_fingerprint(repository, base, [])}\nUntracked candidate files: []\n")
    review = REVIEW_FIXTURE.replace("## Scope\n", "## Scope\n" + fields)
    validation = ("# Validation Report\n## Candidate\n" + fields + "## Behavior Coverage\n| "
                  + " | ".join(COVERAGE_COLUMNS) + " |\n| " + " | ".join(["---"] * 6) + " |\n"
                  "| Asset-only edit preserves publication | python -m unittest tests.assets.TestVersion | pass | "
                  "tests/assets.py:20; fixture command output; local Git candidate | "
                  "No remaining local gap | Tester: local check complete |\n"
                  "## Release Follow-up\nNo release checks required.\n")
    return repository, review, validation


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
    group.add_argument("--validation", type=Path)
    group.add_argument("--fingerprint", action="store_true")
    parser.add_argument("--review-report", type=Path)
    parser.add_argument("--repository", type=Path)
    parser.add_argument("--base")
    parser.add_argument("--untracked", nargs="*", default=[])
    parser.add_argument("--require-solved", action="store_true")
    parser.add_argument("--require-accepted", action="store_true")
    args = parser.parse_args()
    if args.fingerprint:
        if not args.repository or not args.base:
            parser.error("--fingerprint requires --repository and --base")
        print(candidate_fingerprint(args.repository, args.base, args.untracked))
    elif args.self_test:
        self_test()
        print("review_evidence self-test: passed")
    else:
        try:
            if args.validation:
                if not args.review_report:
                    parser.error("--validation requires --review-report")
                errors = validation_report_errors(args.validation.read_text(), args.review_report.read_text(),
                                                  require_solved=args.require_solved,
                                                  expected_repository=args.repository)
            else:
                value = (args.plan or args.review).read_text()
                errors = applicability_errors(value) if args.plan else review_report_errors(
                    value, require_accepted=args.require_accepted,
                )
        except OSError as error:
            errors = [str(error)]
        print(json.dumps({"status": "failed" if errors else "passed", "errors": errors}))
        raise SystemExit(bool(errors))
