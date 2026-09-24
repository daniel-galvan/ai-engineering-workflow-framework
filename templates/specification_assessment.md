---
title: Feature Specification Assessment
version: 0.1.0
status: Pilot
owner: Engineering
last_updated: <DATE-OF-CREATION>
depends_on:
  - ../playbooks/feature_delivery.md
  - ./work_record.md
  - ./asset_manifest.json
---

# Specification Assessment

Create `.thoughts/<WORK-ITEM-ID>/specification_assessment.md` for a Feature Delivery
`specification_assessment` run. This is a coverage and readiness judgment, not an implementation plan or approval.
Write for a reader who has not followed the investigation. Explain technical terms in plain language.

## Question and Result

State what work was assessed, the exact `Workflow result` (`Ready for implementation`,
`Ready with explicit follow-ups`, or `Not ready for implementation`), and why. When reviewing a completed Spike,
distinguish its output from any unverified claim that its Stories fully cover the Epic.

Workflow result: <EXACT-FINAL-HANDOFF-RESULT>

## Source and Asset Baseline

Link the primary work item or specification, relevant child or linked work, repository revisions, and
[`asset_manifest.json`](asset_manifest.json). For a completed-Spike Epic, include the Spike and every resulting Story.
State which sources were read, unavailable, or empty. For each material attachment, record its manifest asset ID,
observation, evidence ID, and consequence for coverage or validation. Do not treat a ticket status or a missing Spike
write-up as proof of technical completeness.
State the manifest's source and asset row counts, including non-material assets. Distinguish an empty Jira attachment
inventory from an empty asset manifest; count Jira issues separately from source rows.

## Coverage

One row per distinct requested outcome, acceptance criterion, edge case, or integration requirement. Include negative
cases and current controls where relevant. `Covered` means the proposed work has implementable behavior and
observable acceptance or test criteria, not merely a similar title. Split a broad row when work items cover different
behaviors. Cite exact source and evidence references.
For each claimed gap, name the exact Story criterion it contradicts or fails to cover. Preserve explicit exclusions,
such as a field intentionally derived rather than compared, instead of silently replacing them with a proposed rule.
Identify the observable test and dependency for each material row; do not mistake unimplemented code for an absent
Story requirement.
When a criterion applies to multiple save or batch routes, retain route-level negative-case and conflict tests where
the source supports them; do not invent a new acceptance rule.

| Requirement / behavior | Proposed work / Story | Evidence | Status | Test / dependency | Gap or follow-up | Owner |
| --- | --- | --- | --- | --- | --- | --- |
| | | | Covered / Partial / Missing / Conflicting | | | |

## Gaps, Risks, and Decisions

Separate confirmed gaps from unsupported possibilities. For each material gap, explain its consequence and the
smallest decision or Story change needed. If no gaps remain, say so with evidence. A narrow unresolved technical
question may warrant a separate Technical Spike; do not rerun the completed Spike by default.

## Disposition and Next Action

State why the coverage table supports the exact result. A ready result cannot have unresolved decisions that may
change scope, ownership, architecture, security or privacy controls, acceptance criteria, or validation strategy.
For `Not ready for implementation`, link `clarification_brief.md` and name the decision owner. For ready results,
name who should plan or deliver the work next; this report does not authorize source changes.
