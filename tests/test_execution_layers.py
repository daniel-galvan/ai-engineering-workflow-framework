"""Keep shared workflow invariants separate from provider and source policies."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ExecutionLayers(unittest.TestCase):
    def test_core_keeps_invariants_and_normalized_seams_without_concrete_operations(self):
        core = (ROOT / "contracts/workflow_execution.md").read_text()
        for number in range(1, 42):
            self.assertIn(f"`INV-{number:02d}`", core)
        for heading in ("# Human Control Model", "# Work-Item Read Contract", "# Worker Contract",
                        "# Stage Completion and Fan-In", "## Worker Runtime Closure", "# Workflow State Machine"):
            self.assertIn(heading, core)
        for detail in ("MCP", "Atlassian", "Rovo", "Codex", "browser", "spawn_agent", "create_thread", "fork_thread",
                       "send_message_to_thread", "fork_context", ".codex/agents", "list_agents", "read_thread",
                       "wait_threads", "source_access_receipt.py", "plugin-backed launcher"):
            with self.subTest(detail=detail):
                self.assertNotIn(detail, core)
        self.assertIn("../providers/README.md", core)
        self.assertIn("../integrations/jira.md#read-path", core)

    def test_adapter_preserves_launch_routing_activation_and_closure_controls(self):
        adapter = (ROOT / "providers/codex.md").read_text()
        for control in ("first framework tool call", "direct Atlassian MCP connector first", "source_access_receipt.py",
                        "worker_activation_attempts: 0", "plugin_revision_mismatch", "fork_context: false",
                        "spawn_agent", "Never use `create_thread`", "fork_thread", "send_message_to_thread",
                        "list_agents", "read_thread", "wait_threads", "terminal_observations",
                        "does not assert capacity release", "worker_runtime_release_unavailable"):
            with self.subTest(control=control):
                self.assertIn(control, adapter)
        self.assertIn("../integrations/jira.md#feature-delivery-source-access-gate", adapter)

    def test_idle_worker_corrections_require_an_execution_triggering_dispatch(self):
        for path in ("providers/codex.md", "skills/run/SKILL.md"):
            text = (ROOT / path).read_text()
            self.assertIn("followup_task", text)
            self.assertIn("does not start an idle worker", text)

    def test_jira_owns_source_coverage_and_failures_and_sentry_owns_acquisition(self):
        jira = (ROOT / "integrations/jira.md").read_text()
        for policy in ("## Feature Delivery Source-Access Gate", "at most one distinct configured Jira connector",
                       "not connector-wide authentication failures", "Inventory every member of that collection",
                       "## Freshness and reconciliation", "## Write boundary", "## Privacy and sharing"):
            with self.subTest(policy=policy):
                self.assertIn(policy, " ".join(jira.split()) if "at most one" in policy else jira)
        self.assertIn("../contracts/workflow_execution.md#work-item-read-contract", jira)
        sentry = (ROOT / "integrations/sentry.md").read_text()
        self.assertIn("## Acquisition Ownership", sentry)
        self.assertIn("Before Evidence Topology activation", sentry)
        self.assertIn("## Source-Access Gate", sentry)

    def test_access_observations_preserve_the_prepared_input_manifest(self):
        launcher = " ".join((ROOT / "skills/run/SKILL.md").read_text().split())
        self.assertIn("Run filename discovery in a separate tool result from content reads or searches", launcher)
        for name in ("skills/run/SKILL.md", "contracts/workflow_execution.md"):
            text = " ".join((ROOT / name).read_text().split())
            with self.subTest(file=name):
                self.assertIn("Before preparation", text)
                self.assertIn("access-status updates in the source manifest before", text)
                self.assertIn("`run_inputs.json` is frozen; do not edit it or replace its recorded hash", text)
                self.assertIn("Record later access observations in the current-run evidence and work record", text)

    def test_sentry_access_failure_stops_before_preparation_without_log_fallback(self):
        launcher = (ROOT / "skills/run/SKILL.md").read_text()
        gate = launcher.split("5b. For Sentry Issue Remediation", 1)[1].split("6. For Standard Sentry planning", 1)[0]
        for phrase in ("issue and its latest event", "--source Sentry", "OPERATION_UNAVAILABLE",
                       "zero worker activation attempts", "no artifact root or work record",
                       "Supplied logs do not", "explicitly selects an offline", "30 seconds", "90 seconds"):
            self.assertIn(phrase, gate)
        investigator = (ROOT / "providers/codex/agents/sentry_current_state_investigator.toml").read_text()
        self.assertIn("return a blocked result with `required_source_unavailable` immediately", investigator)
        self.assertNotIn("fallback search and stop with bounded uncertainty", investigator)
        for file in ("templates/sentry_issue_run_prompt.md", "providers/codex/agents/sentry_orchestrator.toml"):
            text = (ROOT / file).read_text()
            self.assertIn("required_source_unavailable", text)
            self.assertIn("Supplied logs do not waive", text)
        playbook = (ROOT / "playbooks/sentry_issue_remediation.md").read_text()
        self.assertNotIn("then retain `supplied_occurrence` and the bounded uncertainty", playbook)

    def test_sentry_uses_existing_source_access_receipt(self):
        from datetime import datetime
        from scripts.source_access_receipt import blocked_receipt

        for code in ("OPERATION_UNAVAILABLE", "PERMISSION_DENIED", "UNAUTHENTICATED", "NOT_FOUND", "TIMEOUT"):
            with self.subTest(code=code):
                receipt = blocked_receipt("Sentry", "ISSUE-1", "issue_event_read", code,
                                          "2026-10-13T12:00:00Z",
                                          observed_at=datetime.fromisoformat("2026-10-13T12:00:30+00:00"))
                self.assertEqual(receipt["status"], "blocked")
                self.assertEqual(receipt["reason"], "required_source_unavailable")
                self.assertEqual(receipt["worker_activation_attempts"], 0)
                self.assertIsNone(receipt["artifact_root"])

    def test_cross_layer_links_resolve_to_existing_headings(self):
        for name in ("contracts/workflow_execution.md", "providers/codex.md", "integrations/jira.md"):
            source = ROOT / name
            for target, anchor in re.findall(r"\]\(([^()]+\.md)#([^()]+)\)", source.read_text()):
                destination = (source.parent / target).resolve()
                if destination == source:
                    continue
                headings = re.findall(r"^#+ (.+)$", destination.read_text(), re.M)
                slugs = {re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-") for heading in headings}
                with self.subTest(source=name, link=f"{target}#{anchor}"):
                    self.assertIn(anchor, slugs)


if __name__ == "__main__":
    unittest.main()
