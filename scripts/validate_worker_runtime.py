#!/usr/bin/env python3
"""Validate worker binding delivery and unsafe runtime transitions."""

from __future__ import annotations

import argparse
import ast
import io
import hashlib
import json
import re
import shlex
import tempfile
import tokenize
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
V40_RUNTIME_FIXTURE = ROOT / "tests" / "fixtures" / "v40_sentry_worker_runtime.json"
V41_CONTEXT_TRACE_FIXTURE = ROOT / "tests" / "fixtures" / "v41_sentry_context_trace.json"
ACTIVE_STATUSES = {"pending_init", "running", "in_progress", "awaiting_dependency"}
TERMINAL_STATUSES = {"completed", "failed", "stopped", "interrupted", "cancelled"}
DESTRUCTIVE_TRANSITIONS = {"interrupt", "close", "replace"}
DELIVERY_WORKERS = {"implement": "implementer", "review": "reviewer", "validate": "tester", "handoff": "documenter"}
TRACE_METADATA_KEYS = {
    "description", "expected_errors", "source_task", "source_thread", "fixture", "schema_version",
}
FORBIDDEN_CONTEXT_PATTERNS = (
    ("memory_path", re.compile(r"(?i)(?:^|[/\\])memory\.md(?:$|[/\\])")),
    ("memory_directory", re.compile(r"(?i)(?:^|[/\\])\.codex[/\\]memories(?:$|[/\\])")),
    ("rollout_summary", re.compile(r"(?i)(?:^|[/\\])rollout_summaries(?:$|[/\\])")),
    ("archived_artifact", re.compile(r"(?i)(?:^|[\s/\\\"'])\.thoughts[/\\][^/\\]+[/\\]runs(?:$|[\s/\\\"'])")),
    ("archived_artifact", re.compile(r"(?i)\.thoughts[/\\][^/\\\s]+(?:[_-]v[0-9]+|[_-]backup|[_-]archive)(?:$|[/\\\s])")),
    ("memory_citation", re.compile(r"(?i)<oai-mem-citation>")),
)


def prepared_package_errors(root: Path) -> list[str]:
    """Reject execution from a different package than the prepared run."""
    try:
        manifest = json.loads((root / "role_bindings.json").read_text())
        package = manifest.get("framework_package")
        if package is None:
            return []  # Legacy packets retain their existing validation path.
        if (Path(package["root"]).resolve() != ROOT
                or package["plugin_sha256"] != hashlib.sha256((ROOT / ".codex-plugin/plugin.json").read_bytes()).hexdigest()):
            return ["prepared_framework_package_mismatch: prepare recovery from the selected package"]
        return []
    except (OSError, ValueError, TypeError, KeyError):
        return ["prepared_framework_package_invalid"]


def worker_binding(bindings: dict, worker: str) -> str:
    if worker in bindings["bindings"]:
        return worker
    matches = [role for role, contract in bindings.get("worker_contracts", {}).items()
               if isinstance(contract, dict) and contract.get("worker") == worker]
    if not matches and DELIVERY_WORKERS.get(worker) in bindings["bindings"]:
        return DELIVERY_WORKERS[worker]
    if len(matches) != 1:
        raise ValueError("worker_binding_identity_invalid")
    return matches[0]


def _pending_rejections(root: Path) -> dict:
    ledger_path = root / "runtime_dispatches.json"
    if not ledger_path.exists():
        return {}
    ledger = json.loads(ledger_path.read_text())
    current = json.loads((root / "finalization_packet.json").read_text())["identity"]["Run ID"]
    pending = ledger.get("rejected_results", {})
    if not isinstance(pending, dict):
        raise ValueError("worker_rejection_receipt_invalid")
    for receipt in pending.values():
        path = Path(receipt["trace"])
        if (receipt["run_id"] != current or path.resolve().parent != root.resolve()
                or hashlib.sha256(path.read_bytes()).hexdigest() != receipt["sha256"]):
            raise ValueError("worker_rejection_receipt_invalid")
    return pending


def _recovery_errors(path: Path, role: str, handle: str, dispatch: str, provider_status: str) -> list[str]:
    try:
        trace = json.loads(path.read_text())
        current = json.loads((path.parent / "finalization_packet.json").read_text())
        bindings = json.loads((path.parent / "role_bindings.json").read_text())
        if (trace.get("run_id") != current["identity"]["Run ID"]
                or worker_binding(bindings, trace["spawn"]["agent"]) != role):
            return ["rejected_result_current_binding_required"]
        errors = rejected_result_errors(trace, handle, dispatch)
        error = transition_error("replace", provider_status, rejected_result=not errors)
        if error:
            errors.append(error)
        if role in current.get("activation_repairs", {}):
            errors.append("activation_repair_limit_reached")
        return errors
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        return ["rejected_result_trace_invalid:" + str(error)]


