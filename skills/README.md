# Skills

Skills are provider-neutral capabilities used by roles and playbooks.

A skill defines:

* the capability to perform,
* required inputs,
* expected outputs,
* completion criteria,
* safety boundaries.

Provider adapters map these capabilities to platform-specific tools. Skills do not name or require a specific AI provider.

The canonical skill ID is the filename without `.md`. Roles and playbooks must reference these IDs rather than provider-specific capability names.

## Catalog

* `work_item_context.md`
* `workflow_planning.md`
* `repository_exploration.md`
* `dependency_mapping.md`
* `architecture_mapping.md`
* `destination_integration.md`
* `code_migration.md`
* `build_and_test.md`
* `operational_readiness.md`
* `work_record_maintenance.md`
* `failure_diagnosis.md`

Worker tool, model-profile, dependency, approval, and failure semantics are defined in [`../contracts/workflow_execution.md`](../contracts/workflow_execution.md).
