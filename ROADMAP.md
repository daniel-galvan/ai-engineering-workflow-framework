# Roadmap

Current behavior and exercise status live in [README.md](README.md), [PLAYBOOK_CATALOG.md](PLAYBOOK_CATALOG.md), and the
playbooks. This file lists only planned evolution.

## Next validation

- Evaluate the v0.3.0 prompt, control, and model baseline on comparable real runs.
- Measure control fidelity, authoritative-input consumption, human intervention, elapsed time, and wait time.
- Reduce Deep elapsed and wait time without skipping required workers, gates, or fan-in.
- Improve remediation completion reliability across all four playbooks.
- Confirm source-to-destination Feature Delivery coverage under v0.3.0.
- Perform a cross-playbook failure audit after collecting comparable v0.3.0 run evidence.

## Expansion freeze

Do not add playbooks or execution abstractions during the current pilot. First validate the four existing playbooks
through remediation, Code Review, validation, and handoff; simplify any rules that real runs prove unnecessary.

After that, reconsider scenario coverage and framework evolution only when a validated gap cannot be expressed by the
existing contract, roles, skills, stages, gates, and artifacts.
