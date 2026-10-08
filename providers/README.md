# Provider Adapters

Provider adapters define concrete execution rules and map canonical skills and tool IDs to platform capabilities.
The [execution contract](../contracts/workflow_execution.md) defines provider-neutral semantics; adapters define
launcher preflight, worker activation, runtime status/release operations, and connector routing that satisfy them.

The canonical skill ID is the filename without `.md`. Provider adapters may also map internal provider-neutral capacity
classifications and tool IDs defined in `../contracts/workflow_execution.md`.

They do not redefine role responsibilities or playbook stages. If a provider cannot perform a skill, the work must
record that limitation and use an approved equivalent or stop.

Named capabilities are not claims of availability in every runtime. A missing mapping must be recorded as a limitation
before the worker runs. Apply the selected source [integration](../integrations/README.md) for retrieval scope,
freshness, privacy, and write rules; an adapter must not silently replace those rules or waive a shared workflow gate.

The Codex pilot is explained in the framework's [`../OPERATING_GUIDE.md`](../OPERATING_GUIDE.md), with a formal adapter
at [`codex.md`](codex.md) and model/effort settings at [`codex/model_effort_policy.md`](codex/model_effort_policy.md).

Available adapters:

* [Generic](generic.md)
* [Claude](claude.md)
* [Codex](codex.md)
* [Cursor](cursor.md)

Codex worker definitions are stored under [`codex/agents/`](codex/agents/); they are packaged with the plugin and may be
exposed as an optional execution-repository runtime view.
