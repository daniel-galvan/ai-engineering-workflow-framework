"""Deterministic work records validation rules."""

from __future__ import annotations

from pathlib import Path
from . import common
import hashlib
import json
import re
import subprocess
import sys
import tomllib
from .common import (
    LARGE_WORK_RECORD_BYTES,
    MODEL_BASELINE_ID,
    NO_ACTIVE_HANDLES,
    PROHIBITED_CONTEXT_MARKERS,
    RANGE_REFERENCE,
    REFERENCE_ID,
    ROLE_AGENT_ALIASES,
    ROOT,
    SENTRY_EVIDENCE_INPUT_MARKERS,
    SENTRY_ROLE_AGENTS,
    STALE_FINALIZER_REFERENCE,
    TERMINAL_STATES,
    UNOBSERVED_MODEL_VALUES,
    WORKER_OUTCOMES,
    fail,
)
from .contracts import (
    RFC3339_TIMESTAMP,
    _contains_hypothesis,
    _mentions_user_source,
    fix_design_result_errors,
    reasoning_record_errors,
    sentry_contract_delta_errors,
    sentry_upstream_boundary_errors,
    terminal_semantics_errors,
)
from .frontmatter import (
    frontmatter_value,
)
from .markdown import (
    fenced_section,
    markdown_table,
)
from .playbooks import (
    feature_assessment_disposition_error,
    technical_spike_disposition_error,
    technical_spike_report_errors,
)
from .provider_policy import (
    model_observation_unavailable,
)
from .references import (
    _artifact_path,
    current_artifact_errors,
)
try:
    from asset_manifest import ASSET_MANIFEST_FILENAME, asset_plan_errors, validate_asset_manifest
except ModuleNotFoundError:
    from scripts.asset_manifest import ASSET_MANIFEST_FILENAME, asset_plan_errors, validate_asset_manifest
try:
    from review_evidence import applicability_errors, completed_review_errors
except ModuleNotFoundError:
    from scripts.review_evidence import applicability_errors, completed_review_errors
try:
    from run_input_manifest import load_manifest
except ModuleNotFoundError:
    from scripts.run_input_manifest import load_manifest
try:
    from specification_assessment import NO_PLAN_MESSAGE, REPORT_NAME, assessment_report_errors
except ModuleNotFoundError:
    from scripts.specification_assessment import NO_PLAN_MESSAGE, REPORT_NAME, assessment_report_errors


def _feature_record_expected_inputs(
    text: str, identity: dict[str, str], root: Path,
) -> tuple[dict[str, dict[str, str]], list[str]]:
    record_rows = {
        row.get("Input ID", ""): row
        for row in markdown_table(text, "# Input Register")
        if row.get("Input ID", "").strip()
    }
    reference = str(identity.get("Run input manifest", "")).strip()
    if not reference or reference.lower() in {"none", "not applicable"}:
        return record_rows, ["Feature Delivery requires Run input manifest for asset source reconciliation"]
    path = Path(reference)
    path = path if path.is_absolute() else root / path
    if not path.is_file():
        return record_rows, [f"Feature Delivery requires readable run_inputs.json for asset source reconciliation: {path}"]
    expected_hash = str(identity.get("Run input manifest hash", "")).strip()
    if not expected_hash:
        return record_rows, ["Feature Delivery requires the run_inputs.json content hash for asset source reconciliation"]
    try:
        actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        return record_rows, [f"Feature Delivery cannot hash run_inputs.json for asset source reconciliation: {error}"]
    if actual_hash != expected_hash:
        return record_rows, ["Feature Delivery run_inputs.json hash does not match finalization metadata"]
    try:
        prepared = load_manifest(path, explicit=False)
    except ValueError as error:
        return record_rows, [f"Feature Delivery cannot read run_inputs.json for asset source reconciliation: {error}"]
    if prepared.get("status") != "explicit":
        return record_rows, ["Feature Delivery run_inputs.json must have status explicit for asset source reconciliation"]
    prepared_rows = {
        str(row.get("Input ID")): row
        for row in prepared["inputs"]
        if isinstance(row, dict) and str(row.get("Input ID", "")).strip()
    }
    missing = sorted(set(prepared_rows) - set(record_rows))
    extra = sorted(set(record_rows) - set(prepared_rows))
    errors = []
    if missing:
        errors.append("Feature Delivery work record dropped run inputs: " + ", ".join(missing))
    if extra:
        errors.append("Feature Delivery work record added undeclared run inputs: " + ", ".join(extra))
    return prepared_rows, errors


