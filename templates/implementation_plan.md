---
title: Engineering Implementation Plan
version: 0.4.16
status: Pilot
owner: Engineering
last_updated: <DATE-OF-CREATION>
depends_on:
  - ../contracts/workflow_execution.md
  - ../contracts/claims.md
  - ./work_record.md
---

# Engineering Implementation Plan

> Durable, approval-gated instructions for implementing and validating a
> planned engineering change.

Create this file at:

```text
.thoughts/<WORK-ITEM-ID>/implementation_plan.md
```

The plan is produced during planning and is not authorization to change source code or external systems. The work record
must link to this file. A later session must be able to execute the approved plan without reconstructing the
investigation from chat history.

Uncompleted dependency adaptation, environment setup, test work, operational
configuration, rollout, and rollback work belongs in this plan when a feasible
sequence exists. Those items are not planning blockers merely because they
remain to be executed.

The plan does not authorize implementation. A remediation run must create the
Delivery Activation Barrier, activate the delegated Implementer, and register
the Reviewer, Tester, and Documenter before the first source change.

When this plan reaches `ready_for_implementation`, create the companion `implementation_handoff.md` beside it from
[`implementation_handoff.md`](implementation_handoff.md) only if implementation will happen in another session or
environment, or the user explicitly requests a self-contained transfer file. For same-session implementation, mark the
handoff `Not required`. The handoff is self-contained, uses repository identities and revisions instead of
source-environment paths, and remains non-executable until its approval status is explicit.

# Metadata

| Field | Value |
| --- | --- |
| Work item | |
| Change set ID | One shared remediation identity; list all covered findings or work items |
| Playbook | |
| Requested profile | |
| Executed profile | |
| Lifecycle | |
| Execution repository | |
| Affected repositories | |
| Target revision | |
| Plan status | Draft / Ready for implementation / Approved / Superseded |
| Approval reference | |
| Required tools | Exact tool, version, source, executable path or approved isolated-bootstrap method |
| Portable handoff | `implementation_handoff.md` / Not created / Not required |
| Handoff reason | Different session or environment / Explicit request / Not applicable |
| Last updated | |

# Portable Handoff

Record whether the self-contained `implementation_handoff.md` was generated, its approval status, and why it is needed.
Do not copy framework-relative links or source-machine paths into the portable handoff. The handoff must preserve the
approved scope, target repository identity and revision, evidence summary, exact changes, validation, stop conditions,
rollback, and reporting requirements.

# 1. Scope and Baseline

Record the verified issue behavior, code repository and revision, affected component, event or request topology,
in-scope changes, and explicit exclusions.

# 2. Root Cause and Behavior Contract

Record the confirmed cause or best-supported hypothesis, evidence references, current behavior, expected behavior,
residual uncertainty, and confidence. Preserve the evidence, claim, and decision IDs that support the plan.

# Interface Contract

Complete this table when the change crosses an API, event, payload, schema, or other repository boundary. Copy the exact
contract from the Fix Design result. Use `Not applicable` only when `interface_change` is `false`.

| Surface | Request shape | Response shape | Absence semantics | Compatibility / precedence | Rollout |
| --- | --- | --- | --- | --- | --- |
| | | | | | |

# 3. Source Change Plan

| File or symbol | Intended change | Compatibility constraints | Excluded changes |
| --- | --- | --- | --- |
| | | | |

Keep the change minimal. Record import, dependency, configuration, schema, contract, or rollout implications when
applicable. Every material action must retain its originating claim and decision references.

# 4. Test and Validation Plan

| Level | Test or check | Expected result | Owner | Availability / result |
| --- | --- | --- | --- | --- |
| Regression | | | Implementer / Tester | |
| Focused suite | | | Tester | |
| Broader suite | | | Tester | |
| Originating security rule or scanner rerun | | | Tester | |
| Static or operational checks | | | Reviewer / Tester | |
| Post-release observation | | | Owner | |

State the failure reproduction, regression scenario, fixtures or inputs, and any unavailable or inconclusive validation.
Do not convert an unavailable check into a success claim. Planning normally designs these checks without running them;
record any decision-changing focused check already run as existing evidence.

# 5. Ordered Execution Plan

| Step | Activity | Owner | Dependency or approval gate | Status |
| --- | --- | --- | --- | --- |
| 1 | Reconfirm repository, revision, scope, and worktree state | Implementer | Approved plan and implementation gate | Pending |
| 2 | Add or update a focused regression that reproduces the verified failure | Implementer | Step 1 complete | Pending |
| 3 | Apply the smallest source change described above | Implementer | Step 2 reproduces the failure, or records why it cannot | Pending |
| 4 | Run the focused regression and relevant focused suite | Tester | Step 3 complete | Pending |
| 5 | Strict Code Review: happy paths, alternate and edge paths, callers, compatibility, scope, and coverage | Reviewer | Step 4 complete | Pending |
| 6 | Run broader validation and preserve results | Tester | Review findings resolved or accepted | Pending |
| 7 | Prepare rollout, rollback, monitoring, and post-release checks | Orchestrator / Documenter | Validation result recorded | Pending |
| 8 | Record ownership, residual risk, next action, and handoff | Documenter | Stabilization evidence complete | Pending |

# 6. Risk and Operations

| Risk or impact | Mitigation | Rollback action | Monitoring or follow-up | Owner |
| --- | --- | --- | --- | --- |
| | | | | |

# 7. Completion Criteria

- [ ] Approved scope and target revision reconfirmed.
- [ ] Source and regression-test changes match this plan.
- [ ] Diff and compatibility review completed.
- [ ] Applicable validation results recorded as pass, fail, skipped, unavailable, or inconclusive.
- [ ] Rollout, rollback, monitoring, and post-release checks identified.
- [ ] Residual risks, blockers, owner, and next action recorded in the work record.
- [ ] Work-record link and implementation handoff are complete.

# Open Questions and Decisions

Record unresolved questions, decisions required before implementation, and any plan revision history.
