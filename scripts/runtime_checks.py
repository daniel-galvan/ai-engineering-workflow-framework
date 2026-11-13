#!/usr/bin/env python3
"""Worker binding, context, trace, and transition validation without CLI orchestration."""

from __future__ import annotations

import ast
import io
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
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


def prepared_package_errors(root: Path, *, check_parent_context: bool = True,
                            expected_package_root: Path | None = None,
                            package_content_root: Path | None = None,
                            context_details: list | None = None) -> list[str]:
    """Reject package, lifecycle, profile or parent-context drift from the prepared run."""
    try:
        manifest = json.loads((root / "role_bindings.json").read_text())
        if manifest.get("run_id"):
            current = json.loads((root / "finalization_packet.json").read_text())
            if current.get("identity", {}).get("Run ID") != manifest["run_id"]:
                return ["prepared_run_identity_mismatch"]
            if current.get("work_item", {}).get("ID") != root.name:
                return ["prepared_work_item_mismatch"]
            inputs = manifest.get("run_input_manifest", {})
            if inputs.get("path") and inputs.get("sha256"):
                copied = current.get("run_input_manifest", {})
                if (any(copied.get(key) != inputs[key] for key in ("path", "sha256"))
                        or hashlib.sha256(Path(inputs["path"]).read_bytes()).hexdigest() != inputs["sha256"]):
                    return ["prepared_input_manifest_mismatch"]
        package = manifest.get("framework_package")
        expected_root = expected_package_root.resolve() if expected_package_root is not None else ROOT
        content_root = package_content_root or expected_root
        if package is not None and (Path(package["root"]).resolve() != expected_root
                or package["plugin_sha256"] != hashlib.sha256((content_root / ".codex-plugin/plugin.json").read_bytes()).hexdigest()):
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
            return prepared_parent_context_errors(root, manifest, details=context_details)
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
        if str(observation.get("Dispatch consumption evidence", "")).startswith("native-message:"):
            saved = json.loads(Path(bindings["runtime_evidence"]["ledger"]).read_text())
            origin = trace.get("delivery_ledger", {})
            if (any(origin.get(key) != saved.get(key) for key in
                    ("provider_session", "parent_thread_id", "run_started_at"))
                    or origin.get("identity_sessions", []) != saved.get("identity_sessions", [])
                    or saved.get("thread_mappings", {}).get(handle) != trace.get("thread_id")):
                errors.append("worker_dispatch_consumption_origin_mismatch:" + worker)
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
    retrieval = trace.get("trace_retrieval")
    if _is_codex_session_path(retrieval) and _verified_trace_retrieval_path(trace) is None:
        return ["worker_trace_session_mismatch:" + role]
    receipt = trace.get("result_artifact", {})
    try:
        root = root.resolve()
        try:
            from worker_runtime_evidence import worker_final_response, worker_response_value
        except ModuleNotFoundError:
            from scripts.worker_runtime_evidence import worker_final_response, worker_response_value
        response = worker_final_response(Path(trace["trace_retrieval"]), trace["last_dispatch_at"],
                                         trace["status_observation"]["Observed at"],
                                         trace["status_observation"].get("Latest turn started at"),
                                         turn_id=trace["status_observation"].get("Latest turn ID"),
                                         packet_path=root / "finalization_packet.json", agent=role,
                                         builder=Path(contract["response_builder"]) if contract.get("response_builder") else None)
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
        envelope = worker_response_value(response, Path(trace["trace_retrieval"]))
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
        if (role == "reviewer" and bindings.get("lifecycle") == "remediation"
                and bindings.get("playbook") in {"techops_issue_remediation", "feature_delivery"}
                and re.search(r"^Disposition:\s*accepted\s*$", envelope["output"], re.M)):
            try:
                from review_evidence import review_candidate_metadata_errors
            except ModuleNotFoundError:
                from scripts.review_evidence import review_candidate_metadata_errors
            errors = review_candidate_metadata_errors(envelope["output"])
            if errors:
                return ["worker_review_candidate_metadata_invalid:" + ";".join(errors)]
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
    candidate = (packet.get("worker_contract") or {}).get("recovered_candidate")
    if candidate:
        files = candidate.get("snapshot_files")
        if (candidate.get("status") != "unaccepted" or not isinstance(files, dict) or not files
                or not set(files).issubset(assignment.get("input_paths", []))):
            raise ValueError("recovered_candidate_assignment_required")
        root = Path(packet["finalization_packet"]).resolve().parent
        for name, digest in files.items():
            path = Path(name)
            if (not path.is_absolute() or not path.resolve().is_relative_to(root)
                    or not path.is_file() or path.is_symlink() or not isinstance(digest, str)
                    or hashlib.sha256(path.read_bytes()).hexdigest() != digest):
                raise ValueError("recovered_candidate_snapshot_changed")
        receipts_path = root / "activation_receipts.json"
        try:
            receipts = json.loads(receipts_path.read_text()) if receipts_path.exists() else {}
            previous = any(row.get("run_id") == packet["run_id"] and row.get("agent") == packet["agent"]
                           for row in receipts.values())
            if not previous:
                checkout = packet["coordinator_execution"]["source_checkout"]
                def git(*args):
                    return subprocess.run(["git", "-C", checkout, "-c", "core.fsmonitor=false", *args],
                                          check=True, capture_output=True, text=True, timeout=30).stdout.strip()
                if candidate.get("source_already_present") is True:
                    try:
                        from recovery_candidate import verify_checkout_snapshot
                    except ModuleNotFoundError:
                        from scripts.recovery_candidate import verify_checkout_snapshot
                    try:
                        verify_checkout_snapshot(Path(checkout), candidate["baseline_revision"], candidate["files"])
                    except (ValueError, KeyError, TypeError) as error:
                        raise ValueError("recovered_candidate_source_checkout_changed") from error
                elif git("rev-parse", "HEAD") != candidate["baseline_revision"] or git("status", "--porcelain"):
                    raise ValueError("recovered_candidate_source_checkout_changed")
        except (OSError, subprocess.SubprocessError, KeyError, TypeError, AttributeError) as error:
            raise ValueError("recovered_candidate_source_checkout_unverified") from error
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
    if len(message) > 12000:
        commands = []
        for start in range(0, len(message), 6000):
            literal_path = json.dumps(str(path.resolve()), ensure_ascii=False)
            code = f'print(open({literal_path}).read()[{start}:{min(start + 6000, len(message))}],end="")'
            commands.append(shlex.join([sys.executable, "-c", code]))
        reading = ("Read the complete file in order with each separate literal command below; "
                   "do not omit or change any part:\n" + "\n".join(commands) + "\n")
    else:
        reading = f"Read it with this separate literal command: {shlex.join(['cat', str(path.resolve())])}\n"
    file_identity = (f"Read the complete activation instructions and typed assignment at {path.resolve()}.\n"
                     if len(message) > 12000 else "")
    return (packet["required_prefix"] + "\n"
            + "First step: verify the file; this bootstrap is self-contained. Use only this chat and current-run "
              "artifacts, and verified worker chats created by this run and assigned to you. MEMORY.md may be read as background guidance only. Current user instructions and current-run "
              "evidence take precedence. Memory alone must not establish a task finding or justify an implementation "
              "decision. Verify task-specific memory claims against currently authorized sources. References in memory "
              "do not authorize opening previous chats, sessions, or runs. "
              "Do not include or rely on unrelated chats, sessions, or other memory files unless the current user "
              "explicitly identifies and authorizes the exact source. Verify current claims against current evidence. "
              "Do not search the artifact directory or archives.\n"
            + f"Role: {packet['agent']}; model/effort: {packet['model']} / {packet['effort']}.\n"
            + f"Run ID: {packet['run_id']}.\n"
            + file_identity
            + f"Verify its SHA256 is {digest}; stop on mismatch.\n"
            + "If this same worker already read this same file and SHA256 completely and still has it in context, "
              "reuse that read and continue the assignment. Otherwise read it fully as follows.\n"
            + reading
            + "Use separate tool calls for verification and the complete instruction read.\n"
            + f"Set max_output_tokens to at least {6000 if len(message) > 12000 else len(message.encode())}"
              "; truncated output is not delivery.\n"
            + "Please continue in this same turn through the full typed assignment. A bootstrap acknowledgment is not completion. "
              "The file is the operative role, input, output and policy contract. Use its full instructions. "
              "Do not rerun Coordinator initialization.")


def techops_conformance_errors(path: Path, run_id: str, plan_hash: str) -> list[str]:
    """Check the Implementer's current-run pre-edit file mapping."""
    if not path.is_file() or path.is_symlink():
        return ["techops_conformance_record_required"]
    try:
        record = json.loads(path.read_text())
    except (OSError, ValueError):
        return ["techops_conformance_record_invalid"]
    if not isinstance(record, dict) or record.get("run_id") != run_id or record.get("plan_sha256") != plan_hash:
        return ["techops_conformance_identity_mismatch"]
    entries = record.get("files")
    if not isinstance(entries, list) or not entries:
        return ["techops_conformance_files_required"]
    fields = ("path", "plan_step", "reuse", "change", "validation")
    if any(not isinstance(row, dict) or any(not isinstance(row.get(field), str) or not row[field].strip()
                                             for field in fields) for row in entries):
        return ["techops_conformance_file_mapping_incomplete"]
    return []


def delivery_start_errors(path: Path, implementer_handle: str, provider_status: str, *,
                          require_conformance: bool = True) -> list[str]:
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
            if playbook == "techops_issue_remediation" and require_conformance:
                errors.extend(techops_conformance_errors(path.parent / "implementation_conformance.json",
                                                         identity["Run ID"], reentry["Approved plan SHA256"]))
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
        required = {"implement": "implementer"}
        for role in ("implementer", "reviewer", "tester", "documenter"):
            if not manifest.get("bindings", {}).get(role) or not manifest.get("worker_contracts", {}).get(role):
                return ["delivery_worker_binding_required:" + role]
        packet = json.loads(path.read_text())
        run_id = packet["identity"]["Run ID"]
        selected, handles = {}, []
        inventory_at = timestamp(inventory["Observed at"])
        for worker, role in required.items():
            candidates = []
            for row in current["events"]:
                if (row.get("Operation") != "spawn_agent" or row.get("Provider handle") not in statuses
                        or statuses[row["Provider handle"]] not in ACTIVE_STATUSES
                        or timestamp(row["Last dispatch at"]) > inventory_at):
                    continue
                proof = live_dispatch_binding(row, role, path.parent, run_id, inventory["Observed at"])
                if proof:
                    candidates.append((row, proof))
            if len(candidates) != 1:
                return ["delivery_worker_live_activation_required:" + worker]
            dispatch, proof = candidates[0]
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
                "dispatch_file": proof.get("dispatch_file"),
                "dispatch_file_sha256": proof.get("dispatch_file_sha256")}}
            if not proof.get("dispatch_file") or not _verified_dispatch_content(trace):
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


def terminal_observation_errors(observations: object, handles: list[str], *, require_completed: bool = True,
                                allow_inactive_message: bool = False) -> list[str]:
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
                if (not fresh_turn and allow_inactive_message and not require_completed
                        and row.get("Last dispatch operation") == "send_message"):
                    completed = datetime.fromisoformat(str(row["Latest turn completed at"]).replace("Z", "+00:00"))
                    # send_message queues input but does not start a turn; this proves inactivity only.
                    fresh_turn = (completed.tzinfo is not None and
                                  started <= completed <= times[1] and times[0] <= times[1])
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


def techops_integration_decision_errors(record: object, evidence_ids: set[str]) -> list[str]:
    """Require a supported decision on the conditional integration worker."""
    if not isinstance(record, dict):
        return ["techops_integration_decision_required"]
    errors = []
    if record.get("decision") not in {"required", "not_required"}:
        errors.append("techops_integration_decision_invalid")
    if not isinstance(record.get("reason"), str) or not record["reason"].strip():
        errors.append("techops_integration_reason_required")
    refs = re.findall(r"\bE-[A-Za-z0-9_-]+\b", str(record.get("evidence_refs", "")))
    if not refs or not set(refs) <= evidence_ids:
        errors.append("techops_integration_evidence_required")
    return errors


def techops_reproduction_errors(record: object, evidence_ids: set[str]) -> list[str]:
    """Require a concrete account of the check without requiring reproduction to succeed."""
    if not isinstance(record, dict):
        return ["techops_reproduction_record_required"]
    fields = ("status", "expected", "observed", "check", "environment", "revision", "limitation", "evidence_refs")
    errors = ["techops_reproduction_field_required:" + field for field in fields
              if not isinstance(record.get(field), str) or not record[field].strip()]
    if record.get("status") not in {"reproduced", "verified_by_evidence", "not_reproduced", "unable_to_attempt"}:
        errors.append("techops_reproduction_status_invalid")
    refs = re.findall(r"\bE-[A-Za-z0-9_-]+\b", str(record.get("evidence_refs", "")))
    if not refs or not set(refs) <= evidence_ids:
        errors.append("techops_reproduction_evidence_required")
    return errors


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


