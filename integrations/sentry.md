---

title: Sentry Integration
version: 0.5.30
status: Pilot
provider: mcp
owner: Engineering
last_updated: 2026-10-23
---

# Sentry Integration

Sentry supplies production failure evidence to the Sentry Issue Remediation Playbook through MCP.

## Acquisition Ownership

Before Evidence Topology activation, the Coordinator performs only the required source-access gate below. After that
probe, Evidence Topology owns raw Sentry evidence acquisition and initial repository topology. The Coordinator MUST
NOT perform diagnosis or duplicate the worker's Sentry queries; pass the verified gate observations to the worker.

## Source-Access Gate

An explicit Sentry issue ID or URL makes live issue and latest-event access a prerequisite for `live_sentry` and
`mixed` runs. Before input-manifest creation, preparation, repository analysis, or worker activation, verify that a
configured route can read the exact issue and its latest event. Tool availability, organization visibility, and logs
containing emitted event IDs do not establish access or association with that issue.

Use at most one tool-discovery call. Try a configured direct MCP route first; after failure, at most one distinct
configured route may read the same records. Limit each read to 30 seconds and the complete gate to 90 seconds.
Missing operations, authentication failures, permission denial, missing records, or an exhausted access deadline stop
this invocation with `required_source_unavailable`. Preserve the attempted operation and safe provider error code;
do not retry an unchanged failed route, search unrelated issues/projects, or request credentials. The provider emits
its small source-access receipt with zero worker activation attempts and no artifact root or work record.

Supplied CloudWatch logs or other artifacts do not waive required live access. Do not silently downgrade `live_sentry`
or `mixed` to `supplied_occurrence`. An offline investigation requires the user's explicit selection of that scope;
record it without claiming the supplied data belongs to the inaccessible issue. A request containing only a supplied
occurrence and no live issue identity remains supported without Sentry access.

If required live access becomes unavailable after activation, stop further analysis and downstream worker activation,
report the access blocker, and close already-started workers. Preserve observations already collected; do not continue
Fix Design or source changes while waiting for access. Successful gate observations and the selected route are passed
to Evidence Topology for reuse rather than fetched again.

## Read operations

Use the narrowest operation that answers the current question:

Direct issue resolution requires a stable issue ID or URL plus the Sentry organization slug. A work-item key (for
example, a Jira-style `HEARSAYLABS-PYTHON3-J3V`) is not sufficient by itself. When the organization identity is absent,
do not send an issue request with an empty `organizationSlug`. If a live issue identity was explicitly requested,
stop at the source-access gate until the required identity is available. Use a supplied occurrence without live access
only when no live identity was requested or the user explicitly selected an offline investigation.

| Need | MCP capability |
| --- | --- |
| Issue details | `get_sentry_resource` with `resourceType: issue` |
| Representative event | `get_sentry_resource` with `resourceType: event` |
| Search grouped issues | `search_issues` |
| Search event history or counts | `search_events` |
| Optional root-cause assistance | `analyze_issue_with_seer` |

Seer is optional. Use it when the user requests it or repository evidence is insufficient to establish a root cause.
Treat its result as a hypothesis until validated against the repository and tests.

## Write operations

`update_issue` may resolve, reopen, ignore, or assign a Sentry issue. It is not part of automatic diagnosis or
implementation. Use it only after the code fix, validation, rollout decision, and human approval are complete.

## Evidence rules

Record issue and event URLs, timestamps, environments, releases, culprits, stack context, tags, breadcrumbs, and
occurrence history as evidence. Redact PII and secrets. Do not treat a Sentry stack trace as proof of current source
behavior until it is reconciled with the matching repository revision.

The event-emitting repository, suspected fault repository, and downstream or return-path repository may differ. Preserve
those roles separately in the work record instead of collapsing them into a single `repository` field.

## Boundaries

* MCP is the source for Sentry observations, not repository behavior.
* Sentry data may be incomplete, sampled, delayed, or release-mismatched.
* No Sentry status change is implied by a code change.
* Failed, unavailable, or permission-denied MCP calls are recorded as blockers.
