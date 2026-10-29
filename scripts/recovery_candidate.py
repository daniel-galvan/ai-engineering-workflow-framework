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
                output = item.get("aggregated_output", "")
                warning = ("WARNING: proceeding, even though we could not create PATH aliases: "
                           "Operation not permitted (os error 1)\n")
                if isinstance(output, str) and output.startswith(warning):
                    output = output[len(warning):]
                result = json.loads(output)
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


def replay_candidate(baseline: Path, revision: str, session: Path, thread_id: str,
                     recorded_repository: Path, expected_paths: list[str]) -> dict[str, bytes]:
    """Reconstruct an unaccepted candidate from native edits and a clean baseline checkout."""
    baseline, recorded_repository = baseline.resolve(), recorded_repository.resolve()
    paths = set(expected_paths)
    if not paths or len(paths) != len(expected_paths):
        raise ValueError("candidate_paths_invalid")
    for name in paths:
        path = Path(name)
        if not name or path.is_absolute() or ".." in path.parts or path.as_posix() != name:
            raise ValueError("candidate_path_invalid:" + name)

    def git(*args):
        return subprocess.run(["git", "-C", str(baseline), "-c", "core.fsmonitor=false", *args],
                              check=True, capture_output=True, timeout=30).stdout

    try:
        if git("rev-parse", "HEAD").decode().strip() != revision or git("status", "--porcelain"):
            raise ValueError("candidate_recovery_source_checkout_invalid")
        with session.open() as source, tempfile.TemporaryDirectory() as directory:
            header = json.loads(next(source))
            if header.get("type") != "session_meta" or header.get("payload", {}).get("id") != thread_id:
                raise ValueError("candidate_worker_session_mismatch")
            scratch, seen = Path(directory), set()
            for line in source:
                row = json.loads(line)
                payload, item = row.get("payload", {}), row.get("payload", {}).get("item", {})
                if row.get("type") != "event_msg" or payload.get("type") != "item_completed" or item.get("type") != "FileChange":
                    continue
                for name, change in item.get("changes", {}).items():
                    absolute = Path(name)
                    if not absolute.is_absolute() or not absolute.is_relative_to(recorded_repository):
                        continue
                    relative = absolute.relative_to(recorded_repository).as_posix()
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
                        diff, lines = change["unified_diff"], change["unified_diff"].splitlines()
                        if (not lines or not re.fullmatch(r"@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@.*", lines[0])
                                or any(line.startswith(("--- ", "+++ ")) or
                                       not (line.startswith((" ", "+", "-")) or
                                            line == "\\ No newline at end of file" or
                                            re.fullmatch(r"@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@.*", line))
                                       for line in lines)):
                            raise ValueError("candidate_patch_invalid:" + relative)
                        result = subprocess.run(["patch", "-s", "-f", "-F", "0", str(target)], input=diff,
                                                text=True, capture_output=True, timeout=30)
                        if result.returncode:
                            raise ValueError("candidate_patch_failed:" + relative)
                    else:
                        raise ValueError("candidate_edit_unsupported:" + relative)
                    seen.add(relative)
            if seen != paths:
                raise ValueError("candidate_edit_records_missing")
            return {name: (scratch / name).read_bytes() for name in sorted(paths)}
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, StopIteration, UnicodeError,
            AttributeError, TypeError) as error:
        raise ValueError("candidate_evidence_unavailable") from error