def _tool_output_json(value: str):
    warning = "WARNING: proceeding, even though we could not create PATH aliases: Operation not permitted (os error 1)\n"
    return json.loads(value.removeprefix(warning))


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
                decoded = _tool_output_json(value)
                if isinstance(decoded, (dict, list)):
                    yield from _trace_strings(decoded, path)
                    return
            except ValueError:
                pass
        yield path, value


def _listing_command(command: object) -> bool:
    """Recognize name-only discovery; shell expansion and content consumers remain unaudited."""
    if not isinstance(command, str):
        return False
    try:
        tokens = shlex.split(command)
        if len(tokens) == 3 and Path(tokens[0]).name in {"bash", "sh", "zsh"} and tokens[1] in {"-lc", "-c"}:
            command = tokens[2]
        unquoted = re.sub(r"'[^']*'|\"(?:\\.|[^\"\\])*\"|\\.", "", command)
        if ("$" in unquoted or any(char in command for char in "`<>")
                or re.search(r"\$(?:[A-Za-z0-9_?*!#$@-]|[({\[])", command)):
            return False
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
            if args[:2] == ["git", "-C"] and len(args) > 3:
                args = ["git", *args[3:]]
            tool = Path(args[0]).name
            listing = ((args[:2] == ["git", "status"]
                        and set(args[2:]) <= {"--short", "--branch", "--porcelain", "-s", "-b"})
                       or args == ["git", "rev-parse", "HEAD"]
                       or tool in {"ls", "pwd"} or (tool == "rg" and "--files" in args)
                       or (tool == "find" and not set(args) & {
                           "-exec", "-execdir", "-ok", "-okdir", "-delete", "-fprint", "-fprint0", "-fprintf"}))
            filter_only = (previous == "|" and (
                (tool in {"head", "tail"} and all(re.fullmatch(r"-?(?:n|[0-9]+)", arg) for arg in args[1:]))
                or (tool in {"rg", "grep"} and ((len(args) == 2 and not args[1].startswith("-"))
                    or (len(args) == 3 and args[1] in {"-v", "--invert-match"} and not args[2].startswith("-"))))))
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
            targets = _read_targets(shlex.join(part)) if Path(part[0]).name != 'rg' else []
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


def background_memory_paths(command: str, *, standalone: bool = False) -> set[str]:
    """Recognize registry reads without granting access to any linked source or write."""
    if not isinstance(command, str) or '`' in command or '$(' in command:
        return set()
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|<>\n")
        lexer.whitespace = " \t\r"
        lexer.whitespace_split = True
        lexer.commenters = ""
        segments, segment = [], []
        for token in lexer:
            if token in {";", "&&", "||", "|", "\n", ">", ">>", "<"}:
                segments.append(segment)
                segment = []
            else:
                segment.append(token)
        segments.append(segment)
    except ValueError:
        return set()
    paths = set()
    if standalone and len(segments) != 1:
        return set()
    for tokens in segments:
        targets = {token for token in tokens if re.search(r"(?:^|[/\\])MEMORY\.md$", token)}
        if any('MEMORY.md' in token and token not in targets for token in tokens):
            return set()
        if not targets:
            continue
        if any((target != "MEMORY.md" and not re.search(r"[/\\]memories[/\\]MEMORY\.md$", target))
               or any(pattern.search(target) for label, pattern in FORBIDDEN_CONTEXT_PATTERNS
                      if label in {"archived_artifact", "session_log", "rollout_summary"})
               or (Path(target).is_absolute() and Path(target).is_symlink()) for target in targets):
            return set()
        reader = Path(tokens[0]).name
        allowed = False
        if reader == "cat":
            allowed = all(not token.startswith('-') or token == '--' for token in tokens[1:])
        elif reader == "nl":
            allowed = len(tokens) >= 3 and tokens[1] == '-ba' and all(
                not token.startswith('-') for token in tokens[2:])
        elif reader in {"head", "tail"}:
            allowed = bool(_read_targets(shlex.join(tokens)))
        elif reader == "sed":
            allowed = (len(tokens) >= 4 and tokens[1] == '-n'
                       and bool(re.fullmatch(r"[0-9]+(?:,[0-9]+)?p", tokens[2])))
        elif reader == "rg":
            # No preprocessor, pattern file, or directory enumeration can accompany a registry search.
            options = {"-n", "-i", "-ni", "-in", "-F", "--line-number", "--ignore-case", "--fixed-strings"}
            args = tokens[1:]
            context_options = {"-A", "-B", "-C", "--after-context", "--before-context", "--context"}
            while args:
                if args[0] in options or re.fullmatch(
                        r"(?:-[ABC][0-9]+|--(?:after-context|before-context|context)=[0-9]+)", args[0]):
                    args = args[1:]
                elif args[0] in context_options and len(args) > 1 and re.fullmatch(r"[0-9]+", args[1]):
                    args = args[2:]
                else:
                    break
            if args[:1] == ['--']:
                args = args[1:]
            allowed = len(args) >= 2 and not args[0].startswith('-') and targets.issubset(args[1:])
            allowed = allowed and not any(token.startswith('-') for token in args[1:])
        if not allowed:
            return set()
        if standalone:
            operands = (args[1:] if reader == "rg" else tokens[3:] if reader == "sed"
                        else tokens[2:] if reader == "nl"
                        else _read_targets(shlex.join(tokens)) if reader in {"head", "tail"} else tokens[1:])
            if any(token != '--' and token not in targets for token in operands):
                return set()
        paths.update(targets)
    return paths


def _background_memory_paths(row: dict) -> set[str]:
    paths = set()
    operations = _tool_operations(row)
    if any(name != "exec_command" for name, _ in operations):
        return set()
    for name, arguments in operations:
        if name == "exec_command":
            command = arguments.get("cmd", "")
            if isinstance(command, str) and re.search(r"MEMORY\.md", command):
                targets = background_memory_paths(command)
                if not targets:
                    return set()
                paths.update(targets)
    return paths


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
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _literal_argument(node.left, constants)
        right = _literal_argument(node.right, constants)
        if isinstance(left, str) and isinstance(right, str):
            return left + right
        raise ValueError("nonliteral string concatenation")
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
        output_template = (re.search(r"(?<![\w.])text\s*\(\s*$", source[:start]) is not None
                           and re.match(r"\s*\)", source[end + 1:]) is not None)
        if "\\" in raw and (not output_template or re.search(r"\\(?!n)", raw)):
            raise ValueError("escaped templates are not literal arguments")
        parts, offset = [], 0
        for match in re.finditer(r"\$\{([^}]*)\}", raw):
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*", match[1]):
                # Recognize bounded output formatting without evaluating tool arguments.
                output_expression = (re.fullmatch(
                    r"[A-Za-z_][A-Za-z0-9_]*(?:(?:\?\.|\.)[A-Za-z_][A-Za-z0-9_]*)*"
                    r"\s*===\s*(?:true|false)", match[1]) or re.fullmatch(
                    r"[A-Za-z_][A-Za-z0-9_]*\s*\+\s*1", match[1]) or re.fullmatch(
                    r'(?P<results>[A-Za-z_][A-Za-z0-9_]*)\[(?P<index>[A-Za-z_][A-Za-z0-9_]*)\]'
                    r'\.status\s*===\s*"fulfilled"\s*\?\s*(?P=results)\[(?P=index)\]'
                    r'\.value\.output\s*:\s*String\((?P=results)\[(?P=index)\]\.reason\)', match[1]))
                if output_template and output_expression:
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


def _literal_command_loop(source: str) -> list[tuple[str, dict]] | None:
    """Read a finite literal command list with complete output printed in array order."""
    match = re.fullmatch(
        r"\s*const\s+(?P<commands>[A-Za-z_]\w*)\s*=\s*(?P<values>\[.*\])\s*;"
        r"\s*for\s*\(\s*const\s+(?P<command>[A-Za-z_]\w*)\s+of\s+(?P=commands)\s*\)\s*\{"
        r"\s*const\s+(?P<result>[A-Za-z_]\w*)\s*=\s*await\s+tools\.exec_command\((?P<arguments>\{.*\})\)\s*;"
        r"\s*text\((?P=result)\.output\)\s*;\s*\}\s*;?\s*", source, re.S)
    if not match:
        match = re.fullmatch(
            r"\s*const\s+(?P<commands>[A-Za-z_]\w*)\s*=\s*(?P<values>\[.*\])\s*;"
            r"\s*const\s+(?P<result>[A-Za-z_]\w*)\s*=\s*await\s+Promise\.all\("
            r"(?P=commands)\.map\(\s*(?P<command>[A-Za-z_]\w*)\s*=>\s*tools\.exec_command"
            r"\((?P<arguments>\{.*\})\)\)\)\s*;"
            r"\s*for\s*\(\s*let\s+(?P<index>[A-Za-z_]\w*)\s*=\s*0\s*;\s*(?P=index)\s*<\s*"
            r"(?P=result)\.length\s*;\s*(?P=index)\+\+\s*\)\s*\{\s*text\("
            r"`COMMAND \$\{(?P=index)\s*\+\s*1\}\\n\$\{(?P=result)\[(?P=index)\]\.output\}`"
            r"\)\s*;\s*\}\s*;?\s*", source, re.S)
    if not match:
        return None
    names = [match[key] for key in ("commands", "command", "result")]
    if "index" in match.groupdict():
        names.append(match["index"])
    if len(set(names)) != len(names) or set(names) & {"tools", "text", "Promise"}:
        return None
    try:
        commands = _literal_argument(ast.parse(match["values"], mode="eval").body)
        if not isinstance(commands, list) or not commands or not all(isinstance(value, str) for value in commands):
            return None
        arguments = match["arguments"]
        if match["command"] == "cmd":
            arguments = re.sub(r"^\{\s*cmd\s*(?=[,}])", "{cmd: cmd", arguments, count=1)
        tree = ast.parse(arguments, mode="eval").body
        operations = []
        for command in commands:
            value = _literal_argument(tree, {match["command"]: command})
            if not isinstance(value, dict) or value.get("cmd") != command:
                return None
            operations.append(("exec_command", value))
        return operations
    except (ValueError, SyntaxError, TypeError):
        return None


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
    loop = _literal_command_loop(source)
    if loop is not None:
        return loop
    try:
        # This exact trailing print only formats an already returned tool status.
        # Do not evaluate it or permit expressions in tool arguments.
        source = re.sub(
            r'(?<![\w.])text\(\s*`exit_code=\$\{(?P<r>[A-Za-z_]\w*)\.exit_code\s*\?\?\s*"running"\}'
            r'\$\{(?P=r)\.session_id\s*\?\s*` session_id=\$\{(?P=r)\.session_id\}`\s*:\s*""\}`\s*\)\s*;?\s*$',
            'text("status");', source)
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


def _dispatch_segment(command: str) -> tuple[str, int, int] | None:
    """Recognize only an exact literal slice read, without evaluating provider code."""
    try:
        tokens = shlex.split(command)
        if (len(tokens) != 3 or tokens[1] != "-c" or
                (tokens[0] != "python3" and (not Path(tokens[0]).is_absolute()
                 or Path(tokens[0]).resolve() != Path(sys.executable).resolve()))):
            return None
        tree = ast.parse(tokens[2])
        part = tree.body[0].value.args[0]
        target = part.value.func.value.args[0].value
        start, end = part.slice.lower.value, part.slice.upper.value
        if (not isinstance(target, str) or type(start) is not int or type(end) is not int
                or start < 0 or not 0 < end - start <= 6000):
            return None
        expected = f"print(open({target!r}).read()[{start}:{end}],end='')"
        if ast.dump(tree) == ast.dump(ast.parse(expected)):
            return target, start, end
    except (OSError, ValueError, SyntaxError, TypeError, AttributeError, IndexError):
        pass
    return None


def _verified_dispatch_segments(trace: dict, path: Path, content: str, cwd: Path) -> dict[str, list[str]]:
    """Require ordered, complete, paired outputs for the entire immutable dispatch."""
    cursor, verified, owners = 0, {}, {}
    rows = trace.get("tool_trace", [])
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or row.get("type") not in {"function_call", "custom_tool_call"}:
            continue
        for name, arguments in _tool_operations(row):
            segment = _dispatch_segment(arguments.get("cmd", "")) if name == "exec_command" else None
            if not segment:
                continue
            target, start, end = segment
            target_path = Path(target) if Path(target).is_absolute() else Path(arguments.get("workdir") or cwd) / target
            if target_path.resolve() != path.resolve():
                continue
            call_id = row.get("call_id")
            if (start != cursor or end > len(content) or not call_id
                    or call_id in owners and owners[call_id] != index):
                return {}
            owners[call_id] = index
            verified.setdefault(call_id, []).append(content[start:end])
            cursor = end
    if cursor != len(content):
        return {}
    for call_id, segments in verified.items():
        paired = [item for item in rows[owners[call_id] + 1:] if isinstance(item, dict)
                  and item.get("type") in {"function_call_output", "custom_tool_call_output"}
                  and item.get("call_id") == call_id]
        if len(paired) != 1:
            return {}
        delivered = "\0".join(value for _, value in _trace_strings({"tool_trace": paired}))
        if "Warning: truncated output" in delivered:
            return {}
        offset = 0
        for segment in segments:
            found = delivered.find(segment, offset)
            if found < 0:
                return {}
            offset = found + len(segment)
    return verified


