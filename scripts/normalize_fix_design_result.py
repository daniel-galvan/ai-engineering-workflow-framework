#!/usr/bin/env python3
"""Apply lossless producer-format repairs to a Sentry Fix Design result."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "validate_library.py"
ROLLOUT_TERMS = re.compile(r"\b(?:canary|consumer|deploy|producer|rollout)\w*\b", re.IGNORECASE)


def _compact(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _legacy_fallbacks(value: object) -> list[str]:
    if not isinstance(value, dict):
        return []
    return [
        nested.strip()
        for key, nested in value.items()
        if key == "legacy_fallback" and _nonempty_string(nested)
    ]


def normalize_fix_design_result(data: object) -> tuple[dict[str, object], list[str]]:
    if not isinstance(data, dict):
        raise ValueError("fix_design_result.json must contain one object")
    normalized = json.loads(json.dumps(data))
    changes: list[str] = []

    inputs = normalized.get("inputs_consumed")
    if isinstance(inputs, list) and inputs and any(not isinstance(value, str) for value in inputs):
        converted: list[str] = []
        for value in inputs:
            if isinstance(value, str) and value.strip():
                converted.append(value)
                continue
            if not isinstance(value, dict) or set(value) != {"input_id", "disposition"}:
                raise ValueError("inputs_consumed contains an ambiguous non-string entry")
            input_id = value.get("input_id")
            disposition = value.get("disposition")
            if not _nonempty_string(input_id) or not _nonempty_string(disposition):
                raise ValueError("inputs_consumed object entries require string input_id and disposition")
            converted.append(f"{input_id.strip()}: {disposition.strip()}")
        normalized["inputs_consumed"] = converted
        changes.append("inputs_consumed objects converted to equivalent strings")

    blockers = normalized.get("blocking_unknowns")
    if normalized.get("plan_readiness") == "ready_for_implementation" and isinstance(blockers, list) and blockers:
        nonblocking: list[dict[str, object]] = []
        for blocker in blockers:
            if not isinstance(blocker, dict):
                raise ValueError("ready blocking_unknowns contains an ambiguous entry")
            flags = [
                blocker.get("invalidates_supported_change"),
                blocker.get("invalidates_supported_boundary_or_change"),
            ]
            if False not in flags or True in flags:
                raise ValueError("ready blocking_unknowns is not explicitly non-blocking")
            nonblocking.append(blocker)
        remaining = normalized.get("checks_remaining")
        if not isinstance(remaining, list):
            raise ValueError("checks_remaining must be a list before moving non-blocking unknowns")
        for blocker in nonblocking:
            receipt = f"Non-blocking unknown retained from producer result: {_compact(blocker)}"
            if receipt not in remaining:
                remaining.append(receipt)
        normalized["blocking_unknowns"] = []
        changes.append("explicitly non-blocking unknowns moved to checks_remaining")

    contract = normalized.get("interface_contract")
    if normalized.get("interface_change") is True and isinstance(contract, dict):
        missing = [
            field
            for field in (
                "surface",
                "request_shape",
                "response_shape",
                "absence_semantics",
                "compatibility_precedence",
                "rollout",
            )
            if not _nonempty_string(contract.get(field))
        ]
        if missing:
            request = contract.get("request_addition")
            response = contract.get("response_addition")
            invariants = contract.get("invariants")
            boundary = normalized.get("supported_remediation_boundary")
            if not isinstance(request, dict) or not isinstance(response, dict):
                raise ValueError("interface_contract cannot be losslessly converted to the canonical shape")
            if not isinstance(invariants, list) or not all(_nonempty_string(value) for value in invariants):
                raise ValueError("interface_contract invariants must be a non-empty string list")
            fallbacks = _legacy_fallbacks(request) + _legacy_fallbacks(response)
            if not fallbacks:
                raise ValueError("interface_contract has no explicit absence semantics")
            rollout_sources = [*fallbacks, *invariants]
            checks_remaining = normalized.get("checks_remaining")
            if isinstance(checks_remaining, list):
                rollout_sources.extend(value for value in checks_remaining if _nonempty_string(value))
            rollout = [value.strip() for value in rollout_sources if ROLLOUT_TERMS.search(value)]
            if not _nonempty_string(boundary) or not rollout:
                raise ValueError("interface_contract has no explicit surface or rollout semantics")
            additions = {
                "surface": boundary.strip(),
                "request_shape": _compact(request),
                "response_shape": _compact(response),
                "absence_semantics": "; ".join(dict.fromkeys(fallbacks)),
                "compatibility_precedence": "; ".join(dict.fromkeys(value.strip() for value in invariants)),
                "rollout": "; ".join(dict.fromkeys(rollout)),
            }
            for field in missing:
                contract[field] = additions[field]
            changes.append("legacy interface contract augmented with canonical string fields")

    return normalized, changes


def normalize_artifact_root(artifact_root: Path, backup: Path | None = None) -> dict[str, object]:
    artifact_root = artifact_root.resolve()
    design = artifact_root / "fix_design_result.json"
    evidence = artifact_root / "normalized_evidence.md"
    if not design.is_file() or not evidence.is_file():
        raise ValueError("artifact root requires fix_design_result.json and normalized_evidence.md")
    normalized, changes = normalize_fix_design_result(json.loads(design.read_text()))
    candidate_text = json.dumps(normalized, indent=2, ensure_ascii=False) + "\n"
    with tempfile.TemporaryDirectory(prefix="fix-design-normalize-") as directory:
        candidate_root = Path(directory)
        shutil.copyfile(evidence, candidate_root / evidence.name)
        candidate = candidate_root / design.name
        candidate.write_text(candidate_text)
        completed = subprocess.run(
            ["python3", str(VALIDATOR), "--sentry-artifacts", str(candidate_root)],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode:
            message = (completed.stdout + completed.stderr).strip()
            raise ValueError(f"normalized candidate failed validation: {message}")
    if changes:
        if backup:
            backup = backup.resolve()
            if backup.exists():
                raise ValueError(f"backup already exists: {backup}")
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(design, backup)
        temporary = design.with_suffix(".json.tmp")
        temporary.write_text(candidate_text)
        os.replace(temporary, design)
    return {
        "status": "normalized" if changes else "unchanged",
        "path": str(design),
        "changes": changes,
        "validation": "passed",
        "backup": str(backup) if changes and backup else None,
    }


def self_test() -> None:
    fixture = json.loads((ROOT / "tests" / "fixtures" / "v32_sentry_fix_design_recovery.json").read_text())
    normalized, changes = normalize_fix_design_result(fixture["malformed_fix_design_result"])
    assert changes == fixture["expected_changes"]
    assert normalized["inputs_consumed"] == fixture["expected_inputs_consumed"]
    assert normalized["blocking_unknowns"] == []
    contract = normalized["interface_contract"]
    assert isinstance(contract, dict)
    assert all(_nonempty_string(contract[field]) for field in fixture["expected_interface_fields"])
    print("normalize_fix_design_result self-test: passed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", type=Path)
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.artifact_root:
        parser.error("--artifact-root is required")
    try:
        result = normalize_artifact_root(args.artifact_root, args.backup)
    except (json.JSONDecodeError, OSError, ValueError) as error:
        print(json.dumps({"status": "blocked", "reason": str(error)}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
