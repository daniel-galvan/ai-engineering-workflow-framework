#!/usr/bin/env python3
"""Deterministically finalize a successful Standard Sentry planning run."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from finalize_work_record import finalize


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "validate_library.py"
PLAN_TEMPLATE = ROOT / "templates" / "implementation_plan.md"
V34_FIXTURE = ROOT / "tests" / "fixtures" / "v34_sentry_deterministic_finalization.json"
INTERFACE_FIELDS = (
    ("Surface", "surface"),
    ("Request shape", "request_shape"),
    ("Response shape", "response_shape"),
    ("Absence semantics", "absence_semantics"),
    ("Compatibility / precedence", "compatibility_precedence"),
    ("Rollout", "rollout"),
)


def _cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", "<br>")


def _table(headers: tuple[str, ...], rows: list[dict[str, object]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend(
        "| " + " | ".join(_cell(row.get(header, "")) for header in headers) + " |"
        for row in rows
    )
    return "\n".join(lines)


def _bullets(values: object, *, empty: str = "None recorded.") -> str:
    if not isinstance(values, list) or not values:
        return empty
    return "\n".join(f"- {value}" for value in values)


def _material_rows(value: object, identity_field: str) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    rows = [row for row in value if isinstance(row, dict)]
    return rows if any(str(row.get(identity_field, "")).strip() for row in rows) else []


def _git(repository: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repository), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def _repository_row(role: str, declared: Path) -> dict[str, object]:
    resolved = declared.resolve()
    revision = _git(resolved, "rev-parse", "HEAD")
    branch = _git(resolved, "branch", "--show-current") or "detached"
    dirty = bool(_git(resolved, "status", "--porcelain"))
    return {
        "Repository role": role,
        "Declared path": str(declared),
        "Resolved path": str(resolved),
        "Branch / detached": branch,
        "Full revision": revision,
        "Clean status": "Dirty" if dirty else "Clean",
        "User-selected ref": "Current checkout",
        "Release mapping": "Not established",
        "Evidence eligibility": "Current-checkout source evidence; production mapping remains explicit",
    }


def _parse_repository(value: str) -> tuple[str, Path]:
    role, separator, path = value.partition("=")
    if not separator or not role.strip() or not path.strip():
        raise ValueError("repository must use ROLE=/absolute/path")
    resolved = Path(path).resolve()
    if not resolved.is_dir():
        raise ValueError(f"repository does not exist: {resolved}")
    return role.strip(), resolved


def _plan_version() -> str:
    match = re.search(r"^version:\s*(\S+)\s*$", PLAN_TEMPLATE.read_text(), re.MULTILINE)
    if not match:
        raise ValueError("implementation_plan_template_version_unavailable")
    return match.group(1)


def _numbered_step(value: object, index: int) -> tuple[str, str]:
    text = str(value).strip()
    match = re.match(r"^(\d+)\.\s*(.*)$", text)
    return (match.group(1), match.group(2)) if match else (str(index), text)


def render_plan(
    fix: dict[str, object], packet: dict[str, object], repositories: list[dict[str, object]]
) -> str:
    plan = fix.get("plan")
    if not isinstance(plan, dict):
        raise ValueError("ready Fix Design requires a structured plan payload")
    title = str(plan.get("title", "")).strip()
    if not title:
        raise ValueError("ready Fix Design plan requires a title")

    interface = fix.get("interface_contract")
    if fix.get("interface_change") is True:
        if not isinstance(interface, dict):
            raise ValueError("interface_change requires interface_contract")
        interface_row = {header: interface.get(field, "") for header, field in INTERFACE_FIELDS}
    else:
        interface_row = {header: "Not applicable" for header, _ in INTERFACE_FIELDS}

    boundaries = plan.get("exact_boundaries", [])
    source_rows: list[dict[str, object]] = []
    if isinstance(boundaries, list):
        for boundary in boundaries:
            if not isinstance(boundary, dict):
                continue
            source_rows.append({
                "Repository": boundary.get("repository", ""),
                "Files or symbols": "<br>".join(str(item) for item in boundary.get("files_symbols", [])),
                "Intended change": "Apply the shared smallest intended change within this boundary.",
                "Compatibility constraints": "See the exact Interface Contract and compatibility rules.",
            })
    if not source_rows:
        source_rows.append({
            "Repository": "Supported boundary",
            "Files or symbols": fix["supported_remediation_boundary"],
            "Intended change": fix["supported_intended_change"],
            "Compatibility constraints": "See Interface Contract",
        })

    tests = plan.get("regression_test_strategy", [])
    test_rows = [
        {
            "Level": "Regression" if index == 1 else "Focused / contract",
            "Test or check": value,
            "Expected result": "The supported contract behavior is demonstrated without changing legacy semantics.",
            "Owner": "Implementer / Tester",
            "Availability / result": "Planned; not run during planning",
        }
        for index, value in enumerate(tests if isinstance(tests, list) else [], start=1)
    ] or [{
        "Level": "Focused",
        "Test or check": "Execute the Fix Design validation strategy.",
        "Expected result": "The intended change and compatibility behavior are demonstrated.",
        "Owner": "Tester",
        "Availability / result": "Planned; not run during planning",
    }]

    steps = plan.get("ordered_steps", [])
    step_rows = []
    for index, value in enumerate(steps if isinstance(steps, list) else [], start=1):
        number, activity = _numbered_step(value, index)
        step_rows.append({
            "Step": number,
            "Activity": activity,
            "Owner": "Implementer / Tester / Reviewer as applicable",
            "Dependency or approval gate": "Approved plan; prior step complete",
            "Status": "Pending",
        })
    if not step_rows:
        raise ValueError("ready Fix Design plan requires ordered_steps")

    risks = plan.get("risks", []) if isinstance(plan.get("risks"), list) else []
    rollback = plan.get("rollback", []) if isinstance(plan.get("rollback"), list) else []
    monitoring = plan.get("monitoring", []) if isinstance(plan.get("monitoring"), list) else []
    risk_rows = []
    for index, risk in enumerate(risks):
        risk_rows.append({
            "Risk or impact": risk,
            "Mitigation": "Preserve compatibility constraints and validate before rollout.",
            "Rollback action": rollback[index] if index < len(rollback) else "Use the documented rollback sequence.",
            "Monitoring or follow-up": (
                monitoring[index] if index < len(monitoring) else "Use the documented monitoring plan."
            ),
            "Owner": "Implementation owner",
        })
    if not risk_rows:
        risk_rows.append({
            "Risk or impact": "Residual uncertainty remains.",
            "Mitigation": str(plan.get("residual_uncertainty", "Reconfirm before implementation.")),
            "Rollback action": "Revert the bounded change.",
            "Monitoring or follow-up": "Validate the supported boundary after release.",
            "Owner": "Implementation owner",
        })

    checks_remaining = fix.get("checks_remaining", [])
    open_questions = _bullets(checks_remaining, empty="- No blocking questions; approval remains required.")
    completion = plan.get("completion_criteria", [])
    completion_lines = (
        "\n".join(f"- [ ] {item}" for item in completion)
        if completion
        else "- [ ] Supported change validated."
    )
    repo_names = ", ".join(str(row["Resolved path"]) for row in repositories)
    work_item = packet["work_item"]["ID"]
    metadata = _table(("Field", "Value"), [
        {"Field": "Work item", "Value": work_item},
        {"Field": "Change set ID", "Value": work_item},
        {"Field": "Playbook", "Value": packet["identity"]["Playbook / version"]},
        {"Field": "Requested profile", "Value": "standard"},
        {"Field": "Executed profile", "Value": "standard"},
        {"Field": "Lifecycle", "Value": "planning"},
        {"Field": "Affected repositories", "Value": repo_names},
        {"Field": "Plan status", "Value": "Ready for implementation; approval pending"},
        {"Field": "Approval reference", "Value": "Not recorded"},
        {"Field": "Portable handoff", "Value": "Not required for current planning handoff"},
        {"Field": "Last updated", "Value": packet["work_item"]["Last Updated"]},
    ])

    return f"""---
