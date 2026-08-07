---
title: Engineering Implementation Plan
version: 0.1
status: Pilot
owner: Engineering
last_updated: YYYY-MM-DD
depends_on:
  - ../contracts/workflow_execution.md
  - ./work_record.md
---

# Engineering Implementation Plan

> Durable, approval-gated instructions for implementing and validating a
> planned engineering change.

Create this file at:

```text
.thoughts/<WORK-ITEM-ID>/implementation_plan.md
```

The plan is produced during planning and is not authorization to change source
code or external systems. The work record must link to this file. A later
session must be able to execute the approved plan without reconstructing the
investigation from chat history.

# Metadata

| Field | Value |
| --- | --- |
| Work item | |
| Playbook | |
| Requested profile | |
| Executed profile | |
| Lifecycle | |
| Target repository | |
| Target revision | |
| Plan status | Draft / Ready for implementation / Approved / Superseded |
| Approval reference | |
| Last updated | |

# 1. Scope and Baseline

Record the verified issue behavior, target repository and revision, affected
component, event or request topology, in-scope changes, and explicit
exclusions.

# 2. Root Cause and Behavior Contract

Record the confirmed cause or best-supported hypothesis, evidence references,
current behavior, expected behavior, residual uncertainty, and confidence.

# 3. Source Change Plan

| File or symbol | Intended change | Compatibility constraints | Excluded changes |
| --- | --- | --- | --- |
| | | | |

Keep the change minimal. Record import, dependency, configuration, schema,
contract, or rollout implications when applicable.

# 4. Test and Validation Plan

| Level | Test or check | Expected result | Owner | Availability / result |
| --- | --- | --- | --- | --- |
| Regression | | | Implementer / Tester | |
| Focused suite | | | Tester | |
| Broader suite | | | Tester | |
| Originating security rule or scanner rerun | | | Tester | |
| Static or operational checks | | | Reviewer / Tester | |
| Post-release observation | | | Owner | |

State the failure reproduction, regression scenario, fixtures or inputs, and
any unavailable or inconclusive validation. Do not convert an unavailable
check into a success claim.

# 5. Ordered Execution Plan

| Step | Activity | Owner | Dependency or approval gate | Status |
| --- | --- | --- | --- | --- |
| 1 | Reconfirm repository, revision, scope, and worktree state | Implementer | Approved plan and implementation gate | Pending |
| 2 | Apply the smallest source change described above | Implementer | Step 1 complete | Pending |
| 3 | Add or update focused regression coverage | Implementer | Step 2 complete | Pending |
| 4 | Code Review: diff, scope, compatibility, and coverage | Reviewer | Steps 2–3 complete | Pending |
| 5 | Run the validation ladder and preserve results | Tester | Review findings resolved or accepted | Pending |
| 6 | Prepare rollout, rollback, monitoring, and post-release checks | Orchestrator / Documenter | Validation result recorded | Pending |
| 7 | Record ownership, residual risk, next action, and handoff | Documenter | Stabilization evidence complete | Pending |

# 6. Risk and Operations

| Risk or impact | Mitigation | Rollback action | Monitoring or follow-up | Owner |
| --- | --- | --- | --- | --- |
| | | | | |

# 7. Completion Criteria

- [ ] Approved scope and target revision reconfirmed.
- [ ] Source and regression-test changes match this plan.
- [ ] Diff and compatibility review completed.
- [ ] Applicable validation results recorded as pass, fail, skipped,
      unavailable, or inconclusive.
- [ ] Rollout, rollback, monitoring, and post-release checks identified.
- [ ] Residual risks, blockers, owner, and next action recorded in the work
      record.
- [ ] Work-record link and implementation handoff are complete.

# Open Questions and Decisions

Record unresolved questions, decisions required before implementation, and
any plan revision history.
