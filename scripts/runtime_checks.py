#!/usr/bin/env python3
"""Worker binding, context, trace, and transition validation without CLI orchestration."""

from __future__ import annotations

import ast
import io
import hashlib
import json
import re
import shlex
import subprocess
import tempfile
import tokenize
from datetime import datetime
from pathlib import Path

try:
    from workflow_policy import FORBIDDEN_MEMORY_CONTEXT_PATTERNS
except ModuleNotFoundError:
    from scripts.workflow_policy import FORBIDDEN_MEMORY_CONTEXT_PATTERNS


ROOT = Path(__file__).resolve().parents[1]
ACTIVE_STATUSES = {"pending_init", "running", "in_progress", "awaiting_dependency"}
TERMINAL_STATUSES = {"completed", "failed", "stopped", "interrupted", "cancelled"}
DESTRUCTIVE_TRANSITIONS = {"interrupt", "close", "replace"}
TRACE_METADATA_KEYS = {
    "description", "expected_errors", "source_task", "source_thread", "fixture", "schema_version",
}
FORBIDDEN_CONTEXT_PATTERNS = (
    *FORBIDDEN_MEMORY_CONTEXT_PATTERNS,
    ("archived_artifact", re.compile(r"(?i)(?:^|[\s/\\\"'])\.thoughts[/\\][^/\\]+[/\\]runs(?:$|[\s/\\\"'])")),
    ("archived_artifact", re.compile(r"(?i)\.thoughts[/\\][^/\\\s]+(?:[_-]v[0-9]+|[_-]backup|[_-]archive)(?:$|[/\\\s])")),
    ("memory_citation", re.compile(r"(?i)<oai-mem-citation>")),
)


try:
    from provider_runtime import (worker_binding, DELIVERY_WORKERS, launch_binding_errors, read_runtime_events,
                                  validate_prepared_provider_source, latest_worker_dispatch, timestamp)
except ModuleNotFoundError:
    from scripts.provider_runtime import (worker_binding, DELIVERY_WORKERS, launch_binding_errors,
                                          read_runtime_events, validate_prepared_provider_source,
                                          latest_worker_dispatch, timestamp)


def prepared_package_errors(root: Path, *, check_parent_context: bool = True) -> list[str]:
    """Reject package, lifecycle, profile or parent-context drift from the prepared run."""
    try:
        manifest = json.loads((root / "role_bindings.json").read_text())
        package = manifest.get("framework_package")
        if package is not None and (Path(package["root"]).resolve() != ROOT
                or package["plugin_sha256"] != hashlib.sha256((ROOT / ".codex-plugin/plugin.json").read_bytes()).hexdigest()):
            return ["prepared_framework_package_mismatch: prepare recovery from the selected package"]
        if manifest.get("lifecycle"):
            lifecycle = json.loads((root / "finalization_packet.json").read_text())["identity"].get("Lifecycle")
            if lifecycle != manifest["lifecycle"]:
                return ["prepared_lifecycle_mismatch:expected=" + manifest["lifecycle"] + ";received=" + str(lifecycle)]
        if manifest.get("execution_profile"):
            profile = json.loads((root / "finalization_packet.json").read_text())["identity"].get("Requested profile")
            if profile != manifest["execution_profile"]:
                return ["prepared_execution_profile_mismatch:expected=" + manifest["execution_profile"] + ";received=" + str(profile)]
        if check_parent_context:
            try:
                from provider_runtime import prepared_parent_context_errors
            except ModuleNotFoundError:
                from scripts.provider_runtime import prepared_parent_context_errors
            return prepared_parent_context_errors(root, manifest)
        return []
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return ["prepared_framework_package_invalid"]


def trace_identity_errors(trace: dict, root: Path, worker: str, handle: str, thread: str | None = None) -> list[str]:
    """Bind a prepared trace to the result slot being accepted."""
    if not (root / "role_bindings.json").is_file():
        return []  # Legacy records do not carry prepared worker identities.
    try:
        bindings = json.loads((root / "role_bindings.json").read_text())
        if not bindings.get("runtime_evidence"):
            return []  # Legacy records retain their original acceptance contract.
        current = json.loads((root / "finalization_packet.json").read_text())
        spawn = trace["spawn"]
        errors = []
        if trace.get("run_id") != current["identity"]["Run ID"]:
            errors.append("worker_trace_run_mismatch:" + worker)
        if worker_binding(bindings, spawn["agent"]) != worker_binding(bindings, worker):
            errors.append("worker_trace_role_mismatch:" + worker)
        if spawn.get("provider_handle") != handle:
            errors.append("worker_trace_handle_mismatch:" + worker)
        if (not trace.get("thread_id") or spawn.get("thread_id") != trace["thread_id"]
                or thread is not None and trace["thread_id"] != thread):
            errors.append("worker_trace_thread_mismatch:" + worker)
        observation = trace.get("status_observation", {})
        if (observation.get("Provider handle") != handle or observation.get("Thread ID") != trace.get("thread_id")
                or observation.get("Last dispatch at") != trace.get("last_dispatch_at")):
            errors.append("worker_trace_observation_mismatch:" + worker)
        errors.extend(terminal_observation_errors([observation], [handle]))
        errors.extend(launch_binding_errors(trace, root, worker_binding(bindings, worker)))
        errors.extend(result_artifact_errors(trace, bindings, root, worker_binding(bindings, worker)))
        return errors
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        return ["worker_trace_identity_invalid:" + worker + ":" + str(error)]


def result_artifact_errors(trace: dict, bindings: dict, root: Path, role: str) -> list[str]:
    """Require the staged response to match the latest completed worker answer."""
    contract = bindings.get("worker_contracts", {}).get(role, {})
    if not contract.get("result_hash_required"):
        return []
    receipt = trace.get("result_artifact", {})
    try:
        root = root.resolve()
        try:
            from worker_runtime_evidence import worker_final_response, strict_json_loads
        except ModuleNotFoundError:
            from scripts.worker_runtime_evidence import worker_final_response, strict_json_loads
        response = worker_final_response(Path(trace["trace_retrieval"]), trace["last_dispatch_at"],
                                         trace["status_observation"]["Observed at"],
                                         trace["status_observation"].get("Latest turn started at"),
                                         turn_id=trace["status_observation"].get("Latest turn ID"))
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        if str(error).startswith("worker_final_response"):
            return [str(error) + ":" + role]
        return ["worker_result_contract_invalid:" + role + ":" + str(error)]
    if not isinstance(receipt, dict) or receipt.get("dispatch_at") != trace.get("last_dispatch_at"):
        return ["worker_result_artifact_changed:" + role]
    try:
        dispatch_digest = hashlib.sha256(trace["last_dispatch_at"].encode()).hexdigest()[:16]
        stage = (root / ".worker_responses" / role / dispatch_digest).resolve()
        expected = {"path": ("result.json", "sha256"), "output_path": ("output.md", "output_sha256"),
                    "response_path": ("response.json", "response_sha256")}
        if contract.get("asset_inventory"):
            expected["asset_manifest_path"] = ("asset_manifest.json", "asset_manifest_sha256")
        paths = {}
        for field, (name, hash_field) in expected.items():
            path = Path(receipt.get(field, "")).resolve()
            if (path != stage / name or not path.is_file()
                    or receipt.get(hash_field) != hashlib.sha256(path.read_bytes()).hexdigest()):
                return ["worker_result_artifact_changed:" + role]
            paths[field] = path
        if paths["response_path"].read_text() != response:
            return ["worker_result_artifact_changed:" + role]
        envelope = strict_json_loads(response)
        if (paths["output_path"].read_text() != envelope["output"]
                or json.loads(paths["path"].read_text()) != envelope["result"]):
            return ["worker_result_artifact_changed:" + role]
        if contract.get("asset_inventory") and json.loads(paths["asset_manifest_path"].read_text()) != envelope.get("asset_manifest"):
            return ["worker_result_artifact_changed:" + role]
        try:
            from merge_techops_result import validated_result
        except ModuleNotFoundError:
            from scripts.merge_techops_result import validated_result
        validated_result(json.loads((root / "finalization_packet.json").read_text()),
                         envelope["result"], bindings, role)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        if str(error).startswith("worker_final_response"):
            return [str(error) + ":" + role]
        return ["worker_result_contract_invalid:" + role + ":" + str(error)]
    return []


def activation_message(packet: dict, assignment: dict) -> str:
    """Serialize the binding once; assignments cannot override prepared outputs or policy."""
    if (not isinstance(assignment, dict) or not isinstance(assignment.get("objective"), str)
            or not assignment["objective"].strip()
            or set(assignment) - {"objective", "input_paths"}
            or not isinstance(assignment.get("input_paths", []), list)
            or not all(isinstance(path, str) and path.strip() for path in assignment.get("input_paths", []))):
        raise ValueError("expected objective and optional input_paths only")
    for source in assignment.get("input_paths", []):
        path = Path(source)
        if path.name == "AGENTS.md":
            path = path if path.is_absolute() else Path(packet["finalization_packet"]).parents[2] / path
            if not path.is_file():
                raise ValueError("assigned_instruction_file_missing: omit absent optional guidance: " + source)
    return (packet["required_prefix"] + "\n" + json.dumps(packet, sort_keys=True)
            + "\nTyped assignment:\n" + json.dumps(assignment, sort_keys=True))


