"""Delivery evidence must prove the current candidate and expose test gaps."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from review_evidence import candidate_fingerprint, delivery_evidence_fixture, review_report_errors, validation_report_errors


class ValidationEvidence(unittest.TestCase):
    def test_coverage_rejects_missing_duplicate_placeholder_and_deferred_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            repository, review, report = delivery_evidence_fixture(Path(directory))
            self.assertEqual(validation_report_errors(report, review, require_solved=True), [])
            report_path = Path(directory) / "validation_report.md"
            review_path = Path(directory) / "code_review.md"
            report_path.write_text(report)
            review_path.write_text(review)
            command = [sys.executable, str(Path(__file__).resolve().parents[1] / "scripts/review_evidence.py"),
                       "--validation", str(report_path), "--review-report", str(review_path),
                       "--repository", str(repository), "--require-solved"]
            self.assertEqual(subprocess.run(command, capture_output=True).returncode, 0)
            report_path.write_text("Tests passed.")
            self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
            rejected = review.replace("Disposition: accepted", "Disposition: changes_required")
            self.assertTrue(validation_report_errors(report, rejected))
            row = next(line for line in report.splitlines() if line.startswith("| Asset-only"))
            for broken in ("Tests passed.", report.replace(row, ""), report.replace(row, row + "\n" + row),
                           report.replace("tests/assets.py:20; fixture command output; local Git candidate", "Unknown"),
                           report.replace("| pass |", "| deferred |"),
                           report.replace("## Release Follow-up\nNo release checks required.", "## Release Follow-up")):
                with self.subTest(report=broken):
                    self.assertTrue(validation_report_errors(broken, review))
            self.assertTrue(validation_report_errors(report.replace("| No remaining local gap |", "| TBD |"), review))
            self.assertTrue(validation_report_errors(report.replace("No release checks required.", "Run D3/D4/D6 in QA."), review))
            release = ("| Check | Environment / dependency | Additional proof | Owner / next action |\n"
                       "| --- | --- | --- | --- |\n"
                       "| Deployed storage smoke | DEV storage API | Verify deployed credentials and endpoint | "
                       "Delivery owner: run after authorized deployment |")
            self.assertEqual(validation_report_errors(report.replace("No release checks required.", release), review), [])
            duplicate = release.replace("Deployed storage smoke", "python -m unittest tests.assets.TestVersion")
            self.assertTrue(validation_report_errors(report.replace("No release checks required.", duplicate), review))

    def test_partial_failure_is_truthful_but_cannot_be_solved(self):
        with tempfile.TemporaryDirectory() as directory:
            _, review, report = delivery_evidence_fixture(Path(directory))
            for result in ("fail", "blocked"):
                partial = report.replace("| pass |", f"| {result} |").replace(
                    "No remaining local gap", "Docker socket unavailable; database check not executed").replace(
                    "Tester: local check complete", "Delivery owner: restore Docker then Tester reruns check")
                self.assertEqual(validation_report_errors(partial, review), [])
                self.assertTrue(validation_report_errors(partial, review, require_solved=True))

    def test_candidate_changes_invalidate_review_and_validation_including_test_only_edits(self):
        with tempfile.TemporaryDirectory() as directory:
            repository, review, report = delivery_evidence_fixture(Path(directory))
            self.assertEqual(validation_report_errors(report, review, expected_repository=repository), [])
            self.assertTrue(validation_report_errors(report, review, expected_repository=repository.parent))
            base = subprocess.check_output(["git", "-C", str(repository), "rev-parse", "HEAD"]).decode().strip()
            prior = candidate_fingerprint(repository, base, [])
            (repository / "test_asset.py").write_text("assert version == 2\n")
            subprocess.run(["git", "-C", str(repository), "add", "test_asset.py"], check=True)
            self.assertNotEqual(candidate_fingerprint(repository, base, []), prior)
            self.assertTrue(validation_report_errors(report, review))
            current = candidate_fingerprint(repository, base, [])
            self.assertTrue(validation_report_errors(report.replace(prior, current), review))
            self.assertEqual(validation_report_errors(report.replace(prior, current), review.replace(prior, current)), [])

    def test_affected_targets_cannot_be_missing_deferred_or_silently_excluded(self):
        with tempfile.TemporaryDirectory() as directory:
            _, review, report = delivery_evidence_fixture(Path(directory))
            start = report.index("## Affected Tests")
            end = report.index("## Release Follow-up", start)
            self.assertTrue(validation_report_errors(report[:start] + report[end:], review))
            review_start = review.index("## Affected Tests")
            review_end = review.index("## Findings", review_start)
            self.assertTrue(review_report_errors(review[:review_start] + review[review_end:], require_accepted=True))
            inventory = report[start:end]
            row = next(line for line in inventory.splitlines() if line.startswith("| Asset-only"))
            for broken in (inventory.replace(row, ""), inventory.replace(row, row + "\n" + row),
                           inventory.replace("| pass |", "| deferred |"),
                           inventory.replace("| pass |", "| excluded |"),
                           inventory.replace("asset.py caller search; test discovery", "Unknown"),
                           inventory.replace("Reviewer:", "Implementer:"),
                           inventory.replace("tests/assets.py:20; fixture command output", "Pending"),
                           inventory.replace("| pass |", "| bogus |")):
                with self.subTest(inventory=broken):
                    self.assertTrue(validation_report_errors(report.replace(inventory, broken), review))
            extra = row.replace("tests.assets.TestVersion", "tests.consumer.TestSQLArguments")
            expanded_review = review.replace(row, row + "\n" + extra)
            self.assertTrue(validation_report_errors(report, expanded_review))
            expanded_report = report.replace(row, row + "\n" + extra)
            self.assertEqual(validation_report_errors(expanded_report, expanded_review, require_solved=True), [])
            excluded = extra.replace("| pass |", "| excluded |").replace(
                "tests/assets.py:20; fixture command output", "Not executed: reviewed exclusion").replace(
                "Reviewer: traced upload consumer and owning tests",
                "Reviewer: consumer uses independent storage; traced source proves no changed contract")
            self.assertEqual(validation_report_errors(report.replace(row, row + "\n" + excluded),
                review.replace(row, row + "\n" + excluded), require_solved=True), [])
            for result in ("fail", "blocked"):
                partial = report.replace(inventory, inventory.replace("| pass |", f"| {result} |"))
                self.assertEqual(validation_report_errors(partial, review), [])
                self.assertTrue(validation_report_errors(partial, review, require_solved=True))
                self.assertTrue(review_report_errors(review.replace(row, row.replace("| pass |", f"| {result} |"))))
            deferred_review = review.replace(row, row.replace("| pass |", "| deferred |"))
            self.assertEqual(validation_report_errors(report, deferred_review, require_solved=True), [])

    def test_untracked_candidate_content_is_bound_and_paths_are_constrained(self):
        with tempfile.TemporaryDirectory() as directory:
            repository, _, _ = delivery_evidence_fixture(Path(directory))
            base = subprocess.check_output(["git", "-C", str(repository), "rev-parse", "HEAD"]).decode().strip()
            new_file = repository / "test_asset.py"
            new_file.write_text("assert version == 2\n")
            first = candidate_fingerprint(repository, base, [new_file.name])
            new_file.write_text("assert version == 3\n")
            self.assertNotEqual(first, candidate_fingerprint(repository, base, [new_file.name]))
            for paths in (["../outside"], [str(new_file)], [new_file.name, new_file.name], ["missing.py"]):
                with self.subTest(paths=paths), self.assertRaises(ValueError):
                    candidate_fingerprint(repository, base, paths)


if __name__ == "__main__":
    unittest.main()
