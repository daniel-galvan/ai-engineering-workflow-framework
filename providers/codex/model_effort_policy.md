---

title: Codex Model and Effort Policy
version: 0.5.20
status: Pilot
provider: codex
provider_independent_profiles: true
baseline_id: codex-role-policy-gpt61-sol-luna-orchestrator-v20261001
owner: Engineering
last_updated: 2026-10-08
---

# Codex Model and Effort Policy

This policy maps reusable framework roles to Codex custom agents for Technical Spike, Feature Delivery, TechOps Issue
Remediation, Vulnerability Investigation, and Sentry Issue Remediation. It is advanced provider configuration, not a
normal run input. The role policy below is an initial hypothesis: an experimental baseline to validate against real
runs, not a claim of optimal model selection.

The experimental baseline is identified by `baseline_id` in front matter and shared across these playbooks. Profiles
select which roles run; they do not change a role's model or reasoning effort. Record the baseline ID plus requested and
resolved values in the work record, and revise it only from comparable evaluation evidence.

Codex policy labels map to configuration values as follows:

| Policy label | Codex configuration value |
| --- | --- |
| Light | `low` |
| Medium | `medium` |
| High | `high` |
| Extra High | `xhigh` |
| Max | `max` |
| Ultra | `ultra` (Codex App/runtime-specific; not portable) |

This pilot uses `gpt-6.1-sol` for design and review work, and `gpt-6-luna` for coordination and focused, high-volume
roles. Both IDs are advertised by the current Codex host. Exact model/effort resolution remains required for each run.
Astra is outside this baseline; adopting it requires a separate policy revision and runtime verification.

GPT-6.1 Sol supports `low`, `medium` (default), `high`, `xhigh`, and `max`. It does not support `none` or `minimal`.
GPT-6 Luna also supports `none`. The Sol roles retain explicit `low` effort; migration alone does not justify changing
effort. `Ultra` remains Codex App/runtime-specific and must be verified in the target runtime before use.

## GPT-6.1 Sol evidence and compatibility

Official sources checked on 2026-10-01. GPT-6.1 Sol was released on September 29, 2026.

| Standard API pricing per 1M tokens, up to 272K input | GPT-6 Sol | GPT-6.1 Sol |
| --- | --- | --- |
| Input | $2.00 | $2.00 |
| Cached input | $0.20 | $0.10 |
| Cache writes | $2.50 | $2.50 |
| Output | $10.00 | $10.00 |

Cached input is 50% cheaper; the other standard rates are unchanged. Savings depend on cache hits and token consumption.
These API prices do not establish Codex credit savings. Record only provider-reported usage when exposed.

OpenAI positions GPT-6.1 Sol as delivering near-Astra performance for complex coding, computer use, and professional
work. The reviewed guidance does not quantify a head-to-head quality or latency gain over GPT-6 Sol on our workflows.
Treat that improvement as a pilot hypothesis, not a measured result. Context capacity remains 1,050,000 tokens with
128,000 maximum output tokens.

For direct API use, GPT-6.1 Sol requires the Responses API for tool calling; Chat Completions supports requests without
tools. It supports US and EU data residency, with Fast mode unavailable for EU residency. Responses API multi-agent
support is in beta; this does not change the framework's Codex worker graph or automatically enable a different
delegation runtime.

OpenAI also fixed GPT-6 Sol and Luna image encoding on September 25, improving visual tasks in API and Codex. When
comparing runs that use images, record the run dates and consider reevaluating results affected by that bug.

Preserve the prior effort and output contracts for the Sol upgrade. Compare architecture and review runs against the
prior baseline using the same tasks, evidence, and effort; record quality, elapsed time, human effort, and exposed
usage. Do not infer a quality gain from model selection alone.

OpenAI's family prompting advice is based on behavior observed with Astra. Evaluate it with the selected model before
claiming the same behavior for Sol: make instruction precedence, authorized persistence, delegation, and proportionate
verification explicit.

Sources: [GPT-6.1 Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol),
[GPT-6 Sol](https://developers.openai.com/api/docs/models/gpt-6-sol),
[model and migration guidance](https://developers.openai.com/api/docs/guides/latest-model), and
[API changelog](https://developers.openai.com/api/docs/changelog).

## Experimental Role Baseline

| Role | Codex model | Policy effort | TOML value |
| --- | --- | --- | --- |
| Orchestrator | `gpt-6-luna` | Extra High | `xhigh` |
| Current-State Investigator | `gpt-6-luna` | High | `high` |
| Dependency Analyst | `gpt-6-luna` | High | `high` |
| Repository Integrator | `gpt-6-luna` | High | `high` |
| Solution Architect | `gpt-6.1-sol` | Light | `low` |
| Reviewer | `gpt-6.1-sol` | Light | `low` |
| Implementer | `gpt-6-luna` | Extra High | `xhigh` |
| Tester | `gpt-6-luna` | Extra High | `xhigh` |
| Documenter | `gpt-6-luna` | Light | `low` |

This baseline assigns Luna with Extra High effort to coordination, implementation, and testing; High effort to
investigation and integration; and Light effort to documentation. GPT-6.1 Sol handles design and review at Light effort.
Keep the baseline only when comparable runs show that it maintains or improves quality, elapsed time, and human effort.

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
| Work-record documentation | `gpt-6-luna` | `low` (Light) |

This profile is enforced by the named agent files when the Orchestrator uses those agents. Prompt text alone does not
override a pinned agent model or effort.

### Specialized Sentry Agent Mapping

| Worker responsibility | Codex agent | Reuses role policy |
| --- | --- | --- |
| Orchestration | `sentry_orchestrator` | Orchestrator |
| Sentry evidence and initial topology | `sentry_current_state_investigator` | Current-State Investigator |
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
