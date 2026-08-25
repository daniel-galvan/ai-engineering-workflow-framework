---

title: Dependency Mapping
version: 0.3.3
status: Pilot
category: Analysis
provider_independent: true
owner: Engineering
last_updated: 2026-08-21
---

# Dependency Mapping

> Map upstream callers, downstream dependencies, coupling, ownership, and change impact.

## Inputs

* Current-state code inventory
* Repository and build configuration
* Runtime and integration evidence

## Produces

* Dependency inventory and graph
* Caller and consumer map
* Ownership map
* Coupling classification
* Impact assessment
* Adaptation candidates

## Completion Criteria

Dependencies that can invalidate the proposed boundary are identified or explicitly marked unknown.

## Safety

Do not equate package presence with runtime use. Verify calls, configuration, and data flow.
