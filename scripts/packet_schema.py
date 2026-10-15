"""Shared packet field validation for merging and finalization."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKET_TEMPLATE = ROOT / "templates" / "finalization_packet.json"
CLOSURE_TEMPLATE = ROOT / "templates" / "runtime_closure.json"
UUID_PATTERN = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


def shape_errors(value: object, template: object, path: str) -> list[str]:
    if isinstance(template, dict):
        if not isinstance(value, dict):
            return [f"{path} must be an object"]
        errors = [f"{path}.{key} is missing" for key in template if key not in value]
        for key in template.keys() & value.keys():
            errors.extend(shape_errors(value[key], template[key], f"{path}.{key}"))
        return errors
    if isinstance(template, list):
        if not isinstance(value, list):
            return [f"{path} must be a list"]
        if template:
            return [
                error
                for index, item in enumerate(value)
                for error in shape_errors(item, template[0], f"{path}[{index}]")
            ]
        return []
    if not isinstance(value, type(template)):
        return [f"{path} must be {type(template).__name__}"]
    return []


def _validate_shapes(packet: object, closure: object) -> None:
    errors = shape_errors(packet, json.loads(PACKET_TEMPLATE.read_text()), "packet")
    errors.extend(shape_errors(closure, json.loads(CLOSURE_TEMPLATE.read_text()), "closure"))
    if errors:
        raise ValueError("packet_schema_invalid: " + "; ".join(errors))


def normalize_runtime_closure(closure: dict[str, object]) -> None:
    for row in closure.get("runtime_closure", []):
        if not isinstance(row, dict):
            continue
        handles = UUID_PATTERN.findall(str(row.get("Completed worker handles", "")))
        if handles and str(row.get("Runtime status", "")).strip().lower() == "released":
            row["Completed worker handles"] = ", ".join(dict.fromkeys(handles))
            evidence = str(row.get("Closure evidence or blocker", ""))
            if str(row.get("Runtime status", "")).strip().lower() == "released" and any(
                handle.lower() not in evidence.lower() for handle in handles
            ):
                row["Closure evidence or blocker"] = f"{evidence.rstrip('.')} Completed handles: {', '.join(handles)}."
