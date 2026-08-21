#!/usr/bin/env python3
"""Static consistency checks for the workflow-framework pilot."""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RELEASE_VERSION = "0.3.0"
MODEL_BASELINE_ID = "codex-role-policy-v0.3.0-01"
MAX_MARKDOWN_PROSE_WIDTH = 120
SKILLS = {
    path.stem for path in (ROOT / "skills").glob("*.md") if path.stem != "README"
}
TEMPLATES = list((ROOT / "templates").glob("*_run_prompt.md"))
INVARIANT = "The shared contract and selected playbook own lifecycle, worker activation,"
MATURITY = {"not_exercised", "exercising"}
EXERCISE_COMBINATIONS = (
    "standard + planning",
    "deep + planning",
    "standard + remediation",
    "deep + remediation",
)
WORKFLOW_CONTRACT = ROOT / "contracts" / "workflow_execution.md"
WORKFLOW_GUIDANCE = ROOT / "contracts" / "workflow_execution_guidance.md"
WORKFLOW_VOCABULARY = ROOT / "contracts" / "workflow_vocabulary.md"
PORTABLE_HANDOFF_CONTRACT = ROOT / "contracts" / "portable_implementation_handoff.md"
CLAIMS_CONTRACT = ROOT / "contracts" / "claims.md"
WORKFLOW_EVALUATION = ROOT / "frameworks" / "workflow_evaluation.md"
CODEX_POLICY = ROOT / "providers" / "codex" / "model_effort_policy.md"
CODEX_AGENT_DIR = ROOT / "providers" / "codex" / "agents"
IMPLEMENTATION_HANDOFF_TEMPLATE = ROOT / "templates" / "implementation_handoff.md"

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


def frontmatter(text: str) -> list[str]:
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        return []
    try:
        return lines[1 : lines.index("---", 1)]
    except ValueError:
        return []


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
    dependency_list = False
    for line in frontmatter(text):
        if line == "depends_on:":
            dependency_list = True
            continue
        if dependency_list and line.startswith("  - "):
            dependency = line[4:]
            if not (path.parent / dependency).resolve().exists():
                fail(f"{path.relative_to(ROOT)} references missing dependency {dependency}")
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
                fail(f"{path.relative_to(ROOT)}:{line_number} has broken link {target}")
        if line.lstrip().startswith("|") or not line.strip():
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
    if version and version.group(1) != RELEASE_VERSION:
        fail(f"{path.relative_to(ROOT)} has version {version.group(1)!r}")

agent_configs = {}
for path in ROOT.rglob("*.toml"):
    with path.open("rb") as handle:
        config = tomllib.load(handle)
    if path.parent == CODEX_AGENT_DIR:
        agent_configs[path.stem] = config

policy_text = CODEX_POLICY.read_text()
expected_agents = {}

if f"baseline_id: {MODEL_BASELINE_ID}" not in policy_text:
    fail(f"{CODEX_POLICY.relative_to(ROOT)} has no current model-policy baseline ID")

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

for agent_name in ("orchestrator", "sentry_orchestrator"):
    instructions = agent_configs[agent_name].get("developer_instructions", "")
    for phrase in (
        "A `wait_agent` timeout is a polling boundary, not a worker failure.",
        "do not call `close_agent`",
        "coordinator_interrupted_after_wait_timeout",
        "A wait timeout or `running` status is",
    ):
        if phrase not in instructions:
            fail(f"{agent_name}.toml is missing safe wait/recovery rule: {phrase}")
    for phrase in (
        "An implementation approval received during a planning conversation",
        "Coordinator-only",
        "Never report remediation complete after",
        "An `in_progress`, `running`, or `awaiting_dependency` status is intermediate",
        "No action is required from the user.",
    ):
        if phrase not in instructions:
            fail(f"{agent_name}.toml is missing remediation barrier rule: {phrase}")

for agent_name, phrases in {
    "implementer": (
        "delegated current-run Implementer",
        "Delivery Activation Barrier",
        "workflow violation",
        "plan-conformance manifest",
        "replanning_required",
    ),
    "reviewer": (
        "delegated Reviewer inspected the current",
        "accepted delivery review",
        "plan-conformance manifest",
    ),
    "tester": (
        "delegated Reviewer returns `accepted`",
        "terminal result",
    ),
    "documenter": (
        "completed handoff",
        "Activation Barrier shows terminal",
    ),
}.items():
    instructions = agent_configs[agent_name].get("developer_instructions", "")
    for phrase in phrases:
        if phrase not in instructions:
            fail(f"{agent_name}.toml is missing remediation barrier rule: {phrase}")

