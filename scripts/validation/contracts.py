"""Deterministic contracts validation rules."""

from __future__ import annotations

from collections import Counter
import json
import re
from .common import (
    BLOCKING_DECISION_TYPES,
    CLAIMS_CONTRACT,
    ENGINEERING_OUTCOMES,
    ENGINEERING_STATES,
    INTERFACE_CONTRACT_FIELDS,
    JIRA_FIXTURE,
    JIRA_INTEGRATION,
    JIRA_REQUIRED_HEADINGS,
    LIFECYCLES,
    PORTABLE_HANDOFF_CONTRACT,
    PROFILES,
    PROFILE_STATUSES,
    PROHIBITED_CONTEXT_MARKERS,
    READINESS_ACTIONS,
    REFERENCE_ID,
    ROOT,
    SENTRY_PLAN_FIELDS,
    TERMINAL_STATES,
    UNRESOLVED_INTERFACE_MARKERS,
    WORKFLOW_CONTRACT,
    WORKFLOW_GUIDANCE,
    WORKFLOW_OUTCOMES,
    WORKFLOW_VOCABULARY,
    WORK_ITEM_READ_FIXTURE,
    fail,
)
from .markdown import (
    is_table_row,
    markdown_table,
    table_cells,
)


RFC3339_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)

WORK_ITEM_READ_SCOPES = {"item", "hierarchy", "selected_links", "history", "write_metadata"}

WORK_ITEM_READ_REQUIREDNESS = {"required", "optional"}

WORK_ITEM_READ_RESULT_STATES = {
    "complete",
    "empty",
    "not_found",
    "unavailable",
    "permission_denied",
    "partial",
    "stale",
    "conflict",
}

WORK_ITEM_READ_EVIDENCE_STATUSES = {"verified", "inferred", "contradicted", "unknown"}

WORK_ITEM_ASSET_AVAILABILITIES = {"available", "unavailable", "permission_denied", "redacted", "not_found"}

