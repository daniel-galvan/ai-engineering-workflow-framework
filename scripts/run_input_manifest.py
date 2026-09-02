#!/usr/bin/env python3
"""Build and validate the immutable current-run input manifest."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
DEFAULT_PRECEDENCE_RULE = (
    "Current explicit user decisions and constraints, plus explicitly supplied current-run context and artifacts, "
    "override historical conclusions. Live runtime evidence is additive unless the user explicitly selects live-only analysis."
)
REQUIRED_INPUT_FIELDS = ("Input ID", "Input or artifact", "Source or path", "Authority", "Status")
LOCAL_LINE_REFERENCE = re.compile(r"^(?P<path>/.*?)(?::\d+(?:-\d+)?|#L\d+(?:-L?\d+)?)$")


def _text(value: object, field: str) -> str:
    result = str(value).strip()
    if not result:
        raise ValueError(f"run_input_manifest_{field}_empty")
    return result


def _strip_local_line_reference(value: str) -> str:
    """Use the file portion for availability/hash checks while preserving the source text."""
    match = LOCAL_LINE_REFERENCE.fullmatch(value.strip())
    return match.group("path") if match else value.strip()


def _absolute_paths(value: object) -> list[Path]:
    """Resolve one path or a semicolon-delimited list of absolute paths."""
    if isinstance(value, list):
        raw_values = [_strip_local_line_reference(str(item)) for item in value]
    else:
        raw = str(value).strip()
        raw_values = (
            [_strip_local_line_reference(part) for part in raw.split(";")]
            if ";" in raw else [_strip_local_line_reference(raw)]
        )
    if len(raw_values) == 1:
        return [Path(raw_values[0]).expanduser().resolve()]
    if not raw_values or any(not item.startswith("/") or item.startswith("//") for item in raw_values):
        return []
    return [Path(item).expanduser().resolve() for item in raw_values]


def _normalize_input(row: object, index: int) -> dict[str, object]:
    if not isinstance(row, dict):
        raise ValueError(f"run_input_manifest_input_{index}_invalid")
    normalized = dict(row)
    for field in REQUIRED_INPUT_FIELDS:
        normalized[field] = _text(row.get(field, ""), field.lower().replace(" ", "_"))
    input_id = normalized["Input ID"]
    if not input_id.replace("_", "").replace("-", "").isalnum():
        raise ValueError(f"run_input_manifest_input_id_invalid:{input_id}")
    normalized.setdefault("Classification", "supporting current-run input")
    normalized.setdefault("Expected use", "Consume or explicitly disposition before finalization")
    source_path = normalized.get("path")
    if not source_path:
        candidate = str(normalized["Source or path"])
        if candidate.startswith("/") and not candidate.startswith("//"):
            source_path = candidate
    if source_path:
        paths = _absolute_paths(source_path)
        if len(paths) == 1:
            path = paths[0]
            normalized["path"] = str(path)
            normalized["availability"] = "available" if path.exists() else "unavailable"
            if path.is_file():
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                supplied_digest = str(normalized.get("sha256", "")).strip()
                if supplied_digest and supplied_digest != digest:
                    raise ValueError(f"run_input_manifest_hash_mismatch:{input_id}")
                normalized["sha256"] = digest
        elif len(paths) > 1:
            normalized.pop("path", None)
            normalized["paths"] = [str(path) for path in paths]
            normalized["availability"] = (
                "available" if all(path.exists() for path in paths) else "unavailable"
            )
        else:
            # Preserve the legacy single-value behavior for a non-path source string.
            path = Path(str(source_path)).expanduser().resolve()
            normalized["path"] = str(path)
            normalized["availability"] = "available" if path.exists() else "unavailable"
            if path.is_file():
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                supplied_digest = str(normalized.get("sha256", "")).strip()
                if supplied_digest and supplied_digest != digest:
                    raise ValueError(f"run_input_manifest_hash_mismatch:{input_id}")
                normalized["sha256"] = digest
    return normalized


def validate_manifest(value: object, *, explicit: bool | None = None) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("run_input_manifest_invalid")
    schema_version = value.get("schema_version", SCHEMA_VERSION)
    if schema_version != SCHEMA_VERSION:
        raise ValueError(f"run_input_manifest_schema_version:{schema_version}")
    precedence_rule = _text(
        value["precedence_rule"] if "precedence_rule" in value else DEFAULT_PRECEDENCE_RULE,
        "precedence_rule",
    )
    raw_inputs = value.get("inputs")
    if not isinstance(raw_inputs, list) or not raw_inputs:
        raise ValueError("run_input_manifest_inputs_missing")
    inputs = [_normalize_input(row, index) for index, row in enumerate(raw_inputs)]
    ids = [str(row["Input ID"]) for row in inputs]
    if len(set(ids)) != len(ids):
        raise ValueError("run_input_manifest_duplicate_input_id")
    status = str(value.get("status", "explicit" if explicit else "generated_minimum")).strip()
    if status not in {"explicit", "generated_minimum"}:
        raise ValueError(f"run_input_manifest_status_invalid:{status}")
    if explicit is True and status != "explicit":
        raise ValueError("run_input_manifest_status_invalid:explicit input cannot be generated_minimum")
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "precedence_rule": precedence_rule,
        "inputs": inputs,
    }


def load_manifest(path: Path, *, explicit: bool = True) -> dict[str, object]:
    if not path.is_file():
        raise ValueError(f"run_input_manifest_unavailable:{path}")
    try:
        value: Any = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"run_input_manifest_invalid:{path}:{error}") from error
    return validate_manifest(value, explicit=explicit)


def default_manifest(work_item: str, playbook: str, execution_repository: Path) -> dict[str, object]:
    return validate_manifest({
        "schema_version": SCHEMA_VERSION,
        "status": "generated_minimum",
        "precedence_rule": DEFAULT_PRECEDENCE_RULE,
        "inputs": [
            {
                "Input ID": "RUN-001",
                "Input or artifact": f"Work item {work_item}",
                "Source or path": "Current user request",
                "Authority": "Authoritative current-run scope",
                "Classification": "observed report or requested outcome",
                "Expected use": "Scope and run identity",
                "Status": "Registered",
            },
            {
                "Input ID": "RUN-002",
                "Input or artifact": f"Selected playbook {playbook}",
                "Source or path": "Current user request",
                "Authority": "Authoritative current-run constraint",
                "Classification": "authoritative decision or constraint",
                "Expected use": "Select lifecycle and worker graph",
                "Status": "Registered",
            },
            {
                "Input ID": "RUN-003",
                "Input or artifact": "Execution repository",
                "Source or path": str(execution_repository),
                "Authority": "Coordinator runtime observation",
                "Classification": "supporting artifact, reference, or data source",
                "Expected use": "Durable run root and repository identity",
                "Status": "Registered",
                "path": str(execution_repository),
            },
        ],
    })


def merge_manifests(existing: dict[str, object], incoming: dict[str, object]) -> dict[str, object]:
    current = validate_manifest(existing)
    addition = validate_manifest(incoming, explicit=True)
    rows = list(current["inputs"])
    by_id = {str(row["Input ID"]): row for row in rows}
    for row in addition["inputs"]:
        input_id = str(row["Input ID"])
        if input_id in by_id and by_id[input_id] != row:
            raise ValueError(f"run_input_manifest_conflicting_input_id:{input_id}")
        if input_id not in by_id:
            rows.append(row)
    return validate_manifest({
        "schema_version": SCHEMA_VERSION,
        "status": "explicit" if "explicit" in {current["status"], addition["status"]} else "generated_minimum",
        "precedence_rule": addition["precedence_rule"],
        "inputs": rows,
    })


def write_manifest(path: Path, manifest: dict[str, object]) -> dict[str, object]:
    normalized = validate_manifest(manifest)
    path.write_text(json.dumps(normalized, indent=2, sort_keys=True) + "\n")
    normalized["path"] = str(path.resolve())
    normalized["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return normalized


def packet_metadata(path: Path, manifest: dict[str, object]) -> dict[str, object]:
    return {
        "path": str(path.resolve()),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "status": manifest["status"],
        "precedence_rule": manifest["precedence_rule"],
        "input_ids": [str(row["Input ID"]) for row in manifest["inputs"]],
    }
