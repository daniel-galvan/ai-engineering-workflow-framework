#!/usr/bin/env python3
"""CLI for deterministic framework, artifact, and terminal handoff validation."""

from __future__ import annotations

import argparse
from pathlib import Path

if __package__:
    from .validation.common import ROOT, fail
    from .validation.finalization import validate_normalized_evidence, validate_sentry_artifacts
    from .validation.library import validate_library
    from .validation.playbooks import technical_spike_report_errors
    from .validation.provider_policy import _plugin_version_refresh_error
    from .validation.self_tests import self_test_reasoning_records
    from .validation.work_records import validate_work_record
else:
    from validation.common import ROOT, fail
    from validation.finalization import validate_normalized_evidence, validate_sentry_artifacts
    from validation.library import validate_library
    from validation.playbooks import technical_spike_report_errors
    from validation.provider_policy import _plugin_version_refresh_error
    from validation.self_tests import self_test_reasoning_records
    from validation.work_records import validate_work_record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("emit-handoff", "allow-unreleased", "self-test"):
        parser.add_argument("--" + flag, action="store_true")
    for flag in ("sentry-artifacts", "normalized-evidence", "technical-spike-report",
                 "technical-spike-input-manifest"):
        parser.add_argument("--" + flag, type=lambda value: Path(value).resolve())
    for flag in ("technical-spike-primary-goal", "technical-spike-profile",
                 "technical-spike-workflow-result", "technical-spike-budget-status"):
        parser.add_argument("--" + flag)
    parser.add_argument("--technical-spike-expected-revision", action="append", default=[])
    parser.add_argument("work_records", nargs="*", metavar="WORK_RECORD")
    options = parser.parse_intermixed_args(argv)
    emit_handoff = options.emit_handoff
    allow_unreleased = options.allow_unreleased
    artifact_root = options.sentry_artifacts
    normalized_evidence = options.normalized_evidence
    technical_spike_report = options.technical_spike_report
    technical_spike_primary_goal = options.technical_spike_primary_goal
    technical_spike_profile = options.technical_spike_profile
    technical_spike_workflow_result = options.technical_spike_workflow_result
    technical_spike_budget_status = options.technical_spike_budget_status
    technical_spike_input_manifest = options.technical_spike_input_manifest
    technical_spike_expected_revisions = options.technical_spike_expected_revision
    arguments = options.work_records
    validate_library()
    if emit_handoff and len(arguments) != 1:
        fail("--emit-handoff requires exactly one terminal work record")
    if options.self_test:
        self_test_reasoning_records()
    if artifact_root:
        validate_sentry_artifacts(artifact_root, allow_unreleased=allow_unreleased)
    if normalized_evidence:
        validate_normalized_evidence(normalized_evidence)
    if technical_spike_report:
        missing = [
            name for name, value in (
                ("--technical-spike-primary-goal", technical_spike_primary_goal),
                ("--technical-spike-profile", technical_spike_profile),
                ("--technical-spike-workflow-result", technical_spike_workflow_result),
            ) if not value
        ]
        if missing:
            fail("technical spike report validation requires: " + ", ".join(missing))
        report_errors = technical_spike_report_errors(
            technical_spike_report.read_text() if technical_spike_report.is_file() else "",
            technical_spike_primary_goal,
            technical_spike_profile,
            technical_spike_workflow_result,
            technical_spike_budget_status,
            technical_spike_input_manifest,
            tuple(technical_spike_expected_revisions),
        )
        if report_errors:
            fail("\n".join(report_errors))
        if arguments:
            fail("technical spike report validation cannot be combined with a work record")
    handoffs = [
        validate_work_record(Path(argument).resolve(), require_terminal=not allow_unreleased, allow_unreleased=allow_unreleased)
        for argument in arguments
    ]
    for work_record in sorted(ROOT.glob(".thoughts/*/work_record.md")):
        validate_work_record(work_record, allow_unreleased=allow_unreleased)
    plugin_refresh_error = _plugin_version_refresh_error()
    if plugin_refresh_error:
        fail(plugin_refresh_error)

    print("Workflow-framework validation: passed")
    if emit_handoff:
        print(handoffs[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