def work_item_read_contract_errors(
    fixture: object,
    *,
    label: str = "Work-item read fixture",
    expected_source_system: str | None = None,
) -> list[str]:
    errors: list[str] = []
    if not isinstance(fixture, dict):
        return [f"{label} shape must contain one object"]

    request = fixture.get("request")
    result = fixture.get("result")
    if not isinstance(request, dict):
        errors.append(f"{label} request must be an object")
    if not isinstance(result, dict):
        errors.append(f"{label} result must be an object")
    if not isinstance(request, dict) or not isinstance(result, dict):
        return errors

    if request.get("capability") != "work_item_read":
        errors.append(f"{label} request must use work_item_read")
    identity = request.get("identity")
    if not isinstance(identity, dict):
        errors.append(f"{label} identity must be an object")
        identity_source = None
    else:
        identity_source = identity.get("source_system")
        if not isinstance(identity_source, str) or not identity_source.strip():
            errors.append(f"{label} identity must name a source system")
        elif expected_source_system and identity_source != expected_source_system:
            errors.append(f"{label} identity must name {expected_source_system}")
        if not identity.get("key") and not identity.get("url"):
            errors.append(f"{label} identity needs a key or URL")
    scopes = request.get("scope")
    if not isinstance(scopes, list) or not scopes or any(scope not in WORK_ITEM_READ_SCOPES for scope in scopes):
        errors.append(f"{label} scope must contain valid non-empty scopes")
    if request.get("requiredness") not in WORK_ITEM_READ_REQUIREDNESS:
        errors.append(f"{label} requiredness must be required or optional")
    if isinstance(scopes, list) and any(scope != "item" for scope in scopes):
        if not isinstance(request.get("selection_reason"), str) or not request["selection_reason"].strip():
            errors.append(f"{label} requires selection_reason for non-item scope")

    state = result.get("state")
    if state not in WORK_ITEM_READ_RESULT_STATES:
        errors.append(f"{label} has an invalid result state")
    retrieved_at = result.get("retrieved_at")
    if not isinstance(retrieved_at, str) or not RFC3339_TIMESTAMP.fullmatch(retrieved_at):
        errors.append(f"{label} retrieved_at must be RFC 3339")
    for field in ("source_updated_at",):
        if field in result:
            value = result[field]
            if not isinstance(value, str) or not RFC3339_TIMESTAMP.fullmatch(value):
                errors.append(f"{label} {field} must be RFC 3339")
    if "source_version" in result and (
        not isinstance(result["source_version"], str) or not result["source_version"].strip()
    ):
        errors.append(f"{label} source_version must be a non-empty string")

    work_item = result.get("work_item")
    if work_item is None and state == "complete":
        errors.append(f"{label} complete result requires work_item")
    elif work_item is not None and not isinstance(work_item, dict):
        errors.append(f"{label} work_item must be an object when present")
    elif isinstance(work_item, dict):
        for field in ("id", "source_system", "type", "title", "description"):
            if not isinstance(work_item.get(field), str) or not work_item[field].strip():
                errors.append(f"{label} work_item {field} must be a non-empty string")
        if identity_source and work_item.get("source_system") != identity_source:
            errors.append(f"{label} work_item must use the identity source system")

    evidence = result.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        errors.append(f"{label} evidence must be a non-empty list")
    else:
        for index, record in enumerate(evidence):
            if not isinstance(record, dict):
                errors.append(f"{label} evidence {index} must be an object")
                continue
            for field in ("evidence_id", "source_location", "authority", "status"):
                if not isinstance(record.get(field), str) or not record[field].strip():
                    errors.append(f"{label} evidence {index} is missing {field}")
            if record.get("status") not in WORK_ITEM_READ_EVIDENCE_STATUSES:
                errors.append(f"{label} evidence {index} has an invalid status")
            if not isinstance(record.get("redacted"), bool):
                errors.append(f"{label} evidence {index} redacted must be boolean")
    if isinstance(scopes, list) and "history" in scopes:
        assets = result.get("assets")
        if not isinstance(assets, list):
            errors.append(f"{label} history result requires an explicit assets list")
        else:
            asset_ids: set[str] = set()
            for index, asset in enumerate(assets):
                if not isinstance(asset, dict):
                    errors.append(f"{label} asset {index} must be an object")
                    continue
                for field in (
                    "asset_id", "source_location", "locator", "name", "media_type", "availability",
                    "retrieval_limitation",
                ):
                    if not isinstance(asset.get(field), str) or not asset[field].strip():
                        errors.append(f"{label} asset {index} is missing {field}")
                asset_id = asset.get("asset_id")
                if isinstance(asset_id, str) and asset_id in asset_ids:
                    errors.append(f"{label} duplicate asset_id {asset_id}")
                if isinstance(asset_id, str):
                    asset_ids.add(asset_id)
                if asset.get("availability") not in WORK_ITEM_ASSET_AVAILABILITIES:
                    errors.append(f"{label} asset {index} has an invalid availability")
                if not isinstance(asset.get("redacted"), bool):
                    errors.append(f"{label} asset {index} redacted must be boolean")
    for field in ("related_context", "limitations"):
        if not isinstance(result.get(field), list):
            errors.append(f"{label} {field} must be a list")
    return errors

def jira_adapter_contract_errors(fixture: object) -> list[str]:
    return work_item_read_contract_errors(
        fixture,
        label="Jira integration fixture",
        expected_source_system="Jira",
    )

def reasoning_record_errors(text: str) -> list[str]:
    errors = []
    tables = (
        ("evidence", "# Evidence", "Evidence ID"),
        ("claim", "# Claims", "Claim ID"),
        ("decision", "# Decision Log", "Decision ID"),
        ("action", "# Action Log", "Action ID"),
    )
    records = {}
    for label, heading, key in tables:
        rows = markdown_table(text, heading)
        ids = [row.get(key, "") for row in rows if row.get(key, "")]
        for duplicate in sorted(value for value, count in Counter(ids).items() if count > 1):
            errors.append(f"duplicate {label} {duplicate}")
        records[label] = {row.get(key, ""): row for row in rows if row.get(key, "")}
    evidence, claims, decisions, actions = (records[label] for label, _, _ in tables)

    if not all((evidence, claims, decisions, actions)):
        errors.append("must contain populated Evidence, Claims, Decision Log, and Action Log tables")
        return errors

    evidence_used = set()
    claims_used = set()
    decisions_used = set()
    for evidence_id, row in evidence.items():
        if not row.get("Source") or row["Source"] in {"Unknown", "None"}:
            errors.append(f"{evidence_id} has no source")
    for claim_id, row in claims.items():
        refs = set(REFERENCE_ID.findall(row.get("Evidence refs", "")))
        if not refs:
            errors.append(f"{claim_id} has no evidence refs")
        for ref in refs:
            if ref not in evidence:
                if ref.upper().startswith("CHK-"):
                    errors.append(
                        f"{claim_id} references missing evidence {ref}; {ref} is an experiment/check ID, "
                        "not an Evidence-table ID; map it to a source-backed Evidence ID"
                    )
                else:
                    errors.append(f"{claim_id} references missing evidence {ref}")
            else:
                evidence_used.add(ref)
    for decision_id, row in decisions.items():
        refs = set(REFERENCE_ID.findall(row.get("Claim refs", "")))
        if not refs:
            errors.append(f"{decision_id} has no claim refs")
        for ref in refs:
            if ref not in claims:
                errors.append(f"{decision_id} references missing claim {ref}")
            else:
                claims_used.add(ref)
    for action_id, row in actions.items():
        refs = set(REFERENCE_ID.findall(row.get("Decision ref", "")))
        if len(refs) != 1:
            errors.append(f"{action_id} must reference exactly one decision")
        for ref in refs:
            if ref not in decisions:
                errors.append(f"{action_id} references missing decision {ref}")
            else:
                decisions_used.add(ref)

    for label, records, used in (
        ("evidence", evidence, evidence_used),
        ("claim", claims, claims_used),
        ("decision", decisions, decisions_used),
    ):
        for orphan in sorted(set(records) - used):
            errors.append(f"orphaned {label} {orphan}")
    return errors