def _python_read_targets(source: str, *, pretty: bool = False, argv: tuple[str, ...] = ()) -> list[str]:
    """Resolve read-only inspection paths from literals and fixed file lists without executing Python."""
    tree = ast.parse(source)
    targets, constants = [], {}
    stores = [node.id for node in ast.walk(tree) if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)]
    builtins = {"print", "len", "isinstance", "str", "list", "type", "sorted", "range", "min", "max"}
    protected = builtins | {"open", "json", "pprint", "sys", "Path", "hashlib"}
    def literal_paths(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return [node.value]
        if isinstance(node, ast.Name) and stores.count(node.id) == 1:
            return constants.get(node.id, [])
        if isinstance(node, (ast.Tuple, ast.List)):
            values = [literal_paths(item) for item in node.elts]
            return [value for items in values for value in items] if all(values) else []
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Path"
                and len(node.args) == 1 and not node.keywords):
            return literal_paths(node.args[0])
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            return [str(Path(base) / name) for base in literal_paths(node.left) for name in literal_paths(node.right)]
        return []
    for _ in range(len(stores)):
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                name, value = node.targets[0].id, node.value
            elif isinstance(node, (ast.For, ast.comprehension)) and isinstance(node.target, ast.Name):
                name, value = node.target.id, node.iter
            else:
                continue
            if stores.count(name) == 1 and (paths := literal_paths(value)):
                constants[name] = paths
    called_attributes = {id(node.func) for node in ast.walk(tree)
                         if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store) and node.id in protected:
            return []
        if (isinstance(node, (ast.AugAssign, ast.AnnAssign, ast.NamedExpr, ast.With, ast.AsyncWith,
                             ast.Delete, ast.Try, ast.AsyncFor, ast.AsyncFunctionDef))
                or pretty and isinstance(node, ast.Attribute) and id(node) not in called_attributes):
            return []
        if isinstance(node, (ast.For, ast.comprehension)) and (
                not isinstance(node.target, ast.Name) or node.target.id in protected):
            return []
        if isinstance(node, ast.Import) and any(item.name not in ({"json", "pprint"} if pretty else {"json", "sys", "hashlib"})
                                                or item.asname for item in node.names):
            return []
        if isinstance(node, ast.ImportFrom) and (pretty or node.module != "pathlib" or node.level
                or [(item.name, item.asname) for item in node.names] != [("Path", None)]):
            return []
        if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.Lambda)):
            return []
        if isinstance(node, ast.Assign) and any(not isinstance(target, ast.Name)
                or target.id in protected for target in node.targets):
            return []
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            if node.func.id == "open":
                if len(node.args) != 1 or node.keywords:
                    return []
                argument = node.args[0]
                if pretty and not isinstance(argument, ast.Constant):
                    return []
                paths = literal_paths(argument)
                if (isinstance(argument, ast.Subscript) and isinstance(argument.value, ast.Attribute)
                        and isinstance(argument.value.value, ast.Name) and argument.value.value.id == "sys"
                        and argument.value.attr == "argv" and isinstance(argument.slice, ast.Constant)
                        and type(argument.slice.value) is int and 0 < argument.slice.value < len(argv)):
                    paths = [argv[argument.slice.value]]
                if not paths:
                    return []
                targets.extend(paths)
            elif node.func.id == "Path" and not pretty:
                if not literal_paths(node):
                    return []
            elif node.func.id not in builtins:
                return []
            elif pretty:
                allowed_keywords = {"sep", "end", "flush"} if node.func.id == "print" else (
                    {"reverse"} if node.func.id == "sorted" else set())
                if (any(keyword.arg not in allowed_keywords or not isinstance(keyword.value, ast.Constant)
                        for keyword in node.keywords) or node.func.id != "print" and
                        len(node.args) != (2 if node.func.id == "isinstance" else 1)):
                    return []
        elif isinstance(node.func, ast.Attribute):
            if not pretty and node.func.attr == "is_file":
                paths = literal_paths(node.func.value)
                if node.args or node.keywords or not paths:
                    return []
                targets.extend(paths)
                continue
            if not pretty and node.func.attr in {"read_text", "read_bytes"}:
                paths = literal_paths(node.func.value)
                if node.args or node.keywords or not paths:
                    return []
                targets.extend(paths)
                continue
            json_load = (isinstance(node.func.value, ast.Name) and node.func.value.id == "json"
                         and node.func.attr in {"load", "loads", "dumps"})
            pretty_print = (pretty and isinstance(node.func.value, ast.Name) and node.func.value.id == "pprint"
                            and node.func.attr in {"pp", "pprint", "pformat"})
            hashing = (not pretty and isinstance(node.func.value, ast.Name) and node.func.value.id == "hashlib"
                       and node.func.attr == "sha256" and len(node.args) == 1 and not node.keywords)
            formatting = (not pretty and node.func.attr in {"decode", "hexdigest"}
                          and not node.args and not node.keywords)
            if json_load and any(keyword.arg not in {"indent", "sort_keys", "ensure_ascii"}
                                 or not isinstance(keyword.value, ast.Constant) for keyword in node.keywords):
                return []
            if pretty_print and (len(node.args) != 1 or any(
                    keyword.arg not in {"indent", "width", "depth", "compact", "sort_dicts"}
                    or not isinstance(keyword.value, ast.Constant) for keyword in node.keywords)):
                return []
            if not json_load and not pretty_print and not hashing and not formatting and node.func.attr not in (
                    {"keys", "items", "values", "get", "lower"} if pretty else {"keys", "items", "values", "get", "find"}):
                return []
        else:
            return []
    return targets


def _pretty_packet_reads(trace: dict, root: Path | None) -> dict[str, dict]:
    """Bind read-only pretty-printed metadata to the one literal current packet input."""
    result = {}
    if root is None:
        return result
    for row in trace.get("tool_trace", []):
        if not isinstance(row, dict):
            continue
        operations = _tool_operations(row)
        if not row.get("call_id") or len(operations) != 1 or operations[0][0] != "exec_command":
            continue
        try:
            args = operations[0][1]
            tokens = shlex.split(args.get("cmd", ""))
            if (len(tokens) != 3 or tokens[1] != "-c" or tokens[0] != "python3" and
                    (not Path(tokens[0]).is_absolute() or Path(tokens[0]).resolve() != Path(sys.executable).resolve())):
                continue
            targets = _python_read_targets(tokens[2], pretty=True)
            if len(targets) != 1:
                continue
            path = Path(targets[0])
            path = path if path.is_absolute() else Path(args.get("workdir", root.parent.parent)) / path
            if path.is_symlink() or path.resolve() != root / "finalization_packet.json":
                continue
            reentry = json.loads(path.read_text()).get("reentry")
            if isinstance(reentry, dict) and isinstance(reentry.get("Prior artifacts"), str):
                result[row["call_id"]] = reentry
        except (OSError, ValueError, TypeError, SyntaxError):
            continue
    return result


def _without_pretty_reentry_reference(text: str, expected: dict) -> str:
    """Mask only the archive-pointer value in a matching current reentry dictionary."""
    stack, replacements = [], []
    lines = text.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    try:
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            if token.type != tokenize.OP:
                continue
            if token.string in "{[(":
                stack.append((token.string, token.start))
                continue
            if token.string not in "}])" or not stack:
                continue
            opening, start = stack.pop()
            if opening != "{" or token.string != "}":
                continue
            begin = offsets[start[0] - 1] + start[1]
            end = offsets[token.end[0] - 1] + token.end[1]
            literal = text[begin:end]
            if "Prior artifacts" not in literal or ast.literal_eval(literal) != expected:
                continue
            tree = ast.parse(literal, mode="eval").body
            value = next(value for key, value in zip(tree.keys, tree.values)
                         if isinstance(key, ast.Constant) and key.value == "Prior artifacts")
            encoded = literal.encode()
            fragment_lines = literal.splitlines(keepends=True)
            first = sum(len(line.encode()) for line in fragment_lines[:value.lineno - 1]) + value.col_offset
            last = sum(len(line.encode()) for line in fragment_lines[:value.end_lineno - 1]) + value.end_col_offset
            replacement = (encoded[:first] + b"'[current packet archive reference]'" + encoded[last:]).decode()
            replacements.append((begin, end, replacement))
    except (ValueError, SyntaxError, TypeError, AttributeError, StopIteration, tokenize.TokenError):
        return text
    for begin, end, replacement in sorted(replacements, reverse=True):
        text = text[:begin] + replacement + text[end:]
    return text


def _read_targets(command: str, *, include_json: bool = False) -> list[str]:
    if not isinstance(command, str):
        return []
    segment = _dispatch_segment(command)
    if segment:
        return [segment[0]]
    chunk = _chunked_dispatch_read(command)
    if chunk:
        return [chunk[0]]
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|<>\n")
        lexer.whitespace_split, lexer.commenters = True, ""
        args = list(lexer)
        if (len(args) == 3 and (re.fullmatch(r"python(?:3(?:\.[0-9]+)?)?", args[0])
                or Path(args[0]).resolve() == Path(sys.executable).resolve())
                and args[1] == "-c" and not any(char in command for char in '$`')):
            # JSON projections retain their existing field-level output verification.
            if not include_json and any(isinstance(node, ast.Import) and any(item.name == "json" for item in node.names)
                   for node in ast.walk(ast.parse(args[2]))):
                return []
            return _python_read_targets(args[2])
    except (ValueError, SyntaxError):
        return []
    python = re.fullmatch(r"(\S+) - <<['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?\n(.*?)\n\2\s*", command, re.S)
    if python:
        try:
            if (not re.fullmatch(r"python(?:3(?:\.[0-9]+)?)?", python[1])
                    and Path(python[1]).resolve() != Path(sys.executable).resolve()):
                return []
            return _python_read_targets(python[3])
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
    if any(value in command for value in ("$(", "`")):
        return []
    loop = re.search(r"(?:^|;)\s*(for\s+[A-Za-z_]\w*\s+in\s+)", command)
    if loop and loop.start() and _listing_command(command[:loop.start()]):
        return _read_targets(command[loop.start(1):], include_json=include_json)
    try:
        lexer = shlex.shlex(command.strip(), posix=True, punctuation_chars=";&|<>\n")
        lexer.whitespace = " \t\r"
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
            if len(parts[0]) < 4 or parts[0][2] != "in" or not re.fullmatch(r"[A-Za-z_]\w*", parts[0][1]):
                return []
            variable = "$" + parts[0][1]
            if any(target.startswith("-") or "$" in target for target in parts[0][3:]):
                return []
            def echo_label(part, prefix):
                return (len(part) == 3 and part[:2] == [prefix, "echo"]
                        and re.fullmatch(r"[A-Za-z0-9 _:-]*" + re.escape(variable), part[2]))
            body = parts[1:]
            conditions = (["do", "if", "test", "-f", variable],
                          ["do", "if", "[", "-f", variable, "]"])
            if body and body[0] in conditions:
                body = body[1:]
                if body and echo_label(body[0], "then"):
                    body = [["then", *body[1]]] + body[2:] if len(body) > 1 else []
                if body and body[0] == ["then", "cat", variable]:
                    body = body[1:]
                    if body and echo_label(body[0], "else"):
                        body = body[1:]
                    if body[:2] == [["fi"], ["done"]]:
                        targets = parts[0][3:]
                        for part in body[2:]:
                            if not part:
                                continue
                            selected = _read_targets(shlex.join(part), include_json=include_json)
                            if not selected and not _listing_command(shlex.join(part)):
                                return []
                            targets.extend(selected)
                        return targets
            if len(parts) != 4:
                return []
            if (len(parts[1]) != 4 or parts[1][:2] != ["do", "printf"] or parts[1][3] != variable
                    or parts[2] != ["cat", variable] or parts[3] != ["done"]):
                return []
            return parts[0][3:]
        if any(token in {";", "&&", "\n"} for token in tokens) and "$" not in command:
            parts, part = [], []
            for token in tokens:
                if token in {";", "&&", "\n"}:
                    parts.append(part)
                    part = []
                else:
                    part.append(token)
            parts.append(part)
            if not parts[-1]:
                return []
            reads = []
            for part in parts:
                selected = _read_targets(shlex.join(part), include_json=include_json)
                if not selected and not _listing_command(shlex.join(part)):
                    return []
                reads.extend(selected)
            return reads
        if '|' in tokens:
            parts, part = [], []
            for token in tokens:
                if token == '|':
                    parts.append(shlex.join(part))
                    part = []
                else:
                    part.append(token)
            parts.append(shlex.join(part))
            return (_read_targets(parts[0], include_json=include_json) if all(part and _listing_command('pwd | ' + part)
                                                  for part in parts[1:]) else [])
        if not tokens or "$" in command or any(re.fullmatch(r'[;&|<>\n]+', token) for token in tokens):
            return []
        if tokens[0] == 'rg':
            paths, pattern, index = [], False, 1
            while index < len(tokens):
                token = tokens[index]
                if token in {'-g', '--glob', '-t', '--type', '--type-not', '-A', '-B', '-C', '-m', '--max-count'}:
                    if index + 1 == len(tokens):
                        return []
                    index += 2
                    continue
                if token.startswith('-'):
                    if token not in {'-n', '-i', '-F', '-S', '-l', '--line-number', '--ignore-case', '--fixed-strings'}:
                        return []
                elif not pattern:
                    pattern = True
                else:
                    paths.append(token)
                index += 1
            return paths if pattern else []
        if tokens[0] == "cat" and len(tokens) > 1 and all(not arg.startswith("-") for arg in tokens[1:]):
            return tokens[1:]
        if tokens[0] in {"head", "tail"}:
            if len(tokens) == 4 and tokens[1] == "-n" and re.fullmatch(r"[1-9][0-9]*", tokens[2]):
                return [tokens[3]] if not tokens[3].startswith("-") else []
            if len(tokens) == 3 and re.fullmatch(r"-[1-9][0-9]*|--lines=[1-9][0-9]*", tokens[1]):
                return [tokens[2]] if not tokens[2].startswith("-") else []
        if (len(tokens) > 3 and tokens[:2] == ["sed", "-n"]
                and re.fullmatch(r"[0-9]+(?:,[0-9]+)?p", tokens[2])):
            return tokens[3:]
        return []
    except (ValueError, SyntaxError):
        return []


