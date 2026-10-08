"""Deterministic self tests validation rules."""

from __future__ import annotations

from pathlib import Path
from io import StringIO
import json
from contextlib import redirect_stdout
import tempfile
from .common import (
    CODEX_AGENT_DIR,
    INTERFACE_CONTRACT_FIELDS,
    MODEL_BASELINE_ID,
    RANGE_REFERENCE,
    ROOT,
    SENTRY_EVIDENCE_INPUT_MARKERS,
    V28_STABILIZATION_FIXTURE,
    V29_CONTRACT_FAILURE_FIXTURE,
    V31_FIX_DESIGN_FIXTURE,
    V32_FIX_DESIGN_RECOVERY_FIXTURE,
    V34_SENTRY_FINALIZATION_FIXTURE,
    V37_V38_RUNTIME_FIXTURE,
)
from .contracts import (
    WORK_ITEM_READ_RESULT_STATES,
    _contains_hypothesis,
    _mentions_user_source,
    fix_design_result_errors,
    jira_adapter_contract_errors,
    reasoning_record_errors,
    sentry_contract_delta_errors,
    sentry_upstream_boundary_errors,
    work_item_read_contract_errors,
)
from .markdown import (
    table_cells,
)
from .frontmatter import frontmatter_value
from .playbooks import (
    feature_assessment_disposition_error,
    technical_spike_disposition_error,
    technical_spike_report_errors,
)
from .provider_policy import (
    model_observation_unavailable,
)
from .work_records import (
    validate_work_record,
)
try:
    from asset_manifest import self_test as asset_manifest_self_test
except ModuleNotFoundError:
    from scripts.asset_manifest import self_test as asset_manifest_self_test
try:
    from review_evidence import REVIEW_FIXTURE, self_test as review_evidence_self_test
except ModuleNotFoundError:
    from scripts.review_evidence import REVIEW_FIXTURE, self_test as review_evidence_self_test


