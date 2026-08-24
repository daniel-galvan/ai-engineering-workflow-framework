---
title: Portable Implementation Handoff
version: 0.3.2
status: Pilot
owner: Engineering
last_updated: <DATE-OF-CREATION>
depends_on:
  - ../contracts/portable_implementation_handoff.md
---

# Portable Implementation Handoff

> Self-contained instructions for executing an approved implementation plan in another session or environment.

This file is derived from a completed planning artifact. It is the execution source for the receiving session, but it
does not replace the source plan or grant approval. Do not change source when `Handoff status` is `Approval pending`.

This document is self-contained. It must not depend on chat history, source-machine paths, or unavailable planning
documents.

Create this handoff only when implementation will happen in another session or environment, or when the user explicitly
requests a self-contained transfer file. Same-session implementation does not require a handoff.

## Start Here

From a session already started at the root of the target Git repository, run:

```text
Execute the approved implementation handoff at:
<PATH>/implementation_handoff.md

You are already at the root of the target repository. Follow the handoff exactly.
```

## Execution Metadata

| Field | Value |
| --- | --- |
| Work item | |
| Source system | |
| Handoff status | Draft / Approval pending / Approved / Superseded / Complete |
| Approval reference | |
| Source planning run | |
| Target repository identity | |
| Target project or component path | |
| Target branch | |
| Additional repositories | |
| Receiving environment | |
| Local target path | Resolve in the receiving environment |
| Generated | |

## Receiving-Session Instructions

Start the session at the root of the target Git repository and read this file completely before changing anything. For a
monorepo, keep the session at the repository root so sibling projects remain available.

1. Verify the repository identity, remote, current default branch, current revision, and worktree state.
2. Start from the current default branch and record its current revision. Do not check out a historical production or
   planning revision unless the user explicitly requests that change.
3. Verify the repository-native runtime, dependency setup, services, credentials, fixtures, and validation commands.
   Prefer a currently valid repository entrypoint, such as a script or Makefile target, over direct package-manager
   commands. Do not use a repository target that passes options rejected by the installed runtime.
4. Confirm that `Handoff status` is `Approved`, or obtain and record explicit approval in this session before source
   changes; the approval must cover the scope below.
5. Execute the ordered plan without requesting approval after each individual implementation step.

If the target repository, default branch, approved scope, or required environment cannot be verified, stop before source
changes and report the exact mismatch. Do not infer that a different checkout or dependency state is equivalent.

## Scope Boundaries

### Objective

<OBJECTIVE>

### Approved changes

- <FILE, SYMBOL, OR CONFIGURATION CHANGE>

### Do not change

- <EXCLUDED FILE, REPOSITORY, BEHAVIOR, OR EXTERNAL SYSTEM>

## Evidence, Claims, and Decisions

Summarize the evidence that supports the implementation decision. Include source, revision, confidence, uncertainty, and
the decision or approval that authorizes each material action.

| ID | Evidence or claim | Confidence / status | Decision or action supported |
| --- | --- | --- | --- |
| | | | |

## Environment Preflight

| Check | Required condition | Command or evidence | Result |
| --- | --- | --- | --- |
| Repository root | Expected repository root and remote are checked out | | Pending |
| Target project or component | The affected project or component path exists within the repository | | Pending |
| Default branch | Current default branch is checked out; record its starting revision | | Pending |
| Starting revision | Current `HEAD` is recorded for the implementation run; no historical revision is substituted | | Pending |
| Test runtime | The repository-native runtime used by the test entrypoint is available | | Pending |
| Dependencies | Required dependencies are available without unapproved source changes | | Pending |
| Services and fixtures | Required local services, data, or fixtures are available | | Pending |
| Project test entrypoint | The repository-native test or build entrypoints used below are available | | Pending |
| Optional validation tools | Tools required by listed lint, format, or static checks are available | | Pending |

If a package-manager executable is broken but the repository-native test entrypoint remains usable, do not treat the
package-manager failure as a blocker for implementation or tests. Record the affected optional checks as unavailable.

## Ordered Execution Plan

One implementation approval covers all in-scope steps below. Continue through the complete sequence unless a defined
stop condition is reached.

| Step | Activity | Owner | Dependency | Status |
| --- | --- | --- | --- | --- |
| 1 | Reconfirm repository root, project path, default branch, starting revision, scope, and worktree | Implementer | Approved handoff and preflight | Pending |
| 2 | Apply the approved source change | Implementer | Step 1 complete | Pending |
| 3 | Add or update focused regression coverage | Implementer | Step 2 complete | Pending |
| 4 | Perform strict Code Review across happy paths, alternate paths, edge cases, callers, compatibility, scope, and coverage | Reviewer | Steps 2–3 complete | Pending |
| 5 | Resolve in-scope findings and repeat review when required | Implementer / Reviewer | Review disposition | Pending |
| 6 | Run the validation ladder and preserve results | Tester | Review accepted | Pending |
| 7 | Record residual risk, rollback, monitoring, and handoff | Documenter | Validation recorded | Pending |

## Source Change Details

| File or symbol | Change | Compatibility constraint | Excluded change |
| --- | --- | --- | --- |
| | | | |

## Strict Code Review Requirements

The Reviewer must inspect and record the result for each applicable dimension:

- intended happy paths and existing behavior that must remain unchanged;
- alternate, error, empty, missing, null, boundary, and other relevant edge paths;
- affected callers, producers, consumers, contracts, persistence, and compatibility boundaries;
- regression coverage, including whether the tests would fail for the original defect where practical; and
- scope, unintended files, security or operational impact, rollback, and remaining validation gaps.

A happy-path-only review is incomplete. Record any dimension that could not be verified as an explicit review gap.

## Validation and Review

The commands in this table are authoritative for this handoff. Do not infer replacement commands from a Makefile,
package manager, earlier plan, or earlier handoff version. Verify command options against the installed runtime before
execution and record any unavailable or obsolete command separately.

| Level | Command or check | Expected result | Result |
| --- | --- | --- | --- |
| Regression | | | Pending |
| Focused suite | | | Pending |
| Broader suite | | | Pending |
| Static or operational checks | | | Pending |
| Post-release observation | | | Pending |

Code Review is a required step, not only a final summary. Findings within the approved scope return to implementation
and review without requiring a new approval. Do not claim independent review unless a separate reviewer or review pass
actually performed it. The validation commands in this handoff are authoritative; do not infer replacement commands from
a Makefile or an earlier handoff version. Record any unavailable or obsolete command separately.

## Stop Conditions

Stop before the affected action and report the exact reason when:

- approval is missing or does not cover the proposed change;
- repository identity, default branch, starting revision, scope, or ownership is materially different;
- new evidence invalidates the approved design;
- a destructive, external, irreversible, or security-sensitive action is required but not approved;
- required dependencies, permissions, services, fixtures, review, or validation are unavailable; or
- the implementation would require an out-of-scope change.

Do not hide a skipped, unavailable, failed, or inconclusive check behind a successful handoff.

## Rollback and Operations

| Risk or impact | Mitigation | Rollback action | Monitoring or follow-up | Owner |
| --- | --- | --- | --- | --- |
| | | | | |

## Final Report

Return a concise report containing:

- changes made and files modified;
- strict Code Review dimensions covered, findings, gaps, and dispositions;
- every validation command and its result;
- unavailable or inconclusive checks;
- remaining risks, rollback, monitoring, and release requirements; and
- the exact next action or `Nothing technical.`
