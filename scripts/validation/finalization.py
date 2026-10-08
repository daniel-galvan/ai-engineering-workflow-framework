"""Deterministic finalization validation rules."""

from __future__ import annotations

from pathlib import Path
import json
import subprocess
from .common import (
    CODEX_AGENT_DIR,
    FINALIZATION_PACKET_TEMPLATE,
    FINALIZE_SENTRY_PLANNING,
    FINALIZE_WORK_RECORD,
    NORMALIZE_FIX_DESIGN_RESULT,
    NO_ACTIVE_HANDLES,
    PREPARE_RUN,
    PROHIBITED_CONTEXT_MARKERS,
    ROOT,
    RUNTIME_CLOSURE_TEMPLATE,
    RUN_PREFLIGHT,
    RUN_SKILL,
    SENTRY_EVIDENCE_INPUT_MARKERS,
    SENTRY_FIX_DESIGN_CONTRACT,
    SENTRY_NORMALIZED_EVIDENCE_CONTRACT,
    SENTRY_WORK_RECORD_TEMPLATE,
    V36_SENTRY_FINALIZATION_FIXTURE,
    V40_RUNTIME_FIXTURE,
    WORKER_RUNTIME_GUARD,
    fail,
)
from .contracts import (
    fix_design_result_errors,
    sentry_contract_delta_errors,
    sentry_upstream_boundary_errors,
)
from .work_records import (
    validate_work_record,
)
try:
    from run_input_manifest import load_manifest
except ModuleNotFoundError:
    from scripts.run_input_manifest import load_manifest


def validate_sentry_artifacts(root: Path, *, allow_unreleased: bool = False) -> None:
    errors: list[str] = []
    packet_path = root / "finalization_packet.json"
    run_inputs_path = root / "run_inputs.json"
    packet: dict[str, object] = {}
    if packet_path.is_file():
        try:
            candidate = json.loads(packet_path.read_text())
        except (json.JSONDecodeError, OSError):
            candidate = {}
        if isinstance(candidate, dict):
            packet = candidate
    metadata = packet.get("run_input_manifest")
    if metadata is not None or run_inputs_path.is_file():
        if not isinstance(metadata, dict):
            errors.append("finalization_packet.json is missing run_input_manifest metadata")
        else:
            declared = Path(str(metadata.get("path", "")))
            if declared.name != "run_inputs.json":
                errors.append("run_input_manifest metadata must reference run_inputs.json")
            if not run_inputs_path.is_file():
                errors.append("run_inputs.json is missing")
            else:
                import hashlib

                if hashlib.sha256(run_inputs_path.read_bytes()).hexdigest() != str(metadata.get("sha256", "")):
                    errors.append("run_input_manifest hash does not match finalization metadata")
                else:
                    try:
                        run_inputs = load_manifest(run_inputs_path, explicit=False)
                    except ValueError as error:
                        errors.append(str(error))
                    else:
                        if run_inputs.get("status") != "explicit":
                            errors.append("run_input_manifest_required")
                        expected_ids = [str(value) for value in metadata.get("input_ids", [])]
                        actual_ids = [str(row["Input ID"]) for row in run_inputs["inputs"]]
                        if expected_ids != actual_ids:
                            errors.append("run_input_manifest metadata does not match its inputs")
                        packet_ids = {
                            str(row.get("Input ID", "")) for row in packet.get("inputs", [])
                            if isinstance(row, dict)
                        }
                        missing = [value for value in actual_ids if value not in packet_ids]
                        if missing:
                            errors.append("finalization packet dropped run inputs: " + ", ".join(missing))
    evidence = root / "normalized_evidence.md"
    evidence_text = ""
    design = root / "fix_design_result.json"
    if not evidence.is_file():
        errors.append("normalized_evidence.md is missing")
    else:
        evidence_text = evidence.read_text()
        errors.extend(sentry_contract_delta_errors(evidence_text))
        for marker in PROHIBITED_CONTEXT_MARKERS:
            if marker in evidence_text:
                errors.append(f"normalized evidence contains prohibited context marker: {marker}")
    if not design.is_file():
        errors.append("fix_design_result.json is missing")
    else:
        try:
            result = json.loads(design.read_text())
        except (json.JSONDecodeError, OSError) as error:
            errors.append(f"invalid fix_design_result.json: {error}")
        else:
            manifest_path = root / "role_bindings.json"
            require_plan = False
            if manifest_path.is_file():
                try:
                    manifest = json.loads(manifest_path.read_text())
                except (json.JSONDecodeError, OSError):
                    manifest = {}
                require_plan = "standard_planning_finalization" in manifest.get("worker_contracts", {})
            errors.extend(fix_design_result_errors(
                result,
                required_input_markers=SENTRY_EVIDENCE_INPUT_MARKERS,
                require_plan=require_plan,
            ))
            if isinstance(result, dict):
                errors.extend(sentry_upstream_boundary_errors(
                    evidence_text, result, require_plan=require_plan
                ))
    if errors:
        fail(f"{root}: " + "\nFAIL: ".join(errors))
    if allow_unreleased:
        return
    packet_path = root / "finalization_packet.json"
    closure_path = root / "runtime_closure.json"
    if packet_path.is_file() and closure_path.is_file():
        try:
            packet = json.loads(packet_path.read_text())
            closure = json.loads(closure_path.read_text())
        except (json.JSONDecodeError, OSError):
            return
        closure_rows = closure.get("runtime_closure", [])
        released = bool(closure_rows) and all(
            isinstance(row, dict)
            and str(row.get("Runtime status", "")).strip().lower() == "released"
            and NO_ACTIVE_HANDLES.fullmatch(str(row.get("Remaining active handles", "")).strip())
            for row in closure_rows
        )
        terminal_packet = (
            str(packet.get("handoff", {}).get("workflow_result", "")).strip()
            and str(packet.get("finalization", {}).get("Final reconciliation", ""))
            .strip()
            .lower()
            .startswith("passed")
        )
        if released and terminal_packet:
            record = root / "work_record.md"
            if not record.is_file():
                fail(f"{root}: released terminal artifact set requires work_record.md")
            validate_work_record(record, require_terminal=True)


