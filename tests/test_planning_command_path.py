"""Whole planning command paths; only worker output and native provider events are simulated."""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from contextlib import ExitStack
from pathlib import Path
from uuid import UUID
from unittest.mock import patch

from scripts.review_evidence import (
    AFFECTED_TEST_COLUMNS, COVERAGE_COLUMNS, PLAN_COLUMNS, REVIEW_COLUMNS,
    DESIGN_COLUMNS, SOLUTION_COLUMNS, VALIDATION_COLUMNS, candidate_fingerprint,
)
from tests import test_packaged_lifecycle as packaging


class PlanningCommandPath(unittest.TestCase):
    def test_techops_ready_plan_through_actual_shipped_commands(self):
        self.planning_path("techops_issue_remediation")

    def test_feature_ready_plan_through_actual_shipped_commands(self):
        self.planning_path("feature_delivery")

    def test_feature_remediation_through_actual_shipped_commands(self):
        self.planning_path("feature_delivery", continue_to_remediation=True)

    def test_techops_remediation_through_actual_shipped_commands(self):
        self.planning_path("techops_issue_remediation", continue_to_remediation=True)

    def test_techops_remediation_publishes_blocked_runtime_snapshot(self):
        self.planning_path("techops_issue_remediation", continue_to_remediation=True,
                           blocked_runtime_snapshot=True)

    def test_techops_remediation_closes_from_targeted_provider_status(self):
        self.planning_path("techops_issue_remediation", continue_to_remediation=True,
                           targeted_runtime_observation=True)

    def test_late_parent_violation_blocks_success_but_preserves_failure_delivery(self):
        for playbook in ("techops_issue_remediation", "feature_delivery"):
            with self.subTest(playbook=playbook):
                self.planning_path(playbook, late_parent_violation=True)

    def test_failed_worker_replacement_reaches_publication_with_both_handles_closed(self):
        for playbook in ("techops_issue_remediation", "feature_delivery"):
            with self.subTest(playbook=playbook):
                self.planning_path(playbook, recover_failed_worker=True)

    def test_native_fragment_continuation_preserves_accepted_results_through_publication(self):
        for playbook in ("techops_issue_remediation", "feature_delivery"):
            with self.subTest(playbook=playbook):
                self.planning_path(playbook, native_continuation=True)

    def planning_path(self, playbook, *, late_parent_violation=False, recover_failed_worker=False,
                      native_continuation=False, continue_to_remediation=False,
                      blocked_runtime_snapshot=False, targeted_runtime_observation=False):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as environment:
            package = packaging.PackagedLifecycle().package(directory)
            repository = Path(directory) / "repository"
            repository.mkdir()
            source = repository / "src" / "counter" / "counter.py"
            source.parent.mkdir(parents=True)
            source.write_text("def increment(value):\n    return value - 1\n")
            instructions = source.parent / "AGENTS.md"
            instructions.write_text("Do not read .thoughts/DEMO-1/runs/prior/analysis.md.\n")
            (source.parent / "test_counter.py").write_text("from counter import increment\n\ndef test_increment():\n    assert increment(2) == 3\n")
            (repository / ".gitignore").write_text(".thoughts/\n__pycache__/\n")
            for arguments in (("init", "-q"), ("config", "user.name", "Fixture"),
                              ("config", "user.email", "fixture@example.invalid"), ("add", "."),
                              ("commit", "-qm", "Initial counter fixture")):
                subprocess.run(["git", "-C", str(repository), *arguments], check=True, capture_output=True)
            source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            parent_id, turn_id = str(UUID(int=1)), str(UUID(int=2))
            provider = Path(directory) / ("native/sessions" if native_continuation else "provider")
            provider.mkdir(parents=True)
            parent = provider / ("rollout-" + parent_id + ".jsonl" if native_continuation else "parent.jsonl")
            if native_continuation:
                environment.enter_context(patch.dict(os.environ, {"CODEX_THREAD_ID": parent_id,
                                                                 "CODEX_SESSION_ID": "",
                                                                 "CODEX_HOME": str(provider.parent)}))

            def append(path, kind, **payload):
                with path.open("a") as stream:
                    stream.write(json.dumps({"timestamp": datetime.now(timezone.utc).isoformat(),
                                             "type": kind, "payload": payload}) + "\n")

            append(parent, "session_meta", id=parent_id, cwd=str(repository))
            append(parent, "turn_context", turn_id=turn_id)
            append(parent, "response_item", role="user", content=[{"type": "input_text", "text":
                "Use only this controlled offline case and supplied source. Plan DEMO-1 in standard/planning: increment(2) returns 1 and must return 3. "
                "Read-only source inspection; do not run product tests or builds."}])

            def command(script, *arguments, expected=0):
                result = subprocess.run([sys.executable, str(package / "scripts" / script), *map(str, arguments)],
                                        cwd=package, capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, expected, script + "\n" + result.stdout + result.stderr)
                return result.stdout

            def render_table(columns, cells):
                return "| " + " | ".join(columns) + " |\n| " + " | ".join(["---"] * len(columns)) + " |\n| " + " | ".join(cells) + " |\n"

            parent_option = () if native_continuation else ("--provider-session", parent)
            preflight = json.loads(command("run_preflight.py", *parent_option))
            inputs = Path(directory) / "inputs.json"
            inputs.write_text(json.dumps({"inputs": [{"Input ID": "IN-001", "Input or artifact":
                "Counter defect: increment(2) returns 1; expected 3. Planning only, standard profile.",
                "Source or path": "User", "Authority": "User", "Status": "Verified"},
                {"Input ID": "IN-002", "Input or artifact": "Jira DEMO-1 supplied offline record: no attachments or remote links",
                 "Source or path": "Jira DEMO-1", "Authority": "User supplied fixture", "Status": "Verified"}]}))
            run = json.loads(command("prepare_run.py", "--execution-repository", repository, "--work-item", "DEMO-1",
                "--playbook", playbook, "--input-manifest", inputs,
                *parent_option, "--lifecycle", "planning"))
            root, packet_path = Path(run["artifact_root"]), Path(run["finalization_packet"])
            self.assertEqual(Path(run["documenter_packet_stager"]).name, "stage_documenter_packet.py")
            if playbook == "techops_issue_remediation":
                documenter_instructions = run["worker_contracts"]["documenter"]["instructions"]
                self.assertIn("Preserve the Coordinator-prepared State", documenter_instructions)
                self.assertNotIn("set State ready_for_implementation", documenter_instructions)
            template = json.loads((package / "templates/finalization_packet.json").read_text())
            roles = (("issue-evidence", "current_state_investigator", "ISS"),
                     ("failure-path", "dependency_analyst", "FP"),
                     ("fix-design", "solution_architect", "FD"), ("handoff", "documenter", "DOC"))
            if playbook == "feature_delivery":
                roles = (("feature-context", "current_state_investigator", "FC"),
                         ("impact-analysis", "dependency_analyst", "IA"),
                         ("feature-design", "solution_architect", "FD"), ("handoff", "documenter", "DOC"))
            first_namespace, second_namespace = roles[0][2], roles[1][2]
            completed, summaries, result_hashes, statuses, rejected_traces = {}, {}, {}, {}, {}
            coordinator_handoff_identity = None

            def inventory(omit_handles=()):
                call = "inventory-" + str(len(completed)) + "-" + datetime.now().strftime("%H%M%S%f")
                append(parent, "response_item", type="function_call", namespace="collaboration", name="list_agents",
                       call_id=call, arguments="{}")
                append(parent, "response_item", type="function_call_output", call_id=call,
                       output=json.dumps({"agents": [{"agent_name": handle, "agent_status": {statuses.get(handle, "completed"): "Done"}}
                                                    for handle in completed if handle not in set(omit_handles)]}))

            collector = ("--provider-session", parent, "--parent-thread-id", parent_id,
                         "--started-at", run["runtime_evidence"]["run_started_at"],
                         "--ledger", run["runtime_evidence"]["ledger"])
            for index, (worker, role, namespace) in enumerate(roles):
                if worker == "handoff":
                    stage_args = ["--packet", packet_path, "--coordinator-model-effort", "Not exposed / Not exposed",
                                  "--prompt-conformance", "pass"]
                    if playbook == "techops_issue_remediation":
                        stage_args.extend(["--state", "ready_for_implementation"])
                    staged = json.loads(command("stage_documenter_packet.py", *stage_args))
                    self.assertEqual(staged["status"], "staged")
                    packet = json.loads(packet_path.read_text())
                    coordinator_handoff_identity = {key: packet["identity"][key] for key in (
                        "Activated profile", "Executed profile", "Profile status", "State", "Engineering state",
                        "Workflow outcome", "Engineering outcome", "Coordinator model/effort",
                        "Prompt template / revision / conformance")}
                    self.assertEqual({row["Worker"] for row in packet["workers"]}, set(summaries))
                    self.assertEqual(packet["synchronization"][-1]["Barrier status"].split(";")[0], "Passed")
                assignment = root / (worker + "-assignment.json")
                assignment.write_text(json.dumps({"objective": "Complete the current counter planning stage: " + worker,
                    "input_paths": [str(packet_path), str(source)]}))
                activation = root / (worker + "-activation.txt")
                guarded = json.loads(command("validate_worker_runtime.py", "--activation-packet-bundle",
                    run["activation_packet_bundle"]["path"], "--expected-agent", role, "--expected-bundle-sha256",
                    run["activation_packet_bundle"]["sha256"], "--assignment", assignment, "--dispatch-file", activation))
                if recover_failed_worker and index == 0:
                    failed_handle, failed_id = "/root/failed_original", str(UUID(int=900))
                    append(parent, "response_item", type="function_call", namespace="collaboration", name="spawn_agent",
                           call_id="spawn-failed", arguments=json.dumps({"task_name": "failed_original",
                           "message": guarded["activation_message"], **guarded["launch_arguments"]}))
                    append(parent, "event_msg", item={"type": "SubAgentActivity", "kind": "started",
                           "agent_path": failed_handle, "agent_thread_id": failed_id})
                    failed_child = provider / "failed-original.jsonl"
                    append(failed_child, "session_meta", id=failed_id, cwd=str(repository))
                    append(failed_child, "response_item", type="function_call", name="exec_command", call_id="bootstrap",
                           arguments=json.dumps({"cmd": "cat " + str(activation), "workdir": str(repository)}))
                    append(failed_child, "response_item", type="function_call_output", call_id="bootstrap", output=activation.read_text())
                    append(parent, "event_msg", item={"type": "SubAgentActivity", "kind": "failed",
                           "agent_path": failed_handle, "agent_thread_id": failed_id})
                    completed[failed_handle], statuses[failed_handle] = failed_id, "failed"
                    inventory()
                    rejected = root / "failed-original-trace.json"
                    command("worker_runtime_evidence.py", *collector, "--worker-session", failed_child,
                            "--agent", role, "--trace", rejected, expected=2)
                    rejected_traces[rejected] = rejected.read_bytes()
                    rejected_result = json.loads(rejected.read_text())
                    self.assertEqual(rejected_result["audit"]["status"], "rejected")
                    dispatch_at = rejected_result["last_dispatch_at"]
                    recovery = ("--activation-packet-bundle", run["activation_packet_bundle"]["path"],
                        "--expected-agent", role, "--expected-bundle-sha256", run["activation_packet_bundle"]["sha256"],
                        "--assignment", assignment, "--rejected-trace", rejected, "--provider-handle", failed_handle,
                        "--last-dispatch-at", dispatch_at, "--provider-status", "failed")
                    activation = root / (worker + "-replacement-activation.txt")
                    guarded = json.loads(command("validate_worker_runtime.py", *recovery, "--dispatch-file", activation))
                    repeated = command("validate_worker_runtime.py", *recovery, "--dispatch-file", root / "forbidden-third-attempt.txt", expected=2)
                    self.assertIn("activation_repair_limit_reached", repeated)
                handle, child_id = "/root/" + worker.replace("-", "_"), str(UUID(int=index + 100))
                append(parent, "response_item", type="function_call", namespace="collaboration", name="spawn_agent",
                       call_id="spawn-" + worker, arguments=json.dumps({"task_name": worker.replace("-", "_"),
                       "message": guarded["activation_message"], **guarded["launch_arguments"]}))
                append(parent, "event_msg", item={"type": "SubAgentActivity", "kind": "started",
                       "agent_path": handle, "agent_thread_id": child_id})
                child = provider / (worker + ".jsonl")
                append(child, "session_meta", id=child_id, cwd=str(repository))
                append(child, "turn_context", turn_id=str(UUID(int=index + 200)),
                       model=guarded["launch_arguments"]["model"], effort=guarded["launch_arguments"]["reasoning_effort"])
                append(child, "response_item", type="function_call", name="exec_command", call_id="bootstrap",
                       arguments=json.dumps({"cmd": "cat " + str(activation), "workdir": str(repository)}))
                append(child, "response_item", type="function_call_output", call_id="bootstrap", output=activation.read_text())
                append(child, "response_item", type="function_call", name="exec_command", call_id="source",
                       arguments=json.dumps({"cmd": "cat " + str(source), "workdir": str(repository)}))
                append(child, "response_item", type="function_call_output", call_id="source", output=source.read_text())
                append(child, "response_item", type="function_call", name="exec_command", call_id="instructions",
                       arguments=json.dumps({"cmd": "cat " + str(instructions), "workdir": str(repository)}))
                append(child, "response_item", type="function_call_output", call_id="instructions",
                       output=instructions.read_text())
                if role == "solution_architect":
                    fixture_path = source.parent / "test_counter.py"
                    append(child, "response_item", type="function_call", name="exec_command", call_id="fixture",
                           arguments=json.dumps({"cmd": "cat " + str(fixture_path), "workdir": str(repository)}))
                    append(child, "response_item", type="function_call_output", call_id="fixture", output=fixture_path.read_text())
                summary = {**dict.fromkeys(template["worker_results"][0], "Current counter source inspected"),
                    "Worker": worker, "Outcome": "complete", "Confidence": "High", "Uncertainties / blockers": "None",
                    "Evidence / claim refs": "E-" + (first_namespace if worker == "handoff" else namespace) + "-001",
                    "Actual model/effort": guarded["launch_arguments"]["model"] + " / " + guarded["launch_arguments"]["reasoning_effort"],
                    "Usage/credits": "Not exposed"}
                summary["Unique contribution"] = (
                    "Bounded the supplied symptom and expected counter behavior.",
                    "Traced subtraction to the decrement without deployment assumptions.",
                    "Selected the minimal operator correction and regression extension.",
                    "Assembled accepted analysis and an unapproved plan without source changes.")[index]
                summaries[worker] = summary
                response_manifest = None
                if worker != "handoff":
                    evidence = {"Evidence ID": "E-" + namespace + "-001", "Source": str(source),
                        "Summary": "Current counter subtracts one; supplied requirement explicitly expects an increment.",
                        "Confidence": "High", "Uncertainty": "Deployment was not inspected or needed for this local plan.",
                        "Status": "Verified"}
                    result = {"run_id": run["run_id"], "worker_result": summary, "evidence": [evidence], "claims": [{
                        "Claim ID": "CL-" + namespace + "-001", "Claim": "Change the existing subtraction to addition.",
                        "Evidence refs": evidence["Evidence ID"], "Confidence": "High", "Uncertainty": "None",
                        "Status": "Supported"}], "decisions": [], "actions": []}
                    if role == "solution_architect":
                        evidence["Source"] = str(source.parent / "test_counter.py")
                        evidence["Summary"] = "The existing fixture expects increment(2) == 3; zero and negative cases remain planned."
                        result["decisions"] = [{"Decision ID": "DE-FD-001", "Decision": "Use addition in the existing counter function.",
                            "Claim refs": f"CL-{first_namespace}-001, CL-{second_namespace}-001, CL-FD-001", "Owner": "Implementer", "Status": "Proposed"}]
                        result["actions"] = [{"Action ID": "A-FD-001", "Action": "After approval, correct the operator and extend the regression fixture.",
                            "Decision ref": "DE-FD-001", "Owner": "Implementer", "Status": "Proposed"}]
                        if playbook == "feature_delivery":
                            result.update(plan_readiness="ready_for_implementation", implementation_plan_action="create")
                        else:
                            result["techops_checks"] = [{"Check": check, "Status": "not_applicable" if check == "history_reconciliation" else "passed",
                            "Evidence refs": "E-ISS-001, E-FP-001, E-FD-001", "Detail":
                            "No report/current-code mismatch; current source confirms the reported subtraction."
                            if check == "history_reconciliation" else
                            "Existing source and regression fixture inspected; local correction and test extensions planned, not executed."}
                            for check in ("issue_scope", "history_reconciliation", "plan_dependencies", "regression_fixture")]
                    if playbook == "feature_delivery" and index == 0:
                        # Simulated context-worker inventory of the explicitly supplied offline Jira record.
                        response_manifest = {
                            "schema_version": 1, "status": "passed", "work_item": "DEMO-1", "sources": [{
                                "source_id": "SRC-JIRA", "input_id": "IN-002", "kind": "jira_issue_attachments",
                                "locator": "Jira DEMO-1 attachments", "requiredness": "required", "discovery_status": "empty",
                                "discovery_method": "Read complete attachment inventory in supplied offline Jira record",
                                "remote_link_inventory": {"status": "empty", "method": "Read supplied remote link inventory", "locators": []},
                                "limitation": "None", "asset_ids": [], "evidence_refs": ["E-FC-001"]}], "assets": [],
                            "gate": {"inventory_complete": True, "all_assets_accounted_for": True,
                                "all_available_assets_reviewed": True, "all_material_assets_linked": True,
                                "reviewed_before_plan": True, "unresolved_asset_ids": [], "blocking_source_ids": []}}
                    response = {"output": "# Current counter planning\n" + evidence["Summary"] + "\n",
                                "result": result}
                    if response_manifest is not None:
                        response["asset_manifest"] = response_manifest
                    append(child, "response_item", type="message", role="assistant", phase="final_answer",
                           content=[{"type": "output_text", "text": json.dumps(response)}])
                else:
                    # Simulated Documenter output preserves accepted tables and generated Coordinator audits.
                    packet = json.loads(packet_path.read_text())
                    packet["work_item"]["Title"] = "Correct the counter increment"
                    packet["playbook_selection"].update({"Primary evidence": "Current source and supplied defect",
                        "Primary goal": "Implementation planning", "Closest alternative": "Feature Delivery",
                        "Why this playbook": "A bounded defect in an existing numeric operation"})
                    if coordinator_handoff_identity is not None:
                        self.assertEqual({key: packet["identity"][key] for key in coordinator_handoff_identity},
                                         coordinator_handoff_identity)
                    packet["finalization"].update({"Concurrent-run decision": "Independent temporary fixture repository",
                        "Active related run or work item": "None", "Related-run check": "The fixture owns this isolated repository",
                        "Final reconciliation": "Accepted analysis preserved; runtime closure pending Coordinator receipt",
                        "Finalization schema": "Pending"})
                    packet["workers"].append({"Worker": "handoff", "Role": "documenter",
                        "Assigned inputs": "Accepted planning packet and current-run artifacts",
                        "Mode": "planning", "Depth": "standard", "Skills": "Prepared Documenter instructions",
                        "Tools": "artifact_write", "Capacity": "Not exposed",
                        "Configured model/effort": run["bindings"]["documenter"]["model"] + " / " +
                            run["bindings"]["documenter"]["effort"],
                        "Provider-observed model/effort": run["bindings"]["documenter"]["model"] + " / " +
                            run["bindings"]["documenter"]["effort"], "Usage": "Not exposed",
                        "Depends on": "Accepted analytical fan-in", "Outcome": "complete", "Confidence": "High"})
                    packet["worker_results"].append(summary)
                    plan = root / "implementation_plan.md"
                    plan.write_text("---\nstatus: Draft\n---\n# Counter implementation plan\n"
                        "Plan status: Unapproved. Change subtraction to addition and extend the existing regression fixture.\n" +
                        "# Behavior Applicability\n" + render_table(PLAN_COLUMNS, ["Counter increment", "User IN-001", f"E-{first_namespace}-001",
                            "Inspected subtraction and supplied increment expectation", "required", "Use existing addition operation"]) +
                        "# Design Justification\n" + render_table(DESIGN_COLUMNS, ["Existing numeric operation", "Increment by one",
                            f"E-{second_namespace}-001 confirms subtraction", "Compared direct addition without new state", "Replace the operator",
                            "One operator change; no schema or external system change"]) +
                        "# Complete Solution\n" + render_table(SOLUTION_COLUMNS, ["Counter function and regression fixture", "Increment all supported numeric values",
                            "planned", "E-FD-001; product tests not executed in planning", "Implementer adds positive, zero and negative cases",
                            "required_for_completion"]))
                    packet["durable_artifacts"].extend([{"Artifact": "Implementation plan", "Path": str(plan), "Status": "Draft",
                        "Purpose": "Unapproved implementation proposal"}, {"Artifact": "Work record", "Path": str(root / "work_record.md"),
                        "Status": "Prepared", "Purpose": "Packaged finalizer-owned terminal report"}])
                    packet["handoff"] = {"workflow_result": "Plan created", "implementation_plan": str(plan),
                        "established": ["The current function subtracts one; the supplied requirement expects an increment."],
                        "best_current_explanations": [{"explanation": "The subtraction operator causes the reported decrement.",
                            "confidence": "High", "reason": "Current source and explicit expected behavior agree on the defect."}],
                        "next_action": {"owner": "User", "action": "Review the plan and explicitly approve implementation.",
                            "complete_when": "The exact plan is approved for remediation reentry."},
                        "artifacts": [str(plan), str(root / "work_record.md")],
                        "execution": "standard/planning; source changes none; runtime closure pending",
                        "provenance": "plugin ai-engineering-workflows " + preflight["plugin_version"] + "; framework revision "
                            + preflight["framework_revision"] + " (clean); playbook " + playbook + " 0.5.33."}
                    if playbook == "feature_delivery":
                        assets = root / "asset_manifest.json"
                        plan.write_text(plan.read_text() + "\n## Asset Baseline\n\n"
                            + f"[Asset inventory]({assets}): the supplied Jira fixture has no attachments or remote links.\n")
                        packet["durable_artifacts"].append({"Artifact": "Asset inventory", "Path": str(assets),
                            "Status": "passed", "Purpose": "Current feature-context inventory"})
                        packet["handoff"]["artifacts"].append(str(assets))
                    packet_path.write_text(json.dumps(packet))
                append(parent, "event_msg", item={"type": "SubAgentActivity", "kind": "completed",
                       "agent_path": handle, "agent_thread_id": child_id})
                completed[handle] = child_id
                inventory()
                trace = root / (worker + "-trace.json")
                command("worker_runtime_evidence.py", *collector, "--worker-session", child, "--agent", role, "--trace", trace)
                audit = next(row for row in json.loads(packet_path.read_text())["runtime_audits"]
                             if row.get("Worker") == worker)
                self.assertEqual(Path(audit["Trace path"]), trace.resolve())
                if worker != "handoff":
                    command("merge_techops_result.py", "--packet", packet_path, "--agent", role)
                    contract = run["worker_contracts"][role]
                    for field in ("output", "result"):
                        path = Path(contract[field])
                        result_hashes[path] = hashlib.sha256(path.read_bytes()).hexdigest()
                    if contract.get("asset_inventory"):
                        path = Path(contract["asset_inventory"]["output"])
                        result_hashes[path] = hashlib.sha256(path.read_bytes()).hexdigest()
                if native_continuation and index == 0:
                    accepted = json.loads(packet_path.read_text())
                    earlier, parent = parent, provider / ("reopened-" + parent_id + ".jsonl")
                    append(parent, "session_meta", id=parent_id, cwd=str(repository))
                    append(parent, "turn_context", turn_id=str(UUID(int=999)))
                    append(parent, "response_item", role="user", content=[{"type": "input_text", "text":
                        "Continue this run, preserving accepted findings. Do not repeat completed investigation."}])
                    previous_run = run
                    run = json.loads(command("prepare_run.py", "--execution-repository", repository,
                        "--work-item", "DEMO-1", "--playbook", playbook, "--continuation",
                        "--input-manifest", run["run_input_manifest"]["path"]))
                    self.assertEqual(run["run_id"], previous_run["run_id"])
                    self.assertEqual(run["runtime_evidence"]["run_started_at"], previous_run["runtime_evidence"]["run_started_at"])
                    self.assertEqual(run["runtime_evidence"]["identity_sessions"], [str(earlier.resolve())])
                    continued = json.loads(packet_path.read_text())
                    self.assertEqual(continued["worker_results"], accepted["worker_results"])
                    self.assertEqual(continued["evidence"], accepted["evidence"])
                    collector = ("--provider-session", parent, "--parent-thread-id", parent_id,
                                 "--started-at", run["runtime_evidence"]["run_started_at"],
                                 "--ledger", run["runtime_evidence"]["ledger"])
                    append(parent, "response_item", type="function_call", name="mcp__codex_app__read_thread",
                           call_id="continued-worker-status", arguments=json.dumps({"threadId": child_id}))
            closure = root / "runtime_closure.json"
            command("worker_runtime_evidence.py", *collector, "--pending-closure", closure)
            finalize = ("--packet", packet_path, "--closure", closure, "--record", root / "work_record.md",
                        "--coordinator-model-effort", "Not exposed / Not exposed", "--framework-revision",
                        preflight["framework_revision"], "--framework-status", "clean")
            command("finalize_work_record.py", *finalize, "--check-packet")
            command("finalize_work_record.py", *finalize, "--pre-release")
            inventory()
            command("worker_runtime_evidence.py", *collector, "--closure", closure)
            receipt = json.loads(closure.read_text())
            self.assertEqual({row["Provider handle"] for row in receipt["terminal_observations"]}, set(completed))
            command("finalize_work_record.py", *finalize)
            response = root / "handoff_response.md"
            emitted = command("finalize_work_record.py", "--packet", packet_path, "--publish-response", response)
            self.assertEqual(emitted.encode(), response.read_bytes())
            self.assertEqual(json.loads((root / "handoff_delivery.json").read_text())["status"], "verified")
            if continue_to_remediation:
                self.assertIn(playbook, {"feature_delivery", "techops_issue_remediation"})
                approved_plan = (root / "implementation_plan.md").read_bytes()
                prior_checks = json.loads(packet_path.read_text()).get("techops_checks")
                append(parent, "response_item", role="user", content=[{"type": "input_text", "text":
                    "The exact prepared implementation plan is approved for remediation. Preserve its scope."}])
                prior_run_id = run["run_id"]
                run = json.loads(command("prepare_run.py", "--execution-repository", repository,
                    "--work-item", "DEMO-1", "--playbook", playbook, "--continuation",
                    "--remediation-reentry", "--approval-reference", "Explicit approval of the exact plan",
                    "--input-manifest", run["run_input_manifest"]["path"]))
                self.assertNotEqual(run["run_id"], prior_run_id)
                self.assertEqual((root / "implementation_plan.md").read_bytes(), approved_plan)
                packet_path = Path(run["finalization_packet"])
                current_packet = json.loads(packet_path.read_text())
                self.assertEqual(current_packet["reentry"]["Prior run ID"], prior_run_id)
                self.assertEqual(current_packet["reentry"]["Approved plan SHA256"], hashlib.sha256(approved_plan).hexdigest())
                if playbook == "techops_issue_remediation":
                    self.assertEqual(current_packet.get("techops_checks"), prior_checks)
                    self.assertEqual(set(run["worker_contracts"]), {"implementer", "reviewer", "tester", "documenter"})
                completed.clear()
                statuses.clear()
                remediation_collector = ("--provider-session", parent, "--parent-thread-id", parent_id,
                    "--started-at", run["runtime_evidence"]["run_started_at"],
                    "--ledger", run["runtime_evidence"]["ledger"])
                remediation_roles = (("implementer", "implement", "IM"),
                                     ("reviewer", "review", "RV"), ("tester", "validate", "TE"))
                delivery_threads = {}
                base_revision = subprocess.check_output(["git", "-C", str(repository), "rev-parse", "HEAD"],
                    text=True).strip()
                review_text = validation_text = ""
                test_command = "python -c 'assert increment(2)==3 and increment(0)==1 and increment(-2)==-1'"
                delivery_dispatches = {}
                for delivery_index, (agent, worker, namespace) in enumerate(remediation_roles, 1):
                    assignment = root / (worker + "-assignment.json")
                    assigned_inputs = [str(root / "implementation_plan.md"), str(source),
                                       str(source.parent / "test_counter.py")]
                    if agent == "tester":
                        assigned_inputs.extend([str(root / "code_review.md"), str(root / "implementation_plan.md")])
                    assignment.write_text(json.dumps({"objective": "Complete the approved counter remediation role",
                        "input_paths": assigned_inputs}))
                    activation = root / (worker + "-activation.txt")
                    guarded = json.loads(command("validate_worker_runtime.py", "--activation-packet-bundle",
                        run["activation_packet_bundle"]["path"], "--expected-agent", agent,
                        "--expected-bundle-sha256", run["activation_packet_bundle"]["sha256"],
                        "--assignment", assignment, "--dispatch-file", activation))
                    handle = "/root/" + worker
                    thread = str(UUID(int=700 + delivery_index))
                    child = provider / (worker + "-remediation.jsonl")
                    delivery_threads[agent] = thread
                    delivery_dispatches[agent] = {"assignment": assignment, "activation": activation,
                        "guarded": guarded, "handle": handle, "thread": thread, "child": child}
                    append(parent, "response_item", type="function_call", namespace="collaboration",
                        name="spawn_agent", call_id="remediation-spawn-" + worker,
                        arguments=json.dumps({"task_name": worker, "message": guarded["activation_message"],
                            **guarded["launch_arguments"]}))
                    append(parent, "event_msg", item={"type": "SubAgentActivity", "kind": "started",
                        "agent_path": handle, "agent_thread_id": thread})
                    statuses[handle] = "running"
                    completed[handle] = thread
                inventory()
                activation_result = json.loads(command("worker_runtime_evidence.py", *remediation_collector))
                self.assertEqual(activation_result.get("profile_activation", {}).get("status"), "activated",
                    json.dumps(activation_result, sort_keys=True))
                for delivery_index, (agent, worker, namespace) in enumerate(remediation_roles, 1):
                    dispatch = delivery_dispatches[agent]
                    activation, guarded = dispatch["activation"], dispatch["guarded"]
                    handle, thread, child = dispatch["handle"], dispatch["thread"], dispatch["child"]
                    child.write_text("")
                    append(child, "session_meta", id=thread, cwd=str(repository))
                    append(child, "response_item", type="function_call", name="exec_command", call_id="bootstrap",
                        arguments=json.dumps({"cmd": "cat " + str(activation), "workdir": str(repository)}))
                    append(child, "response_item", type="function_call_output", call_id="bootstrap",
                        output=activation.read_text())
                    append(child, "turn_context", turn_id=str(UUID(int=800 + delivery_index)),
                        model=guarded["launch_arguments"]["model"],
                        effort=guarded["launch_arguments"]["reasoning_effort"])
                    if agent == "implementer":
                        source_guard = json.loads(command("validate_worker_runtime.py", "--before-source-change",
                            packet_path, "--implementer-handle", handle, "--provider-status", "running"))
                        self.assertEqual(source_guard["status"], "allowed")
                        source.write_text("def increment(value):\n    return value + 1\n")
                        (source.parent / "test_counter.py").write_text(
                            "from counter import increment\n\n"
                            "def test_increment():\n"
                            "    assert increment(2) == 3\n"
                            "    assert increment(0) == 1\n"
                            "    assert increment(-2) == -1\n")
                        plan_text = (root / "implementation_plan.md").read_text()
                        plan_text = plan_text.replace(
                            "| Counter function and regression fixture | Increment all supported numeric values | planned |",
                            "| Counter function and regression fixture | Increment all supported numeric values | verified |",
                        )
                        (root / "implementation_plan.md").write_text(plan_text)
                        tested = subprocess.run([sys.executable, "-c",
                            "import sys; sys.path.insert(0, " + repr(str(source.parent)) + "); "
                            "from counter import increment; assert increment(2)==3 and increment(0)==1 and increment(-2)==-1"],
                            cwd=repository, capture_output=True, text=True)
                        self.assertEqual(tested.returncode, 0, tested.stdout + tested.stderr)
                        summary_text = "Implemented addition and exercised positive, zero, and negative inputs."
                    elif agent == "reviewer":
                        candidate = candidate_fingerprint(repository, base_revision, [])
                        candidate_fields = (f"Repository: {repository}\nBase revision: {base_revision}\n"
                            f"Candidate SHA256: {candidate}\nUntracked candidate files: []\n")
                        behavior = "Counter increment"
                        review_values = [behavior, "Counter requirement IN-001", "counter.increment",
                            "The implementation decremented values", "The candidate adds one and preserves input type",
                            "Inspected source and positive, zero, and negative cases", "src/counter/test_counter.py",
                            "verified"]
                        affected_values = [behavior, "counter.py; test_counter.py", test_command,
                            "Read the approved plan, implementation diff, and existing test fixture", "pass",
                            "Executed all three expected-value assertions against the candidate",
                            "Reviewer: independently verified implementation and test coverage"]
                        review_text = ("# Code Review\n## Scope\n" + candidate_fields +
                            "Disposition: accepted\n## Behavior Review\n" + render_table(REVIEW_COLUMNS, review_values) +
                            "## Affected Tests\n" + render_table(AFFECTED_TEST_COLUMNS, affected_values) +
                            "## Findings\nNo confirmed candidate defects.\n## Validation\n" +
                            render_table(VALIDATION_COLUMNS, ["Candidate assertions", "pass", candidate,
                                "Positive, zero, and negative values",
                                "Deployment was not tested; Tester to verify the exact candidate"]) +
                            "## Reconciliation and Next Action\nThe approved plan is implemented; Tester owns the final candidate check.\n")
                        summary_text = "Accepted the exact implementation candidate and required regression cases."
                    else:
                        candidate = candidate_fingerprint(repository, base_revision, [])
                        candidate_fields = (f"Repository: {repository}\nBase revision: {base_revision}\n"
                            f"Candidate SHA256: {candidate}\nUntracked candidate files: []\n")
                        behavior = "Counter increment"
                        review_values = [behavior, "counter.py and explicit requirement IN-001", "counter.increment",
                            "The implementation decremented values", "The candidate adds one", "Three numeric input cases",
                            "src/counter/test_counter.py positive, zero, and negative assertions", "verified"]
                        affected_values = [behavior, "counter.py; test_counter.py", test_command,
                            "Read the approved plan, implementation diff, and existing test fixture", "pass",
                            "Executed all three expected-value assertions against the candidate",
                            "Reviewer: independently verified implementation and test coverage"]
                        validation_text = ("# Validation Report\n## Candidate\n" + candidate_fields +
                            "## Behavior Coverage\n" + render_table(COVERAGE_COLUMNS, [behavior, test_command, "pass",
                                candidate, "No remaining local behavior gap", "Service owner: release through normal checks"]) +
                            "## Affected Tests\n" + render_table(AFFECTED_TEST_COLUMNS, affected_values) +
                            "## Release Follow-up\nNo release checks required.\n")
                        summary_text = "Passed all three candidate assertions for positive, zero, and negative inputs."
                    evidence_id = f"E-{namespace}-001"
                    summary = {**dict.fromkeys(template["worker_results"][0], "Current remediation result"),
                        "Worker": worker, "Outcome": "complete", "Confidence": "High",
                        "Unique contribution": summary_text, "Evidence / claim refs": evidence_id,
                        "Uncertainties / blockers": "Production release and monitoring are outside this local fixture.",
                        "Actual model/effort": guarded["launch_arguments"]["model"] + " / " +
                            guarded["launch_arguments"]["reasoning_effort"], "Usage/credits": "Not exposed"}
                    evidence = {**dict.fromkeys(template["evidence"][0], "Current candidate evidence"),
                        "Evidence ID": evidence_id, "Source": str(source if agent == "implementer" else
                            root / ("code_review.md" if agent == "reviewer" else "validation_report.md")),
                        "Summary": summary_text, "Confidence": "High",
                        "Uncertainty": "Production release is not part of this fixture.", "Status": "Verified"}
                    result = {"run_id": run["run_id"], "worker_result": summary, "evidence": [evidence],
                        "claims": [], "decisions": [], "actions": []}
                    if agent == "reviewer":
                        result["output"] = review_text
                    elif agent == "tester":
                        result["output"] = validation_text
                    else:
                        result["output"] = "Implemented the plan in the existing counter and test files."
                    append(child, "response_item", type="message", role="assistant", phase="final_answer",
                        content=[{"type": "output_text", "text": json.dumps({"output": result["output"],
                            "result": result})}])
                    statuses[handle] = "completed"
                    inventory()
                    trace = root / (worker + "-remediation-trace.json")
                    command("worker_runtime_evidence.py", *remediation_collector, "--worker-session", child,
                        "--agent", agent, "--trace", trace)
                    merged = subprocess.run([sys.executable, str(package / "scripts/merge_techops_result.py"),
                        "--packet", str(packet_path), "--agent", agent, "--trace", str(trace)], cwd=package,
                        capture_output=True, text=True, timeout=60)
                    self.assertEqual(merged.returncode, 0, merged.stdout + merged.stderr)
                packet = json.loads(packet_path.read_text())
                staged = json.loads(command("stage_documenter_packet.py", "--packet", packet_path,
                    "--coordinator-model-effort", "Not exposed / Not exposed", "--prompt-conformance", "pass",
                    "--engineering-outcome", "solved"))
                self.assertEqual(staged["state"], "handoff")
                doc_assignment = root / "documenter-assignment.json"
                doc_assignment.write_text(json.dumps({"objective": "Complete the accepted implementation handoff",
                    "input_paths": [str(packet_path), str(root / "implementation_plan.md"),
                                    str(root / "code_review.md"), str(root / "validation_report.md")]}))
                doc_activation = root / "documenter-activation.txt"
                doc_guard = json.loads(command("validate_worker_runtime.py", "--activation-packet-bundle",
                    run["activation_packet_bundle"]["path"], "--expected-agent", "documenter",
                    "--expected-bundle-sha256", run["activation_packet_bundle"]["sha256"],
                    "--assignment", doc_assignment, "--dispatch-file", doc_activation))
                doc_handle, doc_thread = "/root/handoff", str(UUID(int=799))
                append(parent, "response_item", type="function_call", namespace="collaboration",
                    name="spawn_agent", call_id="remediation-spawn-documenter",
                    arguments=json.dumps({"task_name": "handoff", "message": doc_guard["activation_message"],
                        **doc_guard["launch_arguments"]}))
                append(parent, "event_msg", item={"type": "SubAgentActivity", "kind": "started",
                    "agent_path": doc_handle, "agent_thread_id": doc_thread})
                statuses[doc_handle] = "running"
                completed[doc_handle] = doc_thread
                inventory()
                doc_child = provider / "handoff-remediation.jsonl"
                doc_child.write_text("")
                append(doc_child, "session_meta", id=doc_thread, cwd=str(repository))
                append(doc_child, "response_item", type="function_call", name="exec_command", call_id="bootstrap",
                    arguments=json.dumps({"cmd": "cat " + str(doc_activation), "workdir": str(repository)}))
                append(doc_child, "response_item", type="function_call_output", call_id="bootstrap",
                    output=doc_activation.read_text())
                doc_binding = run["bindings"]["documenter"]
                append(doc_child, "turn_context", turn_id=str(UUID(int=801)), model=doc_binding["model"],
                    effort=doc_binding["effort"])
                packet = json.loads(packet_path.read_text())
                doc_evidence = {**dict.fromkeys(template["evidence"][0], "Current-run handoff evidence"),
                    "Evidence ID": "E-DOC-001", "Source": str(root / "handoff_response.md"),
                    "Summary": "The Documenter recorded the accepted implementation and validation handoff.",
                    "Confidence": "High", "Uncertainty": "Live release is outside this fixture.", "Status": "Verified"}
                doc_worker = {**dict.fromkeys(template["workers"][0], "Recorded from guarded dispatch"),
                    "Worker": "handoff", "Role": "documenter", "Assigned inputs": "Accepted packet, plan, review, validation",
                    "Mode": "remediation", "Depth": "standard", "Skills": "work_record_maintenance",
                    "Tools": "work_record_read, work_record_write, artifact_write",
                    "Configured model/effort": doc_binding["model"] + " / " + doc_binding["effort"],
                    "Provider-observed model/effort": doc_binding["model"] + " / " + doc_binding["effort"],
                    "Outcome": "complete", "Confidence": "High"}
                doc_result = {**dict.fromkeys(template["worker_results"][0], "Documenter handoff"),
                    "Worker": "handoff", "Outcome": "complete", "Confidence": "High",
                    "Unique contribution": "Persisted accepted handoff with plan, review, and validation artifacts.",
                    "Evidence / claim refs": "E-DOC-001", "Uncertainties / blockers": "Production release is outside scope.",
                    "Actual model/effort": doc_binding["model"] + " / " + doc_binding["effort"],
                    "Usage/credits": "Not exposed"}
                packet["workers"].append(doc_worker)
                packet["worker_results"].append(doc_result)
                packet["evidence"].append(doc_evidence)
                for namespace, claim, evidence_id in (
                    ("IM", "The approved increment change is implemented in the execution source.", "E-IM-001"),
                    ("RV", "The current implementation satisfies the approved increment behavior.", "E-RV-001"),
                    ("TE", "The required positive, zero, and negative cases pass on the candidate.", "E-TE-001"),
                    ("DOC", "The implementation and local validation handoff is recorded.", "E-DOC-001"),
                ):
                    packet["claims"].append({"Claim ID": f"CL-{namespace}-001", "Claim": claim,
                        "Evidence refs": evidence_id, "Confidence": "High", "Uncertainty": "None",
                        "Status": "Supported"})
                packet["decisions"].append({"Decision ID": "DE-DEL-001",
                    "Decision": "Accept the approved increment correction for local delivery and release follow-up.",
                    "Claim refs": "CL-IM-001, CL-RV-001, CL-TE-001, CL-DOC-001",
                    "Owner": "Coordinator", "Status": "Accepted"})
                packet["actions"].append({"Action ID": "A-DEL-001",
                    "Action": "Run the normal release and monitoring checks.", "Decision ref": "DE-DEL-001",
                    "Owner": "Service owner", "Status": "Proposed"})
                handoff_artifacts = ["implementation_plan.md", "code_review.md", "validation_report.md"]
                durable_outputs = [("code_review.md", "Accepted", "Independent implementation review"),
                    ("validation_report.md", "Passed", "Current candidate validation"),
                    ("implementation_plan.md", "Implemented", "Approved plan and execution record")]
                if playbook == "feature_delivery":
                    handoff_artifacts.append("asset_manifest.json")
                    durable_outputs.append(("asset_manifest.json", "Passed", "Feature input inventory"))
                packet["handoff"].update({"workflow_result": "The approved counter correction passed local validation and is ready for release checks.",
                    "implementation_plan": str(root / "implementation_plan.md"),
                    "established": ["The source now increments; positive, zero, and negative assertions pass."],
                    "best_current_explanations": [], "next_action": {"owner": "Service owner",
                        "action": "Run the normal release and monitoring checks.",
                        "complete_when": "The correction is deployed and monitored."},
                    "artifacts": [str(root / name) for name in handoff_artifacts],
                    "execution": playbook + " remediation completed; external release was not performed.",
                    "provenance": "plugin ai-engineering-workflows " + preflight["plugin_version"] +
                        "; framework revision " + preflight["framework_revision"] + "; " + playbook + " 0.5.33"})
                for name, status, purpose in durable_outputs:
                    packet["durable_artifacts"].append({"Artifact": name, "Path": str(root / name),
                        "Status": status, "Purpose": purpose})
                if playbook == "feature_delivery":
                    packet["playbook_selection"]["Primary goal"] = "Implementation planning"
                packet_path.write_text(json.dumps(packet, indent=2) + "\n")
                append(doc_child, "response_item", type="message", role="assistant", phase="final_answer",
                    content=[{"type": "output_text", "text": "The accepted packet and handoff artifacts are complete."}])
                statuses[doc_handle] = "completed"
                inventory()
                command("worker_runtime_evidence.py", *remediation_collector, "--worker-session", doc_child,
                    "--agent", "documenter", "--trace", root / "documenter-remediation-trace.json")
                closure = root / "runtime_closure.json"
                finalization = ("--packet", packet_path, "--closure", closure, "--record", root / "work_record.md",
                    "--coordinator-model-effort", "Not exposed / Not exposed", "--framework-revision",
                    preflight["framework_revision"], "--framework-status", "clean")
                if blocked_runtime_snapshot:
                    inventory(omit_handles={"/root/handoff"})
                    blocked_args = ("--blocked-closure", closure, "--blocker",
                        "post-dispatch provider inventory omitted /root/handoff and targeted status could not be verified")
                    missing_probe = command("worker_runtime_evidence.py", *remediation_collector,
                        *blocked_args, expected=2)
                    self.assertIn("targeted_worker_status_failure_evidence_required:/root/handoff", missing_probe)
                    unsupported = "targeted-status-unverifiable"
                    append(parent, "response_item", type="function_call", name="mcp__codex_app__read_thread",
                           call_id=unsupported, arguments=json.dumps({"threadId": completed["/root/handoff"]}))
                    append(parent, "response_item", type="function_call_output", call_id=unsupported,
                           output=json.dumps({"status": "completed"}))
                    unsupported_closure = root / "runtime_closure-unverifiable.json"
                    unsupported_receipt = command("worker_runtime_evidence.py", *remediation_collector,
                        "--blocked-closure", unsupported_closure, "--blocker",
                        "targeted provider response omitted required status metadata")
                    self.assertEqual(json.loads(unsupported_receipt)["status"], "recorded")
                    unverifiable_row = json.loads(unsupported_closure.read_text())["runtime_closure"][0]
                    self.assertEqual(unverifiable_row["Runtime status"], "Blocked")
                    self.assertIn("targeted read_thread was unverifiable for /root/handoff",
                                  unverifiable_row["Closure evidence or blocker"])
                    self.assertIn("targeted_status_metadata_unavailable",
                                  unverifiable_row["Closure evidence or blocker"])
                    returned = "targeted-status-returned"
                    append(parent, "response_item", type="function_call", name="mcp__codex_app__read_thread",
                           call_id=returned, arguments=json.dumps({"threadId": completed["/root/handoff"]}))
                    dispatch_at = max(row["Last dispatch at"] for row in json.loads(
                        Path(remediation_collector[-1]).read_text())["events"]
                        if row.get("Provider handle") == "/root/handoff")
                    dispatch_time = datetime.fromisoformat(dispatch_at.replace("Z", "+00:00"))
                    append(parent, "response_item", type="function_call_output", call_id=returned,
                        output=json.dumps({"schemaVersion": 1,
                            "thread": {"id": completed["/root/handoff"], "status": {"type": "idle"}},
                            "turns": [{"id": str(UUID(int=803)), "status": "completed",
                                "startedAt": (dispatch_time + timedelta(milliseconds=1)).timestamp(),
                                "completedAt": (dispatch_time + timedelta(milliseconds=2)).timestamp()}]}))
                    returned_probe = command("worker_runtime_evidence.py", *remediation_collector,
                        *blocked_args, expected=2)
                    self.assertIn("worker_runtime_terminal_receipt_available: use --closure", returned_probe)
                    probe = "targeted-status-unavailable"
                    append(parent, "response_item", type="function_call", name="mcp__codex_app__read_thread",
                           call_id=probe, arguments=json.dumps({"threadId": completed["/root/handoff"]}))
                    append(parent, "response_item", type="function_call_output", call_id=probe,
                           output=json.dumps({"error": "permission_denied"}))
                    blocked_receipt = json.loads(command("worker_runtime_evidence.py", *remediation_collector,
                        *blocked_args))
                    self.assertEqual(blocked_receipt["status"], "recorded")
                    closure_rows = json.loads(closure.read_text())["runtime_closure"]
                    self.assertEqual(len(closure_rows), 1)
                    self.assertEqual(closure_rows[0]["Runtime status"], "Blocked")
                    self.assertEqual(closure_rows[0]["Remaining active handles"], "Unknown")
                    self.assertIn("/root/handoff", closure_rows[0]["Closure evidence or blocker"])
                    blocked = command("finalize_work_record.py", *finalization, "--blocked-runtime-snapshot")
                    self.assertIn("TechOps remediation blocked work record: saved; runtime release unverified", blocked)
                    record_text = (root / "work_record.md").read_text()
                    self.assertIn("| Workflow outcome | blocked |", record_text)
                    self.assertIn("| Engineering outcome | solved |", record_text)
                    self.assertIn("worker_runtime_release_unavailable", record_text)
                elif targeted_runtime_observation:
                    inventory(omit_handles={"/root/handoff"})
                    command("worker_runtime_evidence.py", *remediation_collector, "--pending-closure", closure)
                    command("finalize_work_record.py", *finalization, "--check-packet")
                    command("finalize_work_record.py", *finalization, "--pre-release")
                    inventory(omit_handles={"/root/handoff"})
                    ledger = json.loads(Path(remediation_collector[-1]).read_text())
                    dispatch_at = max(row["Last dispatch at"] for row in ledger["events"]
                                      if row.get("Provider handle") == "/root/handoff")
                    dispatch_time = datetime.fromisoformat(dispatch_at.replace("Z", "+00:00"))
                    started_at = dispatch_time + timedelta(milliseconds=1)
                    completed_at = dispatch_time + timedelta(milliseconds=2)
                    targeted = "targeted-status-terminal"
                    append(parent, "response_item", type="function_call", name="mcp__codex_app__read_thread",
                           call_id=targeted, arguments=json.dumps({"threadId": completed["/root/handoff"]}))
                    append(parent, "response_item", type="function_call_output", call_id=targeted,
                        output=json.dumps({"schemaVersion": 1,
                            "thread": {"id": completed["/root/handoff"], "status": {"type": "idle"}},
                            "turns": [{"id": str(UUID(int=802)), "status": "completed",
                                "startedAt": started_at.timestamp(), "completedAt": completed_at.timestamp()}]}))
                    command("worker_runtime_evidence.py", *remediation_collector, "--closure", closure)
                    receipt = json.loads(closure.read_text())
                    handoff_observation = next(row for row in receipt["terminal_observations"]
                        if row["Provider handle"] == "/root/handoff")
                    self.assertEqual(handoff_observation["Status source"], "read_thread")
                    self.assertEqual(handoff_observation["Latest turn status"], "completed")
                    self.assertEqual(handoff_observation["Thread status"], "idle")
                    command("finalize_work_record.py", *finalization)
                else:
                    rejected_block = command("worker_runtime_evidence.py", *remediation_collector,
                        "--blocked-closure", closure, "--blocker", "Provider inventory did not expose status",
                        expected=2)
                    self.assertIn("worker_runtime_terminal_receipt_available", rejected_block)
                    self.assertFalse(closure.exists())
                    command("worker_runtime_evidence.py", *remediation_collector, "--pending-closure", closure)
                    command("finalize_work_record.py", *finalization, "--check-packet")
                    command("finalize_work_record.py", *finalization, "--pre-release")
                    inventory()
                    command("worker_runtime_evidence.py", *remediation_collector, "--closure", closure)
                    receipt = json.loads(closure.read_text())
                    self.assertEqual({row["Provider handle"] for row in receipt["terminal_observations"]},
                        {"/root/implement", "/root/review", "/root/validate", "/root/handoff"})
                    command("finalize_work_record.py", *finalization)
                remediation_response = root / "handoff_response.md"
                emitted = command("finalize_work_record.py", "--packet", packet_path,
                    "--publish-response", remediation_response)
                self.assertEqual(emitted.encode(), remediation_response.read_bytes())
                self.assertEqual(json.loads((root / "handoff_delivery.json").read_text())["status"], "verified")
            if late_parent_violation:
                append(parent, "response_item", type="custom_tool_call", name="exec", input=
                       'await tools.exec_command({cmd:"cat /repo/.codex/memories/MEMORY.md"})')
                before = packet_path.read_bytes()
                late_trace = root / "late-documenter-trace.json"
                blocked = command("worker_runtime_evidence.py", *collector, "--worker-session", child,
                                  "--agent", role, "--trace", late_trace, expected=2)
                self.assertIn("parent_context_nonconformant", blocked)
                self.assertEqual(json.loads(late_trace.read_text())["audit"]["status"], "passed")
                self.assertNotIn(role, json.loads(Path(run["runtime_evidence"]["ledger"]).read_text()).get("rejected_results", {}))
                self.assertEqual(packet_path.read_bytes(), before)
                blocked = command("merge_techops_result.py", "--packet", packet_path, "--agent", roles[0][1], expected=2)
                self.assertIn("parent_context_nonconformant", blocked)
                self.assertEqual(packet_path.read_bytes(), before)
                blocked = command("finalize_work_record.py", *finalize, "--check-packet", expected=2)
                self.assertIn("parent_context_nonconformant", blocked)
                blocked = command("finalize_work_record.py", "--packet", packet_path, "--publish-response", response, expected=2)
                self.assertIn("parent_context_nonconformant", blocked)
                self.assertFalse((root / "handoff_delivery.json").exists())
                Path(run["runtime_evidence"]["ledger"]).unlink()
                command("finalize_work_record.py", "--packet", packet_path, "--workflow-failure",
                        "parent_context_nonconformant: current parent read unassigned memory", expected=2)
                failure = root / "handoff_failure.md"
                published = command("finalize_work_record.py", "--packet", packet_path, "--publish-response", failure)
                self.assertEqual(published.encode(), failure.read_bytes())
                receipt = json.loads((root / "finalization_failure.json").read_text())
                self.assertEqual(receipt["runtime_closure"], "terminal")
                self.assertTrue(Path(run["runtime_evidence"]["ledger"]).is_file())
                self.assertEqual(json.loads((root / "handoff_delivery.json").read_text())["status"], "verified")
            for result_path, digest in result_hashes.items():
                self.assertEqual(hashlib.sha256(result_path.read_bytes()).hexdigest(), digest)
            for rejected, original in rejected_traces.items():
                self.assertEqual(rejected.read_bytes(), original)
            if recover_failed_worker:
                self.assertEqual({row["Provider handle"]: row["Provider status"] for row in receipt["terminal_observations"]}["/root/failed_original"], "failed")
            if not continue_to_remediation:
                self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), source_hash)
            changed = subprocess.run(["git", "-C", str(repository), "status", "--porcelain"], capture_output=True, text=True, check=True)
            if continue_to_remediation:
                self.assertEqual({line[3:] for line in changed.stdout.splitlines()},
                    {str(source.relative_to(repository)), "src/counter/test_counter.py"})
            else:
                self.assertEqual(changed.stdout, "")


if __name__ == "__main__":
    unittest.main()
