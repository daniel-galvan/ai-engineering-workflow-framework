"""Generated exercise metadata must stay current without replacing authored guidance."""

import tempfile
import unittest
from pathlib import Path

from scripts.playbook_catalog import BEGIN, END, ROOT, catalog_errors, render_status, updated_catalog


class PlaybookCatalog(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / "playbooks").mkdir()
        self.source = self.root / "playbooks/spike.md"
        self.source.write_text(
            "---\ntitle: Technical Spike Playbook\nversion: 0.5.15\nlast_updated: 2026-10-06\n"
            "status: Pilot\nmaturity: exercising\nexercise_scope: standard + planning\n"
            "validation_summary: checks passed | live rerun pending\n---\n"
        )
        self.catalog = self.root / "PLAYBOOK_CATALOG.md"
        self.catalog.write_text(f"Authored introduction\n{BEGIN}\n{END}\nAuthored architecture\n")
        self.refresh()

    def refresh(self):
        self.catalog.write_text(updated_catalog(self.root))

    def test_checked_in_catalog_is_current(self):
        self.assertEqual(catalog_errors(ROOT), [])

    def test_refresh_preserves_authored_content_and_pending_status(self):
        self.assertEqual(catalog_errors(self.root), [])
        text = self.catalog.read_text()
        self.assertTrue(text.startswith("Authored introduction\n"))
        self.assertTrue(text.endswith("\nAuthored architecture\n"))
        self.assertIn("checks passed &#124; live rerun pending", text)
        self.assertEqual(updated_catalog(self.root), text)

    def test_each_metadata_change_requires_refresh(self):
        original = self.source.read_text()
        for old, new in (("0.5.15", "0.5.16"), ("2026-10-06", "2026-10-08"),
                         ("Pilot", "Draft"), ("exercising", "draft"),
                         ("standard + planning", "deep + planning"), ("live rerun pending", "new run pending")):
            with self.subTest(field=old):
                self.source.write_text(original.replace(old, new))
                self.assertTrue(catalog_errors(self.root))
                self.refresh()
                self.assertEqual(catalog_errors(self.root), [])
                self.source.write_text(original)
                self.refresh()

    def test_added_and_removed_playbooks_require_refresh(self):
        added = self.source.with_name("new.md")
        added.write_text(self.source.read_text().replace("Technical Spike", "New"))
        self.assertTrue(catalog_errors(self.root))
        self.refresh()
        self.assertIn("playbooks/new.md", self.catalog.read_text())
        added.unlink()
        self.assertTrue(catalog_errors(self.root))

    def test_missing_metadata_and_invalid_markers_fail_without_rewriting(self):
        original = self.catalog.read_text()
        self.source.write_text(self.source.read_text().replace("maturity: exercising\n", ""))
        self.assertTrue(catalog_errors(self.root))
        self.assertEqual(self.catalog.read_text(), original)
        with self.assertRaises(ValueError):
            render_status(self.root)
        for text in ("No markers", f"{BEGIN}\n{BEGIN}\n{END}", f"{END}\n{BEGIN}"):
            self.catalog.write_text(text)
            self.assertTrue(catalog_errors(self.root))
            self.assertEqual(self.catalog.read_text(), text)


if __name__ == "__main__":
    unittest.main()
