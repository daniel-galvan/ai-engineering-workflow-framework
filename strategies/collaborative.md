---

title: Collaborative Workflow Strategy
version: 0.3.0
status: Pilot
owner: Engineering
last_updated: 2026-08-21
depends_on:

  - ../frameworks/investigation.md
  - ../contracts/workflow_execution.md

---

# Collaborative Workflow Strategy

> Execute engineering work by decomposing it into specialized workers that collaborate toward a shared outcome.

This strategy is intended for medium and large engineering efforts where the work benefits from multiple perspectives.

The roles may be executed:

* Sequentially
* In parallel
* As AI subagents
* As separate engineering tasks
* By different human engineers

The workflow contract remains the same regardless of the execution model.

---

# Purpose

Large engineering work often requires answering different kinds of questions:

* What exists today?
* How does it work?
* Why was it designed this way?
* What should change, if anything?
* What risks exist?
* How should implementation proceed?

Rather than asking one investigator to answer everything at once, this strategy assigns responsibilities to specialized
roles.

---

# Guiding Principles

A role is **not** an implementation detail.

A role defines:

* Responsibilities
* Questions to answer
* Inputs
* Deliverables

How those responsibilities are fulfilled depends on the available tooling.

---

# Internal Worker Metadata

Current playbooks select the worker graph through the execution profile. Use the playbook as the source of truth; this
strategy does not define a second worker graph or override a role's provider model and reasoning effort.

Provider-neutral worker depth and mode are internal metadata. A user selects lifecycle and profile; the playbook and
provider role policy derive this metadata. When an individual worker needs a provider-neutral depth, use:

| Worker depth | Use for |
| --- | --- |
| `quick` | Small scope, few dependencies, and narrow validation |
| `standard` | Normal bounded engineering work |
| `deep` | Cross-repository, architectural, operational, or high-risk work |

---

# Workflow Modes

Mode and worker depth are separate internal classifications. Discovery is a mode, not a worker depth. Execution profiles
are selected by the playbook.

| Mode | Use |
| --- | --- |
| Discovery | Establish feasibility, scope, options, and risks without expecting implementation. |
| Investigation | Establish an evidence-backed understanding and recommendation. |
| Delivery | Implement and validate an approved change. |
| Stabilization | Reduce operational risk after extraction, migration, upgrade, or release. |
| Review | Independently assess correctness, risk, and readiness. |

---

# Role Lifecycle

Every role follows the same pattern.

## Inputs

What information does the role need?

Examples:

* Normalized work item
* Repository
* Existing documentation
* Work record

---

## Responsibilities

What questions must the role answer?

---

## Deliverables

What artifacts should the role produce?

Deliverables become inputs for later roles.

---

## Exit Criteria

When is the role finished?

---

# Worker graph ownership

The selected playbook owns the worker graph, dependencies, and execution order. The Documenter commonly runs
continuously after initialization, but the playbook decides whether and how it is activated. Choose the smallest set of
roles that provides sufficient confidence.

Start ready independent workers in parallel when runtime capacity allows. If they run sequentially, record the
dependency or capacity reason and resulting wait. Give Deep workers distinct questions and artifacts; repeat raw
investigation only to resolve a recorded discrepancy.

---

# Communication Between Roles

Roles should communicate through documented artifacts rather than implicit context.

Examples include:

* Work records
* Architecture summaries
* Dependency maps
* Design proposals
* Risk assessments
* Validation plans

This allows workflows to be resumed or reviewed at any point.

---

# Skill and Worker Selection

Selection precedence is:

1. Role metadata provides default skills and required documents.
2. The playbook selects the roles and skills required for the scenario.
3. Each stage may add or restrict skills for its workers.
4. The worker profile defines tools, internal provider metadata, inputs, outputs, dependencies, approvals, and
   exit criteria.

The playbook owns the execution graph. Role documents do not define worker ordering.

See `../contracts/workflow_execution.md` for the worker contract and parallelism semantics.

---

# Role Selection

Select roles from the chosen playbook. This strategy does not define a second scenario matrix or fixed role sequence. If
no existing playbook expresses the required graph, document the special workflow requirements before adding one.

---

# AI Execution

When using AI assistants, each selected role is executed through one or more workers defined by the Workflow Execution
Contract.

The worker may be:

* A dedicated subagent
* A specialized prompt
* A separate conversation
* A human engineer
* A step within one session

---

The workflow must not depend on one AI provider. Provider-specific mappings belong in `../providers/`; concrete tool
selection belongs in the worker profile.

---

# Success Criteria

The strategy has succeeded when:

* Each selected worker has completed its responsibilities or recorded a non-complete outcome.
* Deliverables are documented.
* The work record reflects the current understanding.
* The selected outcome is supported by evidence.
* Required gates and approvals are recorded.
* Validation activities are complete or explicitly not applicable.

Implementation should begin only after the workflow reaches `ready_for_implementation` or an equivalent approved state.
