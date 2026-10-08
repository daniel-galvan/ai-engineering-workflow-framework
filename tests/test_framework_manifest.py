"""The generated inventory must detect source changes without inventing releases."""

import json
import tempfile
import unittest
from pathlib import Path

from scripts.framework_manifest import FILENAME, ROOT, build_manifest, manifest_errors


class FrameworkManifest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        for name in ("frameworks/investigation.md", "contracts/workflow_execution.md", "playbooks/technical_spike.md"):
            self.write(name, "---\nversion: 0.5.1\n---\n")
        self.write("providers/codex/model_effort_policy.md", "---\nversion: 0.5.2\nbaseline_id: policy-one\n---\n")
        self.write(".codex-plugin/plugin.json", '{"name": "workflows", "version": "0.1.9+codex.1"}')
        self.refresh()

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def refresh(self):
        self.write(FILENAME, json.dumps(build_manifest(self.root)))

    def test_checked_in_inventory_is_current(self):
        self.assertEqual(manifest_errors(ROOT), [])

    def test_inventory_reports_independent_versions_and_baseline(self):
        manifest = build_manifest(self.root)
        self.assertIsNone(manifest["library_release"])
        self.assertEqual(manifest["execution_contract"]["version"], "0.5.1")
        self.assertEqual(manifest["provider_policies"]["providers/codex/model_effort_policy.md"]["baseline_id"],
                         "policy-one")
        self.assertEqual(manifest["compatibility"]["cross_revision_compatibility"], "not_declared")

    def test_changed_metadata_is_rejected_until_regenerated(self):
        for name, text in (
            ("contracts/workflow_execution.md", "---\nversion: 0.5.17\n---\n"),
            ("providers/codex/model_effort_policy.md", "---\nversion: 0.5.2\nbaseline_id: policy-two\n---\n"),
            (".codex-plugin/plugin.json", '{"name": "workflows", "version": "0.1.9+codex.2"}'),
        ):
            with self.subTest(source=name):
                self.write(name, text)
                self.assertTrue(manifest_errors(self.root))
                self.refresh()
                self.assertEqual(manifest_errors(self.root), [])

    def test_added_and_removed_documents_are_detected_and_local_records_are_excluded(self):
        self.write("playbooks/new.md", "---\nversion: 0.1.0\n---\n")
        self.assertTrue(manifest_errors(self.root))
        self.refresh()
        self.assertIn("new", build_manifest(self.root)["playbooks"])
        (self.root / "playbooks/new.md").unlink()
        self.assertTrue(manifest_errors(self.root))
        self.refresh()
        self.write(".thoughts/ITEM/work_record.md", "---\nversion: 9.9.9\n---\n")
        self.write("tests/fixtures/report.md", "---\nversion: 9.9.9\n---\n")
        self.assertEqual(manifest_errors(self.root), [])

    def test_missing_or_malformed_inventory_fails(self):
        (self.root / FILENAME).unlink()
        self.assertTrue(manifest_errors(self.root))
        self.write(FILENAME, "{broken")
        self.assertTrue(manifest_errors(self.root))


if __name__ == "__main__":
    unittest.main()