for path in (ROOT / "playbooks").glob("*.md"):
    text = path.read_text()
    maturity = re.search(r"^maturity: (.+)$", text, re.M)
    if not maturity or maturity.group(1) not in MATURITY:
        fail(f"{path.relative_to(ROOT)} has no valid maturity")
    exercise_scope = re.search(r"^exercise_scope: (.+)$", text, re.M)
    if not exercise_scope or any(value not in exercise_scope.group(1) for value in EXERCISE_COMBINATIONS):
        fail(f"{path.relative_to(ROOT)} has incomplete exercise scope")
    if not re.search(r"^validation_summary: .+$", text, re.M):
        fail(f"{path.relative_to(ROOT)} has no validation summary")

for path in TEMPLATES:
    text = path.read_text()
    if INVARIANT not in text:
        fail(f"{path.relative_to(ROOT)} is missing the shared run invariants")
    if "Confirmed user decisions and constraints (authoritative; do not reopen):" not in text:
        fail(f"{path.relative_to(ROOT)} is missing the authoritative-input section")
    if "Additional supplied context (preserve and classify):" not in text:
        fail(f"{path.relative_to(ROOT)} is missing the additional-context section")
    for phrase in (
        "Before acting, read the selected playbook plus `contracts/workflow_execution.md` and `contracts/claims.md`",
        "templates and examples are not runtime instructions.",
        "Current explicit user decisions and constraints are authoritative",
        "Delivery Activation Barrier",
        "Never claim successful execution when the required graph is incomplete.",
    ):
        if phrase not in text:
            fail(f"{path.relative_to(ROOT)} is missing runtime bootstrap rule: {phrase}")

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
    if "in parallel" not in text or not re.search(r"recorded\s+discrepancy", text):
        fail(f"{path.relative_to(ROOT)} is missing Deep parallelism or non-duplication rules")

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

feature_delivery_playbook = (ROOT / "playbooks" / "feature_delivery.md").read_text()
for phrase in (
    "independently deployable vertical slice",
    "unavailable baseline is not a planning blocker",
    "source-to-destination feature delivery",
    "always uses `deep`",
    "source and destination revisions",
    "private replacement persistence",
):
    if phrase not in feature_delivery_playbook:
        fail(f"playbooks/feature_delivery.md is missing source-to-destination rule: {phrase}")

planning_readiness_reference = (
    "[planning-readiness]: "
    "../contracts/workflow_execution.md#planning-readiness-and-implementation-work"
)
for filename in (
    "feature_delivery.md",
    "techops_issue_remediation.md",
    "vulnerability_investigation.md",
):
    if planning_readiness_reference not in (ROOT / "playbooks" / filename).read_text():
        fail(f"playbooks/{filename} is missing the shared planning-readiness reference")

sentry_repository_integrator = agent_configs["sentry_repository_integrator"].get(
    "developer_instructions", ""
)
for phrase in (
    "failing or unavailable build or test baseline",
    "do not return `blocked` merely because",
):
    if phrase not in sentry_repository_integrator:
        fail(f"sentry_repository_integrator.toml is missing planning-readiness rule: {phrase}")

workflow_contract = WORKFLOW_CONTRACT.read_text()
if "## Normative Language" not in workflow_contract:
    fail("contracts/workflow_execution.md is missing normative language")
for invariant_id in range(1, 27):
    if f"`INV-{invariant_id:02d}`" not in workflow_contract:
        fail(f"contracts/workflow_execution.md is missing INV-{invariant_id:02d}")
if "# Pilot Conformance Checklist" not in workflow_contract:
    fail("contracts/workflow_execution.md is missing the conformance checklist")
for heading in (
    "# Human Control Model",
    "## Authoritative Run Inputs",
    "## Context Preservation and Classification",
    "## Playbook Selection",
    "## Human-Readable Handoff",
    "## Worker Wait and Termination Semantics",
    "## Stop Conditions",
    "## Explicit Path Verification",
):
    if heading not in workflow_contract:
        fail(f"contracts/workflow_execution.md is missing {heading}")
if "MUST override a historical worker conclusion" not in workflow_contract:
    fail("contracts/workflow_execution.md is missing current-decision precedence")
