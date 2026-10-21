"""Reproductions from the independent Python and v8 review."""

import copy
import csv
import json
import subprocess
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from scripts import prepare_run
from scripts.finalize_work_record import failure_handoff
from scripts.run_input_manifest import load_manifest, packet_metadata, retain_source_releases, source_release_errors
from scripts.planning_contracts import _feature_expected_inputs
from scripts.asset_manifest import validate_asset_manifest, _check_source_files
from scripts.validation.markdown import table_cells
from scripts.review_evidence import _rows
from tests.parent_status_support import write_parent_status_session
from tests import test_sentry_handoff as v8


class ReviewRegressions(unittest.TestCase):
    def repository(self, root):
        repository = root / "repo"
        repository.mkdir()
        for args in (("init", "-q"), ("config", "user.name", "Fixture"),
                     ("config", "user.email", "fixture@example.invalid")):
            subprocess.run(["git", "-C", str(repository), *args], check=True, capture_output=True)
        (repository / "README.md").write_text("fixture")
        for args in (("add", "."), ("commit", "-qm", "fixture")):
            subprocess.run(["git", "-C", str(repository), *args], check=True, capture_output=True)
        return repository

    def input_file(self, path, source):
        path.write_text(json.dumps({"inputs": [{"Input ID": "IN-001", "Input or artifact": "Explicitly selected input",
            "Source or path": str(source), "Authority": "User", "Status": "Registered"}]}))
        return path

    def parent_status_session(self, repository, work_item):
        artifact_root = repository / ".thoughts" / work_item
        return write_parent_status_session(repository.parent / "parent-status.jsonl", artifact_root)

    def test_fresh_restart_preserves_selected_input_before_archiving(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = self.repository(Path(directory))
            inputs = self.input_file(repository / "initial.json", "Current request")
            first = prepare_run.prepare_run(repository, "ITEM-1", "sentry_issue_remediation", None, False,
                                            input_manifest=inputs)
            root = Path(first["artifact_root"])
            decision = root / "accepted_decision.md"
            decision.write_text("Explicitly accepted decision")
            selected = self.input_file(root / "next_inputs.json", decision)
            second = prepare_run.prepare_run(repository, "ITEM-1", "sentry_issue_remediation", None, False,
                                             input_manifest=selected, archive_stale_run=True,
                                             provider_session=self.parent_status_session(repository, "ITEM-1"))
            row = load_manifest(Path(second["run_input_manifest"]["path"]))["inputs"][0]
            self.assertEqual(Path(row["path"]).read_text(), "Explicitly accepted decision")
            self.assertEqual(row["Original source path"], str(decision.resolve()))
            self.assertEqual(len(list((root / "runs").rglob(decision.name))), 1)
            self.assertNotEqual(first["run_id"], second["run_id"])

    def test_snapshot_read_failure_leaves_existing_run_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = self.repository(Path(directory))
            inputs = self.input_file(repository / "initial.json", "Current request")
            run = prepare_run.prepare_run(repository, "ITEM-1", "sentry_issue_remediation", None, False,
                                         input_manifest=inputs)
            root = Path(run["artifact_root"])
            decision = root / "accepted_decision.md"
            decision.write_text("Accepted decision")
            selected = self.input_file(repository / "next.json", decision)
            before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
            original = prepare_run._snapshot_input_files
            def fail_capture(*args, **kwargs):
                if kwargs.get("persist") is False:
                    raise OSError("cannot stage input")
                return original(*args, **kwargs)
            with patch.object(prepare_run, "_snapshot_input_files", side_effect=fail_capture):
                with self.assertRaisesRegex(OSError, "cannot stage input"):
                    prepare_run.prepare_run(repository, "ITEM-1", "sentry_issue_remediation", None, False,
                                            input_manifest=selected, archive_stale_run=True,
                                            provider_session=self.parent_status_session(repository, "ITEM-1"))
            self.assertEqual(before, {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()})

    def test_fresh_restart_preserves_explicitly_selected_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = self.repository(Path(directory))
            initial = self.input_file(repository / "initial.json", "Current request")
            first = prepare_run.prepare_run(repository, "ITEM-1", "sentry_issue_remediation", None, False,
                                            input_manifest=initial)
            root = Path(first["artifact_root"])
            folder = root / "selected_docs"
            folder.mkdir()
            (folder / "decision.md").write_text("Explicitly selected decision")
            (folder / "empty").mkdir()
            (folder / "link").symlink_to("decision.md")
            source_file = root / "selected.txt"
            source_file.write_text("Selected file")
            supplied = self.input_file(repository / "next.json", str(folder) + "; " + str(source_file))
            second = prepare_run.prepare_run(repository, "ITEM-1", "sentry_issue_remediation", None, False,
                                             input_manifest=supplied, archive_stale_run=True,
                                             provider_session=self.parent_status_session(repository, "ITEM-1"))
            row = load_manifest(Path(second["run_input_manifest"]["path"]))["inputs"][0]
            copied = Path(row["paths"][0])
            self.assertTrue(copied.is_relative_to(root))
            self.assertEqual((copied / "decision.md").read_text(), "Explicitly selected decision")
            self.assertTrue((copied / "empty").is_dir())
            self.assertTrue((copied / "link").is_symlink())
            self.assertEqual(Path(row["paths"][1]).read_text(), "Selected file")
            self.assertFalse(folder.exists())
            self.assertEqual(row["Original source paths"], [str(folder), str(source_file)])

            selected_directory = self.input_file(repository / "directory.json", copied)
            third = prepare_run.prepare_run(repository, "ITEM-1", "sentry_issue_remediation", None, False,
                                            input_manifest=selected_directory, archive_stale_run=True,
                                            provider_session=self.parent_status_session(repository, "ITEM-1"))
            single = load_manifest(Path(third["run_input_manifest"]["path"]))["inputs"][0]
            self.assertEqual((Path(single["path"]) / "decision.md").read_text(), "Explicitly selected decision")
            self.assertEqual(single["Original source path"], str(copied))

    def test_repeated_fresh_archives_in_one_second_have_distinct_names(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = root / "work_record.md"
            with patch.object(prepare_run, "datetime") as clock:
                clock.now.side_effect = [datetime(2026, 10, 15, microsecond=value, tzinfo=UTC)
                                         for value in (100, 200)]
                record.write_text("| State | intake |\n")
                status_context = {"verified_related_run_status_probes": 1,
                                  "related_run_status_probe_attempts": 1,
                                  "related_run_status_rows": [], "related_run_thread_ids": [],
                                  "prior_run_dispatch_ledger_present": False}
                first = prepare_run._archive_existing_run(root, True, parent_context=status_context)
                record.write_text("| State | intake |\n")
                second = prepare_run._archive_existing_run(root, True, parent_context=status_context)
            self.assertNotEqual(first, second)
            self.assertTrue((Path(first) / "work_record.md").is_file())
            self.assertTrue((Path(second) / "work_record.md").is_file())

    def test_directory_capture_failure_does_not_archive_the_run(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = self.repository(Path(directory))
            initial = self.input_file(repository / "initial.json", "Current request")
            run = prepare_run.prepare_run(repository, "ITEM-1", "sentry_issue_remediation", None, False,
                                         input_manifest=initial)
            root = Path(run["artifact_root"])
            folder = root / "selected_docs"
            folder.mkdir()
            (folder / "decision.md").write_text("Selected decision")
            supplied = self.input_file(repository / "next.json", folder)
            before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
            with patch.object(prepare_run.shutil, "copytree", side_effect=OSError("directory copy failed")):
                with self.assertRaisesRegex(OSError, "directory copy failed"):
                    prepare_run.prepare_run(repository, "ITEM-1", "sentry_issue_remediation", None, False,
                                                input_manifest=supplied, archive_stale_run=True,
                                                provider_session=self.parent_status_session(repository, "ITEM-1"))
            self.assertEqual(before, {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()})

    def test_directory_publication_failure_restores_the_old_run(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = self.repository(Path(directory))
            initial = self.input_file(repository / "initial.json", "Current request")
            run = prepare_run.prepare_run(repository, "ITEM-1", "sentry_issue_remediation", None, False,
                                         input_manifest=initial)
            root = Path(run["artifact_root"])
            folder = root / "selected_docs"
            folder.mkdir()
            (folder / "decision.md").write_text("Selected decision")
            supplied = self.input_file(repository / "next.json", folder)
            before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
            original = prepare_run.shutil.copytree
            def fail_publication(source, destination, *args, **kwargs):
                if Path(destination).is_relative_to(root / "input_snapshots"):
                    Path(destination).mkdir(parents=True)
                    (Path(destination) / "partial").write_text("Partial publication")
                    raise OSError("publication failed")
                return original(source, destination, *args, **kwargs)
            with patch.object(prepare_run.shutil, "copytree", side_effect=fail_publication):
                with self.assertRaisesRegex(OSError, "publication failed"):
                    prepare_run.prepare_run(repository, "ITEM-1", "sentry_issue_remediation", None, False,
                                                input_manifest=supplied, archive_stale_run=True,
                                                provider_session=self.parent_status_session(repository, "ITEM-1"))
            self.assertEqual(before, {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()})

    def test_archive_move_failures_restore_existing_snapshots_and_artifacts(self):
        for failure_at in (2, 4):
            with self.subTest(failure_at=failure_at), tempfile.TemporaryDirectory() as directory:
                repository = self.repository(Path(directory))
                source = repository / "evidence.txt"
                source.write_text("Existing snapshot")
                initial = self.input_file(repository / "initial.json", source)
                run = prepare_run.prepare_run(repository, "ITEM-1", "sentry_issue_remediation", None, False,
                                             input_manifest=initial)
                root = Path(run["artifact_root"])
                folder = root / "selected_docs"
                folder.mkdir()
                (folder / "decision.md").write_text("Selected decision")
                supplied = self.input_file(repository / "next.json", folder)
                before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
                original, calls = prepare_run.shutil.move, []
                def fail_move(source, destination, *args, **kwargs):
                    if Path(source).parent == root:
                        calls.append(source)
                        if len(calls) == failure_at:
                            raise OSError("archive move failed")
                    return original(source, destination, *args, **kwargs)
                with patch.object(prepare_run.shutil, "move", side_effect=fail_move):
                    with self.assertRaisesRegex(OSError, "archive move failed"):
                        prepare_run.prepare_run(repository, "ITEM-1", "sentry_issue_remediation", None, False,
                                                input_manifest=supplied, archive_stale_run=True,
                                                provider_session=self.parent_status_session(repository, "ITEM-1"))
                self.assertEqual(before, {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()})

    def test_file_disappearing_before_capture_is_rejected_before_any_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "selected.txt"
            source.write_text("selected evidence")
            supplied = self.input_file(root / "inputs.json", source)
            manifest = load_manifest(supplied)
            source.unlink()
            with self.assertRaisesRegex(ValueError, "hashed_file_unavailable"):
                prepare_run._snapshot_input_files(root / "run", manifest, persist=False, input_bytes={})
            self.assertFalse((root / "run").exists())

    def test_multi_file_inputs_are_snapshotted_and_checked_for_every_playbook(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for playbook in sorted(prepare_run.PLAYBOOKS):
                for explicit_list in (False, True):
                    with self.subTest(playbook=playbook, explicit_list=explicit_list):
                        source_root = root / (playbook + str(explicit_list))
                        source_root.mkdir()
                        sources = [source_root / "a.txt", source_root / "b.txt"]
                        for index, source in enumerate(sources):
                            source.write_text(str(index))
                        supplied = self.input_file(source_root / "inputs.json", "; ".join(map(str, sources)))
                        if explicit_list:
                            value = json.loads(supplied.read_text())
                            value["inputs"][0]["path"] = list(map(str, sources))
                            supplied.write_text(json.dumps(value))
                        run = source_root / "run"
                        run.mkdir()
                        manifest, path = prepare_run._prepare_run_inputs(run, "ITEM-1", playbook, root, supplied, False)
                        row = manifest["inputs"][0]
                        self.assertEqual([Path(p).read_text() for p in row["paths"]], ["0", "1"])
                        self.assertTrue(all(Path(p).is_relative_to(run.resolve()) for p in row["paths"]))
                        sources[0].write_text("changed original")
                        sources[1].unlink()
                        self.assertEqual(load_manifest(path)["inputs"][0], row)
                        snapshot = Path(row["paths"][0])
                        snapshot.write_text("tampered snapshot")
                        with self.assertRaisesRegex(ValueError, "hash_mismatch"):
                            load_manifest(path)
                        snapshot.unlink()
                        with self.assertRaisesRegex(ValueError, "hashed_file_unavailable"):
                            load_manifest(path)

    def test_continuation_adds_file_inputs_and_rejects_conflicts_before_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = self.repository(Path(directory))
            inputs = self.input_file(repository / "initial.json", "Current request")
            run = prepare_run.prepare_run(repository, "ITEM-1", "sentry_issue_remediation", None, False,
                                         input_manifest=inputs)
            root = Path(run["artifact_root"])
            source = repository / "additional.txt"
            source.write_text("new evidence")
            supplied = self.input_file(repository / "additional.json", source)
            value = json.loads(supplied.read_text())
            value["inputs"][0]["Input ID"] = "IN-002"
            supplied.write_text(json.dumps(value))
            prepare_run.prepare_run(repository, "ITEM-1", "sentry_issue_remediation", None, True, input_manifest=supplied)
            row = load_manifest(root / "run_inputs.json")["inputs"][1]
            self.assertEqual(Path(row["path"]).read_text(), "new evidence")
            before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
            source.write_text("conflicting replacement")
            with self.assertRaisesRegex(ValueError, "conflicting_input_id:IN-002"):
                prepare_run.prepare_run(repository, "ITEM-1", "sentry_issue_remediation", None, True,
                                        input_manifest=supplied)
            self.assertEqual(before, {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()})

    def test_grouped_csv_release_and_occurrence_retention_matches_single_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self.repository(root)
            logs = [repository / "first.csv", repository / "second.csv"]
            for index, log in enumerate(logs):
                with log.open("w", newline="") as stream:
                    writer = csv.DictWriter(stream, fieldnames=["message"])
                    writer.writeheader()
                    writer.writerow({"message": "Using release from debug info: " + ("a" if index == 0 else "b") * 40})
                    item = {"time": "2026-10-14T01:02:03Z", "workflow_item": {
                        "organization_id": 1, "asset_id": index, "referent_id": "123", "private_payload": "do not retain"}}
                    writer.writerow({"message": json.dumps(item)})
                    writer.writerow({"message": json.dumps(item)})
            supplied = self.input_file(repository / "grouped.json", "; ".join(map(str, logs)))
            run = prepare_run.prepare_run(repository, "ITEM-1", "sentry_issue_remediation", None, False,
                                         input_manifest=supplied)
            saved = load_manifest(Path(run["run_input_manifest"]["path"]))
            row = saved["inputs"][0]
            self.assertEqual(row["Observed releases"], ["a" * 40, "b" * 40])
            self.assertEqual(len(row["Occurrence correlation"]), 2)
            self.assertNotIn("do not retain", json.dumps(saved))
            self.assertEqual(len(source_release_errors("Release unknown", saved)), 2)
            expected = "IN-001 " + "a" * 40 + " " + "b" * 40
            self.assertEqual(source_release_errors(expected, saved), [])
            for log in logs:
                log.unlink()
            retain_source_releases(saved, None)
            self.assertEqual(saved["inputs"][0]["Observed releases"], ["a" * 40, "b" * 40])
            self.assertEqual(len(saved["inputs"][0]["Occurrence correlation"]), 2)

    def test_feature_packet_reconciles_grouped_paths_and_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sources = [root / "a.txt", root / "b.txt"]
            for source in sources:
                source.write_text(source.name)
            supplied = self.input_file(root / "inputs.json", "; ".join(map(str, sources)))
            run = root / "run"
            run.mkdir()
            manifest, path = prepare_run._prepare_run_inputs(run, "ITEM-1", "feature_delivery", root, supplied, False)
            packet = {"run_input_manifest": packet_metadata(path, manifest), "identity": {},
                      "inputs": copy.deepcopy(manifest["inputs"])}
            self.assertEqual(_feature_expected_inputs(packet, run)[1], [])
            for field in ("paths", "sha256_by_path"):
                for missing in (False, True):
                    with self.subTest(field=field, missing=missing):
                        changed = copy.deepcopy(packet)
                        if missing:
                            changed["inputs"][0].pop(field)
                        else:
                            changed["inputs"][0][field] = [] if field == "paths" else {}
                        errors = _feature_expected_inputs(changed, run)[1]
                        self.assertTrue(any("differs from run_inputs.json: " + field in error for error in errors), errors)

    def test_grouped_asset_inventory_cannot_omit_a_registered_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sources = [root / "a.txt", root / "b.txt"]
            for source in sources:
                source.write_text(source.name)
            supplied = self.input_file(root / "inputs.json", "; ".join(map(str, sources)))
            raw = json.loads(supplied.read_text())
            raw["inputs"][0]["Asset source"] = True
            supplied.write_text(json.dumps(raw))
            run = root / "run"
            run.mkdir()
            manifest, _ = prepare_run._prepare_run_inputs(run, "ITEM-1", "feature_delivery", root, supplied, False)
            row = manifest["inputs"][0]
            inventory = {"schema_version": 1, "status": "passed", "work_item": "ITEM-1", "sources": [{
                "source_id": "SRC-1", "input_id": "IN-001", "kind": "other", "locator": row["Source or path"],
                "requiredness": "supporting", "discovery_status": "complete", "discovery_method": "Review selected files",
                "limitation": "None.", "asset_ids": ["A-1", "A-2"], "evidence_refs": ["E-1"]}],
                "assets": [{"asset_id": "A-" + str(index), "source_id": "SRC-1", "name": Path(path).name,
                    "kind": "document", "locator": path, "availability": "available", "requiredness": "supporting",
                    "review_method": "text_read", "review_status": "reviewed_not_relevant", "relevance": "non_material",
                    "observation": "No scope impact", "used_by": [], "evidence_refs": ["E-1"], "disposition": "No scope impact"}
                    for index, path in enumerate(row["paths"], 1)],
                "gate": {"inventory_complete": True, "all_assets_accounted_for": True, "all_available_assets_reviewed": True,
                         "all_material_assets_linked": True, "reviewed_before_plan": True,
                         "unresolved_asset_ids": [], "blocking_source_ids": []}}
            def errors(value):
                return validate_asset_manifest(value, work_item="ITEM-1", expected_inputs={"IN-001": row},
                    expected_input_ids=["IN-001"], expected_evidence_ids=["E-1"], require_passed=True)
            self.assertEqual(errors(inventory), [])
            omitted = copy.deepcopy(inventory)
            omitted["assets"].pop()
            omitted["sources"][0]["asset_ids"].pop()
            self.assertTrue(any("omitted" in error for error in errors(omitted)), errors(omitted))
            wrong = copy.deepcopy(inventory)
            wrong["assets"][1]["locator"] = str(root / "unregistered.txt")
            self.assertTrue(any("outside" in error for error in errors(wrong)), errors(wrong))

    def test_grouped_directory_inventory_handles_contents_and_limits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "folder"
            folder.mkdir()
            hidden = folder / ".hidden"
            hidden.write_text("selected")
            standalone = root / "file.txt"
            standalone.write_text("selected")
            source = {"source_id": "SRC-1", "kind": "other", "locator": "Selected group",
                      "discovery_status": "complete", "asset_ids": ["A-1", "A-2"]}
            assets = {"A-1": {"locator": str(hidden)}, "A-2": {"locator": str(standalone)}}
            self.assertEqual(_check_source_files(source, assets, [folder, standalone]), [])
            with patch("scripts.asset_manifest._directory_entries", return_value=(set(), ["permission denied"])):
                self.assertTrue(any("incomplete" in error for error in _check_source_files(source, assets, [folder, standalone])))
            hidden.unlink()
            standalone.unlink()
            source["asset_ids"] = []
            source["discovery_status"] = "empty"
            empty = root / "empty"
            empty.mkdir()
            self.assertEqual(_check_source_files(source, {}, [folder, empty]), [])
            self.assertTrue(any("unavailable" in error for error in _check_source_files(source, {}, [folder, standalone])))
            source["discovery_status"] = "partial"
            self.assertEqual(_check_source_files(source, {}, [folder, standalone]), [])

    def test_valid_trace_does_not_certify_replaced_evidence(self):
        case = v8.V8SentryHandoff()
        case.setUp()
        try:
            statement = "The incident is fixed and production deployment succeeded."
            case.evidence.write_text(case.evidence.read_text().replace("HTTP rejection observed; cause unknown.", statement))
            report = failure_handoff(case.packet_path, "Later stage failed")
            self.assertIn("Provisional artifact statement (not verified worker output): " + statement, report)
            self.assertNotIn("Verified Evidence Topology findings", report)
            self.assertIn("Dispatched workers without an accepted result: provider handle /root/worker", report)
            self.assertIn("Unaccepted worker artifact retained for audit only: " + str(case.evidence), report)
        finally:
            case.doCleanups()

    def test_optional_closing_delimiter_preserves_escaped_final_pipe(self):
        self.assertEqual(table_cells(r"| A | B\|"), ["A", "B|"])
        self.assertEqual(table_cells(r"| A | B\| |"), ["A", "B|"])
        rows, errors = _rows("## Rows\n| A | B |\n| --- | --- |\n" + r"| first | preserve A\|" + "\n",
                             "## Rows", ("A", "B"))
        self.assertEqual(rows, [["first", "preserve A|"]])
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
