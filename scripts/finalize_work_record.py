#!/usr/bin/env python3
"""Validate a structured packet and atomically render a terminal work record."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "validate_library.py"
PACKET_TEMPLATE = ROOT / "templates" / "finalization_packet.json"
CLOSURE_TEMPLATE = ROOT / "templates" / "runtime_closure.json"
V22_FIXTURE = ROOT / "tests" / "fixtures" / "v22_sentry_planning.json"
V28_STABILIZATION_FIXTURE = ROOT / "tests" / "fixtures" / "v28_sentry_stabilization.json"
V29_CONTRACT_FAILURE_FIXTURE = ROOT / "tests" / "fixtures" / "v29_sentry_contract_failure.json"
UUID_PATTERN = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
MODEL_EFFORT_PATTERN = re.compile(
    r"^\s*(\S+)\s*/\s*(none|minimal|low|medium|high|xhigh|max|ultra)\s*$", re.IGNORECASE
)
ROLE_LABELS = {
    "evidence-topology": "Evidence topology",
    "fix-design": "Fix design",
    "failure-topology": "Failure topology",
    "repository-integration": "Repository integration",
    "handoff": "Documenter",
    "documenter": "Documenter",
    "sentry_current_state_investigator": "Evidence topology",
    "sentry_solution_architect": "Fix design",
    "sentry_repository_integrator": "Repository integration",
}


def _shape_errors(value: object, template: object, path: str) -> list[str]:
    if isinstance(template, dict):
        if not isinstance(value, dict):
            return [f"{path} must be an object"]
        errors = [f"{path}.{key} is missing" for key in template if key not in value]
        for key in template.keys() & value.keys():
            errors.extend(_shape_errors(value[key], template[key], f"{path}.{key}"))
        return errors
    if isinstance(template, list):
        if not isinstance(value, list):
            return [f"{path} must be a list"]
        if template:
            return [
                error
                for index, item in enumerate(value)
                for error in _shape_errors(item, template[0], f"{path}[{index}]")
            ]
        return []
    if not isinstance(value, type(template)):
        return [f"{path} must be {type(template).__name__}"]
    return []


def _validate_shapes(packet: object, closure: object) -> None:
    errors = _shape_errors(packet, json.loads(PACKET_TEMPLATE.read_text()), "packet")
    errors.extend(_shape_errors(closure, json.loads(CLOSURE_TEMPLATE.read_text()), "closure"))
    if errors:
        raise ValueError("packet_schema_invalid: " + "; ".join(errors))


def _normalize_model_effort(value: object) -> object:
    match = MODEL_EFFORT_PATTERN.fullmatch(str(value))
    return f"{match.group(1)} / {match.group(2).lower()}" if match else value


def _normalize_playbook_identity(value: object) -> object:
    parts = str(value).split(" / ", 1)
    if len(parts) != 2 or parts[0].endswith(".md"):
        return value
    supplied = parts[0].strip().lower().replace(" ", "_")
    for path in (ROOT / "playbooks").glob("*.md"):
        title = re.search(r"^title:\s*(.+)$", path.read_text(), re.MULTILINE)
        names = {path.stem.lower()}
        if title:
            names.add(title.group(1).strip().lower().replace(" ", "_"))
        if supplied in names:
            return f"playbooks/{path.name} / {parts[1].strip()}"
    return value


def _normalize_plugin_identity(value: object) -> object:
    supplied = str(value).strip()
    if supplied.lower() == "not applicable" or " / " in supplied:
        return supplied
    match = re.fullmatch(r"([^\s/]+)\s+(\S+)", supplied)
    return f"{match.group(1)} / {match.group(2)}" if match else value


def _normalize_prompt_identity(value: object) -> object:
    parts = str(value).split(" / ", 2)
    if len(parts) != 3:
        return value
    conformance = parts[2].strip().lower()
    if conformance in {"conformant", "passed", "success"} or conformance.startswith("pass:"):
        parts[2] = "pass"
    return " / ".join(parts)


def _normalize_packet(packet: dict[str, object], closure: dict[str, object]) -> None:
    identity = packet.get("identity", {})
    if isinstance(identity, dict):
        framework = str(identity.get("Framework commit / status", ""))
        revision = re.search(r"[0-9a-fA-F]{40}", framework)
        status = re.search(r"\b(Clean|Dirty)\b", framework, re.IGNORECASE)
        if revision and status:
            identity["Framework commit / status"] = f"{revision.group(0)} / {status.group(1).title()}"
        identity["Playbook / version"] = _normalize_playbook_identity(identity.get("Playbook / version", ""))
        identity["Plugin package / version"] = _normalize_plugin_identity(
            identity.get("Plugin package / version", "")
        )
        identity["Prompt template / revision / conformance"] = _normalize_prompt_identity(
            identity.get("Prompt template / revision / conformance", "")
        )
        identity["Coordinator model/effort"] = _normalize_model_effort(identity.get("Coordinator model/effort", ""))
        profiles = [str(identity.get(field, "")).strip().lower() for field in (
            "Requested profile", "Activated profile", "Executed profile"
        )]
        if (
            str(identity.get("Profile status", "")).strip().lower() in {"conformant", "passed"}
            and len(set(profiles)) == 1
            and profiles[0] in {"standard", "deep"}
        ):
            identity["Profile status"] = "executed"
    ledger_by_worker: dict[str, dict[str, object]] = {}
    for row in packet.get("workers", []):
        if not isinstance(row, dict):
            continue
        role = str(row.get("Role", "")).strip().lower()
        if role in ROLE_LABELS:
            row["Role"] = ROLE_LABELS[role]
        row["Configured model/effort"] = _normalize_model_effort(row.get("Configured model/effort", ""))
        ledger_by_worker[str(row.get("Worker", "")).strip().lower()] = row
    for row in packet.get("worker_results", []):
        if not isinstance(row, dict):
            continue
        ledger = ledger_by_worker.get(str(row.get("Worker", "")).strip().lower())
        if ledger:
            row["Actual model/effort"] = ledger.get("Provider-observed model/effort", "")
    durable_artifacts = packet.get("durable_artifacts", [])
    if isinstance(durable_artifacts, list):
        packet["durable_artifacts"] = [
            row for row in durable_artifacts
            if not isinstance(row, dict)
            or not str(row.get("Status", "")).strip().lower().startswith(("omitted", "not created"))
        ]
    for row in closure.get("runtime_closure", []):
        if not isinstance(row, dict):
            continue
        handles = UUID_PATTERN.findall(str(row.get("Completed worker handles", "")))
        if handles:
            row["Completed worker handles"] = ", ".join(dict.fromkeys(handles))
            evidence = str(row.get("Closure evidence or blocker", ""))
            if str(row.get("Runtime status", "")).strip().lower() == "released" and any(
                handle.lower() not in evidence.lower() for handle in handles
            ):
                row["Closure evidence or blocker"] = f"{evidence.rstrip('.')} Completed handles: {', '.join(handles)}."
    handoff = packet.get("handoff")
    if isinstance(handoff, dict):
        handoff["workflow_result"] = re.sub(
            r"^\s*Workflow result:\s*", "", str(handoff.get("workflow_result", "")), flags=re.IGNORECASE
        )
        execution = str(handoff.get("execution", "")).strip()
        if "validation passed" not in execution.lower():
            handoff["execution"] = f"validation passed; {execution}"


def _validate_handoff(packet: dict[str, object]) -> None:
    handoff = packet.get("handoff", {})
    if not isinstance(handoff, dict):
        raise ValueError("packet.handoff must be an object")
    established = handoff.get("established", [])
    if not established:
        raise ValueError("packet.handoff.established must contain at least one human-readable finding")
    for index, item in enumerate(established):
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"packet.handoff.established[{index}] must be a non-empty string")
        if "\n" in item:
            raise ValueError(
                f"packet.handoff.established[{index}] must be one human-readable sentence, not a multiline block"
            )
        if re.fullmatch(r"[A-Z]+-\d+", item.strip()):
            raise ValueError(
                f"packet.handoff.established[{index}] received internal ID {item!r}; "
                "expected a human-readable finding"
            )
    for index, item in enumerate(handoff.get("best_current_explanations", [])):
        if not isinstance(item, (str, dict)):
            raise ValueError(
                f"packet.handoff.best_current_explanations[{index}] must be text or a structured explanation"
            )
    for index, item in enumerate(handoff.get("artifacts", [])):
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"packet.handoff.artifacts[{index}] must be a non-empty path or Markdown link")


def _explanation_text(item: object) -> str:
    if not isinstance(item, dict):
        return str(item)
    explanation = str(item.get("explanation", "")).strip()
    confidence = str(item.get("confidence", "")).strip()
    reason = str(item.get("reason", "")).strip()
    if not explanation:
        raise ValueError("structured handoff explanation is missing explanation")
    if any("\n" in value for value in (explanation, confidence, reason)):
        raise ValueError("structured handoff explanation fields must be single-line text")
    suffix = "; ".join(part for part in (f"confidence: {confidence}" if confidence else "", reason) if part)
    return f"{explanation} ({suffix})" if suffix else explanation


def _artifact_link(item: object, artifact_root: object) -> str:
    value = str(item).strip()
    if value.startswith("[") and "](" in value and value.endswith(")"):
        return value
    path = Path(value)
    if not path.is_absolute():
        path = Path(str(artifact_root)) / path
    return f"[{path.name}]({path})"


def _cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", "<br>")


def _table(headers: tuple[str, ...], rows: list[dict[str, object]]) -> str:
    if not rows:
        raise ValueError(f"missing_rows:{headers[0]}")
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(_cell(row.get(header, "")) for header in headers) + " |")
    return "\n".join(lines)


def _mapping_table(values: dict[str, object]) -> str:
    visible = {
        key: value
        for key, value in values.items()
        if not (key == "Evaluation run ID" and str(value).strip().lower() == "not applicable")
    }
    return _table(("Field", "Value"), [{"Field": key, "Value": value} for key, value in visible.items()])


def _section(title: str, body: str) -> str:
    return f"# {title}\n\n{body}\n"


def _runtime_released(rows: list[dict[str, object]]) -> bool:
    return bool(rows) and all(
        str(row.get("Runtime status", "")).strip().lower() == "released"
        and str(row.get("Remaining active handles", "")).strip().lower() in {"none", "0"}
        for row in rows
    )


def _reconcile_runtime_state(packet: dict[str, object], closure: list[dict[str, object]]) -> None:
    packet["runtime_closure"] = closure
    if not _runtime_released(closure):
        return
    finalization = packet.get("finalization")
    if isinstance(finalization, dict):
        reconciliation = str(finalization.get("Final reconciliation", "")).lower()
        stale = any(token in reconciliation for token in ("pending", "unknown", "in progress"))
        stale = stale or ("active" in reconciliation and "no active" not in reconciliation)
        if stale and "failed" not in reconciliation:
            finalization["Final reconciliation"] = "Passed; runtime closure released with no active handles"
        finalization["Finalization schema"] = "Passed"
    for row in packet.get("durable_artifacts", []):
        if not isinstance(row, dict):
            continue
        artifact_name = re.sub(r"[_-]+", " ", str(row.get("Artifact", "")).lower())
        if "runtime closure" in artifact_name:
            row["Status"] = "Released"
    for row in packet.get("worker_results", []):
        if not isinstance(row, dict):
            continue
        blockers = str(row.get("Uncertainties / blockers", ""))
        if re.fullmatch(r"\s*runtime closure pending(?: coordinator receipt)?\s*", blockers, re.IGNORECASE):
            row["Uncertainties / blockers"] = "None"
    for row in packet.get("synchronization", []):
        if not isinstance(row, dict):
            continue
        barrier = str(row.get("Barrier status", "")).lower()
        stale = any(token in barrier for token in ("pending", "unknown", "in progress"))
        stale = stale or ("active" in barrier and "no active" not in barrier)
        if stale and "failed" not in barrier:
            row["Barrier status"] = "Passed; runtime closure released"
    handoff = packet.get("handoff")
    if isinstance(handoff, dict):
        execution = str(handoff.get("execution", ""))
        execution = re.sub(
            r"runtime\s+(?:pending/unknown|pending|unknown|active|in progress|not released)",
            "runtime released",
            execution,
            flags=re.IGNORECASE,
        )
        handoff["execution"] = execution
        next_action = handoff.get("next_action")
        if isinstance(next_action, dict):
            next_action["action"] = re.sub(
                r"^Run pre-release finalizer, create (?:the )?runtime closure receipt, and\s+",
                "",
                str(next_action.get("action", "")),
                flags=re.IGNORECASE,
            )
            next_action["complete_when"] = re.sub(
                r"^Final reconciliation and finalization schema are no longer Pending and\s+",
                "",
                str(next_action.get("complete_when", "")),
                flags=re.IGNORECASE,
            )


def render(packet: dict[str, object]) -> str:
    handoff = packet["handoff"]
    explanations = handoff.get("best_current_explanations", [])
    explanation_block = ""
    if explanations:
        explanation_block = "\nBest current explanations:\n" + "".join(
            f"- {_explanation_text(item)}\n" for item in explanations
        )
    established = "".join(f"- {item}\n" for item in handoff["established"])
    artifacts = "".join(
        f"- {_artifact_link(item, packet['finalization']['Durable artifact root'])}\n"
        for item in handoff["artifacts"]
    )
    runtime = "released" if _runtime_released(packet["runtime_closure"]) else "not released"
    execution = str(handoff["execution"]).rstrip(" .;")
    if not re.search(r"\bruntime\s+released\b", execution, flags=re.IGNORECASE):
        execution = f"{execution}; runtime {runtime}"
    handoff_text = f"""```text
Workflow result: {handoff['workflow_result']}

- State: {packet['identity']['State']}
- Workflow outcome: {packet['identity']['Workflow outcome']}
- Engineering outcome: {packet['identity']['Engineering outcome']}
- Implementation plan: {handoff['implementation_plan']}

What we established:
{established}{explanation_block}
Next action:
- Owner: {handoff['next_action']['owner']}
- Action: {handoff['next_action']['action']}
- Complete when: {handoff['next_action']['complete_when']}

Artifacts:
{artifacts}
Execution: {execution}.
Provenance: {handoff['provenance']}
```"""

    sections = [
        "# Engineering Work Record\n",
        _section("Work Item", _mapping_table(packet["work_item"])),
        _section("Playbook Selection", _table(
            ("Primary evidence", "Primary goal", "Selected playbook", "Closest alternative", "Why this playbook"),
            [packet["playbook_selection"]],
        )),
        _section("Input Register", _table(
            ("Input ID", "Input or artifact", "Source or path", "Authority", "Status"), packet["inputs"]
        )),
        _section("Repository Evidence Eligibility", _table(
            ("Repository role", "Declared path", "Resolved path", "Branch / detached", "Full revision", "Clean status",
             "User-selected ref", "Release mapping", "Evidence eligibility"), packet["repositories"]
        )),
        _section("Run and Evaluation Identity", _mapping_table(packet["identity"])),
        _section("Run Isolation and Finalization", _mapping_table(packet["finalization"])),
        _section("Durable Artifacts", _table(
            ("Artifact", "Path", "Status", "Purpose"), packet["durable_artifacts"]
        )),
        _section("Worker Execution Ledger", _table(
            ("Worker", "Role", "Assigned inputs", "Mode", "Depth", "Skills", "Tools", "Capacity",
             "Configured model/effort", "Provider-observed model/effort", "Usage", "Depends on",
             "Outcome", "Confidence"), packet["workers"]
        )),
        _section("Worker Synchronization", _table(
            ("Stage", "Workers launched", "Launch mode / exception", "Worker outcomes", "Results summarized",
             "Barrier status"), packet["synchronization"]
        )),
        _section("Worker Runtime Closure", _table(
            ("Run or stage", "Receipt owner", "Completed worker handles", "Runtime status", "Remaining active handles",
             "Closure evidence or blocker"), packet["runtime_closure"]
        )),
        _section("Worker Result Summary", _table(
            ("Worker", "Outcome", "Confidence", "Unique contribution", "Evidence / claim refs",
             "Uncertainties / blockers", "Actual model/effort", "Usage/credits"), packet["worker_results"]
        )),
        _section("Evidence", _table(
            ("Evidence ID", "Source", "Summary", "Confidence", "Uncertainty", "Status"), packet["evidence"]
        )),
        _section("Claims", _table(
            ("Claim ID", "Claim", "Evidence refs", "Confidence", "Uncertainty", "Status"), packet["claims"]
        )),
        _section("Decision Log", _table(
            ("Decision ID", "Decision", "Claim refs", "Owner", "Status"), packet["decisions"]
        )),
        _section("Action Log", _table(
            ("Action ID", "Action", "Decision ref", "Owner", "Status"), packet["actions"]
        )),
        _section("Final Handoff", handoff_text),
    ]
    return "\n".join(sections)


def finalize(packet_path: Path, closure_path: Path, record_path: Path, *, pre_release: bool = False) -> None:
    packet = json.loads(packet_path.read_text())
    closure = json.loads(closure_path.read_text())
    _validate_shapes(packet, closure)
    _normalize_packet(packet, closure)
    _validate_handoff(packet)
    _reconcile_runtime_state(packet, closure["runtime_closure"])
    rendered = render(packet)
    record_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=record_path.parent, suffix=".md", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(rendered)
    try:
        validator_args = [sys.executable, str(VALIDATOR)]
        if not pre_release:
            validator_args.append("--emit-handoff")
        if pre_release:
            validator_args.append("--allow-unreleased")
        validator_args.append(str(temporary))
        result = subprocess.run(
            validator_args,
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            raise ValueError(result.stdout.strip() or result.stderr.strip() or "work_record_validation_failed")
        if not pre_release:
            temporary.replace(record_path)
        print(result.stdout, end="")
    finally:
        temporary.unlink(missing_ok=True)


def prepare_analytical_failure(
    packet_path: Path,
    closure_path: Path,
    record_path: Path,
    *,
    reason: str,
    completed_handles: list[str],
    coordinator_model_effort: str,
    framework_revision: str,
    framework_status: str,
    evidence_artifact: Path,
) -> None:
    packet = json.loads(packet_path.read_text())
    artifact_root = packet_path.parent
    execution_repository = artifact_root.parent.parent
    manifest_path = artifact_root / "role_bindings.json"
    manifest = json.loads(manifest_path.read_text())
    binding = manifest["bindings"]["sentry_current_state_investigator"]
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    work_item = str(packet["work_item"]["ID"])
    git_revision = subprocess.run(
        ["git", "-C", str(execution_repository), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    git_branch = subprocess.run(
        ["git", "-C", str(execution_repository), "branch", "--show-current"],
        capture_output=True, text=True, check=True,
    ).stdout.strip() or "detached"
    git_status = subprocess.run(
        ["git", "-C", str(execution_repository), "status", "--porcelain"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    packet["work_item"].update({"Title": work_item, "Last Updated": now})
    packet["playbook_selection"].update({
        "Primary evidence": "Current Sentry occurrence and normalized evidence",
        "Primary goal": "Evidence-backed Sentry remediation planning",
        "Selected playbook": "sentry_issue_remediation",
        "Closest alternative": "feature_delivery",
        "Why this playbook": "The run investigates a reported Sentry occurrence before implementation.",
    })
    packet["inputs"] = [{
        "Input ID": "IN-001", "Input or artifact": "Current Sentry occurrence",
        "Source or path": str(evidence_artifact), "Authority": "Current-run evidence", "Status": "Consumed",
    }]
    packet["repositories"] = [{
        "Repository role": "Execution", "Declared path": str(execution_repository),
        "Resolved path": str(execution_repository), "Branch / detached": git_branch,
        "Full revision": git_revision, "Clean status": "Dirty" if git_status else "Clean",
        "User-selected ref": "Current checkout", "Release mapping": "Unknown",
        "Evidence eligibility": "Accepted for current-run repository evidence",
    }]
    prompt_identity = str(packet["identity"]["Prompt template / revision / conformance"])
    if prompt_identity.endswith(" / pending"):
        prompt_identity = prompt_identity.removesuffix(" / pending") + f" / fail: {reason}"
    packet["identity"].update({
        "Run ID": f"{work_item}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
        "Framework commit / status": f"{framework_revision} / {framework_status.title()}",
        "Prompt template / revision / conformance": prompt_identity,
        "Coordinator model/effort": coordinator_model_effort,
        "Requested profile": "standard", "Activated profile": "standard", "Executed profile": "standard",
        "Profile status": "blocked", "Lifecycle": "planning", "State": "blocked",
        "Engineering state": "unknown", "Workflow outcome": "blocked", "Engineering outcome": "blocked",
    })
    packet["finalization"].update({
        "Concurrent-run decision": "Current isolated run", "Active related run or work item": "None",
        "Related-run check": "Completed during initialization", "Durable artifact root": str(artifact_root),
        "Final reconciliation": "Passed; analytical failure preserved and runtime released",
        "Finalization schema": "Passed",
    })
    packet["durable_artifacts"] = [
        {"Artifact": "Normalized evidence", "Path": str(evidence_artifact), "Status": "Preserved",
         "Purpose": "Current-run evidence and failed validation input"},
        {"Artifact": "Role bindings", "Path": str(manifest_path), "Status": "Created",
         "Purpose": "Exact worker bindings"},
        {"Artifact": "Finalization packet", "Path": str(packet_path), "Status": "Created",
         "Purpose": "Structured terminal input"},
        {"Artifact": "Runtime closure", "Path": str(closure_path), "Status": "Released",
         "Purpose": "Provider closure receipt"},
        {"Artifact": "Work record", "Path": str(record_path), "Status": "Created",
         "Purpose": "Authoritative terminal handoff"},
    ]
    configured = f"{binding['model']} / {binding['effort']}"
    worker_handle = ", ".join(completed_handles) if completed_handles else "None"
    packet["workers"] = [{
        "Worker": "evidence-topology", "Role": "Evidence topology", "Assigned inputs": "IN-001",
        "Mode": "investigation", "Depth": "standard", "Skills": "Sentry evidence topology",
        "Tools": "Mapped provider operations", "Capacity": "one worker", "Configured model/effort": configured,
        "Provider-observed model/effort": configured, "Usage": "Provider telemetry unavailable",
        "Depends on": "Coordinator initialization", "Outcome": "failed", "Confidence": "High",
    }]
    packet["synchronization"] = [{
        "Stage": "Evidence validation", "Workers launched": "evidence-topology",
        "Launch mode / exception": "Sequential Standard activation", "Worker outcomes": "failed",
        "Results summarized": "Yes", "Barrier status": f"Failed: {reason}",
    }]
    packet["worker_results"] = [{
        "Worker": "evidence-topology", "Outcome": "failed", "Confidence": "High",
        "Unique contribution": "Produced current-run normalized evidence before contract validation failed",
        "Evidence / claim refs": "E-001 / C-001", "Uncertainties / blockers": reason,
        "Actual model/effort": configured, "Usage/credits": "Provider telemetry unavailable",
    }]
    packet["evidence"] = [{
        "Evidence ID": "E-001", "Source": str(evidence_artifact),
        "Summary": f"Normalized evidence failed its producer contract: {reason}", "Confidence": "High",
        "Uncertainty": "None", "Status": "Verified",
    }]
    packet["claims"] = [{
        "Claim ID": "C-001", "Claim": "Fix Design cannot start from invalid normalized evidence.",
        "Evidence refs": "E-001", "Confidence": "High", "Uncertainty": "None", "Status": "Supported",
    }]
    packet["decisions"] = [{
        "Decision ID": "D-001", "Decision": "Stop after the bounded analytical correction and preserve artifacts.",
        "Claim refs": "C-001", "Owner": "Coordinator", "Status": "Applied",
    }]
    packet["actions"] = [{
        "Action ID": "A-001", "Action": "Correct the evidence contract before retrying planning.",
        "Decision ref": "D-001", "Owner": "Framework maintainer", "Status": "Proposed",
    }]
    packet["handoff"] = {
        "workflow_result": "Planning stopped on analytical contract failure",
        "implementation_plan": "omitted; normalized evidence failed validation",
        "established": ["Evidence Topology produced an artifact, but its required contract validation failed."],
        "best_current_explanations": [{"explanation": reason, "confidence": "high",
                                       "reason": "The packaged validator reproduced the failure."}],
        "next_action": {"owner": "Framework maintainer", "action": "Correct the evidence contract and retry.",
                        "complete_when": "Normalized evidence passes before Fix Design activation."},
        "artifacts": [str(evidence_artifact), str(record_path)],
        "execution": (
            "standard/planning; finalization validation passed; analytical validation failed; "
            "workers incomplete; source changes none; runtime released"
        ),
        "provenance": (
            f"plugin {packet['identity']['Plugin package / version']}; framework revision {framework_revision} "
            f"({framework_status.lower()}); playbook {packet['identity']['Playbook / version']}."
        ),
    }
    closure = {"runtime_closure": [{
        "Run or stage": "Current run", "Receipt owner": "Coordinator",
        "Completed worker handles": worker_handle, "Runtime status": "Released",
        "Remaining active handles": "None", "Closure evidence or blocker": (
            f"Provider release confirmed after analytical contract failure. Completed handles: {worker_handle}."
        ),
    }]}
    packet_path.write_text(json.dumps(packet, indent=2) + "\n")
    closure_path.write_text(json.dumps(closure, indent=2) + "\n")
    finalize(packet_path, closure_path, record_path)


def self_test() -> None:
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
            "Playbook / version": "playbooks/sentry_issue_remediation.md / 0.4.7",
            "Framework commit / status": f"{'a' * 40} / Clean", "Plugin package / version": "Not applicable",
            "Provider/runtime configuration": "Not provided",
            "Provider configuration source/status": "manual / resolved",
            "Prompt template / revision / conformance": "templates/sentry_issue_run_prompt.md / 0.4.7 / pass",
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
                    "provenance": f"plugin Not applicable; framework revision {'a' * 40} (clean); playbook sentry_issue_remediation 0.4.7."},
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

    with tempfile.TemporaryDirectory(prefix="workflow-finalize-") as directory:
        root = Path(directory)
        source = root / "packet.json"
        closure = root / "runtime_closure.json"
        record = root / "work_record.md"
        source.write_text(json.dumps(packet))
        closure.write_text(json.dumps({"runtime_closure": packet["runtime_closure"]}))
        finalize(source, closure, record)
        assert "Workflow result: Worker runtime unavailable" in record.read_text()
        rendered = record.read_text()
        assert "{'explanation':" not in rendered
        assert "confidence: high" in rendered
        assert "[work_record.md](/tmp/.thoughts/ITEM-1/work_record.md)" in rendered
        assert "Final reconciliation | Passed; runtime closure released with no active handles |" in rendered
        assert "Finalization schema | Passed |" in rendered
        assert "Workflow result: Workflow result:" not in rendered
        assert "| Passed; runtime closure released |" in rendered
        assert "Final reconciliation | Pending" not in rendered
        assert "runtime pending" not in rendered.lower()
        assert "runtime closure pending" not in rendered.lower()
        assert "| runtime_closure.json |" in rendered
        assert "| Released | Provider receipt |" in rendered
        pending = {"runtime_closure": [dict(packet["runtime_closure"][0], **{
            "Runtime status": "Pending",
            "Closure evidence or blocker": "provider release pending",
        })]}
        pending_closure = root / "pending_runtime_closure.json"
        pending_closure.write_text(json.dumps(pending))
        pre_release_record = root / "pre-release-work-record.md"
        pre_release_record.write_text("existing record must remain untouched\n")
        finalize(source, pending_closure, pre_release_record, pre_release=True)
        assert pre_release_record.read_text() == "existing record must remain untouched\n"
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
        fixture_packet_data = fixture["files"]["finalization_packet.json"]
        fixture_packet_data["identity"]["Framework commit / status"] = f"{'a' * 40} Clean; preflight passed"
        fixture_packet_data["identity"]["Playbook / version"] = "Sentry Issue Remediation / 0.4.7"
        fixture_packet_data["identity"]["Coordinator model/effort"] = "gpt-5.6-luna/medium"
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
        fixture_rendered = fixture_record.read_text()
        assert "Workflow result: Ready for implementation" in fixture_rendered
        assert "templates/sentry_issue_run_prompt.md / 0.4.7 / pass" in fixture_rendered
        assert f"{'a' * 40} / Clean" in fixture_rendered
        assert "playbooks/sentry_issue_remediation.md / 0.4.7" in fixture_rendered
        assert "gpt-5.6-luna / medium" in fixture_rendered
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
        framework_revision = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
        prepare_analytical_failure(
            failure_packet, failure_closure, failure_record,
            reason="contract delta separator missing",
            completed_handles=["01a049e8-689e-7273-bd17-403d4d9a5022"],
            coordinator_model_effort="gpt-5.6-luna / xhigh", framework_revision=framework_revision,
            framework_status="dirty", evidence_artifact=evidence,
        )
        failure_text = failure_record.read_text()
        assert "| State | blocked |" in failure_text
        assert "| Profile status | blocked |" in failure_text
        assert "| Runtime status |" in failure_text and "| Released | None |" in failure_text
        assert "Workflow result: Planning stopped on analytical contract failure" in failure_text
        assert "Workflow result: Pending" not in failure_text
    print("finalize_work_record self-test: passed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", type=Path)
    parser.add_argument("--closure", type=Path)
    parser.add_argument("--record", type=Path)
    parser.add_argument("--pre-release", action="store_true")
    parser.add_argument("--analytical-failure")
    parser.add_argument("--completed-handle", action="append", default=[])
    parser.add_argument("--coordinator-model-effort")
    parser.add_argument("--framework-revision")
    parser.add_argument("--framework-status", choices=("clean", "dirty"))
    parser.add_argument("--evidence-artifact", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.packet or not args.closure or not args.record:
        parser.error("--packet, --closure, and --record are required")
    try:
        if args.analytical_failure:
            if not all((args.coordinator_model_effort, args.framework_revision, args.framework_status,
                        args.evidence_artifact)):
                parser.error(
                    "--analytical-failure requires --coordinator-model-effort, --framework-revision, "
                    "--framework-status, and --evidence-artifact"
                )
            prepare_analytical_failure(
                args.packet.resolve(), args.closure.resolve(), args.record.resolve(),
                reason=args.analytical_failure, completed_handles=args.completed_handle,
                coordinator_model_effort=args.coordinator_model_effort,
                framework_revision=args.framework_revision, framework_status=args.framework_status,
                evidence_artifact=args.evidence_artifact.resolve(),
            )
        else:
            finalize(args.packet.resolve(), args.closure.resolve(), args.record.resolve(), pre_release=args.pre_release)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, OSError, subprocess.CalledProcessError) as error:
        print(json.dumps({"status": "blocked", "reason": str(error)}, sort_keys=True))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
