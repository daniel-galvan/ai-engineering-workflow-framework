"""Preserved finalize_work_record synthetic regression scenarios."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from scripts.asset_manifest import ASSET_MANIFEST_FILENAME
from scripts.finalize_work_record import (
    FINALIZATION_STATUS_FILENAME,
    ROOT,
    UNAVAILABLE_COORDINATOR_MODEL_EFFORT,
    V22_FIXTURE,
    V28_STABILIZATION_FIXTURE,
    V29_CONTRACT_FAILURE_FIXTURE,
    V31_FIX_DESIGN_FIXTURE,
    V34_FINALIZATION_FIXTURE,
    VALIDATOR,
    _normalize_packet,
    _prepare_blocked_runtime_snapshot,
    _reconcile_runtime_state,
    _update_run_budget,
    _validate_handoff,
    expand_work_record,
    finalize,
    prepare_analytical_failure,
    publish_technical_spike_report,
)
from scripts.planning_contracts import (
    _canonicalize_technical_spike_worker_ids,
    _feature_assessment_reference_errors,
    _feature_delivery_asset_contract_errors,
    _feature_delivery_packet_contract_errors,
    _planning_runtime_closure_errors,
    _technical_spike_packet_contract_errors,
    _techops_planning_contract_errors,
    feature_delivery_pre_handoff_errors,
)
from scripts.review_evidence import PLAN_FIXTURE, REVIEW_FIXTURE, delivery_evidence_fixture
from scripts.specification_assessment import NO_PLAN_MESSAGE, REPORT_NAME
from scripts.validation.frontmatter import document_version as _frontmatter_version


def self_test() -> None:
    sentry_playbook_version = re.search(
        r"^version: (\S+)$",
        (ROOT / "playbooks" / "sentry_issue_remediation.md").read_text(),
        re.MULTILINE,
    ).group(1)
    sentry_prompt_version = re.search(
        r"^version: (\S+)$",
        (ROOT / "templates" / "sentry_issue_run_prompt.md").read_text(),
        re.MULTILINE,
    ).group(1)
    technical_spike_version = re.search(
        r"^version: (\S+)$", (ROOT / "playbooks" / "technical_spike.md").read_text(), re.MULTILINE,
    ).group(1)
    technical_spike_prompt_version = re.search(
        r"^version: (\S+)$", (ROOT / "templates" / "technical_spike_run_prompt.md").read_text(), re.MULTILINE,
    ).group(1)
    packet = {
        "work_item": {"ID": "ITEM-1", "Title": "Test", "Last Updated": "2026-08-27T00:00:00Z"},
        "playbook_selection": {
            "Primary evidence": "Failure report",
            "Primary goal": "Controlled diagnosis",
            "Selected playbook": "Sentry Issue Remediation",
            "Closest alternative": "Incident diagnosis",
            "Why this playbook": "Bounded production-error planning",
        },
        "inputs": [{"Input ID": "IN-001", "Input or artifact": "Failure report", "Source or path": "Current user",
                    "Authority": "Supporting evidence", "Status": "Consumed"}],
        "repositories": [{"Repository role": "Execution", "Declared path": "/tmp/repo", "Resolved path": "/tmp/repo",
                          "Branch / detached": "main", "Full revision": "a" * 40, "Clean status": "Clean",
                          "User-selected ref": "Yes", "Release mapping": "Unknown",
                          "Evidence eligibility": "Accepted"}],
        "identity": {
            "Run ID": "run-001", "Evaluation run ID": "Not applicable",
            "Playbook / version": f"playbooks/sentry_issue_remediation.md / {sentry_playbook_version}",
            "Framework commit / status": f"{'a' * 40} / Clean", "Plugin package / version": "Not applicable",
            "Provider/runtime configuration": "Not provided",
            "Provider configuration source/status": "manual / resolved",
            "Prompt template / revision / conformance": (
                f"templates/sentry_issue_run_prompt.md / {sentry_prompt_version} / pass"
            ),
            "Role-policy baseline ID": "Not applicable", "Role binding manifest": "Not applicable",
            "Provider / model configuration": "Manual / Worker Execution Ledger",
            "Coordinator model/effort": "Not applicable", "Requested profile": "standard",
            "Activated profile": "None", "Executed profile": "None", "Profile status": "blocked",
            "Lifecycle": "planning", "State": "blocked", "Engineering state": "unknown",
            "Workflow outcome": "blocked", "Engineering outcome": "blocked",
        },
        "finalization": {"Concurrent-run decision": "Not applicable", "Active related run or work item": "None",
                         "Related-run check": "Current task", "Durable artifact root": "/tmp/.thoughts/ITEM-1",
                         "Final reconciliation": "Pending; runtime closure not yet reconciled", "Finalization schema": "Passed"},
        "durable_artifacts": [
            {"Artifact": "Work record", "Path": "work_record.md", "Status": "Created", "Purpose": "Terminal handoff"},
            {"Artifact": "runtime_closure.json", "Path": "runtime_closure.json", "Status": "Pending", "Purpose": "Provider receipt"},
        ],
        "workers": [{"Worker": "Coordinator", "Role": "Orchestrator", "Assigned inputs": "IN-001",
                     "Mode": "investigation", "Depth": "standard", "Skills": "workflow", "Tools": "local",
                     "Capacity": "current task", "Configured model/effort": "active session",
                     "Provider-observed model/effort": "Unknown", "Usage": "Unknown", "Depends on": "None",
                     "Outcome": "complete", "Confidence": "High"}],
        "synchronization": [{"Stage": "Initialization", "Workers launched": "None",
                             "Launch mode / exception": "worker_runtime_unavailable", "Worker outcomes": "Not applicable",
                             "Results summarized": "Yes", "Barrier status": "Passed; runtime closure pending/unknown"}],
        "runtime_closure": [{"Run or stage": "Current run", "Receipt owner": "Coordinator",
                             "Completed worker handles": "coordinator",
                             "Runtime status": "Released", "Remaining active handles": "None",
                             "Closure evidence or blocker": "provider release confirmation for coordinator"}],
        "worker_results": [{"Worker": "Coordinator", "Outcome": "blocked", "Confidence": "High",
                            "Unique contribution": "Stopped safely", "Evidence / claim refs": "E-001 / C-001",
                            "Uncertainties / blockers": "Runtime closure pending Coordinator receipt", "Actual model/effort": "Unknown",
                            "Usage/credits": "Unknown"}],
        "evidence": [{"Evidence ID": "E-001", "Source": "runtime check", "Summary": "Runtime absent",
                      "Confidence": "High", "Uncertainty": "None", "Status": "Verified"}],
        "claims": [{"Claim ID": "C-001", "Claim": "Worker graph cannot start", "Evidence refs": "E-001",
                    "Confidence": "High", "Uncertainty": "None", "Status": "Supported"}],
        "decisions": [{"Decision ID": "D-001", "Decision": "Stop without task forks", "Claim refs": "C-001",
                       "Owner": "Coordinator", "Status": "Applied"}],
        "actions": [{"Action ID": "A-001", "Action": "Retry with in-task runtime", "Decision ref": "D-001",
                     "Owner": "User", "Status": "Proposed"}],
        "handoff": {"workflow_result": "Workflow result: Worker runtime unavailable", "implementation_plan": "omitted; run blocked",
                    "established": ["No user-owned tasks were created."], "best_current_explanations": [{
                        "explanation": "The in-task worker runtime was unavailable.",
                        "confidence": "high",
                        "reason": "The provider exposed no worker activation capability.",
                    }], "next_action": {
                        "owner": "User", "action": "Retry when in-task workers are available.",
                        "complete_when": "The worker graph starts in the current task."},
                    "artifacts": ["work_record.md"],
                    "execution": "standard/planning; validation passed; workers not started; source changes none; runtime pending/unknown",
                    "provenance": (
                        f"plugin Not applicable; framework revision {'a' * 40} (clean); "
                        f"playbook sentry_issue_remediation {sentry_playbook_version}."
                    )},
    }
    v28 = json.loads(V28_STABILIZATION_FIXTURE.read_text())
    normalization = v28["packet_normalization"]
    normalization_packet = {
        "identity": {
            "Plugin package / version": normalization["plugin_before"],
            "Prompt template / revision / conformance": normalization["prompt_before"],
        },
        "workers": [
            {"Role": role, "Configured model/effort": "gpt-5.6-luna/high"}
            for role in normalization["roles"]
        ],
    }
    _normalize_packet(normalization_packet, {"runtime_closure": []})
    assert normalization_packet["identity"]["Plugin package / version"] == normalization["plugin_after"]
    assert (
        normalization_packet["identity"]["Prompt template / revision / conformance"]
        == normalization["prompt_after"]
    )
    assert [row["Role"] for row in normalization_packet["workers"]] == list(normalization["roles"].values())
    budget_packet = {"durable_artifacts": [{"Artifact": "Run budget", "Status": "Active"}]}
    _normalize_packet(budget_packet, {"runtime_closure": []}, budget_status="within_budget")
    assert budget_packet["durable_artifacts"][0]["Status"] == "within_budget"
    context_packet = {
        "identity": {"Coordinator model/effort": "Packet-input error: active parent model/effort not exposed"},
        "evidence": [{"Evidence ID": "E-001", "Source": "current user clean-run constraint"}],
    }
    _normalize_packet(context_packet, {"runtime_closure": []})
    assert context_packet["identity"]["Coordinator model/effort"] == UNAVAILABLE_COORDINATOR_MODEL_EFFORT
    assert context_packet["evidence"] == []

    execution_packet = json.loads(json.dumps(packet))
    execution_packet["handoff"]["execution"] = "Planning is read-only; Runtime closure is pending Coordinator."
    _reconcile_runtime_state(execution_packet, execution_packet["runtime_closure"])
    assert "runtime closure is pending" not in execution_packet["handoff"]["execution"].lower()
    assert "runtime released" in execution_packet["handoff"]["execution"].lower()
    execution_packet["identity"]["State"] = "completed"
    execution_packet["handoff"]["execution"] = (
        "standard profile executed; Workflow outcome: incomplete; runtime released"
    )
    _reconcile_runtime_state(execution_packet, execution_packet["runtime_closure"])
    assert "workflow outcome: incomplete" not in execution_packet["handoff"]["execution"].lower()
    assert "workflow outcome: completed" in execution_packet["handoff"]["execution"].lower()
    execution_packet["handoff"]["execution"] = (
        "State handoff; standard profile executed; workflow remains in_progress "
        "pending Coordinator finalizer; runtime released"
    )
    _reconcile_runtime_state(execution_packet, execution_packet["runtime_closure"])
    assert "state handoff" not in execution_packet["handoff"]["execution"].lower()
    assert "workflow remains in_progress" not in execution_packet["handoff"]["execution"].lower()
    assert "terminal bookkeeping finalized" in execution_packet["handoff"]["execution"].lower()
    execution_packet["handoff"]["execution"] = "standard profile executed; finalizer pending; runtime released"
    _reconcile_runtime_state(execution_packet, execution_packet["runtime_closure"])
    assert "finalizer pending" not in execution_packet["handoff"]["execution"].lower()
    assert "finalization validation passed" in execution_packet["handoff"]["execution"].lower()

    terminal_packet = json.loads(json.dumps(execution_packet))
    terminal_packet["runtime_closure"][0].update({
        "Completed worker handles": "/root/issue_evidence",
        "Runtime status": "Terminal",
        "Closure evidence or blocker": (
            "provider status snapshot 2026-10-07T22:42:58Z: /root/issue_evidence=completed"
        ),
    })
    _normalize_packet(terminal_packet, {"runtime_closure": terminal_packet["runtime_closure"]})
    assert terminal_packet["runtime_closure"][0]["Completed worker handles"] == "/root/issue_evidence"
    _reconcile_runtime_state(terminal_packet, terminal_packet["runtime_closure"])
    assert "runtime released" not in terminal_packet["handoff"]["execution"].lower()
    assert "runtime terminal" in terminal_packet["handoff"]["execution"].lower()
    assert terminal_packet["durable_artifacts"][1]["Status"] == "Terminal"

    with tempfile.TemporaryDirectory(prefix="workflow-finalize-") as directory:
        root = Path(directory)
        packet["finalization"]["Durable artifact root"] = str(root)
        source = root / "packet.json"
        closure = root / "runtime_closure.json"
        record = root / "work_record.md"
        source.write_text(json.dumps(packet))
        closure.write_text(json.dumps({"runtime_closure": packet["runtime_closure"]}))
        finalize(source, closure, record)
        assert "Workflow result: Worker runtime unavailable" in record.read_text()
        rendered = expand_work_record(record.read_text(), root)
        assert "{'explanation':" not in rendered
        assert "confidence: high" in rendered
        assert f"[work_record.md]({record.resolve()})" in rendered
        assert "| Work record | ./work_record.md |" in rendered
        assert "Final reconciliation | Passed; runtime closure released with no active handles |" in rendered
        assert "Finalization schema | Passed |" in rendered
        assert "Workflow result: Workflow result:" not in rendered
        assert "| Passed; runtime closure released |" in rendered
        assert "Final reconciliation | Pending" not in rendered
        assert "runtime pending" not in rendered.lower()
        assert "runtime closure pending" not in rendered.lower()
        assert "| runtime_closure.json |" in rendered
        assert "| Released | Provider receipt |" in rendered
        broken_record = root / "broken-work-record.md"
        broken_record.write_text(
            rendered
            .replace("Workflow result: Worker runtime unavailable", "Workflow result:")
            .replace(f"- [work_record.md]({record.resolve()})\n\nExecution:", "Execution:")
        )
        rejected = subprocess.run(
            [sys.executable, str(VALIDATOR), str(broken_record)],
            capture_output=True, text=True, check=False,
        )
        assert rejected.returncode != 0
        assert "Final Handoff Workflow result must be populated" in rejected.stdout
        assert "Final Handoff must link at least one artifact" in rejected.stdout
        empty_handoff = json.loads(source.read_text())
        empty_handoff["handoff"].update({
            "workflow_result": "",
            "implementation_plan": "",
            "next_action": {"owner": "", "action": "", "complete_when": ""},
            "artifacts": [],
            "execution": "",
            "provenance": "",
        })
        source.write_text(json.dumps(empty_handoff))
        try:
            finalize(source, closure, record)
        except ValueError as error:
            assert "packet.handoff.workflow_result must be a non-empty string" in str(error)
        else:
            raise AssertionError("finalization must reject an empty terminal handoff")
        feature_version = _frontmatter_version(ROOT / "playbooks" / "feature_delivery.md")
        feature_prompt_version = _frontmatter_version(ROOT / "templates" / "feature_delivery_run_prompt.md")
        assessment = json.loads(json.dumps(packet))
        assessment["playbook_selection"]["Primary goal"] = "Specification assessment"
        assessment["identity"].update({
            "Playbook / version": f"playbooks/feature_delivery.md / {feature_version}",
            "Lifecycle": "planning",
            "State": "awaiting_input",
        })
        assessment["handoff"]["provenance"] = (
            f"plugin Not applicable; framework revision {'a' * 40} (clean); "
            f"playbook feature_delivery {feature_version}."
        )
        assessment["handoff"]["workflow_result"] = "Plan created"
        try:
            _validate_handoff(assessment)
        except ValueError as error:
            assert "requires Workflow result exactly one of" in str(error)
        else:
            raise AssertionError("specification assessment must reject a non-disposition workflow result")
        assessment["handoff"]["workflow_result"] = "Not ready for implementation"
        assessment["handoff"]["implementation_plan"] = NO_PLAN_MESSAGE
        _validate_handoff(assessment)
        feature = json.loads(json.dumps(packet))
        feature["playbook_selection"].update({
            "Primary goal": "Implementation planning",
            "Selected playbook": "Feature Delivery",
        })
        feature["identity"].update({
            "Playbook / version": f"playbooks/feature_delivery.md / {feature_version}",
            "Prompt template / revision / conformance": (
                f"templates/feature_delivery_run_prompt.md / {feature_prompt_version} / pass"
            ),
            "Requested profile": "standard", "Activated profile": "standard", "Executed profile": "standard",
            "Profile status": "executed", "Lifecycle": "planning",
            "State": "ready_for_implementation", "Workflow outcome": "completed",
            "Engineering outcome": "plan_only",
        })
        feature["handoff"]["provenance"] = assessment["handoff"]["provenance"]

        def feature_ledger(worker: str, role: str, depends_on: str) -> dict[str, str]:
            return {
                "Worker": worker, "Role": role, "Assigned inputs": "IN-001",
                "Mode": "investigation", "Depth": "standard", "Skills": "assigned skills",
                "Tools": "assigned tools", "Capacity": "current task",
                "Configured model/effort": "gpt-5.6-luna / low",
                "Provider-observed model/effort": "Not exposed; launch binding gpt-5.6-luna / low",
                "Usage": "Not exposed", "Depends on": depends_on, "Outcome": "complete",
                "Confidence": "High",
            }

        def feature_result(worker: str) -> dict[str, str]:
            return {
                "Worker": worker, "Outcome": "complete", "Confidence": "High",
                "Unique contribution": f"Completed {worker} analysis.",
                "Evidence / claim refs": "E-001 / C-001", "Uncertainties / blockers": "None",
                "Actual model/effort": "Not exposed; launch binding gpt-5.6-luna / low",
                "Usage/credits": "Not exposed",
            }

        feature["workers"] = [
            feature_ledger("feature-context", "current_state_investigator", "None"),
            feature_ledger("impact-analysis", "dependency_analyst", "feature-context"),
            feature_ledger("feature-design", "solution_architect", "impact-analysis"),
            feature_ledger("handoff", "documenter", "feature-design"),
        ]
        feature["worker_results"] = [feature_result(worker) for worker in (
            "feature-context", "impact-analysis", "feature-design", "handoff",
        )]
        feature_root = root / "feature-assets"
        feature_root.mkdir()
        feature["finalization"]["Durable artifact root"] = str(feature_root)
        feature["inputs"] = [{
            "Input ID": "IN-001", "Input or artifact": "Work item ITEM-1", "Source or path": "Jira ITEM-1",
            "Authority": "Current work item", "Status": "Consumed",
        }]
        run_inputs_path = feature_root / "run_inputs.json"
        run_inputs_text = json.dumps({
            "schema_version": 1, "status": "explicit", "inputs": feature["inputs"],
        }) + "\n"
        run_inputs_path.write_text(run_inputs_text)
        feature["run_input_manifest"] = {
            "path": str(run_inputs_path),
            "sha256": hashlib.sha256(run_inputs_text.encode()).hexdigest(),
            "input_ids": ["IN-001"],
        }
        (feature_root / ASSET_MANIFEST_FILENAME).write_text(json.dumps({
            "schema_version": 1, "status": "passed", "work_item": "ITEM-1",
            "sources": [{
                "source_id": "SRC-JIRA", "input_id": "IN-001", "kind": "jira_issue_attachments",
                "locator": "Jira ITEM-1 attachments", "requiredness": "required", "discovery_status": "empty",
                "discovery_method": "read Jira attachment inventory",
                "remote_link_inventory": {
                    "status": "empty", "method": "read Jira remote links for ITEM-1", "locators": [],
                },
                "limitation": "Synthetic fixture has no Jira attachments.",
                "asset_ids": [], "evidence_refs": ["E-001"],
            }], "assets": [], "gate": {
                "inventory_complete": True, "all_assets_accounted_for": True,
                "all_available_assets_reviewed": True, "all_material_assets_linked": True,
                "reviewed_before_plan": True, "unresolved_asset_ids": [], "blocking_source_ids": [],
            },
        }))
        (feature_root / "implementation_plan.md").write_text(
            "# Asset Baseline\n\nasset_manifest.json\n" + PLAN_FIXTURE
        )
        feature["durable_artifacts"].append({
            "Artifact": "Asset manifest", "Path": str(feature_root / ASSET_MANIFEST_FILENAME),
            "Status": "Passed", "Purpose": "Asset gate",
        })
        feature["handoff"]["artifacts"].append(str(feature_root / ASSET_MANIFEST_FILENAME))
        assert _feature_delivery_packet_contract_errors(feature) == []
        assert _feature_delivery_asset_contract_errors(feature) == []
        plan_path = feature_root / "implementation_plan.md"
        plan_path.write_text("# Asset Baseline\nasset_manifest.json\n")
        assert any("Behavior Applicability" in error for error in _feature_delivery_asset_contract_errors(feature))
        plan_path.write_text("# Asset Baseline\nasset_manifest.json\n" + PLAN_FIXTURE)
        partial = json.loads(json.dumps(feature))
        partial["identity"].update({"State": "awaiting_input", "Engineering outcome": "partially_solved",
                                    "Run input manifest": str(run_inputs_path),
                                    "Run input manifest hash": hashlib.sha256(run_inputs_path.read_bytes()).hexdigest()})
        partial["handoff"].update({"workflow_result": "Independent plan saved; retry policy needs input",
                                   "implementation_plan": "Draft partial plan; not ready or approved"})
        draft = "---\nstatus: Draft\n---\n" + plan_path.read_text() + (
            "\n# Open Questions and Decisions\n"
            "| Question or decision | Why it matters | Owner | Status | Evidence refs |\n"
            "| --- | --- | --- | --- | --- |\n"
            "| Retry policy | Defines recovery | Issue owner | pending | E-001 |\n"
        )
        plan_path.write_text(draft)
        brief = feature_root / "clarification_brief.md"
        brief.write_text("# Clarification Brief\n\nIssue owner must select retry policy before implementation.\n")
        partial["durable_artifacts"].extend([
            {"Artifact": "Partial plan", "Path": str(plan_path), "Status": "Draft", "Purpose": "Independent work"},
            {"Artifact": "Clarification brief", "Path": str(brief), "Status": "Open", "Purpose": "Owned decision"},
        ])
        partial["handoff"]["artifacts"].extend([str(plan_path), str(brief)])
        partial_closure = feature_root / "runtime_closure.json"
        partial_closure.write_text(json.dumps({"runtime_closure": [{
            **packet["runtime_closure"][0], "Completed worker handles": "/root/context, /root/impact, /root/design, /root/handoff",
            "Closure evidence or blocker": "Provider close confirmed /root/context, /root/impact, /root/design, /root/handoff",
        }]}))
        partial_packet = feature_root / "partial_packet.json"
        partial_packet.write_text(json.dumps(partial))
        partial_record = feature_root / "work_record.md"
        finalize(partial_packet, partial_closure, partial_record, check_only=True)
        finalize(partial_packet, partial_closure, partial_record, pre_release=True)
        finalize(partial_packet, partial_closure, partial_record)
        assert "| State | awaiting_input |" in partial_record.read_text()
        assert "Independent plan saved" in partial_record.read_text()
        plan_path.write_text("# Asset Baseline\nasset_manifest.json\n" + PLAN_FIXTURE)
        delivery = json.loads(json.dumps(feature))
        delivery["identity"].update({"Lifecycle": "remediation", "State": "completed"})
        assert any("code_review.md" in error for error in _feature_delivery_packet_contract_errors(delivery))
        review_path = feature_root / "code_review.md"
        review_path.write_text(REVIEW_FIXTURE.replace("| verified |", "| defect |"))
        assert any("defect" in error for error in _feature_delivery_packet_contract_errors(delivery))
        review_path.write_text(REVIEW_FIXTURE)
        assert any("register code_review.md" in error for error in _feature_delivery_packet_contract_errors(delivery))
        delivery["durable_artifacts"].append({
            "Artifact": "Code review", "Path": str(review_path), "Status": "Accepted", "Purpose": "Review evidence",
        })
        delivery["handoff"]["artifacts"].append(str(review_path))
        delivery["identity"]["Engineering outcome"] = "solved"
        delivery["workers"] = [feature_ledger(worker, role, "Approved delivery dependency") for worker, role in (
            ("implement", "implementer"), ("review", "reviewer"), ("validate", "tester"), ("handoff", "documenter"),
        )]
        delivery["worker_results"] = [feature_result(worker) for worker in ("implement", "review", "validate", "handoff")]
        delivery["synchronization"] = [{"Stage": "Delivery fan-in", "Workers launched": "implement, review, validate",
                                        "Launch mode / exception": "Sequential delivery", "Worker outcomes": "complete",
                                        "Barrier status": "Passed", "Results summarized": "Accepted review and validation"}]
        delivery["runtime_audits"] = []
        for worker in ("implement", "review", "validate", "handoff"):
            trace_path = feature_root / f"{worker}_trace.json"
            trace_path.write_text(json.dumps({"spawn": {"activation_packet_delivered": True}, "tool_trace": [],
                                             "last_dispatch_at": "2026-10-07T23:40:00Z",
                                             "events": [{"action": "fan_in", "provider_status": "completed"}]}))
            delivery["runtime_audits"].append({"Worker": worker, "Provider handle": f"/root/{worker}",
                                              "Provider status": "completed", "Last dispatch at": "2026-10-07T23:40:00Z",
                                              "Observed at": "2026-10-07T23:50:00Z", "Status source": "list_agents",
                                              "Trace path": str(trace_path)})
        candidate_repo, candidate_review, candidate_validation = delivery_evidence_fixture(feature_root)
        review_path.write_text(candidate_review)
        delivery["repositories"] = [{**delivery["repositories"][0], "Resolved path": str(candidate_repo)}]
        (feature_root / "validation_report.md").write_text(candidate_validation)
        delivery["durable_artifacts"].append({"Artifact": "Validation report",
                                             "Path": str(feature_root / "validation_report.md"),
                                             "Status": "Partial", "Purpose": "Executed tests and unverified database validation"})
        delivery["handoff"]["artifacts"].append(str(feature_root / "validation_report.md"))
        assert _feature_delivery_packet_contract_errors(delivery) == []
        missing_asset_feature = json.loads(json.dumps(feature))
        missing_asset_feature["finalization"]["Durable artifact root"] = str(feature_root / "missing")
        assert any(
            "requires a valid asset_manifest.json" in error
            for error in _feature_delivery_asset_contract_errors(missing_asset_feature)
        )
        incomplete_feature = json.loads(json.dumps(feature))
        incomplete_feature["workers"] = incomplete_feature["workers"][-1:]
        incomplete_feature["worker_results"] = incomplete_feature["worker_results"][-1:]
        feature_errors = _feature_delivery_packet_contract_errors(incomplete_feature)
        assert "Feature Delivery handoff requires execution-ledger rows for:" in "\n".join(feature_errors)
        assert "feature-context" in "\n".join(feature_errors)
        conditional_feature = json.loads(json.dumps(feature))
        conditional_feature["workers"].insert(
            2, feature_ledger("repository-integration", "repository_integrator", "feature-context")
        )
        conditional_feature["worker_results"].insert(2, feature_result("repository-integration"))
        assert _feature_delivery_packet_contract_errors(conditional_feature) == []
        assessment_feature = json.loads(json.dumps(feature))
        assessment_feature["playbook_selection"]["Primary goal"] = "Specification assessment"
        assessment_feature["identity"]["Engineering outcome"] = "solved"
        assessment_feature["handoff"]["workflow_result"] = "Ready for implementation"
        assessment_feature["handoff"]["implementation_plan"] = NO_PLAN_MESSAGE
        report_path = feature_root / REPORT_NAME
        assert "requires specification_assessment.md" in " ".join(
            _feature_delivery_asset_contract_errors(assessment_feature)
        )
        (feature_root / "implementation_plan.md").unlink()
        report_path.write_text(
            "# Specification Assessment\n## Question and Result\nAssessed ITEM-1 against its Stories.\n"
            "Workflow result: Ready for implementation\n## Source and Asset Baseline\n"
            "ITEM-1 and asset_manifest.json reviewed.\n## Coverage\n"
            "| Requirement / behavior | Story coverage | Evidence | Status | Test / dependency | Gap or follow-up | Owner |\n"
            "| --- | --- | --- | --- | --- | --- | --- |\n"
            "| Outcome | ITEM-2 | E-001 | Covered | Check ITEM-2 / ITEM-1 | None | Team |\n"
            "## Gaps, Risks, and Decisions\nNo gaps.\n"
            "## Disposition and Next Action\nProceed to planning.\n"
        )
        design_text = "## Coverage\n" + report_path.read_text().split("## Coverage\n", 1)[1].split(
            "## Gaps", 1,
        )[0]
        (feature_root / "feature_design.md").write_text(design_text)
        assessment_feature["durable_artifacts"].append({
            "Artifact": "Specification assessment", "Path": str(report_path),
            "Status": "Complete", "Purpose": "Readiness coverage",
        })
        assessment_feature["handoff"]["artifacts"].append(str(report_path))
        assert _feature_delivery_packet_contract_errors(assessment_feature) == []
        assert _feature_delivery_asset_contract_errors(assessment_feature) == []
        changed_report = report_path.read_text().replace("| Covered |", "| Partial |")
        report_path.write_text(changed_report)
        assert "must match reviewed coverage" in " ".join(_feature_delivery_asset_contract_errors(assessment_feature))
        report_path.write_text(changed_report.replace("| Partial |", "| Covered |"))
        for name in ("feature_context.md", "impact_analysis.md"):
            (feature_root / name).write_text(f"# {name}\n")
        pre_handoff_path = feature_root / "finalization_packet.json"
        pre_handoff_path.write_text(json.dumps(assessment_feature))
        assert feature_delivery_pre_handoff_errors(pre_handoff_path) == []
        (feature_root / "feature_design.md").write_text(design_text.replace("| Covered |", "| Partial |"))
        assert "feature_design.md ready result requires covered requirements" in " ".join(
            feature_delivery_pre_handoff_errors(pre_handoff_path)
        )
        (feature_root / "feature_design.md").write_text(design_text)
        prepared_handoff = json.loads(json.dumps(assessment_feature))
        prepared_handoff["identity"]["Requested profile"] = ""
        pre_handoff_path.write_text(json.dumps(prepared_handoff))
        assert feature_delivery_pre_handoff_errors(pre_handoff_path) == []
        pre_handoff_path.write_text(json.dumps(assessment_feature))
        (feature_root / "feature_design.md").write_text("## Coverage\n")
        assert "feature_design.md requires a populated" in " ".join(
            feature_delivery_pre_handoff_errors(pre_handoff_path)
        )
        (feature_root / "feature_design.md").write_text(design_text)
        deep_handoff = json.loads(json.dumps(assessment_feature))
        deep_handoff["identity"]["Requested profile"] = "deep"
        pre_handoff_path.write_text(json.dumps(deep_handoff))
        assert "planning_review.md" in " ".join(feature_delivery_pre_handoff_errors(pre_handoff_path))
        pre_handoff_path.write_text(json.dumps(assessment_feature))
        false_reference = json.loads(json.dumps(assessment_feature))
        false_reference["durable_artifacts"].append({
            "Artifact": "Specification coverage mapping", "Path": str(feature_root / "work_record.md"),
            "Status": "Complete", "Purpose": "Coverage",
        })
        false_reference["evidence"][0]["Source"] = "work_record.md Specification Coverage Mapping"
        false_reference["handoff"]["execution"] = "No finalizer invocation."
        assert len(_feature_assessment_reference_errors(false_reference)) == 3
        assessment_feature["identity"].update({"State": "awaiting_input", "Engineering outcome": "partially_solved"})
        assessment_feature["handoff"]["workflow_result"] = "Not ready for implementation"
        report_path.write_text(report_path.read_text().replace(
            "Workflow result: Ready for implementation", "Workflow result: Not ready for implementation",
        ))
        assert _feature_delivery_packet_contract_errors(assessment_feature) == []
        assert _feature_delivery_asset_contract_errors(assessment_feature) == []
        false_release = [{
            "Run or stage": "Feature Delivery assessment", "Receipt owner": "Coordinator",
            "Completed worker handles": "None", "Runtime status": "Released",
            "Remaining active handles": "None",
            "Closure evidence or blocker": "Provider release confirmed by terminal results.",
        }]
        assert any("provider handles released=0" in error for error in
                   _planning_runtime_closure_errors(assessment_feature, false_release))
        blocked_assessment = json.loads(json.dumps(assessment_feature))
        blocked_assessment["handoff"]["provenance"] = (
            f"Feature Delivery {feature_version}; framework {'a' * 40}"
        )
        blocked_closure = {"runtime_closure": [{
            "Run or stage": "Feature Delivery assessment", "Receipt owner": "Coordinator",
            "Completed worker handles": "Unknown", "Runtime status": "Blocked",
            "Remaining active handles": "Unknown",
            "Closure evidence or blocker": "worker_runtime_release_unavailable: provider release not exposed",
        }]}
        _prepare_blocked_runtime_snapshot(blocked_assessment, blocked_closure, report_path, None)
        assert blocked_assessment["identity"]["State"] == "blocked"
        assert blocked_assessment["identity"]["Workflow outcome"] == "blocked"
        assert blocked_assessment["identity"]["Engineering outcome"] == "partially_solved"
        blocked_planning = json.loads(json.dumps(feature))
        blocked_planning["handoff"]["workflow_result"] = "Implementation plan ready; no implementation performed."
        (feature_root / "implementation_plan.md").write_text("# Asset Baseline\n\nasset_manifest.json\n" + PLAN_FIXTURE)
        _prepare_blocked_runtime_snapshot(blocked_planning, blocked_closure, report_path, None)
        assert blocked_planning["identity"]["State"] == "blocked"
        assert blocked_planning["identity"]["Workflow outcome"] == "blocked"
        assert blocked_planning["identity"]["Engineering outcome"] == "plan_only"
        (feature_root / "implementation_plan.md").unlink()
        assert assessment_feature["identity"]["State"] == "awaiting_input"
        assessment_feature["handoff"]["provenance"] = (
            f"Feature Delivery {feature_version}; framework {'a' * 40}"
        )
        assessment_packet = feature_root / "assessment_packet.json"
        assessment_closure = feature_root / "runtime_closure.json"
        assessment_record = feature_root / "assessment_work_record.md"
        assessment_packet.write_text(json.dumps(assessment_feature))
        assessment_closure.write_text(json.dumps(blocked_closure))
        finalize(assessment_packet, assessment_closure, assessment_record, blocked_runtime_snapshot=True)
        assert "State: blocked" in assessment_record.read_text()
        assert "playbook feature_delivery" in assessment_record.read_text()
        design_path = feature_root / "feature_design_result.json"
        design_path.write_text(json.dumps({"asset_gate": {"asset_count": 1, "source_count": 1}}))
        assert "asset_gate.asset_count must equal asset_manifest.json assets count (0)" in (
            "\n".join(_feature_delivery_asset_contract_errors(assessment_feature))
        )
        design_path.write_text(json.dumps({"asset_gate": {"asset_count": 0, "source_count": 2}}))
        assert "asset_gate.source_count must equal asset_manifest.json sources count (1)" in (
            "\n".join(_feature_delivery_asset_contract_errors(assessment_feature))
        )
        design_path.write_text(json.dumps({"asset_gate": {"asset_count": 0, "source_count": 1}}))
        assert _feature_delivery_asset_contract_errors(assessment_feature) == []
        planning_plan = feature_root / "implementation_plan.md"
        planning_plan.write_text("# Asset Baseline\n\nasset_manifest.json\n" + PLAN_FIXTURE)
        planning_feature = json.loads(json.dumps(feature))
        planning_feature["handoff"].update({
            "workflow_result": "Implementation plan ready; no implementation performed.",
            "implementation_plan": str(planning_plan),
            "execution": "standard planning; workers complete; no source changes; runtime pending",
        })
        planning_feature["durable_artifacts"].append({
            "Artifact": "Implementation plan", "Path": str(planning_plan),
            "Status": "Ready for review", "Purpose": "Unapproved plan",
        })
        planning_feature["handoff"]["artifacts"].append(str(planning_plan))
        planning_packet = feature_root / "planning_packet.json"
        planning_record = feature_root / "planning_work_record.md"
        planning_packet.write_text(json.dumps(planning_feature))
        finalize(planning_packet, assessment_closure, planning_record, blocked_runtime_snapshot=True)
        assert "| State | blocked |" in planning_record.read_text()
        assert "| Workflow outcome | blocked |" in planning_record.read_text()
        assert "| Engineering outcome | plan_only |" in planning_record.read_text()
        assert planning_plan.is_file()
        assert "| Finalization schema | Passed for blocked work record |" in expand_work_record(planning_record.read_text(), feature_root)
        assert "| Unverified | Provider receipt |" in planning_record.read_text()
        techops = json.loads(json.dumps(planning_feature))
        techops["identity"]["Playbook / version"] = "playbooks/techops_issue_remediation.md / 0.5.2"
        techops["worker_results"] = [
            dict(techops["worker_results"][0], Worker=worker, Outcome="complete")
            for worker in ("issue-evidence", "failure-path", "fix-design", "handoff")
        ]
        _prepare_blocked_runtime_snapshot(techops, blocked_closure, planning_record, None)
        assert techops["identity"]["Workflow outcome"] == "blocked"
        assert techops["identity"]["Engineering outcome"] == "plan_only"
        # Exercise actual TechOps publication, not only the blocked-state preparer.
        from contextlib import redirect_stdout
        from io import StringIO
        published_techops = json.loads(json.dumps(planning_feature))
        published_techops["identity"].update({
            "Playbook / version": f"playbooks/techops_issue_remediation.md / {_frontmatter_version(ROOT / 'playbooks/techops_issue_remediation.md')}",
            "Prompt template / revision / conformance": f"templates/techops_issue_run_prompt.md / {_frontmatter_version(ROOT / 'templates/techops_issue_run_prompt.md')} / pass",
            "Finalization schema": "Pending",
        })
        roles = {"issue-evidence": "current_state_investigator", "failure-path": "dependency_analyst",
                 "repository-integration": "repository_integrator", "fix-design": "solution_architect", "handoff": "documenter"}
        published_techops["workers"] = [feature_ledger(worker, role, "IN-001") for worker, role in roles.items()]
        published_techops["worker_results"] = [feature_result(worker) for worker in roles]
        published_techops["techops_checks"] = [
            {"Check": name, "Status": "not_applicable" if name == "history_reconciliation" else "passed",
             "Evidence refs": "E-001", "Detail": "Owning worker evidence; fixture has no history mismatch"}
            for name in ("issue_scope", "history_reconciliation", "plan_dependencies", "regression_fixture")
        ]
        published_techops["runtime_audits"] = []
        for worker in roles:
            trace_path = feature_root / f"{worker}_trace.json"
            trace_path.write_text(json.dumps({
                "spawn": {"activation_packet_delivered": True}, "last_dispatch_at": "2026-10-07T23:40:00Z",
                "events": [{"action": "fan_in", "provider_status": "completed"}],
                "tool_trace": [{"tool": "exec_command", "arguments": {"cmd": "rg -n affected_symbol src"}}],
            }))
            published_techops["runtime_audits"].append({
                "Worker": worker, "Provider handle": "/root/" + worker.replace("-", "_"),
                "Provider status": "completed", "Last dispatch at": "2026-10-07T23:40:00Z",
                "Observed at": "2026-10-07T23:53:10Z", "Status source": "list_agents",
                "Trace path": str(trace_path), "Trace retrieval": "read_thread command ledger",
            })
        published_techops["handoff"]["execution"] = (
            "standard planning; no source changes; awaiting Coordinator packet validation and packaged finalization"
        )
        techops_packet = feature_root / "techops_packet.json"
        techops_record = feature_root / "techops_work_record.md"
        techops_packet.write_text(json.dumps(published_techops))
        captured = StringIO()
        with redirect_stdout(captured):
            finalize(techops_packet, assessment_closure, techops_record, blocked_runtime_snapshot=True)
        assert captured.getvalue().splitlines()[0] == "Workflow-framework validation: passed"
        assert "TechOps planning blocked work record: saved; runtime release unverified" in captured.getvalue()
        assert "Feature Delivery implementation planning blocked work record" not in captured.getvalue()
        assert expand_work_record(techops_record.read_text(), feature_root).count("| Finalization schema |") == 1
        assert "awaiting Coordinator" not in techops_record.read_text()
        from scripts.prepare_run import _agent_binding
        bindings = {role: _agent_binding(role, None) for role in roles.values()}
        baseline = re.search(r"^baseline_id: (\S+)$", (ROOT / "providers/codex/model_effort_policy.md").read_text(), re.MULTILINE)[1]
        (feature_root / "role_bindings.json").write_text(json.dumps({
            "playbook": "techops_issue_remediation", "baseline_id": baseline, "bindings": bindings,
        }))
        published_techops["identity"]["Coordinator model/effort"] = "gpt-6.1-sol / high"
        for row in published_techops["workers"]:
            binding = bindings[row["Role"]]
            row["Configured model/effort"] = f"{binding['model']} / {binding['effort']}"
            row["Provider-observed model/effort"] = row["Configured model/effort"]
        techops_packet.write_text(json.dumps(published_techops))
        finalize(techops_packet, assessment_closure, techops_record, pre_release=True)
        assert (feature_root / "pre_release_check.json").is_file()
        observed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        terminal_rows = [{
            "Provider handle": row["Provider handle"], "Provider status": "completed",
            "Last dispatch at": row["Last dispatch at"], "Observed at": observed_at,
            "Status source": "read_thread", "Thread ID": f"00000000-0000-0000-0000-{index:012d}",
            "Latest turn started at": "2026-10-07T23:40:01Z", "Latest turn status": "completed",
            "Thread status": "notLoaded",
        } for index, row in enumerate(published_techops["runtime_audits"])]
        terminal_closure = feature_root / "terminal_closure.json"
        terminal_closure.write_text(json.dumps({
            "runtime_closure": [{
                "Run or stage": "TechOps planning", "Receipt owner": "Coordinator",
                "Completed worker handles": "; ".join(row["Provider handle"] for row in terminal_rows),
                "Runtime status": "Terminal", "Remaining active handles": "0",
                "Closure evidence or blocker": "provider status snapshot " + observed_at + ": " +
                    "; ".join(row["Provider handle"] + "=completed" for row in terminal_rows),
            }], "terminal_observations": terminal_rows,
        }))
        with redirect_stdout(StringIO()):
            finalize(techops_packet, terminal_closure, techops_record)
        assert "| State | ready_for_implementation |" in techops_record.read_text()
        assert "| Terminal | 0 |" in expand_work_record(techops_record.read_text(), feature_root)
        assert "runtime terminal" in techops_record.read_text()
        changed_packet = json.loads(techops_packet.read_text())
        changed_packet["work_item"]["Title"] = "Updated after pre-release"
        techops_packet.write_text(json.dumps(changed_packet))
        try:
            finalize(techops_packet, terminal_closure, techops_record)
        except ValueError as error:
            assert "terminal_closure_requires_current_passed_pre_release" in str(error)
        else:
            raise AssertionError("packet changes must invalidate pre-release")
        (feature_root / "role_bindings.json").unlink()
        delivery["identity"].update({"State": "handoff", "Workflow outcome": "in_progress",
                                     "Engineering outcome": "partially_solved",
                                     "Provider / model configuration": "Codex / Worker Execution Ledger"})
        delivery["playbook_selection"]["Primary goal"] = "Feature implementation"
        delivery["handoff"].update({"workflow_result": "Implementation reviewed; database validation unverified",
                                    "implementation_plan": str(feature_root / "implementation_plan.md"),
                                    "execution": "standard/remediation; source changed; local tests passed; database unverified; runtime pending"})
        delivery_path = feature_root / "delivery_packet.json"
        delivery_record = feature_root / "delivery_work_record.md"
        delivery_bindings = {role: _agent_binding(role, None) for role in ("implementer", "reviewer", "tester", "documenter")}
        (feature_root / "role_bindings.json").write_text(json.dumps({
            "playbook": "feature_delivery", "baseline_id": baseline, "bindings": delivery_bindings,
        }))
        delivery["identity"]["Coordinator model/effort"] = "gpt-6.1-sol / high"
        for row in delivery["workers"]:
            binding = delivery_bindings[row["Role"]]
            row["Configured model/effort"] = f"{binding['model']} / {binding['effort']}"
            row["Provider-observed model/effort"] = row["Configured model/effort"]
        delivery_path.write_text(json.dumps(delivery))
        assert feature_delivery_pre_handoff_errors(delivery_path) == []
        # A partial engineering result can still complete accurate workflow bookkeeping.
        with redirect_stdout(StringIO()):
            finalize(delivery_path, assessment_closure, delivery_record, pre_release=True)
        delivery_terminal_rows = [{
            "Provider handle": row["Provider handle"], "Provider status": "completed",
            "Last dispatch at": row["Last dispatch at"], "Observed at": datetime.now(timezone.utc).isoformat(),
            "Status source": "list_agents",
        } for row in delivery["runtime_audits"]]
        delivery_closure = feature_root / "delivery_closure.json"
        delivery_closure.write_text(json.dumps({"runtime_closure": [{
            "Run or stage": "Feature Delivery remediation", "Receipt owner": "Coordinator",
            "Completed worker handles": "; ".join(row["Provider handle"] for row in delivery_terminal_rows),
            "Runtime status": "Terminal", "Remaining active handles": "0",
            "Closure evidence or blocker": "provider status snapshot " + delivery_terminal_rows[0]["Observed at"] + ": " +
                "; ".join(row["Provider handle"] + "=completed" for row in delivery_terminal_rows),
        }], "terminal_observations": delivery_terminal_rows}))
        with redirect_stdout(StringIO()):
            finalize(delivery_path, delivery_closure, delivery_record)
        assert "| Engineering outcome | partially_solved |" in delivery_record.read_text()
        assert "| Lifecycle | remediation |" in delivery_record.read_text()
        valid_delivery_record = delivery_record.read_bytes()
        stale_delivery_closure = json.loads(delivery_closure.read_text())
        stale_delivery_closure["terminal_observations"][0]["Observed at"] = "2026-10-07T23:50:00Z"
        delivery_closure.write_text(json.dumps(stale_delivery_closure))
        try:
            finalize(delivery_path, delivery_closure, delivery_record)
        except ValueError as error:
            assert "terminal_observation_predates_pre_release" in str(error)
        else:
            raise AssertionError("Feature Delivery accepted pre-release-old terminal status")
        delivery["work_item"]["Title"] = "Changed after pre-release"
        delivery_path.write_text(json.dumps(delivery))
        try:
            finalize(delivery_path, delivery_closure, delivery_record)
        except ValueError as error:
            assert "terminal_closure_requires_current_passed_pre_release" in str(error)
        else:
            raise AssertionError("Feature Delivery accepted a stale packet receipt")
        assert delivery_record.read_bytes() == valid_delivery_record
        # Provider release unavailability still permits an honest current blocked handoff.
        with redirect_stdout(StringIO()):
            finalize(delivery_path, assessment_closure, delivery_record, blocked_runtime_snapshot=True)
        assert "| State | blocked |" in delivery_record.read_text()
        assert "| Engineering outcome | partially_solved |" in delivery_record.read_text()
        (feature_root / "role_bindings.json").unlink()
        published_techops["runtime_audits"][0]["Trace path"] = "missing_trace.json"
        assert any("worker_trace_invalid" in error for error in _techops_planning_contract_errors(published_techops, techops_packet))
        incomplete_techops = json.loads(json.dumps(planning_feature))
        incomplete_techops["identity"]["Playbook / version"] = techops["identity"]["Playbook / version"]
        try:
            _prepare_blocked_runtime_snapshot(incomplete_techops, blocked_closure, planning_record, None)
        except ValueError as error:
            assert "supported planning or remediation packet" in str(error)
        else:
            raise AssertionError("TechOps blocked snapshot accepted incomplete workers")
        spike = json.loads(json.dumps(packet))
        spike["playbook_selection"]["Primary goal"] = "Execute technical spike"
        spike["identity"].update({
            "Playbook / version": f"playbooks/technical_spike.md / {technical_spike_version}",
            "Lifecycle": "planning",
            "State": "completed",
            "Requested profile": "standard", "Activated profile": "standard", "Executed profile": "standard",
            "Profile status": "executed",
            "Workflow outcome": "completed",
            "Engineering outcome": "solved",
        })
        spike["worker_results"].extend([
            {"Worker": worker, "Outcome": "complete"}
            for worker in ("spike-context", "spike-investigation", "handoff")
        ])
        spike["workers"].extend([
            {"Worker": "spike-context", "Role": "current_state_investigator", "Tools": "work_item_read",
             "Outcome": "complete"},
            {"Worker": "spike-investigation", "Role": "solution_architect", "Tools": "mapped operations",
             "Outcome": "complete"},
            {"Worker": "handoff", "Role": "documenter", "Tools": "artifact_write", "Outcome": "complete"},
        ])
        spike["handoff"].update({
            "workflow_result": "Question answered",
            "implementation_plan": "Not created; Technical Spike produces spike_report.md",
            "provenance": (
                f"plugin Not applicable; framework revision {'a' * 40} (clean); "
                f"playbook technical_spike {technical_spike_version}."
            ),
        })
        _validate_handoff(spike)
        mismatched_spike = json.loads(json.dumps(spike))
        context_row = next(row for row in mismatched_spike["workers"] if row["Worker"] == "spike-context")
        context_row["Outcome"] = "pending"
        try:
            _validate_handoff(mismatched_spike)
        except ValueError as error:
            assert "spike-context outcome mismatch" in str(error)
        else:
            raise AssertionError("Technical Spike must reject differing worker and ledger outcomes")
        legacy_spike = json.loads(json.dumps(spike))
        for row in legacy_spike["workers"]:
            if row["Worker"] == "handoff":
                row["Worker"] = "documenter"
        for row in legacy_spike["worker_results"]:
            if row["Worker"] == "handoff":
                row["Worker"] = "documenter"
        _canonicalize_technical_spike_worker_ids(legacy_spike, {"playbook": "technical_spike"})
        _validate_handoff(legacy_spike)
        composite_spike = json.loads(json.dumps(spike))
        composite_ids = {
            "Coordinator": "Coordinator",
            "spike-context": "spike-context/current_state_investigator",
            "spike-investigation": "spike-investigation/solution_architect",
            "handoff": "handoff/documenter",
        }
        for field in ("workers", "worker_results"):
            for row in composite_spike[field]:
                row["Worker"] = composite_ids.get(row["Worker"], row["Worker"])
        _canonicalize_technical_spike_worker_ids(composite_spike, {"playbook": "technical_spike"})
        assert {row["Worker"] for row in composite_spike["workers"]} == set(composite_ids)
        assert {row["Worker"] for row in composite_spike["worker_results"]} == set(composite_ids)
        _validate_handoff(composite_spike)
        wrong_role_spike = json.loads(json.dumps(spike))
        next(row for row in wrong_role_spike["workers"] if row["Worker"] == "spike-investigation")["Role"] = (
            "dependency_analyst"
        )
        try:
            _validate_handoff(wrong_role_spike)
        except ValueError as error:
            assert "spike-investigation requires role solution_architect" in str(error)
        else:
            raise AssertionError("Technical Spike must reject an analytical role mismatch")
        spike["handoff"]["workflow_result"] = "Accepted"
        try:
            _validate_handoff(spike)
        except ValueError as error:
            assert "requires Workflow result exactly one of" in str(error)
        else:
            raise AssertionError("execute_spike must reject review_spike dispositions")
        spike_execution = root / "spike-execution"
        spike_execution.mkdir()
        spike_inputs = root / "spike-inputs.json"
        spike_inputs.write_text(json.dumps({
            "schema_version": 1,
            "status": "explicit",
            "precedence_rule": "Current user decisions govern current-run evidence and scope.",
            "inputs": [{
                "Input ID": "IN-001", "Input or artifact": "Existing Spike",
                "Source or path": "Current user request", "Authority": "Review target",
                "Classification": "Reference document", "Expected use": "Assess evidence",
                "Status": "Registered",
            }],
        }))
        prepared_spike = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "prepare_run.py"),
             "--execution-repository", str(spike_execution), "--work-item", "SPIKE-1",
             "--playbook", "technical_spike", "--input-manifest", str(spike_inputs),
             "--started-at", "2099-09-07T12:00:00Z", "--timebox-minutes", "25",
             "--primary-question", "Can the supplied evidence answer the Spike question?",
             "--success-criterion", "An evidence-backed answer or explicit unknown is recorded."],
            capture_output=True, text=True, check=True,
        )
        prepared_spike_data = json.loads(prepared_spike.stdout)
        spike_root = Path(prepared_spike_data["artifact_root"])
        spike_report = spike_root / "spike_report.md"
        spike_report.write_text("""---
