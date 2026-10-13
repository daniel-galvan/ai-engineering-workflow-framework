"""Exercise shipped entrypoints from a clean local package, without live workers."""

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
            for args in (
                ("scripts/run_preflight.py",),
                ("scripts/prepare_run.py", "--self-test"),
                ("-m", "unittest", "tests.test_context_operation_audit", "tests.test_v6_recovery",
                 "tests.test_planning_recovery", "tests.test_feature_delivery_continuation"),
                ("scripts/finalize_work_record.py", "--self-test"),
            ):
                result = subprocess.run([sys.executable, *args], cwd=package, capture_output=True,
                                        text=True, timeout=60)
                self.assertEqual(result.returncode, 0, " ".join(args) + "\n" +
                                 (result.stdout + result.stderr)[-4000:])
