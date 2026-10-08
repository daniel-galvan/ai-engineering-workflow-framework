"""Deterministic provider policy validation rules."""

from __future__ import annotations

import json
import re
import subprocess
import tomllib
from .common import (
    CODEX_ADAPTER,
    CODEX_AGENT_DIR,
    CODEX_POLICY,
    JIRA_INTEGRATION,
    MODEL_BASELINE_ID,
    MODEL_OBSERVATION_UNAVAILABLE_PREFIXES,
    PLUGIN_MANIFEST,
    POLICY_EFFORTS,
    ROLE_AGENT_ALIASES,
    ROOT,
    RUN_SKILL,
    SKILLS,
    fail,
)


def model_observation_unavailable(value: str) -> bool:
    normalized = " ".join(value.strip().lower().split())
    return any(
        normalized == prefix
        or normalized.startswith(f"{prefix};")
        or normalized.startswith(f"{prefix}:")
        for prefix in MODEL_OBSERVATION_UNAVAILABLE_PREFIXES
    )


def _plugin_version_refresh_error() -> str | None:
    completed = subprocess.run(
        ["git", "-C", str(ROOT), "status", "--porcelain", "--untracked-files=all"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode:
        return None
    changed = [line[3:] for line in completed.stdout.splitlines() if len(line) > 3]
    if not any(path != str(PLUGIN_MANIFEST.relative_to(ROOT)) for path in changed):
        return None
    previous = subprocess.run(
        ["git", "-C", str(ROOT), "show", f"HEAD:{PLUGIN_MANIFEST.relative_to(ROOT)}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if previous.returncode:
        return None
    try:
        previous_version = json.loads(previous.stdout)["version"]
        current_version = json.loads(PLUGIN_MANIFEST.read_text())["version"]
    except (json.JSONDecodeError, KeyError):
        return None
    if previous_version == current_version:
        return "plugin build metadata must change when bundled package content changes"
    return None


def validate_provider_policy() -> dict:
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
        role, model, label, effort = (value.strip() for value in match.groups())
        if role not in ROLE_AGENT_ALIASES:
            continue
        if POLICY_EFFORTS.get(label) != effort:
            fail(f"{CODEX_POLICY.relative_to(ROOT)} maps policy effort {label} inconsistently to {effort}")
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

    for phrase in ("nearest available", "then the parent session"):
        if phrase in policy_text:
            fail(f"{CODEX_POLICY.relative_to(ROOT)} permits unstable provider fallback: {phrase}")
    for phrase in ("do not inherit Coordinator values", "provider_configuration_unavailable", "new baseline ID"):
        if phrase not in policy_text:
            fail(f"{CODEX_POLICY.relative_to(ROOT)} is missing fail-closed provider resolution: {phrase}")

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
    return agent_configs


def validate_runtime_mapping() -> None:
    jira_text = JIRA_INTEGRATION.read_text()
    run_skill = RUN_SKILL.read_text()
    for phrase in (
        "scripts/run_preflight.py",
        "first framework tool call",
        "do not read memory",
        "plugin_revision_mismatch",
        "framework_revision_mismatch",
        "preflight_elapsed_ms",
        "preflight did not initialize a run",
        "no terminal work record is required",
        "receipt is terminal",
        "derives the package root from its own location",
        "scripts/prepare_run.py",
        "role_bindings.json",
        "provider_tool_mapping",
        "literal framework tool ID",
        "fork_context: false",
        "Coordinator initialization: complete",
        "worker_runtime_unavailable",
        "`spawn_agent`",
        "Never use",
        "`create_thread`",
        "`fork_thread`",
        "`send_message_to_thread`",
        "scripts/finalize_work_record.py",
        "scripts/finalize_sentry_planning.py",
        "scripts/normalize_fix_design_result.py",
        "finalization_packet.json",
        "preflight even when the app hides stdout",
        "do not rerun it solely",
        "--pre-release",
        "--analytical-failure-stage",
        "skill or plugin enable/disable directive",
        "task created at or after the captured current turn start",
        "standard_planning_finalization.finalizer",
        "worker_activation_packets.json",
        "worker_runtime_guard",
        "Never interrupt a live worker",
        "artifact creation intentionally omits it",
        "--input-manifest",
        "run_input_manifest_required",
        "current-run input manifest",
        "active parent session; no dedicated Coordinator worker spawned",
        "prompt-completeness gate",
        "run_prompt_incomplete:<field>",
        "the timebox, success criterion",
        "selected playbook's configured default",
        "Do not create a temporary input",
        "--primary-question <question>",
        "--success-criterion <criterion>",
        "only for run-specific overrides",
        "read the exact supplied issue key",
        "worker MUST use that connector first",
        "A later question about why a run blocked",
    ):
        if phrase not in run_skill:
            fail(f"skills/run/SKILL.md is missing fast-preflight control: {phrase}")
    if "--framework-root" in run_skill:
        fail("skills/run/SKILL.md must not pass a separately constructed framework root")
    codex_adapter = CODEX_ADAPTER.read_text()
    for phrase in ("## Launcher and Package Preflight", "## Worker Activation", "## Runtime Closure", "## Source Routing",
                   "first framework tool call", "direct Atlassian MCP connector first", "source_access_receipt.py",
                   "plugin_revision_mismatch", "list_agents", "read_thread", "wait_threads"):
        if phrase not in codex_adapter:
            fail(f"providers/codex.md is missing provider execution rule: {phrase}")
    for phrase in ("## Feature Delivery Source-Access Gate", "Start with `item`",
                   "Inventory every member of that collection", "at most one", "not connector-wide authentication failures"):
        if phrase not in jira_text:
            fail(f"integrations/jira.md is missing source policy: {phrase}")
    for phrase in (
        "fork_context: false",
        "Coordinator initialization: complete",
        "prepare_run.py",
        "worker_runtime_unavailable",
        "`spawn_agent`",
        "Never use `create_thread`",
        "`fork_thread`",
        "`send_message_to_thread`",
        "provider_tool_mapping",
        "literal framework tool ID",
        "try a configured direct MCP operation first",
        "hashed role envelope",
        "worker_runtime_guard",
        "run_inputs.json",
        "current-run input manifest",
    ):
        if phrase not in codex_adapter:
            fail(f"providers/codex.md is missing worker-isolation control: {phrase}")
    for phrase in (
        "## Jira Work-Item Read Mapping",
        "worker MUST use that connector first",
        "successful exact-key issue read there",
        "mcp__atlassian__getJiraIssue",
        "A resource lookup is not an issue read",
        "mcp__codex_apps__atlassian_rovo_getjiraissue",
        "mcp__codex_apps__atlassian_rovo_searchjiraissuesusingjql",
        "mcp__codex_apps__atlassian_rovo_getjiraissueremoteissuelinks",
        "mcp__codex_apps__atlassian_rovo_getvisiblejiraprojects",
        "mcp__codex_apps__atlassian_rovo_getjiraprojectissuetypesmetadata",
        "mcp__codex_apps__atlassian_rovo_getjiraissuetypemetawithfields",
        "mcp__codex_apps__atlassian_rovo_gettransitionsforjiraissue",
        "`work_item_read` MUST NOT invoke Jira create, edit, transition, comment, worklog",
    ):
        if phrase not in codex_adapter:
            fail(f"providers/codex.md is missing Jira provider mapping: {phrase}")
    current_state_agent = (CODEX_AGENT_DIR / "current_state_investigator.toml").read_text()
    for phrase in (
        "connector bound",
        "Do not silently switch connectors",
        "record the route per scope",
        "not open Jira in a browser",
        "normalized `unavailable` state",
        "comments, links, and repository/runtime",
        "observations distinguishable",
    ):
        if phrase not in current_state_agent:
            fail(f"providers/codex/agents/current_state_investigator.toml is missing Jira read control: {phrase}")


def validate_skill_mappings() -> None:
    for name in ("generic.md", "claude.md", "cursor.md", "codex.md"):
        text = (ROOT / "providers" / name).read_text()
        missing = [skill for skill in sorted(SKILLS) if f"`{skill}`" not in text]
        if missing:
            fail(f"providers/{name} is missing skill mappings: {', '.join(missing)}")