def dispatch_message(packet: dict, message: str, path: Path) -> str:
    """Keep the complete guarded instructions in an immutable current-run file."""
    root = Path(packet["finalization_packet"]).resolve().parent
    if path.resolve().parent != root or path.name in {"finalization_packet.json", "work_record.md"}:
        raise ValueError("activation_dispatch_file_outside_current_run")
    digest = hashlib.sha256(message.encode()).hexdigest()
    bindings_path = root / "role_bindings.json"
    receipts_path = root / "activation_receipts.json"
    receipts, receipt = None, None
    if bindings_path.is_file():
        bindings = json.loads(bindings_path.read_text())
        receipts = json.loads(receipts_path.read_text()) if receipts_path.exists() else {}
        receipt = {"sha256": digest, "run_id": packet["run_id"], "agent": packet["agent"],
                   "bundle_sha256": bindings["activation_packet_bundle"]["sha256"]}
        if path.name in receipts and any(receipts[path.name].get(key) != receipt[key]
                                         for key in ("sha256", "run_id", "agent")):
            raise ValueError("activation_dispatch_receipt_conflict")
    if path.exists():
        if path.read_text() != message:
            raise ValueError("activation_dispatch_file_conflict: use a new path for a corrected assignment")
    else:
        with path.open("x") as stream:
            stream.write(message)
    if receipts is not None and path.name not in receipts:
        receipts[path.name] = receipt
        with tempfile.NamedTemporaryFile("w", dir=root, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(receipts, stream, indent=2)
            stream.write("\n")
        try:
            temporary.replace(receipts_path)
        finally:
            temporary.unlink(missing_ok=True)
    return dispatch_notice(packet, message, path)


def dispatch_notice(packet: dict, message: str, path: Path) -> str:
    digest = hashlib.sha256(message.encode()).hexdigest()
    return (packet["required_prefix"] + "\n"
            + "First step: verify and read the supplied file; this bootstrap is self-contained. "
              "Before that read, do not search memory, previous chats, or historical artifacts.\n"
            + f"Role: {packet['agent']}; model/effort: {packet['model']} / {packet['effort']}.\n"
            + f"Run ID: {packet['run_id']}.\n"
            + f"Verify its SHA256 is {digest} before analytical work; on mismatch stop and report it.\n"
            + f"Read it with this separate literal command: {shlex.join(['cat', str(path.resolve())])}\n"
            + "Use separate tool calls for verification and the complete instruction read; do not combine "
              "the read with checksum scripts.\n"
            + f"Set that call's max_output_tokens to at least {len(message.encode())}; truncated output is not delivery.\n"
            + "After verification, continue in this same turn through the full typed assignment and write its required "
              "outputs. A bootstrap acknowledgment is not completion.\n"
            + "The file is the operative role, input, output and policy contract. Read it in full; do not substitute "
              "this launch notice for those instructions. Do not rerun Coordinator initialization.")


def delivery_start_errors(path: Path, implementer_handle: str, provider_status: str) -> list[str]:
    """Check an approved plan before an Implementer edits in a supported remediation playbook."""
    try:
        packet = json.loads(path.read_text())
        identity = packet["identity"]
        playbook = Path(str(identity.get("Playbook / version", "")).split(" / ", 1)[0]).stem
        if playbook == "feature_delivery" and identity.get("Lifecycle") != "remediation":
            return ["feature_implementation_requires_remediation_reentry"]
        if (playbook not in {"feature_delivery", "techops_issue_remediation", "sentry_issue_remediation"}
                or identity.get("Lifecycle") != "remediation"):
            return ["supported_remediation_reentry_required"]
        if (identity.get("Requested profile") not in {"standard", "deep"}
                or identity.get("Activated profile") != identity["Requested profile"]
                or identity.get("Profile status") != "in_progress" or identity.get("State") != "in_progress"):
            return ["remediation_not_activated:expected matching active profile and in_progress state"]
        reentry = packet.get("reentry", {})
        plan = path.parent / "implementation_plan.md"
        if (not reentry.get("Prior run ID") or reentry.get("Prior run ID") == identity.get("Run ID")
                or not str(reentry.get("Approval reference", "")).strip()
                or reentry.get("Approved plan") != str(plan.resolve())
                or reentry.get("Approved plan SHA256") != hashlib.sha256(plan.read_bytes()).hexdigest()):
            return ["approved_plan_changed_or_reentry_incomplete:record approval for the exact current plan"]
        if playbook in {"feature_delivery", "techops_issue_remediation"}:
            try:
                from review_evidence import applicability_errors
            except ModuleNotFoundError:
                from scripts.review_evidence import applicability_errors
            errors = applicability_errors(plan.read_text())
        else:
            try:
                from validation.api import checked
                from validation.finalization import validate_sentry_artifacts
            except ModuleNotFoundError:
                from scripts.validation.api import checked
                from scripts.validation.finalization import validate_sentry_artifacts
            try:
                checked(validate_sentry_artifacts, path.parent)
                errors = []
            except ValueError as error:
                errors = ["sentry_approved_plan_invalid:" + str(error)]
        if provider_status not in {"running", "in_progress"}:
            errors.append("active_implementer_required:expected running or in_progress; received " + provider_status)
        manifest_path = path.parent / "role_bindings.json"
        manifest = json.loads(manifest_path.read_text()) if manifest_path.is_file() else {}
        if manifest.get("runtime_evidence"):
            errors.extend(_feature_delivery_activation_errors(path, manifest, implementer_handle, provider_status))
        else:
            errors.extend(_legacy_delivery_activation_errors(packet, implementer_handle))
        return errors
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        return ["delivery_activation_invalid:" + str(error)]


def _legacy_delivery_activation_errors(packet: dict, implementer_handle: str) -> list[str]:
    """Keep the pre-runtime-evidence packet contract readable during migration."""
    errors, handles = [], []
    for worker, role in DELIVERY_WORKERS.items():
        rows = [row for row in packet.get("workers", []) if row.get("Worker") == worker]
        if len(rows) != 1 or str(rows[0].get("Role", "")).lower() != role:
            errors.append("delivery_worker_registration_required:" + worker)
            continue
        expected = {"in_progress", "running"} if worker == "implement" else {
            "awaiting_dependency", "in_progress", "running"}
        if rows[0].get("Outcome") not in expected or not str(rows[0].get("Depends on", "")).strip():
            errors.append("delivery_worker_activation_required:" + worker)
        match = re.search(r"Provider handle[: ]+(/root/[a-z0-9_]+(?:/[a-z0-9_]+)*|"
                          r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})(?=\s|;|$)",
                          str(rows[0].get("Assigned inputs", "")))
        if worker != "handoff" and not match:
            errors.append("delivery_worker_provider_handle_required:" + worker)
        elif match:
            handles.append(match[1])
            if worker == "implement" and match[1] != implementer_handle:
                errors.append("implementer_handle_mismatch")
    if len(handles) != len(set(handles)):
        errors.append("independent_delivery_handles_required")
    return errors


def _feature_delivery_activation_errors(path: Path, manifest: dict, implementer_handle: str,
                                        implementer_status: str) -> list[str]:
    """Verify remediation role launches from the prepared provider stream, not editable packet rows."""
    try:
        if (manifest.get("playbook") not in {"feature_delivery", "techops_issue_remediation", "sentry_issue_remediation"}
                or manifest.get("lifecycle") != "remediation"):
            return ["remediation_runtime_bindings_required"]
        contract = manifest["runtime_evidence"]
        ledger_path = Path(contract["ledger"])
        if ledger_path.resolve().parent != path.parent.resolve() or not ledger_path.is_file():
            return ["delivery_activation_runtime_ledger_required"]
        saved = json.loads(ledger_path.read_text())
        source = Path(saved["provider_session"])
        validate_prepared_provider_source(manifest, source, saved["parent_thread_id"], saved["run_started_at"])
        current = read_runtime_events(source, saved["parent_thread_id"], saved["run_started_at"],
                                      tuple(Path(value) for value in saved.get("identity_sessions", [])))
        if any(saved.get(key) != current.get(key) for key in ("events", "thread_mappings", "inventories", "failed_dispatches")):
            return ["runtime_dispatch_ledger_stale"]
        if not current.get("inventories"):
            return ["delivery_activation_fresh_inventory_required"]
        inventory = current["inventories"][-1]
        statuses = {}
        for row in inventory["raw_response"].get("agents", []):
            status = row.get("agent_status")
            if isinstance(status, dict) and len(status) == 1:
                status = next(iter(status))
            statuses[row.get("agent_name")] = str(status).strip().lower().replace(" ", "_")
        required = {"implement": "implementer", "review": "reviewer", "validate": "tester"}
        packet = json.loads(path.read_text())
        run_id = packet["identity"]["Run ID"]
        selected, handles = {}, []
        inventory_at = timestamp(inventory["Observed at"])
        for worker, role in required.items():
            candidates = [row for row in current["events"] if row.get("Operation") == "spawn_agent"
                          and row.get("Binding agent") == role and row.get("Provider handle") in statuses
                          and statuses[row["Provider handle"]] in {"pending_init", "running", "in_progress", "awaiting_dependency"}]
            candidates = [row for row in candidates if timestamp(row["Last dispatch at"]) <= inventory_at]
            if len(candidates) != 1:
                return ["delivery_worker_live_activation_required:" + worker]
            dispatch = candidates[0]
            handle = dispatch["Provider handle"]
            latest = latest_worker_dispatch(current, handle)
            if timestamp(latest["Last dispatch at"]) > inventory_at:
                return ["delivery_activation_fresh_inventory_required"]
            expected = manifest.get("bindings", {}).get(role, {})
            launch = dispatch.get("Launch", {})
            if (launch.get("fork_turns") != "none" or launch.get("model") != expected.get("model")
                    or launch.get("reasoning_effort") != expected.get("effort")):
                return ["worker_launch_binding_mismatch:" + role]
            trace = {"run_id": run_id, "spawn": {
                "agent": handle.rsplit("/", 1)[-1], "binding_agent": role, "provider_handle": handle,
                "dispatch_file": dispatch.get("Dispatch file"),
                "dispatch_file_sha256": dispatch.get("Dispatch SHA256")}}
            if not dispatch.get("Dispatch file") or not _verified_dispatch_content(trace):
                return ["worker_dispatch_assignment_unverified:" + role]
            selected[worker] = handle
            handles.append(handle)
        if len(handles) != len(set(handles)):
            return ["independent_delivery_handles_required"]
        if selected["implement"] != implementer_handle:
            return ["implementer_handle_mismatch"]
        actual_status = statuses.get(implementer_handle, "unknown")
        if actual_status != implementer_status.strip().lower().replace(" ", "_"):
            return ["implementer_provider_status_mismatch:expected=" + actual_status]
        return []
    except (OSError, ValueError, KeyError, TypeError, AttributeError, StopIteration) as error:
        return ["delivery_activation_runtime_invalid:" + str(error)]


