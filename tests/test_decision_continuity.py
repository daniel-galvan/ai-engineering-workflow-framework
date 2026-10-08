"""Contract regressions for continuation guidance, not live agent behavior."""

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DecisionContinuity(unittest.TestCase):
    def test_shared_rule_preserves_decisions_without_granting_approval(self):
        text = (ROOT / "contracts/workflow_execution.md").read_text()
        section = text.split("### Decision Continuity in Continuation Reviews\n", 1)[1]
        section = section.split("\n## ", 1)[0]
        for rule in (
            "Preserving accepted behavior is not a new product decision.",
            "Existing code alone does not establish product approval.",
            "does not grant missing implementation or external-action approval.",
            "Stop rereading settled evidence once the named question is resolved.",
            "show the observable failure, affected requirement, existing handling,",
        ):
            with self.subTest(rule=rule):
                self.assertIn(rule, section)

    def test_receiving_instructions_retain_approval_and_bounded_review(self):
        text = (ROOT / "templates/implementation_handoff.md").read_text()
        for rule in (
            "do not request new approval for unchanged accepted behavior.",
            "implementation approval is still required before source changes.",
            "Each additional check must name the decision it could change;",
            "Confirm that `Handoff status` is `Approved`",
        ):
            with self.subTest(rule=rule):
                self.assertIn(rule, text)
        coordinator = (ROOT / "providers/codex/agents/orchestrator.toml").read_text()
        self.assertIn("Overall implementation approval still applies.", coordinator)

    def test_example_covers_preservation_and_reopening(self):
        text = (ROOT / "examples/feature_delivery.md").read_text()
        for scenario in (
            "Accepted decision, current decoder, and existing unit test agree",
            "Current requirement explicitly replaces the old compatibility rule",
            "no accepted decision supports it",
            "A new supported path makes the old fallback expose private data",
            "implementation approval is pending",
            "Check the actual consumer and observable failure first;",
        ):
            with self.subTest(scenario=scenario):
                self.assertIn(scenario, text)


if __name__ == "__main__":
    unittest.main()
