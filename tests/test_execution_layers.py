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
        self.assertIn("before Evidence Topology activation", sentry)

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
