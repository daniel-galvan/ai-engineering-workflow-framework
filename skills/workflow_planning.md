---

title: Workflow Planning
version: 0.4.16
status: Pilot
category: Coordination
provider_independent: true
owner: Engineering
last_updated: 2026-07-24
---

# Workflow Planning

> Select the playbook, lifecycle, profile, roles, skills, tools, order, and gates for a unit of work.

## Inputs

* Work-item context
* Selected playbook
* Available roles and skills
* Available tools and provider mappings
* Risk, scope, and dependency information

## Produces

* Lifecycle and execution profile
* Worker profiles with role, skill, tool, and internal provider metadata
* Inputs and outputs for each worker
* Execution order and parallelism
* Parallel work opportunities
* Stage gates and stop conditions

## Completion Criteria

The plan identifies the smallest worker graph and capability set that provides sufficient confidence. Every worker has
explicit dependencies, approvals, exit criteria, and failure behavior.

## Safety

Do not select a tool because it is available. Select only capabilities required by the work and record the allowlist in
the worker profile.
