"""Candidate recovery verifies exact native edits before reuse."""

import importlib
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.recovery_candidate import snapshot_candidate, verify_candidate, verify_edit_authorization
from scripts import prepare_run as prepare
from scripts.prepare_run import _verify_rejected_delivery_candidate
from scripts.runtime_checks import activation_message


class CandidateRecoveryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.repo = self.root / "repo"
        self.repo.mkdir()
        for command in (("init", "-q"), ("config", "user.name", "Fixture"),
                        ("config", "user.email", "fixture@example.invalid")):
            self.git(*command)
        (self.repo / "tracked.txt").write_text("one\ntwo\n")
        self.git("add", "tracked.txt")
        self.git("commit", "-qm", "baseline")
        self.revision = self.git("rev-parse", "HEAD").decode().strip()
        (self.repo / "tracked.txt").write_text("one\nthree\n")
        (self.repo / "new.txt").write_text("new\n")
        self.session = self.root / "session.jsonl"
        self.rows = [
            {"type": "session_meta", "payload": {"id": "worker"}},
            {"type": "event_msg", "payload": {"type": "item_completed", "item": {
                "type": "FileChange", "changes": {
                    str(self.repo / "tracked.txt"): {"type": "update", "unified_diff":
                        "@@ -1,2 +1,2 @@\n one\n-two\n+three\n"},
                    str(self.repo / "new.txt"): {"type": "add", "content": "new\n"},
                }}}},
        ]
        self.write_session()

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True, capture_output=True).stdout

    def write_session(self):
        self.session.write_text("".join(json.dumps(row) + "\n" for row in self.rows))

    def verify(self, thread="worker", paths=None):
        return verify_candidate(self.repo, self.revision, self.session, thread,
                                paths if paths is not None else ["tracked.txt", "new.txt"])

    def test_replays_recorded_updates_and_additions(self):
        self.assertEqual(set(self.verify()), {"tracked.txt", "new.txt"})

    def test_snapshot_is_exact_and_atomic_when_candidate_changes(self):
        hashes = self.verify()
        destination = self.root / "snapshot"
        (self.repo / "new.txt").write_text("changed\n")
        with self.assertRaisesRegex(ValueError, "candidate_content_changed"):
            snapshot_candidate(self.repo, destination, hashes)
        self.assertFalse(destination.exists())
        (self.repo / "new.txt").write_text("new\n")
        snapshot_candidate(self.repo, destination, hashes)
        self.assertEqual((destination / "tracked.txt").read_bytes(), (self.repo / "tracked.txt").read_bytes())
        self.assertEqual((destination / "new.txt").read_bytes(), (self.repo / "new.txt").read_bytes())
        with self.assertRaisesRegex(ValueError, "candidate_snapshot_destination_invalid"):
            snapshot_candidate(self.repo, destination, hashes)

    def test_activation_requires_assigned_unchanged_snapshot(self):
        worktree = self.root / "worktree"
        self.git("worktree", "add", "--detach", str(worktree), self.revision)
        candidate = self.root / "candidate.txt"
        candidate.write_text("verified")
        digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
        packet = {"finalization_packet": str(self.root / "packet.json"), "required_prefix": "Ready",
                  "run_id": "new-run", "agent": "implementer", "coordinator_execution": {"source_checkout": str(worktree)},
                  "worker_contract": {"recovered_candidate": {"status": "unaccepted",
                                                               "baseline_revision": self.revision,
                                                               "snapshot_files": {str(candidate): digest}}}}
        with self.assertRaisesRegex(ValueError, "recovered_candidate_assignment_required"):
            activation_message(packet, {"objective": "implement"})
        assignment = {"objective": "implement", "input_paths": [str(candidate)]}
        self.assertIn(str(candidate), activation_message(packet, assignment))
        (worktree / "unexpected.txt").write_text("dirty")
        with self.assertRaisesRegex(ValueError, "recovered_candidate_source_checkout_changed"):
            activation_message(packet, assignment)
        (worktree / "unexpected.txt").unlink()
        candidate.write_text("tampered")
        with self.assertRaisesRegex(ValueError, "recovered_candidate_snapshot_changed"):
            activation_message(packet, assignment)

    def test_preparation_supplies_unaccepted_snapshot_to_implementer(self):
        hashes = self.verify()
        initial = prepare.prepare_run(self.repo, "CASE-1", "techops_issue_remediation", None, False)
        root = Path(initial["artifact_root"])
        (root / "implementation_plan.md").write_text("approved plan\n")
        (root / "runtime_dispatches.json").write_text('{"rejected_results":{"worker":"preserve"}}\n')
        (root / "activation_receipts.json").write_text('{"old":"preserve"}\n')
        packet = json.loads(Path(initial["finalization_packet"]).read_text())
        packet["_recovered_candidate"] = {"prior_run_id": packet["identity"]["Run ID"],
                                          "status": "unaccepted", "files": hashes, "baseline_revision": self.revision}
        worktree = self.root / "worktree"
        self.git("worktree", "add", "--detach", str(worktree), self.revision)
        with patch.object(prepare, "_reentry_source", return_value=packet), \
             patch.object(prepare, "resolve_repository_paths", return_value=(self.repo, worktree)):
            recovered = prepare.prepare_run(self.repo, "CASE-1", "techops_issue_remediation", None, True,
                                            remediation_reentry=True, approval_reference="approved")
        contract = recovered["worker_contracts"]["implementer"]
        snapshot = contract["recovered_candidate"]
        self.assertEqual(snapshot["status"], "unaccepted")
        self.assertEqual(set(snapshot["snapshot_files"].values()), set(hashes.values()))
        bundle = json.loads(Path(recovered["activation_packet_bundle"]["path"]).read_text())
        launch = bundle["packets"]["implementer"]
        assignment = {"objective": "verify and implement", "input_paths": list(snapshot["snapshot_files"])}
        self.assertIn("unaccepted", activation_message(launch, assignment))
        self.assertEqual(json.loads(Path(recovered["finalization_packet"]).read_text())["worker_results"], [])
        for name in ("runtime_dispatches.json", "activation_receipts.json"):
            self.assertFalse((root / name).exists())
            archive = Path(recovered["archived_run"]) if "archived_run" in recovered else root / "runs" / packet["identity"]["Run ID"]
            manifest = json.loads((archive / "archive_manifest.json").read_text())
            entry = next(row for row in manifest["files"] if row["path"] == name)
            self.assertEqual(hashlib.sha256((archive / entry["snapshot"]).read_bytes()).hexdigest(), entry["sha256"])

    def test_source_revision_advance_is_explicit_and_requires_unchanged_candidate_baseline(self):
        (self.repo / "unrelated.txt").write_text("other\n")
        self.git("add", "unrelated.txt")
        self.git("commit", "-qm", "unrelated")
        with self.assertRaisesRegex(ValueError, "candidate_revision_changed"):
            self.verify()
        paths = ["tracked.txt", "new.txt"]
        self.assertEqual(set(verify_candidate(self.repo, self.revision, self.session, "worker", paths,
                                              allow_source_revision_advance=True)), set(paths))
        self.git("add", "tracked.txt")
        self.git("commit", "-qm", "changed candidate baseline")
        with self.assertRaisesRegex(ValueError, "candidate_baseline_files_changed"):
            verify_candidate(self.repo, self.revision, self.session, "worker", paths,
                             allow_source_revision_advance=True)

    def test_rejects_tampering_extra_files_and_wrong_session(self):
        (self.repo / "tracked.txt").write_text("one\nother\n")
        with self.assertRaisesRegex(ValueError, "candidate_content_changed"):
            self.verify()
        (self.repo / "tracked.txt").write_text("one\nthree\n")
        (self.repo / "extra.txt").write_text("unexpected")
        with self.assertRaisesRegex(ValueError, "candidate_changed_paths_mismatch"):
            self.verify()
        (self.repo / "extra.txt").unlink()
        with self.assertRaisesRegex(ValueError, "candidate_worker_session_mismatch"):
            self.verify(thread="other")
        with self.assertRaisesRegex(ValueError, "candidate_path_invalid"):
            self.verify(paths=["../outside"])

    def test_rejects_missing_records_and_staged_changes(self):
        self.rows.pop()
        self.write_session()
        with self.assertRaisesRegex(ValueError, "candidate_edit_records_missing"):
            self.verify()
        self.git("add", "tracked.txt")
        with self.assertRaisesRegex(ValueError, "candidate_staged_changes"):
            self.verify()

    def test_rejects_patch_headers_and_symlink_paths(self):
        change = self.rows[1]["payload"]["item"]["changes"][str(self.repo / "tracked.txt")]
        change["unified_diff"] += "--- /tmp/other\n+++ /tmp/other\n"
        self.write_session()
        with self.assertRaisesRegex(ValueError, "candidate_patch_invalid"):
            self.verify()
        (self.repo / "new.txt").unlink()
        (self.repo / "new.txt").symlink_to(self.root / "outside")
        with self.assertRaisesRegex(ValueError, "candidate_path_invalid"):
            self.verify()

    def test_source_guard_must_precede_edits_and_remain_allowed(self):
        guard, packet = self.root / "guard.py", self.root / "packet.json"
        parent = self.root / "parent.jsonl"
        self.rows[1]["timestamp"] = "2026-01-01T00:00:02Z"
        self.write_session()
        action = {"type": "event_msg", "timestamp": "2026-01-01T00:00:01Z", "payload": {
            "type": "item_completed", "item": {"type": "CommandExecution",
                "command": ["bash", "-lc", f"python3 {guard} --before-source-change {packet} "
                            "--implementer-handle /root/worker --provider-status running"],
                "status": "completed", "exit_code": 0, "aggregated_output": '{"status":"allowed"}'}}}
        def write_parent(*events):
            parent.write_text("".join(json.dumps(row) + "\n" for row in [
                {"type": "session_meta", "payload": {"id": "parent"}}, *events]))
        def check():
            return verify_edit_authorization(parent, "parent", self.session, "worker", "2026-01-01T00:00:00Z",
                                             guard, packet, "/root/worker", self.repo, ["tracked.txt", "new.txt"])
        write_parent(action)
        self.assertIsNone(check())
        action["timestamp"] = "2026-01-01T00:00:03Z"
        write_parent(action)
        with self.assertRaisesRegex(ValueError, "candidate_source_guard_missing"):
            check()
        action["timestamp"] = "2026-01-01T00:00:01Z"
        action["payload"]["item"]["exit_code"] = 2
        write_parent(action)
        with self.assertRaisesRegex(ValueError, "candidate_source_guard_missing"):
            check()

    def test_recovery_requires_format_only_rejection_and_native_mapping(self):
        root = self.root / "artifacts"
        root.mkdir()
        error = "worker_result_contract_invalid:implementer:bad format"
        trace = {"run_id": "run", "worker": "implementer", "thread_id": "child",
                 "spawn": {"provider_handle": "/root/worker"}, "trace_retrieval": str(self.session),
                 "audit": {"status": "rejected", "errors": [error, "worker_fan_in_rejected"]}}
        (root / "trace_worker.json").write_text(json.dumps(trace))
        (root / "implementation_conformance.json").write_text(json.dumps({"files": [{"path": "tracked.txt"}]}))
        (root / "role_bindings.json").write_text(json.dumps({"execution_repository": str(self.repo),
            "parent_context": {"provider_session": str(self.session), "parent_thread_id": "parent"},
            "runtime_evidence": {"run_started_at": "2026-01-01T00:00:00Z"},
            "worker_runtime_guard": str(self.root / "guard.py")}))
        prior = {"identity": {"Run ID": "run"}, "reentry": {"Approved plan SHA256": "plan"},
                 "repositories": [{"Repository role": "Execution repository", "Full revision": self.revision}]}
        failure = {"historical_errors": [error]}
        ledger = {"thread_mappings": {"/root/worker": "child"}}
        try:
            checks = importlib.import_module("runtime_checks")
            recovery = importlib.import_module("recovery_candidate")
        except ModuleNotFoundError:
            checks = importlib.import_module("scripts.runtime_checks")
            recovery = importlib.import_module("scripts.recovery_candidate")
        with patch.object(checks, "trace_identity_errors", return_value=[error]), \
             patch.object(checks, "trace_errors", return_value=[error, "worker_fan_in_rejected"]), \
             patch.object(checks, "techops_conformance_errors", return_value=[]), \
             patch.object(recovery, "verify_edit_authorization"), \
             patch.object(recovery, "verify_candidate", return_value={"tracked.txt": "digest"}):
            result = _verify_rejected_delivery_candidate(root, prior, failure, ledger)
            self.assertEqual(result["status"], "unaccepted")
            with self.assertRaisesRegex(ValueError, "candidate_worker_mapping_mismatch"):
                _verify_rejected_delivery_candidate(root, prior, failure, {"thread_mappings": {}})
            with self.assertRaisesRegex(ValueError, "candidate_worker_trace_not_format_only"):
                _verify_rejected_delivery_candidate(root, prior, {"historical_errors": []}, ledger)
            worktree = self.root / "worktree"
            self.git("worktree", "add", "--detach", str(worktree), self.revision)
            result = _verify_rejected_delivery_candidate(root, prior, failure, ledger, source_checkout=worktree)
            self.assertEqual(result["baseline_revision"], self.revision)
            (worktree / "unrelated.txt").write_text("dirty")
            with self.assertRaisesRegex(ValueError, "candidate_recovery_source_checkout_invalid"):
                _verify_rejected_delivery_candidate(root, prior, failure, ledger, source_checkout=worktree)


if __name__ == "__main__":
    unittest.main()
