---
title: Workflow Vocabulary
version: 0.3.2
status: Pilot
owner: Engineering
last_updated: 2026-08-21
---

# Workflow Vocabulary

| Term | Meaning |
| --- | --- |
| Work item | The normalized request being handled, such as a Jira Story, bug, incident, or upgrade. |
| Coordinator | The active session or runtime responsible for activating workers, collecting results, completing fan-in, and closing the run. |
| Workflow run | One execution of a playbook for one work item. |
| Execution repository | Repository where the workflow starts and durable run artifacts are stored. |
| Code repository | Repository inspected or modified by the workflow. |
| Playbook | A scenario-specific workflow made of stages, roles, skills, gates, and outputs. |
| Stage | A meaningful unit of work inside a playbook. |
| Role | A reusable responsibility and reasoning boundary. |
| Skill | A reusable capability required to perform work. |
| Tool | A concrete operation available to a worker. |
| Capacity class | Internal provider-neutral reasoning-capacity metadata. |
| Worker | One execution instance containing role, skills, tools, metadata, and inputs. |
| Artifact | A durable output such as a map, decision, code change, test result, or handoff. |
| Evidence | A source-backed observation used to support or challenge a claim. |
| Claim | A material statement derived from evidence, with explicit confidence and uncertainty. |
| Decision | A selected option, scope boundary, or disposition based on claims. |
| Action | A concrete implementation, validation, documentation, or follow-up step derived from a decision. |
| Gate | A condition that must be satisfied before a stage or transition can proceed. |
| Adapter | A provider-specific implementation at a defined seam. |
| Execution profile | A named selection of worker graph, investigation depth, and validation scope. |
| Lifecycle | How far a workflow run may proceed, such as planning or remediation. |
| Engineering state | What has been established about the work item independently of the workflow run. |
| Portable implementation handoff | A self-contained artifact transferring an approved plan to another session or environment. |
