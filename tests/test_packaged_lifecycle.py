"""Exercise shipped entrypoints from a clean local package, without live workers."""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PackagedLifecycle(unittest.TestCase):
    def test_clean_package_preflight_preparation_audits_and_terminal_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory) / "package"
            shutil.copytree(ROOT, package, symlinks=True,
                            ignore=shutil.ignore_patterns(".git", ".thoughts", "__pycache__"))
            for args in (("init", "-q"), ("config", "user.name", "Package fixture"),
                         ("config", "user.email", "fixture@example.invalid"), ("add", "."),
                         ("commit", "-qm", "Synthetic package snapshot")):
                subprocess.run(["git", "-C", str(package), *args], check=True, capture_output=True)
            source = Path(directory) / "parent.jsonl"
            source.write_text("\n".join(json.dumps({"type": "response_item", "payload": {
                "role": role, "content": [{"text": text}]}}) for role, text in (
                ("developer", "begin the first final answer with Developer Workflows skills are available"),
                ("user", "Run the Sentry playbook"))))
            blocked = subprocess.run([sys.executable, "scripts/run_preflight.py", "--provider-session", str(source)],
                                     cwd=package, capture_output=True, text=True, timeout=60)
            self.assertEqual(blocked.returncode, 0, blocked.stdout + blocked.stderr)
            self.assertEqual(json.loads(blocked.stdout)["status"], "passed")
            self.assertIn("presentation_notice", json.loads(blocked.stdout))
            self.assertFalse((package / ".thoughts").exists())
            for args in (
                ("scripts/run_preflight.py",),
                ("scripts/prepare_run.py", "--self-test"),
                ("scripts/finalize_sentry_planning.py", "--self-test"),
                ("-m", "unittest", "tests.test_context_operation_audit", "tests.test_recovery",
                 "tests.test_planning_recovery", "tests.test_feature_delivery_continuation",
                 "tests.test_shared_runtime_acceptance", "tests.test_sentry_failure",
                 "tests.test_handoff_instruction_conflict", "tests.test_sentry_acceptance", "tests.test_sentry_handoff",
                 "tests.test_python_maintenance", "tests.test_validation_modules", "tests.test_review_regressions"),
                ("scripts/finalize_work_record.py", "--self-test"),
            ):
                result = subprocess.run([sys.executable, *args], cwd=package, capture_output=True,
                                        text=True, timeout=60)
                self.assertEqual(result.returncode, 0, " ".join(args) + "\n" +
                                 (result.stdout + result.stderr)[-4000:])
