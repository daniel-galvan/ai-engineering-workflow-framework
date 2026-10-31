"""Recognize read-only host memory access authorized by native host instructions."""

from __future__ import annotations

import json
import os
import re
import shlex
from pathlib import Path


def host_memory_root(session: Path) -> Path | None:
    """Trust only the native developer/system instruction, never the task prompt."""
    declared_root = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "memories"
    root = declared_root.resolve()
    try:
        with session.open() as stream:
            for line in stream:
                row = json.loads(line)
                payload = row.get("payload", {})
                if (row.get("type") != "response_item" or payload.get("type") != "message"
                        or payload.get("role") not in {"developer", "system"}):
                    continue
                content = payload.get("content", [])
                text = "\n".join(part.get("text", "") for part in content if isinstance(part, dict))
                if "MEMORY_SUMMARY" not in text or "Decision boundary" not in text:
                    continue
                registry = re.search(r"(?m)^\s*-\s+(.+/memories/MEMORY\.md)\s+\(searchable registry", text)
                if registry and Path(registry[1]).is_absolute():
                    return Path(registry[1]).parent.resolve()
                if any(str(path / "MEMORY.md") in text for path in (declared_root, root)):
                    return root
    except (OSError, ValueError, TypeError, AttributeError):
        return None
    return None


def host_memory_target(command: str, root: Path | None, linked_sessions: set[Path] | None = None) -> str | None:
    """Accept only simple read-only commands targeting the host memory catalog or referenced notes."""
    if root is None or not isinstance(command, str) or any(c in command for c in "$`\n\r;&<>"):
        return None
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars="|")
        lexer.whitespace_split = True
        argv = list(lexer)
        if "|" in argv:
            pipe = argv.index("|")
            tail = argv[pipe + 1:]
            safe_sed = (len(tail) == 3 and tail[:2] == ["sed", "-n"]
                        and re.fullmatch(r"[1-9][0-9]*(?:,[1-9][0-9]*)?p", tail[2]))
            safe_head = (tail == ["head"] or len(tail) == 2 and tail[0] == "head"
                         and re.fullmatch(r"-[1-9][0-9]*", tail[1]) or len(tail) == 3
                         and tail[:2] == ["head", "-n"] and re.fullmatch(r"[1-9][0-9]*", tail[2]))
            if not (safe_sed or safe_head):
                return None
            argv = argv[:pipe]
        if len(argv) == 3 and argv[:2] == ["nl", "-ba"]:
            target = argv[2]
        elif len(argv) == 2 and argv[0] == "cat":
            target = argv[1]
        elif (len(argv) == 4 and argv[:2] == ["sed", "-n"]
              and re.fullmatch(r"[1-9][0-9]*(?:,[1-9][0-9]*)?p", argv[2])):
            target = argv[3]
        elif argv and argv[0] == "rg":
            args = argv[1:]
            flags = {"-n", "--line-number", "-i", "--ignore-case", "-F", "--fixed-strings",
                     "-S", "--smart-case", "--no-heading", "--no-config"}
            counts = {"-A", "--after-context", "-B", "--before-context", "-C", "--context", "-m", "--max-count"}
            while args:
                if args[0] in flags:
                    args.pop(0)
                elif args[0] in counts and len(args) > 1 and re.fullmatch(r"[0-9]+", args[1]):
                    del args[:2]
                elif re.fullmatch(r"(?:-[ABCm]|--(?:after-context|before-context|context|max-count)=)[0-9]+", args[0]):
                    args.pop(0)
                else:
                    break
            if len(args) != 2 or not args[0] or args[0].startswith("-"):
                return None
            target = args[1]
        else:
            return None
        path = Path(target)
        if not path.is_absolute():
            return None
        path = path.resolve()
        if (path == root / "MEMORY.md" or path.is_relative_to(root / "rollout_summaries")
                or path.is_relative_to(root / "skills") or path in (linked_sessions or set())):
            return target
        return None
    except (OSError, ValueError, IndexError):
        return None


def host_memory_rollouts(output: str, root: Path) -> set[Path]:
    """Retain only exact native session paths named by a host memory note."""
    allowed = set()
    pattern = r"\brollout_path\s*[=:]\s*(?:([\"'`])([^\n]+?\.jsonl)\1|([^\s'\"`]+\.jsonl))"
    for _, quoted, unquoted in re.findall(pattern, output):
        value = quoted or unquoted
        path = Path(value)
        if path.is_absolute():
            try:
                resolved = path.resolve()
                if resolved.is_relative_to((root.parent / "sessions").resolve()):
                    allowed.add(resolved)
            except (OSError, ValueError):
                continue
    return allowed


def host_memory_read(command: str, root: Path | None, linked_sessions: set[Path] | None = None) -> bool:
    return host_memory_target(command, root, linked_sessions) is not None
