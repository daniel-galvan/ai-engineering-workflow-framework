---

title: Code Migration
version: 0.3.0
status: Pilot
category: Implementation
provider_independent: true
owner: Engineering
last_updated: 2026-07-24
---

# Code Migration

> Move and adapt an approved capability while preserving intentional behavior and making dependencies explicit.

## Inputs

* Approved target architecture
* Integration plan
* Source and destination repositories
* Migration phases and acceptance criteria

## Produces

* Small, reviewable code changes
* Adapted interfaces, configuration, and dependencies
* Preserved or expanded tests
* Documented deviations and limitations

## Completion Criteria

The migrated capability builds and runs through its intended destination path.

## Safety

Do not delete the source path or remove rollback options until destination behavior is validated.
