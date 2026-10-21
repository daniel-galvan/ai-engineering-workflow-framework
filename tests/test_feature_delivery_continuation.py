"""Regressions for the planning-to-delivery continuation and handoff seams."""

import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import prepare_run as preparation
import finalize_work_record as finalizer
import validate_worker_runtime as runtime
from run_input_manifest import load_manifest
from review_evidence import delivery_evidence_fixture, PLAN_FIXTURE
from tests.worker_response_support import stage_worker_response


class FeatureDeliveryContinuation(unittest.TestCase):
    def inputs(self, root):
        source = root / "inputs.json"
        source.write_text(json.dumps({"inputs": [{
            "Input ID": "PLAN-001", "Input or artifact": "Approved plan",
            "Source or path": str(root / "plan.md"), "Authority": "Approved user decision",
            "Status": "Registered", "Asset source": True,
        }]}))
        return source

    def test_remediation_merger_publishes_review_and_validation_to_required_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "plan.md").write_text(PLAN_FIXTURE)
            first = preparation.prepare_run(root, "ITEM-REPORTS", "feature_delivery", None, False,
                                            input_manifest=self.inputs(root))
            artifact_root = Path(first["artifact_root"])
            packet_path = Path(first["finalization_packet"])
            packet = json.loads(packet_path.read_text())
            packet["identity"].update({"Lifecycle": "planning", "State": "ready_for_implementation",
                                      "Requested profile": "standard", "Workflow outcome": "completed"})
            packet_path.write_text(json.dumps(packet))
            plan_path = artifact_root / "implementation_plan.md"
            plan_path.write_text(PLAN_FIXTURE)
            (artifact_root / "runtime_closure.json").write_text(json.dumps({"runtime_closure": [{
                "Run or stage": "planning", "Receipt owner": "Coordinator", "Completed worker handles": "/root/handoff",
                "Runtime status": "Released", "Remaining active handles": "None",
                "Closure evidence or blocker": "Provider confirmed the planning worker closed"}]}))
            run = preparation.prepare_run(root, "ITEM-REPORTS", "feature_delivery", None, True,
                input_manifest=Path(first["run_input_manifest"]["path"]), remediation_reentry=True,
                approval_reference="Explicit synthetic approval")
            artifact_root = Path(run["artifact_root"])
            packet_path = Path(run["finalization_packet"])
            result_fields = json.loads((preparation.ROOT / "templates/finalization_packet.json").read_text())
            for agent, worker, namespace, report_name in (
                ("reviewer", "review", "RV", "code_review.md"),
                ("tester", "validate", "TE", "validation_report.md"),
            ):
                evidence_id = f"E-{namespace}-001"
                summary = {**dict.fromkeys(result_fields["worker_results"][0], "Synthetic current candidate"),
                           "Worker": worker, "Outcome": "complete", "Evidence / claim refs": evidence_id}
                evidence = {**dict.fromkeys(result_fields["evidence"][0], "Synthetic report fixture"),
                            "Evidence ID": evidence_id}
                result = {"run_id": run["run_id"], "worker_result": summary, "evidence": [evidence],
                          "claims": [], "decisions": [], "actions": []}
                report = f"# {report_name}\nSynthetic complete report from the prepared result envelope.\n"
                trace_path, _ = stage_worker_response(run, agent, result, output=report,
                    provider_handle="/root/" + worker,
                    child_thread_id=str(UUID(int=202 + len(summary["Worker"]))))
                merged = subprocess.run([sys.executable, str(preparation.ROOT / "scripts/merge_techops_result.py"),
                    "--packet", str(packet_path), "--agent", agent, "--trace", str(trace_path)],
                    cwd=preparation.ROOT, capture_output=True, text=True)
                self.assertEqual(merged.returncode, 0, merged.stdout + merged.stderr)
                self.assertEqual((artifact_root / report_name).read_text(), report)
                self.assertEqual(run["worker_contracts"][agent]["output"], str(artifact_root / report_name))

    def test_input_snapshot_survives_output_edits_and_continuation_hash_is_current(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "plan.md").write_text("approved version\n")
            source = self.inputs(root)
            result = preparation.prepare_run(root, "ITEM-1", "feature_delivery", None, False,
                                             input_manifest=source)
            manifest_path = Path(result["run_input_manifest"]["path"])
            saved = load_manifest(manifest_path)
            snapshot = Path(saved["inputs"][0]["path"])
            self.assertNotEqual(snapshot, root / "plan.md")
            (root / "plan.md").write_text("updated output\n")
            self.assertEqual(snapshot.read_text(), "approved version\n")
            result = preparation.prepare_run(root, "ITEM-1", "feature_delivery", None, True,
                                             input_manifest=manifest_path)
            packet = json.loads(Path(result["finalization_packet"]).read_text())
            digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
            self.assertEqual(packet["identity"]["Run input manifest hash"], digest)
            self.assertEqual(packet["run_input_manifest"]["sha256"], digest)
            self.assertEqual(packet["inputs"], load_manifest(manifest_path)["inputs"])
            _, errors = finalizer._feature_expected_inputs(packet, manifest_path.parent)
            self.assertEqual(errors, [])
            packet["identity"]["Run input manifest hash"] = "0" * 64
            self.assertTrue(finalizer._feature_expected_inputs(packet, manifest_path.parent)[1])
            packet["identity"]["Run input manifest hash"] = digest
            packet["inputs"][0]["Authority"] = "Changed without an input observation"
            self.assertTrue(finalizer._feature_expected_inputs(packet, manifest_path.parent)[1])

    def test_reentry_requires_approval_preserves_history_and_resets_delivery_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "plan.md").write_text("approved plan\n")
            result = preparation.prepare_run(root, "ITEM-2", "feature_delivery", None, False,
                                             input_manifest=self.inputs(root), execution_profile="deep")
            artifact_root = Path(result["artifact_root"])
            packet_path = artifact_root / "finalization_packet.json"
            prior = json.loads(packet_path.read_text())
            prior["identity"].update({"Lifecycle": "planning", "State": "ready_for_implementation",
                                      "Requested profile": "deep", "Workflow outcome": "completed"})
            prior["decisions"] = [{"Decision": "Keep accepted compatibility rule"}]
            packet_path.write_text(json.dumps(prior))
            (artifact_root / "implementation_plan.md").write_text(PLAN_FIXTURE)
            (artifact_root / "runtime_closure.json").write_text(json.dumps({"runtime_closure": [{
                "Run or stage": "planning", "Receipt owner": "Coordinator",
                "Completed worker handles": "/root/handoff", "Runtime status": "Released",
                "Remaining active handles": "None", "Closure evidence or blocker": "Provider close confirmed release of /root/handoff",
            }]}))
            with self.assertRaisesRegex(ValueError, "approval_reference_required"):
                preparation.prepare_run(root, "ITEM-2", "feature_delivery", None, True,
                                        input_manifest=Path(result["run_input_manifest"]["path"]), remediation_reentry=True)
            old_bytes = packet_path.read_bytes()
            plan = artifact_root / "implementation_plan.md"
            plan.write_text("Unassessed schema proposal\n")
            with self.assertRaisesRegex(ValueError, "remediation_plan_evidence_required"):
                preparation.prepare_run(root, "ITEM-2", "feature_delivery", None, True,
                    input_manifest=self.inputs(root), remediation_reentry=True, approval_reference="User approved plan")
            self.assertEqual(packet_path.read_bytes(), old_bytes)
            self.assertFalse((artifact_root / "runs").exists())
            plan.write_text(PLAN_FIXTURE)
            closure_path = artifact_root / "runtime_closure.json"
            closed_bytes = closure_path.read_bytes()
            closure_path.write_text(closed_bytes.decode().replace('"Released"', '"Blocked"'))
            with self.assertRaisesRegex(ValueError, "prior_worker_runtime_closure_required"):
                preparation.prepare_run(root, "ITEM-2", "feature_delivery", None, True,
                                        input_manifest=Path(result["run_input_manifest"]["path"]),
                                        remediation_reentry=True, approval_reference="Explicit user approval")
            self.assertEqual(packet_path.read_bytes(), old_bytes)
            self.assertFalse((artifact_root / "runs").exists())
            closure_path.write_bytes(closed_bytes)
            result = preparation.prepare_run(root, "ITEM-2", "feature_delivery", None, True,
                                             input_manifest=Path(result["run_input_manifest"]["path"]),
                                             remediation_reentry=True, approval_reference="User approval in current turn")
            current = json.loads(packet_path.read_text())
            archived = Path(result["archived_prior_run"])
            self.assertEqual((archived / "finalization_packet.json").read_bytes(), old_bytes)
            self.assertNotEqual(current["identity"]["Run ID"], prior["identity"]["Run ID"])
            self.assertEqual(current["identity"]["Lifecycle"], "remediation")
            self.assertEqual(current["identity"]["Profile status"], "requested")
            self.assertEqual(current["identity"]["Engineering outcome"], "unknown")
            self.assertEqual(current["identity"]["Requested profile"], "deep")
            self.assertEqual(current["decisions"], prior["decisions"])
            self.assertEqual(current["worker_results"], [])
            self.assertEqual((artifact_root / "implementation_plan.md").read_text(), PLAN_FIXTURE)
            self.assertEqual(current["reentry"]["Approved plan SHA256"],
                             hashlib.sha256(PLAN_FIXTURE.encode()).hexdigest())
            packets = json.loads(Path(result["activation_packet_bundle"]["path"]).read_text())["packets"]
            self.assertIn("before_source_change_guard", packets["implementer"]["worker_contract"])
            bindings_path = artifact_root / "role_bindings.json"
            bindings = json.loads(bindings_path.read_text())
            parent_id = str(UUID(int=303))
            provider = root / "provider.jsonl"
            ledger_path = artifact_root / "runtime_dispatches.json"
            started = datetime.now(timezone.utc).replace(microsecond=0)
            bindings["runtime_evidence"].update({"run_started_at": started.isoformat(), "ledger": str(ledger_path)})
            bindings_path.write_text(json.dumps(bindings))

            def guard():
                return subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1]
                    / "scripts/validate_worker_runtime.py"), "--before-source-change", str(packet_path),
                    "--implementer-handle", "/root/implement", "--provider-status", "running"],
                    cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True,
                    env={key: value for key, value in os.environ.items()
                         if key not in {"CODEX_THREAD_ID", "CODEX_SESSION_ID"}})

            def event(offset, kind, **payload):
                return {"timestamp": (started + timedelta(seconds=offset)).isoformat(), "type": kind,
                        "payload": payload}

            rows = [event(0, "session_meta", id=parent_id, cwd=str(root))]
            handles, threads = [], []
            for index, (worker, role) in enumerate((("implement", "implementer"), ("review", "reviewer"),
                                                     ("validate", "tester")), 1):
                handle, thread = "/root/" + worker, str(UUID(int=303 + index))
                assignment = artifact_root / (worker + "-assignment.json")
                assignment.write_text(json.dumps({"objective": "Work on the approved implementation plan",
                                                  "input_paths": [str(plan)]}))
                dispatch = artifact_root / (worker + "-activation.txt")
                result_cli = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1]
                    / "scripts/validate_worker_runtime.py"), "--activation-packet-bundle",
                    result["activation_packet_bundle"]["path"], "--expected-agent", role,
                    "--expected-bundle-sha256", result["activation_packet_bundle"]["sha256"],
                    "--assignment", str(assignment), "--dispatch-file", str(dispatch)],
                    cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True,
                    env={key: value for key, value in os.environ.items()
                         if key not in {"CODEX_THREAD_ID", "CODEX_SESSION_ID"}})
                self.assertEqual(result_cli.returncode, 0, result_cli.stdout + result_cli.stderr)
                guarded = json.loads(result_cli.stdout)
                rows.extend([event(index * 2 + 1, "response_item", type="function_call", namespace="collaboration",
                    name="spawn_agent", call_id="spawn-" + worker, arguments=json.dumps({
                        "task_name": worker, "message": guarded["activation_message"],
                        **guarded["launch_arguments"]})),
                    event(index * 2 + 2, "event_msg", item={"type": "SubAgentActivity", "kind": "started",
                        "agent_path": handle, "agent_thread_id": thread})])
                handles.append(handle)
                threads.append(thread)
            rows.extend([event(9, "response_item", type="function_call", namespace="collaboration",
                name="list_agents", call_id="inventory", arguments="{}"),
                event(10, "response_item", type="function_call_output", call_id="inventory",
                    output=json.dumps({"agents": [{"agent_name": handle, "agent_status": {"running": "Active"}}
                                       for handle in handles]}))])
            provider.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            missing_ledger = guard()
            self.assertEqual(missing_ledger.returncode, 2, missing_ledger.stdout + missing_ledger.stderr)
            self.assertIn("remediation_not_activated", missing_ledger.stdout)
            collector = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1]
                / "scripts/worker_runtime_evidence.py"), "--provider-session", str(provider),
                "--parent-thread-id", parent_id, "--started-at", started.isoformat(), "--ledger", str(ledger_path)],
                cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True,
                env={key: value for key, value in os.environ.items()
                     if key not in {"CODEX_THREAD_ID", "CODEX_SESSION_ID"}})
            self.assertEqual(collector.returncode, 0, collector.stdout + collector.stderr)
            collected = json.loads(collector.stdout)
            self.assertEqual(collected["profile_activation"]["status"], "activated")
            activated = json.loads(packet_path.read_text())["identity"]
            self.assertEqual(activated["Activated profile"], "deep")
            self.assertEqual(activated["Profile status"], "in_progress")
            # All three real activations suffice; Documenter is activated only after accepted fan-in.
            accepted = guard()
            self.assertEqual(accepted.returncode, 0, accepted.stdout + accepted.stderr)
            self.assertFalse((artifact_root / "runtime_closure.json").exists())
            current_run_id = current["identity"]["Run ID"]
            result = preparation.prepare_run(root, "ITEM-2", "feature_delivery", None, True,
                                             input_manifest=Path(result["run_input_manifest"]["path"]))
            followed = json.loads(packet_path.read_text())
            self.assertEqual(followed["identity"]["Run ID"], current_run_id)
            self.assertEqual(followed["identity"]["Lifecycle"], "remediation")
            self.assertEqual(result["workflow_objective"], "feature_implementation")

    def test_documenter_guard_rejects_planning_packet_for_prepared_remediation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "plan.md").write_text("approved plan\n")
            result = preparation.prepare_run(root, "ITEM-3", "feature_delivery", None, False,
                                             input_manifest=self.inputs(root))
            bindings_path = Path(result["role_binding_manifest"])
            bindings = json.loads(bindings_path.read_text())
            bindings["lifecycle"] = "remediation"
            bindings_path.write_text(json.dumps(bindings))
            packet_path = Path(result["finalization_packet"])
            packet = json.loads(packet_path.read_text())
            packet["identity"]["Lifecycle"] = "planning"
            packet_path.write_text(json.dumps(packet))
            bundle = result["activation_packet_bundle"]
            self.assertIn("feature_delivery_packet_lifecycle_mismatch",
                          runtime.activation_packet_errors(Path(bundle["path"]), "documenter", bundle["sha256"]))

    def delivery_packet(self, root):
        packet = {"identity": {"Playbook / version": "playbooks/feature_delivery.md / 0.5.2",
                               "Lifecycle": "remediation", "State": "handoff",
                               "Requested profile": "deep", "Activated profile": "deep", "Executed profile": "deep",
                               "Profile status": "executed", "Workflow outcome": "in_progress",
                               "Engineering outcome": "partially_solved"},
                  "finalization": {"Durable artifact root": str(root)},
                  "workers": [], "worker_results": [], "runtime_audits": [],
                  "synchronization": [{"Stage": "Delivery fan-in", "Workers launched": "implement, review, validate",
                                       "Barrier status": "Passed", "Results summarized": "Review accepted; database unverified"}],
                  "evidence": [{"Evidence ID": "E-001"}], "terminal_observations": []}
        for index, (worker, role) in enumerate((('implement', 'implementer'), ('review', 'reviewer'), ('validate', 'tester'))):
            packet["workers"].append({**{field: "Recorded" for field in finalizer.FEATURE_DELIVERY_LEDGER_FIELDS},
                                      "Worker": worker, "Role": role, "Outcome": "complete"})
            packet["worker_results"].append({**{field: "Recorded" for field in finalizer.FEATURE_DELIVERY_RESULT_FIELDS},
                                             "Worker": worker, "Outcome": "complete", "Evidence / claim refs": "E-001",
                                             "Uncertainties / blockers": "context-unverified; database unverified"})
            packet["runtime_audits"].append({"Worker": worker, "Provider handle": f"/root/{worker}",
                                           "Provider status": "completed", "Last dispatch at": "2026-10-07T23:40:00Z",
                                           "Observed at": "2026-10-07T23:50:00Z", "Status source": "list_agents",
                                           "Trace retrieval": "unavailable: provider export returned permission_denied"})
        repository, review, validation = delivery_evidence_fixture(root)
        packet["repositories"] = [{"Repository role": "Execution", "Resolved path": str(repository)}]
        (root / "code_review.md").write_text(review)
        (root / "validation_report.md").write_text(validation)
        (root / "implementation_plan.md").write_text(PLAN_FIXTURE)
        return packet

    def test_remediation_gate_requires_workers_review_validation_fan_in_and_audits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packet = self.delivery_packet(root)
            path = root / "finalization_packet.json"
            self.assertEqual(finalizer._feature_delivery_remediation_errors(packet, path, pre_handoff=True), [])
            original_plan = (root / "implementation_plan.md").read_text()
            (root / "implementation_plan.md").write_text(original_plan.replace("| verified |", "| assumed |"))
            solved = copy.deepcopy(packet)
            solved["identity"]["Engineering outcome"] = "solved"
            self.assertTrue(any("complete solution required outcome remains assumed" in error for error in
                                finalizer._feature_delivery_remediation_errors(solved, path, pre_handoff=True)))
            self.assertFalse(any("complete solution required outcome" in error for error in
                                 finalizer._feature_delivery_remediation_errors(packet, path, pre_handoff=True)))
            (root / "implementation_plan.md").write_text(original_plan)
            omitted = (root / "code_review.md").read_text().replace("Asset-only edit preserves publication", "Other path")
            (root / "code_review.md").write_text(omitted)
            self.assertTrue(any("review omits required plan" in error for error in
                                finalizer._feature_delivery_remediation_errors(packet, path, pre_handoff=True)))
            (root / "code_review.md").write_text(omitted.replace("Other path", "Asset-only edit preserves publication"))
            for field in ("worker_results", "workers", "synchronization", "runtime_audits"):
                broken = copy.deepcopy(packet)
                broken[field] = []
                with self.subTest(field=field):
                    self.assertTrue(finalizer._feature_delivery_remediation_errors(broken, path, pre_handoff=True))
            current_review = (root / "code_review.md").read_text()
            (root / "code_review.md").write_text(current_review.replace("Disposition: accepted", "Disposition: changes_required"))
            self.assertTrue(finalizer._feature_delivery_remediation_errors(packet, path, pre_handoff=True))
            (root / "code_review.md").write_text(current_review)
            unverified = copy.deepcopy(packet)
            unverified["identity"].update({"State": "completed", "Workflow outcome": "completed"})
            self.assertIn("feature_delivery_context_unverified_prevents_completion",
                          finalizer._feature_delivery_remediation_errors(unverified, path, pre_handoff=True))
            validation = (root / "validation_report.md").read_text()
            (root / "validation_report.md").write_text("Unit tests passed.\n")
            self.assertTrue(finalizer._feature_delivery_remediation_errors(packet, path, pre_handoff=True))
            (root / "validation_report.md").write_text(validation)
            start = validation.index("## Affected Tests")
            end = validation.index("## Release Follow-up", start)
            (root / "validation_report.md").write_text(validation[:start] + validation[end:])
            self.assertTrue(any("Affected Tests" in error for error in
                                finalizer._feature_delivery_remediation_errors(packet, path, pre_handoff=True)))
            (root / "validation_report.md").write_text(validation)
            repository = Path(packet["repositories"][0]["Resolved path"])
            (repository / "asset.py").write_text("version = 3\n")
            self.assertTrue(any("candidate changed" in error for error in
                                finalizer._feature_delivery_remediation_errors(packet, path, pre_handoff=True)))
            (root / "validation_report.md").unlink()
            self.assertTrue(finalizer._feature_delivery_remediation_errors(packet, path, pre_handoff=True))


if __name__ == "__main__":
    unittest.main()
