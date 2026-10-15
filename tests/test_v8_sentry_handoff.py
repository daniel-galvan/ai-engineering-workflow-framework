"""Preserve verified current-run evidence when a later Sentry stage fails."""

import copy
import json
import os
import tempfile
import unittest
from pathlib import Path

from scripts import finalize_work_record as finalizer
from tests import test_shared_runtime_acceptance as shared


class V8SentryHandoff(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        builder = shared.SharedRuntimeAcceptance()
        fixture = builder.fixture(temporary.name, "sentry_issue_remediation", "sentry_current_state_investigator")
        self.run, self.root = fixture[:2]
        self.trace, ledger = builder.export(fixture)
        Path(self.run["runtime_evidence"]["ledger"]).write_text(json.dumps(ledger))
        self.path = self.root / "trace_evidence_topology.json"
        self.path.write_text(json.dumps(self.trace))
        self.packet_path = self.root / "finalization_packet.json"
        self.packet = json.loads(self.packet_path.read_text())
        fixture_path = Path(__file__).parent / "fixtures/v37_v38_sentry_runtime_regressions.json"
        evidence = "## Confirmed Facts\n\n- HTTP rejection observed; cause unknown.\n\n"
        evidence += json.loads(fixture_path.read_text())["normalized_evidence"]
        self.evidence = self.root / "normalized_evidence.md"
        self.evidence.write_text(evidence)

    def test_self_attestation_remains_a_typed_result_field(self):
        from scripts.normalize_fix_design_result import normalize_artifact_root
        fixture_path = Path(__file__).parent / "fixtures/v37_v38_sentry_runtime_regressions.json"
        result = json.loads(fixture_path.read_text())["valid_awaiting_fix_design_result"]
        result["context_conformance"] = "context-unverified"
        target = self.root / "fix_design_result.json"
        target.write_text(json.dumps(result))
        before = target.read_bytes()
        with self.assertRaisesRegex(ValueError, "context_conformance must pass"):
            normalize_artifact_root(self.root)
        self.assertEqual(target.read_bytes(), before)

    def test_failure_preserves_provisional_evidence_without_requiring_a_fixed_trace_filename(self):
        report = finalizer.failure_handoff(self.packet_path, "Later stage failed")
        self.assertIn("Provisional artifact statement (not verified worker output): HTTP rejection observed; cause unknown.", report)
        self.assertIn(str(self.evidence), report)
        self.assertNotIn("No accepted worker result", report)
        self.assertIn("Unaccepted worker artifact retained for audit only: " + str(self.evidence), report)
        self.assertIn("reported work is provisional", report)
        self.assertIn("Prepared workers without an accepted result: evidence-topology", report)

    def test_explicit_trace_path_supports_a_filename_without_trace_in_it(self):
        saved = self.root / "evidence-proof.json"
        self.path.rename(saved)
        for path in (str(saved), saved.name):
            with self.subTest(path=path):
                self.packet["runtime_audits"] = [{"Worker": "evidence-topology", "Trace path": path}]
                self.packet_path.write_text(json.dumps(self.packet))
                report = finalizer.failure_handoff(self.packet_path, "Failed")
                self.assertIn("Provisional artifact statement (not verified worker output): HTTP rejection observed", report)
                self.assertIn(str(saved), report)

    def test_relative_packet_path_resolves_against_the_same_run(self):
        relative = Path(os.path.relpath(self.packet_path))
        report = finalizer.failure_handoff(relative, "Failed")
        self.assertIn("Provisional artifact statement (not verified worker output): HTTP rejection observed", report)
        self.assertIn(str(self.evidence), report)

    def test_rejected_wrong_role_or_stale_trace_never_promotes_facts(self):
        for change in ({"run_id": "other-run"}, {"audit": {"status": "rejected", "errors": []}},
                       {"worker": "sentry_solution_architect"}, {"last_dispatch_at": "2000-01-01T00:00:00Z"}):
            with self.subTest(change=change):
                trace = copy.deepcopy(self.trace)
                trace.update(change)
                if "worker" in change:
                    trace["spawn"]["agent"] = change["worker"]
                self.path.write_text(json.dumps(trace))
                report = finalizer.failure_handoff(self.packet_path, "Failed")
                self.assertNotIn("Provisional artifact statement (not verified worker output):", report)
                self.assertIn(str(self.evidence), report)

    def test_unidentified_legacy_contract_still_keeps_its_output_link(self):
        self.path.unlink()
        bindings_path = self.root / "role_bindings.json"
        bindings = json.loads(bindings_path.read_text())
        for contract in bindings["worker_contracts"].values():
            contract.pop("worker_id", None)
            if contract.get("output"):
                contract["output"] = Path(contract["output"]).name
        bindings_path.write_text(json.dumps(bindings))
        report = finalizer.failure_handoff(self.packet_path, "Failed")
        self.assertIn(str(self.evidence), report)
        self.assertIn("Unaccepted worker artifact retained for audit only: " + str(self.evidence), report)
        self.assertNotIn("Provisional artifact statement (not verified worker output):", report)

    def test_invalid_evidence_is_linked_without_promoting_facts(self):
        self.evidence.write_text("## Confirmed Facts\n\n- Unvalidated claim\n")
        report = finalizer.failure_handoff(self.packet_path, "Failed")
        self.assertNotIn("Provisional artifact statement (not verified worker output):", report)
        self.assertIn(str(self.evidence), report)

    def test_unrelated_or_malformed_trace_does_not_hide_the_valid_one(self):
        (self.root / "a_trace.json").write_text("not JSON")
        report = finalizer.failure_handoff(self.packet_path, "Failed")
        self.assertIn("Provisional artifact statement (not verified worker output): HTTP rejection observed", report)

    def test_external_trace_path_and_missing_bindings_cannot_establish_acceptance(self):
        outside = self.root.parent / "external-trace.json"
        self.path.rename(outside)
        self.packet["runtime_audits"] = [{"Trace path": str(outside)}]
        self.packet_path.write_text(json.dumps(self.packet))
        self.assertNotIn("Provisional artifact statement (not verified worker output):", finalizer.failure_handoff(self.packet_path, "Failed"))
        self.path.symlink_to(outside)
        self.assertNotIn("Provisional artifact statement (not verified worker output):", finalizer.failure_handoff(self.packet_path, "Failed"))
        self.path.unlink()
        outside.rename(self.path)
        (self.root / "role_bindings.json").unlink()
        self.assertNotIn("Provisional artifact statement (not verified worker output):", finalizer.failure_handoff(self.packet_path, "Failed"))


if __name__ == "__main__":
    unittest.main()
