# AI-assisted Software Engineering Workflow Framework

Version

v0.1 pilot baseline

---

## Implemented framework components

### Frameworks

- Engineering Work Framework

### Contracts

- Workflow Execution Contract

### Strategies

- Collaborative Strategy

### Roles

- Orchestrator
- Current-State Investigator
- Dependency Analyst
- Solution Architect
- Repository Integrator
- Implementer
- Reviewer
- Tester
- Documenter

### Templates

- work_record
- implementation_plan
- Sentry Issue Remediation run prompt
- Vulnerability Investigation run prompt
- Service Extraction and Stabilization run prompt
- Feature Delivery run prompt
- TechOps Issue Remediation run prompt

### Playbooks

- Vulnerability Investigation (exercising)
- Service Extraction and Stabilization (not exercised)
- Feature Delivery (exercising)
- TechOps Issue Remediation (exercising; not yet exercised)
- Sentry Issue Remediation (exercising; planning validated)

### Pilot artifacts awaiting exercise

- Service Extraction and Stabilization planning and remediation lifecycle
- Feature Delivery remediation lifecycle
- TechOps Issue Remediation planning and remediation lifecycle

---

## Next Milestone

Complete the Phase 0 foundation and exercise the Service Extraction and Stabilization pilot with a real Jira Story

- Service Extraction and Stabilization playbook
- Worker profiles with roles, skills, tools, model profiles, effort, dependencies, and approvals
- Source-to-destination repository workflow
- Stabilized service handoff
- General work record with execution history, errors, blockers, and closure state

Then begin Phase 1 scenario coverage

- Bug fix
- TechOps and incident
- Feature delivery pilot validation
- Migration family
- New project

The initial contract, skill catalog, provider adapter mappings, and Sentry
planning workflow have been exercised. Service Extraction has been aligned with
the shared lifecycle, fan-in, artifact-root, and implementation-plan rules but
still requires the real Jira Story pilot before being marked stable. Sentry
remediation execution remains unvalidated.

---

Planned supporting playbooks

- Package Upgrade
- Architecture Review
- Vulnerability remediation

---

## Future

- Dynamic orchestration
- Automatic role selection
- AI-provider profiles
- Effort estimation
- Prompt generation