def sentry_contract_delta_errors(text: str) -> list[str]:
    lines = text.splitlines()
    heading_index = next(
        (index for index, line in enumerate(lines) if re.fullmatch(r"#{1,6}\s+Contract Delta\s*", line)),
        None,
    )
    if heading_index is None:
        return ["normalized evidence requires a Contract Delta heading at any Markdown heading level"]
    table_index = heading_index + 1
    while table_index < len(lines) and not lines[table_index].strip():
        table_index += 1
    if table_index >= len(lines) or not is_table_row(lines[table_index]):
        return ["contract delta heading must be followed by a Markdown table header"]
    expected_headers = ("Boundary", "Representation", "Field identity / coordinate space", "Evidence refs")
    headers = table_cells(lines[table_index])
    if tuple(headers) != expected_headers:
        return [f"contract delta table headers must be: {' | '.join(expected_headers)}"]
    if table_index + 1 >= len(lines) or not is_table_row(lines[table_index + 1]):
        return ["contract delta table requires a Markdown separator row immediately after the header"]
    separator = table_cells(lines[table_index + 1])
    if len(separator) != len(headers) or not all(
        "-" in cell and set(cell) <= {"-", ":"} for cell in separator
    ):
        return ["contract delta table requires a Markdown separator row immediately after the header"]
    rows = []
    for line_number, line in enumerate(lines[table_index + 2:], table_index + 3):
        if not is_table_row(line):
            break
        cells = table_cells(line)
        if len(cells) != len(headers):
            return [f"contract delta row {line_number} has {len(cells)} cells; expected {len(headers)}"]
        rows.append(dict(zip(headers, cells, strict=True)))
    if not rows:
        return ["contract delta table requires five populated boundary rows"]
    required = {"Baseline", "Outbound", "Destination input", "Return", "Semantic input equivalence"}
    boundaries = [row.get("Boundary", "") for row in rows]
    errors = []
    for duplicate, count in Counter(boundaries).items():
        if duplicate and count > 1:
            errors.append(f"contract delta contains duplicate boundary: {duplicate}")
    by_boundary = {row.get("Boundary", ""): row for row in rows}
    for boundary in sorted(required - set(by_boundary)):
        errors.append(f"contract delta is missing boundary: {boundary}")
    for boundary in required & set(by_boundary):
        row = by_boundary[boundary]
        for field in ("Representation", "Field identity / coordinate space", "Evidence refs"):
            if not row.get(field, "").strip():
                errors.append(f"contract delta {boundary} is missing {field}")
    semantic = by_boundary.get("Semantic input equivalence", {}).get("Representation", "").lower()
    if semantic and semantic not in {"equivalent", "not_equivalent", "not_established"}:
        errors.append("contract delta Semantic input equivalence has an invalid representation")
    return errors


def _sentry_contract_delta_rows(text: str) -> dict[str, dict[str, str]]:
    """Return the validated Contract Delta rows for semantic boundary checks."""
    if sentry_contract_delta_errors(text):
        return {}
    lines = text.splitlines()
    heading_index = next(
        (index for index, line in enumerate(lines) if re.fullmatch(r"#{1,6}\s+Contract Delta\s*", line)),
        None,
    )
    if heading_index is None:
        return {}
    table_index = heading_index + 1
    while table_index < len(lines) and not lines[table_index].strip():
        table_index += 1
    rows: list[dict[str, str]] = []
    for line in lines[table_index + 2 :]:
        if not is_table_row(line):
            break
        cells = table_cells(line)
        if len(cells) != 4:
            return {}
        rows.append(dict(zip(
            ("Boundary", "Representation", "Field identity / coordinate space", "Evidence refs"),
            cells,
            strict=True,
        )))
    return {row["Boundary"]: row for row in rows}