if "## Delivery Code Review Loop" not in workflow_contract:
    fail("contracts/workflow_execution.md is missing the delivery review loop")
for phrase in (
    "## Planning Readiness and Implementation Work",
    "Implementation-plan work includes",
    "A true planning blocker exists only",
    "## Delivery Activation and Completion Barrier",
    "active delegated `implement` worker",
    "A source change made before the barrier",
    "The remediation run remains `in_progress`",
    "## Implementation Plan Conformance Check",
    "plan-conformance manifest",
    "unmapped change",
    "## Continuous Worker Progress",
    "ordinary worker transition",
    "runtime closure is recorded",
):
    if phrase not in workflow_contract:
        fail(f"contracts/workflow_execution.md is missing planning-readiness rule: {phrase}")
for phrase in (
    "Workflow execution: <completed | incomplete | blocked>",
    "Task outcome: <solved | partially_solved | plan_only | blocked | incorrect>",
):
    if phrase not in workflow_contract:
        fail(f"contracts/workflow_execution.md is missing handoff result: {phrase}")
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
for phrase in (
    "A wait timeout is a polling boundary, not a worker outcome.",
    "coordinator_interrupted_after_wait_timeout",
    "activated_profile",
    "executed_profile",
    "Portable Implementation Handoff Contract](portable_implementation_handoff.md)",
    "Workflow Execution Guidance](workflow_execution_guidance.md)",
    "## Input Delivery and Consumption Gate",
    "Input IDs actually used in `inputs_consumed`",
    "Workers that share a completed dependency and do not depend on each other MUST start in parallel",
    "Deep does not authorize duplicated investigation",
):
    if phrase not in workflow_contract:
        fail(f"contracts/workflow_execution.md is missing wait/profile semantics: {phrase}")
for path in (WORKFLOW_GUIDANCE, WORKFLOW_VOCABULARY, PORTABLE_HANDOFF_CONTRACT):
    if not path.exists():
        fail(f"{path.relative_to(ROOT)} is missing")
portable_handoff_contract = PORTABLE_HANDOFF_CONTRACT.read_text()
for phrase in ("# Portable Implementation Handoff Contract", "The portable handoff MUST"):
    if phrase not in portable_handoff_contract:
        fail(f"{PORTABLE_HANDOFF_CONTRACT.relative_to(ROOT)} is missing: {phrase}")
work_record_template = (ROOT / "templates" / "work_record.md").read_text()
if "| Engineering state |" not in work_record_template:
    fail("templates/work_record.md is missing engineering state")
if "| Approval type |" not in work_record_template:
    fail("templates/work_record.md is missing approval type")
if "# Path Verification" not in work_record_template:
    fail("templates/work_record.md is missing path verification")
if "# Input Register" not in work_record_template:
    fail("templates/work_record.md is missing input provenance")
if "| Input ID |" not in work_record_template or "| Assigned inputs |" not in work_record_template:
    fail("templates/work_record.md is missing input assignment tracking")
if "# Delivery Activation Gate" not in work_record_template:
    fail("templates/work_record.md is missing the delivery activation gate")
if "# Implementation Conformance Check" not in work_record_template:
    fail("templates/work_record.md is missing implementation conformance")
if "| Internal owner |" not in work_record_template:
    fail("templates/work_record.md is missing internal-owner handoff guidance")
if "| User action |" not in work_record_template:
    fail("templates/work_record.md is missing user-action handoff guidance")
for phrase in ("# Playbook Selection", "| Workflow execution |", "| Task outcome |"):
    if phrase not in work_record_template:
        fail(f"templates/work_record.md is missing outcome/classification field: {phrase}")
if "| Model-policy baseline ID |" not in work_record_template:
    fail("templates/work_record.md is missing the model-policy baseline ID")

role_requirements = {
    "orchestrator.md": ("Delivery Activation Barrier", "does not implement", "An active worker status is not a handoff"),
    "implementer.md": ("delegated worker", "workflow violation"),
    "reviewer.md": ("delegated Implementer returns a terminal", "accepted delivery review"),
    "tester.md": ("delegated Reviewer accepts the current diff", "terminal result"),
    "documenter.md": ("remediation handoff records terminal Implementer", "runtime closure"),
}
for filename, phrases in role_requirements.items():
    role_text = (ROOT / "roles" / filename).read_text()
    for phrase in phrases:
        if phrase not in role_text:
            fail(f"roles/{filename} is missing remediation barrier rule: {phrase}")