def self_test_reasoning_records() -> None:
    asset_manifest_self_test()
    review_evidence_self_test()
    assert table_cells(r"| Field | message \| link_title \| link_summary |") == [
        "Field", "message | link_title | link_summary"
    ]
    assert _mentions_user_source("current user request")
    assert not _mentions_user_source("/Users/dgalvan/projects/worker-result.json")
    valid_jira_fixture = {
        "request": {
            "capability": "work_item_read",
            "identity": {"source_system": "Jira", "key": "EXAMPLE-123"},
            "scope": ["item", "hierarchy", "history"],
            "requiredness": "required",
            "selection_reason": "Primary work item",
        },
        "result": {
            "state": "complete",
            "source_updated_at": "2026-09-04T18:00:00Z",
            "retrieved_at": "2026-09-04T18:01:00Z",
            "work_item": {
                "id": "10001",
                "source_system": "Jira",
                "type": "Story",
                "title": "Example work item",
                "description": "Synthetic fixture content",
            },
            "assets": [],
            "related_context": [],
            "evidence": [{
                "evidence_id": "jira-001",
                "source_location": "fields.summary",
                "authority": "direct_requirement",
                "status": "verified",
                "redacted": False,
            }],
            "limitations": [],
        },
    }
    assert jira_adapter_contract_errors(valid_jira_fixture) == []
    assert work_item_read_contract_errors(valid_jira_fixture) == []
    bounded_jira = json.loads(json.dumps(valid_jira_fixture))
    bounded_jira["request"]["scope"] = ["item"]
    bounded_jira["request"].pop("selection_reason")
    bounded_jira["result"].pop("assets")
    bounded_jira["result"]["limitations"] = ["Hierarchy, links, history, and assets not requested; bounded issue scope."]
    assert jira_adapter_contract_errors(bounded_jira) == []
    selected_history = json.loads(json.dumps(valid_jira_fixture))
    selected_history["request"].pop("selection_reason")
    assert any("selection_reason" in error for error in jira_adapter_contract_errors(selected_history))
    selected_history["request"]["scope"] = ["item", "history"]
    selected_history["request"]["selection_reason"] = "Report-bearing comments resolve the diagnosis."
    selected_history["result"]["limitations"] = ["Attachment inventory not requested; assets list does not prove empty."]
    assert jira_adapter_contract_errors(selected_history) == []
    selected_history["result"].pop("assets")
    assert any("explicit assets list" in error for error in jira_adapter_contract_errors(selected_history))
    for state in sorted(WORK_ITEM_READ_RESULT_STATES - {"complete"}):
        state_fixture = json.loads(json.dumps(valid_jira_fixture))
        state_fixture["result"]["state"] = state
        state_fixture["result"].pop("work_item")
        assert work_item_read_contract_errors(state_fixture) == [], state
    invalid_jira_fixture = json.loads(json.dumps(valid_jira_fixture))
    invalid_jira_fixture["request"]["scope"] = ["project_scan"]
    invalid_errors = jira_adapter_contract_errors(invalid_jira_fixture)
    assert "Jira integration fixture scope must contain valid non-empty scopes" in invalid_errors
    assert feature_assessment_disposition_error(
        "feature_delivery",
        "planning",
        "awaiting_input",
        "Specification assessment",
        "Not ready for implementation",
    ) is None
    assert feature_assessment_disposition_error(
        "feature_delivery",
        "planning",
        "ready_for_implementation",
        "Specification assessment",
        "Ready with explicit follow-ups",
    ) is None
    assert "requires Workflow result exactly one of" in feature_assessment_disposition_error(
        "feature_delivery",
        "planning",
        "ready_for_implementation",
        "Specification assessment",
        "Plan created",
    )
    assert technical_spike_disposition_error(
        "technical_spike", "planning", "completed", "Execute technical spike",
        "Question answered", "completed", "solved",
    ) is None
    assert technical_spike_disposition_error(
        "technical_spike", "planning", "completed", "Review technical spike",
        "Changes required", "completed", "partially_solved",
    ) is None
    assert "requires Engineering outcome solved" in technical_spike_disposition_error(
        "technical_spike", "planning", "completed", "Review technical spike",
        "Accepted", "completed", "partially_solved",
    )
    valid_spike_report = """---
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
| Objective | execute_spike |
| Primary question | Can the current boundary preserve the required data? |
| Assessment criteria or control domains | None declared |
| Timebox or evidence budget | 10 minutes; one repository trace and one focused test |
| Success criterion | Request and response behavior are established |
| Execution profile | standard |
| Repositories and revisions | abcdef1234567890abcdef1234567890abcdef12 |
| Review target | Not applicable |
| Comparison reference | Not applicable |
## Scope and Non-goals
Bounded path only.

## Plain-Language Summary
The check shows that the boundary keeps the data. Runtime behavior was not checked. The next step is to confirm the
same result after deployment.

## Integration Participants and Boundaries
| Participant or technology | Role or boundary | Evidence refs | Evidence status or unknown |
| --- | --- | --- | --- |
| Not applicable | Not applicable | Not applicable | No material integration participants |
## Method and Evidence
| Evidence ID | Method or source | Observation | Status | Limitation |
| --- | --- | --- | --- | --- |
| E-001 | Repository trace | Boundary preserves the data | Verified | Runtime not observed |
## Direct Evidence
| Evidence ID | Repository or source | Revision or version | File or artifact location | Observation | Status |
| --- | --- | --- | --- | --- | --- |
| E-001 | Execution repository | abcdef1 | src/boundary.py:10 | Boundary preserves the data | Verified |
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
| Boundary preserves data | Public request/response boundary | Focused test | Data retained or lost | Retained (E-001) | Supports answer |
## Findings
The current boundary preserves the required data (E-001).
## Options and Tradeoffs
| Option | Evidence | Benefits | Costs or risks | When to choose |
| --- | --- | --- | --- | --- |
| Keep boundary | E-001 | No change | Runtime unverified | Current scope |
## Recommendation
Keep the current boundary pending runtime confirmation (E-001).
## Reference Comparison
| Reference | Agreement | Difference or omission | Impact on recommendation |
| --- | --- | --- | --- |
| Not applicable | Not applicable | Not applicable | Not applicable |
## Remaining Unknowns and Follow-up
| Unknown or follow-up | Why it matters | Owner | Next evidence or decision |
| --- | --- | --- | --- |
| Runtime parity | Confirms deployment | Service owner | Observe deployment |
## Disposition
| Field | Value |
| --- | --- |
| Workflow result | Question answered |
| Question or review conclusion | Current boundary is sufficient |
| Budget status | within_budget |
| Feature Delivery handoff | Ready to consume |
"""
    assert technical_spike_report_errors(
        valid_spike_report, "Execute technical spike", "standard", "Question answered"
    ) == []
    workflow_metadata_summary = valid_spike_report.replace(
        "## Plain-Language Summary\n",
        "## Plain-Language Summary\nWorkflow result: Question answered.\n",
    )
    assert "must not contain workflow disposition metadata" in "\n".join(
        technical_spike_report_errors(
            workflow_metadata_summary, "Execute technical spike", "standard", "Question answered"
        )
    )
    mixed_source_report = valid_spike_report.replace(
        "| E-001 | Execution repository | abcdef1 | src/boundary.py:10 |",
        "| E-001 | Execution repository plus Jira and Slack | abcdef1 | src/boundary.py:10 |",
    )
    assert "combines sources" in "\n".join(
        technical_spike_report_errors(
            mixed_source_report, "Execute technical spike", "standard", "Question answered"
        )
    )
    assert "prepared execution repository revision" in "\n".join(
        technical_spike_report_errors(
            valid_spike_report, "Execute technical spike", "standard", "Question answered",
            expected_revisions=("f" * 40,),
        )
    )
    unanchored_method = valid_spike_report.replace(
        "| E-001 | Execution repository | abcdef1 | src/boundary.py:10 | Boundary preserves the data | Verified |",
        "| E-999 | Execution repository | abcdef1 | src/boundary.py:10 | Boundary preserves the data | Verified |",
    )
    assert "Evidence E-001 Method or source must include an exact source locator" in "\n".join(
        technical_spike_report_errors(
            unanchored_method, "Execute technical spike", "standard", "Question answered"
        )
    )
    generic_method_observation = unanchored_method.replace(
        "| E-001 | Repository trace | Boundary preserves the data | Verified | Runtime not observed |",
        "| E-001 | src/boundary.py:10 @ abcdef1 | Source-backed observation retained. | Verified | Runtime not observed |",
    )
    assert "Evidence E-001 Observation must describe the source-backed observation" in "\n".join(
        technical_spike_report_errors(
            generic_method_observation, "Execute technical spike", "standard", "Question answered"
        )
    )
    ambiguous_direct_location = valid_spike_report.replace(
        "src/boundary.py:10 | Boundary preserves the data",
        "src/boundary.py:10 or src/other.py:20 | Boundary preserves the data",
    )
    assert "File or artifact location must identify an exact" in "\n".join(
        technical_spike_report_errors(
            ambiguous_direct_location, "Execute technical spike", "standard", "Question answered"
        )
    )
    generic_direct_observation = valid_spike_report.replace(
        "src/boundary.py:10 | Boundary preserves the data",
        "src/boundary.py:10 | Current-run evidence observation.",
    )
    assert "Observation must describe the verified source observation" in "\n".join(
        technical_spike_report_errors(
            generic_direct_observation, "Execute technical spike", "standard", "Question answered"
        )
    )
    assert "must preserve the framework template frontmatter" in "\n".join(
        technical_spike_report_errors(
            valid_spike_report.split("---\n", 2)[2].lstrip(),
            "Execute technical spike", "standard", "Question answered",
        )
    )
    assert RANGE_REFERENCE.search("SA-E-001 through SA-E-015")
    assert RANGE_REFERENCE.search("SA-C-001 through SA-C-009")
    with tempfile.TemporaryDirectory(prefix="workflow-spike-context-") as directory:
        manifest_path = Path(directory) / "run_inputs.json"
        manifest_path.write_text(json.dumps({
            "schema_version": 1,
            "status": "explicit",
            "precedence_rule": "Current user decisions govern current-run evidence and scope.",
            "inputs": [{
                "Input ID": "IN-001", "Input or artifact": "Jira SPIKE-1",
                "Source or path": "Current user request", "Authority": "User",
                "Classification": "work item", "Expected use": "Bound question",
                "Status": "Registered",
            }],
        }))
        undeclared_context = valid_spike_report.replace(
            "| E-001 | Repository trace | Boundary preserves the data |",
            "| E-001 | Confluence 1397227555 | Boundary preserves the data |",
        )
        assert "undeclared external document locator" in "\n".join(
            technical_spike_report_errors(
                undeclared_context, "Execute technical spike", "standard", "Question answered",
                input_manifest_path=manifest_path,
            )
        )
        undeclared_url_context = valid_spike_report.replace(
            "| E-001 | Repository trace | Boundary preserves the data |",
            "| E-001 | Confluence https://yext.atlassian.net/wiki/pages/1397227555 | Boundary preserves the data |",
        )
        assert "undeclared external document locator" in "\n".join(
            technical_spike_report_errors(
                undeclared_url_context, "Execute technical spike", "standard", "Question answered",
                input_manifest_path=manifest_path,
            )
        )
        declared_context = json.loads(manifest_path.read_text())
        declared_context["inputs"].append({
            "Input ID": "IN-002", "Input or artifact": "Confluence 1397227555",
            "Source or path": "Current user request", "Authority": "User",
            "Classification": "supporting document", "Expected use": "Current-run evidence",
            "Status": "Registered",
        })
        manifest_path.write_text(json.dumps(declared_context))
        assert technical_spike_report_errors(
            undeclared_context, "Execute technical spike", "standard", "Question answered",
            input_manifest_path=manifest_path,
        ) == []
    invalid_decision_status = valid_spike_report.replace(
        "| Not applicable | No unresolved decision remains | None | None | Recorded |",
        "| Confirmed fact | Keep the current boundary | E-001 | Test owner | Recommended |",
    )
    assert "confirmed facts cannot use" in "\n".join(
        technical_spike_report_errors(
            invalid_decision_status, "Execute technical spike", "standard", "Question answered"
        )
    )
    declared_criteria = valid_spike_report.replace(
        "| Assessment criteria or control domains | None declared |",
        "| Assessment criteria or control domains | Data minimization; Query behavior |",
    )
    assert "declared 2, assessed 0" in "\n".join(
        technical_spike_report_errors(
            declared_criteria, "Execute technical spike", "standard", "Question answered"
        )
    )
    comma_safe_criteria = valid_spike_report.replace(
        "| Assessment criteria or control domains | None declared |",
        "| Assessment criteria or control domains | Data paths; Current access, transport and storage controls; "
        "Retention, deletion and downstream boundaries |",
    ).replace(
        "| Not applicable | Not applicable | No external assessment baseline declared | None | None |",
        "| Data paths | E-001 | Established | Runtime unverified | Observe deployment |\n"
        "| Current access, transport and storage controls | E-001 | Partially established | Deployment unverified | "
        "Observe deployment |\n"
        "| Retention, deletion and downstream boundaries | E-001 | Partially established | Downstream unverified | "
        "Trace lineage |",
    )
    assert technical_spike_report_errors(
        comma_safe_criteria, "Execute technical spike", "standard", "Question answered"
    ) == []
    mismatched_criteria = comma_safe_criteria.replace(
        "| Data paths | E-001 |", "| Different domain | E-001 |", 1
    )
    assert "Assessment Criteria names must match" in "\n".join(
        technical_spike_report_errors(
            mismatched_criteria, "Execute technical spike", "standard", "Question answered"
        )
    )
    reordered_sections = valid_spike_report.replace(
        "## Findings\nThe current boundary preserves the required data (E-001).\n"
        "## Options and Tradeoffs",
        "## Options and Tradeoffs",
    ).replace(
        "## Recommendation\n",
        "## Findings\nThe current boundary preserves the required data (E-001).\n"
        "## Recommendation\n",
    )
    assert "canonical sections must preserve" in "\n".join(
        technical_spike_report_errors(
            reordered_sections, "Execute technical spike", "standard", "Question answered"
        )
    )
    missing_option = valid_spike_report.replace(
        "| Keep boundary | E-001 | No change | Runtime unverified | Current scope |",
        "| | | | | |",
    )
    assert "requires one complete option row" in "\n".join(
        technical_spike_report_errors(
            missing_option, "Execute technical spike", "standard", "Question answered"
        )
    )
    vague_direct_location = valid_spike_report.replace(
        "| E-001 | Execution repository | abcdef1 | src/boundary.py:10 |",
        "| E-001 | Execution repository | abcdef1 | Scoped encryption search |",
    )
    assert "File or artifact location must identify an exact" in "\n".join(
        technical_spike_report_errors(
            vague_direct_location, "Execute technical spike", "standard", "Question answered"
        )
    )
    mixed_vague_direct_location = valid_spike_report.replace(
        "| E-001 | Execution repository | abcdef1 | src/boundary.py:10 |",
        "| E-001 | Execution repository | abcdef1 | src/boundary.py:10; targeted source/schema search |",
    )
    assert "File or artifact location must identify an exact" in "\n".join(
        technical_spike_report_errors(
            mixed_vague_direct_location, "Execute technical spike", "standard", "Question answered"
        )
    )
    vague_revision = valid_spike_report.replace(
        "| E-001 | Execution repository | abcdef1 |",
        "| E-001 | Execution repository | current working revision |",
    )
    assert "Revision or version must identify an exact" in "\n".join(
        technical_spike_report_errors(
            vague_revision, "Execute technical spike", "standard", "Question answered"
        )
    )
    grouped_option_reference = valid_spike_report.replace(
        "| Keep boundary | E-001 |",
        "| Keep boundary | E-02-E-05 |",
    )
    assert "Options and Tradeoffs" in "\n".join(
        technical_spike_report_errors(
            grouped_option_reference, "Execute technical spike", "standard", "Question answered"
        )
    )
    undeclared_option_reference = valid_spike_report.replace(
        "| Keep boundary | E-001 |",
        "| Keep boundary | E-999 |",
    )
    assert "references undeclared Evidence ID 'E-999'" in "\n".join(
        technical_spike_report_errors(
            undeclared_option_reference, "Execute technical spike", "standard", "Question answered"
        )
    )
    check_id_in_option = valid_spike_report.replace(
        "| Keep boundary | E-001 |",
        "| Keep boundary | CHK-001 |",
    )
    assert "is an experiment/check ID" in "\n".join(
        technical_spike_report_errors(
            check_id_in_option, "Execute technical spike", "standard", "Question answered"
        )
    )
    missing_option_reference = valid_spike_report.replace(
        "| Keep boundary | E-001 |",
        "| Keep boundary | Not applicable |",
    )
    assert "must cite at least one exact Evidence ID" in "\n".join(
        technical_spike_report_errors(
            missing_option_reference, "Execute technical spike", "standard", "Question answered"
        )
    )
    grouped_method_reference = valid_spike_report.replace(
        "| E-001 | Repository trace | Boundary preserves the data |",
        "| REPO-001–REPO-014 | Repository trace | Boundary preserves the data |",
    )
    assert "grouped/range reference" in "\n".join(
        technical_spike_report_errors(
            grouped_method_reference, "Execute technical spike", "standard", "Question answered"
        )
    )
    grouped_check_reference = valid_spike_report.replace(
        "| Boundary preserves data | Public request/response boundary | Focused test | Data retained or lost | Retained (E-001) | Supports answer |",
        "| Boundary preserves data | Public request/response boundary | Focused test | Data retained or lost | Retained (E-001–E-002) | Supports answer |",
    )
    assert "Experiments and Checks" in "\n".join(
        technical_spike_report_errors(
            grouped_check_reference, "Execute technical spike", "standard", "Question answered"
        )
    )
    grouped_finding_reference = valid_spike_report.replace(
        "The current boundary preserves the required data (E-001).",
        "The current boundary preserves the required data (E-001–E-002).",
    )
    assert "Findings" in "\n".join(
        technical_spike_report_errors(
            grouped_finding_reference, "Execute technical spike", "standard", "Question answered"
        )
    )
    missing_check_evidence = valid_spike_report.replace("Retained (E-001)", "Retained")
    assert "Experiments and Checks Boundary preserves data must cite" in "\n".join(
        technical_spike_report_errors(
            missing_check_evidence, "Execute technical spike", "standard", "Question answered"
        )
    )
    missing_finding_evidence = valid_spike_report.replace(
        "The current boundary preserves the required data (E-001).",
        "The current boundary preserves the required data.",
    )
    assert "spike_report.md ## Findings must cite" in "\n".join(
        technical_spike_report_errors(
            missing_finding_evidence, "Execute technical spike", "standard", "Question answered"
        )
    )
    missing_recommendation_evidence = valid_spike_report.replace(
        "Keep the current boundary pending runtime confirmation (E-001).",
        "Keep the current boundary pending runtime confirmation.",
    )
    assert "spike_report.md ## Recommendation must cite" in "\n".join(
        technical_spike_report_errors(
            missing_recommendation_evidence, "Execute technical spike", "standard", "Question answered"
        )
    )
    markdown_formatted_metadata = valid_spike_report.replace(
        "| Objective | execute_spike |", "| Objective | `execute_spike` |"
    ).replace("| Execution profile | standard |", "| Execution profile | `standard` |")
    assert technical_spike_report_errors(
        markdown_formatted_metadata, "Execute technical spike", "standard", "Question answered"
    ) == []
    v15_profile_drift = valid_spike_report.replace(
        "| Execution profile | standard |", "| Execution profile | standard / planning |"
    )
    assert "spike_report.md Execution profile must be standard" in technical_spike_report_errors(
        v15_profile_drift, "Execute technical spike", "standard", "Question answered"
    )
    invalid_decision_category = valid_spike_report.replace(
        "| Not applicable | No unresolved decision remains | None | None | Recorded |",
        "| Unknown | No unresolved decision remains | None | None | Recorded |",
    )
    assert "spike_report.md Decision Context Category" in "\n".join(
        technical_spike_report_errors(
            invalid_decision_category, "Execute technical spike", "standard", "Question answered"
        )
    )
    missing_observable_seam = valid_spike_report.replace(
        "| Boundary preserves data | Public request/response boundary | Focused test |",
        "| Boundary preserves data | | Focused test |",
    )
    assert "spike_report.md requires one complete experiment" in "\n".join(
        technical_spike_report_errors(
            missing_observable_seam, "Execute technical spike", "standard", "Question answered"
        )
    )
    assert "spike_report.md Workflow result must match Final Handoff" in technical_spike_report_errors(
        valid_spike_report, "Execute technical spike", "standard", "Inconclusive"
    )
    declared_without_comparison = valid_spike_report.replace(
        "| Comparison reference | Not applicable |", "| Comparison reference | existing-spike.md |"
    )
    assert "spike_report.md must compare the declared Comparison reference" in technical_spike_report_errors(
        declared_without_comparison, "Execute technical spike", "standard", "Question answered"
    )
    valid = """# Playbook Selection
| Primary evidence | Primary goal | Selected playbook | Closest alternative | Why this playbook |
| --- | --- | --- | --- | --- |
| Review comments | Improve controls | Feature Delivery | TechOps | Planned framework improvement |
# Repository Evidence Eligibility
| Repository role | Full revision |
| --- | --- |
| Execution | abcdef123456 |
# Run and Evaluation Identity
| Field | Value |
| --- | --- |
| Run ID | run-001 |
| Evaluation run ID | evaluation-001 |
| Playbook / version | playbooks/feature_delivery.md / 0.5.1 |
| Framework commit / status | 0123456789abcdef0123456789abcdef01234567 / Dirty |
| Plugin package / version | ai-engineering-workflows / 0.2.1 |
| Provider/runtime configuration | Not provided |
| Provider configuration source/status | bundled provider definitions / resolved |
| Prompt template / revision / conformance | templates/feature_delivery_run_prompt.md / __PROMPT_REVISION__ / pass |
| Role-policy baseline ID | codex-role-policy-gpt61-sol-luna-orchestrator-v20261001 |
| Role binding manifest | role_bindings.json |
| Provider / model configuration | Codex / Worker Execution Ledger |
| Coordinator model/effort | gpt-6-luna / medium |
| Requested profile | standard |
| Activated profile | standard |
| Executed profile | standard |
| Profile status | executed |
| Lifecycle | remediation |
| State | completed |
| Engineering state | validated |
| Workflow outcome | completed |
| Engineering outcome | solved |
# Worker Execution Ledger
| Worker | Role | Configured model/effort | Provider-observed model/effort | Usage |
| --- | --- | --- | --- | --- |
| Coordinator | Orchestrator | active session | active session | Unknown |
# Work Item
| Field | Value |
| --- | --- |
| Title | Example work item |
| Last Updated | 2026-08-26T00:00:00Z |
# Run Isolation and Finalization
| Field | Value |
| --- | --- |
| Concurrent-run decision | Isolated run |
| Related-run check | No related run reused |
| Durable artifact root | __ARTIFACT_ROOT__ |
| Final reconciliation | Passed; runtime closure released with no active handles |
| Finalization schema | Passed |
# Durable Artifacts
| Artifact | Path | Status | Purpose |
| --- | --- | --- | --- |
| runtime_closure.json | runtime_closure.json | Released | Provider receipt |
# Evaluation Run Continuation Ledger
| Sequence | Type | Trigger or new evidence | New input IDs | Previous terminal state | Recorded at | Outcome |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Initial | Request | IN-001 | None | 2026-08-26T00:00:00Z | completed |
# Evaluation Worker Activation Ledger
| Sequence | Continuation | Worker | Provider handle | Action | Input IDs | Observed at | Outcome or error |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 1 | Coordinator | coordinator | spawn | IN-001 | 2026-08-26T00:00:00Z | completed |
## Evaluation Worker Timing Ledger
| Worker | Provider handle | Activated | Started | Terminal | Elapsed |
| --- | --- | --- | --- | --- | --- |
| Coordinator | coordinator | 2026-08-26T00:00:00Z | 2026-08-26T00:00:00Z | 2026-08-26T00:00:01Z | PT1S |
# Worker Runtime Closure
| Run or stage | Receipt owner | Completed worker handles | Runtime status | Remaining active handles | Closure evidence or blocker |
| --- | --- | --- | --- | --- | --- |
| Final | Coordinator | 01a04174-7f58-7a12-b91d-9d171c43f012 | Released | None | provider release confirmation for 01a04174-7f58-7a12-b91d-9d171c43f012 |
# Worker Result Summary
| Worker | Outcome | Confidence | Unique contribution |
| --- | --- | --- | --- |
| Coordinator | completed | High | Finalized record |
# Evidence
| Evidence ID | Source |
| --- | --- |
| evidence-001 | test.log |
# Claims
| Claim ID | Evidence refs |
| --- | --- |
| claim-001 | evidence-001 |
# Decision Log
| Decision ID | Claim refs |
| --- | --- |
| decision-001 | claim-001 |
# Action Log
| Action ID | Decision ref |
| --- | --- |
| action-001 | decision-001 |
# Final Handoff
```text
Workflow result: Completed test run

- State: completed
- Engineering state: validated
- Workflow outcome: completed
- Engineering outcome: solved
- Implementation plan: omitted; test fixture

What we established:
- Validator controls passed.

Next action:
- Owner: Test owner
- Action: Retain the fixture.
- Complete when: The self-test passes.

Artifacts:
- work_record.md

Execution: standard/remediation; validation passed; workers complete; runtime released; source or external changes none.
Provenance: plugin ai-engineering-workflows 0.2.1; framework revision
0123456789abcdef0123456789abcdef01234567 (dirty); playbook feature_delivery 0.5.1.
```
"""
    prompt_revision = frontmatter_value(ROOT / "templates/feature_delivery_run_prompt.md", "version")
    valid = valid.replace("__PROMPT_REVISION__", prompt_revision)
    assert reasoning_record_errors(valid) == []
    invalid = valid.replace("| claim-001 | evidence-001 |", "| claim-001 | evidence-999 |")
    assert "claim-001 references missing evidence evidence-999" in reasoning_record_errors(invalid)
    assert "orphaned evidence evidence-001" in reasoning_record_errors(invalid)
    invalid_check_ref = valid.replace(
        "| claim-001 | evidence-001 |", "| claim-001 | evidence-001; CHK-001 |"
    )
    assert any(
        "claim-001 references missing evidence CHK-001; CHK-001 is an experiment/check ID, "
        "not an Evidence-table ID" in error
        for error in reasoning_record_errors(invalid_check_ref)
    )
    valid_check_evidence = valid.replace(
        "| evidence-001 | test.log |", "| CHK-001 | test.log |"
    ).replace("| claim-001 | evidence-001 |", "| claim-001 | CHK-001 |")
    assert reasoning_record_errors(valid_check_evidence) == []
    contract_delta = """# Contract Delta

| Boundary | Representation | Field identity / coordinate space | Evidence refs |
| --- | --- | --- | --- |
| Baseline | field-keyed object | field names | evidence-001 |
| Outbound | scalar message | field identity lost | evidence-002 |
| Destination input | scalar message | no field identity | evidence-003 |
| Return | scalar result | no field identity | evidence-004 |
| Semantic input equivalence | not_equivalent | Not applicable | evidence-001, evidence-002 |
"""
    assert sentry_contract_delta_errors(contract_delta) == []
    assert "contract delta is missing boundary: Return" in sentry_contract_delta_errors(
        contract_delta.replace("| Return | scalar result | no field identity | evidence-004 |\n", "")
    )
    ready_fix = {
        "worker_id": "fix-design",
        "worker_handle": "01a04174-7f58-7a12-b91d-9d171c43f012",
        "outcome": "complete",
        "plan_readiness": "ready_for_implementation",
        "implementation_plan_action": "create",
        "inputs_consumed": ["IN-001"],
        "context_conformance": "pass",
        "configuration_conformance": "pass",
        "checks_performed": ["Compared the source-of-truth input with the outbound contract."],
        "checks_remaining": ["Verify production parity before release."],
        "supported_remediation_boundary": "Outbound contract loses one required field.",
        "supported_intended_change": "Preserve the required field across the contract.",
        "interface_change": False,
        "interface_contract": None,
        "blocking_unknowns": [],
        "confidence": {
            "level": "high",
            "basis": "The current contract comparison identifies the field loss.",
            "limits": "Production parity remains to be verified.",
        },
    }
    assert fix_design_result_errors(ready_fix) == []
    assert _contains_hypothesis({"checks_performed": [{"hypothesis": "contract loss"}]})
    assert not _contains_hypothesis({"checks_performed": ["verified fact"]})
    assert any(
        "normalized_evidence.md" in error
        for error in fix_design_result_errors(
            ready_fix, required_input_markers=SENTRY_EVIDENCE_INPUT_MARKERS
        )
    )
    ready_fix_with_evidence = {**ready_fix, "inputs_consumed": ["IN-001", "/run/normalized_evidence.md"]}
    assert fix_design_result_errors(
        ready_fix_with_evidence, required_input_markers=SENTRY_EVIDENCE_INPUT_MARKERS
    ) == []
    malformed_fix = dict(ready_fix)
    malformed_fix.pop("worker_handle")
    malformed_errors = fix_design_result_errors(malformed_fix)
    assert any("fix design result is missing fields: worker_handle" in error for error in malformed_errors)
    malformed_interface = {
        **ready_fix_with_evidence,
        "interface_change": True,
        "interface_contract": {"surface": "Event payload"},
    }
    interface_errors = fix_design_result_errors(malformed_interface)
    assert "interface_contract request_shape must be a non-empty string" in interface_errors
    unresolved_interface = {
        **ready_fix_with_evidence,
        "interface_change": True,
        "interface_contract": {
            field: ("TBD; exact contract is required before rollout." if field != "surface" else "Event payload")
            for field in INTERFACE_CONTRACT_FIELDS
        },
    }
    unresolved_errors = fix_design_result_errors(unresolved_interface)
    assert any("contains unresolved semantics" in error for error in unresolved_errors)
    proposed_interface = {
        **ready_fix_with_evidence,
        "interface_change": True,
        "interface_contract": {
            "surface": "Proposed additive event payload contract.",
            "request_shape": "Preserve scalar text and add a proposed top-level text_fields map.",
            "response_shape": "Return field-local extents with a proposed field property for identity.",
            "absence_semantics": "Proposed fields are optional; missing values retain legacy fallback.",
            "compatibility_precedence": "Proposed keyed values win when present; scalar remains compatible.",
            "rollout": "Confirm proposed wire names during implementation before producer rollout.",
        },
    }
    assert fix_design_result_errors(proposed_interface) == []
    assert model_observation_unavailable("Not exposed; explicit launch binding was recorded")
    assert not model_observation_unavailable("Unknown")
    overcautious_fix = {
        **ready_fix,
        "plan_readiness": "awaiting_input",
        "implementation_plan_action": "omit",
        "blocking_unknowns": [
            {
                "decision_type": "indispensable_evidence",
                "question": "Which deployed revision ran?",
                "unavailable_reason": "Release mapping is unavailable.",
                "fix_implications": ["Preserve the required field."],
                "evidence_refs": ["evidence-001"],
                "invalidates_supported_change": False,
            }
        ],
    }
    overcautious_errors = fix_design_result_errors(overcautious_fix)
    assert any("materially different fixes" in error for error in overcautious_errors)
    assert any("cannot defer an established boundary" in error for error in overcautious_errors)
    cleared_candidate_fix = {
        **ready_fix,
        "plan_readiness": "awaiting_input",
        "implementation_plan_action": "omit",
        "supported_remediation_boundary": "",
        "supported_intended_change": "",
        "blocking_unknowns": [
            {
                "decision_type": "incompatible_alternatives",
                "question": "Which compatible wire representation should be selected?",
                "unavailable_reason": "Two representations remain under consideration.",
                "fix_implications": ["Use an additive top-level map.", "Use a nested versioned object."],
                "evidence_refs": ["evidence-001"],
                "invalidates_supported_change": False,
            }
        ],
        "clarification_brief": {
            "confirmed_facts": ["The current contract loses field identity."],
            "strongest_hypothesis": "An additive keyed representation preserves compatibility.",
            "feasible_options": ["Use an additive top-level map.", "Use a nested versioned object."],
            "recommendation": "Use the additive representation unless compatibility evidence rejects it.",
            "plain_language_next_action": "Choose the wire representation for implementation.",
        },
    }
    cleared_candidate_errors = fix_design_result_errors(cleared_candidate_fix)
    assert any("cannot clear the candidate boundary" in error for error in cleared_candidate_errors)
    v28 = json.loads(V28_STABILIZATION_FIXTURE.read_text())
    assert fix_design_result_errors(
        v28["fix_design_result"], required_input_markers=SENTRY_EVIDENCE_INPUT_MARKERS
    ) == []
    v31 = json.loads(V31_FIX_DESIGN_FIXTURE.read_text())
    assert fix_design_result_errors(
        v31["fix_design_result"], required_input_markers=SENTRY_EVIDENCE_INPUT_MARKERS
    ) == []
    v31_missing_handle = {**v31["fix_design_result"], "worker_handle": "not exposed"}
    assert "fix design worker_handle must contain the exact activation handle" in fix_design_result_errors(
        v31_missing_handle, required_input_markers=SENTRY_EVIDENCE_INPUT_MARKERS
    )
    v31_structured_interface = {
        **v31["fix_design_result"],
        "interface_change": True,
        "interface_contract": {
            "surface": ["event", "response"],
            "request_shape": {"text_fields": []},
            "response_shape": {"infractions": []},
            "absence_semantics": "Legacy fallback",
            "compatibility_precedence": "Keyed fields win",
            "rollout": ["Consumer first", "Producer second"],
        },
    }
    structured_errors = fix_design_result_errors(
        v31_structured_interface, required_input_markers=SENTRY_EVIDENCE_INPUT_MARKERS
    )
    for field in ("surface", "request_shape", "response_shape", "rollout"):
        assert f"interface_contract {field} must be a non-empty string" in structured_errors
    v32 = json.loads(V32_FIX_DESIGN_RECOVERY_FIXTURE.read_text())
    assert "fix design inputs_consumed must be a non-empty list" in fix_design_result_errors(
        v32["malformed_fix_design_result"], required_input_markers=SENTRY_EVIDENCE_INPUT_MARKERS
    )
    invalid_v28 = {
        **v28["fix_design_result"],
        "plan_readiness": "awaiting_input",
        "implementation_plan_action": "omit",
        "blocking_unknowns": [v28["invalid_runtime_blocker"]],
    }
    assert any(
        "contradicting_evidence_refs" in error for error in fix_design_result_errors(invalid_v28)
    )
    v37_v38 = json.loads(V37_V38_RUNTIME_FIXTURE.read_text())
    assert fix_design_result_errors(
        v37_v38["valid_awaiting_fix_design_result"],
        required_input_markers=SENTRY_EVIDENCE_INPUT_MARKERS,
    ) == []
    absence_only_errors = fix_design_result_errors(
        v37_v38["invalid_absence_only_blocker"],
        required_input_markers=SENTRY_EVIDENCE_INPUT_MARKERS,
    )
    assert any(
        v37_v38["expected_absence_only_error"] in error for error in absence_only_errors
    )
    v29 = json.loads(V29_CONTRACT_FAILURE_FIXTURE.read_text())
    assert sentry_contract_delta_errors(v29["malformed_normalized_evidence"]) == [
        v29["expected_malformed_error"]
    ]
    assert sentry_contract_delta_errors(v29["valid_normalized_evidence"]) == []
    v34 = json.loads(V34_SENTRY_FINALIZATION_FIXTURE.read_text())
    assert sentry_upstream_boundary_errors(
        v34["normalized_evidence"], v34["fix_design_result"], require_plan=True
    ) == []
    downstream_only = json.loads(json.dumps(v34["fix_design_result"]))
    downstream_only["interface_contract"]["request_shape"] = (
        "No inbound request-shape change; continue consuming the existing scalar message."
    )
    assert sentry_upstream_boundary_errors(
        v34["normalized_evidence"], downstream_only, require_plan=True
    ) == [
        "ready fix design must address the observed upstream field-preservation delta: "
        "include the producer boundary and an affirmative field-keyed request change"
    ]
    missing_identity = json.loads(json.dumps(v34["fix_design_result"]))
    missing_identity["interface_contract"]["response_shape"] = (
        "Return local extents for each infraction without a field property or qualification."
    )
    assert sentry_upstream_boundary_errors(
        v34["normalized_evidence"], missing_identity, require_plan=True
    ) == [
        "ready field-keyed interface must preserve field identity in the response contract; "
        "name a field property, key, identifier, or equivalent qualification"
    ]
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "work_record.md"
        valid = valid.replace("__ARTIFACT_ROOT__", str(path.parent))
        (path.parent / "runtime_closure.json").write_text("{}\n")
        (path.parent / "role_bindings.json").write_text(json.dumps({
            "baseline_id": MODEL_BASELINE_ID,
            "playbook": "feature_delivery",
            "bindings": {
                "current_state_investigator": {
                    "definition": str(CODEX_AGENT_DIR / "current_state_investigator.toml"),
                    "model": "gpt-6-luna",
                    "effort": "high",
                },
            },
        }))
        (path.parent / "code_review.md").write_text(REVIEW_FIXTURE)
        valid = valid.replace(
            "| runtime_closure.json | runtime_closure.json | Released | Provider receipt |",
            "| runtime_closure.json | runtime_closure.json | Released | Provider receipt |\n"
            "| code_review.md | code_review.md | Accepted | Review evidence |",
        ).replace("- work_record.md\n", "- work_record.md\n- code_review.md\n")
        path.write_text(valid)
        assert validate_work_record(path, require_terminal=True).startswith("Workflow result:")

        normal = valid.replace("| Evaluation run ID | evaluation-001 |", "| Evaluation run ID | Not applicable |")
        normal = normal.replace(
            "| Role-policy baseline ID | codex-role-policy-gpt61-sol-luna-orchestrator-v20261001 |",
            "| Role-policy baseline ID | Not applicable |",
        )
        normal = normal.replace("| Role binding manifest | role_bindings.json |", "| Role binding manifest | Not applicable |")
        normal = normal.replace(
            "| Provider / model configuration | Codex / Worker Execution Ledger |",
            "| Provider / model configuration | Generic / Worker Execution Ledger |",
        )
        normal = normal.replace("# Evaluation Run Continuation Ledger", "# Omitted Evaluation Run Continuation Ledger")
        normal = normal.replace("# Evaluation Worker Activation Ledger", "# Omitted Evaluation Worker Activation Ledger")
        normal = normal.replace("## Evaluation Worker Timing Ledger", "## Omitted Evaluation Worker Timing Ledger")
        path.write_text(normal)
        validate_work_record(path, require_terminal=True)

        def validation_output(record: str) -> str:
            path.write_text(record)
            captured = StringIO()
            with redirect_stdout(captured):
                try:
                    validate_work_record(path, require_terminal=True)
                except SystemExit:
                    pass
                else:
                    raise AssertionError("expected validation failure")
            return captured.getvalue()

        def assert_invalid(record: str, expected: str) -> None:
            output = validation_output(record)
            assert expected in output, output

        terminal = valid.replace(
            "01a04174-7f58-7a12-b91d-9d171c43f012 | Released | None | "
            "provider release confirmation for 01a04174-7f58-7a12-b91d-9d171c43f012",
            "/root/feature_context | Terminal | None | provider status snapshot "
            "2026-10-07T22:42:58Z: /root/feature_context=completed",
        ).replace("runtime closure released", "runtime closure terminal").replace(
            "runtime released", "runtime terminal",
        ).replace("| Released | Provider receipt |", "| Terminal | Provider receipt |")
        terminal += (
            "\n# Worker Terminal Observations\n\n"
            "| Provider handle | Provider status | Last dispatch at | Observed at | Status source |\n"
            "| --- | --- | --- | --- | --- |\n"
            "| /root/feature_context | completed | 2026-10-07T22:40:00Z | 2026-10-07T22:42:58Z | list_agents |\n"
        )
        path.write_text(terminal)
        validate_work_record(path, require_terminal=True)
        assert_invalid(terminal.replace("=completed", "=running"), "snapshot contains non-terminal workers")
        assert_invalid(terminal.replace("=completed", "=stopped"), "lacks exact provider terminal status")
        assert_invalid(terminal.replace("2026-10-07T22:42:58Z", "Unknown"), "timestamped provider status snapshot")
        assert_invalid(terminal.replace("| Terminal | None |", "| Terminal | Unknown |"), "zero active turns")

        path.write_text(valid.replace("| Released | None |", "| Released | None observed after close request |"))
        validate_work_record(path, require_terminal=True)
        assert_invalid(
            valid.replace("| Released | None |", "| Released | None observed but not checked |"),
            "released runtime closure must have no active handles",
        )
        assert_invalid(
            valid.replace(
                "01a04174-7f58-7a12-b91d-9d171c43f012 | Released",
                "/root/feature_context | Blocked",
            ),
            "never task paths or labels",
        )
        assert_invalid(
            valid.replace("| Review comments | Improve controls |", "| Review comments | Specification assessment |")
            .replace("| Related-run check | No related run reused |",
                     "| Active related run or work item | None reported by preparation |\n"
                     "| Related-run check | No scan performed |"),
            "Active related run None requires a timestamped provider-task and sibling-root check",
        )

        assert_invalid(
            valid.replace(
                "Execution: standard/remediation; validation passed; workers complete; runtime released; source or external changes none.",
                "Execution: State handoff; workflow remains in_progress pending Coordinator finalizer; runtime released.",
            ),
            "completed handoff Execution contains stale transitional state",
        )
        assert_invalid(
            valid.replace(
                "Execution: standard/remediation; validation passed; workers complete; runtime released; source or external changes none.",
                "Execution: standard/remediation; Workflow outcome: incomplete; runtime released.",
            ),
            "completed handoff Execution contains stale transitional state",
        )
        assert_invalid(
            valid.replace(
                "Execution: standard/remediation; validation passed; workers complete; runtime released; source or external changes none.",
                "Execution: standard/remediation; finalizer pending; runtime released.",
            ),
            "completed handoff Execution contains stale transitional state",
        )
        assert_invalid(
            valid.replace("## Evaluation Worker Timing Ledger", "## Missing Evaluation Worker Timing Ledger"),
            "Evaluation Worker Timing Ledger must contain populated timing rows",
        )
        assert_invalid(
            valid.replace(
                "| runtime_closure.json | runtime_closure.json | Released | Provider receipt |",
                "| runtime_closure.json | runtime_closure.json | Pending | Provider receipt |",
            ),
            "runtime-closure artifact status Released",
        )
        assert_invalid(
            valid.replace("| Evaluation run ID | evaluation-001 |", "| Evaluation run ID | Unknown |"),
            "Evaluation run ID must identify the evaluated run",
        )
        assert_invalid(
            valid.replace("| Role-policy baseline ID | codex-role-policy-gpt61-sol-luna-orchestrator-v20261001 |", "| Role-policy baseline ID | providers/codex/model_effort_policy.md |"),
            "Role-policy baseline ID must be an identifier, not a path",
        )
        assert_invalid(valid.replace("| TechOps |", "| None selected |"), "run-specific evidence")
        assert_invalid(
            valid.replace("templates/feature_delivery_run_prompt.md", "templates/work_record.md"),
            "Prompt template must match",
        )
        assert_invalid(
            valid.replace(
                f"templates/feature_delivery_run_prompt.md / {prompt_revision} / pass",
                "templates/feature_delivery_run_prompt.md / framework revision 0123456789abcdef / pass",
            ),
            f"Prompt template revision must be {prompt_revision}",
        )
        assert_invalid(
            valid.replace(
                "provider release confirmation for 01a04174-7f58-7a12-b91d-9d171c43f012",
                "all workers released",
            ),
            "requires provider release evidence",
        )
        assert_invalid(
            valid.replace("| Final | Coordinator |", "| Final | Documenter |"),
            "runtime closure Receipt owner received 'Documenter'; expected 'Coordinator'",
        )
        assert_invalid(
            valid.replace(
                "provider release confirmation for 01a04174-7f58-7a12-b91d-9d171c43f012",
                "provider release confirmation",
            ),
            "Closure evidence or blocker must identify completed handles",
        )
        assert_invalid(
            valid.replace("| Workflow outcome | completed |", "| Workflow outcome | incomplete |", 1),
            "state completed requires Workflow outcome completed",
        )
        assert_invalid(
            valid.replace("| Profile status | executed |", "| Profile status | completed |"),
            "invalid Profile status: completed",
        )
        assert_invalid(
            valid.replace("| Workflow outcome | completed |", "| Workflow outcome | partially_solved |", 1),
            "invalid Workflow outcome: partially_solved",
        )
        assert_invalid(
            valid.replace("| Released | None |", "| Unknown | Unknown |"),
            "completed workflow requires released or terminal runtime closure",
        )
        bound_worker = valid.replace(
            "| Coordinator | Orchestrator | active session | active session | Unknown |",
            "| evidence-topology | Current-State Investigator / Sentry Evidence | gpt-5.6-luna / low | "
            "gpt-5.6-luna / low | Unknown |",
        )
        assert_invalid(bound_worker, "configured model/effort received 'gpt-5.6-luna / low'; expected 'gpt-6-luna / high'")
        multiple = valid.replace("| Evaluation run ID | evaluation-001 |", "| Evaluation run ID | Unknown |")
        multiple = multiple.replace(
            "| Role-policy baseline ID | codex-role-policy-gpt61-sol-luna-orchestrator-v20261001 |",
            "| Role-policy baseline ID | providers/codex/model_effort_policy.md |",
        )
        output = validation_output(multiple)
        assert "Evaluation run ID must identify the evaluated run" in output
        assert "Role-policy baseline ID must be an identifier, not a path" in output

        legacy = path.with_name("legacy_work_record.md")
        legacy.write_text(
            "# Engineering Work Record\n\n"
            "## Identity and terminal contract\n\n"
            "| Field | Value |\n|---|---|\n| State | awaiting_input |\n"
        )
        with redirect_stdout(StringIO()):
            try:
                validate_work_record(legacy, require_terminal=True)
            except SystemExit:
                pass
            else:
                raise AssertionError("legacy compact work records must fail terminal validation")
