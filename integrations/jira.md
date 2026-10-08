---
title: Jira Integration
version: 0.5.20
status: Pilot
provider_independent: true
owner: Engineering
last_updated: 2026-10-08
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

## Feature Delivery Source-Access Gate

Before initializing a Jira-backed Feature Delivery run, read the exact supplied issue through an available configured
connector after the selected adapter's launch-readiness checks. Concrete connector preference, operations, launcher
sequencing, and blocked-receipt rendering belong to the provider adapter; for Codex, see its
[launcher rules](../providers/codex.md#launcher-and-package-preflight) and
[Jira read mapping](../providers/codex.md#jira-work-item-read-mapping).

Bind the successful connector and issue-read operation to the context worker. A resource lookup on one connector MUST
NOT authorize reads through another. On authentication failure or an absent issue-read operation, try at most one
distinct configured Jira connector, never another operation on the failed route. If neither route succeeds, stop before
initialization, preparation, input-manifest creation, or worker activation. Record the attempted source and operation,
safe failure code, and one access-restoration action. Create no artifact root or work record; this is not an assessment
disposition. `not_found` and `permission_denied` are item-specific outcomes, not connector-wide authentication failures.
A successful item read does not prove hierarchy, link, history, or asset access. For a required scope absent on the
selected connector, the worker may use one distinct alternative connector only after an exact-key read succeeds there;
it MUST record the route for each scope. A failed route is not silently retried. Other playbooks retain their own
source-access rules; do not probe optional sources.

## Read path

Start with `item`: read the exact issue's summary, current description, acceptance criteria, status, type, and
explicit constraints. The selected playbook states what evidence its question requires. Add a scope only for that
requirement or a recorded unresolved question; do not request `hierarchy`, `selected_links`, and `history` by default.

| Tier | Escalation trigger | Minimum Jira evidence |
| --- | --- | --- |
| Required | Jira is the work-item source | Exact issue by key or URL; current scope, criteria, status, type, and constraints |
| Parent / hierarchy | Scope is thin, inherited context is referenced, or the question concerns cross-issue coverage | Relevant parent/ancestors; direct-child inventory only when the question requires collection coverage |
| Linked issues | A reference, dependency, precedent, or conflicting requirement could change the answer | Selected issue or document with a recorded selection reason |
| History | Current fields cannot resolve a reported symptom, prior decision, or status/delivery conflict | Relevant comments or change history for selected issues |
| Attachments / remote links | Supplied or referenced assets, unresolved evidence, or a playbook asset gate requires them | Attachment/remote-link inventory and selected contents for in-scope issues |
| Write metadata | An explicitly approved external write is being prepared | Live project, issue-type, field, allowed-value, and transition metadata |

Record the question, selected scopes and issues, and stop condition in the normalized request's `selection_reason` and
context artifact. Reuse the successful exact-issue read; expand only the missing fields or collections. When the
question is answered, stop retrieval. Record unselected scopes as `not requested` in selection notes or limitations,
not as a result state, `empty`, or `unavailable`;
`complete` applies to the requested scope and does not imply all related work or assets were reviewed.

When collection coverage is required, page through the complete direct-child inventory for the supplied Epic or
selected parent, or the selected link/attachment collection. Inventory every member of that collection regardless of
type or status. A bounded summary roster may precede per-issue expansion: mark unopened records
`not selected; summary-only` with a reason, not as proven non-material. Fully read issues whose requirements,
dependencies, prior fixes, or assets could change the answer. A Done status alone does not establish relevance or
absence of output. Do not scan an entire project or recursively traverse unrelated links.

Empty collections require a successful query; failed, truncated, or unpaged collections are `partial` or `unavailable`.
Before downstream analysis or fan-in, reconcile coverage for the selected scopes in the context artifact and return
one correction to the owning worker for omissions. Missing indispensable evidence limits readiness; an unselected
optional scope does not block a bounded conclusion. Prior issues remain context, not inherited current-run requirements.

## Adapter Contract

The Jira adapter conforms to the shared
[Work-Item Read Contract](../contracts/workflow_execution.md#work-item-read-contract).
It maps Jira-specific reads to the shared scopes without exposing Jira API
shapes or provider-specific operation names:

| Shared scope | Jira-specific read |
| --- | --- |
| `item` | Direct issue read by exact key or URL. |
| `hierarchy` | Selected parent/ancestors; complete direct-child inventory only when collection coverage is required. |
| `selected_links` | Selected linked issues, pull requests, documents, or remote links relevant to the question. |
| `history` | Selected comments, change history, delivery records, or attachment inventory for in-scope issues; record which reads are required. |
| `write_metadata` | Live project, issue-type, field, allowed-value, and transition metadata before an approved write. |

The canonical offline fixture shape is
[`tests/fixtures/jira_adapter_contract.json`](../tests/fixtures/jira_adapter_contract.json).
It is tracked in this repository, bundled with the plugin, and validated by `python3 scripts/validate_library.py`;
it is not generated or downloaded during a run. It contains synthetic issue data, not live Jira evidence.

## Attachment and Asset Inventory

Inventory attachments on the supplied item and every issue selected under the applicable retrieval gate when the
playbook requires an asset inventory or an asset could answer the question. Inventory remote links separately when
selected; empty `issuelinks` or attachment fields do not prove an empty remote-link collection. Preserve owner issue,
source locator, retrieval method, availability, redaction, and review/disposition state for every discovered asset.
Review material assets' actual contents before using them as evidence: render or visually inspect images and video;
read logs and documents. Other discovered assets may remain `not selected` with a reason unless the playbook requires
complete review. An unread filename or count is not consumed evidence.

For a selected collection, preserve inaccessible, redacted, unsupported, or irrelevant assets explicitly. A missing
material asset remains `partial` or `unavailable` with its effect on the answer; never describe it as reviewed.
Reconcile selected issue and asset inventories before downstream analysis or fan-in. An omitted collection is not an
empty result. If `history` was selected for comments or changelog alone, preserve the normalized `assets` list and
state that attachment inventory was `not requested`; an empty list then makes no claim that Jira has no attachments.

For Feature Delivery, `feature-context` additionally produces the plan-level `asset_manifest.json` gate.
The normalized result must preserve each attachment's stable name/locator, type, availability, redaction state, and
retrieval limitation. A valid empty attachment collection is recorded as `empty`; an omitted attachment field is not an
empty result. If the connector cannot enumerate or retrieve the collection, record `unavailable`, `partial`, or
`permission_denied` with the attempted operation and keep planning at `awaiting_input` when the missing material could
change scope, acceptance, or the implementation boundary.

The Feature Delivery `asset_manifest.json` is the review-level companion to the normalized Jira read. It must include
the Jira attachment source even when the collection is empty, that source's `remote_link_inventory`, a source and asset
row for every remote link discovered within the selected issue scope, plus every explicitly supplied file, folder, or
URL source. It is not valid to cite the issue description, an attachment count, or a filename as proof that an image or
document was reviewed.

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

- Technical Spike starts with its exact ticket and expands only to evidence needed for the bounded question or review.
- Feature Delivery declares its related-work and asset needs in the playbook. Its asset
  review gate is not passed until the attachment collection and all declared supporting asset sources are explicitly
  accounted for.
- TechOps Issue Remediation requires the issue and report-bearing comments; other scopes answer named diagnosis gaps.
- Vulnerability Investigation may use it for `VULN-*` work-item context and
  related tickets; scanner or advisory evidence remains usable when Jira is not
  configured or is only an optional supporting source.

The selected playbook owns worker order, claims, approvals, fan-in, and durable
artifacts. This integration only defines how Jira evidence is scoped, retrieved,
normalized, refreshed, and separated from external writes.
