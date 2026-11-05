"""Native provider observations and prepared worker identity resolution."""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
from datetime import datetime, timezone
from pathlib import Path

UUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")

DELIVERY_WORKERS = {"implement": "implementer", "review": "reviewer", "validate": "tester", "handoff": "documenter"}
RELATED_RUN_STATUS_FIELDS = {"id", "status", "hostId", "kind", "updatedAt"}
RELATED_RUN_TERMINAL_STATUSES = {"completed", "failed", "stopped", "interrupted", "cancelled", "idle", "archived",
                                "not_found"}


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
    bindings = ledger = None
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
                elif row.get("Operation") in {"send_message", "followup_task"} and row.get("Status") == "failed":
                    add(mappings.get(row.get("Provider handle")), required=True)
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
            elif "terminal_observations" not in closure and isinstance(bindings, dict) and isinstance(ledger, dict):
                # A blocked closure has no terminal observations; authenticate its identities, then probe them anew.
                try:
                    rows = closure["runtime_closure"]
                    row = rows[0]
                    parent = bindings["parent_context"]
                    contract = bindings["runtime_evidence"]
                    source = Path(ledger["provider_session"])
                    if (len(rows) != 1 or row["Runtime status"] != "Blocked"
                            or row["Run or stage"] != "Current run" or row["Receipt owner"] != "Coordinator"
                            or ledger["parent_thread_id"] != parent["parent_thread_id"]
                            or source.resolve() != Path(parent["provider_session"]).resolve()
                            or timestamp(ledger["run_started_at"]) != timestamp(contract["run_started_at"])):
                        raise ValueError("receipt mismatch")
                    handles = dispatched_worker_handles(ledger)
                    evidence = row["Closure evidence or blocker"]
                    if (not handles or set(handles) != set(mappings) or len(set(mappings.values())) != len(mappings)
                            or not isinstance(evidence, str)
                            or not (evidence.endswith("; dispatched handles: " + "; ".join(handles))
                                    or (evidence.startswith("Provider closure collection failed: ")
                                        and len(evidence) > len("Provider closure collection failed: ")))):
                        raise ValueError("worker identity mismatch")
                    for event in ledger["events"]:
                        if mappings.get(event.get("Provider handle")) != event.get("Thread ID"):
                            raise ValueError("dispatch identity mismatch")
                    native = read_runtime_events(source, ledger["parent_thread_id"], ledger["run_started_at"],
                                                 tuple(Path(value) for value in ledger.get("identity_sessions", [])))
                    if any(ledger.get(key, []) != native.get(key, [])
                           for key in ("events", "thread_mappings", "failed_dispatches")):
                        raise ValueError("stale ledger")
                except (OSError, ValueError, KeyError, TypeError, IndexError, StopIteration, AttributeError) as error:
                    raise ValueError("stale_run_closure_identity_invalid") from error
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
    if not identities and isinstance(bindings, dict):
        parent_context = bindings.get("parent_context")
        packet_path = artifact_root / "finalization_packet.json"
        if isinstance(parent_context, dict) and packet_path.is_file():
            packet = _read_status_receipt(packet_path)
            identity = packet.get("identity", {})
            saved_ids = parent_context.get("related_run_thread_ids", [])
            if not isinstance(saved_ids, list):
                raise ValueError("stale_run_thread_identity_invalid")
            if (bindings.get("run_id") == identity.get("Run ID")
                    and identity.get("State") == "in_progress"
                    and parent_context.get("parent_thread_id") == current_thread_id):
                for value in saved_ids:
                    add(value, required=True)
    identities.discard(current_thread_id)
    return tuple(sorted(identities))


def scoped_prior_run_status_thread_ids(
    artifact_root: Path, current_thread_id: str, authorized_prior_parent_thread_id: str | None = None,
) -> tuple[str, ...]:
    """Read prior identities only for this chat or a parent the user explicitly authorized."""
    if not isinstance(current_thread_id, str) or not UUID.fullmatch(current_thread_id):
        raise ValueError("stale_run_thread_identity_invalid")
    if (authorized_prior_parent_thread_id is not None
            and (not isinstance(authorized_prior_parent_thread_id, str)
                 or not UUID.fullmatch(authorized_prior_parent_thread_id))):
        raise ValueError("stale_run_status_authorization_invalid")
    bindings_path = artifact_root / "role_bindings.json"
    bindings = _read_status_receipt(bindings_path) if bindings_path.is_file() else {}
    if not isinstance(bindings, dict):
        raise ValueError("stale_run_thread_identity_invalid")
    parent_context = bindings.get("parent_context")
    if parent_context is not None and not isinstance(parent_context, dict):
        raise ValueError("stale_run_thread_identity_invalid")
    prior_parent = parent_context.get("parent_thread_id") if isinstance(parent_context, dict) else None
    ledger_path = artifact_root / "runtime_dispatches.json"
    ledger = _read_status_receipt(ledger_path) if ledger_path.is_file() else {}
    ledger_parent = ledger.get("parent_thread_id") if isinstance(ledger, dict) else None
    if prior_parent is not None and ledger_parent is not None and prior_parent != ledger_parent:
        raise ValueError("stale_run_thread_identity_invalid")
    prior_parent = prior_parent or ledger_parent
    has_prior_receipts = any((artifact_root / name).is_file() for name in (
        "role_bindings.json", "runtime_dispatches.json", "runtime_closure.json"))
    if not prior_parent:
        if has_prior_receipts:
            raise ValueError("stale_run_parent_identity_invalid")
        return ()
    if not isinstance(prior_parent, str) or not UUID.fullmatch(prior_parent):
        raise ValueError("stale_run_thread_identity_invalid")
    if authorized_prior_parent_thread_id is not None and authorized_prior_parent_thread_id != prior_parent:
        raise ValueError("stale_run_status_authorization_mismatch")
    if prior_parent != current_thread_id and authorized_prior_parent_thread_id != prior_parent:
        raise ValueError("prior_run_status_requires_user_authorization")
    return prior_run_status_thread_ids(artifact_root, current_thread_id)