def activation_packet_errors(path: Path, expected_agent: str, expected_sha256: str,
                             *, rejected_trace_sha256: str | None = None) -> list[str]:
    if not path.is_file():
        return ["activation_packet_unavailable"]
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha256:
        return ["activation_packet_hash_mismatch"]
    try:
        bundle = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return ["activation_packet_invalid"]
    packets = bundle.get("packets")
    if not isinstance(packets, dict) or not isinstance(packets.get(expected_agent), dict):
        return ["activation_packet_agent_unavailable"]
    packet = packets[expected_agent]
    errors: list[str] = prepared_package_errors(path.parent) if (path.parent / "role_bindings.json").is_file() else []
    failure_path = path.parent / "finalization_failure.json"
    if failure_path.is_file():
        try:
            failure = json.loads(failure_path.read_text())
            if failure.get("status") == "failed" and (failure.get("stage") == "workflow"
                    or int(failure.get("attempt_count", 0)) >= 2):
                errors.append("worker_activation_requires_planning_recovery")
        except (ValueError, TypeError):
            errors.append("worker_activation_failure_receipt_invalid")
    try:
        for role, receipt in _pending_rejections(path.parent).items():
            if role != expected_agent or receipt["sha256"] != rejected_trace_sha256:
                errors.append("worker_activation_rejected_result_pending:" + role)
    except (OSError, ValueError, TypeError, KeyError) as error:
        errors.append("worker_rejection_receipt_invalid:" + str(error))
    if packet.get("required_prefix") != "Coordinator initialization: complete":
        errors.append("activation_packet_prefix_invalid")
    if packet.get("agent") != expected_agent:
        errors.append("activation_packet_agent_mismatch")
    definition = Path(str(packet.get("definition", "")))
    if not definition.is_file():
        errors.append("provider_definition_unavailable")
    elif hashlib.sha256(definition.read_bytes()).hexdigest() != packet.get("definition_sha256"):
        errors.append("provider_definition_hash_mismatch")
    if not str(packet.get("developer_instructions", "")).strip():
        errors.append("provider_instructions_unavailable")
    if not packet.get("model") or not packet.get("effort"):
        errors.append("provider_binding_incomplete")
    contract = packet.get("worker_contract")
    if "run_id" in packet or "finalization_packet" in packet:
        current_path = path.parent / "finalization_packet.json"
        try:
            current = json.loads(current_path.read_text())
            if (not packet.get("run_id") or packet["run_id"] != current["identity"]["Run ID"]
                    or packet.get("finalization_packet") != str(current_path.resolve())):
                errors.append("worker_run_identity_mismatch")
        except (OSError, ValueError, KeyError, TypeError):
            errors.append("worker_run_identity_unavailable")
    elif isinstance(contract, dict) and "run_id" in str(contract.get("result_instructions", "")):
        errors.append("worker_run_identity_not_delivered")
    if isinstance(contract, dict) and "output" in contract:
        for field in ("output", "result", "implementation_plan"):
            if field in contract:
                output = Path(str(contract[field]))
                if not output.is_absolute() or output.resolve().parent != path.parent.resolve():
                    errors.append(f"worker_{field}_outside_current_run")
    budget_path = path.parent / "run_budget.json"
    if budget_path.is_file():
        try:
            budget = json.loads(budget_path.read_text())
            activation_deadline = datetime.fromisoformat(
                str(budget["activation_deadline_at"]).replace("Z", "+00:00")
            )
            if activation_deadline.tzinfo is None:
                raise ValueError
            if datetime.now(UTC) >= activation_deadline.astimezone(UTC):
                errors.append("run_budget_finalization_reserve")
        except (KeyError, ValueError, json.JSONDecodeError, OSError):
            errors.append("run_budget_invalid")
    input_manifest = packet.get("run_input_manifest")
    if not isinstance(input_manifest, dict):
        errors.append("run_input_manifest_not_delivered")
    else:
        if input_manifest.get("status") != "explicit":
            errors.append("run_input_manifest_required")
        if not input_manifest.get("path") or not input_manifest.get("sha256"):
            errors.append("run_input_manifest_metadata_incomplete")
        if not isinstance(input_manifest.get("inputs"), list) or not input_manifest["inputs"]:
            errors.append("run_input_manifest_inputs_missing")
        manifest_path = Path(str(input_manifest.get("path", ""))).expanduser()
        if manifest_path.is_file():
            if hashlib.sha256(manifest_path.read_bytes()).hexdigest() != str(input_manifest.get("sha256")):
                errors.append("run_input_manifest_hash_mismatch")
        elif manifest_path:
            errors.append("run_input_manifest_unavailable")
    bindings_path = path.parent / "role_bindings.json"
    if expected_agent == "documenter" and bindings_path.is_file():
        try:
            bindings = json.loads(bindings_path.read_text())
        except (OSError, json.JSONDecodeError):
            errors.append("role_bindings_invalid")
        else:
            if isinstance(bindings, dict) and bindings.get("playbook") == "feature_delivery":
                try:
                    current = json.loads((path.parent / "finalization_packet.json").read_text())
                    if bindings.get("lifecycle") and current.get("identity", {}).get("Lifecycle") != bindings["lifecycle"]:
                        errors.append("feature_delivery_packet_lifecycle_mismatch")
                except (OSError, ValueError, TypeError, AttributeError):
                    errors.append("feature_delivery_packet_invalid")
                try:
                    from finalize_work_record import feature_delivery_pre_handoff_errors
                except ModuleNotFoundError:  # Imported as scripts.validate_worker_runtime from the repository root.
                    from scripts.finalize_work_record import feature_delivery_pre_handoff_errors
                errors.extend(feature_delivery_pre_handoff_errors(path.parent / "finalization_packet.json"))
            elif isinstance(bindings, dict) and bindings.get("playbook") == "techops_issue_remediation":
                packet_path = path.parent / "finalization_packet.json"
                try:
                    planning = json.loads(packet_path.read_text())
                    if planning.get("identity", {}).get("Lifecycle") == "planning":
                        completed = {row.get("Worker") for row in planning.get("worker_results", [])
                                     if row.get("Outcome") == "complete"}
                        required = {"issue-evidence", "failure-path", "fix-design"}
                        if planning.get("identity", {}).get("Executed profile") == "deep":
                            required.update({"repository-integration", "planning-review"})
                        if not required <= completed:
                            errors.append("techops_pre_handoff_workers_incomplete")
                        try:
                            from finalize_work_record import _techops_planning_contract_errors
                        except ModuleNotFoundError:
                            from scripts.finalize_work_record import _techops_planning_contract_errors
                        errors.extend(_techops_planning_contract_errors(planning, packet_path, pre_handoff=True))
                except (OSError, ValueError, TypeError, AttributeError):
                    errors.append("techops_pre_handoff_packet_invalid")
    return errors