title: Technical Spike Report
version: test
status: Pilot
owner: Engineering
last_updated: 2026-09-11T00:00:00Z
---

# Technical Spike Report

## Metadata
| Field | Value |
| --- | --- |
| Work item | SPIKE-1 |
| Objective | review_spike |
| Primary question | Does existing evidence support implementation planning? |
| Timebox or evidence budget | One bounded review |
| Success criterion | Separate supported claims from unknowns |
| Execution profile | deep |
| Repositories and revisions | aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa |
| Review target | Existing Spike |
| Comparison reference | Not applicable |

## Scope and Non-goals
Review only; no implementation plan.

## Plain-Language Summary
The existing Spike has an evidence gap. The current review identifies what is missing and what should be checked next.
No implementation change is proposed by this report.

## Integration Participants and Boundaries
| Participant or technology | Role or boundary | Evidence refs | Evidence status or unknown |
| --- | --- | --- | --- |
| Not applicable | Not applicable | Not applicable | No material integration participants |

## Method and Evidence
| Evidence ID | Method or source | Observation | Status | Limitation |
| --- | --- | --- | --- | --- |
| E-001 | Repository trace | One material gap remains | Verified | Runtime not observed |

## Direct Evidence
| Evidence ID | Repository or source | Revision or version | File or artifact location | Observation | Status |
| --- | --- | --- | --- | --- | --- |
| E-001 | Execution repository | aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa | src/boundary.py:10 | One material gap remains | Verified |