def transition_error(action: str, provider_status: str, *, rejected_result: bool = False) -> str | None:
    status = provider_status.strip().lower()
    if action in DESTRUCTIVE_TRANSITIONS and status in ACTIVE_STATUSES:
        return f"unsafe_{action}_while_{status}"
    if action == "close" and status not in TERMINAL_STATUSES:
        return f"close_requires_terminal_status:{status or 'unknown'}"
    if (action == "replace" and status not in {"failed", "stopped", "interrupted", "cancelled"}
            and not (status == "completed" and rejected_result)):
        return f"replace_requires_failed_or_stopped_status:{status or 'unknown'}"
    if action == "fan_in" and status != "completed":
        return f"fan_in_requires_completed_status:{status or 'unknown'}"
    return None


def rejected_result_errors(trace: dict, handle: str, dispatch: str) -> list[str]:
    """An inactive task can be replaced only with its independently rejected current result."""
    if not isinstance(trace, dict):
        return ["rejected_result_trace_invalid"]
    observation = trace.get("status_observation", {})
    if not isinstance(observation, dict) or not isinstance(trace.get("spawn"), dict):
        return ["rejected_result_trace_invalid"]
    errors = terminal_observation_errors([observation], [handle], require_completed=False)
    if trace["spawn"].get("activation_message_conformance") == "failed":
        expected = trace["spawn"].get("expected_message_sha256", "")
        observed = trace["spawn"].get("observed_message_sha256", "")
        if (not all(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value)
                    for value in (expected, observed)) or expected == observed):
            errors.append("activation_rejection_evidence_required")
    if (trace.get("spawn", {}).get("provider_handle") != handle
            or trace.get("last_dispatch_at") != dispatch
            or observation.get("Last dispatch at") != dispatch
            or observation.get("Thread ID") != trace.get("thread_id")
            or observation.get("Thread ID") != trace["spawn"].get("thread_id")):
        errors.append("rejected_result_dispatch_mismatch")
    audit = trace.get("audit", {})
    actual = trace_errors(trace, require_freshness=True)
    if (not any(error != "worker_fan_in_rejected" for error in actual)
            or not isinstance(audit, dict) or audit.get("status") != "rejected" or audit.get("errors") != actual):
        errors.append("rejected_result_audit_required")
    return errors


def terminal_observation_errors(observations: object, handles: list[str], *, require_completed: bool = True) -> list[str]:
    """Require completion for fan-in; closure may also prove a failed worker is inactive."""
    if not isinstance(observations, list) or not observations:
        return ["terminal_observations_required"]
    errors: list[str] = []
    observed: set[str] = set()
    for row in observations:
        if not isinstance(row, dict):
            errors.append("terminal_observation_invalid")
            continue
        handle = str(row.get("Provider handle", ""))
        if handle not in handles or handle in observed or not re.fullmatch(
            r"(?:[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}|/root/[a-z0-9_]+(?:/[a-z0-9_]+)*)", handle,
        ):
            errors.append(f"terminal_observation_handle_invalid:{handle}")
        observed.add(handle)
        statuses = {"completed", "idle"} if require_completed else TERMINAL_STATUSES | {"idle"}
        if str(row.get("Provider status", "")).lower() not in statuses:
            errors.append(f"terminal_observation_not_terminal:{handle}")
        source = str(row.get("Status source", ""))
        if source not in {"list_agents", "read_thread", "wait_threads"}:
            errors.append(f"terminal_observation_source_invalid:{handle}")
        if source in {"read_thread", "wait_threads"} and not re.fullmatch(
            r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", str(row.get("Thread ID", "")),
        ):
            errors.append(f"terminal_observation_thread_id_required:{handle}")
        try:
            if any(not re.fullmatch(
                r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})", str(row.get(field, "")),
            ) for field in ("Last dispatch at", "Observed at")):
                raise ValueError
            times = [datetime.fromisoformat(str(row[field]).replace("Z", "+00:00"))
                     for field in ("Last dispatch at", "Observed at")]
            if source in {"read_thread", "wait_threads"}:
                started = datetime.fromisoformat(str(row["Latest turn started at"]).replace("Z", "+00:00"))
                # Thread metadata exposes seconds; dispatch receipts may retain subsecond precision.
                fresh_turn = started >= times[0].replace(microsecond=0)
                if (not fresh_turn and row.get("Dispatch consumed") is True
                        and str(row.get("Dispatch consumption evidence", "")).strip()):
                    completed = datetime.fromisoformat(str(row["Latest turn completed at"]).replace("Z", "+00:00"))
                    fresh_turn = (completed.tzinfo is not None and
                                  times[0].replace(microsecond=0) <= completed <= times[1] and started <= completed)
                if started.tzinfo is None or not fresh_turn or started > times[1]:
                    errors.append(f"terminal_observation_latest_turn_stale:{handle}")
                turn_statuses = {"completed"} if require_completed else TERMINAL_STATUSES
                if row.get("Latest turn status") not in turn_statuses:
                    errors.append(f"terminal_observation_latest_turn_not_completed:{handle}")
                if row.get("Thread status") not in {"idle", "notLoaded"}:
                    errors.append(f"terminal_observation_thread_not_idle:{handle}")
            if any(value.tzinfo is None for value in times):
                raise ValueError
            if times[1] < times[0]:
                errors.append(f"terminal_observation_stale:{handle}")
        except (KeyError, ValueError, TypeError):
            errors.append(f"terminal_observation_timestamp_invalid:{handle}")
    if observed != set(handles):
        errors.append("terminal_observations_incomplete")
    return list(dict.fromkeys(errors))


def techops_check_errors(checks: object, evidence_ids: set[str]) -> list[str]:
    if not isinstance(checks, list):
        return ["techops_planning_checks_required"]
    errors: list[str] = []
    seen: set[str] = set()
    for row in checks:
        if not isinstance(row, dict):
            errors.append("techops_planning_check_invalid")
            continue
        name = str(row.get("Check", ""))
        if name not in TECHOPS_CHECKS or name in seen:
            errors.append(f"techops_planning_check_invalid:{name}")
        seen.add(name)
        status = row.get("Status")
        if status != "passed" and not (name == "history_reconciliation" and status == "not_applicable"):
            errors.append(f"techops_planning_check_not_passed:{name}")
        if name == "history_reconciliation" and status == "passed":
            if (not re.fullmatch(r"[0-9a-fA-F]{7,40}", str(row.get("Commit", "")))
                    or not str(row.get("Work item", "")).strip()):
                errors.append("techops_history_patch_and_work_item_required")
            else:
                for field in ("Patch evidence refs", "Work item evidence refs"):
                    proof = re.findall(r"\bE-[A-Za-z0-9_-]+\b", str(row.get(field, "")))
                    check_refs = set(re.findall(r"\bE-[A-Za-z0-9_-]+\b", str(row.get("Evidence refs", ""))))
                    if not proof or not set(proof) <= evidence_ids & check_refs:
                        errors.append("techops_history_patch_and_work_item_required")
                patch_refs = set(re.findall(r"\bE-[A-Za-z0-9_-]+\b", str(row.get("Patch evidence refs", ""))))
                item_refs = set(re.findall(r"\bE-[A-Za-z0-9_-]+\b", str(row.get("Work item evidence refs", ""))))
                if patch_refs & item_refs:
                    errors.append("techops_history_distinct_sources_required")
        refs = re.findall(r"\bE-[A-Za-z0-9_-]+\b", str(row.get("Evidence refs", "")))
        if not refs or not set(refs) <= evidence_ids or not str(row.get("Detail", "")).strip():
            errors.append(f"techops_planning_check_evidence_required:{name}")
    if seen != TECHOPS_CHECKS:
        errors.append("techops_planning_checks_incomplete")
    return list(dict.fromkeys(errors))


def _trace_strings(value: object, path: tuple[str, ...] = ()):
    """Yield strings from provider tool activity, excluding fixture metadata."""
    if isinstance(value, dict):
        for key, nested in value.items():
            if str(key) in TRACE_METADATA_KEYS or not path and key == "audit":
                continue
            yield from _trace_strings(nested, (*path, str(key)))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            yield from _trace_strings(nested, (*path, str(index)))
    elif isinstance(value, str):
        if path[:1] == ("tool_trace",) and "output" in path[2:]:
            try:
                decoded = json.loads(value)
                if isinstance(decoded, (dict, list)):
                    yield from _trace_strings(decoded, path)
                    return
            except ValueError:
                pass
        yield path, value


def _listing_command(command: object) -> bool:
    """Recognize name-only discovery; shell expansion and content consumers remain unaudited."""
    if not isinstance(command, str) or any(char in command for char in "$`<>"):
        return False
    try:
        tokens = shlex.split(command)
        if len(tokens) == 3 and Path(tokens[0]).name in {"bash", "sh", "zsh"} and tokens[1] in {"-lc", "-c"}:
            command = tokens[2]
        lexer = shlex.shlex(command, posix=True, punctuation_chars="|;&")
        lexer.whitespace_split = True
        lexer.commenters = ""
        parts, current = [], []
        for token in lexer:
            if token in {";", "&&", "|", "||", "&"}:
                parts.extend([current, token])
                current = []
            else:
                current.append(token)
        parts.append(current)
        previous = ""
        for part in parts:
            if isinstance(part, str):
                if part not in {";", "&&", "|"}:
                    return False
                previous = part
                continue
            args = part
            if not args:
                continue
            tool = Path(args[0]).name
            listing = (args == ["git", "status", "--short"]
                       or tool in {"ls", "pwd"} or (tool == "rg" and "--files" in args)
                       or (tool == "find" and not set(args) & {
                           "-exec", "-execdir", "-ok", "-okdir", "-delete", "-fprint", "-fprint0", "-fprintf"}))
            filter_only = (previous == "|" and (
                (tool in {"head", "tail"} and all(re.fullmatch(r"-?(?:n|[0-9]+)", arg) for arg in args[1:]))
                or (tool in {"rg", "grep"} and len(args) == 2 and not args[1].startswith("-"))))
            metadata = (tool == "wc" and len(args) in {3, 4}
                        and all(arg in {"-l", "-c", "-lc", "-cl"} for arg in args[1:-1])
                        and not args[-1].startswith("-")
                        and not any(pattern.search(args[-1]) for _, pattern in FORBIDDEN_CONTEXT_PATTERNS))
            if not listing and not filter_only and not metadata:
                return False
            previous = ""
        return bool(tokens)
    except ValueError:
        return False