def _has_explicit_field_identity(response_shape: object) -> bool:
    text = str(response_shape).lower()
    if "field" not in text:
        return False
    if any(marker in text for marker in (
        "no new response property", "unqualified", "no field identity", "identity is absent",
        "source field is unavailable",
    )):
        return False
    if re.search(r"\b(?:no|without|missing|absent|unavailable)\b.{0,30}\bfield\b", text):
        return False
    return any(marker in text for marker in (
        "property", "key", "identity", "identifier", "qualified", "tag", "coordinate", "origin",
    ))


def _mentions_user_source(value: object) -> bool:
    return bool(re.search(r"(?<![a-z])user(?:\b|[-_])", str(value).lower()))


def sentry_upstream_boundary_errors(
    normalized_evidence: str, fix_design: dict[str, object], *, require_plan: bool
) -> list[str]:
    """Ensure a field-loss delta cannot be finalized as a downstream-only fix."""
    if not require_plan or fix_design.get("plan_readiness") != "ready_for_implementation":
        return []
    rows = _sentry_contract_delta_rows(normalized_evidence)
    if not rows:
        return []
    delta_fields = ("Representation", "Field identity / coordinate space")
    baseline = " ".join(rows.get("Baseline", {}).get(field, "") for field in delta_fields).lower()
    outbound = " ".join(rows.get("Outbound", {}).get(field, "") for field in delta_fields).lower()
    destination = " ".join(rows.get("Destination input", {}).get(field, "") for field in delta_fields).lower()
    field_keyed = any(
        marker in baseline for marker in ("field-keyed", "field keyed", "link_title", "link_summary")
    )
    scalar_loss = any(
        marker in value
        for value in (outbound, destination)
        for marker in ("scalar", "message-only", "identity lost", "no field identity", "no outbound")
    )
    if not (field_keyed and scalar_loss):
        return []

    plan = fix_design.get("plan")
    contract = fix_design.get("interface_contract")
    boundary_rows = plan.get("exact_boundaries") if isinstance(plan, dict) else None
    has_upstream_boundary = False
    if isinstance(boundary_rows, list):
        for row in boundary_rows:
            if not isinstance(row, dict):
                continue
            repository = str(row.get("repository", "")).lower()
            symbols = " ".join(str(value) for value in row.get("files_symbols", [])).lower()
            boundary_text = f"{repository} {symbols}"
            if "fanmgmt" in boundary_text and any(
                marker in symbols
                for marker in ("publisher", "workflow.py", "_publish_to_eos", "serializer", "request")
            ):
                has_upstream_boundary = True
                break
    request_shape = str(contract.get("request_shape", "")).lower() if isinstance(contract, dict) else ""
    response_shape = str(contract.get("response_shape", "")).lower() if isinstance(contract, dict) else ""
    adds_field_keyed_request = any(
        marker in request_shape
        for marker in ("field-keyed", "field keyed", "text_fields", "link_title", "link_summary")
    ) and not re.search(
        r"\bno\s+(?:inbound\s+)?request|\b(?:no|without)\s+.*(?:field|title|summary)",
        request_shape,
    )
    if has_upstream_boundary and adds_field_keyed_request:
        if _has_explicit_field_identity(response_shape):
            return []
        return [
            "ready field-keyed interface must preserve field identity in the response contract; "
            "name a field property, key, identifier, or equivalent qualification"
        ]
    return [
        "ready fix design must address the observed upstream field-preservation delta: "
        "include the producer boundary and an affirmative field-keyed request change"
    ]


