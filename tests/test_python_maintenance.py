"""Correctness and compatibility gates for the Python maintenance pass."""

import ast
import contextlib
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import prepare_run, validate_library
from scripts.asset_manifest import asset_plan_errors
from scripts.normalize_fix_design_result import normalize_artifact_root
from scripts.review_evidence import _rows
from scripts.run_input_manifest import load_manifest, packet_metadata
from scripts.specification_assessment import coverage_mapping_errors
from scripts.validation.api import checked, record_validation_output, validate_package
from scripts.validation.common import fail
from scripts.validation.finalization import validate_sentry_artifacts
from scripts.validation.markdown import table_cells

ROOT = Path(__file__).resolve().parents[1]


class PythonMaintenance(unittest.TestCase):
    def test_every_playbook_freezes_supplied_source_bytes_without_freezing_the_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.py"
            source.write_text("before implementation\n")
            supplied = root / "inputs.json"
            supplied.write_text(json.dumps({"inputs": [{
                "Input ID": "SRC-001", "Input or artifact": "Source baseline", "Source or path": str(source),
                "Authority": "Current repository", "Status": "Observed", "Classification": "repository source",
            }]}))
            for playbook in sorted(prepare_run.PLAYBOOKS):
                with self.subTest(playbook=playbook):
                    source.write_text("before implementation\n")
                    artifact_root = root / playbook
                    artifact_root.mkdir()
                    manifest, path = prepare_run._prepare_run_inputs(
                        artifact_root, "ITEM-1", playbook, root, supplied, False)
                    metadata = packet_metadata(path, manifest)
                    snapshot = Path(manifest["inputs"][0]["path"])
                    self.assertNotEqual(source, snapshot)
                    source.write_text("approved implementation\n")
                    loaded = load_manifest(path)
                    self.assertEqual(loaded["inputs"][0]["sha256"], hashlib.sha256(snapshot.read_bytes()).hexdigest())
                    self.assertEqual(loaded["inputs"][0]["Original source path"], str(source.resolve()))
                    self.assertEqual(metadata["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
                    continued, _ = prepare_run._prepare_run_inputs(
                        artifact_root, "ITEM-1", playbook, root, None, True)
                    self.assertEqual(continued["inputs"], loaded["inputs"])
                    snapshot.write_text("tampered saved evidence")
                    with self.assertRaisesRegex(ValueError, "run_input_manifest_hash_mismatch:SRC-001"):
                        load_manifest(path)
                    snapshot.unlink()
                    with self.assertRaisesRegex(ValueError, "run_input_manifest_hashed_file_unavailable:SRC-001"):
                        load_manifest(path)

    def test_supplied_evidence_hash_mismatch_is_still_rejected_before_snapshotting(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "evidence.txt"
            source.write_text("current")
            supplied = root / "inputs.json"
            supplied.write_text(json.dumps({"inputs": [{
                "Input ID": "E-001", "Input or artifact": "Supplied evidence", "Source or path": str(source),
                "Authority": "User", "Status": "Observed", "sha256": "0" * 64,
            }]}))
            with self.assertRaisesRegex(ValueError, "hash_mismatch:E-001"):
                prepare_run._prepare_run_inputs(root / "run", "ITEM-1", "sentry_issue_remediation", root, supplied, False)
            self.assertFalse((root / "run").exists())

    def test_asset_and_assessment_tables_accept_escaped_pipes_and_reject_extra_columns(self):
        plan = ("# Asset Baseline\nasset_manifest.json\n"
                "| Asset ID | Evidence refs | Observation | Planning consequence |\n"
                "| --- | --- | --- | --- |\n"
                r"| A-001 | E-001 | A\|B observed | preserve A\|B |" + "\n")
        assets = {"assets": [{"asset_id": "A-001", "relevance": "material", "evidence_refs": ["E-001"]}]}
        self.assertEqual(asset_plan_errors(plan, assets), [])
        self.assertTrue(asset_plan_errors(plan.replace(r"A\|B observed", "A|B observed"), assets))
        coverage = ("## Coverage\n"
                    "| Requirement / behavior | Story | Evidence | Status | Gap | Impact | Action |\n"
                    "| --- | --- | --- | --- | --- | --- | --- |\n"
                    r"| A\|B | ITEM-1 | E-001 | Covered | None | None | Retain |" + "\n")
        self.assertEqual(coverage_mapping_errors(coverage, "assessment"), [])
        self.assertTrue(coverage_mapping_errors(coverage.replace(r"A\|B", "A|B"), "assessment"))

    def test_shared_parser_preserves_optional_outer_pipes_and_empty_edge_cells(self):
        for line in (r"| A | B\|C", r"A | B\|C |", r"| A | B\|C |"):
            self.assertEqual(table_cells(line), ["A", "B|C"])
        self.assertEqual(table_cells("|| A ||"), ["", "A", ""])
        rows, errors = _rows("## Review\n| A | B |\n| --- | --- |\n| first | last value\n",
                             "## Review", ("A", "B"))
        self.assertEqual(errors, [])
        self.assertEqual(rows, [["first", "last value"]])

    def test_artifact_gate_rejects_a_rewritten_input_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            supplied = root / "inputs.json"
            supplied.write_text(json.dumps({"inputs": [{
                "Input ID": "IN-001", "Input or artifact": "Current request", "Source or path": "User request",
                "Authority": "User", "Status": "Observed",
            }]}))
            manifest, path = prepare_run._prepare_run_inputs(root, "ITEM-1", "sentry_issue_remediation",
                                                            root, supplied, False)
            packet = {"run_input_manifest": packet_metadata(path, manifest), "inputs": manifest["inputs"]}
            (root / "finalization_packet.json").write_text(json.dumps(packet))
            path.write_text(path.read_text().replace("Current request", "Rewritten request"))
            with self.assertRaisesRegex(ValueError, "run_input_manifest hash does not match finalization metadata"):
                checked(validate_sentry_artifacts, root, allow_unreleased=True)

    def test_help_and_invalid_arguments_do_not_scan_library(self):
        for args, status in ((["--help"], 0), (["--not-a-flag"], 2), (["--normalized-evidence"], 2)):
            with self.subTest(args=args), patch.object(validate_library, "validate_library") as scan, \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()), \
                    self.assertRaises(SystemExit) as error:
                validate_library.main(args)
            self.assertEqual(error.exception.code, status)
            scan.assert_not_called()
        for entrypoint in (["scripts/validate_library.py"], ["-m", "scripts.validate_library"]):
            result = subprocess.run([sys.executable, *entrypoint, "--help"], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("--technical-spike-expected-revision", result.stdout)

    def test_internal_normalization_checks_fresh_artifacts_without_spawning_a_validator(self):
        fixture = json.loads((ROOT / "tests/fixtures/v37_v38_sentry_runtime_regressions.json").read_text())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            design = root / "fix_design_result.json"
            design.write_text(json.dumps(fixture["valid_awaiting_fix_design_result"]))
            evidence = root / "normalized_evidence.md"
            evidence.write_text(fixture["normalized_evidence"])
            before = design.read_bytes()
            with patch("subprocess.run", side_effect=AssertionError("child validator")), \
                    patch("scripts.validation.api.validate_library", side_effect=AssertionError("library scan")):
                self.assertEqual(normalize_artifact_root(root)["validation"], "passed")
                evidence.write_text("invalid evidence")
                with self.assertRaisesRegex(ValueError, "normalized candidate failed validation"):
                    normalize_artifact_root(root)
            self.assertEqual(design.read_bytes(), before)

    def test_api_failure_translation_and_package_gate_preserve_rejection(self):
        with self.assertRaisesRegex(ValueError, "FAIL: rejected"):
            checked(fail, "rejected")
        with patch("scripts.validation.api.validate_library") as scan, \
                patch("scripts.validation.api._plugin_version_refresh_error", return_value="stale package"):
            with self.assertRaisesRegex(ValueError, "stale package"):
                checked(validate_package)
            scan.assert_called_once_with()

    def test_api_resolves_record_paths_like_the_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "record.md"
            with patch("scripts.validation.api.validate_work_record", return_value="canonical handoff") as check:
                self.assertEqual(record_validation_output(path), "Workflow-framework validation: passed\ncanonical handoff\n")
                check.assert_called_once_with(path.resolve(), require_terminal=True, allow_unreleased=False)

    def test_python_children_use_the_current_interpreter(self):
        for path in (ROOT / "scripts").rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.List) and node.elts and isinstance(node.elts[0], ast.Constant):
                    self.assertNotIn(node.elts[0].value, {"python", "python3"}, path)

    def test_cli_keeps_repeated_spike_revisions(self):
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "report.md"
            report.write_text("report")
            with patch.object(validate_library, "validate_library"), \
                    patch.object(validate_library, "ROOT") as root, \
                    patch.object(validate_library, "_plugin_version_refresh_error", return_value=None), \
                    patch.object(validate_library, "technical_spike_report_errors", return_value=[]) as check, \
                    contextlib.redirect_stdout(io.StringIO()):
                root.glob.return_value = []
                self.assertEqual(validate_library.main([
                    "--technical-spike-report", str(report), "--technical-spike-primary-goal", "execute technical spike",
                    "--technical-spike-profile", "standard", "--technical-spike-workflow-result", "Question answered",
                    "--technical-spike-expected-revision", "a" * 40,
                    "--technical-spike-expected-revision", "b" * 40,
                ]), 0)
                self.assertEqual(check.call_args.args[-1], ("a" * 40, "b" * 40))

    def test_runtime_and_planning_libraries_do_not_import_cli_or_test_modules(self):
        forbidden = {"finalize_work_record", "prepare_run", "validate_worker_runtime", "tests"}
        for name in ("planning_contracts", "runtime_checks", "provider_runtime", "work_record_format"):
            for node in ast.walk(ast.parse((ROOT / "scripts" / (name + ".py")).read_text())):
                if isinstance(node, ast.ImportFrom):
                    parts = (node.module or "").split(".")
                    self.assertFalse(forbidden.intersection(parts), (name, node.module))


if __name__ == "__main__":
    unittest.main()
