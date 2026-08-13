---

title: Engineering Work Framework
version: 0.1
status: Pilot
owner: Engineering
last_updated: 2026-07-24
depends_on:

  - ../contracts/workflow_execution.md
---

# Engineering Work Framework

> A reusable, investigation-first methodology for evidence-driven engineering work.

This framework defines **how** engineering work should be understood, coordinated, validated, and recorded.

It is intentionally domain-agnostic and serves as the shared kernel for playbooks covering security, bugs, upgrades,
migrations, incidents, features, and future domains.

---

# Purpose

The objective of every workflow is to produce an evidence-backed outcome appropriate to the work item. For
implementation work, that means an implementation-ready understanding before changes are made. For triage or closure
work, it may mean a justified non-implementation outcome.

Engineering work should answer:

* What is happening?
* Why is it happening?
* What evidence supports that conclusion?
* What options exist?
* What outcome is required?
* Which option, if any, should be implemented?
* How will the solution be validated?

---

# Evidence-Driven Philosophy

The goal is **understanding before implementation**.

Good engineering work:

* Are driven by evidence rather than intuition.
* Separate facts from assumptions.
* Challenge initial conclusions.
* Consider multiple remediation options.
* Produce a documented decision.

The objective is not to be "fast."

The objective is to reach the correct conclusion with an appropriate level of confidence.

---

# Investigation Loop

```text
Observe
    │
    ▼
Collect Evidence
    │
    ▼
Form Hypotheses
    │
    ▼
Validate or Refute
    │
    ▼
Revise Understanding
    │
    └──────────────┐
                   │
        More evidence required?
                   │
                   ▼
              Collect Evidence
                   │
                   ▼
      Recommendation
                   │
                   ▼
      Validation Strategy
```

Investigations are iterative.

New evidence may require revisiting earlier conclusions.

---

# Work Principles

Every workflow should follow these principles.

## 1. Evidence over Assumptions

When evidence conflicts with assumptions, trust the evidence.

Clearly distinguish between:

* Facts
* Inferences
* Hypotheses
* Unknowns

---

## 2. Use the Strongest Relevant Source of Truth

For code behavior, prefer conclusions supported by the current repository. For incidents and operational work, runtime
evidence may be more authoritative. In every case, identify the source and explain conflicts.

Do not treat any source as authoritative merely because it is convenient.

---

## 3. Keep the Smallest Practical Scope

Avoid expanding the work unless new evidence requires it.

Investigate the reported problem first.

Broaden scope only when justified.

---

## 4. Work Is Iterative

Do not force the workflow forward.

If new evidence changes the understanding of the problem:

* revisit previous conclusions,
* update documentation,
* revise recommendations.

---

## 5. Compare Alternatives

Do not stop after identifying the first possible solution.

Consider multiple viable approaches before recommending one.

Document why alternatives were rejected.

---

## 6. Documentation Is Part of the Investigation

An investigation is incomplete if its reasoning cannot be understood later.

Continuously document:

* findings,
* evidence,
* decisions,
* assumptions,
* unresolved questions.

---

# Source Guidance

When multiple information sources disagree, consider:

1. Direct current observation
2. Current repository or runtime state, depending on the question
3. Current work item and acceptance criteria
4. Existing work record
5. Team documentation and previous work
6. Dashboards, scanners, and general documentation

Explain meaningful discrepancies.

---

# Standard Evidence Workflow

Every workflow should answer the following questions, adapting them to its selected mode.

---

## Question 1 — What Do We Already Know?

Recover existing context before beginning new work.

Examples:

* Previous work records
* Existing documentation
* Similar tickets
* Previous implementations
* Team notes

### Exit Criteria

Existing knowledge has been summarized.

---

## Question 2 — What Is the Actual Problem?

Understand what is being investigated.

Examples:

* Bug
* Vulnerability
* Upgrade
* Migration
* Operational issue

Define:

* scope,
* affected systems,
* initial uncertainty.

### Exit Criteria

The problem has been clearly classified.

---

## Question 3 — What Evidence Exists?

Collect evidence before drawing conclusions.

Examples:

* Source code
* Logs
* Tests
* Stack traces
* Dependency graphs
* Scanner reports
* Architecture documentation

Separate observations from interpretations.

### Exit Criteria

Sufficient evidence exists to begin analysis.

---

## Question 4 — What Does the Evidence Tell Us?

Analyze the evidence.

Identify:

* likely causes,
* contradictions,
* confidence,
* remaining unknowns.

If necessary:

Return to Question 3.

### Exit Criteria

The current understanding is supported by evidence.

---

## Question 5 — What Are the Available Options?

Generate multiple possible solutions.

For every option consider:

* benefits,
* risks,
* effort,
* blast radius,
* validation requirements.

Prefer the smallest safe solution.

### Exit Criteria

A preferred recommendation has been selected.

---

## Question 6 — Are We Ready to Implement?

Before implementation verify:

* sufficient evidence exists,
* assumptions are documented,
* alternatives were considered,
* validation is defined,
* confidence is acceptable.

If not:

Continue investigating.

### Exit Criteria

The investigation is implementation-ready.

---

# Work Record

Each unit of engineering work should maintain a work record. The execution repository is the durable-artifact root. The
recommended location is:

```text
<execution-repository>/.thoughts/<WORK-ITEM-ID>/work_record.md
```

The record should evolve alongside the workflow.

It should capture:

* Facts
* Evidence
* Assumptions
* Unknowns
* Decisions
* Alternatives
* Risks
* Validation strategy
* Workflow state and next action
* Worker execution and outcomes
* Errors, blockers, approvals, and handoffs

---

# Decision Making

Every significant recommendation should answer:

* What is being recommended?
* Why?
* What evidence supports it?
* What alternatives were considered?
* Why were they rejected?
* What validation is required?

---

# Stop Conditions

The selected workflow is complete when:

* Its playbook entry and exit criteria are satisfied.
* Evidence supports the current conclusion or closure reason.
* Unknowns, errors, and blockers are documented.
* Required decisions and approvals are recorded.
* Validation is complete or explicitly not applicable.
* The work record is current.

Implementation begins only when the workflow reaches `ready_for_implementation` or an equivalent approved state. A
workflow may instead close as no action, duplicate, not a bug, deferred, or blocked when the evidence supports that
outcome.

---

# Relationship to Playbooks

This framework defines **how** engineering work is performed.

Playbooks define **what** should be done for a specific engineering domain.

Playbooks should extend this framework rather than duplicate it.
