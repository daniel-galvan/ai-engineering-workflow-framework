"""Native provider observations and prepared worker identity resolution."""

from __future__ import annotations

import json
import os
import re
import shlex
from datetime import datetime, timezone
from pathlib import Path

UUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")

DELIVERY_WORKERS = {"implement": "implementer", "review": "reviewer", "validate": "tester", "handoff": "documenter"}
RELATED_RUN_STATUS_FIELDS = {"id", "status", "hostId", "kind", "updatedAt"}
RELATED_RUN_TERMINAL_STATUSES = {"completed", "failed", "stopped", "interrupted", "cancelled", "idle", "archived"}


def strict_json_loads(value: str):
    """Parse JSON while rejecting ambiguous duplicate keys and non-finite constants."""
    def unique_object(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                raise ValueError("duplicate JSON key: " + key)
            result[key] = item
        return result

    return json.loads(value, object_pairs_hook=unique_object,
                      parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)))


def _read_status_receipt(path: Path):
    try:
        return strict_json_loads(path.read_text())
    except (OSError, ValueError) as error:
        raise ValueError("stale_run_thread_identity_invalid:" + str(error)) from error


def prior_run_status_thread_ids(artifact_root: Path, current_thread_id: str) -> tuple[str, ...]:
    """Read only prior-run identity receipts needed to scope a status-only recovery query."""
    identities = set()

    def add(value, *, required=False):
        if value is None and required:
            raise ValueError("stale_run_thread_identity_invalid")
        if value is not None:
            if not isinstance(value, str) or not UUID.fullmatch(value):
                raise ValueError("stale_run_thread_identity_invalid")
            identities.add(value)

    ledger_proves_no_dispatches = False
    try:
        if not isinstance(current_thread_id, str) or not UUID.fullmatch(current_thread_id):
            raise ValueError("stale_run_thread_identity_invalid")
        bindings_path = artifact_root / "role_bindings.json"
        if bindings_path.is_file():
            bindings = _read_status_receipt(bindings_path)
            parent_context = bindings.get("parent_context")
            if parent_context is not None and not isinstance(parent_context, dict):
                raise ValueError("stale_run_thread_identity_invalid")
            if parent_context is not None:
                add(parent_context.get("parent_thread_id"))
        ledger_path = artifact_root / "runtime_dispatches.json"
        if ledger_path.is_file():
            ledger = _read_status_receipt(ledger_path)
            if not isinstance(ledger, dict) or not isinstance(ledger.get("events"), list):
                raise ValueError("stale_run_dispatch_rows_invalid")
            mappings = ledger.get("thread_mappings", {})
            if not isinstance(mappings, dict):
                raise ValueError("stale_run_thread_mapping_invalid")
            for value in mappings.values():
                add(value, required=True)
            for row in ledger["events"]:
                if not isinstance(row, dict):
                    raise ValueError("stale_run_dispatch_rows_invalid")
                add(row.get("Thread ID"), required=True)
            failures = ledger.get("failed_dispatches", [])
            if not isinstance(failures, list):
                raise ValueError("stale_run_dispatch_rows_invalid")
            failed_without_workers = True
            for row in failures:
                if not isinstance(row, dict):
                    raise ValueError("stale_run_dispatch_rows_invalid")
                thread_id = row.get("Thread ID")
                if thread_id is not None:
                    add(thread_id, required=True)
                    failed_without_workers = False
                elif row.get("Operation") != "spawn_agent" or row.get("Status") != "failed":
                    raise ValueError("stale_run_thread_identity_invalid")
            timing = ledger.get("timing")
            if timing is None:
                open_worker_intervals = ledger.get("open_worker_intervals")
            elif isinstance(timing, dict):
                open_worker_intervals = timing.get("open_worker_intervals")
            else:
                open_worker_intervals = None
            ledger_proves_no_dispatches = (
                not ledger["events"] and not mappings and failed_without_workers
                and type(open_worker_intervals) is int and open_worker_intervals == 0
            )
        closure_path = artifact_root / "runtime_closure.json"
        if closure_path.is_file():
            closure = _read_status_receipt(closure_path)
            if not isinstance(closure, dict):
                raise ValueError("stale_run_closure_identity_invalid")
            if "terminal_observations" not in closure and ledger_proves_no_dispatches:
                pass  # A zero-dispatch ledger has no worker identities for closure to report.
            elif not isinstance(closure.get("terminal_observations"), list):
                raise ValueError("stale_run_closure_identity_invalid")
            else:
                for row in closure["terminal_observations"]:
                    if not isinstance(row, dict):
                        raise ValueError("stale_run_closure_identity_invalid")
                    add(row.get("Thread ID"), required=True)
    except (OSError, json.JSONDecodeError, AttributeError, TypeError) as error:
        raise ValueError("stale_run_thread_identity_invalid:" + str(error)) from error
    identities.discard(current_thread_id)
    return tuple(sorted(identities))


def related_run_status_projection_source(
    work_item: str, current_thread_id: str, prior_thread_ids: tuple[str, ...] = (),
) -> str:
    """Return the only permitted, redacted provider task-status lookup for this work item."""
    if not isinstance(work_item, str) or not re.fullmatch(r"[A-Za-z0-9._-]+", work_item):
        raise ValueError("stale_run_status_work_item_invalid")
    if not isinstance(current_thread_id, str) or not UUID.fullmatch(current_thread_id):
        raise ValueError("stale_run_status_thread_id_invalid")
    if (not isinstance(prior_thread_ids, tuple)
            or any(not isinstance(value, str) or not UUID.fullmatch(value) for value in prior_thread_ids)):
        raise ValueError("stale_run_status_prior_thread_ids_invalid")
    return ("const response = await tools.mcp__codex_app__list_threads({limit: 50});\n"
            "const data = JSON.parse(response.content[0].text);\n"
            "const rows = [...(data.pinnedThreads || []), ...(data.threads || [])];\n"
            f"const priorIds = {json.dumps(list(prior_thread_ids))};\n"
            f"const related = rows.filter(row => row.id !== {json.dumps(current_thread_id)} &&\n"
            f"  ((typeof row.title === 'string' && row.title.includes({json.dumps(work_item)}) || priorIds.includes(row.id)))\n"
            "  .map(row => ({\n"
            "    id: row.id, status: row.status, hostId: row.hostId, kind: row.kind,\n"
            "    updatedAt: row.updatedAt\n"
            "  }));\n"
            "text(JSON.stringify(related));")


