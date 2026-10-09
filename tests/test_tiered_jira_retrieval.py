"""Bounded Jira context is valid; selected scopes retain their evidence gates."""

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class TieredJiraRetrieval(unittest.TestCase):
    def test_canonical_fixture_starts_with_exact_issue(self):
        fixture = json.loads((ROOT / "tests/fixtures/jira_adapter_contract.json").read_text())
        self.assertEqual(fixture["request"]["scope"], ["item"])
        self.assertEqual(fixture["result"]["state"], "complete")
        self.assertIn("not queried", fixture["result"]["limitations"][0])

    def test_callers_do_not_reinstate_blanket_retrieval(self):
        forbidden = (
            "request `item`, `hierarchy`, `selected_links`, and `history` together",
            "For every Jira-backed playbook, the context read MUST include",
            "For every Jira-backed assignment, enumerate",
            "parent and direct siblings of a supplied child",
            "recover and record their complete direct inventory",
            "Enumerate the Jira sibling summary roster",
        )
        for name in ("integrations/jira.md", "skills/work_item_context.md", "skills/run/SKILL.md",
                     "providers/codex/agents/current_state_investigator.toml",
                     "providers/codex/agents/orchestrator.toml", "scripts/prepare_run.py"):
            text = " ".join((ROOT / name).read_text().split())
            for phrase in forbidden:
                with self.subTest(file=name, phrase=phrase):
                    self.assertNotIn(phrase, text)

    def test_required_playbook_gates_and_scope_limits_remain(self):
        feature = " ".join((ROOT / "playbooks/feature_delivery.md").read_text().split())
        self.assertIn("require the complete direct-child inventory", feature)
        self.assertIn("Every Feature Delivery run MUST create `asset_manifest.json`", feature)
        self.assertIn("supplied issue and selected related issues", feature)
        jira = " ".join((ROOT / "integrations/jira.md").read_text().split())
        self.assertIn("Empty collections require a successful query", jira)
        self.assertIn("unselected optional scope does not block a bounded conclusion", jira)
        self.assertIn("not as a result state", jira)
        for name in ("technical_spike", "feature_delivery", "techops_issue_remediation", "vulnerability_investigation"):
            text = (ROOT / f"playbooks/{name}.md").read_text()
            self.assertIn("exact", text)
            self.assertIn("stop", text)


if __name__ == "__main__":
    unittest.main()