def activation_message(packet: dict, assignment: dict) -> str:
    """Serialize the binding once; assignments cannot override prepared outputs or policy."""
    if (not isinstance(assignment, dict) or not isinstance(assignment.get("objective"), str)
            or not assignment["objective"].strip()
            or set(assignment) - {"objective", "input_paths"}
            or not isinstance(assignment.get("input_paths", []), list)
            or not all(isinstance(path, str) and path.strip() for path in assignment.get("input_paths", []))):
        raise ValueError("expected objective and optional input_paths only")
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
            + f"Role: {packet['agent']}; model/effort: {packet['model']} / {packet['effort']}.\n"
            + f"Run ID: {packet['run_id']}.\n"
            + f"Read the complete activation instructions and typed assignment at {path.resolve()}.\n"
            + f"Verify its SHA256 is {digest} before analytical work; on mismatch stop and report it.\n"
            + "The file is the operative role, input, output and policy contract. Read it in full; do not substitute "
              "this launch notice for those instructions. Do not rerun Coordinator initialization.")


def delivery_start_errors(path: Path, implementer_handle: str, provider_status: str) -> list[str]:
    """Check the current approved plan and independent graph before an Implementer edits."""
    try:
        from review_evidence import applicability_errors
    except ModuleNotFoundError:
        from scripts.review_evidence import applicability_errors
    try:
        packet = json.loads(path.read_text())
        identity = packet["identity"]
        if (Path(str(identity.get("Playbook / version", "")).split(" / ", 1)[0]).stem != "feature_delivery"
                or identity.get("Lifecycle") != "remediation"):
            return ["feature_implementation_requires_remediation_reentry"]
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
        errors = applicability_errors(plan.read_text())
        if provider_status not in {"running", "in_progress"}:
            errors.append("active_implementer_required:expected running or in_progress; received " + provider_status)
        roles = DELIVERY_WORKERS
        handles = []
        for worker, role in roles.items():
            rows = [row for row in packet.get("workers", []) if row.get("Worker") == worker]
            if len(rows) != 1 or str(rows[0].get("Role", "")).lower() != role:
                errors.append("delivery_worker_registration_required:" + worker)
                continue
            row = rows[0]
            expected = {"in_progress", "running"} if worker == "implement" else {"awaiting_dependency", "in_progress", "running"}
            if row.get("Outcome") not in expected or not str(row.get("Depends on", "")).strip():
                errors.append("delivery_worker_activation_required:" + worker)
            if worker != "handoff":
                match = re.search(r"Provider handle[: ]+(/root/[a-z0-9_]+(?:/[a-z0-9_]+)*|"
                                  r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})(?=\s|;|$)",
                                  str(row.get("Assigned inputs", "")))
                if not match:
                    errors.append("delivery_worker_provider_handle_required:" + worker)
                else:
                    handles.append(match[1])
                    if worker == "implement" and match[1] != implementer_handle:
                        errors.append("implementer_handle_mismatch")
        if len(handles) != len(set(handles)):
            errors.append("independent_delivery_handles_required")
        return errors
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        return ["delivery_activation_invalid:" + str(error)]


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
    """A completed task can be replaced only with its independently rejected current result."""
    if not isinstance(trace, dict):
        return ["rejected_result_trace_invalid"]
    observation = trace.get("status_observation", {})
    if not isinstance(observation, dict) or not isinstance(trace.get("spawn"), dict):
        return ["rejected_result_trace_invalid"]
    errors = terminal_observation_errors([observation], [handle])
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