def _related_run_status_rows(payload: dict) -> list[dict]:
    output = payload.get("output")
    if isinstance(output, list):
        texts = [row.get("text") for row in output if isinstance(row, dict)
                 and row.get("type") in {"text", "input_text", "output_text"}
                 and isinstance(row.get("text"), str)]
        if len(texts) != len(output) or len(texts) != 1:
            raise ValueError("parent_related_run_status_output_invalid")
        output = texts[0]
    if not isinstance(output, str):
        raise ValueError("parent_related_run_status_output_invalid")
    try:
        rows = strict_json_loads(output)
    except ValueError as error:
        raise ValueError("parent_related_run_status_output_invalid") from error
    if not isinstance(rows, list):
        raise ValueError("parent_related_run_status_output_invalid")
    seen, validated = set(), []
    for row in rows:
        if (not isinstance(row, dict) or set(row) - RELATED_RUN_STATUS_FIELDS
                or not {"id", "status"}.issubset(row)
                or not isinstance(row["id"], str) or not UUID.fullmatch(row["id"])
                or not isinstance(row["status"], str) or row["id"] in seen
                or any(key in row and row[key] is not None and not isinstance(row[key], str)
                       for key in {"hostId", "kind", "updatedAt"})):
            raise ValueError("parent_related_run_status_output_invalid")
        seen.add(row["id"])
        validated.append(row)
    return validated


def stale_run_status_errors(
    context: dict | None, prior_state: str | None, *, require_prior_dispatch_ledger: bool = True,
) -> list[str]:
    """Require fresh, redacted, terminal status for every known prior task/worker before archiving."""
    if (not isinstance(context, dict)
            or type(context.get("verified_related_run_status_probes")) is not int
            or context["verified_related_run_status_probes"] != 1
            or type(context.get("related_run_status_probe_attempts")) is not int
            or context["related_run_status_probe_attempts"] != 1):
        return ["stale_run_status_probe_required"]
    rows = context.get("related_run_status_rows")
    expected = context.get("related_run_thread_ids")
    if not isinstance(rows, list) or not isinstance(expected, list):
        return ["stale_run_status_evidence_invalid"]
    if (any(not isinstance(value, str) or not UUID.fullmatch(value) for value in expected)
            or len(expected) != len(set(expected))
            or context.get("parent_thread_id") in expected):
        return ["stale_run_status_evidence_invalid"]
    observed = {row.get("id") for row in rows if isinstance(row, dict)}
    errors = ["stale_run_worker_status_missing:" + thread_id for thread_id in expected
              if thread_id not in observed]
    for row in rows:
        if not isinstance(row, dict):
            errors.append("stale_run_status_evidence_invalid")
            continue
        if row.get("status", "").lower() not in RELATED_RUN_TERMINAL_STATUSES:
            errors.append("stale_run_related_task_active:" + row.get("id", "unknown"))
    if require_prior_dispatch_ledger and context.get("prior_run_dispatch_ledger_present") is not True:
        errors.append("stale_run_dispatch_ledger_required")
    return errors


def _verified_empty_memory_search(command: str, observation: dict,
                                 framework_root: Path | None = None) -> bool:
    """Recognize only a native, no-result search of the host memory index."""
    path_alias_warning = (
        "WARNING: proceeding, even though we could not create PATH aliases: "
        "Operation not permitted (os error 1)\n"
    )
    try:
        commands = command.split(" && ")
        if len(commands) == 2:
            if framework_root is None:
                return False
            bootstrap = shlex.split(commands[0])
            skill = (framework_root.expanduser().resolve() / "skills" / "run" / "SKILL.md").resolve()
            if (len(bootstrap) != 2 or Path(bootstrap[0]).name != "cat"
                    or Path(bootstrap[1]).resolve() != skill):
                return False
            search_command = commands[1]
            parsed_count = 2
            expected_bootstrap_path = str(skill)
        elif len(commands) == 1:
            search_command = command
            parsed_count = 1
            expected_bootstrap_path = None
        else:
            return False
        argv = shlex.split(search_command)
    except ValueError:
        return False
    if Path(argv[0]).name != "rg":
        return False
    args, flags = argv[1:], []
    allowed_flags = {"-n", "--line-number", "-i", "--ignore-case", "-F", "--fixed-strings"}
    while args and args[0] in allowed_flags:
        flags.append(args.pop(0))
    if (len(args) != 2 or not any(flag in {"-n", "--line-number"} for flag in flags)
            or len(flags) != len(set(flags))):
        return False
    query, target = args[0], Path(args[1])
    if not query or not target.is_absolute() or target.parts[-3:] != (".codex", "memories", "MEMORY.md"):
        return False
    native_command = observation.get("command")
    if not isinstance(native_command, list) or not native_command or native_command[-1] != command:
        return False
    parsed = observation.get("parsed_cmd")
    if (observation.get("exit_code") != 1 or isinstance(observation.get("exit_code"), bool)
            or observation.get("status") != "failed"
            or not isinstance(parsed, list) or len(parsed) != parsed_count
            or not all(isinstance(item, dict) for item in parsed)):
        return False
    item = parsed[-1]
    if not (item.get("type") == "search" and item.get("query") == query
            and str(item.get("path", "")) in {str(target), target.name}):
        return False
    if expected_bootstrap_path is None:
        return observation.get("aggregated_output") in {"", path_alias_warning}
    bootstrap_item = parsed[0]
    try:
        skill_text = Path(expected_bootstrap_path).read_text()
    except OSError:
        return False
    output = observation.get("aggregated_output")
    expected_output = skill_text[:min(len(skill_text), 65536)]
    return (bootstrap_item.get("type") == "read"
            and isinstance(bootstrap_item.get("path"), str)
            and Path(bootstrap_item["path"]).resolve() == Path(expected_bootstrap_path)
            and output in {expected_output, path_alias_warning + expected_output})


