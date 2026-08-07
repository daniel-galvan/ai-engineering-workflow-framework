---

title: Codex Model and Effort Policy
version: 0.1
status: Pilot
provider: codex
provider_independent_profiles: true
owner: Engineering
last_updated: 2026-08-04
---

# Codex Model and Effort Policy

This policy maps the library's provider-neutral model profiles to Codex custom
agents for the Feature Delivery and Service Extraction pilots and Sentry Issue
Remediation.

The pilot uses one role-quality policy across Feature Delivery, Service
Extraction, and Sentry.
Profiles select which roles run; they do not change a role's model or
reasoning effort. Record the requested and resolved values in the work record.

User-facing effort labels map to Codex configuration values as follows:

| Policy label | Codex configuration value |
|---|---|
| Light | `low` |
| Medium | `medium` |
| High | `high` |
| Extra High | `xhigh` |
| Max | `max` |
| Ultra | `ultra` |

## Pilot Role Quality Policy

| Role | Codex model | Policy effort | TOML value |
|---|---|---|---|
| Orchestrator | `gpt-5.6-luna` | Extra High | `xhigh` |
| Current-State Investigator / Sentry Evidence | `gpt-5.6-luna` | Medium | `medium` |
| Dependency Analyst | `gpt-5.6-luna` | High | `high` |
| Repository Integrator | `gpt-5.6-luna` | High | `high` |
| Solution Architect | `gpt-5.6-terra` | Light | `low` |
| Reviewer | `gpt-5.6-terra` | Light | `low` |
| Implementer | `gpt-5.6-luna` | High | `high` |
| Tester | `gpt-5.6-luna` | Extra High | `xhigh` |
| Documenter | `gpt-5.6-luna` | Light | `low` |

## Generic Agent Usage

Feature Delivery and Service Extraction use the generic agent definitions. The
selected execution profile changes the required worker graph, not a role's
pinned model or effort.

### Service Extraction

| Profile | Required planning workers |
| --- | --- |
| `standard` | Orchestrator, Current-State Investigator, Dependency Analyst, Solution Architect, Repository Integrator, and Documenter |
| `deep` | Standard workers plus Reviewer as `planning-review` for independent planning review |

### Feature Delivery

Feature Delivery uses Orchestrator, Current-State Investigator, Dependency
Analyst, Solution Architect, and Documenter for `standard`; Repository
Integrator is conditional. `deep` makes Repository Integrator and Reviewer
mandatory.

After explicit approval and remediation re-entry, both profiles add
Implementer, Reviewer, Tester, and continuous Documenter. The current session
owns fan-out directly when a coordinator subagent cannot delegate.

## Sentry Issue Remediation

The Sentry playbook uses specialized `sentry_*.toml` agents only for
Sentry-specific investigation. Delivery roles reuse the generic agents so
implementation, review, testing, and documentation policy cannot drift.

| Responsibility | Codex model | Codex effort |
|---|---|---|
| Diagnosis, architecture, implementation, and review | Role-specific | Role-specific |
| Sentry evidence and testing | Role-specific | Role-specific |
| Work-record documentation | `gpt-5.6-luna` | `low` (Light) |

This profile is enforced by the named agent files when the Orchestrator uses
those agents. Prompt text alone does not override a pinned agent model or
effort. If a requested model is unavailable, use a separate equivalent agent
definition with the nearest available model and record the substitution.

### Sentry Agent Mapping

| Worker responsibility | Codex agent | Model | Reasoning effort |
|---|---|---|---|
| Orchestration | `sentry_orchestrator` | `gpt-5.6-luna` | `xhigh` (Extra High) |
| Sentry evidence and initial topology | `sentry_current_state_investigator` | `gpt-5.6-luna` | `medium` |
| Failure topology and root-cause analysis | `sentry_dependency_analyst` | `gpt-5.6-luna` | `high` |
| Fix design | `sentry_solution_architect` | `gpt-5.6-terra` | `low` (Light) |
| Repository integration | `sentry_repository_integrator` | `gpt-5.6-luna` | `high` |
| Implementation | `implementer` | `gpt-5.6-luna` | `high` |
| Code Review | `reviewer` | `gpt-5.6-terra` | `low` (Light) |
| Testing | `tester` | `gpt-5.6-luna` | `xhigh` (Extra High) |
| Documentation | `documenter` | `gpt-5.6-luna` | `low` (Light) |

### Sentry Profile Activation

For Sentry planning runs:

- `standard` activates the Orchestrator, Current-State Investigator, Solution
  Architect, and Documenter. Repository Integrator is conditional.
- `deep` adds the independent Dependency Analyst and requires Repository
  Integrator.
- The Standard and Deep Solution Architects use the same Terra/Light policy.
  Deep receives more independent evidence; it does not silently change the
  Solution Architect's model or effort.

## Resolution

The workflow selects a provider-neutral profile. The Codex agent file supplies
the concrete model and `model_reasoning_effort`. When those fields are pinned
in the selected agent file, that file wins. If a field is omitted, Codex
resolves it from an explicit spawn value, configured subagent defaults, and
then the parent session.

If a recommended model or effort is unavailable, use the nearest available
setting and record the substitution as an execution note and risk.

## Delegation Runtime

The TOML agent files configure worker identity, model, effort, and instructions;
they do not invoke workers or grant nested delegation capability.

The active main Codex session must act as the Orchestrator when the runtime
does not expose worker delegation to a coordinator subagent. It must activate
the required workers directly, collect their result envelopes, and complete
fan-in, and release completed worker handles before reporting profile success.
A coordinator subagent that cannot spawn descendants is not a successful
execution of the selected profile.

## Pilot safety

* Exploration, architecture, review, and documentation agents are read-only.
* Implementation and test agents may write only within the approved workflow
  and must not make external writes.
* Do not change migrated business logic without explicit approval.
* Do not treat model selection as evidence of correctness; validation remains
  required.

## Usage accounting

Agent configuration selects model and reasoning effort; it does not expose
credit accounting. Record provider-reported usage when the execution surface
exposes it. Never estimate credits from token counts or invent missing values.