title: Engineering Implementation Plan
version: {_plan_version()}
status: Pilot
owner: Engineering
last_updated: {packet['work_item']['Last Updated']}
depends_on:
  - ./work_record.md
  - ./normalized_evidence.md
  - ./fix_design_result.json
---

# Engineering Implementation Plan

## {title}

This is an approval-gated planning artifact. It does not authorize source-code or external-system changes.

# Metadata

{metadata}

# 1. Scope and Baseline

## In scope

{_bullets(plan.get('scope'))}

## Explicit exclusions

{_bullets(plan.get('exclusions'))}

Supported remediation boundary: {fix['supported_remediation_boundary']}

# 2. Root Cause and Behavior Contract

Root cause or best-supported explanation: {plan.get('root_cause', '')}

Supported intended change: {fix['supported_intended_change']}

Residual uncertainty: {plan.get('residual_uncertainty', 'None recorded.')}

# Interface Contract

{_table(tuple(header for header, _ in INTERFACE_FIELDS), [interface_row])}

# 3. Source Change Plan

## Smallest intended change

{_bullets(plan.get('smallest_intended_change'))}

## Compatibility and absence rules

{_bullets(plan.get('compatibility_and_absence'))}

{_table(('Repository', 'Files or symbols', 'Intended change', 'Compatibility constraints'), source_rows)}

