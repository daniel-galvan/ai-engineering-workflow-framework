# Integrations

Integrations define how external systems provide work-item context and runtime evidence to provider-neutral workflows.
They own source identity, required retrieval scope, freshness, privacy, and write boundaries. Concrete connector
selection, launcher sequencing, and tool names belong to the selected [provider adapter](../providers/README.md).
The [execution contract](../contracts/workflow_execution.md) defines normalized inputs, outcomes, and workflow gates.

They do not replace playbooks, roles, skills, or the shared workflow contract. External writes require explicit
authorization and a recorded approval.

Current integrations:

* [Jira](jira.md)
* [Sentry](sentry.md)