def feature_asset_record_errors(
    text: str, path: Path, identity: dict[str, str], finalization: dict[str, str],
) -> list[str]:
    playbook_name = Path(identity.get("Playbook / version", "").split(" / ", 1)[0]).stem
    if (
        playbook_name != "feature_delivery"
        or identity.get("Lifecycle") != "planning"
        or identity.get("State") not in {"ready_for_implementation", "awaiting_input", "completed"}
    ):
        return []
    root_value = finalization.get("Durable artifact root", "")
    root = Path(root_value).resolve() if root_value else path.parent.resolve()
    manifest_path = root / ASSET_MANIFEST_FILENAME
    if not manifest_path.is_file():
        return [f"{path}: Feature Delivery requires {ASSET_MANIFEST_FILENAME}"]
    try:
        manifest = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        return [f"{path}: invalid {ASSET_MANIFEST_FILENAME}: {error}"]
    input_rows, input_errors = _feature_record_expected_inputs(text, identity, root)
    evidence_ids = {
        row.get("Evidence ID", "")
        for row in markdown_table(text, "# Evidence")
        if row.get("Evidence ID", "").strip()
    }
    claim_evidence_ids = {
        reference
        for row in markdown_table(text, "# Claims")
        for reference in REFERENCE_ID.findall(row.get("Evidence refs", ""))
    }
    work_item = {
        row.get("Field", ""): row.get("Value", "")
        for row in markdown_table(text, "# Work Item")
    }
    errors = input_errors + validate_asset_manifest(
        manifest,
        work_item=work_item.get("Identifier") or work_item.get("ID") or None,
        expected_input_ids=input_rows,
        expected_inputs=input_rows,
        expected_evidence_ids=evidence_ids,
        material_claim_evidence_ids=claim_evidence_ids,
        require_jira_source=True,
        require_passed=identity.get("State") in {"ready_for_implementation", "completed"}
        and identity.get("Lifecycle") == "planning",
    )
    if "# Asset Inventory and Review" not in text or ASSET_MANIFEST_FILENAME not in text:
        errors.append("Feature Delivery work record requires the Asset Inventory and Review section")
    durable_targets = {
        target
        for row in markdown_table(text, "# Durable Artifacts")
        if (target := _artifact_path(row.get("Path", ""), path)) is not None
    }
    if manifest_path.resolve() not in durable_targets:
        errors.append("Feature Delivery work record must register asset_manifest.json")
    handoff = fenced_section(text, "# Final Handoff")
    handoff_targets = {
        target
        for line in handoff.splitlines()
        if line.startswith("- ")
        and (target := _artifact_path(line[2:], path)) is not None
    }
    if manifest_path.resolve() not in handoff_targets:
        errors.append("Feature Delivery Final Handoff must link asset_manifest.json")
    selection = markdown_table(text, "# Playbook Selection")
    assessment = bool(selection) and selection[0].get("Primary goal", "").strip().lower() == "specification assessment"
    if assessment:
        report = root / REPORT_NAME
        design = root / "feature_design.md"
        design_text = design.read_text() if design.is_file() else None
        if design_text is None:
            errors.append("Feature Delivery specification assessment requires reviewed feature_design.md")
        if not report.is_file():
            errors.append(f"Feature Delivery specification assessment requires {REPORT_NAME}")
        else:
            handoff_result = re.search(r"^Workflow result:\s*(.+)$", handoff, re.MULTILINE)
            expected_result = handoff_result.group(1).strip() if handoff_result else ""
            material_ids = tuple(
                str(asset.get("asset_id", "")) for asset in manifest.get("assets", [])
                if isinstance(asset, dict) and asset.get("relevance") == "material"
            )
            errors.extend(assessment_report_errors(
                report.read_text(), expected_result, material_ids, reviewed_coverage_text=design_text,
            ))
        if report.resolve() not in durable_targets:
            errors.append(f"Feature Delivery work record must register {REPORT_NAME}")
        if report.resolve() not in handoff_targets:
            errors.append(f"Feature Delivery Final Handoff must link {REPORT_NAME}")
        if (root / "implementation_plan.md").is_file():
            errors.append("Feature Delivery specification assessment must not create implementation_plan.md")
    elif identity.get("State") in {"ready_for_implementation", "completed"}:
        plan = root / "implementation_plan.md"
        if plan.is_file():
            errors.extend(asset_plan_errors(plan.read_text(), manifest))
            errors.extend(applicability_errors(plan.read_text()))
        else:
            errors.append(f"{path}: Feature Delivery planning requires implementation_plan.md")
    if not assessment and identity.get("State") == "awaiting_input":
        if (root / "implementation_plan.md").is_file():
            errors.append("Feature Delivery awaiting_input must not retain implementation_plan.md")
    return list(dict.fromkeys(f"{path}: {error}" for error in errors))