def current_parent_session(source: Path | None = None) -> Path | None:
    """Resolve the native current fragment from identity and event metadata only."""
    identity = os.environ.get("CODEX_THREAD_ID") or os.environ.get("CODEX_SESSION_ID")
    if not identity:
        return source.resolve() if source else None
    if not UUID.fullmatch(identity):
        raise ValueError("provider_current_identity_invalid")
    sessions = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "sessions"
    candidates, incomplete = {}, []
    for path in sessions.rglob("*" + identity.lower() + "*.jsonl"):
        with path.open() as stream:
            header = json.loads(next(stream, ""))
            if not isinstance(header, dict) or not isinstance(header.get("payload"), dict):
                raise ValueError("provider_current_session_metadata_invalid")
            if header.get("type") != "session_meta" or str(header["payload"].get("id", "")).lower() != identity.lower():
                continue
            turn, started, latest = None, None, None
            for line in stream:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    if not line.endswith("\n"):
                        break
                    raise
                if not isinstance(row, dict):
                    raise ValueError("provider_current_session_metadata_invalid")
                if row.get("type") == "turn_context":
                    payload = row.get("payload")
                    turn = payload.get("turn_id") if isinstance(payload, dict) else None
                    if not isinstance(turn, str) or not UUID.fullmatch(turn):
                        raise ValueError("provider_current_turn_unavailable")
                    started = latest = timestamp(str(row.get("timestamp", "")))
                elif started and row.get("timestamp"):
                    latest = max(latest, timestamp(str(row["timestamp"])))
            if started:
                candidates[path.resolve()] = (started, latest, turn)
            else:
                incomplete.append(timestamp(str(header["timestamp"])) if header.get("timestamp") else None)
    if not candidates:
        raise ValueError("provider_current_session_unavailable")
    newest = max(value[:2] for value in candidates.values())
    if any(created is None or created >= newest[0] for created in incomplete):
        raise ValueError("provider_current_turn_unavailable")
    selected = [path for path, value in candidates.items() if value[:2] == newest]
    if len(selected) != 1:
        raise ValueError("provider_current_session_ambiguous")
    if source and source.resolve() != selected[0]:
        raise ValueError("provider_current_session_mismatch: use the current native fragment")
    return selected[0]


