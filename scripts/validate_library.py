#!/usr/bin/env python3
"""Static consistency checks for the workflow-framework pilot."""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILLS = {
    path.stem for path in (ROOT / "skills").glob("*.md") if path.stem != "README"
}
TEMPLATES = list((ROOT / "templates").glob("*_run_prompt.md"))
INVARIANT = "The shared contract and selected playbook own lifecycle, worker activation,"
MATURITY = {"not_exercised", "exercising"}
WORKFLOW_CONTRACT = ROOT / "contracts" / "workflow_execution.md"
CLAIMS_CONTRACT = ROOT / "contracts" / "claims.md"


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


for path in ROOT.rglob("*.md"):
    text = path.read_text()
    version = re.search(r"^version: (.+)$", text, re.M)
    if version and version.group(1) != "0.1":
        fail(f"{path.relative_to(ROOT)} has version {version.group(1)!r}")

for path in ROOT.rglob("*.toml"):
    with path.open("rb") as handle:
        tomllib.load(handle)

for path in (ROOT / "playbooks").glob("*.md"):
    text = path.read_text()
    maturity = re.search(r"^maturity: (.+)$", text, re.M)
    if not maturity or maturity.group(1) not in MATURITY:
        fail(f"{path.relative_to(ROOT)} has no valid maturity")

for path in TEMPLATES:
    text = path.read_text()
    if INVARIANT not in text:
        fail(f"{path.relative_to(ROOT)} is missing the shared run invariants")

for path in (ROOT / "playbooks").glob("*.md"):
    text = path.read_text()
    if "standard planning workers, then `implement`" in text:
        fail(f"{path.relative_to(ROOT)} reruns planning workers during remediation")
    if "In-scope review findings return" not in text:
        fail(f"{path.relative_to(ROOT)} is missing the delivery review loop")

workflow_contract = WORKFLOW_CONTRACT.read_text()
if "## Delivery Code Review Loop" not in workflow_contract:
    fail("contracts/workflow_execution.md is missing the delivery review loop")
if not CLAIMS_CONTRACT.exists():
    fail("contracts/claims.md is missing")
if "Claims, Evidence, Decisions, and Actions Contract" not in workflow_contract:
    fail("contracts/workflow_execution.md is missing the claims contract reference")
if "| `confidence`       | Yes" not in workflow_contract:
    fail("contracts/workflow_execution.md is missing required worker confidence")
if "# Workflow State Machine" not in workflow_contract:
    fail("contracts/workflow_execution.md is missing the canonical state machine")

for name in ("generic.md", "claude.md", "cursor.md", "codex.md"):
    text = (ROOT / "providers" / name).read_text()
    missing = [skill for skill in sorted(SKILLS) if f"`{skill}`" not in text]
    if missing:
        fail(f"providers/{name} is missing skill mappings: {', '.join(missing)}")

print("Workflow-framework validation: passed")
