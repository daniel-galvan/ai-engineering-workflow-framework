#!/usr/bin/env python3
"""Prepare fresh run artifacts and resolve Codex worker bindings."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import tomllib
from datetime import UTC, datetime
from pathlib import Path

try:
    from run_input_manifest import (
        DEFAULT_PRECEDENCE_RULE,
        default_manifest,
        load_manifest,
        merge_manifests,
        packet_metadata,
        write_manifest,
    )
except ModuleNotFoundError:  # Imported as scripts.prepare_run from the repository root.
    from scripts.run_input_manifest import (
        DEFAULT_PRECEDENCE_RULE,
        default_manifest,
        load_manifest,
        merge_manifests,
        packet_metadata,
        write_manifest,
    )


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "providers" / "codex" / "model_effort_policy.md"
BUNDLED_AGENTS = ROOT / "providers" / "codex" / "agents"
PLUGIN_MANIFEST = ROOT / ".codex-plugin" / "plugin.json"
SENTRY_FIX_DESIGN_CONTRACT = ROOT / "templates" / "sentry_fix_design_result_contract.json"
SENTRY_NORMALIZED_EVIDENCE_CONTRACT = ROOT / "templates" / "sentry_normalized_evidence_contract.md"
SENTRY_FIX_DESIGN_NORMALIZER = ROOT / "scripts" / "normalize_fix_design_result.py"
SENTRY_PLANNING_FINALIZER = ROOT / "scripts" / "finalize_sentry_planning.py"
WORKER_RUNTIME_GUARD = ROOT / "scripts" / "validate_worker_runtime.py"
RUN_INPUTS_FILENAME = "run_inputs.json"
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
PROMPT_TEMPLATES = {
    "feature_delivery": "feature_delivery_run_prompt.md",
    "sentry_issue_remediation": "sentry_issue_run_prompt.md",
    "techops_issue_remediation": "techops_issue_run_prompt.md",
    "vulnerability_investigation": "vulnerability_issue_run_prompt.md",
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


def _document_version(path: Path) -> str:
    match = re.search(r"^version:\s*(\S+)\s*$", path.read_text(), re.MULTILINE)
    if not match:
        raise ValueError(f"document_version_unavailable:{path.relative_to(ROOT)}")
    return match.group(1)


def _initial_packet(
    artifact_root: Path,
    work_item: str,
    playbook: str,
    runtime_agents: Path | None,
    manifest: dict[str, object],
    manifest_path: Path,
) -> dict[str, object]:
    packet = json.loads((ROOT / "templates" / "finalization_packet.json").read_text())
    playbook_path = ROOT / "playbooks" / f"{playbook}.md"
    prompt_path = ROOT / "templates" / PROMPT_TEMPLATES[playbook]
    plugin = json.loads(PLUGIN_MANIFEST.read_text())
    input_manifest = manifest["run_input_manifest"]
    packet["work_item"]["ID"] = work_item
    packet["inputs"] = list(input_manifest["inputs"])
    packet["run_input_manifest"] = input_manifest
    packet["playbook_selection"]["Selected playbook"] = playbook
    packet["identity"].update({
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
    }
    packets: dict[str, dict[str, object]] = {}
    for agent, binding in manifest["bindings"].items():
        definition = Path(binding["definition"])
        configuration = tomllib.loads(definition.read_text())
        developer_instructions = configuration.get("developer_instructions")
        if not isinstance(developer_instructions, str) or not developer_instructions.strip():
            raise ValueError(f"provider_instructions_unavailable:{agent}")
        packet = {
            "schema_version": 1,
            "required_prefix": "Coordinator initialization: complete",
            "agent": agent,
            "definition": binding["definition"],
            "definition_sha256": binding["definition_sha256"],
            "model": binding["model"],
            "effort": binding["effort"],
            "source": binding["source"],
            "provider_tool_mapping": manifest["provider_tool_mapping"],
            "run_input_manifest": manifest["run_input_manifest"],
            "coordinator_execution": manifest["coordinator_execution"],
            "worker_contract": contract_by_agent.get(agent),
            "developer_instructions": developer_instructions.strip(),
        }
        packets[agent] = packet
    path = artifact_root / "worker_activation_packets.json"
    path.write_text(json.dumps({"schema_version": 1, "packets": packets}, indent=2, sort_keys=True) + "\n")
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _prepare_run_inputs(
    artifact_root: Path,
    work_item: str,
    playbook: str,
    execution_repository: Path,
    supplied_path: Path | None,
    continuation: bool,
    validated_supplied: dict[str, object] | None = None,
) -> tuple[dict[str, object], Path]:
    destination = artifact_root / RUN_INPUTS_FILENAME
    if continuation and destination.is_file():
        current = load_manifest(destination, explicit=False)
        if supplied_path:
            current = merge_manifests(current, load_manifest(supplied_path, explicit=True))
            write_manifest(destination, current)
        return load_manifest(destination, explicit=False), destination
    if supplied_path:
        source = validated_supplied or load_manifest(supplied_path, explicit=True)
    else:
        source = default_manifest(work_item, playbook, execution_repository.resolve())
    return write_manifest(destination, source), destination


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
        "baseline_id": _baseline_id(),
        "playbook": playbook,
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


def _archive_existing_run(artifact_root: Path, archive_stale_run: bool) -> str | None:
    record = artifact_root / "work_record.md"
    if not record.is_file():
        return None
    text = record.read_text()
    state = _table_value(text, "State")
    if state not in TERMINAL_STATES:
        if not archive_stale_run:
            raise ValueError("existing_run_not_terminal")
        run_id = datetime.now(UTC).strftime("stale-%Y%m%dT%H%M%SZ")
    else:
        run_id = _table_value(text, "Run ID")
    if not run_id or run_id in {"Unknown", "None"}:
        run_id = datetime.now(UTC).strftime("run-%Y%m%dT%H%M%SZ")
    destination = artifact_root / "runs" / re.sub(r"[^A-Za-z0-9._-]", "_", run_id)
    if destination.exists():
        raise ValueError("prior_run_archive_exists")
    destination.mkdir(parents=True)
    for path in artifact_root.iterdir():
        if path.name == "runs":
            continue
        shutil.move(str(path), destination / path.name)
    return str(destination)


def prepare_run(
    execution_repository: Path,
    work_item: str,
    playbook: str,
    runtime_agents: Path | None,
    continuation: bool,
    archive_stale_run: bool = False,
    input_manifest: Path | None = None,
) -> dict[str, object]:
    playbook = _playbook_name(playbook)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", work_item):
        raise ValueError("invalid_work_item")
    if not execution_repository.resolve().is_dir():
        raise ValueError("execution_repository_unavailable")
    if continuation and archive_stale_run:
        raise ValueError("continuation_cannot_archive_stale_run")
    resolved_execution_repository = execution_repository.resolve()
    artifact_root = resolved_execution_repository / ".thoughts" / work_item
    # Validate supplied input and provider bindings before creating, archiving, or
    # overwriting any run artifact. This makes invalid retries transactional.
    validated_supplied = load_manifest(input_manifest, explicit=True) if input_manifest else None
    resolved_runtime_agents = runtime_agents.resolve() if runtime_agents else None
    manifest = resolve_bindings(playbook, resolved_runtime_agents)
    artifact_root.mkdir(parents=True, exist_ok=True)
    archived = None if continuation else _archive_existing_run(artifact_root, archive_stale_run)
    record = artifact_root / "work_record.md"
    if continuation:
        if not record.is_file():
            raise ValueError("continuation_record_unavailable")
    elif not record.exists():
        template = "sentry_work_record.md" if playbook == "sentry_issue_remediation" else "work_record.md"
        shutil.copyfile(ROOT / "templates" / template, record)
    run_inputs, run_inputs_path = _prepare_run_inputs(
        artifact_root, work_item, playbook, resolved_execution_repository, input_manifest, continuation,
        validated_supplied,
    )
    manifest["run_input_manifest"] = packet_metadata(run_inputs_path, run_inputs)
    manifest["run_input_manifest"]["inputs"] = run_inputs["inputs"]
    manifest["run_input_manifest"]["precedence_rule"] = run_inputs["precedence_rule"]
    fix_design_contract = None
    normalized_evidence_contract = None
    if playbook == "sentry_issue_remediation":
        fix_design_contract = artifact_root / "fix_design_result_contract.json"
        shutil.copyfile(SENTRY_FIX_DESIGN_CONTRACT, fix_design_contract)
        normalized_evidence_contract = artifact_root / "normalized_evidence_contract.md"
        shutil.copyfile(SENTRY_NORMALIZED_EVIDENCE_CONTRACT, normalized_evidence_contract)
        manifest["worker_contracts"] = {
            "evidence_topology": {
                "contract": str(normalized_evidence_contract),
                "output": str(artifact_root / "normalized_evidence.md"),
            },
            "fix_design": {
                "contract": str(fix_design_contract),
                "normalizer": str(SENTRY_FIX_DESIGN_NORMALIZER),
                "output": str(artifact_root / "fix_design_result.json"),
            },
            "standard_planning_finalization": {
                "finalizer": str(SENTRY_PLANNING_FINALIZER),
                "owner": "Coordinator",
            },
        }
    manifest["worker_runtime_guard"] = str(WORKER_RUNTIME_GUARD)
    manifest["activation_packet_bundle"] = _write_activation_packets(artifact_root, manifest)
    manifest_path = artifact_root / "role_bindings.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    packet_path = artifact_root / "finalization_packet.json"
    if not continuation and not packet_path.exists():
        packet = _initial_packet(artifact_root, work_item, playbook, resolved_runtime_agents, manifest, manifest_path)
        packet_path.write_text(json.dumps(packet, indent=2) + "\n")
    elif continuation and packet_path.is_file():
        packet = json.loads(packet_path.read_text())
        packet["run_input_manifest"] = manifest["run_input_manifest"]
        existing_inputs = packet.get("inputs")
        existing_ids = {
            str(row.get("Input ID", "")) for row in existing_inputs
            if isinstance(row, dict)
        } if isinstance(existing_inputs, list) else set()
        packet["inputs"] = list(existing_inputs) if isinstance(existing_inputs, list) else []
        packet["inputs"].extend(
            row for row in run_inputs["inputs"] if str(row["Input ID"]) not in existing_ids
        )
        packet["identity"]["Run input manifest"] = manifest["run_input_manifest"]["path"]
        packet_path.write_text(json.dumps(packet, indent=2) + "\n")
    return {
        "status": "prepared",
        "artifact_root": str(artifact_root),
        "work_record": str(record),
        "finalization_packet": str(packet_path),
        "run_input_manifest": str(run_inputs_path),
        "run_input_manifest_status": run_inputs["status"],
        "role_binding_manifest": str(manifest_path),
        "fix_design_result_contract": str(fix_design_contract) if fix_design_contract else None,
        "normalized_evidence_contract": (
            str(normalized_evidence_contract) if normalized_evidence_contract else None
        ),
        "archived_prior_run": archived,
        **manifest,
    }


def self_test() -> None:
    import tempfile

    with tempfile.TemporaryDirectory(prefix="workflow-prepare-") as directory:
        execution = Path(directory)
        input_source = execution / "inputs.json"
        input_source.write_text(json.dumps({
            "schema_version": 1,
            "precedence_rule": DEFAULT_PRECEDENCE_RULE,
            "inputs": [{
                "Input ID": "USER-001",
                "Input or artifact": "Supplied current-run context",
                "Source or path": "Current user request",
                "Authority": "Authoritative current-run context",
                "Classification": "observed report or requested outcome",
                "Expected use": "Evidence worker and Fix Design",
                "Status": "Registered",
            }],
        }))
        first_input = execution / "first-input.md"
        second_input = execution / "second-input.md"
        first_input.write_text("first\n")
        second_input.write_text("second\n")
        composite_source = execution / "composite-inputs.json"
        composite_source.write_text(json.dumps({
            "schema_version": 1,
            "precedence_rule": DEFAULT_PRECEDENCE_RULE,
            "inputs": [{
                "Input ID": "USER-002",
                "Input or artifact": "Two supplied guidance files",
                "Source or path": f"{first_input}; {second_input}",
                "Authority": "Authoritative current-run context",
                "Status": "Registered",
            }],
        }))
        composite = load_manifest(composite_source, explicit=True)["inputs"][0]
        assert composite["availability"] == "available"
        assert composite["paths"] == [str(first_input.resolve()), str(second_input.resolve())]
        implicit_source = execution / "implicit-inputs.json"
        implicit_source.write_text(json.dumps({
            "schema_version": 1,
            "inputs": [{
                "Input ID": "USER-IMPLICIT",
                "Input or artifact": "Manifest without an explicit precedence rule",
                "Source or path": "Current user request",
                "Authority": "Authoritative current-run context",
                "Status": "Registered",
            }],
        }))
        implicit = load_manifest(implicit_source, explicit=True)
        assert implicit["precedence_rule"] == DEFAULT_PRECEDENCE_RULE
        first = prepare_run(
            execution, "ITEM-1", "playbooks/sentry_issue_remediation.md", None, False,
            input_manifest=input_source,
        )
        assert first["playbook"] == "sentry_issue_remediation"
        assert first["bindings"]["sentry_solution_architect"]["model"] == "gpt-5.6-sol"
        assert first["provider_tool_mapping"]["repository_read"] == "exec_command"
        fixture = json.loads((ROOT / "tests" / "fixtures" / "v25_capability_mapping.json").read_text())
        assert first["provider_tool_mapping"] == fixture["expected_codex_mapping"]
        assert first["provider_configuration_source_status"] == "bundled / resolved"
        assert Path(first["fix_design_result_contract"]).is_file()
        assert Path(first["normalized_evidence_contract"]).is_file()
        assert first["worker_contracts"]["evidence_topology"]["contract"] == first[
            "normalized_evidence_contract"
        ]
        assert first["worker_contracts"]["fix_design"]["contract"] == first["fix_design_result_contract"]
        assert first["worker_runtime_guard"] == str(WORKER_RUNTIME_GUARD)
        activation_bundle = Path(first["activation_packet_bundle"]["path"])
        assert activation_bundle.is_file()
        evidence_packet = json.loads(activation_bundle.read_text())["packets"][
            "sentry_current_state_investigator"
        ]
        assert evidence_packet["required_prefix"] == "Coordinator initialization: complete"
        assert evidence_packet["developer_instructions"].startswith("Own raw Sentry evidence")
        assert evidence_packet["worker_contract"]["output"].endswith("normalized_evidence.md")
        assert hashlib.sha256(activation_bundle.read_bytes()).hexdigest() == first[
            "activation_packet_bundle"
        ]["sha256"]
        prepared_manifest = json.loads(Path(first["role_binding_manifest"]).read_text())
        assert prepared_manifest["worker_contracts"]["fix_design"]["normalizer"] == str(
            SENTRY_FIX_DESIGN_NORMALIZER
        )
        assert prepared_manifest["worker_contracts"]["standard_planning_finalization"]["finalizer"] == str(
            SENTRY_PLANNING_FINALIZER
        )
        runtime = execution / "agents"
        runtime.mkdir()
        for name in SENTRY_AGENTS:
            (runtime / f"{name}.toml").symlink_to(BUNDLED_AGENTS / f"{name}.toml")
        linked = resolve_bindings("sentry_issue_remediation", runtime)
        assert linked["provider_configuration_source_status"] == "runtime / resolved (9 definitions; 9 symlinked)"
        prepared_packet = json.loads(Path(first["finalization_packet"]).read_text())
        assert prepared_packet["work_item"]["ID"] == "ITEM-1"
        assert prepared_packet["identity"]["Role binding manifest"] == first["role_binding_manifest"]
        assert prepared_packet["identity"]["Prompt template / revision / conformance"].endswith(" / pending")
        assert prepared_packet["durable_artifacts"][0]["Artifact"] == "Role bindings"
        assert first["run_input_manifest_status"] == "explicit"
        assert prepared_packet["inputs"][0]["Input ID"] == "USER-001"
        assert prepared_packet["run_input_manifest"]["status"] == "explicit"
        assert prepared_packet["identity"]["Coordinator execution"].startswith("active parent session")
        assert _playbook_name("Sentry Issue Remediation") == "sentry_issue_remediation"
        assert _playbook_name("Sentry Issue Remediation Playbook") == "sentry_issue_remediation"
        record = Path(first["work_record"])
        record.write_text(
            record.read_text().replace("| Run ID | |", "| Run ID | run-1 |").replace(
                "| State | intake |", "| State | completed |"
            )
        )
        second = prepare_run(
            execution, "ITEM-1", "sentry_issue_remediation", None, False,
            input_manifest=input_source,
        )
        assert second["archived_prior_run"].endswith("runs/run-1")
        assert Path(second["work_record"]).is_file()
        stale = prepare_run(
            execution, "ITEM-STALE", "sentry_issue_remediation", None, False,
            input_manifest=input_source,
        )
        stale_artifact = Path(stale["artifact_root"]) / "normalized_evidence.md"
        stale_artifact.write_text("preserved stale evidence\n")
        try:
            prepare_run(
                execution, "ITEM-STALE", "sentry_issue_remediation", None, False,
                input_manifest=input_source,
            )
        except ValueError as error:
            assert str(error) == "existing_run_not_terminal"
        else:
            raise AssertionError("unverified nonterminal run must block")
        recovered = prepare_run(
            execution, "ITEM-STALE", "sentry_issue_remediation", None, False,
            archive_stale_run=True, input_manifest=input_source,
        )
        archived_stale = Path(recovered["archived_prior_run"])
        assert archived_stale.name.startswith("stale-")
        assert (archived_stale / "normalized_evidence.md").read_text() == "preserved stale evidence\n"
        assert _table_value(Path(recovered["work_record"]).read_text(), "State") == "intake"
        try:
            prepare_run(execution, "ITEM-2", "playbooks/unknown.md", None, False)
        except ValueError as error:
            assert str(error) == "unknown_playbook:playbooks/unknown.md"
        else:
            raise AssertionError("unknown playbook must be rejected")
        invalid_source = execution / "invalid-inputs.json"
        invalid_source.write_text(json.dumps({
            "schema_version": 1,
            "precedence_rule": "",
            "inputs": [{
                "Input ID": "USER-INVALID",
                "Input or artifact": "Invalid fixture",
                "Source or path": "Current user request",
                "Authority": "Authoritative current-run context",
                "Status": "Registered",
            }],
        }))
        try:
            prepare_run(
                execution, "ITEM-INVALID", "sentry_issue_remediation", None, False,
                input_manifest=invalid_source,
            )
        except ValueError as error:
            assert str(error) == "run_input_manifest_precedence_rule_empty"
        else:
            raise AssertionError("invalid input manifest must be rejected before artifact creation")
        assert not (execution / ".thoughts" / "ITEM-INVALID").exists()
    print("prepare_run self-test: passed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execution-repository", type=Path)
    parser.add_argument("--work-item")
    parser.add_argument("--playbook")
    parser.add_argument("--runtime-agents", type=Path)
    parser.add_argument("--continuation", action="store_true")
    parser.add_argument("--archive-stale-run", action="store_true")
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
        )
    except ValueError as error:
        print(json.dumps({"status": "blocked", "reason": str(error)}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
