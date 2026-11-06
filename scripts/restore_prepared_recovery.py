#!/usr/bin/env python3
"""Restore an archived planning run after an undispatched recovery preparation."""

import argparse
import hashlib
import json
import re
import tempfile
from pathlib import Path

try:
    from prepare_run import _archive_recovery
    from provider_runtime import read_runtime_events, validate_prepared_provider_source
except ModuleNotFoundError:
    from scripts.prepare_run import _archive_recovery
    from scripts.provider_runtime import read_runtime_events, validate_prepared_provider_source


def _replace(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(data)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def restore(root: Path, current_run: str, prior_run: str, *, check_only: bool = False) -> dict:
    root = root.resolve()
    if current_run == prior_run or any(not re.fullmatch(r"[A-Za-z0-9_.-]+", value)
                                       for value in (current_run, prior_run)):
        raise ValueError("restore_run_ids_invalid")
    packet = json.loads((root / "finalization_packet.json").read_text())
    bindings = json.loads((root / "role_bindings.json").read_text())
    archive = root / "runs" / prior_run
    if (root / "runs").is_symlink() or archive.is_symlink():
        raise ValueError("restore_archive_path_invalid")
    identity = packet["identity"]
    if (identity["Run ID"] != current_run or bindings["run_id"] != current_run
            or identity.get("Lifecycle") != "planning" or identity.get("State") != "in_progress"
            or packet.get("recovery", {}).get("Prior run ID") != prior_run
            or Path(packet["recovery"]["Prior artifacts"]).resolve() != archive.resolve()):
        raise ValueError("restore_prepared_recovery_identity_mismatch")
    parent, runtime = bindings["parent_context"], bindings["runtime_evidence"]
    source = Path(parent["provider_session"])
    ledger = read_runtime_events(source, parent["parent_thread_id"], runtime["run_started_at"],
                                 tuple(Path(value) for value in runtime.get("identity_sessions", [])))
    if ledger["events"] or ledger.get("failed_dispatches"):
        raise ValueError("restore_recovery_already_dispatched")
    manifest = json.loads((archive / "archive_manifest.json").read_text())
    if manifest.get("run_id") != prior_run:
        raise ValueError("restore_archive_identity_mismatch")
    contents = {}
    for entry in manifest["files"]:
        relative = Path(entry["path"])
        target = root / relative
        snapshot = (archive / entry["snapshot"]).resolve()
        if (relative.is_absolute() or ".." in relative.parts or relative.parts[:1] == ("runs",)
                or entry["path"] in contents or target.is_symlink()
                or not target.resolve().is_relative_to(root)
                or not snapshot.is_relative_to((root / "runs").resolve())):
            raise ValueError("restore_archive_path_invalid")
        data = snapshot.read_bytes()
        if hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise ValueError("restore_archive_hash_mismatch:" + entry["path"])
        contents[entry["path"]] = data
    previous = json.loads(contents["finalization_packet.json"])
    previous_bindings = json.loads(contents["role_bindings.json"])
    if (previous["identity"]["Run ID"] != prior_run or previous_bindings["run_id"] != prior_run
            or previous_bindings["parent_context"]["parent_thread_id"] != parent["parent_thread_id"]):
        raise ValueError("restore_archive_parent_mismatch")
    result = {"status": "verified" if check_only else "restored", "run_id": prior_run,
              "preserved_recovery": str(root / "runs" / current_run), "verified_files": len(contents)}
    if check_only:
        return result
    validate_prepared_provider_source(bindings, source, parent["parent_thread_id"], runtime["run_started_at"])
    _archive_recovery(root, current_run)
    before = {name: (root / name).read_bytes() if (root / name).exists() else None for name in contents}
    changed = []
    try:
        for name, data in contents.items():
            if before[name] != data:
                _replace(root / name, data)
                changed.append(name)
    except Exception:
        for name in reversed(changed):
            if before[name] is None:
                (root / name).unlink(missing_ok=True)
            else:
                _replace(root / name, before[name])
        raise
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--current-run-id", required=True)
    parser.add_argument("--prior-run-id", required=True)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    try:
        result = restore(args.artifact_root, args.current_run_id, args.prior_run_id, check_only=args.check_only)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"status": "blocked", "reason": str(error)}))
        return 2
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
