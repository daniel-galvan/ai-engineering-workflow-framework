"""Native provider observations and prepared worker identity resolution."""

from __future__ import annotations

import json
import os
import re
import shlex
from datetime import datetime
from pathlib import Path

UUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")

DELIVERY_WORKERS = {"implement": "implementer", "review": "reviewer", "validate": "tester", "handoff": "documenter"}


def _verified_empty_memory_search(command: str, observation: dict) -> bool:
    """Recognize only a native, no-result search of the host memory index."""
    try:
        argv = shlex.split(command)
    except ValueError:
        return False
    if len(argv) != 4 or Path(argv[0]).name != "rg" or argv[1] not in {"-n", "--line-number"}:
        return False
    query, target = argv[2], Path(argv[3])
    if not query or not target.is_absolute() or target.parts[-3:] != (".codex", "memories", "MEMORY.md"):
        return False
    parsed = observation.get("parsed_cmd")
    if (observation.get("exit_code") != 1 or isinstance(observation.get("exit_code"), bool)
            or observation.get("aggregated_output") != "" or observation.get("status") != "failed"
            or not isinstance(parsed, list) or len(parsed) != 1 or not isinstance(parsed[0], dict)):
        return False
    item = parsed[0]
    return (item.get("type") == "search" and item.get("query") == query
            and Path(str(item.get("path", ""))).name == "MEMORY.md")


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
                         expected_turn_id: str | None = None, runtime_evidence: dict | None = None) -> dict:
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
        turn, operations, children, errors = None, [], set(known_children), []
        command_observations: dict[str, list[dict]] = {}
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
                operations, children, errors = [], set(known_children), []
                command_observations = {}
            elif turn and (expected_turn_id is None or turn == expected_turn_id) and row.get("type") == "event_msg":
                item = payload.get("item", {})
                if item.get("type") == "SubAgentActivity" and item.get("kind") == "started":
                    children.add(item.get("agent_thread_id"))
                elif (payload.get("type") == "item_completed" and item.get("type") == "CommandExecution"
                      and isinstance(item.get("command"), list) and item["command"]
                      and isinstance(item["command"][-1], str)):
                    command_observations.setdefault(item["command"][-1], []).append(item)
            elif turn and (expected_turn_id is None or turn == expected_turn_id) and row.get("type") == "response_item" and payload.get("type") in {
                    "function_call", "custom_tool_call"}:
                calls = _tool_operations(payload)
                if not calls and payload.get("type") == "custom_tool_call" and "tools." in str(payload.get("input", "")):
                    errors.append("parent_tool_arguments_unavailable")
                for name, arguments in calls:
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
                        errors.append("parent_unassigned_thread_discovery")
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
    exempt = set()
    empty_memory_probes = 0
    for command, indexes in operation_indexes.items():
        observations = command_observations.get(command, [])
        if (len(indexes) == 1 and len(observations) == 1
                and _verified_empty_memory_search(command, observations[0])):
            exempt.add(indexes[0])
            empty_memory_probes += 1
    audited_operations = [operation for index, operation in enumerate(operations) if index not in exempt]
    details = []
    errors.extend(context_trace_errors({"tool_trace": audited_operations}, details=details,
                                      input_paths=input_paths, artifact_root=artifact_root))
    return {"status": "rejected" if errors else "passed", "provider_session": str(source.resolve()),
            "parent_thread_id": thread, "turn_id": turn, "errors": list(dict.fromkeys(errors)),
            "context_violations": details, "empty_memory_probes": empty_memory_probes}


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
            runtime_evidence=manifest.get("runtime_evidence"))
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
        events, mappings, inventories, failed_dispatches = [], {}, [], []
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
            elif payload.get("type") == "function_call_output":
                call_id = payload.get("call_id")
                if (call_id not in pending_followups and call_id not in spawn_calls
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
            "thread_mappings": mappings, "inventories": inventories,
            "identity_sessions": [str(source.resolve()) for source in identity_sessions]}


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
