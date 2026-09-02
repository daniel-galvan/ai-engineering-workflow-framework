# Normalized Sentry Evidence Contract

Write one current-run evidence artifact at the assigned `normalized_evidence.md` path. Preserve exact field names,
field-local coordinates, repository paths, source references, and material uncertainty. Do not include historical-run or
memory evidence unless the user explicitly supplied it for this run.

Use these sections:

1. `# Normalized Evidence`
2. `## Run Scope` — work item, evidence-source classification, declared repositories, and query limits used. When
   no stable Sentry issue identifier was supplied, state `Sentry issue: not supplied` and
   `Sentry identity: unresolved (no stable Sentry issue identifier supplied)`. A work-item key is not treated as a
   Sentry issue identifier.
3. `## Source Register` — stable evidence IDs, exact source or path, observation, authority, and verification status.
4. `## Confirmed Facts` — facts with evidence references; do not mix hypotheses into this section.
5. `## Best Current Hypotheses` — each hypothesis, supporting and contradicting evidence, confidence, and limits.
6. `## Topology` — emitter, comparison owner, baseline producer, deployed route owner, candidate divergence owner, and
   confirmed defect owner. Use `Not established` where the current run does not establish a role.
7. `## Uncertainty and Checks Remaining` — unresolved items and the smallest check that could change the disposition.
8. `# Contract Delta` — the exact table below.

```markdown
| Boundary | Representation | Field identity / coordinate space | Evidence refs |
| --- | --- | --- | --- |
| Baseline | ... | ... | ... |
| Outbound | ... | ... | ... |
| Destination input | ... | ... | ... |
| Return | ... | ... | ... |
| Semantic input equivalence | equivalent, not_equivalent, or not_established | ... | ... |
```

The worker must validate the completed artifact with the assigned packaged validator before returning. Reading the
validator implementation or regression fixtures is not part of the evidence assignment.
