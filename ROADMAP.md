# Roadmap

Current behavior and exercise status live in [README.md](README.md), [PLAYBOOK_CATALOG.md](PLAYBOOK_CATALOG.md), and the
playbooks. This file lists only planned evolution.

## Next validation

- Evaluate the current prompt and control revisions with the current
  [Codex role-policy baseline](providers/codex/model_effort_policy.md) on comparable real runs.
- Measure control fidelity, authoritative-input consumption, human intervention, elapsed time, and wait time.
- Exercise more Vulnerability Investigation Deep planning and remediation scenarios.
- Exercise Technical Spike `execute_spike` and `review_spike` with real bounded Jira work items.
- Reduce Deep elapsed and wait time without skipping required workers, gates, or fan-in.
- Improve remediation completion reliability across all four delivery playbooks.
- Perform a cross-playbook failure audit after collecting comparable current-baseline run evidence.

## Work-record validation

Exercise compact records and their linked operational snapshots on new Standard runs across all playbooks.
Verify continuation, archive/transfer, and missing or conflicting receipt failures on real runs; retain historical
records under the legacy reader. Current format and responsibilities are documented in
[OPERATING_GUIDE.md](OPERATING_GUIDE.md).

## Expansion freeze

After comparable pilot evidence, declare dependency compatibility ranges and validate them against document revisions.
Keep cross-revision compatibility undeclared until supported versions have evidence; dependency paths and matching
version inventories alone do not establish compatibility.

Extend the existing approval/re-entry and finalization tests to cover the complete workflow state machine: recovery
from awaiting input or blocked, approved implementation, review corrections, validation failures, handoff, and terminal
completion. Preserve the distinction between lifecycle (`planning` / `remediation`) and workflow state; use the
[canonical state machine](contracts/workflow_execution.md#workflow-state-machine) rather than introducing another one.

Do not add more playbooks or execution abstractions during the current pilot. First exercise Technical Spike and
validate the four delivery playbooks through remediation, Code Review, validation, and handoff; simplify any rules that
real runs prove unnecessary.

After that, reconsider scenario coverage and framework evolution only when a validated gap cannot be expressed by the
existing contract, roles, skills, stages, gates, and artifacts.