def terminal_observation_errors(observations: object, handles: list[str]) -> list[str]:
    """Validate current status reads, including workers omitted by live inventory."""
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
        if str(row.get("Provider status", "")).lower() not in {"completed", "idle"}:
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
                if row.get("Latest turn status") != "completed":
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


TECHOPS_CHECKS = {"issue_scope", "history_reconciliation", "plan_dependencies", "regression_fixture"}


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
            if str(key) in TRACE_METADATA_KEYS:
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
            listing = (tool in {"ls", "pwd"} or (tool == "rg" and "--files" in args)
                       or (tool == "find" and not set(args) & {
                           "-exec", "-execdir", "-ok", "-okdir", "-delete", "-fprint", "-fprint0", "-fprintf"}))
            filter_only = (previous == "|" and (
                (tool in {"head", "tail"} and all(re.fullmatch(r"-?(?:n|[0-9]+)", arg) for arg in args[1:]))
                or (tool in {"rg", "grep"} and len(args) == 2 and not args[1].startswith("-"))))
            if not listing and not filter_only:
                return False
            previous = ""
        return bool(tokens)
    except ValueError:
        return False


def _listing_outputs(trace: dict) -> set[tuple[str, ...]]:
    outputs, calls = set(), set()
    rows = trace.get("tool_trace", [])
    if not isinstance(rows, list):
        return outputs
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        prefix = ("tool_trace", str(index))
        arguments = row.get("arguments", {})
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except ValueError:
                arguments = {}
        known_exec = row.get("tool") == "exec_command" or (
            row.get("type") == "function_call" and row.get("name") == "exec_command")
        if known_exec and isinstance(arguments, dict) and _listing_command(arguments.get("cmd")):
            if row.get("call_id"):
                calls.add(row["call_id"])
            outputs.update({prefix + ("result",), prefix + ("output",), prefix + ("arguments", "output")})
        if row.get("type") == "function_call_output" and row.get("call_id") in calls:
            outputs.add(prefix + ("output",))
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


THOUGHT_PATH = re.compile(r"(?:/[A-Za-z0-9_.-]+)*/?\.thoughts/[^\s\"'<>`\\;,)}\]]+")


def _authorized_read(row: dict, assigned: list[str]) -> bool:
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


