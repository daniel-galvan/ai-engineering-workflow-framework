"""Native parent context boundaries before preparation and worker activation."""

import io
import hashlib
import json
import sys
import os
import shlex
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts.prepare_run import _archive_existing_run, prepare_run
from scripts.provider_runtime import (
    parent_context_audit,
    prior_run_status_thread_ids,
    related_run_status_projection_source,
    scoped_prior_run_status_thread_ids,
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

    def test_native_preflight_proves_only_the_bound_package_selection(self):
        from scripts.provider_runtime import native_preflight_observed
        root = self.root.resolve() / "framework"
        command = "python3 " + str(root / "scripts/run_preflight.py")
        result = {"status": "passed", "framework_revision": "a" * 40, "framework_root": str(root),
                  "framework_status": "clean", "plugin_version": "0.5.33+fixture"}
        for change in ("valid", "turn", "revision", "version", "root", "script", "shell", "interpreter", "failed", "output"):
            rows = json.loads(json.dumps(self.rows))
            item = {"type": "CommandExecution", "command": ["bash", "-lc", command],
                    "status": "completed", "exit_code": 0, "aggregated_output": json.dumps(result)}
            if change == "turn": rows[-1]["payload"]["turn_id"] = CHILD
            elif change in {"revision", "version", "root"}:
                fields = {"revision": "framework_revision", "version": "plugin_version", "root": "framework_root"}
                altered = dict(result); altered[fields[change]] = "other"
                item["aggregated_output"] = json.dumps(altered)
            elif change == "script": item["command"][-1] = "python3 /tmp/run_preflight.py"
            elif change == "shell": item["command"][-1] += "; cat /tmp/extra"
            elif change == "interpreter": item["command"][-1] = command.replace("python3", "/tmp/python3", 1)
            elif change == "failed": item["exit_code"] = 2
            elif change == "output": item["aggregated_output"] = "No structured observation"
            rows.append({"type": "event_msg", "payload": {"type": "item_completed", "item": item}})
            self.source.write_text("".join(json.dumps(row) + "\n" for row in rows))
            with self.subTest(change=change):
                self.assertEqual(native_preflight_observed(self.source, TURN, root, "a" * 40, "0.5.33+fixture"), change == "valid")

    def test_native_finalization_requires_exact_original_command_and_report(self):
        from scripts.provider_runtime import native_finalization_observed
        root = self.root.resolve() / "framework"
        packet = self.root.resolve() / "finalization_packet.json"
        record = packet.parent / "work_record.md"
        canonical = b"Canonical report\n"
        command = shlex.join(["python3", str(root / "scripts/finalize_work_record.py"),
            "--packet", str(packet), "--closure", str(packet.parent / "runtime_closure.json"),
            "--record", str(record), "--framework-revision", "a" * 40, "--framework-status", "clean"])
        for change in ("valid", "turn", "packet", "record", "revision", "script", "interpreter", "shell",
                       "precheck", "duplicate", "failed", "output"):
            rows = json.loads(json.dumps(self.rows))
            item = {"type": "CommandExecution", "command": ["bash", "-lc", command],
                    "status": "completed", "exit_code": 0,
                    "aggregated_output": "Delivery pending: fixture\nWorkflow-framework validation: passed\nCanonical report\n"}
            if change == "turn": rows[-1]["payload"]["turn_id"] = CHILD
            elif change in {"packet", "record", "script", "revision", "interpreter"}:
                old = {"packet": str(packet), "record": str(record), "script": str(root / "scripts/finalize_work_record.py"),
                       "revision": "a" * 40, "interpreter": "python3"}[change]
                item["command"][-1] = command.replace(old, "/tmp/other", 1)
            elif change == "shell": item["command"][-1] += "; cat /tmp/extra"
            elif change == "precheck": item["command"][-1] += " --pre-release"
            elif change == "duplicate": item["command"][-1] += " --record " + str(record)
            elif change == "failed": item["exit_code"] = 2
            elif change == "output": item["aggregated_output"] += "Changed report"
            rows.append({"type": "event_msg", "payload": {"type": "item_completed", "item": item}})
            self.source.write_text("".join(json.dumps(row) + "\n" for row in rows))
            with self.subTest(change=change):
                self.assertEqual(native_finalization_observed(self.source, TURN, root, packet, record, "a" * 40, canonical), change == "valid")

    def test_host_memory_citation_write_is_rejected(self):
        codex = self.root / "codex"
        memory = codex / "memories" / "raw_memories.md"
        directive = {"type": "response_item", "payload": {"type": "message", "role": "developer",
            "content": [{"type": "input_text", "text": "Decision boundary MEMORY_SUMMARY " + str(memory)}]}}
        artifact = self.root / "repo" / ".thoughts" / "ITEM-1"
        artifact.mkdir(parents=True)
        target = artifact / "handoff_presentation_suffix.md"
        citation = "<oai-mem-citation>\n<citation_entries>\nraw_memories.md:1-2|note=[historical context]\n</citation_entries>\n<rollout_ids>\n</rollout_ids>\n</oai-mem-citation>"
        target.write_text(citation)
        command = ("python3 - <<'PY'\nfrom pathlib import Path\n"
                   f"p=Path({str(target)!r})\np.write_text({citation!r})\nprint(p)\nprint(p.read_text())\nPY")
        observation = {"type": "event_msg", "payload": {"type": "item_completed", "item": {
            "type": "CommandExecution", "command": ["bash", "-lc", command], "status": "completed", "exit_code": 0}}}
        self.rows.extend([directive, self.call("exec_command", cmd=command), observation])
        with patch.dict(os.environ, {"CODEX_HOME": str(codex)}):
            errors = self.audit(artifact_root=artifact)["errors"]
            self.assertIn("forbidden_context_reference:memory_citation", errors)
            for unsafe in (command.replace(str(target), str(self.root / "outside.md")),
                           command.replace("\nPY", "\nopen('.thoughts/OTHER/runs/prior/notes.md').read()\nPY"),
                           command.replace("raw_memories.md:1-2", "raw_memories.md:2-1")):
                self.rows[-2] = self.call("exec_command", cmd=unsafe)
            self.assertEqual(self.audit(artifact_root=artifact)["status"], "rejected")
            self.rows[-2] = self.call("exec_command", cmd=command)
            directive["payload"]["role"] = "user"
            self.assertIn("forbidden_context_reference:memory_citation", self.audit(artifact_root=artifact)["errors"])
            directive["payload"]["role"] = "developer"
            self.rows.pop()
            self.assertIn("forbidden_context_reference:memory_citation", self.audit(artifact_root=artifact)["errors"])

    def test_injected_host_memory_does_not_authorize_memory_reads(self):
        codex = self.root / "codex"
        memory = codex / "memories" / "raw_memories.md"
        memory.parent.mkdir(parents=True)
        memory.write_text("relevant historical note\n")
        directive = {"type": "response_item", "payload": {"type": "message", "role": "developer",
            "content": [{"type": "input_text", "text": "## Memory\nDecision boundary\nMEMORY_SUMMARY\n" + str(memory)}]}}
        search = "rg -n -i 'ITEM-1|workflow' " + str(memory)
        read = "nl -ba " + str(memory) + " | sed -n '1,20p'"
        def observation(command):
            return {"type": "event_msg", "payload": {"type": "item_completed", "item": {
                "type": "CommandExecution", "command": ["/bin/bash", "-lc", command],
                "status": "completed", "exit_code": 0, "aggregated_output": "historical note"}}}
        self.rows[1:1] = [directive]
        self.rows.extend([self.call("exec_command", cmd=search), observation(search),
                          self.call("exec_command", cmd=read), observation(read)])
        with patch.dict(os.environ, {"CODEX_HOME": str(codex)}):
            result = self.audit(framework_root=self.root / "framework", require_preflight_order=True)
            self.assertEqual(result["status"], "rejected", result)
            self.assertEqual(result["host_memory_reads"], 0)
            self.assertIn("forbidden_context_reference:memory_path", result["errors"])
            self.assertIn("parent_framework_content_before_preflight", result["errors"])
            directive["payload"]["role"] = "user"
            self.assertIn("forbidden_context_reference:memory_path", self.audit()["errors"])
            directive["payload"]["role"] = "developer"
            observed = self.rows.pop()
            self.assertIn("forbidden_context_reference:memory_path", self.audit()["errors"])
            self.rows.append(observed)
            self.rows[-2] = self.call("exec_command", cmd=read + " ; cat /secret")
            self.assertIn("forbidden_context_reference:memory_path", self.audit()["errors"])

    def test_host_memory_cannot_authorize_reading_a_linked_session_log(self):
        codex = self.root / "codex"
        memory = codex / "memories" / "raw_memories.md"
        memory.parent.mkdir(parents=True)
        session = codex / "sessions" / "prior.jsonl"
        session.parent.mkdir()
        session.write_text("{}\n")
        marker = {"type": "response_item", "payload": {"type": "message", "role": "developer",
            "content": [{"type": "input_text", "text": "Decision boundary MEMORY_SUMMARY " + str(memory)}]}}
        search = "rg -n ITEM " + str(memory)
        read = "cat " + str(session)
        def observation(command, output):
            return {"type": "event_msg", "payload": {"type": "item_completed", "item": {
                "type": "CommandExecution", "command": ["bash", "-lc", command],
                "status": "completed", "exit_code": 0, "aggregated_output": output}}}
        self.rows[1:1] = [marker]
        with patch.dict(os.environ, {"CODEX_HOME": str(codex)}):
            self.rows.extend([self.call("exec_command", cmd=search), observation(search, "rollout_path=" + str(session)),
                              self.call("exec_command", cmd=read), observation(read, "{}")])
            result = self.audit(framework_root=self.root / "framework", require_preflight_order=True)
            self.assertEqual(result["status"], "rejected", result)
            self.assertIn("forbidden_context_reference:memory_path", result["errors"])
            self.assertIn("forbidden_context_reference:session_log", result["errors"])

    def test_actual_memory_read_is_rejected_but_quotes_and_prior_turn_are_ignored(self):
        memory = "/repo/.codex/memories/raw_memories.md"
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
            ('cat "$CODEX_HOME/memories/raw_memories.md"', "memory_path"),
            ('rg -n issue "${CODEX_HOME}/memories/notes.md"', "memory_directory"),
            ('rg -n issue "$CODEX_HOME"/memories/notes.md', "memory_directory"),
            ('rg -n issue "${CODEX_HOME}"/memories/notes.md', "memory_directory"),
            (r'rg -n issue "$env:CODEX_HOME"\memories\notes.md', "memory_directory"),
            ('cat "$CODEX_HOME/sessions/prior.jsonl"', "session_log"),
        ):
            with self.subTest(command=command):
                self.rows = self.rows[:2] + [self.call("exec_command", cmd=command)]
                self.assertIn("forbidden_context_reference:" + expected, self.audit()["errors"])

    def test_verified_no_match_memory_search_is_still_forbidden(self):
        memory = "/Users/example/.codex/memories/raw_memories.md"
        command = "rg -n 'ECHO-2806|planning' " + memory
        self.rows.extend([self.call("exec_command", cmd=command), self.command_execution(command)])
        result = self.audit()
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["empty_memory_probes"], 0)
        self.assertIn("forbidden_context_reference:memory_path", result["errors"])

    def test_verified_fixed_string_memory_search_is_still_forbidden(self):
        memory = "/Users/example/.codex/memories/raw_memories.md"
        command = "rg -n -F 'ECHO-2806' " + memory
        parsed = [{"type": "search", "cmd": "rg -n -F ECHO-2806 " + memory,
                  "query": "ECHO-2806", "path": "raw_memories.md"}]
        self.rows.extend([self.call("exec_command", cmd=command),
                          self.command_execution(command, parsed_cmd=parsed)])
        result = self.audit()
        self.assertEqual(result["status"], "rejected", result)
        self.assertEqual(result["empty_memory_probes"], 0)
        self.assertIn("forbidden_context_reference:memory_path", result["errors"])

    def test_no_match_host_memory_search_cannot_precede_preflight(self):
        framework = self.root / "framework"
        memory = "/Users/example/.codex/memories/raw_memories.md"
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
        self.assertEqual(result["status"], "rejected", result)
        self.assertEqual(result["empty_memory_probes"], 0)
        self.assertIn("forbidden_context_reference:memory_path", result["errors"])

    def test_nonempty_memory_probe_still_blocks_preflight_order(self):
        framework = self.root / "framework"
        memory = "/Users/example/.codex/memories/raw_memories.md"
        search = "rg -n 'ECHO-2806|planning' " + memory
        preflight = f"python3 {framework}/scripts/run_preflight.py"
        self.rows.extend([self.call("exec_command", cmd=search),
                          self.command_execution(search, exit_code=0, output="match")])
        result = self.audit(framework_root=framework, require_preflight_order=True)
        self.assertIn("parent_framework_content_before_preflight", result["errors"])
        self.assertIn("forbidden_context_reference:memory_path", result["errors"])

    def test_empty_memory_probe_with_startup_warning_is_still_forbidden(self):
        memory = "/Users/example/.codex/memories/raw_memories.md"
        query = "ECHO-2806|Issue Remediation|issue_remediation"
        command = "rg -n -i " + shlex.quote(query) + " " + memory
        warning = ("WARNING: proceeding, even though we could not create PATH aliases: "
                   "Operation not permitted (os error 1)\n")
        parsed = [{"type": "search", "cmd": command, "query": query, "path": "raw_memories.md"}]
        self.rows.extend([self.call("exec_command", cmd=command),
                          self.command_execution(command, output=warning, parsed_cmd=parsed)])
        result = self.audit()
        self.assertEqual(result["status"], "rejected", result)
        self.assertEqual(result["empty_memory_probes"], 0)
        self.assertIn("forbidden_context_reference:memory_path", result["errors"])

        self.rows[-1]["payload"]["item"]["aggregated_output"] += "raw_memories.md:7: ECHO-2806"
        result = self.audit()
        self.assertIn("forbidden_context_reference:memory_path", result["errors"])

    def test_case_insensitive_memory_search_is_still_forbidden(self):
        memory = "/Users/example/.codex/memories/raw_memories.md"
        query = "ECHO-2806|Issue Remediation|issue_remediation"
        command = "rg -n -i " + shlex.quote(query) + " " + memory
        parsed = [{"type": "search", "cmd": command, "query": query, "path": "raw_memories.md"}]
        self.rows.extend([self.call("exec_command", cmd=command),
                          self.command_execution(command, parsed_cmd=parsed)])
        result = self.audit()
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["empty_memory_probes"], 0)
        self.assertIn("forbidden_context_reference:memory_path", result["errors"])

        forged = self.command_execution(command, parsed_cmd=[
            {"type": "search", "cmd": command, "query": query, "path": "/tmp/raw_memories.md"}])
        self.rows = self.rows[:2] + [self.call("exec_command", cmd=command), forged]
        result = self.audit()
        self.assertIn("forbidden_context_reference:memory_path", result["errors"])

    def test_no_match_probe_cannot_share_native_run_skill_bootstrap_command(self):
        framework = self.root / "framework"
        skill = framework / "skills" / "run" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("# Active run instructions\n" * 4)
        memory = Path("/Users/example/.codex/memories/raw_memories.md")
        query = "ECHO-2806|Issue Remediation|techops_issue_remediation"
        search = "rg -n " + shlex.quote(query) + " " + str(memory)
        command = "cat " + shlex.quote(str(skill)) + " && " + search
        observation = {"type": "event_msg", "payload": {"type": "item_completed", "item": {
            "type": "CommandExecution", "command": ["/bin/bash", "-lc", command],
            "status": "failed", "exit_code": 1, "aggregated_output": skill.read_text(),
            "parsed_cmd": [{"type": "read", "cmd": "cat " + str(skill), "path": str(skill)},
                           {"type": "search", "cmd": search, "query": query, "path": "raw_memories.md"}]}}}
        self.rows.extend([self.call("exec_command", cmd=command), observation])
        result = self.audit(framework_root=framework, require_preflight_order=True)
        self.assertEqual(result["status"], "rejected", result)
        self.assertIn("parent_framework_content_before_preflight", result["errors"])
        self.assertEqual(result["empty_memory_probes"], 0)

        observation["payload"]["item"]["aggregated_output"] += "match from memory"
        result = self.audit(framework_root=framework, require_preflight_order=True)
        self.assertEqual(result["empty_memory_probes"], 0)
        self.assertTrue(any(error.startswith("forbidden_context_reference:memory_")
                            for error in result["errors"]))

    def test_memory_search_is_not_exempt_without_exact_native_no_match_evidence(self):
        memory = "/Users/example/.codex/memories/raw_memories.md"
        command = "rg -n issue " + memory
        variants = (
            None,
            self.command_execution(command, exit_code=0),
            self.command_execution(command, output="matched text"),
            self.command_execution(command, status="completed"),
            self.command_execution(command, parsed_cmd=[
                {"type": "search", "query": "issue", "path": "raw_memories.md"},
                {"type": "search", "query": "issue", "path": "raw_memories.md"},
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

    def test_legacy_title_based_status_projection_is_rejected(self):
        artifact_root = self.root / ".thoughts" / "ECHO-2806"
        legacy = ("const response = await tools.mcp__codex_app__list_threads({limit:50});\n"
                  "const data = JSON.parse(response.content[0].text);\n"
                  "const related = data.threads.filter(row => row.title.includes('ECHO-2806'));\n")
        self.rows.append({"type": "response_item", "payload": {"type": "custom_tool_call",
            "name": "exec", "call_id": "legacy-status", "input": legacy}})
        self.assertIn("parent_unassigned_thread_discovery", self.audit(artifact_root=artifact_root)["errors"])

    @unittest.skipUnless(shutil.which("node"), "Node.js required to execute the provider JavaScript")
    def test_related_status_projection_returns_only_explicit_id_status(self):
        prior = {"wake": None, "polls": [{
            "thread": {"id": CHILD, "status": {"type": "idle", "activeFlags": []}},
            "latestTurn": {"status": "completed"},
            "preview": "private worker prompt", "items": [{"text": "private worker output"}],
        }]}
        projection = related_run_status_projection_source("ECHO-2806", PARENT, (CHILD,))
        stub = ("const calls = [];\nconst tools = {mcp__codex_app__list_threads: async () => {\n"
                "  calls.push('list_threads'); throw new Error('must not inventory provider threads');\n"
                "}, mcp__codex_app__read_thread: async () => { throw new Error('must not read chat history'); },\n"
                "mcp__codex_app__wait_threads: async args => {\n"
                "  calls.push(...args.targets.map(row => row.threadId));\n"
                "  if (args.timeoutMs !== 0 || args.targets.length !== 1 || 'hostId' in args.targets[0])\n"
                "    throw new Error('unexpected exact-id status request');\n"
                "  if (args.targets[0].threadId !== " + json.dumps(CHILD) + ")\n"
                "    throw new Error('unexpected exact-id target');\n"
                "  return {content: [{text: JSON.stringify(" + json.dumps(prior) + ")} ]};\n"
                "}};\nconst text = value => process.stdout.write(JSON.stringify({rows: JSON.parse(value), calls}));\n")
        result = subprocess.run([shutil.which("node"), "--input-type=module", "-"], input=stub + projection,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"rows": [{"id": CHILD, "status": "completed"}],
                                                      "calls": [CHILD]})
        self.assertNotIn("private", result.stdout)
        self.assertNotIn("mcp__codex_app__read_thread", projection)
        skill = (Path(__file__).resolve().parents[1] / "skills/run/SKILL.md").read_text()
        example = textwrap.dedent(skill.split("   ```javascript\n", 1)[1].split("   ```", 1)[0])
        example = example.replace("PRIOR-WORKER-THREAD-UUID", CHILD)
        self.assertEqual(example.strip(), projection)

    @unittest.skipUnless(shutil.which("node"), "Node.js required to execute the provider JavaScript")
    def test_related_status_projection_checks_each_worker_when_wait_returns_only_one(self):
        projection = related_run_status_projection_source("ECHO-2806", PARENT, (CHILD, TURN))
        stub = textwrap.dedent("""
            const calls = [];
            const tools = {mcp__codex_app__wait_threads: async args => {
              calls.push(args.targets.map(row => row.threadId));
              const id = args.targets[0].threadId;
              return {content: [{text: JSON.stringify({
                wake: {reason: 'inactiveStatus', threadId: id},
                polls: [{thread: {id, status: {type: 'notLoaded'}}, latestTurn: {status: 'completed'}}]
              })}]};
            }};
            const text = value => process.stdout.write(JSON.stringify({rows: JSON.parse(value), calls}));
        """)
        result = subprocess.run([shutil.which("node"), "--input-type=module", "-"], input=stub + projection,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {
            "rows": [{"id": CHILD, "status": "completed"}, {"id": TURN, "status": "completed"}],
            "calls": [[CHILD], [TURN]],
        })

    @unittest.skipUnless(shutil.which("node"), "Node.js required to execute the provider JavaScript")
    def test_empty_related_status_projection_makes_no_provider_calls(self):
        projection = related_run_status_projection_source("ECHO-2806", PARENT)
        stub = ("const calls = [];\n"
                "const call = async name => { calls.push(name); throw new Error('unexpected provider call'); };\n"
                "const tools = {mcp__codex_app__list_threads: () => call('list_threads'),\n"
                "  mcp__codex_app__read_thread: () => call('read_thread'),\n"
                "  mcp__codex_app__wait_threads: () => call('wait_threads')};\n"
                "const text = value => process.stdout.write(JSON.stringify({rows: JSON.parse(value), calls}));\n")
        result = subprocess.run([shutil.which("node"), "--input-type=module", "-"], input=stub + projection,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"rows": [], "calls": []})

    @unittest.skipUnless(shutil.which("node"), "Node.js required to execute the provider JavaScript")
    def test_related_status_projection_requires_terminal_latest_turn_for_idle(self):
        projection = related_run_status_projection_source("ECHO-2806", PARENT, (CHILD,))
        for latest, expected in (("completed", "completed"), ("failed", "failed"),
                                 ("inProgress", "unavailable"), (None, "unavailable")):
            with self.subTest(latest=latest):
                read = {"wake": None, "polls": [{"thread": {
                    "id": CHILD, "status": {"type": "idle", "activeFlags": []}},
                    "latestTurn": None if latest is None else {"status": latest}}]}
                stub = ("const tools = {mcp__codex_app__wait_threads: async args => {\n"
                        "if (args.targets[0].threadId !== " + json.dumps(CHILD) + ") throw new Error('unexpected id');\n"
                        "return {content: [{text: " + json.dumps(json.dumps(read)) + "}]};\n"
                        "}};\n"
                        "const text = value => process.stdout.write(value);\n")
                result = subprocess.run([shutil.which("node"), "--input-type=module", "-"], input=stub + projection,
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout), [{"id": CHILD, "status": expected}])

    @unittest.skipUnless(shutil.which("node"), "Node.js required to execute the provider JavaScript")
    def test_related_status_projection_fails_closed_for_missing_or_unavailable_ids(self):
        projection = related_run_status_projection_source("ECHO-2806", PARENT, (CHILD,))
        stub = ("const tools = {mcp__codex_app__wait_threads: async () => ({content: [{text: " +
                json.dumps(json.dumps({"polls": [], "errors": [{"threadId": CHILD}]})) + "}]})};\n"
                "const text = value => process.stdout.write(value);\n")
        result = subprocess.run([shutil.which("node"), "--input-type=module", "-"], input=stub + projection,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [{"id": CHILD, "status": "unavailable"}])

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
        self.assertIn("parent_tool_arguments_unavailable", self.audit()["errors"])

        self.rows.extend([
            {"type": "response_item", "payload": {
                "type": "custom_tool_call", "name": "exec", "call_id": "status-call-2", "input": projection}},
            {"type": "response_item", "payload": {
                "type": "custom_tool_call_output", "call_id": "status-call-2",
                "output": [{"type": "text", "text": "[]"}]}}])
        result = self.audit(artifact_root=artifact_root)
        self.assertIn("parent_related_run_status_probe_invalid", result["errors"])
        self.assertEqual(result["verified_related_run_status_probes"], 1)

        self.rows = self.rows[:2] + [{"type": "response_item", "payload": {
            "type": "custom_tool_call", "name": "exec",
            "call_id": "bad-status-call",
            "input": projection.replace("text(JSON.stringify(relatedRows));",
                                         "text(response.content[0].text);")}}]
        result = self.audit(artifact_root=artifact_root)
        self.assertIn("parent_tool_arguments_unavailable", result["errors"])

        self.rows = self.rows[:2] + [status_call, status_output,
            self.call("mcp__codex_app__read_thread", threadId=CHILD)]
        result = self.audit(artifact_root=artifact_root)
        self.assertIn("parent_unassigned_thread_read:" + CHILD, result["errors"])

    def test_active_reentry_projection_uses_saved_related_thread_ids(self):
        artifact_root = self.root / ".thoughts" / "ECHO-2806"
        artifact_root.mkdir(parents=True)
        run_id = "ECHO-2806-active"
        (artifact_root / "role_bindings.json").write_text(json.dumps({
            "run_id": run_id,
            "parent_context": {"parent_thread_id": PARENT, "related_run_thread_ids": [CHILD]},
        }))
        (artifact_root / "finalization_packet.json").write_text(json.dumps({
            "identity": {"Run ID": run_id, "State": "in_progress"},
        }))

        self.assertEqual(prior_run_status_thread_ids(artifact_root, PARENT), (CHILD,))
        projection = related_run_status_projection_source("ECHO-2806", PARENT, (CHILD,))
        self.rows.extend([
            {"type": "response_item", "payload": {"type": "custom_tool_call", "name": "exec",
             "call_id": "status-call", "input": projection}},
            {"type": "response_item", "payload": {"type": "custom_tool_call_output", "call_id": "status-call",
             "output": [{"type": "text", "text": json.dumps([{"id": CHILD, "status": "completed"}])}]}},
        ])
        result = self.audit(artifact_root=artifact_root)
        self.assertEqual(result["status"], "passed", result)
        self.assertEqual(result["related_run_status_rows"], [{"id": CHILD, "status": "completed"}])

    def test_continuation_projection_can_target_only_provider_verified_current_workers(self):
        artifact_root = self.root / ".thoughts" / "ECHO-2806"
        call = {"type": "response_item", "payload": {"type": "custom_tool_call", "name": "exec",
                "call_id": "status", "input": related_run_status_projection_source("ECHO-2806", PARENT, (CHILD,))}}
        output = {"type": "response_item", "payload": {"type": "custom_tool_call_output", "call_id": "status",
                  "output": [{"type": "text", "text": json.dumps([{"id": CHILD, "status": "completed"}])}]}}
        call["timestamp"] = "2026-10-01T00:00:02Z"
        self.rows.extend([call, output])
        runtime = {"run_started_at": "2026-10-01T00:00:00Z"}
        native = {"thread_mappings": {"/root/worker": CHILD}, "events": [
            {"Provider handle": "/root/worker", "Thread ID": CHILD, "Last dispatch at": "2026-10-01T00:00:00Z"}]}
        with patch("scripts.provider_runtime.read_runtime_events", return_value=native):
            result = self.audit(artifact_root=artifact_root, related_run_thread_ids=(TURN,), runtime_evidence=runtime)
            self.assertEqual(result["status"], "passed", result)
            self.assertEqual(result["related_run_thread_ids"], [TURN])
            self.assertEqual(result["verified_related_run_status_probes"], 0)
            self.assertEqual(result["related_run_status_probe_attempts"], 0)
            self.assertEqual(result["related_run_status_rows"], None)
            self.assertEqual(stale_run_status_errors(result, "in_progress", require_prior_dispatch_ledger=False),
                             ["stale_run_status_probe_required"])
            call["payload"]["input"] = related_run_status_projection_source("ECHO-2806", PARENT, tuple(sorted((CHILD, TURN))))
            output["payload"]["output"] = [{"type": "text", "text": json.dumps([
                {"id": CHILD, "status": "completed"}, {"id": TURN, "status": "completed"}])}]
            self.assertEqual(self.audit(artifact_root=artifact_root, related_run_thread_ids=(TURN,),
                                        runtime_evidence=runtime)["status"], "passed")
            call["payload"]["input"] = related_run_status_projection_source("ECHO-2806", PARENT, (CHILD, PARENT))
            self.assertIn("parent_tool_arguments_unavailable", self.audit(artifact_root=artifact_root,
                related_run_thread_ids=(TURN,), runtime_evidence=runtime)["errors"])
            call["payload"]["input"] = related_run_status_projection_source("ECHO-2806", PARENT, (CHILD,)) + '\ntext("extra");'
            self.assertIn("parent_tool_arguments_unavailable", self.audit(artifact_root=artifact_root,
                related_run_thread_ids=(TURN,), runtime_evidence=runtime)["errors"])

    def test_current_worker_projection_does_not_repeat_prior_run_probe(self):
        artifact_root = self.root / ".thoughts" / "ECHO-2806"
        prior_worker = "00000000-0000-0000-0000-000000000004"
        prior_call = {"type": "response_item", "timestamp": "2026-10-01T00:00:02Z", "payload": {
            "type": "custom_tool_call", "name": "exec", "call_id": "prior-status",
            "input": related_run_status_projection_source("ECHO-2806", PARENT, (prior_worker,))}}
        prior_output = {"type": "response_item", "timestamp": "2026-10-01T00:00:03Z", "payload": {
            "type": "custom_tool_call_output", "call_id": "prior-status",
            "output": [{"type": "text", "text": json.dumps([{"id": prior_worker, "status": "completed"}])}]}}
        current_call = {"type": "response_item", "timestamp": "2026-10-01T00:00:04Z", "payload": {
            "type": "custom_tool_call", "name": "exec", "call_id": "current-status",
            "input": related_run_status_projection_source("ECHO-2806", PARENT, (CHILD,))}}
        current_output = {"type": "response_item", "timestamp": "2026-10-01T00:00:05Z", "payload": {
            "type": "custom_tool_call_output", "call_id": "current-status",
            "output": [{"type": "text", "text": json.dumps([{"id": CHILD, "status": "completed"}])}]}}
        self.rows.extend([prior_call, prior_output, current_call, current_output])
        runtime = {"run_started_at": "2026-10-01T00:00:00Z"}
        native = {"thread_mappings": {"/root/worker": CHILD}, "events": [
            {"Provider handle": "/root/worker", "Thread ID": CHILD, "Last dispatch at": "2026-10-01T00:00:00Z"}]}
        with patch("scripts.provider_runtime.read_runtime_events", return_value=native):
            result = self.audit(artifact_root=artifact_root, related_run_thread_ids=(prior_worker,),
                                runtime_evidence=runtime)
            self.assertEqual(result["status"], "passed", result)
            self.assertEqual(result["related_run_status_probe_attempts"], 1)
            self.assertEqual(result["verified_related_run_status_probes"], 1)
            self.assertEqual(result["related_run_status_rows"], [{"id": prior_worker, "status": "completed"}])
            current_call["payload"]["input"] = related_run_status_projection_source(
                "ECHO-2806", PARENT, tuple(sorted((prior_worker, CHILD))))
            self.assertIn("parent_related_run_status_probe_invalid",
                          self.audit(artifact_root=artifact_root, related_run_thread_ids=(prior_worker,),
                                     runtime_evidence=runtime)["errors"])

    def test_later_worker_dispatch_does_not_invalidate_earlier_status_projection(self):
        root = self.root / ".thoughts" / "ECHO-2806"
        future = "00000000-0000-0000-0000-000000000004"
        projection = related_run_status_projection_source("ECHO-2806", PARENT, (CHILD,))
        call = {"type": "response_item", "timestamp": "2026-10-01T00:00:02Z", "payload": {
            "type": "custom_tool_call", "name": "exec", "call_id": "status", "input": projection}}
        output = {"type": "response_item", "payload": {"type": "custom_tool_call_output", "call_id": "status",
            "output": [{"type": "text", "text": json.dumps([{"id": CHILD, "status": "completed"}])}]}}
        self.rows.extend([call, output])
        native = {"thread_mappings": {"/root/implement": CHILD, "/root/review": future}, "events": [
            {"Provider handle": "/root/implement", "Thread ID": CHILD, "Last dispatch at": "2026-10-01T00:00:00Z"},
            {"Provider handle": "/root/review", "Thread ID": future, "Last dispatch at": "2026-10-01T00:00:03Z"}]}
        runtime = {"run_started_at": "2026-10-01T00:00:00Z"}
        with patch("scripts.provider_runtime.read_runtime_events", return_value=native):
            result = self.audit(artifact_root=root, related_run_thread_ids=(TURN,), runtime_evidence=runtime)
            self.assertEqual(result["status"], "passed", result)
            call["payload"]["input"] = related_run_status_projection_source("ECHO-2806", PARENT, (CHILD, future))
            output["payload"]["output"] = [{"type": "text", "text": json.dumps([
                {"id": CHILD, "status": "completed"}, {"id": future, "status": "completed"}])}]
            self.assertIn("parent_tool_arguments_unavailable", self.audit(artifact_root=root,
                related_run_thread_ids=(TURN,), runtime_evidence=runtime)["errors"])
            call["timestamp"] = "2026-10-01T00:00:04Z"
            self.assertEqual(self.audit(artifact_root=root, related_run_thread_ids=(TURN,),
                runtime_evidence=runtime)["status"], "passed")

    def test_parent_allows_only_current_run_worker_trace_session(self):
        artifact_root = self.root / ".thoughts" / "ITEM-1"
        artifact_root.mkdir(parents=True)
        sessions = self.root / ".codex" / "sessions" / "2026" / "10" / "01"
        sessions.mkdir(parents=True)
        self.source = sessions / f"rollout-parent-{PARENT}.jsonl"
        worker_session = sessions / f"rollout-worker-{CHILD}.jsonl"
        worker_session.write_text(json.dumps({"type": "session_meta", "payload": {"id": CHILD}}) + "\n")
        runtime = {"run_started_at": "2026-10-01T00:00:00Z",
                   "collector": str(Path(__file__).resolve().parents[1] / "scripts" / "worker_runtime_evidence.py"),
                   "ledger": str(artifact_root / "runtime_dispatches.json")}
        script = Path(runtime["collector"])
        native = {"thread_mappings": {"/root/worker": CHILD}, "events": [
            {"Provider handle": "/root/worker", "Thread ID": CHILD,
             "Last dispatch at": runtime["run_started_at"]}]}

        def base_command():
            return ["python3", str(script), "--provider-session", str(self.source),
                "--parent-thread-id", PARENT, "--started-at", runtime["run_started_at"],
                "--ledger", runtime["ledger"]]

        def command(session):
            return shlex.join(base_command() + ["--worker-session", str(session), "--agent",
                "current_state_investigator", "--trace", str(artifact_root / "trace.json")])

        self.rows.append(self.call("exec_command", cmd=command(worker_session), workdir=str(self.root)))
        with patch("scripts.provider_runtime.read_runtime_events", return_value=native):
            result = self.audit(artifact_root=artifact_root, related_run_thread_ids=(), runtime_evidence=runtime)
            self.assertEqual(result["status"], "passed", result)

            prior_thread = "00000000-0000-0000-0000-000000000004"
            prior_session = sessions / f"rollout-prior-{prior_thread}.jsonl"
            prior_session.write_text(json.dumps({"type": "session_meta", "payload": {"id": prior_thread}}) + "\n")
            self.rows[-1] = self.call("exec_command", cmd=command(prior_session), workdir=str(self.root))
            self.assertIn("forbidden_context_reference:session_log",
                          self.audit(artifact_root=artifact_root, related_run_thread_ids=(),
                                     runtime_evidence=runtime)["errors"])
            thread_command = shlex.join(base_command() + ["--worker-thread-id", CHILD, "--agent",
                "current_state_investigator", "--trace", str(artifact_root / "trace.json")])
            self.rows[-1] = self.call("exec_command", cmd=thread_command, workdir=str(self.root))
            self.assertEqual(self.audit(artifact_root=artifact_root, related_run_thread_ids=(),
                                        runtime_evidence=runtime)["status"], "passed")
            invalid_thread_command = shlex.join(base_command() + ["--worker-thread-id", prior_thread, "--agent",
                "current_state_investigator", "--trace", str(artifact_root / "trace.json")])
            self.rows[-1] = self.call("exec_command", cmd=invalid_thread_command, workdir=str(self.root))
            self.assertIn("forbidden_context_reference:session_log",
                          self.audit(artifact_root=artifact_root, related_run_thread_ids=(),
                                     runtime_evidence=runtime)["errors"])
            mistyped = base_command()
            mistyped[mistyped.index("--parent-thread-id") + 1] = prior_thread
            self.rows[-1] = self.call("exec_command", cmd=shlex.join(mistyped), workdir=str(self.root))
            self.assertEqual(self.audit(artifact_root=artifact_root, related_run_thread_ids=(),
                                        runtime_evidence=runtime)["status"], "passed")
            grouped = shlex.join(base_command()) + "\npython3 " + shlex.quote(str(script)) + " --help"
            for separator in (" && ", "; ", " | "):
                checksum = shlex.join(["shasum", "-a", "256", str(artifact_root / "worker_activation_packets.json")])
                self.rows[-1] = self.call("exec_command", cmd=shlex.join(base_command()) + separator + checksum)
                self.assertEqual(self.audit(artifact_root=artifact_root, related_run_thread_ids=(),
                                            runtime_evidence=runtime)["status"], "passed")
                for session in (self.source, prior_session):
                    self.rows[-1] = self.call("exec_command", cmd=shlex.join(base_command()) + separator
                                             + shlex.join(["cat", str(session)]))
                    self.assertIn("forbidden_context_reference:session_log",
                                  self.audit(artifact_root=artifact_root, related_run_thread_ids=(),
                                             runtime_evidence=runtime)["errors"])
            self.rows[-1] = self.call("exec_command", cmd=grouped, workdir=str(self.root))
            self.assertEqual(self.audit(artifact_root=artifact_root, related_run_thread_ids=(),
                                        runtime_evidence=runtime)["status"], "passed")
            self.rows[-1] = self.call("exec_command", cmd=grouped + "\ncat " + str(prior_session),
                                      workdir=str(self.root))
            self.assertIn("forbidden_context_reference:session_log",
                          self.audit(artifact_root=artifact_root, related_run_thread_ids=(),
                                     runtime_evidence=runtime)["errors"])
            finalizer = script.with_name("finalize_work_record.py")
            failure = shlex.join(["python3", str(finalizer), "--workflow-failure",
                "parent_context_nonconformant:forbidden_context_reference:session_log",
                "--packet", str(artifact_root / "finalization_packet.json"),
                "--provider-session", str(self.source), "--parent-thread-id", PARENT])
            self.rows[-1] = self.call("exec_command", cmd=failure, workdir=str(self.root))
            self.assertEqual(self.audit(artifact_root=artifact_root, related_run_thread_ids=(),
                                        runtime_evidence=runtime)["status"], "passed")
            self.rows[-1] = self.call("exec_command", cmd=failure.replace(str(self.source), str(prior_session)),
                                      workdir=str(self.root))
            self.assertIn("forbidden_context_reference:session_log",
                          self.audit(artifact_root=artifact_root, related_run_thread_ids=(),
                                     runtime_evidence=runtime)["errors"])
            self.rows[-1] = self.call("exec_command", cmd="echo prepare\n" + command(worker_session),
                                      workdir=str(self.root))
            self.assertEqual(self.audit(artifact_root=artifact_root, related_run_thread_ids=(),
                                        runtime_evidence=runtime)["status"], "passed")
            self.rows[-1] = self.call("exec_command", cmd="echo prepare\n" + command(worker_session)
                                      + "\ncat " + str(prior_session), workdir=str(self.root))
            self.assertIn("forbidden_context_reference:session_log",
                          self.audit(artifact_root=artifact_root, related_run_thread_ids=(),
                                     runtime_evidence=runtime)["errors"])
            old_collector = self.root / "old-package" / "scripts" / "worker_runtime_evidence.py"
            old_command = shlex.join(base_command()).replace(str(script), str(old_collector))
            self.rows[-1] = self.call("exec_command", cmd=old_command, workdir=str(self.root))
            self.assertIn("forbidden_context_reference:session_log",
                          self.audit(artifact_root=artifact_root, related_run_thread_ids=(),
                                     runtime_evidence=runtime)["errors"])
            self.assertEqual(self.audit(artifact_root=artifact_root, related_run_thread_ids=(),
                runtime_evidence=runtime, audit_previous_collector=old_collector)["status"], "passed")
            (artifact_root / "finalization_packet.json").write_text(json.dumps({"recovery": {
                "Prior run ID": "ITEM-1-20260930T230000000000Z"}}))
            prior_command = base_command()
            prior_command[prior_command.index("--started-at") + 1] = "2026-09-30T23:00:00Z"
            self.rows[-1] = self.call("exec_command", cmd=shlex.join(prior_command), workdir=str(self.root))
            self.assertEqual(self.audit(artifact_root=artifact_root, related_run_thread_ids=(),
                                        runtime_evidence=runtime)["status"], "passed")
            prior_command[prior_command.index("--started-at") + 1] = "2026-09-29T23:00:00Z"
            self.rows[-1] = self.call("exec_command", cmd=shlex.join(prior_command), workdir=str(self.root))
            self.assertIn("forbidden_context_reference:session_log",
                          self.audit(artifact_root=artifact_root, related_run_thread_ids=(),
                                     runtime_evidence=runtime)["errors"])

            closure_command = shlex.join(base_command() + ["--closure", str(artifact_root / "runtime_closure.json")])
            self.rows[-1] = self.call("exec_command", cmd=closure_command, workdir=str(self.root))
            self.assertEqual(self.audit(artifact_root=artifact_root, related_run_thread_ids=(),
                                        runtime_evidence=runtime)["status"], "passed")
            self.rows[-1] = self.call("exec_command", cmd=shlex.join(base_command()), workdir=str(self.root))
            self.assertEqual(self.audit(artifact_root=artifact_root, related_run_thread_ids=(),
                                        runtime_evidence=runtime)["status"], "passed")
            self.rows[-1] = self.call("exec_command", cmd=closure_command + "; cat " + str(prior_session),
                                      workdir=str(self.root))
            self.assertIn("forbidden_context_reference:session_log",
                          self.audit(artifact_root=artifact_root, related_run_thread_ids=(),
                                     runtime_evidence=runtime)["errors"])
            appended = command(worker_session) + "; cat " + str(prior_session)
            self.rows[-1] = self.call("exec_command", cmd=appended, workdir=str(self.root))
            self.assertIn("forbidden_context_reference:session_log",
                          self.audit(artifact_root=artifact_root, related_run_thread_ids=(),
                                     runtime_evidence=runtime)["errors"])

    def test_recovery_audit_allows_only_prior_run_workers_from_the_bound_recovery(self):
        artifact_root = self.root / ".thoughts" / "ITEM-1"
        artifact_root.mkdir(parents=True)
        sessions = self.root / ".codex" / "sessions" / "2026" / "10" / "01"
        sessions.mkdir(parents=True)
        self.source = sessions / f"rollout-parent-{PARENT}.jsonl"
        prior_worker = "00000000-0000-0000-0000-000000000004"
        unrelated_worker = "00000000-0000-0000-0000-000000000005"
        prior_started_at = "2026-09-30T23:00:00Z"
        (artifact_root / "finalization_packet.json").write_text(json.dumps({"recovery": {
            "Prior run ID": "ITEM-1-20260930T230000000000Z"}}))
        runtime = {"run_started_at": "2026-10-01T00:00:00Z",
                   "collector": str(Path(__file__).resolve().parents[1] / "scripts" / "worker_runtime_evidence.py"),
                   "ledger": str(artifact_root / "runtime_dispatches.json")}
        command = shlex.join(["python3", runtime["collector"], "--provider-session", str(self.source),
            "--parent-thread-id", PARENT, "--started-at", prior_started_at, "--ledger", runtime["ledger"],
            "--worker-thread-id", prior_worker, "--agent", "current_state_investigator",
            "--trace", str(artifact_root / "prior.trace.json")])
        self.rows.append(self.call("exec_command", cmd=command, workdir=str(self.root)))
        with patch("scripts.provider_runtime.read_runtime_events", return_value={"events": [], "thread_mappings": {}}):
            result = self.audit(artifact_root=artifact_root, related_run_thread_ids=(prior_worker,),
                                runtime_evidence=runtime)
            self.assertEqual(result["status"], "passed", result)
            self.rows[-1] = self.call("exec_command", cmd=command.replace(prior_worker, unrelated_worker),
                                      workdir=str(self.root))
            self.assertIn("forbidden_context_reference:session_log",
                          self.audit(artifact_root=artifact_root, related_run_thread_ids=(prior_worker,),
                                     runtime_evidence=runtime)["errors"])
            self.rows[-1] = self.call("exec_command", cmd=command.replace(
                prior_started_at, runtime["run_started_at"]), workdir=str(self.root))
            self.assertIn("forbidden_context_reference:session_log",
                          self.audit(artifact_root=artifact_root, related_run_thread_ids=(prior_worker,),
                                     runtime_evidence=runtime)["errors"])

    def test_planning_recovery_wrapper_uses_automatic_native_binding(self):
        skill = (Path(__file__).resolve().parents[1] / "skills/run/SKILL.md").read_text()
        self.assertIn("Normal preflight and preparation commands omit `--provider-session`", skill)
        self.assertIn("do not embed\n   a session-log path in that wrapper", skill)
        script = Path(__file__).resolve().parents[1] / "scripts/prepare_run.py"
        command = ("python3 - <<'PY'\nimport json, subprocess\n"
                   "manifest = {'inputs': []}\n"
                   f"args = ['python3', {str(script)!r}, '--continuation', '--planning-recovery', "
                   "'--approval-reference', 'current user message', '--input-json', json.dumps(manifest)]\n"
                   "subprocess.run(args, check=True)\nPY\n")
        self.rows.append(self.call("exec_command", cmd=command))
        self.assertEqual(self.audit(related_run_thread_ids=())["status"], "passed")
        self.rows[-1] = self.call("exec_command", cmd=command + "cat /tmp/.codex/sessions/other.jsonl")
        self.assertIn("forbidden_context_reference:session_log", self.audit(related_run_thread_ids=())["errors"])

    def test_planning_recovery_command_references_only_current_session(self):
        self.source = self.root / ".codex" / "sessions" / "parent.jsonl"
        self.source.parent.mkdir(parents=True)
        script = Path(__file__).resolve().parents[1] / "scripts/prepare_run.py"
        command = shlex.join(["python3", str(script), "--continuation", "--planning-recovery",
            "--approval-reference", "user authorized recovery", "--execution-repository", str(self.root),
            "--work-item", "ECHO-2806", "--playbook", "techops_issue_remediation",
            "--provider-session", str(self.source)])
        self.rows.append(self.call("exec_command", cmd=command))
        self.assertEqual(self.audit(related_run_thread_ids=())["status"], "passed")
        continuation = shlex.join(["python3", str(script), "--continuation",
            "--execution-repository", str(self.root), "--work-item", "ECHO-2806",
            "--playbook", "techops_issue_remediation", "--provider-session", str(self.source),
            "--input-manifest", str(self.root / "input.json")])
        self.rows[-1] = self.call("exec_command", cmd="echo prepare\n" + continuation)
        self.assertEqual(self.audit(related_run_thread_ids=())["status"], "passed")
        self.rows[-1] = self.call("exec_command", cmd=continuation + "\ncat /tmp/.codex/sessions/other.jsonl")
        self.assertIn("forbidden_context_reference:session_log",
                      self.audit(related_run_thread_ids=())["errors"])
        reordered = shlex.join(["python3", str(script), "--execution-repository", str(self.root),
            "--work-item", "ECHO-2806", "--playbook", "playbooks/techops_issue_remediation.md",
            "--continuation", "--provider-session", str(self.source)])
        self.rows[-1] = self.call("exec_command", cmd=reordered)
        self.assertEqual(self.audit(related_run_thread_ids=())["status"], "passed")
        incomplete = shlex.join(["python3", str(script), "--continuation", "--provider-session", str(self.source)])
        self.rows[-1] = self.call("exec_command", cmd=incomplete)
        self.assertEqual(self.audit(related_run_thread_ids=())["status"], "passed")
        pinned_scripts = self.root / "pinned" / "scripts"
        pinned_command = command.replace(str(script), str(pinned_scripts / "prepare_run.py"))
        self.rows[-1] = self.call("exec_command", cmd=pinned_command)
        self.assertIn("forbidden_context_reference:session_log", self.audit(related_run_thread_ids=())["errors"])
        self.assertEqual(self.audit(related_run_thread_ids=(), audit_script_dir=pinned_scripts)["status"], "passed")
        family = self.root / ".codex/plugins/cache/market/plugin"
        older = family / "0.5.33+codex.123" / "scripts"
        newer = family / "0.5.33+codex.456" / "scripts"
        refreshed_command = command.replace(str(script), str(newer / "prepare_run.py"))
        self.rows[-1] = self.call("exec_command", cmd=refreshed_command)
        self.assertEqual(self.audit(related_run_thread_ids=(), audit_script_dir=older)["status"], "passed")
        bad_command = refreshed_command.replace("0.5.33+codex.456", "untrusted")
        self.rows[-1] = self.call("exec_command", cmd=bad_command)
        self.assertIn("forbidden_context_reference:session_log",
                      self.audit(related_run_thread_ids=(), audit_script_dir=older)["errors"])
        self.rows[-1] = self.call("exec_command", cmd=command + "; cat /tmp/.codex/sessions/other.jsonl")
        self.assertIn("forbidden_context_reference:session_log",
                      self.audit(related_run_thread_ids=())["errors"])

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
                   "--work-item", "ECHO-2806", "--provider-session", str(self.source),
                   "--authorize-prior-parent-thread", TURN]
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
        audit = self.audit(artifact_root=artifact_root, related_run_thread_ids=tuple(output["prior_thread_ids"]))
        self.assertEqual(audit["status"], "passed", audit["errors"])
        self.assertEqual(stale_run_status_errors(audit, "active"), [])

        ledger = artifact_root / "runtime_dispatches.json"
        ledger.write_text('{"thread_mappings": {"/root/prior-worker": "invalid"}, "events": []}')
        rejected = subprocess.run(command, capture_output=True, text=True, timeout=30)
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("stale_run_thread_identity_invalid", json.loads(rejected.stdout)["reason"])
        self.assertEqual(ledger.read_text(), '{"thread_mappings": {"/root/prior-worker": "invalid"}, "events": []}')

    def test_fresh_status_projection_blocks_unapproved_prior_parent(self):
        artifact_root = self.root / ".thoughts" / "ECHO-2806"
        artifact_root.mkdir(parents=True)
        (artifact_root / "role_bindings.json").write_text(json.dumps({
            "parent_context": {"parent_thread_id": TURN}}))
        (artifact_root / "runtime_dispatches.json").write_text(json.dumps({
            "thread_mappings": {}, "events": [], "failed_dispatches": [],
            "timing": {"open_worker_intervals": 0}}))
        self.audit()
        script = Path(__file__).resolve().parents[1] / "scripts/prepare_run.py"
        result = subprocess.run(["python3", str(script), "--status-projection", "--execution-repository",
                                 str(self.root), "--work-item", "ECHO-2806", "--provider-session", str(self.source)],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["reason"], "prior_run_status_requires_user_authorization")

    def test_unapproved_parent_blocks_before_reading_prior_run_receipts(self):
        artifact_root = self.root / ".thoughts" / "ECHO-2806"
        artifact_root.mkdir(parents=True)
        (artifact_root / "role_bindings.json").write_text(json.dumps({
            "parent_context": {"parent_thread_id": TURN}}))
        (artifact_root / "runtime_dispatches.json").write_text(json.dumps({
            "parent_thread_id": TURN, "thread_mappings": {"/root/prior-worker": CHILD}}))
        with patch("scripts.provider_runtime.prior_run_status_thread_ids",
                   side_effect=AssertionError("prior session details were read")) as prior_details:
            with self.assertRaisesRegex(ValueError, "prior_run_status_requires_user_authorization"):
                scoped_prior_run_status_thread_ids(artifact_root, PARENT)
        prior_details.assert_not_called()

    def test_prior_worker_status_requires_authorizing_its_parent_thread(self):
        artifact_root = self.root / ".thoughts" / "ECHO-2806"
        artifact_root.mkdir(parents=True)
        (artifact_root / "role_bindings.json").write_text(json.dumps({
            "parent_context": {"parent_thread_id": TURN}}))
        (artifact_root / "runtime_dispatches.json").write_text(json.dumps({
            "thread_mappings": {"/root/prior-worker": CHILD}, "events": [], "failed_dispatches": []}))
        self.audit()
        script = Path(__file__).resolve().parents[1] / "scripts/prepare_run.py"
        base = ["python3", str(script), "--status-projection", "--execution-repository", str(self.root),
                "--work-item", "ECHO-2806", "--provider-session", str(self.source)]
        blocked = subprocess.run(base, capture_output=True, text=True, timeout=30)
        self.assertEqual(blocked.returncode, 2)
        self.assertEqual(json.loads(blocked.stdout)["reason"], "prior_run_status_requires_user_authorization")
        authorized = subprocess.run(base + ["--authorize-prior-parent-thread", TURN],
                                    capture_output=True, text=True, timeout=30)
        self.assertEqual(authorized.returncode, 0, authorized.stdout + authorized.stderr)
        output = json.loads(authorized.stdout)
        self.assertEqual(output["prior_thread_ids"], sorted([TURN, CHILD]))
        self.assertIn("mcp__codex_app__wait_threads", output["projection"])
        self.assertNotIn("mcp__codex_app__read_thread", output["projection"])

    def test_terminal_local_closure_does_not_authorize_a_prior_parent(self):
        artifact_root = self.root / ".thoughts" / "ECHO-2806"
        artifact_root.mkdir(parents=True)
        (artifact_root / "role_bindings.json").write_text(json.dumps({
            "parent_context": {"parent_thread_id": TURN}}))
        (artifact_root / "runtime_dispatches.json").write_text(json.dumps({
            "thread_mappings": {"/root/worker": CHILD},
            "events": [{"Thread ID": CHILD}], "failed_dispatches": []}))
        (artifact_root / "runtime_closure.json").write_text(json.dumps({
            "runtime_closure": [{"Runtime status": "Terminal", "Remaining active handles": "0"}],
            "terminal_observations": [{"Thread ID": CHILD, "Provider status": "completed"}]}))
        self.audit()
        script = Path(__file__).resolve().parents[1] / "scripts/prepare_run.py"
        result = subprocess.run(["python3", str(script), "--status-projection", "--execution-repository",
                                 str(self.root), "--work-item", "ECHO-2806", "--provider-session", str(self.source)],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["reason"], "prior_run_status_requires_user_authorization")

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

    def test_failed_same_run_status_projection_retains_bound_prior_workers(self):
        from scripts.prepare_run import status_projection
        root = self.root / ".thoughts" / "ECHO-2806"
        root.mkdir(parents=True)
        self.audit()
        bindings = {"run_id": "run-1", "parent_context": {
            "parent_thread_id": PARENT, "related_run_thread_ids": [CHILD]}}
        packet = {"identity": {"Run ID": "run-1", "State": "in_progress"}}
        (root / "role_bindings.json").write_text(json.dumps(bindings))
        (root / "finalization_packet.json").write_text(json.dumps(packet))
        (root / "runtime_dispatches.json").write_text(json.dumps({
            "thread_mappings": {}, "events": [], "failed_dispatches": []}))
        (root / "finalization_failure.json").write_text(json.dumps({"status": "failed"}))
        before = {path.name: path.read_bytes() for path in root.iterdir()}
        with patch("scripts.provider_runtime.current_parent_session", return_value=self.source):
            output = status_projection(self.root, "ECHO-2806", self.source)
        self.assertEqual(output["prior_thread_ids"], [CHILD])
        self.assertEqual(output["projection"], related_run_status_projection_source("ECHO-2806", PARENT, (CHILD,)))
        self.assertEqual(before, {path.name: path.read_bytes() for path in root.iterdir()})
        self.rows.extend([
            {"type": "response_item", "payload": {"type": "custom_tool_call", "name": "exec",
                "call_id": "status", "input": output["projection"]}},
            {"type": "response_item", "payload": {"type": "custom_tool_call_output", "call_id": "status",
                "output": [{"type": "text", "text": json.dumps([{"id": CHILD, "status": "completed"}])}]}}])
        audit = self.audit(artifact_root=root, related_run_thread_ids=(CHILD,))
        self.assertEqual(audit["status"], "passed", audit)
        for identity in ({"Run ID": "different", "State": "in_progress"},
                         {"Run ID": "run-1", "State": "completed"}):
            (root / "finalization_packet.json").write_text(json.dumps({"identity": identity}))
            with patch("scripts.provider_runtime.current_parent_session", return_value=self.source):
                self.assertEqual(status_projection(self.root, "ECHO-2806", self.source)["prior_thread_ids"], [])

    def test_related_status_probe_requires_correlated_minimal_output(self):
        artifact_root = self.root / ".thoughts" / "ECHO-2806"
        artifact_root.mkdir(parents=True)
        (artifact_root / "role_bindings.json").write_text(json.dumps({
            "parent_context": {"parent_thread_id": PARENT}}))
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

        mismatched = {"type": "response_item", "payload": {
            **output["payload"], "output": [{"type": "text", "text": json.dumps([
                {"id": TURN, "status": "completed"}])}]}}
        self.rows = self.rows[:2] + [call, mismatched]
        self.assertIn("parent_related_run_status_output_invalid", self.audit(artifact_root=artifact_root)["errors"])

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
        not_found = {**context, "related_run_status_rows": [{"id": CHILD, "status": "not_found"}]}
        self.assertEqual(stale_run_status_errors(not_found, "active"), [])
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

        for operation in ("send_message", "followup_task"):
            failed = {"Operation": operation, "Provider handle": "/root/worker", "Status": "failed"}
            ledger.write_text(json.dumps({"thread_mappings": {"/root/worker": CHILD}, "events": [],
                                          "failed_dispatches": [failed]}))
            self.assertEqual(prior_run_status_thread_ids(artifact_root, PARENT), (CHILD,))
            for invalid in ({**failed, "Provider handle": "/root/unknown"}, {**failed, "Status": "running"}):
                ledger.write_text(json.dumps({"thread_mappings": {"/root/worker": CHILD}, "events": [],
                                              "failed_dispatches": [invalid]}))
                with self.assertRaisesRegex(ValueError, "stale_run_thread_identity_invalid"):
                    prior_run_status_thread_ids(artifact_root, PARENT)

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

    def test_blocked_closure_recovers_identities_only_from_verified_dispatch_ledger(self):
        root = self.root / ".thoughts" / "ITEM-1"
        root.mkdir(parents=True)
        session = self.root / "provider.jsonl"
        ledger = {"parent_thread_id": CHILD, "provider_session": str(session),
                  "run_started_at": "2026-10-01T00:00:00Z",
                  "events": [{"Operation": "spawn_agent", "Provider handle": "/root/worker", "Thread ID": TURN}],
                  "thread_mappings": {"/root/worker": TURN}, "failed_dispatches": []}
        bindings = {"parent_context": {"parent_thread_id": CHILD, "provider_session": str(session)},
                    "runtime_evidence": {"run_started_at": ledger["run_started_at"]}}
        closure = {"runtime_closure": [{"Runtime status": "Blocked", "Run or stage": "Current run",
                    "Receipt owner": "Coordinator", "Closure evidence or blocker":
                    "worker_runtime_release_unavailable: unavailable; dispatched handles: /root/worker"}]}
        for name, value in (("role_bindings.json", bindings), ("runtime_dispatches.json", ledger),
                            ("runtime_closure.json", closure)):
            (root / name).write_text(json.dumps(value))
        with patch("scripts.provider_runtime.read_runtime_events", return_value=ledger):
            self.assertEqual(prior_run_status_thread_ids(root, PARENT), tuple(sorted((CHILD, TURN))))
            for key, value in (("events", []), ("thread_mappings", {}), ("failed_dispatches", [{"Status": "failed"}])):
                with self.subTest(stale=key), patch("scripts.provider_runtime.read_runtime_events",
                                                   return_value={**ledger, key: value}):
                    with self.assertRaisesRegex(ValueError, "stale_run_closure_identity_invalid"):
                        prior_run_status_thread_ids(root, PARENT)
            closure["runtime_closure"][0]["Closure evidence or blocker"] = (
                "Provider closure collection failed: terminal_inventory_unverified")
            (root / "runtime_closure.json").write_text(json.dumps(closure))
            self.assertEqual(prior_run_status_thread_ids(root, PARENT), tuple(sorted((CHILD, TURN))))
            with patch("scripts.provider_runtime.read_runtime_events", return_value={**ledger, "events": []}):
                with self.assertRaisesRegex(ValueError, "stale_run_closure_identity_invalid"):
                    prior_run_status_thread_ids(root, PARENT)
            closure["runtime_closure"][0]["Closure evidence or blocker"] = (
                "worker_runtime_release_unavailable: unavailable; dispatched handles: /root/worker")
            closure["runtime_closure"][0]["Runtime status"] = "Terminal"
            (root / "runtime_closure.json").write_text(json.dumps(closure))
            with self.assertRaisesRegex(ValueError, "stale_run_closure_identity_invalid"):
                prior_run_status_thread_ids(root, PARENT)
            closure["runtime_closure"][0]["Runtime status"] = "Blocked"
            closure["runtime_closure"][0]["Closure evidence or blocker"] += "; /root/extra"
            (root / "runtime_closure.json").write_text(json.dumps(closure))
            with self.assertRaisesRegex(ValueError, "stale_run_closure_identity_invalid"):
                prior_run_status_thread_ids(root, PARENT)

            closure["runtime_closure"][0]["Closure evidence or blocker"] = (
                "worker_runtime_release_unavailable: unavailable; dispatched handles: /root/worker")
            (root / "runtime_closure.json").write_text(json.dumps(closure))
            (root / "work_record.md").write_text("| State | blocked |\n| Run ID | ITEM-1-prior |\n")
            (root / "previous-artifact.txt").write_text("preserve this")
            ids = list(prior_run_status_thread_ids(root, PARENT))
            context = {"parent_thread_id": PARENT, "verified_related_run_status_probes": 1,
                       "related_run_status_probe_attempts": 1, "related_run_thread_ids": ids,
                       "prior_run_dispatch_ledger_present": True,
                       "related_run_status_rows": [{"id": value, "status": "completed"} for value in ids]}
            for status in ("running", "unavailable"):
                context["related_run_status_rows"][0]["status"] = status
                with self.assertRaisesRegex(ValueError, "prior_run_archive_blocked"):
                    _archive_existing_run(root, True, parent_context=context)
                self.assertEqual((root / "previous-artifact.txt").read_text(), "preserve this")
            context["related_run_status_rows"][0]["status"] = "completed"
            archived = Path(_archive_existing_run(root, True, parent_context=context))
            self.assertEqual((archived / "previous-artifact.txt").read_text(), "preserve this")
            self.assertFalse((root / "previous-artifact.txt").exists())

    def test_preflight_allows_launcher_and_packaged_cli_help_only(self):
        framework = self.root / 'framework'
        scripts = framework / 'scripts'
        scripts.mkdir(parents=True)
        helper = scripts / 'prepare_run.py'
        helper.write_text('# Packaged CLI fixture\n')
        skill = framework / 'skills/run/SKILL.md'
        for command in (f'python3 {helper} --help', f'python3 {helper} -h',
                        f'cat {skill} && python3 {helper} --help'):
            with self.subTest(command=command):
                self.rows = self.rows[:2] + [self.call('exec_command', cmd=command)]
                self.assertEqual(self.audit(framework_root=framework, require_preflight_order=True)['status'], 'passed')
        for command in (f'cat {skill} && python3 {helper} --work-item ITEM-1',
                        f'python3 {self.root}/prepare_run.py --help',
                        f'python3 {helper} --help && cat /repo/source.py',
                        f'python3 {helper} --help; cat /repo/source.py'):
            with self.subTest(command=command):
                self.rows = self.rows[:2] + [self.call('exec_command', cmd=command)]
                self.assertIn('parent_framework_content_before_preflight',
                              self.audit(framework_root=framework, require_preflight_order=True)['errors'])

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

        versioned_python = f"python3.15 {framework}/scripts/run_preflight.py"
        observed_versioned = {"type": "event_msg", "payload": {"type": "item_completed", "item": {
            "type": "CommandExecution", "command": ["/bin/bash", "-lc", versioned_python],
            "status": "completed", "exit_code": 0,
            "aggregated_output": json.dumps({"status": "passed"})}}}
        self.rows = self.rows[:2] + [self.call("exec_command", cmd=versioned_python), observed_versioned,
                                     self.call("exec_command", cmd=f"sed -n '1,20p' {playbook}")]
        self.assertEqual(self.audit(framework_root=framework, require_preflight_order=True)["status"], "passed")

        self.rows = self.rows[:2] + [self.call("exec_command", cmd=preflight), observed_preflight,
                                     self.call("exec_command", cmd=f"sed -n '1,20p' {playbook}")]
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
        self.assertIn("A work-item key or link to the current task does", skill)
        self.assertIn("unless the current user explicitly identifies", skill)
        self.assertIn("Do not consult other memory files, rollout summaries", " ".join(skill.split()))
        self.assertNotIn("Follow higher-priority host memory instructions", skill)
        self.assertNotIn("host-required read-only memory check may precede it", skill)
        export_guidance = skill.split("If the latest inventory omits this worker", 1)[1].split(
            "Do not manually reconstruct a trace", 1)[0]
        self.assertIn("rerun the collector without `--observation`", export_guidance)
        self.assertIn("no separate observation file is needed", export_guidance)
        self.assertNotIn("supply `--observation`", export_guidance)
        section = skill.split("this exact projection", 1)[1]
        snippet = section.split("```javascript\n", 1)[1].split("\n   ```", 1)[0]
        prior_id = "00000000-0000-0000-0000-000000000004"
        expected = related_run_status_projection_source("ECHO-2806", PARENT, (prior_id,))
        expected = expected.replace(json.dumps(PARENT), '"PARENT-THREAD-UUID"')
        expected = expected.replace(json.dumps([prior_id]), '["PRIOR-WORKER-THREAD-UUID"]')
        self.assertIn("mcp__codex_app__wait_threads", expected)
        self.assertNotIn("mcp__codex_app__read_thread", expected)
        self.assertIn("const batches = priorIds.map(id => [id]);", expected)
        self.assertEqual(textwrap.dedent(snippet).strip(), expected)

    def test_tool_operations_parse_only_static_string_concatenation(self):
        from scripts.runtime_checks import _tool_operations

        payload = {"type": "custom_tool_call", "name": "exec", "input": (
            'const root = "/repo"; '
            "const results = await Promise.all(["
            'tools.exec_command({cmd:"cat " + root + "/one",workdir:"/repo",max_output_tokens:500}),'
            'tools.exec_command({cmd:"cat " + root + "/two",workdir:"/repo",max_output_tokens:500})]); '
            "for (const r of results) text(r.output);"
        )}
        self.assertEqual(_tool_operations(payload), [
            ("exec_command", {"cmd": "cat /repo/one", "workdir": "/repo", "max_output_tokens": 500}),
            ("exec_command", {"cmd": "cat /repo/two", "workdir": "/repo", "max_output_tokens": 500}),
        ])

        payload["input"] = payload["input"].replace('"cat " + root', '"cat " + dynamic')
        self.assertEqual(_tool_operations(payload), [])

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
        self.rows[-1]["payload"]["input"] += (
            'for (let i=0;i<results.length;i++) text(`guard_${i+1}: '
            '${results[i].status === "fulfilled" ? results[i].value.output : String(results[i].reason)}`)'
        )
        self.assertNotIn("parent_tool_arguments_unavailable", self.audit()["errors"])
        self.rows[-1]["payload"]["input"] = (
            'const rs=await Promise.allSettled([tools.exec_command({cmd:"cat /repo/one"}),'
            'tools.exec_command({cmd:"cat /repo/two"})]);'
            'for(let i=0;i<rs.length;i++)text(`--- ${i+1} ---\\n'
            '${rs[i].status==="fulfilled"?rs[i].value.output:String(rs[i].reason)}`);'
        )
        self.assertNotIn("parent_tool_arguments_unavailable", self.audit()["errors"])
        self.rows[-1]["payload"]["input"] += ' text(`${tools.exec_command({cmd:"cat /secret"})}`)'
        self.assertIn("parent_tool_arguments_unavailable", self.audit()["errors"])
        self.rows[-1]["payload"]["input"] = (
            'await tools.exec_command({cmd:`cat /repo/one\\ncat /secret`});'
        )
        self.assertIn("parent_tool_arguments_unavailable", self.audit()["errors"])

    def test_incomplete_literal_command_is_still_audited(self):
        payload = {"type": "custom_tool_call", "name": "exec",
                   "input": 'const r = await tools.exec_command({cmd:"cat /repo/file"}\n'}
        self.rows.append({"type": "response_item", "payload": payload})
        self.assertNotIn("parent_tool_arguments_unavailable", self.audit()["errors"])
        payload["input"] = payload["input"].replace('/repo/file', '.thoughts/OTHER/runs/old/secret')
        self.assertIn("forbidden_context_reference:archived_artifact", self.audit()["errors"])
        for source in ('const r = await tools.exec_command({cmd:unknown}',
                       'await tools.exec_command({cmd:"cat /secret"}); ' + payload["input"],
                       'const r = await tools.exec_command({cmd:"cat /repo/file", extra:unknown}'):
            payload["input"] = source
            self.assertIn("parent_tool_arguments_unavailable", self.audit()["errors"])

    def test_thoughts_instruction_probes_are_rejected_but_current_flow_artifacts_are_allowed(self):
        shared_instructions = self.root / ".thoughts" / "AGENTS.md"
        artifact_root = self.root / ".thoughts" / "ITEM-1"
        command = (f"for f in {shared_instructions} {artifact_root}/AGENTS.md "
                   f"{artifact_root}/assignment_issue_evidence.json; "
                   "do if test -e \"$f\"; then printf 'present %s\\n' \"$f\"; "
                   "else printf 'absent %s\\n' \"$f\"; fi; done")
        for probe in ("test -f " + str(shared_instructions), command):
            self.rows.append(self.call("exec_command", cmd=probe))
            rejected = self.audit(artifact_root=artifact_root)
            self.assertEqual(rejected["status"], "rejected")
            self.assertIn("forbidden_context_reference:archived_artifact", rejected["errors"])

        self.rows = self.rows[:2]
        self.rows.append(self.call("exec_command", cmd="test -f " + str(artifact_root / "assignment_issue_evidence.json")))
        self.assertEqual(self.audit(artifact_root=artifact_root)["status"], "passed")

        archived = self.root / ".thoughts" / "OTHER" / "runs" / "old" / "notes.md"
        self.rows[-1] = self.call("exec_command", cmd=command.replace(
            str(artifact_root / "assignment_issue_evidence.json"), str(archived)))
        self.assertIn("forbidden_context_reference:archived_artifact",
                      self.audit(artifact_root=artifact_root)["errors"])
        self.rows[-1]["payload"]["arguments"] = json.dumps({"cmd": "test -f " + str(archived)})
        self.assertIn("forbidden_context_reference:archived_artifact",
                      self.audit(artifact_root=artifact_root)["errors"])

    def test_literal_worker_status_observation_is_bounded(self):
        from scripts.provider_runtime import _literal_worker_status_observation
        source = (f'const r = await tools.mcp__codex_app__read_thread({{threadId:"{CHILD}",turnLimit:1,includeOutputs:false}});\n'
                  'const raw = r.content?.find(x=>x.type==="text")?.text || "";\n'
                  'const data = JSON.parse(raw);\nconst turn = data.turns?.[0];\n'
                  'const observed = await tools.clock__curr_time({});\ntext(JSON.stringify({\n'
                  '  thread_id:data.thread?.id,\n  thread_status:data.thread?.status?.type,\n'
                  '  latest_turn_id:turn?.id,\n  latest_turn_status:turn?.status,\n'
                  '  latest_turn_started_at:new Date(turn.startedAt*1000).toISOString(),\n'
                  '  latest_turn_completed_at:new Date(turn.completedAt*1000).toISOString(),\n'
                  '  observed_at:observed.current_time.replace(" UTC","T").replace(" ","").replace(/(\\d{2}:\\d{2}:\\d{2})T/, "$1Z")\n}));')
        self.assertEqual(_literal_worker_status_observation(source), [
            ("mcp__codex_app__read_thread", {"threadId": CHILD, "turnLimit": 1, "includeOutputs": False}),
            ("clock__curr_time", {})])
        for changed in (source + ' await tools.exec_command({cmd:"cat /secret"});',
                        source.replace('turnLimit:1', 'turnLimit:unknown'),
                        source.replace('clock__curr_time({})', 'exec_command({cmd:"secret"})')):
            self.assertIsNone(_literal_worker_status_observation(changed))

    def test_literal_command_batch_audits_each_command_and_rejects_extra_code(self):
        from scripts.provider_runtime import _literal_command_batch
        source = ('const cmds = [["first", "cat /repo/one"], ["second", "cat /repo/two"]];\n'
                  'const results = await Promise.all(cmds.map(async ([name, cmd]) => {\n'
                  '  const r = await tools.exec_command({cmd, workdir:"/repo", yield_time_ms:10000, max_output_tokens:2000});\n'
                  '  return `${name}\\n${r.output}`;\n'
                  '}));\nfor (const r of results) text(r);')
        calls = _literal_command_batch(source)
        self.assertEqual([args["cmd"] for _, args in calls], ["cat /repo/one", "cat /repo/two"])
        self.rows.append({"type": "response_item", "payload": {"type": "custom_tool_call", "name": "exec", "input": source}})
        self.assertNotIn("parent_tool_arguments_unavailable", self.audit()["errors"])
        self.rows[-1]["payload"]["input"] = source.replace("cat /repo/two", "cat .thoughts/OTHER/runs/old/secret")
        self.assertIn("forbidden_context_reference:archived_artifact", self.audit()["errors"])
        for changed in (source + ' await tools.exec_command({cmd:"cat /secret"});',
                        source.replace('return `${name}', 'await tools.exec_command({cmd:"cat /secret"}); return `${name}'),
                        source.replace('cat /repo/one', '${secret}')):
            self.assertIsNone(_literal_command_batch(changed))

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

        for predicate in ('x=>x.type==="text"', "part => part.type === 'text'"):
            with self.subTest(predicate=predicate):
                formatted = source.replace('text(JSON.stringify({handle, result: r}));',
                    f'const raw = r.content?.find({predicate})?.text || ""; '
                    'const data = JSON.parse(raw); text(JSON.stringify({handle, thread: data.thread}));')
                self.rows[-1]["payload"]["input"] = formatted
                self.assertEqual(self.audit()["status"], "passed")
                self.rows[-1]["payload"]["input"] = formatted.replace(predicate, 'x=>eval(x)')
                self.assertIn("parent_tool_arguments_unavailable", self.audit()["errors"])

        self.rows[-1]["payload"]["input"] = source.replace(child_two, TURN)
        result = self.audit()
        self.assertIn("parent_unassigned_thread_read:" + TURN, result["errors"])
        self.assertNotIn("parent_tool_arguments_unavailable", result["errors"])

        self.rows[-1]["payload"]["input"] = source + '\nawait tools.exec_command({cmd:"cat /repo/other"})'
        self.assertIn("parent_tool_arguments_unavailable", self.audit()["errors"])

    def test_prior_worker_only_allows_exact_status_only_projections(self):
        from scripts.provider_runtime import targeted_status_projection_source, targeted_wait_projection_source
        for projection in (targeted_status_projection_source, targeted_wait_projection_source):
            with self.subTest(projection=projection.__name__):
                self.rows.append({"type": "response_item", "payload": {"type": "custom_tool_call", "name": "exec",
                    "input": projection(CHILD)}})
                self.assertEqual(self.audit(related_run_thread_ids=(CHILD,))["status"], "passed")
                self.assertIn("parent_unassigned_thread_read:" + CHILD,
                              self.audit(related_run_thread_ids=())["errors"])
                self.rows[-1]["payload"]["input"] += '\ntext("extra");'
                self.assertIn("parent_unassigned_thread_read:" + CHILD,
                              self.audit(related_run_thread_ids=(CHILD,))["errors"])
                self.rows.pop()
        self.rows.append(self.call("mcp__codex_app__read_thread", threadId=CHILD, turnLimit=1, includeOutputs=False))
        self.assertIn("parent_unassigned_thread_read:" + CHILD, self.audit(related_run_thread_ids=(CHILD,))["errors"])

    def test_compact_status_projection_is_audited_as_one_assigned_read(self):
        from scripts.provider_runtime import targeted_status_projection_source
        self.rows.append({"type": "event_msg", "payload": {"item": {
            "type": "SubAgentActivity", "kind": "started", "agent_path": "/root/first",
            "agent_thread_id": CHILD}}})
        self.rows.append({"type": "response_item", "payload": {"type": "custom_tool_call", "name": "exec",
            "input": targeted_status_projection_source(CHILD)}})
        self.assertEqual(self.audit()["status"], "passed")
        self.rows[-1]["payload"]["input"] = targeted_status_projection_source(TURN)
        self.assertIn("parent_unassigned_thread_read:" + TURN, self.audit()["errors"])
        skill = (Path(__file__).resolve().parents[1] / "skills/run/SKILL.md").read_text()
        self.assertIn(targeted_status_projection_source(TURN), "\n".join(line.strip() for line in skill.splitlines()))

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
            "const command = 'cat ' + '/repo/.codex/memories/raw_memories.md'; "
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
        nested = source + ' text(`exit_code=${result.exit_code ?? "running"}${result.session_id ? ` session_id=${result.session_id}` : ""}`);'
        self.assertEqual(_tool_operations({**row, "input": nested}), _tool_operations(row))
        self.assertEqual(_tool_operations({**row, "input": nested.replace('cmd:`python3 ${base}', 'cmd:`python3 ${resolve()}')}), [])
        self.assertEqual(_tool_operations({**row, "input": nested.replace('result.session_id ? ` session_id=${result.session_id}`', 'tools.exec_command({cmd:"bad"}) ? ` session_id=${result.session_id}`')}), [])
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

    def closed_zero_dispatch_fixture(self):
        root = self.root / '.thoughts/ITEM-1'
        root.mkdir(parents=True)
        run_id = 'ITEM-1-closed'
        started = '2026-10-01T00:00:00Z'
        def write(name, value):
            (root / name).write_text(json.dumps(value))
        write('role_bindings.json', {'run_id': run_id, 'lifecycle': 'planning',
              'parent_context': {'parent_thread_id': CHILD, 'provider_session': '/never-open/old-chat.jsonl'},
              'runtime_evidence': {'run_started_at': started}})
        write('finalization_packet.json', {'work_item': {'ID': 'ITEM-1'}, 'identity': {
              'Run ID': run_id, 'Lifecycle': 'planning', 'State': 'in_progress'},
              'workers': [], 'worker_results': [], 'runtime_audits': []})
        packet = (root / 'finalization_packet.json').read_bytes()
        (root / 'snapshot.json').write_bytes(packet)
        packet_hash = hashlib.sha256(packet).hexdigest()
        write('runtime_dispatches.json', {'parent_thread_id': CHILD, 'run_started_at': started,
              'events': [], 'failed_dispatches': [], 'thread_mappings': {}, 'timing': {'open_worker_intervals': 0}})
        write('runtime_closure.json', {'runtime_closure': [{'Runtime status': 'Terminal',
              'Completed worker handles': 'None dispatched', 'Remaining active handles': '0'}],
              'terminal_observations': []})
        (root / 'work_record.md').write_text('Uninitialized record; the failure is recorded separately.\n')
        (root / 'handoff_failure.md').write_text('Closed control failure; no workers dispatched.\n')
        (root / 'handoff_response.md').write_bytes((root / 'handoff_failure.md').read_bytes())
        report_hash = hashlib.sha256((root / 'handoff_failure.md').read_bytes()).hexdigest()
        write('finalization_failure.json', {'status': 'failed', 'stage': 'workflow', 'run_id': run_id,
              'reported_by': 'Coordinator', 'runtime_closure': 'terminal',
              'packet_snapshot': str(root / 'snapshot.json'), 'snapshot_sha256': packet_hash,
              'packet_sha256': packet_hash, 'handoff_packet_sha256': packet_hash, 'handoff_sha256': report_hash})
        write('handoff_delivery.json', {'status': 'verified', 'run_id': run_id,
              'canonical_sha256': report_hash, 'proposed_sha256': report_hash,
              'record_sha256': hashlib.sha256((root / 'work_record.md').read_bytes()).hexdigest()})
        return root, run_id

    def test_fresh_run_preserves_closed_zero_dispatch_artifacts_without_reading_old_chat(self):
        root, prior_id = self.closed_zero_dispatch_fixture()
        (root / 'old_findings.md').write_text('OLD_FINDINGS_MUST_NOT_BECOME_CURRENT_EVIDENCE')
        self.assertEqual(scoped_prior_run_status_thread_ids(root, PARENT), ())
        projection = related_run_status_projection_source('ITEM-1', PARENT, ())
        self.rows.extend([
            {'type': 'response_item', 'payload': {'type': 'custom_tool_call', 'name': 'exec',
             'call_id': 'status', 'input': projection}},
            {'type': 'response_item', 'payload': {'type': 'custom_tool_call_output',
             'call_id': 'status', 'output': [{'type': 'text', 'text': '[]'}]}},
        ])
        self.assertEqual(self.audit(artifact_root=root)['status'], 'passed')
        with patch('scripts.provider_runtime.read_runtime_events', side_effect=AssertionError('No old chat reads')):
            run = prepare_run(self.root, 'ITEM-1', 'feature_delivery', None, False,
                provider_session=self.source, input_data={'inputs': [{'Input ID': 'IN-001',
                    'Input or artifact': 'Fresh request', 'Source or path': 'User',
                    'Authority': 'User', 'Status': 'Verified'}]})
        self.assertEqual(Path(run['archived_prior_run']), (root / 'runs' / prior_id).resolve())
        self.assertEqual((root / 'runs' / prior_id / 'old_findings.md').read_text(),
                         'OLD_FINDINGS_MUST_NOT_BECOME_CURRENT_EVIDENCE')
        self.assertFalse((root / 'old_findings.md').exists())
        self.assertNotEqual(run['run_id'], prior_id)
        self.assertNotIn('OLD_FINDINGS_MUST_NOT_BECOME_CURRENT_EVIDENCE', Path(run['finalization_packet']).read_text())

    def test_closed_zero_dispatch_archive_rejects_changed_or_incomplete_receipts(self):
        from scripts.provider_runtime import closed_zero_dispatch_run_id
        root, run_id = self.closed_zero_dispatch_fixture()
        original = {p.name: p.read_bytes() for p in root.iterdir()}
        self.assertEqual(closed_zero_dispatch_run_id(root), run_id)
        changes = (
            ('runtime_dispatches.json', lambda d: d.update(events=[{'Operation': 'spawn_agent'}])),
            ('runtime_dispatches.json', lambda d: d['timing'].update(open_worker_intervals=1)),
            ('runtime_dispatches.json', lambda d: d.update(parent_thread_id=TURN)),
            ('runtime_closure.json', lambda d: d['runtime_closure'][0].update({'Runtime status': 'Blocked'})),
            ('finalization_failure.json', lambda d: d.update(packet_sha256='0' * 64)),
            ('handoff_delivery.json', lambda d: d.update(status='pending')),
            ('finalization_packet.json', lambda d: d.update(workers=[{'Worker': 'unclosed'}])),
        )
        for name, change in changes:
            with self.subTest(name=name, change=change):
                data = json.loads(original[name]); change(data)
                (root / name).write_text(json.dumps(data))
                self.assertIsNone(closed_zero_dispatch_run_id(root))
                with self.assertRaises(ValueError):
                    scoped_prior_run_status_thread_ids(root, PARENT)
                (root / name).write_bytes(original[name])
        (root / 'handoff_failure.md').write_text('Changed report')
        self.assertIsNone(closed_zero_dispatch_run_id(root))
        before = (root / 'finalization_packet.json').read_bytes()
        with self.assertRaisesRegex(ValueError, 'closed_run_receipts_changed'):
            _archive_existing_run(root, False, parent_context={'closed_zero_dispatch_run_id': run_id})
        self.assertEqual((root / 'finalization_packet.json').read_bytes(), before)
        (root / 'handoff_failure.md').write_bytes(original['handoff_failure.md'])
        (root / 'runtime_closure.json').unlink()
        self.assertIsNone(closed_zero_dispatch_run_id(root))

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

    def test_stdin_manifest_preserves_json_without_shell_quoting(self):
        from scripts.runtime_checks import _tool_operations
        inputs = {"inputs": [{"Input ID": "IN-001", "Input or artifact": "User's \"quoted\" request — café",
            "Source or path": "User", "Authority": "User", "Status": "Verified"}]}
        script = Path(__file__).resolve().parents[1] / "scripts/prepare_run.py"
        command = shlex.join([sys.executable, str(script), "--execution-repository", str(self.root),
            "--work-item", "ITEM-1", "--playbook", "feature_delivery", "--input-json", "-",
            "--provider-session", str(self.source)]) + " <<'RUN_INPUT_JSON'\n" + json.dumps(inputs, ensure_ascii=False) + "\nRUN_INPUT_JSON"
        source = 'const r=await tools.exec_command({cmd:' + json.dumps(command) + '}); text(r.output);'
        calls = _tool_operations({"type": "custom_tool_call", "name": "exec", "input": source})
        self.assertEqual(calls, [("exec_command", {"cmd": command})])
        self.rows.append({"type": "response_item", "payload": {
            "type": "custom_tool_call", "name": "exec", "input": source}})
        self.assertEqual(self.audit(artifact_root=self.root / ".thoughts/ITEM-1")["status"], "passed")
        result = subprocess.run(["bash", "-c", command], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        run = json.loads(result.stdout)
        saved = json.loads(Path(run["run_input_manifest"]["path"]).read_text())
        self.assertEqual({key: saved["inputs"][0][key] for key in inputs["inputs"][0]}, inputs["inputs"][0])
        before = Path(run["finalization_packet"]).read_bytes()
        invalid = command.replace(json.dumps(inputs, ensure_ascii=False), json.dumps(inputs) + "}")
        rejected = subprocess.run(["bash", "-c", invalid], capture_output=True, text=True, timeout=30)
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("Extra data", json.loads(rejected.stdout)["reason"])
        self.assertEqual(Path(run["finalization_packet"]).read_bytes(), before)

    def test_preparation_write_denial_returns_scoped_retry_guidance(self):
        from scripts import prepare_run as preparation
        root = self.root / '.thoughts/ITEM-1'
        arguments = ['prepare_run.py', '--execution-repository', str(self.root), '--work-item', 'ITEM-1',
                     '--playbook', 'feature_delivery', '--input-json', json.dumps({'inputs': [{
                         'Input ID': 'IN-001', 'Input or artifact': 'Current issue', 'Source or path': 'User',
                         'Authority': 'User', 'Status': 'Verified'}]})]
        for denied in (root, self.root / 'private-guide.md', root / 'private-input.json'):
            output = io.StringIO()
            with patch.object(sys, 'argv', arguments), patch.object(preparation, 'prepare_run',
                    side_effect=PermissionError(1, 'Operation not permitted', str(denied))), redirect_stdout(output):
                self.assertEqual(preparation.main(), 2)
            receipt = json.loads(output.getvalue())
            if denied == root:
                self.assertEqual(receipt['reason'], 'artifact_root_permission_denied')
                self.assertEqual(receipt['artifact_root'], str(root.resolve()))
                self.assertIn('scoped', receipt['next_action'])
                self.assertIn('same preparation command', receipt['next_action'])
            else:
                self.assertNotIn('next_action', receipt)
                self.assertIn('Operation not permitted', receipt['reason'])
        self.assertFalse(root.exists())

    def test_preparation_is_transactional_and_activation_rechecks_later_reads(self):
        inputs = self.root / "inputs.json"
        inputs.write_text(json.dumps({"inputs": [{"Input ID": "IN-001", "Input or artifact": "Current issue",
            "Source or path": "User", "Authority": "User", "Status": "Verified"}]}))
        self.rows.append(self.call("exec_command", cmd="cat /repo/.codex/memories/raw_memories.md"))
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
        self.rows.append(self.call("exec_command", cmd="cat /repo/.codex/memories/raw_memories.md"))
        self.audit()
        self.assertTrue(any(error.startswith("parent_context_nonconformant") for error in check()))
        self.rows.append({"type": "turn_context", "timestamp": "2026-10-01T00:00:03Z",
                          "payload": {"turn_id": CHILD}})
        self.audit()
        self.assertTrue(any(error.startswith("parent_context_turn_mismatch:expected=" + TURN)
                            for error in check()))


if __name__ == "__main__":
    unittest.main()