def related_run_status_projection_source(
    work_item: str, current_thread_id: str, prior_thread_ids: tuple[str, ...] = (),
) -> str:
    """Return a redacted, batched status snapshot for explicitly authorized prior threads."""
    if not isinstance(work_item, str) or not re.fullmatch(r"[A-Za-z0-9._-]+", work_item):
        raise ValueError("stale_run_status_work_item_invalid")
    if not isinstance(current_thread_id, str) or not UUID.fullmatch(current_thread_id):
        raise ValueError("stale_run_status_thread_id_invalid")
    if (not isinstance(prior_thread_ids, tuple)
            or any(not isinstance(value, str) or not UUID.fullmatch(value) for value in prior_thread_ids)):
        raise ValueError("stale_run_status_prior_thread_ids_invalid")
    return (f"const priorIds = {json.dumps(list(prior_thread_ids))};\n"
            "const terminal = new Set(['completed', 'failed', 'stopped', 'interrupted', 'cancelled']);\n"
            "const batches = [];\n"
            "for (let i = 0; i < priorIds.length; i += 8) batches.push(priorIds.slice(i, i + 8));\n"
            "const relatedRows = (await Promise.all(batches.map(async ids => {\n"
            "  try {\n"
            "    const result = await tools.mcp__codex_app__wait_threads({\n"
            "      targets: ids.map(threadId => ({threadId})), timeoutMs: 0\n"
            "    });\n"
            "    if (result.isError || !Array.isArray(result.content) || result.content.length !== 1)\n"
            "      return ids.map(id => ({id, status: 'unavailable'}));\n"
            "    const snapshot = JSON.parse(result.content[0].text);\n"
            "    const polls = Array.isArray(snapshot.polls) ? snapshot.polls : [];\n"
            "    const byId = new Map(polls.map(poll => [poll.thread?.id, poll]));\n"
            "    return ids.map(id => {\n"
            "      const poll = byId.get(id);\n"
            "      const latestTurn = poll?.latestTurn;\n"
            "      const threadStatus = poll?.thread?.status;\n"
            "      const inactive = ['idle', 'ready'].includes(threadStatus?.type) && !threadStatus.activeFlags?.length\n"
            "        || snapshot.wake?.threadId === id && snapshot.wake.reason === 'inactiveStatus';\n"
            "      return {id, status: inactive && terminal.has(latestTurn?.status)\n"
            "        ? latestTurn.status : 'unavailable'};\n"
            "    });\n"
            "  } catch { return ids.map(id => ({id, status: 'unavailable'})); }\n"
            "}))).flat();\n"
            "text(JSON.stringify(relatedRows));")


def _related_run_status_rows(payload: dict) -> list[dict]:
    output = payload.get("output")
    if isinstance(output, list):
        texts = [row.get("text") for row in output if isinstance(row, dict)
                 and row.get("type") in {"text", "input_text", "output_text"}
                 and isinstance(row.get("text"), str)]
        if (len(texts) == len(output) == 2
                and re.fullmatch(r"Script completed\nWall time [0-9]+(?:\.[0-9]+)? seconds\nOutput:\n", texts[0])):
            texts = texts[1:]
        elif len(texts) != len(output) or len(texts) != 1:
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
                       and not (key == "updatedAt" and type(row[key]) is int)
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
        status = row.get("status", "").lower()
        if status == "unavailable":
            errors.append("stale_run_related_task_status_unavailable:" + row.get("id", "unknown"))
        elif status not in RELATED_RUN_TERMINAL_STATUSES:
            errors.append("stale_run_related_task_active:" + row.get("id", "unknown"))
    if require_prior_dispatch_ledger and context.get("prior_run_dispatch_ledger_present") is not True:
        errors.append("stale_run_dispatch_ledger_required")
    return errors


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


def _literal_worker_status_observation(source: str) -> list[tuple[str, dict]] | None:
    """Recognize a complete literal status read plus local output formatting."""
    prefix = re.match(r'^\s*const r = await tools\.mcp__codex_app__read_thread\(\{threadId:"([0-9a-fA-F-]+)",turnLimit:1,includeOutputs:false\}\);', source)
    if not prefix or not UUID.fullmatch(prefix[1]):
        return None
    body = '''
const raw = r.content?.find(x=>x.type==="text")?.text || "";
const data = JSON.parse(raw);
const turn = data.turns?.[0];
const observed = await tools.clock__curr_time({});
text(JSON.stringify({
  thread_id:data.thread?.id,
  thread_status:data.thread?.status?.type,
  latest_turn_id:turn?.id,
  latest_turn_status:turn?.status,
  latest_turn_started_at:new Date(turn.startedAt*1000).toISOString(),
  latest_turn_completed_at:new Date(turn.completedAt*1000).toISOString(),
  observed_at:observed.current_time.replace(" UTC","T").replace(" ","").replace(/(\\d{2}:\\d{2}:\\d{2})T/, "$1Z")
}));'''
    if source[prefix.end():].strip() != body.strip():
        return None
    return [("mcp__codex_app__read_thread", {"threadId": prefix[1], "turnLimit": 1, "includeOutputs": False}),
            ("clock__curr_time", {})]


