"""Work-record projections and canonical handoff formatting."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

try:
    from workflow_policy import NO_ACTIVE_HANDLES
except ModuleNotFoundError:
    from scripts.workflow_policy import NO_ACTIVE_HANDLES
try:
    from asset_manifest import ASSET_MANIFEST_FILENAME
except ModuleNotFoundError:
    from scripts.asset_manifest import ASSET_MANIFEST_FILENAME


try:
    from packet_schema import _validate_shapes, normalize_runtime_closure
except ModuleNotFoundError:
    from scripts.packet_schema import _validate_shapes, normalize_runtime_closure


def _material_rows(value: object, identity_field: str) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    rows = [row for row in value if isinstance(row, dict)]
    return rows if any(str(row.get(identity_field, "")).strip() for row in rows) else []


def _feature_asset_manifest(packet: dict[str, object]) -> tuple[Path, dict[str, object] | None]:
    finalization = packet.get("finalization", {})
    root = finalization.get("Durable artifact root") if isinstance(finalization, dict) else None
    root_path = Path(str(root)) if root else Path(".")
    path = root_path / ASSET_MANIFEST_FILENAME
    if not path.is_file():
        return path, None
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return path, None
    return path, value if isinstance(value, dict) else None


def _explanation_text(item: object) -> str:
    if not isinstance(item, dict):
        return str(item)
    explanation = str(item.get("explanation", "")).strip()
    confidence = str(item.get("confidence", "")).strip()
    reason = str(item.get("reason", "")).strip()
    if not explanation:
        raise ValueError("structured handoff explanation is missing explanation")
    if any("\n" in value for value in (explanation, confidence, reason)):
        raise ValueError("structured handoff explanation fields must be single-line text")
    suffix = "; ".join(part for part in (f"confidence: {confidence}" if confidence else "", reason) if part)
    return f"{explanation} ({suffix})" if suffix else explanation


def _artifact_link(item: object, artifact_root: object) -> str:
    value = str(item).strip()
    if value.startswith("[") and "](" in value and value.endswith(")"):
        label, target = value.split("](", 1)
        target = target[:-1]
        if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", target):
            return value
        target = target.strip("<>")
        path = Path(target)
        if not path.is_absolute():
            path = Path(str(artifact_root)) / path
        destination = str(path.resolve())
        return f"{label}](<{destination}>)" if " " in destination else f"{label}]({destination})"
    path = Path(value)
    if not path.is_absolute():
        path = Path(str(artifact_root)) / path
    destination = str(path.resolve())
    return f"[{path.name}](<{destination}>)" if " " in destination else f"[{path.name}]({destination})"


def _relative_artifact_path(value: object, artifact_root: object) -> str:
    path = Path(str(value).strip())
    root = Path(str(artifact_root)).resolve()
    if not path.is_absolute():
        path = root / path
    try:
        relative = path.resolve().relative_to(root)
    except ValueError:
        return str(path)
    return f"./{relative}"


def _artifact_rows_for_record(packet: dict[str, object]) -> list[dict[str, object]]:
    root = packet["finalization"]["Durable artifact root"]
    return [
        {**row, "Path": _relative_artifact_path(row.get("Path", ""), root)}
        for row in packet["durable_artifacts"]
    ]


def _feature_asset_section(packet: dict[str, object]) -> str:
    path, manifest = _feature_asset_manifest(packet)
    if manifest is None:
        return f"Asset manifest unavailable: {path}. Terminal planning is prohibited."
    root = path.parent.resolve()
    sources = [
        {
            "Source ID": source.get("source_id", ""),
            "Input ID": source.get("input_id", ""),
            "Kind": source.get("kind", ""),
            "Locator": source.get("locator", ""),
            "Discovery": source.get("discovery_status", ""),
            "Limitation": source.get("limitation", ""),
            "Evidence refs": ", ".join(source.get("evidence_refs", [])),
        }
        for source in manifest.get("sources", [])
        if isinstance(source, dict)
    ]
    assets = [
        {
            "Asset ID": asset.get("asset_id", ""),
            "Source ID": asset.get("source_id", ""),
            "Kind": asset.get("kind", ""),
            "Locator": asset.get("locator", ""),
            "Review": asset.get("review_status", ""),
            "Method": asset.get("review_method", ""),
            "Relevance": asset.get("relevance", ""),
            "Observation / disposition": (
                f"{asset.get('observation', '')} {asset.get('disposition', '')}"
            ).strip(),
            "Evidence refs": ", ".join(asset.get("evidence_refs", [])),
        }
        for asset in manifest.get("assets", [])
        if isinstance(asset, dict)
    ]
    gate = manifest.get("gate", {})
    gate_status = str(manifest.get("status", ""))
    body = (
        f"Manifest: [{path.name}]({_relative_artifact_path(path, root)})\n\n"
        f"Asset gate: {gate_status}; inventory_complete={gate.get('inventory_complete')}; "
        f"all_assets_accounted_for={gate.get('all_assets_accounted_for')}; "
        f"all_available_assets_reviewed={gate.get('all_available_assets_reviewed')}; "
        f"all_material_assets_linked={gate.get('all_material_assets_linked')}; "
        f"reviewed_before_plan={gate.get('reviewed_before_plan')}.\n\n"
        "Source inventory:\n"
        + _table(("Source ID", "Input ID", "Kind", "Locator", "Discovery", "Limitation", "Evidence refs"), sources)
    )
    if assets:
        body += (
            "\n\nAsset review:\n"
            + _table(
                ("Asset ID", "Source ID", "Kind", "Locator", "Review", "Method", "Relevance",
                 "Observation / disposition", "Evidence refs"),
                assets,
            )
        )
    else:
        body += "\n\nAsset review: No individual assets; every declared source reported an explicit empty inventory."
    return body


def _cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", "<br>")


def _table(headers: tuple[str, ...], rows: list[dict[str, object]]) -> str:
    if not rows:
        raise ValueError(f"missing_rows:{headers[0]}")
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(_cell(row.get(header, "")) for header in headers) + " |")
    return "\n".join(lines)


def _mapping_table(values: dict[str, object]) -> str:
    visible = {
        key: value
        for key, value in values.items()
        if not (key == "Evaluation run ID" and str(value).strip().lower() == "not applicable")
    }
    return _table(("Field", "Value"), [{"Field": key, "Value": value} for key, value in visible.items()])


def _section(title: str, body: str) -> str:
    return f"# {title}\n\n{body}\n"


def _runtime_closed(rows: list[dict[str, object]]) -> bool:
    return bool(rows) and all(
        str(row.get("Runtime status", "")).strip().lower() in {"released", "terminal"}
        and NO_ACTIVE_HANDLES.fullmatch(str(row.get("Remaining active handles", "")).strip())
        for row in rows
    )


def snapshot_bytes(packet: dict[str, object]) -> bytes:
    return (json.dumps(packet, indent=2) + "\n").encode()


def snapshot_name(packet: dict[str, object]) -> str:
    return f"finalization_snapshot.{hashlib.sha256(snapshot_bytes(packet)).hexdigest()}.json"


def render_compact(packet: dict[str, object]) -> str:
    """Project the validated packet into a resumable engineering record."""
    operational = {
        "Run Isolation and Finalization", "Worker Execution Ledger", "Worker Synchronization",
        "Worker Runtime Closure", "Worker Terminal Observations", "Worker Runtime Audits",
    }
    sections = re.split(r"(?m)(?=^# )", render(packet))
    result = []
    for section in sections:
        title = section.split("\n", 1)[0].removeprefix("# ")
        if title in operational:
            continue
        if title == "Run and Evaluation Identity":
            fields = (
                "Run ID", "Playbook / version", "Framework commit / status", "Plugin package / version",
                "Requested profile", "Executed profile", "Lifecycle", "State", "Engineering state", "Workflow outcome",
                "Engineering outcome", "Current stage", "Internal owner", "Next-action owner", "User action", "Next action",
            )
            summary = {key: packet["identity"].get(key, "Not provided") for key in fields}
            action = packet.get("handoff", {}).get("next_action", {})
            for field, value in {"Current stage": packet["identity"].get("State"), "Internal owner": "Workflow Coordinator",
                                 "Next-action owner": action.get("owner"), "Next action": action.get("action"),
                                 "User action": action.get("action") if packet["identity"].get("State") == "awaiting_input"
                                 else "None required by this handoff"}.items():
                if summary.get(field) in {"", "Not provided", None} and value:
                    summary[field] = value
            summary["Runtime status"] = ", ".join(
                str(row["Runtime status"]) for row in packet["runtime_closure"]
            )
            limitations = [str(row["Closure evidence or blocker"]) for row in packet["runtime_closure"]
                           if str(row["Runtime status"]).lower() not in {"released", "terminal"}]
            if limitations:
                summary["Runtime limitation"] = "; ".join(limitations)
            section = _section("Run Summary", _mapping_table(summary))
        elif title == "Repository Evidence Eligibility":
            section = _section("Repository Baseline", _table(
                ("Repository role", "Declared path", "Full revision", "Evidence eligibility"), packet["repositories"]
            ))
        elif title == "Worker Result Summary":
            section = _section(title, _table(
                ("Worker", "Outcome", "Confidence", "Unique contribution", "Evidence / claim refs",
                 "Uncertainties / blockers"), packet["worker_results"]
            ))
        elif title == "Asset Inventory and Review":
            _, manifest = _feature_asset_manifest(packet)
            status = manifest.get("status", "Unavailable") if manifest else "Unavailable"
            section = _section(title, f"Manifest: [asset_manifest.json](asset_manifest.json)\n\nAsset gate: {status}.")
        result.append(section.strip())
    name = snapshot_name(packet)
    result.insert(1, _section("Workflow Receipts", (
        f"Operational details: [Workflow state snapshot]({name}).\n\n"
        "This normalized finalization-packet snapshot preserves run identity, provider configuration, worker ledgers,\n"
        "synchronization, finalization, and runtime observations. Linked source receipts remain required.\n\n"
        f"<!-- workflow-state: {name} -->"
    )).strip())
    return "\n\n".join(result) + "\n"


def render_handoff(packet: dict[str, object]) -> str:
    handoff = packet["handoff"]
    explanations = handoff.get("best_current_explanations", [])
    explanation_block = ""
    if explanations:
        explanation_block = "\nBest current explanations:\n" + "".join(
            f"- {_explanation_text(item)}\n" for item in explanations
        )
    established = "".join(f"- {item}\n" for item in handoff["established"])
    risks = [str(row.get("Uncertainties / blockers", "")).strip() for row in packet.get("worker_results", [])
             if isinstance(row, dict) and str(row.get("Uncertainties / blockers", "")).strip().lower()
             not in {"", "none", "not applicable", "no provider handle exists because the worker was not activated."}]
    risks = [value for value in risks if not re.fullmatch(
        r"See (?:normalized_evidence\.md(?: and Fix Design checks remaining)?|blocking_unknowns and clarification_brief)"
        r"(?:; provider trace audit passed)?", value, re.I)]
    if packet["identity"].get("State") == "awaiting_input":
        risks.insert(0, "Unresolved evidence or decisions in Next action still limit the requested outcome.")
    risk = "; ".join(dict.fromkeys(" ".join(value.split()) for value in risks)) or (
        "The requested engineering outcome remains unresolved."
        if packet["identity"]["Workflow outcome"] == "blocked" else "No additional risk recorded in this handoff.")
    artifacts = "".join(
        f"- {_artifact_link(item, packet['finalization']['Durable artifact root'])}\n"
        for item in handoff["artifacts"]
    )
    runtime = "not released" if packet["runtime_closure"] else "closure unverified"
    if _runtime_closed(packet["runtime_closure"]):
        runtime = "released" if all(
            str(row.get("Runtime status", "")).lower() == "released" for row in packet["runtime_closure"]
        ) else "terminal"
    execution = str(handoff["execution"]).rstrip(" .;")
    if not re.search(rf"\bruntime\s+{runtime}\b", execution, flags=re.IGNORECASE):
        execution = f"{execution}; runtime {runtime}"
    return f"""```text
Workflow result: {handoff['workflow_result']}

- State: {packet['identity']['State']}
- Engineering state: {packet['identity']['Engineering state']}
- Workflow outcome: {packet['identity']['Workflow outcome']}
- Engineering outcome: {packet['identity']['Engineering outcome']}
- Implementation plan: {handoff['implementation_plan']}

What we established:
{established}{explanation_block}
Next action:
- Owner: {handoff['next_action']['owner']}
- Action: {handoff['next_action']['action']}
- Complete when: {handoff['next_action']['complete_when']}

Artifacts:
{artifacts}
Execution: {execution}.
Provenance: {handoff['provenance']}
Not checked: Work outside the execution and validation scope recorded above.
Risk: {risk}
```"""


def render(packet: dict[str, object]) -> str:
    handoff_text = render_handoff(packet)
    sections = [
        "# Engineering Work Record\n",
        _section("Work Item", _mapping_table(packet["work_item"])),
        _section("Playbook Selection", _table(
            ("Primary evidence", "Primary goal", "Selected playbook", "Closest alternative", "Why this playbook"),
            [packet["playbook_selection"]],
        )),
        _section("Input Register", _table(
            ("Input ID", "Input or artifact", "Source or path", "Authority", "Status"), packet["inputs"]
        )),
        _section("Repository Evidence Eligibility", _table(
            ("Repository role", "Declared path", "Resolved path", "Branch / detached", "Full revision", "Clean status",
             "User-selected ref", "Release mapping", "Evidence eligibility"), packet["repositories"]
        )),
        _section("Run and Evaluation Identity", _mapping_table(packet["identity"])),
        _section("Run Isolation and Finalization", _mapping_table(packet["finalization"])),
        _section("Durable Artifacts", _table(
            ("Artifact", "Path", "Status", "Purpose"), _artifact_rows_for_record(packet)
        )),
        _section("Worker Execution Ledger", _table(
            ("Worker", "Role", "Assigned inputs", "Mode", "Depth", "Skills", "Tools", "Capacity",
             "Configured model/effort", "Provider-observed model/effort", "Usage", "Depends on",
             "Outcome", "Confidence"), packet["workers"]
        )),
        _section("Worker Synchronization", _table(
            ("Stage", "Workers launched", "Launch mode / exception", "Worker outcomes", "Results summarized",
             "Barrier status"), packet["synchronization"]
        )),
        _section("Worker Runtime Closure", _table(
            ("Run or stage", "Receipt owner", "Completed worker handles", "Runtime status", "Remaining active handles",
             "Closure evidence or blocker"), packet["runtime_closure"]
        )),
        _section("Worker Result Summary", _table(
            ("Worker", "Outcome", "Confidence", "Unique contribution", "Evidence / claim refs",
             "Uncertainties / blockers", "Actual model/effort", "Usage/credits"), packet["worker_results"]
        )),
        _section("Evidence", _table(
            ("Evidence ID", "Source", "Summary", "Confidence", "Uncertainty", "Status"), packet["evidence"]
        )),
        _section("Claims", _table(
            ("Claim ID", "Claim", "Evidence refs", "Confidence", "Uncertainty", "Status"), packet["claims"]
        )),
        _section("Decision Log", _table(
            ("Decision ID", "Decision", "Claim refs", "Owner", "Status"), packet["decisions"]
        )),
        _section("Action Log", _table(
            ("Action ID", "Action", "Decision ref", "Owner", "Status"), packet["actions"]
        )),
        _section("Final Handoff", handoff_text),
    ]
    playbook_name = Path(str(packet["identity"].get("Playbook / version", "")).split(" / ", 1)[0]).stem
    if playbook_name == "feature_delivery":
        sections.insert(4, _section("Asset Inventory and Review", _feature_asset_section(packet)))
    for key, title, headers in (
        ("terminal_observations", "Worker Terminal Observations", (
            "Provider handle", "Provider status", "Last dispatch at", "Observed at", "Status source",
            "Thread ID", "Latest turn started at", "Latest turn status",
            "Thread status",
        )),
        ("techops_checks", "TechOps Planning Checks", (
            "Check", "Status", "Evidence refs", "Detail", "Commit", "Patch evidence refs",
            "Work item", "Work item evidence refs",
        )),
        ("runtime_audits", "Worker Runtime Audits", (
            "Worker", "Provider handle", "Provider status", "Last dispatch at", "Observed at", "Status source",
            "Thread ID", "Latest turn started at", "Latest turn status", "Trace path", "Trace retrieval",
            "Thread status",
        )),
    ):
        if packet.get(key):
            sections.insert(-1, _section(title, _table(headers, packet[key])))
    return "\n".join(sections)


def expand_work_record(text: str, root: Path) -> str:
    """Verify a compact projection, then feed its complete packet to legacy checks."""
    match = re.search(r"<!-- workflow-state: (finalization_snapshot\.([0-9a-f]{64})\.json) -->", text)
    if not match:
        if "workflow-state:" in text or re.search(r"finalization_snapshot\.[0-9a-f]{64}\.json", text):
            raise ValueError("compact work record requires a valid workflow-state snapshot reference")
        return text
    path = root / match.group(1)
    if path.is_symlink():
        raise ValueError("workflow-state snapshot must be a local regular file")
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != match.group(2):
        raise ValueError("workflow-state snapshot hash mismatch")
    packet = json.loads(content)
    receipt_path = root / packet["runtime_receipt"]
    if receipt_path.resolve().parent != root.resolve() or receipt_path.is_symlink():
        raise ValueError("runtime closure receipt must be a local regular file")
    receipt = json.loads(receipt_path.read_text())
    _validate_shapes(packet, receipt)
    normalize_runtime_closure(receipt)
    if (receipt.get("runtime_closure") != packet["runtime_closure"]
            or receipt.get("terminal_observations", []) != packet.get("terminal_observations", [])):
        raise ValueError("workflow-state snapshot conflicts with its runtime closure receipt")
    if text != render_compact(packet):
        raise ValueError("work record does not match its workflow-state snapshot; rerun the finalizer")
    return render(packet)