def parent_context_audit(source: Path, *, artifact_root: Path | None = None,
                         input_paths: tuple[str, ...] = (), expected_thread_id: str | None = None,
                         expected_turn_id: str | None = None, runtime_evidence: dict | None = None,
                         related_run_thread_ids: tuple[str, ...] | None = None,
                         prior_dispatch_ledger_present: bool | None = None,
                         framework_root: Path | None = None,
                         require_preflight_order: bool = False) -> dict:
    """Audit current-turn operations without importing messages or previous analytical content."""
    try:
        from runtime_checks import _tool_operations, context_trace_errors
    except ModuleNotFoundError:
        from scripts.runtime_checks import _tool_operations, context_trace_errors
    with source.open() as stream:
        header = json.loads(next(stream, ""))
        thread = header.get("payload", {}).get("id")
        if (header.get("type") != "session_meta" or not isinstance(thread, str) or not UUID.fullmatch(thread)
                or expected_thread_id is not None and thread != expected_thread_id):
            raise ValueError("provider_session_parent_mismatch")
        known_children = set()
        if runtime_evidence:
            native = read_runtime_events(source, thread, runtime_evidence["run_started_at"],
                tuple(Path(value) for value in runtime_evidence.get("identity_sessions", [])))
            known_children = {native["thread_mappings"][row["Provider handle"]] for row in native["events"]}
        identity_error = None
        try:
            if related_run_thread_ids is None:
                prior_ids = prior_run_status_thread_ids(artifact_root, thread) if artifact_root else ()
            else:
                if (not isinstance(related_run_thread_ids, tuple)
                        or any(not isinstance(value, str) or not UUID.fullmatch(value)
                               for value in related_run_thread_ids)):
                    raise ValueError("stale_run_status_prior_thread_ids_invalid")
                prior_ids = tuple(sorted(set(related_run_thread_ids) - {thread}))
        except ValueError as error:
            prior_ids = ()
            identity_error = str(error)
        ledger_present = (artifact_root is not None and (artifact_root / "runtime_dispatches.json").is_file()
                          if prior_dispatch_ledger_present is None else prior_dispatch_ledger_present)
        turn, operations, sequenced_operations, children, errors = None, [], [], set(known_children), []
        command_observations: dict[str, list[dict]] = {}
        exempt = set()
        pending_related_run_status = {}
        related_run_probe_attempts = 0
        verified_related_run_status_probes = 0
        related_run_status_rows = None
        for line in stream:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                if not line.endswith("\n"):
                    break  # The native provider may still be appending its last event.
                raise
            payload = row.get("payload", {})
            if row.get("type") == "turn_context":
                if expected_turn_id and turn == expected_turn_id and payload.get("turn_id") != expected_turn_id:
                    break
                turn = payload.get("turn_id")
                operations, sequenced_operations, children, errors = [], [], set(known_children), []
                command_observations = {}
                exempt = set()
                pending_related_run_status = {}
                related_run_probe_attempts = 0
                verified_related_run_status_probes = 0
                related_run_status_rows = None
                if identity_error:
                    errors.append(identity_error)
            elif turn and (expected_turn_id is None or turn == expected_turn_id) and row.get("type") == "event_msg":
                item = payload.get("item", {})
                if item.get("type") == "SubAgentActivity" and item.get("kind") == "started":
                    children.add(item.get("agent_thread_id"))
                elif (payload.get("type") == "item_completed" and item.get("type") == "CommandExecution"
                      and isinstance(item.get("command"), list) and item["command"]
                      and isinstance(item["command"][-1], str)):
                    command = item["command"][-1]
                    command_observations.setdefault(command, []).append(item)
            elif (turn and (expected_turn_id is None or turn == expected_turn_id)
                  and row.get("type") == "response_item" and payload.get("type") in {
                      "function_call_output", "custom_tool_call_output"}):
                call_id = payload.get("call_id")
                if call_id in pending_related_run_status:
                    pending_related_run_status.pop(call_id)
                    if payload.get("isError") or payload.get("status") in {"failed", "error"}:
                        errors.append("parent_related_run_status_output_invalid")
                    else:
                        try:
                            related_run_status_rows = _related_run_status_rows(payload)
                            verified_related_run_status_probes += 1
                        except ValueError as error:
                            errors.append(str(error))
            elif turn and (expected_turn_id is None or turn == expected_turn_id) and row.get("type") == "response_item" and payload.get("type") in {
                    "function_call", "custom_tool_call"}:
                raw_source = payload.get("input") if payload.get("type") == "custom_tool_call" else None
                try:
                    expected_projection = (related_run_status_projection_source(artifact_root.name, thread, prior_ids)
                                           if artifact_root is not None else None)
                except ValueError:
                    expected_projection = None
                exact_status_projection = raw_source == expected_projection and expected_projection is not None
                calls = (
                    [("mcp__codex_app__list_threads", {"limit": 50})]
                    if exact_status_projection else _tool_operations(payload)
                )
                if (not calls and payload.get("type") == "custom_tool_call"
                        and "tools.mcp__codex_app__list_threads({limit: 50})" in str(raw_source or "")):
                    calls = [("mcp__codex_app__list_threads", {})]
                if not calls and payload.get("type") == "custom_tool_call" and "tools." in str(raw_source or ""):
                    errors.append("parent_tool_arguments_unavailable")
                status_projection_candidate = (
                    exact_status_projection and len(calls) == 1
                    and calls[0][0].rsplit("__", 1)[-1] == "list_threads"
                    and calls[0][1] == {"limit": 50}
                    and isinstance(payload.get("call_id"), str) and payload["call_id"])
                for name, arguments in calls:
                    sequenced_operations.append({"name": name, "arguments": arguments})
                    if name == "exec_command":
                        operations.append({"type": "function_call", "name": name, "arguments": arguments})
                    elif name == "apply_patch":
                        if not isinstance(arguments.get("patch"), str):
                            errors.append("parent_tool_arguments_unavailable")
                            continue
                        targets = re.findall(r"^\*\*\* (?:(?:Add|Update|Delete) File|Move to): (.+)$",
                                             arguments["patch"], re.M)
                        operations.append({"type": "function_call", "name": name, "arguments": {"paths": targets}})
                    elif name.rsplit("__", 1)[-1] in {"read_thread", "wait_threads"}:
                        targets = (arguments.get("targets", []) if name.endswith("wait_threads") else [arguments])
                        for target in targets:
                            identity = target.get("threadId")
                            if identity not in children and "codex://threads/" + str(identity) not in input_paths:
                                errors.append("parent_unassigned_thread_read:" + str(identity))
                    elif name.rsplit("__", 1)[-1] in {"list_threads", "list_archived_threads"}:
                        if (name.rsplit("__", 1)[-1] == "list_threads" and status_projection_candidate
                                and related_run_probe_attempts == 0):
                            exempt.add(len(operations))
                            pending_related_run_status[payload["call_id"]] = True
                            related_run_probe_attempts += 1
                        else:
                            errors.append("parent_unassigned_thread_discovery")
                        operations.append({"type": "function_call", "name": name, "arguments": arguments})
        if pending_related_run_status:
            errors.append("parent_related_run_status_output_missing")
        if not isinstance(turn, str) or not UUID.fullmatch(turn):
            raise ValueError("provider_current_turn_unavailable")
        if expected_turn_id and turn != expected_turn_id:
            raise ValueError("provider_bound_turn_unavailable")
    # A query-only memory probe is harmless only when the provider's native execution record
    # proves one exact rg search returned no matches. Keep all other memory references blocked.
    operation_indexes: dict[str, list[int]] = {}
    for index, operation in enumerate(operations):
        arguments = operation.get("arguments", {})
        command = arguments.get("cmd") if operation.get("name") == "exec_command" else None
        if isinstance(command, str):
            operation_indexes.setdefault(command, []).append(index)
    empty_memory_probes = 0
    preflight_memory_probes = set()
    for command, indexes in operation_indexes.items():
        observations = command_observations.get(command, [])
        if (len(indexes) == 1 and len(observations) == 1
                and _verified_empty_memory_search(command, observations[0], framework_root)):
            exempt.add(indexes[0])
            empty_memory_probes += 1
            # A host-mandated no-match search is not framework discovery. Only its standalone form may precede
            # preflight; combined commands remain subject to normal ordering checks.
            if len(command.split(" && ")) == 1:
                preflight_memory_probes.add(command)
    audited_operations = [operation for index, operation in enumerate(operations) if index not in exempt]
    if require_preflight_order and framework_root is not None:
        # Only the separately verified, standalone no-match host probe may precede preflight.
        errors.extend(_preflight_order_errors(sequenced_operations, framework_root, command_observations,
                                              preflight_memory_probes))
    details = []
    errors.extend(context_trace_errors({"tool_trace": audited_operations}, details=details,
                                      input_paths=input_paths, artifact_root=artifact_root))
    return {"status": "rejected" if errors else "passed", "provider_session": str(source.resolve()),
            "parent_thread_id": thread, "turn_id": turn, "errors": list(dict.fromkeys(errors)),
            "context_violations": details, "empty_memory_probes": empty_memory_probes,
            "verified_related_run_status_probes": verified_related_run_status_probes,
            "related_run_status_probe_attempts": related_run_probe_attempts,
            "related_run_status_rows": related_run_status_rows,
            "related_run_thread_ids": list(prior_ids),
            "prior_run_dispatch_ledger_present": bool(ledger_present)}


