"""Publication recovery preserves finalized evidence and its original package identity."""

import hashlib
import io
import json
import shutil
import subprocess
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts import finalize_work_record as finalizer
from scripts.runtime_checks import prepared_package_errors


class PublicationRecovery(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.origin = self.root / "prepared-package"
        (self.origin / ".codex-plugin").mkdir(parents=True)
        plugin = self.origin / ".codex-plugin/plugin.json"
        self.plugin = json.loads((finalizer.ROOT / ".codex-plugin/plugin.json").read_text())
        self.plugin["version"] = self.plugin["version"].split("+", 1)[0] + "+fixture"
        plugin.write_text(json.dumps(self.plugin))
        (self.origin / "scripts").mkdir()
        (self.origin / "scripts/validate_library.py").write_text(
            "import sys\nassert '--emit-handoff' in sys.argv\n"
            "print('Workflow-framework validation: passed\\nCanonical report')\n")
        self.packet = self.root / "finalization_packet.json"
        self.packet.write_text(json.dumps({"identity": {"Run ID": "run", "Lifecycle": "remediation",
            "Requested profile": "standard", "Playbook / version": "techops_issue_remediation / 0.5.33",
            "Framework commit / status": "a" * 40 + " / Clean"}}))
        self.bindings = {"run_id": "run", "lifecycle": "remediation", "execution_profile": "standard",
            "framework_package": {"root": str(self.origin), "plugin_sha256": hashlib.sha256(plugin.read_bytes()).hexdigest()},
            "parent_context": {"run_id": "run", "provider_session": "native.jsonl", "parent_thread_id": "parent",
                               "turn_id": "original-turn", "input_paths": []}, "runtime_evidence": {}}
        codex = self.root / "codex"
        source = codex / "sessions" / "native.jsonl"
        source.parent.mkdir(parents=True)
        source.write_text('{}\n')
        self.bindings["parent_context"]["provider_session"] = str(source)
        (self.root / "role_bindings.json").write_text(json.dumps(self.bindings))
        (self.root / "pre_release_check.json").write_text(json.dumps({"status": "passed",
            "packet_sha256": hashlib.sha256(self.packet.read_bytes()).hexdigest()}))
        (self.root / "runtime_closure.json").write_text(json.dumps({"terminal_observations": [],
            "runtime_closure": [{"Runtime status": "Terminal", "Remaining active handles": "0"}]}))
        self.record = self.root / "work_record.md"
        self.record.write_text("| Run ID | run |\n")
        stack = self.enterContext(ExitStack())
        stack.enter_context(patch.dict("os.environ", {"CODEX_HOME": str(codex)}))
        try:
            import framework_manifest as manifests
            import run_preflight as preflights
            import provider_runtime as providers
            import planning_contracts as contracts
        except ModuleNotFoundError:
            from scripts import framework_manifest as manifests, run_preflight as preflights
            from scripts import provider_runtime as providers, planning_contracts as contracts
        stack.enter_context(patch.object(manifests, "manifest_errors", return_value=[]))
        self.preflight = stack.enter_context(patch.object(preflights, "preflight",
            return_value={"status": "passed", "framework_status": "clean"}))
        self.audit = stack.enter_context(patch.object(providers, "parent_context_audit",
            return_value={"status": "passed", "errors": []}))
        self.selection = stack.enter_context(patch.object(providers, "native_preflight_observed", return_value=True))
        self.finalization = stack.enter_context(patch.object(providers, "native_finalization_observed", return_value=True))
        stack.enter_context(patch.object(contracts, "terminal_closure_dispatch_errors", return_value=[]))
        stack.enter_context(patch.object(finalizer, "verify_recovery_record"))
        stack.enter_context(patch.object(finalizer, "recovery_canonical_report", return_value=b"Canonical report\n"))

    def test_recovery_retains_identity_and_compares_original_canonical_bytes(self):
        self.assertIn("prepared_framework_package_mismatch", prepared_package_errors(self.root)[0])
        self.assertIn("prepared_framework_package_mismatch", prepared_package_errors(self.root, check_parent_context=False)[0])
        self.assertIn("prepared_framework_package_mismatch", prepared_package_errors(
            self.root, check_parent_context=False, package_content_root=self.origin)[0])
        preserved = {p: p.read_bytes() for p in self.root.glob("*.json")}
        preserved[self.record] = self.record.read_bytes()
        suffix = self.root / "suffix.md"
        suffix.write_text("Required citation\n")
        proposed = self.root / "outgoing.md"
        proposed.write_text("Canonical report\nRequired citation\n")
        args = ["finalizer", "--packet", str(self.packet), "--publish-response", str(proposed),
                "--presentation-suffix", str(suffix), "--recover-presentation"]
        output = io.StringIO()
        with patch("sys.argv", args), patch.object(finalizer, "checked"), redirect_stdout(output):
            self.assertEqual(finalizer.main(), 0, output.getvalue())
        self.assertEqual(output.getvalue(), proposed.read_text())
        receipt = json.loads((self.root / "handoff_delivery.json").read_text())
        self.assertEqual(receipt["publication_recovery"]["prepared_package_root"], str(self.origin))
        self.assertEqual(receipt["publication_recovery"]["parent_turn_id"], "original-turn")
        self.assertEqual(self.audit.call_args.kwargs["expected_turn_id"], "original-turn")
        self.assertEqual(self.selection.call_args.args[1], "original-turn")
        self.assertTrue(all(p.read_bytes() == content for p, content in preserved.items()))
        proposed.write_text("Changed report\nRequired citation\n")
        with patch("sys.argv", args), patch.object(finalizer, "checked"), redirect_stdout(io.StringIO()):
            self.assertEqual(finalizer.main(), 2)
        self.assertFalse((self.root / "handoff_delivery.json").exists())
        (self.root / "runtime_closure.json").write_text('[]')
        with patch("sys.argv", args), patch.object(finalizer, "checked"), redirect_stdout(io.StringIO()):
            self.assertEqual(finalizer.main(), 2)

    def test_pruned_cache_restores_exact_commit_without_rebinding(self):
        source = self.root / "publisher-source"
        shutil.copytree(self.origin, source)
        for args in (["init", "-q"], ["add", "."], ["-c", "user.name=Fixture", "-c",
                     "user.email=fixture@example.invalid", "commit", "-qm", "Original package"]):
            subprocess.run(["git", "-C", str(source), *args], check=True, capture_output=True)
        revision = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
        packet = json.loads(self.packet.read_text())
        packet["identity"]["Framework commit / status"] = revision + " / Clean"
        self.packet.write_text(json.dumps(packet))
        (self.root / "pre_release_check.json").write_text(json.dumps({"status": "passed",
            "packet_sha256": hashlib.sha256(self.packet.read_bytes()).hexdigest()}))
        shutil.rmtree(self.origin)
        preserved = {p: p.read_bytes() for p in self.root.glob("*.json")}
        outgoing = self.root / "outgoing.md"
        outgoing.write_text("Canonical report\n")
        args = ["finalizer", "--packet", str(self.packet), "--publish-response", str(outgoing), "--recover-presentation"]
        for invalid in ("history", "plugin_hash"):
            if invalid == "history":
                changed = json.loads(self.packet.read_text())
                changed["identity"]["Framework commit / status"] = "f" * 40 + " / Clean"
                self.packet.write_text(json.dumps(changed))
                (self.root / "pre_release_check.json").write_text(json.dumps({"status": "passed",
                    "packet_sha256": hashlib.sha256(self.packet.read_bytes()).hexdigest()}))
            else:
                changed = json.loads((self.root / "role_bindings.json").read_text())
                changed["framework_package"]["plugin_sha256"] = "0" * 64
                (self.root / "role_bindings.json").write_text(json.dumps(changed))
            with patch.object(finalizer, "ROOT", source), patch("sys.argv", args), patch.object(finalizer, "checked"), \
                    patch.object(finalizer.subprocess, "run", wraps=subprocess.run) as commands, redirect_stdout(io.StringIO()):
                self.assertEqual(finalizer.main(), 2)
            self.assertFalse(any(call.args[0][:2] == ["git", "clone"] for call in commands.call_args_list))
            for p, contents in preserved.items(): p.write_bytes(contents)
        for selection in (False, True):
            self.selection.return_value = selection
            output = io.StringIO()
            with patch.object(finalizer, "ROOT", source), patch("sys.argv", args), patch.object(finalizer, "checked"), \
                    patch.object(finalizer.subprocess, "run", wraps=subprocess.run) as commands, redirect_stdout(output):
                self.assertEqual(finalizer.main(), 0 if selection else 2, output.getvalue())
            clones = [call for call in commands.call_args_list if call.args[0][:2] == ["git", "clone"]]
            self.assertEqual(len(clones), int(selection))
            self.assertFalse(self.origin.exists())
            if selection:
                receipt = json.loads((self.root / "handoff_delivery.json").read_text())["publication_recovery"]
                self.assertEqual(receipt["prepared_package_root"], str(self.origin))
                self.assertTrue(receipt["prepared_package_restored"])
                self.assertEqual(receipt["framework_revision"], revision)
                self.assertFalse(Path(receipt["canonical_package_root"]).exists())
                self.assertEqual(self.preflight.call_args.kwargs["declared_framework_revision"], revision)
                self.assertEqual(output.getvalue(), outgoing.read_text())
        self.assertTrue(all(p.read_bytes() == contents for p, contents in preserved.items()))

    def test_recovery_rejects_changed_packet_active_workers_and_failed_context(self):
        originals = {p: p.read_bytes() for p in self.root.glob("*.json")}
        for change in ("packet", "closure", "package", "failure", "parent_run", "context", "origin_preflight", "selection", "finalization", "fake_session"):
            with self.subTest(change=change):
                if change == "packet": self.packet.write_text(self.packet.read_text() + " ")
                elif change == "closure":
                    (self.root / "runtime_closure.json").write_text('{"runtime_closure": []}')
                elif change == "package":
                    (self.origin / ".codex-plugin/plugin.json").write_text('{}')
                elif change == "failure":
                    (self.root / "finalization_failure.json").write_text('{"status":"failed"}')
                elif change == "parent_run":
                    altered = json.loads(json.dumps(self.bindings))
                    altered["parent_context"]["run_id"] = "other"
                    (self.root / "role_bindings.json").write_text(json.dumps(altered))
                elif change == "context": self.audit.return_value = {"status": "rejected", "errors": ["unassigned_read"]}
                elif change == "origin_preflight": self.preflight.return_value = {"status": "blocked"}
                elif change == "selection": self.selection.return_value = False
                elif change == "finalization": self.finalization.return_value = False
                else:
                    altered = json.loads(json.dumps(self.bindings))
                    altered["parent_context"]["provider_session"] = str(self.record)
                    (self.root / "role_bindings.json").write_text(json.dumps(altered))
                with self.assertRaises((ValueError, KeyError)):
                    finalizer.publication_recovery_context(self.packet, self.record)
                if change == "selection":
                    self.assertFalse(self.preflight.call_count)
                for p, content in originals.items(): p.write_bytes(content)
                (self.root / "finalization_failure.json").unlink(missing_ok=True)
                (self.origin / ".codex-plugin/plugin.json").write_text(
                    json.dumps(self.plugin))
                self.audit.return_value = {"status": "passed", "errors": []}
                self.preflight.return_value = {"status": "passed", "framework_status": "clean"}
                self.preflight.reset_mock()
                self.selection.return_value = True
                self.finalization.return_value = True


class PublicationRecordProjection(unittest.TestCase):
    def test_valid_projection_of_changed_engineering_data_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            packet = json.loads(finalizer.PACKET_TEMPLATE.read_text())
            packet["identity"].update({"State": "blocked", "Engineering state": "unknown"})
            packet_path = root / "finalization_packet.json"
            packet_path.write_text(json.dumps(packet))
            closure = {"terminal_observations": [], "runtime_closure": [{
                "Run or stage": "Current run", "Receipt owner": "Coordinator", "Completed worker handles": "None dispatched",
                "Runtime status": "Terminal", "Remaining active handles": "0", "Closure evidence or blocker": "No workers"}]}
            (root / "runtime_closure.json").write_text(json.dumps(closure))
            normalized = json.loads(json.dumps(packet))
            finalizer._normalize_packet(normalized, closure, packet_path)
            finalizer._reconcile_runtime_state(normalized, closure["runtime_closure"])
            normalized["runtime_receipt"] = "runtime_closure.json"
            normalized["work_item"]["Last Updated"] = "2026-10-31T00:00:00Z"
            record = root / "work_record.md"
            def write_projection():
                (root / finalizer.snapshot_name(normalized)).write_bytes(finalizer.snapshot_bytes(normalized))
                record.write_text(finalizer.render_compact(normalized))
            write_projection()
            finalizer.verify_recovery_record(packet_path, record, packet, closure, finalizer.ROOT)
            normalized["handoff"]["workflow_result"] = "Changed engineering conclusion"
            write_projection()
            # The record is internally valid, but no longer derives from the unchanged passed packet.
            finalizer.expand_work_record(record.read_text(), root)
            with self.assertRaisesRegex(ValueError, "not_derived_from_passed_packet"):
                finalizer.verify_recovery_record(packet_path, record, packet, closure, finalizer.ROOT)