def frontmatter_value_at_revision(revision: str, path: Path, field: str) -> str | None:
    try:
        relative = path.relative_to(ROOT)
    except ValueError:
        return frontmatter_value(path, field)
    completed = subprocess.run(
        ["git", "-C", str(ROOT), "show", f"{revision}:{relative}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode:
        return frontmatter_value(path, field)
    prefix = f"{field}:"
    for line in completed.stdout.splitlines():
        if line.startswith(prefix):
            return line.split(":", 1)[1].strip()
    return None


def _validate_work_record(path: Path, require_terminal: bool = False, *, allow_unreleased: bool = False) -> str:
    if not path.is_file():
        fail(f"work record does not exist: {path}")
        return ""
    if path.stat().st_size > LARGE_WORK_RECORD_BYTES:
        print(
            f"WARNING: {path} is unusually large; remove duplicated evidence when safe",
            file=sys.stderr,
        )
    text = path.read_text()
    try:
        from finalize_work_record import expand_work_record
    except ModuleNotFoundError:
        from scripts.finalize_work_record import expand_work_record
    try:
        text = expand_work_record(text, path.parent)
    except (OSError, ValueError, KeyError, TypeError) as error:
        fail(f"{path}: invalid workflow-state snapshot: {error}")
        return ""
    identity = {
        row.get("Field", ""): row.get("Value", "")
        for row in (markdown_table(text, "# Run and Evaluation Identity") or markdown_table(text, "# Run Summary"))
    }
    if identity.get("State") not in TERMINAL_STATES:
        if require_terminal:
            fail(f"{path}: work record is not terminal or lacks Run and Evaluation Identity")
        return ""
    for error in reasoning_record_errors(text):
        fail(f"{path}: {error}")
    selection = markdown_table(text, "# Playbook Selection")
    required_selection = {
        "Primary evidence",
        "Primary goal",
        "Selected playbook",
        "Closest alternative",
        "Why this playbook",
    }
    if (
        not selection
        or not required_selection.issubset(selection[0])
        or any(not selection[0].get(field) for field in required_selection)
    ):
        fail(f"{path}: Playbook Selection must record the selected playbook, closest alternative, and rationale")
    empty_selection = {"none", "none selected", "unknown", "not applicable", "n/a"}
    for field in required_selection:
        if selection and selection[0].get(field, "").strip().lower() in empty_selection:
            fail(f"{path}: Playbook Selection {field} must contain run-specific evidence")
    required_identity = (
        "Run ID",
        "Playbook / version",
        "Framework commit / status",
        "Plugin package / version",
        "Provider/runtime configuration",
        "Provider configuration source/status",
        "Prompt template / revision / conformance",
        "Role-policy baseline ID",
        "Role binding manifest",
        "Provider / model configuration",
        "Coordinator model/effort",
        "Requested profile",
        "Activated profile",
        "Executed profile",
        "Profile status",
        "Lifecycle",
        "State",
        "Engineering state",
        "Workflow outcome",
        "Engineering outcome",
    )
    missing = [field for field in required_identity if not identity.get(field)]
    if missing:
        fail(f"{path}: missing evaluation identity: {', '.join(missing)}")
    for field in required_identity:
        identity.setdefault(field, "")
    unresolved = [
        field
        for field in required_identity
        if "`" in identity[field] or ("<" in identity[field] and ">" in identity[field])
    ]
    if unresolved:
        fail(f"{path}: unresolved Run Identity placeholders: {', '.join(unresolved)}")
    for error in terminal_semantics_errors(identity):
        fail(f"{path}: {error}")
    evaluation_run_id = identity.get("Evaluation run ID", "Not applicable")
    evaluation_run = evaluation_run_id != "Not applicable"
    if evaluation_run and evaluation_run_id in {"Unknown", "None"}:
        fail(f"{path}: Evaluation run ID must identify the evaluated run")
    if evaluation_run and identity["Role-policy baseline ID"] in {"Unknown", "None", "Not applicable"}:
        fail(f"{path}: Role-policy baseline ID must identify the evaluated baseline")
    baseline_id = identity["Role-policy baseline ID"]
    if baseline_id != "Not applicable" and ("/" in baseline_id or baseline_id.endswith(".md")):
        fail(f"{path}: Role-policy baseline ID must be an identifier, not a path")
    prompt_by_playbook = {
        "feature_delivery": "templates/feature_delivery_run_prompt.md",
        "techops_issue_remediation": "templates/techops_issue_run_prompt.md",
        "sentry_issue_remediation": "templates/sentry_issue_run_prompt.md",
        "technical_spike": "templates/technical_spike_run_prompt.md",
        "vulnerability_investigation": "templates/vulnerability_issue_run_prompt.md",
    }
    playbook_name = Path(identity["Playbook / version"].split(" / ", 1)[0]).stem
    provider_model = identity["Provider / model configuration"].strip()
    codex_run = (
        provider_model.lower().startswith("codex")
        or baseline_id != "Not applicable"
        or identity["Role binding manifest"] != "Not applicable"
    )
    if " / " not in provider_model:
        fail(f"{path}: Provider / model configuration must identify the provider and its ledger")
    coordinator_model = identity["Coordinator model/effort"].strip()
    coordinator_unavailable = (
        coordinator_model.lower() == "not exposed / not exposed"
        and "active parent session" in identity.get("Coordinator execution", "").lower()
    )
    if codex_run and not coordinator_unavailable and not re.fullmatch(
        r"\S+ / (?:none|minimal|low|medium|high|xhigh|max|ultra)", coordinator_model, re.IGNORECASE
    ):
        fail(
            f"{path}: Coordinator model/effort received {coordinator_model!r}; expected "
            "'<active model> / <active effort>'"
        )
    framework_identity = identity["Framework commit / status"]
    valid_framework_identity = re.fullmatch(r"[0-9a-fA-F]{40} / (?:Clean|Dirty)", framework_identity)
    if not valid_framework_identity:
        fail(
            f"{path}: Framework commit / status received {framework_identity!r}; "
            "expected '<40-character Git SHA> / <Clean|Dirty>'"
        )
    plugin_identity = identity["Plugin package / version"]
    if plugin_identity != "Not applicable" and not re.fullmatch(r"[^\s/]+ / \S+", plugin_identity):
        fail(f"{path}: Plugin package / version must contain an exact package and version")
    manifest: dict[str, object] | None = None
    if codex_run:
        if baseline_id != MODEL_BASELINE_ID:
            fail(f"{path}: Codex runs must use current Role-policy baseline ID {MODEL_BASELINE_ID}")
        manifest_value = identity["Role binding manifest"]
        manifest_path = Path(manifest_value)
        if not manifest_path.is_absolute():
            manifest_path = path.parent / manifest_path.name
        if not manifest_path.is_file():
            fail(f"{path}: role binding manifest does not exist: {manifest_path}")
        try:
            manifest = json.loads(manifest_path.read_text())
        except (json.JSONDecodeError, OSError) as error:
            fail(f"{path}: invalid role binding manifest: {error}")
            manifest = {}
        if manifest.get("baseline_id") != baseline_id:
            fail(f"{path}: role binding manifest baseline does not match Run Identity")
        if manifest.get("playbook") != playbook_name:
            fail(f"{path}: role binding manifest playbook does not match Run Identity")
        for agent, binding in manifest.get("bindings", {}).items():
            definition = Path(binding.get("definition", ""))
            if not definition.is_file():
                fail(f"{path}: role binding definition does not exist for {agent}: {definition}")
                continue
            try:
                definition_data = tomllib.loads(definition.read_text())
            except (OSError, tomllib.TOMLDecodeError) as error:
                fail(f"{path}: invalid role binding definition for {agent}: {error}")
                continue
            if (
                binding.get("model") != definition_data.get("model")
                or binding.get("effort") != definition_data.get("model_reasoning_effort")
            ):
                fail(f"{path}: role binding manifest differs from provider definition for {agent}")
    expected_prompt = prompt_by_playbook.get(playbook_name)
    if expected_prompt:
        prompt_identity = identity["Prompt template / revision / conformance"].split(" / ", 2)
        framework_revision, framework_status = (
            framework_identity.split(" / ", 1) if valid_framework_identity else ("", "Dirty")
        )
        expected_version = (
            frontmatter_value_at_revision(framework_revision, ROOT / expected_prompt, "version")
            if framework_status == "Clean"
            else frontmatter_value(ROOT / expected_prompt, "version")
        )
        if len(prompt_identity) != 3 or prompt_identity[0] != expected_prompt:
            fail(f"{path}: Prompt template must match {expected_prompt} for {playbook_name}")
        elif prompt_identity[1] != expected_version:
            fail(f"{path}: Prompt template revision must be {expected_version} for {playbook_name}")
        elif not re.fullmatch(r"(?:pass|fail(?:[:;].+)?)", prompt_identity[2], re.IGNORECASE):
            fail(f"{path}: Prompt template conformance must be pass or fail with details")
    finalization = {
        row.get("Field", ""): row.get("Value", "")
        for row in markdown_table(text, "# Run Isolation and Finalization")
    }
    if (
        codex_run and playbook_name == "feature_delivery" and selection
        and selection[0].get("Primary goal", "").strip().lower() == "specification assessment"
        and finalization.get("Active related run or work item", "").strip().lower().startswith("none")
    ):
        related_check = finalization.get("Related-run check", "")
        timestamped = any(
            RFC3339_TIMESTAMP.fullmatch(part.strip("()[];,")) for part in related_check.split()
        )
        if not timestamped or not all(term in related_check.lower() for term in ("provider", "sibling")):
            fail(
                f"{path}: Active related run None requires a timestamped provider-task and sibling-root check; "
                "otherwise record Unknown; detection unavailable"
            )
    for error in feature_asset_record_errors(text, path, identity, finalization):
        fail(error)
    review_root = Path(finalization.get("Durable artifact root") or path.parent).resolve()
    registered_review_paths = {
        target for row in markdown_table(text, "# Durable Artifacts")
        if (target := _artifact_path(row.get("Path", ""), path)) is not None
    }
    linked_review_paths = {
        target for line in fenced_section(text, "# Final Handoff").splitlines()
        if line.startswith("- ") and (target := _artifact_path(line[2:], path)) is not None
    }
    for error in completed_review_errors(identity, review_root, registered_paths=registered_review_paths,
                                         handoff_paths=linked_review_paths):
        fail(f"{path}: {error}")
    repositories = markdown_table(text, "# Repository Evidence Eligibility")
    if not repositories or any(not row.get("Full revision") for row in repositories):
        fail(f"{path}: every relevant repository must record its full revision")
    work_item = {
        row.get("Field", ""): row.get("Value", "")
        for row in markdown_table(text, "# Work Item")
    }
    if playbook_name == "feature_delivery" and identity["State"] in {
        "ready_for_implementation", "awaiting_input", "completed",
    }:
        title = work_item.get("Title", "").strip()
        if not title or title.lower().startswith("unknown"):
            fail(f"{path}: Feature Delivery requires the recovered work-item title")
    if not RFC3339_TIMESTAMP.fullmatch(work_item.get("Last Updated", "")):
        fail(f"{path}: Work Item Last Updated must be an RFC 3339 timestamp")
    required_tables = {
        "# Worker Execution Ledger": (
            "Worker",
            "Role",
            "Configured model/effort",
        ),
        "# Worker Runtime Closure": (
            "Run or stage",
            "Receipt owner",
            "Completed worker handles",
            "Runtime status",
        ),
        "# Worker Result Summary": (
            "Worker",
            "Outcome",
            "Confidence",
            "Unique contribution",
        ),
    }
    table_rows = {}
    for heading, fields in required_tables.items():
        rows = markdown_table(text, heading)
        table_rows[heading] = rows
        if not rows or any(not row.get(field) for row in rows for field in fields):
            fail(f"{path}: {heading} must contain populated terminal rows")
    for row in table_rows["# Worker Runtime Closure"]:
        receipt_owner = row.get("Receipt owner", "").strip()
        if receipt_owner != "Coordinator":
            fail(
                f"{path}: runtime closure Receipt owner received {receipt_owner!r}; expected 'Coordinator'"
            )
        handles = [
            value.strip().lower()
            for value in re.split(r",|;|<br\s*/?>", row.get("Completed worker handles", ""))
        ]
        terminal_runtime = row.get("Runtime status", "").strip().lower() == "terminal"
        if codex_run and not terminal_runtime and any(
            handle not in {"none", "unknown", "unavailable"}
            and not re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", handle)
            for handle in handles
        ):
            fail(
                f"{path}: Completed worker handles received {row.get('Completed worker handles', '')!r}; "
                "expected provider UUIDs or Unknown/Unavailable, never task paths or labels"
            )
        if terminal_runtime:
            evidence = row.get("Closure evidence or blocker", "").strip().lower()
            if not codex_run or not NO_ACTIVE_HANDLES.fullmatch(row.get("Remaining active handles", "").strip()):
                fail(f"{path}: Terminal closure requires Codex provider status and zero active turns")
            snapshot = re.search(r"provider status snapshot (\S+):", evidence)
            if not snapshot or not RFC3339_TIMESTAMP.fullmatch(snapshot.group(1).upper()):
                fail(f"{path}: Terminal closure requires a timestamped provider status snapshot")
            if re.search(r"=(?:running|pending_init|pending|in_progress|not_found)(?=[;,.\s]|$)", evidence):
                fail(f"{path}: Terminal closure snapshot contains non-terminal workers")
            for handle in handles:
                identifier = re.fullmatch(
                    r"(?:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|/root/[a-z0-9_]+(?:/[a-z0-9_]+)*)",
                    handle,
                )
                status = re.search(re.escape(handle) + r"=(?:completed|idle)(?=[;,.\s]|$)", evidence)
                if not identifier or not status:
                    fail(f"{path}: Terminal closure lacks exact provider terminal status for {handle!r}")
            try:
                from validate_worker_runtime import terminal_observation_errors
            except ModuleNotFoundError:
                from scripts.validate_worker_runtime import terminal_observation_errors
            observations = markdown_table(text, "# Worker Terminal Observations")
            for error in terminal_observation_errors(
                [item for item in observations if item.get("Provider handle", "").lower() in handles], handles,
            ):
                fail(f"{path}: {error}")
        if row.get("Runtime status", "").strip().lower() == "released":
            if not NO_ACTIVE_HANDLES.fullmatch(row.get("Remaining active handles", "").strip()):
                fail(f"{path}: released runtime closure must have no active handles")
            closure_evidence = row.get("Closure evidence or blocker", "").strip().lower()
            if "provider" not in closure_evidence or not any(word in closure_evidence for word in ("release", "close")):
                fail(f"{path}: released runtime closure requires provider release evidence")
            if codex_run and any(
                handle != "none"
                and not re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", handle)
                for handle in handles
            ):
                fail(
                    f"{path}: Completed worker handles received {row.get('Completed worker handles', '')!r}; "
                    "expected bare provider UUIDs separated by commas or semicolons"
                )
            missing_handles = [handle for handle in handles if handle and handle not in closure_evidence]
            if missing_handles:
                fail(
                    f"{path}: Closure evidence or blocker must identify completed handles: "
                    f"{', '.join(missing_handles)}"
                )
    runtime_released = bool(table_rows["# Worker Runtime Closure"]) and all(
        row.get("Runtime status", "").strip().lower() == "released"
        and NO_ACTIVE_HANDLES.fullmatch(row.get("Remaining active handles", "").strip())
        for row in table_rows["# Worker Runtime Closure"]
    )
    runtime_terminal = bool(table_rows["# Worker Runtime Closure"]) and all(
        row.get("Runtime status", "").strip().lower() in {"released", "terminal"}
        and NO_ACTIVE_HANDLES.fullmatch(row.get("Remaining active handles", "").strip())
        for row in table_rows["# Worker Runtime Closure"]
    )
    if codex_run and runtime_terminal and (playbook_name == "feature_delivery" or not runtime_released):
        completed_workers = {
            row.get("Worker", "").strip().lower()
            for row in table_rows["# Worker Result Summary"]
            if row.get("Outcome", "").strip().lower() == "complete"
        }
        released_handles = {
            handle.strip().lower()
            for row in table_rows["# Worker Runtime Closure"]
            for handle in re.split(r",|;|<br\s*/?>", row.get("Completed worker handles", ""))
            if handle.strip().lower() not in {"", "none", "unknown", "unavailable"}
        }
        if len(released_handles) < len(completed_workers):
            fail(
                f"{path}: runtime closure has {len(released_handles)} provider handles "
                f"for {len(completed_workers)} completed workers; use worker_runtime_release_unavailable "
                "instead of Released when provider release cannot be confirmed"
            )
    if runtime_terminal:
        reconciliation = finalization.get("Final reconciliation", "").strip().lower()
        stale = any(token in reconciliation for token in ("pending", "unknown", "in progress"))
        stale = stale or ("active" in reconciliation and "no active" not in reconciliation)
        if stale:
            fail(f"{path}: released runtime closure cannot retain pending final reconciliation")
        if finalization.get("Finalization schema", "").strip().lower() != "passed":
            fail(f"{path}: released runtime closure requires Finalization schema Passed")
        for row in markdown_table(text, "# Worker Synchronization"):
            barrier = row.get("Barrier status", "").strip().lower()
            stale = any(token in barrier for token in ("pending", "unknown", "in progress"))
            stale = stale or ("active" in barrier and "no active" not in barrier)
            if stale:
                fail(f"{path}: released runtime closure cannot retain pending synchronization barrier")
        for row in markdown_table(text, "# Durable Artifacts"):
            artifact_name = re.sub(r"[_-]+", " ", row.get("Artifact", "").strip().lower())
            if "runtime closure" in artifact_name and row.get("Status", "").strip().lower() != (
                "released" if runtime_released else "terminal"
            ):
                fail(f"{path}: released runtime closure requires the runtime-closure artifact status Released")
        for row in table_rows["# Worker Result Summary"]:
            blockers = row.get("Uncertainties / blockers", "").strip().lower()
            if re.search(r"runtime closure pending", blockers):
                fail(f"{path}: released runtime closure cannot retain pending worker-result closure text")
    if not allow_unreleased and "Finalization schema" in identity:
        fail(f"{path}: Finalization schema belongs only in Run Isolation and Finalization")
    if not allow_unreleased and identity["State"] == "blocked":
        if finalization.get("Finalization schema", "").strip().lower() not in {
            "passed", "passed for blocked work record",
        }:
            fail(f"{path}: published blocked record requires passed finalization schema")
        for row in markdown_table(text, "# Durable Artifacts"):
            name = Path(row.get("Path", "")).name
            if name in {"work_record.md", "runtime_closure.json"} and re.search(
                r"pending|expected|prepared skeleton", row.get("Status", ""), re.IGNORECASE,
            ):
                fail(f"{path}: published blocked record retains stale artifact status for {name}")
    if playbook_name == "techops_issue_remediation" and identity.get("Lifecycle") == "planning":
        try:
            from finalize_work_record import _techops_planning_contract_errors
        except ModuleNotFoundError:
            from scripts.finalize_work_record import _techops_planning_contract_errors
        for error in _techops_planning_contract_errors({
            "identity": identity, "worker_results": table_rows["# Worker Result Summary"],
            "evidence": markdown_table(text, "# Evidence"),
            "techops_checks": markdown_table(text, "# TechOps Planning Checks"),
            "runtime_audits": markdown_table(text, "# Worker Runtime Audits"),
            "terminal_observations": markdown_table(text, "# Worker Terminal Observations"),
        }, path):
            fail(f"{path}: {error}")
    if playbook_name == "technical_spike":
        for row in table_rows["# Worker Result Summary"]:
            match = RANGE_REFERENCE.search(row.get("Evidence / claim refs", ""))
            if match:
                fail(
                    f"{path}: Worker Result Summary for {row.get('Worker', 'unknown')} must use exact IDs; "
                    f"grouped/range reference {match.group(0)!r} is not allowed"
                )
    if identity["Workflow outcome"] == "completed" and not allow_unreleased:
        for row in table_rows["# Worker Runtime Closure"]:
            if row.get("Runtime status", "").strip().lower() not in {"released", "terminal"}:
                fail(f"{path}: completed workflow requires released or terminal runtime closure")
            if not NO_ACTIVE_HANDLES.fullmatch(row.get("Remaining active handles", "").strip()):
                fail(f"{path}: completed workflow requires zero active handles")
    worker_rows = table_rows["# Worker Execution Ledger"]
    result_rows = table_rows["# Worker Result Summary"]
    if playbook_name == "sentry_issue_remediation" and codex_run:
        ledger_by_worker = {row.get("Worker", "").strip().lower(): row for row in worker_rows}
        for row in result_rows:
            outcome = row.get("Outcome", "").strip().lower()
            if outcome not in WORKER_OUTCOMES:
                fail(f"{path}: invalid worker result outcome: {outcome}")
            worker_key = row.get("Worker", "").strip().lower()
            ledger_row = ledger_by_worker.get(worker_key)
            if ledger_row and outcome != ledger_row.get("Outcome", "").strip().lower():
                fail(f"{path}: Worker Result Summary outcome must match the execution ledger for {row.get('Worker', '')}")
            if worker_key not in {"coordinator", "orchestrator"}:
                actual = row.get("Actual model/effort", "").strip().lower()
                if actual in UNOBSERVED_MODEL_VALUES:
                    fail(
                        f"{path}: Codex worker result must record provider-observed model/effort or an explicit "
                        f"unavailable marker for {row.get('Worker', '')}"
                    )
                if ledger_row and actual != ledger_row.get("Provider-observed model/effort", "").strip().lower():
                    fail(f"{path}: Worker Result Summary model/effort must match the execution ledger for {row.get('Worker', '')}")
    for row in worker_rows:
        outcome = row.get("Outcome", "").strip().lower()
        if "Outcome" in row and outcome not in WORKER_OUTCOMES:
            fail(f"{path}: invalid worker outcome: {outcome}")
        if codex_run and row.get("Worker", "").strip().lower() not in {"coordinator", "orchestrator"}:
            role = row.get("Role", "").strip()
            agent = SENTRY_ROLE_AGENTS.get(role) if playbook_name == "sentry_issue_remediation" else None
            bindings = manifest.get("bindings", {}) if manifest else {}
            if not agent and role in bindings:
                agent = role
            if not agent:
                aliases = ROLE_AGENT_ALIASES.get(role, ())
                agent = aliases[0] if aliases else None
            binding = bindings.get(agent) if agent else None
            if not binding:
                fail(f"{path}: activated worker role has no resolved binding: {role or row.get('Worker', '')}")
                continue
            configured = row.get("Configured model/effort", "").strip().lower()
            expected = f"{binding['model']} / {binding['effort']}".lower()
            if configured != expected:
                fail(
                    f"{path}: {row.get('Worker', role)} configured model/effort received {configured!r}; "
                    f"expected {expected!r}"
                )
            observed = row.get("Provider-observed model/effort", "").strip().lower()
            if observed in UNOBSERVED_MODEL_VALUES:
                fail(
                    f"{path}: Codex worker ledger must record provider-observed model/effort or an explicit "
                    f"unavailable marker for {row.get('Worker', role)}"
                )
            elif not model_observation_unavailable(observed) and observed != configured:
                fail(f"{path}: {row.get('Worker', role)} provider-observed model/effort must match configured model/effort")
    fix_worker_rows = [
        row for row in worker_rows
        if SENTRY_ROLE_AGENTS.get(row.get("Role", "").strip()) == "sentry_solution_architect"
    ]
    handoff_text = fenced_section(text, "# Final Handoff")
    analytical_contract_failure = (
        identity["State"] == "blocked"
        and "analytical contract failure" in handoff_text.lower()
    )
    if playbook_name == "sentry_issue_remediation" and fix_worker_rows and analytical_contract_failure:
        if not any(row.get("Outcome", "").strip().lower() == "failed" for row in fix_worker_rows):
            fail(f"{path}: failed Fix Design contract must record worker outcome failed")
    elif playbook_name == "sentry_issue_remediation" and fix_worker_rows:
        if any(row.get("Outcome", "").strip().lower() != "complete" for row in fix_worker_rows):
            fail(f"{path}: Sentry Fix Design worker outcome must be complete; use plan_readiness for awaiting_input")
        fix_result_path = path.parent / "fix_design_result.json"
        if not fix_result_path.is_file():
            fail(f"{path}: completed Sentry Fix Design requires fix_design_result.json")
        else:
            fix_result: object = {}
            try:
                fix_result = json.loads(fix_result_path.read_text())
            except (json.JSONDecodeError, OSError) as error:
                fail(f"{path}: invalid fix_design_result.json: {error}")
                fix_result = {}
            require_plan = bool(
                manifest
                and "standard_planning_finalization" in manifest.get("worker_contracts", {})
            )
            for error in fix_design_result_errors(
                fix_result,
                required_input_markers=SENTRY_EVIDENCE_INPUT_MARKERS,
                require_plan=require_plan,
            ):
                fail(f"{path}: {error}")
            evidence_path = path.parent / "normalized_evidence.md"
            if isinstance(fix_result, dict) and evidence_path.is_file():
                for error in sentry_upstream_boundary_errors(
                    evidence_path.read_text(), fix_result, require_plan=require_plan
                ):
                    fail(f"{path}: {error}")
            if not isinstance(fix_result, dict):
                fix_result = {}
            if _contains_hypothesis(fix_result):
                if not re.search(r"^Best current explanations:\s*$", handoff_text, re.MULTILINE):
                    fail(f"{path}: Final Handoff must include Best current explanations when Fix Design returns a hypothesis")
            readiness = fix_result.get("plan_readiness")
            expected_identity = {
                "ready_for_implementation": {
                    "State": "ready_for_implementation",
                    "Workflow outcome": "completed",
                    "Engineering outcome": "plan_only",
                },
                "awaiting_input": {
                    "State": "awaiting_input",
                    "Workflow outcome": "completed",
                    "Engineering outcome": "partially_solved",
                },
            }.get(readiness, {})
            for field, expected in expected_identity.items():
                if identity.get(field) != expected:
                    fail(f"{path}: Fix Design {readiness} requires {field} {expected}")
            plan = path.parent / "implementation_plan.md"
            clarification = path.parent / "clarification_brief.md"
            if readiness == "ready_for_implementation":
                if not plan.is_file():
                    fail(f"{path}: ready Fix Design requires implementation_plan.md")
                elif fix_result.get("interface_change"):
                    contract_rows = markdown_table(plan.read_text(), "# Interface Contract")
                    interface_contract = fix_result.get("interface_contract", {})
                    plan_fields = {
                        "Surface": "surface",
                        "Request shape": "request_shape",
                        "Response shape": "response_shape",
                        "Absence semantics": "absence_semantics",
                        "Compatibility / precedence": "compatibility_precedence",
                        "Rollout": "rollout",
                    }
                    if len(contract_rows) != 1 or any(not contract_rows[0].get(field) for field in plan_fields):
                        fail(
                            f"{path}: # Interface Contract received {len(contract_rows)} parseable rows; expected one "
                            "populated row with Surface, Request shape, Response shape, Absence semantics, "
                            "Compatibility / precedence, and Rollout; escape field-internal pipes as \\|"
                        )
                    elif isinstance(interface_contract, dict) and all(key in interface_contract for key in plan_fields.values()) and any(
                        contract_rows[0][field] != interface_contract[key] for field, key in plan_fields.items()
                    ):
                        fail(f"{path}: implementation plan Interface Contract must match fix_design_result.json")
                if clarification.exists():
                    fail(f"{path}: ready Fix Design cannot retain clarification_brief.md")
            elif readiness == "awaiting_input":
                if not clarification.is_file():
                    fail(f"{path}: awaiting Fix Design requires clarification_brief.md")
                if plan.exists():
                    fail(f"{path}: awaiting Fix Design cannot retain implementation_plan.md")
            completed_handles = " ".join(
                row.get("Completed worker handles", "") for row in table_rows["# Worker Runtime Closure"]
            )
            worker_handle = fix_result.get("worker_handle")
            if isinstance(worker_handle, str) and worker_handle.strip() and worker_handle not in completed_handles:
                fail(f"{path}: Fix Design worker_handle is absent from runtime closure")
        evidence_path = path.parent / "normalized_evidence.md"
        if not evidence_path.is_file():
            fail(f"{path}: completed Sentry Fix Design requires normalized_evidence.md")
        else:
            evidence_text = evidence_path.read_text()
            for marker in PROHIBITED_CONTEXT_MARKERS:
                if marker in evidence_text:
                    fail(f"{path}: normalized evidence contains prohibited context marker: {marker}")
            for error in sentry_contract_delta_errors(evidence_text):
                fail(f"{path}: {error}")
    for row in markdown_table(text, "# Input Register"):
        if "worker" in row.get("Input or artifact", "").lower() and _mentions_user_source(row.get("Source or path", "")):
            fail(f"{path}: worker-produced inputs must cite the provider worker/result handle, not the user")
    for row in markdown_table(text, "# Evidence"):
        if "preflight" in " ".join(row.values()).lower() and _mentions_user_source(row.get("Source", "")):
            fail(f"{path}: preflight evidence must cite the Coordinator/provider observation, not the user")
    if evaluation_run:
        evaluation_tables = {
            "# Evaluation Run Continuation Ledger": ("Sequence", "Type", "New input IDs", "Recorded at"),
            "# Evaluation Worker Activation Ledger": (
                "Sequence",
                "Worker",
                "Provider handle",
                "Action",
                "Input IDs",
                "Observed at",
                "Outcome or error",
            ),
        }
        for heading, fields in evaluation_tables.items():
            rows = markdown_table(text, heading)
            if not rows or any(not row.get(field) for row in rows for field in fields):
                fail(f"{path}: {heading} must contain populated evaluation rows")
        for heading, timestamp_field in (
            ("# Evaluation Run Continuation Ledger", "Recorded at"),
            ("# Evaluation Worker Activation Ledger", "Observed at"),
        ):
            for row in markdown_table(text, heading):
                if not RFC3339_TIMESTAMP.fullmatch(row[timestamp_field]):
                    fail(f"{path}: {heading} {timestamp_field} must be RFC 3339")
        timing_rows = markdown_table(text, "## Evaluation Worker Timing Ledger")
        timing_fields = ("Worker", "Provider handle", "Activated", "Started", "Terminal", "Elapsed")
        if not timing_rows or any(not row.get(field) for row in timing_rows for field in timing_fields):
            fail(f"{path}: Evaluation Worker Timing Ledger must contain populated timing rows")
        for row in timing_rows:
            for field in ("Activated", "Started", "Terminal"):
                if not RFC3339_TIMESTAMP.fullmatch(row[field]):
                    fail(f"{path}: Evaluation Worker Timing Ledger {field} must be RFC 3339")
            if row["Elapsed"].lower() in {"terminal", "released", "unknown", "unavailable"}:
                fail(f"{path}: Evaluation Worker Timing Ledger Elapsed must be a duration, not a state")

    handoff = fenced_section(text, "# Final Handoff")
    required_handoff = (
        "Workflow result:",
        "- State:",
        "- Engineering state:",
        "- Workflow outcome:",
        "- Engineering outcome:",
        "- Implementation plan:",
        "What we established:",
        "Next action:",
        "- Owner:",
        "- Action:",
        "- Complete when:",
        "Artifacts:",
        "Execution:",
        "Provenance:",
    )
    positions = [handoff.find(label) for label in required_handoff]
    if not handoff or any(position < 0 for position in positions) or positions != sorted(positions):
        fail(f"{path}: Final Handoff must contain the canonical ordered labels")
    if re.search(r"^Workflow result:\s*Workflow result:", handoff, re.MULTILINE | re.IGNORECASE):
        fail(f"{path}: Final Handoff must contain exactly one Workflow result prefix")
    for label in (
        "Workflow result:",
        "- Engineering state:",
        "- Implementation plan:",
        "- Owner:",
        "- Action:",
        "- Complete when:",
        "Execution:",
        "Provenance:",
    ):
        value = re.search(rf"^{re.escape(label)}[ \t]*(.+)$", handoff, re.MULTILINE)
        if not value or not value.group(1).strip():
            fail(f"{path}: Final Handoff {label.rstrip(':')} must be populated")
    for label, field in (
        ("- State:", "State"),
        ("- Engineering state:", "Engineering state"),
        ("- Workflow outcome:", "Workflow outcome"),
        ("- Engineering outcome:", "Engineering outcome"),
    ):
        value = re.search(rf"^{re.escape(label)}\s*(.+)$", handoff, re.MULTILINE)
        if not value or value.group(1).strip() != identity[field]:
            fail(f"{path}: Final Handoff {field} must match Run Identity")
    selection_rows = markdown_table(text, "# Playbook Selection")
    primary_goal = selection_rows[0].get("Primary goal", "") if selection_rows else ""
    workflow_result = re.search(r"^Workflow result:\s*(.+)$", handoff, re.MULTILINE)
    disposition_error = feature_assessment_disposition_error(
        playbook_name,
        identity["Lifecycle"],
        identity["State"],
        primary_goal,
        workflow_result.group(1) if workflow_result else "",
    )
    if disposition_error:
        fail(f"{path}: {disposition_error}")
    if playbook_name == "feature_delivery" and identity["Lifecycle"] == "planning" and (
        primary_goal.strip().lower() == "specification assessment"
    ) and identity["State"] in {"ready_for_implementation", "awaiting_input"}:
        expected_outcome = "solved" if identity["State"] == "ready_for_implementation" else "partially_solved"
        if identity["Engineering outcome"] != expected_outcome:
            fail(f"{path}: Feature Delivery specification assessment requires Engineering outcome {expected_outcome}")
        plan_line = re.search(r"^- Implementation plan:\s*(.+)$", handoff, re.MULTILINE)
        if not plan_line or plan_line.group(1).strip() != NO_PLAN_MESSAGE:
            fail(f"{path}: Feature Delivery specification assessment Implementation plan must be {NO_PLAN_MESSAGE}")
    spike_disposition_error = technical_spike_disposition_error(
        playbook_name,
        identity["Lifecycle"],
        identity["State"],
        primary_goal,
        workflow_result.group(1) if workflow_result else "",
        identity["Workflow outcome"],
        identity["Engineering outcome"],
    )
    if spike_disposition_error:
        fail(f"{path}: {spike_disposition_error}")
    runtime_value = "released" if all(
        row.get("Runtime status", "").strip().lower() == "released"
        for row in table_rows["# Worker Runtime Closure"]
    ) else "terminal" if runtime_terminal else "not released"
    execution = re.search(r"^Execution:\s*(.*?)\nProvenance:", handoff, re.MULTILINE | re.DOTALL)
    execution_text = " ".join(execution.group(1).lower().split()) if execution else ""
    if not allow_unreleased and re.search(
        r"(?:awaiting|pending)\s+(?:coordinator\s+)?packet validation|"
        r"(?:awaiting|pending)\s+(?:packaged\s+)?finalization", execution_text,
    ):
        fail(f"{path}: published handoff Execution contains obsolete publication steps")
    if not execution or f"runtime {runtime_value}" not in execution_text:
        fail(f"{path}: Final Handoff runtime must match Worker Runtime Closure")
    if identity["State"].strip().lower() == "completed" and not allow_unreleased and re.search(
        r"\b(?:state(?:\s*:\s*|\s+)(?:remains\s+)?handoff|"
        r"workflow remains\s+(?:in_progress|handoff)|"
        r"workflow\s+outcome\s*:\s*(?:incomplete|in_progress|handoff|pending|blocked|unknown)|"
        r"pre-release and terminal release not run|"
        rf"{STALE_FINALIZER_REFERENCE}|"
        r"runtime closure\s+(?:is\s+)?(?:pending|unknown|active|in progress|not released))\b",
        execution_text,
    ):
        fail(f"{path}: completed handoff Execution contains stale transitional state")
    for error in current_artifact_errors(
        markdown_table(text, "# Durable Artifacts"),
        path,
        finalization.get("Durable artifact root", ""),
    ):
        fail(error)
    handoff_artifacts: set[Path] = set()
    if handoff:
        in_artifacts = False
        artifact_count = 0
        for line in handoff.splitlines():
            if line == "Artifacts:":
                in_artifacts = True
                continue
            if in_artifacts and line.startswith("Execution:"):
                break
            if in_artifacts and line.startswith("- "):
                artifact_count += 1
                target = _artifact_path(line[2:], path)
                if target is None:
                    fail(f"{path}: Final Handoff contains an empty artifact path")
                elif not target.is_file() and not (
                    target.name == "work_record.md" and target.parent == path.parent
                ):
                    fail(f"{path}: Final Handoff artifact does not exist: {target}")
                else:
                    handoff_artifacts.add(target)
        if not artifact_count:
            fail(f"{path}: Final Handoff must link at least one artifact")
    if playbook_name == "feature_delivery":
        required_artifacts = [{
            "awaiting_input": "clarification_brief.md",
            "ready_for_implementation": (
                REPORT_NAME if primary_goal.strip().lower() == "specification assessment" else "implementation_plan.md"
            ),
        }.get(identity["State"])]
        if primary_goal.strip().lower() == "specification assessment" and identity["State"] == "awaiting_input":
            required_artifacts.append(REPORT_NAME)
        for required_artifact in filter(None, required_artifacts):
            target = (path.parent / required_artifact).resolve()
            durable_targets = {
                artifact
                for row in markdown_table(text, "# Durable Artifacts")
                if (artifact := _artifact_path(row.get("Path", ""), path)) is not None
            }
            if target not in durable_targets:
                fail(f"{path}: Feature Delivery {identity['State']} must register {required_artifact}")
            if target not in handoff_artifacts:
                fail(f"{path}: Feature Delivery {identity['State']} must link {required_artifact} in Final Handoff")
    if playbook_name == "technical_spike":
        implementation_plan = re.search(r"^- Implementation plan:\s*(.+)$", handoff, re.MULTILINE)
        expected = "Not created; Technical Spike produces spike_report.md"
        if not implementation_plan or implementation_plan.group(1).strip() != expected:
            fail(f"{path}: Technical Spike Implementation plan must be exactly {expected}")
        plan = (path.parent / "implementation_plan.md").resolve()
        if plan.is_file():
            fail(f"{path}: Technical Spike must not create implementation_plan.md")
        if identity["State"] == "completed":
            target = (path.parent / "spike_report.md").resolve()
            durable_targets = {
                artifact
                for row in markdown_table(text, "# Durable Artifacts")
                if (artifact := _artifact_path(row.get("Path", ""), path)) is not None
            }
            if target not in durable_targets:
                fail(f"{path}: Technical Spike completed must register spike_report.md")
            if target not in handoff_artifacts:
                fail(f"{path}: Technical Spike completed must link spike_report.md in Final Handoff")
            if target.is_file():
                budget_status = None
                budget_path = target.parent / "run_budget.json"
                if budget_path.is_file():
                    try:
                        budget_status = json.loads(budget_path.read_text()).get("status")
                    except (json.JSONDecodeError, OSError) as error:
                        fail(f"{path}: invalid run_budget.json: {error}")
                manifest_path = None
                manifest_value = identity.get("Run input manifest")
                if manifest_value and str(manifest_value).strip().lower() not in {"none", "not applicable"}:
                    manifest_path = Path(str(manifest_value))
                    if not manifest_path.is_absolute():
                        manifest_path = path.parent / manifest_path
                    manifest_path = manifest_path.resolve()
                for error in technical_spike_report_errors(
                    target.read_text(), primary_goal, identity["Executed profile"],
                    workflow_result.group(1) if workflow_result else "", budget_status,
                    manifest_path,
                ):
                    fail(f"{path}: {error}")
    if playbook_name == "sentry_issue_remediation" and codex_run:
        if not allow_unreleased and runtime_value == "released" and execution:
            if "validation passed" not in " ".join(execution.group(1).lower().split()):
                fail(f"{path}: released Sentry handoff must report validation passed")
    return handoff


def validate_work_record(path: Path, require_terminal: bool = False, *, allow_unreleased: bool = False) -> str:
    if common._WORK_RECORD_ERRORS is not None:
        raise RuntimeError("nested work-record validation")
    errors: list[str] = []
    common._WORK_RECORD_ERRORS = errors
    try:
        handoff = _validate_work_record(path, require_terminal, allow_unreleased=allow_unreleased)
    finally:
        common._WORK_RECORD_ERRORS = None
    if errors:
        fail("\nFAIL: ".join(errors))
    return handoff
