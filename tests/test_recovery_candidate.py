"""Candidate recovery verifies exact native edits before reuse."""

import importlib
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.recovery_candidate import (replay_candidate, replay_followup_candidate, snapshot_candidate, snapshot_replayed_candidate,
                                        verify_candidate, verify_edit_authorization)
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

    def test_followup_replays_only_authorized_snapshot_updates(self):
        initial = {"tracked.txt": b"one\nthree\n", "new.txt": b"new\n"}
        self.rows[1]["payload"]["item"]["changes"] = {
            str(self.repo / "tracked.txt"): {"type": "update", "unified_diff": "@@ -1,2 +1,2 @@\n one\n-three\n+four\n"}}
        self.write_session()
        result, touched = replay_followup_candidate(self.repo, self.session, "worker", initial)
        self.assertEqual(result, {"tracked.txt": b"one\nfour\n", "new.txt": b"new\n"})
        self.assertEqual(touched, ["tracked.txt"])
        self.assertEqual((self.repo / "tracked.txt").read_bytes(), initial["tracked.txt"])
        with self.assertRaisesRegex(ValueError, "candidate_worker_session_mismatch"):
            replay_followup_candidate(self.repo, self.session, "other", initial)
        self.rows[1]["payload"]["item"]["changes"][str(self.repo / "other.txt")] = {"type": "add", "content": "new"}
        self.write_session()
        with self.assertRaisesRegex(ValueError, "candidate_followup_edit_outside_snapshot"):
            replay_followup_candidate(self.repo, self.session, "worker", initial)

    def test_recovered_candidate_requires_bound_followup_and_exact_checkout(self):
        root = self.root / "run"
        root.mkdir()
        initial = {"tracked.txt": b"one\nthree\n", "new.txt": b"new\n"}
        self.rows[1]["payload"]["item"]["changes"] = {
            str(self.repo / "tracked.txt"): {"type": "update", "unified_diff": "@@ -1,2 +1,2 @@\n one\n-three\n+four\n"}}
        self.write_session()
        (self.repo / "tracked.txt").write_bytes(b"one\nfour\n")
        candidate = {"status": "unaccepted", "baseline_revision": self.revision}
        trace = {"run_id": "delivery", "worker": "implementer", "audit": {"status": "rejected"},
                 "thread_id": "worker", "trace_retrieval": str(self.session), "last_dispatch_at": "dispatch",
                 "spawn": {"provider_handle": "/root/worker"}}
        trace_path = root / "trace_followup.json"
        trace_path.write_text(json.dumps(trace))
        digest = hashlib.sha256(trace_path.read_bytes()).hexdigest()
        accepted_path = root / "accepted.json"
        accepted_path.write_text(json.dumps({"spawn": {"dispatch_file_sha256": "accepted-dispatch"}}))
        prior = {"identity": {"Run ID": "delivery"}, "runtime_audits": [{"Worker": "implement", "Trace path": str(accepted_path)}],
                 "activation_repairs": {"implementer": {"Attempt": 1, "Provider handle": "/root/worker",
                    "Last dispatch at": "dispatch", "Rejected trace SHA256": digest,
                    "Corrected dispatch SHA256": "accepted-dispatch"}}}
        bindings = {"parent_context": {"provider_session": str(self.session), "parent_thread_id": "parent"},
                    "runtime_evidence": {"run_started_at": "start"}}
        (root / "role_bindings.json").write_text(json.dumps(bindings))
        dispatch = {"worker_contract": {"recovered_candidate": candidate, "before_source_change_guard": "/guard"},
                    "coordinator_execution": {"source_checkout": str(self.repo)}}
        content = "Coordinator initialization: complete\n" + json.dumps(dispatch) + "\nTyped assignment:\n{}"
        with patch.object(prepare, "_accepted_implementer_candidate", return_value=candidate), \
             patch.object(prepare, "_recover_preserved_candidate", return_value={"_contents": initial}), \
             patch(("runtime_checks" if importlib.util.find_spec("runtime_checks") else "scripts.runtime_checks") + "._verified_dispatch_content", return_value=content), \
             patch(("recovery_candidate" if importlib.util.find_spec("recovery_candidate") else "scripts.recovery_candidate") + ".verify_edit_authorization"):
            result = prepare._recover_accepted_candidate(root, prior, self.repo)
            self.assertEqual(result["_contents"], {"tracked.txt": b"one\nfour\n", "new.txt": b"new\n"})
            self.assertEqual(result["status"], "unaccepted")
            (self.repo / "tracked.txt").write_text("tampered\n")
            with self.assertRaisesRegex(ValueError, "candidate_content_changed"):
                prepare._recover_accepted_candidate(root, prior, self.repo)
            (self.repo / "tracked.txt").write_bytes(b"one\nfour\n")
            trace_path.write_text(json.dumps({**trace, "run_id": "other"}))
            with self.assertRaisesRegex(ValueError, "candidate_followup_trace_unverified"):
                prepare._recover_accepted_candidate(root, prior, self.repo)

    def test_accepted_followup_is_replayed_and_must_match_checkout(self):
        root = self.root / "run"
        root.mkdir()
        initial = {"tracked.txt": b"one\nthree\n", "new.txt": b"new\n"}
        self.rows[1]["payload"]["item"]["changes"] = {
            str(self.repo / "tracked.txt"): {"type": "update", "unified_diff": "@@ -1,2 +1,2 @@\n one\n-three\n+four\n"}}
        self.write_session()
        (self.repo / "tracked.txt").write_bytes(b"one\nfour\n")
        candidate = {"status": "unaccepted", "baseline_revision": self.revision}
        trace = {"audit": {"status": "passed"}, "thread_id": "worker", "trace_retrieval": str(self.session),
                 "spawn": {"provider_handle": "/root/worker"}}
        trace_path = root / "implementer_trace.json"
        trace_path.write_text(json.dumps(trace))
        prior = {"identity": {"Run ID": "delivery"}, "runtime_audits": [{"Worker": "implement", "Trace path": str(trace_path)}]}
        (root / "role_bindings.json").write_text(json.dumps({"parent_context": {"provider_session": str(self.session),
            "parent_thread_id": "parent"}, "runtime_evidence": {"run_started_at": "start"}}))
        dispatch = {"worker_contract": {"before_source_change_guard": "/guard"}}
        content = "Coordinator initialization: complete\n" + json.dumps(dispatch) + "\nTyped assignment:\n{}"
        with patch.object(prepare, "_accepted_implementer_candidate", return_value=candidate), \
             patch.object(prepare, "_recover_preserved_candidate", return_value={"_contents": initial}), \
             patch(("runtime_checks" if importlib.util.find_spec("runtime_checks") else "scripts.runtime_checks") + "._verified_dispatch_content", return_value=content), \
             patch(("recovery_candidate" if importlib.util.find_spec("recovery_candidate") else "scripts.recovery_candidate") + ".verify_edit_authorization"):
            result = prepare._recover_current_accepted_candidate(root, prior, self.repo)
            self.assertEqual(result["_contents"], {"tracked.txt": b"one\nfour\n", "new.txt": b"new\n"})
            self.assertEqual(result["base_candidate"], candidate)
            (self.repo / "tracked.txt").write_text("tampered\n")
            with self.assertRaisesRegex(ValueError, "candidate_content_changed"):
                prepare._recover_current_accepted_candidate(root, prior, self.repo)

    def test_unmerged_worker_edit_requires_terminal_evidence_and_exact_checkout(self):
        root = self.root / "run"
        root.mkdir()
        initial = {"tracked.txt": b"one\nthree\n", "new.txt": b"new\n"}
        self.rows[1]["payload"]["item"]["changes"] = {
            str(self.repo / "tracked.txt"): {"type": "update", "unified_diff": "@@ -1,2 +1,2 @@\n one\n-three\n+four\n"}}
        self.write_session()
        (self.repo / "tracked.txt").write_bytes(b"one\nfour\n")
        prior = {"identity": {"Run ID": "delivery", "Lifecycle": "remediation"},
                 "workers": [], "worker_results": [], "runtime_audits": []}
        frozen = json.dumps(prior).encode()
        snapshot = root / "snapshot.json"
        snapshot.write_bytes(frozen)
        digest = hashlib.sha256(frozen).hexdigest()
        failure = {"status": "failed", "stage": "workflow", "reported_by": "Coordinator", "runtime_closure": "terminal",
                   "run_id": "delivery", "packet_snapshot": str(snapshot), "snapshot_sha256": digest, "packet_sha256": digest,
                   "errors": ["parent_context_nonconformant:example"]}
        (root / "finalization_failure.json").write_text(json.dumps(failure))
        ledger = {"thread_mappings": {"/root/worker": "worker"}, "timing": {"open_worker_intervals": 0}}
        (root / "runtime_dispatches.json").write_text(json.dumps(ledger))
        candidate = {"status": "unaccepted", "baseline_revision": self.revision}
        bindings = {"recovered_candidate": candidate, "parent_context": {"provider_session": str(self.session),
                    "parent_thread_id": "parent"}, "runtime_evidence": {"run_started_at": "start"}}
        (root / "role_bindings.json").write_text(json.dumps(bindings))
        trace = {"run_id": "delivery", "worker": "implementer", "audit": {"status": "passed"}, "thread_id": "worker",
                 "last_dispatch_at": "time",
                 "trace_retrieval": str(self.session), "spawn": {"provider_handle": "/root/worker"}}
        (root / "trace_implementer.json").write_text(json.dumps(trace))
        observations = [{"Provider handle": "/root/worker", "Provider status": "completed", "Thread ID": "worker",
                         "Last dispatch at": "time"}]
        dispatch = {"worker_contract": {"recovered_candidate": candidate, "before_source_change_guard": "/guard"},
                    "coordinator_execution": {"source_checkout": str(self.repo)}}
        content = "Coordinator initialization: complete\n" + json.dumps(dispatch) + "\nTyped assignment:\n{}"
        prefix = "" if importlib.util.find_spec("runtime_checks") else "scripts."
        with patch(prefix + "planning_contracts.terminal_closure_dispatch_errors", return_value=[]), \
             patch(prefix + "worker_runtime_evidence.dispatch_audit_errors", return_value=[]), \
             patch(prefix + "worker_runtime_evidence._native_terminal_observations", return_value=observations), \
             patch(prefix + "runtime_checks._verified_dispatch_content", return_value=content), \
             patch(prefix + "recovery_candidate.verify_edit_authorization"), \
             patch.object(prepare, "_verified_recovery_planning"), \
             patch.object(prepare, "_recover_preserved_candidate", return_value={"_contents": initial}):
            result = prepare._recover_unmerged_candidate(root, prior, {"terminal_observations": observations}, self.repo)
            self.assertEqual(result["_contents"], {"tracked.txt": b"one\nfour\n", "new.txt": b"new\n"})
            self.assertTrue(result["unmerged_parent_failure"])
            (self.repo / "tracked.txt").write_text("tampered\n")
            with self.assertRaisesRegex(ValueError, "candidate_content_changed"):
                prepare._recover_unmerged_candidate(root, prior, {"terminal_observations": observations}, self.repo)
            (self.repo / "tracked.txt").write_bytes(b"one\nfour\n")
            (root / "finalization_failure.json").write_text(json.dumps({**failure, "runtime_closure": "unverified"}))
            with self.assertRaisesRegex(ValueError, "remediation_recovery_evidence_unverified"):
                prepare._recover_unmerged_candidate(root, prior, {"terminal_observations": observations}, self.repo)

    def test_replay_from_clean_worktree_ignores_other_checkout_changes(self):
        worktree = self.root / "worktree"
        self.git("worktree", "add", "--detach", str(worktree), self.revision)
        (self.repo / "tracked.txt").write_text("unrelated current work")
        (self.repo / "new.txt").unlink()
        paths = ["tracked.txt", "new.txt"]
        contents = replay_candidate(worktree, self.revision, self.session, "worker", self.repo, paths)
        self.assertEqual(contents, {"tracked.txt": b"one\nthree\n", "new.txt": b"new\n"})
        hashes = {name: hashlib.sha256(data).hexdigest() for name, data in contents.items()}
        destination = self.root / "snapshot"
        bad = dict(contents, **{"new.txt": b"tampered"})
        with self.assertRaisesRegex(ValueError, "candidate_content_changed"):
            snapshot_replayed_candidate(destination, hashes, bad)
        self.assertFalse(destination.exists())
        snapshot_replayed_candidate(destination, hashes, contents)
        self.assertEqual((destination / "new.txt").read_bytes(), b"new\n")
        with self.assertRaisesRegex(ValueError, "candidate_worker_session_mismatch"):
            replay_candidate(worktree, self.revision, self.session, "other", self.repo, paths)
        with self.assertRaisesRegex(ValueError, "candidate_path_invalid"):
            replay_candidate(worktree, self.revision, self.session, "worker", self.repo, ["../escape"])
        with self.assertRaisesRegex(ValueError, "candidate_recovery_source_checkout_invalid"):
            replay_candidate(worktree, "wrong-revision", self.session, "worker", self.repo, paths)
        change = self.rows[1]["payload"]["item"]["changes"][str(self.repo / "tracked.txt")]
        change["unified_diff"] += "--- /tmp/other\n+++ /tmp/other\n"
        self.write_session()
        with self.assertRaisesRegex(ValueError, "candidate_patch_invalid"):
            replay_candidate(worktree, self.revision, self.session, "worker", self.repo, paths)
        (worktree / "dirty").write_text("other")
        with self.assertRaisesRegex(ValueError, "candidate_recovery_source_checkout_invalid"):
            replay_candidate(worktree, self.revision, self.session, "worker", self.repo, paths)

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

    def test_preserved_candidate_revalidates_binding_archive_and_snapshot(self):
        root = self.root / "artifacts"
        root.mkdir()
        worktree = self.root / "worktree"
        self.git("worktree", "add", "--detach", str(worktree), self.revision)
        contents = {"tracked.txt": b"one\nthree\n", "new.txt": b"new\n"}
        hashes = {name: hashlib.sha256(data).hexdigest() for name, data in contents.items()}
        previous = "prior-run"
        snapshot_root = root / ("recovery_candidate." + previous)
        snapshot_replayed_candidate(snapshot_root, hashes, contents)
        archive = root / "runs" / previous
        archive.mkdir(parents=True)
        trace = {"run_id": previous, "worker": "implementer", "audit": {"status": "rejected"},
                 "trace_retrieval": str(self.session), "thread_id": "worker", "spawn": {"provider_handle": "/root/worker"}}
        old_bindings = {"execution_repository": str(self.repo), "parent_context": {"provider_session": str(self.session),
                        "parent_thread_id": "parent"}, "runtime_evidence": {"run_started_at": "start"},
                        "worker_runtime_guard": str(self.root / "guard")}
        old_packet = {"identity": {"Run ID": previous}, "reentry": {"Approved plan SHA256": "plan"}}
        entries = []
        for name, value in (("trace_worker.json", trace), ("role_bindings.json", old_bindings),
                            ("finalization_packet.json", old_packet)):
            data = json.dumps(value).encode()
            (archive / name).write_bytes(data)
            entries.append({"path": name, "snapshot": name, "sha256": hashlib.sha256(data).hexdigest()})
        (archive / "archive_manifest.json").write_text(json.dumps({"run_id": previous, "files": entries}))
        candidate = {"prior_run_id": previous, "status": "unaccepted", "trace_sha256": entries[0]["sha256"],
                     "baseline_revision": self.revision, "files": hashes,
                     "snapshot_files": {str(snapshot_root / name): digest for name, digest in hashes.items()}}
        packet = {"identity": {"Run ID": "current"}, "reentry": {"Approved plan SHA256": "plan"}}
        bundle_path = root / "worker_activation_packets.json"
        bundle_path.write_text(json.dumps({"packets": {"implementer": {"worker_contract": {"recovered_candidate": candidate}}}}))
        bindings = {"run_id": "current", "source_checkout": str(worktree), "recovered_candidate": candidate,
                    "worker_contracts": {"implementer": {"recovered_candidate": candidate}},
                    "activation_packet_bundle": {"path": str(bundle_path),
                        "sha256": hashlib.sha256(bundle_path.read_bytes()).hexdigest()}}
        (root / "role_bindings.json").write_text(json.dumps(bindings))
        self.assertEqual(prepare._continued_candidate(root, bindings), candidate)
        altered = dict(bindings, recovered_candidate={**candidate, "baseline_revision": "other"})
        with self.assertRaisesRegex(ValueError, "continuation_candidate_binding_invalid"):
            prepare._continued_candidate(root, altered)
        try:
            recovery = importlib.import_module("recovery_candidate")
        except ModuleNotFoundError:
            recovery = importlib.import_module("scripts.recovery_candidate")
        with patch.object(recovery, "verify_edit_authorization"), patch.object(recovery, "replay_candidate", return_value=contents):
            result = prepare._recover_preserved_candidate(root, packet, worktree)
            self.assertEqual(result["_contents"], contents)
            (snapshot_root / "new.txt").write_text("tampered")
            with self.assertRaisesRegex(ValueError, "candidate_recovery_snapshot_invalid"):
                prepare._recover_preserved_candidate(root, packet, worktree)
            (snapshot_root / "new.txt").write_bytes(contents["new.txt"])
            (archive / "trace_worker.json").write_text("tampered")
            with self.assertRaisesRegex(ValueError, "candidate_recovery_archive_evidence_invalid"):
                prepare._recover_preserved_candidate(root, packet, worktree)
            (archive / "trace_worker.json").write_bytes(json.dumps(trace).encode())
            for name, data in contents.items():
                (worktree / name).write_bytes(data)
            candidate["source_already_present"] = True
            bundle_path.write_text(json.dumps({"packets": {"implementer": {"worker_contract": {"recovered_candidate": candidate}}}}))
            bindings["activation_packet_bundle"]["sha256"] = hashlib.sha256(bundle_path.read_bytes()).hexdigest()
            (root / "role_bindings.json").write_text(json.dumps(bindings))
            result = prepare._recover_preserved_candidate(root, packet, worktree)
            self.assertTrue(result["source_already_present"])
            self.assertEqual(result["_contents"], contents)
            later_snapshot = root / "recovery_candidate.current"
            snapshot_replayed_candidate(later_snapshot, hashes, contents)
            candidate["snapshot_run_id"] = "current"
            candidate["snapshot_files"] = {str(later_snapshot / name): digest for name, digest in hashes.items()}
            bundle_path.write_text(json.dumps({"packets": {"implementer": {"worker_contract": {"recovered_candidate": candidate}}}}))
            bindings["activation_packet_bundle"]["sha256"] = hashlib.sha256(bundle_path.read_bytes()).hexdigest()
            (root / "role_bindings.json").write_text(json.dumps(bindings))
            self.assertEqual(prepare._recover_preserved_candidate(root, packet, worktree)["_contents"], contents)
            (worktree / "new.txt").write_text("tampered")
            with self.assertRaisesRegex(ValueError, "candidate_content_changed"):
                prepare._recover_preserved_candidate(root, packet, worktree)

    def test_repeated_recovery_replays_verified_followup_and_rejects_tampering(self):
        root = self.root / "artifacts"
        root.mkdir()
        before = {"tracked.txt": b"one\nthree\n", "new.txt": b"new\n"}
        after = {"tracked.txt": b"one\nfour\n", "new.txt": b"new\n"}
        hashes = lambda values: {name: hashlib.sha256(data).hexdigest() for name, data in values.items()}
        def archive(run, values):
            directory = root / "runs" / run
            directory.mkdir(parents=True, exist_ok=True)
            rows = []
            for name, value in values.items():
                data = value if isinstance(value, bytes) else json.dumps(value).encode()
                (directory / name).write_bytes(data)
                rows.append({"path": name, "snapshot": name, "sha256": hashlib.sha256(data).hexdigest()})
            (directory / "archive_manifest.json").write_text(json.dumps({"run_id": run, "files": rows}))
        def snapshot(run, values):
            directory = root / ("recovery_candidate." + run)
            snapshot_replayed_candidate(directory, hashes(values), values)
            return {str(directory / name): digest for name, digest in hashes(values).items()}
        base_trace = {"run_id": "first", "worker": "implementer", "audit": {"status": "rejected"},
                      "trace_retrieval": str(self.session), "thread_id": "worker", "spawn": {"provider_handle": "/root/first"}}
        parent = {"provider_session": str(self.session), "parent_thread_id": "parent"}
        bindings = {"execution_repository": str(self.repo), "source_checkout": str(self.repo),
                    "parent_context": parent, "runtime_evidence": {"run_started_at": "start"},
                    "worker_runtime_guard": "/guard"}
        archive("first", {"trace_first.json": base_trace, "role_bindings.json": bindings,
                          "finalization_packet.json": {"identity": {"Run ID": "first"}, "reentry": {"Approved plan SHA256": "plan"}}})
        base = {"prior_run_id": "first", "status": "unaccepted", "baseline_revision": self.revision,
                "trace_sha256": hashlib.sha256(json.dumps(base_trace).encode()).hexdigest(), "files": hashes(before),
                "source_already_present": True, "snapshot_files": snapshot("first", before)}
        self.rows[1]["payload"]["item"]["changes"] = {
            str(self.repo / "tracked.txt"): {"type": "update", "unified_diff": "@@ -1,2 +1,2 @@\n one\n-three\n+four\n"}}
        self.write_session()
        (self.repo / "tracked.txt").write_bytes(after["tracked.txt"])
        dispatch = {"run_id": "second", "agent": "implementer", "coordinator_execution": {"source_checkout": str(self.repo)},
                    "worker_contract": {"recovered_candidate": base, "before_source_change_guard": "/guard"}}
        raw = ("Coordinator initialization: complete\n" + json.dumps(dispatch) + "\nTyped assignment:\n{}").encode()
        dispatch_sha = hashlib.sha256(raw).hexdigest()
        trace = {"run_id": "second", "worker": "implementer", "audit": {"status": "rejected"},
                 "trace_retrieval": str(self.session), "thread_id": "worker", "last_dispatch_at": "time",
                 "spawn": {"provider_handle": "/root/followup", "dispatch_file": str(root / "dispatch.txt"), "dispatch_file_sha256": dispatch_sha}}
        accepted = {"run_id": "second", "worker": "implementer", "audit": {"status": "passed"},
                    "spawn": {"dispatch_file": str(root / "dispatch.txt"), "dispatch_file_sha256": dispatch_sha}}
        trace_sha = hashlib.sha256(json.dumps(trace).encode()).hexdigest()
        repair = {"Attempt": 1, "Provider handle": "/root/followup", "Last dispatch at": "time",
                  "Rejected trace SHA256": trace_sha, "Corrected dispatch SHA256": dispatch_sha}
        archived_packet = {"identity": {"Run ID": "second"}, "reentry": {"Approved plan SHA256": "plan"},
                           "activation_repairs": {"implementer": repair},
                           "runtime_audits": [{"Worker": "implement", "Trace path": str(root / "trace_accepted.json")}]}
        receipts = {"dispatch.txt": {"sha256": dispatch_sha, "run_id": "second", "agent": "implementer"}}
        archive("second", {"trace_followup.json": trace, "trace_accepted.json": accepted, "dispatch.txt": raw,
                           "activation_receipts.json": receipts, "role_bindings.json": bindings,
                           "finalization_packet.json": archived_packet})
        candidate = {"prior_run_id": "second", "status": "unaccepted", "trace_sha256": trace_sha,
                     "baseline_revision": self.revision, "files": hashes(after), "source_already_present": True,
                     "snapshot_files": snapshot("second", after), "base_candidate": base}
        prior = {"reentry": {"Approved plan SHA256": "plan"}}
        try:
            recovery = importlib.import_module("recovery_candidate")
        except ModuleNotFoundError:
            recovery = importlib.import_module("scripts.recovery_candidate")
        with patch.object(recovery, "verify_edit_authorization"), patch.object(recovery, "verify_candidate", return_value=hashes(before)):
            result = prepare._recover_candidate_archive(root, prior, self.repo, candidate, visited=set(), check_checkout=True)
            self.assertEqual(result["_contents"], after)
            accepted_trace = {**trace, "audit": {"status": "passed"}}
            accepted_sha = hashlib.sha256(json.dumps(accepted_trace).encode()).hexdigest()
            accepted_packet = {**archived_packet, "worker_results": [{"Worker": "implement", "Outcome": "complete"}],
                "runtime_audits": [{"Worker": "implement", "Trace path": str(root / "trace_accepted.json"),
                                    "Provider handle": "/root/followup", "Thread ID": "worker", "Last dispatch at": "time"}]}
            archive("second", {"trace_accepted.json": accepted_trace, "dispatch.txt": raw,
                               "activation_receipts.json": receipts, "role_bindings.json": bindings,
                               "finalization_packet.json": accepted_packet})
            candidate["trace_sha256"] = accepted_sha
            self.assertEqual(prepare._recover_candidate_archive(root, prior, self.repo, candidate,
                                                                visited=set(), check_checkout=True)["_contents"], after)
            unmerged_packet = {"identity": {"Run ID": "second"}, "reentry": {"Approved plan SHA256": "plan"},
                               "workers": [], "worker_results": [], "runtime_audits": []}
            packet_sha = hashlib.sha256(json.dumps(unmerged_packet).encode()).hexdigest()
            failure = {"status": "failed", "stage": "workflow", "reported_by": "Coordinator",
                       "runtime_closure": "terminal", "run_id": "second", "snapshot_sha256": packet_sha,
                       "packet_sha256": packet_sha, "errors": ["parent_context_nonconformant:example"]}
            observation = {"Provider status": "completed", "Provider handle": "/root/followup", "Thread ID": "worker",
                           "Last dispatch at": "time"}
            ledger = {"thread_mappings": {"/root/followup": "worker"}, "timing": {"open_worker_intervals": 0}}
            archive("second", {"trace_accepted.json": accepted_trace, "dispatch.txt": raw,
                               "activation_receipts.json": receipts, "role_bindings.json": bindings,
                               "finalization_packet.json": unmerged_packet, "finalization_failure.json": failure,
                               "runtime_closure.json": {"terminal_observations": [observation]}, "runtime_dispatches.json": ledger})
            candidate["unmerged_parent_failure"] = True
            self.assertEqual(prepare._recover_candidate_archive(root, prior, self.repo, candidate,
                                                                visited=set(), check_checkout=True)["_contents"], after)
            archive("second", {"trace_accepted.json": accepted_trace, "dispatch.txt": raw,
                               "activation_receipts.json": receipts, "role_bindings.json": bindings,
                               "finalization_packet.json": unmerged_packet,
                               "finalization_failure.json": {**failure, "runtime_closure": "unverified"},
                               "runtime_closure.json": {"terminal_observations": [observation]}, "runtime_dispatches.json": ledger})
            with self.assertRaisesRegex(ValueError, "candidate_followup_trace_unverified"):
                prepare._recover_candidate_archive(root, prior, self.repo, candidate, visited=set(), check_checkout=True)
            archive("second", {"trace_accepted.json": accepted_trace, "dispatch.txt": raw,
                               "activation_receipts.json": receipts, "role_bindings.json": bindings,
                               "finalization_packet.json": unmerged_packet, "finalization_failure.json": failure,
                               "runtime_closure.json": {"terminal_observations": [observation]}, "runtime_dispatches.json": ledger})
            (root / "runs" / "second" / "dispatch.txt").write_text("tampered")
            with self.assertRaisesRegex(ValueError, "candidate_recovery_archive_evidence_invalid"):
                prepare._recover_candidate_archive(root, prior, self.repo, candidate, visited=set(), check_checkout=True)

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

    def test_activation_accepts_only_the_exact_existing_candidate(self):
        hashes = self.verify()
        snapshot = self.root / "snapshot"
        snapshot_candidate(self.repo, snapshot, hashes)
        files = {str(snapshot / name): digest for name, digest in hashes.items()}
        packet = {"finalization_packet": str(self.root / "packet.json"), "required_prefix": "Ready",
                  "run_id": "new-run", "agent": "implementer", "coordinator_execution": {"source_checkout": str(self.repo)},
                  "worker_contract": {"recovered_candidate": {"status": "unaccepted", "baseline_revision": self.revision,
                      "files": hashes, "snapshot_files": files, "source_already_present": True}}}
        assignment = {"objective": "review and complete", "input_paths": list(files)}
        self.assertIn("unaccepted", activation_message(packet, assignment))
        (self.repo / "tracked.txt").write_text("tampered")
        with self.assertRaisesRegex(ValueError, "recovered_candidate_source_checkout_changed"):
            activation_message(packet, assignment)
        (self.repo / "tracked.txt").write_text("one\nthree\n")
        (self.repo / "extra.txt").write_text("unrelated work")
        with self.assertRaisesRegex(ValueError, "recovered_candidate_source_checkout_changed"):
            activation_message(packet, assignment)
        (self.repo / "extra.txt").unlink()
        self.git("add", "tracked.txt")
        with self.assertRaisesRegex(ValueError, "recovered_candidate_source_checkout_changed"):
            activation_message(packet, assignment)

    def test_preparation_supplies_unaccepted_snapshot_to_implementer(self):
        hashes = self.verify()
        initial = prepare.prepare_run(self.repo, "CASE-1", "techops_issue_remediation", None, False)
        root = Path(initial["artifact_root"])
        (root / "implementation_plan.md").write_text("approved plan\n")
        (root / "runtime_dispatches.json").write_text('{"rejected_results":{"worker":"preserve"}}\n')
        (root / "activation_receipts.json").write_text('{"old":"preserve"}\n')
        packet = json.loads(Path(initial["finalization_packet"]).read_text())
        contents = {name: (self.repo / name).read_bytes() for name in hashes}
        packet["_recovered_candidate"] = {"prior_run_id": packet["identity"]["Run ID"],
                                          "status": "unaccepted", "files": hashes, "baseline_revision": self.revision,
                                          "_contents": contents}
        self.git("checkout", "--", "tracked.txt")
        (self.repo / "new.txt").unlink()
        (self.repo / "unrelated.txt").write_text("unrelated work")
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

    def test_preparation_and_activation_keep_an_existing_unaccepted_candidate(self):
        hashes = self.verify()
        contents = {name: (self.repo / name).read_bytes() for name in hashes}
        initial = prepare.prepare_run(self.repo, "CASE-EXISTING", "techops_issue_remediation", None, False)
        root = Path(initial["artifact_root"])
        (root / "implementation_plan.md").write_text("approved plan\n")
        prior = json.loads(Path(initial["finalization_packet"]).read_text())
        prior["_recovered_candidate"] = {"prior_run_id": prior["identity"]["Run ID"], "status": "unaccepted",
            "files": hashes, "baseline_revision": self.revision, "source_already_present": True, "_contents": contents}
        worktree = self.root / "worktree"
        self.git("worktree", "add", "--detach", str(worktree), self.revision)
        for name, data in contents.items():
            (worktree / name).write_bytes(data)
        with patch.object(prepare, "_reentry_source", return_value=prior), \
             patch.object(prepare, "resolve_repository_paths", return_value=(self.repo, worktree)):
            recovered = prepare.prepare_run(self.repo, "CASE-EXISTING", "techops_issue_remediation", None, True,
                                            remediation_reentry=True, approval_reference="approved")
        candidate = recovered["worker_contracts"]["implementer"]["recovered_candidate"]
        self.assertTrue(candidate["source_already_present"])
        self.assertIn("Do not reset or reapply it", recovered["worker_contracts"]["implementer"]["instructions"])
        bundle = json.loads(Path(recovered["activation_packet_bundle"]["path"]).read_text())
        assignment = {"objective": "review candidate", "input_paths": list(candidate["snapshot_files"])}
        self.assertIn("unaccepted", activation_message(bundle["packets"]["implementer"], assignment))
        for name, data in contents.items():
            self.assertEqual((worktree / name).read_bytes(), data)

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
        warning = ("WARNING: proceeding, even though we could not create PATH aliases: "
                   "Operation not permitted (os error 1)\n")
        action["payload"]["item"]["aggregated_output"] = warning + '{"status":"allowed"}'
        write_parent(action)
        self.assertIsNone(check())
        action["payload"]["item"]["aggregated_output"] = "Unexpected output\n" + warning + '{"status":"allowed"}'
        write_parent(action)
        with self.assertRaisesRegex(ValueError, "candidate_source_guard_missing"):
            check()
        action["payload"]["item"]["aggregated_output"] = '{"status":"allowed"}'
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
             patch.object(recovery, "verify_candidate", return_value={"tracked.txt": "digest"}), \
             patch.object(recovery, "replay_candidate", return_value={"tracked.txt": b"candidate"}):
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
            (worktree / "unrelated.txt").unlink()
            candidate_data = b"candidate"
            (worktree / "tracked.txt").write_bytes(candidate_data)
            trace["last_dispatch_at"] = "dispatch"
            trace["audit"]["errors"] = [error, "worker_fan_in_rejected", "forbidden_context_reference:archived_artifact"]
            trace_path = root / "trace_worker.json"
            trace_path.write_text(json.dumps(trace))
            receipt = {"trace": str(trace_path), "run_id": "run", "sha256": hashlib.sha256(trace_path.read_bytes()).hexdigest(),
                       "Provider handle": "/root/worker", "Last dispatch at": "dispatch"}
            prior["repositories"][0]["Resolved path"] = str(self.repo)
            rejected = {**ledger, "rejected_results": {"implementer": receipt}}
            with patch.object(checks, "trace_errors", return_value=trace["audit"]["errors"]), \
                 patch.object(recovery, "verify_candidate", return_value={"tracked.txt": hashlib.sha256(candidate_data).hexdigest()}):
                result = _verify_rejected_delivery_candidate(root, prior, failure, rejected,
                    source_checkout=worktree, source_already_present=True)
                self.assertTrue(result["source_already_present"])
                self.assertEqual(result["_contents"], {"tracked.txt": candidate_data})
                (worktree / "tracked.txt").write_text("tampered")
                with self.assertRaisesRegex(ValueError, "candidate_content_changed"):
                    _verify_rejected_delivery_candidate(root, prior, failure, rejected,
                        source_checkout=worktree, source_already_present=True)
                (worktree / "tracked.txt").write_bytes(candidate_data)
                receipt["sha256"] = "tampered"
                with self.assertRaisesRegex(ValueError, "candidate_rejected_receipt_invalid"):
                    _verify_rejected_delivery_candidate(root, prior, failure, rejected,
                        source_checkout=worktree, source_already_present=True)


if __name__ == "__main__":
    unittest.main()
