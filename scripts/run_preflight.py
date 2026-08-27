#!/usr/bin/env python3
"""Run the small, fail-fast checks required before loading a workflow."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
import time
from pathlib import Path


FULL_SHA = re.compile(r"^[0-9a-fA-F]{40}$")
EXIT_OK = 0
EXIT_BLOCKED = 2


def _framework_root(script: Path) -> Path:
    return script.resolve().parents[1]


def _git(root: Path, *args: str) -> tuple[int, str, str]:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode, completed.stdout.strip(), completed.stderr.strip()


def _plugin_root(path: Path) -> Path | None:
    if not path.exists():
        return None
    resolved = path.resolve()
    if resolved.is_file() and resolved.name == "SKILL.md" and resolved.parent.name == "run":
        return resolved.parents[2]
    if resolved.is_dir() and (resolved / "skills").is_dir():
        return resolved
    return resolved


def _result(status: str, reason: str | None, **fields: str) -> dict[str, str | None]:
    return {"status": status, "reason": reason, **fields}


def preflight(
    framework_root: Path,
    *,
    declared_framework_revision: str | None = None,
    declared_plugin_path: Path | None = None,
) -> dict[str, str | None]:
    root = framework_root.expanduser().resolve()
    if not root.is_dir():
        return _result("blocked", "framework_root_unavailable", framework_root=str(root))
    if not (root / "PLAYBOOK_CATALOG.md").is_file() or not (root / ".codex-plugin" / "plugin.json").is_file():
        return _result("blocked", "plugin_package_incomplete", framework_root=str(root))

    if declared_plugin_path is not None:
        declared_root = _plugin_root(declared_plugin_path.expanduser())
        if declared_root is None or declared_root != root:
            return _result(
                "blocked",
                "plugin_revision_mismatch",
                framework_root=str(root),
                declared_plugin_path=str(declared_plugin_path.expanduser()),
            )

    revision_code, revision, revision_error = _git(root, "rev-parse", "HEAD")
    if revision_code:
        return _result(
            "blocked",
            "framework_revision_unavailable",
            framework_root=str(root),
            detail=revision_error or "git rev-parse HEAD failed",
        )
    if declared_framework_revision is not None:
        declared = declared_framework_revision.strip()
        if not FULL_SHA.fullmatch(declared):
            return _result(
                "blocked",
                "run_prompt_nonconformant",
                framework_root=str(root),
                framework_revision=revision,
            )
        if declared.lower() != revision.lower():
            return _result(
                "blocked",
                "framework_revision_mismatch",
                framework_root=str(root),
                framework_revision=revision,
                declared_framework_revision=declared,
            )

    status_code, dirty_status, status_error = _git(root, "status", "--short", "--untracked-files=all")
    if status_code:
        return _result(
            "blocked",
            "framework_status_unavailable",
            framework_root=str(root),
            framework_revision=revision,
            detail=status_error or "git status failed",
        )
    if dirty_status:
        return _result(
            "blocked",
            "framework_revision_mismatch",
            framework_root=str(root),
            framework_revision=revision,
            framework_status="dirty",
        )

    return _result(
        "passed",
        None,
        framework_root=str(root),
        framework_revision=revision,
        framework_status="clean",
    )


def _git_checked(root: Path, *args: str) -> str:
    code, stdout, stderr = _git(root, *args)
    if code:
        raise AssertionError(stderr or f"git {' '.join(args)} failed")
    return stdout


def self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="workflow-preflight-") as directory:
        root = Path(directory)
        (root / ".codex-plugin").mkdir()
        (root / "skills" / "run").mkdir(parents=True)
        (root / "PLAYBOOK_CATALOG.md").write_text("# catalog\n")
        (root / ".codex-plugin" / "plugin.json").write_text('{"name":"test","version":"0.0.1"}\n')
        skill = root / "skills" / "run" / "SKILL.md"
        skill.write_text("# run\n")
        subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.name", "preflight-test"], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.email", "preflight@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "test"], check=True)
        revision = _git_checked(root, "rev-parse", "HEAD")

        script = root / "scripts" / "run_preflight.py"
        assert _framework_root(script) == root.resolve()
        assert _framework_root(script) != root.parent.resolve()

        passed = preflight(root, declared_framework_revision=revision, declared_plugin_path=skill)
        assert passed["status"] == "passed", passed

        (root / "README.md").write_text("dirty\n")
        dirty = preflight(root)
        assert dirty["reason"] == "framework_revision_mismatch", dirty
        (root / "README.md").unlink()

        mismatch = preflight(root, declared_framework_revision="0" * 40)
        assert mismatch["reason"] == "framework_revision_mismatch", mismatch

        stale = preflight(root, declared_plugin_path=root / "missing" / "SKILL.md")
        assert stale["reason"] == "plugin_revision_mismatch", stale

    print("run_preflight self-test: passed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--declared-framework-revision")
    parser.add_argument("--declared-plugin-path", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return EXIT_OK

    started = time.perf_counter()
    result = preflight(
        _framework_root(Path(__file__)),
        declared_framework_revision=args.declared_framework_revision,
        declared_plugin_path=args.declared_plugin_path,
    )
    result["preflight_elapsed_ms"] = str(round((time.perf_counter() - started) * 1000, 1))
    print(json.dumps(result, sort_keys=True))
    return EXIT_OK if result["status"] == "passed" else EXIT_BLOCKED


if __name__ == "__main__":
    raise SystemExit(main())
