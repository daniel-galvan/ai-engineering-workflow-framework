# Provider Adapters

Provider adapters map the canonical skill IDs in `../skills/` to available platform capabilities.

The canonical skill ID is the filename without `.md`. Provider adapters may also map the model profiles and tool IDs
defined in `../contracts/workflow_execution.md`.

They do not redefine role responsibilities or playbook stages. If a provider cannot perform a skill, the work must
record that limitation and use an approved equivalent or stop.

Adapters are reference mappings, not claims that every named capability is available in every runtime. A missing mapping
must be recorded as a limitation before the worker runs.

The Codex pilot is explained in the framework's [`../OPERATING_GUIDE.md`](../OPERATING_GUIDE.md), with a formal adapter
at [`codex.md`](codex.md) and model/effort settings at [`codex/model_effort_policy.md`](codex/model_effort_policy.md).
