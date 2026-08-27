---
title: Contributing to the AI-assisted Software Engineering Workflow Framework
version: 0.4.3
status: Pilot
owner: Engineering
last_updated: 2026-08-27
---

# Contributing

Keep the framework provider-neutral, composable, evidence-driven, and small.

For the architecture and building-block map, see the [README](README.md) and the detailed [Operating
Guide](OPERATING_GUIDE.md). This file focuses only on how to extend the framework.

## Change rules

1. Reuse an existing role or skill before adding one.
2. Add a skill only when the capability is reusable across playbooks.
3. Add a playbook only when the scenario needs distinct stages, dependencies, gates, or artifacts.
4. Keep provider-specific model, effort, and tool behavior in `providers/`; do not put it in a provider-neutral
   playbook.
5. Keep lifecycle, worker activation, fan-in, recovery, approval, handoff, and claims/evidence/decision/action rules in
   the shared contracts.
6. Use the canonical run-template format. Update the template when the shared prompt contract changes; do not create
   one-off prompt formats.
7. Keep work records in the execution repository under `.thoughts/<WORK-ITEM-ID>/`; do not commit real work-item context
   here.
8. Record verified facts, hypotheses, unknowns, blockers, and limitations separately.
9. Keep plugin packaging thin: launcher and metadata files may route into the framework, but must not redefine
   contracts, playbooks, templates, roles, skills, or provider policy.

## Adding a playbook

Reuse the shared contract and declare:

- purpose and selection criteria;
- inputs and evidence sources;
- stages, worker dependencies, and fan-in;
- roles, skills, tools, and provider mappings;
- planning and remediation behavior;
- approval gates and failure behavior;
- artifacts, validation, and terminal outcomes; and
- a canonical run template and safe example.

Exercise the playbook against a real work item before calling it validated.

## Updating the Codex plugin

When a change affects the installed plugin package:

1. keep `.codex-plugin/plugin.json`, `.agents/plugins/marketplace.json`, `skills/run/`, and `scripts/run_preflight.py`
   consistent with the repository layout;
2. preserve the plugin's base version and refresh its single `+codex.<timestamp>` cache-busting suffix;
3. run the framework validator and verify the plugin JSON and launcher files; and
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
python3 scripts/validate_library.py
python3 scripts/validate_library.py /path/to/.thoughts/WORK-ITEM/work_record.md
```

The optional path performs terminal work-record identity and referential-integrity validation.

The validator checks document semantic versions, Markdown prose width and table structure, TOML syntax, playbook
maturity, template consistency, provider-adapter coverage, and Codex policy/TOML alignment.

## Version policy

Versioned documents evolve independently. Increment a document's semantic version when its contract or required
behavior changes; do not change unrelated document versions merely to keep them aligned.
