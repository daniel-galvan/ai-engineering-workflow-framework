---

title: Sentry Integration
version: 0.3.1
status: Pilot
provider: mcp
owner: Engineering
last_updated: 2026-07-28
---

# Sentry Integration

Sentry supplies production failure evidence to the Sentry Issue Remediation Playbook through MCP.

## Read operations

Use the narrowest operation that answers the current question:

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
