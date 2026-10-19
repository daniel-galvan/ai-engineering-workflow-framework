"""Compose planning recovery, provider evidence and partial-handoff gates."""

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from scripts import finalize_work_record as finalizer
from scripts import prepare_run as preparation
from scripts.merge_techops_result import merge_result
from scripts.review_evidence import PLAN_FIXTURE, draft_plan_errors
from scripts.worker_runtime_evidence import read_runtime_events


PARENT = "00000000-0000-0000-0000-000000000001"
CHILD = "00000000-0000-0000-0000-000000000002"
START = "2026-10-12T00:00:00Z"
DRAFT = "---\nstatus: Draft\n---\n" + PLAN_FIXTURE + (
    "\n# Open Questions and Decisions\n\n"
    "| Question or decision | Why it matters | Owner | Status | Evidence refs |\n"
    "| --- | --- | --- | --- | --- |\n"
    "| Retry policy | Defines recovery | Issue owner | pending | E-FD-001 |\n"
)


class PlanningRecovery(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.inputs = self.root / "inputs.json"
        self.inputs.write_text(json.dumps({"inputs": [{
            "Input ID": "IN-001", "Input or artifact": "Jira ITEM-1",
            "Source or path": "Current request", "Authority": "User", "Status": "Verified",
        }]}))
        self.prepared = preparation.prepare_run(self.root, "ITEM-1", "feature_delivery", None, False,
                                                input_manifest=self.inputs)
        self.artifacts = Path(self.prepared["artifact_root"])
        self.packet_path = Path(self.prepared["finalization_packet"])
        self.packet = json.loads(self.packet_path.read_text())

    def close_prior(self):
        self.packet["identity"].update({"Requested profile": "standard", "State": "awaiting_input",
                                       "Workflow outcome": "completed"})
        self.packet["worker_results"] = [{"Worker": "old-analysis", "Outcome": "complete"}]
        self.packet_path.write_text(json.dumps(self.packet))
        (self.artifacts / "runtime_closure.json").write_text(json.dumps({"runtime_closure": [{
            "Run or stage": "planning", "Receipt owner": "Coordinator", "Completed worker handles": "/root/old",
            "Runtime status": "Released", "Remaining active handles": "None",
            "Closure evidence or blocker": "Provider confirmed close of /root/old",
        }]}))

    def test_exhaustion_blocks_before_mutation_and_recovery_archives_counters(self):
        self.close_prior()
        failure = self.artifacts / "finalization_failure.json"
        receipt = {"status": "failed", "attempt_count": 2, "errors": ["Earlier template error"]}
        failure.write_text(json.dumps(receipt))
        saved = self.packet_path.read_bytes()
        with self.assertRaisesRegex(ValueError, "recovery_required"):
            preparation.prepare_run(self.root, "ITEM-1", "feature_delivery", None, True,
                                    input_manifest=self.inputs)
        self.assertEqual(self.packet_path.read_bytes(), saved)
        with self.assertRaisesRegex(ValueError, "approval_reference_required"):
            preparation.prepare_run(self.root, "ITEM-1", "feature_delivery", None, True,
                                    input_manifest=self.inputs, planning_recovery=True)
        (self.artifacts / "implementation_plan.md").write_text(DRAFT)
        result = preparation.prepare_run(self.root, "ITEM-1", "feature_delivery", None, True,
            input_manifest=self.inputs, planning_recovery=True, approval_reference="User requests recovery")
        current = json.loads(self.packet_path.read_text())
        archived = Path(result["archived_prior_run"])
        self.assertEqual((archived / "finalization_packet.json").read_bytes(), saved)
        self.assertEqual(json.loads((archived / failure.name).read_text()), receipt)
        self.assertFalse(failure.exists())
        self.assertNotEqual(current["identity"]["Run ID"], self.packet["identity"]["Run ID"])
        self.assertEqual(current["identity"]["Lifecycle"], "planning")
        self.assertEqual(current["workers"], [])
        self.assertEqual(current["worker_results"], [])
        self.assertEqual(current["runtime_audits"], [])
        self.assertEqual((self.artifacts / "implementation_plan.md").read_text(), DRAFT)
        contracts = json.loads(Path(result["activation_packet_bundle"]["path"]).read_text())["packets"]
        self.assertIn("result_fields", contracts["current_state_investigator"]["worker_contract"])
        self.assertIn("asset_inventory", contracts["current_state_investigator"]["worker_contract"])
        bindings = json.loads(Path(result["role_binding_manifest"]).read_text())
        self.assertTrue(bindings["runtime_evidence"]["collector"])

    def test_exhaustion_also_blocks_an_in_progress_packet(self):
        (self.artifacts / "finalization_failure.json").write_text(json.dumps({
            "status": "failed", "attempt_count": 2,
        }))
        with self.assertRaisesRegex(ValueError, "exhausted_attempts"):
            preparation.prepare_run(self.root, "ITEM-1", "feature_delivery", None, True,
                                    input_manifest=self.inputs)

    def test_blocked_invocation_still_requires_every_completed_handle(self):
        self.close_prior()
        self.packet['identity']['State'] = 'blocked'
        self.packet['worker_results'].append({'Worker': 'another-analysis', 'Outcome': 'complete'})
        self.packet_path.write_text(json.dumps(self.packet))
        with self.assertRaisesRegex(ValueError, 'prior_worker_runtime_closure_required'):
            preparation.prepare_run(self.root, 'ITEM-1', 'feature_delivery', None, True,
                input_manifest=self.inputs, planning_recovery=True, approval_reference='User requests recovery')

    def test_recovery_without_plan_does_not_register_a_missing_deliverable(self):
        self.close_prior()
        preparation.prepare_run(self.root, 'ITEM-1', 'feature_delivery', None, True,
            input_manifest=self.inputs, planning_recovery=True, approval_reference='User requests recovery')
        current = json.loads(self.packet_path.read_text())
        self.assertNotIn('Approved plan', current['recovery'])
        self.assertFalse(any(Path(row['Path']).name == 'implementation_plan.md'
                             for row in current['durable_artifacts']))

    def test_hash_bound_failure_receipt_allows_recovery_of_provisional_packet(self):
        self.close_prior()
        self.packet['identity']['State'] = 'in_progress'
        self.packet_path.write_text(json.dumps(self.packet))
        subprocess.run([sys.executable, str(finalizer.ROOT / 'scripts/finalize_work_record.py'),
            '--packet', str(self.packet_path), '--workflow-failure', 'activation_message_mismatch'],
            capture_output=True, text=True, check=False)
        result = preparation.prepare_run(self.root, 'ITEM-1', 'feature_delivery', None, True,
            input_manifest=self.inputs, planning_recovery=True, approval_reference='User requests recovery')
        self.assertTrue(Path(result['archived_prior_run']).is_dir())

    def test_stale_failure_receipt_does_not_close_an_active_invocation(self):
        self.close_prior()
        self.packet['identity']['State'] = 'in_progress'
        self.packet_path.write_text(json.dumps(self.packet))
        (self.artifacts / 'finalization_failure.json').write_text(json.dumps({
            'status': 'failed', 'stage': 'workflow', 'packet_sha256': '0' * 64}))
        with self.assertRaisesRegex(ValueError, 'requires_terminal_invocation'):
            preparation.prepare_run(self.root, 'ITEM-1', 'feature_delivery', None, True,
                input_manifest=self.inputs, planning_recovery=True, approval_reference='User requests recovery')

    def test_recovery_requires_prior_closure_and_partial_plan_cannot_enter_remediation(self):
        self.close_prior()
        (self.artifacts / "implementation_plan.md").write_text(DRAFT)
        closure = self.artifacts / "runtime_closure.json"
        closure.write_text(closure.read_text().replace('"Released"', '"Blocked"'))
        with self.assertRaisesRegex(ValueError, "prior_worker_runtime_closure_required"):
            preparation.prepare_run(self.root, "ITEM-1", "feature_delivery", None, True,
                input_manifest=self.inputs, planning_recovery=True, approval_reference="User requests recovery")
        with self.assertRaisesRegex(ValueError, "remediation_requires_ready_plan"):
            preparation.prepare_run(self.root, "ITEM-1", "feature_delivery", None, True,
                input_manifest=self.inputs, remediation_reentry=True, approval_reference="User approves")

    def test_failure_publication_preserves_diagnostics_and_attempt_limit(self):
        failure = self.artifacts / "finalization_failure.json"
        previous = {"attempt_count": 2, "correction_allowed": False,
                    "errors": ["Specific earlier error"], "first_attempt_at": START}
        failure.write_text(json.dumps(previous))
        result = subprocess.run([sys.executable, str(finalizer.ROOT / "scripts/finalize_work_record.py"),
            "--packet", str(self.packet_path), "--workflow-failure", "finalization_contract_failure"],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        current = json.loads(failure.read_text())
        self.assertEqual(current["attempt_count"], 2)
        self.assertEqual(current["first_attempt_at"], START)
        self.assertIn("Specific earlier error", current["historical_errors"])
        self.assertEqual(current["errors"], ["finalization_contract_failure"])
        with self.assertRaisesRegex(ValueError, "correction_limit_reached"):
            finalizer.finalize(self.packet_path, self.artifacts / "missing-closure.json",
                               self.artifacts / "work_record.md", pre_release=True)

    def test_partial_plan_requires_draft_and_owned_decisions(self):
        self.assertEqual(draft_plan_errors(DRAFT), [])
        self.assertTrue(draft_plan_errors(DRAFT.replace("status: Draft", "status: Approved")))
        self.assertTrue(draft_plan_errors(DRAFT.replace("| pending |", "| resolved |")))
        self.assertTrue(draft_plan_errors(DRAFT.replace("| Issue owner |", "| |")))
        self.assertTrue(draft_plan_errors(DRAFT + "\n# Metadata\n| Plan status | Approved |\n"))

    def test_planning_documenter_gate_rejects_missing_upstream_and_audits(self):
        self.packet["identity"].update({"Requested profile": "standard", "Activated profile": "standard",
                                       "Executed profile": "standard", "Profile status": "executed"})
        self.packet_path.write_text(json.dumps(self.packet))
        errors = finalizer.feature_delivery_pre_handoff_errors(self.packet_path)
        self.assertTrue(any("feature-context" in error for error in errors))
        self.assertTrue(any("feature_design.md" in error for error in errors))

    def test_feature_result_merge_is_exact_idempotent_and_run_bound(self):
        bindings = json.loads(Path(self.prepared["role_binding_manifest"]).read_text())
        contract = bindings["worker_contracts"]["current_state_investigator"]
        self.assertIn("Worker value must be exactly feature-context", contract["instructions"])
        self.assertIn("without repeating their rows", contract["instructions"])
        result = {"run_id": self.packet["identity"]["Run ID"], "worker_result": {
            key: "Recorded" for key in contract["result_fields"]["worker_results"]}, "evidence": [{
                key: "Observed" for key in contract["result_fields"]["evidence"]}]}
        result["worker_result"].update({"Worker": "feature-context", "Outcome": "complete"})
        result["evidence"][0]["Evidence ID"] = "E-FC-001"
        source = Path(contract["result"])
        source.write_text(json.dumps(result))
        merge_result(self.packet_path, "current_state_investigator")
        saved = self.packet_path.read_bytes()
        merge_result(self.packet_path, "current_state_investigator")
        self.assertEqual(self.packet_path.read_bytes(), saved)
        self.assertEqual(json.loads(saved)["evidence"][0]["Evidence ID"], "E-FC-001")
        result["run_id"] = "other-run"
        source.write_text(json.dumps(result))
        with self.assertRaisesRegex(ValueError, "worker_result_run_mismatch"):
            merge_result(self.packet_path, "current_state_investigator")
        self.assertEqual(self.packet_path.read_bytes(), saved)

    def test_failed_spawn_does_not_poison_later_dispatch(self):
        def event(time, kind, **payload):
            return {"timestamp": time, "type": kind, "payload": payload}
        events = [event(START, "session_meta", id=PARENT),
            event("2026-10-12T00:01:00Z", "response_item", type="function_call", namespace="collaboration",
                  name="spawn_agent", call_id="failed", arguments='{"task_name":"old"}'),
            event("2026-10-12T00:01:01Z", "response_item", type="function_call_output", call_id="failed",
                  output="agent path already exists"),
            event("2026-10-12T00:02:00Z", "response_item", type="function_call", namespace="collaboration",
                  name="spawn_agent", call_id="new", arguments='{"task_name":"new"}'),
            event("2026-10-12T00:02:01Z", "event_msg", item={"type": "SubAgentActivity", "kind": "started",
                  "agent_path": "/root/new", "agent_thread_id": CHILD})]
        source = self.root / "provider.jsonl"
        source.write_text("".join(json.dumps(row) + "\n" for row in events))
        ledger = read_runtime_events(source, PARENT, START)
        self.assertEqual(ledger["failed_dispatches"][0]["Task"], "old")
        self.assertEqual(ledger["thread_mappings"], {"/root/new": CHILD})
        self.assertEqual(len(ledger["events"]), 1)

    def test_identity_fragment_maps_redispatch_without_importing_prior_results(self):
        source = self.root / "prior.jsonl"
        source.write_text(json.dumps({"timestamp": START, "type": "session_meta", "payload": {"id": PARENT}})
            + "\n" + json.dumps({"timestamp": START, "type": "event_msg", "payload": {"item": {
                "type": "SubAgentActivity", "kind": "started", "agent_path": "/root/old",
                "agent_thread_id": CHILD}}}) + "\n")
        current = self.root / "current.jsonl"
        current.write_text(json.dumps({"timestamp": START, "type": "session_meta", "payload": {"id": PARENT}})
            + "\n" + json.dumps({"timestamp": START, "type": "response_item", "payload": {
                "type": "function_call", "namespace": "collaboration", "name": "followup_task",
                "arguments": '{"target":"old"}'}}) + "\n")
        result = read_runtime_events(current, PARENT, START, (source,))
        self.assertEqual(result["events"][0]["Thread ID"], CHILD)
        self.assertEqual(len(result["events"]), 1)
        source.write_text(source.read_text().replace(PARENT, CHILD))
        with self.assertRaisesRegex(ValueError, "provider_session_parent_mismatch"):
            read_runtime_events(current, PARENT, START, (source,))

    def test_composed_current_results_pass_guard_and_stale_evidence_is_rejected(self):
        bindings = json.loads(Path(self.prepared["role_binding_manifest"]).read_text())
        start = bindings["runtime_evidence"]["run_started_at"]
        started = datetime.fromisoformat(start.replace("Z", "+00:00"))
        events = [{"timestamp": start, "type": "session_meta", "payload": {"id": PARENT}}]
        self.packet["identity"].update({"Requested profile": "standard", "Activated profile": "standard",
                                       "Executed profile": "standard", "Profile status": "executed"})
        self.packet["work_item"]["Title"] = "Update asset lifecycle"
        self.packet["workers"] = []
        self.packet["worker_results"] = []
        self.packet["runtime_audits"] = []
        for index, (worker, role) in enumerate((('feature-context', 'current_state_investigator'),
                                               ('impact-analysis', 'dependency_analyst'),
                                               ('feature-design', 'solution_architect'))):
            name = worker.replace('-', '_')
            handle = '/root/' + name
            dispatch = (started + timedelta(seconds=index + 1)).isoformat()
            thread = f"00000000-0000-0000-0000-{index + 2:012d}"
            events.extend([
                {"timestamp": dispatch, "type": "response_item", "payload": {"type": "function_call",
                    "namespace": "collaboration", "name": "spawn_agent",
                    "arguments": json.dumps({"task_name": name, "fork_turns": "none",
                        "model": bindings["bindings"][role]["model"],
                        "reasoning_effort": bindings["bindings"][role]["effort"]})}},
                {"timestamp": dispatch, "type": "event_msg", "payload": {"item": {
                    "type": "SubAgentActivity", "kind": "started", "agent_path": handle,
                    "agent_thread_id": thread}}},
            ])
            self.packet['workers'].append({**dict.fromkeys(finalizer.FEATURE_DELIVERY_LEDGER_FIELDS, 'Recorded'),
                                           'Worker': worker, 'Role': role, 'Outcome': 'complete'})
            self.packet['worker_results'].append({**dict.fromkeys(finalizer.FEATURE_DELIVERY_RESULT_FIELDS, 'Recorded'),
                'Worker': worker, 'Outcome': 'complete', 'Uncertainties / blockers': 'context-unverified'})
            self.packet['runtime_audits'].append({'Worker': worker, 'Provider handle': handle,
                'Thread ID': thread, 'Last dispatch at': dispatch, 'Provider status': 'completed',
                'Observed at': (started + timedelta(seconds=10)).isoformat(), 'Status source': 'list_agents',
                'Trace retrieval': 'unavailable: exact provider export returned permission_denied'})
            (self.artifacts / (name + '.md')).write_text('# Current findings\n')
        provider = self.root / 'provider.jsonl'
        provider.write_text(''.join(json.dumps(row) + '\n' for row in events))
        ledger = Path(bindings['runtime_evidence']['ledger'])
        ledger.write_text(json.dumps(read_runtime_events(provider, PARENT, start)))
        template = json.loads(finalizer.PACKET_TEMPLATE.read_text())
        self.packet['evidence'] = [{**dict.fromkeys(template['evidence'][0], 'Observed'), 'Evidence ID': 'E-FC-001'}]
        self.packet['claims'] = [{**dict.fromkeys(template['claims'][0], 'Supported'),
                                  'Claim ID': 'CL-FC-001', 'Evidence refs': 'E-FC-001'}]
        self.packet['decisions'] = [{**dict.fromkeys(template['decisions'][0], 'Selected'),
                                    'Decision ID': 'DE-FC-001', 'Claim refs': 'CL-FC-001'}]
        self.packet['actions'] = [{**dict.fromkeys(template['actions'][0], 'Planned'),
                                  'Action ID': 'A-FC-001', 'Decision ref': 'DE-FC-001'}]
        asset = {'schema_version': 1, 'status': 'passed', 'work_item': 'ITEM-1', 'sources': [{
            'source_id': 'SRC-JIRA', 'input_id': 'IN-001', 'kind': 'jira_issue_attachments',
            'locator': 'Jira ITEM-1 attachments', 'requiredness': 'required', 'discovery_status': 'empty',
            'discovery_method': 'Read full attachment inventory',
            'remote_link_inventory': {'status': 'empty', 'method': 'Read remote links', 'locators': []},
            'limitation': 'None', 'asset_ids': [], 'evidence_refs': ['E-FC-001']}], 'assets': [], 'gate': {
            'inventory_complete': True, 'all_assets_accounted_for': True, 'all_available_assets_reviewed': True,
            'all_material_assets_linked': True, 'reviewed_before_plan': True,
            'unresolved_asset_ids': [], 'blocking_source_ids': []}}
        manifest = self.artifacts / 'asset_manifest.json'
        manifest.write_text(json.dumps(asset))
        self.packet_path.write_text(json.dumps(self.packet))
        self.assertIn('worker_result_source_missing:feature-context',
                      finalizer.feature_delivery_pre_handoff_errors(self.packet_path))
        # This gate fixture supplies source envelopes, not worker acceptance evidence.
        for row, role in zip(self.packet['worker_results'],
                             ('current_state_investigator', 'dependency_analyst', 'solution_architect')):
            result = {'run_id': self.prepared['run_id'], 'worker_result': row}
            if role == 'current_state_investigator':
                result.update({key: self.packet[key] for key in ('evidence', 'claims', 'decisions', 'actions')})
            if role == 'solution_architect':
                result.update(plan_readiness='awaiting_input', implementation_plan_action='omit')
            Path(bindings['worker_contracts'][role]['result']).write_text(json.dumps(result))
        self.assertEqual(finalizer.feature_delivery_pre_handoff_errors(self.packet_path), [])
        asset['sources'][0]['evidence_refs'] = ['E-OLD-001']
        manifest.write_text(json.dumps(asset))
        self.assertTrue(any('E-OLD-001' in error for error in
                            finalizer.feature_delivery_pre_handoff_errors(self.packet_path)))
        self.packet['runtime_audits'][0]['Last dispatch at'] = START
        self.packet_path.write_text(json.dumps(self.packet))
        self.assertTrue(any('dispatch_mismatch' in error for error in
                            finalizer.feature_delivery_pre_handoff_errors(self.packet_path)))


if __name__ == "__main__":
    unittest.main()