## Decision Context
| Category | Statement or branch | Evidence refs | Owner or decision needed | Status |
| --- | --- | --- | --- | --- |
| Not applicable | No unresolved decision remains | None | None | Recorded |

## Assessment Criteria
| Criterion or domain | Evidence refs | Assessment | Gap or limitation | Required next evidence or decision |
| --- | --- | --- | --- | --- |
| Not applicable | Not applicable | No external assessment baseline declared | None | None |

## Experiments and Checks
| Hypothesis or review criterion | Observable seam | Command or method | Expected discriminating outcomes | Actual result | Disposition impact |
| --- | --- | --- | --- | --- | --- |
| Existing evidence is complete | Supplied Spike report boundary | Not run | Complete or incomplete | Not run; source review was sufficient (E-001) | Changes required |

## Findings
One material evidence gap remains (E-001).

## Options and Tradeoffs
| Option | Evidence | Benefits | Costs or risks | When to choose |
| --- | --- | --- | --- | --- |
| Revise Spike | E-001 | Closes evidence gap | Additional review | Before Feature Delivery |

## Recommendation
Revise the existing Spike (E-001).

## Reference Comparison
| Reference | Agreement | Difference or omission | Impact on recommendation |
| --- | --- | --- | --- |
| Not applicable | Not applicable | Not applicable | Not applicable |

