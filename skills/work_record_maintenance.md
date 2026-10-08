---

title: Work-Record Maintenance
version: 0.5.2
status: Pilot
category: Documentation
provider_independent: true
owner: Engineering
last_updated: 2026-10-08
---

# Work-Record Maintenance

> Keep the durable work record current enough for another engineer or AI to resume without rediscovery.

## Inputs

* Current work record
* Findings, evidence, decisions, errors, and validation results
* Role and stage outputs

## Produces

* Updated `work_record.md`
* Decision and evidence history
* Current risks and unknowns
* Next steps and handoff state

## Completion Criteria

The record reflects current scope, reasoning, status, evidence, and next action.

## Safety

Separate facts, inferences, hypotheses, and unknowns. Do not replace technical decisions with summaries.

For generated terminal records, update `finalization_packet.json` and source receipts, then rerun the packaged
finalizer. Keep detailed operational data in the linked `finalization_snapshot.<sha256>.json`; keep engineering
conclusions and a compact status summary in Markdown. Preserve the linked snapshot when archiving or transferring
the record. Do not edit generated Markdown or silently migrate historical records.
