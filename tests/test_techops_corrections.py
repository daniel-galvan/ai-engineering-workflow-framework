"""Regressions for native status reads and TechOps blocked publication."""

import copy
import hashlib
import json
import io
import os
import subprocess
from contextlib import redirect_stdout
from unittest.mock import patch
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import finalize_work_record as finalizer
import validate_worker_runtime as runtime
import prepare_run as prepare
import planning_contracts
from tests.worker_response_support import stage_worker_response


class TechOpsCorrections(unittest.TestCase):
    def test_invalid_techops_goal_provenance_stops_before_creating_run_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "inputs.json"
            manifest.write_text(json.dumps({"schema_version": 1, "status": "explicit", "inputs": [{
                "Input ID": "RUN-GOAL-001", "Input or artifact": "Requested outcome: implementation_plan",
                "Source or path": "Current user request in this Codex App chat",
                "Authority": "Explicit user outcome", "Classification": "requested outcome",
                "Expected use": "Validate playbook and objective selection", "Status": "Registered",
            }]}))
            with self.assertRaisesRegex(ValueError, "run_goal_provenance_conflict:RUN-GOAL-001"):
                prepare.prepare_run(
                    root, "ECHO-2806", "techops_issue_remediation", None, False,
                    input_manifest=manifest, workflow_objective="implementation_planning",
                    requested_outcome="implementation_plan",
                )
            self.assertFalse((root / ".thoughts" / "ECHO-2806").exists())

    def test_owner_can_repair_references_without_rewriting_accepted_findings(self):
        from scripts.merge_techops_result import validated_result
        with tempfile.TemporaryDirectory() as directory:
            run = prepare.prepare_run(Path(directory), "LINK-1", "techops_issue_remediation", None, False)
            packet = json.loads(Path(run["finalization_packet"]).read_text())
            bindings = json.loads(Path(run["role_binding_manifest"]).read_text())
            template = json.loads((prepare.ROOT / "templates/finalization_packet.json").read_text())
            result = {"run_id": packet["identity"]["Run ID"], "worker_result": {
                **dict.fromkeys(template["worker_results"][0], "Current evidence"),
                "Worker": "issue-evidence", "Outcome": "complete"},
                "integration_decision": {"decision": "not_required", "reason": "One component", "evidence_refs": "E-ISS-1"}}
            for table, key, identity in (("evidence", "Evidence ID", "E-ISS-1"),
                                         ("claims", "Claim ID", "CL-ISS-1"),
                                         ("decisions", "Decision ID", "DE-ISS-1"),
                                         ("actions", "Action ID", "A-ISS-1")):
                result[table] = [{**dict.fromkeys(template[table][0], "Observed"), key: identity}]
            for table, field, reference in (("claims", "Evidence refs", "E-ISS-1"),
                                             ("decisions", "Claim refs", "CL-ISS-1"),
                                             ("actions", "Decision ref", "DE-ISS-1")):
                result[table][0][field] = reference
            for table, key in (("evidence", "Evidence ID"), ("claims", "Claim ID"),
                               ("decisions", "Decision ID")):
                second = {**result[table][0], key: result[table][0][key].replace("-1", "-2")}
                result[table].append(second)
            packet = validated_result(packet, result, bindings, "current_state_investigator")
            for table, field, key in (("claims", "Evidence refs", "Claim ID"),
                                      ("decisions", "Claim refs", "Decision ID"),
                                      ("actions", "Decision ref", "Action ID")):
                with self.subTest(table=table):
                    corrected = copy.deepcopy(result)
                    corrected[table][0][field] = corrected[table][0][field].replace("-1", "-2")
                    revised = validated_result(packet, corrected, bindings, "current_state_investigator")
                    row = next(r for r in revised[table] if r[key] == corrected[table][0][key])
                    self.assertEqual(row[field], corrected[table][0][field])
                    other = next(k for k in corrected[table][0] if k not in {key, field})
                    corrected[table][0][other] = "Rewritten finding"
                    with self.assertRaisesRegex(ValueError, "worker_result_row_conflict"):
                        validated_result(packet, corrected, bindings, "current_state_investigator")
                    corrected = copy.deepcopy(result)
                    corrected[table][0][key] = corrected[table][0][key].replace("-ISS-", "-FD-")
                    with self.assertRaisesRegex(ValueError, "worker_result_row_invalid"):
                        validated_result(packet, corrected, bindings, "current_state_investigator")

    def test_claim_evidence_refs_cannot_use_input_ids(self):
        from scripts.merge_techops_result import validated_result
        with tempfile.TemporaryDirectory() as directory:
            run = prepare.prepare_run(Path(directory), "REF-1", "techops_issue_remediation", None, False)
            packet = json.loads(Path(run["finalization_packet"]).read_text())
            bindings = json.loads(Path(run["role_binding_manifest"]).read_text())
            template = json.loads((prepare.ROOT / "templates/finalization_packet.json").read_text())
            result = {"run_id": packet["identity"]["Run ID"], "worker_result": {
                **dict.fromkeys(template["worker_results"][0], "Current evidence"),
                "Worker": "issue-evidence", "Outcome": "complete"}, "claims": [{
                    **dict.fromkeys(template["claims"][0], "Observed"),
                    "Claim ID": "CL-ISS-1", "Evidence refs": "CL-ISS-1"}]}
            result["claims"][0]["Evidence refs"] = "IN-001"
            with self.assertRaisesRegex(ValueError, "worker_result_reference_type_invalid"):
                validated_result(packet, result, bindings, "current_state_investigator")

    def test_analytical_references_must_use_the_correct_record_type(self):
        from scripts.merge_techops_result import validated_result
        with tempfile.TemporaryDirectory() as directory:
            run = prepare.prepare_run(Path(directory), "REF-2", "techops_issue_remediation", None, False)
            packet = json.loads(Path(run["finalization_packet"]).read_text())
            bindings = json.loads(Path(run["role_binding_manifest"]).read_text())
            self.assertIn("Claims Evidence refs accepts only E-* evidence IDs",
                          bindings["worker_contracts"]["current_state_investigator"]["result_instructions"])
            template = json.loads((prepare.ROOT / "templates/finalization_packet.json").read_text())
            result = {"run_id": packet["identity"]["Run ID"], "worker_result": {
                **dict.fromkeys(template["worker_results"][0], "Current evidence"),
                "Worker": "issue-evidence", "Outcome": "complete"}}
            result["integration_decision"] = {"decision": "not_required", "reason": "One component", "evidence_refs": "E-ISS-1"}
            rows = {}
            for table, key, identity in (("evidence", "Evidence ID", "E-ISS-1"),
                                         ("claims", "Claim ID", "CL-ISS-1"),
                                         ("decisions", "Decision ID", "DE-ISS-1"),
                                         ("actions", "Action ID", "A-ISS-1")):
                rows[table] = {**dict.fromkeys(template[table][0], "Observed"), key: identity}
                result[table] = [rows[table]]
            rows["claims"]["Evidence refs"] = "E-ISS-1"
            rows["decisions"]["Claim refs"] = "CL-ISS-1"
            rows["actions"]["Decision ref"] = "DE-ISS-1"
            with self.subTest(kind="valid"):
                validated_result(packet, result, bindings, "current_state_investigator")
            for table, field, invalid in (("claims", "Evidence refs", "CL-ISS-1"),
                                          ("decisions", "Claim refs", "DE-ISS-1"),
                                          ("actions", "Decision ref", "A-ISS-1")):
                with self.subTest(field=field):
                    rows[table][field] = invalid
                    with self.assertRaises(ValueError) as raised:
                        validated_result(packet, result, bindings, "current_state_investigator")
                    target = {"claims": "evidence", "decisions": "claims", "actions": "decisions"}[table]
                    identity = rows[table][{"claims": "Claim ID", "decisions": "Decision ID",
                                            "actions": "Action ID"}[table]]
                    self.assertIn(
                        f"worker_result_reference_type_invalid:{table}:{identity}:{field}:{invalid}:expected_{target}_id",
                        str(raised.exception))
                    rows[table][field] = {"claims": "E-ISS-1", "decisions": "CL-ISS-1",
                                          "actions": "DE-ISS-1"}[table]

    def test_merger_rejects_edits_after_result_audit(self):
        from scripts.merge_techops_result import merge_result
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = root / "inputs.json"
            inputs.write_text(json.dumps({"inputs": [{"Input ID": "IN-001", "Input or artifact": "Current issue",
                "Source or path": "User", "Authority": "User", "Status": "Verified"}]}))
            run = prepare.prepare_run(root, "HASH-1", "techops_issue_remediation", None, False, input_manifest=inputs)
            packet_path = Path(run["finalization_packet"])
            packet = json.loads(packet_path.read_text())
            template = json.loads((prepare.ROOT / "templates/finalization_packet.json").read_text())
            result = {"run_id": packet["identity"]["Run ID"], "worker_result": {
                **dict.fromkeys(template["worker_results"][0], "Current evidence"),
                "Worker": "issue-evidence", "Outcome": "complete"}, "evidence": [
                    {**dict.fromkeys(template["evidence"][0], "Observed"), "Evidence ID": "E-ISS-1"}],
                "integration_decision": {"decision": "not_required", "reason": "One component", "evidence_refs": "E-ISS-1"}}
            trace, exported = stage_worker_response(run, "current_state_investigator", result)
            source = Path(exported["result_artifact"]["path"])
            merge_result(packet_path, "current_state_investigator", trace=trace)
            before = packet_path.read_bytes()
            result["worker_result"]["Confidence"] = "Coordinator rewrite"
            source.write_text(json.dumps(result))
            with self.assertRaisesRegex(ValueError, "worker_result_artifact_changed"):
                merge_result(packet_path, "current_state_investigator", trace=trace)
            self.assertEqual(packet_path.read_bytes(), before)
            packet["runtime_audits"] = []
            packet_path.write_text(json.dumps(packet))
            Path(run["runtime_evidence"]["ledger"]).write_text("{}")
            before = packet_path.read_bytes()
            with self.assertRaisesRegex(ValueError, "worker_result_trace_required"):
                merge_result(packet_path, "current_state_investigator")
            self.assertEqual(packet_path.read_bytes(), before)

    def test_merger_accepts_execution_repository_relative_trace_path(self):
        from scripts.merge_techops_result import merge_result
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = root / "inputs.json"
            inputs.write_text(json.dumps({"inputs": [{"Input ID": "IN-001", "Input or artifact": "Current issue",
                "Source or path": "User", "Authority": "User", "Status": "Verified"}]}))
            run = prepare.prepare_run(root, "TRACE-PATH-1", "techops_issue_remediation", None, False,
                                      input_manifest=inputs)
            packet_path = Path(run["finalization_packet"])
            packet = json.loads(packet_path.read_text())
            template = json.loads((prepare.ROOT / "templates/finalization_packet.json").read_text())
            result = {"run_id": packet["identity"]["Run ID"], "worker_result": {
                **dict.fromkeys(template["worker_results"][0], "Current evidence"),
                "Worker": "issue-evidence", "Outcome": "complete"}, "evidence": [
                    {**dict.fromkeys(template["evidence"][0], "Observed"), "Evidence ID": "E-ISS-1"}],
                "integration_decision": {"decision": "not_required", "reason": "One component", "evidence_refs": "E-ISS-1"}}
            trace_path, _ = stage_worker_response(run, "current_state_investigator", result)
            repository_relative_trace = trace_path.resolve().relative_to(root.resolve())
            previous_cwd = Path.cwd()
            try:
                os.chdir(root)
                merge_result(packet_path, "current_state_investigator", trace=repository_relative_trace)
            finally:
                os.chdir(previous_cwd)

            packet = json.loads(packet_path.read_text())
            self.assertIn("issue-evidence", {row["Worker"] for row in packet["runtime_audits"]})

    def test_techops_worker_row_uses_provider_activation_metadata_without_child_turn_context(self):
        from scripts.merge_techops_result import merge_result

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = root / "inputs.json"
            inputs.write_text(json.dumps({"inputs": [{"Input ID": "IN-001", "Input or artifact": "Current issue",
                "Source or path": "User", "Authority": "User", "Status": "Verified"}]}))
            run = prepare.prepare_run(root, "HASH-METADATA", "techops_issue_remediation", None, False,
                                      input_manifest=inputs)
            packet_path = Path(run["finalization_packet"])
            packet = json.loads(packet_path.read_text())
            template = json.loads((prepare.ROOT / "templates/finalization_packet.json").read_text())
            result = {"run_id": packet["identity"]["Run ID"], "worker_result": {
                **dict.fromkeys(template["worker_results"][0], "Current evidence"),
                "Worker": "issue-evidence", "Outcome": "complete",
                "Actual model/effort": "gpt-6-luna / high"}, "evidence": [
                    {**dict.fromkeys(template["evidence"][0], "Observed"), "Evidence ID": "E-ISS-1"}],
                "integration_decision": {"decision": "not_required", "reason": "One component", "evidence_refs": "E-ISS-1"}}
            trace_path, trace = stage_worker_response(run, "current_state_investigator", result,
                                                      include_runtime_configuration=False)
            self.assertIsNone(trace["runtime_configurations"][0]["model"])
            self.assertIsNone(trace["runtime_configurations"][0]["effort"])
            self.assertEqual(trace["activation_metadata"], {"model": "gpt-6-luna", "effort": "high"})
            merge_result(packet_path, "current_state_investigator", trace=trace_path)
            packet = json.loads(packet_path.read_text())
            worker = next(row for row in packet["workers"] if row["Worker"] == "issue-evidence")
            self.assertEqual(worker["Provider-observed model/effort"], "gpt-6-luna / high")

    def test_techops_pre_release_rejects_nonterminal_planning_identity(self):
        packet = {"identity": {"Playbook / version": "playbooks/techops_issue_remediation.md / 0.5.33",
                               "Lifecycle": "planning", "State": "handoff", "Workflow outcome": "incomplete"}}
        with self.assertRaisesRegex(ValueError, "TechOps planning.*ready_for_implementation"):
            finalizer._validate_pre_release_state(packet)
        packet["identity"].update({"State": "ready_for_implementation", "Workflow outcome": "completed"})
        finalizer._validate_pre_release_state(packet)

    def test_packet_cannot_rewrite_accepted_worker_reasoning(self):
        from scripts.merge_techops_result import merged_result_errors
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "failure_path_result.json"
            original = {"claims": [{"Claim ID": "CL-FP-1", "Evidence refs": "E-FP-1", "Claim": "First line\nNext | line"}],
                        "evidence": [], "decisions": [], "actions": []}
            source.write_text(json.dumps(original))
            manifest = {"worker_contracts": {"dependency_analyst": {"result": str(source)}}}
            packet = {**copy.deepcopy(original), "worker_results": [{"Worker": "failure-path", "Outcome": "complete"}]}
            self.assertEqual(merged_result_errors(packet, manifest, root), [])
            rendered = copy.deepcopy(packet)
            rendered["claims"][0]["Claim"] = "First line<br>Next | line"
            self.assertEqual(merged_result_errors(rendered, manifest, root, table_projection=True), [])
            self.assertTrue(merged_result_errors(rendered, manifest, root))
            rendered["claims"][0]["Evidence refs"] += " E-FD-1"
            self.assertTrue(merged_result_errors(rendered, manifest, root, table_projection=True))
            packet["claims"][0]["Evidence refs"] += " E-FD-1"
            self.assertIn("worker_owned_record_changed:failure-path:claims:CL-FP-1",
                          merged_result_errors(packet, manifest, root))
            source.unlink()
            self.assertIn("worker_result_source_missing:failure-path", merged_result_errors(packet, manifest, root))

    def test_failed_techops_handoff_requires_prepared_bounded_continuation(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            inputs = repository / "inputs.json"
            inputs.write_text(json.dumps({"inputs": [{"Input ID": "I-001", "Input or artifact": "Issue",
                "Source or path": "User", "Authority": "User", "Status": "Verified"}]}))
            run = prepare.prepare_run(repository, "ISSUE-1", "techops_issue_remediation", None, False,
                                      input_manifest=inputs)
            root = Path(run["artifact_root"])
            packet_path = root / "finalization_packet.json"
            packet = json.loads(packet_path.read_text())
            packet["identity"]["Lifecycle"] = "planning"
            packet_path.write_text(json.dumps(packet))
            failure = root / "finalization_failure.json"
            failure.write_text(json.dumps({"status": "failed", "stage": "workflow", "run_id": run["run_id"]}))
            def errors(run, digest="a" * 64):
                bundle = run["activation_packet_bundle"]
                return runtime.activation_packet_errors(Path(bundle["path"]), "documenter", bundle["sha256"],
                                                        rejected_trace_sha256=digest)
            self.assertIn("worker_activation_requires_planning_recovery", errors(run))
            continued = prepare.prepare_run(repository, "ISSUE-1", "techops_issue_remediation", None, True,
                                            input_manifest=inputs)
            self.assertEqual(continued["run_id"], run["run_id"])
            self.assertNotIn("worker_activation_requires_planning_recovery", errors(continued))
            self.assertIn("techops_pre_handoff_workers_incomplete", errors(continued))
            self.assertIn("worker_activation_requires_planning_recovery", errors(continued, None))
            failure.write_text(json.dumps({"status": "failed", "stage": "workflow", "run_id": "other"}))
            self.assertIn("worker_activation_requires_planning_recovery", errors(continued))
            failure.write_text(json.dumps({"status": "failed", "stage": "workflow", "run_id": run["run_id"],
                                           "attempt_count": 2}))
            with self.assertRaisesRegex(ValueError, "exhausted_attempts"):
                prepare.prepare_run(repository, "ISSUE-1", "techops_issue_remediation", None, True,
                                    input_manifest=inputs)
            self.assertIn("worker_activation_requires_planning_recovery", errors(continued))

    def test_unactivated_remediation_recovery_requires_matching_native_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = root / "implementation_plan.md"
            plan.write_text("approved plan")
            reentry = {"Prior run ID": "planning", "Approval reference": "approved",
                       "Approved plan": str(plan.resolve()), "Approved plan SHA256": hashlib.sha256(plan.read_bytes()).hexdigest()}
            packet = {"identity": {"Run ID": "delivery", "Lifecycle": "remediation"}, "reentry": reentry,
                      "workers": [], "worker_results": [], "runtime_audits": []}
            (root / "finalization_packet.json").write_text(json.dumps(packet))
            snapshot = root / "finalization_snapshot.json"
            snapshot.write_text(json.dumps(packet))
            failure = {"status": "failed", "stage": "workflow", "run_id": "delivery",
                       "errors": ["remediation_not_activated"], "runtime_closure": "terminal",
                       "reported_by": "Coordinator", "packet_snapshot": str(snapshot),
                       "snapshot_sha256": hashlib.sha256(snapshot.read_bytes()).hexdigest(),
                       "packet_sha256": hashlib.sha256(snapshot.read_bytes()).hexdigest()}
            failure_path = root / "finalization_failure.json"
            failure_path.write_text(json.dumps(failure))
            ledger = {"events": [], "failed_dispatches": [], "thread_mappings": {}}
            ledger_path = root / "runtime_dispatches.json"
            ledger_path.write_text(json.dumps(ledger))
            closure = {"runtime_closure": [{"Runtime status": "Terminal", "Remaining active handles": "0",
                                            "Completed worker handles": "None dispatched"}]}
            (root / "runtime_closure.json").write_text(json.dumps(closure))
            bindings = {"playbook": "techops_issue_remediation", "run_id": "delivery", "runtime_evidence": {"ledger": "bound"}}
            with patch("worker_runtime_evidence.dispatch_audit_errors", return_value=[]):
                self.assertEqual(prepare._recover_unactivated_remediation(root, bindings),
                                 (failure_path, failure_path.read_bytes(), (root / "runtime_closure.json").read_bytes()))
                for changed in ({**ledger, "events": [{"Operation": "spawn_agent"}]},
                                {**ledger, "failed_dispatches": [{}]}, {**ledger, "thread_mappings": {"x": "y"}}):
                    ledger_path.write_text(json.dumps(changed))
                    self.assertIsNone(prepare._recover_unactivated_remediation(root, bindings))
                ledger_path.write_text(json.dumps(ledger))
                plan.write_text("changed plan")
                self.assertIsNone(prepare._recover_unactivated_remediation(root, bindings))
                plan.write_text("approved plan")
                failure_path.write_text(json.dumps({**failure, "errors": ["different_failure"]}))
                self.assertIsNone(prepare._recover_unactivated_remediation(root, bindings))
                failure_path.write_text(json.dumps({**failure, "snapshot_sha256": "bad"}))
                self.assertIsNone(prepare._recover_unactivated_remediation(root, bindings))
                failure_path.write_text(json.dumps({**failure, "attempt_count": 2}))
                self.assertIsNone(prepare._recover_unactivated_remediation(root, bindings))
                failure_path.write_text(json.dumps(failure))
                (root / "runtime_closure.json").write_text(json.dumps({"runtime_closure": [{
                    "Runtime status": "Blocked", "Remaining active handles": "Unknown"}]}))
                self.assertIsNone(prepare._recover_unactivated_remediation(root, bindings))
                (root / "runtime_closure.json").write_text(json.dumps(closure))
            failure_path.write_text(json.dumps(failure))
            with patch("worker_runtime_evidence.dispatch_audit_errors", return_value=["stale"]):
                self.assertIsNone(prepare._recover_unactivated_remediation(root, bindings))

    def test_pre_handoff_checks_upstream_audits_without_accepting_rejected_handoff(self):
        packet = {"identity": {"Playbook / version": "playbooks/techops_issue_remediation.md / 0.5.33",
                              "Lifecycle": "planning", "Engineering outcome": "plan_only"},
                  "worker_results": [{"Worker": name, "Outcome": "complete"}
                                     for name in ("issue-evidence", "failure-path", "fix-design", "handoff")],
                  "runtime_audits": [{"Worker": name} for name in ("issue-evidence", "failure-path", "fix-design", "handoff")],
                  "terminal_observations": [{"Provider handle": "/root/handoff"}]}
        saved = copy.deepcopy(packet)
        with patch.object(planning_contracts, "_worker_runtime_audit_errors", return_value=["upstream_defect"]) as audit:
            errors = planning_contracts._techops_planning_contract_errors(packet, Path("packet.json"), pre_handoff=True)
            self.assertIn("upstream_defect", errors)
            checked, _, completed = audit.call_args.args
            self.assertNotIn("handoff", completed)
            self.assertNotIn("handoff", {row["Worker"] for row in checked["runtime_audits"]})
            self.assertEqual(checked["terminal_observations"], [])
            planning_contracts._techops_planning_contract_errors(packet, Path("packet.json"))
            self.assertIn("handoff", audit.call_args.args[2])
        self.assertEqual(packet, saved)

    def test_continuation_provenance_refresh_requires_no_worker(self):
        packet = {"identity": {"Plugin package / version": "ai-engineering-workflows / refreshed",
                              "Framework commit / status": "new-revision / Clean",
                              "Playbook / version": "playbooks/techops_issue_remediation.md / 0.5.3"},
                  "handoff": {"provenance": "old package", "implementation_plan": "implementation_plan.md"},
                  "worker_results": [{"Worker": "fix-design", "Outcome": "complete"}]}
        results = copy.deepcopy(packet["worker_results"])
        finalizer._normalize_packet(packet, {"runtime_closure": []})
        self.assertEqual(packet["handoff"]["provenance"],
                         "plugin ai-engineering-workflows refreshed; framework revision new-revision (clean); "
                         "playbook techops_issue_remediation 0.5.3.")
        self.assertEqual(packet["handoff"]["implementation_plan"], "implementation_plan.md")
        self.assertEqual(packet["worker_results"], results)

    def test_handoff_lists_each_artifact_destination_once(self):
        packet = {"identity": {"State": "blocked", "Engineering state": "unknown",
                              "Workflow outcome": "blocked", "Engineering outcome": "blocked"},
                  "runtime_closure": [], "finalization": {"Durable artifact root": "/tmp/run"},
                  "handoff": {"workflow_result": "Blocked", "implementation_plan": "Not created",
                              "established": [], "best_current_explanations": [],
                              "next_action": {"owner": "Coordinator", "action": "Recover", "complete_when": "Validated"},
                              "artifacts": ["[Repository integration](repository_integration.md)",
                                            "/tmp/run/repository_integration.md", "work_record.md"],
                              "execution": "planning", "provenance": "current package"}}
        response = finalizer.render_handoff(packet)
        self.assertEqual(response.count(f"({Path('/tmp/run/repository_integration.md').resolve()})"), 1)
        self.assertIn("[Repository integration]", response)
        self.assertIn(f"[work_record.md]({Path('/tmp/run/work_record.md').resolve()})", response)
        packet["handoff"]["implementation_plan"] = "implementation_plan.md (Draft; unapproved)"
        response = finalizer.render_handoff(packet)
        self.assertIn(f"- Implementation plan: [implementation_plan.md]({Path('/tmp/run/implementation_plan.md').resolve()}) "
                      "(Draft; unapproved)", response)

    def test_handoff_uses_curated_risk_summary_and_preserves_legacy_fallback(self):
        packet = {
            "identity": {"State": "ready_for_implementation", "Engineering state": "designed",
                         "Workflow outcome": "completed", "Engineering outcome": "plan_only"},
            "runtime_closure": [], "finalization": {"Durable artifact root": "/tmp/run"},
            "handoff": {"workflow_result": "Current evidence supports a conditional plan.",
                        "implementation_plan": "Not created", "established": [],
                        "best_current_explanations": [],
                        "next_action": {"owner": "Implementer", "action": "Reproduce both save paths",
                                        "complete_when": "Fresh readback identifies the failure boundary"},
                        "artifacts": [], "execution": "Planning only", "provenance": "current package"},
            "worker_results": [
                {"Worker": "issue-evidence", "Outcome": "complete",
                 "Uncertainties / blockers": "No runtime reproduction or backend readback evidence; reported save sequence unknown."},
                {"Worker": "failure-path", "Outcome": "complete",
                 "Uncertainties / blockers": "Backend readback and save sequence remain unverified."},
                {"Worker": "handoff", "Outcome": "complete",
                 "Uncertainties / blockers": "The reported save sequence and backend readback remain unverified."},
            ],
        }
        response = finalizer.render_handoff(packet)
        self.assertIn("Risk: The reported save sequence and backend readback remain unverified.", response)
        self.assertNotIn("No runtime reproduction or backend readback evidence", response)
        legacy_packet = copy.deepcopy(packet)
        legacy_packet["worker_results"] = legacy_packet["worker_results"][:-1]
        legacy_response = finalizer.render_handoff(legacy_packet)
        self.assertIn("Risk: No runtime reproduction or backend readback evidence; reported save sequence unknown.",
                      legacy_response)

    def test_targeted_terminal_reads_cover_omitted_workers(self):
        observations = [{
            "Provider handle": f"/root/{worker}", "Provider status": "completed",
            "Last dispatch at": "2026-10-07T23:40:00Z", "Observed at": "2026-10-07T23:53:10Z",
            "Status source": "read_thread", "Thread ID": f"00000000-0000-0000-0000-{index:012d}",
            "Latest turn started at": "2026-10-07T23:40:01Z", "Latest turn status": "completed",
            "Thread status": "notLoaded",
        } for index, worker in enumerate(("evidence", "failure", "integration", "design", "handoff"))]
        handles = [row["Provider handle"] for row in observations]
        self.assertEqual(runtime.terminal_observation_errors(observations, handles), [])
        self.assertTrue(runtime.terminal_observation_errors(observations[2:], handles))
        stale = copy.deepcopy(observations)
        stale[0]["Last dispatch at"] = "2026-10-07T23:54:00Z"
        self.assertTrue(runtime.terminal_observation_errors(stale, handles))
        running = copy.deepcopy(observations)
        running[0]["Provider status"] = "running"
        self.assertTrue(runtime.terminal_observation_errors(running, handles))
        unavailable = copy.deepcopy(observations)
        unavailable[0]["Status source"] = "historical completion"
        self.assertTrue(runtime.terminal_observation_errors(unavailable, handles))
        historical = copy.deepcopy(observations)
        historical[0]["Latest turn started at"] = "2026-10-07T23:39:00Z"
        self.assertTrue(runtime.terminal_observation_errors(historical, handles))
        queued = copy.deepcopy(observations)
        queued[0]["Thread status"] = "inProgress"
        self.assertTrue(runtime.terminal_observation_errors(queued, handles))
        precise = copy.deepcopy(observations)
        precise[0]["Last dispatch at"] = "2026-10-07T23:40:01.900Z"
        self.assertEqual(runtime.terminal_observation_errors(precise, handles), [])

    def test_techops_stager_rejects_conflicting_disposition(self):
        from scripts import stage_documenter_packet as stager
        from scripts import runtime_checks
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packet = {"identity": {"Lifecycle": "planning", "Playbook / version": "techops_issue_remediation.md / 0.5.33",
                                   "Run ID": "run-1", "Requested profile": "standard",
                                   "Prompt template / revision / conformance": "template / 0.5.33 / pending"},
                      "planning_disposition": {"plan_readiness": "awaiting_input", "implementation_plan_action": "omit"}}
            path = root / "finalization_packet.json"
            path.write_text(json.dumps(packet))
            (root / "role_bindings.json").write_text(json.dumps({"playbook": "techops_issue_remediation", "run_id": "run-1"}))
            with patch.object(runtime_checks, "prepared_package_errors", return_value=[]):
                with self.assertRaisesRegex(ValueError, "techops_planning_disposition_state_mismatch"):
                    stager.stage(path, coordinator_model_effort="test", prompt_conformance="pass", state="ready_for_implementation")
            self.assertEqual(json.loads(path.read_text()), packet)

    def test_ready_plan_must_pass_remediation_entry_contract(self):
        from review_evidence import PLAN_FIXTURE
        packet = {"identity": {"Playbook / version": "playbooks/techops_issue_remediation.md / 0.5.33",
                               "Lifecycle": "planning", "State": "ready_for_implementation"},
                  "planning_disposition": {"plan_readiness": "ready_for_implementation", "implementation_plan_action": "create"},
                  "worker_results": [], "evidence": []}
        with tempfile.TemporaryDirectory() as directory, patch.object(
                planning_contracts, "_worker_runtime_audit_errors", return_value=[]):
            root = Path(directory)
            plan = root / "implementation_plan.md"
            plan.write_text(PLAN_FIXTURE)
            valid = planning_contracts._techops_planning_contract_errors(packet, root / "packet.json")
            plan.write_text(PLAN_FIXTURE.replace("# Behavior Applicability", "## Behavior Applicability"))
            invalid = planning_contracts._techops_planning_contract_errors(packet, root / "packet.json")
            self.assertNotIn("requires exactly one # Behavior Applicability", valid)
            self.assertIn("requires exactly one # Behavior Applicability", invalid)
            plan.unlink()
            self.assertIn("techops_implementation_plan_required",
                          planning_contracts._techops_planning_contract_errors(packet, root / "packet.json"))
            self.assertNotIn("techops_implementation_plan_required",
                             planning_contracts._techops_planning_contract_errors(packet, root / "packet.json", pre_handoff=True))

    def test_techops_remediation_handoff_requires_conformance_link(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            record = {"run_id": "run-1", "plan_sha256": "a" * 64, "files": [{"path": "a.py",
                "plan_step": "Step 1", "reuse": "Existing function", "change": "Repair", "validation": "Focused test"}]}
            conformance = root / "implementation_conformance.json"
            conformance.write_text(json.dumps(record))
            packet = {"identity": {"Playbook / version": "techops_issue_remediation.md / 0.5.33",
                      "Lifecycle": "remediation", "Run ID": "run-1", "Engineering outcome": "solved"},
                      "reentry": {"Prior run ID": "prior", "Approval reference": "Approved",
                                  "Approved plan": str(root / "implementation_plan.md"), "Approved plan SHA256": "a" * 64},
                      "durable_artifacts": [], "handoff": {"artifacts": []}, "evidence": []}
            with patch.object(planning_contracts, "_feature_delivery_remediation_errors", side_effect=lambda *a, **k: []), \
                 patch.object(planning_contracts, "techops_check_errors", return_value=[]):
                errors = planning_contracts._techops_remediation_contract_errors(packet, root / "packet.json")
                self.assertIn("techops_conformance_handoff_reference_required", errors)
                packet["durable_artifacts"].append({"Path": str(conformance)})
                packet["handoff"]["artifacts"].append(str(conformance))
                self.assertEqual(planning_contracts._techops_remediation_contract_errors(packet, root / "packet.json"), [])
                target = root / "other.json"
                conformance.rename(target)
                conformance.symlink_to(target)
                self.assertIn("techops_conformance_record_required",
                              planning_contracts._techops_remediation_contract_errors(packet, root / "packet.json"))

    def test_techops_conformance_requires_current_run_and_complete_file_mapping(self):
        from scripts.runtime_checks import techops_conformance_errors
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "implementation_conformance.json"
            self.assertIn("techops_conformance_record_required", techops_conformance_errors(path, "run-1", "hash"))
            record = {"run_id": "run-1", "plan_sha256": "hash", "files": [{"path": "a.py",
                "plan_step": "Step 1", "reuse": "Existing function", "change": "Repair", "validation": "Focused test"}]}
            path.write_text(json.dumps(record))
            self.assertEqual(techops_conformance_errors(path, "run-1", "hash"), [])
            self.assertIn("techops_conformance_identity_mismatch", techops_conformance_errors(path, "run-2", "hash"))
            record["files"][0]["validation"] = ""
            path.write_text(json.dumps(record))
            self.assertIn("techops_conformance_file_mapping_incomplete", techops_conformance_errors(path, "run-1", "hash"))

    def test_techops_planning_test_permission_respects_user_restrictions(self):
        from scripts import runtime_checks
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            final = root / "finalization_packet.json"
            final.write_text(json.dumps({"identity": {"Lifecycle": "planning"}}))
            packet = {"agent": "dependency_analyst", "lifecycle": "planning", "finalization_packet": str(final),
                      "worker_contract": {"contract": "/package/playbooks/techops_issue_remediation.md"},
                      "run_input_manifest": {"inputs": []}}
            trace = {"spawn": {"dispatch_file": str(root / "dispatch")}, "tool_trace": [
                {"tool": "exec_command", "arguments": {"cmd": "bazel test //service:focused"}}]}
            def check():
                with patch.object(runtime_checks, "_verified_dispatch_content", return_value="prefix\n" + json.dumps(packet) + "\n"):
                    return runtime_checks.planning_permission_errors(trace)
            self.assertEqual(check(), [])
            for command in ("bazel test //...", "go test ./...", "python3 -m unittest discover", "pytest",
                            "python3 -m pytest -q"):
                trace["tool_trace"][0]["arguments"]["cmd"] = command
                self.assertIn("planning_diagnostic_test_not_focused", check())
            packet["run_input_manifest"]["inputs"].append({"Authority": "User", "Classification": "execution authorization",
                                                           "Status": "Approved", "Authorized operations": ["test_run"]})
            self.assertEqual(check(), [])
            packet["run_input_manifest"]["inputs"] = []
            trace["tool_trace"][0]["arguments"]["cmd"] = "bazel build //service:binary"
            self.assertIn("planning_operation_not_authorized:build_run", check())
            trace["tool_trace"][0]["arguments"]["cmd"] = "bazel test //service:focused"
            packet["run_input_manifest"]["inputs"].append({"Authority": "User", "Classification": "execution restriction",
                                                           "Denied operations": ["test_run"]})
            self.assertIn("planning_operation_not_authorized:test_run", check())
            packet["agent"] = "current_state_investigator"
            packet["run_input_manifest"]["inputs"] = []
            self.assertIn("planning_operation_not_authorized:test_run", check())

    def test_integration_decision_requires_reason_and_current_evidence(self):
        from scripts.runtime_checks import techops_integration_decision_errors
        record = {"decision": "required", "reason": "Report crosses a service boundary", "evidence_refs": "E-ISS-1"}
        self.assertEqual(techops_integration_decision_errors(record, {"E-ISS-1"}), [])
        self.assertEqual(techops_integration_decision_errors({**record, "decision": "not_required"}, {"E-ISS-1"}), [])
        self.assertIn("techops_integration_decision_invalid",
                      techops_integration_decision_errors({**record, "decision": "maybe"}, {"E-ISS-1"}))
        self.assertIn("techops_integration_reason_required",
                      techops_integration_decision_errors({**record, "reason": ""}, {"E-ISS-1"}))
        self.assertIn("techops_integration_evidence_required", techops_integration_decision_errors(record, set()))

    def test_standard_required_integration_must_complete(self):
        packet = {"identity": {"Playbook / version": "techops_issue_remediation.md / 0.5.33", "Lifecycle": "planning"},
                  "worker_results": [{"Worker": "issue-evidence", "Outcome": "complete"},
                                     {"Worker": "fix-design", "Outcome": "complete"}],
                  "evidence": [{"Evidence ID": "E-ISS-1"}],
                  "integration_decision": {"decision": "required", "reason": "Service boundary",
                                           "evidence_refs": "E-ISS-1"}}
        with patch.object(planning_contracts, "_worker_runtime_audit_errors", return_value=[]):
            errors = planning_contracts._techops_planning_contract_errors(packet, Path("/tmp/packet.json"), pre_handoff=True)
            self.assertIn("techops_required_integration_incomplete", errors)
            packet["integration_decision"]["decision"] = "not_required"
            errors = planning_contracts._techops_planning_contract_errors(packet, Path("/tmp/packet.json"), pre_handoff=True)
            self.assertNotIn("techops_required_integration_incomplete", errors)

    def test_fix_design_waits_for_required_integration(self):
        packet = {"identity": {"Requested profile": "standard"},
                  "worker_results": [{"Worker": "issue-evidence", "Outcome": "complete"},
                                     {"Worker": "failure-path", "Outcome": "complete"}],
                  "evidence": [{"Evidence ID": "E-ISS-1"}],
                  "integration_decision": {"decision": "required", "reason": "Service boundary",
                                           "evidence_refs": "E-ISS-1"}}
        self.assertIn("techops_design_prerequisites_incomplete", planning_contracts.techops_design_gate_errors(packet))
        packet["worker_results"].append({"Worker": "repository-integration", "Outcome": "complete"})
        self.assertEqual(planning_contracts.techops_design_gate_errors(packet), [])
        packet["worker_results"].pop()
        packet["integration_decision"]["decision"] = "not_required"
        self.assertEqual(planning_contracts.techops_design_gate_errors(packet), [])
        packet["identity"]["Requested profile"] = "deep"
        self.assertIn("techops_design_prerequisites_incomplete", planning_contracts.techops_design_gate_errors(packet))

    def test_fix_design_activation_rejects_missing_required_integration(self):
        with tempfile.TemporaryDirectory() as directory:
            run = prepare.prepare_run(Path(directory), "DESIGN-GATE", "techops_issue_remediation", None, False)
            packet_path = Path(run["finalization_packet"])
            packet = json.loads(packet_path.read_text())
            packet["worker_results"] = [{"Worker": "issue-evidence", "Outcome": "complete"},
                                        {"Worker": "failure-path", "Outcome": "complete"}]
            packet["evidence"] = [{"Evidence ID": "E-ISS-1"}]
            packet["integration_decision"] = {"decision": "required", "reason": "Service boundary",
                                              "evidence_refs": "E-ISS-1"}
            packet_path.write_text(json.dumps(packet))
            bundle = run["activation_packet_bundle"]
            errors = runtime.activation_packet_errors(Path(bundle["path"]), "solution_architect", bundle["sha256"])
            self.assertIn("techops_design_prerequisites_incomplete", errors)

    def test_reproduction_record_distinguishes_results_and_requires_evidence(self):
        from scripts.runtime_checks import techops_reproduction_errors
        record = {"status": "unable_to_attempt", "expected": "Saved values persist",
                  "observed": "No runtime check performed", "check": "Inspected current save path",
                  "environment": "Local checkout", "revision": "abc1234", "limitation": "Fixture unavailable",
                  "evidence_refs": "E-FP-1"}
        self.assertEqual(techops_reproduction_errors(record, {"E-FP-1"}), [])
        for status in ("reproduced", "verified_by_evidence", "not_reproduced"):
            self.assertEqual(techops_reproduction_errors({**record, "status": status}, {"E-FP-1"}), [])
        self.assertIn("techops_reproduction_status_invalid",
                      techops_reproduction_errors({**record, "status": "passed"}, {"E-FP-1"}))
        self.assertIn("techops_reproduction_evidence_required",
                      techops_reproduction_errors(record, {"E-FP-2"}))
        self.assertIn("techops_reproduction_field_required:check",
                      techops_reproduction_errors({**record, "check": ""}, {"E-FP-1"}))

    def test_failure_path_result_requires_reproduction_record(self):
        from scripts.merge_techops_result import validated_result
        template = json.loads((prepare.ROOT / "templates/finalization_packet.json").read_text())
        packet = copy.deepcopy(template)
        packet["identity"].update({"Run ID": "run-1", "Lifecycle": "planning"})
        for name in ("worker_results", "evidence", "claims", "decisions", "actions"):
            packet[name] = []
        result = {"run_id": "run-1", "worker_result": {
            **dict.fromkeys(template["worker_results"][0], "Evidence"),
            "Worker": "failure-path", "Outcome": "complete"},
            "evidence": [{**dict.fromkeys(template["evidence"][0], "Evidence"), "Evidence ID": "E-FP-1"}]}
        bindings = {"playbook": "techops_issue_remediation", "lifecycle": "planning",
                    "worker_contracts": {"dependency_analyst": {}}}
        with self.assertRaisesRegex(ValueError, "techops_reproduction_record_required"):
            validated_result(packet, result, bindings, "dependency_analyst")
        result["reproduction"] = {"status": "unable_to_attempt", "expected": "Saved values persist",
            "observed": "No runtime check performed", "check": "Inspected current save path",
            "environment": "Local checkout", "revision": "abc1234", "limitation": "Fixture unavailable",
            "evidence_refs": "E-FP-1"}
        accepted = validated_result(packet, result, bindings, "dependency_analyst")
        self.assertEqual(accepted["reproduction"], result["reproduction"])
        from scripts.merge_techops_result import merged_result_errors
        from scripts.work_record_format import _mapping_table
        from scripts.validation.markdown import markdown_table
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "failure_path_result.json"
            source.write_text(json.dumps(result))
            bindings["worker_contracts"]["dependency_analyst"]["result"] = str(source)
            table = "# TechOps Reproduction\n\n" + _mapping_table(accepted["reproduction"])
            rows = markdown_table(table, "# TechOps Reproduction")
            accepted["reproduction"] = {row["Field"]: row["Value"] for row in rows}
            self.assertNotIn("worker_owned_record_changed:failure-path:reproduction",
                             merged_result_errors(accepted, bindings, root, table_projection=True))
            accepted["reproduction"]["status"] = "reproduced"
            self.assertIn("worker_owned_record_changed:failure-path:reproduction",
                          merged_result_errors(accepted, bindings, root, table_projection=True))

    def test_planning_checks_require_supported_evidence(self):
        checks = [{"Check": name, "Status": "not_applicable" if name == "history_reconciliation" else "passed", "Evidence refs": "E-001",
                   "Detail": "Current-run owning worker evidence"} for name in runtime.TECHOPS_CHECKS]
        self.assertEqual(runtime.techops_check_errors(checks, {"E-001"}), [])
        self.assertTrue(runtime.techops_check_errors(checks[:-1], {"E-001"}))
        checks[0]["Evidence refs"] = "E-999"
        self.assertTrue(runtime.techops_check_errors(checks, {"E-001"}))

    def test_missing_trace_retrieval_is_not_an_audit(self):
        packet = {
            "identity": {"Playbook / version": "playbooks/techops_issue_remediation.md / 0.5.3",
                         "Lifecycle": "planning"},
            "worker_results": [{"Worker": "fix-design", "Outcome": "complete"}],
            "evidence": [{"Evidence ID": "E-001"}],
            "techops_checks": [{"Check": name, "Status": "not_applicable" if name == "history_reconciliation" else "passed", "Evidence refs": "E-001",
                                "Detail": "Owning worker evidence"} for name in runtime.TECHOPS_CHECKS],
            "runtime_audits": [{"Worker": "fix-design", "Provider handle": "/root/design",
                                "Provider status": "completed", "Last dispatch at": "2026-10-07T23:40:00Z",
                                "Observed at": "2026-10-07T23:53:10Z", "Status source": "list_agents"}],
        }
        errors = finalizer._techops_planning_contract_errors(packet, Path("/tmp/finalization_packet.json"))
        self.assertIn("worker_trace_retrieval_evidence_required:fix-design", errors)
        packet["runtime_audits"][0]["Trace retrieval"] = "unavailable: read_thread returned permission_denied"
        packet["worker_results"][0]["Uncertainties / blockers"] = "context-unverified"
        self.assertEqual(finalizer._techops_planning_contract_errors(packet, Path("/tmp/packet.json")), [])

        with tempfile.TemporaryDirectory(prefix="techops-audit-") as directory:
            packet_path = Path(directory) / "packet.json"
            trace_path = packet_path.with_name("trace.json")
            packet["runtime_audits"][0]["Trace path"] = str(trace_path)
            trace = {"spawn": {"activation_packet_delivered": True}, "tool_trace": [],
                     "last_dispatch_at": "2026-10-07T23:40:00Z"}
            trace_path.write_text(json.dumps(trace))
            self.assertIn("worker_fan_in_guard_receipt_required:fix-design",
                          finalizer._techops_planning_contract_errors(packet, packet_path))
            trace["events"] = [{"action": "fan_in", "provider_status": "completed"}]
            trace["tool_trace"] = [{"tool": "exec_command", "arguments": {"cmd": "cat /tmp/.codex/memories/MEMORY.md"}}]
            trace_path.write_text(json.dumps(trace))
            self.assertTrue(any("forbidden_context_reference" in error
                                for error in finalizer._techops_planning_contract_errors(packet, packet_path)))
            trace["tool_trace"] = []
            trace["last_dispatch_at"] = "2026-10-07T23:39:00Z"
            trace_path.write_text(json.dumps(trace))
            self.assertIn("worker_trace_stale:fix-design",
                          finalizer._techops_planning_contract_errors(packet, packet_path))

    def test_blocked_publication_has_one_schema_status(self):
        packet = {
            "identity": {"State": "blocked", "Finalization schema": "Pending"},
            "finalization": {"Finalization schema": "Pending"}, "durable_artifacts": [],
            "handoff": {"execution": "no source changes; awaiting Coordinator packet validation and packaged finalization; runtime not released"},
        }
        finalizer._reconcile_runtime_state(packet, [{"Runtime status": "Blocked"}])
        self.assertNotIn("Finalization schema", packet["identity"])
        self.assertEqual(packet["finalization"]["Finalization schema"], "Passed for blocked work record")
        self.assertNotIn("awaiting Coordinator", packet["handoff"]["execution"])
        self.assertIn("runtime not released", packet["handoff"]["execution"])

    def test_techops_summary_is_not_a_readiness_token(self):
        packet = {"identity": {"Playbook / version": "playbooks/techops_issue_remediation.md / 0.5.33",
                               "State": "awaiting_input", "Workflow outcome": "completed",
                               "Engineering outcome": "partially_solved"},
                  "handoff": {"workflow_result": "The source stages edits; a draft-only persistence plan is proposed; production is unverified.",
                              "implementation_plan": "/tmp/implementation_plan.md", "execution": "planning only",
                              "provenance": "techops_issue_remediation", "established": ["The callback stages edits."],
                              "artifacts": ["/tmp/plan.md"],
                              "next_action": {"owner": "Coordinator", "action": "Reconcile runtime proof",
                                              "complete_when": "Fresh worker observations are available"}}}
        finalizer._validate_handoff(packet, check_provenance=False)
        for token in ("ready_for_implementation", "Ready for implementation", "blocked", "designed", "plan_only",
                      "Partially answered", "Answered"):
            with self.subTest(token=token):
                packet["handoff"]["workflow_result"] = token
                with self.assertRaisesRegex(ValueError, "plain-language work summary"):
                    finalizer._validate_handoff(packet, check_provenance=False)
        packet["identity"]["Playbook / version"] = "playbooks/feature_delivery.md / 0.5.33"
        finalizer._validate_handoff(packet, check_provenance=False)

    def test_terminal_failure_preserves_work_summary_without_publishing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packet_path = root / "finalization_packet.json"
            packet = {"identity": {"Engineering state": "designed"}, "handoff": {
                "workflow_result": "Source stages metadata; a draft-save plan is proposed; production remains unverified.",
                "implementation_plan": str(root / "implementation_plan.md"),
                "established": ["The update path carries name, description and subject."],
                "best_current_explanations": [{"explanation": "Dialog update was staged", "confidence": "medium",
                                               "reason": "Source trace only"}],
                "next_action": {"owner": "Engineering", "action": "Confirm Save sequence", "complete_when": "Fresh read agrees"},
                "artifacts": [str(root / "fix_design.md")], "execution": "No source changes or tests",
                "provenance": "fixture; not independently audited"}}
            packet_path.write_text(json.dumps(packet))
            record = root / "work_record.md"
            record.write_text("prepared skeleton\n")
            before = packet_path.read_bytes()
            receipt = root / "finalization_failure.json"
            receipt.write_text(json.dumps({"status": "failed", "errors": ["terminal_observation_stale"]}))
            output = io.StringIO()
            arguments = ["finalizer", "--packet", str(packet_path), "--closure", str(root / "runtime_closure.json"),
                         "--record", str(record)]
            with patch.object(sys, "argv", arguments), patch.object(finalizer, "finalize", side_effect=ValueError("terminal_observation_stale")), redirect_stdout(output):
                self.assertEqual(finalizer.main(), 2)
            text = output.getvalue()
            for label in ("Workflow-framework validation: failed", "Workflow result:", "Engineering state:",
                          "What we established:", "Best current explanations:", "Next action:", "Complete when:",
                          "Artifacts:", "Execution:", "Provenance:"):
                self.assertIn(label, text)
            for detail in ("name, description and subject", "Dialog update was staged", "confidence: medium",
                           "Confirm Save sequence", "terminal_observation_stale", str(receipt)):
                self.assertIn(detail, text)
            self.assertNotIn("Workflow-framework validation: passed", text)
            self.assertNotIn("Tip: Developer Workflows", text)
            self.assertIn("unverified", text)
            self.assertEqual(record.read_text(), "prepared skeleton\n")
            self.assertEqual(packet_path.read_bytes(), before)
            self.assertEqual((packet_path.parent / "handoff_failure.md").read_text().strip(),
                             text[text.index("Workflow-framework validation: failed"):].strip())
            for flag in ("--check-packet", "--pre-release"):
                with patch.object(sys, "argv", arguments + [flag]), patch.object(finalizer, "finalize", side_effect=ValueError("failure")), redirect_stdout(io.StringIO()) as feedback:
                    self.assertEqual(finalizer.main(), 2)
                self.assertNotIn("What we established:", feedback.getvalue())
            packet["handoff"]["workflow_result"] = "Ready for implementation"
            packet_path.write_text(json.dumps(packet))
            failed_summary = finalizer.failure_handoff(packet_path, "invalid result token")
            self.assertIn("Provisional work summary: The update path", failed_summary)
            self.assertNotIn("Provisional work summary: Ready for implementation", failed_summary)
            packet_path.write_text("[]")
            self.assertIn("No accepted worker result", finalizer.failure_handoff(packet_path, "invalid packet"))
            packet["handoff"]["artifacts"].append("invalid\0path")
            packet_path.write_text(json.dumps(packet))
            self.assertIn("Unrenderable recorded artifact", finalizer.failure_handoff(packet_path, "invalid artifact"))
            packet["handoff"]["artifacts"].pop()
            packet_path.write_text("not JSON")
            self.assertIn("validation: failed", finalizer.failure_handoff(packet_path, "invalid JSON"))
            # Exercise the real CLI failure route, without mocked publication.
            packet_path.write_text(json.dumps(packet))
            result = subprocess.run([sys.executable, str(finalizer.ROOT / "scripts/finalize_work_record.py"),
                                     *arguments[1:]], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn("What we established:", result.stdout)
            self.assertEqual(record.read_text(), "prepared skeleton\n")

    def test_followup_requires_matching_fresh_audit_and_closure(self):
        audit = {"Worker": "handoff", "Provider handle": "/root/handoff", "Provider status": "completed",
                 "Last dispatch at": "2026-10-09T02:23:38Z", "Observed at": "2026-10-09T02:18:00Z",
                 "Status source": "list_agents", "Trace path": "",
                 "Trace retrieval": "unavailable: no provider thread UUID mapping"}
        packet = {"runtime_audits": [audit], "worker_results": [{"Worker": "handoff",
                  "Uncertainties / blockers": "context-unverified"}],
                  "terminal_observations": [{**audit, "Last dispatch at": "2026-10-09T02:19:39Z"}]}
        path = Path("/tmp/packet.json")
        errors = finalizer._worker_runtime_audit_errors(packet, path, {"handoff"})
        self.assertIn("terminal_closure_worker_audit_stale", errors)
        self.assertIn("terminal_observation_stale:/root/handoff", errors)
        audit["Observed at"] = "2026-10-09T02:25:00Z"
        packet["terminal_observations"] = [dict(audit)]
        self.assertEqual(finalizer._worker_runtime_audit_errors(packet, path, {"handoff"}), [])
        # Thread tools require an actual UUID even when the collaboration handle is valid.
        audit.update({"Status source": "read_thread", "Thread ID": "/root/handoff"})
        self.assertIn("terminal_observation_thread_id_required:/root/handoff",
                      runtime.terminal_observation_errors([audit], ["/root/handoff"]))

    def test_techops_label(self):
        packet = {"identity": {"Playbook / version": "playbooks/techops_issue_remediation.md / 0.5.3"},
                  "playbook_selection": {"Primary goal": "Issue remediation"}}
        self.assertEqual(finalizer._blocked_snapshot_label(packet), "TechOps planning")


if __name__ == "__main__":
    unittest.main()
