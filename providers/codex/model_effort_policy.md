---

title: Codex Model and Effort Policy
version: 0.1
status: Pilot
provider: codex
provider_independent_profiles: true
owner: Engineering
last_updated: 2026-08-11
---

# Codex Model and Effort Policy

This policy maps reusable framework roles to Codex custom agents for Feature Delivery, TechOps Issue Remediation,
Vulnerability Investigation, Service Extraction, and Sentry Issue Remediation. It does not assign one provider model to
the provider-neutral `standard_reasoning` or `deep_reasoning` labels; the role policy below is the concrete pilot
mapping.

The pilot uses one role-quality policy across Feature Delivery, Service Extraction, Sentry, TechOps Issue Remediation,
and Vulnerability Investigation. Profiles select which roles run; they do not change a role's model or reasoning effort.
Record the requested and resolved values in the work record.

User-facing effort labels map to Codex configuration values as follows:

| Policy label | Codex configuration value |
| --- | --- |
| Light | `low` |
| Medium | `medium` |
| High | `high` |
| Extra High | `xhigh` |
| Max | `max` |
| Ultra | `ultra` (Codex App/runtime-specific; not portable) |

OpenAI's current GPT-5.6 guidance documents `none`, `low`, `medium`, `high`, `xhigh`, and `max` as reasoning-effort
values. This pilot uses explicit `gpt-5.6-luna` and `gpt-5.6-terra` model IDs; it does not use the `gpt-5.6` alias
because that alias routes to Sol. Verify any Codex App-only label, such as `Ultra`, in the target runtime before pinning
it in an agent definition. See the [official GPT-5.6 model
guidance](https://developers.openai.com/api/docs/guides/latest-model).

## Pilot Role Quality Policy

| Role | Codex model | Policy effort | TOML value |
| --- | --- | --- | --- |
| Orchestrator | `gpt-5.6-luna` | Medium | `medium` |
| Current-State Investigator / Sentry Evidence | `gpt-5.6-luna` | Medium | `medium` |
| Dependency Analyst | `gpt-5.6-luna` | Medium | `medium` |
| Repository Integrator | `gpt-5.6-luna` | Medium | `medium` |
| Solution Architect | `gpt-5.6-luna` | Extra High | `xhigh` |
| Reviewer | `gpt-5.6-luna` | Extra High | `xhigh` |
| Implementer | `gpt-5.6-luna` | Medium | `medium` |
| Tester | `gpt-5.6-luna` | Medium | `medium` |
| Documenter | `gpt-5.6-luna` | Light | `low` |

## Agent selection

The playbook is the source of truth for which workers run in each execution profile. This policy is the source of truth
only for the model and reasoning effort assigned to each role. The profile changes the worker graph, not the quality
policy of a role. The contract's worker depth (`quick`, `standard`, or `deep`) is separate from Codex reasoning effort.

## Sentry Issue Remediation

The Sentry playbook uses specialized `sentry_*.toml` agents only for Sentry-specific investigation. Delivery roles reuse
the generic agents so implementation, review, testing, and documentation policy cannot drift.

| Responsibility | Codex model | Codex effort |
| --- | --- | --- |
| Diagnosis, architecture, implementation, and review | Role-specific | Role-specific |
| Sentry evidence and testing | Role-specific | Role-specific |
| Work-record documentation | `gpt-5.6-luna` | `low` (Light) |

This profile is enforced by the named agent files when the Orchestrator uses those agents. Prompt text alone does not
override a pinned agent model or effort. If a requested model is unavailable, use a separate equivalent agent definition
with the nearest available model and record the substitution.

### Specialized Sentry Agent Mapping

| Worker responsibility | Codex agent | Reuses role policy |
| --- | --- | --- |
| Orchestration | `sentry_orchestrator` | Orchestrator |
| Sentry evidence and initial topology | `sentry_current_state_investigator` | Current-State Investigator / Sentry Evidence |
| Failure topology and root-cause analysis | `sentry_dependency_analyst` | Dependency Analyst |
| Fix design | `sentry_solution_architect` | Solution Architect |
| Repository integration | `sentry_repository_integrator` | Repository Integrator |

Sentry reuses the generic `implementer`, `reviewer`, `tester`, and `documenter` agents for delivery, Code Review,
testing, and documentation.

### Sentry Profile Activation

For Sentry planning runs:

- The Sentry playbook selects its standard and deep worker graphs.
- Specialized Sentry agents use the same role policy as their generic counterparts unless this table explicitly assigns
  a different agent.
- Deep receives more independent evidence; it does not silently change a role's model or effort.

## Resolution

The workflow selects a provider-neutral profile. The Codex agent file supplies the concrete model and
`model_reasoning_effort`. When those fields are pinned in the selected agent file, that file wins. If a field is
omitted, Codex resolves it from an explicit spawn value, configured subagent defaults, and then the parent session.

If a recommended model or effort is unavailable, use the nearest available setting and record the substitution as an
execution note and risk.

## Delegation Runtime

The TOML agent files configure worker identity, model, effort, and instructions; they do not invoke workers or grant
nested delegation capability.

The active main Codex session must act as the Orchestrator when the runtime does not expose worker delegation to a
coordinator subagent. It must activate the required workers directly, collect their result envelopes, and complete
fan-in, and release completed worker handles before reporting profile success. A coordinator subagent that cannot spawn
descendants is not a successful execution of the selected profile.

## Pilot safety

* Exploration, architecture, review, and documentation agents are read-only.
* Implementation and test agents may write only within the approved workflow and must not make external writes.
* Do not change migrated business logic without explicit approval.
* Do not treat model selection as evidence of correctness; validation remains required.

## Usage accounting

Agent configuration selects model and reasoning effort; it does not expose credit accounting. Record provider-reported
usage when the execution surface exposes it. Never estimate credits from token counts or invent missing values.

Use the [workflow evaluation](../../frameworks/workflow_evaluation.md) to compare real pilot runs. Do not change this
policy from one run alone.
