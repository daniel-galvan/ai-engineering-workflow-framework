"""Bounded re-attestation of an accepted TechOps planning result."""

import hashlib
import json
from pathlib import Path


ATTESTATION = ("Accepted-result refresh: The intervening messages requested status or closure only; "
               "they contained no substantive correction or new task. The accepted findings are unchanged.")
OBJECTIVE = ("Review all messages and follow-ups received after your previously accepted answer and before this assignment. "
             "If and only if they requested status or closure only and contained no substantive correction "
             "or new task, return the exact accepted result and exact accepted output from the assigned files, "
             "appending this sentence to the output after two newlines: " + ATTESTATION + " "
             "If you cannot verify that, return a blocked result instead. Do not investigate, edit, test or build.")
ROLES = {"current_state_investigator", "dependency_analyst", "repository_integrator", "solution_architect", "reviewer"}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def authorize(root: Path, role: str, handle: str, status: str) -> dict:
    """Verify the failed run, original accepted evidence, and terminal latest worker dispatch."""
    try:
        from runtime_checks import trace_errors, trace_identity_errors, terminal_observation_errors
        from provider_runtime import latest_worker_dispatch, timestamp
        from planning_contracts import terminal_closure_dispatch_errors
        from worker_runtime_evidence import dispatch_audit_errors
        from validate_worker_runtime import _pending_rejections
    except ModuleNotFoundError:
        from scripts.runtime_checks import trace_errors, trace_identity_errors, terminal_observation_errors
        from scripts.provider_runtime import latest_worker_dispatch, timestamp
        from scripts.planning_contracts import terminal_closure_dispatch_errors
        from scripts.worker_runtime_evidence import dispatch_audit_errors
        from scripts.validate_worker_runtime import _pending_rejections
    root = root.resolve()
    try:
        bindings = json.loads((root / "role_bindings.json").read_text())
        current = json.loads((root / "finalization_packet.json").read_text())
        failure_path = root / "finalization_failure.json"
        failure = json.loads(failure_path.read_text())
        recovery = bindings["handoff_recovery"]
        snapshot = Path(failure["packet_snapshot"])
        if (role not in ROLES or bindings.get("playbook") != "techops_issue_remediation"
                or bindings.get("lifecycle") != "planning" or current["identity"].get("Lifecycle") != "planning"
                or failure.get("status") != "failed" or failure.get("stage") != "workflow"
                or failure.get("runtime_closure") != "terminal" or failure.get("reported_by") != "Coordinator"
                or failure.get("run_id") != current["identity"]["Run ID"]
                or recovery.get("run_id") != failure.get("run_id")
                or recovery.get("failure_sha256") != digest(failure_path)
                or snapshot.resolve().parent != root or snapshot.is_symlink()
                or digest(snapshot) != failure.get("snapshot_sha256")
                or failure.get("packet_sha256") != failure.get("snapshot_sha256")):
            raise ValueError("accepted_refresh_failure_binding_invalid")
        old = json.loads(snapshot.read_text())
        contract = bindings["worker_contracts"][role]
        worker = contract.get("worker_id") or contract.get("worker")
        audits = [row for row in old["runtime_audits"] if row.get("Worker") == worker]
        rows = [row for row in old["worker_results"] if row.get("Worker") == worker and row.get("Outcome") == "complete"]
        if len(audits) != 1 or len(rows) != 1 or audits[0].get("Provider handle") != handle:
            raise ValueError("accepted_refresh_prior_result_required")
        if [row for row in current.get("worker_results", []) if row.get("Worker") == worker] != rows:
            raise ValueError("accepted_refresh_prior_result_changed")
        if role in current.get("accepted_result_refreshes", {}) or role in current.get("activation_repairs", {}):
            raise ValueError("accepted_refresh_limit_reached")
        if _pending_rejections(root):
            raise ValueError("accepted_refresh_rejection_pending")
        prior = audits[0]
        trace_path = Path(prior["Trace path"])
        if trace_path.resolve().parent != root or trace_path.is_symlink():
            raise ValueError("accepted_refresh_trace_invalid")
        trace = json.loads(trace_path.read_text())
        errors = trace_errors(trace, require_freshness=True)
        errors += trace_identity_errors(trace, root, worker, handle, prior["Thread ID"])
        if errors or trace.get("last_dispatch_at") != prior.get("Last dispatch at"):
            raise ValueError("accepted_refresh_prior_trace_invalid:" + ";".join(errors))
        output, result = Path(contract["output"]), Path(contract["result"])
        if any(p.resolve().parent != root or p.is_symlink() for p in (output, result)):
            raise ValueError("accepted_refresh_artifact_invalid")
        staged = trace["result_artifact"]
        if (output.read_bytes() != Path(staged["output_path"]).read_bytes()
                or json.loads(result.read_text()) != json.loads(Path(staged["path"]).read_text())):
            raise ValueError("accepted_refresh_artifact_changed")
        ledger = json.loads((root / "runtime_dispatches.json").read_text())
        latest = latest_worker_dispatch(ledger, handle, include_failed=True)
        if (latest != latest_worker_dispatch(ledger, handle)
                or latest.get("Operation") not in {"send_message", "followup_task"}
                or timestamp(latest["Last dispatch at"]) <= timestamp(prior["Last dispatch at"])
                or ledger.get("thread_mappings", {}).get(handle) != prior["Thread ID"]):
            raise ValueError("accepted_refresh_later_dispatch_required")
        closure = json.loads((root / "runtime_closure.json").read_text())
        observations = closure["terminal_observations"]
        terminal = [row for row in observations if row.get("Provider handle") == handle]
        if (status not in {"completed", "idle"} or len(terminal) != 1
                or terminal[0].get("Provider status") != status
                or terminal[0].get("Last dispatch at") != latest["Last dispatch at"]
                or terminal_observation_errors(terminal, [handle])
                or terminal_closure_dispatch_errors(root / "finalization_packet.json", observations)
                or dispatch_audit_errors({"runtime_audits": []}, root / "finalization_packet.json", closure_only=True)):
            raise ValueError("accepted_refresh_terminal_evidence_invalid")
        return {"run_id": failure["run_id"], "worker": worker, "handle": handle,
                "thread_id": prior["Thread ID"], "prior_trace": str(trace_path), "prior_trace_sha256": digest(trace_path),
                "failure_sha256": digest(failure_path), "result": str(result), "result_sha256": digest(result),
                "output": str(output), "output_sha256": digest(output), "last_dispatch_at": latest["Last dispatch at"]}
    except (OSError, KeyError, TypeError, AttributeError, json.JSONDecodeError) as error:
        raise ValueError("accepted_refresh_evidence_invalid:" + str(error)) from error


