#!/usr/bin/env python3
"""Generate or check the library's version inventory from canonical metadata."""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILENAME = "framework_manifest.json"


def metadata(path: Path) -> dict[str, str]:
    lines = path.read_text().splitlines()
    if not lines or lines[0] != "---":
        return {}
    try:
        end = lines.index("---", 1)
    except ValueError:
        raise ValueError(f"{path}: unclosed front matter") from None
    # Inventory only the flat scalar fields used by versioned document headers.
    return dict(line.split(": ", 1) for line in lines[1:end] if ": " in line and not line.startswith(" "))


def build_manifest(root: Path = ROOT) -> dict:
    documents = {}
    policies = {}
    for path in sorted(root.rglob("*.md")):
        relative = path.relative_to(root)
        if "tests" in relative.parts or any(part.startswith(".") for part in relative.parts):
            continue
        fields = metadata(path)
        if "version" not in fields:
            continue
        name = relative.as_posix()
        documents[name] = fields["version"]
        if "baseline_id" in fields:
            policies[name] = {"version": fields["version"], "baseline_id": fields["baseline_id"]}

    def revision(name: str) -> dict[str, str]:
        return {"path": name, "version": documents[name]}

    package = json.loads((root / ".codex-plugin/plugin.json").read_text())
    return {
        "schema_version": 1,
        "library_release": None,
        "library_release_status": "No aggregate library release is assigned; Git revisions identify snapshots.",
        "plugin_package": {"name": package["name"], "version": package["version"]},
        "framework": revision("frameworks/investigation.md"),
        "execution_contract": revision("contracts/workflow_execution.md"),
        "playbooks": {
            Path(name).stem: {"path": name, "version": version}
            for name, version in documents.items()
            if Path(name).parent == Path("playbooks")
        },
        "provider_policies": policies,
        "compatibility": {
            "document_versions": "independent",
            "cross_revision_compatibility": "not_declared",
            "rules": ["CONTRIBUTING.md", "contracts/workflow_execution.md", "providers/README.md"],
        },
        "documents": documents,
    }


def manifest_errors(root: Path = ROOT) -> list[str]:
    try:
        actual = json.loads((root / FILENAME).read_text())
        expected = build_manifest(root)
    except (OSError, ValueError, KeyError) as error:
        return [f"{FILENAME}: {error}"]
    if actual != expected:
        return [f"{FILENAME} is stale; run python3 scripts/framework_manifest.py --write"]
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="Regenerate the checked-in manifest")
    args = parser.parse_args()
    if args.write:
        (ROOT / FILENAME).write_text(json.dumps(build_manifest(), indent=2) + "\n")
        print(f"{FILENAME}: updated")
        return 0
    errors = manifest_errors()
    print("\n".join(errors) if errors else f"{FILENAME}: current")
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
