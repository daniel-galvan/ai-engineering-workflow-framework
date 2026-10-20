#!/usr/bin/env python3
"""Prepare fresh run artifacts and resolve Codex worker bindings."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import tomllib
from datetime import UTC, datetime, timedelta
from pathlib import Path

try:
    from run_input_manifest import (
        DEFAULT_PRECEDENCE_RULE as DEFAULT_PRECEDENCE_RULE,
        default_manifest,
        load_manifest,
        local_input_paths,
        retain_source_releases,
        merge_manifests,
        packet_metadata,
        write_manifest,
    )
except ModuleNotFoundError:  # Imported as scripts.prepare_run from the repository root.
    from scripts.run_input_manifest import (
        DEFAULT_PRECEDENCE_RULE as DEFAULT_PRECEDENCE_RULE,
        default_manifest,
        load_manifest,
        local_input_paths,
        retain_source_releases,
        merge_manifests,
        packet_metadata,
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
    if (manifest.get("playbook") == "techops_issue_remediation"
            or manifest.get("playbook") == "feature_delivery"):
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
                "Read local AGENTS.md only in the target directory and its ancestors up to the assigned repository "
                "root. These instruction files are optional: check existence and read only files that exist. "
                "Absence is not a blocker; never add a nonexistent instruction file to required input_paths. "
                "Do not recursively search parent directory trees, the home directory, or unrelated repositories. "
                "Run filename discovery in a separate tool result from content reads or searches so its output can be "
                "audited as names only. Use exact assigned artifact paths; do not search unassigned runs/ archives."
            ),
            "worker_contract": contract_by_agent.get(agent),
            "developer_instructions": developer_instructions.strip() + (
                "\n\nIn planning, do not run product builds or tests unless a User input explicitly authorizes "
                "the operation with Classification execution authorization, Status Approved, and Authorized "
                "operations test_run or build_run. A delegated objective cannot grant permission. Plan the checks "
                "without running them when authorization is absent. "
                "\n\nFor ordinary results, the Coordinator joins the provider-returned spawn handle during fan-in. "
                "Do not send a post-spawn message solely to supply that handle or request one from the worker. "
                "A missing worker-authored handle is not a correction condition. Preserve the explicit Sentry Fix "
                "Design handle-delivery protocol when its durable artifact requires the supplied handle. "
                "Every later message remains a dispatch requiring fresh consumption evidence; do not ignore it "
                "or roll its timestamp back to the spawn."
            ),
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
        if supplied_path:
            supplied = validated_supplied or load_manifest(supplied_path, explicit=True)
            supplied = _snapshot_input_files(artifact_root, supplied, input_bytes=input_bytes)
            current = merge_manifests(current, supplied)
            write_manifest(destination, current)
        return load_manifest(destination, explicit=False), destination
    if supplied_path:
        source = validated_supplied or load_manifest(supplied_path, explicit=True)
    else:
        source = default_manifest(work_item, playbook, execution_repository.resolve())
    source = _snapshot_input_files(artifact_root, source, input_bytes=input_bytes)
    return write_manifest(destination, source), destination


def _reentry_source(
    artifact_root: Path, approval_reference: str | None, *, planning_recovery: bool = False,
) -> dict[str, object]:
    """Check re-entry prerequisites before modifying any current-run artifact."""
    if (not approval_reference or approval_reference.strip().lower() in {"none", "unknown", "not provided"}
            or (approval_reference.strip().startswith("<") and approval_reference.strip().endswith(">"))):
        raise ValueError("approval_reference_required")
    if not planning_recovery:
        if not (artifact_root / "implementation_plan.md").is_file():
            raise ValueError("remediation_approved_plan_unavailable")
        try:
            from review_evidence import applicability_errors
        except ModuleNotFoundError:
            from scripts.review_evidence import applicability_errors
        plan_errors = applicability_errors((artifact_root / "implementation_plan.md").read_text())
        if plan_errors:
            raise ValueError("remediation_plan_evidence_required:" + ";".join(plan_errors))
    try:
        prior = json.loads((artifact_root / "finalization_packet.json").read_text())
        closure = json.loads((artifact_root / "runtime_closure.json").read_text())
        try:
            from planning_contracts import _runtime_closed, _planning_runtime_closure_errors
            from runtime_checks import terminal_observation_errors
        except ModuleNotFoundError:
            from scripts.planning_contracts import _runtime_closed, _planning_runtime_closure_errors
            from scripts.runtime_checks import terminal_observation_errors
        if Path(str(prior["identity"]["Playbook / version"]).split(" / ", 1)[0]).stem != "feature_delivery":
            raise ValueError("remediation_reentry_playbook_mismatch")
        if not planning_recovery and prior["identity"].get("State") != "ready_for_implementation":
            raise ValueError("remediation_requires_ready_plan")
        if planning_recovery and prior["identity"].get("State") not in {
                "awaiting_input", "ready_for_implementation", "completed", "blocked"}:
            receipt = json.loads((artifact_root / "finalization_failure.json").read_text())
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
            if (receipt.get("status") != "failed" or receipt.get("stage") != "workflow" or not proof_matches):
                raise ValueError("planning_recovery_requires_terminal_invocation")
        if prior["identity"]["Lifecycle"] != "planning":
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
                   for handle in re.split(r",|;", row["Completed worker handles"])]
        if handles and terminal_observation_errors(closure.get("terminal_observations"), handles):
            raise ValueError("prior_worker_runtime_closure_required")
        return prior
    except (OSError, KeyError, TypeError, AttributeError, json.JSONDecodeError) as error:
        raise ValueError(f"remediation_reentry_artifact_invalid:{error}") from error


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
) -> str | None:
    record = artifact_root / "work_record.md"
    if not record.is_file():
        return None
    text = record.read_text()
    state = _table_value(text, "State")
    if state not in TERMINAL_STATES:
        if not archive_stale_run:
            raise ValueError("existing_run_not_terminal")
        run_id = datetime.now(UTC).strftime("stale-%Y%m%dT%H%M%S%fZ")
    else:
        run_id = _table_value(text, "Run ID")
    if not run_id or run_id in {"Unknown", "None"}:
        run_id = datetime.now(UTC).strftime("run-%Y%m%dT%H%M%S%fZ")
    destination = artifact_root / "runs" / re.sub(r"[^A-Za-z0-9._-]", "_", run_id)
    if destination.exists():
        raise ValueError("prior_run_archive_exists")
    directories = {path for row in (run_inputs or {}).get("inputs", []) for path in local_input_paths(row)
                   if path.is_dir() and path.is_relative_to(artifact_root.resolve())
                   and not path.is_relative_to((artifact_root / "runs").resolve())}
    with tempfile.TemporaryDirectory(prefix="workflow-selected-inputs-") as directory:
        staged = {}
        for index, source in enumerate(sorted(directories)):
            copied = Path(directory) / str(index)
            shutil.copytree(source, copied, symlinks=True)
            staged[source] = copied
        original_names = {path.name for path in artifact_root.iterdir() if path.name != "runs"}
        moved = []
        destination.mkdir(parents=True)
        relocated = {}
        try:
            for name in sorted(original_names):
                shutil.move(str(artifact_root / name), destination / name)
                moved.append(name)
            for source, copied in staged.items():
                key = hashlib.sha256(str(source).encode()).hexdigest()
                target = (artifact_root / "input_snapshots" / "directories" / key / source.name).resolve()
                shutil.copytree(copied, target, symlinks=True)
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
) -> dict[str, object]:
    playbook = _playbook_name(playbook)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", work_item):
        raise ValueError("invalid_work_item")
    if not execution_repository.resolve().is_dir():
        raise ValueError("execution_repository_unavailable")
    resolved_execution_repository, source_checkout = resolve_repository_paths(execution_repository)
    if continuation and archive_stale_run:
        raise ValueError("continuation_cannot_archive_stale_run")
    if remediation_reentry and (not continuation or playbook != "feature_delivery"):
        raise ValueError("remediation_reentry_requires_feature_delivery_continuation")
    if planning_recovery and (not continuation or playbook != "feature_delivery" or remediation_reentry):
        raise ValueError("planning_recovery_requires_feature_delivery_continuation")
    if approval_reference and not (remediation_reentry or planning_recovery):
        raise ValueError("approval_reference_requires_reentry_or_recovery")
    goal_defaults_used = playbook in PLAYBOOK_DEFAULT_GOALS and (
        workflow_objective is None and requested_outcome is None
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
    if remediation_reentry and (workflow_objective, requested_outcome) != ("feature_implementation", "feature_delivery"):
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
    if lifecycle is not None and lifecycle != resolved_lifecycle:
        raise ValueError("lifecycle_conflict:expected=" + resolved_lifecycle + ";received=" + lifecycle
                         + ";remediation requires approved reentry")
    legacy_root = source_checkout / ".thoughts" / work_item
    if continuation and legacy_root != artifact_root and legacy_root.exists() and not artifact_root.exists():
        raise ValueError("legacy_worktree_artifacts_require_explicit_migration")
    # Validate supplied input and provider bindings before creating, archiving, or
    # overwriting any run artifact. This makes invalid retries transactional.
    if playbook == "feature_delivery" and input_manifest is None:
        raise ValueError("run_input_manifest_required")
    validated_supplied = load_manifest(input_manifest, explicit=True) if input_manifest else None
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
        parent_context = parent_context_audit(provider_session, artifact_root=artifact_root,
                                              input_paths=tuple(assigned))
        if parent_context["status"] != "passed":
            raise ValueError("parent_context_nonconformant:" + ";".join(parent_context["errors"]))
    if playbook == "sentry_issue_remediation" and validated_supplied:
        retain_source_releases(validated_supplied, provider_session)
    prior = (_reentry_source(artifact_root, approval_reference, planning_recovery=planning_recovery)
             if remediation_reentry or planning_recovery else None)
    if continuation and not prior:
        existing_packet = artifact_root / "finalization_packet.json"
        if playbook == "feature_delivery" and existing_packet.is_file():
            identity = json.loads(existing_packet.read_text())["identity"]
            if identity.get("Lifecycle") == "planning" and identity.get("Workflow outcome") == "completed":
                raise ValueError("planning_recovery_required:terminal_execution")
        failure_path = artifact_root / "finalization_failure.json"
        if failure_path.is_file():
            failure = json.loads(failure_path.read_text())
            if not isinstance(failure, dict):
                raise ValueError("finalization_receipt_invalid")
            if failure.get("status") == "failed" and int(failure.get("attempt_count", 0)) >= 2:
                raise ValueError("finalization_recovery_required:exhausted_attempts")
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
    artifact_root.mkdir(parents=True, exist_ok=True)
    archived = None if continuation else _archive_existing_run(artifact_root, archive_stale_run, validated_supplied)
    if prior:
        archived_path = _archive_recovery(artifact_root, prior["identity"]["Run ID"])
        archived = str(archived_path)
        for name in ("pre_release_check.json", "finalization_failure.json", "runtime_closure.json", "run_budget.json"):
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
                        "validate and handoff; Coordinator cannot substitute. Before each implementation slice run "
                        "the runtime guard --before-source-change finalization_packet --implementer-handle the "
                        "provider-returned handle --provider-status the freshly observed status. Wait until allowed. "
                        "Review and validation stay independent and cover the exact candidate and every criterion."
                    ),
                }
    if playbook == "techops_issue_remediation":
        instructions = {
            "current_state_investigator": (
                "Start with the exact issue and report-bearing comments. Expand to hierarchy, selected links, "
                "siblings, attachments, remote links or history only for a recorded scope, failure-path, prior-fix "
                "or rollout question. A self-contained bug does not require a sibling roster. Reuse successful "
                "reads; unselected collections are not empty. Resolve conflicting selected status/comment evidence "
                "with history. Use exact evidence IDs, never ranges, in result references."
            ),
            "dependency_analyst": (
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
                "Do not mark a check passed without its owning worker's evidence. Finalization schema belongs only in "
                "finalization, not identity. For Engineering outcome plan_only after analytical fan-in, create "
                "implementation_plan as well as output; use the accepted TechOps checks, not Sentry readiness fields. "
                "Keep the plan unapproved and external proof gates separate from local work. "
                "For a supported complete planning result, set State ready_for_implementation and Workflow outcome "
                "completed; never use handoff/incomplete as the final TechOps planning identity. "
                "Use awaiting_input or blocked when indispensable evidence or a material decision is unresolved. "
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
        for agent, (worker, namespace) in WORKERS.items():
            manifest["worker_contracts"][agent].update({
                "worker_id": worker, "id_namespace": namespace,
                "result": str(artifact_root / f"{worker.replace('-', '_')}_result.json"),
                "result_hash_required": True,
                "result_fields": {name: list(result_template[name][0])
                                  for name in ("worker_results", *TABLES)},
                "result_instructions": (
                    "Write the narrative to output and a JSON envelope to result with run_id, worker_result, "
                    "and evidence/claims/decisions/actions arrays. Use result_fields exactly; worker_result uses "
                    f"worker_results fields. Its Worker value must be exactly {worker}. "
                    "Every field value in worker_result and in evidence/claims/decisions/actions "
                    "rows must be a string, including Evidence / claim refs, Evidence refs, Claim refs and Decision ref; "
                    "join multiple references in one string, never an array. "
                    "Use E/CL/DE/A-<id_namespace>-<number> IDs and exact references. "
                    "Reference upstream IDs unchanged without copying their rows; emit only your namespace's rows. "
                    "Outcome is complete, failed or blocked, never completed. "
                    "Fix Design also supplies the four techops_checks. Do not include Feature Delivery-only "
                    "plan_readiness or implementation_plan_action fields; record unresolved decisions in the narrative "
                    "and worker_result. Do not edit the Coordinator packet or audits."
                ),
            })
        manifest["worker_result_merger"] = str(ROOT / "scripts" / "merge_techops_result.py")
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
                "result_fields": fields,
                "instructions": (
                    "Write narrative to output and JSON to result with current run_id, worker_result, "
                    "evidence/claims/decisions/actions using result_fields. worker_result is one object using the exact "
                    "worker_results fields (including capitalization), not an array or lowercase summary. "
                    "Every field value in worker_result and in evidence/claims/decisions/actions rows must be a string, "
                    "including Evidence / claim refs, Evidence refs, Claim refs and Decision ref; join multiple "
                    "references in one string, never an array. "
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
            "scope exists. A partial Draft preserves the Clarification Brief and does not approve implementation."
        )
        manifest["worker_contracts"]["current_state_investigator"]["asset_inventory"] = (
            manifest["worker_contracts"]["feature_asset_inventory"])
        manifest["worker_result_merger"] = str(ROOT / "scripts/merge_techops_result.py")
    if playbook in {"techops_issue_remediation", "sentry_issue_remediation"} or (
            playbook == "feature_delivery" and workflow_objective != "specification_assessment"):
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
    manifest["worker_runtime_guard"] = str(WORKER_RUNTIME_GUARD)
    packet_path = artifact_root / "finalization_packet.json"
    if continuation and not prior and packet_path.is_file():
        manifest["run_id"] = json.loads(packet_path.read_text())["identity"]["Run ID"]
    else:
        started_at = str(manifest.get("run_budget", {}).get("started_at") or manifest["prepared_at"])
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
            for field in ("work_item", "decisions", "claims", "evidence"):
                packet[field] = prior[field]
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
        **manifest,
    }


def self_test() -> None:
    try:
        from self_check import run_self_check
    except ModuleNotFoundError:
        from scripts.self_check import run_self_check
    run_self_check("prepare_run", "self_test")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execution-repository", type=Path)
    parser.add_argument("--work-item")
    parser.add_argument("--playbook")
    parser.add_argument("--runtime-agents", type=Path)
    parser.add_argument("--provider-session", type=Path, help="Exact current parent record for context audit and live source observations")
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
    parser.add_argument("--workflow-objective")
    parser.add_argument("--requested-outcome")
    parser.add_argument("--started-at", help="RFC 3339 end-to-end task start")
    parser.add_argument("--timebox-minutes", type=int)
    parser.add_argument("--primary-question")
    parser.add_argument("--success-criterion")
    parser.add_argument(
        "--input-manifest",
        type=Path,
        help="JSON file containing current-run context, decisions, and supporting artifacts",
    )
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.execution_repository or not args.work_item or not args.playbook:
        parser.error("--execution-repository, --work-item, and --playbook are required")
    try:
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
        )
    except (OSError, ValueError) as error:
        print(json.dumps({"status": "blocked", "reason": str(error)}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