def fix_design_result_errors(
    data: object, *, required_input_markers: tuple[str, ...] = (), require_plan: bool = False
) -> list[str]:
    if not isinstance(data, dict):
        return ["fix_design_result.json must contain one object"]
    errors = []
    required = {
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
    }
    missing = sorted(
        field for field in required
        if field not in data and (field != "confidence" or require_plan)
    )
    if missing:
        errors.append(f"fix design result is missing fields: {', '.join(missing)}")
        return errors
    readiness = data["plan_readiness"]
    action = data["implementation_plan_action"]
    if readiness not in READINESS_ACTIONS:
        errors.append(f"invalid plan_readiness: {readiness}")
    elif action != READINESS_ACTIONS[readiness]:
        errors.append(f"{readiness} requires implementation_plan_action: {READINESS_ACTIONS[readiness]}")
    if data["outcome"] != "complete":
        errors.append("fix design outcome must be complete before finalization")
    for field in ("worker_id", "worker_handle", "configuration_conformance"):
        if not isinstance(data[field], str) or not data[field].strip():
            errors.append(f"fix design {field} must be a non-empty string")
    if isinstance(data["worker_handle"], str) and data["worker_handle"].strip().lower() in {
        "not exposed", "unknown", "none", "not applicable",
    }:
        errors.append("fix design worker_handle must contain the exact activation handle")
    if (
        not isinstance(data["inputs_consumed"], list)
        or not data["inputs_consumed"]
        or not all(isinstance(value, str) and value.strip() for value in data["inputs_consumed"])
    ):
        errors.append("fix design inputs_consumed must be a non-empty list")
    elif required_input_markers and not any(
        marker in value for value in data["inputs_consumed"] for marker in required_input_markers
    ):
        errors.append(
            "fix design inputs_consumed must include " + " or ".join(required_input_markers)
        )
    if data["context_conformance"] != "pass":
        errors.append("fix design context_conformance must pass")
    for field in ("supported_remediation_boundary", "supported_intended_change"):
        if not isinstance(data[field], str):
            errors.append(f"fix design {field} must be a string")
    for field in ("checks_performed", "checks_remaining", "blocking_unknowns"):
        if not isinstance(data[field], list):
            errors.append(f"fix design {field} must be a list")
    if not isinstance(data["interface_change"], bool):
        errors.append("fix design interface_change must be true or false")
    confidence = data.get("confidence")
    if confidence is not None or require_plan:
        if not isinstance(confidence, dict):
            errors.append("fix design confidence must be an object with level, basis, and limits")
        else:
            for field in ("level", "basis", "limits"):
                if not isinstance(confidence.get(field), str) or not confidence[field].strip():
                    errors.append(f"fix design confidence {field} must be a non-empty string")
    if errors:
        return errors
    boundary = data["supported_remediation_boundary"]
    intended_change = data["supported_intended_change"]
    blockers = data["blocking_unknowns"]
    interface_change = data["interface_change"]
    interface_contract = data["interface_contract"]
    if bool(boundary.strip()) != bool(intended_change.strip()):
        errors.append("supported remediation boundary and intended change must be provided together")
    if readiness == "ready_for_implementation":
        if "clarification_brief" in data:
            errors.append("ready fix design must omit clarification_brief")
        if not isinstance(boundary, str) or not boundary.strip():
            errors.append("ready fix design requires a supported remediation boundary")
        if not isinstance(intended_change, str) or not intended_change.strip():
            errors.append("ready fix design requires a supported intended change")
        if blockers:
            errors.append("ready fix design cannot retain blocking_unknowns")
        if interface_change:
            if not isinstance(interface_contract, dict):
                errors.append("ready interface change requires interface_contract")
            else:
                for field in INTERFACE_CONTRACT_FIELDS:
                    value = interface_contract.get(field)
                    if not isinstance(value, str) or not value.strip():
                        errors.append(f"interface_contract {field} must be a non-empty string")
                    elif UNRESOLVED_INTERFACE_MARKERS.search(value):
                        errors.append(
                            f"ready interface contract {field} contains unresolved semantics; "
                            "change readiness to awaiting_input until the exact value is established"
                        )
                request_shape = str(interface_contract.get("request_shape", "")).lower()
                response_shape = str(interface_contract.get("response_shape", "")).lower()
                field_keyed = any(
                    marker in request_shape
                    for marker in ("field-keyed", "field keyed", "text_fields", "link_title", "link_summary")
                )
                local_extents = "extent" in response_shape and any(
                    marker in response_shape for marker in ("field", "local", "source")
                )
                explicit_identity = _has_explicit_field_identity(response_shape)
                if field_keyed and local_extents and not explicit_identity:
                    errors.append(
                        "field-local multi-field extents require explicit response-side field identity"
                    )
        elif interface_contract is not None:
            errors.append("non-interface change requires interface_contract: null")
        plan = data.get("plan")
        if require_plan and not isinstance(plan, dict):
            errors.append("ready fix design requires structured plan content")
        elif isinstance(plan, dict):
            missing_plan_fields = [field for field in SENTRY_PLAN_FIELDS if field not in plan]
            if missing_plan_fields:
                errors.append("ready fix design plan is missing fields: " + ", ".join(missing_plan_fields))
            for field in ("title", "root_cause"):
                if field in plan and (not isinstance(plan[field], str) or not plan[field].strip()):
                    errors.append(f"ready fix design plan {field} must be a non-empty string")
            for field in set(SENTRY_PLAN_FIELDS) - {"title", "root_cause", "residual_uncertainty"}:
                if field in plan and not isinstance(plan[field], list):
                    errors.append(f"ready fix design plan {field} must be a list")
            for field in ("ordered_steps", "completion_criteria"):
                if field in plan and isinstance(plan[field], list) and not plan[field]:
                    errors.append(f"ready fix design plan {field} must not be empty")
    elif readiness == "awaiting_input":
        if "plan" in data:
            errors.append("awaiting_input fix design must omit plan")
        if not data["checks_performed"]:
            errors.append("awaiting_input requires at least one performed discriminating check")
        if not blockers:
            errors.append("awaiting_input requires at least one structured blocking unknown")
        for index, blocker in enumerate(blockers, start=1):
            if not isinstance(blocker, dict):
                errors.append(f"blocking unknown {index} must be an object")
                continue
            decision_type = blocker.get("decision_type")
            implications = blocker.get("fix_implications")
            evidence_refs = blocker.get("evidence_refs")
            contradicting_refs = blocker.get("contradicting_evidence_refs")
            observed_competing = blocker.get("observed_competing_boundaries")
            if decision_type not in BLOCKING_DECISION_TYPES:
                errors.append(f"blocking unknown {index} has invalid decision_type")
            if not isinstance(blocker.get("invalidates_supported_change"), bool):
                errors.append(f"blocking unknown {index} invalidates_supported_change must be a boolean")
            if not isinstance(blocker.get("question"), str) or not blocker["question"].strip():
                errors.append(f"blocking unknown {index} requires a question")
            if not isinstance(blocker.get("unavailable_reason"), str) or not blocker["unavailable_reason"].strip():
                errors.append(f"blocking unknown {index} requires an unavailable_reason")
            if (
                not isinstance(implications, list)
                or not all(isinstance(value, str) for value in implications)
                or len({value.strip() for value in implications if value.strip()}) < 2
            ):
                errors.append(f"blocking unknown {index} must identify at least two materially different fixes")
            if (
                not isinstance(evidence_refs, list)
                or not evidence_refs
                or not all(isinstance(value, str) and value.strip() for value in evidence_refs)
            ):
                errors.append(f"blocking unknown {index} requires evidence_refs")
            if blocker.get("invalidates_supported_change") is True and (
                not isinstance(contradicting_refs, list)
                or not contradicting_refs
                or not all(isinstance(value, str) and value.strip() for value in contradicting_refs)
            ):
                errors.append(
                    f"blocking unknown {index} that invalidates a supported change requires "
                    "contradicting_evidence_refs"
                )
            if blocker.get("invalidates_supported_change") is True:
                if not isinstance(observed_competing, list) or not observed_competing:
                    errors.append(
                        f"blocking unknown {index} that invalidates a supported change requires at least one "
                        "observed_competing_boundary"
                    )
                else:
                    for competing_index, competing in enumerate(observed_competing, start=1):
                        if not isinstance(competing, dict):
                            errors.append(
                                f"blocking unknown {index} observed_competing_boundary {competing_index} "
                                "must be an object"
                            )
                            continue
                        for field in ("boundary", "observation"):
                            if not isinstance(competing.get(field), str) or not competing[field].strip():
                                errors.append(
                                    f"blocking unknown {index} observed_competing_boundary {competing_index} "
                                    f"requires {field}"
                                )
                        competing_refs = competing.get("evidence_refs")
                        if (
                            not isinstance(competing_refs, list)
                            or not competing_refs
                            or not all(isinstance(value, str) and value.strip() for value in competing_refs)
                        ):
                            errors.append(
                                f"blocking unknown {index} observed_competing_boundary {competing_index} "
                                "requires evidence_refs"
                            )
        if (
            not boundary.strip()
            and not intended_change.strip()
            and any(
                isinstance(blocker, dict)
                and blocker.get("decision_type") == "incompatible_alternatives"
                and blocker.get("invalidates_supported_change") is False
                for blocker in blockers
            )
        ):
            errors.append(
                "awaiting_input incompatible_alternatives blocker cannot clear the candidate boundary and intended "
                "change; retain the candidate or provide evidence that it is invalidated"
            )
        if boundary and intended_change and not all(
            isinstance(blocker, dict) and blocker.get("invalidates_supported_change") is True
            for blocker in blockers
        ):
            errors.append(
                "awaiting_input cannot defer an established boundary and intended change without evidence that each "
                "blocker invalidates the supported change"
            )
        clarification = data.get("clarification_brief")
        if not isinstance(clarification, dict):
            errors.append("awaiting_input requires a structured clarification_brief")
        else:
            for field in ("confirmed_facts", "feasible_options"):
                values = clarification.get(field)
                if (
                    not isinstance(values, list)
                    or not values
                    or not all(isinstance(value, str) and value.strip() for value in values)
                ):
                    errors.append(f"clarification_brief {field} must be a non-empty list of strings")
            for field in ("strongest_hypothesis", "recommendation", "plain_language_next_action"):
                if not isinstance(clarification.get(field), str) or not clarification[field].strip():
                    errors.append(f"clarification_brief {field} must be a non-empty string")
    serialized = json.dumps(data, sort_keys=True)
    for marker in PROHIBITED_CONTEXT_MARKERS:
        if marker in serialized:
            errors.append(f"fix design result contains prohibited context marker: {marker}")
    return errors


