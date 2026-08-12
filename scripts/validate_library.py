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


for path in ROOT.rglob("*.md"):
    text = path.read_text()
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

for path in (ROOT / "playbooks").glob("*.md"):
    text = path.read_text()
    if "standard planning workers, then `implement`" in text:
        fail(f"{path.relative_to(ROOT)} reruns planning workers during remediation")
    if not re.search(r"In-scope review\s+findings return", text):
        fail(f"{path.relative_to(ROOT)} is missing the delivery review loop")
    if not re.search(r"Worker result ledger:\s+one compact row per activated worker", text):
        fail(f"{path.relative_to(ROOT)} is missing the canonical worker-result ledger")

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