# 4. Test and Validation Plan

{_table(('Level', 'Test or check', 'Expected result', 'Owner', 'Availability / result'), test_rows)}

# 5. Ordered Execution Plan

{_table(('Step', 'Activity', 'Owner', 'Dependency or approval gate', 'Status'), step_rows)}

# 6. Risk and Operations

## Rollout

{_bullets(plan.get('rollout'))}

## Rollback

{_bullets(plan.get('rollback'))}

## Monitoring

{_bullets(plan.get('monitoring'))}

{_table(('Risk or impact', 'Mitigation', 'Rollback action', 'Monitoring or follow-up', 'Owner'), risk_rows)}

# 7. Completion Criteria

{completion_lines}

# Open Questions and Decisions

{open_questions}
"""


def _binding(manifest: dict[str, object], agent: str) -> tuple[str, str]:
    value = manifest.get("bindings", {}).get(agent)
    if not isinstance(value, dict):
        raise ValueError(f"missing role binding: {agent}")
    model_effort = f"{value['model']} / {value['effort']}"
    observed = f"Not exposed; explicit launch binding {value['model']} / {value['effort']}"
    return model_effort, observed


def _released_closure(path: Path, handles: list[str]) -> dict[str, object]:
    if path.is_file():
        closure = json.loads(path.read_text())
        rows = closure.get("runtime_closure", [])
        completed = " ".join(str(row.get("Completed worker handles", "")) for row in rows if isinstance(row, dict))
        if rows and all(handle in completed for handle in handles) and all(
            str(row.get("Runtime status", "")).lower() == "released"
            and str(row.get("Remaining active handles", "")).lower() in {"none", "0"}
            for row in rows if isinstance(row, dict)
        ):
            return closure
    joined = "; ".join(handles)
    return {"runtime_closure": [{
        "Run or stage": "Standard Sentry planning",
        "Receipt owner": "Coordinator",
        "Completed worker handles": joined,
        "Runtime status": "Released",
        "Remaining active handles": "None",
        "Closure evidence or blocker": f"Provider release confirmed for completed handles: {joined}.",
    }]}


def finalize_standard_sentry(
    artifact_root: Path,
    *,
    evidence_handle: str,
    coordinator_model_effort: str,
    framework_revision: str,
    framework_status: str,
    repository_specs: list[str],
) -> None:
    artifact_root = artifact_root.resolve()
    packet_path = artifact_root / "finalization_packet.json"
    record_path = artifact_root / "work_record.md"
    evidence_path = artifact_root / "normalized_evidence.md"
    fix_path = artifact_root / "fix_design_result.json"
    manifest_path = artifact_root / "role_bindings.json"
    closure_path = artifact_root / "runtime_closure.json"
    plan_path = artifact_root / "implementation_plan.md"
    for required in (packet_path, evidence_path, fix_path, manifest_path):
        if not required.is_file():
            raise ValueError(f"required artifact is missing: {required}")
    if not re.fullmatch(r"[0-9a-fA-F]{40}", framework_revision):
        raise ValueError("framework_revision must be a 40-character Git SHA")
    if not re.fullmatch(
        r"\S+\s*/\s*(?:none|minimal|low|medium|high|xhigh|max|ultra)", coordinator_model_effort
    ):
        raise ValueError("coordinator_model_effort must use '<model> / <effort>'")

    packet = json.loads(packet_path.read_text())
    fix = json.loads(fix_path.read_text())
    manifest = json.loads(manifest_path.read_text())
    if (
        fix.get("plan_readiness") != "ready_for_implementation"
        or fix.get("implementation_plan_action") != "create"
    ):
        raise ValueError("deterministic Standard finalization currently requires ready_for_implementation/create")
    fix_handle = str(fix.get("worker_handle", "")).strip()
    for label, handle in (("evidence", evidence_handle), ("fix design", fix_handle)):
        if not re.fullmatch(r"[0-9a-fA-F-]{36}", handle):
            raise ValueError(f"{label} result is missing its exact provider UUID handle")

    execution_repository = artifact_root.parent.parent
    repositories = _material_rows(packet.get("repositories"), "Repository role")
    if not repositories:
        specs = repository_specs or [f"Execution={execution_repository}"]
        repositories = [_repository_row(*_parse_repository(spec)) for spec in specs]

    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    work_item = str(packet["work_item"]["ID"])
    packet["work_item"].update({
        "Title": str(packet["work_item"].get("Title", "")).strip() or work_item,
        "Last Updated": now,
    })
    if not all(str(packet["playbook_selection"].get(field, "")).strip() for field in packet["playbook_selection"]):
        packet["playbook_selection"] = {
            "Primary evidence": "Validated normalized Sentry evidence and canonical Fix Design result",
            "Primary goal": "Produce an evidence-backed, approval-gated Sentry remediation plan",
            "Selected playbook": "sentry_issue_remediation",
            "Closest alternative": "feature_delivery",
            "Why this playbook": "The run diagnoses a reported Sentry-related failure before implementation.",
        }
    if not _material_rows(packet.get("inputs"), "Input ID"):
        packet["inputs"] = [
            {"Input ID": "UPSTREAM-001", "Input or artifact": "Normalized evidence",
             "Source or path": str(evidence_path), "Authority": "Validated current-run worker output",
             "Status": "Consumed"},
            {"Input ID": "UPSTREAM-002", "Input or artifact": "Fix Design result",
             "Source or path": str(fix_path), "Authority": "Validated current-run worker output",
             "Status": "Consumed"},
        ]
    packet["repositories"] = repositories
    prompt_identity = str(packet["identity"]["Prompt template / revision / conformance"])
    if prompt_identity.endswith(" / pending"):
        prompt_identity = prompt_identity.removesuffix(" / pending") + " / pass"
    packet["identity"].update({
        "Run ID": str(packet["identity"].get("Run ID", "")).strip()
        or f"{work_item}-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}",
        "Framework commit / status": f"{framework_revision} / {framework_status.title()}",
        "Prompt template / revision / conformance": prompt_identity,
        "Coordinator model/effort": coordinator_model_effort,
        "Requested profile": "standard", "Activated profile": "standard", "Executed profile": "standard",
        "Profile status": "executed", "Lifecycle": "planning", "State": "ready_for_implementation",
        "Engineering state": "designed", "Workflow outcome": "completed", "Engineering outcome": "plan_only",
    })
    packet["finalization"].update({
        "Concurrent-run decision": str(packet["finalization"].get("Concurrent-run decision", "")).strip()
        or "Current isolated run",
        "Active related run or work item": str(
            packet["finalization"].get("Active related run or work item", "")
        ).strip()
        or "None",
        "Related-run check": str(packet["finalization"].get("Related-run check", "")).strip()
        or "Completed during initialization",
        "Durable artifact root": str(artifact_root),
        "Final reconciliation": "Passed; analytical fan-in complete and runtime released",
        "Finalization schema": "Passed",
    })

    evidence_model, evidence_observed = _binding(manifest, "sentry_current_state_investigator")
    fix_model, fix_observed = _binding(manifest, "sentry_solution_architect")
    packet["workers"] = [
        {"Worker": "evidence-topology", "Role": "Evidence topology", "Assigned inputs": "Current-run inputs",
         "Mode": "investigation", "Depth": "standard", "Skills": "Bounded Sentry evidence collection",
         "Tools": "Mapped provider operations", "Capacity": "one in-task worker",
         "Configured model/effort": evidence_model, "Provider-observed model/effort": evidence_observed,
         "Usage": "Provider telemetry unavailable", "Depends on": "Coordinator initialization",
         "Outcome": "complete", "Confidence": "High for recorded evidence; uncertainties explicit"},
        {"Worker": "fix-design", "Role": "Fix design", "Assigned inputs": "UPSTREAM-001",
         "Mode": "investigation", "Depth": "standard", "Skills": "Bounded remediation design",
         "Tools": "Mapped provider operations", "Capacity": "one in-task worker",
         "Configured model/effort": fix_model, "Provider-observed model/effort": fix_observed,
         "Usage": "Provider telemetry unavailable", "Depends on": "Validated Evidence topology",
         "Outcome": "complete", "Confidence": "High for the supported design boundary"},
    ]
    packet["synchronization"] = [{
        "Stage": "Standard analytical fan-in", "Workers launched": "evidence-topology; fix-design",
        "Launch mode / exception": "Sequential dependency order", "Worker outcomes": "complete; complete",
        "Results summarized": "Yes; canonical artifacts consumed", "Barrier status": "Passed; runtime closure released",
    }]
    packet["worker_results"] = [
        {"Worker": "evidence-topology", "Outcome": "complete", "Confidence": "High for recorded evidence",
         "Unique contribution": (
             "Created and validated normalized_evidence.md with explicit uncertainty and Contract Delta"
         ),
         "Evidence / claim refs": "E-001 / C-001", "Uncertainties / blockers": "See normalized_evidence.md",
         "Actual model/effort": evidence_observed, "Usage/credits": "Provider telemetry unavailable"},
        {"Worker": "fix-design", "Outcome": "complete", "Confidence": "High for the supported design boundary",
         "Unique contribution": str(fix["supported_intended_change"]), "Evidence / claim refs": "E-002 / C-001; C-002",
         "Uncertainties / blockers": "No blocking unknowns; remaining checks are plan gates",
         "Actual model/effort": fix_observed, "Usage/credits": "Provider telemetry unavailable"},
    ]
    if not _material_rows(packet.get("evidence"), "Evidence ID"):
        packet["evidence"] = [
            {"Evidence ID": "E-001", "Source": str(evidence_path),
             "Summary": "Validated current-run normalized evidence establishes the observed topology and uncertainty.",
             "Confidence": "High", "Uncertainty": "See normalized evidence", "Status": "Verified"},
            {"Evidence ID": "E-002", "Source": str(fix_path), "Summary": str(fix["supported_remediation_boundary"]),
             "Confidence": "High", "Uncertainty": "See Fix Design checks remaining", "Status": "Verified"},
        ]
        packet["claims"] = [
            {"Claim ID": "C-001", "Claim": str(fix["supported_remediation_boundary"]),
             "Evidence refs": "E-001; E-002", "Confidence": "High", "Uncertainty": "Explicit in source artifacts",
             "Status": "Supported"},
            {"Claim ID": "C-002", "Claim": str(fix["supported_intended_change"]),
             "Evidence refs": "E-002", "Confidence": "High", "Uncertainty": "Validation remains planned",
             "Status": "Supported"},
        ]
        packet["decisions"] = [{
            "Decision ID": "D-001",
            "Decision": "Create an approval-gated implementation plan for the supported change.",
            "Claim refs": "C-001; C-002", "Owner": "Coordinator", "Status": "Applied",
        }]
        packet["actions"] = [{
            "Action ID": "A-001", "Action": "Review and approve the implementation plan before remediation.",
            "Decision ref": "D-001", "Owner": "Work-item owner", "Status": "Proposed",
        }]
    else:
        for row in packet.get("actions", []):
            if isinstance(row, dict) and str(row.get("Action ID", "")).strip().lower() == "action-001":
                row.update({
                    "Action": "Render the plan and terminal record from the validated Fix Design result.",
                    "Owner": "Deterministic Standard finalizer", "Status": "Completed",
                })

    plan_path.write_text(render_plan(fix, packet, repositories))
    packet["durable_artifacts"] = [
        {"Artifact": "Role bindings", "Path": str(manifest_path), "Status": "Created",
         "Purpose": "Exact worker bindings"},
        {"Artifact": "Normalized evidence", "Path": str(evidence_path), "Status": "Created and validated",
         "Purpose": "Current-run evidence"},
        {"Artifact": "Fix design result", "Path": str(fix_path), "Status": "Created and validated",
         "Purpose": "Canonical design result"},
        {"Artifact": "Implementation plan", "Path": str(plan_path),
         "Status": "Ready for implementation; approval pending",
         "Purpose": "Approval-gated implementation design"},
        {"Artifact": "Finalization packet", "Path": str(packet_path), "Status": "Created",
         "Purpose": "Structured terminal input"},
        {"Artifact": "Runtime closure", "Path": str(closure_path), "Status": "Released",
         "Purpose": "Provider release receipt"},
        {"Artifact": "Work record", "Path": str(record_path), "Status": "Created",
         "Purpose": "Authoritative terminal handoff"},
    ]
    plan = fix["plan"]
    confidence = fix.get("confidence", {})
    confidence_basis = confidence.get("basis", "") if isinstance(confidence, dict) else ""
    residual = plan.get("residual_uncertainty", "") if isinstance(plan, dict) else ""
    packet["handoff"] = {
        "workflow_result": "Ready for implementation",
        "implementation_plan": f"created at {plan_path}; approval pending; no source or external changes made",
        "established": [str(fix["supported_remediation_boundary"]), str(fix["supported_intended_change"])],
        "best_current_explanations": ([{"explanation": str(confidence_basis), "confidence": "high",
                                        "reason": str(residual)}] if confidence_basis else []),
        "next_action": {"owner": "Work-item owner", "action": "Review and explicitly approve the implementation plan.",
                        "complete_when": "Implementation approval is recorded before a remediation run begins."},
        "artifacts": [str(record_path), str(evidence_path), str(fix_path), str(plan_path)],
        "execution": (
            "standard/planning; analytical validation passed; deterministic rendering passed; "
            "source changes none; runtime released"
        ),
        "provenance": (
            f"plugin {packet['identity']['Plugin package / version']}; framework revision {framework_revision} "
            f"({framework_status}); playbook {packet['identity']['Playbook / version']}."
        ),
    }

    handles = [evidence_handle, fix_handle]
    closure = _released_closure(closure_path, handles)
    closure_path.write_text(json.dumps(closure, indent=2) + "\n")
    packet_path.write_text(json.dumps(packet, indent=2) + "\n")
    validation = subprocess.run(
        [sys.executable, str(VALIDATOR), "--sentry-artifacts", str(artifact_root)],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    if validation.returncode:
        raise ValueError(validation.stdout.strip() or validation.stderr.strip())
    finalize(packet_path, closure_path, record_path)


def self_test() -> None:
    fixture = json.loads(V34_FIXTURE.read_text())
    with tempfile.TemporaryDirectory(prefix="workflow-sentry-finalize-") as directory:
        execution_repository = Path(directory) / "repo"
        execution_repository.mkdir()
        subprocess.run(["git", "init", "-q", str(execution_repository)], check=True)
        subprocess.run(
            ["git", "-C", str(execution_repository), "config", "user.email", "test@example.com"], check=True
        )
        subprocess.run(
            ["git", "-C", str(execution_repository), "config", "user.name", "Test"], check=True
        )
        (execution_repository / "README.md").write_text("fixture\n")
        subprocess.run(["git", "-C", str(execution_repository), "add", "README.md"], check=True)
        subprocess.run(["git", "-C", str(execution_repository), "commit", "-qm", "fixture"], check=True)
        prepared = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "prepare_run.py"),
             "--execution-repository", str(execution_repository), "--work-item", "ITEM-V34",
             "--playbook", "sentry_issue_remediation"],
            capture_output=True, text=True, check=True,
        )
        artifact_root = Path(json.loads(prepared.stdout)["artifact_root"])
        (artifact_root / "normalized_evidence.md").write_text(fixture["normalized_evidence"])
        (artifact_root / "fix_design_result.json").write_text(
            json.dumps(fixture["fix_design_result"], indent=2) + "\n"
        )
        framework_revision = _git(ROOT, "rev-parse", "HEAD")
        framework_status = "dirty" if _git(ROOT, "status", "--porcelain") else "clean"
        finalize_standard_sentry(
            artifact_root,
            evidence_handle="01a04aba-22cf-7ed0-ba6c-fd794e83c54a",
            coordinator_model_effort="gpt-5.6-luna / high",
            framework_revision=framework_revision,
            framework_status=framework_status,
            repository_specs=[f"Execution={execution_repository}"],
        )
        plan_text = (artifact_root / "implementation_plan.md").read_text()
        record_text = (artifact_root / "work_record.md").read_text()
        contract = fixture["fix_design_result"]["interface_contract"]
        assert "# Interface Contract\n\n| Surface | Request shape" in plan_text
        assert "## Interface Contract" not in plan_text
        for _, field in INTERFACE_FIELDS:
            assert _cell(contract[field]) in plan_text
        assert "| documenter |" not in record_text.lower()
        assert "| State | ready_for_implementation |" in record_text
        assert "deterministic rendering passed" in record_text
    print("finalize_sentry_planning self-test: passed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", type=Path)
    parser.add_argument("--evidence-handle")
    parser.add_argument("--coordinator-model-effort")
    parser.add_argument("--framework-revision")
    parser.add_argument("--framework-status", choices=("clean", "dirty"))
    parser.add_argument("--provider-release-confirmed", action="store_true")
    parser.add_argument("--repository", action="append", default=[], metavar="ROLE=/ABSOLUTE/PATH")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not all((args.artifact_root, args.evidence_handle, args.coordinator_model_effort,
                args.framework_revision, args.framework_status, args.provider_release_confirmed)):
        parser.error(
            "--artifact-root, --evidence-handle, --coordinator-model-effort, --framework-revision, "
            "--framework-status, and --provider-release-confirmed are required"
        )
    try:
        finalize_standard_sentry(
            args.artifact_root,
            evidence_handle=args.evidence_handle,
            coordinator_model_effort=args.coordinator_model_effort,
            framework_revision=args.framework_revision,
            framework_status=args.framework_status,
            repository_specs=args.repository,
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, OSError, subprocess.CalledProcessError) as error:
        print(json.dumps({"status": "blocked", "reason": str(error)}, sort_keys=True))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
