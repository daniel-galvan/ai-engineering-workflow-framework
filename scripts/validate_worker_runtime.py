#!/usr/bin/env python3
"""Validate worker binding delivery and unsafe runtime transitions."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import tempfile
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
V40_RUNTIME_FIXTURE = ROOT / "tests" / "fixtures" / "v40_sentry_worker_runtime.json"
V41_CONTEXT_TRACE_FIXTURE = ROOT / "tests" / "fixtures" / "v41_sentry_context_trace.json"
ACTIVE_STATUSES = {"pending_init", "running", "in_progress", "awaiting_dependency"}
TERMINAL_STATUSES = {"completed", "failed", "stopped", "interrupted", "cancelled"}
DESTRUCTIVE_TRANSITIONS = {"interrupt", "close", "replace"}
TRACE_METADATA_KEYS = {
    "description", "expected_errors", "source_task", "source_thread", "fixture", "schema_version",
}
FORBIDDEN_CONTEXT_PATTERNS = (
    ("memory_path", re.compile(r"(?i)(?:^|[/\\])memory\.md(?:$|[/\\])")),
    ("memory_directory", re.compile(r"(?i)(?:^|[/\\])\.codex[/\\]memories(?:$|[/\\])")),
    ("rollout_summary", re.compile(r"(?i)(?:^|[/\\])rollout_summaries(?:$|[/\\])")),
    ("archived_artifact", re.compile(r"(?i)(?:^|[\s/\\\"'])\.thoughts[/\\][^/\\]+[/\\]runs(?:$|[\s/\\\"'])")),
    ("memory_citation", re.compile(r"(?i)<oai-mem-citation>")),
)


def activation_packet_errors(path: Path, expected_agent: str, expected_sha256: str) -> list[str]:
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
    errors: list[str] = []
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
    if path.exists():
        if path.read_text() != message:
            raise ValueError("activation_dispatch_file_conflict: use a new path for a corrected assignment")
    else:
        with path.open("x") as stream:
            stream.write(message)
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
        roles = {"implement": "implementer", "review": "reviewer", "validate": "tester", "handoff": "documenter"}
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
        packet = json.loads(bundle_path.read_text())["packets"][spawn["agent"]]
        current = json.loads((root / "finalization_packet.json").read_text())
        if (Path(packet["finalization_packet"]).resolve() != root / "finalization_packet.json"
                or packet["run_id"] != trace["run_id"]
                or packet["run_id"] != current["identity"]["Run ID"]
                or packet["agent"] != spawn["agent"]):
            return None
        assignment = json.loads(content.split("\nTyped assignment:\n", 1)[1])
        return content if activation_message(packet, assignment) == content else None
    except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError):
        return None


def context_trace_errors(trace: dict[str, object]) -> list[str]:
    """Reject worker traces that reference unassigned memory or archived runs."""
    if not isinstance(trace, dict):
        return ["tool_trace_invalid"]
    errors: list[str] = []
    declared = str(trace.get("context_conformance", "")).strip().lower()
    if declared in {"fail", "failed", "blocked"}:
        errors.append("context_conformance_failed")
    listings = _listing_outputs(trace)
    dispatch_content = _verified_dispatch_content(trace)
    for path, value in _trace_strings(trace):
        for label, pattern in FORBIDDEN_CONTEXT_PATTERNS:
            if label == "archived_artifact" and any(path[:len(prefix)] == prefix for prefix in listings):
                continue
            # Required instruction output can contain preservation locators; archive operations still fail.
            candidate = value
            if (label == "archived_artifact" and value == dispatch_content
                    and path[:1] == ("tool_trace",) and "output" in path[2:]):
                continue
            if (label == "archived_artifact" and dispatch_content and dispatch_content in value
                    and path[:1] == ("tool_trace",) and "output" in path[2:]):
                candidate = value.replace(dispatch_content, "")
            if pattern.search(candidate):
                errors.append(f"forbidden_context_reference:{label}")
                break
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
    if not observed_role and not observed_path and not spawn.get("activation_packet_delivered"):
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
            args.transition or (args.provider_status and not args.before_source_change),
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
            args.transition != "replace" or not all((args.rejected_trace, args.provider_handle, args.last_dispatch_at))):
        parser.error("rejected-result recovery requires replace, --rejected-trace, --provider-handle and --last-dispatch-at")
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
        errors = activation_packet_errors(
            args.activation_packet_bundle.resolve(), args.expected_agent, args.expected_bundle_sha256
        )
        if not errors:
            bundle = json.loads(args.activation_packet_bundle.read_text())
            packet = bundle["packets"][args.expected_agent]
            if args.assignment:
                try:
                    message = activation_message(packet, json.loads(args.assignment.read_text()))
                    if args.dispatch_file:
                        message = dispatch_message(packet, message, args.dispatch_file)
                        result["dispatch_file"] = str(args.dispatch_file.resolve())
                        result["dispatch_file_sha256"] = hashlib.sha256(args.dispatch_file.read_bytes()).hexdigest()
                    if args.activation_message and args.activation_message.read_text() != message:
                        errors.append("activation_message_mismatch")
                    else:
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
