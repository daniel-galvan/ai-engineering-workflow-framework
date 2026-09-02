---

title: Codex Model and Effort Policy
version: 0.4.15
status: Pilot
provider: codex
provider_independent_profiles: true
baseline_id: codex-role-policy-v20260827032839
owner: Engineering
last_updated: 2026-08-27
---

# Codex Model and Effort Policy

This policy maps reusable framework roles to Codex custom agents for Feature Delivery, TechOps Issue Remediation,
Vulnerability Investigation, and Sentry Issue Remediation. It is advanced provider configuration, not a normal run
input. The role policy below is an initial hypothesis: an experimental baseline to validate against real runs, not a
claim of optimal model selection.

The experimental baseline is `codex-role-policy-v20260827032839` and is shared across Feature Delivery, Sentry, TechOps
Issue Remediation, and Vulnerability Investigation. Profiles select which roles run; they do not change a role's model
or reasoning effort. Record the baseline ID plus requested and resolved values in the work record, and revise it only
from comparable evaluation evidence.

Codex policy labels map to configuration values as follows:

| Policy label | Codex configuration value |
| --- | --- |
| Light | `low` |
| Medium | `medium` |
| High | `high` |
| Extra High | `xhigh` |
| Max | `max` |
| Ultra | `ultra` (Codex App/runtime-specific; not portable) |

OpenAI's current GPT-5.6 guidance documents `none`, `low`, `medium`, `high`, `xhigh`, and `max` as reasoning-effort
values. This pilot uses explicit `gpt-5.6-luna`, `gpt-5.6-sol`, and `gpt-5.6-terra` model IDs; it does not use the
`gpt-5.6` alias because that alias routes to Sol. Verify any Codex App-only label, such as `Ultra`, in the target
runtime before pinning it in an agent definition. See the [official GPT-5.6 model
guidance](https://developers.openai.com/api/docs/guides/latest-model).

## Experimental Role Baseline

| Role | Codex model | Policy effort | TOML value |
| --- | --- | --- | --- |
| Orchestrator | `gpt-5.6-luna` | Extra High | `xhigh` |
| Current-State Investigator / Sentry Evidence | `gpt-5.6-luna` | High | `high` |
| Dependency Analyst | `gpt-5.6-luna` | High | `high` |
| Repository Integrator | `gpt-5.6-luna` | High | `high` |
| Solution Architect | `gpt-5.6-sol` | Light | `low` |
| Reviewer | `gpt-5.6-sol` | Light | `low` |
| Implementer | `gpt-5.6-luna` | Extra High | `xhigh` |
| Tester | `gpt-5.6-luna` | Extra High | `xhigh` |
| Documenter | `gpt-5.6-luna` | Light | `low` |

This baseline assigns Luna with Extra High effort to coordination, Sol with Light effort to design and review, and keeps
the existing investigation, implementation, testing, and documentation assignments. Keep the baseline only when
comparable runs show that it maintains or improves quality, elapsed-time, and human-effort metrics.

## Agent selection

The playbook is the source of truth for which workers run in each execution profile. This policy is the source of truth
only for the model and reasoning effort assigned to each role. The profile changes the worker graph, not the quality
policy of a role. Provider-neutral worker depth is internal contract metadata, separate from Codex reasoning effort.

## Sentry Issue Remediation

Only Sentry-specific investigation uses specialized `sentry_*.toml` agents.

| Responsibility | Codex model | Codex effort |
| --- | --- | --- |
| Diagnosis, architecture, implementation, and review | Role-specific | Role-specific |
| Sentry evidence and testing | Role-specific | Role-specific |
| Work-record documentation | `gpt-5.6-luna` | `low` (Light) |

This profile is enforced by the named agent files when the Orchestrator uses those agents. Prompt text alone does not
override a pinned agent model or effort.

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

The workflow selects a provider-neutral profile. Before activation, every required AI worker must resolve an exact
model and `model_reasoning_effort` from its selected agent definition or explicit work-graph binding. When the runtime
would otherwise inherit Coordinator settings, pass those exact values explicitly; do not inherit Coordinator values or
accept provider defaults as the role binding.

If the exact model or effort is unavailable or cannot be bound, stop with `provider_configuration_unavailable`. A
different model or effort requires an explicit policy decision, updated agent definition, and new baseline ID; never
substitute another setting within the current baseline.

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
* Do not change existing business logic without explicit approval.
* Do not treat model selection as evidence of correctness; validation remains required.

## Usage accounting

Agent configuration selects model and reasoning effort; it does not expose credit accounting. Record provider-reported
usage when the execution surface exposes it. Never estimate credits from token counts or invent missing values.

Use the [experimental workflow evaluation](../../frameworks/experimental/workflow_evaluation.md) to compare real pilot
runs. Do not change this
policy from one run alone.
