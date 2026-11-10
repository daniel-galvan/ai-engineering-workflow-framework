#!/usr/bin/env python3
"""Prepare fresh run artifacts and resolve Codex worker bindings."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import tomllib
from datetime import UTC, datetime, timedelta
from pathlib import Path

try:
    from run_input_manifest import (
        DEFAULT_PRECEDENCE_RULE as DEFAULT_PRECEDENCE_RULE,
        default_manifest,
        is_code_scope,
        load_manifest,
        local_input_paths,
        retain_source_releases,
        merge_manifests,
        packet_metadata,
        validate_manifest,
        write_manifest,
    )
except ModuleNotFoundError:  # Imported as scripts.prepare_run from the repository root.
    from scripts.run_input_manifest import (
        DEFAULT_PRECEDENCE_RULE as DEFAULT_PRECEDENCE_RULE,
        default_manifest,
        is_code_scope,
        load_manifest,
        local_input_paths,
        retain_source_releases,
        merge_manifests,
        packet_metadata,
        validate_manifest,
        write_manifest,
    )


try:
    from workflow_policy import PROMPT_TEMPLATES
except ModuleNotFoundError:
    from scripts.workflow_policy import PROMPT_TEMPLATES


try:
    from validation.frontmatter import document_version as _document_version
except ModuleNotFoundError:
    from scripts.validation.frontmatter import document_version as _document_version


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "providers" / "codex" / "model_effort_policy.md"
BUNDLED_AGENTS = ROOT / "providers" / "codex" / "agents"
PLUGIN_MANIFEST = ROOT / ".codex-plugin" / "plugin.json"
SENTRY_FIX_DESIGN_CONTRACT = ROOT / "templates" / "sentry_fix_design_result_contract.json"
SENTRY_NORMALIZED_EVIDENCE_CONTRACT = ROOT / "templates" / "sentry_normalized_evidence_contract.md"
ASSET_MANIFEST_TEMPLATE = ROOT / "templates" / "asset_manifest.json"
SENTRY_FIX_DESIGN_NORMALIZER = ROOT / "scripts" / "normalize_fix_design_result.py"
SENTRY_PLANNING_FINALIZER = ROOT / "scripts" / "finalize_sentry_planning.py"
WORKER_RUNTIME_GUARD = ROOT / "scripts" / "validate_worker_runtime.py"
RUN_INPUTS_FILENAME = "run_inputs.json"
RUN_BUDGET_FILENAME = "run_budget.json"
TERMINAL_STATES = {"awaiting_input", "blocked", "ready_for_implementation", "completed"}
UNINITIALIZED_WORK_RECORD_STATE = (
    "`intake` / `classified` / `in_progress` / `awaiting_input` / `blocked` / `ready_for_implementation` / "
    "`implementation` / `code_review` / `validation` / `handoff` / `completed`"
)
ORPHANED_RUN_RECEIPTS = {
    "asset_manifest.json", "finalization_failure.json", "finalization_packet.json",
    "fix_design_result.json", "handoff_delivery.json", "pre_release_check.json",
    "role_bindings.json", "run_budget.json", "run_inputs.json", "runtime_closure.json", "runtime_dispatches.json",
    "worker_activation_packets.json",
}
SENTRY_AGENTS = (
    "sentry_orchestrator",
    "sentry_current_state_investigator",
    "sentry_dependency_analyst",
    "sentry_repository_integrator",
    "sentry_solution_architect",
    "implementer",
    "reviewer",
    "tester",
    "documenter",
)
GENERIC_AGENTS = (
    "orchestrator",
    "current_state_investigator",
    "dependency_analyst",
    "repository_integrator",
    "solution_architect",
    "implementer",
    "reviewer",
    "tester",
    "documenter",
)
PLAYBOOKS = {path.stem for path in (ROOT / "playbooks").glob("*.md")}
WORKFLOW_OUTCOMES = {
    "technical_spike": {
        "execute_spike": "technical_answer",
        "review_spike": "spike_assessment",
    },
    "feature_delivery": {
        "implementation_planning": "implementation_plan",
        "specification_assessment": "specification_assessment",
        "feature_implementation": "feature_delivery",
    },
    "techops_issue_remediation": {
        "implementation_planning": "implementation_plan",
    },
}
PLAYBOOK_DEFAULT_GOALS = {
    "technical_spike": {
        "workflow_objective": "execute_spike",
        "requested_outcome": "technical_answer",
        "authority": "Technical Spike playbook configuration",
    },
    "feature_delivery": {
        "workflow_objective": "implementation_planning",
        "requested_outcome": "implementation_plan",
        "authority": "Feature Delivery playbook configuration",
    },
    "techops_issue_remediation": {
        "workflow_objective": "implementation_planning",
        "requested_outcome": "implementation_plan",
        "authority": "TechOps Issue Remediation playbook configuration",
    },
}
TECHNICAL_SPIKE_PRIMARY_GOALS = {
    "execute_spike": "Execute technical spike",
    "review_spike": "Review technical spike",
}
CODEX_TOOL_MAPPING = {
    "work_item_read": "supplied context, connected work-item tool, or exec_command",
    "work_record_read": "exec_command",
    "work_record_write": "apply_patch",
    "repository_read": "exec_command",
    "repository_search": "exec_command",
    "history_read": "exec_command",
    "dependency_inspect": "exec_command",
    "security_scan": "configured scanner or connector",
    "artifact_write": "apply_patch",
    "repository_write": "apply_patch",
    "build_run": "exec_command",
    "test_run": "exec_command",
    "diff_review": "exec_command",
    "runtime_observe": "connected runtime tool or exec_command for local runtime evidence",
}


def _table_value(text: str, field: str) -> str | None:
    match = re.search(rf"^\|\s*{re.escape(field)}\s*\|\s*([^|]+?)\s*\|$", text, re.MULTILINE)
    return match.group(1).strip() if match else None


def _baseline_id() -> str:
    match = re.search(r"^baseline_id:\s*(\S+)\s*$", POLICY.read_text(), re.MULTILINE)
    if not match:
        raise ValueError("role_policy_baseline_unavailable")
    return match.group(1)


def _playbook_name(value: str) -> str:
    name = Path(value).stem
    if name in PLAYBOOKS:
        return name
    normalized = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    for path in (ROOT / "playbooks").glob("*.md"):
        title = re.search(r"^title:\s*(.+?)\s*$", path.read_text(), re.MULTILINE)
        title_name = (
            re.sub(r"[^a-z0-9]+", "_", title.group(1).lower()).strip("_")
            if title else ""
        )
        if title_name.removesuffix("_playbook") == normalized or title_name == normalized:
            return path.stem
    raise ValueError(f"unknown_playbook:{value}")


def _playbook_defaults(playbook: str) -> dict[str, object]:
    path = ROOT / "playbooks" / f"{playbook}.md"
    text = path.read_text()
    minutes_match = re.search(r"^default_timebox_minutes:\s*(\d+)\s*$", text, re.MULTILINE)
    success_match = re.search(r"^default_success_criterion:\s*(.+?)\s*$", text, re.MULTILINE)
    if not minutes_match or not success_match:
        raise ValueError(f"playbook_defaults_unavailable:{playbook}")
    success = success_match.group(1).strip()
    if len(success) >= 2 and success[0] == success[-1] == '"':
        success = json.loads(success)
    return {"timebox_minutes": int(minutes_match.group(1)), "success_criterion": success}


def _run_goal_row(
    requested_outcome: str | None,
    source: str = "Current user request",
    authority: str = "Explicit user outcome",
) -> dict[str, str]:
    return {
        "Input ID": "RUN-GOAL-001", "Input or artifact": f"Requested outcome: {requested_outcome}",
        "Source or path": source, "Authority": authority,
        "Classification": "requested outcome", "Expected use": "Validate playbook and objective selection",
        "Status": "Registered",
    }


def _required_spike_bound(value: str | None, field: str) -> str:
    text = str(value or "").strip()
    if not text or text.lower() in {"none", "unknown", "not provided"} or (
        text.startswith("<") and text.endswith(">")
    ):
        raise ValueError(f"run_prompt_incomplete:{field}")
    return text


def _merge_input_rows(
    manifest: dict[str, object], additions: tuple[dict[str, str], ...],
) -> dict[str, object]:
    rows = list(manifest["inputs"])
    by_id = {str(row["Input ID"]): row for row in rows}
    for row in additions:
        if row["Input ID"] in by_id and by_id[row["Input ID"]] != row:
            raise ValueError(f"run_input_manifest_conflicting_input_id:{row['Input ID']}")
        if row["Input ID"] not in by_id:
            rows.append(row)
    return {**manifest, "inputs": rows}


def _spike_bound_rows(
    primary_question: str, success_criterion: str, success_source: str, success_authority: str,
) -> tuple[dict[str, str], ...]:
    return (
        {
            "Input ID": "SPIKE-QUESTION-001", "Input or artifact": f"Primary question: {primary_question}",
            "Source or path": "Current user request", "Authority": "Explicit current-run question",
            "Classification": "technical question", "Expected use": "Bound the Technical Spike investigation",
            "Status": "Registered",
        },
        {
            "Input ID": "SPIKE-SUCCESS-001", "Input or artifact": f"Success criterion: {success_criterion}",
            "Source or path": success_source, "Authority": success_authority,
            "Classification": "success criterion", "Expected use": "Determine whether the question is answered",
            "Status": "Registered",
        },
    )


def _validate_run_goal(
    playbook: str,
    workflow_objective: str | None,
    requested_outcome: str | None,
    supplied_manifest: dict[str, object] | None,
    allow_default_provenance: bool = False,
) -> None:
    if workflow_objective is None and requested_outcome is None:
        return
    if not workflow_objective or not requested_outcome:
        raise ValueError("run_goal_declaration_incomplete")
    outcomes = WORKFLOW_OUTCOMES.get(playbook)
    if not outcomes:
        return
    selected_outcome = outcomes.get(workflow_objective)
    if selected_outcome is None:
        raise ValueError(f"workflow_objective_unsupported:{playbook}:{workflow_objective}")
    if requested_outcome != selected_outcome:
        raise ValueError(
            f"run_goal_conflict:requested_outcome={requested_outcome};"
            f"selected_outcome={selected_outcome};workflow_objective={workflow_objective}"
        )
    rows = supplied_manifest.get("inputs", []) if supplied_manifest else []
    declarations = [row for row in rows if row.get("Input ID") == "RUN-GOAL-001"]
    if len(declarations) != 1:
        if allow_default_provenance and not declarations:
            return
        raise ValueError("run_goal_provenance_missing:RUN-GOAL-001")
    expected = _run_goal_row(requested_outcome)
    if allow_default_provenance and declarations[0].get("Source or path") == "Selected playbook defaults":
        expected = _run_goal_row(requested_outcome, "Selected playbook defaults",
                                 str(PLAYBOOK_DEFAULT_GOALS[playbook]["authority"]))
    if any(declarations[0].get(field) != value for field, value in expected.items()):
        raise ValueError("run_goal_provenance_conflict:RUN-GOAL-001")


def _with_run_goal(
    manifest: dict[str, object], workflow_objective: str | None, requested_outcome: str | None,
    source: str = "Current user request", authority: str = "Explicit user outcome",
) -> dict[str, object]:
    if not workflow_objective:
        return manifest
    additions = (
        _run_goal_row(requested_outcome, source, authority),
        {
            "Input ID": "RUN-GOAL-002", "Input or artifact": f"Workflow objective: {workflow_objective}",
            "Source or path": source, "Authority": authority,
            "Classification": "workflow configuration", "Expected use": "Select worker graph and output contract",
            "Status": "Registered",
        },
    )
    return _merge_input_rows(manifest, additions)


def _with_spike_bounds(
    manifest: dict[str, object], primary_question: str, success_criterion: str,
    success_source: str, success_authority: str,
) -> dict[str, object]:
    return _merge_input_rows(
        manifest, _spike_bound_rows(primary_question, success_criterion, success_source, success_authority)
    )


def _run_budget(started_at: str | None, timebox_minutes: int | None) -> dict[str, object] | None:
    if started_at is None and timebox_minutes is None:
        return None
    if not started_at or timebox_minutes is None:
        raise ValueError("run_budget_declaration_incomplete")
    if timebox_minutes <= 0:
        raise ValueError("run_budget_minutes_invalid")
    try:
        started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("run_budget_started_at_invalid") from error
    if started.tzinfo is None:
        raise ValueError("run_budget_started_at_invalid")
    deadline = started.astimezone(UTC) + timedelta(minutes=timebox_minutes)
    if deadline <= datetime.now(UTC):
        raise ValueError("run_budget_exhausted_before_activation")
    reserve_seconds = min(120, max(1, timebox_minutes * 6))
    return {
        "schema_version": 1,
        "started_at": started.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "deadline_at": deadline.isoformat().replace("+00:00", "Z"),
        "activation_deadline_at": (
            deadline - timedelta(seconds=reserve_seconds)
        ).isoformat().replace("+00:00", "Z"),
        "finalization_reserve_seconds": reserve_seconds,
        "timebox_minutes": timebox_minutes,
        "status": "within_budget",
    }


def _git(repository: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *args], capture_output=True, text=True, check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else "Unknown"


def _repository_row(repository: Path) -> dict[str, str]:
    resolved = repository.resolve()
    revision = _git(resolved, "rev-parse", "HEAD")
    branch = _git(resolved, "branch", "--show-current")
    status = _git(resolved, "status", "--porcelain")
    clean_status = "Unknown" if status == "Unknown" else ("Dirty" if status else "Clean")
    return {
        "Repository role": "Execution repository",
        "Declared path": str(repository),
        "Resolved path": str(resolved),
        "Branch / detached": branch if branch != "Unknown" and branch else "detached",
        "Full revision": revision,
        "Clean status": clean_status,
        "User-selected ref": "Current checkout",
        "Release mapping": "Unknown",
        "Evidence eligibility": (
            "Caveated current-run source evidence; checkout contains uncommitted changes"
            if clean_status == "Dirty" else "Eligible current-run source evidence"
        ),
    }


def resolve_repository_paths(repository: Path) -> tuple[Path, Path]:
    """Keep source evidence in the active checkout and durable records in the main checkout."""
    declared = repository.resolve()
    common = _git(declared, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if common == "Unknown":
        return declared, declared  # Non-Git execution folders remain supported.
    source = Path(_git(declared, "rev-parse", "--show-toplevel"))
    if _git(Path.cwd(), "rev-parse", "--path-format=absolute", "--git-common-dir") == common:
        source = Path(_git(Path.cwd(), "rev-parse", "--show-toplevel"))
    listing = _git(declared, "worktree", "list", "--porcelain")
    first = listing.split("\n\n", 1)[0]
    if not first.startswith("worktree ") or "\nbare" in first:
        raise ValueError("main_execution_repository_unavailable")
    main = Path(first.splitlines()[0].removeprefix("worktree ")).resolve()
    if not main.is_dir() or _git(main, "rev-parse", "--path-format=absolute", "--git-common-dir") != common:
        raise ValueError("main_execution_repository_identity_mismatch")
    return main, source


def _initial_packet(
    artifact_root: Path,
    work_item: str,
    playbook: str,
    workflow_objective: str | None,
    repository_row: dict[str, str],
    runtime_agents: Path | None,
    manifest: dict[str, object],
    manifest_path: Path,
) -> dict[str, object]:
    packet = json.loads((ROOT / "templates" / "finalization_packet.json").read_text())
    # These arrays describe events that happened during the run; template schema
    # placeholders are not evidence and must not survive into a fresh packet.
    for field in ("workers", "worker_results", "synchronization"):
        packet[field] = []
    playbook_path = ROOT / "playbooks" / f"{playbook}.md"
    prompt_path = ROOT / "templates" / PROMPT_TEMPLATES[playbook]
    plugin = json.loads(PLUGIN_MANIFEST.read_text())
    input_manifest = manifest["run_input_manifest"]
    recorded_at = str(manifest.get("run_budget", {}).get("started_at", ""))
    if not recorded_at:
        recorded_at = str(manifest.get("prepared_at") or datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    packet["work_item"]["ID"] = work_item
    packet["work_item"]["Last Updated"] = recorded_at
    packet["inputs"] = list(input_manifest["inputs"])
    packet["run_input_manifest"] = input_manifest
    packet["repositories"] = [repository_row]
    main_repository = Path(str(manifest.get("execution_repository", repository_row["Resolved path"])))
    if str(main_repository) != repository_row["Resolved path"]:
        record_repository = _repository_row(main_repository)
        record_repository["Repository role"] = "Execution repository (durable records only)"
        record_repository["Evidence eligibility"] = "Not source evidence; durable artifact storage only"
        packet["repositories"].append(record_repository)
    if playbook == "techops_issue_remediation":
        packet["techops_checks"] = [
            {"Check": name, "Status": "pending", "Evidence refs": "", "Detail": ""}
            for name in ("issue_scope", "history_reconciliation", "plan_dependencies", "regression_fixture")
        ]
        packet["runtime_audits"] = []
    packet["playbook_selection"]["Selected playbook"] = playbook
    if playbook == "technical_spike" and workflow_objective in TECHNICAL_SPIKE_PRIMARY_GOALS:
        packet["playbook_selection"]["Primary goal"] = TECHNICAL_SPIKE_PRIMARY_GOALS[workflow_objective]
    if playbook == "feature_delivery":
        packet["playbook_selection"]["Primary goal"] = (
            "Specification assessment" if workflow_objective == "specification_assessment" else
            "Feature implementation" if workflow_objective == "feature_implementation" else "Implementation planning"
        )
    packet["identity"].update({
        "Run ID": manifest["run_id"],
        "Lifecycle": manifest.get("lifecycle", packet["identity"]["Lifecycle"]),
        "Requested profile": manifest["execution_profile"],
        "Playbook / version": f"playbooks/{playbook}.md / {_document_version(playbook_path)}",
        "Plugin package / version": f"{plugin['name']} / {plugin['version']}",
        "Provider/runtime configuration": str(runtime_agents) if runtime_agents else "Not provided",
        "Provider configuration source/status": manifest["provider_configuration_source_status"],
        "Prompt template / revision / conformance": (
            f"templates/{prompt_path.name} / {_document_version(prompt_path)} / pending"
        ),
        "Role-policy baseline ID": manifest["baseline_id"],
        "Role binding manifest": str(manifest_path),
        "Provider / model configuration": "Codex / Worker Execution Ledger",
        "Run input manifest": input_manifest["path"],
        "Run input manifest hash": input_manifest["sha256"],
        "Framework commit / status": f"{_git(ROOT, 'rev-parse', 'HEAD')} / {('Dirty' if _git(ROOT, 'status', '--porcelain') else 'Clean')}",
        "Coordinator execution": "active parent session; no dedicated Coordinator worker spawned",
    })
    packet["finalization"]["Durable artifact root"] = str(artifact_root)
    packet["durable_artifacts"] = [
        {
            "Artifact": "Role bindings",
            "Path": str(manifest_path),
            "Status": "Created",
            "Purpose": "Exact worker bindings",
        },
        {
            "Artifact": "Finalization packet",
            "Path": str(artifact_root / "finalization_packet.json"),
            "Status": "Prepared",
            "Purpose": "Structured finalization input",
        },
        {
            "Artifact": "Run input manifest",
            "Path": input_manifest["path"],
            "Status": (
                "Explicit" if input_manifest["status"] == "explicit"
                else "Incomplete; current prompt inputs required"
            ),
            "Purpose": "Immutable current-run context, decisions, and supporting artifacts",
        },
    ]
    if manifest.get("run_budget"):
        packet["durable_artifacts"].append({
            "Artifact": "Run budget", "Path": manifest["run_budget"]["path"], "Status": "Active",
            "Purpose": "End-to-end deadline and terminal budget status",
        })
    if playbook == "technical_spike":
        packet["durable_artifacts"].append({
            "Artifact": "Technical Spike report", "Path": str(artifact_root / "spike_report.md"),
            "Status": "Expected before terminal finalization", "Purpose": "Canonical Technical Spike report",
        })
    if playbook == "feature_delivery":
        packet["durable_artifacts"].append({
            "Artifact": "Asset manifest", "Path": str(artifact_root / "asset_manifest.json"),
            "Status": "Required before planning fan-in", "Purpose": "Complete current-run asset inventory and review gate",
        })
        if workflow_objective == "specification_assessment":
            packet["durable_artifacts"].append({
                "Artifact": "Specification assessment", "Path": str(artifact_root / "specification_assessment.md"),
                "Status": "Expected before terminal finalization", "Purpose": "Story-set coverage and readiness judgment",
            })
    return packet


def _agent_binding(name: str, runtime_agents: Path | None) -> dict[str, str]:
    runtime_file = runtime_agents / f"{name}.toml" if runtime_agents else None
    source = runtime_file if runtime_file and runtime_file.is_file() else BUNDLED_AGENTS / f"{name}.toml"
    if not source.is_file():
        raise ValueError(f"provider_configuration_unavailable:{name}")
    data = tomllib.loads(source.read_text())
    model = data.get("model")
    effort = data.get("model_reasoning_effort")
    if not model or not effort:
        raise ValueError(f"provider_configuration_incomplete:{name}")
    return {
        "agent": name,
        "definition": str(source.resolve()),
        "definition_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "model": model,
        "effort": effort,
        "source": "runtime" if runtime_file and source == runtime_file else "bundled",
    }


def _write_activation_packets(
    artifact_root: Path,
    manifest: dict[str, object],
) -> dict[str, str]:
    worker_contracts = manifest.get("worker_contracts", {})
    contract_by_agent = {
        "sentry_current_state_investigator": worker_contracts.get("evidence_topology"),
        "sentry_repository_integrator": worker_contracts.get("repository_integration"),
        "sentry_solution_architect": worker_contracts.get("fix_design"),
        "current_state_investigator": worker_contracts.get("feature_asset_inventory"),
    }
    if (manifest.get("playbook") in {"techops_issue_remediation", "feature_delivery"}
            or (manifest.get("playbook") == "sentry_issue_remediation"
                and manifest.get("lifecycle") == "remediation")):
        contract_by_agent.update(worker_contracts)
    packets: dict[str, dict[str, object]] = {}
    for agent, binding in manifest["bindings"].items():
        definition = Path(binding["definition"])
        configuration = tomllib.loads(definition.read_text())
        developer_instructions = configuration.get("developer_instructions")
        if not isinstance(developer_instructions, str) or not developer_instructions.strip():
            raise ValueError(f"provider_instructions_unavailable:{agent}")
        packet = {
            "schema_version": 1,
            "framework_package": manifest["framework_package"],
            "required_prefix": "Coordinator initialization: complete",
            "agent": agent,
            "run_id": manifest["run_id"],
            "lifecycle": manifest["lifecycle"],
            "execution_profile": manifest["execution_profile"],
            "finalization_packet": str(artifact_root / "finalization_packet.json"),
            "definition": binding["definition"],
            "definition_sha256": binding["definition_sha256"],
            "model": binding["model"],
            "effort": binding["effort"],
            "source": binding["source"],
            "provider_tool_mapping": manifest["provider_tool_mapping"],
            "run_input_manifest": manifest["run_input_manifest"],
            "coordinator_execution": manifest["coordinator_execution"],
            "repository_instructions": (
                f"Use {manifest['source_checkout']} as the source checkout for repository reads, Git commands, "
                f"changes, and validation. Use {artifact_root} for current-run workflow artifacts. "
                f"Keep every run-created file, including scratch drafts and temporary output, inside {artifact_root}; "
                "do not write them to a separate temporary directory. "
                "The execution_repository in coordinator_execution is the durable-records repository and may "
                "be a different checkout or branch; do not use it as the source checkout when paths differ. "
                "Before source work, verify the source checkout's branch and revision against the prepared run. "
                "Follow applicable instructions already delivered in this worker's current context and honor explicit "
                "instruction-read requirements. Before inspecting, planning or changing code, obtain missing local "
                "AGENTS.md guidance only in the source target directory and its ancestors up to the source checkout root. "
                "Check explicit candidate paths with guarded reads that combine existence checks and content reads; "
                "these exact-path reads need no separate filename listing. Never run a repository-wide AGENTS.md search "
                "with rg, find or globbing. "
                "Keep track of checked directories (including absent files) and fully read instructions in this worker's "
                "current context. When code scope expands, check only new ancestor directories. Reuse complete guidance "
                "already present; repeat a check or read only for changed instructions or paths, missing or truncated "
                "content, or context lost after compaction. A parent or another worker reading a file does not deliver "
                "its contents to this worker; a path or summary alone is not complete instruction delivery. "
                "Issue-only analysis and workflow-artifact work do not initiate additional source-instruction discovery. "
                "Inputs classified as engineering guidance are registered references, not mandatory early asset review. "
                "Defer their contents until an assigned code, test, build, infrastructure or repository question needs them, "
                "including source investigation during planning. Read only relevant sections from the prepared snapshot; "
                "reuse sections already available in this worker's context. Do not read a whole guide merely to inventory "
                "it or repeat it in each payload. Carry Input IDs, purpose and snapshot references forward; record relevant "
                "consumption or deferred-not-needed disposition. Documenter uses accepted findings and references unless "
                "its own task requires a specific section. Product specifications and acceptance evidence remain assets. "
                "Use .thoughts only for framework-flow artifacts such as fan-in/fan-out outputs; it is not a "
                "code, test, infrastructure, project, or repository path. Do not check the artifact root or its "
                ".thoughts parent for AGENTS.md. These instruction files are optional: read only files that exist. "
                "Absence is not a blocker; never add a nonexistent instruction file to required input_paths. "
                "Do not recursively search parent directory trees, the home directory, or unrelated repositories. "
                "Run filename discovery in a separate tool result from content reads or searches so its output can be "
                "audited as names only. Use exact assigned artifact paths; do not search unassigned runs/ archives."
            ),
            "worker_contract": contract_by_agent.get(agent),
            "developer_instructions": developer_instructions.strip() + (
                ("\n\nIn TechOps planning, a focused existing test is permitted only when it can distinguish a "
                 "hypothesis, identify the boundary, or change readiness. Record the hypothesis, discriminating "
                 "outcomes and runner availability before executing it. Honor user execution restrictions. "
                 "Product builds require explicit user authorization; do not run broad suites or repair environments. "
                 if manifest.get("playbook") == "techops_issue_remediation" and agent in {"dependency_analyst", "solution_architect"}
                 else "\n\nIn planning, do not run product builds or tests unless a User input explicitly authorizes "
                 "the operation with Classification execution authorization, Status Approved, and Authorized "
                 "operations test_run or build_run. A delegated objective cannot grant permission. Plan the checks "
                 "without running them when authorization is absent. ") + (
                "\n\nFor ordinary results, the Coordinator joins the provider-returned spawn handle during fan-in. "
                "Do not send a post-spawn message solely to supply that handle or request one from the worker. "
                "A missing worker-authored handle is not a correction condition. Preserve the explicit Sentry Fix "
                "Design handle-delivery protocol when its durable artifact requires the supplied handle. "
                "Every later message remains a dispatch requiring fresh consumption evidence; do not ignore it "
                "or roll its timestamp back to the spawn."
            )),
        }
        packets[agent] = packet
    path = artifact_root / "worker_activation_packets.json"
    path.write_text(json.dumps({"schema_version": 1, "packets": packets}, indent=2, sort_keys=True) + "\n")
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _snapshot_input_files(
    artifact_root: Path, manifest: dict[str, object], *, persist: bool = True,
    input_bytes: dict[str, bytes] | None = None,
) -> dict[str, object]:
    """Capture selected bytes before archival, then publish immutable input snapshots."""
    if input_bytes is None:
        input_bytes = {}
    rows = []
    for original in manifest["inputs"]:
        row = dict(original)
        multiple = bool(row.get("paths"))
        sources = [str(path) for path in local_input_paths(row)]
        targets, hashes = [], {}
        for locator in sources:
            source = Path(locator)
            expected = row.get("sha256_by_path", {}).get(locator) if multiple else row.get("sha256")
            if locator not in input_bytes and not source.is_file():
                if expected:
                    raise ValueError(f"run_input_manifest_hashed_file_unavailable:{row['Input ID']}")
                targets.append(locator)
                continue
            data = input_bytes[locator] if locator in input_bytes else source.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            if expected != digest:
                raise ValueError(f"run_input_manifest_hash_mismatch:{row['Input ID']}")
            target = (artifact_root / "input_snapshots" / digest / source.name).resolve()
            if target.exists() and target.read_bytes() != data:
                raise ValueError(f"input_snapshot_conflict:{row['Input ID']}")
            input_bytes[locator] = data
            if persist and not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            targets.append(str(target))
            hashes[str(target)] = digest
        if multiple:
            row.setdefault("Original source paths", sources)
            row["paths"], row["sha256_by_path"] = targets, hashes
        elif hashes:
            row.setdefault("Original source path", sources[0])
            row["path"] = targets[0]
        rows.append(row)
    return {**manifest, "inputs": rows}


def _prepare_run_inputs(
    artifact_root: Path,
    work_item: str,
    playbook: str,
    execution_repository: Path,
    supplied_path: Path | None,
    continuation: bool,
    validated_supplied: dict[str, object] | None = None,
    input_bytes: dict[str, bytes] | None = None,
) -> tuple[dict[str, object], Path]:
    destination = artifact_root / RUN_INPUTS_FILENAME
    if continuation and destination.is_file():
        current = load_manifest(destination, explicit=False)
        if supplied_path or validated_supplied is not None:
            supplied = validated_supplied or load_manifest(supplied_path, explicit=True)
            supplied = _snapshot_input_files(artifact_root, supplied, input_bytes=input_bytes)
            current = merge_manifests(current, supplied)
            write_manifest(destination, current)
        return load_manifest(destination, explicit=False), destination
    if supplied_path or validated_supplied is not None:
        source = validated_supplied or load_manifest(supplied_path, explicit=True)
    else:
        source = default_manifest(work_item, playbook, execution_repository.resolve())
    source = _snapshot_input_files(artifact_root, source, input_bytes=input_bytes)
    return write_manifest(destination, source), destination


def _verify_rejected_delivery_candidate(artifact_root: Path, prior: dict, failure: dict, ledger: dict,
                                        *, source_checkout: Path | None = None,
                                        source_already_present: bool = False) -> dict:
    """Authenticate a rejected Implementer's existing changes without accepting its result."""
    try:
        from runtime_checks import trace_errors, trace_identity_errors, techops_conformance_errors
        from recovery_candidate import replay_candidate, verify_candidate, verify_checkout_snapshot, verify_edit_authorization
    except ModuleNotFoundError:
        from scripts.runtime_checks import trace_errors, trace_identity_errors, techops_conformance_errors
        from scripts.recovery_candidate import replay_candidate, verify_candidate, verify_checkout_snapshot, verify_edit_authorization
    run_id = prior["identity"]["Run ID"]
    matches = []
    for path in artifact_root.glob("trace*.json"):
        try:
            trace = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if trace.get("run_id") == run_id and trace.get("worker") == "implementer" and trace.get("audit", {}).get("status") == "rejected":
            matches.append((path, trace))
    if len(matches) != 1:
        raise ValueError("candidate_rejected_trace_required")
    path, trace = matches[0]
    handle, thread = trace["spawn"]["provider_handle"], trace["thread_id"]
    if ledger.get("thread_mappings", {}).get(handle) != thread:
        raise ValueError("candidate_worker_mapping_mismatch")
    identity_errors = trace_identity_errors(trace, artifact_root, "implementer", handle, thread)
    runtime_errors = trace_errors(trace, require_freshness=True)
    allowed_errors = {identity_errors[0], "worker_fan_in_rejected"} if len(identity_errors) == 1 else set()
    if source_already_present:
        allowed_errors.add("forbidden_context_reference:archived_artifact")
        receipt = ledger.get("rejected_results", {}).get("implementer", {})
        if (Path(receipt.get("trace", "")).resolve() != path.resolve() or receipt.get("run_id") != run_id
                or receipt.get("sha256") != hashlib.sha256(path.read_bytes()).hexdigest()
                or receipt.get("Provider handle") != handle or receipt.get("Last dispatch at") != trace.get("last_dispatch_at")):
            raise ValueError("candidate_rejected_receipt_invalid")
    if (len(identity_errors) != 1 or not identity_errors[0].startswith("worker_result_contract_invalid:implementer:")
            or set(runtime_errors) != allowed_errors or trace.get("audit", {}).get("errors") != runtime_errors
            or (not source_already_present and not any(identity_errors[0] in error for error in failure.get("historical_errors", [])))):
        raise ValueError("candidate_worker_trace_not_format_only")
    bindings = json.loads((artifact_root / "role_bindings.json").read_text())
    conformance = artifact_root / "implementation_conformance.json"
    if techops_conformance_errors(conformance, run_id, prior["reentry"]["Approved plan SHA256"]):
        raise ValueError("candidate_conformance_invalid")
    files = [row["path"] for row in json.loads(conformance.read_text())["files"]]
    recorded_source = next(row for row in prior["repositories"] if row["Repository role"] == "Execution repository")
    repository = Path(recorded_source["Resolved path"] if source_already_present else bindings["execution_repository"]).resolve()
    revision = recorded_source["Full revision"]
    advanced_source = source_checkout is not None and source_checkout.resolve() != repository
    if advanced_source:
        source_checkout = source_checkout.resolve()
        common = _git(repository, "rev-parse", "--path-format=absolute", "--git-common-dir")
        if (common == "Unknown" or _git(source_checkout, "rev-parse", "--path-format=absolute", "--git-common-dir") != common
                or _git(source_checkout, "rev-parse", "HEAD") != revision
                or (not source_already_present and _git(source_checkout, "-c", "core.fsmonitor=false", "status", "--porcelain") != "")):
            raise ValueError("candidate_recovery_source_checkout_invalid")
    session = Path(trace["trace_retrieval"])
    parent = bindings["parent_context"]
    verify_edit_authorization(Path(parent["provider_session"]), parent["parent_thread_id"], session, thread,
        bindings["runtime_evidence"]["run_started_at"], Path(bindings["worker_runtime_guard"]),
        artifact_root / "finalization_packet.json", handle, repository, files)
    if source_already_present:
        if not advanced_source:
            raise ValueError("candidate_recovery_source_checkout_invalid")
        hashes = verify_candidate(repository, revision, session, thread, files)
        verify_checkout_snapshot(source_checkout, revision, hashes)
        contents = {name: (source_checkout / name).read_bytes() for name in hashes}
    elif advanced_source:
        contents = replay_candidate(source_checkout, revision, session, thread, repository, files)
        hashes = {name: hashlib.sha256(data).hexdigest() for name, data in contents.items()}
    else:
        contents = None
        hashes = verify_candidate(repository, revision, session, thread, files)
    result = {"prior_run_id": run_id, "status": "unaccepted", "trace_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
              "baseline_revision": revision, "files": hashes}
    if contents is not None:
        result["_contents"] = contents
    if source_already_present:
        result["source_already_present"] = True
    return result