def _listing_read_prefix(command: str, cwd: Path) -> str | None:
    """Separate a final listing from literal reads without exempting the read content."""
    if not isinstance(command, str) or any(char in command for char in "$`<>"):
        return None
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|")
        lexer.whitespace_split = True
        lexer.commenters = ""
        parts, current = [], []
        for token in lexer:
            if token and all(char in ";&" for char in token):
                if token not in {";", "&&"} or not current:
                    return None
                parts.append(current)
                current = []
            else:
                current.append(token)
        parts.append(current)
        if len(parts) < 2 or not _listing_command(shlex.join(parts[-1])):
            return None
        prefix = ""
        for part in parts[:-1]:
            limit = None
            if "|" in part:
                split = part.index("|")
                pipe = part[split + 1:]
                if (part.count("|") != 1 or len(pipe) != 2 or pipe[0] != "head"
                        or not re.fullmatch(r"-[1-9][0-9]{0,3}", pipe[1])):
                    return None
                limit = int(pipe[1][1:])
                part = part[:split]
            content = ""
            targets = _read_targets(shlex.join(part))
            if targets:
                for target in targets:
                    path = Path(target)
                    path = path if path.is_absolute() else cwd / path
                    if (any(pattern.search(str(path.resolve())) for _, pattern in FORBIDDEN_CONTEXT_PATTERNS)
                            or not path.is_file() or path.stat().st_size + len(prefix) + len(content) > 262144):
                        return None
                    text = path.read_text()
                    if part[:2] == ["sed", "-n"]:
                        bounds = [int(value) for value in part[2][:-1].split(",")]
                        if min(bounds) < 1 or bounds[-1] < bounds[0]:
                            return None
                        text = "".join(text.splitlines(keepends=True)[bounds[0] - 1:bounds[-1]])
                    content += text
            elif len(part) >= 4 and part[:2] == ["rg", "-n"]:
                if part[2].startswith("-"):
                    return None
                checked, size = 0, len(prefix)
                for target in part[3:]:
                    path = Path(target)
                    path = path if path.is_absolute() else cwd / path
                    for source in path.rglob("*") if path.is_dir() else [path]:
                        checked += 1
                        if (checked > 256 or not source.resolve().is_relative_to(cwd.resolve())
                                or any(pattern.search(str(source.resolve())) for _, pattern in FORBIDDEN_CONTEXT_PATTERNS)
                                or source.is_symlink()):
                            return None
                        if source.is_file():
                            size += source.stat().st_size
                        elif not source.is_dir():
                            return None
                        if size > 262144:
                            return None
                # Reproduce only bounded literal searches, never provider shell code or rg options.
                with tempfile.TemporaryFile() as output:
                    result = subprocess.run(["rg", "--no-config", "-n", "--", *part[2:]], cwd=cwd,
                                            stdout=output, stderr=subprocess.DEVNULL, timeout=2)
                    if result.returncode not in {0, 1} or output.tell() > 262144:
                        return None
                    output.seek(0)
                    content = output.read().decode()
            elif len(part) >= 2 and part[0] == "printf":
                format_string = part[1]
                if (not re.fullmatch(r"(?:[^%]|%s|%%)*", format_string)
                        or re.search(r"\\(?![nt\\])", format_string)):
                    return None
                format_string = re.sub(r"\\([nt\\])", lambda match: {
                    "n": "\n", "t": "\t", "\\": "\\"}[match[1]], format_string)
                content = format_string % tuple(part[2:])
            else:
                return None
            prefix += content if limit is None else "".join(content.splitlines(keepends=True)[:limit])
            if len(prefix) > 262144:
                return None
        return prefix or None
    except (OSError, UnicodeError, ValueError, TypeError, subprocess.TimeoutExpired):
        return None


def _listing_outputs(trace: dict, *, read_prefixes: dict | None = None,
                     cwd: Path | None = None) -> set[tuple[str, ...]]:
    outputs, calls, mixed = set(), set(), {}
    rows = trace.get("tool_trace", [])
    if not isinstance(rows, list):
        return outputs
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        prefix = ("tool_trace", str(index))
        operations = _tool_operations(row)
        if operations and all(name == "exec_command" and _listing_command(arguments.get("cmd"))
                              for name, arguments in operations):
            if row.get("call_id"):
                calls.add(row["call_id"])
            outputs.update({prefix + ("result",), prefix + ("output",), prefix + ("arguments", "output"),
                            prefix + ("arguments", "cmd")})
        elif read_prefixes is not None and len(operations) == 1 and operations[0][0] == "exec_command":
            arguments = operations[0][1]
            workdir = arguments.get("workdir", cwd or Path.cwd())
            content = (_listing_read_prefix(arguments.get("cmd"), Path(workdir))
                       if isinstance(workdir, (str, Path)) else None)
            if content:
                for key in ("result", "output"):
                    read_prefixes[prefix + (key,)] = content
                if row.get("call_id"):
                    mixed[row["call_id"]] = content
        if row.get("type") in {"function_call_output", "custom_tool_call_output"} and row.get("call_id") in calls:
            outputs.add(prefix + ("output",))
        if read_prefixes is not None and row.get("type") in {"function_call_output", "custom_tool_call_output"}:
            if row.get("call_id") in mixed:
                read_prefixes[prefix + ("output",)] = mixed[row["call_id"]]
    return outputs


def _verified_dispatch_content(trace: dict) -> str | None:
    """Authenticate the current prepared contract before exempting its metadata echo."""
    try:
        spawn = trace["spawn"]
        path = Path(spawn["dispatch_file"]).resolve()
        if any(pattern.search(str(path)) for _, pattern in FORBIDDEN_CONTEXT_PATTERNS):
            return None
        content = path.read_text()
        if hashlib.sha256(path.read_bytes()).hexdigest() != spawn["dispatch_file_sha256"]:
            return None
        root = path.parent
        bindings = json.loads((root / "role_bindings.json").read_text())
        reference = bindings["activation_packet_bundle"]
        bundle_path = Path(reference["path"]).resolve()
        if bundle_path.parent != root or hashlib.sha256(bundle_path.read_bytes()).hexdigest() != reference["sha256"]:
            return None
        role = worker_binding(bindings, spawn.get("binding_agent", spawn["agent"]))
        packet = json.loads(bundle_path.read_text())["packets"][role]
        receipts_path = root / "activation_receipts.json"
        if receipts_path.exists():
            receipt = json.loads(receipts_path.read_text()).get(path.name, {})
            if (receipt.get("sha256") != spawn["dispatch_file_sha256"]
                    or receipt.get("run_id") != trace["run_id"] or receipt.get("agent") != role):
                return None
            if receipt["bundle_sha256"] != reference["sha256"]:
                packet = json.loads(content.split("\n", 2)[1])
        current = json.loads((root / "finalization_packet.json").read_text())
        if (Path(packet["finalization_packet"]).resolve() != root / "finalization_packet.json"
                or packet["run_id"] != trace["run_id"]
                or packet["run_id"] != current["identity"]["Run ID"]
                or packet["agent"] != role):
            return None
        assignment = json.loads(content.split("\nTyped assignment:\n", 1)[1])
        return content if activation_message(packet, assignment) == content else None
    except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError):
        return None


def _authorized_read(row: dict, assigned: list[str]) -> bool:
    operations = _tool_operations(row)
    if operations and all(name == "exec_command" for name, _ in operations):
        targets = [_read_targets(arguments.get("cmd", "")) for _, arguments in operations]
        if all(targets) and all(path in assigned for group in targets for path in group):
            return True
    arguments = row.get("arguments", {})
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except ValueError:
            arguments = {}
    command = arguments.get("cmd") if isinstance(arguments, dict) else None
    if command is None and row.get("type") == "custom_tool_call":
        command = row.get("input")
    if isinstance(command, str) and "tools.exec_command" in command:
        match = re.fullmatch(r"(?:text\()?await tools\.exec_command\((\{.*\})\)\)?;?", command.strip(), re.S)
        if not match:
            return False
        try:
            command = json.loads(match.group(1)).get("cmd")
        except (ValueError, AttributeError):
            return False
    if not isinstance(command, str) or any(char in command for char in (";", "|", "&", ">", "<", "\n", "`", "$")):
        return False
    try:
        tokens = shlex.split(command)
    except ValueError:
        return False
    return bool(tokens and not any(token.startswith("--pre") for token in tokens)
                and tokens[0] in {"cat", "head", "tail", "rg"}
                and any(path in tokens for path in assigned))


def _literal_argument(node: ast.AST, constants: dict[str, str] | None = None):
    constants = constants or {}
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            elif (isinstance(value, ast.FormattedValue) and isinstance(value.value, ast.Name)
                  and value.conversion == -1 and value.format_spec is None
                  and value.value.id in constants):
                parts.append(constants[value.value.id])
            else:
                raise ValueError("nonliteral template substitution")
        return "".join(parts)
    if isinstance(node, ast.Dict):
        return {(key.id if isinstance(key, ast.Name) else _literal_argument(key, constants)):
                _literal_argument(value, constants)
                for key, value in zip(node.keys, node.values)}
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_literal_argument(value, constants) for value in node.elts]
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.List) and node.func.attr == "join"
            and len(node.args) == 1 and not node.keywords):
        parts = _literal_argument(node.func.value, constants)
        separator = _literal_argument(node.args[0], constants)
        if isinstance(separator, str) and all(isinstance(part, str) for part in parts):
            return separator.join(parts)
        raise ValueError("nonliteral string join")
    if isinstance(node, ast.Name) and node.id in {"true", "false", "null"}:
        return {"true": True, "false": False, "null": None}[node.id]
    if isinstance(node, ast.Name) and node.id in constants:
        return constants[node.id]
    raise ValueError("nonliteral tool argument")


