---
title: Contributing to the AI-assisted Software Engineering Workflow Framework
version: 0.1
status: Pilot
owner: Engineering
---

# Contributing

Keep the framework provider-neutral, composable, evidence-driven, and small.

For the architecture and building-block map, see the [README](README.md) and
the detailed [Operating Guide](OPERATING_GUIDE.md). This file focuses only on
how to extend the framework.

## Change rules

1. Reuse an existing role or skill before adding one.
2. Add a skill only when the capability is reusable across playbooks.
3. Add a playbook only when the scenario needs distinct stages, dependencies,
   gates, or artifacts.
4. Keep provider-specific model, effort, and tool behavior in
   `providers/`; do not put it in a provider-neutral playbook.
5. Keep lifecycle, worker activation, fan-in, recovery, approval, handoff, and
   claims/evidence/decision/action rules in the shared contracts.
6. Use the canonical run-template format. Update the template when the shared
   prompt contract changes; do not create one-off prompt formats.
7. Keep work records in the execution repository under
   `.thoughts/<WORK-ITEM-ID>/`; do not commit real work-item context here.
8. Record verified facts, hypotheses, unknowns, blockers, and limitations
   separately.

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

## Validation

From the repository root, run:

```bash
python3 scripts/validate_library.py
```

The validator checks document versions, TOML syntax, Markdown table structure,
playbook maturity, template consistency, provider-adapter coverage, and Codex
policy/TOML alignment.

## Version policy

All versioned documents remain at `0.1` during ordinary pilot evolution.
Change a version only when an explicit named release or version update is
requested.
