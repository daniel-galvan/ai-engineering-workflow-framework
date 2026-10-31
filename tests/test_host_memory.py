"""Host memory access must remain read-only and limited to the host's files."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.host_memory import host_memory_read, host_memory_rollouts, host_memory_root


class HostMemoryTest(unittest.TestCase):
    def test_native_authority_and_read_boundaries(self):
        with tempfile.TemporaryDirectory() as directory:
            codex = Path(directory) / "codex home"
            root = codex / "memories"
            root.mkdir(parents=True)
            registry = root / "MEMORY.md"
            registry.write_text("entry\n")
            notes = root / "rollout_summaries"
            notes.mkdir()
            (notes / "prior.md").write_text("context\n")
            outside = Path(directory) / "secret.md"
            outside.write_text("secret\n")
            (notes / "escape.md").symlink_to(outside)
            session = Path(directory) / "session.jsonl"
            directive = {"type": "response_item", "payload": {"type": "message", "role": "developer",
                         "content": [{"type": "input_text", "text": "Decision boundary MEMORY_SUMMARY " + str(registry)}]}}
            session.write_text(json.dumps(directive) + "\n")
            with patch.dict(os.environ, {"CODEX_HOME": str(codex)}):
                trusted = host_memory_root(session)
                self.assertEqual(trusted, root.resolve())
                for command in (f"rg -n -F ITEM '{registry}'", f"sed -n '1,20p' '{notes / 'prior.md'}'",
                                f"nl -ba '{registry}' | sed -n '1,20p'", f"rg -n ITEM '{registry}' | head -25",
                                f"rg -n -C 2 'ITEM|service' '{registry}'",
                                f"rg --no-config -S -A2 -B 0 --context=3 -m 5 ITEM '{registry}'"):
                    with self.subTest(command=command):
                        self.assertTrue(host_memory_read(command, trusted))
                for command in (f"cat '{notes / 'escape.md'}'", f"cat '{outside}'",
                                f"cat '{registry}' ; cat '{outside}'", f"cat '{registry}' > '{outside}'",
                                f"rg -n '$(whoami)' '{registry}'", f"cat '{registry}' | head -n 3 | cat",
                                f"cat '{root / 'other.md'}'", f"rg -C -1 ITEM '{registry}'",
                                f"rg -C 2 --pre whoami ITEM '{registry}'",
                                f"rg -C 2 -f '{outside}' '{registry}'",
                                f"rg --context=2 ITEM '{registry}' '{outside}'"):
                    with self.subTest(command=command):
                        self.assertFalse(host_memory_read(command, trusted))
                sessions = codex / "sessions"
                sessions.mkdir()
                linked = sessions / "prior.jsonl"
                linked.write_text("{}\n")
                discovered = host_memory_rollouts("rollout_path=`" + str(linked) + "`", trusted)
                self.assertFalse(host_memory_read(f"cat '{linked}'", trusted))
                self.assertTrue(host_memory_read(f"cat '{linked}'", trusted, discovered))
                self.assertFalse(host_memory_read(f"cat '{outside}'", trusted, discovered))
                directive["payload"]["content"][0]["text"] = (
                    "Decision boundary MEMORY_SUMMARY\n- " + str(registry) + " (searchable registry; primary file)")
                session.write_text(json.dumps(directive) + "\n")
                with patch.dict(os.environ, {"CODEX_HOME": str(Path(directory) / "different-home")}):
                    self.assertEqual(host_memory_root(session), root.resolve())
                directive["payload"]["role"] = "user"
                session.write_text(json.dumps(directive) + "\n")
                self.assertIsNone(host_memory_root(session))


if __name__ == "__main__":
    unittest.main()