## Remaining Unknowns and Follow-up
Runtime behavior remains unverified.

## Disposition
| Field | Value |
| --- | --- |
| Workflow result | Changes required |
| Question or review conclusion | Existing evidence is incomplete |
| Budget status | within_budget |
| Feature Delivery handoff | Needs follow-up |
""")
        (spike_root / "run_budget.json").write_text(json.dumps({
            "schema_version": 1,
            "started_at": "2000-01-01T00:00:00Z",
            "deadline_at": "2000-01-01T00:01:00Z",
            "timebox_minutes": 1,
            "status": "within_budget",
        }, indent=2) + "\n")
        preserved_budget_root = root / "preserved-budget"
        preserved_budget_root.mkdir()
        (preserved_budget_root / "run_budget.json").write_text(json.dumps({
            "schema_version": 1,
            "started_at": "2000-01-01T00:00:00Z",
            "deadline_at": "2000-01-01T00:01:00Z",
            "timebox_minutes": 1,
            "status": "exhausted_with_useful_result",
        }, indent=2) + "\n")
        assert _update_run_budget(
            preserved_budget_root / "finalization_packet.json"
        ) == "exhausted_with_useful_result"
        spike_packet_path = Path(prepared_spike_data["finalization_packet"])
        spike_packet = json.loads(spike_packet_path.read_text())
        spike_manifest = json.loads(Path(prepared_spike_data["role_binding_manifest"]).read_text())
        spike_packet["work_item"].update({
            "Title": "Review existing Spike", "Last Updated": "2026-09-07T00:00:00Z",
        })
        spike_packet["playbook_selection"].update({
            "Primary evidence": "Existing Spike and repository evidence",
            "Primary goal": "Review technical spike", "Selected playbook": "Technical Spike",
            "Closest alternative": "Feature Delivery implementation planning",
            "Why this playbook": "Primary goal is evidence review, not implementation planning",
        })
        spike_packet["repositories"] = [{
            "Repository role": "Execution", "Declared path": str(spike_execution),
            "Resolved path": str(spike_execution), "Branch / detached": "main",
            "Full revision": "a" * 40, "Clean status": "Clean", "User-selected ref": "Yes",
            "Release mapping": "Unknown", "Evidence eligibility": "Accepted",
        }]
        spike_packet["identity"].update({
            "Run ID": "spike-review-001", "Framework commit / status": f"{'a' * 40} / Dirty",
            "Plugin package / version": "corrupted / value",
            "Provider configuration source/status": "corrupted",
            "Prompt template / revision / conformance": (
                f"templates/technical_spike_run_prompt.md / {technical_spike_prompt_version} / pass"
            ),
            "Coordinator model/effort": "gpt-5.6-luna / xhigh", "Requested profile": "deep",
            "Activated profile": "deep", "Executed profile": "deep", "Profile status": "executed",
            "Role-policy baseline ID": "corrupted", "Lifecycle": "planning", "State": "handoff",
            "Engineering state": "understood",
            "Workflow outcome": "in_progress", "Engineering outcome": "unknown",
        })
        spike_packet["finalization"].update({
            "Concurrent-run decision": "new run", "Active related run or work item": "None",
            "Related-run check": "Passed", "Final reconciliation": "Pending runtime release",
            "Finalization schema": "Pending",
        })
        worker_specs = (
            ("spike-context", "current_state_investigator"),
            ("spike-assessment", "reviewer"),
            ("repository-integration", "repository_integrator"),
            ("handoff", "documenter"),
        )
        spike_packet["workers"] = []
        spike_packet["worker_results"] = []
        for worker, role in worker_specs:
            binding = spike_manifest["bindings"][role]
            configured = (
                f"incorrect/none; expected {binding['model']}/{binding['effort']}; definition {binding['definition']}; "
                f"sha {binding['definition_sha256']}"
            )
            spike_packet["workers"].append({
                "Worker": worker, "Role": role, "Assigned inputs": "IN-001", "Mode": "delegated",
                "Depth": "deep", "Skills": "technical spike review", "Tools": "mapped operations",
                "Capacity": "Not exposed", "Configured model/effort": configured,
                "Provider-observed model/effort": (
                    f"Not exposed; configured binding {binding['model']}/{binding['effort']}"
                ),
                "Usage": "Not exposed", "Depends on": "prior stage", "Outcome": "complete",
                "Confidence": "High",
            })
            if worker == "spike-context":
                spike_packet["workers"][-1]["Tools"] = "work_item_read; mapped operations"
            spike_packet["worker_results"].append({
                "Worker": worker, "Outcome": "complete", "Confidence": "High",
                "Unique contribution": f"Completed {worker}", "Evidence / claim refs": "E-001 / C-001",
                "Uncertainties / blockers": "None", "Actual model/effort": "Not exposed",
                "Usage/credits": "Not exposed",
            })
        spike_packet["synchronization"] = [{
            "Stage": "Analytical fan-in", "Workers launched": "spike assessment and repository integration",
            "Launch mode / exception": "Parallel after context", "Worker outcomes": "complete",
            "Results summarized": "Yes", "Barrier status": "Pending runtime release",
        }]
        spike_packet["evidence"] = [{
            "Evidence ID": "E-001", "Source": str(spike_report), "Summary": "Evidence gap found",
            "Confidence": "High", "Uncertainty": "Runtime not observed", "Status": "Verified",
        }]
        spike_packet["claims"] = [{
            "Claim ID": "C-001", "Claim": "Existing Spike needs revision", "Evidence refs": "E-001",
            "Confidence": "High", "Uncertainty": "Runtime not observed", "Status": "Supported",
        }]
        spike_packet["decisions"] = [{
            "Decision ID": "D-001", "Decision": "Require Spike revision", "Claim refs": "C-001",
            "Owner": "Reviewer", "Status": "Applied",
        }]
        spike_packet["actions"] = [{
            "Action ID": "A-001", "Action": "Revise existing Spike", "Decision ref": "D-001",
            "Owner": "Work-item owner", "Status": "Proposed",
        }]
        spike_packet["durable_artifacts"].extend([
            {"Artifact": "Spike report", "Path": str(spike_report), "Status": "Created",
             "Purpose": "Technical Spike disposition and direct evidence"},
            {"Artifact": "Runtime closure", "Path": str(spike_root / "runtime_closure.json"),
             "Status": "Pending", "Purpose": "Provider receipt"},
            {"Artifact": "Work record", "Path": str(spike_root / "work_record.md"),
             "Status": "Pending", "Purpose": "Canonical terminal record"},
        ])
        spike_packet["handoff"] = {
            "workflow_result": "Changes required",
            "implementation_plan": "Not created; Technical Spike produces spike_report.md",
            "established": ["Existing Spike needs revision before Feature Delivery."],
            "best_current_explanations": [],
            "next_action": {"owner": "Work-item owner", "action": "Revise existing Spike.",
                            "complete_when": "Material evidence gap is closed."},
            "artifacts": [str(spike_report), str(spike_root / "work_record.md")],
            "execution": "deep/planning; validation passed; workers complete; state remains handoff pending packaged finalizer",
            "provenance": (
                f"plugin {spike_packet['identity']['Plugin package / version']}; framework revision "
                f"{'a' * 40} (dirty); playbook technical_spike {technical_spike_version}."
            ),
        }
        v15_packet = json.loads(json.dumps(spike_packet))
        v15_packet["playbook_selection"]["Primary goal"] = "technical_answer"
        v15_packet["identity"].update({
            "Requested profile": "standard", "Activated profile": "standard", "Executed profile": "standard",
            "Prompt template / revision / conformance": (
                f"templates/technical_spike_run_prompt.md / {technical_spike_prompt_version} / context-unverified"
            ),
            "State": "handoff", "Workflow outcome": "completed",
        })
        v15_packet["handoff"]["workflow_result"] = (
            "Partially answered; State: handoff; Workflow outcome: completed; Engineering outcome: partially_solved"
        )
        v15_errors = _technical_spike_packet_contract_errors(v15_packet, pre_release=True)
        assert "Technical Spike Primary goal must be Execute technical spike or Review technical spike" in v15_errors
        assert "Technical Spike prompt conformance must be pass or fail:<missing fields>" in v15_errors
        assert "Technical Spike pre-release State handoff requires a non-completed Workflow outcome" in v15_errors
        v15_result_packet = json.loads(json.dumps(v15_packet))
        v15_result_packet["playbook_selection"]["Primary goal"] = "Execute technical spike"
        v15_result_errors = _technical_spike_packet_contract_errors(v15_result_packet, pre_release=True)
        assert "Technical Spike handoff Workflow result must be exactly one of: Question answered, Partially answered, Inconclusive" in v15_result_errors
        empty_reasoning_packet = json.loads(json.dumps(spike_packet))
        empty_reasoning_packet.update({
            "evidence": [{"Evidence ID": "", "Source": "", "Summary": "", "Confidence": "",
                          "Uncertainty": "", "Status": ""}],
            "claims": [{"Claim ID": "", "Claim": "", "Evidence refs": "", "Confidence": "",
                        "Uncertainty": "", "Status": ""}],
            "decisions": [{"Decision ID": "", "Decision": "", "Claim refs": "", "Owner": "",
                           "Status": ""}],
            "actions": [{"Action ID": "", "Action": "", "Decision ref": "", "Owner": "",
                         "Status": ""}],
        })
        empty_reasoning_errors = _technical_spike_packet_contract_errors(
            empty_reasoning_packet, pre_release=True
        )
        assert any(
            "requires populated rows for: Evidence, Claims, Decision Log, Action Log" in error
            for error in empty_reasoning_errors
        )
        partial_reasoning_packet = json.loads(json.dumps(spike_packet))
        partial_reasoning_packet["claims"][0] = {
            "Claim ID": "C-001", "Claim": "", "Evidence refs": "E-001",
            "Confidence": "high", "Uncertainty": "None", "Status": "Supported",
        }
        partial_reasoning_errors = _technical_spike_packet_contract_errors(
            partial_reasoning_packet, pre_release=True
        )
        assert any(
            "incomplete reasoning rows: Claims row 1: Claim" in error
            for error in partial_reasoning_errors
        )
        placeholder_worker_packet = json.loads(json.dumps(spike_packet))
        placeholder_worker_packet["worker_results"][0]["Evidence / claim refs"] = (
            "To be normalized by handoff into exact E-* rows"
        )
        placeholder_errors = _technical_spike_packet_contract_errors(
            placeholder_worker_packet, pre_release=True
        )
        assert any(
            "spike-context Evidence / claim refs must be finalized" in error
            for error in placeholder_errors
        )
        grouped_packet = json.loads(json.dumps(spike_packet))
        grouped_packet["worker_results"][0]["Evidence / claim refs"] = "E-001 through E-002 / C-001"
        grouped_packet["handoff"]["established"][0] = "Existing Spike needs revision (E-001–E-002)."
        grouped_errors = _technical_spike_packet_contract_errors(
            grouped_packet, pre_release=True
        )
        assert any(
            "worker result spike-context" in error and "grouped/range reference" in error
            for error in grouped_errors
        )
        assert any(
            "handoff established[0]" in error and "grouped/range reference" in error
            for error in grouped_errors
        )
        orphan_packet = json.loads(json.dumps(spike_packet))
        orphan_packet["evidence"].append({
            "Evidence ID": "E-999", "Source": "orphaned source", "Summary": "Not used",
            "Confidence": "High", "Uncertainty": "None", "Status": "Verified",
        })
        orphan_errors = _technical_spike_packet_contract_errors(orphan_packet, pre_release=True)
        assert any(
            "orphaned evidence E-999; add E-999 to a claim's Evidence refs" in error
            for error in orphan_errors
        )
        generic_evidence_packet = json.loads(json.dumps(spike_packet))
        generic_evidence_packet["evidence"][0]["Summary"] = (
            "Current-run verified observation retained in analytical artifact."
        )
        assert any(
            "generic placeholder Summary" in error
            for error in _technical_spike_packet_contract_errors(generic_evidence_packet, pre_release=True)
        )
        spike_packet_path.write_text(json.dumps(spike_packet, indent=2) + "\n")
        spike_closure = spike_root / "runtime_closure.json"
        spike_handles = [f"01a00000-0000-7000-8000-{index:012d}" for index in range(1, 5)]
        spike_closure.write_text(json.dumps({"runtime_closure": [{
            "Run or stage": "Technical Spike", "Receipt owner": "Coordinator",
            "Completed worker handles": ", ".join(spike_handles), "Runtime status": "Released",
            "Remaining active handles": "None",
            "Closure evidence or blocker": f"Provider release confirmed. Completed handles: {', '.join(spike_handles)}.",
        }]}, indent=2) + "\n")
        completed_spike_packet = json.loads(json.dumps(spike_packet))
        completed_spike_packet["identity"]["State"] = "completed"
        incomplete_closure_errors = _planning_runtime_closure_errors(
            completed_spike_packet,
            [{
                "Run or stage": "Technical Spike", "Receipt owner": "Coordinator",
                "Completed worker handles": spike_handles[0], "Runtime status": "Released",
                "Remaining active handles": "None", "Closure evidence or blocker": "Provider release confirmed.",
            }],
        )
        assert any(
            "provider handles released=1; completed workers=4" in error
            for error in incomplete_closure_errors
        )
        spike_record = spike_root / "work_record.md"
        valid_spike_report = spike_report.read_text()
        candidate = spike_root / "spike_report.candidate.md"
        candidate.write_text(valid_spike_report)
        spike_report.write_text("previous valid report\n")
        unregistered_packet = json.loads(json.dumps(spike_packet))
        unregistered_packet["durable_artifacts"] = [
            row for row in unregistered_packet["durable_artifacts"]
            if Path(str(row.get("Path", ""))).name != "spike_report.md"
        ]
        spike_packet_path.write_text(json.dumps(unregistered_packet, indent=2) + "\n")
        try:
            publish_technical_spike_report(spike_packet_path, candidate)
        except ValueError as error:
            assert "must predeclare durable artifact spike_report.md" in str(error)
        else:
            raise AssertionError("the report must be predeclared before publication")
        assert candidate.exists()
        assert spike_report.read_text() == "previous valid report\n"
        stale_packet = json.loads(json.dumps(spike_packet))
        for artifact in stale_packet["durable_artifacts"]:
            if Path(str(artifact.get("Path", ""))).name == "spike_report.md":
                artifact["Path"] = str(candidate)
        stale_packet["handoff"]["artifacts"] = [
            str(value).replace("spike_report.md", "spike_report.candidate.md")
            for value in stale_packet["handoff"]["artifacts"]
        ]
        spike_packet_path.write_text(json.dumps(stale_packet, indent=2) + "\n")
        try:
            publish_technical_spike_report(spike_packet_path, candidate)
        except ValueError as error:
            assert "must reference published spike_report.md" in str(error)
        else:
            raise AssertionError("candidate references must be rejected before publication")
        assert candidate.exists()
        assert spike_report.read_text() == "previous valid report\n"
        spike_packet_path.write_text(json.dumps(spike_packet, indent=2) + "\n")
        publish_technical_spike_report(spike_packet_path, candidate)
        assert not candidate.exists()
        valid_spike_report = spike_report.read_text()
        publishing_packet = json.loads(json.dumps(spike_packet))
        for field in ("workers", "worker_results"):
            publishing_packet[field] = [
                row for row in publishing_packet[field] if row["Worker"] != "handoff"
            ]
        spike_packet_path.write_text(json.dumps(publishing_packet, indent=2) + "\n")
        candidate.write_text(valid_spike_report)
        publish_technical_spike_report(spike_packet_path, candidate)
        assert not candidate.exists()
        try:
            _validate_handoff(publishing_packet)
        except ValueError as error:
            assert "requires terminal results for: handoff" in str(error)
        else:
            raise AssertionError("pre-release must still require the completed Documenter")
        publishing_packet["worker_results"] = [
            row for row in publishing_packet["worker_results"] if row["Worker"] != "spike-context"
        ]
        spike_packet_path.write_text(json.dumps(publishing_packet, indent=2) + "\n")
        candidate.write_text(valid_spike_report)
        try:
            publish_technical_spike_report(spike_packet_path, candidate)
        except ValueError as error:
            assert "requires terminal results for: spike-context" in str(error)
        else:
            raise AssertionError("report publication must require completed analytical workers")
        candidate.unlink()
        spike_packet_path.write_text(json.dumps(spike_packet, indent=2) + "\n")
        invalid_candidate = valid_spike_report.replace("## Findings", "## Missing Findings")
        candidate.write_text(invalid_candidate)
        try:
            publish_technical_spike_report(spike_packet_path, candidate)
        except ValueError as error:
            assert "spike_report.md is missing ## Findings" in str(error)
        else:
            raise AssertionError("invalid candidate report must not be published")
        assert spike_report.read_text() == valid_spike_report
        assert not (spike_root / FINALIZATION_STATUS_FILENAME).exists()
        candidate.unlink()
        released_receipt = spike_closure.read_text()
        spike_closure.write_text(json.dumps({"runtime_closure": [{
            "Run or stage": "Technical Spike", "Receipt owner": "Coordinator",
            "Completed worker handles": "Unavailable", "Runtime status": "Blocked",
            "Remaining active handles": "Unknown",
            "Closure evidence or blocker": (
                "worker_runtime_release_unavailable: no exact provider-returned closure handle or release receipt "
                "was exposed for the completed workers. Provider traces were also unavailable."
            ),
        }]}, indent=2) + "\n")
        spike_record.write_text("prepared template\n")
        finalize(spike_packet_path, spike_closure, spike_record, blocked_runtime_snapshot=True)
        blocked_record = spike_record.read_text()
        blocked_receipt = spike_closure.read_text()
        assert "| State | blocked |" in blocked_record
        assert "| Workflow outcome | blocked |" in blocked_record
        assert "| Blocked | Unknown |" in expand_work_record(blocked_record, spike_root)
        assert "worker_runtime_release_unavailable" in blocked_record
        assert "| State | handoff |" not in blocked_record
        assert "state remains handoff" not in blocked_record.lower()
        assert "workflow remains in_progress" not in blocked_record.lower()
        assert json.loads(spike_packet_path.read_text())["identity"]["State"] == "handoff"
        spike_closure.write_text(json.dumps({"runtime_closure": [{
            "Run or stage": "Technical Spike", "Receipt owner": "Coordinator",
            "Completed worker handles": "Unavailable", "Runtime status": "Blocked",
            "Remaining active handles": "Unknown",
            "Closure evidence or blocker": "Provider release receipts unavailable for completed workers.",
        }]}, indent=2) + "\n")
        try:
            finalize(spike_packet_path, spike_closure, spike_record, blocked_runtime_snapshot=True)
        except ValueError as error:
            assert "worker_runtime_release_unavailable" in str(error)
        else:
            raise AssertionError("a blocked receipt must identify the unavailable-release blocker")
        assert spike_record.read_text() == blocked_record
        assert (spike_root / FINALIZATION_STATUS_FILENAME).exists()
        spike_closure.write_text(blocked_receipt)
        finalize(spike_packet_path, spike_closure, spike_record, blocked_runtime_snapshot=True)
        blocked_record = spike_record.read_text()
        assert "| State | blocked |" in blocked_record
        assert "| Blocked | Unknown |" in expand_work_record(blocked_record, spike_root)
        assert "worker_runtime_release_unavailable" in blocked_record
        assert not (spike_root / FINALIZATION_STATUS_FILENAME).exists()
        spike_closure.write_text(released_receipt)
        try:
            finalize(spike_packet_path, spike_closure, spike_record, blocked_runtime_snapshot=True)
        except ValueError as error:
            assert "Coordinator-owned receipt with Runtime status Blocked" in str(error)
        else:
            raise AssertionError("a released receipt must not create a blocked snapshot")
        assert spike_record.read_text() == blocked_record
        unavailable_with_false_zero = {"runtime_closure": [{
            "Run or stage": "Technical Spike", "Receipt owner": "Coordinator",
            "Completed worker handles": "Unavailable", "Runtime status": "Blocked",
            "Remaining active handles": "None",
            "Closure evidence or blocker": "worker_runtime_release_unavailable: provider release unknown.",
        }]}
        spike_closure.write_text(json.dumps(unavailable_with_false_zero))
        try:
            finalize(spike_packet_path, spike_closure, spike_record, blocked_runtime_snapshot=True)
        except ValueError as error:
            assert "Coordinator-owned receipt with Runtime status Blocked" in str(error)
        else:
            raise AssertionError("unavailable release cannot claim zero active handles")
        assert spike_record.read_text() == blocked_record
        spike_closure.write_text(released_receipt)
        spike_report.write_text(valid_spike_report.replace("## Direct Evidence", "## Missing Direct Evidence"))
        try:
            finalize(spike_packet_path, spike_closure, spike_record, pre_release=True)
        except ValueError as error:
            assert "spike_report.md is missing ## Direct Evidence" in str(error)
        else:
            raise AssertionError("the first correction must expose report errors after terminal normalization")
        spike_report.write_text(valid_spike_report)
        finalize(spike_packet_path, spike_closure, spike_record, pre_release=True)
        assert not (spike_root / FINALIZATION_STATUS_FILENAME).exists()
        premature_spike = json.loads(spike_packet_path.read_text())
        premature_spike["identity"]["State"] = "completed"
        spike_packet_path.write_text(json.dumps(premature_spike, indent=2) + "\n")
        try:
            finalize(spike_packet_path, spike_closure, spike_record, pre_release=True)
        except ValueError as error:
            assert "must keep State handoff" in str(error)
        else:
            raise AssertionError("pre-release finalization must own the terminal state transition")
        spike_packet_path.write_text(json.dumps(spike_packet, indent=2) + "\n")
        finalize(spike_packet_path, spike_closure, spike_record, pre_release=True)
        assert not (spike_root / FINALIZATION_STATUS_FILENAME).exists()
        assert "| Budget status | exceeded_during_finalization |" in spike_report.read_text()
        finalize(spike_packet_path, spike_closure, spike_record)
        spike_rendered = expand_work_record(spike_record.read_text(), spike_root)
        assert "Workflow result: Changes required" in spike_rendered
        assert "| State | completed |" in spike_rendered
        assert "| Workflow outcome | completed |" in spike_rendered
        assert "| Engineering outcome | partially_solved |" in spike_rendered
        assert "finalization validation passed" in spike_rendered
        assert "state remains handoff" not in spike_rendered.lower()
        assert "workflow remains in_progress" not in spike_rendered.lower()
        assert "| Last Updated | 2026-09-07T00:00:00Z |" not in spike_rendered
        assert re.search(
            r"\| Timebox or evidence budget \|[^|]*1 minutes[^|]*\|",
            spike_report.read_text(),
        ), spike_report.read_text()
        assert "| spike-context | Current-State Investigator |" in spike_rendered
        context_binding = spike_manifest["bindings"]["current_state_investigator"]
        assert f"{context_binding['model']} / {context_binding['effort']}" in spike_rendered
        assert "| Role-policy baseline ID | corrupted |" not in spike_rendered
        assert f"[spike_report.md]({spike_report.resolve()})" in spike_rendered
        incomplete_terminal = json.loads(spike_packet_path.read_text())
        incomplete_terminal["identity"].update({
            "State": "completed", "Workflow outcome": "completed", "Engineering outcome": "partially_solved",
        })
        incomplete_terminal["worker_results"] = [
            row for row in incomplete_terminal["worker_results"]
            if row.get("Worker") != "handoff"
        ]
        spike_packet_path.write_text(json.dumps(incomplete_terminal, indent=2) + "\n")
        try:
            finalize(spike_packet_path, spike_closure, spike_record)
        except ValueError as error:
            assert "requires terminal results for: handoff" in str(error)
        else:
            raise AssertionError("a Technical Spike cannot complete without the handoff worker")
        terminal_failure = json.loads((spike_root / FINALIZATION_STATUS_FILENAME).read_text())
        assert terminal_failure["phase"] == "terminal"
        assert terminal_failure["terminal_failure"] is True
        assert any("requires terminal results for: handoff" in error for error in terminal_failure["errors"])
        blocked_profile = json.loads(json.dumps(spike_packet))
        blocked_profile["identity"].update({
            "State": "completed", "Workflow outcome": "completed", "Engineering outcome": "partially_solved",
            "Profile status": "blocked", "Executed profile": "None",
        })
        spike_packet_path.write_text(json.dumps(blocked_profile, indent=2) + "\n")
        try:
            finalize(spike_packet_path, spike_closure, spike_record)
        except ValueError as error:
            assert "Profile status executed and matching profiles" in str(error)
        else:
            raise AssertionError("a blocked profile cannot produce a completed Technical Spike")
        spike_packet_path.write_text(json.dumps(spike_packet, indent=2) + "\n")
        malformed_spike = json.loads(spike_packet_path.read_text())
        malformed_spike["workers"] = {}
        spike_packet_path.write_text(json.dumps(malformed_spike, indent=2) + "\n")
        status_before_check = (spike_root / FINALIZATION_STATUS_FILENAME).read_text()
        try:
            finalize(spike_packet_path, spike_closure, spike_record, check_only=True)
        except ValueError as error:
            assert "packet_precheck_failed:packet_schema_invalid" in str(error)
        else:
            raise AssertionError("packet precheck must reject malformed shapes")
        assert (spike_root / FINALIZATION_STATUS_FILENAME).read_text() == status_before_check
        try:
            finalize(spike_packet_path, spike_closure, spike_record, pre_release=True)
        except ValueError as error:
            assert "packet_schema_invalid" in str(error)
        else:
            raise AssertionError("malformed packet shape must fail pre-release")
        shape_failure = json.loads((spike_root / FINALIZATION_STATUS_FILENAME).read_text())
        assert shape_failure["attempt_count"] == 1
        assert shape_failure["correction_allowed"] is True
        spike_packet_path.write_text(json.dumps(spike_packet, indent=2) + "\n")
        finalize(spike_packet_path, spike_closure, spike_record, pre_release=True)
        assert not (spike_root / FINALIZATION_STATUS_FILENAME).exists()
        broken_spike = json.loads(spike_packet_path.read_text())
        broken_spike["identity"].update({
            "State": "handoff", "Workflow outcome": "in_progress",
            "Engineering outcome": "partially_solved",
        })
        broken_spike["playbook_selection"]["Primary goal"] = "Create implementation plan"
        broken_spike["identity"]["Framework commit / status"] = "malformed"
        broken_spike["handoff"]["provenance"] = broken_spike["handoff"]["provenance"].replace(
            "a" * 40, "malformed"
        )
        spike_packet_path.write_text(json.dumps(broken_spike, indent=2) + "\n")
        for attempt in (1, 2):
            try:
                finalize(spike_packet_path, spike_closure, spike_record, pre_release=True)
            except ValueError as error:
                assert "Technical Spike Primary goal must be" in str(error)
                assert ("finalization_contract_failure:" in str(error)) == (attempt == 2)
            else:
                raise AssertionError("invalid corrected packet must fail pre-release")
        failure_receipt = json.loads((spike_root / FINALIZATION_STATUS_FILENAME).read_text())
        assert failure_receipt["attempt_count"] == 2
        assert failure_receipt["correction_allowed"] is False
        assert failure_receipt["shutdown_deadline"]
        try:
            finalize(spike_packet_path, spike_closure, spike_record, pre_release=True)
        except ValueError as error:
            assert "correction_limit_reached" in str(error)
        else:
            raise AssertionError("third pre-release attempt must stop before validation")
        source.write_text(json.dumps(packet))
        framework_revision = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        finalize(
            source, closure, record,
            coordinator_model_effort="Not applicable",
            framework_revision=framework_revision,
            framework_status="dirty",
        )
        assert f"{framework_revision} / Dirty" in record.read_text()
        source.write_text(json.dumps(packet))
        pending = {"runtime_closure": [dict(packet["runtime_closure"][0], **{
            "Runtime status": "Pending",
            "Closure evidence or blocker": "provider release pending",
        })]}
        pending_closure = root / "pending_runtime_closure.json"
        pending_closure.write_text(json.dumps(pending))
        pre_release_record = root / "pre-release-work-record.md"
        pre_release_record.write_text("existing record must remain untouched\n")
        snapshots_before_check = set(root.glob("finalization_snapshot.*.json"))
        finalize(source, pending_closure, pre_release_record, pre_release=True)
        assert pre_release_record.read_text() == "existing record must remain untouched\n"
        assert set(root.glob("finalization_snapshot.*.json")) == snapshots_before_check
        awaiting = json.loads(source.read_text())
        awaiting["identity"].update({
            "Profile status": "executed",
            "State": "awaiting_input",
            "Workflow outcome": "completed",
            "Engineering outcome": "partially_solved",
        })
        source.write_text(json.dumps(awaiting))
        finalize(source, pending_closure, pre_release_record, pre_release=True)
        assert pre_release_record.read_text() == "existing record must remain untouched\n"
        assert set(root.glob("finalization_snapshot.*.json")) == snapshots_before_check
        invalid_identity = json.loads(source.read_text())
        invalid_identity["identity"]["Profile status"] = "passed"
        source.write_text(json.dumps(invalid_identity))
        try:
            finalize(source, pending_closure, pre_release_record, pre_release=True)
        except ValueError as error:
            assert "invalid Profile status" in str(error)
        else:
            raise AssertionError("pre-release validation must reject invalid identity")
        invalid_summary = json.loads(source.read_text())
        invalid_summary["identity"]["Profile status"] = "blocked"
        invalid_summary["handoff"]["established"] = ["C-001"]
        source.write_text(json.dumps(invalid_summary))
        try:
            finalize(source, pending_closure, pre_release_record, pre_release=True)
        except ValueError as error:
            assert "expected a human-readable finding" in str(error)
        else:
            raise AssertionError("finalization must reject claim-ID-only summaries")
        source.write_text(json.dumps(packet))
        invalid = dict(packet)
        invalid["evidence"] = []
        source.write_text(json.dumps(invalid))
        before = record.read_text()
        try:
            finalize(source, closure, record)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid packet must fail")
        assert record.read_text() == before

        fixture = json.loads(
            V22_FIXTURE.read_text()
            .replace("__FRAMEWORK_ROOT__", str(ROOT))
            .replace("__ARTIFACT_ROOT__", str(root))
        )
        try:
            from scripts.prepare_run import resolve_bindings
        except ModuleNotFoundError:
            from scripts.prepare_run import resolve_bindings

        current_bindings = resolve_bindings("sentry_issue_remediation", None)
        fixture_bindings = fixture["files"]["role_bindings.json"]
        fixture_bindings["baseline_id"] = current_bindings["baseline_id"]
        for agent, binding in fixture_bindings["bindings"].items():
            binding["model"] = current_bindings["bindings"][agent]["model"]
            binding["effort"] = current_bindings["bindings"][agent]["effort"]
        fixture_packet_data = fixture["files"]["finalization_packet.json"]
        fixture["files"]["fix_design_result.json"]["plan"] = json.loads(
            V34_FINALIZATION_FIXTURE.read_text()
        )["fix_design_result"]["plan"]
        fixture_packet_data["identity"]["Framework commit / status"] = f"{'a' * 40} Clean; preflight passed"
        fixture_packet_data["identity"]["Playbook / version"] = (
            f"Sentry Issue Remediation / {sentry_playbook_version}"
        )
        fixture_packet_data["identity"]["Prompt template / revision / conformance"] = (
            f"templates/sentry_issue_run_prompt.md / {sentry_prompt_version} / pass"
        )
        fixture_packet_data["identity"]["Coordinator model/effort"] = "gpt-6-luna/medium"
        fixture_packet_data["handoff"]["workflow_result"] = "Workflow result: Ready for implementation"
        fixture_packet_data["handoff"]["next_action"] = {
            "owner": "Coordinator",
            "action": "Run pre-release finalizer, create runtime closure receipt, and obtain implementation approval.",
            "complete_when": "Final reconciliation and finalization schema are no longer Pending and implementation is approved.",
        }
        for worker in fixture_packet_data["workers"]:
            worker["Configured model/effort"] = worker["Configured model/effort"].replace(" / ", "/")
        fixture_closure_data = fixture["files"]["runtime_closure.json"]["runtime_closure"][0]
        fixture_closure_data["Completed worker handles"] = (
            "evidence 01a00000-0000-7000-8000-000000000001; "
            "fix 01a00000-0000-7000-8000-000000000002; "
            "documenter 01a00000-0000-7000-8000-000000000003"
        )
        for name, content in fixture["files"].items():
            target = root / name
            target.write_text(content if isinstance(content, str) else json.dumps(content, indent=2) + "\n")
        fixture_packet = root / "finalization_packet.json"
        fixture_closure = root / "runtime_closure.json"
        fixture_record = root / "v22_work_record.md"
        packet_before = fixture_packet.read_text()
        finalize(fixture_packet, fixture_closure, fixture_record)
        fixture_rendered = expand_work_record(fixture_record.read_text(), root)
        assert "Workflow result: Ready for implementation" in fixture_rendered
        assert f"templates/sentry_issue_run_prompt.md / {sentry_prompt_version} / pass" in fixture_rendered
        assert f"{'a' * 40} / Clean" in fixture_rendered
        assert f"playbooks/sentry_issue_remediation.md / {sentry_playbook_version}" in fixture_rendered
        assert "gpt-6-luna / medium" in fixture_rendered
        assert "evidence 01a00000" not in fixture_rendered
        assert "runtime closure released" in fixture_rendered
        assert "Workflow result: Workflow result:" not in fixture_rendered
        assert "Finalization schema | Passed |" in fixture_rendered
        assert "Action: obtain implementation approval." in fixture_rendered
        assert "Work-record budget exception" not in fixture_rendered
        assert fixture_packet.read_text() == packet_before

        malformed = json.loads(fixture_packet.read_text())
        del malformed["identity"]["State"]
        del malformed["handoff"]["next_action"]
        fixture_packet.write_text(json.dumps(malformed))
        try:
            finalize(fixture_packet, fixture_closure, fixture_record)
        except ValueError as error:
            message = str(error)
            assert "packet.identity.State is missing" in message
            assert "packet.handoff.next_action is missing" in message
        else:
            raise AssertionError("packet validation must report every structural error in one pass")
    with tempfile.TemporaryDirectory(prefix="workflow-analytical-failure-") as directory:
        execution_repository = Path(directory) / "repo"
        execution_repository.mkdir()
        subprocess.run(["git", "init", "-q", str(execution_repository)], check=True)
        subprocess.run(["git", "-C", str(execution_repository), "config", "user.email", "test@example.com"], check=True)
        subprocess.run(["git", "-C", str(execution_repository), "config", "user.name", "Test"], check=True)
        (execution_repository / "README.md").write_text("fixture\n")
        subprocess.run(["git", "-C", str(execution_repository), "add", "README.md"], check=True)
        subprocess.run(["git", "-C", str(execution_repository), "commit", "-qm", "fixture"], check=True)
        prepared = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "prepare_run.py"),
             "--execution-repository", str(execution_repository), "--work-item", "ITEM-FAIL",
             "--playbook", "sentry_issue_remediation"],
            capture_output=True, text=True, check=True,
        )
        prepared_data = json.loads(prepared.stdout)
        failure_root = Path(prepared_data["artifact_root"])
        evidence = failure_root / "normalized_evidence.md"
        evidence.write_text(json.loads(V29_CONTRACT_FAILURE_FIXTURE.read_text())["malformed_normalized_evidence"])
        failure_packet = failure_root / "finalization_packet.json"
        failure_closure = failure_root / "runtime_closure.json"
        failure_record = failure_root / "work_record.md"
        failure_closure.write_text(json.dumps({"runtime_closure": [{
            "Run or stage": "Current run", "Receipt owner": "Coordinator", "Runtime status": "Released",
            "Completed worker handles": "01a049e8-689e-7273-bd17-403d4d9a5022", "Remaining active handles": "None",
            "Closure evidence or blocker": "Provider release confirmed. Completed handles: 01a049e8-689e-7273-bd17-403d4d9a5022."}]}))
        framework_revision = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
        prepare_analytical_failure(
            failure_packet, failure_closure, failure_record,
            reason="contract delta separator missing",
            failure_stage="evidence_topology",
            completed_handles=["01a049e8-689e-7273-bd17-403d4d9a5022"],
            coordinator_model_effort="gpt-5.6-luna / xhigh", framework_revision=framework_revision,
            framework_status="dirty", evidence_artifact=evidence,
        )
        failure_text = expand_work_record(failure_record.read_text(), failure_root)
        assert "| State | blocked |" in failure_text
        assert "| Profile status | blocked |" in failure_text
        assert "| Runtime status |" in failure_text and "| Released | None |" in failure_text
        assert "Workflow result: Planning stopped on analytical contract failure" in failure_text
        assert "Workflow result: Pending" not in failure_text

        prepared_without_artifact = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "prepare_run.py"),
             "--execution-repository", str(execution_repository), "--work-item", "ITEM-NO-ARTIFACT",
             "--playbook", "sentry_issue_remediation"],
            capture_output=True, text=True, check=True,
        )
        missing_root = Path(json.loads(prepared_without_artifact.stdout)["artifact_root"])
        missing_record = missing_root / "work_record.md"
        (missing_root / "runtime_closure.json").write_text(json.dumps({"runtime_closure": [{
            "Run or stage": "Current run", "Receipt owner": "Coordinator", "Runtime status": "Released",
            "Completed worker handles": "None", "Remaining active handles": "None",
            "Closure evidence or blocker": "Provider confirms no workers activated; runtime released. Completed handles: None."}]}))
        prepare_analytical_failure(
            missing_root / "finalization_packet.json", missing_root / "runtime_closure.json", missing_record,
            reason="worker stopped before writing its assigned artifact",
            failure_stage="evidence_topology", completed_handles=[],
            coordinator_model_effort="gpt-5.6-luna / xhigh", framework_revision=framework_revision,
            framework_status="dirty", evidence_artifact=None,
        )
        missing_text = missing_record.read_text()
        assert "Workflow result: Planning stopped on analytical runtime failure" in missing_text
        assert "Evidence Topology ended without producing its assigned normalized evidence artifact" in missing_text
        assert "| Normalized evidence |" not in missing_text
        assert "Worker runtime receipt" in missing_text

        prepared_fix = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "prepare_run.py"),
             "--execution-repository", str(execution_repository), "--work-item", "ITEM-FIX",
             "--playbook", "sentry_issue_remediation"],
            capture_output=True, text=True, check=True,
        )
        fix_root = Path(json.loads(prepared_fix.stdout)["artifact_root"])
        fix_evidence = fix_root / "normalized_evidence.md"
        fix_evidence.write_text(json.loads(V29_CONTRACT_FAILURE_FIXTURE.read_text())["valid_normalized_evidence"])
        (fix_root / "fix_design_result.json").write_text(V31_FIX_DESIGN_FIXTURE.read_text())
        fix_packet_path = fix_root / "finalization_packet.json"
        fix_packet = json.loads(fix_packet_path.read_text())
        fix_manifest = json.loads((fix_root / "role_bindings.json").read_text())["bindings"]
        worker_specs = (
            ("evidence-topology", "Evidence topology", "sentry_current_state_investigator"),
            ("repository-integration", "Repository integration", "sentry_repository_integrator"),
            ("fix-design", "Fix design", "sentry_solution_architect"),
        )
        fix_packet["workers"] = []
        fix_packet["worker_results"] = []
        for worker, role, agent in worker_specs:
            model_effort = f"{fix_manifest[agent]['model']} / {fix_manifest[agent]['effort']}"
            fix_packet["workers"].append({
                "Worker": worker, "Role": role, "Assigned inputs": "IN-001",
                "Mode": "investigation", "Depth": "standard", "Skills": "Bounded Sentry analysis",
                "Tools": "Mapped provider operations", "Capacity": "one worker",
                "Configured model/effort": model_effort, "Provider-observed model/effort": model_effort,
                "Usage": "Provider telemetry unavailable", "Depends on": "Prior stage",
                "Outcome": "complete", "Confidence": "High",
            })
            fix_packet["worker_results"].append({
                "Worker": worker, "Outcome": "complete", "Confidence": "High",
                "Unique contribution": f"Completed {role}", "Evidence / claim refs": "E-001 / C-001",
                "Uncertainties / blockers": "None", "Actual model/effort": model_effort,
                "Usage/credits": "Provider telemetry unavailable",
            })
        fix_packet["synchronization"] = [{
            "Stage": "Analytical fan-in", "Workers launched": "all analytical workers",
            "Launch mode / exception": "Dependency ordered", "Worker outcomes": "complete",
            "Results summarized": "Yes", "Barrier status": "Pending Fix Design validation",
        }]
        fix_packet_path.write_text(json.dumps(fix_packet, indent=2) + "\n")
        fix_handles = [
            "01a04a1a-aa1d-7a62-9dde-f16dfac04be2",
            "01a04a20-70f2-7d51-aad4-5e17acd9f7a1",
            "01a04a25-9231-7531-a89d-0b1252f894fe",
        ]
        fix_closure = fix_root / "runtime_closure.json"
        fix_closure.write_text(json.dumps({"runtime_closure": [{
            "Run or stage": "Current run", "Receipt owner": "Coordinator",
            "Completed worker handles": ", ".join(fix_handles), "Runtime status": "Released",
            "Remaining active handles": "None",
            "Closure evidence or blocker": f"Provider release confirmed. Completed handles: {', '.join(fix_handles)}.",
        }]}, indent=2) + "\n")
        fix_record = fix_root / "work_record.md"
        prepare_analytical_failure(
            fix_packet_path, fix_closure, fix_record,
            reason="legacy validator required a literal normalized_evidence.md path",
            failure_stage="fix_design", completed_handles=fix_handles,
            coordinator_model_effort="gpt-5.6-luna / xhigh", framework_revision=framework_revision,
            framework_status="dirty", evidence_artifact=fix_evidence,
        )
        fix_text = expand_work_record(fix_record.read_text(), fix_root)
        assert "Normalized evidence passed and Fix Design returned" in fix_text
        assert "normalized evidence failed validation" not in fix_text
        assert "| repository-integration |" in fix_text
        assert all(handle in fix_text for handle in fix_handles)
    print("finalize_work_record self-test: passed")
