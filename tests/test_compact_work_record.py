"""Compact records keep engineering context and require intact operational receipts."""

import copy
import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import finalize_work_record as finalizer


class CompactWorkRecord(unittest.TestCase):
    def packet(self, root, playbook="sentry_issue_remediation"):
        def populate(value):
            if isinstance(value, dict):
                return {key: populate(item) for key, item in value.items()}
            if isinstance(value, list):
                return [populate(item) for item in value]
            return value or "Fixture value"

        packet = populate(json.loads(finalizer.PACKET_TEMPLATE.read_text()))
        packet.update(populate(json.loads(finalizer.CLOSURE_TEMPLATE.read_text())))
        packet["identity"].update({"Playbook / version": f"playbooks/{playbook}.md / 0.5.1",
                                   "State": "blocked", "Run ID": "fixture-run"})
        packet["finalization"]["Durable artifact root"] = str(root)
        packet["runtime_closure"][0].update({"Runtime status": "Released", "Remaining active handles": "None"})
        packet["runtime_receipt"] = "runtime_closure.json"
        packet["worker_results"][0]["Unique contribution"] = "Explained the supported failure path"
        packet["handoff"]["established"] = ["Engineering context survives compaction"]
        packet["handoff"]["artifacts"] = ["work_record.md"]
        (root / "runtime_closure.json").write_text(json.dumps({"runtime_closure": packet["runtime_closure"]}))
        return packet

    def publish_snapshot(self, root, packet):
        path = root / finalizer.snapshot_name(packet)
        path.write_bytes(finalizer.snapshot_bytes(packet))
        return path, finalizer.render_compact(packet)

    def test_all_playbook_projections_preserve_reasoning_and_legacy_validation_view(self):
        for playbook in ("feature_delivery", "sentry_issue_remediation", "techops_issue_remediation",
                         "vulnerability_investigation", "technical_spike"):
            with self.subTest(playbook=playbook), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                packet = self.packet(root, playbook)
                _, text = self.publish_snapshot(root, packet)
                self.assertIn("Engineering context survives compaction", text)
                self.assertIn("Explained the supported failure path", text)
                self.assertIn("# Evidence\n", text)
                self.assertIn("# Decision Log\n", text)
                self.assertNotIn("# Worker Execution Ledger\n", text)
                self.assertNotIn("# Worker Runtime Closure\n", text)
                self.assertNotIn("# Worker Synchronization\n", text)
                self.assertNotIn("Provider/runtime configuration", text)
                self.assertEqual(finalizer.expand_work_record(text, root), finalizer.render(packet))
                self.assertLess(len(text), len(finalizer.render(packet)))

    def test_missing_changed_or_conflicting_receipts_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packet = self.packet(root)
            path, text = self.publish_snapshot(root, packet)
            content = path.read_bytes()
            path.unlink()
            with self.assertRaises(OSError):
                finalizer.expand_work_record(text, root)
            path.write_bytes(content + b" ")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                finalizer.expand_work_record(text, root)
            path.write_bytes(content)
            closure = copy.deepcopy(packet["runtime_closure"])
            closure[0]["Runtime status"] = "Blocked"
            (root / "runtime_closure.json").write_text(json.dumps({"runtime_closure": closure}))
            with self.assertRaisesRegex(ValueError, "conflicts with its runtime"):
                finalizer.expand_work_record(text, root)
            (root / "runtime_closure.json").unlink()
            with self.assertRaises(OSError):
                finalizer.expand_work_record(text, root)

    def test_modified_markdown_or_removed_snapshot_reference_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, text = self.publish_snapshot(root, self.packet(root))
            changed = text.replace("| State | blocked |", "| State | completed |")
            with self.assertRaisesRegex(ValueError, "does not match"):
                finalizer.expand_work_record(changed, root)
            changed = re.sub(r"<!-- workflow-state: .* -->", "", text)
            with self.assertRaisesRegex(ValueError, "requires a valid"):
                finalizer.expand_work_record(changed, root)

    def test_legacy_record_does_not_require_snapshot(self):
        text = "# Engineering Work Record\n\n# Run and Evaluation Identity\n\nLegacy content\n"
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(finalizer.expand_work_record(text, Path(directory)), text)

    def test_initialization_template_does_not_require_terminal_snapshot(self):
        text = (ROOT / "templates" / "work_record.md").read_text()
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(finalizer.expand_work_record(text, Path(directory)), text)

    def test_archived_record_reads_its_own_runtime_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "current"
            root.mkdir()
            packet = self.packet(root)
            _, text = self.publish_snapshot(root, packet)
            archive = Path(directory) / "archive"
            shutil.copytree(root, archive)
            (root / "runtime_closure.json").unlink()
            self.assertEqual(finalizer.expand_work_record(text, archive), finalizer.render(packet))

    def test_failed_candidate_snapshot_cannot_change_previous_record(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            accepted = self.packet(root)
            accepted_path, text = self.publish_snapshot(root, accepted)
            record = root / "work_record.md"
            record.write_text(text)
            candidate = copy.deepcopy(accepted)
            candidate["evidence"] = []
            source = root / "finalization_packet.json"
            source.write_text(json.dumps(candidate))
            with self.assertRaises(ValueError):
                finalizer.finalize(source, root / "runtime_closure.json", record)
            self.assertEqual(record.read_text(), text)
            self.assertEqual(list(root.glob("finalization_snapshot.*.json")), [accepted_path])
            self.assertEqual(finalizer.expand_work_record(text, root), finalizer.render(accepted))


if __name__ == "__main__":
    unittest.main()
