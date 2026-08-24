# Roadmap

Current behavior and exercise status live in [README.md](README.md), [PLAYBOOK_CATALOG.md](PLAYBOOK_CATALOG.md), and the
playbooks. This file lists only planned evolution.

## Next validation

- Evaluate the v0.3.2 prompt and controls with the existing model baseline on comparable real runs.
- Measure control fidelity, authoritative-input consumption, human intervention, elapsed time, and wait time.
- Exercise more Vulnerability Investigation Deep planning and remediation scenarios.
- Reduce Deep elapsed and wait time without skipping required workers, gates, or fan-in.
- Improve remediation completion reliability across all four playbooks.
- Perform a cross-playbook failure audit after collecting comparable v0.3.2 run evidence.

## Expansion freeze

Do not add playbooks or execution abstractions during the current pilot. First validate the four existing playbooks
through remediation, Code Review, validation, and handoff; simplify any rules that real runs prove unnecessary.

After that, reconsider scenario coverage and framework evolution only when a validated gap cannot be expressed by the
existing contract, roles, skills, stages, gates, and artifacts.
