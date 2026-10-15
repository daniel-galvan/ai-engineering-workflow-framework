#!/usr/bin/env python3
"""Build and validate the immutable current-run input manifest."""

from __future__ import annotations

import csv
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


def _provider_text(value: object):
    if isinstance(value, dict):
        if value.get("isError") is True:
            raise ValueError("sentry_source_observation_failed")
        for key, item in value.items():
            if key == "release" and isinstance(item, str):
                yield "release: " + item
            elif key == "release" and isinstance(item, dict) and isinstance(item.get("version"), str):
                yield "release: " + item["version"]
            yield from _provider_text(item)
    elif isinstance(value, list):
        for item in value:
            yield from _provider_text(item)
    elif isinstance(value, str):
        try:
            decoded = json.loads(value)
        except ValueError:
            yield value
        else:
            if isinstance(decoded, (dict, list)):
                yield from _provider_text(decoded)
            else:
                yield value


def retain_source_releases(manifest: dict, provider_session: Path | None) -> None:
    """Carry observed releases into the hashed input manifest before worker summarization."""
    live = [row for row in manifest["inputs"] if re.search(r"https://[^/]*sentry\.io/issues/\d+", str(row["Source or path"]))
            and row.get("Evidence mode") != "supplied_occurrence"]
    if live and provider_session is None:
        raise ValueError("sentry_source_observation_requires_provider_session")
    releases = {row["Input ID"]: set() for row in live}
    if live:
        calls = {}
        observed_inputs = set()
        with provider_session.open() as stream:
            header = json.loads(next(stream))
            if header.get("type") != "session_meta":
                raise ValueError("source_observation_provider_session_invalid")
            for line in stream:
                event = json.loads(line)
                payload = event.get("payload", {})
                code = str(payload.get("input", payload.get("arguments", "")))
                if payload.get("type") in {"function_call", "custom_tool_call"} and "scripts/run_preflight.py" in code:
                    releases = {row["Input ID"]: set() for row in live}
                    calls.clear()
                    observed_inputs.clear()
                source_name = str(payload.get("namespace", "") + payload.get("name", "")).lower()
                source_read = (payload.get("type") == "function_call" and "sentry" in source_name
                    and any(name in source_name for name in ("get_sentry_resource", "execute_sentry_tool"))) or (
                    payload.get("type") == "custom_tool_call" and re.search(
                        r"tools\.mcp__sentry__(?:get_sentry_resource|execute_sentry_tool)\(", code))
                if source_read:
                    selected = [row["Input ID"] for row in live if re.search(
                        r"(?<!\d)" + re.search(r"/issues/(\d+)", row["Source or path"])[1] + r"(?!\d)", code)]
                    calls[payload.get("call_id")] = selected or ([live[0]["Input ID"]] if len(live) == 1 else [])
                if payload.get("type") in {"function_call_output", "custom_tool_call_output"} and payload.get("call_id") in calls:
                    observed_inputs.update(calls[payload["call_id"]])
                    for text in _provider_text(payload.get("output")):
                        for input_id in calls[payload["call_id"]]:
                            releases[input_id].update(re.findall(r"(?im)\brelease\**:\s*([A-Za-z0-9._+/-]{1,120})", text))
        for row in live:
            if row["Input ID"] not in observed_inputs:
                raise ValueError("sentry_source_observation_unavailable:" + row["Input ID"])
            row["Observed releases"] = sorted(releases[row["Input ID"]])
            row["Release observation"] = ("Provider source read" if row["Observed releases"]
                                          else "Not exposed by provider source read")
    for row in manifest["inputs"]:
        path = Path(str(row.get("path", "")))
        if path.is_file() and path.suffix.lower() == ".csv":
            observed = re.findall(r"Using release from debug info: ([0-9a-fA-F]{40})", path.read_text(errors="replace"))
            if observed:
                row["Observed releases"] = sorted(set(observed))
                row["Release observation"] = "Supplied occurrence log"
            occurrences = []
            with path.open(newline="", encoding="utf-8-sig") as stream:
                for entry in csv.DictReader(stream):
                    try:
                        # Exported log messages can contain literal newlines inside JSON strings.
                        log = json.loads(entry.get("message", ""), strict=False)
                    except ValueError:
                        continue
                    if not isinstance(log, dict) or not isinstance(log.get("workflow_item"), dict):
                        continue
                    item = log["workflow_item"]
                    when = str(log.get("time", ""))
                    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T[\d:.]+Z", when):
                        continue
                    occurrence = {"UTC attempt": when}
                    for key in ("organization_id", "asset_id", "referent_id"):
                        value = str(item.get(key, ""))
                        if re.fullmatch(r"[0-9a-fA-F-]{1,64}", value):
                            occurrence[key] = value
                    if occurrence not in occurrences:
                        occurrences.append(occurrence)
            if occurrences:
                row["Occurrence correlation"] = occurrences


def source_release_errors(text: str, manifest: dict) -> list[str]:
    return ["source_release_dropped:" + str(row["Input ID"]) + ":" + str(release)
            for row in manifest.get("inputs", []) for release in row.get("Observed releases", [])
            if not any(re.search(r"(?<![\w-])" + re.escape(str(row["Input ID"])) + r"(?![\w-])", line)
                       and re.search(r"(?<![\w.+/-])" + re.escape(str(release)) + r"(?![\w.+/-])", line)
                       for line in text.splitlines())]


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
    if "Asset source" in normalized and not isinstance(normalized["Asset source"], bool):
        raise ValueError(f"run_input_manifest_asset_source_invalid:{input_id}")
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
