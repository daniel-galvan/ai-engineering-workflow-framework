"""Native parent context boundaries before preparation and worker activation."""

import json
import shlex
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from scripts.prepare_run import prepare_run
from scripts.provider_runtime import (
    parent_context_audit,
    prior_run_status_thread_ids,
    related_run_status_projection_source,
    stale_run_status_errors,
    strict_json_loads,
)
from scripts.worker_runtime_evidence import strict_json_loads as worker_strict_json_loads
from scripts.validate_worker_runtime import activation_packet_errors


PARENT = "00000000-0000-0000-0000-000000000001"
TURN = "00000000-0000-0000-0000-000000000002"
CHILD = "00000000-0000-0000-0000-000000000003"


class ParentContext(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "parent.jsonl"
        self.rows = [{"type": "session_meta", "timestamp": "2026-10-01T00:00:00Z",
                      "payload": {"id": PARENT}},
                     {"type": "turn_context", "timestamp": "2026-10-01T00:00:01Z",
                      "payload": {"turn_id": TURN}}]

    def call(self, name, **arguments):
        return {"type": "response_item", "timestamp": "2026-10-01T00:00:02Z",
                "payload": {"type": "function_call", "name": name, "arguments": json.dumps(arguments)}}

    def command_execution(self, command, *, exit_code=1, output="", status=None, parsed_cmd=None):
        argv = shlex.split(command)
        query_path = argv[-1]
        query = argv[2]
        return {"type": "event_msg", "timestamp": "2026-10-01T00:00:03Z",
                "payload": {"type": "item_completed", "item": {
                    "type": "CommandExecution", "id": "exec-00000000-0000-0000-0000-000000000001",
                    "command": ["/bin/bash", "-lc", command],
                    "status": status if status is not None else ("failed" if exit_code else "completed"),
                    "exit_code": exit_code, "aggregated_output": output,
                    "parsed_cmd": parsed_cmd if parsed_cmd is not None else [
                        {"type": "search", "cmd": command, "query": query, "path": query_path}],
                }}}

    def audit(self, **kwargs):
        self.source.write_text("".join(json.dumps(row) + "\n" for row in self.rows))
        return parent_context_audit(self.source, **kwargs)

    def test_actual_memory_read_is_rejected_but_quotes_and_prior_turn_are_ignored(self):
        memory = "/repo/.codex/memories/MEMORY.md"
        self.rows.insert(1, {"type": "turn_context", "timestamp": "2026-09-30T23:59:00Z",
                             "payload": {"turn_id": CHILD}})
        self.rows.insert(2, self.call("exec_command", cmd="cat " + memory))
        self.rows.extend([self.call("spawn_agent", message="Do not read " + memory),
            {"type": "response_item", "timestamp": "2026-10-01T00:00:02Z",
             "payload": {"type": "function_call_output", "output": "cat " + memory}},
            self.call("exec_command", cmd="cat start_prompt.md")])
        self.assertEqual(self.audit()["status"], "passed")
        self.rows.append(self.call("exec_command", cmd="rg -n issue " + memory))
        result = self.audit()
        self.assertEqual(result["turn_id"], TURN)
        self.assertIn("forbidden_context_reference:memory_path", result["errors"])

    def test_codex_home_memory_paths_are_rejected_when_quoted(self):
        for command, expected in (
            ('cat "$CODEX_HOME/memories/MEMORY.md"', "memory_path"),
            ('rg -n issue "${CODEX_HOME}/memories/notes.md"', "memory_directory"),
            ('rg -n issue "$CODEX_HOME"/memories/notes.md', "memory_directory"),
            ('rg -n issue "${CODEX_HOME}"/memories/notes.md', "memory_directory"),
            (r'rg -n issue "$env:CODEX_HOME"\memories\notes.md', "memory_directory"),
        ):
            with self.subTest(command=command):
                self.rows = self.rows[:2] + [self.call("exec_command", cmd=command)]
                self.assertIn("forbidden_context_reference:" + expected, self.audit()["errors"])

    def test_verified_no_match_memory_probe_is_distinct_from_a_memory_read(self):
        memory = "/Users/example/.codex/memories/MEMORY.md"
        command = "rg -n 'ECHO-2806|planning' " + memory
        self.rows.extend([self.call("exec_command", cmd=command), self.command_execution(command)])
        result = self.audit()
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["empty_memory_probes"], 1)
        self.assertNotIn("forbidden_context_reference:memory_path", result["errors"])

    def test_verified_fixed_string_no_match_memory_probe_is_distinct_from_a_memory_read(self):
        memory = "/Users/example/.codex/memories/MEMORY.md"
        command = "rg -n -F 'ECHO-2806' " + memory
        parsed = [{"type": "search", "cmd": "rg -n -F ECHO-2806 " + memory,
                  "query": "ECHO-2806", "path": "MEMORY.md"}]
        self.rows.extend([self.call("exec_command", cmd=command),
                          self.command_execution(command, parsed_cmd=parsed)])
        result = self.audit()
        self.assertEqual(result["status"], "passed", result)
        self.assertEqual(result["empty_memory_probes"], 1)

    def test_verified_empty_host_memory_probe_may_precede_preflight(self):
        framework = self.root / "framework"
        memory = "/Users/example/.codex/memories/MEMORY.md"
        search = "rg -n 'ECHO-2806|planning' " + memory
        preflight = f"python3 {framework}/scripts/run_preflight.py"
        observation = {"type": "event_msg", "payload": {"type": "item_completed", "item": {
            "type": "CommandExecution", "command": ["/bin/bash", "-lc", preflight],
            "status": "completed", "exit_code": 0,
            "aggregated_output": json.dumps({"status": "passed"})}}}
        self.rows.extend([self.call("exec_command", cmd=search), self.command_execution(search),
                          self.call("exec_command", cmd=preflight), observation,
                          self.call("exec_command", cmd="cat playbooks/techops_issue_remediation.md")])
        result = self.audit(framework_root=framework, require_preflight_order=True)
        self.assertEqual(result["status"], "passed", result)
        self.assertEqual(result["empty_memory_probes"], 1)

    def test_nonempty_memory_probe_still_blocks_preflight_order(self):
        framework = self.root / "framework"
        memory = "/Users/example/.codex/memories/MEMORY.md"
        search = "rg -n 'ECHO-2806|planning' " + memory
        preflight = f"python3 {framework}/scripts/run_preflight.py"
        self.rows.extend([self.call("exec_command", cmd=search),
                          self.command_execution(search, exit_code=0, output="match")])
        result = self.audit(framework_root=framework, require_preflight_order=True)
        self.assertIn("parent_framework_content_before_preflight", result["errors"])
        self.assertIn("forbidden_context_reference:memory_path", result["errors"])

    def test_empty_memory_probe_allows_only_exact_native_shell_startup_warning(self):
        memory = "/Users/example/.codex/memories/MEMORY.md"
        query = "ECHO-2806|Issue Remediation|issue_remediation"
        command = "rg -n -i " + shlex.quote(query) + " " + memory
        warning = ("WARNING: proceeding, even though we could not create PATH aliases: "
                   "Operation not permitted (os error 1)\n")
        parsed = [{"type": "search", "cmd": command, "query": query, "path": "MEMORY.md"}]
        self.rows.extend([self.call("exec_command", cmd=command),
                          self.command_execution(command, output=warning, parsed_cmd=parsed)])
        result = self.audit()
        self.assertEqual(result["status"], "passed", result)
        self.assertEqual(result["empty_memory_probes"], 1)

        self.rows[-1]["payload"]["item"]["aggregated_output"] += "MEMORY.md:7: ECHO-2806"
        result = self.audit()
        self.assertEqual(result["empty_memory_probes"], 0)
        self.assertIn("forbidden_context_reference:memory_path", result["errors"])

    def test_verified_case_insensitive_probe_accepts_native_basename_path(self):
        memory = "/Users/example/.codex/memories/MEMORY.md"
        query = "ECHO-2806|Issue Remediation|issue_remediation"
        command = "rg -n -i " + shlex.quote(query) + " " + memory
        parsed = [{"type": "search", "cmd": command, "query": query, "path": "MEMORY.md"}]
        self.rows.extend([self.call("exec_command", cmd=command),
                          self.command_execution(command, parsed_cmd=parsed)])
        result = self.audit()
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["empty_memory_probes"], 1)

        forged = self.command_execution(command, parsed_cmd=[
            {"type": "search", "cmd": command, "query": query, "path": "/tmp/MEMORY.md"}])
        self.rows = self.rows[:2] + [self.call("exec_command", cmd=command), forged]
        result = self.audit()
        self.assertEqual(result["empty_memory_probes"], 0)
        self.assertIn("forbidden_context_reference:memory_path", result["errors"])

    def test_no_match_probe_cannot_share_native_run_skill_bootstrap_command(self):
        framework = self.root / "framework"
        skill = framework / "skills" / "run" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("# Active run instructions\n" * 4)
        memory = Path("/Users/example/.codex/memories/MEMORY.md")
        query = "ECHO-2806|Issue Remediation|techops_issue_remediation"
        search = "rg -n " + shlex.quote(query) + " " + str(memory)
        command = "cat " + shlex.quote(str(skill)) + " && " + search
        observation = {"type": "event_msg", "payload": {"type": "item_completed", "item": {
            "type": "CommandExecution", "command": ["/bin/bash", "-lc", command],
            "status": "failed", "exit_code": 1, "aggregated_output": skill.read_text(),
            "parsed_cmd": [{"type": "read", "cmd": "cat " + str(skill), "path": str(skill)},
                           {"type": "search", "cmd": search, "query": query, "path": "MEMORY.md"}]}}}
        self.rows.extend([self.call("exec_command", cmd=command), observation])
        result = self.audit(framework_root=framework, require_preflight_order=True)
        self.assertEqual(result["status"], "rejected", result)
        self.assertIn("parent_framework_content_before_preflight", result["errors"])
        self.assertEqual(result["empty_memory_probes"], 1)

        observation["payload"]["item"]["aggregated_output"] += "match from memory"
        result = self.audit(framework_root=framework, require_preflight_order=True)
        self.assertEqual(result["empty_memory_probes"], 0)
        self.assertTrue(any(error.startswith("forbidden_context_reference:memory_")
                            for error in result["errors"]))

    def test_memory_search_is_not_exempt_without_exact_native_no_match_evidence(self):
        memory = "/Users/example/.codex/memories/MEMORY.md"
        command = "rg -n issue " + memory
        variants = (
            None,
            self.command_execution(command, exit_code=0),
            self.command_execution(command, output="matched text"),
            self.command_execution(command, status="completed"),
            self.command_execution(command, parsed_cmd=[
                {"type": "search", "query": "issue", "path": "MEMORY.md"},
                {"type": "search", "query": "issue", "path": "MEMORY.md"},
            ]),
        )
        for observation in variants:
            with self.subTest(observation=observation is not None):
                self.rows = self.rows[:2] + [self.call("exec_command", cmd=command)]
                if observation is not None:
                    self.rows.append(observation)
                result = self.audit()
                self.assertEqual(result["empty_memory_probes"], 0)
                self.assertTrue(any(error.startswith("forbidden_context_reference:memory_")
                                    for error in result["errors"]))

        piped = command + " | head -20"
        self.rows = self.rows[:2] + [self.call("exec_command", cmd=piped), self.command_execution(piped)]
        self.assertTrue(any(error.startswith("forbidden_context_reference:memory_")
                            for error in self.audit()["errors"]))

    def test_approved_continuity_read_is_allowed_but_write_and_unassigned_read_are_not(self):
        artifact = self.root / ".thoughts" / "ITEM-1"
        archived = str(artifact / "runs" / "prior" / "decisions.md")
        self.rows.append(self.call("exec_command", cmd="cat " + archived))
        self.assertEqual(self.audit(artifact_root=artifact, input_paths=(archived,))["status"], "passed")
        self.assertEqual(self.audit(artifact_root=artifact)["status"], "rejected")
        self.rows[-1] = self.call("exec_command", cmd="echo changed > " + archived)
        self.assertEqual(self.audit(artifact_root=artifact, input_paths=(archived,))["status"], "rejected")

    def test_parent_can_observe_its_workers_and_explicit_continuity_threads(self):
        self.rows.append({"type": "event_msg", "timestamp": "2026-10-01T00:00:02Z",
            "payload": {"item": {"type": "SubAgentActivity",
            "kind": "started", "agent_thread_id": CHILD}}})
        self.rows.extend([self.call("mcp__codex_app__read_thread", threadId=CHILD),
                          self.call("mcp__codex_app__read_thread", threadId=TURN)])
        self.assertIn("parent_unassigned_thread_read:" + TURN, self.audit()["errors"])
        self.assertEqual(self.audit(input_paths=("codex://threads/" + TURN,))["status"], "passed")
        self.rows.append(self.call("mcp__codex_app__wait_threads", targets=[{"threadId": PARENT}]))
        self.assertIn("parent_unassigned_thread_read:" + PARENT, self.audit()["errors"])
        self.rows.append(self.call("mcp__codex_app__list_threads", limit=10))
        self.assertIn("parent_unassigned_thread_discovery", self.audit()["errors"])

    @unittest.skipUnless(shutil.which("node"), "Node.js required to execute the provider JavaScript")
    def test_related_status_projection_executes_and_redacts_inventory(self):
        related = {"id": TURN, "title": "ECHO-2806 planning", "summary": "private diagnosis",
                   "status": "notLoaded", "hostId": "local", "kind": "codex", "updatedAt": 1792624353}
        prior = {"thread": {"id": CHILD, "status": {"type": "completed"},
                             "preview": "private worker prompt"},
                 "turns": [{"status": "completed", "items": [{"text": "private worker output"}]}]}
        visible = {"thread": {"id": TURN, "status": {"type": "notLoaded"},
                               "preview": "private related prompt"},
                   "turns": [{"status": "completed", "items": [{"text": "private related output"}]}]}
        wait_state = {"wake": {"reason": "inactiveStatus", "threadId": TURN},
                      "polls": [{"thread": {"id": TURN, "status": {"type": "notLoaded"}},
                                 "latestTurn": {"status": "completed"},
                                 "latestAssistantMessage": {"text": "private final message"}}]}
        inventory = {"pinnedThreads": [related], "threads": [
            {"id": PARENT, "title": "ECHO-2806 current run", "status": "active"},
            {"id": "unrelated", "title": "Other work", "summary": "private", "status": "idle"}]}
        projection = related_run_status_projection_source("ECHO-2806", PARENT, (CHILD,))
        stub = ("const tools = {mcp__codex_app__list_threads: async args => {\n"
                "  if (args.limit !== 50) throw new Error('unexpected inventory request');\n"
                "  return {content: [{text: " + json.dumps(json.dumps(inventory)) + "}]};\n"
                "}, mcp__codex_app__read_thread: async args => {\n"
                "  if (args.turnLimit !== 1 || args.includeOutputs !== false)\n"
                "    throw new Error('unexpected exact-id request');\n"
                "  const values = {" + json.dumps(CHILD) + ": " + json.dumps(prior) + ", " +
                json.dumps(TURN) + ": " + json.dumps(visible) + "};\n"
                "  const value = values[args.threadId];\n"
                "  if (!value || (args.threadId === " + json.dumps(TURN) + " && args.hostId !== 'local') ||\n"
                "      (args.threadId === " + json.dumps(CHILD) + " && 'hostId' in args))\n"
                "    throw new Error('unexpected exact-id target');\n"
                "  return {content: [{text: " + "JSON.stringify(value)" + "}]};\n"
                "}, mcp__codex_app__wait_threads: async args => {\n"
                "  if (args.timeoutMs !== 0 || args.targets?.length !== 1 ||\n"
                "      args.targets[0].threadId !== " + json.dumps(TURN) + " || args.targets[0].hostId !== 'local')\n"
                "    throw new Error('unexpected wait status target');\n"
                "  return {content: [{text: " + json.dumps(json.dumps(wait_state)) + "}]};\n"
                "}};\nconst text = value => process.stdout.write(value);\n")
        result = subprocess.run([shutil.which("node"), "--input-type=module", "-"], input=stub + projection,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [
            {"id": CHILD, "status": "completed"},
            {"id": TURN, "status": "completed"}])
        self.assertNotIn("private", result.stdout)
        skill = (Path(__file__).resolve().parents[1] / "skills/run/SKILL.md").read_text()
        example = textwrap.dedent(skill.split("   ```javascript\n", 1)[1].split("   ```", 1)[0])
        example = example.replace("PARENT-THREAD-UUID", PARENT).replace("PRIOR-WORKER-THREAD-UUID", CHILD)
        self.assertEqual(example.strip(), projection)

    @unittest.skipUnless(shutil.which("node"), "Node.js required to execute the provider JavaScript")
    def test_related_status_projection_requires_terminal_latest_turn_for_idle(self):
        projection = related_run_status_projection_source("ECHO-2806", PARENT, (CHILD,))
        for latest, expected in (("completed", "completed"), ("failed", "failed"),
                                 ("inProgress", "unavailable"), (None, "unavailable")):
            with self.subTest(latest=latest):
                read = {"thread": {"id": CHILD, "status": {"type": "idle"}},
                        "turns": [] if latest is None else [{"status": latest}]}
                stub = ("const tools = {mcp__codex_app__list_threads: async () => ({content: [{text: "
                        + json.dumps(json.dumps({"threads": []})) + "}]}),\n"
                        "mcp__codex_app__read_thread: async () => ({content: [{text: "
                        + json.dumps(json.dumps(read)) + "}]})};\n"
                        "const text = value => process.stdout.write(value);\n")
                result = subprocess.run([shutil.which("node"), "--input-type=module", "-"], input=stub + projection,
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout), [{"id": CHILD, "status": expected}])

    @unittest.skipUnless(shutil.which("node"), "Node.js required to execute the provider JavaScript")
    def test_related_status_projection_marks_unavailable_exact_ids(self):
        projection = related_run_status_projection_source("ECHO-2806", PARENT, (CHILD,))
        inventory = {"threads": [{"id": TURN, "title": "ECHO-2806 other", "hostId": "local"}]}
        thread = {"thread": {"id": TURN, "status": {"type": "notLoaded"}}}
        stub = ("const tools = {mcp__codex_app__list_threads: async () => ({content: [{text: " +
                json.dumps(json.dumps(inventory)) + "}]}),\n"
                "mcp__codex_app__read_thread: async args => args.threadId === " + json.dumps(CHILD) +
                " ? {isError: true} : {content: [{text: " + json.dumps(json.dumps(thread)) + "}]},\n"
                "mcp__codex_app__wait_threads: async () => ({isError: true})};\n"
                "const text = value => process.stdout.write(value);\n")
        result = subprocess.run([shutil.which("node"), "--input-type=module", "-"], input=stub + projection,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [
            {"id": CHILD, "status": "unavailable"}, {"id": TURN, "status": "unavailable"}])

    def test_only_one_exact_redacted_related_run_status_projection_is_allowed(self):
        artifact_root = self.root / ".thoughts" / "ECHO-2806"
        projection = related_run_status_projection_source(artifact_root.name, PARENT)
        status_call = {"type": "response_item", "payload": {
            "type": "custom_tool_call", "name": "exec", "call_id": "status-call", "input": projection}}
        status_output = {"type": "response_item", "payload": {
            "type": "custom_tool_call_output", "call_id": "status-call",
            "output": [{"type": "text", "text": "[]"}]}}
        self.rows.extend([status_call, status_output])

        result = self.audit(artifact_root=artifact_root)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["verified_related_run_status_probes"], 1)
        self.assertEqual(result["related_run_status_rows"], [])
        status_call["payload"]["input"] = "\n" + projection + "\n"
        self.assertEqual(self.audit(artifact_root=artifact_root)["status"], "passed")
        status_output["payload"]["output"] = [
            {"type": "input_text", "text": "Script completed\nWall time 0.6 seconds\nOutput:\n"},
            {"type": "input_text", "text": "[]"}]
        self.assertEqual(self.audit(artifact_root=artifact_root)["status"], "passed")
        self.assertIn("parent_unassigned_thread_discovery", self.audit()["errors"])

        self.rows.extend([
            {"type": "response_item", "payload": {
                "type": "custom_tool_call", "name": "exec", "call_id": "status-call-2", "input": projection}},
            {"type": "response_item", "payload": {
                "type": "custom_tool_call_output", "call_id": "status-call-2",
                "output": [{"type": "text", "text": "[]"}]}}])
        result = self.audit(artifact_root=artifact_root)
        self.assertIn("parent_unassigned_thread_discovery", result["errors"])
        self.assertEqual(result["verified_related_run_status_probes"], 1)

        self.rows = self.rows[:2] + [{"type": "response_item", "payload": {
            "type": "custom_tool_call", "name": "exec",
            "call_id": "bad-status-call",
            "input": projection.replace("text(JSON.stringify(relatedRows));",
                                         "text(response.content[0].text);")}}]
        result = self.audit(artifact_root=artifact_root)
        self.assertIn("parent_unassigned_thread_discovery", result["errors"])

        self.rows = self.rows[:2] + [status_call, status_output,
            self.call("mcp__codex_app__read_thread", threadId=CHILD)]
        result = self.audit(artifact_root=artifact_root)
        self.assertIn("parent_unassigned_thread_read:" + CHILD, result["errors"])

    def test_status_projection_helper_includes_prior_parent_and_worker_without_writing(self):
        artifact_root = self.root / ".thoughts" / "ECHO-2806"
        artifact_root.mkdir(parents=True)
        (artifact_root / "role_bindings.json").write_text(json.dumps({
            "parent_context": {"parent_thread_id": TURN}, "private": "do not expose"}))
        (artifact_root / "runtime_dispatches.json").write_text(json.dumps({
            "thread_mappings": {"/root/prior-worker": CHILD}, "events": [], "failed_dispatches": [],
            "private": "do not expose"}))
        self.audit()
        before = {path.name: path.read_bytes() for path in artifact_root.iterdir()}
        script = Path(__file__).resolve().parents[1] / "scripts/prepare_run.py"
        command = ["python3", str(script), "--status-projection", "--execution-repository", str(self.root),
                   "--work-item", "ECHO-2806", "--provider-session", str(self.source)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["prior_thread_ids"], sorted([TURN, CHILD]))
        self.assertEqual(output["projection"], related_run_status_projection_source(
            "ECHO-2806", PARENT, tuple(sorted([TURN, CHILD]))))
        self.assertNotIn("do not expose", result.stdout)
        self.assertEqual(before, {path.name: path.read_bytes() for path in artifact_root.iterdir()})
        call = {"type": "response_item", "payload": {"type": "custom_tool_call", "name": "exec",
                "call_id": "status", "input": output["projection"]}}
        response = {"type": "response_item", "payload": {"type": "custom_tool_call_output", "call_id": "status",
                    "output": [{"type": "text", "text": json.dumps([
                        {"id": TURN, "status": "idle"}, {"id": CHILD, "status": "completed"}])}]}}
        self.rows.extend([self.call("exec_command", cmd=shlex.join(command)), call, response])
        audit = self.audit(artifact_root=artifact_root)
        self.assertEqual(audit["status"], "passed", audit["errors"])
        self.assertEqual(stale_run_status_errors(audit, "active"), [])

        ledger = artifact_root / "runtime_dispatches.json"
        ledger.write_text('{"thread_mappings": {"/root/prior-worker": "invalid"}, "events": []}')
        rejected = subprocess.run(command, capture_output=True, text=True, timeout=30)
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("stale_run_thread_identity_invalid", json.loads(rejected.stdout)["reason"])
        self.assertEqual(ledger.read_text(), '{"thread_mappings": {"/root/prior-worker": "invalid"}, "events": []}')

    def test_status_projection_helper_does_not_create_a_new_artifact_root(self):
        self.audit()
        script = Path(__file__).resolve().parents[1] / "scripts/prepare_run.py"
        result = subprocess.run(["python3", str(script), "--status-projection", "--execution-repository",
                                 str(self.root), "--work-item", "ECHO-2806", "--provider-session", str(self.source)],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["prior_thread_ids"], [])
        self.assertEqual(output["projection"], related_run_status_projection_source("ECHO-2806", PARENT))
        self.assertFalse((self.root / ".thoughts").exists())

    def test_related_status_probe_requires_correlated_minimal_output(self):
        artifact_root = self.root / ".thoughts" / "ECHO-2806"
        artifact_root.mkdir(parents=True)
        (artifact_root / "runtime_dispatches.json").write_text(json.dumps({
            "thread_mappings": {"/root/prior-worker": CHILD}, "events": [], "failed_dispatches": [],
        }))
        projection = related_run_status_projection_source(artifact_root.name, PARENT, (CHILD,))
        call = {"type": "response_item", "payload": {
            "type": "custom_tool_call", "name": "exec", "call_id": "status-call", "input": projection}}
        output = {"type": "response_item", "payload": {
            "type": "custom_tool_call_output", "call_id": "status-call",
            "output": [{"type": "text", "text": json.dumps([
                {"id": CHILD, "status": "completed", "hostId": "local", "kind": "codex",
                 "updatedAt": 1792624353}])}]}}
        self.rows.extend([call, output])
        result = self.audit(artifact_root=artifact_root)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["related_run_thread_ids"], [CHILD])

        self.rows = self.rows[:2] + [call, {"type": "response_item", "payload": {
            **output["payload"], "output": [{"type": "text", "text": json.dumps([
                {"id": CHILD, "status": "notLoaded", "updatedAt": 1792624353}])}]}}]
        result = self.audit(artifact_root=artifact_root)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(stale_run_status_errors(result, "active"), ["stale_run_related_task_active:" + CHILD])

        for invalid in (True, [], {}, 3.5):
            with self.subTest(updatedAt=invalid):
                self.rows = self.rows[:2] + [call, {"type": "response_item", "payload": {
                    **output["payload"], "output": [{"type": "text", "text": json.dumps([
                        {"id": CHILD, "status": "completed", "updatedAt": invalid}])}]}}]
                self.assertIn("parent_related_run_status_output_invalid", self.audit(artifact_root=artifact_root)["errors"])

        self.rows = self.rows[:2] + [call]
        self.assertIn("parent_related_run_status_output_missing", self.audit(artifact_root=artifact_root)["errors"])

        self.rows = self.rows[:2] + [call, {"type": "response_item", "payload": {
            **output["payload"], "call_id": "another-call"}}]
        self.assertIn("parent_related_run_status_output_missing", self.audit(artifact_root=artifact_root)["errors"])

        for unsafe in (
            [{"id": CHILD, "status": "completed", "summary": "private task content"}],
            [{"id": CHILD, "status": "running"}],
        ):
            with self.subTest(unsafe=unsafe):
                self.rows = self.rows[:2] + [call, {"type": "response_item", "payload": {
                    "type": "custom_tool_call_output", "call_id": "status-call",
                    "output": [{"type": "text", "text": json.dumps(unsafe)}]}}]
                result = self.audit(artifact_root=artifact_root)
                if "summary" in unsafe[0]:
                    self.assertIn("parent_related_run_status_output_invalid", result["errors"])
                else:
                    self.assertEqual(result["status"], "passed")
                    self.assertEqual(stale_run_status_errors(result, "active"),
                                     ["stale_run_related_task_active:" + CHILD])

        duplicate_status = ('[{"id":"' + CHILD + '","status":"running","status":"completed"}]')
        self.rows = self.rows[:2] + [call, {"type": "response_item", "payload": {
            "type": "custom_tool_call_output", "call_id": "status-call",
            "output": [{"type": "text", "text": duplicate_status}]}}]
        self.assertIn("parent_related_run_status_output_invalid", self.audit(artifact_root=artifact_root)["errors"])

    def test_stale_archive_status_requires_all_known_workers_to_be_terminal(self):
        context = {
            "verified_related_run_status_probes": 1,
            "related_run_status_probe_attempts": 1,
            "related_run_status_rows": [{"id": CHILD, "status": "completed"}],
            "related_run_thread_ids": [CHILD],
            "prior_run_dispatch_ledger_present": True,
        }
        self.assertEqual(stale_run_status_errors(context, "active"), [])
        active = {**context, "related_run_status_rows": [{"id": CHILD, "status": "running"}]}
        self.assertEqual(stale_run_status_errors(active, "active"), ["stale_run_related_task_active:" + CHILD])
        missing = {**context, "related_run_status_rows": []}
        self.assertEqual(stale_run_status_errors(missing, "active"), ["stale_run_worker_status_missing:" + CHILD])
        unavailable = {**context, "related_run_status_rows": [{"id": CHILD, "status": "unavailable"}]}
        self.assertEqual(stale_run_status_errors(unavailable, "active"),
                         ["stale_run_related_task_status_unavailable:" + CHILD])
        missing_ledger = {**context, "prior_run_dispatch_ledger_present": False}
        self.assertEqual(stale_run_status_errors(missing_ledger, "active"), ["stale_run_dispatch_ledger_required"])
        self.assertEqual(stale_run_status_errors(None, "active"), ["stale_run_status_probe_required"])

    def test_prior_worker_identity_collection_fails_closed_on_malformed_receipts(self):
        # CLI and package imports can load the shared helper under different module names.
        self.assertEqual(worker_strict_json_loads.__code__, strict_json_loads.__code__)
        with self.assertRaisesRegex(ValueError, "NaN"):
            strict_json_loads('{"value":NaN}')

        artifact_root = self.root / ".thoughts" / "ITEM-1"
        artifact_root.mkdir(parents=True)
        ledger = artifact_root / "runtime_dispatches.json"
        ledger.write_text(json.dumps({"thread_mappings": {},
            "events": [{"Operation": "spawn_agent", "Provider handle": "/root/worker"}],
            "failed_dispatches": []}))
        with self.assertRaisesRegex(ValueError, "stale_run_thread_identity_invalid"):
            prior_run_status_thread_ids(artifact_root, PARENT)

        ledger.write_text(json.dumps({"thread_mappings": {}, "events": [],
            "failed_dispatches": [{"Operation": "spawn_agent", "Provider handle": "/root/worker",
                                   "Status": "failed"}]}))
        self.assertEqual(prior_run_status_thread_ids(artifact_root, PARENT), ())

        ledger.write_text('{"thread_mappings":{"/root/worker":"' + CHILD + '","/root/worker":"' +
                          PARENT + '"},"events":[],"failed_dispatches":[]}')
        with self.assertRaisesRegex(ValueError, "stale_run_thread_identity_invalid"):
            prior_run_status_thread_ids(artifact_root, "00000000-0000-0000-0000-000000000004")

    def test_zero_dispatch_ledger_allows_stale_closure_without_terminal_observations(self):
        artifact_root = self.root / ".thoughts" / "ITEM-1"
        artifact_root.mkdir(parents=True)
        (artifact_root / "role_bindings.json").write_text(json.dumps({
            "parent_context": {"parent_thread_id": CHILD}}))
        (artifact_root / "runtime_dispatches.json").write_text(json.dumps({
            "events": [], "thread_mappings": {}, "failed_dispatches": [],
            "timing": {"open_worker_intervals": 0}}))
        (artifact_root / "runtime_closure.json").write_text(json.dumps({
            "status": "blocked", "completed_handles": "Unknown", "remaining_handles": "Unknown"}))
        self.assertEqual(prior_run_status_thread_ids(artifact_root, PARENT), (CHILD,))
        (artifact_root / "runtime_closure.json").write_text("null")
        with self.assertRaisesRegex(ValueError, "stale_run_closure_identity_invalid"):
            prior_run_status_thread_ids(artifact_root, PARENT)
        (artifact_root / "runtime_closure.json").write_text(json.dumps({"status": "blocked"}))

        (artifact_root / "runtime_dispatches.json").write_text(json.dumps({
            "events": [], "thread_mappings": {}, "failed_dispatches": [],
            "timing": {"open_worker_intervals": 1}}))
        with self.assertRaisesRegex(ValueError, "stale_run_closure_identity_invalid"):
            prior_run_status_thread_ids(artifact_root, PARENT)

        (artifact_root / "runtime_dispatches.json").write_text(json.dumps({
            "events": [{"Thread ID": CHILD}], "thread_mappings": {},
            "failed_dispatches": [], "timing": {"open_worker_intervals": 0}}))
        with self.assertRaisesRegex(ValueError, "stale_run_closure_identity_invalid"):
            prior_run_status_thread_ids(artifact_root, PARENT)

        (artifact_root / "runtime_dispatches.json").write_text(json.dumps({
            "events": [], "thread_mappings": {}, "failed_dispatches": [],
            "open_worker_intervals": None}))
        with self.assertRaisesRegex(ValueError, "stale_run_closure_identity_invalid"):
            prior_run_status_thread_ids(artifact_root, PARENT)

    def test_preflight_order_blocks_workflow_reads_until_preflight_call(self):
        framework = self.root / "framework"
        skill = framework / "skills" / "run" / "SKILL.md"
        playbook = framework / "playbooks" / "techops_issue_remediation.md"
        combined = f"cat {skill} && sed -n '1,20p' {playbook}"
        self.rows.append(self.call("exec_command", cmd=combined))
        result = self.audit(framework_root=framework, require_preflight_order=True)
        self.assertIn("parent_framework_content_before_preflight", result["errors"])
        self.rows = self.rows[:2] + [self.call("exec_command", cmd="git status --short")]
        self.assertIn("parent_framework_content_before_preflight",
                      self.audit(framework_root=framework, require_preflight_order=True)["errors"])

        preflight = f"python3 {framework}/scripts/run_preflight.py"
        self.rows = self.rows[:2] + [self.call("exec_command", cmd=f"cat {skill}")]
        observed_preflight = {"type": "event_msg", "payload": {"type": "item_completed", "item": {
            "type": "CommandExecution", "command": ["/bin/bash", "-lc", preflight],
            "status": "completed", "exit_code": 0,
            "aggregated_output": json.dumps({"status": "passed"})}}}
        self.rows.extend([self.call("exec_command", cmd=preflight), observed_preflight,
                          self.call("exec_command", cmd=f"sed -n '1,20p' {playbook}")])
        self.assertEqual(self.audit(framework_root=framework, require_preflight_order=True)["status"], "passed")

        self.rows = self.rows[:2] + [self.call("exec_command", cmd=f"cat '{skill}'"),
            self.call("exec_command", cmd=preflight), observed_preflight,
            self.call("exec_command", cmd=f"sed -n '1,20p' {playbook}")]
        self.assertEqual(self.audit(framework_root=framework, require_preflight_order=True)["status"], "passed")

        observed_preflight["payload"]["item"]["exit_code"] = 2
        observed_preflight["payload"]["item"]["aggregated_output"] = json.dumps({"status": "blocked"})
        result = self.audit(framework_root=framework, require_preflight_order=True)
        self.assertIn("parent_framework_content_before_preflight", result["errors"])

    def test_bootstrap_allows_only_bounded_chunks_of_the_active_skill(self):
        framework = self.root / "framework"
        skill = framework / "skills/run/SKILL.md"
        header = self.rows[:2]
        self.rows = header + [self.call("exec_command", cmd=f"cat '{skill}'"),
            self.call("exec_command", cmd=f"sed -n '1,220p' '{skill}'"),
            self.call("exec_command", cmd=f"sed -n '221,460p' '{skill}'")]
        self.assertEqual(self.audit(framework_root=framework, require_preflight_order=True)["status"], "passed")
        for command in (f"sed -n '1,20p' {framework}/playbooks/techops_issue_remediation.md",
                        f"sed -n '1,20p' {framework}/other/skills/run/SKILL.md",
                        f"sed -n '1p;w /tmp/copied' {skill}",
                        f"sed -n '1,20p' {skill}; cat {framework}/contracts/workflow_execution.md"):
            with self.subTest(command=command):
                self.rows = header + [self.call("exec_command", cmd=command)]
                self.assertIn("parent_framework_content_before_preflight",
                              self.audit(framework_root=framework, require_preflight_order=True)["errors"])

    def test_external_connector_calls_are_ordered_after_preflight(self):
        framework = self.root / "framework"
        issue_read = self.call("mcp__atlassian__get_issue", issue_key="ECHO-2806")
        self.rows.append(issue_read)
        result = self.audit(framework_root=framework, require_preflight_order=True)
        self.assertIn("parent_framework_content_before_preflight", result["errors"])

        preflight = f"python3 {framework}/scripts/run_preflight.py"
        observed = {"type": "event_msg", "payload": {"type": "item_completed", "item": {
            "type": "CommandExecution", "command": ["/bin/bash", "-lc", preflight],
            "status": "completed", "exit_code": 0,
            "aggregated_output": json.dumps({"status": "passed"})}}}
        self.rows = self.rows[:2] + [self.call("exec_command", cmd=preflight), observed, issue_read]
        self.assertEqual(self.audit(framework_root=framework, require_preflight_order=True)["status"], "passed")

    def test_shipped_status_projection_matches_the_audit_allowlist(self):
        skill = (Path(__file__).resolve().parents[1] / "skills" / "run" / "SKILL.md").read_text()
        section = skill.split("this exact projection", 1)[1]
        snippet = section.split("```javascript\n", 1)[1].split("\n   ```", 1)[0]
        prior_id = "00000000-0000-0000-0000-000000000004"
        expected = related_run_status_projection_source("ECHO-2806", PARENT, (prior_id,))
        expected = expected.replace(json.dumps(PARENT), '"PARENT-THREAD-UUID"')
        expected = expected.replace(json.dumps([prior_id]), '["PRIOR-WORKER-THREAD-UUID"]')
        self.assertEqual(textwrap.dedent(snippet).strip(), expected)

    def test_missing_turn_wrong_parent_and_unparsed_calls_cannot_pass(self):
        with self.assertRaisesRegex(ValueError, "parent_mismatch"):
            self.audit(expected_thread_id=CHILD)
        self.rows.pop()
        with self.assertRaisesRegex(ValueError, "current_turn_unavailable"):
            self.audit()
        self.rows.append({"type": "turn_context", "payload": {"turn_id": TURN}})
        self.rows.append({"type": "response_item", "payload": {"type": "custom_tool_call",
            "input": "await tools.exec_command(argumentsFromElsewhere)"}})
        self.assertIn("parent_tool_arguments_unavailable", self.audit()["errors"])
        self.rows[-1]["payload"]["input"] = (
            'const cmds = [["first", "cat /repo/one"], ["second", "cat /repo/two"]]; '
            "const results = await Promise.allSettled(cmds.map(async ([label, cmd]) => { "
            "const r = await tools.exec_command({cmd}); return {label, ...r}; })); "
            "for (const r of results) text(JSON.stringify(r));"
        )
        self.assertIn("parent_tool_arguments_unavailable", self.audit()["errors"])
        from scripts.runtime_checks import _tool_operations
        self.rows[-1]["payload"]["input"] = (
            "const reads = await Promise.allSettled(["
            'tools.exec_command({cmd:"cat /repo/one"}),'
            'tools.exec_command({cmd:"cat /repo/two"})]);'
        )
        self.assertEqual(_tool_operations(self.rows[-1]["payload"]), [
            ("exec_command", {"cmd": "cat /repo/one"}),
            ("exec_command", {"cmd": "cat /repo/two"}),
        ])

    def test_literal_assigned_thread_batch_is_audited_without_executing_the_loop(self):
        child_two = "00000000-0000-0000-0000-000000000004"
        for child, handle in ((CHILD, "/root/first"), (child_two, "/root/second")):
            self.rows.append({"type": "event_msg", "payload": {"item": {
                "type": "SubAgentActivity", "kind": "started", "agent_path": handle,
                "agent_thread_id": child}}})
        source = (
            f'const ids = [["{CHILD}", "/root/first"], ["{child_two}", "/root/second"]];\n'
            'for (const [threadId, handle] of ids) {\n'
            '  const r = await tools.mcp__codex_app__read_thread({threadId, turnLimit: 1, '
            'includeOutputs: false, maxOutputCharsPerItem: 1});\n'
            '  text(JSON.stringify({handle, result: r}));\n'
            '}')
        self.rows.append({"type": "response_item", "payload": {"type": "custom_tool_call", "name": "exec",
            "input": source}})
        result = self.audit()
        self.assertEqual(result["status"], "passed", result)

        self.rows[-1]["payload"]["input"] = source.replace(child_two, TURN)
        result = self.audit()
        self.assertIn("parent_unassigned_thread_read:" + TURN, result["errors"])
        self.assertNotIn("parent_tool_arguments_unavailable", result["errors"])

        self.rows[-1]["payload"]["input"] = source + '\nawait tools.exec_command({cmd:"cat /repo/other"})'
        self.assertIn("parent_tool_arguments_unavailable", self.audit()["errors"])

    def test_literal_wait_batch_checks_every_target_and_rejects_extra_operations(self):
        from scripts.provider_runtime import _literal_parent_thread_read_batch
        source = ('const ids=' + json.dumps([CHILD, TURN]) + ';\n'
            'const rs=await Promise.allSettled(ids.map(threadId=>tools.mcp__codex_app__wait_threads({targets:[{threadId,hostId:"local"}],timeoutMs:0})));\n'
            'for(let i=0;i<rs.length;i++){\n'
            ' if(rs[i].status!=="fulfilled"){text(JSON.stringify({i,error:String(rs[i].reason)}));continue;}\n'
            ' const raw=rs[i].value.content?.[0]?.text||"";\n'
            ' try {const d=JSON.parse(raw); const p=d.polls?.[0]||{}; text(JSON.stringify({i,threadId:ids[i],wake:d.wake,thread:p.thread,latestTurn:p.latestTurn,revision:p.revision,cursor:p.cursor}));} catch {text(JSON.stringify({i,raw:raw.slice(0,200)}));}\n'
            '}\n')
        rows = _literal_parent_thread_read_batch(source)
        self.assertEqual([row[1]["targets"][0]["threadId"] for row in rows], [CHILD, TURN])
        self.assertIsNone(_literal_parent_thread_read_batch(source + 'await tools.exec_command({cmd:"cat x"});'))
        self.assertIsNone(_literal_parent_thread_read_batch(source.replace(CHILD, "not-a-uuid")))
        self.assertIsNone(_literal_parent_thread_read_batch(source.replace('timeoutMs:0', 'timeoutMs:0, extra:true')))

    def test_literal_const_tool_arguments_are_audited_but_dynamic_values_fail_closed(self):
        patch = ("*** Begin Patch\n*** Add File: " + str(self.root / ".thoughts" / "ITEM-1" / "runs" /
                 "current" / "receipt.json") + "\n+{}\n*** End Patch")
        self.rows.append({"type": "response_item", "payload": {"type": "custom_tool_call", "name": "exec",
            "input": "const patch = " + json.dumps(patch) + "; await tools.apply_patch(patch);"}})
        result = self.audit(artifact_root=self.root / ".thoughts" / "ITEM-1")
        self.assertNotIn("parent_tool_arguments_unavailable", result["errors"])
        self.assertIn("forbidden_context_reference:archived_artifact", result["errors"])

        self.rows[-1]["payload"]["input"] = "const patch = buildPatch(); await tools.apply_patch(patch);"
        self.assertIn("parent_tool_arguments_unavailable", self.audit()["errors"])

        for source in (
            "const patch = 'safe' + 'unreviewed'; await tools.apply_patch(patch);",
            "const command = 'cat ' + '/repo/.codex/memories/MEMORY.md'; "
            "await tools.exec_command({cmd: command});",
            "const patch = 'safe'\n+ 'unreviewed'; await tools.apply_patch(patch);",
        ):
            self.rows[-1]["payload"]["input"] = source
            self.assertIn("parent_tool_arguments_unavailable", self.audit()["errors"])

        self.rows[-1]["payload"]["input"] = "const patch = 'safe'\nawait tools.apply_patch(patch);"
        self.assertEqual(self.audit()["status"], "passed")

        for source in (
            "const patch = 'safe'; patch = buildPatch(); await tools.apply_patch(patch);",
            "const patch = 'safe'; { let patch = buildPatch(); } await tools.apply_patch(patch);",
            "const patch = 'safe'; function apply(patch) { tools.apply_patch(patch); }",
            "const patch = 'safe'; const target = { apply(patch) { tools.apply_patch(patch); } };",
        ):
            self.rows[-1]["payload"]["input"] = source
            self.assertIn("parent_tool_arguments_unavailable", self.audit()["errors"])

    def test_immediate_literal_array_join_resolves_without_executing_javascript(self):
        from scripts.runtime_checks import _tool_operations
        source = ('const script="/package/scripts/guard.py";\n'
                  'const args=["python3",script,"--assignment","/repo/.thoughts/ITEM-1/assignment.json"].join(" ");\n'
                  'const r=await tools.exec_command({cmd:args,login:false}); text(r.output);')
        row = {"type": "custom_tool_call", "name": "exec", "input": source}
        self.assertEqual(_tool_operations(row), [("exec_command", {
            "cmd": "python3 /package/scripts/guard.py --assignment /repo/.thoughts/ITEM-1/assignment.json",
            "login": False})])
        for invalid in (source.replace('const script=', 'let script='),
                        source.replace('"python3",script', '"python3",unknown'),
                        source.replace('"python3",script', '"python3",resolve()'),
                        source.replace('.join(" ")', '.join(separator)'),
                        source.replace('const args=', 'let args='),
                        source.replace('const args=[', 'const parts=[').replace(
                            '].join(" ");', ']; const args=parts.join(" ");'),
                        source.replace('const r=await', 'args=resolve(); const r=await')):
            with self.subTest(source=invalid):
                self.assertEqual(_tool_operations({**row, "input": invalid}), [])

    def test_template_arguments_resolve_only_known_literal_constants(self):
        from scripts.runtime_checks import _tool_operations
        source = ('const base="/package/scripts"; const root="/repo/.thoughts/ITEM-1"; '
                  'const result=await tools.exec_command({cmd:`python3 ${base}/collector.py --ledger ${root}/ledger.json`,'
                  'workdir:"/repo"}); text(result.output);')
        row = {"type": "custom_tool_call", "name": "exec", "input": source}
        self.assertEqual(_tool_operations(row), [("exec_command", {
            "cmd": "python3 /package/scripts/collector.py --ledger /repo/.thoughts/ITEM-1/ledger.json",
            "workdir": "/repo"})])
        for invalid in (source.replace('const base="/package/scripts"', 'let base="/package/scripts"'),
                        source.replace('${base}', '${missing}'),
                        source.replace('${base}', '${result.output}'),
                        source.replace('${base}', '${resolve()}'),
                        source.replace('${base}', '${base + root}'),
                        source.replace('const result=', 'base=resolve(); const result='),
                        source.replace('const result=', '{ let base="other"; } const result='),
                        source.replace('${base}', r'\${base}')):
            with self.subTest(source=invalid):
                self.assertEqual(_tool_operations({**row, "input": invalid}), [])
        logged = source + " text(`exit_code=${result.exit_code}`);"
        self.assertEqual(_tool_operations({**row, "input": logged}), _tool_operations(row))
        native_shape = source.replace(" --ledger", " --parent-thread-id 00000000-0000-0000-0000-000000000001 "
                                      "--started-at 2026-10-22T03:49:11.414904Z --ledger")
        self.assertEqual(len(_tool_operations({**row, "input": native_shape})), 1)
        self.rows.append({"type": "response_item", "payload": row})
        self.assertNotIn("parent_tool_arguments_unavailable", self.audit()["errors"])
        self.rows[-1]["payload"] = {**row, "input": source.replace("ledger.json", "runs/prior/notes.md")}
        self.assertIn("forbidden_context_reference:archived_artifact", self.audit()["errors"])

    def test_literal_jira_call_allows_output_property_checks(self):
        from scripts.runtime_checks import _tool_operations
        call = ('const r=await tools.mcp__atlassian__getJiraIssue('
                '{cloudId:"https://example.atlassian.net",issueIdOrKey:"ITEM-1"}); ')
        output = ('for (const c of (r?.content||[])) if(c.type==="text") text(c.text); '
                  'text(`isError=${r?.isError===true}`);')
        row = {"type": "custom_tool_call", "name": "exec", "input": call + output}
        self.assertEqual(_tool_operations(row), [("mcp__atlassian__getJiraIssue", {
            "cloudId": "https://example.atlassian.net", "issueIdOrKey": "ITEM-1"})])
        self.rows.append({"type": "response_item", "payload": row})
        self.assertNotIn("parent_tool_arguments_unavailable", self.audit()["errors"])
        for source in (
                call + 'text(`value=${resolve()}`);',
                call + 'text(`value=${tools.exec_command({cmd:"bad"})}`);',
                'await tools.exec_command({cmd:`${r?.isError===true}`});',
                'await tools.exec_command({cmd:r?.output});'):
            with self.subTest(source=source):
                self.assertEqual(_tool_operations({**row, "input": source}), [])

    def test_preparation_accepts_literal_const_manifest_creation(self):
        inputs = self.root / "inputs.json"
        inputs.write_text(json.dumps({"inputs": [{"Input ID": "IN-001", "Input or artifact": "Current issue",
            "Source or path": "User", "Authority": "User", "Status": "Verified"}]}))
        patch = ("*** Begin Patch\n*** Add File: " + str(self.root / "inputs.json") + "\n+{}\n*** End Patch")
        self.rows.append({"type": "response_item", "payload": {"type": "custom_tool_call", "name": "exec",
            "input": "const patch = " + json.dumps(patch) + "; await tools.apply_patch(patch);"}})
        self.assertEqual(self.audit()["status"], "passed")
        run = prepare_run(self.root, "ITEM-1", "feature_delivery", None, False,
                          input_manifest=inputs, provider_session=self.source)
        self.assertEqual(run["status"], "prepared")

    def test_staging_manifest_inside_work_item_preserves_work_item_isolation(self):
        for sibling in (True, False):
            with self.subTest(sibling_work_item=sibling):
                inputs = self.root / (".thoughts/ITEM-1-inputs.json" if sibling else ".thoughts/ITEM-1/intake_inputs.json")
                inputs.parent.mkdir(parents=True, exist_ok=True)
                inputs.write_text(json.dumps({"inputs": [{"Input ID": "IN-001", "Input or artifact": "Current issue",
                    "Source or path": "User", "Authority": "User", "Status": "Verified"}]}))
                patch = "*** Begin Patch\n*** Add File: " + str(inputs) + "\n+{}\n*** End Patch"
                self.rows = self.rows[:2] + [self.call("apply_patch", patch=patch),
                    self.call("exec_command", cmd="python3 prepare_run.py --input-manifest " + str(inputs))]
                self.audit()
                if sibling:
                    with self.assertRaisesRegex(ValueError, "forbidden_context_reference:archived_artifact"):
                        prepare_run(self.root, "ITEM-1", "techops_issue_remediation", None, False,
                                    input_manifest=inputs, provider_session=self.source)
                    self.assertFalse((self.root / ".thoughts/ITEM-1").exists())
                else:
                    run = prepare_run(self.root, "ITEM-1", "techops_issue_remediation", None, False,
                                      input_manifest=inputs, provider_session=self.source)
                    self.assertEqual(run["status"], "prepared")
                    self.assertTrue(inputs.is_file())
                    self.assertTrue((inputs.parent / "run_inputs.json").is_file())

    def test_inline_manifest_command_passes_parent_audit_and_prepares(self):
        inputs = {"inputs": [{"Input ID": "IN-001", "Input or artifact": "User's current issue",
            "Source or path": "User", "Authority": "User", "Status": "Verified"}]}
        script = Path(__file__).resolve().parents[1] / "scripts/prepare_run.py"
        args = ["python3", str(script), "--execution-repository", str(self.root), "--work-item", "ITEM-1",
                "--playbook", "techops_issue_remediation", "--input-json", json.dumps(inputs),
                "--provider-session", str(self.source)]
        self.rows.append(self.call("exec_command", cmd=shlex.join(args)))
        self.assertEqual(self.audit(artifact_root=self.root / ".thoughts/ITEM-1")["status"], "passed")
        result = subprocess.run(args, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        prepared = json.loads(result.stdout)
        self.assertEqual(prepared["run_input_manifest_status"], "explicit")
        self.assertFalse((self.root / ".thoughts/ITEM-1/intake_inputs.json").exists())
        prior = {p.relative_to(self.root): p.read_bytes() for p in (self.root / ".thoughts").rglob("*") if p.is_file()}
        args[args.index("--input-json") + 1] = "null"
        rejected = subprocess.run(args, capture_output=True, text=True, timeout=30)
        self.assertEqual(rejected.returncode, 2)
        self.assertEqual(json.loads(rejected.stdout)["reason"], "run_input_manifest_invalid")
        self.assertEqual(prior, {p.relative_to(self.root): p.read_bytes()
                                 for p in (self.root / ".thoughts").rglob("*") if p.is_file()})

    def test_preparation_is_transactional_and_activation_rechecks_later_reads(self):
        inputs = self.root / "inputs.json"
        inputs.write_text(json.dumps({"inputs": [{"Input ID": "IN-001", "Input or artifact": "Current issue",
            "Source or path": "User", "Authority": "User", "Status": "Verified"}]}))
        self.rows.append(self.call("exec_command", cmd="cat /repo/.codex/memories/MEMORY.md"))
        self.audit()
        with self.assertRaisesRegex(ValueError, "parent_context_nonconformant"):
            prepare_run(self.root, "ITEM-1", "feature_delivery", None, False,
                        input_manifest=inputs, provider_session=self.source)
        self.assertFalse((self.root / ".thoughts").exists())
        self.rows.pop()
        self.audit()
        run = prepare_run(self.root, "ITEM-1", "feature_delivery", None, False,
                          input_manifest=inputs, provider_session=self.source)
        bundle = run["activation_packet_bundle"]
        check = lambda: activation_packet_errors(Path(bundle["path"]), "current_state_investigator", bundle["sha256"])
        self.assertEqual(check(), [])
        self.rows.append(self.call("exec_command", cmd="cat /repo/.codex/memories/MEMORY.md"))
        self.audit()
        self.assertTrue(any(error.startswith("parent_context_nonconformant") for error in check()))
        self.rows.append({"type": "turn_context", "timestamp": "2026-10-01T00:00:03Z",
                          "payload": {"turn_id": CHILD}})
        self.audit()
        self.assertTrue(any(error.startswith("parent_context_turn_mismatch:expected=" + TURN)
                            for error in check()))


if __name__ == "__main__":
    unittest.main()
