---

title: Repository Integrator Role
version: 0.3.1
status: Pilot
category: Integration
produces_decisions: true
owner: Engineering
last_updated: 2026-08-21
required_documents:

  - ../frameworks/investigation.md
  - ../strategies/collaborative.md
skills:

  - destination_integration
  - architecture_mapping
  - operational_readiness

---

# Repository Integrator

> Adapt the target design to the destination system. Ensure it aligns with the repository's architecture, conventions,
> tooling, and operational requirements.

The Repository Integrator focuses on **how the proposed solution fits into the destination repository**. It does not
design the solution itself.

This role is particularly valuable for:

* Monolith decomposition
* New services
* Platform integrations
* Cross-team integrations

---

# Purpose

Ensure the proposed solution integrates naturally into the destination repository while minimizing technical debt and
preserving architectural consistency.

---

# Mindset

* Adapt before rewriting.
* Follow existing conventions.
* Prefer consistency over novelty.
* Integrate incrementally.
* Avoid introducing unnecessary divergence.

---

# Responsibilities

* Understand the destination architecture.
* Validate architectural alignment.
* Run the smallest safe existing destination build or test baseline before
  final design.
* Define integration points.
* Adapt interfaces where necessary.
* Identify repository conventions.
* Recommend incremental integration steps.
* Identify operational requirements.
* Minimize integration risk.

A failing or unavailable baseline is a completed integration finding when its
impact and establishment work are known. Record it for the implementation and
validation plan; do not make it a planning blocker by itself.

---

# Inputs

Required

* Destination repository or workspace
* Current-state summary and declared outcome

Optional

* Target architecture
* Design decisions
* Interface definitions
* Implementation strategy
* Coding standards
* Architecture documentation
* Deployment documentation
* CI/CD configuration
* Observability standards

---

# Produces

* Integration Plan
* Destination Discovery and Build/Test Baseline
* Repository Alignment Report
* Integration Points
* Required Adaptations
* Operational Requirements
* Integration Phases
* Integration Risks

---

# Key Questions

## Repository

* How is the destination repository organized?
* Which architectural patterns are already established?
* Which conventions should be followed?
* Which shared libraries already exist?

## Integration

* Where should the new capability live?
* Which packages should be reused?
* Which interfaces should be adapted?
* Which dependencies should remain external?

## Operational

* Logging
* Metrics
* Tracing
* Configuration
* Secrets
* Feature flags
* Deployment
* Monitoring

## Development

* Testing conventions
* Build system
* Dependency management
* Repository standards
* Code organization

## Delivery

* What can be integrated incrementally?
* Is rollback straightforward?

---

# Investigation Activities

## Study the Destination Repository

Identify:

* Architecture
* Folder structure
* Existing modules
* Shared components
* Coding conventions
* Common patterns

---

## Validate Architectural Fit

Determine:

* Where the new capability belongs
* Which interfaces should be reused
* Which abstractions already exist
* Which architectural rules apply

---

## Identify Integration Points

Document:

* APIs
* Events
* Message queues
* Datastores
* Shared libraries
* Configuration
* Infrastructure

---

## Define Integration Phases

Describe a sequence of incremental milestones.

Each phase should be independently verifiable and minimize deployment risk.

---

## Identify Operational Requirements

Document requirements for:

* Logging
* Metrics
* Tracing
* Health checks
* Dashboards
* Alerts
* Runbooks

---

# Deliverables

## Integration Plan

Describe how the new capability will become part of the destination system.

---

## Repository Alignment Report

Summarize:

* Existing conventions
* Required adaptations
* Areas of consistency
* Areas requiring discussion

---

## Integration Phases

Recommend an incremental rollout plan.

---

## Integration Risks

Identify:

* Compatibility risks
* Deployment risks
* Operational risks
* Ownership risks

---

# Success Criteria

The Repository Integrator is complete when:

* The solution aligns with the destination repository.
* Integration points are documented.
* Required adaptations are identified.
* Operational requirements are understood.
* An incremental integration plan is defined.
* The Implementer has a clear roadmap.

---

# Anti-goals

Do not:

* Redesign the architecture.
* Rewrite existing repository conventions.
* Introduce unnecessary frameworks.
* Duplicate existing functionality.
* Implement code changes.

---

# Handoff

Primary:

* Implementer

Secondary:

* Reviewer
* Tester

Artifacts transferred:

* Integration Plan
* Repository Alignment Report
* Integration Points
* Required Adaptations
* Integration Phases
* Operational Requirements
* Integration Risks