def validate_normalized_evidence(path: Path) -> None:
    if not path.is_file():
        fail(f"normalized evidence does not exist: {path}")
    errors = sentry_contract_delta_errors(path.read_text())
    if errors:
        fail(f"{path}: " + "\nFAIL: ".join(errors))


def validate_finalization_definitions() -> None:
    work_record_template = (ROOT / "templates" / "work_record.md").read_text()
    if not RUN_SKILL.is_file():
        fail("skills/run/SKILL.md is missing")
    if not RUN_PREFLIGHT.is_file():
        fail("scripts/run_preflight.py is missing")
    if not PREPARE_RUN.is_file():
        fail("scripts/prepare_run.py is missing")
    if not WORKER_RUNTIME_GUARD.is_file():
        fail("scripts/validate_worker_runtime.py is missing")
    else:
        worker_runtime_self_test = subprocess.run(
            ["python3", str(WORKER_RUNTIME_GUARD), "--self-test"],
            capture_output=True,
            text=True,
            check=False,
        )
        if worker_runtime_self_test.returncode:
            fail(
                "scripts/validate_worker_runtime.py self-test failed: "
                + (worker_runtime_self_test.stdout + worker_runtime_self_test.stderr).strip()
            )
    if not V40_RUNTIME_FIXTURE.is_file():
        fail("tests/fixtures/v40_sentry_worker_runtime.json is missing")
    if not FINALIZE_WORK_RECORD.is_file():
        fail("scripts/finalize_work_record.py is missing")
    if not FINALIZE_SENTRY_PLANNING.is_file():
        fail("scripts/finalize_sentry_planning.py is missing")
    if not NORMALIZE_FIX_DESIGN_RESULT.is_file():
        fail("scripts/normalize_fix_design_result.py is missing")
    else:
        normalizer_self_test = subprocess.run(
            ["python3", str(NORMALIZE_FIX_DESIGN_RESULT), "--self-test"],
            capture_output=True,
            text=True,
            check=False,
        )
        if normalizer_self_test.returncode:
            fail(
                "scripts/normalize_fix_design_result.py self-test failed: "
                + (normalizer_self_test.stdout + normalizer_self_test.stderr).strip()
            )
    for template in (FINALIZATION_PACKET_TEMPLATE, RUNTIME_CLOSURE_TEMPLATE):
        if not template.is_file():
            fail(f"{template.relative_to(ROOT)} is missing")
        else:
            try:
                json.loads(template.read_text())
            except json.JSONDecodeError as error:
                fail(f"{template.relative_to(ROOT)} is invalid JSON: {error}")
    if not SENTRY_FIX_DESIGN_CONTRACT.is_file():
        fail("templates/sentry_fix_design_result_contract.json is missing")
    else:
        try:
            fix_design_contract = json.loads(SENTRY_FIX_DESIGN_CONTRACT.read_text())
        except json.JSONDecodeError as error:
            fail(f"templates/sentry_fix_design_result_contract.json is invalid JSON: {error}")
        else:
            contract_fields = set(fix_design_contract.get("required_fields", {}))
            if contract_fields != {
                "worker_id",
                "worker_handle",
                "outcome",
                "plan_readiness",
                "implementation_plan_action",
                "inputs_consumed",
                "context_conformance",
                "configuration_conformance",
                "checks_performed",
                "checks_remaining",
                "supported_remediation_boundary",
                "supported_intended_change",
                "interface_change",
                "interface_contract",
                "blocking_unknowns",
                "confidence",
            }:
                fail("templates/sentry_fix_design_result_contract.json has an invalid required-field set")
    if not SENTRY_NORMALIZED_EVIDENCE_CONTRACT.is_file():
        fail("templates/sentry_normalized_evidence_contract.md is missing")
    else:
        normalized_evidence_contract = SENTRY_NORMALIZED_EVIDENCE_CONTRACT.read_text()
        for phrase in (
            "## Run Scope",
            "## Source Register",
            "## Confirmed Facts",
            "## Best Current Hypotheses",
            "## Topology",
            "## Uncertainty and Checks Remaining",
            "# Contract Delta",
            "validator implementation or regression fixtures is not part",
        ):
            if phrase not in normalized_evidence_contract:
                fail(f"templates/sentry_normalized_evidence_contract.md is missing {phrase}")
    if not V36_SENTRY_FINALIZATION_FIXTURE.is_file():
        fail("tests/fixtures/v36_sentry_finalization_regression.json is missing")
    else:
        v36_fixture = json.loads(V36_SENTRY_FINALIZATION_FIXTURE.read_text())
        valid_v36_fix = json.loads(json.dumps(v36_fixture["fix_design_result"]))
        valid_v36_fix["confidence"] = v36_fixture["expected_confidence"]
        if fix_design_result_errors(valid_v36_fix, required_input_markers=SENTRY_EVIDENCE_INPUT_MARKERS, require_plan=True):
            fail("v36 valid field-identity regression fixture must pass Fix Design validation")
        invalid_v36_fix = json.loads(json.dumps(valid_v36_fix))
        invalid_v36_fix["interface_contract"]["response_shape"] = v36_fixture["invalid_unqualified_response_shape"]
        invalid_v36_errors = fix_design_result_errors(
            invalid_v36_fix,
            required_input_markers=SENTRY_EVIDENCE_INPUT_MARKERS,
            require_plan=True,
        )
        if v36_fixture["expected_identity_error"] not in invalid_v36_errors:
            fail("v36 unqualified-response regression fixture must fail response-side identity validation")
    if not SENTRY_WORK_RECORD_TEMPLATE.is_file():
        fail("templates/sentry_work_record.md is missing")


