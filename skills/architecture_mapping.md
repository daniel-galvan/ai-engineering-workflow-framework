---

title: Architecture Mapping
version: 0.3.0
status: Pilot
category: Design
provider_independent: true
owner: Engineering
last_updated: 2026-07-24
---

# Architecture Mapping

> Represent current and target responsibilities, boundaries, interfaces, data flows, and tradeoffs.

## Inputs

* Current-state summary
* Dependency and ownership analysis
* Work-item objectives and constraints

## Produces

* Current or target architecture summary
* Boundary and ownership decisions
* Interface and contract definitions
* Alternatives and tradeoffs
* Risks and validation requirements

## Completion Criteria

Another engineer can implement or review the selected design without reconstructing its reasoning.

## Safety

Prefer the smallest safe boundary. Do not redesign unrelated systems.
