---

title: Build and Test
version: 0.5.1
status: Pilot
category: Validation
provider_independent: true
owner: Engineering
last_updated: 2026-08-25
---

# Build and Test

> Execute the repository's build, test, static-analysis, and smoke-validation commands and preserve objective evidence.

## Inputs

* Repository standards
* Changed files and acceptance criteria
* Risk-based validation plan

## Repository-Native Test Discovery

Before running validation, establish the repository's testing conventions from evidence in this order:

1. the nearest `AGENTS.md` and directory-local guidance;
2. the owning build definition and test target;
3. language manifests and checked-in test configuration;
4. one or two representative tests owned by the same component;
5. a compatible sibling component only when the owning area has no tests; and
6. repository scripts or CI definitions for the narrowest supported command.

Record the representative test paths, language and framework, owning target, and exact validation command. Prefer scoped
guidance and local tests when evidence conflicts. Do not add a test dependency when the repository already provides a
supported framework.

## Required Coverage and Evidence

For approved remediation, the Implementer adds missing regression assertions and the Tester checks coverage against
criteria and material behavior. Return runnable gaps through Coordinator to Implementer, Reviewer and Tester without
another approval; do not defer them to the user. A passing target is not proof that every required assertion exists.
Check downstream arguments and forbidden side effects; mocks must expose writes rather than silently return unchanged
data. Any source/test/fixture edit requires acceptance of the resulting candidate before final validation.
Feature Delivery uses `templates/validation_report.md` and `scripts/review_evidence.py --validation` to reconcile the
reviewed inventory, current candidate and execution evidence. Separate blocked local proof from deployment follow-up.

## Produces

* Commands executed
* Pass and failure results
* Test evidence
* Regression assessment
* Defects and residual risks

## Completion Criteria

Acceptance criteria have objective evidence, or missing evidence is documented with its impact.

## Safety

Never report validation from assumptions. Preserve failure output and distinguish unavailable tests from passing tests.
