"""Connect no-fix clarification, analytical failure, closure and response delivery."""

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from scripts import prepare_run, finalize_work_record as finalizer
from scripts.normalize_fix_design_result import normalize_artifact_root
from scripts.validation.contracts import fix_design_result_errors
from scripts.worker_runtime_evidence import read_runtime_events

ROOT = Path(__file__).resolve().parents[1]
HANDLE = "/root/solution_architect"
THREAD = "00000000-0000-0000-0000-000000000002"


class SentryFailureRegression(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.repository = Path(temporary.name) / "repo"
        self.repository.mkdir()
        for args in (("init", "-q"), ("config", "user.name", "Fixture"),
                     ("config", "user.email", "fixture@example.invalid")):
            subprocess.run(["git", "-C", str(self.repository), *args], check=True, capture_output=True)
        (self.repository / "README.md").write_text("Synthetic fixture\n")
        for args in (("add", "."), ("commit", "-qm", "Synthetic fixture")):
            subprocess.run(["git", "-C", str(self.repository), *args], check=True, capture_output=True)
        inputs = self.repository / "inputs.json"
        inputs.write_text(json.dumps({"inputs": [{"Input ID": "IN-001", "Input or artifact": "Synthetic occurrence",
            "Source or path": "Current user request", "Authority": "User", "Status": "Registered"}]}))
        self.run = prepare_run.prepare_run(self.repository, "TEST-1", "sentry_issue_remediation", None, False,
                                          input_manifest=inputs)
        self.root = Path(self.run["artifact_root"])
        self.packet = self.root / "finalization_packet.json"
        self.closure = self.root / "runtime_closure.json"
        fixture = json.loads((ROOT / "tests/fixtures/v37_v38_sentry_runtime_regressions.json").read_text())
        self.evidence = self.root / "normalized_evidence.md"
        self.evidence.write_text(fixture["normalized_evidence"] + "\n## Confirmed Facts\n\n- HTTP rejection is observed; its cause is unknown.\n")
        self.design = fixture["valid_awaiting_fix_design_result"]
        self.design["worker_handle"] = HANDLE
        (self.root / "fix_design_result.json").write_text(json.dumps(self.design))

    def command(self, *args):
        return subprocess.run([sys.executable, str(ROOT / "scripts/finalize_work_record.py"), *map(str, args)],
                              capture_output=True, text=True)

    def arguments(self):
        return ("--packet", self.packet, "--closure", self.closure, "--record", self.root / "work_record.md",
                "--analytical-failure", "Synthetic rejected Fix Design envelope", "--analytical-failure-stage", "fix_design",
                "--completed-handle", HANDLE, "--coordinator-model-effort", "Not exposed / Not exposed",
                "--framework-revision", subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                "--framework-status", "dirty", "--evidence-artifact", self.evidence)

    def terminal_receipt(self):
        started = self.run["runtime_evidence"]["run_started_at"]
        base = datetime.fromisoformat(started.replace("Z", "+00:00"))
        stamp = lambda seconds: (base + timedelta(seconds=seconds)).isoformat()
        event = lambda seconds, kind, **payload: {"timestamp": stamp(seconds), "type": kind, "payload": payload}
        parent = "00000000-0000-0000-0000-000000000001"
        source = self.root / "provider.jsonl"
        source.write_text("\n".join(json.dumps(row) for row in [event(0, "session_meta", id=parent),
            event(1, "response_item", type="function_call", namespace="collaboration", name="spawn_agent",
                  arguments=json.dumps({"task_name": "solution_architect"})),
            event(1, "event_msg", item={"type": "SubAgentActivity", "kind": "started", "agent_path": HANDLE, "agent_thread_id": THREAD}),
            event(10, "event_msg", item={"type": "SubAgentActivity", "kind": "completed", "agent_path": HANDLE})]) + "\n")
        Path(self.run["runtime_evidence"]["ledger"]).write_text(json.dumps(read_runtime_events(source, parent, started)))
        self.closure.write_text(json.dumps({"runtime_closure": [{"Run or stage": "planning", "Receipt owner": "Coordinator",
            "Completed worker handles": HANDLE, "Runtime status": "Terminal", "Remaining active handles": "0",
            "Closure evidence or blocker": "provider status snapshot " + stamp(20) + ": " + HANDLE + "=completed"}],
            "terminal_observations": [{"Provider handle": HANDLE, "Thread ID": THREAD, "Provider status": "completed",
                "Status source": "read_thread", "Observed at": stamp(20),
                "Last dispatch at": stamp(1), "Latest turn started at": stamp(1),
                "Latest turn completed at": stamp(10), "Latest turn status": "completed", "Thread status": "idle"}]}))

    def test_no_fix_selected_clarification_normalizes_without_a_plan(self):
        self.assertEqual(fix_design_result_errors(self.design, require_plan=True), [])
        first = copy.deepcopy(self.design)
        first["supported_remediation_boundary"] = "Candidate investigation location; no remediation selected"
        first["supported_intended_change"] = "No supported change selected"
        self.assertTrue(fix_design_result_errors(first, require_plan=True))
        first["supported_intended_change"] = ""
        self.assertIn("supported remediation boundary and intended change must be provided together",
                      fix_design_result_errors(first, require_plan=True))
        self.assertEqual(normalize_artifact_root(self.root)["validation"], "passed")
        self.assertFalse((self.root / "implementation_plan.md").exists())

    def test_failure_preserves_identity_findings_and_native_terminal_receipt(self):
        self.terminal_receipt()
        before_closure = self.closure.read_bytes()
        packet = json.loads(self.packet.read_text())
        packet["handoff"] = {"established": ["HTTP rejection is observed; its cause is unknown."],
                             "artifacts": [str(self.evidence)]}
        packet["evidence"] = [{"Evidence ID": "E-001", "Source": "Synthetic occurrence", "Summary": "Observed HTTP rejection",
            "Confidence": "High", "Uncertainty": "Cause unknown", "Status": "Verified"}]
        packet["claims"] = [{"Claim ID": "C-001", "Claim": "Cause remains unknown", "Evidence refs": "E-001",
            "Confidence": "High", "Uncertainty": "Unknown exception", "Status": "Supported"}]
        packet["decisions"] = [{"Decision ID": "D-001", "Decision": "Obtain the missing exception", "Claim refs": "C-001",
            "Owner": "Coordinator", "Status": "Applied"}]
        packet["actions"] = [{"Action ID": "A-001", "Action": "Correlate destination logs", "Decision ref": "D-001",
            "Owner": "Service owner", "Status": "Proposed"}]
        self.packet.write_text(json.dumps(packet))
        result = self.command(*self.arguments())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        current = json.loads(self.packet.read_text())
        self.assertEqual(current["identity"]["Run ID"], self.run["run_id"])
        self.assertEqual(current["evidence"][0], packet["evidence"][0])
        self.assertEqual(current["claims"][0], packet["claims"][0])
        self.assertEqual(current["decisions"][0], packet["decisions"][0])
        self.assertEqual(current["actions"][0], packet["actions"][0])
        self.assertEqual(self.closure.read_bytes(), before_closure)
        self.assertIn("HTTP rejection is observed; its cause is unknown", result.stdout)
        self.assertIn("runtime terminal", result.stdout)
        self.assertNotIn("Provider release confirmed", result.stdout)
        repeated = self.command(*self.arguments())
        self.assertEqual(repeated.returncode, 0, repeated.stdout + repeated.stderr)
        retried = json.loads(self.packet.read_text())
        self.assertEqual(retried["handoff"]["best_current_explanations"], current["handoff"]["best_current_explanations"])
        self.assertEqual(len(retried["synchronization"]), len(current["synchronization"]))
        proposed = self.root / "proposed_response.md"
        proposed.write_text(result.stdout.split("Workflow-framework validation: passed\n", 1)[1])
        verified = self.command("--packet", self.packet, "--verify-response", proposed)
        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
        self.assertEqual(proposed.read_text().strip().splitlines()[-2][:12], "Not checked:")
        proposed.write_text(proposed.read_text() + "An extra summary\n")
        self.assertEqual(self.command("--packet", self.packet, "--verify-response", proposed).returncode, 2)
        self.assertFalse((self.root / "handoff_delivery.json").exists())

    def test_missing_closure_never_manufactures_release_or_changes_identity(self):
        before = self.packet.read_bytes()
        result = self.command(*self.arguments())
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.packet.read_bytes(), before)
        self.assertFalse(self.closure.exists())
        self.assertIn("runtime closure unverified", result.stdout)
        self.assertNotIn("Provider release confirmed", result.stdout)
        receipt = json.loads((self.root / "finalization_failure.json").read_text())
        self.assertEqual(receipt["run_id"], self.run["run_id"])
        self.assertFalse(receipt["validation_performed"])
        proposed = self.root / "proposed_response.md"
        proposed.write_bytes((self.root / "handoff_failure.md").read_bytes())
        self.assertEqual(self.command("--packet", self.packet, "--verify-response", proposed).returncode, 0)


    def test_delivery_rejects_self_comparison_and_changed_canonical_content(self):
        self.command(*self.arguments())
        canonical = self.root / "handoff_failure.md"
        self.assertEqual(self.command("--packet", self.packet, "--verify-response", canonical).returncode, 2)
        proposed = self.root / "proposed_response.md"
        proposed.write_bytes(canonical.read_bytes())
        self.assertEqual(self.command("--packet", self.packet, "--verify-response", proposed).returncode, 0)
        canonical.write_text(canonical.read_text() + "Altered canonical report\n")
        proposed.write_bytes(canonical.read_bytes())
        failed = self.command("--packet", self.packet, "--verify-response", proposed)
        self.assertEqual(failed.returncode, 2)
        self.assertIn("handoff_canonical_content_changed", failed.stdout)
        self.assertFalse((self.root / "handoff_delivery.json").exists())

    def test_malformed_closure_is_reported_without_mutating_the_packet(self):
        before = self.packet.read_bytes()
        for value in ([], {"runtime_closure": ["malformed"]}):
            with self.subTest(value=value):
                self.closure.write_text(json.dumps(value))
                result = self.command(*self.arguments())
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertNotIn("Traceback", result.stderr)
                self.assertEqual(self.packet.read_bytes(), before)

    def test_delivery_rejects_a_changed_packet(self):
        self.command(*self.arguments())
        proposed = self.root / "proposed_response.md"
        proposed.write_bytes((self.root / "handoff_failure.md").read_bytes())
        packet = json.loads(self.packet.read_text())
        packet["identity"]["Run ID"] = "different-run"
        self.packet.write_text(json.dumps(packet))
        result = self.command("--packet", self.packet, "--verify-response", proposed)
        self.assertEqual(result.returncode, 2)
        self.assertIn("handoff_packet_changed", result.stdout)

    def test_malformed_control_failure_packet_has_no_traceback(self):
        self.packet.write_text("{}")
        result = self.command("--packet", self.packet, "--workflow-failure", "Malformed packet")
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)

    def test_control_failure_preserves_current_audited_evidence_facts(self):
        from tests.test_shared_runtime_acceptance import SharedRuntimeAcceptance
        builder = SharedRuntimeAcceptance()
        fixture = builder.fixture(str(self.repository), "sentry_issue_remediation", "sentry_current_state_investigator")
        trace, ledger = builder.export(fixture)
        root = fixture[1]
        Path(fixture[0]["runtime_evidence"]["ledger"]).write_text(json.dumps(ledger))
        (root / "evidence_topology.trace.json").write_text(json.dumps(trace))
        (root / "normalized_evidence.md").write_text("## Confirmed Facts\n\n- Synthetic rejection observed; cause unknown.\n")
        result = self.command("--packet", root / "finalization_packet.json", "--workflow-failure", "Closure unavailable")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Recorded evidence fact: Synthetic rejection observed; cause unknown", result.stdout)
        trace["run_id"] = "old-run"
        (root / "evidence_topology.trace.json").write_text(json.dumps(trace))
        result = self.command("--packet", root / "finalization_packet.json", "--workflow-failure", "Closure unavailable")
        self.assertNotIn("Recorded evidence fact: Synthetic rejection observed", result.stdout)


if __name__ == "__main__":
    unittest.main()
