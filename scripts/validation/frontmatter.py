"""Canonical document header parsing and semantic versions."""

import re
from pathlib import Path

SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def frontmatter(text: str) -> list[str]:
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        return []
    try:
        return lines[1 : lines.index("---", 1)]
    except ValueError:
        return []


def frontmatter_value(path: Path, field: str) -> str | None:
    prefix = f"{field}:"
    return next(
        (line.split(":", 1)[1].strip() for line in frontmatter(path.read_text()) if line.startswith(prefix)),
        None,
    )