def _literal_parent_thread_read_batch(source: str) -> list[tuple[str, dict]] | None:
    """Expand only the literal assigned-thread status loop used by coordinator closure."""
    wait_batch = re.fullmatch(r'\s*const ids\s*=\s*(\[[\s\S]*?\]);\s*(?P<body>[\s\S]*)', source)
    wait_body = ('const rs=await Promise.allSettled(ids.map(threadId=>tools.mcp__codex_app__wait_threads({targets:[{threadId,hostId:"local"}],timeoutMs:0})));\n'
                 'for(let i=0;i<rs.length;i++){\n'
                 ' if(rs[i].status!=="fulfilled"){text(JSON.stringify({i,error:String(rs[i].reason)}));continue;}\n'
                 ' const raw=rs[i].value.content?.[0]?.text||"";\n'
                 ' try {const d=JSON.parse(raw); const p=d.polls?.[0]||{}; text(JSON.stringify({i,threadId:ids[i],wake:d.wake,thread:p.thread,latestTurn:p.latestTurn,revision:p.revision,cursor:p.cursor}));} catch {text(JSON.stringify({i,raw:raw.slice(0,200)}));}\n'
                 '}')
    if wait_batch and wait_batch["body"].strip() == wait_body:
        try:
            identities = json.loads(wait_batch[1])
        except json.JSONDecodeError:
            return None
        if (isinstance(identities, list) and identities and len(identities) <= 8
                and all(isinstance(identity, str) and UUID.fullmatch(identity) for identity in identities)):
            return [("mcp__codex_app__wait_threads", {"targets": [{"threadId": identity, "hostId": "local"}],
                     "timeoutMs": 0}) for identity in identities]
        return None
    match = re.fullmatch(
        r'\s*const ids\s*=\s*(\[[\s\S]*?\]);\s*'
        r'for\s*\(const\s*\[threadId,\s*handle\]\s*of\s*ids\)\s*\{\s*'
        r'const r\s*=\s*await tools\.mcp__codex_app__read_thread\('
        r'\{threadId,\s*turnLimit:\s*1,\s*includeOutputs:\s*false,\s*maxOutputCharsPerItem:\s*1\}\);'
        r'(?P<body>[\s\S]*)\}\s*', source)
    if (not match or source.count("tools.") != 1 or len(re.findall(r"\bids\b", source)) != 2
            or re.search(r"\b(?:ids|threadId|for|while|function|eval|Function|globalThis|constructor|"
                         r"return|throw|break|continue)\b|=>", match["body"])):
        return None
    try:
        identities = json.loads(match[1])
    except json.JSONDecodeError:
        return None
    if (not isinstance(identities, list) or not identities
            or any(not isinstance(row, list) or len(row) != 2
                   or not isinstance(row[0], str) or not UUID.fullmatch(row[0])
                   or not isinstance(row[1], str) for row in identities)):
        return None
    return [("mcp__codex_app__read_thread", {"threadId": identity, "turnLimit": 1,
             "includeOutputs": False, "maxOutputCharsPerItem": 1}) for identity, _ in identities]


def _literal_command_batch(source: str) -> list[tuple[str, dict]] | None:
    """Expand a bounded literal command batch without executing its JavaScript."""
    match = re.fullmatch(
        r'\s*const cmds\s*=\s*(\[[\s\S]*?\]);\s*'
        r'const results\s*=\s*await Promise\.all\(cmds\.map\(async \(\[name,\s*cmd\]\)\s*=>\s*\{\s*'
        r'const r\s*=\s*await tools\.exec_command\(\{cmd,\s*workdir:("(?:[^"\\]|\\.)*"),\s*'
        r'yield_time_ms:(\d+),\s*max_output_tokens:(\d+)\}\);\s*'
        r'return `\$\{name\}\\n\$\{r\.output\}`;\s*\}\)\);\s*'
        r'for\s*\(const r of results\)\s*text\(r\);\s*', source)
    if not match:
        return None
    try:
        commands, workdir = json.loads(match[1]), json.loads(match[2])
    except (ValueError, TypeError):
        return None
    if (not isinstance(commands, list) or not 1 <= len(commands) <= 32
            or any(not isinstance(row, list) or len(row) != 2
                   or not all(isinstance(value, str) for value in row)
                   or "$" in row[1] or "`" in row[1] for row in commands)):
        return None
    return [("exec_command", {"cmd": command, "workdir": workdir,
                              "yield_time_ms": int(match[3]), "max_output_tokens": int(match[4])})
            for _, command in commands]


def _incomplete_literal_command(source: str) -> list[tuple[str, dict]] | None:
    """Audit the literal command even when its JavaScript call is missing the closing parenthesis."""
    match = re.fullmatch(r'\s*const\s+\w+\s*=\s*await\s+tools\.exec_command\(\{\s*cmd\s*:\s*("(?:[^"\\]|\\.)*")\s*\}\s*', source)
    if not match:
        return None
    try:
        return [("exec_command", {"cmd": json.loads(match[1])})]
    except ValueError:
        return None


def _same_cached_package_script(candidate: Path, script_dir: Path, filename: str) -> bool:
    candidate = candidate.resolve()
    anchor = script_dir.resolve()
    if candidate == anchor / filename:
        return True
    if anchor.name != "scripts" or candidate.name != filename or candidate.parent.name != "scripts":
        return False
    family = anchor.parent.parent
    return (candidate.parent.parent.parent == family
            and ".codex/plugins/cache/" in str(family) + "/"
            and bool(re.fullmatch(r"[0-9]+(?:\.[0-9]+)*\+codex\.[0-9]+", candidate.parent.parent.name)))


