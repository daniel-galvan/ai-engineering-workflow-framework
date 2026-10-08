"""Deterministic playbooks validation rules."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import json
import re
from .common import (
    ASSET_MANIFEST_TEMPLATE,
    CODEX_AGENT_DIR,
    EXTERNAL_DOCUMENT_MARKER,
    EXTERNAL_DOCUMENT_URL,
    FEATURE_ASSESSMENT_DISPOSITIONS,
    FORBIDDEN_REPORT_CONTEXT_PATTERNS,
    JIRA_INTEGRATION,
    LIFECYCLES,
    MATURITY,
    REFERENCE_ID,
    ROOT,
    RUN_SKILL,
    TECHNICAL_SPIKE_DISPOSITIONS,
    TECHNICAL_SPIKE_SOURCE_LOCATOR,
    URL_REFERENCE,
    WORKFLOW_CONTRACT,
    fail,
)
from .contracts import (
    sentry_contract_delta_errors,
)
from .frontmatter import (
    frontmatter_value,
)
from .markdown import (
    markdown_table,
)
from .references import (
    _direct_evidence_location_is_vague,
    _direct_evidence_observation_is_vague,
    _grouped_reference_errors,
    _grouped_reference_text_errors,
    _is_not_applicable,
    normalized_metadata_value,
)
try:
    from run_input_manifest import load_manifest
except ModuleNotFoundError:
    from scripts.run_input_manifest import load_manifest


def _declared_spike_criteria(value: object) -> list[str]:
    text = normalized_metadata_value(value)
    if not text or text.lower().startswith("none declared") or _is_not_applicable(text):
        return []
    separator = r"\s*;\s*" if ";" in text else r"\s*,\s*"
    return [item.strip() for item in re.split(separator, text) if item.strip()]


def _normalized_spike_criterion(value: object) -> str:
    return re.sub(r"\s+", " ", normalized_metadata_value(value)).strip().casefold()


def _technical_spike_evidence_reference_errors(
    rows: list[dict[str, str]], section: str, fields: tuple[str, ...],
    evidence_ids: set[str], *, allow_check_ids: bool = False,
) -> list[str]:
    errors = []
    for index, row in enumerate(rows, start=1):
        identity = row.get("Evidence ID", "") or row.get("Option", "") or f"row {index}"
        for field in fields:
            for reference in REFERENCE_ID.findall(row.get(field, "")):
                if reference.upper().startswith("CHK-") and not allow_check_ids:
                    errors.append(
                        f"spike_report.md {section} {identity} {field} must reference Evidence IDs; "
                        f"{reference!r} is an experiment/check ID"
                    )
                elif reference.upper().startswith("E-") and reference not in evidence_ids:
                    errors.append(
                        f"spike_report.md {section} {identity} {field} references undeclared Evidence ID "
                        f"{reference!r}"
                    )
    return errors


def _technical_spike_evidence_text_errors(
    text: str, section: str, evidence_ids: set[str], *, require_evidence: bool = False,
) -> list[str]:
    match = re.search(
        rf"^{re.escape(section)}\s*\n(.*?)(?=^##\s|\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    if not match:
        return []
    errors = []
    references = tuple(dict.fromkeys(REFERENCE_ID.findall(match.group(1))))
    for reference in references:
        if reference.upper().startswith("CHK-"):
            errors.append(
                f"spike_report.md {section} must not use experiment/check ID {reference!r}; "
                "map it to a source-backed Evidence ID"
            )
        elif reference.upper().startswith("E-") and reference not in evidence_ids:
            errors.append(
                f"spike_report.md {section} references undeclared Evidence ID {reference!r}"
            )
    if require_evidence and not any(reference.upper().startswith("E-") for reference in references):
        errors.append(f"spike_report.md {section} must cite at least one exact Evidence ID")
    return errors


def _technical_spike_check_evidence_errors(
    rows: list[dict[str, str]], evidence_ids: set[str],
) -> list[str]:
    errors = []
    for index, row in enumerate(rows, start=1):
        references = tuple(dict.fromkeys(
            reference
            for field in (
                "Hypothesis or review criterion", "Observable seam", "Command or method",
                "Expected discriminating outcomes", "Actual result", "Disposition impact",
            )
            for reference in REFERENCE_ID.findall(row.get(field, ""))
        ))
        if not any(reference.upper().startswith("E-") for reference in references):
            identity = row.get("Hypothesis or review criterion", "") or f"row {index}"
            errors.append(
                f"spike_report.md Experiments and Checks {identity} must cite at least one exact Evidence ID"
            )
    return errors


def _technical_spike_report_evidence_traceability_errors(
    evidence_rows: list[dict[str, str]], direct_evidence_rows: list[dict[str, str]],
    decision_context: list[dict[str, str]], criteria: list[dict[str, str]],
    integration: list[dict[str, str]], options: list[dict[str, str]],
    checks: list[dict[str, str]], text: str,
) -> list[str]:
    referenced: set[str] = set()

    def collect(rows: list[dict[str, str]], fields: tuple[str, ...]) -> None:
        for row in rows:
            for field in fields:
                referenced.update(
                    reference for reference in REFERENCE_ID.findall(row.get(field, ""))
                    if reference.upper().startswith("E-")
                )

    collect(decision_context, ("Evidence refs",))
    collect(criteria, ("Evidence refs",))
    collect(integration, ("Evidence refs",))
    collect(options, ("Evidence",))
    collect(checks, (
        "Hypothesis or review criterion", "Observable seam", "Command or method",
        "Expected discriminating outcomes", "Actual result", "Disposition impact",
    ))
    for section in (
        "## Findings", "## Recommendation", "## Remaining Unknowns and Follow-up", "## Reference Comparison",
    ):
        match = re.search(rf"^{re.escape(section)}\s*\n(.*?)(?=^##\s|\Z)", text, re.MULTILINE | re.DOTALL)
        if match:
            referenced.update(
                reference for reference in REFERENCE_ID.findall(match.group(1))
                if reference.upper().startswith("E-")
            )

    direct_ids = {
        row.get("Evidence ID", "").strip() for row in direct_evidence_rows
        if row.get("Evidence ID", "").strip()
    }
    evidence_by_id = {
        row.get("Evidence ID", "").strip(): row for row in evidence_rows
        if row.get("Evidence ID", "").strip()
    }
    errors = []
    for evidence_id in sorted(referenced):
        if evidence_id in direct_ids:
            continue
        row = evidence_by_id.get(evidence_id)
        if not row:
            continue
        source = row.get("Method or source", "")
        if not TECHNICAL_SPIKE_SOURCE_LOCATOR.search(source):
            errors.append(
                f"spike_report.md Evidence {evidence_id} Method or source must include an exact source "
                "locator or direct-evidence row"
            )
        if _direct_evidence_observation_is_vague(row.get("Observation", "")):
            errors.append(
                f"spike_report.md Evidence {evidence_id} Observation must describe the source-backed "
                "observation; generic placeholder is not sufficient"
            )
    return errors


def _manifest_declares_reference(reference: str, declared_text: str) -> bool:
    normalized = reference.rstrip(".,;:)]}").lower()
    if normalized in declared_text:
        return True
    if URL_REFERENCE.fullmatch(reference):
        ticket_ids = REFERENCE_ID.findall(reference)
        return any(ticket_id.lower() in declared_text for ticket_id in ticket_ids)
    return False


def _spike_report_context_errors(
    evidence_rows: list[dict[str, str]], direct_evidence_rows: list[dict[str, str]],
    manifest_path: Path | None,
) -> list[str]:
    if manifest_path is None:
        return []
    try:
        manifest = load_manifest(manifest_path, explicit=False)
    except ValueError as error:
        return [f"spike_report.md run input manifest is invalid: {error}"]
    declared_text = json.dumps(manifest, sort_keys=True).lower()
    sources = [
        ("Method and Evidence", row.get("Evidence ID", "row"), "Method or source", row.get("Method or source", ""))
        for row in evidence_rows
    ] + [
        ("Direct Evidence", row.get("Evidence ID", "row"), field, row.get(field, ""))
        for row in direct_evidence_rows
        for field in ("Repository or source", "File or artifact location")
    ]
    errors = []
    for section, identity, field, value in sources:
        if not value.strip():
            continue
        for label, pattern in FORBIDDEN_REPORT_CONTEXT_PATTERNS:
            if pattern.search(value):
                errors.append(
                    f"spike_report.md {section} {identity} {field} contains forbidden context: {label}"
                )
        references = [
            match.group(0).rstrip(".,;:)]}")
            for match in EXTERNAL_DOCUMENT_URL.finditer(value)
        ]
        if EXTERNAL_DOCUMENT_MARKER.search(value):
            references.extend(re.findall(r"\b\d{6,}\b", value))
        for reference in dict.fromkeys(references):
            if not _manifest_declares_reference(reference, declared_text):
                errors.append(
                    f"spike_report.md {section} {identity} {field} references undeclared external document "
                    f"locator {reference!r}; declare it in run_inputs.json or remove it"
                )
    return errors


def technical_spike_report_errors(
    text: str, primary_goal: str, profile: str, workflow_result: str,
    expected_budget_status: str | None = None,
    input_manifest_path: Path | None = None,
    expected_revisions: tuple[str, ...] = (),
) -> list[str]:
    errors = []
    if not re.match(r"\A---\s*\n.*?\n---\s*\n", text, re.DOTALL):
        errors.append("spike_report.md must preserve the framework template frontmatter")
    if not re.search(r"^# Technical Spike Report\s*$", text, re.MULTILINE):
        errors.append("spike_report.md must preserve the # Technical Spike Report title")
    required_headings = (
        "## Metadata",
        "## Scope and Non-goals",
        "## Plain-Language Summary",
        "## Integration Participants and Boundaries",
        "## Method and Evidence",
        "## Direct Evidence",
        "## Decision Context",
        "## Assessment Criteria",
        "## Experiments and Checks",
        "## Findings",
        "## Options and Tradeoffs",
        "## Recommendation",
        "## Reference Comparison",
        "## Remaining Unknowns and Follow-up",
        "## Disposition",
    )
    heading_positions = []
    for heading in required_headings:
        match = re.search(rf"^{re.escape(heading)}\s*$", text, re.MULTILINE)
        if not match:
            errors.append(f"spike_report.md is missing {heading}")
        else:
            heading_positions.append(match.start())
    if len(heading_positions) == len(required_headings) and heading_positions != sorted(heading_positions):
        errors.append("spike_report.md canonical sections must preserve the framework template order")
    metadata = {row.get("Field", ""): row.get("Value", "") for row in markdown_table(text, "## Metadata")}
    plain_summary = re.search(
        r"^## Plain-Language Summary\s*\n(.*?)(?=^## |\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    if not plain_summary or not plain_summary.group(1).strip():
        errors.append("spike_report.md Plain-Language Summary must contain a readable explanation")
    elif re.search(r"\bWorkflow result\s*:", plain_summary.group(1), re.IGNORECASE):
        errors.append("spike_report.md Plain-Language Summary must not contain workflow disposition metadata")
    for row in markdown_table(text, "## Direct Evidence"):
        source = row.get("Repository or source", "")
        if re.search(r"\s+(?:\+|plus)\s+", source, re.IGNORECASE):
            errors.append(
                f"spike_report.md Direct Evidence {row.get('Evidence ID', 'row')} combines sources; "
                "use separate Evidence IDs for each source"
            )
    declared_revisions = normalized_metadata_value(metadata.get("Repositories and revisions", ""))
    for revision in expected_revisions:
        if revision and revision not in declared_revisions:
            errors.append(
                "spike_report.md Metadata Repositories and revisions must include the prepared execution "
                f"repository revision {revision}"
            )
    expected_objective = {
        "execute technical spike": "execute_spike",
        "review technical spike": "review_spike",
    }.get(primary_goal.strip().lower())
    for field in ("Work item", "Primary question", "Timebox or evidence budget", "Success criterion"):
        if not metadata.get(field, "").strip():
            errors.append(f"spike_report.md Metadata requires {field}")
    timebox = normalized_metadata_value(metadata.get("Timebox or evidence budget", ""))
    if timebox and not re.search(
        r"\b\d+(?:\.\d+)?[- ]?(?:minutes?|mins?|hours?|checks?|commands?|items?|tests?|artifacts?|sources?)\b",
        timebox,
        re.IGNORECASE,
    ):
        errors.append(
            "spike_report.md Timebox or evidence budget must state a numeric duration or evidence count"
        )
    objective = normalized_metadata_value(metadata.get("Objective", ""))
    profile_value = normalized_metadata_value(metadata.get("Execution profile", ""))
    if expected_objective and objective != expected_objective:
        errors.append(f"spike_report.md Objective must be {expected_objective}")
    if profile_value != profile:
        errors.append(f"spike_report.md Execution profile must be {profile}")
    review_target = normalized_metadata_value(metadata.get("Review target", ""))
    comparison_reference = normalized_metadata_value(metadata.get("Comparison reference", ""))
    if not comparison_reference:
        errors.append("spike_report.md Metadata requires Comparison reference")
    if expected_objective == "review_spike" and review_target.lower() in {
        "", "none", "not applicable",
    }:
        errors.append("spike_report.md review_spike requires Review target")
    if expected_objective == "execute_spike" and review_target.lower() not in {"none", "not applicable", "n/a"}:
        errors.append("spike_report.md execute_spike requires Review target to be Not applicable")
    if expected_objective == "review_spike" and comparison_reference.lower() not in {
        "none", "not applicable", "n/a",
    }:
        errors.append("spike_report.md review_spike requires Comparison reference to be Not applicable")
    evidence = markdown_table(text, "## Method and Evidence")
    if not evidence or any(not row.get(field, "").strip() for row in evidence for field in (
        "Evidence ID", "Method or source", "Observation", "Status", "Limitation",
    )):
        errors.append("spike_report.md requires one complete evidence row")
    direct_evidence = markdown_table(text, "## Direct Evidence")
    if not direct_evidence or any(not row.get(field, "").strip() for row in direct_evidence for field in (
        "Evidence ID", "Repository or source", "Revision or version", "File or artifact location", "Observation",
        "Status",
    )):
        errors.append("spike_report.md requires one complete direct-evidence row")
    integration = markdown_table(text, "## Integration Participants and Boundaries")
    if not integration or any(not row.get(field, "").strip() for row in integration for field in (
        "Participant or technology", "Role or boundary", "Evidence refs", "Evidence status or unknown",
    )):
        errors.append("spike_report.md requires one complete integration-participant row")
    errors.extend(_grouped_reference_errors(evidence, "Method and Evidence", ("Evidence ID",)))
    errors.extend(_grouped_reference_errors(direct_evidence, "Direct Evidence", ("Evidence ID",)))
    for row in direct_evidence:
        if _direct_evidence_location_is_vague(row.get("File or artifact location", "")):
            errors.append(
                f"spike_report.md Direct Evidence {row.get('Evidence ID', 'row')} File or artifact location "
                "must identify an exact file, document, runtime artifact, URL, or command; globs and search labels "
                "are not sufficient"
            )
        if _direct_evidence_observation_is_vague(row.get("Observation", "")):
            errors.append(
                f"spike_report.md Direct Evidence {row.get('Evidence ID', 'row')} Observation must describe "
                "the verified source observation; generic placeholder is not sufficient"
            )
        revision = normalized_metadata_value(row.get("Revision or version", ""))
        if (
            re.search(
                r"\b(?:current|latest|head|working\s+(?:tree|revision)|current\s+checkout)\b",
                revision,
                re.IGNORECASE,
            )
            and not re.search(r"\b[0-9a-f]{7,40}\b", revision, re.IGNORECASE)
        ):
            errors.append(
                f"spike_report.md Direct Evidence {row.get('Evidence ID', 'row')} Revision or version "
                "must identify an exact revision or version, not a current/working-tree label"
            )
    declared_evidence_ids = {
        row.get("Evidence ID", "").strip()
        for row in evidence + direct_evidence
        if row.get("Evidence ID", "").strip()
    }
    decision_context = markdown_table(text, "## Decision Context")
    if not decision_context or any(not row.get(field, "").strip() for row in decision_context for field in (
        "Category", "Statement or branch", "Evidence refs", "Owner or decision needed", "Status",
    )):
        errors.append("spike_report.md requires one complete decision-context row")
    allowed_decision_categories = {
        "confirmed fact", "assumption or hypothesis", "open decision", "recommended default", "not applicable",
    }
    if any(row.get("Category", "").strip().lower() not in allowed_decision_categories for row in decision_context):
        errors.append(
            "spike_report.md Decision Context Category must be Confirmed fact, Assumption or hypothesis, "
            "Open decision, Recommended default, or Not applicable"
        )
    for row in decision_context:
        category = row.get("Category", "").strip().lower()
        status = row.get("Status", "").strip().lower()
        if category == "confirmed fact" and re.match(r"^(recommended|proposed)\b", status):
            errors.append(
                "spike_report.md Decision Context confirmed facts cannot use a Recommended or Proposed status; "
                "use Recommended default for normative guidance"
            )
    criteria = markdown_table(text, "## Assessment Criteria")
    if not criteria or any(not row.get(field, "").strip() for row in criteria for field in (
        "Criterion or domain", "Evidence refs", "Assessment", "Gap or limitation", "Required next evidence or decision",
    )):
        errors.append("spike_report.md requires one complete assessment-criteria or Not applicable row")
    declared_criteria = _declared_spike_criteria(metadata.get("Assessment criteria or control domains", ""))
    assessed_criteria = [
        row for row in criteria
        if not _is_not_applicable(row.get("Criterion or domain", ""))
    ]
    if declared_criteria and len(assessed_criteria) != len(declared_criteria):
        errors.append(
            "spike_report.md Assessment Criteria must contain one row per declared criterion or control domain "
            f"(declared {len(declared_criteria)}, assessed {len(assessed_criteria)})"
        )
    elif declared_criteria and Counter(
        _normalized_spike_criterion(row.get("Criterion or domain", "")) for row in assessed_criteria
    ) != Counter(_normalized_spike_criterion(item) for item in declared_criteria):
        errors.append(
            "spike_report.md Assessment Criteria names must match the declared criterion or control-domain names "
            f"(declared {declared_criteria!r}, assessed "
            f"{[row.get('Criterion or domain', '').strip() for row in assessed_criteria]!r})"
        )
    errors.extend(_grouped_reference_errors(
        decision_context, "Decision Context", ("Evidence refs",)
    ))
    errors.extend(_technical_spike_evidence_reference_errors(
        decision_context, "Decision Context", ("Evidence refs",), declared_evidence_ids
    ))
    errors.extend(_grouped_reference_errors(criteria, "Assessment Criteria", ("Evidence refs",)))
    errors.extend(_technical_spike_evidence_reference_errors(
        criteria, "Assessment Criteria", ("Evidence refs",), declared_evidence_ids
    ))
    errors.extend(_grouped_reference_errors(integration, "Integration Participants and Boundaries", ("Evidence refs",)))
    errors.extend(_technical_spike_evidence_reference_errors(
        integration, "Integration Participants and Boundaries", ("Evidence refs",), declared_evidence_ids
    ))
    options = markdown_table(text, "## Options and Tradeoffs")
    if not options or any(not row.get(field, "").strip() for row in options for field in (
        "Option", "Evidence", "Benefits", "Costs or risks", "When to choose",
    )):
        errors.append("spike_report.md requires one complete option row")
    errors.extend(_grouped_reference_errors(options, "Options and Tradeoffs", ("Evidence",)))
    errors.extend(_technical_spike_evidence_reference_errors(
        options, "Options and Tradeoffs", ("Evidence",), declared_evidence_ids
    ))
    for index, row in enumerate(options, start=1):
        if _is_not_applicable(row.get("Option", "")):
            continue
        if not any(
            reference in declared_evidence_ids
            for reference in REFERENCE_ID.findall(row.get("Evidence", ""))
        ):
            errors.append(
                f"spike_report.md Options and Tradeoffs row {index} must cite at least one exact Evidence ID"
            )
    if expected_objective == "execute_spike":
        errors.extend(_spike_report_context_errors(evidence, direct_evidence, input_manifest_path))
    checks = markdown_table(text, "## Experiments and Checks")
    if not checks or any(not row.get(field, "").strip() for row in checks for field in (
        "Hypothesis or review criterion", "Observable seam", "Command or method",
        "Expected discriminating outcomes", "Actual result",
        "Disposition impact",
    )):
        errors.append("spike_report.md requires one complete experiment or Not run row")
    errors.extend(_grouped_reference_errors(
        checks,
        "Experiments and Checks",
        (
            "Hypothesis or review criterion", "Observable seam", "Command or method",
            "Expected discriminating outcomes", "Actual result", "Disposition impact",
        ),
    ))
    errors.extend(_technical_spike_evidence_reference_errors(
        checks,
        "Experiments and Checks",
        (
            "Hypothesis or review criterion", "Observable seam", "Command or method",
            "Expected discriminating outcomes", "Actual result", "Disposition impact",
        ),
        declared_evidence_ids,
        allow_check_ids=True,
    ))
    errors.extend(_technical_spike_check_evidence_errors(checks, declared_evidence_ids))
    for section in (
        "## Findings", "## Recommendation", "## Remaining Unknowns and Follow-up", "## Reference Comparison",
    ):
        errors.extend(_grouped_reference_text_errors(text, section))
        errors.extend(_technical_spike_evidence_text_errors(
            text,
            section,
            declared_evidence_ids,
            require_evidence=section in {"## Findings", "## Recommendation"},
        ))
    errors.extend(_technical_spike_report_evidence_traceability_errors(
        evidence, direct_evidence, decision_context, criteria, integration, options, checks, text,
    ))
    comparison = markdown_table(text, "## Reference Comparison")
    if not comparison or any(not row.get(field, "").strip() for row in comparison for field in (
        "Reference", "Agreement", "Difference or omission", "Impact on recommendation",
    )):
        errors.append("spike_report.md requires one complete reference-comparison or Not applicable row")
    elif (
        expected_objective == "execute_spike"
        and comparison_reference.lower() not in {"none", "not applicable", "n/a"}
        and all(row.get("Reference", "").strip().lower() in {"none", "not applicable", "n/a"} for row in comparison)
    ):
        errors.append("spike_report.md must compare the declared Comparison reference")
    disposition = {
        row.get("Field", ""): row.get("Value", "") for row in markdown_table(text, "## Disposition")
    }
    if disposition.get("Workflow result", "").strip() != workflow_result.strip():
        errors.append("spike_report.md Workflow result must match Final Handoff")
    for field in ("Question or review conclusion", "Budget status", "Feature Delivery handoff"):
        if not disposition.get(field, "").strip():
            errors.append(f"spike_report.md Disposition requires {field}")
    budget_status = disposition.get("Budget status", "").strip()
    allowed_budget_statuses = {
        "within_budget", "exhausted_with_useful_result", "exceeded_during_finalization",
        "stopped_by_indispensable_evidence",
    }
    if budget_status and budget_status not in allowed_budget_statuses:
        errors.append("spike_report.md Budget status must use canonical measured status")
    if expected_budget_status and budget_status != expected_budget_status:
        errors.append(f"spike_report.md Budget status must be {expected_budget_status}")
    return errors


def technical_spike_disposition_error(
    playbook: str,
    lifecycle: str,
    state: str,
    primary_goal: str,
    workflow_result: str,
    workflow_outcome: str,
    engineering_outcome: str,
) -> str | None:
    if playbook != "technical_spike":
        return None
    if lifecycle != "planning":
        return "Technical Spike supports planning lifecycle only"
    if state in {"blocked", "awaiting_input"}:
        return None
    if state != "completed":
        return "Technical Spike completed runs require state completed"
    dispositions = TECHNICAL_SPIKE_DISPOSITIONS.get(primary_goal.strip().lower())
    if dispositions is None:
        return "Technical Spike Primary goal must be Execute technical spike or Review technical spike"
    expected_engineering_outcome = dispositions.get(workflow_result.strip())
    if expected_engineering_outcome is None:
        return "Technical Spike completed run requires Workflow result exactly one of: " + ", ".join(dispositions)
    if workflow_outcome != "completed":
        return "Technical Spike completed run requires Workflow outcome completed"
    if engineering_outcome != expected_engineering_outcome:
        return (
            f"Technical Spike disposition {workflow_result.strip()} requires Engineering outcome "
            f"{expected_engineering_outcome}"
        )
    return None


def feature_assessment_disposition_error(
    playbook: str,
    lifecycle: str,
    state: str,
    primary_goal: str,
    workflow_result: str,
) -> str | None:
    if (
        playbook != "feature_delivery"
        or lifecycle != "planning"
        or primary_goal.strip().lower() != "specification assessment"
    ):
        return None
    allowed = FEATURE_ASSESSMENT_DISPOSITIONS.get(state)
    if allowed and workflow_result.strip() not in allowed:
        return (
            f"Feature Delivery specification assessment state {state} requires Workflow result exactly one of: "
            + ", ".join(sorted(allowed))
        )
    return None


def validate_playbook_metadata() -> None:
    for path in (ROOT / "playbooks").glob("*.md"):
        text = path.read_text()
        maturity = re.search(r"^maturity: (.+)$", text, re.M)
        if not maturity or maturity.group(1) not in MATURITY:
            fail(f"{path.relative_to(ROOT)} has no valid maturity")
        supported_lifecycles = {
            value.strip()
            for value in (frontmatter_value(path, "supported_lifecycles") or "planning, remediation").split(",")
        }
        if not supported_lifecycles or not supported_lifecycles <= LIFECYCLES:
            fail(f"{path.relative_to(ROOT)} has invalid supported lifecycles")
        expected_combinations = tuple(
            f"{profile} + {lifecycle}"
            for profile in ("standard", "deep")
            for lifecycle in ("planning", "remediation")
            if lifecycle in supported_lifecycles
        )
        exercise_scope = re.search(r"^exercise_scope: (.+)$", text, re.M)
        if not exercise_scope or any(value not in exercise_scope.group(1) for value in expected_combinations):
            fail(f"{path.relative_to(ROOT)} has incomplete exercise scope")
        unsupported_combinations = (
            f"{profile} + {lifecycle}"
            for profile in ("standard", "deep")
            for lifecycle in LIFECYCLES - supported_lifecycles
        )
        if exercise_scope and any(value in exercise_scope.group(1) for value in unsupported_combinations):
            fail(f"{path.relative_to(ROOT)} declares an unsupported lifecycle in exercise scope")
        if not re.search(r"^validation_summary: .+$", text, re.M):
            fail(f"{path.relative_to(ROOT)} has no validation summary")


def validate_worker_graphs() -> None:
    for path in (ROOT / "playbooks").glob("*.md"):
        text = path.read_text()
        if "standard planning workers, then `implement`" in text:
            fail(f"{path.relative_to(ROOT)} reruns planning workers during remediation")
        supports_remediation = "remediation" in {
            value.strip()
            for value in (frontmatter_value(path, "supported_lifecycles") or "planning, remediation").split(",")
        }
        if supports_remediation and not re.search(r"In-scope review\s+findings return", text):
            fail(f"{path.relative_to(ROOT)} is missing the delivery review loop")
        if "canonical Human-Readable Handoff" not in text and "shared human-readable template" not in text:
            fail(f"{path.relative_to(ROOT)} is missing the canonical human-readable handoff")
        if "in parallel" not in text or not re.search(r"recorded\s+discrepancy", text):
            fail(f"{path.relative_to(ROOT)} is missing Deep parallelism or non-duplication rules")
        if "never activate or delegate an `initialize` worker" not in text:
            fail(f"{path.relative_to(ROOT)} delegates Coordinator initialization")
        final_documenter = re.search(r"Activate\s+one final Documenter after analytical fan-in", text)
        deterministic_sentry = (
            path.stem == "sentry_issue_remediation"
            and "Do not activate a Documenter for either Standard planning result" in text
            and "deterministic Standard finalizer" in text
        )
        if not final_documenter and not deterministic_sentry:
            fail(f"{path.relative_to(ROOT)} is missing final-Documenter ownership")
        if supports_remediation and not re.search(r"final\s+`handoff`\s+after delivery fan-in", text):
            fail(f"{path.relative_to(ROOT)} is missing final remediation handoff ownership")
        if "| `initialize` |" in text:
            fail(f"{path.relative_to(ROOT)} declares an initialize worker")
        if re.search(r"(?:continuous|Continuous).*`handoff`", text):
            fail(f"{path.relative_to(ROOT)} declares a continuous handoff worker")


def validate_scenario_readiness() -> None:
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


def validate_feature_asset_gate() -> None:
    feature_playbook = (ROOT / "playbooks" / "feature_delivery.md").read_text()
    feature_prompt = (ROOT / "templates" / "feature_delivery_run_prompt.md").read_text()
    if not ASSET_MANIFEST_TEMPLATE.is_file():
        fail("templates/asset_manifest.json is missing")
    try:
        json.loads(ASSET_MANIFEST_TEMPLATE.read_text())
    except (OSError, json.JSONDecodeError) as error:
        fail(f"templates/asset_manifest.json is invalid JSON: {error}")
    for text, label in (
        (feature_playbook, "playbooks/feature_delivery.md"),
        (feature_prompt, "templates/feature_delivery_run_prompt.md"),
    ):
        for phrase in (
            "Planning objective:",
            "specification_assessment",
            "Specification assessment",
            "Ready with explicit follow-ups",
            "Not ready for implementation",
        ):
            if phrase not in text:
                fail(f"{label} is missing specification-assessment control: {phrase}")
    if "Planning objective: implementation_planning" not in feature_prompt:
        fail("templates/feature_delivery_run_prompt.md is missing the default planning objective")
    for text, label in (
        (feature_playbook, "playbooks/feature_delivery.md"),
        (feature_prompt, "templates/feature_delivery_run_prompt.md"),
        (JIRA_INTEGRATION.read_text(), "integrations/jira.md"),
    ):
        for phrase in ("asset_manifest.json", "attachment inventory", "awaiting_input"):
            if phrase not in text:
                fail(f"{label} is missing asset-gate control: {phrase}")
    for phrase in (
        "# Asset Inventory and Review",
        "asset_manifest.json",
        "all_assets_accounted_for",
        "reviewed_before_plan",
    ):
        if phrase not in (ROOT / "templates" / "work_record.md").read_text():
            fail(f"templates/work_record.md is missing asset-gate control: {phrase}")
    for phrase in ("# Asset Baseline", "asset_manifest.json", "material asset"):
        if phrase not in (ROOT / "templates" / "implementation_plan.md").read_text():
            fail(f"templates/implementation_plan.md is missing asset-gate control: {phrase}")
    for relative, phrases in {
        "contracts/code_review.md": (
            "## Requirement applicability", "## Review boundary and identity", "## Behavior review",
            "## Finding validity", "## Validation and disposition", "unchanged payload builders",
        ),
        "templates/code_review.md": ("## Behavior Review", "## Reconciliation and Next Action", "Candidate SHA256"),
        "templates/validation_report.md": ("## Behavior Coverage", "## Release Follow-up", "Candidate SHA256"),
        "templates/implementation_plan.md": ("# Behavior Applicability", "Counterexample check / result"),
        "playbooks/feature_delivery.md": ("scripts/review_evidence.py", "contracts/code_review.md"),
    }.items():
        content = (ROOT / relative).read_text()
        for phrase in phrases:
            if phrase not in content:
                fail(f"{relative} is missing evidence-driven review control: {phrase}")
    for phrase in ("Asset source: true", "asset_manifest.json", "awaiting_input"):
        if phrase not in RUN_SKILL.read_text():
            fail(f"skills/run/SKILL.md is missing asset-gate control: {phrase}")
    for path, phrase in (
        (ROOT / "integrations" / "jira.md", "complete direct-child inventory"),
        (ROOT / "integrations" / "jira.md", "playbook requires an asset inventory"),
        (ROOT / "providers" / "codex.md", "enumeration when collection coverage is required"),
        (ROOT / "playbooks" / "technical_spike.md", "A Done child Spike"),
        (CODEX_AGENT_DIR / "orchestrator.toml", "For every Jira-backed run"),
    ):
        if phrase not in path.read_text():
            fail(f"{path.relative_to(ROOT)} is missing Jira related-work coverage: {phrase}")


def validate_technical_spike_definition() -> None:
    technical_spike_playbook = (ROOT / "playbooks" / "technical_spike.md").read_text()
    technical_spike_prompt = (ROOT / "templates" / "technical_spike_run_prompt.md").read_text()
    technical_spike_report = (ROOT / "templates" / "spike_report.md").read_text()
    for text, label in (
        (technical_spike_playbook, "playbooks/technical_spike.md"),
        (technical_spike_prompt, "templates/technical_spike_run_prompt.md"),
    ):
        for phrase in (
            "execute_spike",
            "review_spike",
            "Execute technical spike",
            "Review technical spike",
            "spike_report.md",
            "Question answered",
            "Changes required",
            "Inconclusive",
            "Requested outcome:",
            "Prompt-completeness gate",
            "comparison reference",
            "source of truth",
            "source-specific",
            "Plain-Language Summary",
        ):
            if phrase not in text:
                fail(f"{label} is missing Technical Spike control: {phrase}")
    for phrase in (
        "default_timebox_minutes: 35",
        "default_success_criterion:",
        "Baseline success criterion",
    ):
        if phrase not in technical_spike_playbook:
            fail(f"playbooks/technical_spike.md is missing Technical Spike default: {phrase}")
    for phrase in (
        "Primary question:",
        "Timebox or evidence budget override (optional):",
        "Success criterion override (optional):",
        "Prompt-completeness gate",
        "--primary-question",
        "--success-criterion",
        "playbook supplies the",
    ):
        if phrase not in technical_spike_prompt:
            fail(f"templates/technical_spike_run_prompt.md is missing prompt-completeness control: {phrase}")
    for phrase in (
        "Timebox or evidence budget",
        "Integration Participants and Boundaries",
        "Direct Evidence",
        "Decision Context",
        "Assessment Criteria",
        "Experiments and Checks",
        "Observable seam",
        "Comparison reference",
        "Reference Comparison",
        "Feature Delivery handoff",
        "Plain-Language Summary",
    ):
        if phrase not in technical_spike_report:
            fail(f"templates/spike_report.md is missing Technical Spike report field: {phrase}")
    if not markdown_table(technical_spike_report, "## Direct Evidence"):
        fail("templates/spike_report.md has an invalid Direct Evidence table")


def validate_bounded_vulnerability_route() -> None:
    workflow_contract = WORKFLOW_CONTRACT.read_text()
    vulnerability_playbook = (ROOT / "playbooks" / "vulnerability_investigation.md").read_text()
    for phrase in (
        "### Bounded Dependency Route",
        "shared `change_set_id`",
        "pilot soft target",
        "Routine dependency updates, upgrades, patches, and lockfile refreshes remain `standard`",
        "requested profile is immutable for the run",
        "Worker effort escalation does not activate the `deep` graph",
        "this route uses three delegated workers",
        "The Coordinator performs initialization directly",
        "pilot soft target is 10 minutes end to end",
        "Normal runs have no byte-count field or hard size gate",
        "checkout is not the execution repository",
        "not change source operations back to the original checkout",
        "identifier equality during fan-in",
        "6-8 minutes end to end",
        "Do not call a failure `pre-existing`",
    ):
        if phrase not in vulnerability_playbook:
            fail(f"playbooks/vulnerability_investigation.md is missing bounded-run control: {phrase}")

    vulnerability_prompt = (ROOT / "templates" / "vulnerability_issue_run_prompt.md").read_text()
    for phrase in (
        "owns the affected artifact",
        "Affected component root",
        "three-worker graph",
        "runtime-managed worktree",
        "Coordinator performs preflight directly",
    ):
        if phrase not in vulnerability_prompt:
            fail(f"templates/vulnerability_issue_run_prompt.md is missing bounded-run field: {phrase}")

    for phrase in (
        "The execution repository may itself contain code",
        "Never infer the framework checkout as the",
        "resolved source-checkout path",
        "MUST NOT override an equivalent active worktree",
        "Durable artifacts MUST remain under the",
        "never under an ephemeral managed-worktree path",
        "missing tool does not authorize downloading",
    ):
        if phrase not in workflow_contract:
            fail(f"contracts/workflow_execution.md is missing wall-time boundary: {phrase}")


def validate_sentry_execution() -> None:
    sentry_playbook = (ROOT / "playbooks" / "sentry_issue_remediation.md").read_text()
    if "requested profile is immutable for the run" not in sentry_playbook:
        fail("playbooks/sentry_issue_remediation.md is missing immutable-profile control")
    for phrase in (
        "pilot target is 10-12 minutes",
        "15-17 minutes when cross-repository analysis",
        "deterministic finalization",
        "initialization acknowledgement",
        "exact model and reasoning effort",
        "framework_revision_mismatch",
        "make a stale prompt match",
        "minimal work-record skeleton",
        "scripts/finalize_work_record.py",
        "scripts/finalize_sentry_planning.py",
        "one smallest available check",
        "do not run unit or integration tests merely",
        "Best current explanations",
        "Normal runs have no byte-count field or hard size gate",
        "exclusively owns raw Sentry queries",
        "`limit: 1` when supported",
        "keep the plan `Draft`",
        "Reference",
        "one explicit cross-repository question",
        "canonical durable artifacts",
        "run_already_active",
        "event emitter, comparison owner, baseline producer",
        "initialization is limited",
        "never activate or delegate an `initialize` worker",
        "resolve that issue directly before any project or issue",
        "three Sentry data queries total",
        "30 seconds",
        "90 seconds",
        "supplied_occurrence",
        "fix_design_result.json",
        "# Contract Delta",
        "materially different fix implications",
        "Standard does not parallelize those two dependent stages",
        "artifact exists and passes artifact validation",
        "--normalized-evidence",
        "organization slug",
        "validate_worker_runtime.py --trace",
        "field-preservation change",
        "Pilot Standard finalizer may",
        "independently audited",
    ):
        if phrase not in sentry_playbook:
            fail(f"playbooks/sentry_issue_remediation.md is missing Standard control: {phrase}")
    contract_example = re.search(r"```text\n(# Contract Delta\n.*?\n)```", sentry_playbook, re.DOTALL)
    if not contract_example:
        fail("playbooks/sentry_issue_remediation.md is missing the canonical Contract Delta example")
    elif sentry_contract_delta_errors(
        contract_example.group(1).replace(
            "equivalent / not_equivalent / not_established", "not_established"
        )
    ):
        fail("playbooks/sentry_issue_remediation.md contains an invalid Contract Delta example")
