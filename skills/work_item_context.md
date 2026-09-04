---

title: Work-Item Context
version: 0.4.17
status: Pilot
category: Context
provider_independent: true
owner: Engineering
last_updated: 2026-09-04
---

# Work-Item Context

> Recover the authoritative request, acceptance criteria, constraints, and related work before analysis begins.

## Inputs

* Work-item identifier or supplied request
* Existing work record, if present
* Linked tickets, documents, and prior decisions
* Source-specific integration context, when configured

## Produces

* Objective and scope
* Acceptance criteria
* Constraints and non-goals
* Related work and prior context
* Context-source map and conflicts
* Unknowns requiring validation
* A normalized `work_item_read` request/result pair conforming to the shared
  [Work-Item Read Contract](../contracts/workflow_execution.md#work-item-read-contract)

## Source-Specific Recovery

Apply the configured integration when source-specific retrieval is needed. For
Jira-sourced work items, use the [Jira Integration](../integrations/jira.md).
This skill owns normalized context outputs and context sufficiency; the
integration owns source-specific retrieval, freshness, evidence states, and
write rules. Preserve the normalized request/result pair in the context artifact
before downstream workers consume it.

## Context Sufficiency

Classify the recovered context as one of:

* `sufficient_for_planning`: outcome, affected surface, and observable acceptance conditions are supported;
* `partially_recovered`: investigation may continue, but important acceptance criteria or constraints remain unknown; or
* `clarification_required`: the minimum implementable outcome, affected surface, or acceptance condition cannot be
  established.

For `clarification_required`, preserve the recovered evidence and ask focused questions. Before escalating, use bounded
repository, contract, test, and related-work discovery when it can reduce the uncertainty; record feasible options,
recommendation, and the smallest decision needed. Do not create an implementation plan or invent requirements.

## Completion Criteria

The work can be described without relying on memory or unstated assumptions, or its remaining clarification questions
are explicit.

## Safety

Do not treat a ticket, dashboard, or prior record as proof of current repository behavior. Reconcile it with current
evidence.
