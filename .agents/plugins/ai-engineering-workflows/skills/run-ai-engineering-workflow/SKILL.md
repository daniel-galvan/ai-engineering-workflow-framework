---
name: run-ai-engineering-workflow
description: >-
  Select and run the canonical AI Engineering Workflow Framework playbook for a work item. Use only when explicitly
  invoked to start a framework run.
---

# Run an AI Engineering Workflow

1. Resolve the framework checkout from this skill's source directory and verify it contains
   [`PLAYBOOK_CATALOG.md`](../../../../../PLAYBOOK_CATALOG.md). Do not assume the current working directory is the
   framework checkout.
2. Treat the current working directory as the execution repository unless the user explicitly names another repository.
3. Read the catalog, select the most specialized playbook, and record the primary evidence, primary goal, closest
   alternative, and selection rationale.
4. Read the selected playbook, [`contracts/workflow_execution.md`](../../../../../contracts/workflow_execution.md),
   [`contracts/claims.md`](../../../../../contracts/claims.md), and the canonical run template declared by the playbook.
   Load the Codex provider adapter and model policy only when provider configuration is needed.
5. Populate the canonical template from supplied and discoverable context. Preserve its field names, use `Unknown` or
   `None` for unavailable values, and ask only for a business, scope, ownership, or approval decision that bounded
   discovery cannot resolve.
6. Execute the selected playbook. Default to `planning`; use `remediation` only when an implementation plan exists and
   the user has explicitly approved implementation. The plugin does not override any canonical contract, playbook,
   template, role, skill, or provider policy.