implementation_plan_template = (ROOT / "templates" / "implementation_plan.md").read_text()
if "The plan does not authorize implementation" not in implementation_plan_template:
    fail("templates/implementation_plan.md is missing the delivery activation rule")
if not WORKFLOW_EVALUATION.exists():
    fail("frameworks/workflow_evaluation.md is missing")
workflow_evaluation = WORKFLOW_EVALUATION.read_text()
for heading in ("# Workflow Evaluation", "## Pilot Method", "## Comparison Rules"):
    if heading not in workflow_evaluation:
        fail(f"frameworks/workflow_evaluation.md is missing {heading}")
if "recorded model-policy baseline" not in workflow_evaluation:
    fail("frameworks/workflow_evaluation.md is missing baseline comparison control")
if "# Workflow Evaluation" not in work_record_template:
    fail("templates/work_record.md is missing workflow evaluation")
for phrase in (
    "Task outcome",
    "Clarifications",
    "Approvals",
    "Manual corrections",
    "Reruns",
    "Human review effort",
    "Control fidelity",
    "Instruction violations",
    "Authoritative inputs ignored",
    "Supplied inputs not consumed",
    "Unapproved plan deviations",
    "Worker elapsed time",
    "Worker wait time",
):
    if phrase not in workflow_evaluation:
        fail(f"frameworks/workflow_evaluation.md is missing outcome/burden metric: {phrase}")
    if phrase not in work_record_template:
        fail(f"templates/work_record.md is missing outcome/burden metric: {phrase}")
for phrase in (
    "initial hypothesis: an experimental baseline",
    "Orchestrator | `gpt-5.6-terra` | Medium | `medium`",
    "Dependency Analyst | `gpt-5.6-luna` | Medium | `medium`",
    "Repository Integrator | `gpt-5.6-luna` | Medium | `medium`",
    "Solution Architect | `gpt-5.6-terra` | Medium | `medium`",
    "Reviewer | `gpt-5.6-terra` | Medium | `medium`",
):
    if phrase not in policy_text:
        fail(f"{CODEX_POLICY.relative_to(ROOT)} is missing experimental baseline: {phrase}")

if not IMPLEMENTATION_HANDOFF_TEMPLATE.exists():
    fail("templates/implementation_handoff.md is missing")
implementation_handoff = IMPLEMENTATION_HANDOFF_TEMPLATE.read_text()
for heading in (
    "# Portable Implementation Handoff",
    "## Start Here",
    "## Receiving-Session Instructions",
    "## Environment Preflight",
    "## Ordered Execution Plan",
    "## Strict Code Review Requirements",
    "## Stop Conditions",
    "## Final Report",
):
    if heading not in implementation_handoff:
        fail(f"templates/implementation_handoff.md is missing {heading}")
for phrase in (
    "This document is self-contained",
    "Execute the approved implementation handoff at:",
    "You are already at the root of the target repository. Follow the handoff exactly.",
    "Target project or component path",
    "sibling projects remain available",
    "Handoff status",
    "One implementation approval covers all in-scope steps",
    "implementation will happen in another session or environment",
    "Same-session implementation does not require a handoff",
    "happy paths",
    "alternate, error, empty",
    "The commands in this table are authoritative",
    "Do not claim independent review",
    "Target branch",
    "current default branch",
    "## Scope Boundaries",
):
    if phrase not in implementation_handoff:
        fail(f"templates/implementation_handoff.md is missing {phrase}")
for phrase in (
    "## Requested Runtime Settings",
    "actual model, effort",
    "provider-specific agents",
    "| Target revision |",
    "`Target revision`",
    "## Scope and Exclusions",
):
    if phrase in implementation_handoff:
        fail(f"templates/implementation_handoff.md must not contain runtime-routing detail: {phrase}")
if "implementation_handoff.md" not in (ROOT / "templates" / "implementation_plan.md").read_text():
    fail("templates/implementation_plan.md does not link the portable handoff")

for name in ("generic.md", "claude.md", "cursor.md", "codex.md"):
    text = (ROOT / "providers" / name).read_text()
    missing = [skill for skill in sorted(SKILLS) if f"`{skill}`" not in text]
    if missing:
        fail(f"providers/{name} is missing skill mappings: {', '.join(missing)}")

print("Workflow-framework validation: passed")
