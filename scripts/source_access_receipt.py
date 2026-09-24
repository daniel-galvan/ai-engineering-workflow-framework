#!/usr/bin/env python3
"""Emit a small terminal receipt when a required source is inaccessible before run initialization."""

from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime


PROVIDER_CODE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def blocked_receipt(
    source: str, work_item: str, operation: str, provider_code: str, started_at: str,
    *, observed_at: datetime | None = None,
) -> dict[str, object]:
    if not all(value.strip() for value in (source, work_item, operation)) or not PROVIDER_CODE.fullmatch(provider_code):
        raise ValueError("source_access_receipt_invalid_input")
    try:
        started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("source_access_receipt_invalid_start") from error
    if started.tzinfo is None:
        raise ValueError("source_access_receipt_invalid_start")
    now = observed_at or datetime.now(UTC)
    if now < started:
        raise ValueError("source_access_receipt_invalid_start")
    return {
        "status": "blocked",
        "reason": "required_source_unavailable",
        "source": source.strip(),
        "work_item": work_item.strip(),
        "operation": operation.strip(),
        "provider_code": provider_code,
        "state": "blocked",
        "workflow_outcome": "blocked",
        "profile_status": "not_executed",
        "worker_activation_attempts": 0,
        "artifact_root": None,
        "elapsed_ms": round((now - started).total_seconds() * 1000),
    }


def self_test() -> None:
    started = "2026-09-24T16:11:22Z"
    observed = datetime.fromisoformat("2026-09-24T16:11:52+00:00")
    receipt = blocked_receipt(
        "Jira", "ECHO-2675", "getAccessibleAtlassianResources", "USER_NOT_LOGGED_IN", started,
        observed_at=observed,
    )
    assert receipt["elapsed_ms"] == 30000
    assert receipt["worker_activation_attempts"] == 0 and receipt["artifact_root"] is None
    assert receipt["profile_status"] == "not_executed" and receipt["provider_code"] == "USER_NOT_LOGGED_IN"
    try:
        blocked_receipt("Jira", "ECHO-2675", "lookup", "raw credential text", started, observed_at=observed)
    except ValueError as error:
        assert str(error) == "source_access_receipt_invalid_input"
    else:
        raise AssertionError("unsafe provider detail must not enter the receipt")
    print("source_access_receipt self-test: passed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source")
    parser.add_argument("--work-item")
    parser.add_argument("--operation")
    parser.add_argument("--provider-code")
    parser.add_argument("--started-at")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    try:
        receipt = blocked_receipt(
            args.source or "", args.work_item or "", args.operation or "", args.provider_code or "",
            args.started_at or "",
        )
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps(receipt, sort_keys=True))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