def replay_followup_candidate(repository: Path, session: Path, thread_id: str,
                              initial: dict[str, bytes]) -> tuple[dict[str, bytes], list[str]]:
    """Replay native updates on a verified candidate snapshot without editing the checkout."""
    repository = repository.resolve()
    if not initial:
        raise ValueError("candidate_paths_invalid")
    for name, data in initial.items():
        path = Path(name)
        if (not name or path.is_absolute() or ".." in path.parts or path.as_posix() != name
                or not isinstance(data, bytes)):
            raise ValueError("candidate_path_invalid:" + name)
    try:
        with session.open() as source, tempfile.TemporaryDirectory() as directory:
            header = json.loads(next(source))
            if header.get("type") != "session_meta" or header.get("payload", {}).get("id") != thread_id:
                raise ValueError("candidate_worker_session_mismatch")
            scratch, touched = Path(directory), set()
            for name, data in initial.items():
                target = scratch / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            for line in source:
                row = json.loads(line)
                payload, item = row.get("payload", {}), row.get("payload", {}).get("item", {})
                if row.get("type") != "event_msg" or payload.get("type") != "item_completed" or item.get("type") != "FileChange":
                    continue
                for name, change in item.get("changes", {}).items():
                    absolute = Path(name)
                    if not absolute.is_absolute() or not absolute.is_relative_to(repository):
                        continue
                    relative = absolute.relative_to(repository).as_posix()
                    if relative.startswith(".thoughts/"):
                        continue
                    if relative not in initial or change.get("type") != "update":
                        raise ValueError("candidate_followup_edit_outside_snapshot:" + relative)
                    diff = change.get("unified_diff")
                    lines = diff.splitlines() if isinstance(diff, str) else []
                    if (not lines or not re.fullmatch(r"@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@.*", lines[0])
                            or any(line.startswith(("--- ", "+++ ")) or
                                   not (line.startswith((" ", "+", "-")) or line == "\\ No newline at end of file"
                                        or re.fullmatch(r"@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@.*", line)) for line in lines)):
                        raise ValueError("candidate_patch_invalid:" + relative)
                    applied = subprocess.run(["patch", "-s", "-f", "-F", "0", str(scratch / relative)],
                                             input=diff, text=True, capture_output=True, timeout=30)
                    if applied.returncode:
                        raise ValueError("candidate_patch_failed:" + relative)
                    touched.add(relative)
            if not touched:
                raise ValueError("candidate_edit_records_missing")
            return {name: (scratch / name).read_bytes() for name in sorted(initial)}, sorted(touched)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, StopIteration, UnicodeError,
            AttributeError, TypeError) as error:
        raise ValueError("candidate_evidence_unavailable") from error


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


def verify_checkout_snapshot(repository: Path, revision: str, hashes: dict[str, str]) -> None:
    """Require a checkout to contain exactly the verified unaccepted candidate."""
    repository = repository.resolve()
    if not hashes:
        raise ValueError("candidate_paths_invalid")
    for name in hashes:
        path = Path(name)
        if (not name or path.is_absolute() or ".." in path.parts or path.as_posix() != name
                or any((repository / Path(*path.parts[:i])).is_symlink() for i in range(1, len(path.parts) + 1))):
            raise ValueError("candidate_path_invalid:" + name)
    def git(*args):
        return subprocess.run(["git", "-C", str(repository), "-c", "core.fsmonitor=false", *args],
                              check=True, capture_output=True, timeout=30).stdout
    try:
        if git("rev-parse", "HEAD").decode().strip() != revision:
            raise ValueError("candidate_revision_changed")
        if git("diff", "--cached", "--name-only", "-z"):
            raise ValueError("candidate_staged_changes")
        changed = set(git("diff", "--name-only", "-z").decode().split("\0")) - {""}
        changed.update(set(git("ls-files", "--others", "--exclude-standard", "-z").decode().split("\0")) - {""})
        if changed != set(hashes):
            raise ValueError("candidate_changed_paths_mismatch")
        for name, digest in hashes.items():
            if hashlib.sha256((repository / name).read_bytes()).hexdigest() != digest:
                raise ValueError("candidate_content_changed:" + name)
    except (OSError, subprocess.SubprocessError, UnicodeError) as error:
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


def snapshot_replayed_candidate(destination: Path, hashes: dict[str, str], contents: dict[str, bytes]) -> None:
    """Publish verified replay bytes atomically as unaccepted candidate input."""
    if destination.exists() or destination.is_symlink() or not hashes or hashes.keys() != contents.keys():
        raise ValueError("candidate_snapshot_destination_invalid")
    with tempfile.TemporaryDirectory(prefix=".candidate-", dir=destination.parent) as temporary:
        staging = Path(temporary) / "snapshot"
        staging.mkdir()
        for name, digest in sorted(hashes.items()):
            path = Path(name)
            if not name or path.is_absolute() or ".." in path.parts or path.as_posix() != name:
                raise ValueError("candidate_path_invalid:" + name)
            data = contents[name]
            if hashlib.sha256(data).hexdigest() != digest:
                raise ValueError("candidate_content_changed:" + name)
            target = staging / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        staging.rename(destination)