def _continued_candidate(artifact_root: Path, bindings: dict) -> dict | None:
    """Keep the existing unaccepted snapshot binding when a run continues."""
    candidate = bindings.get("recovered_candidate")
    if candidate is None:
        return None
    try:
        bundle = bindings["activation_packet_bundle"]
        bundle_path = Path(bundle["path"]).resolve()
        if (not isinstance(candidate, dict) or candidate.get("status") != "unaccepted"
                or bundle_path.parent != artifact_root.resolve()
                or hashlib.sha256(bundle_path.read_bytes()).hexdigest() != bundle["sha256"]
                or bindings["worker_contracts"]["implementer"].get("recovered_candidate") != candidate
                or json.loads(bundle_path.read_text())["packets"]["implementer"]["worker_contract"].get("recovered_candidate") != candidate):
            raise ValueError("continuation_candidate_binding_invalid")
        return candidate
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise ValueError("continuation_candidate_binding_invalid") from error


def _accepted_implementer_candidate(artifact_root: Path, prior: dict, source_checkout: Path | None = None) -> dict:
    """Recover snapshot provenance only from a verified, accepted current-run Implementer dispatch."""
    try:
        from planning_contracts import _worker_runtime_audit_errors
        from merge_techops_result import merged_result_errors
        from runtime_checks import _verified_dispatch_content
    except ModuleNotFoundError:
        from scripts.planning_contracts import _worker_runtime_audit_errors
        from scripts.merge_techops_result import merged_result_errors
        from scripts.runtime_checks import _verified_dispatch_content
    bindings = json.loads((artifact_root / "role_bindings.json").read_text())
    results = [row for row in prior.get("worker_results", [])
               if row.get("Worker") == "implement" and row.get("Outcome") == "complete"]
    audits = prior.get("runtime_audits", [])
    matched = [row for row in audits if row.get("Worker") == "implement"]
    implementation = {**prior, "worker_results": results, "runtime_audits": matched, "terminal_observations": []}
    if (len(results) != 1 or len(matched) != 1
            or _worker_runtime_audit_errors(implementation, artifact_root / "finalization_packet.json", {"implement"})
            or merged_result_errors(implementation, bindings, artifact_root)):
        raise ValueError("candidate_accepted_implementer_unverified")
    trace_path = Path(matched[0]["Trace path"]).resolve()
    if trace_path.parent != artifact_root.resolve():
        raise ValueError("candidate_accepted_implementer_unverified")
    trace = json.loads(trace_path.read_text())
    content = _verified_dispatch_content(trace)
    if not content:
        raise ValueError("candidate_accepted_implementer_unverified")
    packet = json.loads(content.split("\n", 2)[1])
    if (source_checkout is not None
            and Path(packet["coordinator_execution"]["source_checkout"]).resolve() != source_checkout.resolve()):
        raise ValueError("candidate_recovery_source_checkout_invalid")
    candidate = packet.get("worker_contract", {}).get("recovered_candidate")
    if not isinstance(candidate, dict) or candidate.get("status") != "unaccepted":
        raise ValueError("candidate_recovery_binding_invalid")
    return candidate


def _recover_preserved_candidate(artifact_root: Path, prior: dict, source_checkout: Path, *,
                                 candidate_override: dict | None = None, check_checkout: bool = True) -> dict:
    """Revalidate an unaccepted candidate from its original recorded edits."""
    try:
        from recovery_candidate import replay_candidate, verify_candidate, verify_checkout_snapshot, verify_edit_authorization
    except ModuleNotFoundError:
        from scripts.recovery_candidate import replay_candidate, verify_candidate, verify_checkout_snapshot, verify_edit_authorization
    bindings = json.loads((artifact_root / "role_bindings.json").read_text())
    candidate = bindings["recovered_candidate"] if candidate_override is None else candidate_override
    bundle = bindings["activation_packet_bundle"]
    bundle_path = Path(bundle["path"])
    if (bindings.get("run_id") != prior["identity"]["Run ID"] or candidate.get("status") != "unaccepted"
            or bundle_path != artifact_root / "worker_activation_packets.json"
            or hashlib.sha256(bundle_path.read_bytes()).hexdigest() != bundle["sha256"]):
        raise ValueError("candidate_recovery_binding_invalid")
    if candidate_override is None:
        if (bindings["worker_contracts"]["implementer"].get("recovered_candidate") != candidate
                or json.loads(bundle_path.read_text())["packets"]["implementer"]["worker_contract"].get("recovered_candidate") != candidate):
            raise ValueError("candidate_recovery_binding_invalid")
    elif _accepted_implementer_candidate(artifact_root, prior, source_checkout) != candidate:
        raise ValueError("candidate_recovery_binding_invalid")
    if candidate_override is None and source_checkout.resolve() != Path(bindings["source_checkout"]).resolve():
        raise ValueError("candidate_recovery_source_checkout_invalid")
    return _recover_candidate_archive(artifact_root, prior, source_checkout, candidate,
                                      visited=set(), check_checkout=candidate_override is None and check_checkout)


