---

title: Destination Integration
version: 0.3.0
status: Pilot
category: Integration
provider_independent: true
owner: Engineering
last_updated: 2026-08-18
---

# Destination Integration

> Adapt an approved design to the destination repository's conventions, tooling, runtime, and operations.

## Inputs

* Destination repository
* Current-state summary and declared outcome

Optional inputs:

* Target architecture or design decisions
* Destination build, deployment, and observability standards

## Produces

* Repository alignment report
* Destination build/test baseline result, or an explicit unavailable status
* Integration points and required adaptations
* Build, runtime, deployment, and configuration plan
* Migration phases and integration risks

## Completion Criteria

The destination has a clear location, build/test baseline or explicit absence,
runtime path, ownership model, and rollback approach.

An unavailable or failing baseline is a planning input when its impact and
establishment work can be described. Record it in the implementation and
validation plan; do not treat it as a planning blocker by itself.

## Safety

Reuse destination conventions and existing components before introducing new infrastructure.
