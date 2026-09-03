---

title: Failure Diagnosis
version: 0.4.16
status: Pilot
category: Analysis
provider_independent: true
owner: Engineering
last_updated: 2026-07-28
---

# Failure Diagnosis

> Reproduce, minimize, explain, and validate a failure before implementing its fix.

## Inputs

* Failure evidence such as a Sentry issue, event, log, trace, or report
* Repository and revision associated with the failure
* Current work record
* Relevant runtime and dependency context
* User-supplied context and supporting artifacts

## Produces

* Reproduction or verification attempt
* Minimized failure description
* Code-path analysis
* Competing root-cause hypotheses
* Evidence-based root-cause conclusion
* Fix boundary and regression-test strategy
* Executed falsification check or local feedback-loop result
* Remaining checks that require unavailable external evidence

## Completion Criteria

The failure is reproduced, verified against direct evidence, or explicitly classified as not reproducible with the
reason and remaining uncertainty documented. Before requesting clarification, consume the available context and
artifacts, record the strongest supported hypothesis or explain why none is possible, and execute the smallest safe
falsification check. A proposed check is not enough. The recommended fix addresses the confirmed cause rather than
only the reported symptom.

## Safety

Do not infer root cause from an exception title alone. Preserve sensitive data boundaries, redact personally
identifiable information, and do not change code until the diagnosis reaches the playbook's implementation gate.
