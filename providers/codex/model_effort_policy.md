---
title: Codex Model and Effort Policy
version: 0.5.35
status: Pilot
provider: codex
provider_independent_profiles: true
baseline_id: codex-role-policy-gpt61-terra-sol-luna-v20261112
owner: Engineering
last_updated: 2026-11-12
---

# Codex Model and Effort Policy

This policy maps reusable framework roles to Codex custom agents for Technical Spike, Feature Delivery, TechOps Issue
Remediation, Vulnerability Investigation, and Sentry Issue Remediation. It is advanced provider configuration, not a
normal run input. The role policy below is an initial hypothesis: a baseline to validate against real
runs, not a claim of optimal model selection.

The baseline is identified by `baseline_id` in front matter and shared across these playbooks. Profiles
select which roles run; they do not change a role's model or reasoning effort. Record the baseline ID plus requested and
resolved values in the work record, and revise it only from comparable evaluation evidence.

Codex policy labels map to configuration values as follows:

| Policy label | Codex configuration value                          |
| ------------ | -------------------------------------------------- |
| Light        | `low`                                              |
| Medium       | `medium`                                           |
| High         | `high`                                             |
| Extra High   | `xhigh`                                            |
| Max          | `max`                                              |
| Ultra        | `ultra` (Codex App/runtime-specific; not portable) |

This baseline uses `gpt-6.1-terra` for evidence investigation, `gpt-6.1-sol` for failure analysis, design, and
review, and `gpt-6-luna` for coordination and focused delivery roles. Verify exact model/effort availability for each
run. Astra is outside this baseline; adopting it requires a separate policy revision and runtime verification.

GPT-6.1 Sol supports `low`, `medium` (default), `high`, `xhigh`, and `max`. It does not support `none` or `minimal`.
GPT-6.1 Terra and GPT-6 Luna also support `none`. `Ultra` remains Codex App/runtime-specific and must be verified in
the target runtime before use.

## Evaluation guidance

Preserve output contracts when changing model or effort. Compare runs against the prior baseline using comparable
tasks and evidence; record quality, elapsed time, human effort, and exposed usage. Do not infer a quality gain from
model selection alone.

When comparing runs that use images, record the run dates and consider reevaluating results affected by the GPT-6 Sol
and Luna image encoding fix on September 25, 2026.

OpenAI's family prompting advice is based on behavior observed with Astra. Evaluate it with the selected model before
claiming the same behavior for Sol: make instruction precedence, authorized persistence, delegation, and proportionate
verification explicit. See the
[model and migration guidance](https://developers.openai.com/api/docs/guides/latest-model) and
[API changelog](https://developers.openai.com/api/docs/changelog).

## Role Baseline

| Role | Codex model | Policy effort | TOML value |
| --- | --- | --- | --- |
| Orchestrator | `gpt-6-luna` | Extra High | `xhigh` |
| Current-State Investigator | `gpt-6.1-terra` | Medium | `medium` |
| Dependency Analyst | `gpt-6.1-sol` | Medium | `medium` |
| Repository Integrator | `gpt-6-luna` | High | `high` |
| Solution Architect | `gpt-6.1-sol` | Medium | `medium` |
| Reviewer | `gpt-6.1-sol` | Medium | `medium` |
| Implementer | `gpt-6-luna` | Extra High | `xhigh` |
| Tester | `gpt-6-luna` | Extra High | `xhigh` |
| Documenter | `gpt-6-luna` | Light | `low` |

This candidate strengthens investigation, diagnosis, design, and review while retaining Luna for other roles. Compare
it with the prior baseline on representative runs, including root-cause accuracy, corrections, elapsed time, human
effort, and provider-reported usage. If usage is too high, evaluate retaining Luna for evidence investigation.

## Agent selection

The playbook is the source of truth for which workers run in each execution profile. This policy is the source of truth
only for the model and reasoning effort assigned to each role. The profile changes the worker graph, not the quality
policy of a role. Provider-neutral worker depth is internal contract metadata, separate from Codex reasoning effort.

## Sentry Issue Remediation

Only Sentry-specific investigation uses specialized `sentry_*.toml` agents.

| Responsibility                                      | Codex model   | Codex effort  |
| --------------------------------------------------- | ------------- | ------------- |
| Diagnosis, architecture, implementation, and review | Role-specific | Role-specific |
| Sentry evidence and testing                         | Role-specific | Role-specific |
| Work-record documentation                           | `gpt-6-luna`  | `low` (Light) |

This profile is enforced by the named agent files when the Orchestrator uses those agents. Prompt text alone does not
override a pinned agent model or effort.

### Specialized Sentry Agent Mapping

| Worker responsibility                    | Codex agent                         | Reuses role policy         |
| ---------------------------------------- | ----------------------------------- | -------------------------- |
| Orchestration                            | `sentry_orchestrator`               | Orchestrator               |
| Sentry evidence and initial topology     | `sentry_current_state_investigator` | Current-State Investigator |
| Failure topology and root-cause analysis | `sentry_dependency_analyst`         | Dependency Analyst         |
| Fix design                               | `sentry_solution_architect`         | Solution Architect         |
| Repository integration                   | `sentry_repository_integrator`      | Repository Integrator      |

Sentry reuses the generic `implementer`, `reviewer`, `tester`, and `documenter` agents for delivery, Code Review,
testing, and documentation.

### Sentry Profile Activation

For Sentry planning runs:

- The Sentry playbook selects its standard and deep worker graphs.
- Specialized Sentry agents use the same role policy as their generic counterparts unless this table explicitly assigns
  a different agent.
- Deep receives more independent evidence; it does not silently change a role's model or effort.

## Resolution

The workflow selects a provider-neutral profile. Before activation, every required AI worker must resolve an exact model
and `model_reasoning_effort` from its selected agent definition or explicit work-graph binding. When the runtime would
otherwise inherit Coordinator settings, pass those exact values explicitly; do not inherit Coordinator values or accept
provider defaults as the role binding.

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

- Exploration, architecture, review, and documentation agents are read-only.
- Implementation and test agents may write only within the approved workflow and must not make external writes.
- Do not change existing business logic without explicit approval.
- Do not treat model selection as evidence of correctness; validation remains required.

## Usage accounting

Agent configuration selects model and reasoning effort; it does not expose credit accounting. Record provider-reported
usage when the execution surface exposes it. Never estimate credits from token counts or invent missing values.

Use the [workflow evaluation](../../frameworks/deferred/workflow_evaluation.md) to compare real pilot
runs. Do not change this policy from one run alone.
