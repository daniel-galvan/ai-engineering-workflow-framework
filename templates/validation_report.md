---
title: Feature Delivery Validation Evidence
version: 0.5.20
status: Pilot
owner: Engineering
last_updated: 2026-10-08
depends_on:
  - ../contracts/code_review.md
---

# Validation Report

Create `validation_report.md` in the active remediation run root. Replace all placeholders and empty rows.

## Candidate

Use the same exact fields in `code_review.md`. Base is the verified target/base commit. Include every intended new
untracked source/test/config file as a repository-relative JSON path; exclude unrelated user files and run artifacts.
The fingerprint includes base, HEAD, tracked staged/unstaged changes, and listed untracked contents. Generate it with:

```text
python3 <framework-root>/scripts/review_evidence.py --fingerprint --repository <repo> --base <base> --untracked <new-file> ...
```

Repository: <ABSOLUTE-EXECUTION-REPOSITORY>
Base revision: <VERIFIED-BASE-COMMIT>
Candidate SHA256: <64-LOWERCASE-HEX-DIGEST>
Untracked candidate files: []

## Behavior Coverage

Reconcile every approved criterion with the complete reviewed behavior inventory; use the exact Behavior names from
code_review.md. Group criteria only when the same check proves them. Name each criterion in the Test / check cell.
Record exact test/assertion paths, commands and execution evidence; identify source-only proof explicitly.
Results: pass, fail, blocked, not_applicable. A runnable missing assertion returns to Implementer; it cannot
be deferred.
For pass, state what it proves and `No remaining local gap` when appropriate. Other rows require a concrete reason,
impact, owner and next action. not_applicable requires an authority-backed reason. Never infer execution from presence
or a suite-level pass. An environment-blocked terminal report may be partial; it cannot support solved
engineering value.

| Criterion / behavior | Test / check | Result | Evidence / environment | Gap / reason | Owner / next action |
| --- | --- | --- | --- | --- | --- |
| | | | | | |

## Affected Tests

One row per behavior and affected target, using the exact Behavior Review names. Discover targets from changed
contracts, actual callers, existing tests/SQL mocks/fixtures, owning build definitions and repository-native dependency
queries or CI selection. Unchanged consumers and tests remain in scope. Include the discovery command/source evidence;
file location alone cannot justify excluding a target. Use a concrete source/manual check for documentation-only work.
Reviewer must independently verify completeness and each exclusion, recording `Reviewer:` with the traced evidence.
For excluded targets, record non-impact proof and `Not executed: reviewed exclusion` as execution evidence. A source
review may use deferred with its planned command and Tester owner; final validation cannot defer runnable work.
Results: pass, fail, blocked, deferred, excluded. Pass requires exact execution receipt; compilation is not execution.

| Changed behavior / contract | Caller / existing tests | Test target / command | Discovery evidence | Result | Execution evidence | Reason / reviewer |
| --- | --- | --- | --- | --- | --- | --- |
| | | | | | | |

## Release Follow-up

List only concrete deployment checks: boundary/dependency, environment, owner, next action and proof beyond completed
local checks. Use the table below or replace the entire section body with `No release checks required.`. Do not repeat
passed tests as vague product checks.

| Check | Environment / dependency | Additional proof | Owner / next action |
| --- | --- | --- | --- |
| | | | |

## Evidence Gate

Validate before Documenter (add --require-solved only for solved engineering value):

```text
python3 <framework-root>/scripts/review_evidence.py --validation <run-root>/validation_report.md --review-report <run-root>/code_review.md --repository <repo>
```

Any source, test or fixture edit invalidates these receipts. Return to Implementer/Reviewer/Tester and recompute the
candidate. After CI repairs, record the failed build/test receipt and repaired expectations; refresh active status,
commit/upload identity and next actions. A local rerun does not prove remote CI is green. Preserve historical reports
as history; update active plan/test status and CURRENT.md from current proof.