def _contains_hypothesis(value: object) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in {"hypothesis", "hypotheses"} and nested:
                return True
            if _contains_hypothesis(nested):
                return True
    elif isinstance(value, list):
        return any(_contains_hypothesis(item) for item in value)
    return False


def terminal_semantics_errors(identity: dict[str, str], *, allow_unreleased: bool = False) -> list[str]:
    errors = []
    enums = {
        "Requested profile": PROFILES,
        "Activated profile": PROFILES | {"None"},
        "Executed profile": PROFILES | {"None"},
        "Profile status": PROFILE_STATUSES,
        "Lifecycle": LIFECYCLES,
        "State": TERMINAL_STATES | ({"handoff", "in_progress"} if allow_unreleased else set()),
        "Engineering state": ENGINEERING_STATES,
        "Workflow outcome": WORKFLOW_OUTCOMES | ({"in_progress"} if allow_unreleased else set()),
        "Engineering outcome": ENGINEERING_OUTCOMES,
    }
    for field, allowed in enums.items():
        if identity.get(field) not in allowed:
            errors.append(f"invalid {field}: {identity.get(field, '')}")
    state = identity.get("State")
    workflow_outcome = identity.get("Workflow outcome")
    if state in {"completed", "ready_for_implementation", "awaiting_input"} and workflow_outcome != "completed":
        errors.append(f"state {state} requires Workflow outcome completed")
    if state == "blocked" and workflow_outcome != "blocked":
        errors.append("state blocked requires Workflow outcome blocked")
    return errors


