# Skills

Skills are provider-neutral capabilities used by roles and playbooks.

A skill defines:

* the capability to perform,
* required inputs,
* expected outputs,
* completion criteria,
* safety boundaries.

Provider adapters map these capabilities to platform-specific tools. Skills do not name or require a specific AI
provider.

The canonical skill ID is the filename without `.md`. Roles and playbooks must reference these IDs rather than
provider-specific capability names.

## Catalog

* [Work-item context](work_item_context.md)
* [Workflow planning](workflow_planning.md)
* [Repository exploration](repository_exploration.md)
* [Dependency mapping](dependency_mapping.md)
* [Architecture mapping](architecture_mapping.md)
* [Destination integration](destination_integration.md)
* [Build and test](build_and_test.md)
* [Operational readiness](operational_readiness.md)
* [Work-record maintenance](work_record_maintenance.md)
* [Failure diagnosis](failure_diagnosis.md)

## Codex launcher

[`run/SKILL.md`](run/SKILL.md) is plugin packaging, not a provider-neutral workflow capability. It is explicitly invoked
to locate the installed framework package, run preflight, select or load a playbook, and enforce terminal validation.
Its [`agents/openai.yaml`](run/agents/openai.yaml) file contains Codex display and invocation metadata.

Worker tool, model-profile, dependency, approval, and failure semantics are defined in
[`../contracts/workflow_execution.md`](../contracts/workflow_execution.md).
