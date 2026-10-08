"""Markdown tables, section extraction, links, dependencies, and formatting checks."""

import re
from pathlib import Path

from .frontmatter import SEMVER, frontmatter

MAX_MARKDOWN_PROSE_WIDTH = 120


def table_cells(line: str) -> list[str]:
    content = line.strip()[1:-1]
    cells: list[str] = []
    current: list[str] = []
    index = 0
    while index < len(content):
        if content[index:index + 2] == r"\|":
            current.append("|")
            index += 2
            continue
        if content[index] == "|":
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(content[index])
        index += 1
    cells.append("".join(current).strip())
    return cells


def is_table_row(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|")


def markdown_table(text: str, heading: str) -> list[dict[str, str]]:
    lines = text.splitlines()
    try:
        start = lines.index(heading) + 1
    except ValueError:
        return []
    while start < len(lines) and not is_table_row(lines[start]):
        if lines[start].startswith("#"):
            return []
        start += 1
    if start + 1 >= len(lines):
        return []
    headers = table_cells(lines[start])
    separator = table_cells(lines[start + 1])
    if len(headers) != len(separator) or not all("-" in cell for cell in separator):
        return []
    rows = []
    for line in lines[start + 2 :]:
        if not is_table_row(line):
            break
        cells = table_cells(line)
        if len(headers) != len(cells):
            return []
        rows.append(dict(zip(headers, cells, strict=True)))
    return rows


def fenced_section(text: str, heading: str) -> str:
    match = re.search(rf"^{re.escape(heading)}\s*\n+```text\s*\n(.*?)\n```", text, re.MULTILINE | re.DOTALL)
    return match.group(1) if match else ""


def markdown_errors(root: Path) -> list[str]:
    errors: list[str] = []
    for path in root.rglob("*.md"):
        lines = path.read_text().splitlines()
        index = 0
        while index + 1 < len(lines):
            if not (is_table_row(lines[index]) and is_table_row(lines[index + 1])):
                index += 1
                continue

            header = table_cells(lines[index])
            separator = table_cells(lines[index + 1])
            is_separator = separator and all(
                "-" in cell and set(cell) <= {"-", ":"} for cell in separator
            )
            if not is_separator:
                index += 1
                continue

            relative = path.relative_to(root)
            if len(header) != len(separator):
                errors.append(f"{relative}:{index + 2} has a table column-count mismatch")
            if not (lines[index + 1].startswith("| ") and lines[index + 1].endswith(" |")):
                errors.append(f"{relative}:{index + 2} has a non-portable table separator")

            row = index + 2
            while row < len(lines) and is_table_row(lines[row]):
                if len(table_cells(lines[row])) != len(header):
                    errors.append(f"{relative}:{row + 1} has a table column-count mismatch")
                row += 1
            index = row


    for path in root.rglob("*.md"):
        if ".thoughts" in path.relative_to(root).parts:
            continue
        text = path.read_text()
        dependency_list = False
        for line in frontmatter(text):
            if line == "depends_on:":
                dependency_list = True
                continue
            if dependency_list and line.startswith("  - "):
                dependency = line[4:]
                if not (path.parent / dependency).resolve().exists():
                    errors.append(f"{path.relative_to(root)} references missing dependency {dependency}")
                continue
            if dependency_list and line.strip():
                dependency_list = False

        in_fence = False
        for line_number, line in enumerate(text.splitlines(), start=1):
            if line.startswith(("```", "~~~")):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            for target in re.findall(r"(?<!!)\[[^]]+\]\(([^)]+)\)", line):
                target = target.strip().strip("<>").split("#", 1)[0]
                if not target or re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I):
                    continue
                if not (path.parent / target).resolve().exists():
                    errors.append(f"{path.relative_to(root)}:{line_number} has broken link {target}")
            if line.lstrip().startswith("|") or not line.strip():
                continue
            if re.match(r"^\s*\#{1,6}[^\s#]", line):
                errors.append(f"{path.relative_to(root)}:{line_number} has an invalid heading marker")
            if re.match(r"^\s*\*\*#{1,6}\s", line) or re.match(
                r"^\s*#{1,6}\s+\*\*", line
            ):
                errors.append(f"{path.relative_to(root)}:{line_number} has a malformed bold heading")
            if len(line) > MAX_MARKDOWN_PROSE_WIDTH:
                errors.append(
                    f"{path.relative_to(root)}:{line_number} prose line is "
                    f"{len(line)} columns; maximum is {MAX_MARKDOWN_PROSE_WIDTH}"
                )
        if in_fence:
            errors.append(f"{path.relative_to(root)} has an unclosed fenced block")
        version = re.search(r"^version: (.+)$", text, re.M)
        if version and not SEMVER.fullmatch(version.group(1)):
            errors.append(f"{path.relative_to(root)} has invalid semantic version {version.group(1)!r}")
    return errors
