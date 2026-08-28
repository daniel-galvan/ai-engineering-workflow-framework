#!/usr/bin/env python3
"""Prepare fresh run artifacts and resolve Codex worker bindings."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import tomllib
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "providers" / "codex" / "model_effort_policy.md"
BUNDLED_AGENTS = ROOT / "providers" / "codex" / "agents"
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
    if name not in PLAYBOOKS:
        raise ValueError(f"unknown_playbook:{value}")
    return name


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
        "model": model,
        "effort": effort,
        "source": "runtime" if runtime_file and source == runtime_file else "bundled",
    }


def resolve_bindings(playbook: str, runtime_agents: Path | None) -> dict[str, object]:
    playbook = _playbook_name(playbook)
    names = SENTRY_AGENTS if playbook == "sentry_issue_remediation" else GENERIC_AGENTS
    return {
        "baseline_id": _baseline_id(),
        "playbook": playbook,
        "provider_tool_mapping": CODEX_TOOL_MAPPING,
        "bindings": {name: _agent_binding(name, runtime_agents) for name in names},
    }


def _archive_terminal_run(artifact_root: Path) -> str | None:
    record = artifact_root / "work_record.md"
    if not record.is_file():
        return None
    text = record.read_text()
    state = _table_value(text, "State")
    if state not in TERMINAL_STATES:
        raise ValueError("existing_run_not_terminal")
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
) -> dict[str, object]:
    playbook = _playbook_name(playbook)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", work_item):
        raise ValueError("invalid_work_item")
    if not execution_repository.resolve().is_dir():
        raise ValueError("execution_repository_unavailable")
    artifact_root = execution_repository.resolve() / ".thoughts" / work_item
    artifact_root.mkdir(parents=True, exist_ok=True)
    archived = None if continuation else _archive_terminal_run(artifact_root)
    record = artifact_root / "work_record.md"
    if continuation:
        if not record.is_file():
            raise ValueError("continuation_record_unavailable")
    elif not record.exists():
        template = "sentry_work_record.md" if playbook == "sentry_issue_remediation" else "work_record.md"
        shutil.copyfile(ROOT / "templates" / template, record)
    packet_path = artifact_root / "finalization_packet.json"
    if not continuation and not packet_path.exists():
        shutil.copyfile(ROOT / "templates" / "finalization_packet.json", packet_path)
    manifest = resolve_bindings(playbook, runtime_agents.resolve() if runtime_agents else None)
    manifest_path = artifact_root / "role_bindings.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return {
        "status": "prepared",
        "artifact_root": str(artifact_root),
        "work_record": str(record),
        "finalization_packet": str(packet_path),
        "role_binding_manifest": str(manifest_path),
        "archived_prior_run": archived,
        **manifest,
    }


def self_test() -> None:
    import tempfile

    with tempfile.TemporaryDirectory(prefix="workflow-prepare-") as directory:
        execution = Path(directory)
        first = prepare_run(execution, "ITEM-1", "playbooks/sentry_issue_remediation.md", None, False)
        assert first["playbook"] == "sentry_issue_remediation"
        assert first["bindings"]["sentry_solution_architect"]["model"] == "gpt-5.6-sol"
        assert first["provider_tool_mapping"]["repository_read"] == "exec_command"
        fixture = json.loads((ROOT / "tests" / "fixtures" / "v25_capability_mapping.json").read_text())
        assert first["provider_tool_mapping"] == fixture["expected_codex_mapping"]
        assert json.loads(Path(first["finalization_packet"]).read_text()) == json.loads(
            (ROOT / "templates" / "finalization_packet.json").read_text()
        )
        record = Path(first["work_record"])
        record.write_text(
            record.read_text().replace("| Run ID | |", "| Run ID | run-1 |").replace(
                "| State | intake |", "| State | completed |"
            )
        )
        second = prepare_run(execution, "ITEM-1", "sentry_issue_remediation", None, False)
        assert second["archived_prior_run"].endswith("runs/run-1")
        assert Path(second["work_record"]).is_file()
        try:
            prepare_run(execution, "ITEM-2", "playbooks/unknown.md", None, False)
        except ValueError as error:
            assert str(error) == "unknown_playbook:playbooks/unknown.md"
        else:
            raise AssertionError("unknown playbook must be rejected")
    print("prepare_run self-test: passed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execution-repository", type=Path)
    parser.add_argument("--work-item")
    parser.add_argument("--playbook")
    parser.add_argument("--runtime-agents", type=Path)
    parser.add_argument("--continuation", action="store_true")
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
        )
    except ValueError as error:
        print(json.dumps({"status": "blocked", "reason": str(error)}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
