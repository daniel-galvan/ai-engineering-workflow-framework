"""The recorded mandatory reminder must block before a workflow starts."""

import json
import tempfile
import unittest
from pathlib import Path

from scripts.run_preflight import handoff_instruction_conflict


class HandoffInstructionConflict(unittest.TestCase):
    def test_mandatory_reminder_and_explicit_invocation_exception(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "parent.jsonl"
            developer = "begin the first final answer with Developer Workflows skills are available"
            for request, expected in (("Run the Sentry playbook", True),
                                      ("$dev-workflows:dev-clarify-requirements", False)):
                rows = [{"type": "response_item", "payload": {"role": role,
                         "content": [{"type": "input_text", "text": text}]}}
                        for role, text in (("developer", developer), ("user", request))]
                source.write_text("\n".join(json.dumps(row) for row in rows))
                self.assertEqual(handoff_instruction_conflict(source), expected)
            rows[-1]["payload"]["content"][0]["text"] = "Run the Sentry playbook again"
            rows.append({"type": "response_item", "payload": {"role": "assistant", "phase": "final_answer"}})
            source.write_text("\n".join(json.dumps(row) for row in rows))
            self.assertFalse(handoff_instruction_conflict(source))
            source.write_text(json.dumps({"type": "response_item", "payload": {"role": "user",
                                         "content": [{"text": developer}]}}))
            self.assertFalse(handoff_instruction_conflict(source))