def _recover_candidate_archive(artifact_root: Path, prior: dict, source_checkout: Path, candidate: dict, *,
                               visited: set[str], check_checkout: bool) -> dict:
    """Reconstruct each archived generation from its recorded source edits."""
    try:
        from recovery_candidate import replay_candidate, verify_candidate, verify_checkout_snapshot, verify_edit_authorization
    except ModuleNotFoundError:
        from scripts.recovery_candidate import replay_candidate, verify_candidate, verify_checkout_snapshot, verify_edit_authorization
    run_id = candidate["prior_run_id"]
    if not isinstance(run_id, str) or not run_id or Path(run_id).name != run_id:
        raise ValueError("candidate_recovery_prior_archive_invalid")
    archive = artifact_root / "runs" / run_id
    manifest = json.loads((archive / "archive_manifest.json").read_text())
    if manifest.get("run_id") != run_id:
        raise ValueError("candidate_recovery_prior_archive_invalid")
    def archived(name):
        rows = [row for row in manifest["files"] if row.get("path") == name]
        if len(rows) != 1:
            raise ValueError("candidate_recovery_archive_evidence_invalid")
        path = (archive / rows[0]["snapshot"]).resolve()
        if not path.is_relative_to((artifact_root / "runs").resolve()):
            raise ValueError("candidate_recovery_archive_evidence_invalid")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != rows[0]["sha256"]:
            raise ValueError("candidate_recovery_archive_evidence_invalid")
        return data
    trace_rows = [row for row in manifest["files"] if isinstance(row.get("path"), str)
                  and Path(row["path"]).name == row["path"] and row["path"].endswith(".json")
                  and row.get("sha256") == candidate["trace_sha256"]]
    if len(trace_rows) != 1:
        raise ValueError("candidate_recovery_archive_evidence_invalid")
    trace = json.loads(archived(trace_rows[0]["path"]))
    original = json.loads(archived("role_bindings.json"))
    original_packet = json.loads(archived("finalization_packet.json"))
    files, revision = candidate["files"], candidate["baseline_revision"]
    repository = Path(original.get("source_checkout", original["execution_repository"])).resolve()
    common = _git(repository, "rev-parse", "--path-format=absolute", "--git-common-dir")
    reviewed_checkout_candidate = (
        candidate.get("source_already_present") is True and trace.get("worker") == "reviewer"
    )
    if reviewed_checkout_candidate:
        try:
            from review_evidence import (
                _candidate_fields, plan_review_coverage_errors, review_candidate_metadata_errors,
                review_report_errors,
            )
        except ModuleNotFoundError:
            from scripts.review_evidence import (
                _candidate_fields, plan_review_coverage_errors, review_candidate_metadata_errors,
                review_report_errors,
            )
        review_trace = trace
        review_path = archived("code_review.md")
        review_text = review_path.decode()
        review_audits = [row for row in original_packet.get("runtime_audits", [])
                         if row.get("Worker") == "review"]
        review_results = [row for row in original_packet.get("worker_results", [])
                          if row.get("Worker") == "review" and row.get("Outcome") == "complete"]
        review_audit = review_audits[0] if len(review_audits) == 1 else {}
        review_observation = review_trace.get("status_observation", {})
        receipts = json.loads(archived("activation_receipts.json"))
        if not isinstance(receipts, dict):
            raise ValueError("candidate_recovery_archive_evidence_invalid")

        def archived_dispatch_packet(saved_trace: dict, agent: str) -> dict:
            spawn = saved_trace.get("spawn", {})
            if not isinstance(spawn, dict):
                raise ValueError("candidate_recovery_archive_evidence_invalid")
            dispatch_file = spawn.get("dispatch_file")
            if not isinstance(dispatch_file, str) or not dispatch_file:
                raise ValueError("candidate_recovery_archive_evidence_invalid")
            dispatch_path = Path(dispatch_file).resolve()
            if dispatch_path.parent != artifact_root.resolve():
                raise ValueError("candidate_recovery_archive_evidence_invalid")
            raw = archived(dispatch_path.name)
            digest = hashlib.sha256(raw).hexdigest()
            receipt = receipts.get(dispatch_path.name, {})
            if (not isinstance(receipt, dict) or digest != spawn.get("dispatch_file_sha256")
                    or receipt.get("sha256") != digest
                    or receipt.get("run_id") != run_id or receipt.get("agent") != agent):
                raise ValueError("candidate_recovery_archive_evidence_invalid")
            try:
                packet = json.loads(raw.decode().split("\n", 2)[1])
                if not isinstance(packet, dict):
                    raise ValueError("dispatch packet must be an object")
                execution = packet.get("coordinator_execution", {})
                if not isinstance(execution, dict):
                    raise ValueError("coordinator execution must be an object")
                checkout = Path(execution.get("source_checkout", "")).resolve()
            except (IndexError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
                raise ValueError("candidate_recovery_archive_evidence_invalid") from None
            if packet.get("run_id") != run_id or packet.get("agent") != agent or checkout != source_checkout.resolve():
                raise ValueError("candidate_recovery_archive_evidence_invalid")
            return packet

        review_fields, review_field_errors = _candidate_fields(review_text)
        review_trace_path = review_audit.get("Trace path")
        if not isinstance(review_trace_path, str) or not review_trace_path:
            raise ValueError("candidate_recovery_archive_evidence_invalid")
        review_errors = [
            *review_field_errors,
            *review_candidate_metadata_errors(review_text, expected_repository=source_checkout),
            *review_report_errors(review_text, require_accepted=True),
            *plan_review_coverage_errors(archived("implementation_plan.md").decode(), review_text),
        ]
        if (len(review_results) != 1 or len(review_audits) != 1 or review_errors
                or review_fields.get("Base revision") != revision
                or review_trace.get("run_id") != run_id or review_trace.get("worker") != "reviewer"
                or review_trace.get("audit", {}).get("status") != "passed"
                or review_trace.get("spawn", {}).get("agent") != "reviewer"
                or review_trace.get("spawn", {}).get("thread_id") != review_trace.get("thread_id")
                or review_trace.get("result_artifact", {}).get("output_sha256")
                    != hashlib.sha256(review_text.encode()).hexdigest()
                or Path(review_trace_path).resolve().parent != artifact_root.resolve()
                or Path(review_trace_path).name != trace_rows[0]["path"]
                or review_audit.get("Provider status") != "completed"
                or review_audit.get("Provider handle") != review_trace.get("spawn", {}).get("provider_handle")
                or review_audit.get("Thread ID") != review_trace.get("thread_id")
                or review_audit.get("Last dispatch at") != review_trace.get("last_dispatch_at")
                or review_observation.get("Provider handle") != review_audit.get("Provider handle")
                or review_observation.get("Thread ID") != review_audit.get("Thread ID")
                or review_observation.get("Last dispatch at") != review_audit.get("Last dispatch at")):
            raise ValueError("candidate_recovery_archive_evidence_invalid")
        archived_dispatch_packet(review_trace, "reviewer")
        implement_audits = [row for row in original_packet.get("runtime_audits", [])
                            if row.get("Worker") == "implement"]
        implement_results = [row for row in original_packet.get("worker_results", [])
                             if row.get("Worker") == "implement" and row.get("Outcome") == "complete"]
        implement_audit = implement_audits[0] if len(implement_audits) == 1 else {}
        implement_trace_path = implement_audit.get("Trace path")
        if not isinstance(implement_trace_path, str) or not implement_trace_path:
            raise ValueError("candidate_recovery_archive_evidence_invalid")
        implement_path = Path(implement_trace_path).resolve()
        implement_rows = [row for row in manifest["files"] if row.get("path") == implement_path.name
                          and Path(str(row.get("path", ""))).name == row.get("path")
                          and str(row.get("path", "")).endswith(".json")]
        if (len(implement_results) != 1 or len(implement_audits) != 1
                or implement_path.parent != artifact_root.resolve() or len(implement_rows) != 1):
            raise ValueError("candidate_recovery_archive_evidence_invalid")
        trace = json.loads(archived(implement_rows[0]["path"]))
        implement_observation = trace.get("status_observation", {})
        if (trace.get("run_id") != run_id or trace.get("worker") not in {"implementer", "implement"}
                or trace.get("audit", {}).get("status") != "passed"
                or trace.get("spawn", {}).get("agent") != "implementer"
                or trace.get("spawn", {}).get("thread_id") != trace.get("thread_id")
                or implement_audit.get("Provider status") != "completed"
                or implement_audit.get("Provider handle") != trace.get("spawn", {}).get("provider_handle")
                or implement_audit.get("Thread ID") != trace.get("thread_id")
                or implement_audit.get("Last dispatch at") != trace.get("last_dispatch_at")
                or implement_observation.get("Provider handle") != implement_audit.get("Provider handle")
                or implement_observation.get("Thread ID") != implement_audit.get("Thread ID")
                or implement_observation.get("Last dispatch at") != implement_audit.get("Last dispatch at")):
            raise ValueError("candidate_recovery_archive_evidence_invalid")
        archived_dispatch_packet(trace, "implementer")
    if (trace.get("run_id") != run_id or trace.get("worker") not in {"implementer", "implement"}
            or trace.get("audit", {}).get("status") not in (
                {"rejected", "passed"} if candidate.get("base_candidate") or reviewed_checkout_candidate else {"rejected"})
            or original_packet.get("identity", {}).get("Run ID") != run_id
            or original_packet.get("reentry", {}).get("Approved plan SHA256") != prior["reentry"]["Approved plan SHA256"]
            or common == "Unknown" or common != _git(source_checkout, "rev-parse", "--path-format=absolute", "--git-common-dir")):
        raise ValueError("candidate_recovery_archive_evidence_invalid")
    session = Path(trace["trace_retrieval"])
    parent = original["parent_context"]
    snapshot_run_id = candidate.get("snapshot_run_id", run_id)
    if not isinstance(snapshot_run_id, str) or not snapshot_run_id or Path(snapshot_run_id).name != snapshot_run_id:
        raise ValueError("candidate_recovery_snapshot_invalid")
    snapshot_root = artifact_root / ("recovery_candidate." + re.sub(r"[^A-Za-z0-9._-]", "_", snapshot_run_id))
    expected_snapshots = {str(snapshot_root / name): digest for name, digest in files.items()}
    if (snapshot_root.is_symlink() or candidate.get("snapshot_files") != expected_snapshots
            or any((snapshot_root / Path(*Path(name).parts[:i])).is_symlink()
                   for name in files for i in range(1, len(Path(name).parts) + 1))):
        raise ValueError("candidate_recovery_snapshot_invalid")
    base = candidate.get("base_candidate")
    if base is not None:
        try:
            from recovery_candidate import replay_followup_candidate
        except ModuleNotFoundError:
            from scripts.recovery_candidate import replay_followup_candidate
        repair = original_packet.get("activation_repairs", {}).get("implementer", {})
        audits = [row for row in original_packet["runtime_audits"] if row.get("Worker") == "implement"]
        accepted_edit = trace.get("audit", {}).get("status") == "passed"
        unmerged = candidate.get("unmerged_parent_failure") is True
        rejected_correction = candidate.get("rejected_correction") is True
        results = [row for row in original_packet.get("worker_results", [])
                   if row.get("Worker") == "implement" and row.get("Outcome") == "complete"]
        if rejected_correction:
            failure = json.loads(archived("finalization_failure.json"))
            closure = json.loads(archived("runtime_closure.json"))
            ledger = json.loads(archived("runtime_dispatches.json"))
            receipt = ledger.get("rejected_results", {}).get("implementer", {})
            first_path = Path(receipt.get("trace", ""))
            if first_path.parent.resolve() != artifact_root.resolve():
                raise ValueError("candidate_followup_trace_unverified")
            first_raw = archived(first_path.name)
            first = json.loads(first_raw)
            if not (not accepted_edit and not audits and not original_packet.get("workers")
                    and not original_packet.get("worker_results") and not original_packet.get("runtime_audits")
                    and hashlib.sha256(archived("finalization_packet.json")).hexdigest()
                        == failure.get("snapshot_sha256") == failure.get("packet_sha256")
                    and first.get("run_id") == run_id and first.get("worker") == "implementer"
                    and first.get("audit", {}).get("status") == "rejected"
                    and first.get("spawn", {}).get("provider_handle") == receipt.get("Provider handle")
                    and first.get("thread_id") == ledger.get("thread_mappings", {}).get(receipt.get("Provider handle"))
                    and first.get("last_dispatch_at") == receipt.get("Last dispatch at")
                    and _corrected_rejection_errors(original_packet, failure, ledger, closure, trace,
                                                    hashlib.sha256(first_raw).hexdigest())):
                raise ValueError("candidate_followup_trace_unverified")
        elif unmerged:
            failure = json.loads(archived("finalization_failure.json"))
            closure = json.loads(archived("runtime_closure.json"))
            ledger = json.loads(archived("runtime_dispatches.json"))
            observations = closure.get("terminal_observations", [])
            errors = failure.get("errors", [])
            if not (accepted_edit and not audits and not original_packet.get("workers")
                    and not original_packet.get("worker_results") and not original_packet.get("runtime_audits")
                    and failure.get("status") == "failed" and failure.get("stage") == "workflow"
                    and failure.get("reported_by") == "Coordinator" and failure.get("runtime_closure") == "terminal"
                    and failure.get("run_id") == run_id and len(errors) == 1
                    and "parent_context_nonconformant:" in str(errors[0])
                    and hashlib.sha256(archived("finalization_packet.json")).hexdigest()
                        == failure.get("snapshot_sha256") == failure.get("packet_sha256")
                    and len(observations) == 1 and observations[0].get("Provider status") == "completed"
                    and observations[0].get("Provider handle") == trace["spawn"]["provider_handle"]
                    and observations[0].get("Thread ID") == trace.get("thread_id")
                    and observations[0].get("Last dispatch at") == trace.get("last_dispatch_at")
                    and bool(trace.get("last_dispatch_at"))
                    and ledger.get("thread_mappings", {}).get(trace["spawn"]["provider_handle"]) == trace.get("thread_id")
                    and ledger.get("timing", {}).get("open_worker_intervals") == 0):
                raise ValueError("candidate_followup_trace_unverified")
        elif (len(audits) != 1 or (accepted_edit and len(results) != 1) or (not accepted_edit and (repair.get("Attempt") != 1
                or repair.get("Rejected trace SHA256") != candidate["trace_sha256"]
                or repair.get("Provider handle") != trace["spawn"]["provider_handle"]
                or repair.get("Last dispatch at") != trace.get("last_dispatch_at")))):
            raise ValueError("candidate_followup_trace_unverified")
        receipts = json.loads(archived("activation_receipts.json"))
        def dispatch_for(saved_trace):
            dispatch_path = Path(saved_trace["spawn"]["dispatch_file"])
            if dispatch_path.parent.resolve() != artifact_root.resolve():
                raise ValueError("candidate_followup_binding_invalid")
            raw = archived(dispatch_path.name)
            digest = hashlib.sha256(raw).hexdigest()
            receipt = receipts[dispatch_path.name]
            if (digest != saved_trace["spawn"]["dispatch_file_sha256"] or receipt.get("sha256") != digest
                    or receipt.get("run_id") != run_id or receipt.get("agent") != "implementer"):
                raise ValueError("candidate_followup_binding_invalid")
            packet = json.loads(raw.decode().split("\n", 2)[1])
            if (packet.get("run_id") != run_id or packet.get("agent") != "implementer"
                    or packet.get("worker_contract", {}).get("recovered_candidate") != base
                    or Path(packet["coordinator_execution"]["source_checkout"]).resolve() != source_checkout.resolve()):
                raise ValueError("candidate_followup_binding_invalid")
            return packet
        dispatch = dispatch_for(trace)
        if not unmerged and not rejected_correction:
            accepted_path = Path(audits[0]["Trace path"])
            if accepted_path.parent.resolve() != artifact_root.resolve():
                raise ValueError("candidate_followup_trace_unverified")
            accepted = json.loads(archived(accepted_path.name))
            if (accepted.get("run_id") != run_id or accepted.get("worker") not in {"implementer", "implement"}
                    or accepted.get("audit", {}).get("status") != "passed"
                    or (accepted_edit and (accepted != trace or audits[0].get("Provider handle") != trace["spawn"]["provider_handle"]
                        or audits[0].get("Thread ID") != trace.get("thread_id")
                        or audits[0].get("Last dispatch at") != trace.get("last_dispatch_at")))
                    or (not accepted_edit and accepted.get("spawn", {}).get("dispatch_file_sha256") != repair.get("Corrected dispatch SHA256"))):
                raise ValueError("candidate_followup_trace_unverified")
            dispatch_for(accepted)
        if (base.get("prior_run_id") in visited or candidate.get("status") != "unaccepted"
                or base.get("baseline_revision") != revision):
            raise ValueError("candidate_recovery_prior_archive_invalid")
        original_candidate = _recover_candidate_archive(artifact_root, prior, source_checkout, base,
                                                         visited=visited | {run_id}, check_checkout=False)
        contents, touched = replay_followup_candidate(source_checkout, session, trace["thread_id"],
                                                       original_candidate["_contents"])
        verify_edit_authorization(Path(parent["provider_session"]), parent["parent_thread_id"], session, trace["thread_id"],
            original["runtime_evidence"]["run_started_at"], Path(dispatch["worker_contract"]["before_source_change_guard"]),
            artifact_root / "finalization_packet.json", trace["spawn"]["provider_handle"], source_checkout, touched)
        if set(contents) != set(files):
            raise ValueError("candidate_recovery_snapshot_invalid")
        if check_checkout:
            verify_checkout_snapshot(source_checkout, revision, files)
    elif not reviewed_checkout_candidate:
        verify_edit_authorization(Path(parent["provider_session"]), parent["parent_thread_id"], session, trace["thread_id"],
            original["runtime_evidence"]["run_started_at"], Path(original["worker_runtime_guard"]),
            artifact_root / "finalization_packet.json", trace["spawn"]["provider_handle"], repository, list(files))
    if base is None and candidate.get("source_already_present") is True:
        if reviewed_checkout_candidate:
            if check_checkout:
                verify_checkout_snapshot(source_checkout, revision, files)
                contents = {name: (source_checkout / name).read_bytes() for name in files}
            else:
                contents = {name: (snapshot_root / name).read_bytes() for name in files}
        else:
            hashes = verify_candidate(repository, revision, session, trace["thread_id"], list(files))
            if hashes != files:
                raise ValueError("candidate_recovery_snapshot_invalid")
            if check_checkout:
                verify_checkout_snapshot(source_checkout, revision, hashes)
                contents = {name: (source_checkout / name).read_bytes() for name in hashes}
            else:
                contents = {name: (snapshot_root / name).read_bytes() for name in hashes}
    elif base is None:
        contents = replay_candidate(source_checkout, revision, session, trace["thread_id"], repository, list(files))
    for name, data in contents.items():
        path = snapshot_root / name
        if (any((snapshot_root / Path(*Path(name).parts[:i])).is_symlink() for i in range(1, len(Path(name).parts) + 1))
                or hashlib.sha256(data).hexdigest() != files[name] or path.read_bytes() != data):
            raise ValueError("candidate_recovery_snapshot_invalid")
    result = {key: candidate[key] for key in ("prior_run_id", "status", "trace_sha256", "baseline_revision", "files")} | {"_contents": contents}
    if candidate.get("source_already_present") is True:
        result["source_already_present"] = True
    if base is not None:
        result["base_candidate"] = base
    if candidate.get("unmerged_parent_failure") is True:
        result["unmerged_parent_failure"] = True
    if candidate.get("rejected_correction") is True:
        result["rejected_correction"] = True
    return result


def _recover_accepted_candidate(artifact_root: Path, prior: dict, source_checkout: Path) -> dict:
    """Prove a failed run's candidate from its accepted snapshot and guarded native follow-up."""
    try:
        from recovery_candidate import replay_followup_candidate, verify_checkout_snapshot, verify_edit_authorization
        from runtime_checks import _verified_dispatch_content
    except ModuleNotFoundError:
        from scripts.recovery_candidate import replay_followup_candidate, verify_checkout_snapshot, verify_edit_authorization
        from scripts.runtime_checks import _verified_dispatch_content
    bindings = json.loads((artifact_root / "role_bindings.json").read_text())
    candidate = _accepted_implementer_candidate(artifact_root, prior, source_checkout)
    original = _recover_preserved_candidate(artifact_root, prior, source_checkout, candidate_override=candidate)
    repair = prior.get("activation_repairs", {}).get("implementer", {})
    digest = repair.get("Rejected trace SHA256")
    paths = [path for path in artifact_root.glob("trace*.json")
             if path.is_file() and not path.is_symlink() and hashlib.sha256(path.read_bytes()).hexdigest() == digest]
    if len(paths) != 1 or repair.get("Attempt") != 1:
        raise ValueError("candidate_followup_trace_unverified")
    trace = json.loads(paths[0].read_text())
    content = _verified_dispatch_content(trace)
    accepted_audit = next(row for row in prior["runtime_audits"] if row.get("Worker") == "implement")
    accepted_trace = json.loads(Path(accepted_audit["Trace path"]).read_text())
    if (not content or trace.get("run_id") != prior["identity"]["Run ID"]
            or trace.get("worker") != "implementer" or trace.get("audit", {}).get("status") != "rejected"
            or trace.get("spawn", {}).get("provider_handle") != repair.get("Provider handle")
            or trace.get("last_dispatch_at") != repair.get("Last dispatch at")
            or accepted_trace.get("spawn", {}).get("dispatch_file_sha256") != repair.get("Corrected dispatch SHA256")):
        raise ValueError("candidate_followup_trace_unverified")
    dispatch = json.loads(content.split("\n", 2)[1])
    if (dispatch.get("worker_contract", {}).get("recovered_candidate") != candidate
            or Path(dispatch["coordinator_execution"]["source_checkout"]).resolve() != source_checkout.resolve()):
        raise ValueError("candidate_followup_binding_invalid")
    session = Path(trace["trace_retrieval"])
    contents, touched = replay_followup_candidate(source_checkout, session, trace["thread_id"], original["_contents"])
    parent = bindings["parent_context"]
    verify_edit_authorization(Path(parent["provider_session"]), parent["parent_thread_id"], session, trace["thread_id"],
        bindings["runtime_evidence"]["run_started_at"], Path(dispatch["worker_contract"]["before_source_change_guard"]),
        artifact_root / "finalization_packet.json", trace["spawn"]["provider_handle"], source_checkout, touched)
    hashes = {name: hashlib.sha256(data).hexdigest() for name, data in contents.items()}
    verify_checkout_snapshot(source_checkout, candidate["baseline_revision"], hashes)
    return {"prior_run_id": prior["identity"]["Run ID"], "status": "unaccepted", "trace_sha256": digest,
            "baseline_revision": candidate["baseline_revision"], "files": hashes, "source_already_present": True,
            "base_candidate": candidate, "_contents": contents}



def _recover_current_accepted_candidate(artifact_root: Path, prior: dict, source_checkout: Path) -> dict:
    """Reconstruct a guarded accepted edit on top of its verified unaccepted snapshot."""
    try:
        from recovery_candidate import replay_followup_candidate, verify_checkout_snapshot, verify_edit_authorization
        from runtime_checks import _verified_dispatch_content
    except ModuleNotFoundError:
        from scripts.recovery_candidate import replay_followup_candidate, verify_checkout_snapshot, verify_edit_authorization
        from scripts.runtime_checks import _verified_dispatch_content
    candidate = _accepted_implementer_candidate(artifact_root, prior, source_checkout)
    original = _recover_preserved_candidate(artifact_root, prior, source_checkout, candidate_override=candidate)
    audit = next(row for row in prior["runtime_audits"] if row.get("Worker") == "implement")
    trace_path = Path(audit["Trace path"]).resolve()
    raw = trace_path.read_bytes()
    trace = json.loads(raw)
    content = _verified_dispatch_content(trace)
    if not content or trace.get("audit", {}).get("status") != "passed":
        raise ValueError("candidate_followup_trace_unverified")
    dispatch = json.loads(content.split("\n", 2)[1])
    session = Path(trace["trace_retrieval"])
    try:
        contents, touched = replay_followup_candidate(source_checkout, session, trace["thread_id"], original["_contents"])
    except ValueError as error:
        if str(error) != "candidate_edit_records_missing":
            raise
        verify_checkout_snapshot(source_checkout, candidate["baseline_revision"], original["files"])
        return original
    bindings = json.loads((artifact_root / "role_bindings.json").read_text())
    parent = bindings["parent_context"]
    verify_edit_authorization(Path(parent["provider_session"]), parent["parent_thread_id"], session, trace["thread_id"],
        bindings["runtime_evidence"]["run_started_at"], Path(dispatch["worker_contract"]["before_source_change_guard"]),
        artifact_root / "finalization_packet.json", trace["spawn"]["provider_handle"], source_checkout, touched)
    hashes = {name: hashlib.sha256(data).hexdigest() for name, data in contents.items()}
    verify_checkout_snapshot(source_checkout, candidate["baseline_revision"], hashes)
    return {"prior_run_id": prior["identity"]["Run ID"], "status": "unaccepted", "trace_sha256": hashlib.sha256(raw).hexdigest(),
            "baseline_revision": candidate["baseline_revision"], "files": hashes, "source_already_present": True,
            "base_candidate": candidate, "_contents": contents}


def _recover_reviewed_checkout_candidate(artifact_root: Path, prior: dict, source_checkout: Path) -> dict:
    """Snapshot a first-run candidate only after its accepted review binds the whole checkout."""
    try:
        from recovery_candidate import verify_checkout_snapshot
        from review_evidence import _candidate_fields, review_candidate_metadata_errors, review_report_errors, plan_review_coverage_errors
    except ModuleNotFoundError:
        from scripts.recovery_candidate import verify_checkout_snapshot
        from scripts.review_evidence import _candidate_fields, review_candidate_metadata_errors, review_report_errors, plan_review_coverage_errors
    bindings = json.loads((artifact_root / "role_bindings.json").read_text())
    source_checkout = source_checkout.resolve()
    if Path(bindings["source_checkout"]).resolve() != source_checkout:
        raise ValueError("candidate_recovery_source_checkout_invalid")
    review = (artifact_root / "code_review.md").read_text()
    if (review_candidate_metadata_errors(review, expected_repository=source_checkout)
            or review_report_errors(review, require_accepted=True)
            or plan_review_coverage_errors((artifact_root / "implementation_plan.md").read_text(), review)):
        raise ValueError("candidate_review_fingerprint_invalid")
    fields, errors = _candidate_fields(review)
    if errors:
        raise ValueError("candidate_review_fingerprint_invalid")
    audit = next(row for row in prior["runtime_audits"] if row.get("Worker") == "review")
    trace_path = Path(audit["Trace path"]).resolve()
    if trace_path.parent != artifact_root.resolve() or trace_path.is_symlink():
        raise ValueError("candidate_review_trace_invalid")
    trace = json.loads(trace_path.read_text())
    if hashlib.sha256(review.encode()).hexdigest() != trace["result_artifact"]["output_sha256"]:
        raise ValueError("candidate_review_trace_invalid")
    untracked = json.loads(fields["Untracked candidate files"])
    try:
        changed = subprocess.check_output(["git", "-C", str(source_checkout), "-c", "core.fsmonitor=false",
            "diff", "--name-only", "-z", fields["Base revision"], "--"], timeout=30).decode().split("\0")
        names = (set(changed) - {""}) | set(untracked)
        contents = {name: (source_checkout / name).read_bytes() for name in names}
        hashes = {name: hashlib.sha256(data).hexdigest() for name, data in contents.items()}
        verify_checkout_snapshot(source_checkout, fields["Base revision"], hashes)
        if review_candidate_metadata_errors(review, expected_repository=source_checkout):
            raise ValueError("candidate_review_fingerprint_invalid")
        verify_checkout_snapshot(source_checkout, fields["Base revision"], hashes)
    except (OSError, subprocess.SubprocessError, UnicodeError) as error:
        raise ValueError("candidate_evidence_unavailable") from error
    return {"prior_run_id": prior["identity"]["Run ID"], "status": "unaccepted",
            "trace_sha256": hashlib.sha256(trace_path.read_bytes()).hexdigest(),
            "baseline_revision": fields["Base revision"], "files": hashes,
            "source_already_present": True, "_contents": contents}



def _verified_recovery_planning(artifact_root: Path, prior: dict) -> dict:
    """Find the preserved approved planning records through authenticated run archives."""
    reentry = prior["reentry"]
    planning = prior
    visited = set()
    while True:
        link = planning["reentry"]
        run_id = link["Prior run ID"]
        if not isinstance(run_id, str) or not run_id or Path(run_id).name != run_id or run_id in visited:
            raise ValueError("remediation_recovery_prior_archive_invalid")
        visited.add(run_id)
        archive = (artifact_root / "runs" / run_id).resolve()
        if Path(link["Prior artifacts"]).resolve() != archive:
            raise ValueError("remediation_recovery_prior_archive_invalid")
        manifest = json.loads((archive / "archive_manifest.json").read_text())
        rows = [row for row in manifest["files"] if row.get("path") == "finalization_packet.json"]
        if manifest.get("run_id") != run_id or len(rows) != 1:
            raise ValueError("remediation_recovery_prior_archive_invalid")
        saved = (archive / rows[0]["snapshot"]).resolve()
        if not saved.is_relative_to((artifact_root / "runs").resolve()):
            raise ValueError("remediation_recovery_prior_archive_invalid")
        data = saved.read_bytes()
        if hashlib.sha256(data).hexdigest() != rows[0]["sha256"]:
            raise ValueError("remediation_recovery_prior_archive_invalid")
        planning = json.loads(data)
        if planning["identity"]["Run ID"] != run_id:
            raise ValueError("remediation_recovery_prior_archive_invalid")
        if planning["identity"].get("Lifecycle") == "planning":
            plans = [row for row in manifest["files"] if row.get("path") == "implementation_plan.md"]
            if (planning["identity"].get("State") != "ready_for_implementation"
                    or planning["identity"].get("Workflow outcome") != "completed" or len(plans) != 1):
                raise ValueError("remediation_recovery_prior_archive_invalid")
            saved_plan = (archive / plans[0]["snapshot"]).resolve()
            if (not saved_plan.is_relative_to((artifact_root / "runs").resolve())
                    or hashlib.sha256(saved_plan.read_bytes()).hexdigest() != plans[0]["sha256"]
                    or plans[0]["sha256"] != reentry["Approved plan SHA256"]):
                raise ValueError("remediation_recovery_prior_archive_invalid")
            break
        if (planning["reentry"]["Approved plan SHA256"] != reentry["Approved plan SHA256"]
                or planning["reentry"]["Approval reference"] != reentry["Approval reference"]):
            raise ValueError("remediation_recovery_prior_archive_invalid")
        if not planning.get("worker_results"):
            break
    for table, key in (("claims", "Claim ID"), ("actions", "Action ID"), ("decisions", "Decision ID"), ("evidence", "Evidence ID")):
        old = {row[key]: row for row in planning.get(table, [])}
        current = {row[key]: row for row in prior.get(table, [])}
        if (len(old) != len(planning.get(table, [])) or len(current) != len(prior.get(table, []))
                or any(current.get(key) != value for key, value in old.items())):
            raise ValueError("remediation_recovery_accepted_evidence_changed")
    for field in ("techops_checks", "reproduction", "integration_decision", "playbook_selection"):
        if planning.get(field) != prior.get(field):
            raise ValueError("remediation_recovery_accepted_evidence_changed")
    if ({k: v for k, v in prior.get("work_item", {}).items() if k != "Last Updated"}
            != {k: v for k, v in planning.get("work_item", {}).items() if k != "Last Updated"}):
        raise ValueError("remediation_recovery_accepted_evidence_changed")
    return planning

_REVIEWER_REPLACEMENT_CONTEXT_FAILURE = (
    "Reviewer fan-in was rejected: worker_fan_in_rejected; forbidden_context_reference:memory_path. "
    "Guarded replacement was rejected: parent_context_nonconformant:parent_tool_arguments_unavailable. "
    "No further worker retries."
)


def _verified_reviewer_replacement_context_failure(artifact_root: Path) -> bool:
    """Recognize only the recorded, rejected-review case whose coordinator could not be audited."""
    try:
        failure = json.loads((artifact_root / "finalization_failure.json").read_text())
        packet = json.loads((artifact_root / "finalization_packet.json").read_text())
        ledger = json.loads((artifact_root / "runtime_dispatches.json").read_text())
        pending = ledger.get("rejected_results", {}).get("reviewer")
        if not isinstance(pending, dict):
            return False
        trace_path = Path(pending["trace"]).resolve()
        raw = trace_path.read_bytes()
        trace = json.loads(raw)
        snapshot = Path(failure["packet_snapshot"]).resolve()
        frozen = snapshot.read_bytes()
        return bool(
            failure.get("status") == "failed" and failure.get("stage") == "workflow"
            and failure.get("reported_by") == "Coordinator"
            and failure.get("runtime_closure") == "unverified"
            and failure.get("errors") == [_REVIEWER_REPLACEMENT_CONTEXT_FAILURE]
            and failure.get("run_id") == packet.get("identity", {}).get("Run ID")
            and packet.get("identity", {}).get("Lifecycle") == "remediation"
            and snapshot.parent == artifact_root.resolve() and json.loads(frozen) == packet
            and hashlib.sha256(frozen).hexdigest() == failure.get("snapshot_sha256") == failure.get("packet_sha256")
            and trace_path.parent == artifact_root.resolve()
            and hashlib.sha256(raw).hexdigest() == pending.get("sha256")
            and pending.get("run_id") == trace.get("run_id") == failure.get("run_id")
            and trace.get("worker") == "reviewer"
            and trace.get("spawn", {}).get("provider_handle") == pending.get("Provider handle")
            and trace.get("last_dispatch_at") == pending.get("Last dispatch at")
            and trace.get("audit", {}).get("status") == "rejected"
            and set(trace.get("audit", {}).get("errors", [])) == {
                "worker_fan_in_rejected", "forbidden_context_reference:memory_path"}
            and ledger.get("timing", {}).get("open_worker_intervals") == 0
            and any(row.get("Worker") == "implement" and row.get("Outcome") == "complete"
                    for row in packet.get("worker_results", []))
        )
    except (OSError, KeyError, TypeError, AttributeError, json.JSONDecodeError):
        return False


def _can_defer_reviewer_parent_audit(artifact_root: Path, previous_context: dict,
                                    remediation_reentry: bool) -> bool:
    """Defer only the prior uninspectable coordinator call covered by a verified rejected-review receipt."""
    return bool(remediation_reentry and previous_context.get("status") == "rejected"
                and previous_context.get("errors") == ["parent_tool_arguments_unavailable"]
                and _verified_reviewer_replacement_context_failure(artifact_root))


def _recover_terminal_reviewer_failure(artifact_root: Path, prior: dict, closure: dict,
                                       source_checkout: Path) -> tuple[dict, dict]:
    """Preserve guarded edits and approved planning after a terminal reviewer audit failure."""
    try:
        from planning_contracts import terminal_closure_dispatch_errors
        from runtime_checks import _verified_dispatch_content, trace_errors
        from worker_runtime_evidence import dispatch_audit_errors, _native_terminal_observations
    except ModuleNotFoundError:
        from scripts.planning_contracts import terminal_closure_dispatch_errors
        from scripts.runtime_checks import _verified_dispatch_content, trace_errors
        from scripts.worker_runtime_evidence import dispatch_audit_errors, _native_terminal_observations
    try:
        packet_path = artifact_root / "finalization_packet.json"
        failure = json.loads((artifact_root / "finalization_failure.json").read_text())
        ledger = json.loads((artifact_root / "runtime_dispatches.json").read_text())
        pending = ledger["rejected_results"]["reviewer"]
        trace_path = Path(pending["trace"]).resolve()
        raw = trace_path.read_bytes()
        trace = json.loads(raw)
        frozen_path = Path(failure["packet_snapshot"]).resolve()
        frozen = frozen_path.read_bytes()
        handles = sorted(ledger["thread_mappings"])
        observations = closure["terminal_observations"]
        errors = failure.get("errors", [])
        recorded_errors = set(trace.get("audit", {}).get("errors", []))
        current_errors = trace_errors(trace, require_freshness=True)
        reviewer_failure = (len(errors) == 1 and "delivery_dependency_unverified:reviewer" in errors[0]
                            and "runtime_audit_dispatch_mismatch:review" in errors[0]
                            and "forbidden_context_reference:memory_path" in errors[0]
                            and recorded_errors == {"worker_fan_in_rejected", "forbidden_context_reference:memory_path"}
                            and current_errors == ["worker_fan_in_rejected"])
        parent_failure = (len(errors) == 1 and errors[0].startswith("parent_context_nonconformant:")
                          and trace.get("audit", {}).get("status") == "rejected"
                          and recorded_errors == {"worker_fan_in_rejected", "forbidden_context_reference:archived_artifact"}
                          and set(current_errors) == recorded_errors)
        replacement_context_failure = (
            errors == [_REVIEWER_REPLACEMENT_CONTEXT_FAILURE]
            and _verified_reviewer_replacement_context_failure(artifact_root)
            and trace.get("audit", {}).get("status") == "rejected"
            and recorded_errors == {"worker_fan_in_rejected", "forbidden_context_reference:memory_path"}
            and set(current_errors) == recorded_errors)
        closure_reverified = (failure.get("runtime_closure") == "terminal" or
                              replacement_context_failure and failure.get("runtime_closure") == "unverified")
        if not (failure.get("status") == "failed" and failure.get("stage") == "workflow"
                and failure.get("reported_by") == "Coordinator" and closure_reverified
                and failure.get("run_id") == prior["identity"]["Run ID"] and prior["identity"].get("Lifecycle") == "remediation" and len(errors) == 1
                and (reviewer_failure or parent_failure or replacement_context_failure)
                and frozen_path.parent == artifact_root.resolve() and json.loads(frozen) == prior
                and hashlib.sha256(frozen).hexdigest() == failure.get("snapshot_sha256") == failure.get("packet_sha256")
                and trace_path.parent == artifact_root.resolve() and hashlib.sha256(raw).hexdigest() == pending["sha256"]
                and pending["run_id"] == trace.get("run_id") == prior["identity"]["Run ID"]
                and trace.get("worker") == "reviewer" and trace.get("spawn", {}).get("provider_handle") == pending["Provider handle"]
                and trace.get("last_dispatch_at") == pending["Last dispatch at"]
                and _verified_dispatch_content(trace) and handles and ledger["timing"]["open_worker_intervals"] == 0
                and any(row.get("Provider handle") == pending["Provider handle"]
                        and (row.get("Provider status") == "completed"
                             or row.get("Provider status") == "idle"
                             and row.get("Status source") in {"read_thread", "wait_threads"}
                             and row.get("Latest turn status") == "completed"
                             and row.get("Thread status") in {"idle", "notLoaded"})
                        and row.get("Last dispatch at") == pending["Last dispatch at"]
                        and row.get("Thread ID") == trace.get("thread_id") for row in observations)
                and len(observations) == len(handles) and not terminal_closure_dispatch_errors(packet_path, observations, historical_recovery=True)
                and not dispatch_audit_errors({"runtime_audits": []}, packet_path, closure_only=True, historical_recovery=True)
                and _native_terminal_observations(ledger, handles, require_terminal=False) == observations):
            raise ValueError("remediation_recovery_evidence_unverified")
        reentry = prior["reentry"]
        plan = artifact_root / "implementation_plan.md"
        if (not reentry.get("Approval reference") or reentry.get("Approved plan") != str(plan.resolve())
                or hashlib.sha256(plan.read_bytes()).hexdigest() != reentry.get("Approved plan SHA256")):
            raise ValueError("remediation_recovery_plan_changed")
        planning = _verified_recovery_planning(artifact_root, prior)
        return _recover_current_accepted_candidate(artifact_root, prior, source_checkout), planning
    except (OSError, KeyError, TypeError, AttributeError, StopIteration, json.JSONDecodeError) as error:
        raise ValueError("remediation_recovery_evidence_unverified") from error



def _recover_terminal_unmerged_review(artifact_root: Path, prior: dict, closure: dict,
                                      source_checkout: Path) -> tuple[dict, dict]:
    """Preserve the accepted candidate after a parent failure before review fan-in."""
    try:
        from planning_contracts import terminal_closure_dispatch_errors
        from runtime_checks import _verified_dispatch_content, trace_errors
        from worker_runtime_evidence import dispatch_audit_errors, _native_terminal_observations
    except ModuleNotFoundError:
        from scripts.planning_contracts import terminal_closure_dispatch_errors
        from scripts.runtime_checks import _verified_dispatch_content, trace_errors
        from scripts.worker_runtime_evidence import dispatch_audit_errors, _native_terminal_observations
    try:
        packet_path = artifact_root / "finalization_packet.json"
        failure = json.loads((artifact_root / "finalization_failure.json").read_text())
        ledger = json.loads((artifact_root / "runtime_dispatches.json").read_text())
        snapshot = Path(failure["packet_snapshot"]).resolve()
        frozen = snapshot.read_bytes()
        handles = sorted(ledger["thread_mappings"])
        observations = closure["terminal_observations"]
        errors = failure.get("errors", [])
        if not (failure.get("status") == "failed" and failure.get("stage") == "workflow"
                and failure.get("reported_by") == "Coordinator" and failure.get("runtime_closure") == "terminal"
                and failure.get("run_id") == prior["identity"]["Run ID"]
                and prior["identity"].get("Lifecycle") == "remediation"
                and len(errors) == 1 and errors[0].startswith("parent_context_nonconformant:")
                and snapshot.parent == artifact_root.resolve() and json.loads(frozen) == prior
                and hashlib.sha256(frozen).hexdigest() == failure.get("snapshot_sha256") == failure.get("packet_sha256")
                and not ledger.get("rejected_results")
                and ledger.get("timing", {}).get("open_worker_intervals") == 0 and handles
                and len(observations) == len(handles)
                and not terminal_closure_dispatch_errors(packet_path, observations, historical_recovery=True)
                and not dispatch_audit_errors({"runtime_audits": []}, packet_path, closure_only=True, historical_recovery=True)
                and _native_terminal_observations(ledger, handles, require_terminal=False) == observations):
            raise ValueError("remediation_recovery_evidence_unverified")
        matches = []
        review_trace_found = False
        for path in artifact_root.glob("trace*.json"):
            if path.is_symlink() or not path.is_file():
                continue
            trace = json.loads(path.read_text())
            handle = trace.get("spawn", {}).get("provider_handle")
            if trace.get("run_id") != prior["identity"]["Run ID"] or trace.get("worker") not in {"review", "reviewer"}:
                continue
            review_trace_found = True
            if (trace.get("audit", {}).get("status") == "passed"
                    and ledger["thread_mappings"].get(handle) == trace.get("thread_id")
                    and trace.get("last_dispatch_at") and _verified_dispatch_content(trace)
                    and not trace_errors(trace, require_freshness=True)
                    and any(row.get("Provider handle") == handle and row.get("Thread ID") == trace.get("thread_id")
                            and row.get("Last dispatch at") == trace.get("last_dispatch_at")
                            and row.get("Provider status") == "completed" for row in observations)):
                matches.append(path)
        result_rows = [prior.get(field, []) for field in ("workers", "worker_results", "runtime_audits")]
        if (any(not isinstance(rows, list) for rows in result_rows)
                or len(matches) > 1
                or not matches and (review_trace_found or any(
                    isinstance(row, dict) and row.get("Worker") in {"review", "reviewer"}
                    for rows in result_rows for row in rows))):
            raise ValueError("remediation_recovery_evidence_unverified")
        reentry = prior["reentry"]
        plan = artifact_root / "implementation_plan.md"
        if (not reentry.get("Approval reference") or reentry.get("Approved plan") != str(plan.resolve())
                or hashlib.sha256(plan.read_bytes()).hexdigest() != reentry.get("Approved plan SHA256")):
            raise ValueError("remediation_recovery_plan_changed")
        return _recover_current_accepted_candidate(artifact_root, prior, source_checkout), _verified_recovery_planning(artifact_root, prior)
    except (OSError, KeyError, TypeError, AttributeError, StopIteration, json.JSONDecodeError) as error:
        raise ValueError("remediation_recovery_evidence_unverified") from error


def _verified_historical_tester_guard_rejection(artifact_root: Path, bindings: dict, expected_errors: list[str]) -> bool:
    """Verify the native guard output for the original run and activation bundle."""
    try:
        parent = bindings["parent_context"]
        session = Path(parent["provider_session"])
        expected_hash = hashlib.sha256((artifact_root / "worker_activation_packets.json").read_bytes()).hexdigest()
        session_verified = active_turn = False
        with session.open() as stream:
            for line in stream:
                event = json.loads(line)
                payload = event.get("payload", {})
                if event.get("type") == "session_meta":
                    session_verified = payload.get("id") == parent["parent_thread_id"]
                elif event.get("type") == "turn_context":
                    active_turn = payload.get("turn_id") == parent["turn_id"]
                elif session_verified and active_turn and event.get("type") == "event_msg" and payload.get("type") == "item_completed":
                    item = payload.get("item", {})
                    command = item.get("command", [])
                    if (item.get("type") != "CommandExecution" or item.get("status") != "failed"
                            or item.get("exit_code") != 2 or len(command) != 3
                            or Path(command[0]).name not in {"bash", "sh", "zsh"}
                            or command[1] not in {"-c", "-lc"}):
                        continue
                    try:
                        args = shlex.split(command[2])
                        output = json.loads(item.get("aggregated_output", ""))
                    except (ValueError, TypeError):
                        continue
                    if (len(args) not in {10, 12} or Path(args[0]).name not in {"python", "python3"}
                            or args[1] != bindings["worker_runtime_guard"]):
                        continue
                    options = dict(zip(args[2::2], args[3::2]))
                    required = {"--activation-packet-bundle", "--expected-agent", "--expected-bundle-sha256", "--assignment"}
                    if (len(options) == (len(args) - 2) // 2 and options.get("--activation-packet-bundle") == str(artifact_root / "worker_activation_packets.json")
                            and options.get("--expected-agent") == "tester"
                            and options.get("--expected-bundle-sha256") == expected_hash
                            and set(options) in (required, required | {"--dispatch-file"})
                            and output == {"errors": expected_errors, "status": "blocked"}):
                        return True
    except (OSError, KeyError, TypeError, AttributeError, json.JSONDecodeError):
        return False
    return False


def _verified_historical_tester_guard_parser_rejection(artifact_root: Path, bindings: dict) -> bool:
    return _verified_historical_tester_guard_rejection(artifact_root, bindings,
        ["parent_context_nonconformant:parent_tool_arguments_unavailable"])


def _undispatched_tester_recovery(artifact_root: Path, prior: dict, ledger: dict, errors: list) -> bool:
    """Prove a rejected Tester and an authorized replacement that never started."""
    try:
        from validate_worker_runtime import _defer_downstream_rejection
        from provider_runtime import latest_worker_dispatch
    except ModuleNotFoundError:
        from scripts.validate_worker_runtime import _defer_downstream_rejection
        from scripts.provider_runtime import latest_worker_dispatch
    try:
        if (len(errors) != 1 or not isinstance(errors[0], str)
                or "tester" not in errors[0].lower() or "reject" not in errors[0].lower()):
            return False
        pending = ledger.get("rejected_results", {})
        if set(pending) != {"tester"}:
            return False
        receipt = pending["tester"]
        repair = prior.get("activation_repairs", {}).get("tester", {})
        if (repair.get("Attempt") != 1 or repair.get("Rejected trace SHA256") != receipt["sha256"]
                or repair.get("Provider handle") != receipt["Provider handle"]
                or repair.get("Last dispatch at") != receipt["Last dispatch at"]
                or not _defer_downstream_rejection(artifact_root, "implementer", "tester", receipt)):
            return False
        handle = receipt["Provider handle"]
        if latest_worker_dispatch(ledger, handle, include_failed=True)["Last dispatch at"] != receipt["Last dispatch at"]:
            return False
        accepted = {row["Provider handle"] for row in prior.get("runtime_audits", [])
                    if row.get("Worker") in {"implement", "review"}}
        if (len(accepted) != 2 or handle in accepted or set(ledger["thread_mappings"]) != accepted | {handle}
                or ledger.get("failed_dispatches")):
            return False
        receipts = json.loads((artifact_root / "activation_receipts.json").read_text())
        return any(value.get("sha256") == repair.get("Corrected dispatch SHA256")
                   and value.get("agent") == "tester" and value.get("run_id") == prior["identity"]["Run ID"]
                   and (artifact_root / name).is_file() and not (artifact_root / name).is_symlink()
                   and hashlib.sha256((artifact_root / name).read_bytes()).hexdigest() == value["sha256"]
                   for name, value in receipts.items() if Path(name).name == name)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return False


def _recover_post_delivery_context_failure(artifact_root: Path, prior: dict, closure: dict,
                                           source_checkout: Path) -> tuple[dict, dict]:
    """Preserve approved planning and candidate after a verified late delivery failure."""
    try:
        from planning_contracts import _worker_runtime_audit_errors, terminal_closure_dispatch_errors
        from merge_techops_result import merged_result_errors
        from provider_runtime import parent_context_audit
        from validate_worker_runtime import _defer_downstream_rejection
        from worker_runtime_evidence import dispatch_audit_errors, _native_terminal_observations
    except ModuleNotFoundError:
        from scripts.planning_contracts import _worker_runtime_audit_errors, terminal_closure_dispatch_errors
        from scripts.merge_techops_result import merged_result_errors
        from scripts.provider_runtime import parent_context_audit
        from scripts.validate_worker_runtime import _defer_downstream_rejection
        from scripts.worker_runtime_evidence import dispatch_audit_errors, _native_terminal_observations
    try:
        packet_path = artifact_root / "finalization_packet.json"
        failure = json.loads((artifact_root / "finalization_failure.json").read_text())
        ledger = json.loads((artifact_root / "runtime_dispatches.json").read_text())
        bindings = json.loads((artifact_root / "role_bindings.json").read_text())
        snapshot = Path(failure["packet_snapshot"]).resolve()
        frozen = snapshot.read_bytes()
        handles = sorted(ledger["thread_mappings"])
        observations = closure["terminal_observations"]
        parent = bindings["parent_context"]
        context = parent_context_audit(Path(parent["provider_session"]), artifact_root=artifact_root,
            input_paths=tuple(parent["input_paths"]), expected_thread_id=parent["parent_thread_id"],
            expected_turn_id=parent["turn_id"], runtime_evidence=bindings["runtime_evidence"],
            related_run_thread_ids=tuple(parent.get("related_run_thread_ids", [])),
            prior_dispatch_ledger_present=parent.get("prior_run_dispatch_ledger_present", False))
        results = {row.get("Worker"): row.get("Outcome") for row in prior.get("worker_results", [])}
        errors = failure.get("errors", [])
        has_context_failure = (len(errors) == 1 and isinstance(errors[0], str) and
            ("parent_context_nonconformant:" in errors[0] or
             "parent_unassigned_thread_read:" in errors[0] or
             "parent context" in errors[0].lower() and "nonconformant" in errors[0].lower()))
        context_verified = (has_context_failure and context.get("status") == "rejected" and context.get("errors")
            and all(error in errors[0] or error.rsplit(":", 1)[-1] in errors[0] for error in context["errors"]))
        if (has_context_failure and context.get("status") == "passed" and not context.get("errors")
                and "parent_tool_arguments_unavailable" in errors[0]):
            context_verified = _verified_historical_tester_guard_parser_rejection(artifact_root, bindings)
        pending = ledger.get("rejected_results", {})
        undispatched_tester = _undispatched_tester_recovery(artifact_root, prior, ledger, errors)
        pending_verified = (not pending or isinstance(pending, dict) and set(pending) == {"tester"}
            and (results.get("validate") == "blocked" or undispatched_tester)
            and _defer_downstream_rejection(artifact_root, "implementer", "tester", pending["tester"]))
        if not (failure.get("status") == "failed" and failure.get("stage") == "workflow"
                and failure.get("reported_by") == "Coordinator" and failure.get("runtime_closure") in {"terminal", "unverified"}
                and failure.get("run_id") == prior["identity"]["Run ID"]
                and prior["identity"].get("Lifecycle") == "remediation"
                and (has_context_failure and context_verified or undispatched_tester)
                and context.get("turn_id") == parent["turn_id"]
                and snapshot.parent == artifact_root.resolve() and json.loads(frozen) == prior
                and hashlib.sha256(frozen).hexdigest() == failure.get("snapshot_sha256") == failure.get("packet_sha256")
                and len(prior.get("worker_results", [])) == len(results)
                and results.get("implement") == results.get("review") == "complete"
                and (set(results) == {"implement", "review"} or
                     set(results) == {"implement", "review", "validate"} and results["validate"] in {"complete", "blocked"})
                and pending_verified and ledger.get("timing", {}).get("open_worker_intervals") == 0
                and handles and len(observations) == len(handles)
                and not terminal_closure_dispatch_errors(packet_path, observations, historical_recovery=True)
                and not dispatch_audit_errors({"runtime_audits": []}, packet_path, closure_only=True, historical_recovery=True)
                and _native_terminal_observations(ledger, handles, require_terminal=False) == observations
                and not _worker_runtime_audit_errors(prior, packet_path, set(results))
                and not merged_result_errors(prior, bindings, artifact_root)):
            raise ValueError("remediation_recovery_evidence_unverified")
        plan = artifact_root / "implementation_plan.md"
        reentry = prior["reentry"]
        if (not reentry.get("Approval reference") or reentry.get("Approved plan") != str(plan.resolve())
                or hashlib.sha256(plan.read_bytes()).hexdigest() != reentry.get("Approved plan SHA256")):
            raise ValueError("remediation_recovery_plan_changed")
        candidate = (_recover_reviewed_checkout_candidate(artifact_root, prior, source_checkout)
                     if undispatched_tester and not bindings.get("recovered_candidate")
                     else _recover_current_accepted_candidate(artifact_root, prior, source_checkout))
        return candidate, _verified_recovery_planning(artifact_root, prior)
    except (OSError, KeyError, TypeError, AttributeError, StopIteration, json.JSONDecodeError) as error:
        raise ValueError("remediation_recovery_evidence_unverified") from error


def _predispatch_context_failure(errors: list) -> bool:
    """Recognize one known failure code, including a coordinator's surrounding explanation."""
    if len(errors) != 1 or not isinstance(errors[0], str):
        return False
    pattern = (r"(?:(?:parent_context_nonconformant:)?forbidden_context_reference:(?:archived_artifact|memory_path)"
               r"(?:;parent_context_turn_mismatch:expected=[0-9a-f-]+;received=[0-9a-f-]+;prepare the current continuation)?"
               r"|parent_context_nonconformant:parent_unassigned_thread_discovery|remediation_not_activated)")
    message = re.sub(r"^remediation_not_activated:\s*", "", errors[0])
    match = re.search(r"(?<![\w:])" + pattern + r"(?![\w:])", message)
    remainder = message[:match.start()] + message[match.end():] if match else message
    return bool(match) and not re.search(r"[a-z_]+:[a-z_]", remainder)


def _recover_predispatch_context_candidate(artifact_root: Path, prior: dict, closure: dict,
                                           source_checkout: Path) -> dict:
    """Recover a preserved candidate after a terminal failure before worker dispatch."""
    try:
        from planning_contracts import terminal_closure_dispatch_errors
        from worker_runtime_evidence import dispatch_audit_errors
    except ModuleNotFoundError:
        from scripts.planning_contracts import terminal_closure_dispatch_errors
        from scripts.worker_runtime_evidence import dispatch_audit_errors
    try:
        packet_path = artifact_root / "finalization_packet.json"
        failure = json.loads((artifact_root / "finalization_failure.json").read_text())
        ledger = json.loads((artifact_root / "runtime_dispatches.json").read_text())
        snapshot = Path(failure["packet_snapshot"]).resolve()
        frozen = snapshot.read_bytes()
        errors = failure.get("errors", [])
        reentry = prior["reentry"]
        plan = artifact_root / "implementation_plan.md"
        failure_verified = _predispatch_context_failure(errors)
        combined_errors = ["parent_context_nonconformant:forbidden_context_reference:memory_path",
                           "delivery_dependency_not_accepted:tester"]
        if len(errors) == 1 and isinstance(errors[0], str) and all(error in errors[0] for error in combined_errors):
            bindings = json.loads((artifact_root / "role_bindings.json").read_text())
            failure_verified = _verified_historical_tester_guard_rejection(artifact_root, bindings, combined_errors)
        if not (failure.get("status") == "failed" and failure.get("stage") == "workflow"
                and failure.get("reported_by") == "Coordinator" and failure.get("runtime_closure") == "terminal"
                and failure.get("run_id") == prior["identity"]["Run ID"] and prior["identity"].get("Lifecycle") == "remediation"
                and failure_verified
                and snapshot.parent == artifact_root.resolve() and json.loads(frozen) == prior
                and hashlib.sha256(frozen).hexdigest() == failure.get("snapshot_sha256") == failure.get("packet_sha256")
                and not prior.get("workers") and not prior.get("worker_results") and not prior.get("runtime_audits")
                and not ledger.get("thread_mappings") and not ledger.get("events") and not ledger.get("failed_dispatches")
                and ledger.get("timing", {}).get("open_worker_intervals") == 0 and closure.get("terminal_observations") == []
                and not terminal_closure_dispatch_errors(packet_path, [], historical_recovery=True)
                and not dispatch_audit_errors({"runtime_audits": []}, packet_path, closure_only=True, historical_recovery=True)
                and reentry.get("Approval reference") and reentry.get("Approved plan") == str(plan.resolve())
                and hashlib.sha256(plan.read_bytes()).hexdigest() == reentry.get("Approved plan SHA256")):
            raise ValueError("remediation_recovery_evidence_unverified")
        _verified_recovery_planning(artifact_root, prior)
        return _recover_preserved_candidate(artifact_root, prior, source_checkout)
    except (OSError, KeyError, TypeError, AttributeError, json.JSONDecodeError) as error:
        raise ValueError("remediation_recovery_evidence_unverified") from error



def _recover_stopped_bootstrap_candidate(artifact_root: Path, prior: dict, closure: dict,
                                         source_checkout: Path, *, rejected: bool = False,
                                         check_checkout: bool = True) -> dict:
    """Preserve an unchanged candidate after terminal, unaccepted worker attempts."""
    try:
        from planning_contracts import terminal_closure_dispatch_errors
        from worker_runtime_evidence import dispatch_audit_errors, _native_terminal_observations
    except ModuleNotFoundError:
        from scripts.planning_contracts import terminal_closure_dispatch_errors
        from scripts.worker_runtime_evidence import dispatch_audit_errors, _native_terminal_observations
    try:
        packet_path = artifact_root / "finalization_packet.json"
        failure = json.loads((artifact_root / "finalization_failure.json").read_text())
        ledger = json.loads((artifact_root / "runtime_dispatches.json").read_text())
        snapshot = Path(failure["packet_snapshot"]).resolve()
        frozen = snapshot.read_bytes()
        errors = failure.get("errors", [])
        handles = sorted(ledger["thread_mappings"])
        observations = closure["terminal_observations"]
        reentry = prior["reentry"]
        plan = artifact_root / "implementation_plan.md"
        if rejected:
            pending = ledger.get("rejected_results", {})
            if not isinstance(pending, dict) or set(pending) != {"implementer"}:
                raise ValueError("candidate_rejected_trace_unverified")
            receipt = pending["implementer"]
            path = Path(receipt["trace"])
            if path.is_symlink() or path.resolve().parent != artifact_root.resolve():
                raise ValueError("candidate_rejected_trace_unverified")
            raw = path.read_bytes()
            trace = json.loads(raw)
            handle = receipt["Provider handle"]
            closure_dispatch = receipt.get("Last dispatch at")
            repair = prior.get("activation_repairs", {}).get("implementer")
            if repair:
                try:
                    from provider_runtime import latest_worker_dispatch
                except ModuleNotFoundError:
                    from scripts.provider_runtime import latest_worker_dispatch
                # The correction is not accepted as a result; it only determines which
                # dispatch the independent terminal observation must close.
                latest = latest_worker_dispatch(ledger, handle)
                receipts = json.loads((artifact_root / "activation_receipts.json").read_text())
                approved = [(name, row) for name, row in receipts.items()
                            if row.get("run_id") == prior["identity"]["Run ID"]
                            and row.get("agent") == "implementer"
                            and row.get("sha256") == repair.get("Corrected dispatch SHA256")]
                if not (repair.get("Attempt") == 1 and repair.get("Provider handle") == handle
                        and repair.get("Last dispatch at") == receipt.get("Last dispatch at")
                        and repair.get("Rejected trace SHA256") == receipt.get("sha256")
                        and latest.get("Operation") == "followup_task"
                        and latest.get("Last dispatch at") != receipt.get("Last dispatch at")
                        and len(approved) == 1):
                    raise ValueError("candidate_rejected_trace_unverified")
                corrected = artifact_root / approved[0][0]
                if (corrected.is_symlink() or corrected.resolve().parent != artifact_root.resolve()
                        or hashlib.sha256(corrected.read_bytes()).hexdigest() != approved[0][1]["sha256"]):
                    raise ValueError("candidate_rejected_trace_unverified")
                closure_dispatch = latest["Last dispatch at"]
            if not (hashlib.sha256(raw).hexdigest() == receipt.get("sha256")
                    and receipt.get("run_id") == trace.get("run_id") == prior["identity"]["Run ID"]
                    and trace.get("worker") == "implementer" and trace.get("audit", {}).get("status") == "rejected"
                    and trace.get("spawn", {}).get("provider_handle") == handle
                    and trace.get("thread_id") == ledger["thread_mappings"].get(handle)
                    and trace.get("last_dispatch_at") == receipt.get("Last dispatch at")
                    and any(row.get("Provider handle") == handle and row.get("Provider status") in
                            {"completed", "idle", "interrupted", "stopped", "cancelled", "failed"}
                            and row.get("Last dispatch at") == closure_dispatch for row in observations)):
                raise ValueError("candidate_rejected_trace_unverified")
        else:
            unactivated = (len(errors) == 1 and isinstance(errors[0], str)
                           and errors[0].startswith("remediation_not_activated:"))
            bootstrap = (len(errors) == 1 and isinstance(errors[0], str)
                         and "bootstrap" in errors[0].lower() and "before reading" in errors[0].lower())
            if (not (unactivated or bootstrap) or ledger.get("rejected_results") or ledger.get("failed_dispatches")):
                raise ValueError("remediation_recovery_evidence_unverified")
        if not (failure.get("status") == "failed" and failure.get("stage") == "workflow"
                and failure.get("reported_by") == "Coordinator" and failure.get("runtime_closure") == "terminal"
                and failure.get("run_id") == prior["identity"]["Run ID"] and prior["identity"].get("Lifecycle") == "remediation"
                and len(errors) == 1 and isinstance(errors[0], str)
                and snapshot.parent == artifact_root.resolve() and json.loads(frozen) == prior
                and hashlib.sha256(frozen).hexdigest() == failure.get("snapshot_sha256") == failure.get("packet_sha256")
                and not prior.get("workers") and not prior.get("worker_results") and not prior.get("runtime_audits")
                and handles
                and ledger.get("timing", {}).get("open_worker_intervals") == 0
                and isinstance(observations, list) and len(observations) == len(handles)
                and all(row.get("Provider status") in ({"completed", "idle", "interrupted", "stopped", "cancelled", "failed"}
                         if rejected or unactivated else {"interrupted", "stopped", "cancelled", "failed"}) for row in observations)
                and not terminal_closure_dispatch_errors(packet_path, observations, historical_recovery=True)
                and not dispatch_audit_errors({"runtime_audits": []}, packet_path, closure_only=True, historical_recovery=True)
                and _native_terminal_observations(ledger, handles, require_terminal=False) == observations
                and reentry.get("Approval reference") and reentry.get("Approved plan") == str(plan.resolve())
                and hashlib.sha256(plan.read_bytes()).hexdigest() == reentry.get("Approved plan SHA256")):
            raise ValueError("remediation_recovery_evidence_unverified")
        _verified_recovery_planning(artifact_root, prior)
        return _recover_preserved_candidate(artifact_root, prior, source_checkout, check_checkout=check_checkout)
    except (OSError, KeyError, TypeError, AttributeError, json.JSONDecodeError) as error:
        raise ValueError("remediation_recovery_evidence_unverified") from error


def _recover_rejected_candidate(artifact_root: Path, prior: dict, closure: dict, source_checkout: Path) -> dict:
    """Use the recorded edit replay when the preserved snapshot has changed."""
    try:
        return _recover_stopped_bootstrap_candidate(artifact_root, prior, closure, source_checkout, rejected=True)
    except ValueError as error:
        if not str(error).startswith(("candidate_content_changed:", "candidate_changed_paths_mismatch")):
            raise
        if prior.get("activation_repairs", {}).get("implementer"):
            return _recover_rejected_correction(artifact_root, prior, closure, source_checkout)
        return _recover_failed_remediation(artifact_root, prior, closure, source_checkout=source_checkout)


def _corrected_rejection_errors(prior: dict, failure: dict, ledger: dict, closure: dict,
                                trace: dict, first_trace_sha: str) -> bool:
    """Verify that a rejected correction belongs to the recorded terminal attempt."""
    run_id = prior["identity"]["Run ID"]
    repair = prior.get("activation_repairs", {}).get("implementer", {})
    receipt = ledger.get("rejected_results", {}).get("implementer", {})
    handle = trace.get("spawn", {}).get("provider_handle")
    observations = closure.get("terminal_observations", [])
    errors = failure.get("errors", [])
    return bool(
        failure.get("status") == "failed" and failure.get("stage") == "workflow"
        and failure.get("reported_by") == "Coordinator" and failure.get("runtime_closure") == "terminal"
        and failure.get("run_id") == run_id and len(errors) == 1
        and str(errors[0]).startswith("implementer_corrected_result_rejected:")
        and repair.get("Attempt") == 1 and first_trace_sha
        and repair.get("Rejected trace SHA256") == first_trace_sha == receipt.get("sha256")
        and receipt.get("run_id") == run_id and receipt.get("Provider handle") == repair.get("Provider handle")
        and receipt.get("Last dispatch at") == repair.get("Last dispatch at")
        and trace.get("run_id") == run_id and trace.get("worker") == "implementer"
        and trace.get("audit", {}).get("status") == "rejected"
        and repair.get("Corrected dispatch SHA256")
        and trace.get("spawn", {}).get("dispatch_file_sha256") == repair.get("Corrected dispatch SHA256")
        and handle and trace.get("thread_id") and trace.get("last_dispatch_at")
        and handle != receipt.get("Provider handle") and ledger.get("thread_mappings", {}).get(handle) == trace.get("thread_id")
        and ledger.get("timing", {}).get("open_worker_intervals") == 0
        and any(row.get("Provider handle") == handle and row.get("Thread ID") == trace.get("thread_id")
                and row.get("Last dispatch at") == trace.get("last_dispatch_at")
                and row.get("Provider status") == "completed" for row in observations))


def _recover_rejected_correction(artifact_root: Path, prior: dict, closure: dict, source_checkout: Path) -> dict:
    """Replay a guarded rejected correction over the previously authenticated candidate."""
    try:
        from recovery_candidate import replay_followup_candidate, verify_checkout_snapshot, verify_edit_authorization
        from runtime_checks import _verified_dispatch_content
    except ModuleNotFoundError:
        from scripts.recovery_candidate import replay_followup_candidate, verify_checkout_snapshot, verify_edit_authorization
        from scripts.runtime_checks import _verified_dispatch_content
    original = _recover_stopped_bootstrap_candidate(artifact_root, prior, closure, source_checkout,
                                                     rejected=True, check_checkout=False)
    bindings = json.loads((artifact_root / "role_bindings.json").read_text())
    candidate = bindings["recovered_candidate"]
    failure = json.loads((artifact_root / "finalization_failure.json").read_text())
    ledger = json.loads((artifact_root / "runtime_dispatches.json").read_text())
    receipt = ledger["rejected_results"]["implementer"]
    matches = []
    for path in artifact_root.glob("trace*.json"):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            trace = json.loads(path.read_text())
            if _corrected_rejection_errors(prior, failure, ledger, closure, trace, receipt["sha256"]):
                matches.append((path, trace))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    if len(matches) != 1:
        raise ValueError("candidate_followup_trace_unverified")
    path, trace = matches[0]
    content = _verified_dispatch_content(trace)
    if not content:
        raise ValueError("candidate_followup_trace_unverified")
    dispatch = json.loads(content.split("\n", 2)[1])
    if (dispatch.get("worker_contract", {}).get("recovered_candidate") != candidate
            or Path(dispatch["coordinator_execution"]["source_checkout"]).resolve() != source_checkout.resolve()):
        raise ValueError("candidate_followup_binding_invalid")
    session = Path(trace["trace_retrieval"])
    contents, touched = replay_followup_candidate(source_checkout, session, trace["thread_id"], original["_contents"])
    parent = bindings["parent_context"]
    verify_edit_authorization(Path(parent["provider_session"]), parent["parent_thread_id"], session, trace["thread_id"],
        bindings["runtime_evidence"]["run_started_at"], Path(dispatch["worker_contract"]["before_source_change_guard"]),
        artifact_root / "finalization_packet.json", trace["spawn"]["provider_handle"], source_checkout, touched)
    hashes = {name: hashlib.sha256(data).hexdigest() for name, data in contents.items()}
    verify_checkout_snapshot(source_checkout, candidate["baseline_revision"], hashes)
    return {"prior_run_id": prior["identity"]["Run ID"], "status": "unaccepted",
            "trace_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "baseline_revision": candidate["baseline_revision"],
            "files": hashes, "source_already_present": True, "base_candidate": candidate,
            "rejected_correction": True, "_contents": contents}


def _recover_unmerged_candidate(artifact_root: Path, prior: dict, closure: dict, source_checkout: Path) -> dict:
    """Replay guarded edits from a completed worker whose result the coordinator could not merge."""
    try:
        from planning_contracts import terminal_closure_dispatch_errors
        from recovery_candidate import replay_followup_candidate, verify_checkout_snapshot, verify_edit_authorization
        from runtime_checks import _verified_dispatch_content
        from worker_runtime_evidence import dispatch_audit_errors, _native_terminal_observations
    except ModuleNotFoundError:
        from scripts.planning_contracts import terminal_closure_dispatch_errors
        from scripts.recovery_candidate import replay_followup_candidate, verify_checkout_snapshot, verify_edit_authorization
        from scripts.runtime_checks import _verified_dispatch_content
        from scripts.worker_runtime_evidence import dispatch_audit_errors, _native_terminal_observations
    try:
        packet_path = artifact_root / "finalization_packet.json"
        failure = json.loads((artifact_root / "finalization_failure.json").read_text())
        ledger = json.loads((artifact_root / "runtime_dispatches.json").read_text())
        bindings = json.loads((artifact_root / "role_bindings.json").read_text())
        snapshot = Path(failure["packet_snapshot"]).resolve()
        frozen = snapshot.read_bytes()
        handles = sorted(ledger["thread_mappings"])
        observations = closure["terminal_observations"]
        errors = failure.get("errors", [])
        if not (failure.get("status") == "failed" and failure.get("stage") == "workflow"
                and failure.get("reported_by") == "Coordinator" and failure.get("runtime_closure") in {"terminal", "unverified"}
                and failure.get("run_id") == prior["identity"]["Run ID"]
                and prior["identity"].get("Lifecycle") == "remediation"
                and len(errors) == 1 and "parent_context_nonconformant:" in str(errors[0])
                and snapshot.parent == artifact_root.resolve() and json.loads(frozen) == prior
                and hashlib.sha256(frozen).hexdigest() == failure.get("snapshot_sha256") == failure.get("packet_sha256")
                and not prior.get("workers") and not prior.get("worker_results") and not prior.get("runtime_audits")
                and handles
                and ledger.get("timing", {}).get("open_worker_intervals") == 0
                and len(observations) == len(handles)
                and not terminal_closure_dispatch_errors(packet_path, observations, historical_recovery=True)
                and not dispatch_audit_errors({"runtime_audits": []}, packet_path, closure_only=True, historical_recovery=True)
                and _native_terminal_observations(ledger, handles, require_terminal=False) == observations):
            raise ValueError("remediation_recovery_evidence_unverified")
        _verified_recovery_planning(artifact_root, prior)
        candidate = bindings["recovered_candidate"]
        original = _recover_preserved_candidate(artifact_root, prior, source_checkout, check_checkout=False)
        paths = [path for path in artifact_root.glob("*trace*.json") if path.is_file() and not path.is_symlink()]
        traces = [(path, json.loads(path.read_text())) for path in paths]
        matches = [(path, trace) for path, trace in traces if trace.get("run_id") == prior["identity"]["Run ID"]
                   and trace.get("worker") == "implementer" and trace.get("audit", {}).get("status") == "passed"
                   and trace.get("spawn", {}).get("provider_handle") in handles
                   and trace.get("thread_id") == ledger["thread_mappings"].get(trace.get("spawn", {}).get("provider_handle"))
                   and bool(trace.get("last_dispatch_at"))
                   and any(row.get("Provider handle") == trace.get("spawn", {}).get("provider_handle")
                           and row.get("Last dispatch at") == trace.get("last_dispatch_at") for row in observations)]
        if len(matches) != 1:
            raise ValueError("candidate_followup_trace_unverified")
        path, trace = matches[0]
        content = _verified_dispatch_content(trace)
        if not content:
            raise ValueError("candidate_followup_trace_unverified")
        dispatch = json.loads(content.split("\n", 2)[1])
        if (dispatch.get("worker_contract", {}).get("recovered_candidate") != candidate
                or Path(dispatch["coordinator_execution"]["source_checkout"]).resolve() != source_checkout.resolve()):
            raise ValueError("candidate_followup_binding_invalid")
        session = Path(trace["trace_retrieval"])
        try:
            contents, touched = replay_followup_candidate(source_checkout, session, trace["thread_id"], original["_contents"])
        except ValueError as error:
            if str(error) != "candidate_edit_records_missing":
                raise
            verify_checkout_snapshot(source_checkout, candidate["baseline_revision"], original["files"])
            return original
        if failure.get("runtime_closure") != "terminal":
            raise ValueError("remediation_recovery_evidence_unverified")
        parent = bindings["parent_context"]
        verify_edit_authorization(Path(parent["provider_session"]), parent["parent_thread_id"], session, trace["thread_id"],
            bindings["runtime_evidence"]["run_started_at"], Path(dispatch["worker_contract"]["before_source_change_guard"]),
            packet_path, trace["spawn"]["provider_handle"], source_checkout, touched)
        hashes = {name: hashlib.sha256(data).hexdigest() for name, data in contents.items()}
        verify_checkout_snapshot(source_checkout, candidate["baseline_revision"], hashes)
        return {"prior_run_id": prior["identity"]["Run ID"], "status": "unaccepted",
                "trace_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "baseline_revision": candidate["baseline_revision"], "files": hashes, "source_already_present": True,
                "base_candidate": candidate, "unmerged_parent_failure": True, "_contents": contents}
    except (OSError, KeyError, TypeError, AttributeError, json.JSONDecodeError) as error:
        raise ValueError("remediation_recovery_evidence_unverified") from error


def _recover_terminal_accepted_remediation(artifact_root: Path, prior: dict, closure: dict,
                                           source_checkout: Path) -> tuple[dict, dict]:
    """Re-enter a terminal delivery failure without accepting its rejected downstream work."""
    try:
        from planning_contracts import terminal_closure_dispatch_errors
        from validate_worker_runtime import _defer_downstream_rejection
        from worker_runtime_evidence import dispatch_audit_errors, _native_terminal_observations
    except ModuleNotFoundError:
        from scripts.planning_contracts import terminal_closure_dispatch_errors
        from scripts.validate_worker_runtime import _defer_downstream_rejection
        from scripts.worker_runtime_evidence import dispatch_audit_errors, _native_terminal_observations
    try:
        packet_path = artifact_root / "finalization_packet.json"
        failure = json.loads((artifact_root / "finalization_failure.json").read_text())
        ledger = json.loads((artifact_root / "runtime_dispatches.json").read_text())
        snapshot = Path(failure["packet_snapshot"]).resolve()
        frozen = snapshot.read_bytes()
        frozen_packet = json.loads(frozen)
        pending = ledger.get("rejected_results", {}).get("tester")
        handles = sorted(ledger["thread_mappings"])
        observations = closure["terminal_observations"]
        errors = failure.get("errors", [])
        if not (failure.get("status") == "failed" and failure.get("stage") == "workflow"
                and failure.get("reported_by") == "Coordinator" and failure.get("runtime_closure") in {"terminal", "unverified"}
                and failure.get("run_id") == prior["identity"]["Run ID"] and len(errors) == 1
                and "worker_activation_rejected_result_pending:tester" in errors[0]
                and snapshot.parent == artifact_root.resolve()
                and hashlib.sha256(frozen).hexdigest() == failure.get("snapshot_sha256") == failure.get("packet_sha256")
                and frozen_packet == prior and prior["identity"].get("Lifecycle") == "remediation"
                and len(prior.get("workers", [])) == 1 and len(prior.get("worker_results", [])) == 1
                and prior["worker_results"][0].get("Worker") == "implement"
                and prior["worker_results"][0].get("Outcome") == "complete"
                and isinstance(pending, dict) and _defer_downstream_rejection(artifact_root, "implementer", "tester", pending)
                and ledger.get("timing", {}).get("open_worker_intervals") == 0 and handles
                and isinstance(observations, list) and len(observations) == len(handles)
                and not terminal_closure_dispatch_errors(packet_path, observations, historical_recovery=True)
                and not dispatch_audit_errors({"runtime_audits": []}, packet_path, closure_only=True, historical_recovery=True)
                and _native_terminal_observations(ledger, handles, require_terminal=False) == observations):
            raise ValueError("remediation_recovery_evidence_unverified")
        reentry = prior["reentry"]
        plan = artifact_root / "implementation_plan.md"
        if (not reentry.get("Approval reference") or reentry.get("Approved plan") != str(plan.resolve())
                or hashlib.sha256(plan.read_bytes()).hexdigest() != reentry.get("Approved plan SHA256")):
            raise ValueError("remediation_recovery_plan_changed")
        archive = Path(reentry["Prior artifacts"]).resolve()
        if archive != (artifact_root / "runs" / reentry["Prior run ID"]).resolve():
            raise ValueError("remediation_recovery_prior_archive_invalid")
        manifest = json.loads((archive / "archive_manifest.json").read_text())
        entries = [row for row in manifest["files"] if row.get("path") == "finalization_packet.json"]
        if manifest.get("run_id") != reentry["Prior run ID"] or len(entries) != 1:
            raise ValueError("remediation_recovery_prior_archive_invalid")
        archived_path = (archive / entries[0]["snapshot"]).resolve()
        if not archived_path.is_relative_to((artifact_root / "runs").resolve()):
            raise ValueError("remediation_recovery_prior_archive_invalid")
        archived = archived_path.read_bytes()
        if hashlib.sha256(archived).hexdigest() != entries[0]["sha256"]:
            raise ValueError("remediation_recovery_prior_archive_invalid")
        planning = json.loads(archived)
        candidate = _recover_accepted_candidate(artifact_root, prior, source_checkout)
        bindings = json.loads((artifact_root / "role_bindings.json").read_text())
        result_path = Path(bindings["worker_contracts"]["implementer"]["result"]).resolve()
        if result_path.parent != artifact_root.resolve():
            raise ValueError("remediation_recovery_accepted_evidence_changed")
        implementation = json.loads(result_path.read_text())
        for table, key in (("claims", "Claim ID"), ("actions", "Action ID"),
                           ("decisions", "Decision ID"), ("evidence", "Evidence ID")):
            old = {row[key]: row for row in planning.get(table, [])}
            current = {row[key]: row for row in prior.get(table, [])}
            if len(old) != len(planning.get(table, [])) or len(current) != len(prior.get(table, [])):
                raise ValueError("remediation_recovery_accepted_evidence_changed")
            if any(current.get(key) != value for key, value in old.items()):
                raise ValueError("remediation_recovery_accepted_evidence_changed")
            if set(current) - set(old) != {row[key] for row in implementation.get(table, [])} - set(old):
                raise ValueError("remediation_recovery_accepted_evidence_changed")
        if any(prior.get(field) != planning.get(field) for field in
               ("techops_checks", "reproduction", "integration_decision", "playbook_selection")):
            raise ValueError("remediation_recovery_accepted_evidence_changed")
        if ({k: v for k, v in prior.get("work_item", {}).items() if k != "Last Updated"}
                != {k: v for k, v in planning.get("work_item", {}).items() if k != "Last Updated"}):
            raise ValueError("remediation_recovery_accepted_evidence_changed")
        return candidate, planning
    except (OSError, KeyError, TypeError, AttributeError, StopIteration, json.JSONDecodeError) as error:
        raise ValueError("remediation_recovery_evidence_unverified") from error


def _recover_failed_remediation(artifact_root: Path, prior: dict, closure: dict,
                                *, source_checkout: Path | None = None) -> dict | None:
    """Verify a failed TechOps activation before starting a replacement delivery run."""
    try:
        from planning_contracts import terminal_closure_dispatch_errors
        from worker_runtime_evidence import dispatch_audit_errors, _native_terminal_observations
    except ModuleNotFoundError:
        from scripts.planning_contracts import terminal_closure_dispatch_errors
        from scripts.worker_runtime_evidence import dispatch_audit_errors, _native_terminal_observations
    packet_path = artifact_root / "finalization_packet.json"
    failure = json.loads((artifact_root / "finalization_failure.json").read_text())
    snapshot = Path(failure["packet_snapshot"]).resolve()
    frozen = snapshot.read_bytes()
    frozen_packet = json.loads(frozen)
    reentry = prior["reentry"]
    plan = artifact_root / "implementation_plan.md"
    ledger = json.loads((artifact_root / "runtime_dispatches.json").read_text())
    observations = closure["terminal_observations"]
    handles = sorted(ledger["thread_mappings"])
    expected_error = "remediation_not_activated:expected_matching_active_profile_and_in_progress_state"
    missing_mapping = (failure.get("errors") == ["techops_conformance_record_required"]
                       and not (artifact_root / "implementation_conformance.json").exists())
    context_error = "parent_context_nonconformant:forbidden_context_reference:archived_artifact"
    context_recovery = failure.get("errors") == [context_error] and not handles
    candidate_recovery = (source_checkout is not None and len(failure.get("errors", [])) == 1
                          and failure["errors"][0].startswith("parent_context_nonconformant:")
                          and any(str(error).startswith("worker_result_contract_invalid:implementer:")
                                  for error in failure.get("historical_errors", [])))
    launcher_reread_errors = {
        "launcher_reread_after_compaction",
        "Continuation protocol violation: the active run launcher was reread after preparation; worker dispatch stopped before activation.",
    }
    predispatch_candidate = (source_checkout is not None and not handles and not ledger.get("events")
        and not ledger.get("failed_dispatches") and len(failure.get("errors", [])) == 1
        and failure["errors"][0] in launcher_reread_errors)
    preserved_candidate_recovery = (source_checkout is not None and bool(handles)
        and len(failure.get("errors", [])) == 1
        and failure["errors"][0].startswith("parent_context_nonconformant:")
        and json.loads((artifact_root / "role_bindings.json").read_text()).get("recovered_candidate", {}).get("source_already_present") is True)
    existing_candidate_recovery = (source_checkout is not None and bool(handles)
        and source_checkout.resolve() == artifact_root.resolve().parent.parent
        and bool(ledger.get("rejected_results", {}).get("implementer")))
    if context_recovery or candidate_recovery or predispatch_candidate or preserved_candidate_recovery or existing_candidate_recovery:
        archive = Path(reentry["Prior artifacts"]).resolve()
        expected_archive = (artifact_root / "runs" / reentry["Prior run ID"]).resolve()
        if archive != expected_archive or archive.parent != (artifact_root / "runs").resolve():
            raise ValueError("remediation_recovery_prior_archive_invalid")
        manifest = json.loads((archive / "archive_manifest.json").read_text())
        entries = [row for row in manifest.get("files", []) if row.get("path") == "finalization_packet.json"]
        saved = (archive / "finalization_packet.json").read_bytes()
        approved_source = json.loads(saved)
        fields = ("decisions", "claims", "actions", "evidence", "techops_checks", "reproduction",
                  "integration_decision", "playbook_selection")
        current_item = {k: v for k, v in prior.get("work_item", {}).items() if k != "Last Updated"}
        saved_item = {k: v for k, v in approved_source.get("work_item", {}).items() if k != "Last Updated"}
        if (manifest.get("run_id") != reentry["Prior run ID"] or len(entries) != 1
                or entries[0].get("sha256") != hashlib.sha256(saved).hexdigest()
                or current_item != saved_item
                or any(prior.get(field) != approved_source.get(field) or prior.get(field) != frozen_packet.get(field)
                       for field in fields)):
            raise ValueError("remediation_recovery_accepted_evidence_changed")
    if not (failure.get("status") == "failed" and failure.get("stage") == "workflow"
            and (failure.get("errors") == [expected_error] or missing_mapping or context_recovery or candidate_recovery or predispatch_candidate or preserved_candidate_recovery or existing_candidate_recovery)
            and (failure.get("runtime_closure") == "terminal" or preserved_candidate_recovery
                 and failure.get("runtime_closure") == "unverified")
            and failure.get("reported_by") == "Coordinator" and int(failure.get("attempt_count", 0)) < 2
            and failure.get("run_id") == prior["identity"]["Run ID"]
            and snapshot.parent == artifact_root.resolve()
            and hashlib.sha256(frozen).hexdigest() == failure.get("snapshot_sha256") == failure.get("packet_sha256")
            and frozen_packet["identity"]["Run ID"] == prior["identity"]["Run ID"]
            and frozen_packet["identity"].get("Lifecycle") == "remediation"
            and not frozen_packet.get("workers") and not frozen_packet.get("worker_results")
            and frozen_packet.get("reentry") == reentry and not prior.get("workers")
            and not prior.get("worker_results")
            and (not prior.get("runtime_audits") or preserved_candidate_recovery
                 and prior.get("runtime_audits") == frozen_packet.get("runtime_audits")
                 and all(row.get("Provider handle") in handles for row in prior["runtime_audits"]))
            and reentry.get("Approval reference") and reentry.get("Prior run ID")
            and reentry.get("Approved plan") == str(plan.resolve())
            and hashlib.sha256(plan.read_bytes()).hexdigest() == reentry.get("Approved plan SHA256")
            and (handles or (context_recovery or predispatch_candidate) and not ledger.get("events") and not ledger.get("failed_dispatches"))
            and ledger.get("timing", {}).get("open_worker_intervals") == 0
            and isinstance(observations, list) and len(observations) == len(handles)
            and not terminal_closure_dispatch_errors(packet_path, observations, historical_recovery=True)
            and not dispatch_audit_errors({"runtime_audits": []}, packet_path, closure_only=True, historical_recovery=True)
            and (not handles or _native_terminal_observations(ledger, handles, require_terminal=False) == observations)):
        raise ValueError("remediation_recovery_evidence_unverified")
    repositories = [row for row in prior.get("repositories", []) if row.get("Repository role") == "Execution repository"]
    if len(repositories) != 1 or not repositories[0].get("Full revision"):
        raise ValueError("remediation_recovery_baseline_unavailable")
    repository = Path(repositories[0]["Resolved path"])
    if predispatch_candidate or preserved_candidate_recovery:
        if repository.resolve() != source_checkout.resolve():
            raise ValueError("candidate_recovery_source_checkout_invalid")
        return _recover_preserved_candidate(artifact_root, prior, source_checkout)
    if existing_candidate_recovery:
        return _verify_rejected_delivery_candidate(artifact_root, prior, failure, ledger,
                                                   source_checkout=source_checkout, source_already_present=True)
    if repository.resolve() != artifact_root.resolve().parent.parent:
        raise ValueError("remediation_recovery_repository_mismatch")
    if candidate_recovery:
        if source_checkout.resolve() == repository.resolve():
            raise ValueError("candidate_recovery_requires_clean_worktree")
        return _verify_rejected_delivery_candidate(artifact_root, prior, failure, ledger,
                                                   source_checkout=source_checkout)
    try:
        revision = subprocess.run(["git", "-C", str(repository), "rev-parse", "HEAD"], check=True,
                                  capture_output=True, text=True, timeout=30).stdout.strip()
        status = subprocess.run(["git", "-C", str(repository), "-c", "core.fsmonitor=false", "status", "--porcelain"],
                                check=True, capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError) as error:
        raise ValueError("remediation_recovery_checkout_unverified") from error
    if status or revision != repositories[0]["Full revision"]:
        raise ValueError("remediation_recovery_checkout_changed")


def _recover_finalized_remediation(artifact_root: Path, prior: dict, source_checkout: Path | None) -> tuple[dict, dict]:
    """Preserve a published terminal run without requiring a workflow-failure receipt."""
    try:
        from finalize_work_record import publication_recovery_context, recovery_canonical_report, verify_presentation
    except ModuleNotFoundError:
        from scripts.finalize_work_record import publication_recovery_context, recovery_canonical_report, verify_presentation
    if source_checkout is None or prior["identity"].get("State") not in {"blocked", "completed"}:
        raise ValueError("remediation_finalized_run_unverified")
    record = artifact_root / "work_record.md"
    with tempfile.TemporaryDirectory(prefix="workflow-reentry-package-") as workspace:
        proof = publication_recovery_context(artifact_root / "finalization_packet.json", record,
                                             package_workspace=Path(workspace))
    delivery = json.loads((artifact_root / "handoff_delivery.json").read_text())
    response = Path(delivery["proposed_response"])
    reentry = prior["reentry"]
    plan = artifact_root / "implementation_plan.md"
    if (delivery.get("status") != "verified" or delivery.get("run_id") != prior["identity"]["Run ID"]
            or delivery.get("record_sha256") != proof["record_sha256"]
            or delivery.get("canonical_sha256") != proof["canonical_sha256"]
            or response.is_symlink() or response.resolve().parent != artifact_root.resolve()
            or hashlib.sha256(response.read_bytes()).hexdigest() != delivery.get("proposed_sha256")
            or not reentry.get("Approval reference") or reentry.get("Approved plan") != str(plan.resolve())
            or hashlib.sha256(plan.read_bytes()).hexdigest() != reentry.get("Approved plan SHA256")):
        raise ValueError("remediation_finalized_run_unverified")
    verify_presentation(recovery_canonical_report(record), response.read_bytes(),
                        delivery.get("presentation_prefix", "").encode(), delivery.get("presentation_suffix", "").encode())
    return (_recover_current_accepted_candidate(artifact_root, prior, source_checkout),
            _verified_recovery_planning(artifact_root, prior))


def _reentry_source(
    artifact_root: Path, approval_reference: str | None, *, planning_recovery: bool = False,
    expected_playbook: str = "feature_delivery", source_checkout: Path | None = None,
) -> dict[str, object]:
    """Check re-entry prerequisites before modifying any current-run artifact."""
    if (not approval_reference or approval_reference.strip().lower() in {"none", "unknown", "not provided"}
            or (approval_reference.strip().startswith("<") and approval_reference.strip().endswith(">"))):
        raise ValueError("approval_reference_required")
    if not planning_recovery:
        if not (artifact_root / "implementation_plan.md").is_file():
            raise ValueError("remediation_approved_plan_unavailable")
        if expected_playbook in {"feature_delivery", "techops_issue_remediation"}:
            try:
                from review_evidence import applicability_errors
            except ModuleNotFoundError:
                from scripts.review_evidence import applicability_errors
            plan_errors = applicability_errors((artifact_root / "implementation_plan.md").read_text())
            if plan_errors:
                raise ValueError("remediation_plan_evidence_required:" + ";".join(plan_errors))
        elif expected_playbook == "sentry_issue_remediation":
            try:
                from validation.api import checked
                from validation.finalization import validate_sentry_artifacts
            except ModuleNotFoundError:
                from scripts.validation.api import checked
                from scripts.validation.finalization import validate_sentry_artifacts
            checked(validate_sentry_artifacts, artifact_root)
    try:
        prior = json.loads((artifact_root / "finalization_packet.json").read_text())
        closure = json.loads((artifact_root / "runtime_closure.json").read_text())
        try:
            from planning_contracts import _runtime_closed, _planning_runtime_closure_errors, terminal_closure_dispatch_errors
            from runtime_checks import terminal_observation_errors
        except ModuleNotFoundError:
            from scripts.planning_contracts import _runtime_closed, _planning_runtime_closure_errors, terminal_closure_dispatch_errors
            from scripts.runtime_checks import terminal_observation_errors
        prior_playbook = Path(str(prior["identity"]["Playbook / version"]).split(" / ", 1)[0]).stem
        if prior_playbook != expected_playbook:
            raise ValueError("remediation_reentry_playbook_mismatch")
        failed_delivery = (not planning_recovery and expected_playbook == "techops_issue_remediation"
                           and prior["identity"].get("Lifecycle") == "remediation")
        planning_source = None
        finalized_delivery = failed_delivery and not (artifact_root / "finalization_failure.json").exists()
        if finalized_delivery:
            candidate, planning_source = _recover_finalized_remediation(artifact_root, prior, source_checkout)
        if failed_delivery and not finalized_delivery:
            failure = json.loads((artifact_root / "finalization_failure.json").read_text())
            blocked_tester = any("worker_activation_rejected_result_pending:tester" in str(error)
                                 for error in failure.get("errors", []))
            blocked_reviewer = any("delivery_dependency_unverified:reviewer" in str(error)
                                   and "forbidden_context_reference:memory_path" in str(error)
                                   for error in failure.get("errors", []))
            blocked_reviewer = blocked_reviewer or _verified_reviewer_replacement_context_failure(artifact_root)
            blocked_reviewer = blocked_reviewer or (any(str(error).startswith("parent_context_nonconformant:")
                                                        for error in failure.get("errors", []))
                and "reviewer" in json.loads((artifact_root / "runtime_dispatches.json").read_text()).get("rejected_results", {})
                and any(row.get("Worker") == "implement" and row.get("Outcome") == "complete"
                        for row in prior.get("worker_results", [])))
            predispatch_context = (not prior.get("workers") and not prior.get("worker_results")
                                   and not json.loads((artifact_root / "runtime_dispatches.json").read_text()).get("thread_mappings")
                                   and (_predispatch_context_failure(failure.get("errors", [])) or any(
                                           "parent_context_nonconformant:forbidden_context_reference:memory_path" in str(error)
                                           for error in failure.get("errors", []))))
            stopped_bootstrap = (not prior.get("workers") and not prior.get("worker_results")
                                 and any(("bootstrap" in str(error).lower() and "before reading" in str(error).lower())
                                         or str(error).startswith("remediation_not_activated:")
                                         for error in failure.get("errors", [])))
            unmerged_context = (not prior.get("workers") and not prior.get("worker_results")
                                and any("parent_context_nonconformant:" in str(error)
                                        for error in failure.get("errors", [])))
            rejected_implementer = (not prior.get("workers") and not prior.get("worker_results")
                and "implementer" in json.loads((artifact_root / "runtime_dispatches.json").read_text()).get("rejected_results", {}))
            if stopped_bootstrap and json.loads((artifact_root / "role_bindings.json").read_text()).get("recovered_candidate"):
                if source_checkout is None:
                    raise ValueError("candidate_recovery_source_checkout_invalid")
                candidate = _recover_stopped_bootstrap_candidate(artifact_root, prior, closure, source_checkout)
            elif predispatch_context and json.loads((artifact_root / "role_bindings.json").read_text()).get("recovered_candidate"):
                if source_checkout is None:
                    raise ValueError("candidate_recovery_source_checkout_invalid")
                candidate = _recover_predispatch_context_candidate(artifact_root, prior, closure, source_checkout)
            elif unmerged_context and not rejected_implementer and json.loads((artifact_root / "role_bindings.json").read_text()).get("recovered_candidate"):
                if source_checkout is None:
                    raise ValueError("candidate_recovery_source_checkout_invalid")
                candidate = _recover_unmerged_candidate(artifact_root, prior, closure, source_checkout)
            elif rejected_implementer and json.loads((artifact_root / "role_bindings.json").read_text()).get("recovered_candidate"):
                if source_checkout is None:
                    raise ValueError("candidate_recovery_source_checkout_invalid")
                candidate = _recover_rejected_candidate(artifact_root, prior, closure, source_checkout)
            elif blocked_reviewer:
                if source_checkout is None:
                    raise ValueError("candidate_recovery_source_checkout_invalid")
                candidate, planning_source = _recover_terminal_reviewer_failure(
                    artifact_root, prior, closure, source_checkout)
            elif (any("parent_context_nonconformant:" in str(error) or "parent_unassigned_thread_read:" in str(error) or
                      "parent context" in str(error).lower() and "nonconformant" in str(error).lower()
                      for error in failure.get("errors", []))
                  or _undispatched_tester_recovery(artifact_root, prior,
                      json.loads((artifact_root / "runtime_dispatches.json").read_text()), failure.get("errors", []))) \
                  and any(row.get("Worker") == "review" and row.get("Outcome") == "complete"
                          for row in prior.get("worker_results", [])):
                if source_checkout is None:
                    raise ValueError("candidate_recovery_source_checkout_invalid")
                candidate, planning_source = _recover_post_delivery_context_failure(
                    artifact_root, prior, closure, source_checkout)
            elif (any(str(error).startswith("parent_context_nonconformant:") for error in failure.get("errors", []))
                  and any(row.get("Worker") == "implement" and row.get("Outcome") == "complete"
                          for row in prior.get("worker_results", []))):
                if source_checkout is None:
                    raise ValueError("candidate_recovery_source_checkout_invalid")
                candidate, planning_source = _recover_terminal_unmerged_review(artifact_root, prior, closure, source_checkout)
            elif blocked_tester:
                if source_checkout is None:
                    raise ValueError("candidate_recovery_source_checkout_invalid")
                candidate, planning_source = _recover_terminal_accepted_remediation(
                    artifact_root, prior, closure, source_checkout)
            else:
                candidate = _recover_failed_remediation(artifact_root, prior, closure, source_checkout=source_checkout)
        if failed_delivery and candidate:
            if approval_reference != prior["reentry"]["Approval reference"]:
                raise ValueError("candidate_recovery_approval_mismatch")
            prior["_recovered_candidate"] = candidate
        if not planning_recovery and not failed_delivery and prior["identity"].get("State") != "ready_for_implementation":
            raise ValueError("remediation_requires_ready_plan")
        if planning_recovery and (expected_playbook == "techops_issue_remediation"
                or prior["identity"].get("State") not in {
                    "awaiting_input", "ready_for_implementation", "completed", "blocked"}):
            failure_path = artifact_root / "finalization_failure.json"
            if expected_playbook == "techops_issue_remediation" and not failure_path.is_file():
                raise ValueError("planning_recovery_requires_terminal_invocation")
            try:
                receipt = json.loads(failure_path.read_text())
            except (OSError, ValueError) as error:
                if expected_playbook == "techops_issue_remediation":
                    raise ValueError("planning_recovery_requires_terminal_invocation") from error
                raise
            if expected_playbook == "techops_issue_remediation" and not isinstance(receipt, dict):
                raise ValueError("planning_recovery_requires_terminal_invocation")
            proof_matches = receipt.get("packet_sha256") == hashlib.sha256(
                (artifact_root / "finalization_packet.json").read_bytes()).hexdigest()
            if receipt.get("packet_snapshot"):
                snapshot = Path(receipt["packet_snapshot"]).resolve()
                if snapshot.parent != artifact_root.resolve():
                    raise ValueError("planning_recovery_requires_terminal_invocation")
                frozen = snapshot.read_bytes()
                frozen_packet = json.loads(frozen)
                proof_matches = (hashlib.sha256(frozen).hexdigest() == receipt.get("snapshot_sha256")
                                 and frozen_packet["identity"]["Run ID"] == receipt.get("run_id")
                                 == prior["identity"]["Run ID"]
                                 and frozen_packet["identity"]["Lifecycle"] == "planning")
            if (receipt.get("status") != "failed" or receipt.get("stage") != "workflow" or not proof_matches
                    or (expected_playbook == "techops_issue_remediation" and not receipt.get("packet_snapshot"))):
                raise ValueError("planning_recovery_requires_terminal_invocation")
        if prior["identity"]["Lifecycle"] != "planning" and not failed_delivery:
            raise ValueError("remediation_reentry_requires_planning_run")
        if prior["identity"]["Requested profile"] not in {"standard", "deep"}:
            raise ValueError("remediation_prior_profile_invalid")
        rows = closure["runtime_closure"]
        closure_packet = {**prior, "identity": {**prior["identity"], "State": "awaiting_input"}}
        if (not _runtime_closed(rows) or _planning_runtime_closure_errors(closure_packet, rows)
                or any(row.get("Receipt owner") != "Coordinator" or not row.get("Closure evidence or blocker")
                       for row in rows)):
            raise ValueError("prior_worker_runtime_closure_required")
        handles = [handle.strip() for row in rows if row["Runtime status"].lower() == "terminal"
                   for handle in re.split(r",|;", row["Completed worker handles"])
                   if handle.strip() and handle.strip().lower() != "none dispatched"]
        if handles and terminal_observation_errors(closure.get("terminal_observations"), handles,
                                                   require_completed=False, allow_inactive_message=True):
            raise ValueError("prior_worker_runtime_closure_required")
        if any(row.get("Last dispatch operation") == "send_message"
               for row in closure.get("terminal_observations", []) if isinstance(row, dict)):
            try:
                from worker_runtime_evidence import dispatch_audit_errors
            except ModuleNotFoundError:
                from scripts.worker_runtime_evidence import dispatch_audit_errors
            packet_path = artifact_root / "finalization_packet.json"
            if (terminal_closure_dispatch_errors(packet_path, closure["terminal_observations"], historical_recovery=True)
                    or dispatch_audit_errors({"runtime_audits": []}, packet_path, closure_only=True, historical_recovery=True)):
                raise ValueError("prior_worker_runtime_closure_required")
        if planning_source is not None:
            for field in ("work_item", "decisions", "claims", "actions", "evidence", "techops_checks",
                          "reproduction", "integration_decision", "playbook_selection"):
                if field in planning_source:
                    prior[field] = planning_source[field]
        return prior
    except (OSError, KeyError, TypeError, AttributeError, json.JSONDecodeError) as error:
        raise ValueError(f"remediation_reentry_artifact_invalid:{error}") from error


def _configure_remediation_result_contracts(artifact_root: Path, worker_contracts: dict[str, object]) -> None:
    """Give delivery workers the same typed, Coordinator-merged result contract across playbooks."""
    try:
        from merge_techops_result import FEATURE_REMEDIATION_WORKERS
    except ModuleNotFoundError:
        from scripts.merge_techops_result import FEATURE_REMEDIATION_WORKERS
    template = json.loads((ROOT / "templates" / "finalization_packet.json").read_text())
    result_fields = {name: list(template[name][0]) for name in
                     ("worker_results", "evidence", "claims", "decisions", "actions")}
    output_names = {"implementer": "implement_result.md", "reviewer": "code_review.md",
                    "tester": "validation_report.md"}
    for agent, (worker, namespace) in FEATURE_REMEDIATION_WORKERS.items():
        contract = worker_contracts[agent]
        output_path = artifact_root / output_names[agent]
        if agent in {"reviewer", "tester"}:
            contract["instructions"] += (
                f" Return the complete {output_path.name} contents in the JSON final answer's output field, "
                "using the prepared framework template and all required sections. Do not write the file "
                "directly; the Coordinator merger publishes that field to this prepared path."
            )
        contract.update({
            "worker": worker,
            "id_namespace": namespace,
            "output": str(output_path),
            "result": str(artifact_root / f"{worker}_result.json"),
            "result_hash_required": True,
            "result_response": "strict_json_final_answer",
            "result_fields": result_fields,
            "result_instructions": (
                "Do not edit Coordinator-owned packet rows or write assigned output files directly. "
                "Before ending, return exactly one strict JSON final answer with output (the assigned "
                "worker artifact contents) and result (the current run_id, one worker_result object with "
                "the exact worker_results fields, and evidence/claims/decisions/actions arrays using "
                "result_fields). The result key is worker_result, a single object, never worker_results "
                "or an array; result_fields.worker_results lists its field names. All row field values "
                "must be strings, including references. Set Worker to exactly " + worker +
                "; Outcome is complete, failed, or blocked. For your own rows use IDs in this order: " +
                ", ".join(f"{prefix}-{namespace}-001" for prefix in ("E", "CL", "DE", "A")) +
                " for evidence, claims, decisions, and actions respectively; use unique suffixes. "
                "Reference upstream IDs unchanged. The Coordinator runs the "
                "prepared result merger with your provider role and current trace; it verifies and registers "
                "your accepted result and execution ledger row before activating the next role. A missing "
                "Coordinator row is repaired by rerunning that command with the same trace, not by editing "
                "the packet or redispatching you."
            ),
        })


def _recover_unactivated_remediation(artifact_root: Path, bindings: dict) -> tuple[Path, bytes, bytes] | None:
    """Identify a failed TechOps delivery before any native worker dispatch."""
    failure_path = artifact_root / "finalization_failure.json"
    if not failure_path.is_file() or not bindings.get("runtime_evidence"):
        return None
    try:
        raw = failure_path.read_bytes()
        failure = json.loads(raw)
        packet_path = artifact_root / "finalization_packet.json"
        packet = json.loads(packet_path.read_text())
        identity = packet["identity"]
        reentry = packet["reentry"]
        snapshot = Path(failure["packet_snapshot"])
        frozen = snapshot.read_bytes()
        previous = json.loads(frozen)
        plan = artifact_root / "implementation_plan.md"
        ledger = json.loads((artifact_root / "runtime_dispatches.json").read_text())
        closure_bytes = (artifact_root / "runtime_closure.json").read_bytes()
        closure = json.loads(closure_bytes)["runtime_closure"]
        try:
            from worker_runtime_evidence import dispatch_audit_errors
        except ModuleNotFoundError:
            from scripts.worker_runtime_evidence import dispatch_audit_errors
        recoverable_error = (_predispatch_context_failure(failure.get("errors", [])) or
                             (failure.get("errors") == ["worker_activation_requires_planning_recovery"]
                              and failure.get("historical_errors") == ["remediation_not_activated"]))
        if not (bindings.get("playbook") == "techops_issue_remediation"
                and identity.get("Lifecycle") == "remediation"
                and failure.get("status") == "failed" and failure.get("stage") == "workflow"
                and recoverable_error
                and failure.get("runtime_closure") == "terminal" and failure.get("reported_by") == "Coordinator"
                and int(failure.get("attempt_count", 0)) == 0
                and identity["Run ID"] == failure.get("run_id") == bindings.get("run_id")
                and snapshot.resolve().parent == artifact_root.resolve()
                and hashlib.sha256(frozen).hexdigest() == failure.get("snapshot_sha256") == failure.get("packet_sha256")
                and previous["identity"]["Run ID"] == identity["Run ID"]
                and previous["identity"].get("Lifecycle") == "remediation"
                and previous.get("reentry") == reentry and previous.get("workers") == []
                and previous.get("worker_results") == [] and not previous.get("runtime_audits")
                and packet.get("workers") == []
                and packet.get("worker_results") == [] and not packet.get("runtime_audits")
                and reentry.get("Approval reference") and reentry.get("Prior run ID")
                and reentry.get("Approved plan") == str(plan.resolve())
                and hashlib.sha256(plan.read_bytes()).hexdigest() == reentry.get("Approved plan SHA256")
                and ledger.get("events") == [] and ledger.get("failed_dispatches") == []
                and ledger.get("thread_mappings") == {}
                and len(closure) == 1 and closure[0].get("Runtime status") == "Terminal"
                and closure[0].get("Remaining active handles") == "0"
                and closure[0].get("Completed worker handles") == "None dispatched"):
            return None
        audit_errors = dispatch_audit_errors(packet, packet_path, closure_only=True)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, json.JSONDecodeError):
        return None
    if audit_errors:
        raise ValueError("remediation_recovery_evidence_unverified:" + ";".join(audit_errors))
    return failure_path, raw, closure_bytes