def _allowed_instruction_paths(root: Path, assigned: list[str]) -> set[Path]:
    """Allow source-repository instructions, excluding the artifact tree."""
    repository = root.parent.parent.resolve()
    artifact_tree = (repository / ".thoughts").resolve()
    directories = {repository}
    for source in assigned:
        if not isinstance(source, str) or not source.strip() or "://" in source:
            continue
        path = Path(source)
        try:
            resolved = (path if path.is_absolute() else repository / path).resolve()
        except OSError:
            continue
        if not resolved.is_relative_to(repository) or resolved.is_relative_to(artifact_tree):
            continue
        if resolved.name == "AGENTS.md":
            directories.add(resolved.parent)
        directory = resolved if resolved.is_dir() else resolved.parent
        while directory.is_relative_to(repository):
            if directory.is_relative_to(artifact_tree):
                break
            directories.add(directory)
            if directory == repository:
                break
            directory = directory.parent
    candidates = {directory / "AGENTS.md" for directory in directories}
    # A link to another applicable instruction file is safe; a link to archived analysis is not.
    return {path.resolve() for path in candidates if path.resolve() in candidates}


def _python_packet_projection(tokens: list[str], root: Path, cwd: Path) -> set[str] | None:
    """Recognize a read-only JSON projection without executing its source."""
    if len(tokens) != 3 or Path(tokens[0]).name not in {"python", "python3"} or tokens[1] != "-c":
        return None
    try:
        program = ast.parse(tokens[2])
        body = program.body
        if (len(body) != 4 or not isinstance(body[1], ast.Assign) or len(body[1].targets) != 1
                or not isinstance(body[1].targets[0], ast.Name) or not isinstance(body[1].value, ast.Constant)
                or not isinstance(body[1].value.value, str)):
            return None
        var = body[1].targets[0].id
        packet = Path(body[1].value.value)
        packet = packet if packet.is_absolute() else cwd / packet
        if packet.is_symlink() or packet.resolve() != root / "finalization_packet.json":
            return None
        if (not isinstance(body[2], ast.Assign) or len(body[2].targets) != 1
                or not isinstance(body[2].targets[0], ast.Name)):
            return None
        data_var = body[2].targets[0].id
        expression = body[3].value
        mapping = expression.args[0].args[0]
        if not isinstance(mapping, ast.Dict) or not mapping.keys or not all(
                isinstance(key, ast.Constant) and isinstance(key.value, str) and key.value.isidentifier()
                for key in mapping.keys):
            return None
        fields = [key.value for key in mapping.keys]
        if len(fields) != len(set(fields)) or not set(fields) & {"reentry", "runtime_audits"}:
            return None
        projection = ",".join(f"{field!r}:{data_var}.get({field!r})" for field in fields)
        expected = (f"import json; {var}={str(packet)!r}; {data_var}=json.load(open({var})); "
                    f"print(json.dumps({{{projection}}}, indent=2))")
        actual = tokens[2]
        if not Path(body[1].value.value).is_absolute():
            expected = expected.replace(repr(str(packet)), repr(body[1].value.value), 1)
        if ast.dump(ast.parse(actual)) != ast.dump(ast.parse(expected)):
            return None
        return set(fields)
    except (ValueError, SyntaxError, AttributeError, IndexError, TypeError):
        return None


def _labeled_packet_outputs(trace: dict, root: Path | None) -> dict[str, tuple[str, str]]:
    """Recognize a literal projection of current packet fields, including reentry metadata."""
    if root is None:
        return {}
    result = {}
    for row in trace.get("tool_trace", []):
        if not isinstance(row, dict) or not row.get("call_id"):
            continue
        operations = _tool_operations(row)
        if len(operations) != 1 or operations[0][0] != "exec_command":
            continue
        try:
            args = operations[0][1]
            tokens = shlex.split(args["cmd"])
            if len(tokens) != 3 or Path(tokens[0]).name not in {"python", "python3"} or tokens[1] != "-c":
                continue
            body = ast.parse(tokens[2]).body
            if len(body) != 3 or not isinstance(body[1], ast.Assign) or len(body[1].targets) != 1:
                continue
            variable = body[1].targets[0].id
            locator = body[1].value.args[0].args[0].value
            fields = [item.value for item in body[2].value.generators[0].iter.elts]
            if not fields or "reentry" not in fields or len(fields) != len(set(fields)) or not all(
                    isinstance(field, str) and field.isidentifier() for field in fields):
                continue
            expected = (f"import json; {variable}=json.load(open({locator!r})); "
                        f"[print(k+':', json.dumps({variable}.get(k), indent=2)) for k in {tuple(fields)!r}]")
            if ast.dump(ast.parse(tokens[2])) != ast.dump(ast.parse(expected)):
                continue
            path = Path(locator)
            path = path if path.is_absolute() else Path(args.get("workdir", root.parent.parent)) / path
            if path.is_symlink() or path.resolve() != root / "finalization_packet.json":
                continue
            packet = json.loads(path.read_text())
            reference = packet.get("reentry", {}).get("Prior artifacts")
            if not isinstance(reference, str) or not reference:
                continue
            output = "".join(f"{field}: {json.dumps(packet.get(field), indent=2)}\n" for field in fields)
            result[row["call_id"]] = (output, json.dumps(reference))
        except (OSError, ValueError, KeyError, AttributeError, IndexError, TypeError, SyntaxError):
            continue
    return result


def _read_output_prefixes(trace: dict, assigned: list[str], root: Path | None) -> tuple[set[tuple[str, ...]], dict[str, list[str]]]:
    if root is None:
        return set(), {}
    calls, outputs = set(), set()
    metadata_references = {}
    exact_cat_outputs, exact_reentry_outputs, packet_projections = {}, {}, {}
    for row in trace.get("tool_trace", []):
        if not isinstance(row, dict) or not row.get("call_id"):
            continue
        for name, arguments in _tool_operations(row):
            if name != "exec_command":
                continue
            try:
                tokens = shlex.split(arguments.get("cmd", ""))
                targets = _read_targets(arguments.get("cmd", ""))
                cwd = Path(arguments.get("workdir") or root.parent.parent)
                fields = _python_packet_projection(tokens, root, cwd)
                if fields is not None:
                    metadata = json.loads((root / "finalization_packet.json").read_text())
                    packet_projections.setdefault(row["call_id"], []).append((fields, metadata))
                    continue
                if (len(tokens) == 3 and tokens[0] == "jq"
                        and re.fullmatch(r"\{\s*[A-Za-z_][A-Za-z0-9_]*(?:\s*,\s*[A-Za-z_][A-Za-z0-9_]*)*\s*\}", tokens[1])):
                    fields = {field.strip() for field in tokens[1][1:-1].split(",")}
                    packet = Path(tokens[2])
                    packet = packet if packet.is_absolute() else cwd / packet
                    if (fields & {"reentry", "runtime_audits"} and not packet.is_symlink()
                            and packet.resolve() == root / "finalization_packet.json"):
                        metadata = json.loads(packet.read_text())
                        packet_projections.setdefault(row["call_id"], []).append((fields, metadata))
                    continue
                if len(tokens) == 3 and tokens[:2] == ["jq", ".reentry"]:
                    packet = Path(tokens[2])
                    packet = packet if packet.is_absolute() else cwd / packet
                    if not packet.is_symlink() and packet.resolve() == root / "finalization_packet.json":
                        projection = json.loads(packet.read_text()).get("reentry")
                        if isinstance(projection, dict):
                            exact_reentry_outputs.setdefault(row["call_id"], []).append(projection)
                    continue
                paths = [Path(target) if Path(target).is_absolute() else cwd / target for target in targets]
                receipts = root / "activation_receipts.json"
                instructions = json.loads(receipts.read_text()) if receipts.is_file() else {}
                dispatch = Path(trace["spawn"]["dispatch_file"]).resolve()
                if (not tokens or tokens[0] != "cat" or not targets or tokens[1:] != targets
                        or any(path.is_symlink() or path.resolve().parent != root or not path.is_file()
                               or path.resolve() == dispatch or path.name in instructions for path in paths)):
                    continue
                content = "".join(path.read_text() for path in paths)
            except (OSError, ValueError, TypeError, UnicodeError, KeyError):
                continue
            exact_cat_outputs.setdefault(row["call_id"], set()).add(content)
    strict_projections = set(packet_projections) | set(_labeled_packet_outputs(trace, root)) | set(_pretty_packet_reads(trace, root))
    for index, row in enumerate(trace.get("tool_trace", [])):
        if not isinstance(row, dict):
            continue
        operations = _tool_operations(row)
        safe = bool(operations)
        metadata = []
        for name, arguments in operations:
            if name == "mcp__codex_app__read_thread":
                safe = safe and "codex://threads/" + str(arguments.get("threadId")) in assigned
            elif name == "exec_command":
                if row.get("call_id") in strict_projections:
                    safe = False
                    continue
                command = arguments.get("cmd")
                targets = _read_targets(command, include_json=True)
                if (not targets and isinstance(command, str) and command.splitlines()
                        and all(_listing_command(line) for line in command.splitlines() if line.strip())):
                    continue
                workdir = arguments.get("workdir")
                if workdir is not None and not isinstance(workdir, (str, Path)):
                    safe = False
                    continue
                cwd = Path(workdir or root.parent.parent)
                resolved = [Path(target) if Path(target).is_absolute() else cwd / target for target in targets]
                metadata.extend(path for path in resolved if path.parent.resolve() == root
                                and path.name in {"role_bindings.json", "finalization_packet.json"})
                receipts = root / "activation_receipts.json"
                instructions = json.loads(receipts.read_text()) if receipts.is_file() else {}
                allowed_instructions = _allowed_instruction_paths(root, assigned)
                safe = safe and bool(targets) and all(
                    not any(char in str(path) for char in '*?[]{}~')
                    and not (path.resolve().parent == root and path.name in instructions)
                    and path.resolve() != Path(trace["spawn"]["dispatch_file"]).resolve()
                    and ((path.resolve().parent == root and not path.is_symlink()
                          and (path.is_file() or not path.exists())) or str(path) in assigned
                         or ((path.exists() or path.name == "AGENTS.md" and path.parent.is_dir() and not path.is_symlink())
                             and not path.resolve().is_relative_to(root.parent)
                             and any(Path(parent).is_dir() and path.resolve().is_relative_to(Path(parent).resolve())
                                     for parent in assigned if parent.startswith('/')))
                         or (path.name == "AGENTS.md" and path.resolve() in allowed_instructions
                             and not path.is_symlink() and (path.is_file() or not path.exists() and path.parent.is_dir())))
                    for path in resolved)
            elif name not in {"mcp__codex_apps__atlassian_getjiraissue", "mcp__codex_apps__atlassian_executeread",
                              "mcp__codex_apps__atlassian_discover", "mcp__codex_apps__atlassian_searchjiraissuesusingjql"}:
                safe = False
        if safe:
            if metadata and row.get("call_id"):
                try:
                    if any(file.is_symlink() or not file.is_file() for file in metadata):
                        continue
                    values = [value for file in metadata for _, value in _trace_strings(json.loads(file.read_text()))
                              if (value.startswith(("/", ".thoughts/"))
                                  and (any(pattern.search(value) for _, pattern in FORBIDDEN_CONTEXT_PATTERNS)
                                       or any("/runs/" in ref for ref in THOUGHT_PATH.findall(value))))]
                    metadata_references[row["call_id"]] = values
                except (OSError, ValueError, TypeError):
                    pass
            else:
                outputs.update({("tool_trace", str(index), "result"), ("tool_trace", str(index), "output")})
                if row.get("call_id"):
                    calls.add(row["call_id"])
        if row.get("type") in {"function_call_output", "custom_tool_call_output"} and row.get("call_id") in calls:
            outputs.add(("tool_trace", str(index), "output"))
        if row.get("type") == "custom_tool_call_output" and isinstance(row.get("output"), str):
            try:
                result = json.loads(row["output"])
            except (ValueError, TypeError):
                pass
            else:
                if result in exact_reentry_outputs.get(row.get("call_id"), []):
                    outputs.add(("tool_trace", str(index), "output"))
        if row.get("type") == "custom_tool_call_output" and isinstance(row.get("output"), list):
            for item_index, item in enumerate(row["output"]):
                if not isinstance(item, dict) or not isinstance(item.get("text"), str):
                    continue
                try:
                    result = _tool_output_json(item["text"])
                except (ValueError, TypeError):
                    continue
                for fields, metadata in packet_projections.get(row.get("call_id"), []):
                    if not isinstance(result, dict) or set(result) != fields:
                        continue
                    prefix = ("tool_trace", str(index), "output", str(item_index), "text")
                    if isinstance(metadata.get("reentry"), dict) and result.get("reentry") == metadata["reentry"]:
                        outputs.add(prefix + ("reentry", "Prior artifacts"))
                    audits = result.get("runtime_audits", [])
                    if isinstance(audits, list) and isinstance(metadata.get("runtime_audits"), list):
                        for audit_index, audit in enumerate(audits):
                            if isinstance(audit, dict) and audit in metadata["runtime_audits"]:
                                outputs.add(prefix + ("runtime_audits", str(audit_index), "Trace retrieval"))
                if ((isinstance(result, dict) and result.get("exit_code") == 0
                     and isinstance(result.get("output"), str)
                     and result["output"] in exact_cat_outputs.get(row.get("call_id"), set()))
                        or result in exact_reentry_outputs.get(row.get("call_id"), [])):
                    outputs.add(("tool_trace", str(index), "output", str(item_index), "text"))
    return outputs, metadata_references


