"""Deterministic references validation rules."""

from __future__ import annotations

from pathlib import Path
import re
from .common import (
    EMPTY_ARTIFACT_VALUES,
    RANGE_REFERENCE,
)


def normalized_metadata_value(value: object) -> str:
    normalized = str(value).strip()
    if len(normalized) >= 2 and normalized.startswith("`") and normalized.endswith("`"):
        return normalized[1:-1].strip()
    return normalized


def _is_not_applicable(value: object) -> bool:
    return normalized_metadata_value(value).lower() in {"", "none", "not applicable", "n/a"}


def _direct_evidence_location_is_vague(value: object) -> bool:
    location = normalized_metadata_value(value)
    lowered = re.sub(r"\s+", " ", location.lower())
    if any(marker in location for marker in ("*", "...", "…")):
        return True
    if re.search(r"\s+\bor\s+", lowered):
        return True
    if re.search(
        r"(?:^|[;,]\s*)(?:(?:targeted|broad|scoped)\s+)?"
        r"(?:source(?:/schema)?|schema|repository|codebase)\s+(?:search|scan)"
        r"|(?:^|[;,]\s*)(?:(?:targeted|broad|scoped)\s+)?"
        r"(?:file|directory|path)\s+(?:search|scan|cleanup)",
        lowered,
    ):
        return True
    return bool(re.fullmatch(
        r"(?:[a-z0-9_./-]+\s+){0,4}(?:sources?|search|cleanup|files?|directories?)", lowered,
    ))


def _direct_evidence_observation_is_vague(value: object) -> bool:
    observation = re.sub(r"\s+", " ", normalized_metadata_value(value)).strip()
    return bool(re.fullmatch(
        r"(?:current-run\s+)?(?:source-backed\s+)?(?:verified\s+)?"
        r"(?:evidence\s+)?observation"
        r"(?:\s+retained(?:\s+in\s+(?:the\s+)?analytical\s+artifact)?)?\.?",
        observation,
        re.IGNORECASE,
    ))


def _grouped_reference_errors(
    rows: list[dict[str, str]], section: str, fields: tuple[str, ...],
) -> list[str]:
    errors = []
    for index, row in enumerate(rows, start=1):
        for field in fields:
            match = RANGE_REFERENCE.search(row.get(field, ""))
            if match:
                identity = row.get("Evidence ID", "") or f"row {index}"
                errors.append(
                    f"spike_report.md {section} {identity} {field} must use exact IDs; "
                    f"grouped/range reference {match.group(0)!r} is not allowed"
                )
    return errors


def _grouped_reference_text_errors(text: str, section: str) -> list[str]:
    match = re.search(
        rf"^{re.escape(section)}\s*\n(.*?)(?=^##\s|\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    if not match:
        return []
    return [
        f"spike_report.md {section} must use exact IDs; grouped/range reference {reference!r} is not allowed"
        for reference in dict.fromkeys(RANGE_REFERENCE.findall(match.group(1)))
    ]


def _artifact_path(value: str, record_path: Path) -> Path | None:
    value = value.strip()
    if value.lower() in EMPTY_ARTIFACT_VALUES:
        return None
    if value.startswith("[") and "](" in value and value.endswith(")"):
        value = value.split("](", 1)[1][:-1]
    value = value.strip("<>")
    candidate = Path(value)
    return candidate.resolve() if candidate.is_absolute() else (record_path.parent / candidate).resolve()


def current_artifact_errors(
    rows: list[dict[str, str]], record_path: Path, artifact_root_value: str, *, require_files: bool = True
) -> list[str]:
    errors = []
    if not artifact_root_value.strip():
        return [f"{record_path}: Durable Artifacts requires a durable artifact root"]
    root = Path(artifact_root_value.strip())
    if not root.is_absolute():
        return [f"{record_path}: durable artifact root must be absolute"]
    root = root.resolve()
    if not rows:
        return [f"{record_path}: Durable Artifacts must contain populated rows"]
    for row in rows:
        artifact = row.get("Artifact", "").strip() or "unnamed"
        target = _artifact_path(row.get("Path", ""), record_path)
        if target is None:
            errors.append(f"{record_path}: durable artifact {artifact} has no path")
            continue
        if not target.is_relative_to(root):
            errors.append(f"{record_path}: durable artifact {artifact} escapes the current artifact root")
        elif target.parent != root:
            errors.append(f"{record_path}: durable artifact {artifact} must be a current-run root file, not an archive")
        expected_before_terminal = (
            artifact.lower() == "technical spike report"
            and target.name == "spike_report.md"
            and row.get("Status", "").strip().lower() == "expected before terminal finalization"
        )
        if require_files and not target.is_file() and not expected_before_terminal and not (
            target.name == "work_record.md" and target.parent == record_path.parent
        ):
            errors.append(f"{record_path}: durable artifact {artifact} does not exist: {target}")
    return errors