def resolve_bindings(playbook: str, runtime_agents: Path | None) -> dict[str, object]:
    playbook = _playbook_name(playbook)
    names = SENTRY_AGENTS if playbook == "sentry_issue_remediation" else GENERIC_AGENTS
    runtime_files = [runtime_agents / f"{name}.toml" for name in names] if runtime_agents else []
    resolved_runtime = [path for path in runtime_files if path.is_file()]
    if resolved_runtime:
        symlink_count = sum(path.is_symlink() for path in resolved_runtime)
        provider_status = f"runtime / resolved ({len(resolved_runtime)} definitions; {symlink_count} symlinked)"
    else:
        provider_status = "bundled / resolved"
    return {
        "framework_package": {
            "root": str(ROOT.resolve()),
            "plugin_sha256": hashlib.sha256((ROOT / ".codex-plugin/plugin.json").read_bytes()).hexdigest(),
        },
        "baseline_id": _baseline_id(),
        "playbook": playbook,
        "provider_runtime_configuration": str(runtime_agents) if runtime_agents else "Not provided",
        "provider_configuration_source_status": provider_status,
        "provider_tool_mapping": CODEX_TOOL_MAPPING,
        "coordinator_execution": {
            "role": "sentry_orchestrator" if playbook == "sentry_issue_remediation" else "orchestrator",
            "mode": "active_parent",
            "dedicated_worker_spawned": False,
            "description": "The active parent session performs orchestration and coordination.",
        },
        "bindings": {name: _agent_binding(name, runtime_agents) for name in names},
    }


