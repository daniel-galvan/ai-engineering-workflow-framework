"""Preserved prepare_run synthetic regression scenarios."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
from scripts.prepare_run import (
    ASSET_MANIFEST_TEMPLATE,
    BUNDLED_AGENTS,
    ROOT,
    RUN_BUDGET_FILENAME,
    RUN_INPUTS_FILENAME,
    SENTRY_AGENTS,
    SENTRY_FIX_DESIGN_NORMALIZER,
    SENTRY_PLANNING_FINALIZER,
    WORKER_RUNTIME_GUARD,
    _git,
    _playbook_name,
    _run_goal_row,
    _table_value,
    prepare_run,
    resolve_bindings,
)
from scripts.run_input_manifest import DEFAULT_PRECEDENCE_RULE, load_manifest


def self_test() -> None:
    import tempfile

    with tempfile.TemporaryDirectory(prefix="workflow-prepare-") as directory:
        execution = Path(directory)
        subprocess.run(["git", "init", "-q", str(execution)], check=True)
        subprocess.run(
            ["git", "-C", str(execution), "config", "user.email", "test@example.com"], check=True,
        )
        subprocess.run(
            ["git", "-C", str(execution), "config", "user.name", "Test"], check=True,
        )
        input_source = execution / "inputs.json"
        input_source.write_text(json.dumps({
            "schema_version": 1,
            "precedence_rule": DEFAULT_PRECEDENCE_RULE,
            "inputs": [{
                "Input ID": "USER-001",
                "Input or artifact": "Supplied current-run context",
                "Source or path": "Current user request",
                "Authority": "Authoritative current-run context",
                "Classification": "observed report or requested outcome",
                "Expected use": "Evidence worker and Fix Design",
                "Status": "Registered",
            }],
        }))
        first_input = execution / "first-input.md"
        second_input = execution / "second-input.md"
        first_input.write_text("first\n")
        second_input.write_text("second\n")
        line_reference_source = execution / "line-reference.md"
        line_reference_source.write_text("line reference\n")
        line_reference_manifest = execution / "line-reference-inputs.json"
        line_reference_manifest.write_text(json.dumps({
            "schema_version": 1,
            "precedence_rule": DEFAULT_PRECEDENCE_RULE,
            "inputs": [{
                "Input ID": "USER-LINE",
                "Input or artifact": "A source with a line reference",
                "Source or path": f"{line_reference_source}:12",
                "Authority": "Authoritative current-run context",
                "Status": "Registered",
            }],
        }))
        line_reference = load_manifest(line_reference_manifest, explicit=True)["inputs"][0]
        assert line_reference["path"] == str(line_reference_source.resolve())
        assert line_reference["availability"] == "available"
        composite_source = execution / "composite-inputs.json"
        composite_source.write_text(json.dumps({
            "schema_version": 1,
            "precedence_rule": DEFAULT_PRECEDENCE_RULE,
            "inputs": [{
                "Input ID": "USER-002",
                "Input or artifact": "Two supplied guidance files",
                "Source or path": f"{first_input}; {second_input}",
                "Authority": "Authoritative current-run context",
                "Status": "Registered",
            }],
        }))
        composite = load_manifest(composite_source, explicit=True)["inputs"][0]
        assert composite["availability"] == "available"
        assert composite["paths"] == [str(first_input.resolve()), str(second_input.resolve())]
        implicit_source = execution / "implicit-inputs.json"
        implicit_source.write_text(json.dumps({
            "schema_version": 1,
            "inputs": [{
                "Input ID": "USER-IMPLICIT",
                "Input or artifact": "Manifest without an explicit precedence rule",
                "Source or path": "Current user request",
                "Authority": "Authoritative current-run context",
                "Status": "Registered",
            }],
        }))
        implicit = load_manifest(implicit_source, explicit=True)
        assert implicit["precedence_rule"] == DEFAULT_PRECEDENCE_RULE
        subprocess.run(["git", "-C", str(execution), "add", "-A"], check=True)
        subprocess.run(
            ["git", "-C", str(execution), "commit", "-qm", "prepare fixture"], check=True,
        )
        expected_revision = _git(execution, "rev-parse", "HEAD")
        first = prepare_run(
            execution, "ITEM-1", "playbooks/sentry_issue_remediation.md", None, False,
            input_manifest=input_source,
        )
        assert first["playbook"] == "sentry_issue_remediation"
        assert first["bindings"]["sentry_solution_architect"]["model"] == "gpt-6.1-sol"
        assert first["provider_tool_mapping"]["repository_read"] == "exec_command"
        fixture = json.loads((ROOT / "tests" / "fixtures" / "v25_capability_mapping.json").read_text())
        assert first["provider_tool_mapping"] == fixture["expected_codex_mapping"]
        assert first["provider_configuration_source_status"] == "bundled / resolved"
        assert Path(first["fix_design_result_contract"]).is_file()
        assert Path(first["normalized_evidence_contract"]).is_file()
        assert first["worker_contracts"]["evidence_topology"]["contract"] == first[
            "normalized_evidence_contract"
        ]
        assert first["worker_contracts"]["fix_design"]["contract"] == first["fix_design_result_contract"]
        assert first["worker_runtime_guard"] == str(WORKER_RUNTIME_GUARD)
        activation_bundle = Path(first["activation_packet_bundle"]["path"])
        assert activation_bundle.is_file()
        evidence_packet = json.loads(activation_bundle.read_text())["packets"][
            "sentry_current_state_investigator"
        ]
        assert evidence_packet["required_prefix"] == "Coordinator initialization: complete"
        assert evidence_packet["developer_instructions"].startswith("Own raw Sentry evidence")
        assert evidence_packet["worker_contract"]["output"].endswith("normalized_evidence.md")
        assert hashlib.sha256(activation_bundle.read_bytes()).hexdigest() == first[
            "activation_packet_bundle"
        ]["sha256"]
        prepared_manifest = json.loads(Path(first["role_binding_manifest"]).read_text())
        assert prepared_manifest["worker_contracts"]["fix_design"]["normalizer"] == str(
            SENTRY_FIX_DESIGN_NORMALIZER
        )
        assert prepared_manifest["worker_contracts"]["standard_planning_finalization"]["finalizer"] == str(
            SENTRY_PLANNING_FINALIZER
        )
        runtime = execution / "agents"
        runtime.mkdir()
        for name in SENTRY_AGENTS:
            (runtime / f"{name}.toml").symlink_to(BUNDLED_AGENTS / f"{name}.toml")
        linked = resolve_bindings("sentry_issue_remediation", runtime)
        assert linked["provider_configuration_source_status"] == "runtime / resolved (9 definitions; 9 symlinked)"
        prepared_packet = json.loads(Path(first["finalization_packet"]).read_text())
        assert prepared_packet["work_item"]["ID"] == "ITEM-1"
        assert prepared_packet["repositories"][0]["Full revision"] == expected_revision
        assert prepared_packet["repositories"][0]["Clean status"] == "Clean"
        assert prepared_packet["identity"]["Run ID"].startswith("ITEM-1-")
        assert prepared_packet["work_item"]["Last Updated"].endswith("Z")
        assert prepared_packet["identity"]["Role binding manifest"] == first["role_binding_manifest"]
        assert prepared_packet["identity"]["Prompt template / revision / conformance"].endswith(" / pending")
        assert prepared_packet["durable_artifacts"][0]["Artifact"] == "Role bindings"
        assert first["run_input_manifest_status"] == "explicit"
        assert prepared_packet["inputs"][0]["Input ID"] == "USER-001"
        assert prepared_packet["run_input_manifest"]["status"] == "explicit"
        assert prepared_packet["identity"]["Coordinator execution"].startswith("active parent session")
        assert _playbook_name("Sentry Issue Remediation") == "sentry_issue_remediation"
        assert _playbook_name("Sentry Issue Remediation Playbook") == "sentry_issue_remediation"
        assert _playbook_name("Technical Spike") == "technical_spike"
        record = Path(first["work_record"])
        record.write_text(
            record.read_text().replace("| Run ID | |", "| Run ID | run-1 |").replace(
                "| State | intake |", "| State | completed |"
            )
        )
        second = prepare_run(
            execution, "ITEM-1", "sentry_issue_remediation", None, False,
            input_manifest=input_source,
        )
        assert second["archived_prior_run"].endswith("runs/run-1")
        assert Path(second["work_record"]).is_file()
        stale = prepare_run(
            execution, "ITEM-STALE", "sentry_issue_remediation", None, False,
            input_manifest=input_source,
        )
        stale_artifact = Path(stale["artifact_root"]) / "normalized_evidence.md"
        stale_artifact.write_text("preserved stale evidence\n")
        try:
            prepare_run(
                execution, "ITEM-STALE", "sentry_issue_remediation", None, False,
                input_manifest=input_source,
            )
        except ValueError as error:
            assert str(error) == "existing_run_not_terminal"
        else:
            raise AssertionError("unverified nonterminal run must block")
        recovered = prepare_run(
            execution, "ITEM-STALE", "sentry_issue_remediation", None, False,
            archive_stale_run=True, input_manifest=input_source,
        )
        archived_stale = Path(recovered["archived_prior_run"])
        assert archived_stale.name.startswith("stale-")
        assert (archived_stale / "normalized_evidence.md").read_text() == "preserved stale evidence\n"
        assert _table_value(Path(recovered["work_record"]).read_text(), "State") == "intake"
        try:
            prepare_run(execution, "ITEM-2", "playbooks/unknown.md", None, False)
        except ValueError as error:
            assert str(error) == "unknown_playbook:playbooks/unknown.md"
        else:
            raise AssertionError("unknown playbook must be rejected")
        invalid_source = execution / "invalid-inputs.json"
        invalid_source.write_text(json.dumps({
            "schema_version": 1,
            "precedence_rule": "",
            "inputs": [{
                "Input ID": "USER-INVALID",
                "Input or artifact": "Invalid fixture",
                "Source or path": "Current user request",
                "Authority": "Authoritative current-run context",
                "Status": "Registered",
            }],
        }))
        try:
            prepare_run(
                execution, "ITEM-INVALID", "sentry_issue_remediation", None, False,
                input_manifest=invalid_source,
            )
        except ValueError as error:
            assert str(error) == "run_input_manifest_precedence_rule_empty"
        else:
            raise AssertionError("invalid input manifest must be rejected before artifact creation")
        assert not (execution / ".thoughts" / "ITEM-INVALID").exists()
        goal_source = execution / "goal-inputs.json"
        goal_manifest = json.loads(input_source.read_text())
        goal_manifest["inputs"].append(_run_goal_row("spike_assessment"))
        goal_source.write_text(json.dumps(goal_manifest))
        spike_question = "Can the selected evidence answer the declared technical question?"
        spike_success = "A direct evidence-backed answer or an explicit unresolved unknown is recorded."
        try:
            prepare_run(
                execution, "ITEM-GOAL-CONFLICT", "technical_spike", None, False,
                input_manifest=input_source, workflow_objective="review_spike",
                requested_outcome="implementation_plan", started_at="2099-09-07T12:00:00Z",
                timebox_minutes=25, primary_question=spike_question, success_criterion=spike_success,
            )
        except ValueError as error:
            assert str(error).startswith("run_goal_conflict:")
        else:
            raise AssertionError("contradictory requested outcome and objective must block")
        assert not (execution / ".thoughts" / "ITEM-GOAL-CONFLICT").exists()
        try:
            prepare_run(
                execution, "ITEM-GOAL-INFERRED", "technical_spike", None, False,
                input_manifest=input_source, workflow_objective="review_spike",
                requested_outcome="spike_assessment", started_at="2099-09-07T12:00:00Z",
                timebox_minutes=25, primary_question=spike_question, success_criterion=spike_success,
            )
        except ValueError as error:
            assert str(error) == "run_goal_provenance_missing:RUN-GOAL-001"
        else:
            raise AssertionError("a compatible but unproven inferred outcome must block")
        assert not (execution / ".thoughts" / "ITEM-GOAL-INFERRED").exists()
        aligned = prepare_run(
            execution, "ITEM-GOAL-ALIGNED", "technical_spike", None, False,
            input_manifest=goal_source, workflow_objective="review_spike",
            requested_outcome="spike_assessment", started_at="2099-09-07T12:00:00Z",
            timebox_minutes=25, primary_question=spike_question, success_criterion=spike_success,
        )
        aligned_inputs = json.loads((Path(aligned["artifact_root"]) / RUN_INPUTS_FILENAME).read_text())["inputs"]
        aligned_packet = json.loads(Path(aligned["finalization_packet"]).read_text())
        assert aligned_packet["playbook_selection"]["Primary goal"] == "Review technical spike"
        assert {row["Input ID"] for row in aligned_inputs} >= {
            "RUN-GOAL-001", "RUN-GOAL-002", "SPIKE-QUESTION-001", "SPIKE-SUCCESS-001",
        }
        defaults = prepare_run(
            execution, "ITEM-DEFAULTS", "technical_spike", None, False,
            input_manifest=input_source, started_at="2099-09-07T12:00:00Z",
            primary_question=spike_question,
        )
        defaults_packet = json.loads(Path(defaults["finalization_packet"]).read_text())
        assert defaults_packet["playbook_selection"]["Primary goal"] == "Execute technical spike"
        assert any(
            row["Artifact"] == "Technical Spike report"
            and Path(row["Path"]).name == "spike_report.md"
            and row["Status"] == "Expected before terminal finalization"
            for row in defaults_packet["durable_artifacts"]
        )
        default_inputs = json.loads(
            (Path(defaults["artifact_root"]) / RUN_INPUTS_FILENAME).read_text()
        )["inputs"]
        default_by_id = {row["Input ID"]: row for row in default_inputs}
        assert defaults["run_budget"]["timebox_minutes"] == 35
        assert default_by_id["RUN-GOAL-001"]["Source or path"] == "Selected playbook defaults"
        assert default_by_id["SPIKE-SUCCESS-001"]["Source or path"] == "Selected playbook defaults"
        feature_defaults = prepare_run(
            execution, "ITEM-FEATURE-DEFAULTS", "feature_delivery", None, False,
            input_manifest=input_source,
        )
        feature_inputs = json.loads(
            (Path(feature_defaults["artifact_root"]) / RUN_INPUTS_FILENAME).read_text()
        )["inputs"]
        feature_by_id = {row["Input ID"]: row for row in feature_inputs}
        assert feature_defaults["requested_outcome"] == "implementation_plan"
        assert feature_defaults["workflow_objective"] == "implementation_planning"
        assert feature_by_id["RUN-GOAL-001"]["Input or artifact"] == (
            "Requested outcome: implementation_plan"
        )
        assert feature_by_id["RUN-GOAL-001"]["Source or path"] == "Selected playbook defaults"
        assert feature_by_id["RUN-GOAL-001"]["Authority"] == "Feature Delivery playbook configuration"
        assert feature_by_id["RUN-GOAL-002"]["Input or artifact"] == (
            "Workflow objective: implementation_planning"
        )
        assert feature_defaults["worker_contracts"]["feature_asset_inventory"]["contract"] == str(
            ASSET_MANIFEST_TEMPLATE
        )
        feature_bundle = json.loads(Path(feature_defaults["activation_packet_bundle"]["path"]).read_text())
        assert feature_bundle["packets"]["current_state_investigator"]["worker_contract"]["asset_inventory"]["output"].endswith(
            "asset_manifest.json"
        )
        techops = prepare_run(execution, "ITEM-TECHOPS", "techops_issue_remediation", None, False,
                              input_manifest=input_source)
        techops_bundle = json.loads(Path(techops["activation_packet_bundle"]["path"]).read_text())
        assert "does not require a sibling roster" in techops_bundle["packets"]["current_state_investigator"]["worker_contract"]["instructions"]
        assert "commit patch" in techops_bundle["packets"]["dependency_analyst"]["worker_contract"]["instructions"]
        assert "regression_fixture" in techops_bundle["packets"]["solution_architect"]["worker_contract"]["instructions"]
        assert "runtime_audits" in techops_bundle["packets"]["documenter"]["worker_contract"]["instructions"]
        assert any(
            row["Artifact"] == "Asset manifest"
            for row in json.loads(Path(feature_defaults["finalization_packet"]).read_text())["durable_artifacts"]
        )
        feature_goal_source = execution / "feature-goal-inputs.json"
        feature_goal_manifest = json.loads(input_source.read_text())
        feature_goal_manifest["inputs"].append(_run_goal_row("specification_assessment"))
        feature_goal_source.write_text(json.dumps(feature_goal_manifest))
        feature_assessment = prepare_run(
            execution, "ITEM-FEATURE-ASSESSMENT", "feature_delivery", None, False,
            input_manifest=feature_goal_source, workflow_objective="specification_assessment",
            requested_outcome="specification_assessment",
        )
        assessment_packet = json.loads(Path(feature_assessment["finalization_packet"]).read_text())
        assert assessment_packet["playbook_selection"]["Primary goal"] == "Specification assessment"
        assert any(
            row["Artifact"] == "Specification assessment"
            for row in assessment_packet["durable_artifacts"]
        )
        try:
            prepare_run(execution, "ITEM-FEATURE-NO-MANIFEST", "feature_delivery", None, False)
        except ValueError as error:
            assert str(error) == "run_input_manifest_required"
        else:
            raise AssertionError("Feature Delivery must require an explicit input manifest")
        assert not (execution / ".thoughts" / "ITEM-FEATURE-NO-MANIFEST").exists()
        try:
            prepare_run(
                execution, "ITEM-NO-QUESTION", "technical_spike", None, False,
                input_manifest=invalid_source, workflow_objective="review_spike",
                requested_outcome="spike_assessment", started_at="2099-09-07T12:00:00Z",
                timebox_minutes=25, success_criterion=spike_success,
            )
        except ValueError as error:
            assert str(error) == "run_prompt_incomplete:primary_question"
        else:
            raise AssertionError("Technical Spike must require a primary question")
        assert not (execution / ".thoughts" / "ITEM-NO-QUESTION").exists()
        default_success = prepare_run(
            execution, "ITEM-DEFAULT-SUCCESS", "technical_spike", None, False,
            input_manifest=goal_source, workflow_objective="review_spike",
            requested_outcome="spike_assessment", started_at="2099-09-07T12:00:00Z",
            timebox_minutes=25, primary_question=spike_question,
        )
        assert Path(default_success["artifact_root"]).is_dir()
        default_budget = prepare_run(
            execution, "ITEM-DEFAULT-BUDGET", "technical_spike", None, False,
            input_manifest=goal_source, workflow_objective="review_spike",
            requested_outcome="spike_assessment", started_at="2099-09-07T12:00:00Z",
            primary_question=spike_question, success_criterion=spike_success,
        )
        assert default_budget["run_budget"]["timebox_minutes"] == 35
        try:
            prepare_run(
                execution, "ITEM-NO-START", "technical_spike", None, False,
                input_manifest=goal_source, primary_question=spike_question,
            )
        except ValueError as error:
            assert str(error) == "run_budget_declaration_incomplete"
        else:
            raise AssertionError("Technical Spike must receive the captured start timestamp")
        assert not (execution / ".thoughts" / "ITEM-NO-START").exists()
        budgeted = prepare_run(
            execution, "ITEM-BUDGET", "technical_spike", None, False,
            input_manifest=goal_source, workflow_objective="review_spike",
            requested_outcome="spike_assessment", started_at="2099-09-07T12:00:00Z",
            timebox_minutes=25, primary_question=spike_question, success_criterion=spike_success,
        )
        budget_value = json.loads((Path(budgeted["artifact_root"]) / RUN_BUDGET_FILENAME).read_text())
        assert budget_value["deadline_at"] == "2099-09-07T12:25:00Z"
        assert budget_value["activation_deadline_at"] == "2099-09-07T12:23:00Z"
        assert budget_value["finalization_reserve_seconds"] == 120
        assert budgeted["run_budget"]["status"] == "within_budget"
        try:
            prepare_run(
                execution, "ITEM-BUDGET-EXPIRED", "technical_spike", None, False,
                input_manifest=goal_source, workflow_objective="review_spike",
                requested_outcome="spike_assessment", started_at="2000-01-01T00:00:00Z",
                timebox_minutes=1, primary_question=spike_question, success_criterion=spike_success,
            )
        except ValueError as error:
            assert str(error) == "run_budget_exhausted_before_activation"
        else:
            raise AssertionError("an exhausted budget must block before artifact creation")
        assert not (execution / ".thoughts" / "ITEM-BUDGET-EXPIRED").exists()
    print("prepare_run self-test: passed")
