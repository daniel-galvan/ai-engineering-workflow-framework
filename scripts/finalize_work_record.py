#!/usr/bin/env python3
"""Validate a structured packet and atomically render a terminal work record."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "validate_library.py"
PACKET_TEMPLATE = ROOT / "templates" / "finalization_packet.json"
CLOSURE_TEMPLATE = ROOT / "templates" / "runtime_closure.json"
V22_FIXTURE = ROOT / "tests" / "fixtures" / "v22_sentry_planning.json"


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


def render(packet: dict[str, object]) -> str:
    handoff = packet["handoff"]
    explanations = handoff.get("best_current_explanations", [])
    explanation_block = ""
    if explanations:
        explanation_block = "\nBest current explanations:\n" + "".join(f"- {item}\n" for item in explanations)
    established = "".join(f"- {item}\n" for item in handoff["established"])
    artifacts = "".join(f"- {item}\n" for item in handoff["artifacts"])
    runtime = "released" if _runtime_released(packet["runtime_closure"]) else "not released"
    execution = str(handoff["execution"])
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
            ("Run or stage", "Completed worker handles", "Runtime status", "Remaining active handles",
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
            "Provider / model configuration": "Manual / Worker Execution Ledger", "Requested profile": "standard",
            "Activated profile": "None", "Executed profile": "None", "Profile status": "blocked",
            "Lifecycle": "planning", "State": "blocked", "Engineering state": "unknown",
            "Workflow outcome": "blocked", "Engineering outcome": "blocked",
        },
        "finalization": {"Concurrent-run decision": "Not applicable", "Active related run or work item": "None",
                         "Related-run check": "Current task", "Durable artifact root": "/tmp/.thoughts/ITEM-1",
                         "Final reconciliation": "Pending; runtime closure not yet reconciled", "Finalization schema": "Passed"},
        "durable_artifacts": [{"Artifact": "Work record", "Path": "work_record.md", "Status": "Created",
                               "Purpose": "Terminal handoff"}],
        "workers": [{"Worker": "Coordinator", "Role": "Orchestrator", "Assigned inputs": "IN-001",
                     "Mode": "investigation", "Depth": "standard", "Skills": "workflow", "Tools": "local",
                     "Capacity": "current task", "Configured model/effort": "active session",
                     "Provider-observed model/effort": "Unknown", "Usage": "Unknown", "Depends on": "None",
                     "Outcome": "complete", "Confidence": "High"}],
        "synchronization": [{"Stage": "Initialization", "Workers launched": "None",
                             "Launch mode / exception": "worker_runtime_unavailable", "Worker outcomes": "Not applicable",
                             "Results summarized": "Yes", "Barrier status": "Passed; runtime closure pending/unknown"}],
        "runtime_closure": [{"Run or stage": "Current run", "Completed worker handles": "coordinator",
                             "Runtime status": "Released", "Remaining active handles": "None",
                             "Closure evidence or blocker": "provider release confirmation for coordinator"}],
        "worker_results": [{"Worker": "Coordinator", "Outcome": "blocked", "Confidence": "High",
                            "Unique contribution": "Stopped safely", "Evidence / claim refs": "E-001 / C-001",
                            "Uncertainties / blockers": "In-task runtime absent", "Actual model/effort": "Unknown",
                            "Usage/credits": "Unknown"}],
        "evidence": [{"Evidence ID": "E-001", "Source": "runtime check", "Summary": "Runtime absent",
                      "Confidence": "High", "Uncertainty": "None", "Status": "Verified"}],
        "claims": [{"Claim ID": "C-001", "Claim": "Worker graph cannot start", "Evidence refs": "E-001",
                    "Confidence": "High", "Uncertainty": "None", "Status": "Supported"}],
        "decisions": [{"Decision ID": "D-001", "Decision": "Stop without task forks", "Claim refs": "C-001",
                       "Owner": "Coordinator", "Status": "Applied"}],
        "actions": [{"Action ID": "A-001", "Action": "Retry with in-task runtime", "Decision ref": "D-001",
                     "Owner": "User", "Status": "Proposed"}],
        "handoff": {"workflow_result": "Worker runtime unavailable", "implementation_plan": "omitted; run blocked",
                    "established": ["No user-owned tasks were created."], "best_current_explanations": [], "next_action": {
                        "owner": "User", "action": "Retry when in-task workers are available.",
                        "complete_when": "The worker graph starts in the current task."},
                    "artifacts": ["work_record.md"],
                    "execution": "standard/planning; validation passed; workers not started; source changes none; runtime pending/unknown",
                    "provenance": f"plugin Not applicable; framework revision {'a' * 40} (clean); playbook sentry_issue_remediation 0.4.7."},
    }
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
        assert "Final reconciliation | Passed; runtime closure released with no active handles |" in rendered
        assert "| Passed; runtime closure released |" in rendered
        assert "Final reconciliation | Pending" not in rendered
        assert "runtime pending" not in rendered.lower()
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
        assert "runtime closure released" in fixture_rendered
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
    print("finalize_work_record self-test: passed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", type=Path)
    parser.add_argument("--closure", type=Path)
    parser.add_argument("--record", type=Path)
    parser.add_argument("--pre-release", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.packet or not args.closure or not args.record:
        parser.error("--packet, --closure, and --record are required")
    try:
        finalize(args.packet.resolve(), args.closure.resolve(), args.record.resolve(), pre_release=args.pre_release)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, OSError) as error:
        print(json.dumps({"status": "blocked", "reason": str(error)}, sort_keys=True))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
