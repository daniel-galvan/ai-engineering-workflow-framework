---
title: Contributing to the AI-assisted Software Engineering Workflow Framework
version: 0.5.20
status: Pilot
owner: Engineering
last_updated: 2026-10-08
---

# Contributing

Keep the framework provider-neutral, composable, evidence-driven, and small.

For architecture and building blocks, see the [README](README.md); for run procedures, see the
[Operating Guide](OPERATING_GUIDE.md). This file explains how to extend and validate the framework.

## Change rules

1. Reuse an existing role or skill before adding one.
2. Add a skill only when the capability is reusable across playbooks.
3. Add a playbook only when the scenario needs distinct stages, dependencies, gates, or artifacts.
4. Keep provider-specific model, effort, and tool behavior in `providers/`; do not put it in a provider-neutral
   playbook.
5. Keep lifecycle, worker activation, fan-in, recovery, approval, handoff, and claims/evidence/decision/action rules in
   the shared contracts.
6. Keep canonical plugin-input templates in sync with the shared prompt contract; do not create one-off input formats.
7. Keep work records in the main execution repository under `.thoughts/<WORK-ITEM-ID>/`; do not commit real
   work-item context here.
8. Record verified facts, hypotheses, unknowns, blockers, and limitations separately.
9. Keep plugin packaging thin: launcher and metadata files may route into the framework, but must not redefine
   contracts, playbooks, templates, roles, skills, or provider policy.

## Adding a playbook

Reuse the shared contract and declare:

- purpose and selection criteria;
- inputs and evidence sources;
- stages, worker dependencies, and fan-in;
- roles, skills, tools, and provider mappings;
- supported lifecycles and their behavior;
- approval gates and failure behavior;
- artifacts, validation, and terminal outcomes; and
- a canonical run template and safe example.

Exercise the playbook against a real work item before calling it validated.

## Updating the Codex plugin

Because the plugin packages this repository, every tracked content change affects the installed package:

1. keep `.codex-plugin/plugin.json`, `.agents/plugins/marketplace.json`, `skills/run/`, and `scripts/run_preflight.py`
   consistent with the repository layout;
2. align the plugin's base version with the coordinated framework release and refresh its single `+codex.<timestamp>`
   cache-busting suffix before packaging or installing the changed snapshot;
3. run the framework validator and preflight self-test; they reject changed package content that reuses a plugin build
   identity;
4. reinstall the plugin and test it in a new Codex task.

Do not change framework document versions merely because the plugin cache-buster changed.

## Markdown format

- Use 120 columns as the preferred prose wrap width and never exceed it. Break at sentence or clause boundaries; do not
  preserve an 80-column wrap or force every paragraph to the same visual width.
- Keep Markdown headings as real headings, such as `## Section name`. Do not bold a heading marker, such as
  `**## Section name**`.
- Keep each table row on one line so the table remains portable Markdown.
- Preserve fenced code, commands, URLs, and other intentionally long technical values; the 120-column rule applies to
  prose, not those structures.
- Leave a blank line before headings, lists, tables, and fenced code blocks.

## Validation

From the repository root, run:

```bash
python3 scripts/validate_library.py --self-test
python3 scripts/run_preflight.py --self-test
python3 scripts/prepare_run.py --self-test
python3 scripts/finalize_work_record.py --self-test
python3 -m unittest discover -s tests -p 'test_*.py'
```

To validate a terminal work record's identity and referential integrity, supply its path:

```bash
python3 scripts/validate_library.py /path/to/.thoughts/WORK-ITEM/work_record.md
```

The validator checks document semantic versions, Markdown prose width and table structure, TOML syntax, playbook
maturity, template consistency, provider-adapter coverage, and Codex policy/TOML alignment.

`scripts/validate_library.py` is the CLI; `scripts/validation/library.py` coordinates library checks in their
established fail-fast order. Rules live in `scripts/validation/`, grouped into front matter, Markdown, contracts,
playbooks, roles, provider policy, templates, work records, and finalization. Shared constants and reference helpers
live in `common.py` and `references.py`; the existing regression self-tests live in `self_tests.py`.
Imports do not run validation.
Add focused tests under `tests/` when changing rules; preserve CLI failure messages, check order, and finalization
output. Both `python3 scripts/validate_library.py` and `python3 -m scripts.validate_library` support the same arguments.

## Version policy

Versioned framework documents and the plugin base version use one coordinated release number. A release update changes
every canonical document's `version` and `last_updated` together. Changes staged within a release retain its baseline
until the next coordinated release; Git revisions and the plugin build suffix distinguish those snapshots.

The plugin base version is the canonical library release number. The date in `frameworks/investigation.md` defines the
canonical release update date. The validator rejects documents whose versions or dates differ from that baseline.
Historical fixtures retain their recorded identities, and generated work artifacts use their actual creation or update
timestamps. Update only canonical front matter during a release; preserve dynamic version and timestamp expressions.

After changing a document version, adding or removing a versioned document, changing a provider policy baseline, or
refreshing the plugin package version, run `python3 scripts/framework_manifest.py --write`. The generated
[`framework_manifest.json`](framework_manifest.json) inventories canonical metadata; edit the source documents or plugin
manifest rather than editing its generated values. The framework validator checks that the inventory is current.
Cross-revision compatibility ranges remain unassigned; aligned versions do not imply compatibility or live validation.

Playbook front matter also owns maturity, exercise scope, and validation summary. Refresh those claims when new run
evidence changes them, without treating a document revision as successful exercise evidence. After changing playbook
metadata or adding/removing a playbook, run `python3 scripts/playbook_catalog.py --write` to refresh the generated
exercise-state table. Keep catalog architecture and selection guidance authored; the validator checks the generated
block and fails if it is stale, missing, or malformed.

Declare `supported_lifecycles` explicitly as `planning` or `planning, remediation`. Each playbook must also declare
`exercise_status_standard_planning`, `exercise_status_deep_planning`, `exercise_status_standard_remediation`, and
`exercise_status_deep_remediation`. These flat scalar fields keep the existing front-matter reader sufficient.
Use `pending` when current evidence is insufficient, `exercised` for observed runs, `validated` only for supported
validation evidence, and `unsupported` for lifecycles the playbook cannot execute. The catalog generator and library
validator reject missing or invalid statuses and conflicts with supported lifecycles. Exercise scope records coverage;
it does not certify every current dependency revision. Keep historical exercise evidence and current limitations in
`validation_summary`; do not infer validation from a document version or a static test pass.
