"""Verify an unaccepted delivery candidate against native worker edit records."""

import hashlib
import json
import re
import shlex
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path


def verify_edit_authorization(parent_session: Path, parent_id: str, worker_session: Path, worker_id: str,
                              started_at: str, guard: Path, packet: Path, handle: str,
                              repository: Path, paths: list[str]) -> None:
    """Require a successful native source guard before each recorded candidate edit."""
    def timestamp(value):
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError("candidate_timestamp_invalid")
        return result

    def rows(path, identity):
        with path.open() as stream:
            header = json.loads(next(stream))
            if header.get("type") != "session_meta" or header.get("payload", {}).get("id") != identity:
                raise ValueError("candidate_session_identity_mismatch")
            return [json.loads(line) for line in stream]

    try:
        start = timestamp(started_at)
        observations = []
        for row in rows(parent_session, parent_id):
            payload = row.get("payload", {})
            item = payload.get("item", {})
            if row.get("type") != "event_msg" or payload.get("type") != "item_completed" or item.get("type") != "CommandExecution":
                continue
            command = item.get("command", [])
            if not isinstance(command, list) or len(command) != 3 or command[1] not in {"-c", "-lc"}:
                continue
            tokens = shlex.split(command[2])
            if (len(tokens) != 8 or Path(tokens[0]).name not in {"python", "python3"}
                    or Path(tokens[1]) != guard or tokens[2:4] != ["--before-source-change", str(packet)]
                    or tokens[4:6] != ["--implementer-handle", handle]
                    or tokens[6] != "--provider-status"):
                continue
            observed = timestamp(row["timestamp"])
            if observed < start:
                continue
            try:
                result = json.loads(item.get("aggregated_output", ""))
            except (ValueError, TypeError):
                result = {}
            allowed = (tokens[7] in {"running", "in_progress"} and item.get("status") == "completed"
                       and item.get("exit_code") == 0 and result == {"status": "allowed"})
            observations.append((observed, allowed))
        edits = []
        expected = {str(repository.resolve() / path) for path in paths}
        for row in rows(worker_session, worker_id):
            payload = row.get("payload", {})
            item = payload.get("item", {})
            if (row.get("type") == "event_msg" and payload.get("type") == "item_completed"
                    and item.get("type") == "FileChange" and expected.intersection(item.get("changes", {}))):
                edits.append(timestamp(row["timestamp"]))
        if not edits or any(edit < start for edit in edits):
            raise ValueError("candidate_edit_timing_invalid")
        for edit in edits:
            preceding = [entry for entry in observations if entry[0] < edit]
            if not preceding or not max(preceding, key=lambda entry: entry[0])[1]:
                raise ValueError("candidate_source_guard_missing")
    except (OSError, json.JSONDecodeError, StopIteration, KeyError, TypeError, AttributeError) as error:
        raise ValueError("candidate_authorization_evidence_unavailable") from error


