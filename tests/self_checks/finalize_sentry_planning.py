"""Preserved finalize_sentry_planning synthetic regression scenarios."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from scripts.finalize_sentry_planning import (
    INTERFACE_FIELDS,
    ROOT,
    V34_FIXTURE,
    V36_FIXTURE,
    V37_V38_FIXTURE,
    VALIDATOR,
    WORKER_BINDINGS,
    _completed_workers,
    _git,
    _released_closure,
    finalize_standard_sentry,
    render_clarification_brief,
)
from scripts.work_record_format import expand_work_record
from scripts.work_record_format import _cell


def self_test() -> None:
    from datetime import timedelta
    from scripts.validate_worker_runtime import activation_message, dispatch_message
    from scripts.worker_runtime_evidence import read_runtime_events, export_worker_trace

    def runtime_fixture(root: Path, workers: dict[str, str]) -> list[str]:
        bindings = json.loads((root / "role_bindings.json").read_text())
        started = bindings["runtime_evidence"]["run_started_at"]
        base = datetime.fromisoformat(started.replace("Z", "+00:00"))
        parent_id = "00000000-0000-0000-0000-000000000001"
        def event(second, kind, **payload):
            return {"timestamp": (base + timedelta(seconds=second)).isoformat(), "type": kind, "payload": payload}
        rows = [event(0, "session_meta", id=parent_id)]
        observations, children = [], []
        bundle = json.loads(Path(bindings["activation_packet_bundle"]["path"]).read_text())
        for index, (worker, handle) in enumerate(workers.items(), 2):
            role = WORKER_BINDINGS[worker][0]
            child_id = f"00000000-0000-0000-0000-{index:012d}"
            packet = bundle["packets"][role]
            contract = root / f"activation_{worker}.txt"
            notice = dispatch_message(packet, activation_message(packet, {"objective": "Synthetic worker receipt"}), contract)
            rows.extend([event(index, "response_item", type="function_call", namespace="collaboration",
                name="spawn_agent", arguments=json.dumps({"task_name": handle.rsplit("/", 1)[-1], "message": notice,
                    "fork_turns": "none", "model": packet["model"], "reasoning_effort": packet["effort"]})),
                event(index, "event_msg", item={"type": "SubAgentActivity", "kind": "started",
                                               "agent_path": handle, "agent_thread_id": child_id})])
            child = root / f"{worker}.jsonl"
            child.write_text("\n".join(json.dumps(row) for row in [event(index, "session_meta", id=child_id),
                event(index + 1, "response_item", type="custom_tool_call", call_id="contract", name="exec",
                      input='await tools.exec_command(' + json.dumps({"cmd": "cat " + str(contract)}) + ')'),
                event(index + 2, "response_item", type="custom_tool_call_output", call_id="contract", output=contract.read_text())]) + "\n")
            observations.append({"Provider handle": handle, "Thread ID": child_id, "Provider status": "completed",
                "Last dispatch at": event(index, "unused")["timestamp"], "Observed at": event(20, "unused")["timestamp"],
                "Status source": "read_thread", "Latest turn started at": event(index, "unused")["timestamp"],
                "Latest turn completed at": event(10, "unused")["timestamp"], "Latest turn status": "completed", "Thread status": "idle"})
            children.append((worker, role, child))
        rows.extend(event(10, "event_msg", item={"type": "SubAgentActivity", "kind": "completed", "agent_path": handle})
                    for handle in workers.values())
        parent = root / "parent.jsonl"
        parent.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
        ledger = read_runtime_events(parent, parent_id, started)
        Path(bindings["runtime_evidence"]["ledger"]).write_text(json.dumps(ledger))
        run_id = json.loads((root / "finalization_packet.json").read_text())["identity"]["Run ID"]
        specs = []
        for (worker, role, child), observation in zip(children, observations):
            trace = export_worker_trace(ledger, child, role, observation, run_id=run_id, artifact_root=root)
            assert trace["audit"]["status"] == "passed", trace["audit"]
            path = root / f"{worker}.trace.json"
            path.write_text(json.dumps(trace))
            specs.append(worker + "=" + str(path))
        (root / "runtime_closure.json").write_text(json.dumps({"runtime_closure": [{
            "Run or stage": "planning", "Receipt owner": "Coordinator", "Runtime status": "Terminal",
            "Completed worker handles": "; ".join(workers.values()), "Remaining active handles": "0",
            "Closure evidence or blocker": "provider status snapshot " + event(20, "unused")["timestamp"] + ": "
                + "; ".join(handle + "=completed" for handle in workers.values())}], "terminal_observations": observations}))
        return specs

    fixture = json.loads(V34_FIXTURE.read_text())
    v36_fixture = json.loads(V36_FIXTURE.read_text())
    v37_v38_fixture = json.loads(V37_V38_FIXTURE.read_text())
    with tempfile.TemporaryDirectory(prefix="workflow-sentry-finalize-") as directory:
        receipt = Path(directory) / "closure.json"
        terminal = {"runtime_closure": [{
            "Completed worker handles": "/root/evidence_topology", "Runtime status": "Terminal",
            "Remaining active handles": "0",
            "Closure evidence or blocker": (
                "provider status snapshot 2026-10-07T22:42:58Z: /root/evidence_topology=completed"
            ),
        }]}
        receipt.write_text(json.dumps(terminal))
        assert _released_closure(receipt, ["/root/evidence_topology"]) == terminal
        terminal["runtime_closure"][0]["Runtime status"] = "Blocked"
        receipt.write_text(json.dumps(terminal))
        try:
            _released_closure(receipt, ["/root/evidence_topology"])
        except ValueError:
            pass
        else:
            raise AssertionError("invalid supplied receipt was replaced with fabricated release proof")
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
        input_source = execution_repository / "inputs.json"
        input_source.write_text(json.dumps({
            "schema_version": 1,
            "precedence_rule": (
                "Current explicit user decisions and constraints, plus explicitly supplied current-run context and "
                "artifacts, override historical conclusions. Live runtime evidence is additive unless the user "
                "explicitly selects live-only analysis."
            ),
            "inputs": [{
                "Input ID": "USER-001",
                "Input or artifact": "Fixture current-run context",
                "Source or path": "Current user request",
                "Authority": "Authoritative current-run context",
                "Classification": "observed report or requested outcome",
                "Expected use": "Evidence worker and Fix Design",
                "Status": "Registered",
            }],
        }))
        prepared = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "prepare_run.py"),
             "--execution-repository", str(execution_repository), "--work-item", "ITEM-34",
             "--playbook", "sentry_issue_remediation", "--input-manifest", str(input_source)],
            capture_output=True, text=True, check=True,
        )
        artifact_root = Path(json.loads(prepared.stdout)["artifact_root"])
        (artifact_root / "normalized_evidence.md").write_text(fixture["normalized_evidence"])
        fixture_fix = json.loads(json.dumps(fixture["fix_design_result"]))
        fixture_fix["worker_handle"] = "/root/fix_design"
        fixture_fix["inputs_consumed"] = [*fixture_fix["inputs_consumed"], "USER-001"]
        (artifact_root / "fix_design_result.json").write_text(
            json.dumps(fixture_fix, indent=2) + "\n"
        )
        framework_revision = _git(ROOT, "rev-parse", "HEAD")
        framework_status = "dirty" if _git(ROOT, "status", "--porcelain") else "clean"
        completed_specs = [
            f"{row['worker']}={row['handle']}" for row in v36_fixture["conditional_workers"]
        ]
        alias_workers = _completed_workers(
            "/root/evidence_topology",
            fixture_fix["worker_handle"],
            [
                "sentry_current_state_investigator=/root/evidence_topology",
                f"sentry_solution_architect={fixture_fix['worker_handle']}",
            ],
        )
        assert set(alias_workers) == {"evidence-topology", "fix-design"}
        trace_specs = runtime_fixture(artifact_root, _completed_workers(
            "/root/evidence_topology", fixture_fix["worker_handle"], completed_specs))
        receiver = Path(directory) / "receiver"
        _git(execution_repository, "clone", "--quiet", str(execution_repository), str(receiver))
        finalize_standard_sentry(
            artifact_root,
            evidence_handle="/root/evidence_topology",
            coordinator_model_effort="Not exposed / Not exposed",
            framework_revision=framework_revision,
            framework_status=framework_status,
            repository_specs=[f"Execution={execution_repository}", f"Receiver={receiver}"],
            completed_worker_specs=completed_specs,
            worker_trace_specs=trace_specs,
        )
        plan_text = (artifact_root / "implementation_plan.md").read_text()
        recorded = json.loads((artifact_root / "finalization_packet.json").read_text())
        assert len(recorded["repositories"]) == 2
        assert recorded["repositories"][1]["Full revision"] == _git(receiver, "rev-parse", "HEAD")
        cli = subprocess.run([sys.executable, str(ROOT / "scripts/finalize_sentry_planning.py"),
            "--artifact-root", str(artifact_root), "--evidence-handle", "/root/evidence_topology",
            "--coordinator-model-effort", "Not exposed / Not exposed", "--framework-revision", framework_revision,
            "--framework-status", framework_status, "--repository", f"Execution={execution_repository}",
            *[arg for spec in completed_specs for arg in ("--completed-worker", spec)],
            *[arg for spec in trace_specs for arg in ("--worker-trace", spec)]], capture_output=True, text=True)
        assert cli.returncode == 0, cli.stdout + cli.stderr
        record_text = (artifact_root / "work_record.md").read_text()
        contract = fixture["fix_design_result"]["interface_contract"]
        assert "# Interface Contract\n\n| Surface | Request shape" in plan_text
        assert "## Interface Contract" not in plan_text
        for _, field in INTERFACE_FIELDS:
            assert _cell(contract[field]) in plan_text
        assert "| documenter |" not in record_text.lower()
        assert "| State | ready_for_implementation |" in record_text
        assert "Not exposed / Not exposed" in expand_work_record(record_text, artifact_root)
        assert "deterministic rendering passed" in record_text
        assert "| USER-001 |" in record_text
        assert "Run input manifest" in expand_work_record(record_text, artifact_root)
        assert "active parent session; no dedicated Coordinator worker spawned" in expand_work_record(record_text, artifact_root)
        conditional = v36_fixture["conditional_workers"][0]
        assert f"| {conditional['worker']} |" in record_text
        assert conditional["handle"] in (artifact_root / "runtime_closure.json").read_text()
        output_names = (
            "implementation_plan.md",
            "finalization_packet.json",
            "runtime_closure.json",
            "work_record.md",
            re.search(r"<!-- workflow-state: (finalization_snapshot\.[0-9a-f]{64}\.json) -->", record_text).group(1),
        )
        output_before_failure = {
            name: (artifact_root / name).read_bytes() for name in output_names
        }
        parent_path = artifact_root / "parent.jsonl"
        ledger_path = artifact_root / "runtime_dispatches.json"
        parent_before, ledger_before = parent_path.read_bytes(), ledger_path.read_bytes()
        ledger = json.loads(ledger_before)
        stamp = datetime.fromisoformat(ledger["run_started_at"].replace("Z", "+00:00"))
        def dispatch_event(second, **payload):
            return {"timestamp": (stamp + timedelta(seconds=second)).isoformat(),
                    "type": "response_item", "payload": payload}
        with parent_path.open("a") as stream:
            for row in (dispatch_event(21, type="function_call", namespace="collaboration", name="followup_task",
                        call_id="failed-correction", arguments=json.dumps({"target": "/root/evidence_topology"})),
                        dispatch_event(22, type="function_call_output", call_id="failed-correction",
                        output=json.dumps({"error": "correction rejected"}))):
                stream.write(json.dumps(row) + "\n")
        ledger_path.write_text(json.dumps(read_runtime_events(parent_path, ledger["parent_thread_id"], ledger["run_started_at"])))
        try:
            finalize_standard_sentry(artifact_root, evidence_handle="/root/evidence_topology",
                coordinator_model_effort="Not exposed / Not exposed", framework_revision=framework_revision,
                framework_status=framework_status, repository_specs=[f"Execution={execution_repository}"],
                completed_worker_specs=completed_specs, worker_trace_specs=trace_specs)
        except ValueError as error:
            assert "latest_worker_dispatch_failed" in str(error), error
        else:
            raise AssertionError("Sentry published an old trace after a failed required correction")
        assert all((artifact_root / name).read_bytes() == content for name, content in output_before_failure.items())
        parent_path.write_bytes(parent_before)
        ledger_path.write_bytes(ledger_before)
        stale_record = record_text.replace(
            "| State | ready_for_implementation |", "| State | in_progress |", 1
        )
        (artifact_root / "work_record.md").write_text(stale_record)
        terminal_validation = subprocess.run(
            [sys.executable, str(VALIDATOR), "--sentry-artifacts", str(artifact_root)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert terminal_validation.returncode != 0
        (artifact_root / "work_record.md").write_bytes(output_before_failure["work_record.md"])
        valid_fix_text = (artifact_root / "fix_design_result.json").read_text()
        invalid_fix = json.loads(json.dumps(fixture_fix))
        invalid_fix["confidence"] = v36_fixture["expected_confidence"]
        invalid_fix["interface_contract"]["response_shape"] = v36_fixture[
            "invalid_unqualified_response_shape"
        ]
        (artifact_root / "fix_design_result.json").write_text(json.dumps(invalid_fix, indent=2) + "\n")
        try:
            finalize_standard_sentry(
                artifact_root,
                evidence_handle="/root/evidence_topology",
                coordinator_model_effort="gpt-5.6-luna / high",
                framework_revision=framework_revision,
                framework_status=framework_status,
                repository_specs=[f"Execution={execution_repository}"],
                completed_worker_specs=completed_specs,
                worker_trace_specs=trace_specs,
            )
        except ValueError as error:
            assert v36_fixture["expected_identity_error"] in str(error)
        else:
            raise AssertionError("invalid Fix Design must fail atomic finalization")
        assert all(
            (artifact_root / name).read_bytes() == content
            for name, content in output_before_failure.items()
        )
        (artifact_root / "fix_design_result.json").write_text(valid_fix_text)

        awaiting_prepared = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "prepare_run.py"),
             "--execution-repository", str(execution_repository), "--work-item", "ITEM-38",
             "--playbook", "sentry_issue_remediation", "--input-manifest", str(input_source)],
            capture_output=True, text=True, check=True,
        )
        awaiting_root = Path(json.loads(awaiting_prepared.stdout)["artifact_root"])
        (awaiting_root / "normalized_evidence.md").write_text(v37_v38_fixture["normalized_evidence"])
        awaiting_fix = json.loads(json.dumps(v37_v38_fixture["valid_awaiting_fix_design_result"]))
        awaiting_fix["inputs_consumed"] = [*awaiting_fix["inputs_consumed"], "USER-001"]
        original_input = awaiting_fix["inputs_consumed"][0]
        awaiting_fix["inputs_consumed"][0] = {"input_id": "UPSTREAM-001", "disposition": original_input}
        (awaiting_root / "fix_design_result.json").write_text(
            json.dumps(awaiting_fix, indent=2) + "\n"
        )
        (awaiting_root / "implementation_plan.md").write_text("stale plan must be removed\n")
        awaiting_traces = runtime_fixture(awaiting_root, _completed_workers(
            "01a05979-1001-7c41-8ad5-d5dfc636c252", awaiting_fix["worker_handle"], []))
        finalize_standard_sentry(
            awaiting_root,
            evidence_handle="01a05979-1001-7c41-8ad5-d5dfc636c252",
            coordinator_model_effort="gpt-5.6-luna / xhigh",
            framework_revision=framework_revision,
            framework_status=framework_status,
            repository_specs=[f"Execution={execution_repository}"],
            worker_trace_specs=awaiting_traces,
        )
        awaiting_record = (awaiting_root / "work_record.md").read_text()
        awaiting_brief = (awaiting_root / "clarification_brief.md").read_text()
        assert not (awaiting_root / "implementation_plan.md").exists()
        assert "# Clarification Brief" in awaiting_brief
        assert "## Smallest next action" in awaiting_brief
        awaiting_packet = json.loads((awaiting_root / "finalization_packet.json").read_text())
        normalized_fix = json.loads((awaiting_root / "fix_design_result.json").read_text())
        assert isinstance(normalized_fix["inputs_consumed"][0], str)
        assert original_input in normalized_fix["inputs_consumed"][0]
        accepted_fix = (awaiting_root / "fix_design_result.json").read_bytes()
        invalid_context = dict(normalized_fix, context_conformance="context-unverified")
        (awaiting_root / "fix_design_result.json").write_text(json.dumps(invalid_context))
        before = {path.name: path.read_bytes() for path in awaiting_root.iterdir() if path.is_file()}
        try:
            finalize_standard_sentry(awaiting_root,
                evidence_handle="01a05979-1001-7c41-8ad5-d5dfc636c252",
                coordinator_model_effort="Not exposed / Not exposed", framework_revision=framework_revision,
                framework_status=framework_status, repository_specs=[f"Execution={execution_repository}"],
                worker_trace_specs=awaiting_traces)
        except ValueError as error:
            assert "context_conformance must pass" in str(error), str(error)
        else:
            raise AssertionError("finalization accepted an invalid context field")
        assert {path.name: path.read_bytes() for path in awaiting_root.iterdir() if path.is_file()} == before
        (awaiting_root / "fix_design_result.json").write_bytes(accepted_fix)
        assert len(awaiting_packet["handoff"]["best_current_explanations"]) == 1
        assert "| Next action | Not provided |" not in awaiting_record
        assert json.loads((awaiting_root / "handoff_delivery.json").read_text())["status"] == "pending"
        response = subprocess.run([sys.executable, str(ROOT / "scripts/finalize_work_record.py"),
            "--packet", str(awaiting_root / "finalization_packet.json"),
            "--publish-response", str(awaiting_root / "handoff_response.md")], capture_output=True, text=True)
        assert response.returncode == 0, response.stdout + response.stderr
        assert response.stdout == (awaiting_root / "handoff_response.md").read_text()
        assert json.loads((awaiting_root / "handoff_delivery.json").read_text())["status"] == "verified"
        without_audits = dict(awaiting_packet, runtime_audits=[])
        (awaiting_root / "finalization_packet.json").write_text(json.dumps(without_audits))
        rejected = subprocess.run([sys.executable, str(ROOT / "scripts/validate_library.py"),
            "--sentry-artifacts", str(awaiting_root)], capture_output=True, text=True)
        assert rejected.returncode != 0 and "worker_runtime_audits_incomplete" in rejected.stdout
        (awaiting_root / "finalization_packet.json").write_text(json.dumps(awaiting_packet))
        correlated = render_clarification_brief(awaiting_fix, {"inputs": [{"Input ID": "IN-2",
            "Occurrence correlation": [{"UTC attempt": "2026-10-14T01:02:03Z", "referent_id": "123"}]}]})
        assert "IN-2: UTC attempt=2026-10-14T01:02:03Z; referent_id=123" in correlated
        assert "do not assume it is the same occurrence" in correlated
        assert "| State | awaiting_input |" in awaiting_record
        assert "| Workflow outcome | completed |" in awaiting_record
        assert "| Engineering outcome | partially_solved |" in awaiting_record
        assert "| documenter |" not in awaiting_record.lower()
        assert "deterministic clarification rendering passed" in awaiting_record
        assert "| repository-integration |" in awaiting_record
        assert "not activated; the standard conditional gate did not require it" in awaiting_record.lower()
    print("finalize_sentry_planning self-test: passed")