def observed_dispatch_binding(trace: dict, root: Path) -> dict:
    bindings = json.loads((root / "role_bindings.json").read_text())
    role = worker_binding(bindings, trace["spawn"]["agent"])
    for row in reversed(trace.get("tool_trace", [])):
        for name, arguments in _tool_operations(row):
            if name != "exec_command":
                continue
            cwd = Path(arguments.get("workdir") or bindings["execution_repository"])
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
                if content and _verified_dispatch_segments(trace, path, content, cwd):
                    return proof
                if content and row.get("call_id"):
                    for output in trace.get("tool_trace", []):
                        if (output.get("type") in {"function_call_output", "custom_tool_call_output"}
                                and output.get("call_id") == row["call_id"]
                                and any(_dispatch_read_output(arguments.get("cmd", ""), content) in value
                                        for _, value in _trace_strings({"tool_trace": [output]}))):
                            return proof
    return {}


def live_dispatch_binding(event: dict, role: str, root: Path, run_id: str, observed_at: str) -> dict:
    """Authenticate a live worker's complete instruction read when its launch message is opaque."""
    if event.get("Binding agent"):
        if event.get("Binding agent") != role:
            return {}
        return {"dispatch_file": event.get("Dispatch file"),
                "dispatch_file_sha256": event.get("Dispatch SHA256"), "binding_agent": role}
    thread = event.get("Thread ID")
    if not isinstance(thread, str) or not re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", thread):
        return {}
    sessions = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "sessions"
    try:
        matching = []
        for source in sessions.rglob("*" + thread + "*.jsonl"):
            with source.open() as stream:
                header = json.loads(next(stream, ""))
            if header.get("type") == "session_meta" and header.get("payload", {}).get("id") == thread:
                matching.append(source)
        if len(matching) != 1:
            return {}
        trace = {"run_id": run_id, "spawn": {"agent": role}, "tool_trace": []}
        with matching[0].open() as stream:
            next(stream)
            for line in stream:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    if not line.endswith("\n"):
                        break
                    raise
                if timestamp(row["timestamp"]) < timestamp(event["Last dispatch at"]):
                    continue
                if timestamp(row["timestamp"]) > timestamp(observed_at):
                    continue
                payload = row.get("payload", {})
                if row.get("type") == "response_item" and payload.get("type") in {
                        "function_call", "function_call_output", "custom_tool_call", "custom_tool_call_output"}:
                    trace["tool_trace"].append(payload)
        return observed_dispatch_binding(trace, root)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
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
            for call_id, segments in _verified_dispatch_segments(trace, dispatch_path, content, root.parent.parent).items():
                contents.setdefault(call_id, {}).setdefault("dispatch", []).extend(segments)
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
                    cwd = Path(arguments.get("workdir") or root.parent.parent)
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
            cwd = Path(arguments.get("workdir") or root.parent.parent)
            for target in _ancestor_instruction_reads(operation, root, input_paths=assigned):
                path = Path(target)
                path = path if path.is_absolute() else cwd / path
                try:
                    if path.is_file():
                        record_paired_output(row, path.read_text(), "ancestor")
                except (OSError, UnicodeError):
                    continue
    return contents


def _python_instruction_reads(command: str) -> list[str]:
    """Recognize a literal optional-instruction loop without executing provider code."""
    match = re.fullmatch(r"(python3|/[^\s]+/python3) - <<['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?\n(.*?)\n\2\s*", command, re.S)
    if not match:
        return []
    try:
        if match[1] != "python3" and Path(match[1]).resolve() != Path(sys.executable).resolve():
            return []
        tree = ast.parse(match[3])
        # Exact literal path-list form: it inspects files only and never lists directories.
        if len(tree.body) == 3 and isinstance(tree.body[1], ast.Assign):
            selected = ast.literal_eval(tree.body[1].value)
            if (isinstance(selected, list) and selected
                    and all(isinstance(p, str) and Path(p).name == "AGENTS.md" for p in selected)):
                expected = ("from pathlib import Path\npaths = " + repr(selected) + "\n"
                            "for value in paths:\n path = Path(value)\n if path.is_file():\n"
                            "  print(f'===== {value} =====')\n  print(path.read_text())\n"
                            " else:\n  print(f'ABSENT {value}')")
                if ast.dump(tree) == ast.dump(ast.parse(expected)):
                    return selected
        # This exact read-only inspection also checks the three ancestor instruction paths.
        if len(tree.body) == 5 and isinstance(tree.body[-1], ast.For):
            loop = tree.body[-1]
            selected = [ast.literal_eval(node.args[0]) for node in loop.iter.elts]
            paths = ",".join(f"Path({target!r})" for target in selected)
            packet = ast.literal_eval(tree.body[2].value.args[0])
            expected = ("import json\nfrom pathlib import Path\np=Path(" + repr(packet) + ")\n"
                        "for line in p.read_text().splitlines():\n try:\n  d=json.loads(line)\n"
                        "  print(list(d))\n except ValueError: pass\n"
                        "for p in [" + paths + "]:\n if p.exists(): print(p.read_text())")
            if (isinstance(packet, str) and all(isinstance(target, str) for target in selected)
                    and ast.dump(tree) == ast.dump(ast.parse(expected))):
                return selected
        imports = [node for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        if (len(imports) != 1 or ast.dump(imports[0]) != ast.dump(ast.parse('from pathlib import Path').body[0])
                or any(isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
                       and node.id in {'Path', 'print'} for node in ast.walk(tree))
                or any(isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.Lambda, ast.Delete)) for node in ast.walk(tree))
                or any(isinstance(node, ast.Import) and any(alias.name != 'json' or alias.asname
                       for alias in node.names) for node in ast.walk(tree))
                or any(isinstance(node, ast.Attribute) and (isinstance(node.ctx, ast.Store)
                       or node.attr.startswith('__')) for node in ast.walk(tree))
                or any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                       and node.func.id not in {'Path', 'print', 'len', 'str', 'list', 'sorted', 'isinstance', 'type'}
                       for node in ast.walk(tree))):
            return []
        targets = []
        for loop in tree.body:
            if not isinstance(loop, ast.For):
                continue
            variable = loop.target.id
            selected = [ast.literal_eval(node.args[0]) for node in loop.iter.elts]
            if not selected or not all(isinstance(target, str) for target in selected):
                continue
            paths = ", ".join(f"Path({target!r})" for target in selected)
            marker = loop.body[0].value
            # Permit literal marker text and only the loop path/existence in formatted fields.
            expressions = {ast.dump(ast.parse(value, mode='eval').body)
                           for value in (variable, variable + '.is_file()')}
            if (not isinstance(marker, ast.Call) or ast.unparse(marker.func) != 'print' or marker.keywords
                    or len(marker.args) != 1 or not isinstance(marker.args[0], ast.JoinedStr)
                    or any(not isinstance(part, ast.Constant) and not (
                        isinstance(part, ast.FormattedValue) and part.format_spec is None
                        and ast.dump(part.value) in expressions) for part in marker.args[0].values)):
                continue
            conditions = [variable + '.is_file()'] + [
                f'{variable}.is_file() and {variable} != Path({target!r})' for target in selected]
            for condition in conditions:
                expected = (f'for {variable} in [{paths}]:\n    {ast.unparse(marker)}\n'
                            f'    if {condition}: print({variable}.read_text())')
                if ast.dump(loop) == ast.dump(ast.parse(expected).body[0]):
                    targets.extend(selected)
                    break
        return targets
    except (SyntaxError, AttributeError, IndexError, TypeError, ValueError):
        pass
    return []


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
        python_targets = _python_instruction_reads(command)
        try:
            lexer = shlex.shlex(command, posix=True, punctuation_chars=";&\n")
            lexer.whitespace_split = True
            lexer.whitespace = " \t\r"
            lexer.commenters = ""
            statements, current = [], []
            for token in lexer:
                if token == "&&" or token and all(char in ";\n" for char in token):
                    if current:
                        statements.append(current)
                        current = []
                else:
                    current.append(token)
            if current:
                statements.append(current)
        except ValueError:
            continue
        targets, index = python_targets, len(statements) if python_targets else 0
        # Recognize independent instruction reads; other statements remain fully audited.
        while index < len(statements):
            statement = statements[index]
            if (include_probes and len(statement) == 4 and statement[:3] == ["if", "test", "-f"]
                    and index + 3 < len(statements)
                    and statements[index + 1] == ["then", "cat", statement[3]]
                    and statements[index + 2] == ["else", "printf", "absent\\n"]
                    and statements[index + 3] == ["fi"]):
                # The same literal appears in the existence check and read; both are inspected.
                targets.extend([statement[3], statement[3]])
                index += 4
            elif len(statement) >= 4 and statement[0] == "for" and statement[2] == "in":
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
                    for condition in (["[", "-f", argument, "]"], ["[[", "-f", argument, "]]"],
                                      ["test", "-f", argument])
                    for output in (["printf", "%s\\n", argument], ["echo", argument]))
                valid = valid or include_probes and tail == [
                    "do", "if", "test", "-e", variable, "then", "printf", "present %s\\n", variable,
                    "else", "printf", "absent %s\\n", variable, "fi", "done"]
                valid = valid or include_probes and tail == [
                    "do", "test", "!", "-f", variable, "||", "printf", "%s\\n", variable, "done"]
                if include_probes:
                    for condition in conditions:
                        prefix = ["do", "if", *condition, "then"]
                        output = tail[len(prefix):] if tail[:len(prefix)] == prefix else []
                        if (len(output) == 9 and output[0] == "printf" and output[2] == variable
                                and output[3:5] == ["else", "printf"] and output[6] == variable
                                and output[7:] == ["fi", "done"]
                                and all("%s" in fmt and "%n" not in fmt and not fmt.startswith("-")
                                        and not any(char in fmt for char in "$`<>|&")
                                        for fmt in (output[1], output[5]))):
                            valid = True
                for condition in conditions:
                    prefix = ["do", "if", *condition, "then"]
                    branch_tail = tail
                    if "else" in tail:
                        absent = tail.index("else")
                        notice = tail[absent + 1:-2]
                        safe_notice = (len(notice) >= 2 and notice[0] in {"echo", "printf"}
                            and (notice[0] != "printf" or not notice[1].startswith("-") and "%n" not in notice[1])
                            and any(part in (notice, ["else", *notice]) for part in statements[index + 1:end])
                            and not any(token in {"&", "&&", "|", "||", "<", ">"}
                                or any(char in token for char in "`<>")
                                or "$" in token.replace(variable, "") for token in notice))
                        branch_tail = tail[:absent] + tail[-2:] if safe_notice else []
                    if branch_tail[:len(prefix)] == prefix and branch_tail[-len(suffix):] == suffix:
                        marker = branch_tail[len(prefix):-len(suffix)]
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
                if (not selected and len(statement) == 3 and statement[0] == "python3" and statement[1] == "-c"):
                    try:
                        selected = _python_read_targets(statement[2], pretty=True)
                    except (ValueError, TypeError, SyntaxError):
                        pass
                probe_prefix = include_probes and (
                    len(statement) == 4 and statement[:3] in (["test", "!", "-e"], ["test", "!", "-f"])
                    and not any(char in statement[3] for char in "$`<>|&")
                    or len(statement) == 3 and statement[:2] in (["test", "-e"], ["test", "-f"])
                    and not any(char in statement[2] for char in "$`<>|&")
                    or len(statement) == 2 and statement[0] == "printf"
                    and not statement[1].startswith("-") and not any(char in statement[1] for char in "$`%<>|&"))
                if not selected and not probe_prefix:
                    break
                if (not selected and statement[0] == "test" and statement[-1].endswith("AGENTS.md")):
                    target = Path(statement[-1])
                    target = target if target.is_absolute() else Path(arguments.get("workdir") or root.parent.parent) / target
                    try:
                        if target.name == "AGENTS.md" and target.resolve() in allowed:
                            targets.append(statement[-1])
                    except (OSError, RuntimeError):
                        pass
                targets.extend(selected)
                index += 1
        cwd = Path(arguments.get("workdir") or root.parent.parent)
        for target in targets:
            if any(char in target for char in "$`*"):
                continue
            path = Path(target)
            resolved = (path if path.is_absolute() else cwd / path).resolve()
            if resolved in allowed:
                reads.append(target)
    return reads


