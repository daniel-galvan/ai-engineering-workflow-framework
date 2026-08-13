#!/usr/bin/env python3
"""Static consistency checks for the workflow-framework pilot."""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAX_MARKDOWN_PROSE_WIDTH = 120
SKILLS = {
    path.stem for path in (ROOT / "skills").glob("*.md") if path.stem != "README"
}
TEMPLATES = list((ROOT / "templates").glob("*_run_prompt.md"))
INVARIANT = "The shared contract and selected playbook own lifecycle, worker activation,"
MATURITY = {"not_exercised", "exercising"}
WORKFLOW_CONTRACT = ROOT / "contracts" / "workflow_execution.md"
CLAIMS_CONTRACT = ROOT / "contracts" / "claims.md"
WORKFLOW_EVALUATION = ROOT / "frameworks" / "workflow_evaluation.md"
CODEX_POLICY = ROOT / "providers" / "codex" / "model_effort_policy.md"
CODEX_AGENT_DIR = ROOT / "providers" / "codex" / "agents"

ROLE_AGENT_ALIASES = {
    "Orchestrator": ("orchestrator",),
    "Current-State Investigator / Sentry Evidence": ("current_state_investigator",),
    "Dependency Analyst": ("dependency_analyst",),
    "Repository Integrator": ("repository_integrator",),
    "Solution Architect": ("solution_architect",),
    "Reviewer": ("reviewer",),
    "Implementer": ("implementer",),
    "Tester": ("tester",),
    "Documenter": ("documenter",),
}


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


def table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip()[1:-1].split("|")]