def verify_candidate(repository: Path, revision: str, session: Path, thread_id: str,
                     expected_paths: list[str], *, allow_source_revision_advance: bool = False) -> dict[str, str]:
    """Replay recorded edits in isolation and return hashes only when the checkout matches.

    This verifies provenance, not correctness or approval of the candidate.
    """
    repository = repository.resolve()
    paths = set(expected_paths)
    if not paths or len(paths) != len(expected_paths):
        raise ValueError("candidate_paths_invalid")
    for name in paths:
        path = Path(name)
        if (not name or path.is_absolute() or ".." in path.parts or path.as_posix() != name
                or not (repository / path).resolve().is_relative_to(repository)
                or any(part.is_symlink() for part in [repository / Path(*path.parts[:i])
                                                       for i in range(1, len(path.parts) + 1)])):
            raise ValueError("candidate_path_invalid:" + name)

    def git(*args: str) -> bytes:
        result = subprocess.run(["git", "-C", str(repository), "-c", "core.fsmonitor=false", *args],
                                capture_output=True, timeout=30, check=True)
        return result.stdout

    try:
        if git("rev-parse", "HEAD").decode().strip() != revision:
            if not allow_source_revision_advance:
                raise ValueError("candidate_revision_changed")
            git("merge-base", "--is-ancestor", revision, "HEAD")
            if git("diff", "--name-only", "-z", revision, "HEAD", "--", *sorted(paths)):
                raise ValueError("candidate_baseline_files_changed")
        if git("diff", "--cached", "--name-only", "-z"):
            raise ValueError("candidate_staged_changes")
        changed = set(git("diff", "--name-only", "-z", "HEAD").decode().split("\0")) - {""}
        changed.update(set(git("ls-files", "--others", "--exclude-standard", "-z").decode().split("\0")) - {""})
        if changed != paths:
            raise ValueError("candidate_changed_paths_mismatch")
        with session.open() as source, tempfile.TemporaryDirectory() as directory:
            header = json.loads(next(source))
            if header.get("type") != "session_meta" or header.get("payload", {}).get("id") != thread_id:
                raise ValueError("candidate_worker_session_mismatch")
            scratch = Path(directory)
            seen = set()
            for line in source:
                row = json.loads(line)
                payload = row.get("payload", {})
                item = payload.get("item", {})
                if row.get("type") != "event_msg" or payload.get("type") != "item_completed" or item.get("type") != "FileChange":
                    continue
                for name, change in item.get("changes", {}).items():
                    absolute = Path(name)
                    if not absolute.is_absolute() or not absolute.is_relative_to(repository):
                        continue
                    relative = absolute.relative_to(repository).as_posix()
                    if relative not in paths:
                        continue
                    target = scratch / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    kind = change.get("type")
                    if kind == "add" and relative not in seen and isinstance(change.get("content"), str):
                        target.write_text(change["content"])
                    elif kind == "update" and isinstance(change.get("unified_diff"), str):
                        if relative not in seen:
                            target.write_bytes(git("show", revision + ":" + relative))
                        diff = change["unified_diff"]
                        lines = diff.splitlines()
                        if (not lines or not re.fullmatch(r"@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@.*", lines[0])
                                or any(line.startswith(("--- ", "+++ ")) or
                                       not (line.startswith((" ", "+", "-")) or
                                            line == "\\ No newline at end of file" or
                                            re.fullmatch(r"@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@.*", line))
                                       for line in lines)):
                            raise ValueError("candidate_patch_invalid:" + relative)
                        applied = subprocess.run(["patch", "-s", "-f", "-F", "0", str(target)],
                                                 input=diff, text=True, capture_output=True, timeout=30)
                        if applied.returncode:
                            raise ValueError("candidate_patch_failed:" + relative)
                    else:
                        raise ValueError("candidate_edit_unsupported:" + relative)
                    seen.add(relative)
            if seen != paths:
                raise ValueError("candidate_edit_records_missing")
            result = {}
            for name in sorted(paths):
                expected = (scratch / name).read_bytes()
                actual = (repository / name).read_bytes()
                if actual != expected:
                    raise ValueError("candidate_content_changed:" + name)
                result[name] = hashlib.sha256(actual).hexdigest()
            return result
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, StopIteration, UnicodeError,
            AttributeError, TypeError) as error:
        raise ValueError("candidate_evidence_unavailable") from error


def snapshot_candidate(repository: Path, destination: Path, hashes: dict[str, str]) -> None:
    """Preserve verified bytes as unaccepted input without editing source files."""
    repository = repository.resolve()
    if destination.exists() or destination.is_symlink() or not hashes:
        raise ValueError("candidate_snapshot_destination_invalid")
    with tempfile.TemporaryDirectory(prefix=".candidate-", dir=destination.parent) as temporary:
        staging = Path(temporary) / "snapshot"
        staging.mkdir()
        for name, digest in sorted(hashes.items()):
            path = Path(name)
            source = repository / path
            if (not name or path.is_absolute() or ".." in path.parts or path.as_posix() != name
                    or any((repository / Path(*path.parts[:i])).is_symlink()
                           for i in range(1, len(path.parts) + 1))):
                raise ValueError("candidate_path_invalid:" + name)
            data = source.read_bytes()
            if hashlib.sha256(data).hexdigest() != digest:
                raise ValueError("candidate_content_changed:" + name)
            target = staging / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        staging.rename(destination)