def _framework_searches(trace: dict, root: Path | None) -> dict[str, list[Path]]:
    """Identify single literal searches restricted to the prepared framework package."""
    try:
        package = Path(json.loads((root / "role_bindings.json").read_text())["framework_package"]["root"]).resolve()
    except (OSError, ValueError, KeyError, TypeError):
        return {}
    searches = {}
    for row in trace.get("tool_trace", []):
        if not isinstance(row, dict) or not row.get("call_id"):
            continue
        operations = _tool_operations(row)
        if len(operations) != 1 or operations[0][0] != "exec_command":
            continue
        command = operations[0][1].get("cmd", "")
        if not isinstance(command, str) or any(c in command for c in "$`;&<>\n"):
            continue
        try:
            lexer = shlex.shlex(command, posix=True, punctuation_chars="|")
            lexer.whitespace_split = True
            tokens = list(lexer)
            if "|" in tokens or len(tokens) < 4 or tokens[:2] != ["rg", "-n"]:
                continue
            targets = [Path(token).resolve() for token in tokens[3:] if Path(token).is_absolute()]
            if len(targets) == len(tokens) - 3 and all(path.is_relative_to(package) for path in targets):
                searches[row["call_id"]] = targets
        except (ValueError, OSError):
            continue
    return searches


def _without_verified_search_lines(value: str, targets: list[Path]) -> str:
    remaining = []
    for line in value.splitlines(keepends=True):
        match = re.match(r"^(/[^\n:]+):(\d+):(.*?)(?:\r?\n)?$", line)
        if match:
            path = Path(match[1]).resolve()
            try:
                if (any(path == target or path.is_relative_to(target) for target in targets)
                        and path.stat().st_size <= 262144):
                    lines = path.read_text().splitlines()
                    number = int(match[2])
                    if 0 < number <= len(lines) and lines[number - 1] == match[3]:
                        continue
            except (OSError, UnicodeError):
                pass
        remaining.append(line)
    return "".join(remaining)


def _without_approval_justification(text: str, row: dict, field_path: tuple[str, ...]) -> str:
    """Approval prose is not an executed source read; preserve every executable argument."""
    operations = _tool_operations(row)
    justifications = {args['justification'] for tool, args in operations
                      if tool == 'exec_command' and isinstance(args.get('justification'), str)}
    if field_path[-2:] == ('arguments', 'justification') and text in justifications:
        return '[approval metadata]'
    if justifications and field_path[-1:] == ('arguments',):
        try:
            arguments = json.loads(text)
            if isinstance(arguments, dict) and arguments.get('justification') in justifications:
                arguments['justification'] = '[approval metadata]'
                return json.dumps(arguments)
        except (ValueError, TypeError):
            pass
    if justifications and field_path[-1:] == ('input',):
        try:
            tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
            offsets = [0]
            for line in text.splitlines(keepends=True):
                offsets.append(offsets[-1] + len(line))
            edits = []
            for key, colon, value in zip(tokens, tokens[1:], tokens[2:]):
                if (key.string not in {'justification', '"justification"', "'justification'"}
                        or colon.string != ':' or value.type != tokenize.STRING):
                    continue
                prose = ast.literal_eval(value.string)
                if prose in justifications:
                    begin, end = (offsets[line - 1] + column for line, column in (value.start, value.end))
                    edits.append((begin, end, json.dumps('[approval metadata]')))
            for begin, end, replacement in reversed(edits):
                text = text[:begin] + replacement + text[end:]
        except (ValueError, SyntaxError, TypeError, tokenize.TokenError):
            pass
    return text


def _without_prose_root_punctuation(text: str, row: dict, root: Path) -> str:
    """Distinguish serialized assignment text and failure metadata from executed operations."""
    if (str(root) + "." not in text and ".thoughts/" not in text
            and not any(pattern.search(text) for _, pattern in FORBIDDEN_CONTEXT_PATTERNS)):
        return text
    punctuation = re.compile(r"(" + re.escape(str(root)) + "|" + re.escape(".thoughts/" + root.name)
                             + r")\.(?=\s|$)")
    for tool, arguments in _tool_operations(row):
        command = arguments.get("cmd") if tool == "exec_command" else None
        if not isinstance(command, str):
            continue
        try:
            lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|<>")
            lexer.whitespace_split = True
            tokens = list(lexer)
            package = Path(json.loads((root / "role_bindings.json").read_text())["framework_package"]["root"])
            if ("\n" not in command and len(tokens) == 6 and Path(tokens[0]).name in {"python", "python3"}
                    and Path(tokens[1]).resolve() == (package / "scripts/finalize_work_record.py").resolve()
                    and tokens[2] == "--packet" and Path(tokens[3]).resolve() == (root / "finalization_packet.json").resolve()
                    and tokens[4] == "--workflow-failure"):
                for quote in (shlex.quote, lambda value: json.dumps(value, ensure_ascii=False)):
                    quoted = quote(tokens[5])
                    if command.endswith(quoted):
                        if quote is not shlex.quote and any(char in quoted for char in "$`"):
                            continue
                        replacement = command[:-len(quoted)] + quote(punctuation.sub(r"\1", tokens[5]))
                        text = text.replace(command, replacement)
                        for ascii_only in (False, True):
                            text = text.replace(json.dumps(command, ensure_ascii=ascii_only)[1:-1],
                                                json.dumps(replacement, ensure_ascii=ascii_only)[1:-1])
                        break
        except (OSError, ValueError, KeyError, TypeError):
            pass
        heredocs = list(re.finditer(r"(?m)^cat > (?P<path>[^\s]+) <<'(?P<end>[A-Za-z_][A-Za-z0-9_]*)'\n"
                                   r"(?P<body>.*?)\n(?P=end)(?=\n|$)", command, re.S))
        replacement = command
        for heredoc in reversed(heredocs):
            try:
                target = Path(shlex.split(heredoc['path'])[0]).resolve()
                body = heredoc['body']
                assignment = json.loads(body)
                fields = list(re.finditer(r'"objective"\s*:\s*("(?:\\.|[^"\\])*")', body))
                if (target.parent == root.resolve() and target.suffix == '.json' and len(fields) == 1
                        and set(assignment) == {'objective', 'input_paths'}
                        and isinstance(assignment.get('input_paths'), list)
                        and all(isinstance(path, str) for path in assignment['input_paths'])
                        and isinstance(assignment.get('objective'), str)
                        and json.loads(fields[0][1]) == assignment['objective']):
                    field = fields[0]
                    replacement = (replacement[:heredoc.start('body') + field.start(1)] + json.dumps('[assignment text]')
                                   + replacement[heredoc.start('body') + field.end(1):])
            except (OSError, ValueError, TypeError, IndexError, AttributeError):
                pass
        if replacement != command:
            text = text.replace(command, replacement)
            for ascii_only in (False, True):
                text = text.replace(json.dumps(command, ensure_ascii=ascii_only)[1:-1],
                                    json.dumps(replacement, ensure_ascii=ascii_only)[1:-1])
        match = re.fullmatch(r"python3 - <<['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?\n(.*?)\n\1\s*",
                             command or "", re.S)
        if not match or (not re.match(r"python3 - <<['\"]", command)
                         and any(char in match[2] for char in "$`")):
            continue
        try:
            tree = ast.parse(match[2])
            parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
            names = {"Path", "print", "str", "len", "list", "sorted"}
            bound = names | {"json"} | {node.id for node in ast.walk(tree)
                                      if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)}
            replacements = []
            if any(isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.Lambda, ast.Delete))
                   or isinstance(node, ast.Import) and any(a.name != "json" or a.asname for a in node.names)
                   or isinstance(node, ast.ImportFrom) and ast.dump(node) != ast.dump(
                       ast.parse("from pathlib import Path").body[0])
                   or isinstance(node, (ast.Attribute, ast.Subscript)) and isinstance(node.ctx, ast.Store)
                   or isinstance(node, ast.Name) and (isinstance(node.ctx, ast.Store) and node.id in names | {"json"}
                                                     or isinstance(node.ctx, ast.Load) and node.id not in bound)
                   or isinstance(node, ast.Call) and not (
                       isinstance(node.func, ast.Name) and node.func.id in names
                       or isinstance(node.func, ast.Attribute) and node.func.attr in {
                           "loads", "dumps", "read_text", "write_text", "get", "keys", "items", "values"})
                   for node in ast.walk(tree)):
                continue
            def serialized(node):
                parent = parents.get(node)
                return (isinstance(parent, ast.Call) and isinstance(parent.func, ast.Attribute)
                        and isinstance(parent.func.value, ast.Name) and parent.func.value.id == "json"
                        and parent.func.attr == "dumps" and parent.args and parent.args[0] is node)

            objectives = []
            for mapping in (node for node in ast.walk(tree) if isinstance(node, ast.Dict)):
                if not serialized(mapping):
                    assignment = parents.get(mapping)
                    if (not isinstance(assignment, ast.Assign) or len(assignment.targets) != 1
                            or not isinstance(assignment.targets[0], ast.Name)):
                        continue
                    variable = assignment.targets[0]
                    uses = [node for node in ast.walk(tree) if isinstance(node, ast.Name)
                            and node.id == variable.id and node is not variable]
                    if not uses or any(not isinstance(node.ctx, ast.Load) or not serialized(node) for node in uses):
                        continue
                for key, value in zip(mapping.keys, mapping.values):
                    if (isinstance(key, ast.Constant) and key.value == "objective"
                            and all(isinstance(node, (ast.BinOp, ast.Add, ast.Name, ast.Load))
                                    or isinstance(node, ast.Constant) and isinstance(node.value, str)
                                    for node in ast.walk(value))):
                        objectives.append(value)
            objective_nodes = {node for value in objectives for node in ast.walk(value)}
            literals = set()
            for value in objectives:
                values = {node for node in ast.walk(value) if isinstance(node, ast.Constant)}
                for variable in (node for node in ast.walk(value) if isinstance(node, ast.Name)):
                    assignments = [node for node in ast.walk(tree) if isinstance(node, ast.Name)
                                   and node.id == variable.id and isinstance(node.ctx, ast.Store)]
                    assignment = parents.get(assignments[0]) if len(assignments) == 1 else None
                    if (not isinstance(assignment, ast.Assign) or len(assignment.targets) != 1
                            or not isinstance(assignment.value, ast.Constant) or not isinstance(assignment.value.value, str)
                            or any(node not in objective_nodes for node in ast.walk(tree) if isinstance(node, ast.Name)
                                   and node.id == variable.id and isinstance(node.ctx, ast.Load))):
                        break
                    values.add(assignment.value)
                else:
                    literals.update(values)
            for value in literals:
                normalized = punctuation.sub(r"\1", value.value)
                if normalized != value.value:
                    lines = match[2].encode().splitlines(keepends=True)
                    start = sum(map(len, lines[:value.lineno - 1])) + value.col_offset
                    end = sum(map(len, lines[:value.end_lineno - 1])) + value.end_col_offset
                    replacements.append((start, end, json.dumps(normalized, ensure_ascii=False).encode()))
            body = match[2].encode()
            for start, end, replacement in sorted(replacements, reverse=True):
                body = body[:start] + replacement + body[end:]
            replacement = command[:match.start(2)] + body.decode() + command[match.end(2):]
            text = text.replace(command, replacement)
            for ascii_only in (False, True):
                text = text.replace(json.dumps(command, ensure_ascii=ascii_only)[1:-1],
                                    json.dumps(replacement, ensure_ascii=ascii_only)[1:-1])
        except (SyntaxError, TypeError, ValueError):
            continue
    return text


