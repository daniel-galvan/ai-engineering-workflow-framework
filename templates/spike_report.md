---
title: Technical Spike Report
version: 0.5.4
status: Pilot
owner: Engineering
last_updated: <DATE-OF-CREATION>
depends_on:
  - ../contracts/claims.md
  - ./work_record.md
---

# Technical Spike Report

Create this file at `.thoughts/<WORK-ITEM-ID>/spike_report.md`. Keep it bounded to the declared question and evidence
budget. It is a learning artifact, not an implementation plan or authorization to change production systems.

## Metadata

| Field | Value |
| --- | --- |
| Work item | |
| Objective | `execute_spike` / `review_spike` |
| Primary question | |
| Assessment criteria or control domains | None declared / semicolon-separated criteria or control domains |
| Timebox or evidence budget | |
| Success criterion | |
| Execution profile | `standard` / `deep` |
| Repositories and revisions | |
| Review target | Path or URL / Not applicable |
| Comparison reference | Path or URL / Not applicable |
| Last updated | |

For duration-based runs, record the numeric prepared timebox or a bounded numeric evidence count (for example,
`35 minutes; within_budget`), not only a profile name or completion status. The finalizer supplies the prepared numeric
timebox when `run_budget.json` declares one.

Separate multiple assessment criteria or control domains with semicolons in this Metadata field. Commas inside a
criterion or domain name are content and must be preserved.

## Scope and Non-goals

State what was investigated or reviewed and what was intentionally excluded.

## Method and Evidence

| Evidence ID | Method or source | Observation | Status | Limitation |
| --- | --- | --- | --- | --- |
| | | | Verified / Inferred / Contradicted / Unknown | |

## Direct Evidence

Keep final report independently usable. Cite direct repository, work-item, document, experiment, or runtime evidence;
use an exact file/line, URL or work-item identifier, runtime artifact, or command. Do not use globs, broad directory
labels, or a search name without the location or command that can be independently checked. Record an exact revision
or version; `current`, `latest`, `HEAD`, and working-tree labels are not sufficient by themselves.
For a new current-run Spike, every external document URL or stable locator in an evidence source must be declared in
`run_inputs.json`; a linked historical document is not current-run evidence by discovery alone. Do not cite memory or
archived `.thoughts/.../runs/` material.

| Evidence ID | Repository or source | Revision or version | File or artifact location | Observation | Status |
| --- | --- | --- | --- | --- | --- |
| | | | | | Verified / Supplied / Inferred / Unknown |

## Decision Context

Separate confirmed facts, assumptions, open decisions, and recommended defaults. Record one `Not applicable` row when
no additional decision remains for this Spike. A normative recommendation must use `Recommended default`, not
`Confirmed fact`.

| Category | Statement or branch | Evidence refs | Owner or decision needed | Status |
| --- | --- | --- | --- | --- |
| | | | | |

## Assessment Criteria

When the run declares evaluation criteria, assess each one against the evidence with one row per declared criterion or
control domain. Do not convert an unknown into a gap or a satisfied control. Use one `Not applicable` row when no
external criteria or control baseline was declared.

| Criterion or domain | Evidence refs | Assessment | Gap or limitation | Required next evidence or decision |
| --- | --- | --- | --- | --- |
| | | | | |

## Experiments and Checks

| Hypothesis or review criterion | Observable seam | Command or method | Expected discriminating outcomes | Actual result | Disposition impact |
| --- | --- | --- | --- | --- | --- |
| | | | | | |

Use `Not run` when no experiment was necessary and explain why the existing evidence answered the question.
Record at least one exact source-backed Evidence ID in each check. A `CHK-*` label identifies a check but does not
replace its `E-*` evidence reference.

## Findings

List only findings supported by the evidence above. Keep facts, inferences, and unresolved unknowns distinct. Include
the exact Evidence IDs that directly support each finding.

## Options and Tradeoffs

Use comma-separated exact Evidence IDs for each option and list every directly supporting ID. Do not use grouped or
range references such as `E-01-E-05`.

| Option | Evidence | Benefits | Costs or risks | When to choose |
| --- | --- | --- | --- | --- |
| | | | | |

## Recommendation

State the answer or best-supported direction, confidence, rationale, and material limitations. Include the exact
Evidence IDs supporting the answer and rationale. `Inconclusive` is valid when the budget was exhausted without enough
evidence.

## Reference Comparison

Complete this only after the independent recommendation. For `execute_spike` with no declared comparison reference,
or for `review_spike`, use one `Not applicable` row.

| Reference | Agreement | Difference or omission | Impact on recommendation |
| --- | --- | --- | --- |
| | | | |

## Remaining Unknowns and Follow-up

| Unknown or follow-up | Why it matters | Owner | Next evidence or decision |
| --- | --- | --- | --- |
| | | | |

## Disposition

Use the exact disposition allowed by the Technical Spike playbook for the selected objective.

| Field | Value |
| --- | --- |
| Workflow result | |
| Question or review conclusion | |
| Budget status | within_budget / exhausted_with_useful_result / exceeded_during_finalization / stopped_by_indispensable_evidence |
| Feature Delivery handoff | Ready to consume / Needs follow-up / Not applicable |

Do not claim Feature Delivery readiness here. When implementation planning is the next action, identify the evidence a
later Feature Delivery run should consume and the unresolved decisions it must still validate.