def _redact_current_session_projection(command: str, source: Path, script_dir: Path) -> str:
    """Allow the exact current session path only as the status-projection input."""
    try:
        args = shlex.split(command)
        if (len(args) < 5 or not re.fullmatch(r"python(?:3(?:\.\d+)*)?", Path(args[0]).name)
                or not _same_cached_package_script(Path(args[1]), script_dir, "prepare_run.py")):
            return command
        flags = {"--status-projection", "--continuation", "--planning-recovery"}
        allowed = {"--execution-repository", "--work-item", "--provider-session", "--playbook",
                   "--approval-reference", "--input-manifest", "--authorize-prior-parent-thread"}
        values, seen_flags, index = {}, set(), 2
        while index < len(args):
            option = args[index]
            if option in flags and option not in seen_flags:
                seen_flags.add(option)
                index += 1
            elif option in allowed and option not in values and index + 1 < len(args):
                values[option] = args[index + 1]
                index += 2
            else:
                return command
        if (not seen_flags.intersection({"--status-projection", "--continuation"})
                or ("--status-projection" in seen_flags and "--continuation" in seen_flags)
                or ("--planning-recovery" in seen_flags and "--continuation" not in seen_flags)
                or "--provider-session" not in values
                or ("--work-item" in values and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", values["--work-item"]))
                or Path(values["--provider-session"]).resolve() != source.resolve()):
            return command
        args[args.index("--provider-session") + 1] = "<current-provider-session>"
        return shlex.join(args)
    except (OSError, ValueError):
        return command


def _redact_current_runtime_collection(command: str, source: Path, thread: str, runtime_evidence: dict | None,
                                       artifact_root: Path | None, known_children: set[str], script_dir: Path,
                                       previous_collector: Path | None, prior_started_at: datetime | None) -> str:
    if not runtime_evidence or artifact_root is None:
        return command
    try:
        args = shlex.split(command)
        collector = Path(runtime_evidence["collector"]).resolve()
        allowed_collectors = {collector}
        if previous_collector:
            allowed_collectors.add(Path(previous_collector).resolve())
        if (len(args) < 10 or not re.fullmatch(r"python(?:3(?:\.\d+)*)?", Path(args[0]).name)
                or collector != (script_dir / "worker_runtime_evidence.py").resolve()
                or (Path(args[1]).resolve() not in allowed_collectors
                    and not _same_cached_package_script(Path(args[1]), script_dir, "worker_runtime_evidence.py"))):
            return command
        values, index = {}, 2
        allowed = {"--provider-session", "--parent-thread-id", "--started-at", "--ledger",
                   "--worker-session", "--worker-thread-id", "--observation", "--agent", "--trace",
                   "--closure", "--pending-closure", "--blocked-closure", "--blocker"}
        while index < len(args):
            option = args[index]
            if option not in allowed or option in values or index + 1 == len(args):
                return command
            values[option] = args[index + 1]
            index += 2
        required = {"--provider-session", "--parent-thread-id", "--started-at", "--ledger"}
        run_root = artifact_root.resolve()
        ledger = run_root / "runtime_dispatches.json"
        if (not required.issubset(values)
                or Path(values["--provider-session"]).resolve() != source.resolve()
                or not UUID.fullmatch(values["--parent-thread-id"])
                or (timestamp(values["--started-at"]) != timestamp(runtime_evidence["run_started_at"])
                    and (prior_started_at is None or timestamp(values["--started-at"]) != prior_started_at))
                or Path(runtime_evidence["ledger"]).resolve() != ledger
                or Path(values["--ledger"]).resolve() != ledger
                ):
            return command
        closure_modes = [name for name in ("--closure", "--pending-closure", "--blocked-closure")
                         if name in values]
        trace_options = {"--worker-session", "--worker-thread-id", "--observation", "--agent", "--trace"}
        if closure_modes:
            mode = closure_modes[0]
            if (len(closure_modes) != 1 or any(name in values for name in trace_options)
                    or ("--blocker" in values) != (mode == "--blocked-closure")
                    or Path(values[mode]).resolve().parent != run_root):
                return command
        elif not any(name in values for name in trace_options):
            if set(values) != required:
                return command
        else:
            if ("--blocker" in values or not {"--agent", "--trace"}.issubset(values)
                    or ("--worker-session" in values) == ("--worker-thread-id" in values)
                    or not re.fullmatch(r"[A-Za-z0-9_.-]+", values["--agent"])
                    or Path(values["--trace"]).resolve().parent != run_root
                    or ("--observation" in values
                        and not Path(values["--observation"]).resolve().is_relative_to(run_root))):
                return command
            if "--worker-thread-id" in values:
                worker_id = values["--worker-thread-id"]
                if not UUID.fullmatch(worker_id) or worker_id not in known_children:
                    return command
            else:
                sessions_root = next((path.resolve() for path in source.resolve().parents
                                      if path.name == "sessions" and path.parent.name == ".codex"), None)
                worker_session = Path(values["--worker-session"]).resolve(strict=True)
                if (sessions_root is None or worker_session.suffix != ".jsonl"
                        or not worker_session.is_relative_to(sessions_root)):
                    return command
                worker_ids = UUID.findall(worker_session.name)
                with worker_session.open() as stream:
                    worker_header = json.loads(next(stream, ""))
                worker_payload = worker_header.get("payload") if isinstance(worker_header, dict) else None
                worker_id = worker_payload.get("id") if isinstance(worker_payload, dict) else None
                if (worker_header.get("type") != "session_meta" or not isinstance(worker_id, str)
                        or worker_id not in known_children or len(worker_ids) != 1
                        or worker_ids[0].casefold() != worker_id.casefold()):
                    return command
        if "--observation" in values and "--trace" not in values:
            return command
        args[args.index("--provider-session") + 1] = "<current-parent-session>"
        if "--worker-session" in values:
            args[args.index("--worker-session") + 1] = "<current-run-worker-session>"
        return shlex.join(args)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return command


def _redact_workflow_failure(command: str, source: Path, thread: str, runtime_evidence: dict | None,
                             artifact_root: Path | None, script_dir: Path) -> str:
    if not runtime_evidence or artifact_root is None:
        return command
    try:
        args = shlex.split(command)
        if (len(args) != 10 or not re.fullmatch(r"python(?:3(?:\.\d+)*)?", Path(args[0]).name)
                or not _same_cached_package_script(Path(args[1]), script_dir, "finalize_work_record.py")):
            return command
        values = dict(zip(args[2::2], args[3::2]))
        if (set(values) != {"--workflow-failure", "--packet", "--provider-session", "--parent-thread-id"}
                or not re.fullmatch(r"[A-Za-z0-9_:.-]+", values["--workflow-failure"])
                or Path(values["--packet"]).resolve() != artifact_root.resolve() / "finalization_packet.json"
                or Path(values["--provider-session"]).resolve() != source.resolve()
                or values["--parent-thread-id"] != thread):
            return command
        args[args.index("--provider-session") + 1] = "<current-parent-session>"
        return shlex.join(args)
    except (OSError, ValueError, KeyError, TypeError):
        return command


def parent_context_audit(source: Path, *, artifact_root: Path | None = None,
                         input_paths: tuple[str, ...] = (), expected_thread_id: str | None = None,
                         expected_turn_id: str | None = None, runtime_evidence: dict | None = None,
                         related_run_thread_ids: tuple[str, ...] | None = None,
                         prior_dispatch_ledger_present: bool | None = None,
                         framework_root: Path | None = None,
                         require_preflight_order: bool = False,
                         audit_script_dir: Path | None = None,
                         audit_previous_collector: Path | None = None) -> dict:
    """Audit current-turn operations without importing messages or previous analytical content."""
    try:
        from runtime_checks import _tool_operations, context_trace_errors
    except ModuleNotFoundError:
        from scripts.runtime_checks import _tool_operations, context_trace_errors
    script_dir = audit_script_dir or Path(__file__).resolve().parent
    prior_started_at = None
    if artifact_root and (artifact_root / "finalization_packet.json").is_file():
        try:
            packet = json.loads((artifact_root / "finalization_packet.json").read_text())
            prior_id = packet.get("recovery", {}).get("Prior run ID", "")
            match = re.search(r"-(\d{8}T\d{12}Z)$", prior_id)
            if match:
                prior_started_at = datetime.strptime(match[1], "%Y%m%dT%H%M%S%fZ").replace(tzinfo=timezone.utc)
        except (OSError, ValueError, TypeError, AttributeError):
            pass
    with source.open() as stream:
        header = json.loads(next(stream, ""))
        thread = header.get("payload", {}).get("id")
        if (header.get("type") != "session_meta" or not isinstance(thread, str) or not UUID.fullmatch(thread)
                or expected_thread_id is not None and thread != expected_thread_id):
            raise ValueError("provider_session_parent_mismatch")
        known_children = set()
        native_events = []
        if runtime_evidence:
            native = read_runtime_events(source, thread, runtime_evidence["run_started_at"],
                tuple(Path(value) for value in runtime_evidence.get("identity_sessions", [])))
            native_events = native["events"]
            known_children = {native["thread_mappings"][row["Provider handle"]] for row in native_events}
        identity_error = None
        try:
            if related_run_thread_ids is None:
                prior_ids = scoped_prior_run_status_thread_ids(artifact_root, thread) if artifact_root else ()
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
                    expected_ids = pending_related_run_status.pop(call_id)
                    if payload.get("isError") or payload.get("status") in {"failed", "error"}:
                        errors.append("parent_related_run_status_output_invalid")
                    else:
                        try:
                            rows = _related_run_status_rows(payload)
                            if not {item["id"] for item in rows}.issubset(set(expected_ids)):
                                raise ValueError("parent_related_run_status_output_invalid")
                            related_run_status_rows = rows
                            verified_related_run_status_probes += 1
                        except ValueError as error:
                            errors.append(str(error))
            elif turn and (expected_turn_id is None or turn == expected_turn_id) and row.get("type") == "response_item" and payload.get("type") in {
                    "function_call", "custom_tool_call"}:
                raw_source = payload.get("input") if payload.get("type") == "custom_tool_call" else None
                try:
                    ids_to_check = [prior_ids]
                    if known_children:
                        # Later dispatches cannot retroactively change an earlier exact status query.
                        observed = timestamp(row["timestamp"])
                        at_call = {event["Thread ID"] for event in native_events
                                   if timestamp(event["Last dispatch at"]) <= observed}
                        if at_call:
                            ids_to_check.extend((tuple(sorted(at_call)), tuple(sorted(set(prior_ids) | at_call))))
                    matched_projection_ids = next((ids for ids in ids_to_check
                        if artifact_root is not None and isinstance(raw_source, str)
                        and raw_source.strip() == related_run_status_projection_source(
                            artifact_root.name, thread, ids)), None)
                except (ValueError, KeyError, TypeError):
                    matched_projection_ids = None
                exact_status_projection = matched_projection_ids is not None
                if exact_status_projection:
                    call_id = payload.get("call_id")
                    if not isinstance(call_id, str) or not call_id or related_run_probe_attempts:
                        errors.append("parent_related_run_status_probe_invalid")
                    else:
                        sequenced_operations.append({"name": "related_run_status_projection", "arguments": {}})
                        pending_related_run_status[call_id] = matched_projection_ids
                        related_run_probe_attempts += 1
                    continue
                calls = _tool_operations(payload)
                if not calls and payload.get("type") == "custom_tool_call":
                    calls = (_literal_worker_status_observation(raw_source) or _literal_parent_thread_read_batch(raw_source) or _literal_command_batch(raw_source)
                             or _incomplete_literal_command(raw_source) or [])
                if not calls and payload.get("type") == "custom_tool_call" and "tools." in str(raw_source or ""):
                    errors.append("parent_tool_arguments_unavailable")
                for name, arguments in calls:
                    sequenced_operations.append({"name": name, "arguments": arguments})
                    if name == "exec_command":
                        audit_arguments = arguments
                        command = arguments.get("cmd")
                        if isinstance(command, str):
                            redacted_lines = []
                            for line in command.splitlines(keepends=True):
                                text = line.rstrip("\r\n")
                                replacement = _redact_current_session_projection(text, source, script_dir)
                                if replacement == text:
                                    replacement = _redact_current_runtime_collection(
                                        text, source, thread, runtime_evidence, artifact_root, known_children, script_dir,
                                        audit_previous_collector, prior_started_at)
                                if replacement == text:
                                    replacement = _redact_workflow_failure(
                                        text, source, thread, runtime_evidence, artifact_root, script_dir)
                                redacted_lines.append(replacement + line[len(text):])
                            redacted = "".join(redacted_lines)
                            if redacted != command:
                                audit_arguments = {**arguments, "cmd": redacted}
                        operations.append({"type": "function_call", "name": name, "arguments": audit_arguments})
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
                            status_only_prior = (identity in prior_ids and isinstance(raw_source, str)
                                and raw_source.strip() in {targeted_status_projection_source(identity),
                                                           targeted_wait_projection_source(identity)})
                            if (identity not in children and "codex://threads/" + str(identity) not in input_paths
                                    and not status_only_prior):
                                errors.append("parent_unassigned_thread_read:" + str(identity))
                    elif name.rsplit("__", 1)[-1] in {"list_threads", "list_archived_threads"}:
                        errors.append("parent_unassigned_thread_discovery")
                        operations.append({"type": "function_call", "name": name, "arguments": arguments})
        if pending_related_run_status:
            errors.append("parent_related_run_status_output_missing")
        if not isinstance(turn, str) or not UUID.fullmatch(turn):
            raise ValueError("provider_current_turn_unavailable")
        if expected_turn_id and turn != expected_turn_id:
            raise ValueError("provider_bound_turn_unavailable")
    if require_preflight_order and framework_root is not None:
        errors.extend(_preflight_order_errors(sequenced_operations, framework_root, command_observations))
    details = []
    errors.extend(context_trace_errors({"tool_trace": operations}, details=details,
                                      input_paths=input_paths, artifact_root=artifact_root))
    return {"status": "rejected" if errors else "passed", "provider_session": str(source.resolve()),
            "parent_thread_id": thread, "turn_id": turn, "errors": list(dict.fromkeys(errors)),
            "context_violations": details, "empty_memory_probes": 0, "host_memory_reads": 0,
            "verified_related_run_status_probes": verified_related_run_status_probes,
            "related_run_status_probe_attempts": related_run_probe_attempts,
            "related_run_status_rows": related_run_status_rows,
            "related_run_thread_ids": list(prior_ids),
            "prior_run_dispatch_ledger_present": bool(ledger_present)}

def _preflight_order_errors(operations: list[dict], framework_root: Path,
                            command_observations: dict[str, list[dict]]) -> list[str]:
    """Require package preflight before current-turn repository or workflow operations."""
    preflight_path = (framework_root.expanduser().resolve() / "scripts" / "run_preflight.py").resolve()
    skill_path = (framework_root.expanduser().resolve() / "skills" / "run" / "SKILL.md").resolve()
    completed_preflight = False
    for operation in operations:
        if operation.get("name") != "exec_command":
            if not completed_preflight:
                return ["parent_framework_content_before_preflight"]
            continue
        command = operation.get("arguments", {}).get("cmd")
        if not isinstance(command, str):
            continue
        try:
            argv = shlex.split(command)
        except ValueError:
            argv = []
        skill_read = (len(argv) == 2 and argv[0] == "cat" or
                      len(argv) == 4 and argv[:2] == ["sed", "-n"]
                      and re.fullmatch(r"[1-9][0-9]*(?:,[1-9][0-9]*)?p", argv[2]))
        bootstrap = bool(skill_read and (
            argv[-1] == "skills/run/SKILL.md"
            or Path(argv[-1]).is_absolute() and Path(argv[-1]).resolve() == skill_path))
        is_preflight = (
            len(argv) >= 2 and bool(re.fullmatch(r"python(?:3(?:\.\d+)*)?", Path(argv[0]).name))
            and Path(argv[1]).name == "run_preflight.py"
            and ((Path(argv[1]).is_absolute() and Path(argv[1]).resolve() == preflight_path)
                 or argv[1] in {"scripts/run_preflight.py", "./scripts/run_preflight.py"})
            and not any(token in {"&&", "||", ";", "|", ">", "<"} for token in argv)
        )
        if not completed_preflight and not bootstrap and not is_preflight:
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


def validate_prepared_provider_source(bindings: dict, source: Path, parent_thread_id: str, started_at: str, *,
                                      historical_recovery: bool = False) -> None:
    """Keep trace and failure-closure collection on the same prepared parent and run interval."""
    if not historical_recovery:
        current_parent_session(source)
    parent = bindings.get("parent_context")
    if historical_recovery and (not isinstance(parent, dict) or not bindings.get("runtime_evidence", {}).get("run_started_at")):
        raise ValueError("runtime_dispatch_historical_binding_required")
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


def targeted_status_projection_source(thread_id: str) -> str:
    """Return the exact status-only provider call recognized by the runtime ledger."""
    if not isinstance(thread_id, str) or not UUID.fullmatch(thread_id):
        raise ValueError("targeted_status_thread_id_invalid")
    return (f"const r = await tools.mcp__codex_app__read_thread({{threadId: {json.dumps(thread_id)}, "
            "turnLimit: 1, includeOutputs: false});\n"
            "if (r.isError || !Array.isArray(r.content) || r.content.length !== 1) throw new Error('status unavailable');\n"
            "const d = JSON.parse(r.content[0].text);\n"
            "const t = d.turns?.[0];\n"
            "text(JSON.stringify({thread: {id: d.thread?.id, status: d.thread?.status}, "
            "turns: t ? [{id: t.id, status: t.status, startedAt: t.startedAt, completedAt: t.completedAt}] : []}));")


def targeted_wait_projection_source(thread_id: str) -> str:
    """Return a status-only wait snapshot for a single verified child."""
    if not isinstance(thread_id, str) or not UUID.fullmatch(thread_id):
        raise ValueError("targeted_status_thread_id_invalid")
    return (f"const r = await tools.mcp__codex_app__wait_threads({{targets: [{{threadId: {json.dumps(thread_id)}}}], timeoutMs: 0}});\n"
            "if (r.isError || !Array.isArray(r.content) || r.content.length !== 1) throw new Error('status unavailable');\n"
            "const d = JSON.parse(r.content[0].text);\n"
            "if (!Array.isArray(d.polls) || d.polls.length !== 1) throw new Error('status unavailable');\n"
            "const p = d.polls[0];\n"
            "text(JSON.stringify({wake: d.wake, polls: [{thread: p.thread, latestTurn: p.latestTurn}]}));")


def provider_json_value(value):
    if (isinstance(value, list) and len(value) == 2
            and all(isinstance(row, dict) and row.get("type") == "input_text"
                    and isinstance(row.get("text"), str) for row in value)
            and re.fullmatch(r"Script completed\nWall time [0-9]+(?:\.[0-9]+)? seconds\nOutput:\n", value[0]["text"])):
        value = value[1]["text"]
    if isinstance(value, list) and len(value) == 1 and isinstance(value[0], dict) \
            and value[0].get("type") in {"text", "input_text", "output_text"} and isinstance(value[0].get("text"), str):
        value = value[0]["text"]
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            pass
    return value


def native_preflight_observed(source: Path, turn_id: str, root: Path, revision: str, plugin_version: str) -> bool:
    """Authenticate package selection from a completed command in the bound native turn."""
    try:
        with source.open() as stream:
            return _native_preflight_rows(stream, turn_id, root, revision, plugin_version)
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def native_finalization_observed(source: Path, turn_id: str, root: Path, packet: Path,
                                 record: Path, revision: str, canonical: bytes) -> bool:
    """Authenticate the original finalizer's successful canonical output, including after cache pruning."""
    try:
        with source.open() as stream:
            return _native_finalization_rows(stream, turn_id, root, packet, record, revision, canonical)
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def _native_finalization_rows(stream, turn_id: str, root: Path, packet: Path,
                              record: Path, revision: str, canonical: bytes) -> bool:
    turn = None
    required = {"--packet": str(packet), "--record": str(record),
                "--closure": str(packet.parent / "runtime_closure.json"),
                "--framework-revision": revision, "--framework-status": "clean"}
    try:
        for line in stream:
            row = json.loads(line)
            payload = row.get("payload", {})
            if row.get("type") == "turn_context":
                turn = payload.get("turn_id")
            item = payload.get("item", {})
            command = item.get("command", [])
            if (turn != turn_id or row.get("type") != "event_msg" or item.get("type") != "CommandExecution"
                    or item.get("status") != "completed" or item.get("exit_code") != 0
                    or not isinstance(command, list) or not command or not isinstance(command[-1], str)
                    or any(char in command[-1] for char in "$`;&<>|")):
                continue
            args = shlex.split(command[-1])
            if (len(args) < 2 or args[0] != "python3" and (not Path(args[0]).is_absolute()
                    or Path(args[0]).resolve() != Path(sys.executable).resolve())
                    or Path(args[1]).resolve() != root / "scripts/finalize_work_record.py" or len(args[2:]) % 2):
                continue
            flags = dict(zip(args[2::2], args[3::2]))
            if (len(flags) != len(args[2:]) // 2 or set(flags) - set(required) - {"--coordinator-model-effort"}
                    or any(flags.get(key) != value for key, value in required.items())):
                continue
            output = item.get("aggregated_output", "")
            if isinstance(output, str) and output.partition("Workflow-framework validation: passed\n")[2].encode() == canonical:
                return True
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return False


def _native_preflight_rows(stream, turn_id: str, root: Path, revision: str, plugin_version: str) -> bool:
    turn = None
    try:
        for line in stream:
            row = json.loads(line)
            payload = row.get("payload", {})
            if row.get("type") == "turn_context":
                turn = payload.get("turn_id")
            item = payload.get("item", {})
            if (turn != turn_id or row.get("type") != "event_msg" or item.get("type") != "CommandExecution"
                    or item.get("status") != "completed" or item.get("exit_code") != 0):
                continue
            command = item.get("command", [])
            if not isinstance(command, list) or not command or not isinstance(command[-1], str):
                continue
            if any(char in command[-1] for char in "$`;&<>|"):
                continue
            args = shlex.split(command[-1])
            if (len(args) < 2 or args[0] != "python3" and (not Path(args[0]).is_absolute()
                    or Path(args[0]).resolve() != Path(sys.executable).resolve())
                    or Path(args[1]).resolve() != root / "scripts/run_preflight.py"):
                continue
            try:
                result = json.loads(item.get("aggregated_output", ""))
            except (ValueError, TypeError):
                continue
            if (isinstance(result, dict) and result.get("status") == "passed"
                    and result.get("framework_revision") == revision and result.get("framework_status") == "clean"
                    and result.get("plugin_version") == plugin_version and result.get("framework_root") == str(root)):
                return True
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return False


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
    raw = provider_json_value(raw)
    if isinstance(raw, dict) and isinstance(raw.get("content"), list) and not (raw.get("isError") or raw.get("error")):
        raw = provider_json_value(raw["content"])
    if not isinstance(raw, dict):
        return None
    if operation == "wait_threads":
        wake, polls = raw.get("wake"), raw.get("polls")
        if (not isinstance(polls, list) or len(polls) != 1 or not isinstance(polls[0], dict)
                or raw.get("errors") or raw.get("isError") or raw.get("error")):
            return None
        poll = polls[0]
        thread, latest = poll.get("thread"), poll.get("latestTurn")
        idle_snapshot = (wake is None and isinstance(thread, dict)
                         and isinstance(thread.get("status"), dict)
                         and thread["status"].get("type") == "idle"
                         and not thread["status"].get("activeFlags"))
        valid_wake = (isinstance(wake, dict) and wake.get("threadId") == thread_id
                      and wake.get("reason") in {"inactiveStatus", "turnCompleted"})
        if not (idle_snapshot or valid_wake):
            return None
        if (not isinstance(thread, dict) or thread.get("id") != thread_id
                or not isinstance(latest, dict) or not latest.get("completedAt")
                or valid_wake and wake.get("reason") == "turnCompleted" and wake.get("turnId") != latest.get("id")):
            return None
        completed_at = _provider_status_time(latest.get("completedAt"))
        started_at = _provider_status_time(latest.get("startedAt"))
        if not completed_at or not started_at or not timestamp(started_at) <= timestamp(completed_at) <= timestamp(observed_at):
            return None
        turns = [latest]
    elif operation == "read_thread":
        thread, turns = raw.get("thread"), raw.get("turns")
    else:
        return None
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
    if isinstance(latest.get("id"), str) and latest["id"]:
        observation["Latest turn ID"] = latest["id"]
    completed_at = _provider_status_time(latest.get("completedAt"))
    if completed_at:
        observation["Latest turn completed at"] = completed_at
    return observation


def read_runtime_events(
    path: Path, parent_thread_id: str, started_at: str, identity_sessions: tuple[Path, ...] = (),
) -> dict:
    try:
        from runtime_checks import _tool_operations
    except ModuleNotFoundError:
        from scripts.runtime_checks import _tool_operations
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
                    or row.get("type") == "response_item" and payload.get("type") in {
                        "function_call", "function_call_output", "custom_tool_call", "custom_tool_call_output"}):
                continue
            key = json.dumps(row, sort_keys=True)
            if key in seen:
                continue
            seen.add(key)
            custom_status_call = payload.get("type") == "custom_tool_call"
            compact = []
            if custom_status_call:
                operations = _tool_operations(payload)
                source = payload.get("input", "")
                compact = [(thread, operation) for thread in mappings.values()
                           for operation, projection in (("read_thread", targeted_status_projection_source),
                                                         ("wait_threads", targeted_wait_projection_source))
                           if isinstance(source, str) and source.strip() == projection(thread)]
                if compact:
                    thread, operation = compact[0]
                    arguments = ({"threadId": thread, "turnLimit": 1, "includeOutputs": False}
                                 if operation == "read_thread" else {"targets": [{"threadId": thread}], "timeoutMs": 0})
                    operations = [("mcp__codex_app__" + operation, arguments)]
                elif isinstance(source, str) and "const d = JSON.parse(r.content[0].text);" in source:
                    continue
                elif len(operations) != 1 or operations[0][0].rsplit("__", 1)[-1] not in {"read_thread", "wait_threads"}:
                    continue
                name, arguments = operations[0]
                payload = {**payload, "type": "function_call", "name": name, "arguments": arguments}
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
                    for target, source in (("Observed model", "model"), ("Observed effort", "reasoning_effort")):
                        value = item.get(source)
                        if value is not None:
                            if not isinstance(value, str) or not value.strip():
                                raise ValueError("provider_worker_activation_metadata_invalid")
                            resolved[target] = value
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
                    elif role:
                        command = re.search(r"(?:^|\n)Read it with this separate literal command: ([^\n]+)", message)
                        digest = re.search(r"Verify its SHA256 is ([0-9a-f]{64})", message)
                        try:
                            targets = shlex.split(command[1]) if command else []
                        except ValueError:
                            targets = []
                        if digest and len(targets) == 2 and targets[0] == "cat":
                            event.update({"Dispatch file": targets[1], "Dispatch SHA256": digest[1],
                                          "Binding agent": role[1]})
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
                if not matches and isinstance(target, str):
                    prior = set()
                    with path.open() as history:
                        next(history)
                        for old_line in history:
                            try:
                                old = json.loads(old_line)
                            except json.JSONDecodeError:
                                continue
                            if timestamp(old["timestamp"]) >= started:
                                break
                            item = old.get("payload", {}).get("item", {})
                            handle, identity = item.get("agent_path"), item.get("agent_thread_id")
                            if (old.get("type") == "event_msg" and item.get("type") == "SubAgentActivity"
                                    and item.get("kind") == "started" and isinstance(handle, str)
                                    and target in {handle, handle.rsplit("/", 1)[-1]}
                                    and isinstance(identity, str) and UUID.fullmatch(identity)):
                                prior.add((handle, identity))
                    if len(prior) == 1:
                        handle, identity = prior.pop()
                        mappings[handle] = identity
                        matches = [handle]
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
                        "Operation": operation, "Attempted at": row["timestamp"], "Targets": probes,
                        "Custom call": custom_status_call, "Compact": bool(compact)}
            elif payload.get("type") in {"function_call_output", "custom_tool_call_output"}:
                call_id = payload.get("call_id")
                if (call_id not in pending_followups and call_id not in spawn_calls
                        and call_id not in pending_status_probes
                        and not (inventory_pending and inventory_pending in {True, call_id})):
                    continue
                raw = provider_json_value(payload["output"])
                explicit_error = (
                    bool(payload.get("isError") or payload.get("status") in {"failed", "error"})
                    or isinstance(raw, dict) and bool(raw.get("error") or raw.get("isError")
                                                  or raw.get("status") in ("failed", "error"))
                    or isinstance(raw, str) and bool(re.match(
                        r"^(?:Error[: ]|Failed[: ]|collab tool failed:|Worker unavailable$|agent path(?: `[^`]+`)? already exists$)",
                        raw, re.I)))
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
                        unverified_projection = (probe["Custom call"] and not probe["Compact"]
                                                 and (probe["Operation"] == "wait_threads"
                                                      or isinstance(raw, dict) and "thread" in raw and "turns" in raw))
                        observation = (None if explicit_error or unverified_projection else targeted_thread_observation(
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
        for field, expected_field, error in (
                ("Observed model", "model", "worker_activation_model_mismatch"),
                ("Observed effort", "effort", "worker_activation_effort_mismatch")):
            value = launches[0].get(field)
            if value is not None and value != expected[expected_field]:
                errors.append(error + ":" + role)
        activation_metadata = {
            target: launches[0][field]
            for target, field in (("model", "Observed model"), ("effort", "Observed effort"))
            if field in launches[0]
        }
        if ("activation_metadata" in trace
                and trace["activation_metadata"] != activation_metadata):
            errors.append("worker_activation_metadata_receipt_mismatch:" + role)
        observed = runtime_configurations(Path(trace["trace_retrieval"]), trace["thread_id"],
                                          trace["status_observation"]["Observed at"])
        if trace.get("launch") != launch or trace.get("runtime_configurations") != observed:
            errors.append("worker_launch_receipt_mismatch:" + role)
        for value in observed:
            if (value.get("model") is not None and value["model"] != expected["model"]
                    or value.get("effort") is not None and value["effort"] != expected["effort"]):
                errors.append("worker_runtime_configuration_mismatch:" + role)
        return list(dict.fromkeys(errors))
    except (OSError, ValueError, KeyError, TypeError, AttributeError, StopIteration) as error:
        return ["worker_launch_evidence_invalid:" + role + ":" + str(error)]
