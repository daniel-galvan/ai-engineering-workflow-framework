"""Mandatory presentation text is advisory and must preserve canonical content."""

import json
import tempfile
import unittest
from pathlib import Path

from scripts.run_preflight import mandatory_presentation_notice


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
                self.assertEqual(mandatory_presentation_notice(source), expected)
            rows[-1]["payload"]["content"][0]["text"] = "Run the Sentry playbook again"
            rows.append({"type": "response_item", "payload": {"role": "assistant", "phase": "final_answer"}})
            source.write_text("\n".join(json.dumps(row) for row in rows))
            self.assertFalse(mandatory_presentation_notice(source))
            source.write_text(json.dumps({"type": "response_item", "payload": {"role": "user",
                                         "content": [{"text": developer}]}}))
            self.assertFalse(mandatory_presentation_notice(source))


class PresentationVerification(unittest.TestCase):
    def test_required_footer_and_banner_preserve_canonical_bytes(self):
        from scripts.finalize_work_record import verify_presentation
        canonical = b"Workflow result: complete\nArtifacts: [plan](plan.md)\n"
        for prefix, suffix in ((b"", b""), (b"Required banner\n", b""),
                               (b"", b"Not checked: production.\nRisk: unverified live execution.\n"),
                               (b"Banner\n", b"Footer\n")):
            verify_presentation(canonical, prefix + canonical + suffix, prefix, suffix)
            with self.assertRaisesRegex(ValueError, "handoff_response_mismatch"):
                verify_presentation(canonical, prefix + canonical.replace(b"complete", b"failed") + suffix, prefix, suffix)
        with self.assertRaises(ValueError):
            verify_presentation(canonical, canonical + b"Undeclared footer")