def validate_closure_definitions() -> None:
    if '"Receipt owner": "Coordinator"' not in RUNTIME_CLOSURE_TEMPLATE.read_text():
        fail("templates/runtime_closure.json must assign the provider receipt to the Coordinator")
    for phrase in (
        "finalization_packet.json",
        "scripts/finalize_work_record.py",
        "do not patch `work_record.md`",
        "awaiting_input` is a Fix Design readiness value",
    ):
        if phrase not in (CODEX_AGENT_DIR / "documenter.toml").read_text():
            fail(f"providers/codex/agents/documenter.toml is missing deterministic finalization control: {phrase}")
    for path in (
        CODEX_AGENT_DIR / "orchestrator.toml",
        CODEX_AGENT_DIR / "sentry_orchestrator.toml",
        ROOT / "templates" / "sentry_issue_run_prompt.md",
    ):
        text = path.read_text()
        for phrase in (
            "`spawn_agent`", "Never use", "`create_thread`", "`fork_thread`", "`send_message_to_thread`",
            "worker_runtime_unavailable", "current-run input manifest", "run_inputs.json",
        ):
            if phrase not in text:
                fail(f"{path.relative_to(ROOT)} is missing task-isolation control: {phrase}")


def validate_final_documenter_rules() -> None:
    documenter_role = (ROOT / "roles/documenter.md").read_text()
    documenter_agent = (CODEX_AGENT_DIR / "documenter.toml").read_text()
    for text, label in (
        (documenter_role, "roles/documenter.md"),
        (documenter_agent, "providers/codex/agents/documenter.toml"),
    ):
        if "Standard Sentry planning" not in text or "Normal runs do not record byte counts or budget exceptions" not in text:
            fail(f"{label} is missing Standard Sentry artifact control")
        if (
            "runtime-managed worktrees are not" not in text
            or "artifact roots unless" not in text
            or "direct children of the declared current-run artifact" not in text
        ):
            fail(f"{label} is missing durable artifact-root control")

    for phrase in ("do not patch `work_record.md`", "finish within two minutes", "sole writer", "Best current explanations"):
        if phrase not in documenter_agent:
            fail(f"providers/codex/agents/documenter.toml is missing bounded finalization control: {phrase}")

    for phrase in ("pre-release source snapshot", "finalized packet", "reserve `plan_only`"):
        if phrase not in documenter_agent:
            fail(f"providers/codex/agents/documenter.toml is missing final-handoff control: {phrase}")

    for phrase in ("finalization-schema result", "required artifact set by name"):
        if phrase not in documenter_agent:
            fail(f"providers/codex/agents/documenter.toml is missing terminal-schema control: {phrase}")

    for phrase in ("next-action owner", "canonical human-readable handoff"):
        if phrase not in documenter_role.lower():
            fail(f"roles/documenter.md is missing final-handoff ownership: {phrase}")

    for name in (
        "current_state_investigator.toml",
        "dependency_analyst.toml",
        "repository_integrator.toml",
        "solution_architect.toml",
    ):
        text = (CODEX_AGENT_DIR / name).read_text()
        if "Memory is isolated for new runs" not in text or "do not cite, import, summarize, or use" not in text:
            fail(f"providers/codex/agents/{name} is missing assigned-context isolation")

    for name in (
        "sentry_current_state_investigator.toml",
        "sentry_repository_integrator.toml",
        "sentry_solution_architect.toml",
        "documenter.toml",
    ):
        text = (CODEX_AGENT_DIR / name).read_text()
        if "Memory is isolated for new runs" not in text or "do not" not in text:
            fail(f"providers/codex/agents/{name} is missing memory isolation")

    for path in (
        RUN_SKILL,
        ROOT / "contracts" / "workflow_execution.md",
        ROOT / "templates" / "sentry_issue_run_prompt.md",
        *CODEX_AGENT_DIR.glob("*.toml"),
    ):
        lowered = path.read_text().lower()
        if (
            "higher-priority runtime instructions require a memory pass" in lowered
            or "provider-required memory pass" in lowered
        ):
            fail(f"{path.relative_to(ROOT)} retains the retired memory-pass escape hatch")
