"""Regressions for evidence preservation, recovery identity and runtime auditing."""

import hashlib
import json
import subprocess
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import finalize_work_record as finalizer
from scripts import prepare_run as prepare
from scripts import run_preflight as preflight
from scripts import validate_worker_runtime as runtime
from scripts.merge_techops_result import merge_result
from scripts.worker_runtime_evidence import read_runtime_events


class FrameworkCorrections(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.repository = Path(temporary.name)
        self.inputs = self.repository / "inputs.json"
        self.inputs.write_text(json.dumps({"inputs": [{
            "Input ID": "IN-001", "Input or artifact": "Jira ITEM-1",
            "Source or path": "Current request", "Authority": "User", "Status": "Verified",
        }]}))
        self.run = prepare.prepare_run(self.repository, "ITEM-1", "feature_delivery", None, False,
                                       input_manifest=self.inputs)
        self.root = Path(self.run["artifact_root"])
        self.packet_path = Path(self.run["finalization_packet"])
        self.packet = json.loads(self.packet_path.read_text())
        template = json.loads(finalizer.PACKET_TEMPLATE.read_text())
        self.evidence = {**dict.fromkeys(template["evidence"][0], "Observed"), "Evidence ID": "E-FC-001"}
        self.result = {"run_id": self.packet["identity"]["Run ID"], "worker_result": {
            **dict.fromkeys(template["worker_results"][0], "Recorded"),
            "Worker": "feature-context", "Outcome": "complete"}, "evidence": [self.evidence]}
        self.source = Path(self.run["worker_contracts"]["current_state_investigator"]["result"])

    def merge(self):
        self.source.write_text(json.dumps(self.result))
        merge_result(self.packet_path, "current_state_investigator")

    def test_failure_without_ledger_retains_concrete_closure_blocker(self):
        self.assertFalse((self.root / "runtime_dispatches.json").exists())
        self.assertEqual(finalizer.collect_failure_closure(self.packet_path), "unverified")
        closure = json.loads((self.root / "runtime_closure.json").read_text())["runtime_closure"][0]
        self.assertEqual(closure["Runtime status"], "Blocked")
        self.assertIn("runtime_dispatch_ledger_missing", closure["Closure evidence or blocker"])

    def test_lifecycle_conflict_cannot_change_or_reprepare_an_existing_stage(self):
        before = self.packet_path.read_bytes()
        bindings = self.root / "role_bindings.json"
        binding_bytes = bindings.read_bytes()
        with self.assertRaisesRegex(ValueError, "lifecycle_conflict:expected=planning;received=remediation"):
            prepare.prepare_run(self.repository, "NEW-1", "techops_issue_remediation", None, False,
                                input_manifest=self.inputs, lifecycle="remediation")
        self.assertFalse((self.repository / ".thoughts" / "NEW-1").exists())
        changed = json.loads(before)
        changed["identity"]["Lifecycle"] = "remediation"
        self.packet_path.write_text(json.dumps(changed))
        unaccepted = self.packet_path.read_bytes()
        with self.assertRaisesRegex(ValueError, "prepared_lifecycle_mismatch"):
            prepare.prepare_run(self.repository, "ITEM-1", "feature_delivery", None, True,
                                input_manifest=self.inputs, lifecycle="planning")
        self.assertEqual(self.packet_path.read_bytes(), unaccepted)
        self.assertEqual(bindings.read_bytes(), binding_bytes)
        legacy = json.loads(binding_bytes)
        legacy.pop("framework_package")
        bindings.write_text(json.dumps(legacy))
        self.assertTrue(any(error.startswith("prepared_lifecycle_mismatch")
                            for error in runtime.prepared_package_errors(self.root)))
        bindings.write_bytes(binding_bytes)
        self.packet_path.write_bytes(before)
        run = prepare.prepare_run(self.repository, "ITEM-1", "feature_delivery", None, True,
                                  input_manifest=self.inputs, lifecycle="planning")
        self.assertEqual(run["lifecycle"], "planning")
        self.assertEqual(json.loads(self.packet_path.read_text())["identity"]["Run ID"], self.run["run_id"])

    def test_profile_is_prepared_before_workers_and_cannot_drift_on_continuation(self):
        self.assertEqual(self.packet["identity"]["Requested profile"], "standard")
        self.assertEqual(self.packet["identity"]["Executed profile"], "")
        run = prepare.prepare_run(self.repository, "DEEP-1", "techops_issue_remediation", None, False,
                                  input_manifest=self.inputs, execution_profile="deep")
        bundle = json.loads(Path(run["activation_packet_bundle"]["path"]).read_text())
        self.assertTrue(all(packet["execution_profile"] == "deep" for packet in bundle["packets"].values()))
        before = self.packet_path.read_bytes()
        with self.assertRaisesRegex(ValueError, "execution_profile_conflict"):
            prepare.prepare_run(self.repository, "ITEM-1", "feature_delivery", None, True,
                                input_manifest=self.inputs, execution_profile="deep")
        self.assertEqual(self.packet_path.read_bytes(), before)
        self.packet["identity"]["Requested profile"] = "deep"
        self.packet_path.write_text(json.dumps(self.packet))
        self.assertTrue(any(error.startswith("prepared_execution_profile_mismatch")
                            for error in runtime.prepared_package_errors(self.root)))
        with self.assertRaisesRegex(ValueError, "prepared_execution_profile_mismatch"):
            prepare.prepare_run(self.repository, "ITEM-1", "feature_delivery", None, True,
                                input_manifest=self.inputs)

    def test_pre_handoff_defers_documenter_metadata_but_finalization_requires_it(self):
        from scripts.planning_contracts import _feature_delivery_packet_contract_errors
        self.packet["identity"].update({"State": "awaiting_input", "Workflow outcome": "completed",
                                        "Engineering outcome": "partially_solved"})
        before = _feature_delivery_packet_contract_errors(self.packet, pre_handoff=True)
        final = _feature_delivery_packet_contract_errors(self.packet)
        self.assertFalse(any("recovered work-item title" in error or "execution-ledger rows" in error
                             or "Profile status executed" in error for error in before))
        self.assertTrue(any("terminal results" in error for error in before))
        self.assertTrue(any("recovered work-item title" in error for error in final))
        self.assertTrue(any("profiles must be standard or deep" in error for error in final))
        self.packet["identity"].update({"Activated profile": "standard", "Executed profile": "standard"})
        final = _feature_delivery_packet_contract_errors(self.packet)
        self.assertTrue(any("execution-ledger rows" in error for error in final))
        self.assertTrue(any("Profile status executed" in error for error in final))

    def test_empty_result_preserves_evidence_and_conflicts_do_not_mutate_packet(self):
        self.merge()
        saved = self.packet_path.read_bytes()
        self.result["evidence"] = []
        self.merge()
        self.assertEqual(saved, self.packet_path.read_bytes())
        self.result["evidence"] = [{**self.evidence, "Source": "Changed"}]
        with self.assertRaisesRegex(ValueError, "row_conflict"):
            self.merge()
        self.assertEqual(saved, self.packet_path.read_bytes())

    def test_feature_finalization_rejects_coordinator_rewrites_of_accepted_analysis(self):
        from scripts.merge_techops_result import merged_result_errors
        self.merge()
        packet = json.loads(self.packet_path.read_text())
        bindings = json.loads((self.root / "role_bindings.json").read_text())
        self.assertEqual(merged_result_errors(packet, bindings, self.root), [])
        packet["evidence"][0]["Source"] = "Coordinator rewrite"
        self.assertIn("worker_owned_record_changed:feature-context:evidence:E-FC-001",
                      merged_result_errors(packet, bindings, self.root))
        packet["identity"].update({"Lifecycle": "planning", "State": "awaiting_input",
            "Requested profile": "standard", "Activated profile": "standard", "Executed profile": "standard"})
        packet["finalization"]["Durable artifact root"] = str(self.root)
        self.assertIn("worker_owned_record_changed:feature-context:evidence:E-FC-001",
                      finalizer._feature_delivery_packet_contract_errors(packet))

    def test_bad_types_and_dangling_references_fail_before_mutation(self):
        saved = self.packet_path.read_bytes()
        for value, reason in ((["E-FC-001"], "schema_invalid"), ("E-FC-404", "reference_unresolved")):
            self.result["worker_result"]["Evidence / claim refs"] = value
            with self.assertRaisesRegex(ValueError, reason):
                self.merge()
            self.assertEqual(saved, self.packet_path.read_bytes())
        self.result["worker_result"]["Evidence / claim refs"] = "E-FC-001"
        self.merge()
        self.assertEqual(finalizer._shape_errors(json.loads(self.packet_path.read_text()),
                                                json.loads(finalizer.PACKET_TEMPLATE.read_text()), "packet"), [])

    def test_history_contract_delivers_structured_fields_and_distinct_proof(self):
        run = prepare.prepare_run(self.repository, "HISTORY-1", "techops_issue_remediation", None, False,
                                  input_manifest=self.inputs)
        instructions = run["worker_contracts"]["solution_architect"]["instructions"]
        self.assertIn("requires separate JSON keys Commit, Patch evidence refs, Work item and Work item evidence refs", instructions)
        self.assertIn("not prose inside Detail", instructions)
        self.assertIn("must be distinct and included in Evidence refs", instructions)
        checks = [{"Check": name, "Status": "passed", "Evidence refs": "E-FP-1, E-FD-1", "Detail": "Observed"}
                  for name in runtime.TECHOPS_CHECKS]
        history = next(row for row in checks if row["Check"] == "history_reconciliation")
        history["Detail"] = "Commit abcdef012345; Patch evidence refs E-FP-1; Work item ITEM-2; Work item evidence refs E-FD-1"
        evidence = {"E-FP-1", "E-FD-1"}
        self.assertIn("techops_history_patch_and_work_item_required", runtime.techops_check_errors(checks, evidence))
        history.update({"Commit": "abcdef012345", "Patch evidence refs": "E-FP-1", "Work item": "ITEM-2",
                        "Work item evidence refs": "E-FD-1"})
        self.assertEqual(runtime.techops_check_errors(checks, evidence), [])
        history["Work item evidence refs"] = "E-FP-1"
        self.assertIn("techops_history_distinct_sources_required", runtime.techops_check_errors(checks, evidence))

    def test_semantic_errors_are_reported_together_without_writes(self):
        run = prepare.prepare_run(self.repository, "SEMANTIC-1", "techops_issue_remediation", None, False,
                                  input_manifest=self.inputs)
        contract = run["worker_contracts"]["solution_architect"]
        self.assertIn("Do not include Feature Delivery-only", contract["result_instructions"])
        packet = Path(run["finalization_packet"])
        result_path = Path(contract["result"])
        fields = json.loads(finalizer.PACKET_TEMPLATE.read_text())["worker_results"][0]
        result = {"run_id": json.loads(packet.read_text())["identity"]["Run ID"],
                  "worker_result": {**dict.fromkeys(fields, "Recorded"), "Worker": "fix-design", "Outcome": "complete"},
                  "evidence": [{**self.evidence, "Evidence ID": name} for name in ("E-FD-1", "E-FD-2")],
                  "plan_readiness": "awaiting_input", "implementation_plan_action": "omit",
                  "techops_checks": [{"Check": name, "Status": "passed", "Evidence refs": "E-FD-1, E-FD-2",
                                      "Detail": "Observed"} for name in runtime.TECHOPS_CHECKS]}
        result["worker_result"]["Evidence / claim refs"] = ["E-FD-1", "E-FD-2"]
        result_path.write_text(json.dumps(result))
        before = packet.read_bytes(), result_path.read_bytes()
        with self.assertRaises(ValueError) as caught:
            merge_result(packet, "solution_architect")
        self.assertIn("worker_result.Evidence / claim refs must be str", str(caught.exception))
        self.assertIn("feature_planning_disposition_invalid", str(caught.exception))
        self.assertIn("techops_history_patch_and_work_item_required", str(caught.exception))
        self.assertEqual((packet.read_bytes(), result_path.read_bytes()), before)
        result.pop("plan_readiness")
        result.pop("implementation_plan_action")
        result["worker_result"]["Evidence / claim refs"] = "E-FD-1, E-FD-2"
        history = next(row for row in result["techops_checks"] if row["Check"] == "history_reconciliation")
        history.update({"Commit": "abcdef012345", "Patch evidence refs": "E-FD-1", "Work item": "ITEM-2",
                        "Work item evidence refs": "E-FD-2"})
        result_path.write_text(json.dumps(result))
        merge_result(packet, "solution_architect")
        self.assertEqual(json.loads(packet.read_text())["techops_checks"], result["techops_checks"])
        accepted = packet.read_bytes()
        result.pop("techops_checks")
        result_path.write_text(json.dumps(result))
        with self.assertRaisesRegex(ValueError, "techops_planning_checks_required"):
            merge_result(packet, "solution_architect")
        self.assertEqual(packet.read_bytes(), accepted)
        result["worker_result"]["Outcome"] = "blocked"
        result_path.write_text(json.dumps(result))
        merge_result(packet, "solution_architect")
        self.assertEqual(json.loads(packet.read_text())["worker_results"][-1]["Outcome"], "blocked")

    def test_all_schema_errors_are_reported_before_the_single_correction(self):
        template = json.loads(finalizer.PACKET_TEMPLATE.read_text())
        for playbook in ("techops_issue_remediation", "feature_delivery"):
            with self.subTest(playbook=playbook), tempfile.TemporaryDirectory() as directory:
                run = prepare.prepare_run(Path(directory), "ITEM-ALL", playbook, None, False,
                                          input_manifest=self.inputs)
                contract = run["worker_contracts"]["current_state_investigator"]
                instructions = contract.get("result_instructions", contract.get("instructions", ""))
                worker = contract.get("worker_id", contract.get("worker"))
                self.assertIn(f"Its Worker value must be exactly {worker}.", instructions)
                self.assertIn("Every field value", instructions)
                self.assertIn("never an array", instructions)
                packet_path = Path(run["finalization_packet"])
                packet = json.loads(packet_path.read_text())
                namespace = contract["id_namespace"]
                evidence_id = f"E-{namespace}-001"
                result = {"run_id": packet["identity"]["Run ID"],
                          "worker_result": {**dict.fromkeys(template["worker_results"][0], "Observed"),
                              "Worker": contract.get("worker") or contract["worker_id"],
                              "Outcome": "complete", "Evidence / claim refs": [evidence_id]},
                          "evidence": [{**dict.fromkeys(template["evidence"][0], "Observed"),
                                        "Evidence ID": evidence_id}],
                          "claims": [{**dict.fromkeys(template["claims"][0], "Observed"),
                                      "Claim ID": f"CL-{namespace}-{i}", "Evidence refs": [evidence_id]}
                                     for i in range(4)]}
                result_path = Path(contract["result"])
                result_path.write_text(json.dumps(result))
                packet_before, result_before = packet_path.read_bytes(), result_path.read_bytes()
                with self.assertRaises(ValueError) as caught:
                    merge_result(packet_path, "current_state_investigator")
                message = str(caught.exception)
                self.assertIn("worker_result_summary_schema_invalid", message)
                self.assertIn("worker_result.Evidence / claim refs must be str", message)
                for i in range(4):
                    self.assertIn(f"claims[{i}].Evidence refs must be str", message)
                self.assertEqual(packet_path.read_bytes(), packet_before)
                self.assertEqual(result_path.read_bytes(), result_before)
                result["worker_result"]["Evidence / claim refs"] = evidence_id
                for row in result["claims"]:
                    row["Evidence refs"] = evidence_id
                result_path.write_text(json.dumps(result))
                merge_result(packet_path, "current_state_investigator")
                merged = json.loads(packet_path.read_text())
                self.assertEqual(merged["claims"], result["claims"])
                self.assertEqual(merged["worker_results"], [result["worker_result"]])

    def test_wrong_framework_checkout_is_rejected_before_any_write(self):
        path = self.root / "role_bindings.json"
        bindings = json.loads(path.read_text())
        bindings["framework_package"]["root"] = str(self.repository / "another-framework")
        path.write_text(json.dumps(bindings))
        saved = self.packet_path.read_bytes()
        with self.assertRaisesRegex(ValueError, "prepared_framework_package_mismatch"):
            self.merge()
        with self.assertRaisesRegex(ValueError, "prepared_framework_package_mismatch"):
            finalizer.finalize(self.packet_path, self.root / "absent.json", self.root / "work_record.md")
        bundle = self.run["activation_packet_bundle"]
        self.assertTrue(any("prepared_framework_package_mismatch" in error for error in
                            runtime.activation_packet_errors(Path(bundle["path"]),
                                                             "current_state_investigator", bundle["sha256"])))
        self.assertEqual(saved, self.packet_path.read_bytes())

    def test_recovery_uses_frozen_failure_proof_after_packet_reconciliation(self):
        self.packet["identity"].update({"State": "in_progress", "Requested profile": "standard"})
        self.packet_path.write_text(json.dumps(self.packet))
        (self.root / "runtime_closure.json").write_text(json.dumps({"runtime_closure": [{
            "Run or stage": "planning", "Receipt owner": "Coordinator", "Completed worker handles": "None",
            "Runtime status": "Released", "Remaining active handles": "None",
            "Closure evidence or blocker": "No worker was started"}]}))
        result = subprocess.run([sys.executable, str(finalizer.ROOT / "scripts/finalize_work_record.py"),
                                 "--packet", str(self.packet_path), "--workflow-failure", "contract_failure"],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        receipt = json.loads((self.root / "finalization_failure.json").read_text())
        snapshot = Path(receipt["packet_snapshot"])
        saved = snapshot.read_bytes()
        self.packet["work_item"]["Title"] = "Reconciled title"
        self.packet_path.write_text(json.dumps(self.packet))
        recovered = prepare.prepare_run(self.repository, "ITEM-1", "feature_delivery", None, True,
            input_manifest=self.inputs, planning_recovery=True, approval_reference="User requests recovery")
        self.assertNotEqual(recovered["run_id"], self.packet["identity"]["Run ID"])
        self.assertEqual(snapshot.read_bytes(), saved)

    def dispatch_trace(self, assigned):
        packet = json.loads(Path(self.run["activation_packet_bundle"]["path"]).read_text())["packets"][
            "current_state_investigator"]
        path = self.root / "activation_context.txt"
        message = runtime.activation_message(packet, {"objective": "Read assigned inputs", "input_paths": assigned})
        runtime.dispatch_message(packet, message, path)
        return {"run_id": packet["run_id"], "spawn": {"agent": packet["agent"], "dispatch_file": str(path),
                "dispatch_file_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}, "tool_trace": []}

    def test_assigned_archive_read_is_allowed_but_writes_and_unassigned_backup_reads_fail(self):
        archive = str(self.repository / ".thoughts/2967_v1/decision.md")
        trace = self.dispatch_trace([archive])
        for command, allowed in ((f"cat {archive}", True), (f"rm {archive}", False),
                                 (f"cat {archive.replace('decision.md', 'unassigned.md')}", False),
                                 (f"cat {archive} {archive}.bak", False)):
            trace["tool_trace"] = [{"tool": "exec_command", "arguments": {"cmd": command}}]
            self.assertEqual(runtime.context_trace_errors(trace) == [], allowed, command)

    def test_rebinding_keeps_immutable_dispatch_proof_valid(self):
        old_cache = self.repository / "old-cache"
        new_cache = self.repository / "new-cache"
        old_cache.mkdir()
        new_cache.mkdir()
        for cache in (old_cache, new_cache):
            shutil.copyfile(prepare.BUNDLED_AGENTS / "current_state_investigator.toml",
                            cache / "current_state_investigator.toml")
        self.run = prepare.prepare_run(self.repository, "ITEM-1", "feature_delivery", old_cache, True,
                                       input_manifest=self.inputs)
        trace = self.dispatch_trace([])
        content = Path(trace["spawn"]["dispatch_file"]).read_text()
        shutil.rmtree(old_cache)
        rebound = prepare.prepare_run(self.repository, "ITEM-1", "feature_delivery", new_cache, True,
                                      input_manifest=self.inputs)
        self.assertNotEqual(self.run["activation_packet_bundle"]["sha256"],
                            rebound["activation_packet_bundle"]["sha256"])
        self.assertEqual(runtime._verified_dispatch_content(trace), content)

    def test_archive_deduplicates_bytes_and_retry_preserves_the_existing_snapshot(self):
        history = self.root / "history"
        history.mkdir()
        for name in ("read-a.json", "read-b.json", "read-c.json"):
            (history / name).write_bytes(b"Identical historical read\n")
        archive = prepare._archive_recovery(self.root, self.run["run_id"])
        manifest = json.loads((archive / "archive_manifest.json").read_text())
        rows = [row for row in manifest["files"] if row["path"].startswith("history/")]
        self.assertEqual(len(rows), 3)
        self.assertEqual(len({row["snapshot"] for row in rows}), 1)
        self.assertFalse((archive / "history").exists())
        self.assertEqual((archive / rows[0]["snapshot"]).read_bytes(), b"Identical historical read\n")
        saved = (archive / "archive_manifest.json").read_bytes()
        self.assertEqual(prepare._archive_recovery(self.root, self.run["run_id"]), archive)
        (history / "read-a.json").write_text("Changed\n")
        with self.assertRaisesRegex(ValueError, "prior_run_archive_exists"):
            prepare._archive_recovery(self.root, self.run["run_id"])
        self.assertEqual((archive / "archive_manifest.json").read_bytes(), saved)

    def test_terminal_failure_prevents_another_worker_dispatch(self):
        (self.root / "finalization_failure.json").write_text(json.dumps({
            "status": "failed", "stage": "workflow", "run_id": self.run["run_id"]}))
        bundle = self.run["activation_packet_bundle"]
        self.assertIn("worker_activation_requires_planning_recovery", runtime.activation_packet_errors(
            Path(bundle["path"]), "current_state_investigator", bundle["sha256"]))

    def test_static_package_defect_fails_preflight_before_work(self):
        (self.repository / ".codex-plugin").mkdir()
        (self.repository / ".codex-plugin/plugin.json").write_text('{"version":"1.0.0"}')
        (self.repository / "PLAYBOOK_CATALOG.md").write_text("# Catalog\n")
        (self.repository / "scripts").mkdir()
        (self.repository / "scripts/validate_library.py").write_text('raise SystemExit("Bad shipped contract")\n')
        with patch.object(preflight, "_git", side_effect=lambda root, *args: (
                0, "a" * 40 if args[0] == "rev-parse" else "", "")), \
                patch.object(preflight, "_reused_plugin_build_identity", return_value=(False, "1.0.0")):
            result = preflight.preflight(self.repository)
        self.assertEqual(result["reason"], "framework_package_validation_failed")
        self.assertIn("Bad shipped contract", result["detail"])

    def test_assigned_provider_read_output_keeps_authorization(self):
        archive = str(self.repository / ".thoughts/2967_v1/decision.md")
        trace = self.dispatch_trace([archive])
        trace["tool_trace"] = [
            {"type": "function_call", "name": "exec_command", "call_id": "read-1",
             "arguments": json.dumps({"cmd": "cat " + archive})},
            {"type": "function_call_output", "call_id": "read-1", "output": archive},
        ]
        self.assertEqual(runtime.context_trace_errors(trace), [])
        trace["tool_trace"][0]["arguments"] = json.dumps({"cmd": "rm " + archive})
        self.assertIn("forbidden_context_reference:archived_artifact", runtime.context_trace_errors(trace))

    def test_renamed_backup_is_rejected_without_a_verified_dispatch(self):
        trace = {"tool_trace": [{"tool": "exec_command", "arguments": {
            "cmd": "cat /repo/.thoughts/2967_v1/decision.md"}}]}
        self.assertIn("forbidden_context_reference:archived_artifact", runtime.context_trace_errors(trace))

    def test_authorized_read_wrapper_cannot_hide_a_write(self):
        archive = str(self.repository / ".thoughts/2967_v1/decision.md")
        trace = self.dispatch_trace([archive])
        read = 'await tools.exec_command(' + json.dumps({"cmd": "cat " + archive}) + ')'
        trace["tool_trace"] = [{"type": "custom_tool_call", "input": read}]
        self.assertEqual(runtime.context_trace_errors(trace), [])
        trace["tool_trace"][0]["input"] = read + '; await tools.apply_patch("Delete ' + archive + '")'
        self.assertIn("forbidden_context_reference:archived_artifact", runtime.context_trace_errors(trace))

    def test_tampered_terminal_snapshot_cannot_authorize_recovery(self):
        self.packet["identity"].update({"State": "in_progress", "Requested profile": "standard"})
        self.packet_path.write_text(json.dumps(self.packet))
        frozen = finalizer.snapshot_bytes(self.packet)
        snapshot = self.root / finalizer.snapshot_name(self.packet)
        snapshot.write_bytes(frozen + b" ")
        (self.root / "runtime_closure.json").write_text('{}')
        (self.root / "finalization_failure.json").write_text(json.dumps({
            "status": "failed", "stage": "workflow", "run_id": self.run["run_id"],
            "packet_snapshot": str(snapshot), "snapshot_sha256": hashlib.sha256(frozen).hexdigest()}))
        saved = self.packet_path.read_bytes()
        with self.assertRaisesRegex(ValueError, "requires_terminal_invocation"):
            prepare.prepare_run(self.repository, "ITEM-1", "feature_delivery", None, True,
                input_manifest=self.inputs, planning_recovery=True, approval_reference="User requests recovery")
        self.assertEqual(self.packet_path.read_bytes(), saved)

    def test_failed_followup_is_not_counted_as_worker_execution(self):
        parent, child = "00000000-0000-0000-0000-000000000001", "00000000-0000-0000-0000-000000000002"
        def event(second, kind, **payload):
            return {"timestamp": f"2026-10-12T00:00:{second:02d}Z", "type": kind, "payload": payload}
        rows = [event(0, "session_meta", id=parent), event(1, "event_msg", item={
            "type": "SubAgentActivity", "kind": "started", "agent_path": "/root/worker", "agent_thread_id": child}),
            event(3, "event_msg", item={"type": "SubAgentActivity", "kind": "completed", "agent_path": "/root/worker"}),
            event(5, "response_item", type="function_call", namespace="collaboration", name="followup_task",
                  call_id="failed", arguments=json.dumps({"target": "/root/worker"})),
            event(6, "response_item", type="function_call_output", call_id="failed", output="Worker unavailable"),
            event(9, "response_item", type="message", content=[])]
        source = self.repository / "provider.jsonl"
        source.write_text("".join(json.dumps(row) + "\n" for row in rows))
        for error in ("Worker unavailable", {"error": "worker unavailable"}, {"isError": True}, {"status": "failed"}):
            with self.subTest(error=error):
                rows[4]["payload"]["output"] = error
                source.write_text("".join(json.dumps(row) + "\n" for row in rows))
                ledger = read_runtime_events(source, parent, "2026-10-12T00:00:00Z")
                self.assertEqual(ledger["timing"]["worker_active_seconds"], 2)
                self.assertEqual(len(ledger["failed_dispatches"]), 1)
                self.assertEqual(ledger["events"], [])

    def test_empty_spawn_ack_waits_for_provider_identity(self):
        parent, child = "00000000-0000-0000-0000-000000000001", "00000000-0000-0000-0000-000000000002"
        def event(second, kind, **payload):
            return {"timestamp": f"2026-10-12T00:00:{second:02d}Z", "type": kind, "payload": payload}
        rows = [event(0, "session_meta", id=parent),
            event(1, "response_item", type="function_call", namespace="collaboration", name="spawn_agent",
                  call_id="spawn", arguments=json.dumps({"task_name": "worker"})),
            event(2, "response_item", type="function_call_output", call_id="spawn", output=""),
            event(3, "event_msg", item={"type": "SubAgentActivity", "kind": "started",
                                      "agent_path": "/root/worker", "agent_thread_id": child})]
        source = self.repository / "provider.jsonl"
        source.write_text("".join(json.dumps(row) + "\n" for row in rows))
        ledger = read_runtime_events(source, parent, "2026-10-12T00:00:00Z")
        self.assertEqual(ledger["failed_dispatches"], [])
        self.assertEqual(ledger["events"][0]["Last dispatch at"], rows[1]["timestamp"])
        self.assertEqual(ledger["thread_mappings"]["/root/worker"], child)

    def test_active_turn_correction_requires_consumption_and_fresh_completion(self):
        import copy
        handle = "/root/worker"
        row = {"Provider handle": handle, "Thread ID": "00000000-0000-0000-0000-000000000002",
            "Provider status": "idle", "Status source": "read_thread", "Thread status": "idle",
            "Latest turn status": "completed", "Latest turn started at": "2026-10-12T00:00:01Z",
            "Last dispatch at": "2026-10-12T00:00:05Z", "Latest turn completed at": "2026-10-12T00:00:09Z",
            "Observed at": "2026-10-12T00:00:10Z", "Dispatch consumed": True,
            "Dispatch consumption evidence": "Provider tool call writes corrected result after dispatch; result SHA256 verified"}
        self.assertEqual(runtime.terminal_observation_errors([row], [handle]), [])
        for failure in ("unconsumed", "missing_evidence", "stale_completion"):
            with self.subTest(failure=failure):
                changed = copy.deepcopy(row)
                if failure == "unconsumed": changed["Dispatch consumed"] = False
                elif failure == "missing_evidence": changed["Dispatch consumption evidence"] = ""
                else: changed["Latest turn completed at"] = "2026-10-12T00:00:03Z"
                self.assertIn("terminal_observation_latest_turn_stale:" + handle,
                              runtime.terminal_observation_errors([changed], [handle]))

    def test_reused_worker_time_includes_followup_without_a_second_spawn(self):
        parent, child = "00000000-0000-0000-0000-000000000001", "00000000-0000-0000-0000-000000000002"
        def event(second, kind, **payload):
            return {"timestamp": f"2026-10-12T00:00:{second:02d}Z", "type": kind, "payload": payload}
        rows = [event(0, "session_meta", id=parent), event(1, "event_msg", item={
            "type": "SubAgentActivity", "kind": "started", "agent_path": "/root/worker", "agent_thread_id": child}),
            event(3, "event_msg", item={"type": "SubAgentActivity", "kind": "completed", "agent_path": "/root/worker"}),
            event(5, "response_item", type="function_call", namespace="collaboration", name="followup_task",
                  call_id="empty-ack", arguments=json.dumps({"target": "/root/worker"})),
            event(6, "response_item", type="function_call_output", call_id="empty-ack", output=""),
            event(9, "event_msg", item={"type": "SubAgentActivity", "kind": "completed", "agent_path": "/root/worker"})]
        source = self.repository / "provider.jsonl"
        source.write_text("".join(json.dumps(row) + "\n" for row in rows))
        ledger = read_runtime_events(source, parent, "2026-10-12T00:00:00Z")
        self.assertEqual(ledger["timing"]["worker_active_seconds"], 6)
        self.assertEqual(ledger["timing"]["no_worker_active_seconds"], 3)