def _literal_templates(source: str) -> str:
    """Translate unescaped JS templates into restricted Python string ASTs, without execution."""
    if "`" not in source:
        return source
    while True:
        token, previous, comment_line, block_comment = None, None, None, False
        for item in tokenize.generate_tokens(io.StringIO(source).readline):
            if item.start[0] == comment_line:
                continue
            if block_comment:
                if previous and previous.string == "*" and item.string == "/" and previous.end == item.start:
                    block_comment = False
                previous = item
                continue
            if item.string == "//":
                comment_line = item.start[0]
                continue
            if previous and previous.string == "/" and item.string == "*" and previous.end == item.start:
                block_comment = True
                previous = item
                continue
            if item.type in {tokenize.OP, tokenize.ERRORTOKEN} and item.string == "`":
                token = item
                break
            previous = item
        if token is None:
            return source
        lines = source.splitlines(keepends=True)
        start = sum(map(len, lines[:token.start[0] - 1])) + token.start[1]
        end = source.find("`", start + 1)
        if end < 0:
            raise ValueError("unterminated template")
        raw = source[start + 1:end]
        if "\\" in raw:
            raise ValueError("escaped templates are not literal arguments")
        output_template = (re.search(r"(?<![\w.])text\s*\(\s*$", source[:start]) is not None
                           and re.match(r"\s*\)", source[end + 1:]) is not None)
        parts, offset = [], 0
        for match in re.finditer(r"\$\{([^}]*)\}", raw):
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*", match[1]):
                # Output-only property checks do not change literal tool arguments.
                if output_template and re.fullmatch(
                        r"[A-Za-z_][A-Za-z0-9_]*(?:(?:\?\.|\.)[A-Za-z_][A-Za-z0-9_]*)*"
                        r"\s*===\s*(?:true|false)", match[1]):
                    parts.append(raw[offset:match.start()].replace("{", "{{").replace("}", "}}"))
                    offset = match.end()
                    continue
                raise ValueError("computed template substitution")
            parts.append(raw[offset:match.start()].replace("{", "{{").replace("}", "}}"))
            parts.append("{" + match[1] + "}")
            offset = match.end()
        parts.append(raw[offset:].replace("{", "{{").replace("}", "}}"))
        if "${" in raw[offset:]:
            raise ValueError("incomplete template substitution")
        source = source[:start] + "f" + repr("".join(parts)) + source[end + 1:]


def _tool_operations(row: dict) -> list[tuple[str, dict]]:
    """Read literal provider arguments; never evaluate orchestration source."""
    if row.get("type") == "function_call" or row.get("tool") == "exec_command":
        arguments = row.get("arguments", {})
        try:
            arguments = json.loads(arguments) if isinstance(arguments, str) else arguments
            return [(row.get("name", row.get("tool", "")), arguments)] if isinstance(arguments, dict) else []
        except ValueError:
            return []
    source = row.get("input")
    if row.get("type") != "custom_tool_call" or not isinstance(source, str):
        return []
    if row.get("name", "").rsplit(".", 1)[-1] == "apply_patch":
        return [("apply_patch", {"patch": source})]
    try:
        source = _literal_templates(source)
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
        operations, constants, declared, index, brace_depth = [], {}, set(), 0, 0
        unsafe_bindings = False
        while index < len(tokens):
            # JavaScript comments must not create operations from quoted examples.
            if tokens[index].string == "//":
                line = tokens[index].start[0]
                while index < len(tokens) and tokens[index].start[0] == line:
                    index += 1
                continue
            if tokens[index].string == "/" and index + 1 < len(tokens) and tokens[index + 1].string == "*":
                index += 2
                while index + 1 < len(tokens) and [v.string for v in tokens[index:index + 2]] != ["*", "/"]:
                    index += 1
                index += 2
                continue
            if tokens[index].type == tokenize.NAME and tokens[index].string in {"const", "let", "var"}:
                if index + 1 < len(tokens) and tokens[index + 1].type == tokenize.NAME:
                    name = tokens[index + 1].string
                    unique_top_level_const = (tokens[index].string == "const" and name not in declared
                                              and brace_depth == 0 and not unsafe_bindings)
                    declared.add(name)
                    if (unique_top_level_const and index + 3 < len(tokens)
                            and tokens[index + 2].string == "=" and tokens[index + 3].string == "["):
                        end = next((i for i in range(index + 4, len(tokens))
                                    if tokens[i].type == tokenize.OP and tokens[i].string == ";"), None)
                        if end is not None:
                            lines = source.splitlines(keepends=True)
                            positions = (tokens[index + 3].start, tokens[end].start)
                            begin, finish = [sum(map(len, lines[:line - 1])) + column
                                             for line, column in positions]
                            try:
                                value = _literal_argument(ast.parse(source[begin:finish], mode="eval").body,
                                                          constants)
                            except (ValueError, SyntaxError, TypeError):
                                value = None
                            if isinstance(value, str):
                                constants[name] = value
                                index = end + 1
                                continue
                    boundary = index + 4
                    literal_statement = (boundary < len(tokens) and tokens[boundary].string == ";")
                    if (boundary + 1 < len(tokens) and tokens[boundary].type in {tokenize.NL, tokenize.NEWLINE}
                            and tokens[boundary + 1].type == tokenize.NAME
                            and tokens[boundary + 1].string in {"await", "const", "let", "var", "tools"}):
                        literal_statement = True
                    if (unique_top_level_const and index + 3 < len(tokens)
                            and tokens[index + 2].string == "=" and tokens[index + 3].type == tokenize.STRING
                            and literal_statement):
                        try:
                            value = ast.literal_eval(tokens[index + 3].string)
                        except (SyntaxError, ValueError):
                            value = None
                        if isinstance(value, str):
                            constants[name] = value
                        index += 4
                        continue
                    constants.pop(name, None)
                    index += 2
                    continue
                constants.clear()
                unsafe_bindings = True
            if (tokens[index].type == tokenize.NAME and tokens[index].string == "function"
                    or tokens[index].string == "=" and index + 1 < len(tokens)
                    and tokens[index + 1].string == ">"):
                constants.clear()
                unsafe_bindings = True
            if (tokens[index].type == tokenize.NAME and tokens[index].string in constants
                    and index + 1 < len(tokens)
                    and tokens[index + 1].string in {"=", "+=", "-=", "*=", "/=", "%=", "++", "--"}):
                constants.pop(tokens[index].string, None)
            if tokens[index].type == tokenize.NAME and tokens[index].string in {"eval", "Function", "globalThis", "constructor"}:
                return []
            if (tokens[index].type == tokenize.NAME and tokens[index].string == "tools"
                    and (index + 3 >= len(tokens) or tokens[index + 1].string != "."
                         or tokens[index + 3].string != "(")):
                return []
            if (index + 3 < len(tokens) and tokens[index].type == tokenize.NAME
                    and tokens[index].string == "tools" and tokens[index + 1].string == "."
                    and tokens[index + 2].type == tokenize.NAME and tokens[index + 3].string == "("):
                name, start, depth = tokens[index + 2].string, index + 4, 1
                index = start
                while index < len(tokens) and depth:
                    if tokens[index].type == tokenize.OP:
                        depth += (tokens[index].string == "(") - (tokens[index].string == ")")
                    index += 1
                if depth:
                    return []
                lines = source.splitlines(keepends=True)
                begin, finish = tokens[start].start, tokens[index - 1].start
                offsets = [sum(map(len, lines[:line - 1])) + column for line, column in (begin, finish)]
                argument = _literal_templates(source[offsets[0]:offsets[1]])
                value = _literal_argument(ast.parse(argument, mode="eval").body,
                                          constants if brace_depth == 0 else {})
                if name == "apply_patch" and isinstance(value, str):
                    value = {"patch": value}
                if not isinstance(value, dict):
                    return []
                operations.append((name, value))
                continue
            if (tokens[index].string == "?" and index + 1 < len(tokens)
                    and tokens[index + 1].string == "."):
                index += 1
                continue
            if tokens[index].type == tokenize.ERRORTOKEN and tokens[index].string.strip():
                return []
            if tokens[index].type == tokenize.OP:
                brace_depth += (tokens[index].string == "{") - (tokens[index].string == "}")
            index += 1
        return operations
    except (ValueError, SyntaxError, TypeError, tokenize.TokenError, IndentationError):
        return []


def _chunked_dispatch_read(command: str) -> tuple[str, int] | None:
    """Recognize only the literal, complete chunk printer; never execute provider code."""
    if not isinstance(command, str):
        return None
    match = re.fullmatch(r"python3 - <<['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?\n(.*?)\n\1\s*", command, re.S)
    if not match:
        return None
    try:
        tree = ast.parse(match[2])
        target = tree.body[0].value.value
        size = tree.body[2].iter.args[2].value
        if not isinstance(target, str) or type(size) is not int or not 256 <= size <= 65536:
            return None
        template = (f"p={target!r}\ns=open(p).read()\n"
                    f"for i in range(0,len(s),{size}): print(f'---CHUNK {{i}}---\\n{{s[i:i+{size}]}}')")
        if ast.dump(tree) == ast.dump(ast.parse(template)):
            return target, size
    except (SyntaxError, AttributeError, IndexError, TypeError, ValueError):
        pass
    return None


def _dispatch_read_output(command: str, content: str) -> str:
    chunk = _chunked_dispatch_read(command)
    if chunk:
        return "".join(f"---CHUNK {i}---\n{content[i:i+chunk[1]]}\n" for i in range(0, len(content), chunk[1]))
    return content