def verify_response(root: Path, role: str, trace: dict) -> None:
    """Recheck a guarded refresh before either audit registration or result merging."""
    root = root.resolve()
    try:
        packet = json.loads((root / "finalization_packet.json").read_text())
        grant = packet.get("accepted_result_refreshes", {}).get(role)
        if not grant:
            return
        for field in ("prior_trace", "result", "output"):
            path = Path(grant[field])
            if path.resolve().parent != root or path.is_symlink():
                raise ValueError("accepted_refresh_saved_evidence_changed")
        if digest(Path(grant["prior_trace"])) != grant["prior_trace_sha256"]:
            raise ValueError("accepted_refresh_saved_evidence_changed")
        prior = json.loads(Path(grant["prior_trace"]).read_text())["result_artifact"]
        prior_result, prior_output = Path(prior["path"]), Path(prior["output_path"])
        if (digest(prior_result) != prior["sha256"] or digest(prior_output) != prior["output_sha256"]
                or digest(prior_output) != grant["output_sha256"]
                or json.loads(prior_result.read_text()) != json.loads(Path(grant["result"]).read_text())
                or Path(grant["output"]).read_text() not in {
                    prior_output.read_text(), prior_output.read_text() + "\n\n" + ATTESTATION}):
            raise ValueError("accepted_refresh_saved_evidence_changed")
        if (digest(root / "finalization_failure.json") != grant["failure_sha256"]
                or trace["run_id"] != grant["run_id"] or trace["thread_id"] != grant["thread_id"]
                or trace["spawn"]["provider_handle"] != grant["handle"]):
            raise ValueError("accepted_refresh_binding_changed")
        try:
            from provider_runtime import timestamp
        except ModuleNotFoundError:
            from scripts.provider_runtime import timestamp
        if timestamp(trace["last_dispatch_at"]) <= timestamp(grant["last_dispatch_at"]):
            raise ValueError("accepted_refresh_dispatch_not_new")
        # The trace's delivery proof must identify the exact guarded assignment.
        try:
            from runtime_checks import _verified_dispatch_content
        except ModuleNotFoundError:
            from scripts.runtime_checks import _verified_dispatch_content
        content = _verified_dispatch_content(trace)
        if content is None or hashlib.sha256(content.encode()).hexdigest() != grant["dispatch_sha256"]:
            raise ValueError("accepted_refresh_dispatch_mismatch")
        artifact = trace["result_artifact"]
        if (json.loads(Path(artifact["path"]).read_text()) != json.loads(prior_result.read_text())
                or Path(artifact["output_path"]).read_text() != prior_output.read_text() + "\n\n" + ATTESTATION):
            raise ValueError("accepted_refresh_response_changed_or_unattested")
    except (OSError, KeyError, TypeError, AttributeError, json.JSONDecodeError) as error:
        raise ValueError("accepted_refresh_response_invalid:" + str(error)) from error
