#!/usr/bin/env python3
"""Refresh or check the catalog's generated playbook exercise metadata."""

import argparse
from pathlib import Path

try:
    from framework_manifest import ROOT, metadata
except ModuleNotFoundError:
    from scripts.framework_manifest import ROOT, metadata

BEGIN = "<!-- BEGIN GENERATED PLAYBOOK STATUS -->"
END = "<!-- END GENERATED PLAYBOOK STATUS -->"
FIELDS = ("version", "last_updated", "status", "maturity", "supported_lifecycles", "exercise_scope",
          "exercise_status", "validation_summary")
COMBINATIONS = ("standard_planning", "deep_planning", "standard_remediation", "deep_remediation")
EXERCISE_STATES = {"pending", "exercised", "validated", "unsupported"}


def exercise_status(fields: dict[str, str]) -> dict[str, str]:
    lifecycles = {value.strip() for value in fields.get("supported_lifecycles", "").split(",")}
    if not lifecycles or not lifecycles <= {"planning", "remediation"}:
        raise ValueError("supported_lifecycles must explicitly declare planning and/or remediation")
    statuses = {key: fields.get(f"exercise_status_{key}", "") for key in COMBINATIONS}
    unknown = set(key for key in fields if key.startswith("exercise_status_")) - {
        f"exercise_status_{key}" for key in COMBINATIONS
    }
    if unknown:
        raise ValueError(f"unknown exercise status fields: {', '.join(sorted(unknown))}")
    for combination, state in statuses.items():
        if not isinstance(state, str) or state not in EXERCISE_STATES:
            raise ValueError(f"invalid exercise_status for {combination}: {state!r}")
        supported = combination.rsplit("_", 1)[1] in lifecycles
        if (supported and state == "unsupported") or (not supported and state != "unsupported"):
            raise ValueError(f"exercise_status for {combination} conflicts with supported_lifecycles")
    return statuses


def render_status(root: Path = ROOT) -> str:
    rows = [BEGIN,
            "| Playbook | Version | Updated | Status | Maturity | Supported lifecycles | Exercise scope | Exercise status | Validation summary |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    paths = sorted((root / "playbooks").glob("*.md"))
    if not paths:
        raise ValueError("No playbooks found")
    for path in paths:
        fields = metadata(path)
        missing = [key for key in ("title", *(key for key in FIELDS if key != "exercise_status"))
                   if not fields.get(key)]
        if missing:
            raise ValueError(f"{path.name}: missing catalog metadata: {', '.join(missing)}")
        try:
            statuses = exercise_status(fields)
        except ValueError as error:
            raise ValueError(f"{path.name}: {error}") from None
        title = fields["title"].removesuffix(" Playbook")
        fields["exercise_status"] = "; ".join(f"{key}: {statuses[key]}" for key in COMBINATIONS)
        cells = [f"[{title}](playbooks/{path.name})", *(fields[key] for key in FIELDS)]
        rows.append("| " + " | ".join(value.replace("|", "&#124;") for value in cells) + " |")
    return "\n".join([*rows, END])


def updated_catalog(root: Path = ROOT) -> str:
    text = (root / "PLAYBOOK_CATALOG.md").read_text()
    if text.count(BEGIN) != 1 or text.count(END) != 1 or text.index(BEGIN) >= text.index(END):
        raise ValueError("PLAYBOOK_CATALOG.md requires one ordered pair of generated status markers")
    start, end = text.index(BEGIN), text.index(END) + len(END)
    return text[:start] + render_status(root) + text[end:]


def catalog_errors(root: Path = ROOT) -> list[str]:
    try:
        expected = updated_catalog(root)
        actual = (root / "PLAYBOOK_CATALOG.md").read_text()
    except (OSError, ValueError) as error:
        return [f"PLAYBOOK_CATALOG.md: {error}"]
    if actual != expected:
        return ["PLAYBOOK_CATALOG.md status is stale; run python3 scripts/playbook_catalog.py --write"]
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="Refresh the generated status block")
    args = parser.parse_args()
    if args.write:
        (ROOT / "PLAYBOOK_CATALOG.md").write_text(updated_catalog())
        print("PLAYBOOK_CATALOG.md: updated")
        return 0
    errors = catalog_errors()
    print("\n".join(errors) if errors else "PLAYBOOK_CATALOG.md: current")
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