def _is_codex_session_path(value: object) -> bool:
    return isinstance(value, str) and re.search(r"[/\\]\.codex[/\\]sessions[/\\]", value) is not None


def _verified_trace_retrieval_path(trace: dict[str, object]) -> Path | None:
    """Verify the trace locator's filename binds it to the worker thread."""
    value = trace.get("trace_retrieval")
    spawn, observation = trace.get("spawn"), trace.get("status_observation")
    if not isinstance(value, str) or not isinstance(spawn, dict) or not isinstance(observation, dict):
        return None
    thread_ids = (trace.get("thread_id"), spawn.get("thread_id"), observation.get("Thread ID"))
    if (any(not isinstance(thread, str) or not thread for thread in thread_ids)
            or len(set(thread_ids)) != 1
            or not re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", thread_ids[0])):
        return None
    try:
        path = Path(value).resolve(strict=True)
    except (OSError, ValueError, TypeError):
        return None
    # Codex names session files with their thread UUID; reject a different session before reading it.
    if (not _is_codex_session_path(str(path)) or path.suffix != ".jsonl"
            or thread_ids[0] not in path.name):
        return None
    return path


def _without_comparison_literals(text: str, row: dict) -> str:
    """Literal comparisons and string searches are data; file arguments remain audited."""
    for name, arguments in _tool_operations(row):
        command = arguments.get("cmd") if name == "exec_command" else None
        if not isinstance(command, str) or any(marker in command for marker in ("$", "`")):
            continue
        try:
            heredoc = re.fullmatch(r"(\S+) - <<['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?\n(.*?)\n\2\s*", command, re.S)
            tokens = [heredoc[1], "-c", heredoc[3]] if heredoc else shlex.split(command)
            if (len(tokens) < 3 or tokens[1] != "-c" or (tokens[0] != "python3"
                    and Path(tokens[0]).resolve() != Path(sys.executable).resolve())):
                continue
            if not _python_read_targets(tokens[2], argv=("-c", *tokens[3:])):
                continue
            tree, changed = ast.parse(tokens[2]), False
            for node in ast.walk(tree):
                values = ([node.left, *node.comparators] if isinstance(node, ast.Compare) else
                          node.args[:1] if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                          and node.func.attr == "find" else [])
                for value in values:
                    if (isinstance(value, ast.Constant) and isinstance(value.value, str)
                            and any(pattern.search(value.value) for _, pattern in FORBIDDEN_CONTEXT_PATTERNS)):
                        value.value = "[comparison data]"
                        changed = True
            if changed:
                sanitized = (command[:heredoc.start(3)] + ast.unparse(tree) + command[heredoc.end(3):]
                             if heredoc else shlex.join([*tokens[:2], ast.unparse(tree), *tokens[3:]]))
                for escape in (lambda value: value, lambda value: json.dumps(value, ensure_ascii=True)[1:-1],
                               lambda value: json.dumps(value, ensure_ascii=False)[1:-1]):
                    text = text.replace(escape(command), escape(sanitized))
        except (ValueError, OSError, SyntaxError):
            continue
    return text

def context_trace_errors(trace: dict[str, object], *, details: list[dict] | None = None,
                         input_paths: tuple[str, ...] = (), artifact_root: Path | None = None,
                         verified_trace_retrieval: Path | None = None,
                         verified_delivery_paths: tuple[str, ...] = ()) -> list[str]:
    """Reject unassigned historical input and all historical writes, preserving instruction echoes."""
    if not isinstance(trace, dict):
        return ["tool_trace_invalid"]
    errors: list[str] = []
    if str(trace.get("context_conformance", "")).strip().lower() in {"fail", "failed", "blocked"}:
        errors.append("context_conformance_failed")
    dispatch_content = _verified_dispatch_content(trace)
    assigned, root, snapshots = list(input_paths), artifact_root, []
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
        for row in packet.get("run_input_manifest", {}).get("inputs", []):
            if not isinstance(row, dict) or str(row.get("Status", "")).lower() in {"rejected", "denied", "superseded"}:
                continue
            if any(value in str(row.get("Expected use", "")).lower()
                   for value in ("do not read", "without reading", "preserve only")):
                continue
            hashes = {path: digest for path, digest in row.get("sha256_by_path", {}).items()
                      if path in row.get("paths", [])} if (isinstance(row.get("sha256_by_path"), dict)
                                                           and isinstance(row.get("paths"), list)) else {}
            if isinstance(row.get("path"), str) and isinstance(row.get("sha256"), str):
                hashes[row["path"]] = row["sha256"]
            for locator, digest in hashes.items():
                try:
                    path = Path(locator)
                    if (isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest)
                            and not path.is_symlink() and path.resolve().parent == root / "input_snapshots" / digest
                            and hashlib.sha256(path.read_bytes()).hexdigest() == digest):
                        snapshots.append(str(path))
                except (OSError, ValueError, TypeError):
                    continue
    for index, row in enumerate(trace.get("tool_trace", [])):
        if not isinstance(row, dict):
            continue
        for name, arguments in _tool_operations(row):
            if dispatch_content and name.rsplit("__", 1)[-1] in {"read_thread", "wait_threads"}:
                targets = arguments.get("targets", []) if name.endswith("wait_threads") else [arguments]
                if not isinstance(targets, list) or not targets:
                    errors.append("context_thread_target_invalid")
                    continue
                for target in targets:
                    thread = target.get("threadId") if isinstance(target, dict) else None
                    if not isinstance(thread, str) or "codex://threads/" + thread not in assigned:
                        errors.append("context_unassigned_thread_read:" + str(thread))
                continue
            if name != "exec_command":
                continue
            for target in _read_targets(arguments.get("cmd", ""), include_json=True):
                if target in assigned or target in _background_memory_paths(row):
                    continue
                try:
                    path = Path(target)
                    working_directory = arguments.get("workdir")
                    cwd = Path(working_directory) if isinstance(working_directory, (str, Path)) and working_directory else (
                        root.parent.parent if root else Path.cwd())
                    resolved = str((path if path.is_absolute() else cwd / path).resolve())
                except (OSError, RuntimeError, ValueError):
                    errors.append("context_read_target_invalid")
                    continue
                for label, pattern in FORBIDDEN_CONTEXT_PATTERNS:
                    match = pattern.search(target) or pattern.search(resolved)
                    if match:
                        errors.append("forbidden_context_reference:" + label)
                        if details is not None:
                            details.append({"error": errors[-1], "trace_path": ["tool_trace", str(index), "arguments", "cmd"],
                                            "reference": match.group().strip()})
                        break
                if root:
                    for reference in THOUGHT_PATH.findall(resolved):
                        relative = reference.split(".thoughts/", 1)[1]
                        if (relative.split("/", 1)[0] != root.name or "/runs/" in relative
                                or Path(resolved).name == "AGENTS.md"):
                            errors.append("forbidden_context_reference:archived_artifact")
                            if details is not None:
                                details.append({"error": errors[-1], "trace_path": ["tool_trace", str(index), "arguments", "cmd"],
                                                "reference": reference})
    listing_reads = {}
    listings = _listing_outputs(trace, read_prefixes=listing_reads, cwd=root.parent.parent if root else None)
    source_outputs, metadata_references = (_read_output_prefixes(trace, assigned + snapshots, root)
                                           if dispatch_content else (set(), {}))
    labeled_outputs = _labeled_packet_outputs(trace, root) if dispatch_content else {}
    pretty_outputs = _pretty_packet_reads(trace, root)
    instruction_contents = _instruction_contents(trace, root, assigned) if root else {}
    framework_searches = _framework_searches(trace, root) if root else {}
    call_sources = {row.get("call_id"): row.get("input", "") for row in trace.get("tool_trace", [])
                    if isinstance(row, dict) and row.get("type") == "custom_tool_call" and row.get("call_id")
                    and isinstance(row.get("input"), str)}
    reads = {row.get("call_id") for row in trace.get("tool_trace", [])
             if isinstance(row, dict) and row.get("call_id") and _authorized_read(row, assigned)}
    instruction_reads = {row.get("call_id"): _ancestor_instruction_reads(
                         row, root, include_probes=True, input_paths=assigned)
                         for row in trace.get("tool_trace", []) if root and isinstance(row, dict) and row.get("call_id")
                         and row.get("type") in {"function_call", "custom_tool_call"}}
    background_reads = {row["call_id"]: paths for row in trace.get("tool_trace", [])
                        if isinstance(row, dict) and row.get("call_id") and (paths := _background_memory_paths(row))}
    for path, value in _trace_strings(trace):
        if (path[:1] == ("delivery_ledger",) and value in verified_delivery_paths
                and (path == ("delivery_ledger", "provider_session")
                     or path[:2] == ("delivery_ledger", "identity_sessions"))):
            continue
        if path == ("trace_retrieval",) and verified_trace_retrieval is not None:
            if Path(value).resolve() == verified_trace_retrieval:
                continue
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
        before_metadata = candidate
        if output:
            references = metadata_references.get(row.get("call_id"), [])
            for reference in references[:]:
                candidate, replaced = re.subn(r"(?<![\w./\\-])" + re.escape(reference)
                                              + r"(?![\w./-]|\\(?![\"\\]))",
                                              "[current metadata]", candidate, count=1)
                if replaced:
                    references.remove(reference)
        metadata_only = candidate != before_metadata
        operational = _without_approval_justification(candidate, row, path) if not output else candidate
        if root and not output:
            operational = _without_comparison_literals(operational, row)
        metadata_only = metadata_only or operational != candidate
        candidate = operational
        background = _background_memory_paths(row) or (background_reads.get(row.get("call_id"), set()) if output else set())
        if output and background:
            # Registry entries can name old sources; seeing a pointer does not authorize following it.
            continue
        spellings = set(background)
        for registry in background:
            for prefix in ("$CODEX_HOME", "${CODEX_HOME}", "%CODEX_HOME%", "$env:CODEX_HOME", "${env:CODEX_HOME}"):
                if registry.startswith(prefix):
                    spellings.update(registry.replace(prefix, prefix + quote, 1) for quote in ('"', "'"))
        spellings.update(json.dumps(value)[1:-1] for value in tuple(spellings))
        for spelling in sorted(spellings, key=len, reverse=True):
            candidate = candidate.replace(spelling, "[background guidance]")
        if root and not output:
            normalized = _without_prose_root_punctuation(candidate, row, root)
            metadata_only = metadata_only or normalized != candidate
            candidate = normalized
        call_contents = instruction_contents.get(row.get("call_id"), {})
        ancestor_instruction_output = output and bool(call_contents.get("ancestor"))
        if output:
            labeled = labeled_outputs.get(row.get("call_id"))
            if labeled and candidate == labeled[0]:
                candidate = candidate.replace(labeled[1], '"[current packet archive reference]"', 1)
            source = call_sources.get(row.get("call_id"), "")
            if row.get("call_id") in pretty_outputs:
                candidate = _without_pretty_reentry_reference(candidate, pretty_outputs[row["call_id"]])
            candidate = "".join(line[:-4] + "\n" if line.startswith("---") and line.endswith("---\n")
                                and json.dumps(line[3:-4], ensure_ascii=False) in source else line
                                for line in candidate.splitlines(keepends=True))
            if row.get("call_id") in framework_searches:
                candidate = _without_verified_search_lines(candidate, framework_searches[row["call_id"]])
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
            checked = candidate if (metadata_only or background or ancestor_instruction_output or label == "archived_artifact"
                                    or output and row.get("call_id") in framework_searches
                                    or _authorized_read(row, assigned)
                                    or output and row.get("call_id") in reads) else value
            if label == "archived_artifact" and listing:
                continue
            if label == "memory_citation" and output:
                definition = '("memory_citation", re.compile(r"(?i)<' + 'oai-mem-citation>")),'
                checked = checked.replace(definition, "")
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


