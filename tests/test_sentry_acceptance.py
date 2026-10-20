"""Native launch, source retention, closure and delivery regressions from v7."""

import copy
import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts import prepare_run, validate_worker_runtime as runtime
from scripts.run_input_manifest import retain_source_releases, source_release_errors
from scripts.worker_runtime_evidence import launch_binding_errors, terminal_closure
from tests import test_shared_runtime_acceptance as shared

ROOT = Path(__file__).resolve().parents[1]
PARENT = shared.PARENT


class V7SentryAcceptance(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.builder = shared.SharedRuntimeAcceptance()

    def fixture(self, name="case"):
        repository = self.root / name
        repository.mkdir()
        return self.builder.fixture(str(repository), "sentry_issue_remediation", "sentry_solution_architect")

    def test_native_wrong_launch_and_inherited_context_are_rejected(self):
        for index, changes in enumerate(({"fork_turns": "all", "model": None, "reasoning_effort": None},
                                          {"model": "wrong-model"}, {"reasoning_effort": "medium"})):
            with self.subTest(changes=changes):
                fixture = self.fixture(str(index))
                arguments = json.loads(fixture[5][1]["payload"]["arguments"])
                arguments.update(changes)
                fixture[5][1]["payload"]["arguments"] = json.dumps(arguments)
                trace, ledger = self.builder.export(fixture)
                self.assertEqual(trace["audit"]["status"], "rejected")
                trace["launch_errors"] = []
                self.assertTrue(launch_binding_errors(trace, fixture[1], fixture[2], ledger))

    def test_native_child_configuration_and_receipt_tampering_are_rejected(self):
        fixture = self.fixture()
        fixture[6].insert(1, fixture[4](2, "turn_context", model="gpt-6-luna", effort="medium"))
        trace, ledger = self.builder.export(fixture)
        self.assertIn("worker_runtime_configuration_mismatch:sentry_solution_architect", trace["audit"]["errors"])
        trace["runtime_configurations"] = []
        self.assertIn("worker_launch_receipt_mismatch:sentry_solution_architect",
                      launch_binding_errors(trace, fixture[1], fixture[2], ledger))

    def test_matching_native_configuration_is_preserved(self):
        fixture = self.fixture()
        fixture[6].insert(1, fixture[4](2, "turn_context", model="gpt-6.1-sol", effort="low"))
        trace, ledger = self.builder.export(fixture)
        self.assertEqual(trace["audit"]["status"], "passed")
        self.assertEqual(trace["launch"]["fork_turns"], "none")
        self.assertEqual(trace["runtime_configurations"][0]["model"], "gpt-6.1-sol")
        self.assertEqual(launch_binding_errors(trace, fixture[1], fixture[2], ledger), [])

    def test_native_inventory_builds_exact_closure_and_rejects_running_or_stale(self):
        fixture = self.fixture()
        event = fixture[4]
        fixture[5].extend([event(21, "response_item", type="function_call", namespace="collaboration",
            name="list_agents", call_id="inventory", arguments="{}"),
            event(22, "response_item", type="function_call_output", call_id="inventory", output=json.dumps({
                "agents": [{"agent_name": "/root", "agent_status": "running"},
                           {"agent_name": "/root/worker", "agent_status": {"completed": "Done"}}]}))])
        _, ledger = self.builder.export(fixture)
        closure = terminal_closure(ledger)
        self.assertEqual(closure["runtime_closure"][0]["Runtime status"], "Terminal")
        self.assertIn("/root/worker=completed", closure["runtime_closure"][0]["Closure evidence or blocker"])
        self.assertEqual(runtime.terminal_observation_errors(closure["terminal_observations"], ["/root/worker"]), [])
        run, root = fixture[:2]
        command = [sys.executable, str(ROOT / "scripts/worker_runtime_evidence.py"),
            "--provider-session", str(root / "parent.jsonl"), "--parent-thread-id", PARENT,
            "--started-at", run["runtime_evidence"]["run_started_at"],
            "--ledger", run["runtime_evidence"]["ledger"]]
        closure_path = root / "runtime_closure.json"
        collected = subprocess.run([*command, "--closure", str(closure_path)], capture_output=True, text=True)
        self.assertEqual(collected.returncode, 0, collected.stdout + collected.stderr)
        exported = subprocess.run([*command, "--worker-session", str(root / "child.jsonl"),
            "--observation", str(closure_path), "--agent", fixture[2], "--trace", str(root / "trace.json")],
            capture_output=True, text=True)
        self.assertEqual(exported.returncode, 0, exported.stdout + exported.stderr)
        self.assertEqual(json.loads((root / "trace.json").read_text())["audit"]["status"], "passed")
        stale = copy.deepcopy(ledger)
        stale["inventories"][-1]["Observed at"] = fixture[3](1)
        with self.assertRaisesRegex(ValueError, "terminal_inventory_unverified"):
            terminal_closure(stale)
        ledger["inventories"][-1]["raw_response"]["agents"][1]["agent_status"] = "running"
        with self.assertRaisesRegex(ValueError, "terminal_inventory_unverified"):
            terminal_closure(ledger)

    def sources(self):
        source = self.root / "provider.jsonl"
        source.write_text("\n".join(json.dumps(row) for row in [
            {"type": "session_meta", "payload": {"id": PARENT}},
            {"type": "turn_context", "payload": {"turn_id": shared.CHILD}},
            {"type": "response_item", "payload": {"type": "custom_tool_call", "call_id": "source",
             "input": 'await tools.mcp__sentry__get_sentry_resource({url:"https://example.sentry.io/issues/123/"})'}},
            {"type": "response_item", "payload": {"type": "custom_tool_call_output", "call_id": "source",
             "output": json.dumps({"content": [{"text": "**release**: " + "a" * 40}]})}}]))
        log = self.root / "occurrence.csv"
        with log.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=["timestamp", "message"])
            writer.writeheader()
            writer.writerow({"message": "Using release from debug info: " + "b" * 40})
            writer.writerow({"message": json.dumps({"time": "2026-10-14T01:02:03Z", "workflow_item": {
                "organization_id": 1, "asset_id": 0, "referent_id": "123",
                "personal_payload": "must not persist\nsecond line"}}).replace("\\n", "\n")})
        inputs = {"inputs": [
            {"Input ID": "IN-1", "Input or artifact": "Sentry issue", "Source or path": "https://example.sentry.io/issues/123/",
             "Authority": "User", "Status": "Accessible"},
            {"Input ID": "IN-2", "Input or artifact": "Supplied occurrence", "Source or path": str(log),
             "path": str(log), "Authority": "User", "Status": "Accessible"}]}
        return source, inputs

    def test_releases_are_retained_per_source_and_correlations_exclude_payloads(self):
        source, inputs = self.sources()
        retain_source_releases(inputs, source)
        self.assertEqual(inputs["inputs"][0]["Observed releases"], ["a" * 40])
        self.assertEqual(inputs["inputs"][1]["Observed releases"], ["b" * 40])
        self.assertNotIn("must not persist", json.dumps(inputs))
        self.assertEqual(inputs["inputs"][1]["Occurrence correlation"][0]["organization_id"], "1")
        self.assertTrue(source_release_errors("a" * 40 + "\n" + "b" * 40, inputs))
        self.assertTrue(source_release_errors("IN-10 " + "a" * 40 + "\nIN-2 " + "b" * 40, inputs))
        self.assertEqual(source_release_errors("IN-1 " + "a" * 40 + "\nIN-2 " + "b" * 40, inputs), [])

    def test_live_and_csv_releases_on_one_input_are_both_retained(self):
        source, inputs = self.sources()
        row = inputs["inputs"][0]
        row["paths"] = [inputs["inputs"][1]["path"]]
        inputs["inputs"] = [row]
        retain_source_releases(inputs, source)
        self.assertEqual(row["Observed releases"], ["a" * 40, "b" * 40])
        self.assertEqual(row["Release observation"], "Provider source read and supplied occurrence log")
        self.assertEqual(row["Occurrence correlation"][0]["organization_id"], "1")
        self.assertEqual(len(source_release_errors("IN-1 " + "a" * 40, inputs)), 1)

    def test_missing_native_source_blocks_before_creating_a_run(self):
        _, inputs = self.sources()
        path = self.root / "inputs.json"
        path.write_text(json.dumps(inputs))
        with self.assertRaisesRegex(ValueError, "sentry_source_observation_requires_provider_session"):
            prepare_run.prepare_run(self.root, "CASE-1", "sentry_issue_remediation", None, False, input_manifest=path)
        self.assertFalse((self.root / ".thoughts").exists())

    def test_source_preparation_preserves_observations_in_the_hashed_manifest(self):
        source, inputs = self.sources()
        path = self.root / "inputs.json"
        path.write_text(json.dumps(inputs))
        run = prepare_run.prepare_run(self.root, "CASE-1", "sentry_issue_remediation", None, False,
                                      input_manifest=path, provider_session=source)
        current = json.loads(Path(run["run_input_manifest"]["path"]).read_text())
        self.assertEqual(current["inputs"][0]["Observed releases"], ["a" * 40])
        self.assertEqual(current["inputs"][1]["Observed releases"], ["b" * 40])

    def test_incomplete_or_previous_invocation_source_reads_are_not_accepted(self):
        source, inputs = self.sources()
        rows = source.read_text().splitlines()
        source.write_text("\n".join(rows[:-1]))
        with self.assertRaisesRegex(ValueError, "sentry_source_observation_unavailable"):
            retain_source_releases(inputs, source)
        source.write_text("\n".join(rows + [json.dumps({"type": "response_item", "payload": {
            "type": "custom_tool_call", "input": "python3 scripts/run_preflight.py"}})]))
        with self.assertRaisesRegex(ValueError, "sentry_source_observation_unavailable"):
            retain_source_releases(inputs, source)

    def test_multiple_source_reads_keep_their_own_releases(self):
        source, inputs = self.sources()
        second = copy.deepcopy(inputs["inputs"][0])
        second.update({"Input ID": "IN-3", "Source or path": "https://example.sentry.io/issues/456/"})
        inputs["inputs"].append(second)
        rows = source.read_text()
        added = rows.splitlines()[1:]
        source.write_text(rows + "\n" + "\n".join(row.replace("123/", "456/").replace('"source"', '"second"')
            .replace("a" * 40, "c" * 40) for row in added))
        retain_source_releases(inputs, source)
        self.assertEqual(inputs["inputs"][0]["Observed releases"], ["a" * 40])
        self.assertEqual(inputs["inputs"][2]["Observed releases"], ["c" * 40])

    def test_discovery_and_failed_source_calls_do_not_count_as_observations(self):
        source, inputs = self.sources()
        original = source.read_text()
        source.write_text(original.replace("get_sentry_resource", "find_organizations"))
        with self.assertRaisesRegex(ValueError, "sentry_source_observation_unavailable"):
            retain_source_releases(inputs, source)
        rows = [json.loads(line) for line in original.splitlines()]
        rows[-1]["payload"]["output"] = json.dumps({"isError": True, "content": [{"text": "Unavailable"}]})
        source.write_text("\n".join(map(json.dumps, rows)))
        with self.assertRaisesRegex(ValueError, "sentry_source_observation_failed"):
            retain_source_releases(inputs, source)

    def test_ledger_refresh_preserves_pending_rejections_and_checks_run_identity(self):
        fixture = self.fixture()
        _, ledger = self.builder.export(fixture)
        run, root = fixture[:2]
        path = Path(run["runtime_evidence"]["ledger"])
        pending = {fixture[2]: {"run_id": run["run_id"], "sha256": "a" * 64}}
        ledger["rejected_results"] = pending
        path.write_text(json.dumps(ledger))
        command = [sys.executable, str(ROOT / "scripts/worker_runtime_evidence.py"),
            "--provider-session", str(root / "parent.jsonl"), "--parent-thread-id", PARENT,
            "--started-at", run["runtime_evidence"]["run_started_at"], "--ledger", str(path)]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(path.read_text())["rejected_results"], pending)
        pending[fixture[2]]["run_id"] = "different-run"
        ledger["rejected_results"] = pending
        path.write_text(json.dumps(ledger))
        before = path.read_bytes()
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("worker_rejection_receipt_run_mismatch", result.stdout)
        self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
