---

title: Work-Item Context
version: 0.1
status: Pilot
category: Context
provider_independent: true
owner: Engineering
last_updated: 2026-08-04
---

# Work-Item Context

> Recover the authoritative request, acceptance criteria, constraints, and related work before analysis begins.

## Inputs

* Work-item identifier or supplied request
* Existing work record, if present
* Linked tickets, documents, and prior decisions
* For Jira work: immediate parent, ancestor hierarchy, and selected related siblings

## Produces

* Objective and scope
* Acceptance criteria
* Constraints and non-goals
* Related work and prior context
* Context-source map and conflicts
* Unknowns requiring validation

## Jira Context Recovery

When a Jira ticket is thin or incomplete, recover context in this order:

1. the ticket itself for task-specific scope, acceptance criteria, and
   constraints;
2. the immediate parent work item for the immediate business outcome;
3. ancestor Stories, Epics, or Initiatives for broader goals, boundaries, and
   sequencing;
4. selected siblings for dependencies, shared interfaces, precedents, or
   rollout order;
5. linked tickets, documents, pull requests, and prior decisions; and
6. current repository evidence for what exists and is feasible today.

Sibling tickets are context, not inherited requirements. Inspect only siblings
that are directly linked, describe the same repository or component, share a
dependency or release, or establish an explicit precedent. Record conflicts
and do not let a parent or sibling override an explicit ticket requirement.

## Context Sufficiency

Classify the recovered context as one of:

* `sufficient_for_planning`: outcome, affected surface, and observable
  acceptance conditions are supported;
* `partially_recovered`: investigation may continue, but important acceptance
  criteria or constraints remain unknown; or
* `clarification_required`: the minimum implementable outcome, affected
  surface, or acceptance condition cannot be established.

For `clarification_required`, preserve the recovered evidence and ask focused
questions. Before escalating, use bounded repository, contract, test, and
related-work discovery when it can reduce the uncertainty; record feasible
options, recommendation, and the smallest decision needed. Do not create an
implementation plan or invent requirements.

## Completion Criteria

The work can be described without relying on memory or unstated assumptions,
or its remaining clarification questions are explicit.

## Safety

Do not treat a ticket, dashboard, or prior record as proof of current repository behavior. Reconcile it with current evidence.
