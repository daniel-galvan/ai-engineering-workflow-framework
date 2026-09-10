---
title: Technical Spike Example
version: 0.5.1
status: Pilot
owner: Engineering
last_updated: 2026-09-07
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
Requested outcome: technical_answer
Spike objective: execute_spike
Primary question: <ONE-DECISION-RELEVANT-QUESTION>
Decision context: <FACTS-ASSUMPTIONS-OPEN-DECISIONS-RECOMMENDED-DEFAULTS>
Assessment criteria or control domains: <NONE-OR-LIST-OF-CRITERIA>
Timebox or evidence budget: <BOUNDED-LIMIT>
Success criterion: <OBSERVABLE-ANSWER-CONDITION>
Review target: None
Comparison reference: <EXISTING-SPIKE-OR-NONE>
```

Use `review_spike` when an existing report or document is the object being assessed. Use `deep` only when the question
crosses repositories, ownership, persistence, security, privacy, or a public contract and needs independent evidence.
For `execute_spike`, establish the answer independently and compare an existing Spike only afterward.

## Expected Outcome

The work record and report are created at:

```text
<execution-repository>/.thoughts/<WORK-ITEM-ID>/work_record.md
<execution-repository>/.thoughts/<WORK-ITEM-ID>/spike_report.md
```

The report records the question, decision context, any declared assessment criteria, measured budget status, direct
evidence with repository revision and file or artifact location, observable experiment seams, options, recommendation,
post-recommendation reference comparison, limitations, remaining unknowns, and exact disposition. It does not create
`implementation_plan.md`.

If implementation planning is next, start a separate Feature Delivery planning run and supply the accepted Spike report
as current-run supporting evidence.