def _preflight_order_errors(operations: list[dict], framework_root: Path,
                            command_observations: dict[str, list[dict]],
                            empty_memory_probes: set[str] | None = None) -> list[str]:
    """Require package preflight before current-turn repository or workflow operations."""
    roots = sorted({str(framework_root.expanduser().absolute()).rstrip("/"),
                    str(framework_root.expanduser().resolve()).rstrip("/")}, key=len, reverse=True)
    root = "(?:" + "|".join(re.escape(value) for value in roots) + ")"
    bootstrap = re.compile(rf"^\s*cat\s+(?:{root}/)?skills/run/SKILL\.md\s*$")
    preflight_path = (framework_root.expanduser().resolve() / "scripts" / "run_preflight.py").resolve()
    completed_preflight = False
    empty_memory_probes = empty_memory_probes or set()
    for operation in operations:
        if operation.get("name") != "exec_command":
            if not completed_preflight:
                return ["parent_framework_content_before_preflight"]
            continue
        command = operation.get("arguments", {}).get("cmd")
        if not isinstance(command, str):
            continue
        if not completed_preflight and command in empty_memory_probes:
            continue
        try:
            argv = shlex.split(command)
        except ValueError:
            argv = []
        is_preflight = (
            len(argv) >= 2 and Path(argv[0]).name in {"python", "python3"}
            and Path(argv[1]).name == "run_preflight.py"
            and ((Path(argv[1]).is_absolute() and Path(argv[1]).resolve() == preflight_path)
                 or argv[1] in {"scripts/run_preflight.py", "./scripts/run_preflight.py"})
            and not any(token in {"&&", "||", ";", "|", ">", "<"} for token in argv)
        )
        if not completed_preflight and not bootstrap.fullmatch(command) and not is_preflight:
            return ["parent_framework_content_before_preflight"]
        if is_preflight:
            observations = command_observations.get(command, [])
            if len(observations) == 1:
                observed = observations[0]
                try:
                    output = json.loads(str(observed.get("aggregated_output", "")))
                except json.JSONDecodeError:
                    output = None
                completed_preflight = (
                    observed.get("status") == "completed" and observed.get("exit_code") == 0
                    and isinstance(output, dict) and output.get("status") == "passed"
                )
    return []


def prepared_parent_context_errors(root: Path, manifest: dict) -> list[str]:
    """Recheck the bound current turn at every acceptance boundary, without importing its answers."""
    parent = manifest.get("parent_context")
    if not parent:
        if os.environ.get("CODEX_THREAD_ID") or os.environ.get("CODEX_SESSION_ID"):
            return ["parent_context_binding_required: prepare the run in the current native chat"]
        return []
    try:
        current_parent_session(Path(parent["provider_session"]))
        # Sentry stages output in a temporary directory; the prepared activation root remains canonical.
        audit_root = Path(manifest["activation_packet_bundle"]["path"]).resolve().parent
        current = parent_context_audit(Path(parent["provider_session"]), artifact_root=audit_root,
            input_paths=tuple(parent["input_paths"]), expected_thread_id=parent["parent_thread_id"],
            runtime_evidence=manifest.get("runtime_evidence"),
            related_run_thread_ids=tuple(parent.get("related_run_thread_ids", [])),
            prior_dispatch_ledger_present=parent.get("prior_run_dispatch_ledger_present", False))
        errors = []
        if current["status"] != "passed":
            errors.append("parent_context_nonconformant:" + ";".join(current["errors"]))
        if current["turn_id"] != parent["turn_id"]:
            errors.append("parent_context_turn_mismatch:expected=" + parent["turn_id"]
                          + ";received=" + current["turn_id"] + ";prepare the current continuation")
        identity = json.loads((root / "finalization_packet.json").read_text())["identity"]
        if parent["run_id"] != manifest.get("run_id") or parent["run_id"] != identity["Run ID"]:
            errors.append("parent_context_run_mismatch")
        return errors
    except (OSError, ValueError, KeyError, TypeError, AttributeError, StopIteration) as error:
        return ["parent_context_evidence_invalid:" + str(error)]


def validate_prepared_provider_source(bindings: dict, source: Path, parent_thread_id: str, started_at: str) -> None:
    """Keep trace and failure-closure collection on the same prepared parent and run interval."""
    current_parent_session(source)
    parent = bindings.get("parent_context")
    if parent:
        if parent_thread_id != parent["parent_thread_id"]:
            raise ValueError("runtime_dispatch_parent_mismatch")
        if source.resolve() != Path(parent["provider_session"]).resolve():
            raise ValueError("runtime_dispatch_provider_session_mismatch")
    expected_start = bindings.get("runtime_evidence", {}).get("run_started_at")
    if expected_start and timestamp(started_at) != timestamp(expected_start):
        raise ValueError("runtime_dispatch_run_start_mismatch:expected=" + expected_start + ";received=" + started_at)


def worker_binding(bindings: dict, worker: str) -> str:
    if worker in bindings["bindings"]:
        return worker
    matches = [role for role, contract in bindings.get("worker_contracts", {}).items()
               if role in bindings["bindings"] and isinstance(contract, dict)
               and (contract.get("worker") or contract.get("worker_id")) == worker]
    sentry = {"evidence-topology": "sentry_current_state_investigator", "failure-topology": "sentry_dependency_analyst",
              "repository-integration": "sentry_repository_integrator", "fix-design": "sentry_solution_architect"}
    if not matches and bindings.get("playbook") == "sentry_issue_remediation" and sentry.get(worker) in bindings["bindings"]:
        return sentry[worker]
    if not matches and DELIVERY_WORKERS.get(worker) in bindings["bindings"]:
        return DELIVERY_WORKERS[worker]
    if len(matches) != 1:
        raise ValueError("worker_binding_identity_invalid")
    return matches[0]


