#!/usr/bin/env python3
"""CLI for deterministic framework, artifact, and terminal handoff validation."""

from __future__ import annotations

from pathlib import Path
import sys

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
    argv = list(sys.argv[1:] if argv is None else argv)
    validate_library()
    emit_handoff = "--emit-handoff" in argv
    allow_unreleased = "--allow-unreleased" in argv
    raw_arguments = list(argv)
    artifact_root = None
    normalized_evidence = None
    technical_spike_report = None
    technical_spike_primary_goal = None
    technical_spike_profile = None
    technical_spike_workflow_result = None
    technical_spike_budget_status = None
    technical_spike_input_manifest = None
    technical_spike_expected_revisions: list[str] = []
    if "--sentry-artifacts" in raw_arguments:
        index = raw_arguments.index("--sentry-artifacts")
        if index + 1 >= len(raw_arguments):
            fail("--sentry-artifacts requires one artifact-root path")
        artifact_root = Path(raw_arguments[index + 1]).resolve()
        del raw_arguments[index:index + 2]
    if "--normalized-evidence" in raw_arguments:
        index = raw_arguments.index("--normalized-evidence")
        if index + 1 >= len(raw_arguments):
            fail("--normalized-evidence requires one artifact path")
        normalized_evidence = Path(raw_arguments[index + 1]).resolve()
        del raw_arguments[index:index + 2]
    for flag, name in (
        ("--technical-spike-report", "technical_spike_report"),
        ("--technical-spike-primary-goal", "technical_spike_primary_goal"),
        ("--technical-spike-profile", "technical_spike_profile"),
        ("--technical-spike-workflow-result", "technical_spike_workflow_result"),
        ("--technical-spike-budget-status", "technical_spike_budget_status"),
        ("--technical-spike-input-manifest", "technical_spike_input_manifest"),
    ):
        if flag in raw_arguments:
            index = raw_arguments.index(flag)
            if index + 1 >= len(raw_arguments):
                fail(f"{flag} requires one value")
            value = raw_arguments[index + 1]
            if name == "technical_spike_report":
                technical_spike_report = Path(value).resolve()
            elif name == "technical_spike_primary_goal":
                technical_spike_primary_goal = value
            elif name == "technical_spike_profile":
                technical_spike_profile = value
            elif name == "technical_spike_workflow_result":
                technical_spike_workflow_result = value
            elif name == "technical_spike_budget_status":
                technical_spike_budget_status = value
            else:
                technical_spike_input_manifest = Path(value).resolve()
            del raw_arguments[index:index + 2]
    while "--technical-spike-expected-revision" in raw_arguments:
        index = raw_arguments.index("--technical-spike-expected-revision")
        if index + 1 >= len(raw_arguments):
            fail("--technical-spike-expected-revision requires one value")
        technical_spike_expected_revisions.append(raw_arguments[index + 1])
        del raw_arguments[index:index + 2]
    arguments = [value for value in raw_arguments if value not in {"--self-test", "--emit-handoff", "--allow-unreleased"}]
    if emit_handoff and len(arguments) != 1:
        fail("--emit-handoff requires exactly one terminal work record")
    if "--self-test" in argv:
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