def is_table_row(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|")


for path in ROOT.rglob("*.md"):
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

        relative = path.relative_to(ROOT)
        if len(header) != len(separator):
            fail(f"{relative}:{index + 2} has a table column-count mismatch")
        if not (lines[index + 1].startswith("| ") and lines[index + 1].endswith(" |")):
            fail(f"{relative}:{index + 2} has a non-portable table separator")

        row = index + 2
        while row < len(lines) and is_table_row(lines[row]):
            if len(table_cells(lines[row])) != len(header):
                fail(f"{relative}:{row + 1} has a table column-count mismatch")
            row += 1
        index = row


for path in ROOT.rglob("*.md"):
    text = path.read_text()
    in_fence = False
    for line_number, line in enumerate(text.splitlines(), start=1):
        if line.startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if in_fence or line.lstrip().startswith("|") or not line.strip():
            continue
        if re.match(r"^\s*\#{1,6}[^\s#]", line):
            fail(f"{path.relative_to(ROOT)}:{line_number} has an invalid heading marker")
        if re.match(r"^\s*\*\*#{1,6}\s", line) or re.match(
            r"^\s*#{1,6}\s+\*\*", line
        ):
            fail(f"{path.relative_to(ROOT)}:{line_number} has a malformed bold heading")
        if len(line) > MAX_MARKDOWN_PROSE_WIDTH:
            fail(
                f"{path.relative_to(ROOT)}:{line_number} prose line is "
                f"{len(line)} columns; maximum is {MAX_MARKDOWN_PROSE_WIDTH}"
            )
    if in_fence:
        fail(f"{path.relative_to(ROOT)} has an unclosed fenced block")
    version = re.search(r"^version: (.+)$", text, re.M)
    if version and version.group(1) != "0.1":
        fail(f"{path.relative_to(ROOT)} has version {version.group(1)!r}")

agent_configs = {}
for path in ROOT.rglob("*.toml"):
    with path.open("rb") as handle:
        config = tomllib.load(handle)
    if path.parent == CODEX_AGENT_DIR:
        agent_configs[path.stem] = config

policy_text = CODEX_POLICY.read_text()
expected_agents = {}

for match in re.finditer(
    r"^\| ([^|]+) \| `([^`]+)` \| ([^|]+) \| `([^`]+)` \|$",
    policy_text,
    re.M,
):
    role, model, _label, effort = (value.strip() for value in match.groups())
    if role not in ROLE_AGENT_ALIASES:
        continue
    for agent_name in ROLE_AGENT_ALIASES[role]:
        expected = (model, effort)
        previous = expected_agents.setdefault(agent_name, expected)
        if previous != expected:
            fail(f"{CODEX_POLICY.relative_to(ROOT)} maps {agent_name} inconsistently")

for match in re.finditer(
    r"^\| [^|]+ \| `([^`]+)` \| ([^|]+) \|$",
    policy_text,
    re.M,
):
    agent_name, role = (value.strip() for value in match.groups())
    if role not in ROLE_AGENT_ALIASES:
        continue
    if agent_name not in agent_configs:
        fail(f"{CODEX_POLICY.relative_to(ROOT)} references missing agent {agent_name}")
    role_agents = ROLE_AGENT_ALIASES[role]
    role_agent = role_agents[0]
    expected = expected_agents[role_agent]
    previous = expected_agents.setdefault(agent_name, expected)
    if previous != expected:
        fail(f"{CODEX_POLICY.relative_to(ROOT)} maps {agent_name} inconsistently")

missing_agents = sorted(set(agent_configs) - set(expected_agents))
undocumented_agents = sorted(set(expected_agents) - set(agent_configs))
if missing_agents:
    fail(f"Codex policy does not document agents: {', '.join(missing_agents)}")
if undocumented_agents:
    fail(f"Codex policy references missing TOML agents: {', '.join(undocumented_agents)}")

for agent_name, config in agent_configs.items():
    if config.get("name") != agent_name:
        fail(f"{agent_name}.toml name does not match its filename")
    actual = (config.get("model"), config.get("model_reasoning_effort"))
    if actual != expected_agents[agent_name]:
        fail(
            f"{agent_name}.toml has {actual[0]} + {actual[1]}; "
            f"policy requires {expected_agents[agent_name][0]} + "
            f"{expected_agents[agent_name][1]}"
        )

for path in (ROOT / "playbooks").glob("*.md"):
    text = path.read_text()
    maturity = re.search(r"^maturity: (.+)$", text, re.M)
    if not maturity or maturity.group(1) not in MATURITY:
        fail(f"{path.relative_to(ROOT)} has no valid maturity")

for path in TEMPLATES:
    text = path.read_text()
    if INVARIANT not in text:
        fail(f"{path.relative_to(ROOT)} is missing the shared run invariants")
    if "Confirmed user decisions and constraints (authoritative; do not reopen):" not in text:
        fail(f"{path.relative_to(ROOT)} is missing the authoritative-input section")
    if "Additional supplied context (preserve and classify):" not in text:
        fail(f"{path.relative_to(ROOT)} is missing the additional-context section")

for path in (ROOT / "playbooks").glob("*.md"):
    text = path.read_text()
    if "standard planning workers, then `implement`" in text:
        fail(f"{path.relative_to(ROOT)} reruns planning workers during remediation")
    if not re.search(r"In-scope review\s+findings return", text):
        fail(f"{path.relative_to(ROOT)} is missing the delivery review loop")
    if not re.search(r"Worker result ledger:\s+one compact row per activated worker", text):
        fail(f"{path.relative_to(ROOT)} is missing the canonical worker-result ledger")
    if "Human-Readable Handoff block" not in text:
        fail(f"{path.relative_to(ROOT)} is missing the human-readable handoff block")

vulnerability_playbook = (ROOT / "playbooks" / "vulnerability_investigation.md").read_text()
for phrase in (
    "## Finding Classification and Route",
    "`dependency`",
    "`injection`",
    "`infrastructure`",
    "at least two concrete options",
    "implementation_plan: not_created",
):
    if phrase not in vulnerability_playbook:
        fail(f"playbooks/vulnerability_investigation.md is missing {phrase}")

sentry_playbook = (ROOT / "playbooks" / "sentry_issue_remediation.md").read_text()
if "Prompt-preparation rules:" not in (ROOT / "templates" / "sentry_issue_run_prompt.md").read_text():
    fail("templates/sentry_issue_run_prompt.md is missing prompt-preparation rules")
if "event_origin_repository: A" not in (ROOT / "templates" / "sentry_issue_run_prompt.md").read_text():
    fail("templates/sentry_issue_run_prompt.md is missing topology extraction rules")
for phrase in (
    "Standard planning is bounded",
    "latest event as the primary occurrence",
    "Do not inspect every",
    "A local/deployed revision mismatch",
    "The remediation boundary is the explicit set",
    "name that scope in plain language",
    "comparison source of truth",
    "Do not ask the user to redefine the baseline",
    "technical hypothesis",
):
    if phrase not in sentry_playbook:
        fail(f"playbooks/sentry_issue_remediation.md is missing {phrase}")
if "Sentry evidence and repository revision are identified" in sentry_playbook:
    fail("playbooks/sentry_issue_remediation.md still blocks on exact revision identification")

workflow_contract = WORKFLOW_CONTRACT.read_text()
if "## Normative Language" not in workflow_contract:
    fail("contracts/workflow_execution.md is missing normative language")
for invariant_id in range(1, 16):
    if f"`INV-{invariant_id:02d}`" not in workflow_contract:
        fail(f"contracts/workflow_execution.md is missing INV-{invariant_id:02d}")
if "# Pilot Conformance Checklist" not in workflow_contract:
    fail("contracts/workflow_execution.md is missing the conformance checklist")
for heading in (
    "# Human Control Model",
    "## Authoritative Run Inputs",
    "## Context Preservation and Classification",
    "## Human-Readable Handoff",
    "## Stop Conditions",
    "## Explicit Path Verification",
):
    if heading not in workflow_contract:
        fail(f"contracts/workflow_execution.md is missing {heading}")
if "## Delivery Code Review Loop" not in workflow_contract:
    fail("contracts/workflow_execution.md is missing the delivery review loop")
if not CLAIMS_CONTRACT.exists():
    fail("contracts/claims.md is missing")
claims_contract = CLAIMS_CONTRACT.read_text()
if "`status: assumed`" not in claims_contract:
    fail("contracts/claims.md is missing material assumption semantics")
for field in ("`assumption_owner`", "`impact_if_wrong`", "`validation_method`"):
    if field not in claims_contract:
        fail(f"contracts/claims.md is missing assumption field {field}")
if "`approval_type`" not in claims_contract:
    fail("contracts/claims.md is missing approval-type semantics")
if "Claims, Evidence, Decisions, and Actions Contract" not in workflow_contract:
    fail("contracts/workflow_execution.md is missing the claims contract reference")
if "| `confidence`       | Yes" not in workflow_contract:
    fail("contracts/workflow_execution.md is missing required worker confidence")
if "# Workflow State Machine" not in workflow_contract:
    fail("contracts/workflow_execution.md is missing the canonical state machine")
if "# Workflow State and Engineering State" not in workflow_contract:
    fail("contracts/workflow_execution.md is missing engineering-state semantics")
work_record_template = (ROOT / "templates" / "work_record.md").read_text()
if "| Engineering state |" not in work_record_template:
    fail("templates/work_record.md is missing engineering state")
if "| Approval type |" not in work_record_template:
    fail("templates/work_record.md is missing approval type")
if "# Path Verification" not in work_record_template:
    fail("templates/work_record.md is missing path verification")
if "| Internal owner |" not in work_record_template:
    fail("templates/work_record.md is missing internal-owner handoff guidance")
if "| User action |" not in work_record_template:
    fail("templates/work_record.md is missing user-action handoff guidance")
if not WORKFLOW_EVALUATION.exists():
    fail("frameworks/workflow_evaluation.md is missing")
workflow_evaluation = WORKFLOW_EVALUATION.read_text()
for heading in ("# Workflow Evaluation", "## Pilot Method", "## Comparison Rules"):
    if heading not in workflow_evaluation:
        fail(f"frameworks/workflow_evaluation.md is missing {heading}")
if "# Workflow Evaluation" not in work_record_template:
    fail("templates/work_record.md is missing workflow evaluation")

for name in ("generic.md", "claude.md", "cursor.md", "codex.md"):
    text = (ROOT / "providers" / name).read_text()
    missing = [skill for skill in sorted(SKILLS) if f"`{skill}`" not in text]
    if missing:
        fail(f"providers/{name} is missing skill mappings: {', '.join(missing)}")

print("Workflow-framework validation: passed")
