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
FIELDS = ("version", "last_updated", "status", "maturity", "exercise_scope", "validation_summary")


def render_status(root: Path = ROOT) -> str:
    rows = [BEGIN, "| Playbook | Version | Updated | Status | Maturity | Exercise scope | Validation summary |",
            "| --- | --- | --- | --- | --- | --- | --- |"]
    paths = sorted((root / "playbooks").glob("*.md"))
    if not paths:
        raise ValueError("No playbooks found")
    for path in paths:
        fields = metadata(path)
        missing = [key for key in ("title", *FIELDS) if not fields.get(key)]
        if missing:
            raise ValueError(f"{path.name}: missing catalog metadata: {', '.join(missing)}")
        title = fields["title"].removesuffix(" Playbook")
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