def _python_read_targets(source: str) -> list[str]:
    """Recognize the recorded JSON inspection form; other Python remains unaudited."""
    tree = ast.parse(source)
    targets, constants = [], {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(item.name != "json" or item.asname for item in node.names):
            return []
        if isinstance(node, (ast.ImportFrom, ast.FunctionDef, ast.ClassDef, ast.Lambda)):
            return []
        if isinstance(node, ast.Assign) and any(not isinstance(target, ast.Name)
                or target.id in {"open", "json", "print"} for target in node.targets):
            return []
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    constants[target.id] = node.value.value
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            if node.func.id == "open":
                if len(node.args) != 1 or node.keywords:
                    return []
                argument = node.args[0]
                path = argument.value if isinstance(argument, ast.Constant) else constants.get(
                    argument.id if isinstance(argument, ast.Name) else "")
                if not isinstance(path, str):
                    return []
                targets.append(path)
            elif node.func.id not in {"print", "len", "isinstance", "str", "list", "type", "sorted"}:
                return []
        elif isinstance(node.func, ast.Attribute):
            json_load = (isinstance(node.func.value, ast.Name) and node.func.value.id == "json"
                         and node.func.attr in {"load", "dumps"})
            if json_load and any(keyword.arg not in {"indent", "sort_keys", "ensure_ascii"}
                                 or not isinstance(keyword.value, ast.Constant) for keyword in node.keywords):
                return []
            if not json_load and node.func.attr not in {"keys", "items", "values", "get"}:
                return []
        else:
            return []
    return targets


def _read_targets(command: str) -> list[str]:
    if not isinstance(command, str):
        return []
    chunk = _chunked_dispatch_read(command)
    if chunk:
        return [chunk[0]]
    python = re.fullmatch(r"python3 - <<['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?\n(.*?)\n\1\s*", command, re.S)
    if python:
        try:
            return _python_read_targets(python[2])
        except (SyntaxError, TypeError, ValueError):
            return []
    hashed_read = re.fullmatch(r"(?:sha256sum|shasum -a 256) ([^\s;&|<>]+) && cat \1", command)
    if hashed_read:
        return [hashed_read[1]]
    read_then_hash = re.fullmatch(r"cat ([^\s;&|<>$`]+)(?:;| &&) (?:sha256sum|shasum -a 256) \1", command)
    if read_then_hash:
        return [read_then_hash[1]]
    verified_read = re.fullmatch(
        r'packet=([^\s;&|<>$`]+); actual=\$\(sha256sum "\$packet" \| cut -d \' \' -f 1\); '
        r'if \[ "\$actual" != [0-9a-f]{64} \]; then printf \'SHA256_MISMATCH %s\\n\' "\$actual"; '
        r'exit 2; fi; printf \'SHA256_OK %s\\n\' "\$actual"; cat "\$packet"', command)
    if verified_read:
        return [verified_read[1]]
    checked_read = re.fullmatch(
        r"actual=\$\((?:sha256sum|shasum -a 256) ([^\s;&|<>$`\"'\\]+) \| awk '\{print \$1\}'\); "
        r'if \[ (\\?"?)\$actual\2 != (\\?"?)[0-9a-f]{64}\3 \]; then '
        r"printf 'SHA256 mismatch: %s\\{1,2}n' (\\?\"?)\$actual\4; exit 2; fi; cat \1", command)
    if checked_read:
        return [checked_read[1]]
    status_suffix = re.fullmatch(r"(.+?)(?:;| &&) git status --short", command, re.S)
    if status_suffix:
        return _read_targets(status_suffix[1])
    if any(value in command for value in ("$(", "`", "<", ">", "|", "&")):
        return []
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";")
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = list(lexer)
        if tokens[:1] == ["for"]:
            parts, part = [], []
            for token in tokens:
                if token == ";":
                    parts.append(part)
                    part = []
                else:
                    part.append(token)
            parts.append(part)
            if len(parts) != 4 or len(parts[0]) < 4 or parts[0][2] != "in":
                return []
            variable = "$" + parts[0][1]
            if (len(parts[1]) != 4 or parts[1][:2] != ["do", "printf"] or parts[1][3] != variable
                    or parts[2] != ["cat", variable] or parts[3] != ["done"]):
                return []
            return parts[0][3:]
        if ";" in tokens and "$" not in command:
            parts, part = [], []
            for token in tokens:
                if token == ";":
                    parts.append(part)
                    part = []
                else:
                    part.append(token)
            parts.append(part)
            if not parts[-1]:
                return []
            if _listing_command(shlex.join(parts[-1])):
                parts = parts[:-1]
            reads = [_read_targets(shlex.join(part)) for part in parts]
            return [target for row in reads for target in row] if reads and all(reads) else []
        if not tokens or "$" in command:
            return []
        if tokens[0] == "cat" and len(tokens) > 1 and all(not arg.startswith("-") for arg in tokens[1:]):
            return tokens[1:]
        if (len(tokens) > 3 and tokens[:2] == ["sed", "-n"]
                and re.fullmatch(r"[0-9]+(?:,[0-9]+)?p", tokens[2])):
            return tokens[3:]
        return []
    except ValueError:
        return []


def _allowed_instruction_paths(root: Path, assigned: list[str]) -> set[Path]:
    """Allow only repository instructions on the run or an explicitly assigned path's ancestor chain."""
    repository = root.parent.parent.resolve()
    directories = {root.resolve(), root.parent.resolve(), repository}
    for source in assigned:
        if not isinstance(source, str) or not source.strip() or "://" in source:
            continue
        path = Path(source)
        try:
            resolved = (path if path.is_absolute() else repository / path).resolve()
        except OSError:
            continue
        if not resolved.is_relative_to(repository):
            continue
        if resolved.name == "AGENTS.md":
            directories.add(resolved.parent)
        directory = resolved if resolved.is_dir() else resolved.parent
        while directory.is_relative_to(repository):
            directories.add(directory)
            if directory == repository:
                break
            directory = directory.parent
    candidates = {directory / "AGENTS.md" for directory in directories}
    # A link to another applicable instruction file is safe; a link to archived analysis is not.
    return {path.resolve() for path in candidates if path.resolve() in candidates}


def _read_output_prefixes(trace: dict, assigned: list[str], root: Path | None) -> set[tuple[str, ...]]:
    if root is None:
        return set()
    calls, outputs = set(), set()
    for index, row in enumerate(trace.get("tool_trace", [])):
        if not isinstance(row, dict):
            continue
        operations = _tool_operations(row)
        safe = bool(operations)
        for name, arguments in operations:
            if name == "mcp__codex_app__read_thread":
                safe = safe and "codex://threads/" + str(arguments.get("threadId")) in assigned
            elif name == "exec_command":
                targets = _read_targets(arguments.get("cmd"))
                cwd = Path(arguments.get("workdir", root.parent.parent))
                resolved = [Path(target) if Path(target).is_absolute() else cwd / target for target in targets]
                receipts = root / "activation_receipts.json"
                instructions = json.loads(receipts.read_text()) if receipts.is_file() else {}
                allowed_instructions = _allowed_instruction_paths(root, assigned)
                safe = safe and bool(targets) and all(
                    not (path.resolve().parent == root and path.name in instructions)
                    and path.resolve() != Path(trace["spawn"]["dispatch_file"]).resolve()
                    and ((path.resolve().parent == root and path.is_file()) or str(path) in assigned
                         or path.name == "AGENTS.md" and path.resolve() in allowed_instructions and path.is_file())
                    for path in resolved)
            elif name not in {"mcp__codex_apps__atlassian_getjiraissue", "mcp__codex_apps__atlassian_executeread",
                              "mcp__codex_apps__atlassian_discover", "mcp__codex_apps__atlassian_searchjiraissuesusingjql"}:
                safe = False
        if safe:
            outputs.update({("tool_trace", str(index), "result"), ("tool_trace", str(index), "output")})
            if row.get("call_id"):
                calls.add(row["call_id"])
        if row.get("type") in {"function_call_output", "custom_tool_call_output"} and row.get("call_id") in calls:
            outputs.add(("tool_trace", str(index), "output"))
    return outputs


