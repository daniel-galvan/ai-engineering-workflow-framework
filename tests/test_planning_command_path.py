"""Whole planning command paths; only worker output and native provider events are simulated."""

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from scripts.review_evidence import PLAN_COLUMNS, DESIGN_COLUMNS, SOLUTION_COLUMNS
from tests import test_packaged_lifecycle as packaging


class PlanningCommandPath(unittest.TestCase):
    def test_techops_ready_plan_through_actual_shipped_commands(self):
        self.planning_path("techops_issue_remediation")

    def test_feature_ready_plan_through_actual_shipped_commands(self):
        self.planning_path("feature_delivery")

    def planning_path(self, playbook):
        with tempfile.TemporaryDirectory() as directory:
            package = packaging.PackagedLifecycle().package(directory)
            repository = Path(directory) / "repository"
            repository.mkdir()
            source = repository / "counter.py"
            source.write_text("def increment(value):\n    return value - 1\n")
            (repository / "test_counter.py").write_text("from counter import increment\n\ndef test_increment():\n    assert increment(2) == 3\n")
            (repository / ".gitignore").write_text(".thoughts/\n")
            for arguments in (("init", "-q"), ("config", "user.name", "Fixture"),
                              ("config", "user.email", "fixture@example.invalid"), ("add", "."),
                              ("commit", "-qm", "Initial counter fixture")):
                subprocess.run(["git", "-C", str(repository), *arguments], check=True, capture_output=True)
            source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            provider = Path(directory) / "provider"
            provider.mkdir()
            parent = provider / "parent.jsonl"
            parent_id, turn_id = str(UUID(int=1)), str(UUID(int=2))

            def append(path, kind, **payload):
                with path.open("a") as stream:
                    stream.write(json.dumps({"timestamp": datetime.now(timezone.utc).isoformat(),
                                             "type": kind, "payload": payload}) + "\n")

            append(parent, "session_meta", id=parent_id, cwd=str(repository))
            append(parent, "turn_context", turn_id=turn_id)
            append(parent, "response_item", role="user", content=[{"type": "input_text", "text":
                "Use only this controlled offline case and supplied source. Plan DEMO-1 in standard/planning: increment(2) returns 1 and must return 3. "
                "Read-only source inspection; do not run product tests or builds."}])

            def command(script, *arguments):
                result = subprocess.run([sys.executable, str(package / "scripts" / script), *map(str, arguments)],
                                        cwd=package, capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, script + "\n" + result.stdout + result.stderr)
                return result.stdout

            preflight = json.loads(command("run_preflight.py", "--provider-session", parent))
            inputs = Path(directory) / "inputs.json"
            inputs.write_text(json.dumps({"inputs": [{"Input ID": "IN-001", "Input or artifact":
                "Counter defect: increment(2) returns 1; expected 3. Planning only, standard profile.",
                "Source or path": "User", "Authority": "User", "Status": "Verified"},
                {"Input ID": "IN-002", "Input or artifact": "Jira DEMO-1 supplied offline record: no attachments or remote links",
                 "Source or path": "Jira DEMO-1", "Authority": "User supplied fixture", "Status": "Verified"}]}))
            run = json.loads(command("prepare_run.py", "--execution-repository", repository, "--work-item", "DEMO-1",
                "--playbook", playbook, "--input-manifest", inputs,
                "--provider-session", parent, "--lifecycle", "planning"))
            root, packet_path = Path(run["artifact_root"]), Path(run["finalization_packet"])
            template = json.loads((package / "templates/finalization_packet.json").read_text())
            roles = (("issue-evidence", "current_state_investigator", "ISS"),
                     ("failure-path", "dependency_analyst", "FP"),
                     ("fix-design", "solution_architect", "FD"), ("handoff", "documenter", "DOC"))
            if playbook == "feature_delivery":
                roles = (("feature-context", "current_state_investigator", "FC"),
                         ("impact-analysis", "dependency_analyst", "IA"),
                         ("feature-design", "solution_architect", "FD"), ("handoff", "documenter", "DOC"))
            first_namespace, second_namespace = roles[0][2], roles[1][2]
            completed, summaries, result_hashes = {}, {}, {}

            def inventory():
                call = "inventory-" + str(len(completed)) + "-" + datetime.now().strftime("%H%M%S%f")
                append(parent, "response_item", type="function_call", namespace="collaboration", name="list_agents",
                       call_id=call, arguments="{}")
                append(parent, "response_item", type="function_call_output", call_id=call,
                       output=json.dumps({"agents": [{"agent_name": handle, "agent_status": {"completed": "Done"}}
                                                    for handle in completed]}))

            collector = ("--provider-session", parent, "--parent-thread-id", parent_id,
                         "--started-at", run["runtime_evidence"]["run_started_at"],
                         "--ledger", run["runtime_evidence"]["ledger"])
            for index, (worker, role, namespace) in enumerate(roles):
                assignment = root / (worker + "-assignment.json")
                assignment.write_text(json.dumps({"objective": "Complete the current counter planning stage: " + worker,
                    "input_paths": [str(packet_path), str(source)]}))
                activation = root / (worker + "-activation.txt")
                guarded = json.loads(command("validate_worker_runtime.py", "--activation-packet-bundle",
                    run["activation_packet_bundle"]["path"], "--expected-agent", role, "--expected-bundle-sha256",
                    run["activation_packet_bundle"]["sha256"], "--assignment", assignment, "--dispatch-file", activation))
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
                if role == "solution_architect":
                    fixture_path = repository / "test_counter.py"
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
                        evidence["Source"] = str(repository / "test_counter.py")
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
                    contract = run["worker_contracts"][role]
                    Path(contract["output"]).write_text("# Current counter planning\n" + evidence["Summary"] + "\n")
                    Path(contract["result"]).write_text(json.dumps(result))
                    result_path = Path(contract["result"])
                    result_hashes[result_path] = hashlib.sha256(result_path.read_bytes()).hexdigest()
                    if playbook == "feature_delivery" and index == 0:
                        # Simulated context-worker inventory of the explicitly supplied offline Jira record.
                        (root / "asset_manifest.json").write_text(json.dumps({
                            "schema_version": 1, "status": "passed", "work_item": "DEMO-1", "sources": [{
                                "source_id": "SRC-JIRA", "input_id": "IN-002", "kind": "jira_issue_attachments",
                                "locator": "Jira DEMO-1 attachments", "requiredness": "required", "discovery_status": "empty",
                                "discovery_method": "Read complete attachment inventory in supplied offline Jira record",
                                "remote_link_inventory": {"status": "empty", "method": "Read supplied remote link inventory", "locators": []},
                                "limitation": "None", "asset_ids": [], "evidence_refs": ["E-FC-001"]}], "assets": [],
                            "gate": {"inventory_complete": True, "all_assets_accounted_for": True,
                                "all_available_assets_reviewed": True, "all_material_assets_linked": True,
                                "reviewed_before_plan": True, "unresolved_asset_ids": [], "blocking_source_ids": []}}))
                else:
                    # Simulated Documenter output preserves accepted tables and generated Coordinator audits.
                    packet = json.loads(packet_path.read_text())
                    packet["work_item"]["Title"] = "Correct the counter increment"
                    packet["playbook_selection"].update({"Primary evidence": "Current source and supplied defect",
                        "Primary goal": "Implementation planning", "Closest alternative": "Feature Delivery",
                        "Why this playbook": "A bounded defect in an existing numeric operation"})
                    packet["identity"].update({"Evaluation run ID": "Not applicable", "Requested profile": "standard",
                        "Activated profile": "standard", "Executed profile": "standard", "Profile status": "executed",
                        "State": "ready_for_implementation", "Engineering state": "designed", "Workflow outcome": "completed",
                        "Engineering outcome": "plan_only", "Coordinator model/effort": "Not exposed / Not exposed",
                        "Prompt template / revision / conformance": packet["identity"]["Prompt template / revision / conformance"].replace("pending", "pass")})
                    packet["finalization"].update({"Concurrent-run decision": "Independent temporary fixture repository",
                        "Active related run or work item": "None", "Related-run check": "The fixture owns this isolated repository",
                        "Final reconciliation": "Accepted analysis preserved; runtime closure pending Coordinator receipt",
                        "Finalization schema": "Pending"})
                    packet["workers"] = [{"Worker": name, "Role": actor, "Assigned inputs": "IN-001",
                        "Mode": "planning", "Depth": "standard", "Skills": "Prepared role instructions",
                        "Tools": "exec_command, apply_patch", "Capacity": "One worker handle", "Configured model/effort":
                        run["bindings"][actor]["model"] + " / " + run["bindings"][actor]["effort"],
                        "Provider-observed model/effort": run["bindings"][actor]["model"] + " / " + run["bindings"][actor]["effort"],
                        "Usage": "Not exposed", "Depends on": "None" if number == 0 else roles[number - 1][0],
                        "Outcome": "complete", "Confidence": "High"} for number, (name, actor, _) in enumerate(roles)]
                    packet["worker_results"] = [row for row in packet["worker_results"] if row.get("Worker")] + [summary]
                    packet["synchronization"] = [{"Stage": "Planning", "Workers launched": ", ".join(summaries),
                        "Launch mode / exception": "Sequential dependency stages", "Worker outcomes": "complete",
                        "Results summarized": "Yes", "Barrier status": "Passed; runtime closure pending"}]
                    plan = root / "implementation_plan.md"
                    def table(heading, columns, cells):
                        return "# " + heading + "\n| " + " | ".join(columns) + " |\n| " + " | ".join(["---"] * len(columns)) + " |\n| " + " | ".join(cells) + " |\n"
                    plan.write_text("---\nstatus: Draft\n---\n# Counter implementation plan\n"
                        "Plan status: Unapproved. Change subtraction to addition and extend the existing regression fixture.\n" +
                        table("Behavior Applicability", PLAN_COLUMNS, ["Counter increment", "User IN-001", f"E-{first_namespace}-001",
                            "Inspected subtraction and supplied increment expectation", "required", "Use existing addition operation"]) +
                        table("Design Justification", DESIGN_COLUMNS, ["Existing numeric operation", "Increment by one",
                            f"E-{second_namespace}-001 confirms subtraction", "Compared direct addition without new state", "Replace the operator",
                            "One operator change; no schema or external system change"]) +
                        table("Complete Solution", SOLUTION_COLUMNS, ["Counter function and regression fixture", "Increment all supported numeric values",
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
                            + preflight["framework_revision"] + " (clean); playbook " + playbook + " 0.5.20."}
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
                if worker != "handoff":
                    command("merge_techops_result.py", "--packet", packet_path, "--agent", role, "--trace", trace)
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
            for result_path, digest in result_hashes.items():
                self.assertEqual(hashlib.sha256(result_path.read_bytes()).hexdigest(), digest)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), source_hash)
            changed = subprocess.run(["git", "-C", str(repository), "status", "--porcelain"], capture_output=True, text=True, check=True)
            self.assertEqual(changed.stdout, "")


if __name__ == "__main__":
    unittest.main()
