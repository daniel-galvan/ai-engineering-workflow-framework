#!/usr/bin/env python3
"""Worker binding, context, trace, and transition validation without CLI orchestration."""

from __future__ import annotations

import ast
import io
import hashlib
import json
import re
import shlex
import tempfile
import tokenize
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
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
    ("archived_artifact", re.compile(r"(?i)\.thoughts[/\\][^/\\\s]+(?:[_-]v[0-9]+|[_-]backup|[_-]archive)(?:$|[/\\\s])")),
    ("memory_citation", re.compile(r"(?i)<oai-mem-citation>")),
)


try:
    from provider_runtime import worker_binding, DELIVERY_WORKERS, launch_binding_errors
except ModuleNotFoundError:
    from scripts.provider_runtime import worker_binding, DELIVERY_WORKERS, launch_binding_errors


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
        return errors
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        return ["worker_trace_identity_invalid:" + worker + ":" + str(error)]


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
    verified_read = re.fullmatch(
        r'packet=([^\s;&|<>$`]+); actual=\$\(sha256sum "\$packet" \| cut -d \' \' -f 1\); '
        r'if \[ "\$actual" != [0-9a-f]{64} \]; then printf \'SHA256_MISMATCH %s\\n\' "\$actual"; '
        r'exit 2; fi; printf \'SHA256_OK %s\\n\' "\$actual"; cat "\$packet"', command)
    if verified_read:
        return [verified_read[1]]
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
                receipts = root / "activation_receipts.json"
                instructions = json.loads(receipts.read_text()) if receipts.is_file() else {}
                safe = safe and bool(targets) and all(
                    not (path.resolve().parent == root and path.name in instructions)
                    and path.resolve() != Path(trace["spawn"]["dispatch_file"]).resolve()
                    and ((path.resolve().parent == root and path.is_file()) or str(path) in assigned)
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
                                and any(content in value for _, value in _trace_strings({"tool_trace": [output]}))):
                            return proof
    return {}


def _instruction_contents(trace: dict, root: Path | None) -> list[str]:
    """Exempt authenticated instruction text, never extra provider output."""
    if root is None:
        return []
    receipts = root / "activation_receipts.json"
    contents = []
    bindings = json.loads((root / "role_bindings.json").read_text())
    role = worker_binding(bindings, trace["spawn"]["agent"])
    for name, receipt in json.loads(receipts.read_text()).items() if receipts.is_file() else []:
        if receipt.get("agent") != role:
            continue
        candidate = {**trace, "spawn": {**trace["spawn"], "dispatch_file": str(root / name),
            "dispatch_file_sha256": receipt.get("sha256"), "binding_agent": receipt.get("agent")}}
        content = _verified_dispatch_content(candidate)
        if content:
            contents.append(content)
    for row in trace.get("tool_trace", []):
        if not isinstance(row, dict):
            continue
        for name, arguments in _tool_operations(row):
            if name != "exec_command":
                continue
            operation = {"tool": name, "arguments": arguments}
            cwd = Path(arguments.get("workdir", root.parent.parent))
            for target in _ancestor_instruction_reads(operation, root):
                path = Path(target)
                path = path if path.is_absolute() else cwd / path
                try:
                    if path.is_file():
                        contents.append(path.read_text())
                except (OSError, UnicodeError):
                    continue
    return contents


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
            r'^for (?P<var>[A-Za-z_]\w*) in (?P<paths>[^;\n]+);\s*do\s+if '
            r'(?:\[ -f "\$(?P=var)" \]|test -f "\$(?P=var)");\s*then\s+'
            r'(?:(?:echo "--- \$(?P=var)"|printf \'\\n--- %s ---\\n\' "\$(?P=var)");\s*)?'
            r'cat "\$(?P=var)";\s*fi;\s*done(?=;|\n|$)', command)
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
    instruction_contents = _instruction_contents(trace, root)
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
            for content in instruction_contents or [dispatch_content]:
                candidate = candidate.replace(content, "")
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
    launch_errors = trace.get("launch_errors", [])
    if not isinstance(launch_errors, list) or any(not isinstance(error, str) for error in launch_errors):
        return ["worker_launch_errors_invalid"]
    errors: list[str] = list(launch_errors)
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


TECHOPS_CHECKS = {"issue_scope", "history_reconciliation", "plan_dependencies", "regression_fixture"}

THOUGHT_PATH = re.compile(r"(?:/[A-Za-z0-9_.-]+)*/?\.thoughts/[^\s\"'<>`\\;,)}\]]+")
