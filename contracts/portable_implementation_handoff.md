---
title: Portable Implementation Handoff Contract
version: 0.3.2
status: Pilot
owner: Engineering
last_updated: 2026-08-21
depends_on:
  - ./workflow_execution.md
---

# Portable Implementation Handoff Contract

When a planning run reaches `ready_for_implementation`, the Documenter MAY create `implementation_handoff.md` beside
`implementation_plan.md` only when implementation will happen in another session or environment, or when the user
explicitly requests a self-contained transfer file. Same-session implementation does not require a handoff. The
implementation plan remains the canonical design artifact; the handoff is a derived artifact.

The portable handoff MUST:

- contain the work item, target repository identity, target branch and starting revision, scope, exclusions, evidence
  summary, decisions, approval status, exact source changes, validation plan, environment preflight, stop conditions,
  rollback, and final reporting requirements;
- use repository identity, remote references, and commits instead of source-environment absolute paths;
- include enough evidence and reasoning to execute without chat history, framework-relative links, or the source
  environment's work-record directory; and
- state whether implementation approval is pending, approved, superseded, or complete.

The receiving session MUST start at the target Git repository root, verify its identity and current branch, and run the
environment preflight before changing source. For a monorepo, it MUST remain at the repository root. A material
repository, branch, or scope mismatch requires a recorded decision. A pending handoff MUST NOT be treated as approval;
explicit approval in the receiving session must be recorded before source changes.

One implementation approval covers every in-scope handoff step. The receiving session MUST NOT ask for approval after
each implementation slice. It MUST stop for a new decision only when new evidence changes approved scope or design, an
unapproved external or irreversible action is required, or a genuine environment, permission, review, or validation
blocker prevents progress.

The handoff can be executed without a framework checkout. If provider-specific agents or runtime delegation are
unavailable, the session MUST record actual model, effort, worker execution, review independence, and validation
results. It MUST NOT claim framework-profile execution, independent review, fan-in, or provider settings that were not
observed.
