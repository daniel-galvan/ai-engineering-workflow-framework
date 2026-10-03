---
title: Code Review Evidence
version: 0.1.0
status: Pilot
owner: Engineering
last_updated: <DATE-OF-CREATION>
depends_on:
  - ../contracts/code_review.md
---

# Code Review

Create `code_review.md` in the active run root. Replace instructions and empty cells with observed evidence.

## Scope

Record repository, branch, actual target/base and merge-base, HEAD, exact reviewed range, candidate fingerprint and
method (including intended worktree/untracked files), stacked dependencies, and local versus uploaded review state.

Disposition: accepted / changes_required / replanning_required / blocked

## Behavior Review

One row per material changed behavior; cross-check against the full candidate. Evidence must identify real paths or
current evidence IDs. Counterexample checks must record observations, not just future test plans.

| Behavior | Applicability evidence | Caller / producer | Consumer / contract | Lifecycle / invariant | Counterexample check / result | Regression evidence | Result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| | | | | | | | |

## Findings

For each finding record P0/P1/P2, exact location and introducing commit/hunk, changed behavior, reachable path, trigger,
violated contract, concrete impact, supporting evidence, repair, and discriminating regression. Otherwise state no
confirmed correctness findings and preserve limits below. Keep unrelated pre-existing defects and suggestions separate.

## Validation

Record applicable scenario checks or non-applicability reasons, commands/source comparisons, result, reviewed revision,
environment, what each check proves, and what remains unverified. Identify later Tester checks as deferred, not passed.

| Check | Result | Environment / revision | What it proves | Remaining limits |
| --- | --- | --- | --- | --- |
| | | | | |

## Reconciliation and Next Action

Recheck previous findings and the complete resulting diff after remediation. Reconcile active plans, decisions, tests,
and bundles; identify historical versions. State remaining findings, validation limits, owner, next action, and
readiness separately for source review, validation, and upload/release. Never claim remote delivery from local evidence.