def validate_source_contracts() -> None:
    work_item_read_errors = []
    if not WORK_ITEM_READ_FIXTURE.is_file():
        work_item_read_errors.append("tests/fixtures/work_item_read_contract.json is missing")
    else:
        try:
            work_item_read_fixture = json.loads(WORK_ITEM_READ_FIXTURE.read_text())
        except json.JSONDecodeError as error:
            work_item_read_errors.append(f"Work-item read fixture is invalid JSON: {error}")
        else:
            work_item_read_errors.extend(work_item_read_contract_errors(work_item_read_fixture))
    if work_item_read_errors:
        fail("Work-item read contract: " + "\nFAIL: ".join(work_item_read_errors))

    jira_errors = []
    if not JIRA_INTEGRATION.is_file():
        jira_errors.append("integrations/jira.md is missing")
    else:
        jira_text = JIRA_INTEGRATION.read_text()
        jira_errors.extend(
            f"Jira integration is missing {heading}"
            for heading in JIRA_REQUIRED_HEADINGS
            if heading not in jira_text
        )
    if not JIRA_FIXTURE.is_file():
        jira_errors.append("tests/fixtures/jira_adapter_contract.json is missing")
    else:
        try:
            jira_fixture = json.loads(JIRA_FIXTURE.read_text())
        except json.JSONDecodeError as error:
            jira_errors.append(f"Jira adapter fixture is invalid JSON: {error}")
        else:
            jira_errors.extend(jira_adapter_contract_errors(jira_fixture))
    if jira_errors:
        fail("Jira contract: " + "\nFAIL: ".join(jira_errors))