def _without_python_script_heredoc_data(command: str, package: Path) -> str:
    """Exclude quoted data sent to packaged scripts, not shell or interpreter input."""
    pattern = re.compile(r"(?ms)^(?P<head>[^\n]*<<'(?P<end>[A-Za-z_][A-Za-z0-9_]*)'[^\n]*)\n"
                         r"(?P<body>.*?)^(?P=end)(?=\n|$)")
    def remove(match):
        head = match["head"]
        if any(char in head for char in ";|&`$") or head.count("<<") != 1:
            return match[0]
        try:
            tokens = shlex.split(head.split("<<", 1)[0])
        except ValueError:
            return match[0]
        if (len(tokens) < 2 or not re.fullmatch(r"python(?:3(?:\.\d+)?)?", Path(tokens[0]).name)
                or not tokens[1].endswith(".py") or Path(tokens[1]).is_symlink()
                or Path(tokens[1]).resolve().parent != (package / "scripts").resolve()):
            return match[0]
        return head + "\n" + match["end"]
    return pattern.sub(remove, command)


def _shell_substitution_fragments(command: str) -> list[str]:
    """Find shell command substitutions without treating single-quoted text as shell code."""
    fragments: list[str] = []

    def scan(text: str, *, here_text: bool = False) -> None:
        def visit(start: int, terminator: str | None = None) -> int | None:
            i, quote, parentheses = start, None, 0
            while i < len(text):
                char = text[i]
                if char == "\\" and quote != "'":
                    i += 2
                    continue
                if not here_text or terminator:
                    if char == "'" and quote != '"':
                        quote = None if quote == "'" else "'"
                        i += 1
                        continue
                    if char == '"' and quote != "'":
                        quote = None if quote == '"' else '"'
                        i += 1
                        continue
                if quote == "'":
                    i += 1
                    continue
                if ((not here_text or terminator) and not quote and char == "#"
                        and (i == start or text[i - 1] in " \t\r\n;|&()")):
                    newline = text.find("\n", i)
                    i = len(text) if newline < 0 else newline + 1
                    continue
                if terminator and char == terminator and not quote:
                    if terminator == ")" and parentheses:
                        parentheses -= 1
                    else:
                        return i
                elif terminator == ")" and char == "(" and not quote:
                    parentheses += 1
                if (text.startswith("$(", i) or
                        (not quote and (not here_text or terminator)
                         and text[i:i + 2] in {"<(", ">("})):
                    end = visit(i + 2, ")")
                    if end is None:
                        return None
                    fragments.append(text[i + 2:end])
                    i = end + 1
                    continue
                if char == "`":
                    end = visit(i + 1, "`")
                    if end is None:
                        return None
                    fragments.append(text[i + 1:end])
                    i = end + 1
                    continue
                i += 1
            return None
        visit(0)

    # Each unquoted here-document is expanded, including bodies overridden by a later redirection.
    heredoc = re.compile(r"(?<!<)<<(?P<strip>-?)[ \t]*(?P<delimiter>"
                         r"'[A-Za-z_][A-Za-z0-9_]*'|\"[A-Za-z_][A-Za-z0-9_]*\"|"
                         r"\\[A-Za-z_][A-Za-z0-9_]*|[A-Za-z_][A-Za-z0-9_]*)(?=$|[ \t\r\n;&|<>])")

    def unquoted(line: str, end: int) -> bool:
        quote, escaped = None, False
        for index, char in enumerate(line[:end]):
            if escaped:
                escaped = False
            elif char == "\\" and quote != "'":
                escaped = True
            elif char == "'" and quote != '"':
                quote = None if quote == "'" else "'"
            elif char == '"' and quote != "'":
                quote = None if quote == '"' else '"'
            elif (char == "#" and not quote and
                  (index == 0 or line[index - 1] in " \t;|&()")):
                return False
        return not quote and not escaped

    lines, outer = command.splitlines(keepends=True), []
    index = 0
    while index < len(lines):
        line = lines[index]
        matches = [match for match in heredoc.finditer(line) if unquoted(line, match.start())]
        outer.append(line)
        index += 1
        if not matches:
            continue
        try:
            prefix = _shell_executable_words(shlex.split(line[:matches[0].start()]))
        except ValueError:
            prefix = []
        shell_input = (bool(prefix) and Path(prefix[0]).name in {"bash", "sh", "zsh"}
                       and not any(value in {"-c", "-lc"} for value in prefix[1:]))
        for number, match in enumerate(matches):
            raw = match["delimiter"]
            quoted = raw[0] in "'\"\\"
            delimiter = raw[1:-1] if raw[0] in "'\"" else raw[1:] if quoted else raw
            content = []
            while index < len(lines):
                current = lines[index]
                index += 1
                line_end = current.rstrip("\r\n")
                if (line_end.lstrip("\t") if match["strip"] else line_end) == delimiter:
                    break
                content.append(current)
            if not quoted:
                scan("".join(content), here_text=True)
            elif shell_input and number == len(matches) - 1:
                scan("".join(content))
    scan("".join(outer))
    return fragments


def _shell_executable_words(words: list[str]) -> list[str]:
    """Unwrap assignments and common shell command wrappers before classifying execution."""
    words = list(words)
    while words:
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]):
            words.pop(0)
            continue
        name = Path(words[0]).name
        if name == "env":
            words.pop(0)
            while words:
                option = words[0]
                if option == "--":
                    words.pop(0)
                    break
                if option in {"-0", "--null", "--help", "--version"}:
                    return []
                if option in {"-i", "--ignore-environment"} or re.match(
                        r"^(?:[A-Za-z_][A-Za-z0-9_]*=|--unset=|--chdir=)", option):
                    words.pop(0)
                elif option in {"-u", "--unset", "-C", "--chdir"}:
                    if len(words) < 2:
                        return []
                    del words[:2]
                elif option in {"-S", "--split-string"} and len(words) >= 2:
                    words = shlex.split(words[1]) + words[2:]
                    break
                else:
                    break
            continue
        if name == "command":
            words.pop(0)
            while words and words[0] in {"-p", "--"}:
                words.pop(0)
            if words and words[0] in {"-v", "-V"}:
                return []  # command -v/-V describes commands instead of executing them.
            continue
        break
    return words


def planning_permission_errors(trace: dict) -> list[str]:
    """Enforce planning permissions and explicit user restrictions."""
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
    contract = packet.get("worker_contract") or {}
    authorized = set()
    denied = set()
    for row in packet.get("run_input_manifest", {}).get("inputs", []):
        if row.get("Authority") == "User" and row.get("Classification") == "execution restriction":
            denied.update(row.get("Denied operations", []))
        if (row.get("Classification") == "execution authorization" and row.get("Status") == "Approved"
                and row.get("Authority") == "User"):
            operations = row.get("Authorized operations", [])
            if isinstance(operations, list) and all(isinstance(value, str) and value in {"test_run", "build_run"}
                                                    for value in operations):
                authorized.update(operations)
    explicit_test = "test_run" in authorized
    if (Path(str(contract.get("contract", ""))).name == "techops_issue_remediation.md"
            and packet.get("agent") in {"dependency_analyst", "solution_architect"}):
        authorized.add("test_run")
    authorized.difference_update(denied)
    if "source_write" in denied:
        baseline = packet.get("coordinator_execution", {}).get("source_read_only_baseline")
        try:
            from review_evidence import source_tree_fingerprint
        except ModuleNotFoundError:
            from scripts.review_evidence import source_tree_fingerprint
        try:
            checkout = Path(packet["coordinator_execution"]["source_checkout"])
            if not baseline or source_tree_fingerprint(checkout) != baseline:
                errors.append("planning_source_write_not_authorized")
        except (OSError, ValueError, KeyError, subprocess.SubprocessError):
            errors.append("planning_source_restriction_unverified")
    for row in trace.get("tool_trace", []):
        for tool, arguments in _tool_operations(row):
            if tool != "exec_command":
                continue
            command = arguments.get("cmd", "")
            if not isinstance(command, str):
                errors.append("planning_command_invalid")
                continue
            try:
                package = Path(packet.get("framework_package", {}).get("root", ROOT))
                command = _without_python_script_heredoc_data(command, package)
                try:
                    tokens = shlex.split(command)
                except ValueError:
                    tokens = []
                if len(tokens) == 3 and Path(tokens[0]).name in {"bash", "sh", "zsh"} and tokens[1] in {"-lc", "-c"}:
                    command = tokens[2]
                command = _without_python_script_heredoc_data(command, package)
                parts = []
                for fragment in [command, *_shell_substitution_fragments(command)]:
                    try:
                        lexer = shlex.shlex(fragment, posix=True, punctuation_chars=";&|<>\n")
                        lexer.whitespace = " \t\r"
                        lexer.whitespace_split = True
                        part = []
                        for token in lexer:
                            if token in {";", "&", "|", "&&", "||", "\n"}:
                                parts.append(part)
                                part = []
                            else:
                                part.append(token)
                        parts.append(part)
                    except ValueError:
                        continue

                for part in parts:
                    part = _shell_executable_words(part)
                    if not part:
                        continue
                    name = Path(part[0]).name
                    operands = [token for token in part[1:] if not token.startswith("-") and token != "--"]
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
                    elif operation == "test_run" and not explicit_test:
                        broad = (any(value.endswith("/...") for value in operands)
                                 or name in {"npm", "pnpm", "yarn", "make"}
                                 or name in {"pytest", "pytest-3"} and not operands
                                 or name in {"python", "python3"} and operands == ["pytest"]
                                 or name in {"python", "python3"} and "discover" in operands)
                        if broad:
                            errors.append("planning_diagnostic_test_not_focused")
            except RecursionError:
                errors.append("planning_command_invalid")
            except (ValueError, TypeError):
                continue
    return list(dict.fromkeys(errors))


def trace_errors(trace: dict[str, object], *, require_freshness: bool = False,
                 context_details: list[dict] | None = None) -> list[str]:
    if not isinstance(trace, dict):
        return ["tool_trace_invalid"]
    retrieval = trace.get("trace_retrieval")
    verified_retrieval = _verified_trace_retrieval_path(trace)
    if _is_codex_session_path(retrieval) and verified_retrieval is None:
        return ["worker_trace_session_mismatch"]
    if not isinstance(trace.get("events", []), list):
        return ["runtime_event_invalid"]
    launch_errors = trace.get("launch_errors", [])
    if not isinstance(launch_errors, list) or any(not isinstance(error, str) for error in launch_errors):
        return ["worker_launch_errors_invalid"]
    errors: list[str] = list(launch_errors)
    verified_delivery_paths = ()
    observation = trace.get("status_observation", {})
    if isinstance(observation, dict) and str(observation.get("Dispatch consumption evidence", "")).startswith("native-message:"):
        try:
            try:
                from worker_runtime_evidence import native_in_turn_delivery
            except ModuleNotFoundError:
                from scripts.worker_runtime_evidence import native_in_turn_delivery
            try:
                from provider_runtime import read_runtime_events
            except ModuleNotFoundError:
                from scripts.provider_runtime import read_runtime_events
            origin = trace["delivery_ledger"]
            ledger = read_runtime_events(Path(origin["provider_session"]), origin["parent_thread_id"],
                                         origin["run_started_at"], tuple(Path(p) for p in origin["identity_sessions"]))
            verified = native_in_turn_delivery(ledger, Path(trace["trace_retrieval"]), observation)
            if verified != observation["Dispatch consumption evidence"]:
                raise ValueError("delivery evidence does not match")
            if _is_codex_session_path(origin["provider_session"]):
                root = Path(trace["spawn"]["dispatch_file"]).resolve().parent
                bindings = json.loads((root / "role_bindings.json").read_text())
                parent, contract = bindings["parent_context"], bindings["runtime_evidence"]
                if (origin["provider_session"] != parent["provider_session"]
                        or origin["parent_thread_id"] != parent["parent_thread_id"]
                        or origin["run_started_at"] != contract["run_started_at"]
                        or origin["identity_sessions"] != contract.get("identity_sessions", [])):
                    raise ValueError("delivery ledger does not match current run")
                verified_delivery_paths = (origin["provider_session"], *origin["identity_sessions"])
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            errors.append("worker_dispatch_consumption_unverified")
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
    errors.extend(context_trace_errors(trace, details=context_details,
                                       verified_trace_retrieval=verified_retrieval,
                                       verified_delivery_paths=verified_delivery_paths))
    return list(dict.fromkeys(errors))


TECHOPS_CHECKS = {"issue_scope", "history_reconciliation", "plan_dependencies", "regression_fixture"}

THOUGHT_PATH = re.compile(r"(?:/[A-Za-z0-9_.-]+)*/?\.thoughts/[^\s\"'<>`\\;,)}\]]+")