def timestamp(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("provider_event_timestamp_requires_timezone")
    return result


def provider_json_value(value):
    if isinstance(value, list) and len(value) == 1 and isinstance(value[0], dict) \
            and value[0].get("type") == "text" and isinstance(value[0].get("text"), str):
        value = value[0]["text"]
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            pass
    return value


def _provider_status_time(value: object) -> str | None:
    if isinstance(value, bool):
        return None
    try:
        if isinstance(value, (int, float)):
            parsed = datetime.fromtimestamp(value, timezone.utc)
        elif isinstance(value, str):
            parsed = timestamp(value)
        else:
            return None
    except (OverflowError, OSError, ValueError):
        return None
    return parsed.isoformat().replace("+00:00", "Z")


def targeted_thread_observation(raw: object, handle: str, thread_id: str, dispatch_at: str,
                                observed_at: str, operation: str) -> dict | None:
    """Normalize only provider status metadata; never retain a thread's analytical text."""
    if operation != "read_thread" or not isinstance(raw, dict):
        return None
    thread = raw.get("thread")
    turns = raw.get("turns")
    if (not isinstance(thread, dict) or thread.get("id") != thread_id or not isinstance(turns, list)
            or not turns):
        return None
    candidates = []
    for turn in turns:
        if not isinstance(turn, dict):
            continue
        started_at = _provider_status_time(turn.get("startedAt"))
        status = turn.get("status")
        if started_at and isinstance(status, str) and status:
            candidates.append((timestamp(started_at), turn, started_at))
    if not candidates:
        return None
    _, latest, started_at = max(candidates, key=lambda row: row[0])
    latest_status = re.sub(r"(?<!^)(?=[A-Z])", "_", latest["status"]).lower()
    latest_status = {"canceled": "cancelled", "in_progress": "running"}.get(latest_status, latest_status)
    thread_state = thread.get("status")
    thread_status = thread_state.get("type") if isinstance(thread_state, dict) else thread_state
    if not isinstance(thread_status, str):
        return None
    if thread_status == "idle" and latest_status in {"completed", "failed", "stopped", "interrupted", "cancelled"}:
        provider_status = "idle"
    elif thread_status in {"active", "running"}:
        provider_status = "running"
    else:
        provider_status = latest_status
    observation = {"Provider handle": handle, "Provider status": provider_status, "Thread ID": thread_id,
        "Status source": operation, "Last dispatch at": dispatch_at, "Observed at": observed_at,
        "Latest turn started at": started_at, "Latest turn status": latest_status, "Thread status": thread_status}
    completed_at = _provider_status_time(latest.get("completedAt"))
    if completed_at:
        observation["Latest turn completed at"] = completed_at
    return observation


def read_runtime_events(
    path: Path, parent_thread_id: str, started_at: str, identity_sessions: tuple[Path, ...] = (),
) -> dict:
    if not UUID.fullmatch(parent_thread_id):
        raise ValueError("parent_thread_id_invalid")
    started = timestamp(started_at)
    with path.open() as stream:
        first = json.loads(next(stream))
        if first.get("type") != "session_meta" or first.get("payload", {}).get("id") != parent_thread_id:
            raise ValueError("provider_session_parent_mismatch")
        events, mappings, inventories, failed_dispatches, status_probes = [], {}, [], [], []
        for source in identity_sessions:
            with source.open() as identity_stream:
                header = json.loads(next(identity_stream))
                if header.get("type") != "session_meta" or header.get("payload", {}).get("id") != parent_thread_id:
                    raise ValueError("provider_session_parent_mismatch")
                for line in identity_stream:
                    row = json.loads(line)
                    item = row.get("payload", {}).get("item", {})
                    if row.get("type") != "event_msg" or item.get("type") != "SubAgentActivity" or item.get("kind") != "started":
                        continue
                    handle, thread = item.get("agent_path"), item.get("agent_thread_id")
                    if not isinstance(handle, str) or not isinstance(thread, str) or not UUID.fullmatch(thread):
                        raise ValueError("provider_worker_identity_invalid")
                    if handle in mappings and mappings[handle] != thread:
                        raise ValueError("provider_worker_identity_conflict")
                    mappings[handle] = thread
        pending_spawn = None
        inventory_pending = None
        pending_followups = {}
        pending_status_probes = {}
        spawn_calls = {}
        observed_starts = {}
        observed_until = started
        active, intervals = {}, []
        def current_run_lines():
            for source in identity_sessions:
                with source.open() as earlier:
                    next(earlier)
                    yield from earlier
            yield from stream
        seen = set()
        for line in current_run_lines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                if not line.endswith("\n"):
                    break  # The provider may still be appending the last event.
                raise ValueError("provider_session_event_invalid") from None
            if timestamp(row["timestamp"]) < started:
                continue
            observed_until = max(observed_until, timestamp(row["timestamp"]))
            payload = row.get("payload", {})
            item = payload.get("item", {})
            if not ((row.get("type") == "event_msg" and item.get("type") == "SubAgentActivity")
                    or row.get("type") == "response_item" and payload.get("type") in {"function_call", "function_call_output"}):
                continue
            key = json.dumps(row, sort_keys=True)
            if key in seen:
                continue
            seen.add(key)
            if row.get("type") == "event_msg" and item.get("type") == "SubAgentActivity":
                handle = item.get("agent_path")
                if item.get("kind") == "started":
                    observed_starts[handle] = timestamp(row["timestamp"])
                    active.setdefault(handle, timestamp(row["timestamp"]))
                elif item.get("kind") in {"completed", "interrupted", "stopped", "failed"} and handle in active:
                    intervals.append((active.pop(handle), timestamp(row["timestamp"])))
            if (row.get("type") == "event_msg" and item.get("type") == "SubAgentActivity"
                    and item.get("kind") == "started"):
                handle, thread = item.get("agent_path"), item.get("agent_thread_id")
                if not isinstance(handle, str) or not isinstance(thread, str) or not UUID.fullmatch(thread):
                    raise ValueError("provider_worker_identity_invalid")
                if handle in mappings and mappings[handle] != thread:
                    raise ValueError("provider_worker_identity_conflict")
                mappings[handle] = thread
                if pending_spawn is not None and handle.rsplit("/", 1)[-1] == pending_spawn[0]:
                    resolved = {**pending_spawn[1], "Provider handle": handle, "Thread ID": thread}
                    events.append(resolved)
                    if pending_spawn[2]:
                        spawn_calls[pending_spawn[2]] = (pending_spawn[0], resolved)
                    pending_spawn = None
            if row.get("type") != "response_item":
                continue
            if payload.get("type") == "function_call" and payload.get("namespace") == "collaboration":
                operation = payload.get("name")
                if operation == "list_agents":
                    inventory_pending = payload.get("call_id") or True
                if operation not in {"spawn_agent", "followup_task", "send_message"}:
                    continue
                arguments = provider_json_value(payload["arguments"])
                if not isinstance(arguments, dict):
                    raise ValueError("provider_function_arguments_invalid")
                event = {"Operation": operation, "Last dispatch at": row["timestamp"]}
                message = arguments.get("message", "")
                if isinstance(message, str):
                    notice = re.search(r"Read the complete activation instructions and typed assignment at ([^\n]+)\.\n"
                                       r"Verify its SHA256 is ([0-9a-f]{64})", message)
                    role = re.search(r"(?:^|\n)Role: ([a-z_]+);", message)
                    if notice and role:
                        event.update({"Dispatch file": notice[1], "Dispatch SHA256": notice[2], "Binding agent": role[1]})
                if operation == "spawn_agent":
                    event["Launch"] = {key: arguments.get(key) for key in ("model", "reasoning_effort", "fork_turns")}
                    if pending_spawn is not None or not isinstance(arguments.get("task_name"), str):
                        raise ValueError("provider_spawn_identity_unresolved")
                    pending_spawn = (arguments["task_name"], event, payload.get("call_id"))
                    if payload.get("call_id"):
                        spawn_calls[payload["call_id"]] = (arguments["task_name"], event)
                    continue
                target = arguments.get("target")
                matches = [handle for handle in mappings if target in {handle, handle.rsplit("/", 1)[-1]}]
                if len(matches) != 1:
                    raise ValueError("provider_dispatch_handle_unmapped")
                handle = matches[0]
                events.append({**event, "Provider handle": handle, "Thread ID": mappings[handle]})
                if payload.get("call_id"):
                    pending_followups[payload["call_id"]] = (handle, event, handle in active)
                if operation == "followup_task":
                    active.setdefault(handle, timestamp(row["timestamp"]))
            elif (payload.get("type") == "function_call" and isinstance(payload.get("name"), str)
                  and payload["name"].rsplit("__", 1)[-1] in {"read_thread", "wait_threads"}):
                operation = payload["name"].rsplit("__", 1)[-1]
                arguments = provider_json_value(payload.get("arguments"))
                if not isinstance(arguments, dict):
                    raise ValueError("provider_function_arguments_invalid")
                targets = arguments.get("targets", []) if operation == "wait_threads" else [arguments]
                if not isinstance(targets, list) or not targets:
                    continue
                probes = []
                for target in targets:
                    if not isinstance(target, dict):
                        continue
                    thread = target.get("threadId")
                    handles = [handle for handle, mapped in mappings.items() if mapped == thread]
                    if len(handles) == 1:
                        probes.append({"Provider handle": handles[0], "Thread ID": thread})
                if probes and isinstance(payload.get("call_id"), str):
                    pending_status_probes[payload["call_id"]] = {
                        "Operation": operation, "Attempted at": row["timestamp"], "Targets": probes}
            elif payload.get("type") == "function_call_output":
                call_id = payload.get("call_id")
                if (call_id not in pending_followups and call_id not in spawn_calls
                        and call_id not in pending_status_probes
                        and not (inventory_pending and inventory_pending in {True, call_id})):
                    continue
                raw = provider_json_value(payload["output"])
                explicit_error = (
                    isinstance(raw, dict) and bool(raw.get("error") or raw.get("isError")
                                                  or raw.get("status") in ("failed", "error"))
                    or isinstance(raw, str) and bool(re.match(
                        r"^(?:Error[: ]|Failed[: ]|Worker unavailable$|agent path already exists$)", raw, re.I)))
                if call_id in pending_followups:
                    handle, event, was_active = pending_followups.pop(call_id)
                    if explicit_error:
                        if not was_active and observed_starts.get(handle, started) < timestamp(event["Last dispatch at"]):
                            active.pop(handle, None)
                        events = [row for row in events if not (row["Provider handle"] == handle
                                  and row["Last dispatch at"] == event["Last dispatch at"])]
                        failed_dispatches.append({**event, "Provider handle": handle, "Status": "failed"})
                if call_id in spawn_calls:
                    task, event = spawn_calls.pop(call_id)
                    if explicit_error:
                        events = [value for value in events if value != event]
                        failed_dispatches.append({**event, "Task": task, "Status": "failed"})
                        if pending_spawn is not None and pending_spawn[2] == call_id:
                            pending_spawn = None
                if call_id in pending_status_probes:
                    probe = pending_status_probes.pop(call_id)
                    for target in probe["Targets"]:
                        dispatch = latest_worker_dispatch({"events": events, "failed_dispatches": failed_dispatches},
                                                          target["Provider handle"], include_failed=True)
                        observation = (None if explicit_error else targeted_thread_observation(
                            raw, target["Provider handle"], target["Thread ID"], dispatch["Last dispatch at"],
                            row["timestamp"], probe["Operation"]))
                        status_probes.append({**target, "Operation": probe["Operation"],
                            "Attempted at": probe["Attempted at"], "Observed at": row["timestamp"],
                            "Result": ("unavailable" if explicit_error else "returned" if observation
                                       or probe["Operation"] == "wait_threads" else "unverifiable"),
                            **({"Reason": "targeted_status_metadata_unavailable"}
                               if not explicit_error and not observation and probe["Operation"] == "read_thread"
                               else {}),
                            **({"terminal_observation": observation} if observation else {})})
                if not inventory_pending or inventory_pending not in {True, call_id}:
                    continue
                if isinstance(raw, dict) and isinstance(raw.get("agents"), list):
                    inventories.append({"Observed at": row["timestamp"], "Status source": "list_agents",
                                        "raw_response": raw})
                inventory_pending = None
    intervals.extend((start, observed_until) for start in active.values())
    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    worker_seconds = sum((end - start).total_seconds() for start, end in merged)
    elapsed = (observed_until - started).total_seconds()
    return {"schema_version": 1, "parent_thread_id": parent_thread_id, "run_started_at": started_at,
            "timing": {"observed_until": observed_until.isoformat(), "elapsed_seconds": elapsed,
                       "worker_active_seconds": worker_seconds, "no_worker_active_seconds": elapsed - worker_seconds,
                       "open_worker_intervals": len(active)},
            "provider_session": str(path.resolve()), "events": events, "failed_dispatches": failed_dispatches,
            "thread_mappings": mappings, "inventories": inventories, "status_probes": status_probes,
            "identity_sessions": [str(source.resolve()) for source in identity_sessions]}


def dispatched_worker_handles(ledger: dict) -> list[str]:
    """Return every observed worker handle, including a started child whose spawn later failed."""
    events = ledger.get("events", [])
    failures = ledger.get("failed_dispatches", [])
    mappings = ledger.get("thread_mappings", {})
    if not isinstance(events, list) or not isinstance(failures, list) or not isinstance(mappings, dict):
        raise ValueError("runtime_dispatch_ledger_invalid")
    handles = set()
    for row in [*events, *failures]:
        if not isinstance(row, dict):
            raise ValueError("runtime_dispatch_rows_invalid")
        handle = row.get("Provider handle")
        if handle is None:
            continue  # A failed spawn with no observed child was never activated.
        if not isinstance(handle, str) or not handle or handle not in mappings:
            raise ValueError("runtime_dispatch_thread_mapping_required")
        handles.add(handle)
    return sorted(handles)


def latest_worker_dispatch(ledger: dict, handle: str, *, include_failed: bool = False) -> dict:
    dispatches = [row for row in ledger["events"] if row.get("Provider handle") == handle]
    failures = [row for row in ledger.get("failed_dispatches", []) if row.get("Provider handle") == handle]
    if include_failed:
        dispatches += failures
    if not dispatches:
        raise ValueError("worker_trace_dispatch_unavailable:" + handle)
    latest = max(dispatches, key=lambda row: timestamp(row["Last dispatch at"]))
    if not include_failed and any(timestamp(row["Last dispatch at"]) >= timestamp(latest["Last dispatch at"])
                                  for row in failures):
        raise ValueError("latest_worker_dispatch_failed:" + handle)
    return latest


def runtime_configurations(source: Path, thread: str, observed_at: str) -> list[dict]:
    with source.open() as stream:
        first = json.loads(next(stream))
        if first.get("type") != "session_meta" or first.get("payload", {}).get("id") != thread:
            raise ValueError("worker_trace_session_mismatch")
        return [{"observed_at": row["timestamp"], "model": row["payload"].get("model"),
                 "effort": row["payload"].get("effort")} for row in map(json.loads, stream)
                if row.get("type") == "turn_context" and timestamp(row["timestamp"]) <= timestamp(observed_at)]


def launch_binding_errors(trace: dict, root: Path, role: str, ledger: dict | None = None) -> list[str]:
    """Check provider launch and child execution metadata, independently of instruction delivery."""
    try:
        bindings = json.loads((root / "role_bindings.json").read_text())
        role = worker_binding(bindings, role)
        contract = bindings.get("runtime_evidence", {})
        if not contract:
            return []
        if ledger is None:
            saved = json.loads(Path(contract["ledger"]).read_text())
            ledger = read_runtime_events(Path(saved["provider_session"]), saved["parent_thread_id"],
                                         saved["run_started_at"], tuple(Path(p) for p in saved.get("identity_sessions", [])))
        handle = trace["spawn"]["provider_handle"]
        launches = [row for row in ledger["events"] if row.get("Provider handle") == handle
                    and row.get("Operation") == "spawn_agent"]
        if not launches:
            return ["worker_launch_receipt_required:" + role] if contract.get("launch_binding_required") else []
        launch = launches[0].get("Launch", {})
        if not contract.get("launch_binding_required") and not any(launch.values()):
            return []
        expected = bindings["bindings"][role]
        errors = []
        if launch.get("fork_turns") != "none":
            errors.append("worker_fresh_context_required:" + role)
        if launch.get("model") != expected["model"]:
            errors.append("worker_launch_model_mismatch:" + role)
        if launch.get("reasoning_effort") != expected["effort"]:
            errors.append("worker_launch_effort_mismatch:" + role)
        observed = runtime_configurations(Path(trace["trace_retrieval"]), trace["thread_id"],
                                          trace["status_observation"]["Observed at"])
        if trace.get("launch") != launch or trace.get("runtime_configurations") != observed:
            errors.append("worker_launch_receipt_mismatch:" + role)
        for value in observed:
            if value.get("model") != expected["model"] or value.get("effort") != expected["effort"]:
                errors.append("worker_runtime_configuration_mismatch:" + role)
        return list(dict.fromkeys(errors))
    except (OSError, ValueError, KeyError, TypeError, AttributeError, StopIteration) as error:
        return ["worker_launch_evidence_invalid:" + role + ":" + str(error)]