def observed_dispatch_binding(trace: dict, root: Path) -> dict:
    bindings = json.loads((root / "role_bindings.json").read_text())
    role = worker_binding(bindings, trace["spawn"]["agent"])
    for row in reversed(trace.get("tool_trace", [])):
        for name, arguments in _tool_operations(row):
            if name != "exec_command":
                continue
            cwd = Path(arguments.get("workdir", bindings["execution_repository"]))
            for target in _read_targets(arguments.get("cmd")):
                path = Path(target) if Path(target).is_absolute() else cwd / target
                path = path.resolve()
                expected = trace["spawn"].get("dispatch_file")
                if (path.parent != root.resolve() or not path.is_file()
                        or expected and path != Path(expected).resolve()):
                    continue
                proof = {"dispatch_file": str(path), "dispatch_file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                         "binding_agent": role, "dispatch_proof_source": "provider_instruction_read"}
                candidate = {**trace, "spawn": {**trace["spawn"], **proof}}
                content = _verified_dispatch_content(candidate)
                if content and row.get("call_id"):
                    for output in trace.get("tool_trace", []):
                        if (output.get("type") in {"function_call_output", "custom_tool_call_output"}
                                and output.get("call_id") == row["call_id"]
                                and any(_dispatch_read_output(arguments.get("cmd", ""), content) in value
                                        for _, value in _trace_strings({"tool_trace": [output]}))):
                            return proof
    return {}


def _instruction_contents(trace: dict, root: Path | None, assigned: list[str]) -> dict[str, dict[str, list[str]]]:
    """Return only instruction text paired with its authenticated provider read."""
    if root is None:
        return {}
    receipts = root / "activation_receipts.json"
    bindings_path = root / "role_bindings.json"
    contents: dict[str, dict[str, list[str]]] = {}

    def record_paired_output(row: dict, expected: str, kind: str) -> None:
        call_id = row.get("call_id")
        if not call_id or row.get("type") not in {"function_call", "custom_tool_call"}:
            return
        for output in trace.get("tool_trace", []):
            if (not isinstance(output, dict)
                    or output.get("type") not in {"function_call_output", "custom_tool_call_output"}
                    or output.get("call_id") != call_id):
                continue
            if any(expected in value for _, value in _trace_strings({"tool_trace": [output]})):
                contents.setdefault(call_id, {}).setdefault(kind, []).append(expected)

    if trace.get("spawn") and receipts.is_file() and bindings_path.is_file():
        role, receipt_rows = None, ()
        try:
            bindings = json.loads(bindings_path.read_text())
            role = worker_binding(bindings, trace["spawn"]["agent"])
            receipt_rows = json.loads(receipts.read_text()).items()
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            pass
        if role is None:
            receipt_rows = ()
        for name, receipt in receipt_rows:
            if not isinstance(receipt, dict) or receipt.get("agent") != role:
                continue
            candidate = {**trace, "spawn": {**trace["spawn"], "dispatch_file": str(root / name),
                "dispatch_file_sha256": receipt.get("sha256"), "binding_agent": receipt.get("agent")}}
            content = _verified_dispatch_content(candidate)
            if not content:
                continue
            dispatch_path = (root / name).resolve()
            for row in trace.get("tool_trace", []):
                if not isinstance(row, dict):
                    continue
                for tool, arguments in _tool_operations(row):
                    if tool != "exec_command":
                        continue
                    command = arguments.get("cmd", "")
                    targets = _read_targets(command)
                    chunk = _chunked_dispatch_read(command)
                    if chunk:
                        targets.append(chunk[0])
                    cwd = Path(arguments.get("workdir", root.parent.parent))
                    if any((Path(target) if Path(target).is_absolute() else cwd / target).resolve() == dispatch_path
                           for target in targets):
                        record_paired_output(row, _dispatch_read_output(command, content), "dispatch")
    for row in trace.get("tool_trace", []):
        if not isinstance(row, dict):
            continue
        for name, arguments in _tool_operations(row):
            if name != "exec_command":
                continue
            operation = {"tool": name, "arguments": arguments}
            cwd = Path(arguments.get("workdir", root.parent.parent))
            for target in _ancestor_instruction_reads(operation, root, input_paths=assigned):
                path = Path(target)
                path = path if path.is_absolute() else cwd / path
                try:
                    if path.is_file():
                        record_paired_output(row, path.read_text(), "ancestor")
                except (OSError, UnicodeError):
                    continue
    return contents


def _ancestor_instruction_reads(row: dict, root: Path, *, include_probes: bool = False,
                                input_paths: list[str] | None = None) -> list[str]:
    allowed = _allowed_instruction_paths(root, input_paths or [])
    reads = []
    for name, arguments in _tool_operations(row):
        if name != "exec_command":
            continue
        command = arguments.get("cmd", "")
        if not isinstance(command, str):
            continue
        try:
            lexer = shlex.shlex(command, posix=True, punctuation_chars=";\n")
            lexer.whitespace_split = True
            lexer.whitespace = " \t\r"
            lexer.commenters = ""
            statements, current = [], []
            for token in lexer:
                if token and all(char in ";\n" for char in token):
                    if current:
                        statements.append(current)
                        current = []
                else:
                    current.append(token)
            if current:
                statements.append(current)
        except ValueError:
            continue
        targets, index = [], 0
        # Unknown shell syntax remains audited; consume only literal reads and instruction loops.
        while index < len(statements):
            statement = statements[index]
            if len(statement) >= 4 and statement[0] == "for" and statement[2] == "in":
                variable = "$" + statement[1]
                end = next((i for i in range(index + 1, len(statements)) if statements[i] == ["done"]), None)
                if end is None:
                    break
                tail = [token for part in statements[index + 1:end + 1] for token in part]
                conditions = (["[", "-f", variable, "]"], ["test", "-f", variable])
                suffix = ["cat", variable, "fi", "done"]
                valid = include_probes and any(
                    tail == ["do", "if", *condition, "then", *output, "fi", "done"]
                    for argument in (variable, '"' + variable + '"')
                    for condition in (["[", "-f", argument, "]"], ["test", "-f", argument])
                    for output in (["printf", "%s\\n", argument], ["echo", argument]))
                for condition in conditions:
                    prefix = ["do", "if", *condition, "then"]
                    if tail[:len(prefix)] == prefix and tail[-len(suffix):] == suffix:
                        marker = tail[len(prefix):-len(suffix)]
                        valid = (not marker or marker[0] in {"echo", "printf"}
                                 and any(part in (marker, ["then", *marker])
                                         for part in statements[index + 1:end])
                                 and (marker[0] != "printf" or len(marker) >= 2
                                      and not marker[1].startswith("-") and "%n" not in marker[1])
                                 and not any(token in {"&", "&&", "|", "||", "<", ">"}
                                             or any(char in token for char in "`<>")
                                             or "$" in token.replace(variable, "") for token in marker))
                if not valid or not re.fullmatch(r"[A-Za-z_]\w*", statement[1]):
                    break
                targets.extend(statement[3:])
                index = end + 1
            elif statement[:1] == ["ls"] and _listing_command(shlex.join(statement)):
                index += 1
            else:
                # Suppressing missing optional instruction errors does not read historical content.
                for redirect in (["2>/dev/null"], ["2>", "/dev/null"]):
                    if statement[-len(redirect):] == redirect:
                        statement = statement[:-len(redirect)]
                        break
                selected = _read_targets(shlex.join(statement))
                if not selected:
                    break
                targets.extend(selected)
                index += 1
        cwd = Path(arguments.get("workdir", root.parent.parent))
        for target in targets:
            if any(char in target for char in "$`*"):
                continue
            path = Path(target)
            resolved = (path if path.is_absolute() else cwd / path).resolve()
            if resolved in allowed:
                reads.append(target)
    return reads


def context_trace_errors(trace: dict[str, object], *, details: list[dict] | None = None,
                         input_paths: tuple[str, ...] = (), artifact_root: Path | None = None) -> list[str]:
    """Reject unassigned historical input and all historical writes, preserving instruction echoes."""
    if not isinstance(trace, dict):
        return ["tool_trace_invalid"]
    errors: list[str] = []
    if str(trace.get("context_conformance", "")).strip().lower() in {"fail", "failed", "blocked"}:
        errors.append("context_conformance_failed")
    dispatch_content = _verified_dispatch_content(trace)
    assigned, root = list(input_paths), artifact_root
    if dispatch_content:
        assignment = json.loads(dispatch_content.split("\nTyped assignment:\n", 1)[1])
        assigned = list(assignment.get("input_paths", []))
        packet = json.loads(dispatch_content.split("\n", 2)[1])
        for row in packet.get("run_input_manifest", {}).get("inputs", []):
            locator = str(row.get("Source or path", ""))
            expected_use = str(row.get("Expected use", "")).lower()
            if (re.fullmatch(r"codex://threads/[0-9a-fA-F-]{36}", locator)
                    and not any(value in expected_use for value in ("do not read", "without reading", "preserve only"))):
                assigned.append(locator)
        root = Path(trace["spawn"]["dispatch_file"]).resolve().parent
    listing_reads = {}
    listings = _listing_outputs(trace, read_prefixes=listing_reads, cwd=root.parent.parent if root else None)
    source_outputs = _read_output_prefixes(trace, assigned, root) if dispatch_content else []
    instruction_contents = _instruction_contents(trace, root, assigned) if root else {}
    reads = {row.get("call_id") for row in trace.get("tool_trace", [])
             if isinstance(row, dict) and row.get("call_id") and _authorized_read(row, assigned)}
    instruction_reads = {row.get("call_id"): _ancestor_instruction_reads(
                         row, root, include_probes=True, input_paths=assigned)
                         for row in trace.get("tool_trace", []) if root and isinstance(row, dict) and row.get("call_id")
                         and row.get("type") in {"function_call", "custom_tool_call"}}
    for path, value in _trace_strings(trace):
        if any(path[:len(prefix)] == prefix for prefix in source_outputs):
            continue
        candidate = value
        for prefix, content in listing_reads.items():
            if path[:len(prefix)] == prefix and candidate.startswith(content):
                candidate = content + "\n".join(line for line in candidate[len(content):].splitlines()
                                                 if not THOUGHT_PATH.fullmatch(line))
                break
        output = path[:1] == ("tool_trace",) and "output" in path[2:]
        row = trace["tool_trace"][int(path[1])] if path[:1] == ("tool_trace",) and len(path) > 1 and str(path[1]).isdigit() else {}
        call_contents = instruction_contents.get(row.get("call_id"), {})
        ancestor_instruction_output = output and bool(call_contents.get("ancestor"))
        if output:
            for content in call_contents.get("dispatch", []) + call_contents.get("ancestor", []):
                candidate = candidate.replace(content, "")
        listing = any(path[:len(prefix)] == prefix for prefix in listings)
        if _authorized_read(row, assigned) or (row.get("type") == "function_call_output" and row.get("call_id") in reads):
            for source in assigned:
                candidate = re.sub(r"(?<![\w./-])" + re.escape(source) + r"(?![\w./-])", "", candidate)
        if root:
            instructions = (instruction_reads.get(row.get("call_id"), []) if output
                            else _ancestor_instruction_reads(row, root, include_probes=True, input_paths=assigned))
            for instruction in instructions:
                candidate = re.sub(r"(?<![\w./-])" + re.escape(instruction) + r"(?![\w./-])", "", candidate, count=1)
        for label, pattern in FORBIDDEN_CONTEXT_PATTERNS:
            checked = candidate if ancestor_instruction_output or label == "archived_artifact" else value
            if label == "archived_artifact" and listing:
                continue
            match = pattern.search(checked)
            if match:
                errors.append(f"forbidden_context_reference:{label}")
                if details is not None:
                    details.append({"error": errors[-1], "trace_path": list(path), "reference": match.group().strip()})
                break
        if root and not listing:
            if output:
                # Directory headings are labels; do not reinterpret the colon as a different work-item ID.
                candidate = re.sub(r"(?m)^(" + re.escape(str(root)) + "|" +
                                   re.escape(".thoughts/" + root.name) + r"):$", r"\1", candidate)
            for reference in THOUGHT_PATH.findall(candidate):
                relative = reference.split(".thoughts/", 1)[1]
                if output and relative == root.name + ".":
                    relative = root.name  # A sentence-ending period in output is not a different work-item ID.
                if relative.split("/", 1)[0] != root.name or "/runs/" in relative:
                    errors.append("forbidden_context_reference:archived_artifact")
                    if details is not None:
                        detail = {"error": errors[-1], "trace_path": list(path), "reference": reference}
                        if detail not in details:
                            details.append(detail)
    return list(dict.fromkeys(errors))


def planning_permission_errors(trace: dict) -> list[str]:
    """Planning checks require explicit user authorization, independent of delegated objectives."""
    content = _verified_dispatch_content(trace)
    if not content:
        return []
    packet = json.loads(content.split("\n", 2)[1])
    current = json.loads(Path(packet["finalization_packet"]).read_text())
    recorded = current.get("identity", {}).get("Lifecycle")
    lifecycle = packet.get("lifecycle") or recorded
    errors = []
    if packet.get("lifecycle") and recorded != lifecycle:
        errors.append("worker_lifecycle_mismatch:expected=" + lifecycle + ";received=" + str(recorded))
    if lifecycle not in {"planning", "remediation"}:
        return errors + ["worker_lifecycle_required"]
    if lifecycle != "planning":
        return errors
    artifact_root = Path(trace["spawn"]["dispatch_file"]).resolve().parent
    repository_root = artifact_root.parent.parent
    contract = packet.get("worker_contract") or {}
    allowed_writes = {Path(contract[key]).resolve() for key in ("output", "result", "implementation_plan")
                      if isinstance(contract.get(key), str)}
    if contract.get("result_response") == "strict_json_final_answer":
        allowed_writes.difference_update(Path(contract[key]).resolve() for key in ("output", "result")
                                        if isinstance(contract.get(key), str))
    authorized = set()
    for row in packet.get("run_input_manifest", {}).get("inputs", []):
        if (row.get("Classification") == "execution authorization" and row.get("Status") == "Approved"
                and row.get("Authority") == "User"):
            operations = row.get("Authorized operations", [])
            if isinstance(operations, list) and all(isinstance(value, str) and value in {"test_run", "build_run"}
                                                    for value in operations):
                authorized.update(operations)
    for row in trace.get("tool_trace", []):
        for tool, arguments in _tool_operations(row):
            if tool == "apply_patch":
                patch = arguments.get("patch")
                targets = re.findall(r"^\*\*\* (?:(?:Add|Update|Delete) File|Move to): (.+)$", patch or "", re.M)
                if not isinstance(patch, str) or not targets:
                    errors.append("planning_write_targets_unavailable")
                    continue
                for target in targets:
                    path = Path(target)
                    path = path if path.is_absolute() else repository_root / path
                    resolved = path.resolve()
                    if not resolved.is_relative_to(artifact_root):
                        errors.append("planning_source_write_not_authorized")
                        break
                    if resolved not in allowed_writes:
                        errors.append("planning_write_target_not_assigned")
                        break
                continue
            if tool != "exec_command":
                continue
            command = arguments.get("cmd", "")
            if not isinstance(command, str):
                errors.append("planning_command_invalid")
                continue
            try:
                tokens = shlex.split(command)
                if len(tokens) == 3 and Path(tokens[0]).name in {"bash", "sh", "zsh"} and tokens[1] in {"-lc", "-c"}:
                    command = tokens[2]
                lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|<>\n")
                lexer.whitespace = " \t\r"
                lexer.whitespace_split = True
                parts, part = [], []
                for token in lexer:
                    if token in {";", "&", "|", "&&", "||", "\n"}:
                        parts.append(part)
                        part = []
                    else:
                        part.append(token)
                parts.append(part)

                def authorized_write_target(target):
                    if target in {"/dev/null", "/dev/stdout", "/dev/stderr"}:
                        return True
                    path = Path(target)
                    cwd = Path(arguments.get("workdir") or repository_root)
                    if not cwd.is_absolute():
                        cwd = repository_root / cwd
                    resolved = (path if path.is_absolute() else cwd / path).resolve()
                    if not resolved.is_relative_to(artifact_root):
                        return False
                    return resolved in allowed_writes

                for part in parts:
                    if not part:
                        continue
                    name = Path(part[0]).name
                    # shortcut: audit literal embedded writes; opaque external scripts need a provider sandbox.
                    if name in {"python", "python3", "node", "ruby"} and re.search(
                            r"\.write_(?:text|bytes)\s*\(|\bopen\s*\([^)]*,\s*['\"](?:w|a|x)"
                            r"|\b(?:os|shutil)\.(?:remove|unlink|mkdir|makedirs|rmdir|rename|replace|"
                            r"copy|copy2|copyfile|copytree|move|rmtree)\s*\(", command):
                        errors.append("planning_source_write_not_authorized")
                    for index, token in enumerate(part[:-1]):
                        if token in {">", ">>", ">|", "&>", "&>>", ">&"}:
                            target = part[index + 1]
                            if not (token == ">&" and target in {"1", "2"}) and not authorized_write_target(target):
                                errors.append("planning_source_write_not_authorized")
                    operands = [token for token in part[1:] if not token.startswith("-") and token != "--"]
                    if name in {"tee", "touch", "mkdir", "rmdir", "rm"}:
                        targets = [target for target in operands if target != "-"]
                    elif name in {"cp", "install", "ln"}:
                        targets = operands[-1:]
                    elif name == "mv":
                        targets = operands
                    elif (name in {"sed", "perl"} and any(token == "-i" or token.startswith("-i") for token in part[1:])
                          or name == "git" and len(part) > 1 and part[1] in {
                              "apply", "checkout", "switch", "reset", "clean", "stash", "am", "merge", "rebase",
                              "cherry-pick"}):
                        errors.append("planning_source_write_not_authorized")
                        targets = []
                    else:
                        targets = []
                    if any(not authorized_write_target(target) for target in targets):
                        errors.append("planning_source_write_not_authorized")
                    operation = None
                    if name in {"bazel", "bazelisk", "go", "npm", "pnpm", "yarn", "make"}:
                        action = next((arg for arg in part[1:] if not arg.startswith("-")), "")
                        if action == "run" and len(part) > 2:
                            action = part[2]
                        if action in {"test", "build"}:
                            operation = "test_run" if action == "test" else "build_run"
                    elif name in {"pytest", "pytest-3"} or (name in {"python", "python3"}
                            and len(part) > 2 and part[1] == "-m" and part[2] in {"pytest", "unittest"}):
                        operation = "test_run"
                    if operation and operation not in authorized:
                        errors.append("planning_operation_not_authorized:" + operation)
            except (ValueError, TypeError):
                continue
    return list(dict.fromkeys(errors))


def trace_errors(trace: dict[str, object], *, require_freshness: bool = False,
                 context_details: list[dict] | None = None) -> list[str]:
    if not isinstance(trace, dict):
        return ["tool_trace_invalid"]
    if not isinstance(trace.get("events", []), list):
        return ["runtime_event_invalid"]
    launch_errors = trace.get("launch_errors", [])
    if not isinstance(launch_errors, list) or any(not isinstance(error, str) for error in launch_errors):
        return ["worker_launch_errors_invalid"]
    errors: list[str] = list(launch_errors)
    response_errors = trace.get("worker_response_errors", [])
    if not isinstance(response_errors, list) or any(not isinstance(error, str) for error in response_errors):
        return ["worker_response_errors_invalid"]
    errors.extend(response_errors)
    spawn = trace.get("spawn", {})
    if not isinstance(spawn, dict):
        return ["spawn_trace_invalid"]
    if require_freshness:
        dispatch = trace.get("last_dispatch_at")
        try:
            if not isinstance(dispatch, str) or datetime.fromisoformat(dispatch.replace("Z", "+00:00")).tzinfo is None:
                raise ValueError
        except ValueError:
            errors.append("worker_trace_dispatch_required")
        if not isinstance(trace.get("tool_trace"), list):
            errors.append("worker_tool_trace_required")
        if not any(isinstance(event, dict) and event.get("action") == "fan_in"
                   and event.get("provider_status") == "completed" for event in trace.get("events", [])):
            errors.append("worker_fan_in_guard_receipt_required")
    if spawn.get("activation_message_conformance") == "failed":
        errors.append("activation_message_mismatch")
    observed_role = spawn.get("observed_agent_role")
    observed_path = spawn.get("observed_agent_path")
    delivered = bool(observed_role or observed_path or spawn.get("activation_packet_delivered"))
    if spawn.get("dispatch_file"):
        delivered = False
        try:
            path = Path(spawn["dispatch_file"]).resolve()
            proof = observed_dispatch_binding(trace, path.parent)
            delivered = (proof.get("dispatch_file") == str(path)
                         and proof.get("dispatch_file_sha256") == spawn.get("dispatch_file_sha256"))
            if observed_role and observed_role != spawn.get("binding_agent", spawn.get("agent")):
                errors.append("provider_binding_role_mismatch")
            if observed_path and delivered:
                contract = json.loads(path.read_text().split("\n", 2)[1])
                if Path(observed_path).resolve() != Path(contract["definition"]).resolve():
                    errors.append("provider_binding_path_mismatch")
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            pass
    if not delivered:
        errors.append("provider_binding_not_delivered")
    elif require_freshness and spawn.get("dispatch_file"):
        try:
            root = Path(spawn["dispatch_file"]).resolve().parent
            bindings = json.loads((root / "role_bindings.json").read_text())
            errors.extend(result_artifact_errors(trace, bindings, root,
                                                worker_binding(bindings, spawn["agent"])))
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            errors.append("worker_result_artifact_invalid:" + str(error))
    for event in trace.get("events", []):
        if not isinstance(event, dict) or "action" not in event:
            errors.append("runtime_event_invalid")
            continue
        error = transition_error(str(event["action"]), str(event.get("provider_status", "")))
        if error:
            errors.append(error)
        if event.get("action") == "fan_in" and event.get("guard_result") == "blocked":
            errors.append("worker_fan_in_rejected")
    failure = trace.get("analytical_failure", {})
    if isinstance(failure, dict) and failure.get("requested") and not failure.get("artifact_created"):
        if failure.get("evidence_artifact_required"):
            errors.append("analytical_failure_artifact_absent")
    errors.extend(planning_permission_errors(trace))
    errors.extend(context_trace_errors(trace, details=context_details))
    return list(dict.fromkeys(errors))


TECHOPS_CHECKS = {"issue_scope", "history_reconciliation", "plan_dependencies", "regression_fixture"}

THOUGHT_PATH = re.compile(r"(?:/[A-Za-z0-9_.-]+)*/?\.thoughts/[^\s\"'<>`\\;,)}\]]+")
