---
title: Evidence-Driven Code Review Contract
version: 0.1.1
status: Pilot
provider_independent: true
owner: Engineering
last_updated: 2026-10-06
---

# Evidence-Driven Code Review Contract

> Investigate broadly, trace actual behavior, challenge assumptions, and report narrowly.

This contract applies to independent delivery review. Feature Delivery also uses its applicability check during
impact analysis and design. It strengthens the existing review stage; it adds no worker or human approval round.
MUST and MUST NOT are normative. The Reviewer remains read-only; the Implementer owns authorized remediation.
When continuing an older approved plan, reconcile these evidence fields using existing verified research plus bounded
checks of missing contracts. Do not restart triage, a Spike, or the planning graph merely to adopt this record format.

## Requirement applicability

Apply [scenario relevance and proportionality](workflow_execution.md#scenario-relevance-and-proportionality) to
proposed edge cases and races. Verify practical exposure, concrete impact, existing handling, and the cost of stronger
handling before accepting added scope. Challenge unnecessary mechanisms even when they appear in an approved plan.
Inspect the closest current repository pattern before accepting a custom type, schema, recovery path, or test facility.

Separate the requested outcome, the chosen engineering mechanism, and any inferred safety or policy rule. A conditional
approval preserves its condition; a feature flag or business setting alone does not prove that a specific mutation
satisfies it. A dependency needed by a proposed mechanism does not prove that the mechanism is required.

For every material proposed behavior, record its authoritative criterion or decision, applicable trigger, evidence,
and a bounded counterexample check in the plan's Behavior Applicability table. Inspect existing negative tests,
unchanged payload builders, and producer/consumer contracts that could contradict the proposal. Record the observed
result, not just a proposed test. Source comparison can suffice during read-only planning.

Classify the behavior as `required`, `conditional`, `deferred`, `excluded`, or `unverified`. Required and conditional
actions need applicability evidence. Do not implement an unverified policy extension as though it were approved.
A deliberate approved behavior change may differ from baseline; name the exact decision and feasible future contract
rather than treating baseline as immutable. Escalate only the unresolved material policy choice after bounded checks.

## Review boundary and identity

Establish the actual repository, branch, HEAD, target/base revision, merge-base, and review range. Do not assume the
target branch name. Record stacked dependencies and both individual-commit and combined behavior when applicable.
Distinguish committed changes, staged/unstaged edits, untracked candidate files, remote refs, and uploaded review state.
An empty committed range is not an empty candidate when the worktree contains intended changes.

Identify the reviewed candidate with the exact base/HEAD and a reproducible diff/content fingerprint including intended
untracked files. Reconfirm it after fixes. If a base or candidate cannot be established, return `blocked` with the
missing evidence; do not invent the range. Local fixes do not prove an uploaded review contains them.

The candidate bounds findings, not investigation. Inspect unchanged code to establish callers, consumers, contracts,
and preserved behavior. Report candidate-caused, worsened, or newly exposed failures, including interactions with
unchanged code. Record unrelated pre-existing issues separately without expanding remediation scope.

## Behavior review

Use [the Code Review template](../templates/code_review.md). Inventory each material changed behavior, grouping related
symbols only when their callers, contracts, and lifecycle are the same. Cross-check coverage with the full diff,
including configuration, fixtures, migrations, tests, and operational commands. Plan conformance is necessary but not
sufficient: independently challenge the assumptions of the approved plan and the expectations encoded by new tests.

Each Behavior Review row MUST identify applicability evidence, actual caller/producer, consumer/payload contract,
lifecycle/invariant, counterexample check and observed result, and regression evidence. State whether it is `verified`,
`defect`, or `unverified`. Bare claims such as "all paths reviewed" or "tests pass" are not evidence.

For new state transitions, trace initiation, persisted state, actual external submission/event and its payload,
completion/callback, retry/partial failure, and user-visible recovery. Atomic persistence alone does not establish a
complete workflow. A pending/queued state needs a supported path to its promised work and completion, or an explicit
recoverable failure contract. Inspect the actual serialized payload, not only an input type or feature setting.

Consider the following scenario families for each material flow; record applicable checks and results, or a concrete
non-applicability reason. Do not execute irrelevant technology checklists or repeat unchanged checks:

- successful execution, no-op/reversal, missing/invalid/boundary input;
- existing producers/consumers, legacy compatibility, unavailable/deleted/stale state;
- duplicate/repeat execution, retry after success, partial failure and process-loss boundaries;
- concurrent writers, ordering, transaction and callback correlation;
- authorization, configuration/dependency failure, cleanup and recovery; and
- modified operational commands: real route, prerequisites, fixture, repeatability and safe cleanup.

## Finding validity

Every correctness finding MUST establish this causal chain with exact source/test references:

`Changed behavior → Reachable path → Trigger → Violated contract → Concrete impact`

Record severity, location, introducing commit or worktree hunk, recommended repair, and the discriminating regression.
Use P0 for critical impact, P1 for serious merge-blocking failures, and P2 for significant correctness/reliability risk.
Do not inflate severity. Style preferences, speculative concerns, and a missing test without a credible failure are
not correctness findings. Keep lower-priority suggestions outside the blocking findings.

## Validation and disposition

Record each check, result, environment/candidate revision, what it proves, and remaining limits. Use the narrowest
meaningful check first, then relevant focused, integration, end-to-end, or broader validation. Test presence,
compilation, or a passing happy path does not prove the requirement or lifecycle is correct. Check whether the
regression's expected result follows from an independently established contract rather than copying the implementation.

An `accepted` source review has no unresolved `defect` or acceptance-critical `unverified` Behavior Review row. Use
`changes_required` for in-scope repairs, `replanning_required` for an invalidated scope/design, and `blocked` for an
evidence/environment limit. Tests owned by the subsequent Tester stage may be `deferred` with a reason; source-review
acceptance does not establish validation, clean-state, upload, release, or deployment readiness.

Return repairs to the Implementer, then recheck the affected paths and interactions and rescan the complete resulting
diff for omissions or new regressions. Continue for unresolved findings; do not add ceremonial iterations after
acceptance or reconstruct unchanged discovery from scratch. Bind the final review to the resulting candidate, not a
prior revision or historical green receipt.

Before handoff, reconcile active plans, decisions, validation claims, and review bundles with the remediation. Preserve
historical artifacts as historical; do not silently reintroduce a rejected assumption through an old patch or plan.
Do not commit, push, upload, submit, resolve remote discussions, change external systems, or rewrite/discard user work
without the corresponding authorization. For Gerrit, preserve Change-Ids and distinguish local and uploaded patch sets.

## Evidence gate

Before accepting Feature Delivery review, run:

```text
python3 <framework-root>/scripts/review_evidence.py --review <run-root>/code_review.md --require-accepted
```

The same script checks a ready implementation plan with `--plan <run-root>/implementation_plan.md`. Finalization
rechecks these records. This is a structural evidence gate, not an automatic proof of semantic correctness; the
independent Reviewer must verify the references, inventory completeness, and actual observed behavior.
