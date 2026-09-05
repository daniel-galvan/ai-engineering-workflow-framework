---
title: Jira Integration
version: 0.2.1
status: Pilot
provider: mcp
owner: Engineering
last_updated: 2026-09-04
---

# Jira Integration

Jira supplies work-item context and issue-state evidence to provider-neutral
workflows. It is a source for what the work item requests and what Jira reports;
it is not proof of current repository or runtime behavior.

This document is the normative home for Jira-specific retrieval, evidence,
freshness, privacy, and write rules. Skills, roles, and playbooks consume the
normalized result and own workflow behavior; they must not restate Jira
retrieval policy.

## Source boundary

- Use the configured Jira connector for the narrowest operation that answers the
  current question.
- A stable issue key or URL is the preferred identity. Preserve the exact source
  system, project, issue key, and URL supplied by the user or resolved from Jira.
- Do not infer a project, issue type, field, component, label, transition, or
  repository from a key or from a similarly named issue.
- If the issue identity or project scope is ambiguous, record the ambiguity and
  continue only with bounded discovery that can resolve it. Do not broaden the
  search silently.
- Jira observations may be incomplete, stale, permission-limited, or changed
  during a run. Preserve those states instead of presenting them as complete
  context.

## Read path

Select the smallest read operation that answers the question:

| Need | Minimum Jira evidence |
| --- | --- |
| Task scope | The issue's summary, description, acceptance criteria, status, type, and explicitly stated constraints |
| Immediate outcome | The directly linked parent work item and its relevant scope |
| Broader objective | Ancestor Stories, Epics, Initiatives, or equivalent hierarchy only when needed |
| Dependency or precedent | Selected siblings, linked issues, pull requests, or documents with a recorded selection reason |
| Current writable shape | Live project, issue-type, field, allowed-value, and transition metadata immediately before a write |
| Related history | Comments, attachments, change history, or linked delivery records relevant to the question |

Use a direct issue read when a stable key or URL is available. Use search only to
resolve a missing identity or answer an explicitly broad question. Do not scan an
entire project, board, or initiative when the issue hierarchy or links provide a
narrower route.

## Adapter Contract

The Jira adapter conforms to the shared
[Work-Item Read Contract](../contracts/workflow_execution.md#work-item-read-contract).
It maps Jira-specific reads to the shared scopes without exposing Jira API
shapes or provider-specific operation names:

| Shared scope | Jira-specific read |
| --- | --- |
| `item` | Direct issue read by exact key or URL. |
| `hierarchy` | Immediate parent and required ancestors. |
| `selected_links` | Narrowly selected siblings, linked issues, pull requests, or documents. |
| `history` | Relevant comments, attachments, change history, or delivery records. |
| `write_metadata` | Live project, issue-type, field, allowed-value, and transition metadata before an approved write. |

The canonical offline fixture shape is
[`tests/fixtures/jira_adapter_contract.json`](../tests/fixtures/jira_adapter_contract.json).

## Context recovery order

When the issue is thin or incomplete, recover context in this order:

1. The issue itself for task-specific scope, acceptance criteria, and constraints.
2. The immediate parent for the immediate business outcome.
3. Ancestors for broader goals, boundaries, and sequencing.
4. Selected siblings for dependencies, shared interfaces, precedents, or rollout
   order.
5. Linked documents, pull requests, releases, and prior decisions.
6. Current repository and runtime evidence for what exists and is feasible today.

Parent, ancestor, and sibling material is context, not automatically inherited
requirements. Explicit requirements on the issue remain authoritative for that
issue. Preserve conflicts and resolve them through current evidence or an
explicit user decision.

## Evidence normalization

Record Jira observations in the framework's evidence chain and Input Register.
Each material observation must preserve:

- source system and exact issue key or URL;
- project and issue type when observed;
- source location, such as field, comment, attachment, link, or hierarchy edge;
- the observed value without interpretation;
- the issue's update timestamp or version when available;
- retrieval timestamp and query or selection scope;
- the worker that collected it;
- authority classification, such as direct requirement, reported symptom,
  supporting context, hypothesis, conflict, or unavailable;
- redaction status and any limitation on using the value; and
- evidence status: `verified`, `inferred`, `contradicted`, or `unknown`.

Keep issue text, comments, attachments, and linked records distinguishable. Do
not collapse a comment's opinion into an issue requirement or a Jira status into
an engineering outcome. Preserve stable source identifiers when evidence moves
between workers, artifacts, claims, and the work record.

## Retrieval result states

Use the shared retrieval states from the
[Work-Item Read Contract](../contracts/workflow_execution.md#work-item-read-contract).
For Jira, `empty` means a valid collection read returned no records, while
`not_found` means the exact issue identity was absent. A permission failure on
an optional supporting source need not block all planning, but its scope and
effect must remain visible in the work record.

## Freshness and reconciliation

- Include `retrieved_at` for every live Jira observation and preserve Jira's
  `updated` timestamp or version when available.
- If an issue changes while a run is active, retain the earlier observation,
  collect the current observation, and record the conflict or reconciliation.
- Re-read the exact issue and relevant metadata immediately before an external
  Jira write. A prior issue read or cached field map is not sufficient by itself.
- Treat cached data as a timestamped supporting observation, never as freshly
  verified data. Refresh when the issue identity, scope, relevant field, or
  writable metadata is unknown, changed, contradictory, or outside the configured
  safety window.
- Reconcile Jira identifiers, status, severity, component, repository, revision,
  and timestamps with repository, runtime, scanner, or Sentry evidence when the
  conclusion depends on them.

## Write boundary

- Planning is read-only: do not create, edit, transition, assign, comment on, or
  otherwise mutate Jira state.
- A Jira draft or write must be represented as an approved framework action with
  an explicit scope and applicable gate. This integration does not grant write
  authority.
- Before creating or editing an issue, verify the exact project, issue type,
  writable fields, allowed values, component or ownership mapping, and transition
  against live Jira metadata.
- Present the final proposed payload before a write unless the user supplied and
  confirmed the complete payload. Record omitted or unresolved fields explicitly.
- A repository change, Sentry resolution, scanner result, or deployment does not
  imply a Jira status, assignment, comment, or transition. Treat each external
  Jira mutation as a separate approved action.

## Privacy and sharing

- Redact credentials, tokens, secrets, personal data, customer payloads, and
  unrelated issue content before copying Jira evidence into artifacts, chat,
  tickets, or documents.
- Preserve the source reference and enough field path or shape to make the
  observation reviewable without copying unnecessary sensitive content.
- Record when an attachment, comment, or field was unavailable or redacted;
  absence of visible content is not evidence that the source was empty.

## Playbook use

- Technical Spike uses this integration for the Spike ticket, bounded hierarchy context, and linked research material.
- Feature Delivery uses this integration for issue and hierarchy context recovery.
- TechOps Issue Remediation uses it for issue reports, comments, attachments,
  links, and related operational work.
- Vulnerability Investigation may use it for `VULN-*` work-item context and
  related tickets; scanner or advisory evidence remains usable when Jira is not
  configured or is only an optional supporting source.

The selected playbook owns worker order, claims, approvals, fan-in, and durable
artifacts. This integration only defines how Jira evidence is scoped, retrieved,
normalized, refreshed, and separated from external writes.
