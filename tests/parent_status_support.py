"""Synthetic native task-status evidence for stale-run archive tests."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from scripts.provider_runtime import prior_run_status_thread_ids, related_run_status_projection_source


PARENT_THREAD_ID = "00000000-0000-0000-0000-000000000101"
TURN_ID = "00000000-0000-0000-0000-000000000102"
STATUS_CALL_ID = "status-call-001"


def write_parent_status_session(
    path: Path, artifact_root: Path, rows: list[dict] | None = None, *, timestamp: str | None = None,
) -> Path:
    """Write one correlated status-only call using identity metadata from the old run."""
    prior_ids = prior_run_status_thread_ids(artifact_root, PARENT_THREAD_ID)
    source = related_run_status_projection_source(artifact_root.name, PARENT_THREAD_ID, prior_ids)
    start = (datetime.fromisoformat(timestamp.replace("Z", "+00:00")) if timestamp else
             datetime.now(UTC) - timedelta(seconds=1))
    stamp = lambda seconds: (start + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")
    native_rows = [
        {"type": "session_meta", "timestamp": stamp(0),
         "payload": {"id": PARENT_THREAD_ID}},
        {"type": "turn_context", "timestamp": stamp(1),
         "payload": {"turn_id": TURN_ID}},
        {"type": "response_item", "timestamp": stamp(2), "payload": {
            "type": "custom_tool_call", "name": "exec", "call_id": STATUS_CALL_ID, "input": source,
        }},
        {"type": "response_item", "timestamp": stamp(3), "payload": {
            "type": "custom_tool_call_output", "call_id": STATUS_CALL_ID,
            "output": [{"type": "text", "text": json.dumps(rows or [])}],
        }},
    ]
    path.write_text("".join(json.dumps(row) + "\n" for row in native_rows))
    return path
