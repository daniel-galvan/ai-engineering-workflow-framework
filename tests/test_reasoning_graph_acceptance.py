"""Worker previews and acceptance must catch complete-graph defects before handoff."""

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts import prepare_run
from scripts.merge_techops_result import validated_result
from scripts.prepare_worker_response import validate_response
from scripts.runtime_checks import TECHOPS_CHECKS


class ReasoningGraphAcceptance(unittest.TestCase):
    def fixture(self, directory, playbook, profile):
        root = Path(directory)
        run = prepare_run.prepare_run(root, "SYNTHETIC-42", playbook, None, False,
            execution_profile=profile, input_data={"inputs": [{"Input ID": "IN-001",
                "Input or artifact": "Current request", "Source or path": "User", "Authority": "User",
                "Status": "Verified"}]})
        packet_path = Path(run["finalization_packet"])
        packet = json.loads(packet_path.read_text())
        for table in ("evidence", "claims", "decisions", "actions", "worker_results"):
            packet[table] = []
        packet_path.write_text(json.dumps(packet))
        return run, packet_path, packet

    def result(self, run, agent, suffix):
        schema = json.loads((prepare_run.ROOT / "templates/finalization_packet.json").read_text())
        contract = run["worker_contracts"][agent]
        namespace = contract["id_namespace"]
        result = {"run_id": run["run_id"], "worker_result": {
            **dict.fromkeys(schema["worker_results"][0], "Current supported finding"),
            "Worker": contract.get("worker") or contract["worker_id"], "Outcome": "complete"}}
        ids = {}
        for table, key, prefix in (("evidence", "Evidence ID", "E"), ("claims", "Claim ID", "CL"),
                                   ("decisions", "Decision ID", "DE"), ("actions", "Action ID", "A")):
            ids[table] = f"{prefix}-{namespace}-{suffix}"
            result[table] = [{**dict.fromkeys(schema[table][0], "Current supported finding"), key: ids[table]}]
        for table, field, target in (("claims", "Evidence refs", "evidence"),
                                     ("decisions", "Claim refs", "claims"), ("actions", "Decision ref", "decisions")):
            result[table][0][field] = ids[target]
        result["worker_result"]["Evidence / claim refs"] = ids["evidence"]
        if agent == "solution_architect":
            result.update(plan_readiness="ready_for_implementation", implementation_plan_action="create")
            if run["playbook"] == "techops_issue_remediation":
                result["techops_checks"] = [{"Check": check, "Status": "not_applicable" if
                    check == "history_reconciliation" else "passed", "Detail": "Current controlled check",
                    "Evidence refs": ids["evidence"]} for check in sorted(TECHOPS_CHECKS)]
        return result

    def test_synthesis_preview_and_acceptance_reject_each_broken_link(self):
        for playbook in ("feature_delivery", "techops_issue_remediation"):
            for profile in ("standard", "deep"):
                with self.subTest(playbook=playbook, profile=profile), tempfile.TemporaryDirectory() as directory:
                    run, path, packet = self.fixture(directory, playbook, profile)
                    result = self.result(run, "solution_architect", "alpha_17")
                    before = path.read_bytes()
                    for table, key, label in (("evidence", "Evidence ID", "evidence"),
                            ("claims", "Claim ID", "claim"), ("decisions", "Decision ID", "decision")):
                        broken = copy.deepcopy(result)
                        extra = {**broken[table][0], key: broken[table][0][key] + "_new"}
                        broken[table].append(extra)
                        with self.subTest(table=table):
                            response = {"output": "Current design", "result": broken}
                            with self.assertRaisesRegex(ValueError, "orphaned " + label + " " + extra[key]):
                                validate_response(path, "solution_architect", response)
                            with self.assertRaisesRegex(ValueError, "orphaned " + label + " " + extra[key]):
                                validated_result(packet, broken, run, "solution_architect")
                            self.assertEqual(path.read_bytes(), before)
                    self.assertEqual(json.loads(validate_response(path, "solution_architect",
                        {"output": "Current design", "result": result}))["result"], result)

    def test_one_draft_correction_must_close_new_rows_and_preserve_upstream_findings(self):
        with tempfile.TemporaryDirectory() as directory:
            run, path, packet = self.fixture(directory, "feature_delivery", "standard")
            upstream = self.result(run, "dependency_analyst", "upstream")
            # Draft stages may leave findings for the final synthesis to connect.
            upstream["evidence"].append({**upstream["evidence"][0], "Evidence ID": "E-IA-unlinked"})
            packet = validated_result(packet, upstream, run, "dependency_analyst")
            path.write_text(json.dumps(packet))
            before = path.read_bytes()
            saved = {p.relative_to(path.parent): p.read_bytes() for p in path.parent.rglob('*') if p.is_file()}
            result = self.result(run, "solution_architect", "synthesis")
            response = {"output": "Current design", "result": result}
            command = [sys.executable, str(prepare_run.ROOT / "scripts/prepare_worker_response.py"),
                       "--packet", str(path), "--agent", "solution_architect", "--response-stdin"]
            def preview():
                return subprocess.run(command, input=json.dumps(response), text=True, capture_output=True, timeout=10)
            first = preview()
            self.assertEqual(first.returncode, 2, first.stdout)
            self.assertIn("orphaned evidence E-IA-unlinked", first.stdout)
            result["claims"].append({**result["claims"][0], "Claim ID": "CL-FD-new", "Evidence refs": "E-IA-unlinked"})
            result["decisions"].append({**result["decisions"][0], "Decision ID": "DE-FD-new", "Claim refs": "CL-FD-new"})
            second = preview()
            self.assertEqual(second.returncode, 2, second.stdout)
            self.assertIn("orphaned decision DE-FD-new", second.stdout)
            result["actions"].append({**result["actions"][0], "Action ID": "A-FD-new", "Decision ref": "DE-FD-new"})
            third = preview()
            self.assertEqual(third.returncode, 0, third.stdout)
            self.assertEqual(json.loads(third.stdout), response)
            accepted = validated_result(packet, result, run, "solution_architect")
            for table, key in (("evidence", "Evidence ID"), ("claims", "Claim ID"),
                               ("decisions", "Decision ID"), ("actions", "Action ID")):
                self.assertEqual(accepted[table][:len(packet[table])], packet[table])
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual({p.relative_to(path.parent): p.read_bytes() for p in path.parent.rglob('*') if p.is_file()}, saved)

    def test_review_cannot_reintroduce_orphans_after_accepted_synthesis(self):
        with tempfile.TemporaryDirectory() as directory:
            run, path, packet = self.fixture(directory, "feature_delivery", "deep")
            packet = validated_result(packet, self.result(run, "solution_architect", "design"), run, "solution_architect")
            path.write_text(json.dumps(packet))
            result = self.result(run, "reviewer", "review")
            result["decisions"].append({**result["decisions"][0], "Decision ID": "DE-PR-unlinked"})
            with self.assertRaisesRegex(ValueError, "orphaned decision DE-PR-unlinked"):
                validate_response(path, "reviewer", {"output": "Independent review", "result": result})

    def test_missing_action_table_is_not_a_graph_validation_bypass(self):
        with tempfile.TemporaryDirectory() as directory:
            run, path, _ = self.fixture(directory, "feature_delivery", "standard")
            result = self.result(run, "solution_architect", "draft")
            result["actions"] = []
            with self.assertRaisesRegex(ValueError, "orphaned decision DE-FD-draft"):
                validate_response(path, "solution_architect", {"output": "Current design", "result": result})
            result["worker_result"]["Outcome"] = "blocked"
            result.update(plan_readiness="awaiting_input", implementation_plan_action="omit")
            response = {"output": "An owned unresolved decision prevents completion.", "result": result}
            self.assertEqual(json.loads(validate_response(path, "solution_architect", response)), response)

    def test_every_declared_json_worker_receives_the_shared_preview(self):
        for playbook in ("feature_delivery", "techops_issue_remediation"):
            for profile in ("standard", "deep"):
                with self.subTest(playbook=playbook, profile=profile), tempfile.TemporaryDirectory() as directory:
                    run, path, _ = self.fixture(directory, playbook, profile)
                    for agent, contract in run["worker_contracts"].items():
                        if contract.get("result_response") != "strict_json_final_answer":
                            continue
                        self.assertEqual(Path(contract["response_builder"]).name, "prepare_worker_response.py")
                        self.assertIn(f"--agent {agent} --response-stdin", contract["result_instructions"])
                    if playbook == "feature_delivery":
                        result = self.result(run, "current_state_investigator", "asset_source")
                        manifest = {"schema_version": 1, "status": "passed", "work_item": "SYNTHETIC-42",
                            "sources": [{"source_id": "SRC-JIRA", "input_id": "IN-001",
                                "kind": "jira_issue_attachments", "locator": "Jira SYNTHETIC-42 attachments",
                                "requiredness": "required", "discovery_status": "empty",
                                "discovery_method": "Read inventory", "limitation": "No attachments",
                                "asset_ids": [], "evidence_refs": [result["evidence"][0]["Evidence ID"]],
                                "remote_link_inventory": {"status": "empty", "method": "Read remote links", "locators": []}}],
                            "assets": [], "gate": {"inventory_complete": True, "all_assets_accounted_for": True,
                                "all_available_assets_reviewed": True, "all_material_assets_linked": True,
                                "reviewed_before_plan": True, "unresolved_asset_ids": [], "blocking_source_ids": []}}
                        response = {"output": "Current source inventory", "result": result, "asset_manifest": manifest}
                        self.assertEqual(json.loads(validate_response(path, "current_state_investigator", response)), response)
                        response["asset_manifest"] = {}
                        with self.assertRaisesRegex(ValueError, "worker_asset_manifest_response_invalid"):
                            validate_response(path, "current_state_investigator", response)
                        response.pop("asset_manifest")
                        with self.assertRaisesRegex(ValueError, "worker_asset_manifest_response_required"):
                            validate_response(path, "current_state_investigator", response)
                        response["asset_manifest"] = []
                        with self.assertRaisesRegex(ValueError, "worker_asset_manifest_response_required"):
                            validate_response(path, "current_state_investigator", response)