def validate_execution_contracts() -> None:
    workflow_contract = WORKFLOW_CONTRACT.read_text()
    for provider_detail in ("MCP", "Atlassian", "Rovo", "Codex", "browser", "spawn_agent", "create_thread", "fork_thread",
                            "send_message_to_thread", "fork_context", ".codex/agents", "list_agents", "read_thread",
                            "wait_threads", "source_access_receipt.py", "plugin-backed launcher"):
        if provider_detail in workflow_contract:
            fail(f"contracts/workflow_execution.md contains provider/integration implementation detail: {provider_detail}")
    for phrase in ("## Initialization and Layer Boundaries", "selected adapter's worker primitive",
                   "source integration's retrieval and coverage policy"):
        if phrase not in workflow_contract:
            fail(f"contracts/workflow_execution.md is missing layer boundary: {phrase}")
    if "## Normative Language" not in workflow_contract:
        fail("contracts/workflow_execution.md is missing normative language")
    for invariant_id in range(1, 42):
        if f"`INV-{invariant_id:02d}`" not in workflow_contract:
            fail(f"contracts/workflow_execution.md is missing INV-{invariant_id:02d}")
    invariant_ids = re.findall(r"\| `(INV-\d{2})` \|", workflow_contract)
    for invariant_id, count in Counter(invariant_ids).items():
        if count > 1:
            fail(f"contracts/workflow_execution.md contains duplicate {invariant_id}")
    if "# Pilot Conformance Checklist" not in workflow_contract:
        fail("contracts/workflow_execution.md is missing the conformance checklist")
    for heading in (
        "# Human Control Model",
        "# Work-Item Read Contract",
        "## Authoritative Run Inputs",
        "## Context Preservation and Classification",
        "## Playbook Selection",
        "## Human-Readable Handoff",
        "## Worker Wait and Termination Semantics",
        "## Stop Conditions",
        "## Explicit Path Verification",
        "## Concurrent Run Isolation",
        "## Final Handoff Reconciliation",
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
        "required claims established by source-backed evidence",
        "critical assumptions supported, contradicted, or explicitly accepted",
        "acceptance criteria recovered or an approved equivalent recorded",
        "no blocking unknown",
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
        "- Engineering state: <unknown | understood | designed | approved | implemented | validated | released | stabilized | not_applicable>",
        "Workflow outcome: <completed | incomplete | blocked>",
        "Engineering outcome: <solved | partially_solved | plan_only | blocked | incorrect>",
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
    for phrase in (
        "## Referential Integrity",
        "every action references an existing decision",
        "every evidence record names a source",
        "no evidence, claim, or decision record is orphaned",
    ):
        if phrase not in claims_contract:
            fail(f"contracts/claims.md is missing referential-integrity control: {phrase}")
    if "Claims, Evidence, Decisions, and Actions Contract" not in workflow_contract:
        fail("contracts/workflow_execution.md is missing the claims contract reference")
    if "Coordinator MUST NOT load the `sentry` skill or invoke a Sentry MCP/app" not in (ROOT / "integrations/sentry.md").read_text():
        fail("integrations/sentry.md is missing the Coordinator Sentry-access boundary")
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
        "A final handoff MUST reconcile durable artifact state",
        "A remediation run sharing an execution repository",
        "Every worker activation MUST include a compact value/source/authority manifest",
        "Evaluation identity, role-policy baseline, detailed",
        "run_already_active",
        "skill or plugin enable/disable directive",
        "current-run input manifest",
        "Live runtime evidence is additive",
        "run_inputs.json",
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


def validate_coordinator_authority() -> None:
    workflow_contract = WORKFLOW_CONTRACT.read_text()
    for phrase in (
        "MUST NOT change a technical worker's diagnosis",
        "mutually conditional candidate files",
        "owning technical worker MUST perform the assigned investigation",
        "renderer is the only writer of the terminal `work_record.md`",
        "Do not add a second generic outcome field",
        "pass those exact values explicitly",
        "sole writer for its assigned non-record artifacts and packet",
        "MUST NOT reread",
        "New runs are memory-isolated",
        "returned activation metadata",
        "Active-run artifacts MUST be direct children",
        "Never reduce a useful hypothesis result",
        "During planning, run a unit or integration test only",
        "Complete when",
        "Reserve `plan_only`",
        "one finalized packet",
        "context_conformance",
        "configuration_conformance",
        "run_prompt_nonconformant",
        "evidence_eligibility",
        "On Documenter-owned paths, keep the final Documenter handle live",
        "implementation_plan_action",
        "provider_configuration_unavailable",
        "Never semantically normalize",
        "Workflow-framework validation: passed",
        "fresh\nprovider context",
        "Coordinator initialization: complete",
        "blocking_unknowns",
        "plan feasibility and specification readiness are separate decisions",
    ):
        if phrase not in workflow_contract:
            fail(f"contracts/workflow_execution.md is missing plan-readiness control: {phrase}")