def _literal_argument(node: ast.AST):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Dict):
        return {(key.id if isinstance(key, ast.Name) else _literal_argument(key)): _literal_argument(value)
                for key, value in zip(node.keys, node.values)}
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_literal_argument(value) for value in node.elts]
    if isinstance(node, ast.Name) and node.id in {"true", "false", "null"}:
        return {"true": True, "false": False, "null": None}[node.id]
    raise ValueError("nonliteral tool argument")


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
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
        operations, index = [], 0
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
                argument = tokenize.untokenize([(token.type, token.string) for token in tokens[start:index - 1]])
                value = _literal_argument(ast.parse(argument, mode="eval").body)
                if not isinstance(value, dict):
                    return []
                operations.append((name, value))
                continue
            if tokens[index].type == tokenize.ERRORTOKEN and tokens[index].string.strip():
                return []
            index += 1
        return operations
    except (ValueError, SyntaxError, TypeError, tokenize.TokenError, IndentationError):
        return []


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
    python = re.fullmatch(r"python3 - <<['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?\n(.*?)\n\1\s*", command, re.S)
    if python:
        try:
            return _python_read_targets(python[2])
        except (SyntaxError, TypeError, ValueError):
            return []
    hashed_read = re.fullmatch(r"(?:sha256sum|shasum -a 256) ([^\s;&|<>]+) && cat \1", command)
    if hashed_read:
        return [hashed_read[1]]
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
        if not tokens or ";" in tokens or "$" in command:
            return []
        if tokens[0] == "cat" and len(tokens) > 1 and all(not arg.startswith("-") for arg in tokens[1:]):
            return tokens[1:]
        if (len(tokens) > 3 and tokens[:2] == ["sed", "-n"]
                and re.fullmatch(r"[0-9]+(?:,[0-9]+)?p", tokens[2])):
            return tokens[3:]
        return []
    except ValueError:
        return []


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
                safe = safe and bool(targets) and all(
                    (path.resolve().parent == root and path.is_file()
                     and path.resolve() != Path(trace["spawn"]["dispatch_file"]).resolve()) or str(path) in assigned
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
    for row in trace.get("tool_trace", []):
        for name, arguments in _tool_operations(row):
            if name != "exec_command":
                continue
            cwd = Path(arguments.get("workdir", bindings["execution_repository"]))
            for target in _read_targets(arguments.get("cmd")):
                path = Path(target) if Path(target).is_absolute() else cwd / target
                path = path.resolve()
                if path.parent != root.resolve() or not path.is_file():
                    continue
                proof = {"dispatch_file": str(path), "dispatch_file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                         "binding_agent": role, "dispatch_proof_source": "provider_instruction_read"}
                candidate = {**trace, "spawn": {**trace["spawn"], **proof}}
                content = _verified_dispatch_content(candidate)
                if content and row.get("call_id"):
                    for output in trace.get("tool_trace", []):
                        if (output.get("type") in {"function_call_output", "custom_tool_call_output"}
                                and output.get("call_id") == row["call_id"]
                                and any(content in value for _, value in _trace_strings({"tool_trace": [output]}))):
                            return proof
    return {}



def _ancestor_instruction_reads(row: dict, root: Path) -> list[str]:
    allowed = {parent / "AGENTS.md" for parent in (root, root.parent, root.parent.parent)}
    reads = []
    for name, arguments in _tool_operations(row):
        if name != "exec_command":
            continue
        command = arguments.get("cmd", "")
        if not isinstance(command, str):
            continue
        targets = _read_targets(command)
        loop = re.match(
            r'^for (?P<var>[A-Za-z_]\w*) in (?P<paths>[^;\n]+); do if '
            r'(?:\[ -f "\$(?P=var)" \]|test -f "\$(?P=var)"); then '
            r'echo "--- \$(?P=var)"; cat "\$(?P=var)"; fi; done(?=;|\n|$)', command)
        if loop:
            try:
                targets = shlex.split(loop["paths"])
            except ValueError:
                continue
        cwd = Path(arguments.get("workdir", root.parent.parent))
        for target in targets:
            if any(char in target for char in "$`*"):
                continue
            path = Path(target)
            resolved = (path if path.is_absolute() else cwd / path).resolve()
            if resolved in allowed:
                reads.append(target)
    return reads


def context_trace_errors(trace: dict[str, object]) -> list[str]:
    """Reject unassigned historical input and all historical writes, preserving instruction echoes."""
    if not isinstance(trace, dict):
        return ["tool_trace_invalid"]
    errors: list[str] = []
    if str(trace.get("context_conformance", "")).strip().lower() in {"fail", "failed", "blocked"}:
        errors.append("context_conformance_failed")
    listings = _listing_outputs(trace)
    dispatch_content = _verified_dispatch_content(trace)
    assigned, root = [], None
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
    source_outputs = _read_output_prefixes(trace, assigned, root)
    reads = {row.get("call_id") for row in trace.get("tool_trace", [])
             if isinstance(row, dict) and row.get("call_id") and _authorized_read(row, assigned)}
    instruction_reads = {row.get("call_id"): _ancestor_instruction_reads(row, root)
                         for row in trace.get("tool_trace", []) if root and isinstance(row, dict) and row.get("call_id")
                         and row.get("type") in {"function_call", "custom_tool_call"}}
    for path, value in _trace_strings(trace):
        if any(path[:len(prefix)] == prefix for prefix in source_outputs):
            continue
        candidate = value
        output = path[:1] == ("tool_trace",) and "output" in path[2:]
        if dispatch_content and output:
            candidate = candidate.replace(dispatch_content, "")
        listing = any(path[:len(prefix)] == prefix for prefix in listings)
        row = trace["tool_trace"][int(path[1])] if path[:1] == ("tool_trace",) and len(path) > 1 and str(path[1]).isdigit() else {}
        if _authorized_read(row, assigned) or (row.get("type") == "function_call_output" and row.get("call_id") in reads):
            for source in assigned:
                candidate = re.sub(r"(?<![\w./-])" + re.escape(source) + r"(?![\w./-])", "", candidate)
        if root:
            instructions = (instruction_reads.get(row.get("call_id"), []) if output
                            else _ancestor_instruction_reads(row, root))
            for instruction in instructions:
                candidate = re.sub(r"(?<![\w./-])" + re.escape(instruction) + r"(?![\w./-])", "", candidate, count=1)
        for label, pattern in FORBIDDEN_CONTEXT_PATTERNS:
            checked = value if label != "archived_artifact" else candidate
            if label == "archived_artifact" and listing:
                continue
            if pattern.search(checked):
                errors.append(f"forbidden_context_reference:{label}")
                break
        if root and not listing:
            for reference in THOUGHT_PATH.findall(candidate):
                relative = reference.split(".thoughts/", 1)[1]
                if relative.split("/", 1)[0] != root.name or "/runs/" in relative:
                    errors.append("forbidden_context_reference:archived_artifact")
    return list(dict.fromkeys(errors))


def trace_errors(trace: dict[str, object], *, require_freshness: bool = False) -> list[str]:
    if not isinstance(trace, dict):
        return ["tool_trace_invalid"]
    if not isinstance(trace.get("events", []), list):
        return ["runtime_event_invalid"]
    errors: list[str] = []
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
    if not delivered and spawn.get("dispatch_file"):
        try:
            path = Path(spawn["dispatch_file"]).resolve()
            proof = observed_dispatch_binding(trace, path.parent)
            delivered = (proof.get("dispatch_file") == str(path)
                         and proof.get("dispatch_file_sha256") == spawn.get("dispatch_file_sha256"))
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            pass
    if not delivered:
        errors.append("provider_binding_not_delivered")
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
    errors.extend(context_trace_errors(trace))
    return errors


def self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="workflow-worker-runtime-") as directory:
        root = Path(directory)
        definition = root / "worker.toml"
        definition.write_text('developer_instructions = "Do bounded work."\nmodel = "gpt-test"\n')
        packet = root / "worker.json"
        manifest_path = root / "run_inputs.json"
        manifest_path.write_text("{\"schema_version\": 1}\n")
        manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        packet.write_text(json.dumps({"packets": {"test_worker": {
            "required_prefix": "Coordinator initialization: complete",
            "agent": "test_worker",
            "definition": str(definition),
            "definition_sha256": hashlib.sha256(definition.read_bytes()).hexdigest(),
            "developer_instructions": "Do bounded work.",
            "model": "gpt-test",
            "effort": "low",
            "run_input_manifest": {
                "path": str(manifest_path),
                "sha256": manifest_sha256,
                "status": "explicit",
                "inputs": [{"Input ID": "USER-001", "Input or artifact": "Current context"}],
            },
        }}}) + "\n")
        packet_sha256 = hashlib.sha256(packet.read_bytes()).hexdigest()
        assert activation_packet_errors(packet, "test_worker", packet_sha256) == []
        documenter_bundle = json.loads(packet.read_text())
        documenter_bundle["packets"]["documenter"] = {
            **documenter_bundle["packets"]["test_worker"], "agent": "documenter",
        }
        packet.write_text(json.dumps(documenter_bundle))
        doc_sha256 = hashlib.sha256(packet.read_bytes()).hexdigest()
        assert activation_packet_errors(packet, "documenter", doc_sha256) == []
        (root / "role_bindings.json").write_text(json.dumps({"playbook": "feature_delivery"}))
        assert "pre-handoff packet unavailable" in " ".join(
            activation_packet_errors(packet, "documenter", doc_sha256)
        )
        (root / "role_bindings.json").write_text("{")
        assert "role_bindings_invalid" in activation_packet_errors(packet, "documenter", doc_sha256)
        (root / "role_bindings.json").write_text(json.dumps({"playbook": "techops_issue_remediation"}))
        assert "techops_pre_handoff_packet_invalid" in activation_packet_errors(packet, "documenter", doc_sha256)
        (root / "finalization_packet.json").write_text(json.dumps({
            "identity": {"Lifecycle": "planning"}, "worker_results": [],
        }))
        assert "techops_pre_handoff_workers_incomplete" in activation_packet_errors(packet, "documenter", doc_sha256)
        (root / "role_bindings.json").unlink()
        packet.write_text(json.dumps({"packets": {"test_worker": documenter_bundle["packets"]["test_worker"]}}))
        packet_sha256 = hashlib.sha256(packet.read_bytes()).hexdigest()
        (root / "run_budget.json").write_text(json.dumps({
            "activation_deadline_at": "2000-01-01T00:00:00Z",
        }))
        assert activation_packet_errors(packet, "test_worker", packet_sha256) == [
            "run_budget_finalization_reserve"
        ]
        (root / "run_budget.json").unlink()
        generated_packet = json.loads(packet.read_text())
        generated_packet["packets"]["test_worker"]["run_input_manifest"]["status"] = "generated_minimum"
        packet.write_text(json.dumps(generated_packet) + "\n")
        generated_sha256 = hashlib.sha256(packet.read_bytes()).hexdigest()
        assert activation_packet_errors(packet, "test_worker", generated_sha256) == [
            "run_input_manifest_required"
        ]
        assert activation_packet_errors(packet, "test_worker", "0" * 64) == [
            "activation_packet_hash_mismatch"
        ]
    trace = json.loads(V40_RUNTIME_FIXTURE.read_text())
    assert trace_errors(trace) == trace["expected_errors"]
    corrected = json.loads(json.dumps(trace))
    corrected["spawn"]["activation_packet_delivered"] = True
    corrected["events"] = [
        {"action": "wait", "provider_status": "running"},
        {"action": "fan_in", "provider_status": "completed"},
        {"action": "close", "provider_status": "completed"},
    ]
    corrected["analytical_failure"]["evidence_artifact_required"] = False
    assert trace_errors(corrected) == []
    context_trace = json.loads(V41_CONTEXT_TRACE_FIXTURE.read_text())
    assert trace_errors(context_trace) == context_trace["expected_errors"]
    clean_trace = json.loads(json.dumps(context_trace))
    clean_trace["tool_trace"] = [{"tool": "exec_command", "arguments": {"cmd": "rg -n 'J3V' current-run.md"}}]
    assert trace_errors(clean_trace) == []
    print("validate_worker_runtime self-test: passed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--activation-packet-bundle", type=Path)
    parser.add_argument("--expected-agent")
    parser.add_argument("--expected-bundle-sha256")
    parser.add_argument("--transition", choices=("wait", "interrupt", "close", "replace", "fan_in"))
    parser.add_argument("--provider-status")
    parser.add_argument("--before-source-change", type=Path)
    parser.add_argument("--implementer-handle")
    parser.add_argument("--rejected-trace", type=Path)
    parser.add_argument("--provider-handle")
    parser.add_argument("--last-dispatch-at")
    parser.add_argument("--trace", type=Path)
    parser.add_argument("--require-freshness", action="store_true")
    parser.add_argument("--assignment", type=Path)
    parser.add_argument("--activation-message", type=Path)
    parser.add_argument("--dispatch-file", type=Path,
                        help="Save complete guarded instructions and return a compact canonical launch message")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    result: dict[str, object] = {"status": "allowed"}
    if args.self_test:
        self_test()
        return 0
    selected_modes = sum(
        bool(value) for value in (
            args.trace,
            args.activation_packet_bundle or args.expected_agent or args.expected_bundle_sha256,
            args.transition or (args.provider_status and not (args.before_source_change or args.activation_packet_bundle)),
            args.before_source_change,
        )
    )
    if selected_modes > 1:
        parser.error("activation, transition, trace and before-source-change modes are mutually exclusive")
    if args.implementer_handle and not args.before_source_change:
        parser.error("--implementer-handle requires --before-source-change")
    if args.require_freshness and not args.trace:
        parser.error("--require-freshness requires --trace")
    if any((args.rejected_trace, args.provider_handle, args.last_dispatch_at)) and (
            not (args.transition == "replace" or args.activation_packet_bundle)
            or not all((args.rejected_trace, args.provider_handle, args.last_dispatch_at, args.provider_status))):
        parser.error("recovery requires activation or replace, rejected trace, provider handle, dispatch and status")
    if args.rejected_trace and args.activation_packet_bundle and not (args.assignment and args.dispatch_file):
        parser.error("corrected activation requires --assignment and --dispatch-file")
    if args.dispatch_file and not args.assignment:
        parser.error("--dispatch-file requires --assignment in activation mode")
    if (args.assignment or args.activation_message or args.dispatch_file) and not args.activation_packet_bundle:
        parser.error("--assignment, --activation-message and --dispatch-file require activation mode")
    if args.before_source_change:
        if not args.implementer_handle or not args.provider_status:
            parser.error("--before-source-change requires --implementer-handle and --provider-status")
        errors = delivery_start_errors(args.before_source_change.resolve(), args.implementer_handle, args.provider_status)
    elif args.trace:
        try:
            errors = trace_errors(json.loads(args.trace.read_text()), require_freshness=args.require_freshness)
        except (OSError, ValueError, TypeError) as error:
            errors = [f"tool_trace_invalid:{error}"]
    elif args.activation_packet_bundle or args.expected_agent or args.expected_bundle_sha256:
        if not args.activation_packet_bundle or not args.expected_agent or not args.expected_bundle_sha256:
            parser.error(
                "--activation-packet-bundle, --expected-agent, and --expected-bundle-sha256 are required together"
            )
        errors = []
        rejection_hash = None
        if args.rejected_trace:
            if args.rejected_trace.resolve().parent != args.activation_packet_bundle.resolve().parent:
                errors.append("rejected_result_current_run_required")
            else:
                errors.extend(_recovery_errors(args.rejected_trace, args.expected_agent, args.provider_handle,
                                               args.last_dispatch_at, args.provider_status))
                if not errors:
                    rejection_hash = hashlib.sha256(args.rejected_trace.read_bytes()).hexdigest()
        if not errors:
            errors = activation_packet_errors(args.activation_packet_bundle.resolve(), args.expected_agent,
                                              args.expected_bundle_sha256, rejected_trace_sha256=rejection_hash)
        if not errors:
            bundle = json.loads(args.activation_packet_bundle.read_text())
            packet = bundle["packets"][args.expected_agent]
            if args.assignment:
                try:
                    message = activation_message(packet, json.loads(args.assignment.read_text()))
                    expected = dispatch_notice(packet, message, args.dispatch_file) if args.dispatch_file else message
                    if args.activation_message and args.activation_message.read_text() != expected:
                        raise ValueError("activation_message_mismatch")
                    if args.dispatch_file:
                        message = dispatch_message(packet, message, args.dispatch_file)
                        if rejection_hash:
                            current_path = args.activation_packet_bundle.parent / "finalization_packet.json"
                            current = json.loads(current_path.read_text())
                            current.setdefault("activation_repairs", {})[args.expected_agent] = {
                                "Attempt": 1, "Provider handle": args.provider_handle,
                                "Last dispatch at": args.last_dispatch_at, "Rejected trace SHA256": rejection_hash,
                                "Corrected dispatch SHA256": hashlib.sha256(args.dispatch_file.read_bytes()).hexdigest()}
                            with tempfile.NamedTemporaryFile("w", dir=current_path.parent, delete=False) as stream:
                                temporary = Path(stream.name)
                                json.dump(current, stream, indent=2)
                                stream.write("\n")
                            try:
                                temporary.replace(current_path)
                            finally:
                                temporary.unlink(missing_ok=True)
                            result["recovery_authorization"] = current["activation_repairs"][args.expected_agent]
                        result["dispatch_file"] = str(args.dispatch_file.resolve())
                        result["dispatch_file_sha256"] = hashlib.sha256(args.dispatch_file.read_bytes()).hexdigest()
                    result["activation_message"] = message
                    result["activation_message_sha256"] = hashlib.sha256(message.encode()).hexdigest()
                except (OSError, ValueError, TypeError) as error:
                    errors.append(f"activation_assignment_invalid:{error}")
            elif args.activation_message:
                errors.append("activation_message_requires_assignment")
            else:
                result["activation_packet"] = packet
    elif args.transition or args.provider_status:
        if not args.transition or not args.provider_status:
            parser.error("--transition and --provider-status are required together")
        errors = []
        if args.rejected_trace:
            try:
                trace = json.loads(args.rejected_trace.read_text())
                errors = rejected_result_errors(trace,
                                                args.provider_handle, args.last_dispatch_at)
                current = json.loads((args.rejected_trace.parent / "finalization_packet.json").read_text())
                if (not trace.get("run_id") or trace["run_id"] != current["identity"]["Run ID"]
                        or any(pattern.search(str(args.rejected_trace.resolve()))
                               for label, pattern in FORBIDDEN_CONTEXT_PATTERNS if label == "archived_artifact")):
                    errors.append("rejected_result_current_run_required")
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
                errors = [f"rejected_result_trace_invalid:{error}"]
        error = transition_error(args.transition, args.provider_status,
                                 rejected_result=bool(args.rejected_trace) and not errors)
        if error:
            errors.append(error)
        if not errors and args.rejected_trace and trace.get("spawn", {}).get("activation_message_conformance") == "failed":
            try:
                role = trace["spawn"].get("agent") or trace["spawn"].get("expected_agent")
                bindings = json.loads((args.rejected_trace.parent / "role_bindings.json").read_text())
                if not role or role not in bindings["bindings"]:
                    raise ValueError("activation_repair_binding_required")
                repairs = current.setdefault("activation_repairs", {})
                if role in repairs:
                    raise ValueError("activation_repair_limit_reached")
                repairs[role] = {"Provider handle": args.provider_handle, "Last dispatch at": args.last_dispatch_at,
                                 "Rejected trace": str(args.rejected_trace.resolve()), "Attempt": 1}
                (args.rejected_trace.parent / "finalization_packet.json").write_text(json.dumps(current, indent=2) + "\n")
                result["activation_repair"] = "reserved; preserve rejected output and dispatch the complete guarded assignment"
            except (OSError, ValueError, KeyError, TypeError) as error:
                errors.append(str(error))
    else:
        parser.error("choose --activation-packet-bundle, --transition, --trace, or --self-test")
    if errors:
        print(json.dumps({"status": "blocked", "errors": errors}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