def _archive_recovery(artifact_root: Path, run_id: str) -> Path:
    """Snapshot distinct bytes once; publish the run manifest atomically."""
    runs = artifact_root / "runs"
    runs.mkdir(exist_ok=True)
    destination = runs / re.sub(r"[^A-Za-z0-9._-]", "_", run_id)
    controls = {"finalization_packet.json", "work_record.md", "finalization_failure.json", "runtime_closure.json"}
    record = artifact_root / "work_record.md"
    if record.is_file():
        controls.update(re.findall(r"finalization_snapshot\.[0-9a-f]{64}\.json", record.read_text()))
    sources = sorted(path for entry in artifact_root.iterdir() if entry.name != "runs"
                     for path in ([entry] if entry.is_file() else entry.rglob("*")) if path.is_file())
    entries = []
    for path in sources:
        if not path.resolve().is_relative_to(artifact_root.resolve()):
            raise ValueError("recovery_archive_source_outside_run")
        relative = path.relative_to(artifact_root).as_posix()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        entries.append({"path": relative, "sha256": digest,
                        "snapshot": relative if relative in controls else f"../_objects/{digest}"})
    manifest = {"schema_version": 1, "run_id": run_id, "files": entries}
    if destination.exists():
        manifest_path = destination / "archive_manifest.json"
        if manifest_path.is_file() and json.loads(manifest_path.read_text()) == manifest:
            for entry in entries:
                target = destination / entry["snapshot"]
                if hashlib.sha256(target.read_bytes()).hexdigest() != entry["sha256"]:
                    raise ValueError("recovery_archive_snapshot_conflict")
            return destination
        if any(destination.iterdir()):
            raise ValueError("prior_run_archive_exists")
        destination.rmdir()
    staging = Path(tempfile.mkdtemp(prefix=".archive-", dir=runs))
    try:
        objects = runs / "_objects"
        objects.mkdir(exist_ok=True)
        for source, entry in zip(sources, entries):
            data = source.read_bytes()
            if hashlib.sha256(data).hexdigest() != entry["sha256"]:
                raise ValueError("recovery_archive_source_changed")
            target = staging / entry["path"] if entry["path"] in controls else objects / entry["sha256"]
            if target.exists():
                if target.read_bytes() != data:
                    raise ValueError("recovery_archive_snapshot_conflict")
            else:
                with target.open("xb") as stream:
                    stream.write(data)
        (staging / "archive_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        staging.rename(destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return destination


def _archive_existing_run(
    artifact_root: Path, archive_stale_run: bool, run_inputs: dict[str, object] | None = None,
    parent_context: dict | None = None, input_manifest: Path | None = None, *, fresh_start: bool = False,
) -> str | None:
    try:
        from provider_runtime import closed_run_id as published_run_id
    except ModuleNotFoundError:
        from scripts.provider_runtime import closed_run_id as published_run_id
    archive_run_id = None if fresh_start else published_run_id(artifact_root)
    observed_closed_id = (parent_context or {}).get("closed_run_id") or (parent_context or {}).get("closed_zero_dispatch_run_id")
    if observed_closed_id and observed_closed_id != archive_run_id:
        raise ValueError("prior_run_archive_blocked:closed_run_receipts_changed")
    record = artifact_root / "work_record.md"
    if not record.is_file():
        if not fresh_start and artifact_root.is_dir() and any((artifact_root / name).is_file() for name in ORPHANED_RUN_RECEIPTS):
            raise ValueError("orphaned_run_control_receipts_without_work_record")
        if not artifact_root.is_dir() or not any(
                path.name != "runs" and (input_manifest is None or path != input_manifest)
                for path in artifact_root.iterdir()):
            return None
    text = record.read_text() if not fresh_start and record.is_file() else ""
    state = _table_value(text, "State") if text else None
    if fresh_start:
        # Start preserves prior bytes; their outcome and findings do not become current evidence.
        for name in ("role_bindings.json", "runtime_dispatches.json"):
            path = artifact_root / name
            if path.is_symlink():
                raise ValueError("prior_run_control_symlink:" + name)
            if not path.is_file():
                continue
            try:
                saved = json.loads(path.read_text())
            except (ValueError, UnicodeError):
                continue  # Incomplete control records are preserved, not interpreted as closure.
            if not isinstance(saved, dict):
                continue
            if name == "role_bindings.json":
                candidate = saved.get("run_id")
                if isinstance(candidate, str) and re.fullmatch(re.escape(artifact_root.name) + r"-[A-Za-z0-9._-]+", candidate):
                    archive_run_id = candidate
                continue
            timing = saved.get("timing", {})
            open_intervals = timing.get("open_worker_intervals", 0) if isinstance(timing, dict) else 0
            inventory = saved.get("inventories", [])
            latest = inventory[-1] if isinstance(inventory, list) and inventory and isinstance(inventory[-1], dict) else {}
            agents = latest.get("raw_response", {}).get("agents", []) if isinstance(latest.get("raw_response", {}), dict) else []
            active = type(open_intervals) is int and open_intervals > 0
            mappings = saved.get("thread_mappings", {})
            if isinstance(agents, list) and isinstance(mappings, dict):
                for row in agents:
                    if not isinstance(row, dict) or row.get("agent_name") not in mappings:
                        continue
                    status = row.get("agent_status")
                    if isinstance(status, dict) and len(status) == 1:
                        status = next(iter(status))
                    active = active or isinstance(status, str) and status in {"running", "pending_init", "waiting"}
            if active:
                try:
                    from worker_runtime_evidence import terminal_closure
                except ModuleNotFoundError:
                    from scripts.worker_runtime_evidence import terminal_closure
                try:
                    terminal_closure(saved)
                except (ValueError, KeyError, TypeError, AttributeError):
                    raise ValueError("run_already_active: prior control evidence records active workers") from None
    if archive_run_id and not fresh_start:
        bindings = json.loads((artifact_root / "role_bindings.json").read_text())
        if (parent_context and bindings.get("parent_context", {}).get("parent_thread_id")
                == parent_context.get("parent_thread_id")):
            try:
                from provider_runtime import read_runtime_events
                from worker_runtime_evidence import terminal_closure
            except ModuleNotFoundError:
                from scripts.provider_runtime import read_runtime_events
                from scripts.worker_runtime_evidence import terminal_closure
            try:
                saved = json.loads((artifact_root / "runtime_dispatches.json").read_text())
                source = Path(parent_context["provider_session"])
                sources = list(saved.get("identity_sessions", []))
                if Path(saved["provider_session"]).resolve() != source.resolve():
                    sources.append(saved["provider_session"])
                current = read_runtime_events(source, parent_context["parent_thread_id"], saved["run_started_at"],
                                              tuple(Path(value) for value in dict.fromkeys(sources)))
                if any(saved.get(field, []) != current.get(field, [])
                       for field in ("events", "thread_mappings", "failed_dispatches")):
                    raise ValueError("runtime_dispatch_ledger_stale")
                terminal_closure(current)
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
                raise ValueError("prior_run_archive_blocked:" + str(error)) from error
        state = "blocked"
    if not fresh_start and record.is_file() and state not in TERMINAL_STATES:
        if not archive_stale_run:
            raise ValueError("existing_run_not_terminal")
    try:
        from provider_runtime import stale_run_status_errors
    except ModuleNotFoundError:
        from scripts.provider_runtime import stale_run_status_errors
    unstarted_template = (state == UNINITIALIZED_WORK_RECORD_STATE
                          and not _table_value(text, "Run ID")
                          and not (artifact_root / "runtime_dispatches.json").is_file())
    status_errors = ([] if fresh_start and parent_context is None else stale_run_status_errors(
        parent_context, state, require_prior_dispatch_ledger=not fresh_start and bool(text)
        and not (state == "intake" or unstarted_template),
    ))
    if status_errors:
        reason = "stale_run_archive_blocked" if state not in TERMINAL_STATES else "prior_run_archive_blocked"
        raise ValueError(reason + ":" + ";".join(status_errors))
    if fresh_start:
        run_id = archive_run_id or datetime.now(UTC).strftime("stale-%Y%m%dT%H%M%S%fZ")
    elif state not in TERMINAL_STATES:
        run_id = datetime.now(UTC).strftime("stale-%Y%m%dT%H%M%S%fZ")
    else:
        run_id = archive_run_id or _table_value(text, "Run ID")
    if not run_id or run_id in {"Unknown", "None"}:
        run_id = datetime.now(UTC).strftime("run-%Y%m%dT%H%M%S%fZ")
    destination = artifact_root / "runs" / re.sub(r"[^A-Za-z0-9._-]", "_", run_id)
    if fresh_start:
        suffix = 2
        while destination.exists():
            destination = artifact_root / "runs" / (run_id + "." + str(suffix))
            suffix += 1
    elif destination.exists():
        raise ValueError("prior_run_archive_exists")
    directories = {path for row in (run_inputs or {}).get("inputs", []) if not is_code_scope(row)
                   for path in local_input_paths(row)
                   if path.is_dir() and path.is_relative_to(artifact_root.resolve())
                   and not path.is_relative_to((artifact_root / "runs").resolve())}
    original_names = {path.name for path in artifact_root.iterdir() if path.name != "runs"}
    moved = []
    destination.mkdir(parents=True)
    relocated = {}
    try:
        for name in sorted(original_names):
            shutil.move(str(artifact_root / name), destination / name)
            moved.append(name)
        for source in sorted(directories):
            key = hashlib.sha256(str(source).encode()).hexdigest()
            target = (artifact_root / "input_snapshots" / "directories" / key / source.name).resolve()
            shutil.copytree(destination / source.relative_to(artifact_root.resolve()), target, symlinks=True)
            relocated[str(source)] = str(target)
    except Exception:
        for name in moved + (["input_snapshots"] if "input_snapshots" not in original_names else []):
            active = artifact_root / name
            if active.is_dir() and not active.is_symlink():
                shutil.rmtree(active)
            elif active.exists() or active.is_symlink():
                active.unlink()
        for name in moved:
            shutil.move(str(destination / name), artifact_root / name)
        destination.rmdir()
        raise
    for row in (run_inputs or {}).get("inputs", []):
        if row.get("path") in relocated:
            row.setdefault("Original source path", row["path"])
            row["path"] = relocated[row["path"]]
        elif any(path in relocated for path in row.get("paths", [])):
            row.setdefault("Original source paths", row["paths"])
            row["paths"] = [relocated.get(path, path) for path in row["paths"]]
    return str(destination)


def prepare_run(
    execution_repository: Path,
    work_item: str,
    playbook: str,
    runtime_agents: Path | None,
    continuation: bool,
    archive_stale_run: bool = False,
    input_manifest: Path | None = None,
    workflow_objective: str | None = None,
    requested_outcome: str | None = None,
    started_at: str | None = None,
    timebox_minutes: int | None = None,
    primary_question: str | None = None,
    success_criterion: str | None = None,
    remediation_reentry: bool = False,
    approval_reference: str | None = None,
    planning_recovery: bool = False,
    provider_session: Path | None = None,
    lifecycle: str | None = None,
    execution_profile: str | None = None,
    input_data: dict[str, object] | None = None,
    authorize_prior_parent_thread: str | None = None,
) -> dict[str, object]:
    playbook = _playbook_name(playbook)
    try:
        from provider_runtime import current_parent_session, scoped_prior_run_status_thread_ids
    except ModuleNotFoundError:
        from scripts.provider_runtime import current_parent_session, scoped_prior_run_status_thread_ids
    provider_session = current_parent_session(provider_session)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", work_item):
        raise ValueError("invalid_work_item")
    if not execution_repository.resolve().is_dir():
        raise ValueError("execution_repository_unavailable")
    resolved_execution_repository, source_checkout = resolve_repository_paths(execution_repository)
    if continuation and archive_stale_run:
        raise ValueError("continuation_cannot_archive_stale_run")
    if remediation_reentry and (not continuation or playbook not in {
            "feature_delivery", "sentry_issue_remediation", "techops_issue_remediation"}):
        raise ValueError("remediation_reentry_requires_supported_playbook_continuation")
    if planning_recovery and (not continuation or playbook not in {
            "feature_delivery", "techops_issue_remediation"} or remediation_reentry):
        raise ValueError("planning_recovery_requires_supported_playbook_continuation")
    if approval_reference and not (remediation_reentry or planning_recovery):
        raise ValueError("approval_reference_requires_reentry_or_recovery")
    goal_defaults_used = playbook in PLAYBOOK_DEFAULT_GOALS and (
        (playbook != "techops_issue_remediation" or planning_recovery)
        and workflow_objective is None and requested_outcome is None
    )
    if goal_defaults_used:
        defaults = PLAYBOOK_DEFAULT_GOALS[playbook]
        workflow_objective = str(defaults["workflow_objective"])
        requested_outcome = str(defaults["requested_outcome"])
        if remediation_reentry:
            workflow_objective, requested_outcome = "feature_implementation", "feature_delivery"
        elif continuation and playbook == "feature_delivery":
            existing = resolved_execution_repository / ".thoughts" / work_item / "finalization_packet.json"
            if existing.is_file() and json.loads(existing.read_text()).get("identity", {}).get("Lifecycle") == "remediation":
                workflow_objective, requested_outcome = "feature_implementation", "feature_delivery"
    if playbook == "feature_delivery" and workflow_objective == "feature_implementation" and not remediation_reentry:
        existing = resolved_execution_repository / ".thoughts" / work_item / "finalization_packet.json"
        if not continuation or not existing.is_file() or json.loads(existing.read_text())["identity"]["Lifecycle"] != "remediation":
            raise ValueError("feature_implementation_requires_remediation_reentry")
    if (remediation_reentry and playbook == "feature_delivery"
            and (workflow_objective, requested_outcome) != ("feature_implementation", "feature_delivery")):
        raise ValueError("run_goal_conflict:remediation_requires_feature_implementation_and_feature_delivery")
    if playbook == "technical_spike":
        defaults = _playbook_defaults(playbook)
        resolved_timebox_minutes = (
            timebox_minutes if timebox_minutes is not None else defaults["timebox_minutes"]
        )
        success_source = "Current user request" if success_criterion is not None else "Selected playbook defaults"
        success_authority = (
            "Explicit current-run success criterion"
            if success_criterion is not None else "Technical Spike playbook configuration"
        )
        success_criterion = success_criterion or str(defaults["success_criterion"])
    else:
        resolved_timebox_minutes = timebox_minutes
        success_source = "Current user request"
        success_authority = "Explicit current-run success criterion"
    budget = _run_budget(started_at, resolved_timebox_minutes)
    if playbook == "technical_spike":
        primary_question = _required_spike_bound(primary_question, "primary_question")
        success_criterion = _required_spike_bound(success_criterion, "success_criterion")
    repository_row = _repository_row(source_checkout)
    repository_row["Repository role"] = "Source checkout"
    repository_row["Declared path"] = str(execution_repository.resolve())
    artifact_root = resolved_execution_repository / ".thoughts" / work_item
    previous_profile = None
    if continuation and (artifact_root / "role_bindings.json").is_file():
        previous_profile = json.loads((artifact_root / "role_bindings.json").read_text()).get("execution_profile")
    if continuation and (artifact_root / "finalization_packet.json").is_file():
        recorded_profile = json.loads((artifact_root / "finalization_packet.json").read_text()).get("identity", {}).get("Requested profile")
        if previous_profile and recorded_profile != previous_profile:
            raise ValueError("prepared_execution_profile_mismatch:expected=" + previous_profile + ";received=" + str(recorded_profile))
        previous_profile = previous_profile or recorded_profile
        if previous_profile not in {"standard", "deep"}:
            previous_profile = None
    if execution_profile is not None and execution_profile not in {"standard", "deep"}:
        raise ValueError("execution_profile_invalid:" + execution_profile)
    if previous_profile and execution_profile and execution_profile != previous_profile:
        raise ValueError("execution_profile_conflict:expected=" + previous_profile + ";received=" + execution_profile)
    resolved_profile = execution_profile or previous_profile or "standard"
    previous_lifecycle = None
    if continuation and not remediation_reentry:
        previous_bindings = artifact_root / "role_bindings.json"
        if previous_bindings.is_file():
            previous_lifecycle = json.loads(previous_bindings.read_text()).get("lifecycle")
        previous_packet = artifact_root / "finalization_packet.json"
        if previous_packet.is_file():
            recorded = json.loads(previous_packet.read_text()).get("identity", {}).get("Lifecycle")
            if previous_lifecycle and recorded and recorded != previous_lifecycle:
                raise ValueError("prepared_lifecycle_mismatch:expected=" + previous_lifecycle + ";received=" + str(recorded))
            previous_lifecycle = previous_lifecycle or recorded
    resolved_lifecycle = "remediation" if remediation_reentry else previous_lifecycle or "planning"
    if resolved_lifecycle not in {"planning", "remediation"} or (
            playbook == "technical_spike" and resolved_lifecycle != "planning"):
        raise ValueError("prepared_lifecycle_unsupported:" + str(resolved_lifecycle))
    if playbook in {"feature_delivery", "techops_issue_remediation"} and resolved_lifecycle == "remediation":
        repository_row["Repository role"] = "Execution repository"
    if lifecycle is not None and lifecycle != resolved_lifecycle:
        raise ValueError("lifecycle_conflict:expected=" + resolved_lifecycle + ";received=" + lifecycle
                         + ";remediation requires approved reentry")
    legacy_root = source_checkout / ".thoughts" / work_item
    if continuation and legacy_root != artifact_root and legacy_root.exists() and not artifact_root.exists():
        raise ValueError("legacy_worktree_artifacts_require_explicit_migration")
    # Validate supplied input and provider bindings before creating, archiving, or
    # overwriting any run artifact. This makes invalid retries transactional.
    if input_manifest is not None and input_data is not None:
        raise ValueError("run_input_manifest_sources_conflict")
    if (planning_recovery and playbook == "techops_issue_remediation"
            and input_manifest is None and input_data is None):
        saved_inputs = artifact_root / RUN_INPUTS_FILENAME
        if not saved_inputs.is_file():
            raise ValueError("run_input_manifest_required")
        input_manifest = saved_inputs
    if playbook == "feature_delivery" and input_manifest is None and input_data is None:
        raise ValueError("run_input_manifest_required")
    validated_supplied = (load_manifest(input_manifest, explicit=True) if input_manifest else
                          validate_manifest(input_data, explicit=True) if input_data is not None else None)
    previous_run_bindings = {}
    if continuation and not (remediation_reentry or planning_recovery) and (artifact_root / "role_bindings.json").is_file():
        previous_run_bindings = json.loads((artifact_root / "role_bindings.json").read_text())
        previous_source = previous_run_bindings.get("source_checkout")
        if previous_source and Path(previous_source).resolve() != source_checkout.resolve():
            raise ValueError("continuation_source_checkout_mismatch:expected=" + str(Path(previous_source).resolve())
                             + ";received=" + str(source_checkout.resolve()))
        previous_parent = previous_run_bindings.get("parent_context", {})
        if provider_session is None and previous_parent:
            provider_session = Path(previous_parent["provider_session"])
    parent_context = None
    if provider_session:
        try:
            from provider_runtime import parent_context_audit
        except ModuleNotFoundError:
            from scripts.provider_runtime import parent_context_audit
        assigned = []
        for row in (validated_supplied or {}).get("inputs", []):
            expected_use = str(row.get("Expected use", "")).lower()
            if (str(row.get("Status", "")).lower() not in {"rejected", "denied", "superseded"}
                    and not any(value in expected_use for value in ("do not read", "without reading", "preserve only"))):
                assigned.extend(str(path) for path in local_input_paths(row))
                assigned.append(str(row.get("Source or path", "")))
        previous_parent = previous_run_bindings.get("parent_context", {})
        control = dict(previous_run_bindings.get("runtime_evidence", {}))
        prior_collector = None
        if control and previous_run_bindings.get("framework_package"):
            pinned_root = Path(previous_run_bindings["framework_package"]["root"]).resolve()
            prior_collector = Path(control["collector"]).resolve()
            if prior_collector != pinned_root / "scripts" / "worker_runtime_evidence.py":
                raise ValueError("continuation_collector_package_mismatch")
        if planning_recovery and not control and (artifact_root / "role_bindings.json").is_file():
            saved_bindings = json.loads((artifact_root / "role_bindings.json").read_text())
            control = dict(saved_bindings.get("runtime_evidence", {}))
        if control:
            control["collector"] = str(Path(__file__).with_name("worker_runtime_evidence.py"))
        related_thread_ids = (tuple(previous_parent["related_run_thread_ids"])
                              if "related_run_thread_ids" in previous_parent else None)
        if not continuation:
            related_thread_ids = ()
        if authorize_prior_parent_thread is not None:
            if previous_parent:
                if authorize_prior_parent_thread != previous_parent.get("parent_thread_id"):
                    raise ValueError("stale_run_status_authorization_mismatch")
            else:
                with provider_session.open() as stream:
                    current_thread_id = json.loads(next(stream, "")).get("payload", {}).get("id")
                related_thread_ids = scoped_prior_run_status_thread_ids(
                    artifact_root, current_thread_id, authorize_prior_parent_thread)
        if previous_parent and Path(previous_parent["provider_session"]).resolve() != provider_session.resolve():
            control["identity_sessions"] = list(dict.fromkeys([
                *control.get("identity_sessions", []), previous_parent["provider_session"]]))
        parent_context = parent_context_audit(provider_session, artifact_root=artifact_root,
            input_paths=tuple(assigned), expected_thread_id=previous_parent.get("parent_thread_id"),
            runtime_evidence=control,
            related_run_thread_ids=related_thread_ids,
            prior_dispatch_ledger_present=previous_parent.get("prior_run_dispatch_ledger_present"),
            audit_previous_collector=prior_collector)
        if parent_context["status"] != "passed":
            raise ValueError("parent_context_nonconformant:" + ";".join(parent_context["errors"]))
        if previous_parent and previous_parent["parent_thread_id"] != parent_context["parent_thread_id"]:
            raise ValueError("continuation_parent_identity_mismatch: continue the run in its original chat")
        if previous_parent:
            pinned_root = None
            if previous_run_bindings.get("framework_package") and previous_run_bindings.get("runtime_evidence"):
                pinned_root = Path(previous_run_bindings["framework_package"]["root"]).resolve()
                pinned_collector = Path(previous_run_bindings["runtime_evidence"]["collector"]).resolve()
                if pinned_collector != pinned_root / "scripts" / "worker_runtime_evidence.py":
                    raise ValueError("continuation_collector_package_mismatch")
            previous_context = parent_context_audit(Path(previous_parent["provider_session"]), artifact_root=artifact_root,
                input_paths=tuple(previous_parent["input_paths"]), expected_thread_id=previous_parent["parent_thread_id"],
                expected_turn_id=previous_parent["turn_id"], runtime_evidence=previous_run_bindings.get("runtime_evidence"),
                related_run_thread_ids=(tuple(previous_parent["related_run_thread_ids"])
                                        if "related_run_thread_ids" in previous_parent else None),
                prior_dispatch_ledger_present=previous_parent.get("prior_run_dispatch_ledger_present"),
                audit_script_dir=pinned_root / "scripts" if pinned_root else None)
            if previous_context["status"] != "passed":
                if not _can_defer_reviewer_parent_audit(artifact_root, previous_context, remediation_reentry):
                    raise ValueError("continuation_parent_context_nonconformant:" + ";".join(previous_context["errors"]))
    if playbook == "sentry_issue_remediation" and validated_supplied:
        retain_source_releases(validated_supplied, provider_session)
    prior = (_reentry_source(artifact_root, approval_reference, planning_recovery=planning_recovery,
                             expected_playbook=playbook, source_checkout=source_checkout)
             if remediation_reentry or planning_recovery else None)
    unactivated_failure = None
    if continuation and not prior:
        existing_packet = artifact_root / "finalization_packet.json"
        if playbook == "feature_delivery" and existing_packet.is_file():
            identity = json.loads(existing_packet.read_text())["identity"]
            record_path = artifact_root / "work_record.md"
            record_text = record_path.read_text() if record_path.is_file() else ""
            failure_path = artifact_root / "finalization_failure.json"
            failure = json.loads(failure_path.read_text()) if failure_path.is_file() else {}
            failed_terminal = (isinstance(failure, dict) and failure.get("status") == "failed"
                               and failure.get("phase") == "terminal" and failure.get("terminal_failure") is True
                               and failure.get("handoff_packet_sha256") == hashlib.sha256(existing_packet.read_bytes()).hexdigest())
            if (identity.get("Lifecycle") == "planning" and identity.get("Workflow outcome") == "completed"
                    and _table_value(record_text, "Run ID") == identity.get("Run ID")
                    and _table_value(record_text, "State") in TERMINAL_STATES and not failed_terminal):
                raise ValueError("planning_recovery_required:terminal_execution")
        failure_path = artifact_root / "finalization_failure.json"
        if failure_path.is_file():
            failure = json.loads(failure_path.read_text())
            if not isinstance(failure, dict):
                raise ValueError("finalization_receipt_invalid")
            if failure.get("status") == "failed" and int(failure.get("attempt_count", 0)) >= 2:
                raise ValueError("finalization_recovery_required:exhausted_attempts")
            try:
                from provider_runtime import closed_zero_dispatch_run_id
                from worker_runtime_evidence import dispatch_audit_errors
            except ModuleNotFoundError:
                from scripts.provider_runtime import closed_zero_dispatch_run_id
                from scripts.worker_runtime_evidence import dispatch_audit_errors
            if (provider_session is not None and previous_run_bindings.get("parent_context")
                    and closed_zero_dispatch_run_id(artifact_root) == previous_run_bindings.get("run_id")):
                errors = dispatch_audit_errors({"runtime_audits": []}, existing_packet, closure_only=True)
                if errors:
                    raise ValueError("continuation_runtime_nonconformant:" + ";".join(errors))
                unactivated_failure = (failure_path, failure_path.read_bytes(),
                                       (artifact_root / "runtime_closure.json").read_bytes())
            elif (playbook == "techops_issue_remediation" and provider_session is not None
                    and previous_run_bindings.get("parent_context")):
                unactivated_failure = _recover_unactivated_remediation(artifact_root, previous_run_bindings)
    if planning_recovery and (workflow_objective, requested_outcome) != ("implementation_planning", "implementation_plan"):
        raise ValueError("planning_recovery_requires_implementation_planning")
    if prior and goal_defaults_used:
        validated_supplied["inputs"] = [row for row in validated_supplied["inputs"] if row["Input ID"] not in {"RUN-GOAL-001", "RUN-GOAL-002"}]
    _validate_run_goal(
        playbook, workflow_objective, requested_outcome, validated_supplied,
        allow_default_provenance=goal_defaults_used,
    )
    resolved_runtime_agents = runtime_agents.resolve() if runtime_agents else None
    manifest = resolve_bindings(playbook, resolved_runtime_agents)
    manifest["prepared_at"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    manifest["execution_repository"] = str(resolved_execution_repository)
    manifest["source_checkout"] = str(source_checkout)
    manifest["coordinator_execution"]["execution_repository"] = str(resolved_execution_repository)
    manifest["coordinator_execution"]["source_checkout"] = str(source_checkout)
    if continuation and not (artifact_root / "work_record.md").is_file():
        raise ValueError("continuation_record_unavailable")
    input_bytes: dict[str, bytes] = {}
    if validated_supplied:
        preview = _snapshot_input_files(artifact_root, validated_supplied, persist=False, input_bytes=input_bytes)
        if continuation and not prior:
            preview = _merge_input_rows(
                load_manifest(artifact_root / RUN_INPUTS_FILENAME, explicit=False), tuple(preview["inputs"]),
            )
        if playbook == "feature_delivery":
            _with_run_goal(preview, workflow_objective, requested_outcome,
                           "Selected playbook defaults" if goal_defaults_used else "Current user request",
                           str(PLAYBOOK_DEFAULT_GOALS[playbook]["authority"]) if goal_defaults_used else "Explicit user outcome")
    continued_candidate = _continued_candidate(artifact_root, previous_run_bindings) if continuation and not prior else None
    artifact_root.mkdir(parents=True, exist_ok=True)
    archived = None if continuation else _archive_existing_run(
        artifact_root, archive_stale_run, validated_supplied, parent_context,
        input_manifest.resolve() if input_manifest else None, fresh_start=True,
    )
    recovered_candidate = prior.get("_recovered_candidate") if prior else continued_candidate
    if recovered_candidate and prior:
        try:
            from recovery_candidate import snapshot_candidate, verify_existing_snapshot
        except ModuleNotFoundError:
            from scripts.recovery_candidate import snapshot_candidate, verify_existing_snapshot
        destination = artifact_root / ("recovery_candidate." + re.sub(r"[^A-Za-z0-9._-]", "_", prior["identity"]["Run ID"]))
        contents = recovered_candidate.pop("_contents", None)
        if destination.exists() or destination.is_symlink():
            verify_existing_snapshot(destination, recovered_candidate["files"])
        elif contents is None:
            snapshot_candidate(resolved_execution_repository, destination, recovered_candidate["files"])
        else:
            try:
                from recovery_candidate import snapshot_replayed_candidate
            except ModuleNotFoundError:
                from scripts.recovery_candidate import snapshot_replayed_candidate
            snapshot_replayed_candidate(destination, recovered_candidate["files"], contents)
        recovered_candidate = {**recovered_candidate, "snapshot_run_id": prior["identity"]["Run ID"], "snapshot_files": {
            str(destination / path): digest for path, digest in recovered_candidate["files"].items()}}
        manifest["recovered_candidate"] = recovered_candidate
    elif recovered_candidate:
        manifest["recovered_candidate"] = recovered_candidate
    if prior:
        archived_path = _archive_recovery(artifact_root, prior["identity"]["Run ID"])
        archived = str(archived_path)
        for name in ("pre_release_check.json", "finalization_failure.json", "runtime_closure.json", "run_budget.json",
                     "runtime_dispatches.json", "activation_receipts.json"):
            (artifact_root / name).unlink(missing_ok=True)
    record = artifact_root / "work_record.md"
    if continuation:
        if not record.is_file():
            raise ValueError("continuation_record_unavailable")
    elif not record.exists():
        template = "sentry_work_record.md" if playbook == "sentry_issue_remediation" else "work_record.md"
        shutil.copyfile(ROOT / "templates" / template, record)
    run_inputs, run_inputs_path = _prepare_run_inputs(
        artifact_root, work_item, playbook, resolved_execution_repository, input_manifest, continuation and not prior,
        validated_supplied, input_bytes,
    )
    if workflow_objective:
        goal_source = "Selected playbook defaults" if goal_defaults_used else "Current user request"
        goal_authority = (
            str(PLAYBOOK_DEFAULT_GOALS[playbook]["authority"])
            if goal_defaults_used else "Explicit user outcome"
        )
        run_inputs = _with_run_goal(
            run_inputs, workflow_objective, requested_outcome, goal_source, goal_authority,
        )
    if playbook == "technical_spike":
        run_inputs = _with_spike_bounds(
            run_inputs, primary_question, success_criterion, success_source, success_authority,
        )
    if workflow_objective or playbook == "technical_spike":
        run_inputs = write_manifest(run_inputs_path, run_inputs)
    manifest["run_input_manifest"] = packet_metadata(run_inputs_path, run_inputs)
    manifest["run_input_manifest"]["inputs"] = run_inputs["inputs"]
    manifest["run_input_manifest"]["precedence_rule"] = run_inputs["precedence_rule"]
    manifest["lifecycle"] = resolved_lifecycle
    manifest["execution_profile"] = resolved_profile
    if budget:
        budget_path = artifact_root / RUN_BUDGET_FILENAME
        budget_path.write_text(json.dumps(budget, indent=2, sort_keys=True) + "\n")
        manifest["run_budget"] = {**budget, "path": str(budget_path)}
    fix_design_contract = None
    normalized_evidence_contract = None
    if playbook == "sentry_issue_remediation":
        fix_design_contract = artifact_root / "fix_design_result_contract.json"
        shutil.copyfile(SENTRY_FIX_DESIGN_CONTRACT, fix_design_contract)
        normalized_evidence_contract = artifact_root / "normalized_evidence_contract.md"
        shutil.copyfile(SENTRY_NORMALIZED_EVIDENCE_CONTRACT, normalized_evidence_contract)
        manifest["worker_contracts"] = {
            "evidence_topology": {
                "worker_id": "evidence-topology",
                "contract": str(normalized_evidence_contract),
                "output": str(artifact_root / "normalized_evidence.md"),
            },
            "fix_design": {
                "worker_id": "fix-design",
                "contract": str(fix_design_contract),
                "normalizer": str(SENTRY_FIX_DESIGN_NORMALIZER),
                "output": str(artifact_root / "fix_design_result.json"),
            },
            "standard_planning_finalization": {
                "finalizer": str(SENTRY_PLANNING_FINALIZER),
                "owner": "Coordinator",
            },
        }
        if manifest["lifecycle"] == "remediation":
            for agent in ("implementer", "reviewer", "tester", "documenter"):
                manifest["worker_contracts"][agent] = {
                    "implementation_plan": str(artifact_root / "implementation_plan.md"),
                    "before_source_change_guard": str(WORKER_RUNTIME_GUARD),
                    "instructions": (
                        "Remain in Sentry remediation. Execute only the approved Sentry implementation plan and "
                        "record any material discrepancy before changing scope. Before each implementation slice, "
                        "the Implementer must ask the Coordinator to run the parent-bound source-change guard "
                        "with the provider-returned handle and freshly observed status. Wait for an allowed result "
                        "before editing. Reviewer and Tester independently inspect the exact candidate."
                    ),
                }
            _configure_remediation_result_contracts(artifact_root, manifest["worker_contracts"])
            manifest["worker_result_merger"] = str(ROOT / "scripts" / "merge_techops_result.py")
    if playbook == "feature_delivery":
        manifest["worker_contracts"] = {
            "feature_asset_inventory": {
                "contract": str(ASSET_MANIFEST_TEMPLATE),
                "output": str(artifact_root / "asset_manifest.json"),
            },
        }
        if manifest["lifecycle"] == "remediation":
            for agent in ("implementer", "reviewer", "tester", "documenter"):
                manifest["worker_contracts"][agent] = {
                    "implementation_plan": str(artifact_root / "implementation_plan.md"),
                    "before_source_change_guard": str(WORKER_RUNTIME_GUARD),
                    "instructions": (
                        "Remain in Feature Delivery remediation. Required independent roles are implement, review, "
                        "validate and handoff; Coordinator cannot substitute. Before each implementation slice, "
                        "the Implementer must ask the Coordinator to run the parent-bound source-change guard "
                        "with the provider-returned handle and freshly observed status. Wait for an allowed result. "
                        "Review and validation stay independent and cover the exact candidate and every criterion."
                    ),
                }
            _configure_remediation_result_contracts(artifact_root, manifest["worker_contracts"])
    if playbook == "techops_issue_remediation":
        instructions = {
            "current_state_investigator": (
                "Return an integration_decision object with decision required or not_required, a reason, and "
                "evidence_refs citing current evidence IDs. Mark required for a repository, service, deployment, "
                "ownership or public-contract boundary; reconcile later contradictory evidence with the Coordinator. "
                "Start with the exact issue and report-bearing comments. Expand to hierarchy, selected links, "
                "siblings, attachments, remote links or history only for a recorded scope, failure-path, prior-fix "
                "or rollout question. A self-contained bug does not require a sibling roster. Reuse successful "
                "reads; unselected collections are not empty. Resolve conflicting selected status/comment evidence "
                "with history. Use exact evidence IDs, never ranges, in result references."
            ),
            "dependency_analyst": (
                "Return a reproduction object in the result with status (reproduced, verified_by_evidence, "
                "not_reproduced, or unable_to_attempt), expected, observed, check, environment, revision, "
                "limitation and evidence_refs. All fields are nonempty strings; cite current-run evidence IDs. "
                "Use reproduced when the check produces the reported symptom; verified_by_evidence when supplied "
                "runtime evidence confirms that symptom; not_reproduced when an executed check does not show it, "
                "including a passing check of expected behavior; unable_to_attempt when no executable check ran. "
                "State the evidence's environment and revision limits. A passing expected-behavior test does not "
                "confirm the reported failure. "
                "Source inspection alone is not an executable reproduction. "
                "When report behavior or copy differs from current code, inspect the affected commit patch and directly "
                "associated work item; finding a git log entry alone is insufficient. Distinguish historical failure, "
                "current behavior, remaining acceptance gap and deployment uncertainty. Correct diagnosis within this run; "
                "prior fixes may be modified and history creates no new user task or approval gate."
            ),
            "solution_architect": (
                "Verify issue_scope and history_reconciliation evidence before design. Keep local regression steps "
                "independent of unavailable deployment evidence unless it changes target, scope or safety; explain actual "
                "dependencies. Read existing test fixtures and plan any required seed, state, fresh-read and error support. "
                "Return techops_checks rows for issue_scope, history_reconciliation, plan_dependencies, regression_fixture "
                "with Status passed (history may be not_applicable with evidence), Evidence refs and Detail. "
                "A passed history_reconciliation object requires separate JSON keys Commit, Patch evidence refs, "
                "Work item and Work item evidence refs, not prose inside Detail. Patch and work-item references "
                "must be distinct and included in Evidence refs, from an inspected patch and its associated work item."
            ),
            "documenter": (
                "Preserve the accepted techops_checks and Coordinator runtime_audits in finalization_packet.json. "
                "Preserve the accepted reproduction record and report its outcome and limitation accurately in the handoff. "
                "Before activation, the Coordinator must run the prepared documenter_packet_stager command in "
                "role_bindings.json; it validates accepted fan-in and writes the Coordinator-owned identity and "
                "synchronization fields. Analytical result merging also registers each worker ledger row from its "
                "authenticated dispatch and trace. Preserve those rows exactly. "
                "Do not mark a check passed without its owning worker's evidence. Finalization schema belongs only in "
                "finalization, not identity. For Engineering outcome plan_only after analytical fan-in, create "
                "implementation_plan as well as output; use the accepted TechOps checks, not Sentry readiness fields. "
                "Use the exact implementation plan template headings, including # Behavior Applicability, "
                "# Design Justification and # Complete Solution, and table values, including lowercase "
                "applicability dispositions and complete-solution statuses. The pre-release check validates "
                "the plan with the same applicability rules as remediation re-entry. "
                "Keep the plan unapproved and external proof gates separate from local work. Preserve the Coordinator-"
                "prepared State, Workflow outcome, Engineering state, Engineering outcome, and profile fields exactly; "
                "do not choose or rewrite them. The Coordinator resolves these values from accepted analysis before "
                "activation. A ready plan uses ready_for_implementation/completed; unresolved indispensable evidence or "
                "a material decision uses the Coordinator-prepared awaiting_input or blocked state. If the supplied "
                "values are missing or conflict with accepted evidence, return the exact mismatch for Coordinator "
                "correction instead of changing the packet. Never use handoff/incomplete as the final TechOps planning "
                "identity. "
                "Write a concrete workflow work summary, never a bare Partially answered label."
            ),
            "reviewer": (
                "Challenge history reconciliation, local/external plan dependencies and fixture feasibility; return "
                "missing evidence to the owning worker before accepting the TechOps planning checks."
            ),
        }
        outputs = {
            "current_state_investigator": "issue_evidence.md", "dependency_analyst": "failure_path.md",
            "repository_integrator": "repository_integration.md", "solution_architect": "fix_design.md",
            "reviewer": "code_review.md", "documenter": "finalization_packet.json",
        }
        instructions["repository_integrator"] = (
            "Consume issue-evidence and any available accepted failure-path evidence; inspect only ownership, deployment "
            "and integration seams. Do not wait for failure-path when issue-evidence identifies an independent seam. "
            "Repeat source tracing only for a named discrepancy. Keep runtime unknowns separate from local work."
        )
        manifest["worker_contracts"] = {
            agent: {"instructions": instruction, "contract": str(ROOT / "playbooks" / "techops_issue_remediation.md"),
                    "output": str(artifact_root / outputs[agent])}
            for agent, instruction in instructions.items()
        }
        manifest["worker_contracts"]["documenter"]["implementation_plan"] = str(artifact_root / "implementation_plan.md")
        try:
            from merge_techops_result import WORKERS, TABLES
        except ModuleNotFoundError:
            from scripts.merge_techops_result import WORKERS, TABLES
        result_template = json.loads((ROOT / "templates/finalization_packet.json").read_text())
        role_result_fields = {
            "current_state_investigator": (
                "For a complete outcome, include result.integration_decision as an object with decision, reason "
                "and evidence_refs, as specified in your instructions. "
            ),
            "dependency_analyst": (
                "For a complete outcome, include result.reproduction as the object specified in your instructions. "
            ),
            "solution_architect": (
                "Include result.techops_checks, result.plan_readiness and result.implementation_plan_action. "
                "Use ready_for_implementation/create, awaiting_input/omit, or blocked/omit for the last two values. "
            ),
        }
        for agent, (worker, namespace) in WORKERS.items():
            manifest["worker_contracts"][agent].update({
                "worker_id": worker, "id_namespace": namespace,
                "result": str(artifact_root / f"{worker.replace('-', '_')}_result.json"),
                "result_hash_required": True,
                "result_response": "strict_json_final_answer",
                "result_fields": {name: list(result_template[name][0])
                                  for name in ("worker_results", *TABLES)},
                "result_instructions": (
                    "Do not write the assigned output or result files directly; return their contents only in this "
                    "JSON response, and let the Coordinator merger publish them after acceptance. "
                    "Return exactly one strict JSON object with keys "
                    "output (narrative string) and result (the JSON envelope with run_id, worker_result, and "
                    "evidence/claims/decisions/actions arrays). The Coordinator captures this answer into immutable "
                    "current-dispatch artifacts; the merger publishes accepted files. Use result_fields exactly; worker_result uses "
                    f"worker_results fields. Its Worker value must be exactly {worker}. "
                    "Every field value in worker_result and in evidence/claims/decisions/actions "
                    "rows must be a string, including Evidence / claim refs, Evidence refs, Claim refs and Decision ref; "
                    "join multiple references in one string, never an array. "
                    "Claims Evidence refs accepts only E-* evidence IDs; decisions Claim refs only CL-* claim IDs; "
                    "actions Decision ref requires exactly one existing DE-* decision ID. Worker summary Evidence / claim refs may mix types. "
                    "Use E/CL/DE/A-<id_namespace>-<number> IDs and exact references. "
                    "Reference upstream IDs unchanged without copying their rows; emit only your namespace's rows. "
                    "Outcome is complete, failed or blocked, never completed. "
                    + role_result_fields.get(agent, "") +
                    "Record unresolved decisions in the narrative and worker_result. Do not edit the Coordinator packet or audits."
                ),
            })
        manifest["worker_contracts"]["solution_architect"]["planning_disposition_required"] = True
        manifest["worker_result_merger"] = str(ROOT / "scripts" / "merge_techops_result.py")
        manifest["documenter_packet_stager"] = str(ROOT / "scripts" / "stage_documenter_packet.py")
        if manifest["lifecycle"] == "remediation":
            manifest["worker_contracts"] = {
                "implementer": {
                    "implementation_plan": str(artifact_root / "implementation_plan.md"),
                    "before_source_change_guard": str(WORKER_RUNTIME_GUARD),
                    "instructions": (
                        "Remain in TechOps remediation and execute only the explicitly approved plan. Preserve its "
                        "scope and record material discrepancies before acting. Before source edits, write "
                        "implementation_conformance.json in the run root with run_id, plan_sha256 and a nonempty "
                        "files array; each entry has path, plan_step, reuse, change and validation strings. "
                        "Before each source-change slice, ask the Coordinator to run the parent-bound runtime guard "
                        "with the provider-returned handle and freshly observed status; wait for an allowed result."
                    ),
                },
                "reviewer": {
                    "implementation_plan": str(artifact_root / "implementation_plan.md"),
                    "instructions": "Independently review the exact TechOps remediation candidate against the approved plan.",
                },
                "tester": {
                    "implementation_plan": str(artifact_root / "implementation_plan.md"),
                    "instructions": "Validate the exact TechOps remediation candidate against its declared regression plan.",
                },
                "documenter": {
                    "implementation_plan": str(artifact_root / "implementation_plan.md"),
                    "instructions": (
                        "Preserve accepted TechOps checks and Coordinator runtime audits. Run the prepared packet "
                        "stager after implement, review, and validate fan-in; it owns final identity and synchronization. "
                        "Register and link implementation_conformance.json in the final handoff and work record. "
                        "Record implementation, validation, release or rollback, monitoring, owner, residual risk, "
                        "and next action. Do not rewrite accepted evidence or audits."
                    ),
                },
            }
            if recovered_candidate:
                contract = manifest["worker_contracts"]["implementer"]
                contract["recovered_candidate"] = recovered_candidate
                contract["instructions"] += (
                    " The recovered candidate is unaccepted input, not a prior accepted worker result. "
                    "Inspect its assigned snapshot files against the approved plan, write a new current-run "
                    "conformance manifest, and apply any in-scope changes only after the source guard passes. "
                    "Produce your own result; Reviewer and Tester must independently check the resulting candidate."
                )
                if recovered_candidate.get("source_already_present") is True:
                    contract["instructions"] += (
                        " The verified unaccepted candidate is already present in the source checkout. "
                        "Do not reset or reapply it; inspect it against the approved plan, then make any "
                        "necessary source changes only after the source-change guard allows them."
                    )
            _configure_remediation_result_contracts(artifact_root, manifest["worker_contracts"])
    if playbook == "feature_delivery" and workflow_objective == "implementation_planning":
        try:
            from merge_techops_result import FEATURE_WORKERS
        except ModuleNotFoundError:
            from scripts.merge_techops_result import FEATURE_WORKERS
        fields = {name: list(rows[0]) for name, rows in json.loads(
            (ROOT / "templates/finalization_packet.json").read_text()).items()
            if name in {"evidence", "claims", "decisions", "actions", "worker_results"}}
        for agent, (worker, namespace) in FEATURE_WORKERS.items():
            manifest["worker_contracts"][agent] = {
                "worker": worker, "id_namespace": namespace,
                "output": str(artifact_root / (worker.replace("-", "_") + ".md")),
                "result": str(artifact_root / (worker.replace("-", "_") + "_result.json")),
                "result_hash_required": True,
                "result_response": "strict_json_final_answer",
                "result_fields": fields,
                "instructions": (
                    "Return exactly one strict JSON object with keys "
                    "output (narrative string) and result (JSON with current run_id, worker_result, "
                    "evidence/claims/decisions/actions using result_fields). The Coordinator captures this answer into "
                    "immutable current-dispatch artifacts; the merger publishes accepted files. worker_result is one object using the exact "
                    "worker_results fields (including capitalization), not an array or lowercase summary. "
                    "Every field value in worker_result and in evidence/claims/decisions/actions rows must be a string, "
                    "including Evidence / claim refs, Evidence refs, Claim refs and Decision ref; join multiple "
                    "references in one string, never an array. "
                    "Claims Evidence refs accepts only E-* evidence IDs; decisions Claim refs only CL-* claim IDs; "
                    "actions Decision ref requires exactly one existing DE-* decision ID. Worker summary Evidence / claim refs may mix types. "
                    f"Its Worker value must be exactly {worker}. Reference existing upstream IDs without "
                    "repeating their rows in these arrays; every emitted row must use this worker's "
                    "E/CL/DE/A-<id_namespace>-<number> namespace. Record exact asset evidence IDs in references. "
                    "Outcome is complete, failed or blocked. Coordinator owns provider receipts and merges this "
                    "envelope before downstream activation. Do not edit the packet or historical result rows. "
                    "Recovery reuses explicitly supplied prior findings after checking current applicability; "
                    "repeat discovery only for a material changed input or unresolved gap."
                ),
            }
        manifest["worker_contracts"]["solution_architect"]["planning_disposition_required"] = True
        manifest["worker_contracts"]["solution_architect"]["instructions"] += (
            " Return plan_readiness and implementation_plan_action. Use ready_for_implementation/create for a "
            "complete supported plan; awaiting_input/create_draft when confirmed independent work has a feasible "
            "partial Draft with owned unresolved decisions; awaiting_input/omit only when no supported partial "
            "scope exists. A partial Draft preserves the Clarification Brief and does not approve implementation. "
            "For a completed design, include an Asset Baseline section linking asset_manifest.json and one row per "
            "material asset with exact columns Asset ID, Evidence refs, Observation, Planning consequence. "
            "Use bare asset IDs in the Asset ID column. The validated merger records consumption; do not edit the manifest."
        )
        manifest["worker_contracts"]["current_state_investigator"]["asset_inventory"] = (
            manifest["worker_contracts"]["feature_asset_inventory"])
        manifest["worker_contracts"]["current_state_investigator"]["instructions"] += (
            " Include asset_manifest as a third key in the final JSON object using the prepared asset_inventory "
            "contract. The Coordinator publishes it before the packaged asset gate; do not write the file yourself. "
            "Use exactly one jira_issue_attachments source tied to the supplied work-item input, aggregating "
            "the selected issues' attachment and remote-link inventories there. "
            "Before downstream design/review consumption, keep all_material_assets_linked false for material assets. "
            "For an asset-only correction after result acceptance, change only asset_manifest and re-emit the "
            "accepted output and result tables verbatim. Do not reword evidence summaries or claim statuses.")
        documenter = manifest["worker_contracts"].setdefault("documenter", {})
        documenter["output"] = str(artifact_root / "finalization_packet.json")
        if manifest["lifecycle"] == "planning" and workflow_objective == "implementation_planning":
            documenter["implementation_plan"] = str(artifact_root / "implementation_plan.md")
        manifest["worker_result_merger"] = str(ROOT / "scripts/merge_techops_result.py")
        manifest["documenter_packet_stager"] = str(ROOT / "scripts/stage_documenter_packet.py")
    for agent, contract in manifest.get("worker_contracts", {}).items():
        if contract.get("result_response") != "strict_json_final_answer":
            continue
        contract["response_builder"] = str(ROOT / "scripts" / "prepare_worker_response.py")
        contract["result_instructions"] = (
            "The output/result paths are Coordinator publication destinations, not worker write permissions. "
            "Do not write those files; return their contents only in the JSON response. "
            "Do not create unassigned draft files. Use stdin for the read-only response preview. "
            "Before your final answer, pipe the complete declared JSON envelope to response_builder with --packet "
            f"{artifact_root / 'finalization_packet.json'} --agent {agent} --response-stdin. "
            "Correct reported draft errors and rerun this read-only preview before ending; return its successful "
            "stdout unchanged. If a truthful repair is unavailable, return a valid blocked result with the limitation. "
            "Draft validation does not accept results or consume a dispatch correction. "
            "At completed planning synthesis and afterward, it checks the entire merged reasoning graph: "
            "link every evidence row to a claim, every claim to a decision, and every decision to an action. "
            "New correction rows must also reach an action; fixing only the previously listed IDs is insufficient. "
            "Preserve accepted upstream rows and factual meaning; do not invent reasoning or actions just to pass. "
            + contract.get("result_instructions", "")
        )
    manifest["runtime_evidence"] = {
        "launch_binding_required": True,
        "collector": str(ROOT / "scripts" / "worker_runtime_evidence.py"),
        "ledger": str(artifact_root / "runtime_dispatches.json"),
        "run_started_at": manifest["prepared_at"],
    }
    if continuation and not prior and (artifact_root / "role_bindings.json").is_file():
        previous = json.loads((artifact_root / "role_bindings.json").read_text()).get("runtime_evidence", {})
        if previous.get("run_started_at"):
            manifest["runtime_evidence"]["run_started_at"] = previous["run_started_at"]
        sources = list(previous.get("identity_sessions", []))
        previous_source = previous_run_bindings.get("parent_context", {}).get("provider_session")
        if previous_source and provider_session and Path(previous_source).resolve() != provider_session.resolve():
            sources.append(previous_source)
        if sources:
            manifest["runtime_evidence"]["identity_sessions"] = list(dict.fromkeys(sources))
    manifest["worker_runtime_guard"] = str(WORKER_RUNTIME_GUARD)
    packet_path = artifact_root / "finalization_packet.json"
    if continuation and not prior and packet_path.is_file():
        manifest["run_id"] = json.loads(packet_path.read_text())["identity"]["Run ID"]
    else:
        started_at = manifest["prepared_at"]
        manifest["run_id"] = work_item + "-" + re.sub(r"[^0-9A-Za-z]", "", started_at)
    if parent_context:
        manifest["parent_context"] = {**parent_context, "run_id": manifest["run_id"], "input_paths": assigned}
    failure_path = artifact_root / "finalization_failure.json"
    if continuation and not prior and playbook == "techops_issue_remediation" and failure_path.is_file():
        manifest["handoff_recovery"] = {
            "run_id": manifest["run_id"],
            "failure_sha256": hashlib.sha256(failure_path.read_bytes()).hexdigest(),
        }
    manifest["activation_packet_bundle"] = _write_activation_packets(artifact_root, manifest)
    manifest_path = artifact_root / "role_bindings.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    if prior or (not continuation and not packet_path.exists()):
        packet = _initial_packet(
            artifact_root, work_item, playbook, workflow_objective, repository_row,
            resolved_runtime_agents, manifest, manifest_path,
        )
        if prior:
            for field in ("work_item", "decisions", "claims", "actions", "evidence"):
                packet[field] = prior[field]
            if "techops_checks" in prior:
                packet["techops_checks"] = prior["techops_checks"]
            if "reproduction" in prior:
                packet["reproduction"] = prior["reproduction"]
            if "integration_decision" in prior:
                packet["integration_decision"] = prior["integration_decision"]
            for field in ("Primary evidence", "Primary goal", "Selected playbook", "Closest alternative", "Why this playbook"):
                packet["playbook_selection"][field] = prior["playbook_selection"][field]
            packet["work_item"]["Last Updated"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
            packet["identity"].update({
                "Requested profile": prior["identity"]["Requested profile"],
                "Activated profile": "None", "Executed profile": "None", "Profile status": "requested",
                "Lifecycle": "planning" if planning_recovery else "remediation",
                "State": "in_progress", "Workflow outcome": "in_progress",
                "Engineering state": "unknown", "Engineering outcome": "unknown",
            })
            for field in ("workers", "worker_results", "synchronization"):
                packet[field] = []
            packet["runtime_audits"] = []
            provenance = {"Prior run ID": prior["identity"]["Run ID"],
                          "Prior artifacts": archived, "Approval reference": approval_reference}
            plan = artifact_root / "implementation_plan.md"
            if not planning_recovery:
                provenance.update({"Approved plan": str(plan),
                                   "Approved plan SHA256": hashlib.sha256(plan.read_bytes()).hexdigest()})
            packet["recovery" if planning_recovery else "reentry"] = provenance
            if plan.is_file():
                packet["durable_artifacts"].append({
                    "Artifact": "Preserved draft plan" if planning_recovery else "Approved implementation plan",
                    "Path": str(plan), "Status": "Draft" if planning_recovery else "Approved",
                    "Purpose": "Preserved planning input; not implementation approval" if planning_recovery else
                               "Preserved plan; delivery activation barrier still required",
                })
            text = (ROOT / "templates" / "work_record.md").read_text()
            for field, value in packet["identity"].items():
                text = re.sub(rf"(?m)^\|\s*{re.escape(field)}\s*\|[^\n]*$",
                              lambda match, field=field, value=value: f"| {field} | {value} |", text)
            text += (f"\n## Lifecycle Recovery / Re-entry\n\nPrior run: {prior['identity']['Run ID']}\n\n"
                     f"Preserved history: {archived}\n\nApproval: {approval_reference}\n\n"
                     "Prior work preserved. Current lifecycle activation and evidence are pending.\n")
            record.write_text(text)
            current_path = artifact_root / "CURRENT.md"
            if current_path.exists():
                current_path.write_text(
                    f"# Current Run\n\nRun: {packet['identity']['Run ID']}\n\nLifecycle: {packet['identity']['Lifecycle']}\n\n"
                    "State: in_progress; current lifecycle activation pending.\n\n"
                    "Use finalization_packet.json and work_record.md for current evidence.\n\n"
                    f"Prior state preserved in {archived}.\n"
                )
        packet_path.write_text(json.dumps(packet, indent=2) + "\n")
    elif continuation and packet_path.is_file():
        packet = json.loads(packet_path.read_text())
        packet["run_input_manifest"] = manifest["run_input_manifest"]
        packet["inputs"] = list(run_inputs["inputs"])
        refreshed = _initial_packet(artifact_root, work_item, playbook, workflow_objective,
                                    repository_row, resolved_runtime_agents, manifest, manifest_path)
        for field in ("Run input manifest", "Run input manifest hash", "Framework commit / status",
                      "Playbook / version", "Plugin package / version", "Role-policy baseline ID",
                      "Role binding manifest", "Provider/runtime configuration", "Provider configuration source/status", "Lifecycle", "Requested profile"):
            packet["identity"][field] = refreshed["identity"][field]
        packet_path.write_text(json.dumps(packet, indent=2) + "\n")
    recovered_failure = None
    if unactivated_failure:
        failure_path, failure_bytes, closure_bytes = unactivated_failure
        closure_path = artifact_root / "runtime_closure.json"
        if failure_path.read_bytes() != failure_bytes or closure_path.read_bytes() != closure_bytes:
            raise ValueError("remediation_failure_changed_during_recovery")
        recovered_failure = artifact_root / ("finalization_failure.recovered."
                                             + hashlib.sha256(failure_bytes).hexdigest() + ".json")
        if recovered_failure.exists() and recovered_failure.read_bytes() != failure_bytes:
            raise ValueError("remediation_failure_snapshot_conflict")
        if not recovered_failure.exists():
            recovered_failure.write_bytes(failure_bytes)
        recovered_closure = artifact_root / ("runtime_closure.recovered."
                                             + hashlib.sha256(closure_bytes).hexdigest() + ".json")
        if recovered_closure.exists() and recovered_closure.read_bytes() != closure_bytes:
            raise ValueError("remediation_closure_snapshot_conflict")
        if not recovered_closure.exists():
            recovered_closure.write_bytes(closure_bytes)
        closure_path.unlink()
        failure_path.unlink()
    return {
        "status": "prepared",
        "lifecycle": resolved_lifecycle,
        "execution_profile": resolved_profile,
        "artifact_root": str(artifact_root),
        "legacy_artifact_root": str(legacy_root) if legacy_root != artifact_root and legacy_root.exists() else None,
        "work_record": str(record),
        "finalization_packet": str(packet_path),
        "run_input_manifest": str(run_inputs_path),
        "run_input_manifest_status": run_inputs["status"],
        "requested_outcome": requested_outcome,
        "workflow_objective": workflow_objective,
        "run_budget": manifest.get("run_budget"),
        "role_binding_manifest": str(manifest_path),
        "fix_design_result_contract": str(fix_design_contract) if fix_design_contract else None,
        "normalized_evidence_contract": (
            str(normalized_evidence_contract) if normalized_evidence_contract else None
        ),
        "archived_prior_run": archived,
        "recovered_failure": str(recovered_failure) if recovered_failure else None,
        **manifest,
    }


def self_test() -> None:
    try:
        from self_check import run_self_check
    except ModuleNotFoundError:
        from scripts.self_check import run_self_check
    run_self_check("prepare_run", "self_test")


def status_projection(execution_repository: Path, work_item: str, provider_session: Path | None,
                      authorize_prior_parent_thread: str | None = None, *, continuation: bool = False) -> dict:
    try:
        from provider_runtime import (current_parent_session, related_run_status_projection_source,
                                      scoped_prior_run_status_thread_ids)
    except ModuleNotFoundError:
        from scripts.provider_runtime import (current_parent_session, related_run_status_projection_source,
                                              scoped_prior_run_status_thread_ids)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", work_item):
        raise ValueError("invalid_work_item")
    if not execution_repository.resolve().is_dir():
        raise ValueError("execution_repository_unavailable")
    session = current_parent_session(provider_session)
    if session is None:
        raise ValueError("provider_current_session_unavailable")
    with session.open() as stream:
        header = json.loads(next(stream, ""))
    if header.get("type") != "session_meta":
        raise ValueError("provider_session_parent_mismatch")
    parent = header.get("payload", {}).get("id")
    repository, _ = resolve_repository_paths(execution_repository)
    root = repository / ".thoughts" / work_item
    ids = (scoped_prior_run_status_thread_ids(root, parent, authorize_prior_parent_thread)
           if continuation or authorize_prior_parent_thread is not None else ())
    bindings_path = root / "role_bindings.json"
    packet_path = root / "finalization_packet.json"
    if (continuation and not ids and bindings_path.is_file() and packet_path.is_file()
            and not (root / "finalization_failure.json").exists()):
        bindings = json.loads(bindings_path.read_text())
        identity = json.loads(packet_path.read_text()).get("identity", {})
        saved_parent = bindings.get("parent_context", {})
        if (bindings.get("run_id") == identity.get("Run ID") and identity.get("State") == "in_progress"
                and saved_parent.get("parent_thread_id") == parent):
            ids = tuple(saved_parent.get("related_run_thread_ids", []))
    return {"status": "ready", "parent_thread_id": parent, "prior_thread_ids": list(ids),
            "projection": related_run_status_projection_source(work_item, parent, ids)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execution-repository", type=Path)
    parser.add_argument("--work-item")
    parser.add_argument("--playbook")
    parser.add_argument("--runtime-agents", type=Path)
    parser.add_argument("--provider-session", type=Path,
                        help="Optional assertion of the current native parent record; normally omit for automatic binding")
    parser.add_argument("--lifecycle", choices=("planning", "remediation"),
                        help="Declared lifecycle; must match the initial planning stage or approved continuation/reentry")
    parser.add_argument("--execution-profile", choices=("standard", "deep"),
                        help="Bind the requested worker profile; defaults to standard for a fresh run")
    parser.add_argument("--continuation", action="store_true")
    parser.add_argument("--remediation-reentry", action="store_true",
                        help="Start a new Feature Delivery remediation lifecycle, preserving planning history")
    parser.add_argument("--approval-reference", help="Explicit approval for implementation re-entry or planning recovery")
    parser.add_argument("--planning-recovery", action="store_true",
                        help="Preserve a closed planning invocation and start an explicitly authorized recovery")
    parser.add_argument("--archive-stale-run", action="store_true")
    parser.add_argument("--status-projection", action="store_true",
                        help="Produce the redacted prior-run status query without changing artifacts")
    parser.add_argument("--authorize-prior-parent-thread",
                        help="Authorize status checks for this exact prior parent thread")
    parser.add_argument("--workflow-objective")
    parser.add_argument("--requested-outcome")
    parser.add_argument("--started-at", help="RFC 3339 end-to-end task start")
    parser.add_argument("--timebox-minutes", type=int)
    parser.add_argument("--primary-question")
    parser.add_argument("--success-criterion")
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument(
        "--input-manifest",
        type=Path,
        help="JSON file containing current-run context, decisions, and supporting artifacts",
    )
    inputs.add_argument("--input-json", help="Current-run input manifest as a JSON object; use - to read JSON from stdin")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.status_projection:
        if not args.execution_repository or not args.work_item:
            parser.error("--status-projection requires --execution-repository and --work-item")
        try:
            print(json.dumps(status_projection(args.execution_repository, args.work_item, args.provider_session,
                                               args.authorize_prior_parent_thread, continuation=args.continuation),
                             sort_keys=True))
        except (OSError, ValueError, TypeError, AttributeError) as error:
            print(json.dumps({"status": "blocked", "reason": str(error)}, sort_keys=True))
            return 2
        return 0
    if not args.execution_repository or not args.work_item or not args.playbook:
        parser.error("--execution-repository, --work-item, and --playbook are required")
    try:
        input_data = None
        if args.input_json is not None:
            input_data = json.load(sys.stdin) if args.input_json == "-" else json.loads(args.input_json)
        if args.input_json is not None and not isinstance(input_data, dict):
            raise ValueError("run_input_manifest_invalid")
        result = prepare_run(
            args.execution_repository,
            args.work_item,
            args.playbook,
            args.runtime_agents,
            args.continuation,
            args.archive_stale_run,
            args.input_manifest,
            args.workflow_objective,
            args.requested_outcome,
            args.started_at,
            args.timebox_minutes,
            args.primary_question,
            args.success_criterion,
            args.remediation_reentry,
            args.approval_reference,
            args.planning_recovery,
            args.provider_session,
            args.lifecycle,
            args.execution_profile,
            input_data,
            args.authorize_prior_parent_thread,
        )
    except PermissionError as error:
        root = resolve_repository_paths(args.execution_repository)[0] / ".thoughts" / args.work_item
        denied = Path(error.filename).resolve() if error.filename else None
        receipt = {"status": "blocked", "reason": str(error)}
        if denied in {root, root.parent}:
            receipt.update(reason="artifact_root_permission_denied", artifact_root=str(root),
                           denied_path=str(denied), next_action=(
                               "Rerun the same preparation command with the complete input manifest through the "
                               "provider's scoped filesystem approval mechanism for this artifact root. On Codex, "
                               "use exec_command with sandbox_permissions=require_escalated and a path-specific "
                               "justification. Keep the artifact root and source checkout unchanged. If approval is "
                               "unavailable or rejected, report that exact restriction; do not retry or relocate artifacts."))
        print(json.dumps(receipt, sort_keys=True))
        return 2
    except (OSError, ValueError) as error:
        print(json.dumps({"status": "blocked", "reason": str(error)}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
