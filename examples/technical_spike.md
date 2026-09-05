---
title: Technical Spike Example
version: 0.1.0
status: Pilot
owner: Engineering
last_updated: 2026-09-04
depends_on:
  - ../playbooks/technical_spike.md
  - ../templates/technical_spike_run_prompt.md
  - ../templates/spike_report.md
  - ../contracts/workflow_execution.md
---

# Technical Spike Example

> Example of answering or reviewing one bounded technical question without turning research into feature delivery.

## Example Scenario

A Jira Spike asks whether an existing service boundary can satisfy a proposed privacy constraint. The run has one
question, a fixed evidence budget, named repositories and documents, and no authorization to change production source.

## Run Format

Use the canonical [`technical_spike_run_prompt.md`](../templates/technical_spike_run_prompt.md) template:

```text
Playbook: playbooks/technical_spike.md
Canonical run template: templates/technical_spike_run_prompt.md
Execution profile: standard
Lifecycle: planning
Spike objective: execute_spike
Primary question: <ONE-DECISION-RELEVANT-QUESTION>
Timebox or evidence budget: <BOUNDED-LIMIT>
Success criterion: <OBSERVABLE-ANSWER-CONDITION>
```

Use `review_spike` when an existing report or document is the object being assessed. Use `deep` only when the question
crosses repositories, ownership, persistence, security, privacy, or a public contract and needs independent evidence.

## Expected Outcome

The work record and report are created at:

```text
<execution-repository>/.thoughts/<WORK-ITEM-ID>/work_record.md
<execution-repository>/.thoughts/<WORK-ITEM-ID>/spike_report.md
```

The report records the question, budget, evidence, experiments, options, recommendation, limitations, remaining
unknowns, and exact disposition. It does not create `implementation_plan.md`.

If implementation planning is next, start a separate Feature Delivery planning run and supply the accepted Spike report
as current-run supporting evidence.
