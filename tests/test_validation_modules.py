"""Extracted validation rules preserve contracts and can run independently of the CLI."""

import copy
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.validation import common
from scripts.validation.contracts import jira_adapter_contract_errors, work_item_read_contract_errors
from scripts.validation.frontmatter import SEMVER, frontmatter, frontmatter_value
from scripts.validation.markdown import fenced_section, markdown_errors, markdown_table, table_cells
from scripts.validation.work_records import validate_work_record

ROOT = Path(__file__).resolve().parents[1]


class ValidationModules(unittest.TestCase):
    def test_frontmatter_and_semantic_version_parsing(self):
        self.assertEqual(frontmatter("---\nversion: 0.5.1\n---\nBody"), ["version: 0.5.1"])
        self.assertEqual(frontmatter("---\nversion: 0.5.1"), [])
        self.assertEqual(frontmatter("# No header"), [])
        self.assertTrue(SEMVER.fullmatch("0.5.17"))
        self.assertIsNone(SEMVER.fullmatch("0.05.17"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "document.md"
            path.write_text("---\nversion: 0.5.1\n---\n")
            self.assertEqual(frontmatter_value(path, "version"), "0.5.1")
            self.assertIsNone(frontmatter_value(path, "absent"))

    def test_markdown_parsers_preserve_escaped_cells_and_sections(self):
        self.assertEqual(table_cells(r"| ID | A\|B |"), ["ID", "A|B"])
        table = "# Rows\n\n| ID | Value |\n| --- | --- |\n| E-001 | observed |\n"
        self.assertEqual(markdown_table(table, "# Rows"), [{"ID": "E-001", "Value": "observed"}])
        self.assertEqual(markdown_table(table.replace("| E-001 | observed |", "| E-001 |"), "# Rows"), [])
        self.assertEqual(fenced_section("# Receipt\n\n```text\npassed\n```\n", "# Receipt"), "passed")

    def test_markdown_errors_retain_links_dependencies_width_and_version_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "document.md"
            path.write_text(
                "---\nversion: 0.05.1\ndepends_on:\n  - missing.md\n---\n\n"
                "[missing](also_missing.md)\n\n" + "x" * 121 + "\n"
            )
            errors = markdown_errors(root)
            for expected in ("missing dependency", "broken link", "prose line is 121", "invalid semantic version"):
                self.assertTrue(any(expected in error for error in errors), errors)
            path.write_text("# Valid\n\n```text\n" + "x" * 200 + "\n```\n")
            self.assertEqual(markdown_errors(root), [])

    def test_table_shape_and_fence_failures_remain_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "document.md"
            path.write_text("| A | B |\n| --- |\n| value |\n\n```text\nunclosed\n")
            errors = markdown_errors(root)
            self.assertTrue(any("column-count mismatch" in error for error in errors))
            self.assertTrue(any("unclosed fenced block" in error for error in errors))

    def test_tracked_jira_fixture_and_reference_are_valid(self):
        path = ROOT / "tests/fixtures/jira_adapter_contract.json"
        self.assertIn("../tests/fixtures/jira_adapter_contract.json", (ROOT / "integrations/jira.md").read_text())
        self.assertEqual(jira_adapter_contract_errors(json.loads(path.read_text())), [])
        tracked = subprocess.run(["git", "ls-files", "--error-unmatch", str(path.relative_to(ROOT))],
                                 cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(tracked.returncode, 0, tracked.stderr)

    def test_selected_history_requires_reason_and_explicit_assets(self):
        fixture = json.loads((ROOT / "tests/fixtures/jira_adapter_contract.json").read_text())
        selected = copy.deepcopy(fixture)
        selected["request"]["scope"] = ["item", "history"]
        self.assertTrue(any("selection_reason" in error for error in work_item_read_contract_errors(selected)))
        selected["request"]["selection_reason"] = "Reported symptom requires comment history."
        self.assertEqual(work_item_read_contract_errors(selected), [])
        selected["result"].pop("assets")
        self.assertTrue(any("explicit assets list" in error for error in work_item_read_contract_errors(selected)))
        selected["request"]["scope"] = ["project_scan"]
        self.assertTrue(any("valid non-empty scopes" in error for error in work_item_read_contract_errors(selected)))

    def test_validator_import_runs_no_checks_subprocesses_or_argument_parsing(self):
        code = '''
import sys
from unittest.mock import patch
sys.argv = ["validator", "unrelated-application-argument"]
with patch("pathlib.Path.rglob", side_effect=AssertionError("library scan on import")), \\
     patch("subprocess.run", side_effect=AssertionError("subprocess on import")):
    import scripts.validate_library as validator
    assert callable(validator.main)
    assert callable(validator.validate_library)
'''
        result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_work_record_failures_do_not_leak_into_the_next_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            for name in ("first.md", "second.md"):
                path = Path(directory) / name
                output = io.StringIO()
                with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as error:
                    validate_work_record(path)
                self.assertEqual(error.exception.code, 1)
                self.assertEqual(output.getvalue(), f"FAIL: work record does not exist: {path}\n")
                self.assertIsNone(common._WORK_RECORD_ERRORS)

    def test_work_record_collector_resets_when_a_rule_raises(self):
        with patch("scripts.validation.work_records._validate_work_record", side_effect=ValueError("invalid")):
            with self.assertRaisesRegex(ValueError, "invalid"):
                validate_work_record(Path("record.md"))
        self.assertIsNone(common._WORK_RECORD_ERRORS)

    def test_allow_unreleased_is_local_to_each_cli_invocation(self):
        from scripts import validate_library as cli

        with patch.object(cli, "validate_library"), patch.object(cli, "ROOT") as root, \
             patch.object(cli, "_plugin_version_refresh_error", return_value=None), \
             patch.object(cli, "validate_work_record", return_value="handoff") as record, \
             patch.object(cli, "validate_sentry_artifacts") as artifacts, \
             contextlib.redirect_stdout(io.StringIO()):
            root.glob.return_value = []
            for allowed in (True, False):
                arguments = ["--sentry-artifacts", "/tmp/artifacts", "/tmp/record.md"]
                if allowed:
                    arguments.insert(0, "--allow-unreleased")
                self.assertEqual(cli.main(arguments), 0)
                record.assert_called_with(Path("/tmp/record.md").resolve(), require_terminal=not allowed,
                                          allow_unreleased=allowed)
                artifacts.assert_called_with(Path("/tmp/artifacts").resolve(), allow_unreleased=allowed)

    def test_cli_retains_missing_argument_failure(self):
        from scripts import validate_library as cli

        output = io.StringIO()
        with patch.object(cli, "validate_library"), contextlib.redirect_stdout(output), \
             self.assertRaises(SystemExit) as error:
            cli.main(["--sentry-artifacts"])
        self.assertEqual(error.exception.code, 1)
        self.assertEqual(output.getvalue(), "FAIL: --sentry-artifacts requires one artifact-root path\n")


if __name__ == "__main__":
    unittest.main()
