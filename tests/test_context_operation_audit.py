"""Recorded provider call shapes: historical data is not current tool activity."""

import json
import hashlib
import shlex
import subprocess
import sys
import unittest
from pathlib import Path

from scripts import validate_worker_runtime as runtime
from scripts import asset_manifest as assets
from scripts import finalize_work_record as finalizer
from scripts.merge_techops_result import merge_result
from scripts.worker_runtime_evidence import export_worker_trace, read_runtime_events
from tests import test_framework_corrections as fixtures
from tests import test_activation_delivery as activation_fixtures
from tests.worker_response_support import stage_worker_response


SOURCE = "00000000-0000-0000-0000-000000000001"


class ContextOperationAudit(unittest.TestCase):
    setUp = fixtures.FrameworkCorrections.setUp
    dispatch_trace = fixtures.FrameworkCorrections.dispatch_trace

    def test_parent_allows_explicit_continuity_reads_but_never_exempts_appended_operations(self):
        from scripts.provider_runtime import parent_context_audit
        source = self.repository / "parent.jsonl"
        approved = "/repo/.thoughts/OLD/runs/accepted/implementation_plan.md"
        header = [{"type": "session_meta", "payload": {"id": SOURCE}},
                  {"type": "turn_context", "payload": {"turn_id": "00000000-0000-0000-0000-000000000002"}}]
        for command in ("sed -n '1,30p' " + approved, "cat " + approved + "; git status --short"):
            call = {"type": "custom_tool_call", "name": "exec", "input":
                    "const result = await tools.exec_command(" + json.dumps({"cmd": command}) + "); text(result.output);"}
            source.write_text("".join(json.dumps(row) + "\n" for row in header + [{"type": "response_item", "payload": call}]))
            self.assertEqual(parent_context_audit(source, artifact_root=self.root, input_paths=(approved,))["status"], "passed")
            self.assertIn("forbidden_context_reference:archived_artifact", parent_context_audit(source, artifact_root=self.root)["errors"])
            call["input"] += "await tools.exec_command({cmd:'cat /repo/.thoughts/OTHER/runs/old/analysis.md'});"
            source.write_text("".join(json.dumps(row) + "\n" for row in header + [{"type": "response_item", "payload": call}]))
            self.assertIn("forbidden_context_reference:archived_artifact",
                          parent_context_audit(source, artifact_root=self.root, input_paths=(approved,))["errors"])

    def test_parent_patch_operations_are_parsed_without_treating_written_prose_as_reads(self):
        from scripts.provider_runtime import parent_context_audit
        source = self.repository / "parent.jsonl"
        header = [{"type": "session_meta", "payload": {"id": SOURCE}},
                  {"type": "turn_context", "payload": {"turn_id": "00000000-0000-0000-0000-000000000002"}}]
        patch = "*** Begin Patch\n*** Add File: " + str(self.root / "notes.md") + "\n+Do not read MEMORY.md or .thoughts/OLD/runs/analysis.md\n*** End Patch"
        for direct in (False, True):
            with self.subTest(direct=direct):
                call = {"type": "custom_tool_call", "name": "apply_patch" if direct else "exec",
                        "input": patch if direct else "text(await tools.apply_patch(" + json.dumps(patch) + "));"}
                source.write_text("".join(json.dumps(row) + "\n" for row in header + [{"type": "response_item", "payload": call}]))
                self.assertEqual(parent_context_audit(source, artifact_root=self.root)["status"], "passed")
                forbidden = dict(call)
                forbidden["input"] = forbidden["input"].replace(str(self.root / "notes.md"), str(self.root / "runs/old/notes.md"))
                source.write_text("".join(json.dumps(row) + "\n" for row in header + [{"type": "response_item", "payload": forbidden}]))
                self.assertIn("forbidden_context_reference:archived_artifact",
                              parent_context_audit(source, artifact_root=self.root)["errors"])
        call["input"] = "await tools.apply_patch(" + json.dumps(patch) + "); await tools.exec_command({cmd:'cat /repo/.codex/memories/MEMORY.md'});"
        call["name"] = "exec"
        source.write_text("".join(json.dumps(row) + "\n" for row in header + [{"type": "response_item", "payload": call}]))
        self.assertIn("forbidden_context_reference:memory_path", parent_context_audit(source, artifact_root=self.root)["errors"])

    def test_parent_allows_assigned_source_ancestor_policy_but_rejects_extra_output(self):
        source = self.repository / "src" / "module" / "current.py"
        source.parent.mkdir(parents=True)
        source.write_text("current source\n")
        instructions = source.parent / "AGENTS.md"
        policy = ("Do not read /Users/example/.codex/memories/MEMORY.md or "
                  ".thoughts/ITEM-1/runs/prior/analysis.md.\n")
        instructions.write_text(policy)
        call = 'await tools.exec_command(' + json.dumps({
            "cmd": "cat " + str(instructions), "workdir": str(self.repository)}) + ')'
        trace = {"tool_trace": self.paired(call, policy)}
        self.assertEqual(runtime.context_trace_errors(
            trace, artifact_root=self.root, input_paths=(str(source),)), [])

        extra = json.loads(json.dumps(trace))
        extra["tool_trace"][-1]["output"] = json.dumps([
            policy, "Read /Users/example/.codex/memories/notes.md",
            ".thoughts/ITEM-1/runs/prior/leaked.md"])
        errors = runtime.context_trace_errors(
            extra, artifact_root=self.root, input_paths=(str(source),))
        self.assertIn("forbidden_context_reference:memory_directory", errors)
        self.assertIn("forbidden_context_reference:archived_artifact", errors)

        unrelated_echo = json.loads(json.dumps(trace))
        echoed = self.paired('await tools.exec_command(' + json.dumps({
            "cmd": "cat " + str(source), "workdir": str(self.repository)}) + ')',
            policy + "Also read .thoughts/ITEM-1/runs/prior/leaked.md.\n")
        echoed[0]["call_id"] = echoed[1]["call_id"] = "unrelated-source-read"
        unrelated_echo["tool_trace"].extend(echoed)
        errors = runtime.context_trace_errors(
            unrelated_echo, artifact_root=self.root, input_paths=(str(source),))
        self.assertIn("forbidden_context_reference:archived_artifact", errors)

        unrelated = self.repository / "other" / "AGENTS.md"
        unrelated.parent.mkdir()
        unrelated.write_text(policy)
        unrelated_call = 'await tools.exec_command(' + json.dumps({
            "cmd": "cat " + str(unrelated), "workdir": str(self.repository)}) + ')'
        unrelated_trace = {"tool_trace": self.paired(unrelated_call, policy)}
        errors = runtime.context_trace_errors(
            unrelated_trace, artifact_root=self.root, input_paths=(str(source),))
        self.assertIn("forbidden_context_reference:memory_path", errors)

    def paired(self, source, output):
        return [{"type": "custom_tool_call", "name": "functions.exec", "call_id": "read-1", "input": source},
                {"type": "custom_tool_call_output", "call_id": "read-1", "output": output}]

    def test_command_echo_delimiter_does_not_change_current_path(self):
        command = "git status --short -- " + str(self.root)
        call = "const cmds=[" + json.dumps(command) + "]; /* command output labels */"
        trace = {"tool_trace": self.paired(call, "---" + command + "---\n")}
        self.assertEqual(runtime.context_trace_errors(trace, artifact_root=self.root), [])
        archived = "git status --short -- " + str(self.root) + "---"
        trace = {"tool_trace": self.paired("const cmds=[" + json.dumps(archived) + "];", "---" + archived + "---\n")}
        self.assertIn("forbidden_context_reference:archived_artifact",
                      runtime.context_trace_errors(trace, artifact_root=self.root))
        trace = {"tool_trace": self.paired(call, "---" + command + "---\n" + str(self.root.parent / "OTHER/runs/old/file"))}
        self.assertIn("forbidden_context_reference:archived_artifact",
                      runtime.context_trace_errors(trace, artifact_root=self.root))

    def test_verified_framework_search_lines_do_not_count_as_archive_reads(self):
        package = self.repository / "framework"
        package.mkdir()
        source = package / "example.py"
        content = 'example = "/tmp/.thoughts/OTHER/runs/prior/plan.md"'
        source.write_text(content + "\n")
        bindings_path = self.root / "role_bindings.json"
        bindings = json.loads(bindings_path.read_text())
        bindings["framework_package"]["root"] = str(package)
        bindings_path.write_text(json.dumps(bindings))
        command = 'rg -n example ' + str(package)
        call = 'const r = await tools.exec_command(' + json.dumps({"cmd": command}) + '); text(r.output);'
        line = str(source) + ':1:' + content
        trace = {"tool_trace": self.paired(call, line)}
        self.assertEqual(runtime.context_trace_errors(trace, artifact_root=self.root), [])
        for change in (line + "\n/tmp/.thoughts/OTHER/runs/prior/secret.md",
                       line.replace('example =', 'invented =')):
            trace["tool_trace"][1]["output"] = change
            self.assertIn("forbidden_context_reference:archived_artifact",
                          runtime.context_trace_errors(trace, artifact_root=self.root))
        trace["tool_trace"][1]["output"] = line
        trace["tool_trace"][0]["input"] += '; await tools.exec_command({cmd:"cat /tmp/.thoughts/OTHER/runs/prior/secret.md"});'
        self.assertIn("forbidden_context_reference:archived_artifact",
                      runtime.context_trace_errors(trace, artifact_root=self.root))

    def test_authorized_thread_output_does_not_execute_quoted_memory_commands(self):
        trace = self.dispatch_trace(["codex://threads/" + SOURCE])
        code = ('const [issue, thread] = await Promise.all(['
                'tools.mcp__codex_apps__atlassian_getjiraissue({issueIdOrKey:"ITEM-1",view:"evidence"}),'
                'tools.mcp__codex_app__read_thread({threadId:"' + SOURCE + '",turnLimit:10,includeOutputs:false})]);'
                'text(JSON.stringify({issue,thread}));')
        quoted = json.dumps({"thread": {"turns": [{"command": "cat /repo/.codex/memories/MEMORY.md"}]}})
        trace["tool_trace"] = self.paired(code, [{"type": "text", "text": quoted}])
        self.assertEqual(runtime.context_trace_errors(trace), [])
        trace["tool_trace"][0]["input"] = code.replace(SOURCE, "00000000-0000-0000-0000-000000000099")
        self.assertTrue(any(error.startswith("forbidden_context_reference:memory_")
                            for error in runtime.context_trace_errors(trace)))

    def test_current_inventory_locators_do_not_mean_archived_files_were_read(self):
        manifest = self.root / "asset_manifest.json"
        inventory = {"assets": [{"locator": "/repo/.thoughts/ITEM-1_v1/runs/old/research.md"}]}
        manifest.write_text(json.dumps(inventory))
        trace = self.dispatch_trace([str(manifest)])
        code = 'const r = await tools.exec_command({cmd:"cat ' + str(manifest) + '"}); text(r.output);'
        trace["tool_trace"] = self.paired(code, json.dumps(inventory))
        self.assertEqual(runtime.context_trace_errors(trace), [])
        trace["tool_trace"].append({"type": "custom_tool_call", "name": "functions.exec", "input":
                                  'await tools.exec_command({cmd:"cat /repo/.thoughts/ITEM-1_v1/runs/old/research.md"})'})
        self.assertIn("forbidden_context_reference:archived_artifact", runtime.context_trace_errors(trace))

    def test_current_root_sentence_punctuation_is_not_another_work_item(self):
        call = 'await tools.exec_command({cmd:"cat current_source.txt"})'
        text = "All run artifacts stay inside " + str(self.root) + ". Do not read prior runs."
        trace = {"tool_trace": self.paired(call, text)}
        self.assertEqual(runtime.context_trace_errors(trace, artifact_root=self.root), [])
        for reference in (str(self.root) + ".", str(self.root) + "./runs/prior/notes.md"):
            changed = {"tool_trace": self.paired('await tools.exec_command(' + json.dumps({
                "cmd": "cat " + reference}) + ')', text)}
            self.assertIn("forbidden_context_reference:archived_artifact",
                          runtime.context_trace_errors(changed, artifact_root=self.root))
        trace["tool_trace"][-1]["output"] = text.replace(self.root.name + ".", "OTHER.")
        self.assertIn("forbidden_context_reference:archived_artifact",
                      runtime.context_trace_errors(trace, artifact_root=self.root))

    def test_reading_detector_definition_does_not_hide_a_real_memory_citation(self):
        call = 'await tools.exec_command({cmd:"sed -n 1,85p runtime_checks.py"})'
        definition = '("memory_citation", re.compile(r"(?i)<' + 'oai-mem-citation>")),'
        trace = {"tool_trace": self.paired(call, definition)}
        self.assertNotIn("forbidden_context_reference:memory_citation",
                         runtime.context_trace_errors(trace, artifact_root=self.root))
        trace["tool_trace"][-1]["output"] += "\n<oai-mem-citation>\n<citation_entries>"
        self.assertIn("forbidden_context_reference:memory_citation",
                      runtime.context_trace_errors(trace, artifact_root=self.root))

    def test_current_input_exclusion_text_in_read_chains_is_not_archive_access(self):
        manifest = self.root / "run_inputs.json"
        content = "All run files stay inside .thoughts/ITEM-1. Do not inspect .thoughts/2806_v1; names only."
        manifest.write_text(content)
        (self.repository / "AGENTS.md").write_text("# Current repository instructions\n")
        for command in ("cat .thoughts/ITEM-1/run_inputs.json AGENTS.md && git status --short",
                        "cat AGENTS.md; cat .thoughts/ITEM-1/run_inputs.json"):
            with self.subTest(command=command):
                trace = self.instruction_read_trace()
                call = 'await tools.exec_command(' + json.dumps({"cmd": command, "workdir": str(self.repository)}) + ')'
                trace["tool_trace"].extend(self.paired(call, content + "\n# Current repository instructions\n"))
                self.assertEqual(runtime.context_trace_errors(trace), [])
                for tail in ("cat .thoughts/2806_v1/notes.md", "git show HEAD:.thoughts/2806_v1/notes.md"):
                    changed = json.loads(json.dumps(trace))
                    changed["tool_trace"][-2]["input"] = call.replace(command, command + "; " + tail)
                    self.assertIn("forbidden_context_reference:archived_artifact", runtime.context_trace_errors(changed))

    def test_wrapped_filename_discovery_is_not_archived_content(self):
        archive = ".thoughts/ITEM-1/runs/previous/issue_evidence.md"
        trace = {"tool_trace": self.paired(
            'const r = await tools.exec_command({cmd:"rg --files .thoughts/ITEM-1"}); text(r.output);',
            [{"type": "input_text", "text": archive}])}
        self.assertEqual(runtime.context_trace_errors(trace), [])
        listing = {"tool_trace": [{"type": "function_call", "name": "exec_command", "arguments": {
            "cmd": "ls -d .thoughts/*/", "workdir": str(self.repository)}}]}
        self.assertEqual(runtime.context_trace_errors(listing, artifact_root=self.root), [])
        trace["tool_trace"][0]["input"] += (
            'await tools.exec_command({cmd:"cat ' + archive + '"});')
        self.assertIn("forbidden_context_reference:archived_artifact", runtime.context_trace_errors(trace))

    def test_inverted_listing_filter_is_name_only(self):
        command = "rg --files --hidden " + str(self.root) + " | rg -v '/runs/'"
        trace = {"tool_trace": [{"type": "function_call", "name": "exec_command",
                                  "arguments": {"cmd": command}}]}
        self.assertEqual(runtime.context_trace_errors(trace, artifact_root=self.root), [])
        trace["tool_trace"][0]["arguments"]["cmd"] += " ; cat /tmp/.thoughts/OTHER/runs/old/secret"
        self.assertIn("forbidden_context_reference:archived_artifact",
                      runtime.context_trace_errors(trace, artifact_root=self.root))

    def test_mixed_reads_and_listing_keep_read_content_audited(self):
        report = self.repository / "report.md"
        report.write_text("Current report\n")
        archive = ".thoughts/ITEM-1/runs/previous/issue_evidence.md"
        command = ("cat report.md && printf '\\n--- directory files ---\\n' && "
                   "rg --files .thoughts/ITEM-1")
        output = "Current report\n\n--- directory files ---\n" + archive
        arguments = {"cmd": command, "workdir": str(self.repository)}
        for wrapped in (False, True):
            with self.subTest(wrapped=wrapped):
                rows = (self.paired("const r = await tools.exec_command(" + json.dumps(arguments) +
                                    "); text(r.output);", [{"type": "input_text", "text": output}])
                        if wrapped else [{"tool": "exec_command", "arguments": arguments,
                                          "result": {"output": output}}])
                self.assertEqual(runtime.context_trace_errors({"tool_trace": rows}), [])
        report.write_text(archive + "\n")
        rows = self.paired("await tools.exec_command(" + json.dumps(arguments) + ")",
                           report.read_text() + "\n--- directory files ---\n" + archive)
        self.assertIn("forbidden_context_reference:archived_artifact",
                      runtime.context_trace_errors({"tool_trace": rows}))

    def test_source_search_and_slice_prefix_keeps_listing_names_separate(self):
        from shutil import which
        if not which("rg"):
            self.skipTest("literal rg prefix reconstruction requires ripgrep")
        source = self.repository / "source.ts"
        source.write_text("first\nmatch current\nlast\n")
        archive = ".thoughts/ITEM-1/runs/previous/issue_evidence.md"
        command = "rg -n 'match' source.ts | head -70; cat source.ts; sed -n '2,3p' source.ts; rg --files .thoughts/ITEM-1"
        prefix = "2:match current\n" + source.read_text() + "match current\nlast\n"
        arguments = {"cmd": command, "workdir": str(self.repository)}
        for wrapped in (False, True):
            with self.subTest(wrapped=wrapped):
                output = prefix + archive + "\n"
                rows = (self.paired("text(await tools.exec_command(" + json.dumps(arguments) + "));", output)
                        if wrapped else [{"tool": "exec_command", "arguments": arguments, "result": {"output": output}}])
                self.assertEqual(runtime.context_trace_errors({"tool_trace": rows}), [])
        directory = self.repository / "sources"
        directory.mkdir()
        (directory / "one.ts").write_text("match current\n")
        directory_command = command.replace("'match' source.ts", "'match' sources")
        rows = self.paired("text(await tools.exec_command(" + json.dumps({**arguments, "cmd": directory_command}) + "));",
                           prefix.replace("2:match current\n", "sources/one.ts:1:match current\n", 1) + archive)
        self.assertEqual(runtime.context_trace_errors({"tool_trace": rows}), [])
        for unsafe in (command.replace("head -70", "xargs cat"),
                       command.replace("'match'", "--pre=cat"),
                       command.replace("source.ts", archive),
                       command + "; cat " + archive):
            rows = self.paired("text(await tools.exec_command(" + json.dumps({**arguments, "cmd": unsafe}) + "));",
                               prefix + archive + "\n")
            self.assertIn("forbidden_context_reference:archived_artifact", runtime.context_trace_errors({"tool_trace": rows}))
        source.write_text(archive + "\n")
        output = archive + "\n" + archive
        rows = self.paired("text(await tools.exec_command(" + json.dumps(arguments) + "));", output)
        self.assertIn("forbidden_context_reference:archived_artifact", runtime.context_trace_errors({"tool_trace": rows}))

    def test_search_prefix_ignores_config_and_fails_closed_when_unavailable_or_unbounded(self):
        import os
        from shutil import which
        from unittest.mock import patch
        from scripts.runtime_checks import _listing_read_prefix
        if not which("rg"):
            self.skipTest("literal rg prefix reconstruction requires ripgrep")
        source = self.repository / "source.ts"
        source.write_text("match current\n")
        config = self.repository / "rg-config"
        config.write_text("--heading\n")
        command = "rg -n match source.ts; rg --files .thoughts/ITEM-1"
        with patch.dict(os.environ, {"RIPGREP_CONFIG_PATH": str(config)}):
            self.assertEqual(_listing_read_prefix(command, self.repository), "1:match current\n")
        for error in (FileNotFoundError(), subprocess.TimeoutExpired("rg", 2)):
            with self.subTest(error=type(error).__name__), patch("scripts.runtime_checks.subprocess.run", side_effect=error):
                self.assertIsNone(_listing_read_prefix(command, self.repository))
        with patch("scripts.runtime_checks.subprocess.run") as run:
            self.assertIsNone(_listing_read_prefix(command.replace("-n match", "-n --pre=cat"), self.repository))
            source.write_text("x" * 262145)
            self.assertIsNone(_listing_read_prefix(command, self.repository))
            run.assert_not_called()

    def test_mixed_listing_exception_requires_exact_read_output_and_safe_command(self):
        report = self.repository / "report.md"
        report.write_text("Current report\n")
        archive = ".thoughts/ITEM-1/runs/previous/issue_evidence.md"
        for command, output in (
            ("cat report.md && rg --files .thoughts/ITEM-1", "Unexpected output\n" + archive),
            ("cat report.md && rg --files .thoughts/ITEM-1", "Current report\nRead " + archive),
            ("cat report.md && rg --files .thoughts/ITEM-1 && cat " + archive, "Current report\n" + archive),
            ("cat report.md && rg --files .thoughts/ITEM-1 | xargs cat", "Current report\n" + archive),
            ("cat report.md & rg --files .thoughts/ITEM-1", "Current report\n" + archive),
            ("cat report.md && printf '%b' ignored && rg --files .thoughts/ITEM-1",
             "Current report\n" + archive),
        ):
            with self.subTest(command=command, output=output):
                code = "await tools.exec_command(" + json.dumps({
                    "cmd": command, "workdir": str(self.repository)}) + ")"
                self.assertIn("forbidden_context_reference:archived_artifact",
                              runtime.context_trace_errors({"tool_trace": self.paired(code, output)}))
        for workdir in (None, [], {}):
            code = "await tools.exec_command(" + json.dumps({
                "cmd": "cat report.md && rg --files .thoughts/ITEM-1", "workdir": workdir}) + ")"
            self.assertIn("forbidden_context_reference:archived_artifact", runtime.context_trace_errors({
                "tool_trace": self.paired(code, "Current report\n" + archive)}))

    def test_mixed_listing_uses_authenticated_repository_when_workdir_is_omitted(self):
        trace = self.dispatch_trace([])
        (self.repository / "report.md").write_text("Current report\n")
        rows = self.paired('await tools.exec_command({cmd:"cat report.md && rg --files .thoughts/ITEM-1"})',
                           "Current report\n.thoughts/ITEM-1/runs/previous/issue_evidence.md")
        rows[0]["call_id"] = rows[1]["call_id"] = "mixed-listing"
        trace["tool_trace"].extend(rows)
        self.assertEqual(runtime.context_trace_errors(trace), [])

    def test_listing_output_does_not_exempt_memory_paths(self):
        report = self.repository / "report.md"
        report.write_text("Current report\n")
        for command in ("rg --files .", "cat report.md && rg --files ."):
            code = "await tools.exec_command(" + json.dumps({
                "cmd": command, "workdir": str(self.repository)}) + ")"
            trace = {"tool_trace": self.paired(code, "Current report\n/Users/example/.codex/memories/MEMORY.md")}
            self.assertIn("forbidden_context_reference:memory_path", runtime.context_trace_errors(trace))

    def test_worker_host_memory_probe_requires_native_proof_of_no_matches(self):
        from unittest.mock import patch
        codex = self.repository / ".codex"
        session = codex / "sessions" / "worker.jsonl"
        session.parent.mkdir(parents=True)
        memory = codex / "memories" / "MEMORY.md"
        command = "rg -n -F ITEM-1 " + str(memory)
        observation = {"type": "CommandExecution", "command": ["bash", "-lc", command],
                       "parsed_cmd": [{"type": "search", "query": "ITEM-1", "path": "MEMORY.md"}],
                       "exit_code": 1, "status": "failed", "aggregated_output": ""}
        header = {"type": "session_meta", "payload": {"id": SOURCE}}
        event = {"type": "event_msg", "payload": {"type": "item_completed", "item": observation}}
        def save(*rows):
            session.write_text("".join(json.dumps(row) + "\n" for row in rows))
        trace = {"thread_id": SOURCE, "trace_retrieval": str(session), "tool_trace": [{
            "type": "function_call", "name": "exec_command", "arguments": {"cmd": command}}]}
        with patch.dict("os.environ", {"CODEX_HOME": str(codex)}):
            save(header, event)
            self.assertEqual(runtime.context_trace_errors(trace), [])
            batched = {"thread_id": SOURCE, "trace_retrieval": str(session), "tool_trace": [{
                "type": "custom_tool_call", "name": "exec", "input":
                'await tools.exec_command({cmd:"shasum -a 256 dispatch.txt"});\n'
                + "await tools.exec_command(" + json.dumps({"cmd": command}) + ");"}]}
            self.assertEqual(runtime.context_trace_errors(batched), [])
            observation.update({"exit_code": 0, "status": "completed", "aggregated_output": "matched historical content"})
            save(header, event)
            self.assertIn("forbidden_context_reference:memory_path", runtime.context_trace_errors(trace))
            self.assertIn("forbidden_context_reference:memory_path", runtime.context_trace_errors(batched))
            observation.update({"exit_code": 1, "status": "failed", "aggregated_output": ""})
            save(header, event)
            batched["tool_trace"][0]["input"] += "\nawait tools.exec_command(" + json.dumps({"cmd": "cat " + str(memory)}) + ");"
            self.assertIn("forbidden_context_reference:memory_path", runtime.context_trace_errors(batched))
            save(header, event, event)
            self.assertEqual(runtime.context_trace_errors(trace), [])
            bad_observation = dict(observation, exit_code=0, status="completed", aggregated_output="matched historical content")
            bad_event = {"type": "event_msg", "payload": {"type": "item_completed", "item": bad_observation}}
            save(header, event, bad_event)
            self.assertIn("forbidden_context_reference:memory_path", runtime.context_trace_errors(trace))
            save({"type": "session_meta", "payload": {"id": "other"}}, event)
            self.assertIn("forbidden_context_reference:memory_path", runtime.context_trace_errors(trace))

    def test_worker_host_memory_read_requires_host_authority_and_native_output(self):
        from unittest.mock import patch
        codex = self.repository / ".codex"
        session = codex / "sessions" / "worker.jsonl"
        session.parent.mkdir(parents=True)
        memory = codex / "memories" / "MEMORY.md"
        memory.parent.mkdir(parents=True)
        memory.write_text("historical .thoughts/OTHER/runs/old/file\n")
        command = "cat " + str(memory)
        header = {"type": "session_meta", "payload": {"id": SOURCE}}
        directive = {"type": "response_item", "payload": {"type": "message", "role": "developer",
                     "content": [{"type": "input_text", "text": "Decision boundary MEMORY_SUMMARY " + str(memory)}]}}
        native = {"type": "event_msg", "timestamp": "2026-10-01T00:00:02Z", "payload": {"type": "item_completed", "item": {
            "type": "CommandExecution", "command": ["bash", "-lc", command], "status": "completed",
            "exit_code": 0, "aggregated_output": memory.read_text()}}}
        trace = {"thread_id": SOURCE, "trace_retrieval": str(session), "last_dispatch_at": "2026-10-01T00:00:01Z",
                 "status_observation": {"Observed at": "2026-10-01T00:00:03Z"},
                 "tool_trace": self.paired("await tools.exec_command(" + json.dumps({"cmd": command}) + ")", memory.read_text())}
        def save():
            session.write_text("".join(json.dumps(row) + "\n" for row in (header, directive, native)))
        with patch.dict("os.environ", {"CODEX_HOME": str(codex)}):
            save()
            self.assertEqual(runtime.context_trace_errors(trace), [])
            batch = ('const rs = await Promise.allSettled(['
                     'tools.exec_command({cmd:"cat /tmp/skill.md"}),'
                     'tools.exec_command(' + json.dumps({"cmd": command}) + ')'
                     ']); for (const r of rs) text(r.status === "fulfilled" ? r.value.output : String(r.reason));')
            batched = {**trace, "tool_trace": self.paired(batch, "skill contents\n" + memory.read_text())}
            self.assertEqual(runtime.context_trace_errors(batched), [])
            batched["tool_trace"][0]["input"] = batch.replace(
                'tools.exec_command({cmd:"cat /tmp/skill.md"})',
                'tools.exec_command(' + json.dumps({"cmd": "cat " + str(memory) + " > /tmp/copy"}) + ')')
            self.assertIn("forbidden_context_reference:memory_path", runtime.context_trace_errors(batched))
            trace["tool_trace"][1]["output"] += ".thoughts/OTHER/runs/old/extra\n"
            self.assertIn("forbidden_context_reference:archived_artifact", runtime.context_trace_errors(trace))
            trace["tool_trace"][1]["output"] = memory.read_text()
            native["timestamp"] = "2026-09-30T00:00:00Z"
            save()
            self.assertIn("forbidden_context_reference:memory_path", runtime.context_trace_errors(trace))
            native["timestamp"] = "2026-10-01T00:00:02Z"
            directive["payload"]["role"] = "user"
            save()
            self.assertIn("forbidden_context_reference:memory_path", runtime.context_trace_errors(trace))

    def test_worker_response_preserves_host_required_memory_citation(self):
        from unittest.mock import patch
        from scripts.worker_runtime_evidence import worker_response_value, _materialize_worker_response
        codex = self.repository / ".codex"
        session = codex / "sessions" / "worker.jsonl"
        session.parent.mkdir(parents=True)
        memory = codex / "memories" / "MEMORY.md"
        directive = {"type": "response_item", "payload": {"type": "message", "role": "developer",
            "content": [{"type": "input_text", "text": "Decision boundary MEMORY_SUMMARY " + str(memory)}]}}
        session.write_text(json.dumps(directive) + "\n")
        envelope = {"output": "Historical context is identified.", "result": {"run_id": "run"}}
        suffix = "\n<oai-mem-citation>\n<citation_entries>\nMEMORY.md:1-2|note=[context]\n</citation_entries>\n<rollout_ids>\n</rollout_ids>\n</oai-mem-citation>"
        response = json.dumps(envelope) + suffix
        with patch.dict("os.environ", {"CODEX_HOME": str(codex)}):
            self.assertEqual(worker_response_value(response, session), envelope)
            receipt = _materialize_worker_response(self.root, "tester", "dispatch", response, {}, session)
            self.assertEqual(Path(receipt["response_path"]).read_text(), response)
            directive["payload"]["role"] = "user"
            session.write_text(json.dumps(directive) + "\n")
            with self.assertRaisesRegex(ValueError, "worker_final_response_json_invalid"):
                worker_response_value(response, session)
            directive["payload"]["role"] = "developer"
            session.write_text(json.dumps(directive) + "\n")
            for invalid in (response + " trailing text", response.replace("MEMORY.md:1-2", "../../secret:1-2"),
                            response.replace("MEMORY.md:1-2", "MEMORY.md:2-1"),
                            response.replace("MEMORY.md:1-2|note=[context]", ""),
                            response.replace("<rollout_ids>\n", "<rollout_ids>\ninvalid-id\n")):
                with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, "worker_final_response_json_invalid"):
                    worker_response_value(invalid, session)

    def test_worker_can_read_only_a_rollout_linked_by_a_native_memory_read(self):
        from unittest.mock import patch
        codex = self.repository / ".codex"
        session = codex / "sessions" / "worker.jsonl"
        session.parent.mkdir(parents=True)
        prior = session.parent / "prior.jsonl"
        memory = codex / "memories" / "MEMORY.md"
        memory.parent.mkdir(parents=True)
        memory.write_text("rollout_path=" + str(prior) + "\n")
        prior.write_text(".thoughts/OTHER/runs/old/file\n")
        directive = {"type": "response_item", "payload": {"type": "message", "role": "developer",
            "content": [{"type": "input_text", "text": "Decision boundary MEMORY_SUMMARY " + str(memory)}]}}
        def native(path):
            return {"type": "event_msg", "timestamp": "2026-10-01T00:00:02Z", "payload": {
                "type": "item_completed", "item": {"type": "CommandExecution",
                "command": ["bash", "-lc", "cat " + str(path)], "status": "completed", "exit_code": 0,
                "aggregated_output": path.read_text()}}}
        first = self.paired('await tools.exec_command(' + json.dumps({"cmd": "cat " + str(memory)}) + ')', memory.read_text())
        second = self.paired('await tools.exec_command(' + json.dumps({"cmd": "cat " + str(prior)}) + ')', prior.read_text())
        for row in second: row["call_id"] = "read-2"
        trace = {"thread_id": SOURCE, "trace_retrieval": str(session), "last_dispatch_at": "2026-10-01T00:00:01Z",
                 "status_observation": {"Observed at": "2026-10-01T00:00:03Z"}, "tool_trace": first + second}
        rows = [{"type": "session_meta", "payload": {"id": SOURCE}}, directive, native(memory), native(prior)]
        with patch.dict("os.environ", {"CODEX_HOME": str(codex)}):
            session.write_text("".join(json.dumps(row) + "\n" for row in rows))
            self.assertEqual(runtime.context_trace_errors(trace), [])
            rows[2]["payload"]["item"]["aggregated_output"] = "no linked rollout\n"
            session.write_text("".join(json.dumps(row) + "\n" for row in rows))
            self.assertIn("forbidden_context_reference:archived_artifact", runtime.context_trace_errors(trace))

    def test_codex_home_memory_paths_are_rejected_when_quoted(self):
        for command, expected in (
            ('cat "$CODEX_HOME/memories/MEMORY.md"', "memory_path"),
            ('rg -n issue "${CODEX_HOME}/memories/notes.md"', "memory_directory"),
            (r'cat "%CODEX_HOME%\memories\MEMORY.md"', "memory_path"),
            (r'rg -n issue "$env:CODEX_HOME\memories\notes.md"', "memory_directory"),
            ('rg -n issue "$CODEX_HOME"/memories/notes.md', "memory_directory"),
            ('rg -n issue "${CODEX_HOME}"/memories/notes.md', "memory_directory"),
            (r'rg -n issue "$env:CODEX_HOME"\memories\notes.md', "memory_directory"),
        ):
            with self.subTest(command=command):
                trace = {"tool_trace": [{"tool": "exec_command", "arguments": {"cmd": command},
                                          "result": {"output": ""}}]}
                self.assertIn("forbidden_context_reference:" + expected,
                              runtime.context_trace_errors(trace))

    def test_spike_report_context_uses_the_shared_memory_path_rules(self):
        from scripts.run_input_manifest import default_manifest
        from scripts.validation.common import FORBIDDEN_REPORT_CONTEXT_PATTERNS
        from scripts.validation.playbooks import _spike_report_context_errors
        from scripts.workflow_policy import FORBIDDEN_MEMORY_CONTEXT_PATTERNS

        self.assertTrue(all(any(label == shared_label and pattern is shared_pattern
                                for label, pattern in FORBIDDEN_REPORT_CONTEXT_PATTERNS)
                            for shared_label, shared_pattern in FORBIDDEN_MEMORY_CONTEXT_PATTERNS))
        manifest = self.repository / "run_inputs.json"
        manifest.write_text(json.dumps(default_manifest("ITEM-1", "technical_spike", self.repository)))
        rows = [{"Evidence ID": "SRC-001", "Method or source":
                 'cat "${CODEX_HOME}/memories/MEMORY.md"'}]
        errors = _spike_report_context_errors(rows, [], manifest)
        self.assertTrue(any("forbidden context: memory_path" in error for error in errors))

    def test_python_inventory_inspection_is_data_but_writes_are_not_allowed(self):
        manifest = self.root / "asset_manifest.json"
        manifest.write_text('{}')
        trace = self.dispatch_trace([])
        command = ("python3 - <<'PY'\nimport json\np=json.load(open(" + repr(str(manifest))
                   + "))\nprint(p.keys())\nprint('sources',json.dumps(p.get('sources',[]),indent=2))\nPY")
        code = 'const r = await tools.exec_command(' + json.dumps({"cmd": command}) + '); text(r.output);'
        trace["tool_trace"] = self.paired(code, "/repo/.thoughts/ITEM-1_v1/runs/old/research.md")
        self.assertEqual(runtime.context_trace_errors(trace), [])
        write = command.replace("print(p.keys())", "open('/repo/.thoughts/ITEM-1_v1/old.md', 'w')")
        trace["tool_trace"][0]["input"] = 'await tools.exec_command(' + json.dumps({"cmd": write}) + ')'
        self.assertIn("forbidden_context_reference:archived_artifact", runtime.context_trace_errors(trace))

    def test_serialized_instruction_output_keeps_its_exact_metadata_exception(self):
        self.artifacts = self.root
        self.bundle = self.run["activation_packet_bundle"]
        self.dispatch_number = 0
        self.command = lambda *args: subprocess.run(
            [sys.executable, str(runtime.ROOT / "scripts/validate_worker_runtime.py"), *map(str, args)],
            capture_output=True, text=True)
        trace = activation_fixtures.ActivationDelivery.instruction_trace(self)
        text = trace["tool_trace"][1]["output"][0]["text"]
        trace["tool_trace"][1]["output"] = [{"type": "text", "text": json.dumps({
            "output": "sha256 digest and filename\n" + text})}]
        self.assertEqual(runtime.context_trace_errors(trace), [])

    def test_recorded_cat_loop_is_read_only_but_an_added_write_is_rejected(self):
        manifest = self.root / "asset_manifest.json"
        manifest.write_text('{}')
        trace = self.dispatch_trace([str(manifest)])
        cmd = "for f in " + str(manifest) + "; do printf '\\n===== %s =====\\n' \"$f\"; cat \"$f\"; done"
        code = 'const r = await tools.exec_command(' + json.dumps({"cmd": cmd}) + '); text(r.output);'
        trace["tool_trace"] = self.paired(code, "/repo/.thoughts/ITEM-1_v1/runs/old/research.md")
        self.assertEqual(runtime.context_trace_errors(trace), [])
        trace["tool_trace"][0]["input"] = code.replace('cat \\"$f\\"', 'rm \\"$f\\"')
        self.assertIn("forbidden_context_reference:archived_artifact", runtime.context_trace_errors(trace))

    def test_batch_with_an_actual_memory_read_is_never_exempt(self):
        trace = self.dispatch_trace(["codex://threads/" + SOURCE])
        code = ('await Promise.all([tools.mcp__codex_app__read_thread({threadId:"' + SOURCE + '"}),'
                'tools.exec_command({cmd:"cat /repo/.codex/memories/MEMORY.md"})]);')
        trace["tool_trace"] = self.paired(code, "cat /repo/.codex/memories/MEMORY.md")
        self.assertTrue(any(error.startswith("forbidden_context_reference:memory_")
                            for error in runtime.context_trace_errors(trace)))

    def test_logical_worker_name_authenticates_its_provider_role(self):
        trace = self.dispatch_trace([])
        trace["spawn"]["agent"] = "feature-context"
        self.assertIsNotNone(runtime._verified_dispatch_content(trace))

    def test_handoff_and_delivery_worker_names_resolve_their_provider_bindings(self):
        bindings = json.loads((self.root / "role_bindings.json").read_text())
        for worker, role in runtime.DELIVERY_WORKERS.items():
            self.assertEqual(runtime.worker_binding(bindings, worker), role)
        packet = json.loads((self.root / "worker_activation_packets.json").read_text())["packets"]["documenter"]
        path = self.root / "activation_handoff.txt"
        runtime.dispatch_message(packet, runtime.activation_message(packet, {"objective": "Write the validated handoff"}), path)
        trace = {"run_id": self.run["run_id"], "spawn": {"agent": "handoff", "dispatch_file": str(path),
            "dispatch_file_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}}
        self.assertIsNotNone(runtime._verified_dispatch_content(trace))

    def test_opaque_parent_launch_uses_observed_instruction_read_for_audit_proof(self):
        trace = self.dispatch_trace(["codex://threads/" + SOURCE])
        child = "00000000-0000-0000-0000-000000000002"
        handle, dispatch = "/root/context", "2026-10-13T01:00:01Z"
        notice = 'sha256sum ' + trace["spawn"]["dispatch_file"] + ' && cat ' + trace["spawn"]["dispatch_file"]
        input_code = 'await tools.exec_command(' + json.dumps({"cmd": notice}) + ')'
        quoted = json.dumps({"thread": {"command": "cat /repo/.codex/memories/MEMORY.md"}})
        trace["tool_trace"] = [{"type": "custom_tool_call", "call_id": "instructions", "input": input_code},
            {"type": "custom_tool_call_output", "call_id": "instructions",
             "output": Path(trace["spawn"]["dispatch_file"]).read_text()}, *self.paired(
            'await tools.mcp__codex_app__read_thread({threadId:"' + SOURCE + '"})', quoted)]
        source = self.repository / "child.jsonl"
        binding = json.loads((self.root / "role_bindings.json").read_text())["bindings"]["current_state_investigator"]
        rows = [{"timestamp": "2026-10-13T01:00:00Z", "type": "session_meta", "payload": {"id": child}},
            *[{"timestamp": "2026-10-13T01:00:02Z", "type": "response_item", "payload": row}
              for row in trace["tool_trace"]],
            {"timestamp": "2026-10-13T01:00:03Z", "type": "turn_context", "payload": {
                "turn_id": "00000000-0000-0000-0000-000000000004", "model": binding["model"],
                "effort": binding["effort"]}},
            {"timestamp": "2026-10-13T01:00:30Z", "type": "response_item", "payload": {
                "type": "message", "role": "assistant", "phase": "final_answer",
                "content": [{"type": "output_text", "text": json.dumps({"output": "Current response",
                    "result": self.result, "asset_manifest": {}})}]}}]
        source.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
        ledger = {"events": [{"Provider handle": handle, "Last dispatch at": dispatch, "Operation": "spawn_agent",
                  "Launch": {"model": binding["model"], "reasoning_effort": binding["effort"], "fork_turns": "none"}}],
                  "thread_mappings": {handle: child}}
        observation = {"Provider handle": handle, "Thread ID": child, "Provider status": "completed",
            "Last dispatch at": dispatch, "Observed at": "2026-10-13T01:01:00Z", "Status source": "read_thread",
            "Latest turn started at": "2026-10-13T01:00:03Z", "Latest turn completed at": "2026-10-13T01:00:30Z",
            "Latest turn status": "completed", "Thread status": "idle"}
        observation.pop("Last dispatch at")
        exported = export_worker_trace(ledger, source, "feature-context", observation,
                                       run_id=trace["run_id"], artifact_root=self.root)
        self.assertEqual(exported["audit"], {"status": "passed", "errors": []})
        self.assertEqual(exported["spawn"]["dispatch_proof_source"], "provider_instruction_read")
        self.assertEqual(exported["spawn"]["dispatch_file_sha256"], trace["spawn"]["dispatch_file_sha256"])

    def instruction_read_trace(self):
        trace = self.dispatch_trace([])
        content = Path(trace["spawn"]["dispatch_file"]).read_text()
        trace["spawn"].pop("activation_packet_delivered", None)
        trace["tool_trace"] = self.paired(
            'const r = await tools.exec_command(' + json.dumps({"cmd": "cat " + trace["spawn"]["dispatch_file"]})
            + '); text(r.output);', [{"type": "input_text", "text": content}])
        return trace

    def test_instruction_read_proves_binding_without_status_flags(self):
        trace = self.instruction_read_trace()
        self.assertEqual(runtime.trace_errors(trace), [])

    def test_labeled_current_packet_projection_does_not_exempt_archive_reads(self):
        trace = self.instruction_read_trace()
        packet_path = self.root / "finalization_packet.json"
        packet = json.loads(packet_path.read_text())
        packet["reentry"] = {"Prior artifacts": str(self.root / "runs" / "old")}
        packet_path.write_text(json.dumps(packet))
        code = ("import json; p=json.load(open('.thoughts/ITEM-1/finalization_packet.json')); "
                "[print(k+':', json.dumps(p.get(k), indent=2)) for k in ('identity', 'reentry')]")
        command = "python3 -c " + shlex.quote(code)
        call = 'await tools.exec_command(' + json.dumps({"cmd": command, "workdir": str(self.repository)}) + ')'
        output = "".join(f"{key}: {json.dumps(packet.get(key), indent=2)}\n" for key in ("identity", "reentry"))
        trace["tool_trace"].extend(self.paired(call, output))
        self.assertEqual(runtime.trace_errors(trace), [])
        trace["tool_trace"][-1]["output"] = output + str(self.root / "runs" / "old" / "private.md")
        self.assertIn("forbidden_context_reference:archived_artifact", runtime.trace_errors(trace))
        trace["tool_trace"][-1]["output"] = output
        trace["tool_trace"][-2]["input"] += ' await tools.exec_command({cmd:"cat .thoughts/ITEM-1/runs/old/private.md"});'
        self.assertIn("forbidden_context_reference:archived_artifact", runtime.trace_errors(trace))

    def test_instruction_proof_rejects_missing_output_wrong_hash_and_wrong_run(self):
        import copy
        base = self.instruction_read_trace()
        for failure in ("missing_output", "mismatched_call", "truncated_output", "wrong_hash", "wrong_run", "no_read"):
            with self.subTest(failure=failure):
                trace = copy.deepcopy(base)
                if failure == "missing_output": trace["tool_trace"].pop()
                elif failure == "mismatched_call": trace["tool_trace"][1]["call_id"] = "unmatched"
                elif failure == "truncated_output": trace["tool_trace"][1]["output"] = "Coordinator initialization: complete"
                elif failure == "wrong_hash": trace["spawn"]["dispatch_file_sha256"] = "0" * 64
                elif failure == "wrong_run": trace["run_id"] = "other-run"
                elif failure == "no_read": trace["tool_trace"][0]["input"] = 'text("contract read")'
                self.assertIn("provider_binding_not_delivered", runtime.trace_errors(trace))

    def test_hash_checked_variable_instruction_read_proves_binding(self):
        trace = self.instruction_read_trace()
        path = trace["spawn"]["dispatch_file"]
        digest = trace["spawn"]["dispatch_file_sha256"]
        command = ('packet=' + path + '; actual=$(sha256sum "$packet" | cut -d \' \' -f 1); '
                   'if [ "$actual" != ' + digest + ' ]; then printf \'SHA256_MISMATCH %s\\n\' "$actual"; '
                   'exit 2; fi; printf \'SHA256_OK %s\\n\' "$actual"; cat "$packet"')
        trace["tool_trace"][0]["input"] = 'await tools.exec_command(' + json.dumps({"cmd": command}) + ')'
        self.assertEqual(runtime.trace_errors(trace), [])
        trace["tool_trace"][0]["input"] = 'await tools.exec_command(' + json.dumps({
            "cmd": command + '; cat .thoughts/ITEM-1/runs/prior/notes.md'}) + ')'
        self.assertIn("provider_binding_not_delivered", runtime.trace_errors(trace))
        self.assertIn("forbidden_context_reference:archived_artifact", runtime.trace_errors(trace))

    def test_awk_checked_activation_read_proves_binding(self):
        for quote in ('"', r'\"'):
            trace = self.instruction_read_trace()
            path = trace["spawn"]["dispatch_file"]
            digest = trace["spawn"]["dispatch_file_sha256"]
            command = ("actual=$(shasum -a 256 " + path + " | awk '{print $1}'); "
                       + f'if [ {quote}$actual{quote} != {quote}{digest}{quote} ]; then '
                       + "printf 'SHA256 mismatch: %s\\\\n' " + quote + "$actual" + quote
                       + "; exit 2; fi; cat " + path)
            trace["tool_trace"][0]["input"] = 'await tools.exec_command(' + json.dumps({"cmd": command}) + ')'
            self.assertEqual(runtime.trace_errors(trace), [])
            trace["tool_trace"][0]["input"] = 'await tools.exec_command(' + json.dumps({
                "cmd": command + '; cat .thoughts/ITEM-1/runs/prior/notes.md'}) + ')'
            self.assertIn("provider_binding_not_delivered", runtime.trace_errors(trace))
            self.assertIn("forbidden_context_reference:archived_artifact", runtime.trace_errors(trace))

    def test_current_directory_heading_and_ancestor_reads_are_not_archive_consumption(self):
        trace = self.instruction_read_trace()
        command = ('ls -la .thoughts/ITEM-1; for f in AGENTS.md .thoughts/AGENTS.md '
                   '.thoughts/ITEM-1/AGENTS.md; do if test -f "$f"; then echo "--- $f"; cat "$f"; fi; done')
        call = 'await tools.exec_command(' + json.dumps({"cmd": command, "workdir": str(self.repository)}) + ')'
        rows = self.paired(call, '.thoughts/ITEM-1:\ntotal 0\n--- .thoughts/AGENTS.md')
        rows[0]["call_id"] = rows[1]["call_id"] = "heading"
        trace["tool_trace"].extend(rows)
        self.assertEqual(runtime.trace_errors(trace), [])
        for heading in ('.thoughts/OTHER:', '.thoughts/ITEM-1/runs/prior:'):
            changed = json.loads(json.dumps(trace))
            changed["tool_trace"][-1]["output"] = heading
            self.assertIn("forbidden_context_reference:archived_artifact", runtime.trace_errors(changed))
        changed = json.loads(json.dumps(trace))
        changed["tool_trace"][-2]["input"] = 'await tools.exec_command({cmd:"cat .thoughts/ITEM-1:"})'
        self.assertIn("forbidden_context_reference:archived_artifact", runtime.trace_errors(changed))

    def test_assigned_source_ancestor_instructions_are_policy_not_archive_reads(self):
        trace = self.instruction_read_trace()
        source = self.repository / "src" / "module" / "current.py"
        source.parent.mkdir(parents=True)
        source.write_text("current source")
        instructions = source.parent / "AGENTS.md"
        policy = ("Do not read /Users/example/.codex/memories/MEMORY.md or "
                  ".thoughts/ITEM-1/runs/prior/analysis.md.\n")
        instructions.write_text(policy)
        packet = json.loads(Path(trace["spawn"]["dispatch_file"]).read_text().split("\n", 2)[1])
        assignment = {"objective": "Inspect the assigned source", "input_paths": [str(source)]}
        dispatch = self.root / "nested-source-activation.txt"
        message = runtime.activation_message(packet, assignment)
        runtime.dispatch_message(packet, message, dispatch)
        trace["spawn"]["dispatch_file"] = str(dispatch.resolve())
        trace["spawn"]["dispatch_file_sha256"] = hashlib.sha256(dispatch.read_bytes()).hexdigest()
        trace["tool_trace"] = self.paired(
            'await tools.exec_command(' + json.dumps({"cmd": "cat " + str(dispatch.resolve()),
                "workdir": str(self.repository)}) + ')', message)
        trace["tool_trace"].extend(self.paired(
            'await tools.exec_command(' + json.dumps({"cmd": "cat " + str(instructions),
                "workdir": str(self.repository)}) + ')', policy))
        self.assertEqual(runtime.trace_errors(trace), [])

        unrelated = self.repository / "other" / "AGENTS.md"
        unrelated.parent.mkdir()
        unrelated.write_text(policy)
        changed = json.loads(json.dumps(trace))
        changed["tool_trace"][-2]["input"] = 'await tools.exec_command(' + json.dumps({
            "cmd": "cat " + str(unrelated), "workdir": str(self.repository)}) + ')'
        changed["tool_trace"][-1]["output"] = policy
        self.assertIn("forbidden_context_reference:archived_artifact", runtime.trace_errors(changed))

        changed = json.loads(json.dumps(trace))
        changed["tool_trace"][-2]["input"] += (
            " await tools.exec_command({cmd:'cat .thoughts/ITEM-1/runs/prior/leaked.md'});")
        errors = runtime.trace_errors(changed)
        self.assertIn("forbidden_context_reference:archived_artifact", errors)

    def test_current_packet_reentry_projection_is_not_an_archive_read(self):
        trace = self.instruction_read_trace()
        packet_path = self.root / "finalization_packet.json"
        packet = json.loads(packet_path.read_text())
        packet["reentry"] = {"Prior artifacts": str(self.root / "runs" / "prior")}
        packet_path.write_text(json.dumps(packet))
        call = 'const r = await tools.exec_command(' + json.dumps({"cmd": "jq '.reentry' " + str(packet_path)}) + '); text(r.output);'
        trace["tool_trace"].extend(self.paired(call, json.dumps(packet["reentry"])))
        self.assertEqual(runtime.trace_errors(trace), [])
        altered = json.loads(json.dumps(trace))
        altered["tool_trace"][-2]["input"] += ' await tools.exec_command({"cmd":"cat .thoughts/ITEM-1/runs/prior/secret.md"});'
        self.assertIn("forbidden_context_reference:archived_artifact", runtime.trace_errors(altered))
        extra = json.loads(json.dumps(trace))
        extra["tool_trace"][-1]["output"] = json.dumps({**packet["reentry"], "leaked": str(self.root / "runs" / "secret")})
        self.assertIn("forbidden_context_reference:archived_artifact", runtime.trace_errors(extra))
        other = json.loads(json.dumps(trace))
        other["tool_trace"][-2]["input"] = other["tool_trace"][-2]["input"].replace(str(packet_path), str(self.root / "runs" / "prior" / "finalization_packet.json"))
        self.assertIn("forbidden_context_reference:archived_artifact", runtime.trace_errors(other))

    def test_packet_object_projection_exempts_only_verified_reentry_path(self):
        trace = self.instruction_read_trace()
        packet_path = self.root / "finalization_packet.json"
        packet = json.loads(packet_path.read_text())
        packet["reentry"] = {"Prior artifacts": str(self.root / "runs" / "prior")}
        packet["identity"]["State"] = "in_progress"
        packet_path.write_text(json.dumps(packet))
        command = "jq '{identity, reentry}' " + str(packet_path)
        call = 'const r = await tools.exec_command(' + json.dumps({"cmd": command}) + '); text(r.output);'
        projected = {key: packet[key] for key in ("identity", "reentry")}
        output = [{"type": "input_text", "text": json.dumps(projected)}]
        rows = self.paired(call, output)
        rows[0]["call_id"] = rows[1]["call_id"] = "packet-projection"
        trace["tool_trace"].extend(rows)
        self.assertEqual(runtime.trace_errors(trace), [])
        changed = json.loads(json.dumps(trace))
        leaked = json.loads(changed["tool_trace"][-1]["output"][0]["text"])
        leaked["identity"]["leaked"] = str(self.root / "runs" / "secret")
        changed["tool_trace"][-1]["output"][0]["text"] = json.dumps(leaked)
        self.assertIn("forbidden_context_reference:archived_artifact", runtime.trace_errors(changed))
        changed = json.loads(json.dumps(trace))
        changed["tool_trace"][-2]["input"] += ' await tools.exec_command({"cmd":"cat .thoughts/ITEM-1/runs/prior/secret.md"});'
        self.assertIn("forbidden_context_reference:archived_artifact", runtime.trace_errors(changed))
        changed = json.loads(json.dumps(trace))
        leaked = json.loads(changed["tool_trace"][-1]["output"][0]["text"])
        leaked["reentry"]["Prior artifacts"] = str(self.root / "runs" / "secret")
        changed["tool_trace"][-1]["output"][0]["text"] = json.dumps(leaked)
        self.assertIn("forbidden_context_reference:archived_artifact", runtime.trace_errors(changed))

    def test_python_packet_projection_with_native_warning_keeps_archive_guard(self):
        trace = self.instruction_read_trace()
        packet_path = self.root / "finalization_packet.json"
        packet = json.loads(packet_path.read_text())
        packet["reentry"] = {"Prior artifacts": str(self.root / "runs" / "prior")}
        packet_path.write_text(json.dumps(packet))
        program = (f'import json; p={str(packet_path)!r}; x=json.load(open(p)); '
                   'print(json.dumps({"identity":x.get("identity"),"reentry":x.get("reentry")}, indent=2))')
        command = "python3 -c " + shlex.quote(program)
        call = 'const r = await tools.exec_command(' + json.dumps({"cmd": command}) + '); text(r.output);'
        warning = "WARNING: proceeding, even though we could not create PATH aliases: Operation not permitted (os error 1)\n"
        projected = {key: packet.get(key) for key in ("identity", "reentry")}
        rows = self.paired(call, [{"type": "input_text", "text": warning + json.dumps(projected)}])
        rows[0]["call_id"] = rows[1]["call_id"] = "python-projection"
        trace["tool_trace"].extend(rows)
        self.assertEqual(runtime.trace_errors(trace), [])
        changed = json.loads(json.dumps(trace))
        changed["tool_trace"][-2]["input"] += ' await tools.exec_command({"cmd":"cat .thoughts/ITEM-1/runs/prior/secret"});'
        self.assertIn("forbidden_context_reference:archived_artifact", runtime.trace_errors(changed))
        changed = json.loads(json.dumps(trace))
        changed["tool_trace"][-1]["output"][0]["text"] += "\n" + str(self.root / "runs" / "secret")
        self.assertIn("forbidden_context_reference:archived_artifact", runtime.trace_errors(changed))
        changed = json.loads(json.dumps(trace))
        changed["tool_trace"][-2]["input"] = changed["tool_trace"][-2]["input"].replace("import json;", "import json; open('/tmp/secret').read();")
        self.assertIn("forbidden_context_reference:archived_artifact", runtime.trace_errors(changed))

    def test_exact_current_packet_output_in_mixed_call_keeps_archive_access_guard(self):
        trace = self.instruction_read_trace()
        packet_path = self.root / "finalization_packet.json"
        packet = json.loads(packet_path.read_text())
        packet["reentry"] = {"Prior artifacts": str(self.root / "runs" / "prior")}
        packet_path.write_text(json.dumps(packet))
        inputs = self.root / "run_inputs.json"
        inputs.write_text('{"inputs": []}\n')
        source = ('text(await tools.exec_command(' + json.dumps({"cmd": "cat " + str(inputs) + " " + str(packet_path)})
                  + ')); text(await tools.exec_command({"cmd":"git status --short"}));')
        output = [{"type": "input_text", "text": json.dumps({"exit_code": 0,
                   "output": inputs.read_text() + packet_path.read_text()})},
                  {"type": "input_text", "text": json.dumps({"exit_code": 0, "output": "clean"})}]
        trace["tool_trace"].extend(self.paired(source, output))
        self.assertEqual(runtime.trace_errors(trace), [])
        altered = json.loads(json.dumps(trace))
        result = json.loads(altered["tool_trace"][-1]["output"][0]["text"])
        result["output"] += "\n" + str(self.root / "runs" / "prior" / "secret.md")
        altered["tool_trace"][-1]["output"][0]["text"] = json.dumps(result)
        self.assertIn("forbidden_context_reference:archived_artifact", runtime.trace_errors(altered))
        altered = json.loads(json.dumps(trace))
        altered["tool_trace"][-2]["input"] += ' text(await tools.exec_command({"cmd":"cat .thoughts/ITEM-1/runs/prior/secret.md"}));'
        self.assertIn("forbidden_context_reference:archived_artifact", runtime.trace_errors(altered))

    def test_python_ancestor_checks_allow_only_literal_instruction_reads(self):
        paths = [self.repository / "AGENTS.md", self.root.parent / "AGENTS.md", self.root / "AGENTS.md"]
        policy = "Do not read .thoughts/ITEM-1/runs/prior/notes.md.\n"
        paths[1].write_text(policy)
        program = ("from pathlib import Path\nfor p in [" + ", ".join(f"Path({str(p)!r})" for p in paths) + "]:\n"
                   "    print(f'--- {p} exists={p.is_file()}')\n    if p.is_file(): print(p.read_text())")
        command = "python3 - <<'PY'\n" + program + "\nPY"
        output = "".join(f"--- {p} exists={p.is_file()}\n" + (p.read_text() + "\n" if p.is_file() else "") for p in paths)
        call = lambda cmd: 'await tools.exec_command(' + json.dumps({"cmd": cmd, "workdir": str(self.repository)}) + ')'
        trace = {"tool_trace": self.paired(call(command), output)}
        self.assertEqual(runtime.context_trace_errors(trace, artifact_root=self.root), [])
        for unsafe in (command + "\ncat .thoughts/ITEM-1/runs/prior/notes.md",
                       command.replace("p.read_text()", "p.write_text('changed')"),
                       command.replace(str(paths[1]), str(self.root / "runs/prior/AGENTS.md")),
                       command.replace(str(paths[1]), str(self.root.parent / "OTHER/AGENTS.md")),
                       command.replace("\nPY", "\nprint(open('.thoughts/ITEM-1/runs/prior/notes.md').read())\nPY")):
            with self.subTest(command=unsafe):
                errors = runtime.context_trace_errors({"tool_trace": self.paired(call(unsafe), "")}, artifact_root=self.root)
                self.assertIn("forbidden_context_reference:archived_artifact", errors)
        paths[1].unlink()
        archived = self.root / "runs/prior/notes.md"
        archived.parent.mkdir(parents=True)
        archived.write_text("old analysis")
        paths[1].symlink_to(archived)
        self.assertIn("forbidden_context_reference:archived_artifact", runtime.context_trace_errors(
            {"tool_trace": self.paired(call(command), "")}, artifact_root=self.root))

    def test_ancestor_filename_probe_is_not_an_archive_read(self):
        for directory in ("", str(self.repository) + "/"):
            trace = self.instruction_read_trace()
            command = (f'for f in {directory}AGENTS.md {directory}.thoughts/AGENTS.md '
                       f'{directory}.thoughts/ITEM-1/AGENTS.md; do if [ -f "$f" ]; '
                       'then printf "%s\\n" "$f"; fi; done')
            call = 'await tools.exec_command(' + json.dumps({"cmd": command, "workdir": str(self.repository)}) + ')'
            rows = self.paired(call, directory + '.thoughts/AGENTS.md')
            rows[0]["call_id"] = rows[1]["call_id"] = "probe"
            self.assertEqual(runtime._ancestor_instruction_reads(rows[0], self.root), [])
            self.assertTrue(runtime._ancestor_instruction_reads(rows[0], self.root, include_probes=True))
            trace["tool_trace"].extend(rows)
            self.assertEqual(runtime.trace_errors(trace), [])

    def test_echo_ancestor_probe_with_literal_quotes_is_not_an_archive_read(self):
        for condition, output in (("test -f $p", "echo $p"),
                                  (r'test -f \"$p\"', r'echo \"$p\"')):
            trace = self.instruction_read_trace()
            command = ('for p in AGENTS.md .thoughts/AGENTS.md .thoughts/ITEM-1/AGENTS.md; '
                       f'do if {condition}; then {output}; fi; done')
            call = 'text(await tools.exec_command(' + json.dumps({"cmd": command,
                "workdir": str(self.repository)}) + '));'
            trace["tool_trace"].extend(self.paired(call, ""))
            self.assertEqual(runtime._ancestor_instruction_reads(trace["tool_trace"][-2], self.root), [])
            self.assertEqual(runtime.trace_errors(trace), [])
            trace["tool_trace"][-2]["input"] = call.replace('fi; done',
                'fi; done; cat .thoughts/OTHER/notes.md')
            self.assertIn("forbidden_context_reference:archived_artifact", runtime.trace_errors(trace))

    def test_bash_ancestor_probe_keeps_archive_restrictions(self):
        trace = self.instruction_read_trace()
        command = ('for f in .thoughts/AGENTS.md .thoughts/ITEM-1/AGENTS.md; '
                   'do if [[ -f "$f" ]]; then printf \'%s\\n\' "$f"; fi; done')
        call = 'await tools.exec_command(' + json.dumps({"cmd": command, "workdir": str(self.repository)}) + ')'
        trace["tool_trace"].extend(self.paired(call, ""))
        self.assertEqual(runtime.trace_errors(trace), [])
        trace["tool_trace"][-2]["input"] = call.replace('fi; done',
            'fi; done; cat .thoughts/ITEM-1/runs/prior/notes.md')
        self.assertIn("forbidden_context_reference:archived_artifact", runtime.trace_errors(trace))

    def test_negated_instruction_probe_keeps_archive_restrictions(self):
        trace = self.instruction_read_trace()
        command = ('for f in .thoughts/AGENTS.md .thoughts/ITEM-1/AGENTS.md; '
                   'do test ! -f "$f" || printf \'%s\\n\' "$f"; done')
        call = 'await tools.exec_command(' + json.dumps({"cmd": command, "workdir": str(self.repository)}) + ')'
        trace["tool_trace"].extend(self.paired(call, ""))
        self.assertEqual(runtime.trace_errors(trace), [])
        trace["tool_trace"][-2]["input"] = call.replace('done', 'done; cat .thoughts/ITEM-1/runs/prior/notes.md')
        self.assertIn("forbidden_context_reference:archived_artifact", runtime.trace_errors(trace))

    def test_ancestor_instructions_are_reads_not_historical_analysis(self):
        for command in (
            'for p in .thoughts/AGENTS.md .thoughts/ITEM-1/AGENTS.md; do if test -f "$p"; then printf \'FOUND %s\\n\' "$p"; cat "$p"; fi; done',
            'for p in .thoughts/AGENTS.md .thoughts/ITEM-1/AGENTS.md; do if test -f "$p"; then echo "Checking $p"; cat "$p"; fi; done',
            'cat AGENTS.md; for p in .thoughts/AGENTS.md .thoughts/ITEM-1/AGENTS.md; do if [ -f "$p" ]; then cat "$p"; fi; done; python3 normalizer.py --help',
            'cat AGENTS.md\ncat .thoughts/AGENTS.md; cat .thoughts/ITEM-1/AGENTS.md',
            'cat AGENTS.md; sed -n "1,20p" .thoughts/AGENTS.md',
            'cat .thoughts/AGENTS.md',
            'cat AGENTS.md .thoughts/AGENTS.md .thoughts/ITEM-1/AGENTS.md 2>/dev/null; cat .thoughts/ITEM-1/finalization_packet.json',
            'cat .thoughts/AGENTS.md 2> /dev/null',
            'for p in AGENTS.md .thoughts/AGENTS.md .thoughts/ITEM-1/AGENTS.md; do\nif [ -f "$p" ]; then\ncat "$p";\nfi;\ndone',
            'for p in AGENTS.md .thoughts/AGENTS.md .thoughts/ITEM-1/AGENTS.md; do if test -f "$p"; then cat "$p"; fi; done\nif test -f .thoughts/ITEM-1/fix_design_result.json; then cat .thoughts/ITEM-1/fix_design_result.json; fi',
            'for p in AGENTS.md .thoughts/AGENTS.md .thoughts/ITEM-1/AGENTS.md; do if [ -f "$p" ]; then cat "$p"; fi; done\npython3 - <<\'PY\'\nprint("current evidence")\nPY',
            'for f in .thoughts/AGENTS.md .thoughts/ITEM-1/AGENTS.md; do if [ -f "$f" ]; then printf \'\\n--- %s ---\\n\' "$f"; cat "$f"; fi; done; if [ -e .thoughts/ITEM-1/normalized_evidence.md ]; then echo yes; fi',
            'for p in AGENTS.md .thoughts/AGENTS.md .thoughts/ITEM-1/AGENTS.md; do if [ -f "$p" ]; then echo "--- $p"; cat "$p"; fi; done\npython3 - <<"PY"\nprint("current evidence")\nPY',
            'for f in .thoughts/AGENTS.md .thoughts/ITEM-1/AGENTS.md; do if test -f "$f"; then echo "--- $f"; cat "$f"; fi; done; if test -e .thoughts/ITEM-1/evidence.md; then echo yes; fi',
        ):
            with self.subTest(command=command):
                trace = self.instruction_read_trace()
                call = 'const r = await tools.exec_command(' + json.dumps({"cmd": command, "workdir": str(self.repository)}) + '); text(r.output);'
                rows = self.paired(call, '--- .thoughts/AGENTS.md')
                rows[0]["call_id"] = rows[1]["call_id"] = "ancestor"
                trace["tool_trace"].extend(rows)
                self.assertEqual(runtime.trace_errors(trace), [])

    def test_instruction_exception_does_not_allow_writes_or_other_work_items(self):
        for command in (
            'for f in .thoughts/AGENTS.md; do if [ -f "$f" ]; then printf "%n" "$f"; fi; done',
            'for f in .thoughts/OTHER/AGENTS.md; do if [ -f "$f" ]; then printf "%s\\n" "$f"; fi; done',
            'for f in .thoughts/AGENTS.md; do if [ -f "$f" ]; then printf "%s\\n" "$f"; fi; done; cat .thoughts/ITEM-1/runs/prior/notes.md',
            'for p in .thoughts/AGENTS.md; do if test -f "$p"; then printf -v p changed; cat "$p"; fi; done',
            'for p in .thoughts/AGENTS.md; do if test -f "$p"; then printf x; p=changed; cat "$p"; fi; done',
            'for p in .thoughts/AGENTS.md; do if test -f "$p"; then printf "%n" p; cat "$p"; fi; done',
            'cat AGENTS.md; for p in .thoughts/AGENTS.md; do if [ -f "$p" ]; then cat "$p"; fi; done; cat .thoughts/ITEM-1/runs/prior/notes.md',
            'cat AGENTS.md; for p in .thoughts/AGENTS.md; do if [ -f "$p" ]; then cat "$p"; fi; done; echo changed > .thoughts/AGENTS.md',
            'cat AGENTS.md; echo "for p in .thoughts/AGENTS.md; do if [ -f \"$p\" ]; then cat \"$p\"; fi; done"; cat .thoughts/ITEM-1/runs/prior/notes.md',
            'cd other; cat .thoughts/AGENTS.md',
            'cat .thoughts/OTHER/AGENTS.md',
            'cat .thoughts/ITEM-1/runs/prior/AGENTS.md',
            'echo changed > .thoughts/AGENTS.md',
            'cat .thoughts/AGENTS.md 2>.thoughts/OTHER/log.txt',
            'cat .thoughts/AGENTS.md 2>/dev/null; cat .thoughts/ITEM-1/runs/prior/notes.md',
            'for p in .thoughts/AGENTS.md; do if test -f "$p"; then cat "$p"; fi; done; cat .thoughts/ITEM-1/runs/prior/notes.md',
            'for p in .thoughts/AGENTS.md; do if test -f "$p"; then cat "$p"; fi; done; echo changed > .thoughts/AGENTS.md',
            'for f in .thoughts/AGENTS.md; do if test -f "$f"; then echo "--- $f"; cat "$f"; fi; done; echo changed > .thoughts/AGENTS.md',
        ):
            with self.subTest(command=command):
                trace = self.instruction_read_trace()
                trace["tool_trace"].append({"type": "custom_tool_call", "input":
                    'await tools.exec_command(' + json.dumps({"cmd": command, "workdir": str(self.repository)}) + ')'})
                self.assertIn("forbidden_context_reference:archived_artifact", runtime.trace_errors(trace))

    def test_audit_diagnostics_are_metadata_but_do_not_hide_actual_reads(self):
        trace = self.instruction_read_trace()
        reference = ".thoughts/ITEM-1/runs/prior/notes.md"
        trace["audit"] = {"context_violations": [{"reference": reference}]}
        self.assertEqual(runtime.context_trace_errors(trace), [])
        trace["tool_trace"].append({"type": "custom_tool_call", "input":
            'await tools.exec_command(' + json.dumps({"cmd": "cat " + reference}) + ')'})
        self.assertIn("forbidden_context_reference:archived_artifact", runtime.context_trace_errors(trace))

    def test_ancestor_instruction_symlink_cannot_reach_archived_analysis(self):
        archive = self.root / "runs/prior/notes.md"
        archive.parent.mkdir(parents=True)
        archive.write_text("Archived analysis")
        (self.root.parent / "AGENTS.md").symlink_to(archive)
        trace = self.instruction_read_trace()
        trace["tool_trace"].append({"type": "custom_tool_call", "input":
            'await tools.exec_command(' + json.dumps({"cmd": "cat .thoughts/AGENTS.md", "workdir": str(self.repository)}) + ')'})
        self.assertIn("forbidden_context_reference:archived_artifact", runtime.trace_errors(trace))

    def test_authenticated_ancestor_policy_text_is_not_an_archive_read(self):
        policy = "# Instructions\nDo not read .thoughts/ITEM-1/runs/prior/notes.md.\n"
        (self.root.parent / "AGENTS.md").write_text(policy)
        trace = self.instruction_read_trace()
        call = 'await tools.exec_command(' + json.dumps({"cmd": 'for p in .thoughts/AGENTS.md; do if test -f "$p"; then cat "$p"; fi; done',
                                                        "workdir": str(self.repository)}) + ')'
        rows = self.paired(call, policy)
        rows[0]["call_id"] = rows[1]["call_id"] = "policy"
        trace["tool_trace"].extend(rows)
        self.assertEqual(runtime.context_trace_errors(trace), [])
        rows[1]["output"] += "\n.thoughts/ITEM-1/runs/prior/leaked.md"
        self.assertIn("forbidden_context_reference:archived_artifact", runtime.context_trace_errors(trace))
        rows[1]["output"] = policy
        trace["tool_trace"].append({"type": "custom_tool_call", "input":
            'await tools.exec_command({cmd:"cat .thoughts/ITEM-1/runs/prior/notes.md"})'})
        self.assertIn("forbidden_context_reference:archived_artifact", runtime.context_trace_errors(trace))

    def test_sentry_preparation_declares_the_shared_collector(self):
        run = fixtures.prepare.prepare_run(self.repository, "SENTRY-1", "sentry_issue_remediation", None, False,
                                           input_manifest=self.inputs)
        self.assertEqual(Path(run["runtime_evidence"]["collector"]).name, "worker_runtime_evidence.py")
        self.assertEqual(Path(run["runtime_evidence"]["ledger"]), Path(run["artifact_root"]) / "runtime_dispatches.json")

    def test_sentry_guard_provider_export_and_fan_in_without_injected_metadata(self):
        self.check_guard_provider_export("sentry_issue_remediation", "sentry_current_state_investigator")

    def test_techops_guard_provider_export_and_fan_in_without_injected_metadata(self):
        self.check_guard_provider_export("techops_issue_remediation", "current_state_investigator")

    def check_guard_provider_export(self, playbook, role):
        from datetime import datetime, timedelta
        run = fixtures.prepare.prepare_run(self.repository, "ITEM-2", playbook, None, False,
                                           input_manifest=self.inputs)
        root = Path(run["artifact_root"])
        bundle = run["activation_packet_bundle"]
        assignment = root / "assignment.json"
        assignment.write_text(json.dumps({"objective": "Collect the supplied occurrence", "input_paths": []}))
        dispatch = root / "activation_evidence_topology.txt"
        guarded = subprocess.run([sys.executable, run["worker_runtime_guard"], "--activation-packet-bundle", bundle["path"],
            "--expected-agent", role, "--expected-bundle-sha256", bundle["sha256"], "--assignment", str(assignment),
            "--dispatch-file", str(dispatch)], capture_output=True, text=True)
        self.assertEqual(guarded.returncode, 0, guarded.stdout + guarded.stderr)
        start = datetime.fromisoformat(run["runtime_evidence"]["run_started_at"].replace("Z", "+00:00"))
        time = lambda seconds: (start + timedelta(seconds=seconds)).isoformat()
        child = "00000000-0000-0000-0000-000000000002"
        handle = "/root/evidence_topology"
        parent = self.repository / "sentry-parent.jsonl"
        parent.write_text("\n".join(json.dumps(row) for row in [
            {"timestamp": time(0), "type": "session_meta", "payload": {"id": SOURCE}},
            {"timestamp": time(1), "type": "response_item", "payload": {"type": "function_call", "namespace": "collaboration", "name": "spawn_agent",
             "arguments": json.dumps({"task_name": "evidence_topology", "agent_type": role, "message": "opaque",
                 "model": "gpt-6-luna", "reasoning_effort": "high", "fork_turns": "none"})}},
            {"timestamp": time(1), "type": "event_msg", "payload": {"item": {"type": "SubAgentActivity",
             "kind": "started", "agent_path": handle, "agent_thread_id": child}}},
        ]) + "\n")
        session = self.repository / "sentry-child.jsonl"
        session.write_text("\n".join(json.dumps(row) for row in [
            {"timestamp": time(1), "type": "session_meta", "payload": {"id": child}},
            {"timestamp": time(2), "type": "response_item", "payload": {"type": "custom_tool_call", "name": "exec",
             "call_id": "instructions", "input": 'const r = await tools.exec_command(' + json.dumps({
                 "cmd": "sha256sum " + str(dispatch) + " && cat " + str(dispatch)}) + '); text(r.output);'}},
            {"timestamp": time(3), "type": "response_item", "payload": {"type": "custom_tool_call_output",
             "call_id": "instructions", "output": [{"type": "input_text", "text": dispatch.read_text()}]}},
            {"timestamp": time(4), "type": "response_item", "payload": {"type": "custom_tool_call", "name": "exec",
             "call_id": "listing", "input": 'const r = await tools.exec_command(' + json.dumps({
                 "cmd": "cat .thoughts/ITEM-2/run_inputs.json && printf '\\n--- directory files ---\\n' && rg --files .thoughts/ITEM-2",
                 "workdir": str(self.repository)}) + '); text(r.output);'}},
            {"timestamp": time(5), "type": "response_item", "payload": {"type": "custom_tool_call_output",
             "call_id": "listing", "output": [{"type": "input_text", "text":
                 (root / "run_inputs.json").read_text() + "\n--- directory files ---\n.thoughts/ITEM-2/runs/previous/work_record.md"}]}},
            {"timestamp": time(6), "type": "response_item", "payload": {"type": "custom_tool_call", "name": "exec",
             "call_id": "ancestors", "input": 'const r = await tools.exec_command(' + json.dumps({
                 "cmd": 'for p in .thoughts/AGENTS.md .thoughts/ITEM-2/AGENTS.md; do if test -f "$p"; then printf \'FOUND %s\\n\' "$p"; cat "$p"; fi; done',
                 "workdir": str(self.repository)}) + '); text(r.output);'}},
            {"timestamp": time(7), "type": "response_item", "payload": {"type": "custom_tool_call_output",
             "call_id": "ancestors", "output": [{"type": "input_text", "text": "No additional AGENTS.md files."}]}},
            {"timestamp": time(8), "type": "turn_context", "payload": {"turn_id": "00000000-0000-0000-0000-000000000104",
             "model": "gpt-6-luna", "effort": "high"}},
        ]) + "\n")
        contract = run["worker_contracts"].get(role, {})
        if contract.get("result_hash_required"):
            worker_fields = contract.get("result_fields", {}).get("worker_results") or json.loads(
                finalizer.PACKET_TEMPLATE.read_text())["worker_results"][0]
            response_result = {"run_id": run["run_id"], "worker_result": {
                **dict.fromkeys(worker_fields, "Observed"),
                "Worker": contract.get("worker_id", contract.get("worker")), "Outcome": "blocked"},
                "evidence": [], "claims": [], "decisions": [], "actions": []}
            if contract.get("planning_disposition_required"):
                response_result.update(plan_readiness="awaiting_input", implementation_plan_action="omit")
            response = {"output": "Current worker response", "result": response_result}
            if contract.get("asset_inventory"):
                response["asset_manifest"] = {}
            with session.open("a") as stream:
                stream.write(json.dumps({"timestamp": time(9), "type": "response_item", "payload": {
                    "type": "message", "role": "assistant", "phase": "final_answer",
                    "content": [{"type": "output_text", "text": json.dumps(response)}]}}) + "\n")
        observation = root / "status.json"
        observation.write_text(json.dumps({"Provider handle": handle, "Thread ID": child, "Provider status": "idle",
            "Observed at": time(30), "Status source": "read_thread", "Latest turn started at": time(8),
            "Latest turn completed at": time(20), "Latest turn status": "completed", "Thread status": "idle"}))
        trace_path = root / "trace.json"
        result = subprocess.run([sys.executable, run["runtime_evidence"]["collector"], "--provider-session", str(parent),
            "--parent-thread-id", SOURCE, "--started-at", time(0), "--ledger", run["runtime_evidence"]["ledger"],
            "--worker-session", str(session), "--observation", str(observation), "--agent", role,
            "--trace", str(trace_path)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        exported = json.loads(trace_path.read_text())
        self.assertEqual(exported["audit"], {"status": "passed", "errors": []})
        self.assertNotIn("activation_packet_delivered", exported["spawn"])
        self.assertEqual(runtime.trace_errors(exported, require_freshness=True), [])

    def test_computed_tool_access_cannot_get_the_source_output_exception(self):
        trace = self.dispatch_trace(["codex://threads/" + SOURCE])
        code = ('await tools.mcp__codex_app__read_thread({threadId:"' + SOURCE + '"}); '
                'await tools["exec_command"]({cmd:"cat /repo/.codex/memories/MEMORY.md"})')
        trace["tool_trace"] = self.paired(code, "/repo/.codex/memories/MEMORY.md")
        self.assertTrue(any(error.startswith("forbidden_context_reference:memory_")
                            for error in runtime.context_trace_errors(trace)))

    def test_plain_parent_launch_retains_the_guarded_dispatch_identity(self):
        trace = self.dispatch_trace([])
        path = trace["spawn"]["dispatch_file"]
        packet = json.loads((self.root / "worker_activation_packets.json").read_text())["packets"][
            "current_state_investigator"]
        notice = runtime.dispatch_message(packet, Path(path).read_text(), Path(path))
        source = self.repository / "parent.jsonl"
        rows = [
            {"timestamp": "2026-10-13T01:00:00Z", "type": "session_meta", "payload": {"id": SOURCE}},
            {"timestamp": "2026-10-13T01:00:01Z", "type": "response_item", "payload": {
                "type": "function_call", "namespace": "collaboration", "name": "spawn_agent",
                "arguments": json.dumps({"task_name": "context", "message": notice})}},
            {"timestamp": "2026-10-13T01:00:02Z", "type": "event_msg", "payload": {"item": {
                "type": "SubAgentActivity", "kind": "started", "agent_path": "/root/context",
                "agent_thread_id": "00000000-0000-0000-0000-000000000002"}}},
        ]
        source.write_text("".join(json.dumps(row) + "\n" for row in rows))
        ledger = read_runtime_events(source, SOURCE, rows[0]["timestamp"])
        self.assertEqual(ledger["events"][0]["Dispatch file"], path)
        self.assertEqual(ledger["events"][0]["Dispatch SHA256"], trace["spawn"]["dispatch_file_sha256"])

    def test_unmatched_and_unknown_outputs_remain_audited(self):
        trace = self.dispatch_trace(["codex://threads/" + SOURCE])
        trace["tool_trace"] = self.paired('text("tools.mcp__codex_app__read_thread({threadId:\\"' + SOURCE + '\\"})")',
                                          "/repo/.codex/memories/MEMORY.md")
        self.assertTrue(any(error.startswith("forbidden_context_reference:memory_")
                            for error in runtime.context_trace_errors(trace)))

        trace["tool_trace"][0]["input"] = 'await tools.mcp__codex_app__read_thread({threadId:"' + SOURCE + '"})'
        trace["tool_trace"][1]["call_id"] = "unmatched"
        self.assertTrue(any(error.startswith("forbidden_context_reference:memory_")
                            for error in runtime.context_trace_errors(trace)))

    def test_continuity_sources_do_not_require_a_product_asset_inventory(self):
        inputs = {"HIST-001": {"Input or artifact": "ITEM-1 prior workflow history",
                              "Source or path": "codex://threads/" + SOURCE,
                              "Authority": "User-supplied context", "Classification": "decision continuity"}}
        self.assertEqual(assets._expected_asset_input_ids(inputs), set())
        self.assertEqual(assets._expected_jira_input_ids(inputs, "ITEM-1"), set())
        inputs["HIST-001"]["Asset source"] = True
        self.assertEqual(assets._expected_asset_input_ids(inputs), {"HIST-001"})

    def test_partial_draft_disposition_is_merged_and_required_at_handoff(self):
        self.result["worker_result"]["Worker"] = "feature-design"
        self.result["evidence"] = []
        self.result.update({"plan_readiness": "awaiting_input", "implementation_plan_action": "create_draft"})
        trace, _ = stage_worker_response(self.run, "solution_architect", self.result)
        merge_result(self.packet_path, "solution_architect", trace=trace)
        packet = json.loads(self.packet_path.read_text())
        self.assertEqual(packet["planning_disposition"], {
            "plan_readiness": "awaiting_input", "implementation_plan_action": "create_draft"})
        packet["identity"].update({"State": "awaiting_input", "Requested profile": "standard",
                                   "Activated profile": "standard", "Executed profile": "standard"})
        self.assertIn("feature_partial_draft_plan_required", finalizer._feature_delivery_packet_contract_errors(packet))
        self.result["implementation_plan_action"] = "create"
        saved = self.packet_path.read_bytes()
        with self.assertRaisesRegex(ValueError, "feature_planning_disposition_invalid"):
            trace, _ = stage_worker_response(self.run, "solution_architect", self.result)
            merge_result(self.packet_path, "solution_architect", trace=trace)
        self.assertEqual(self.packet_path.read_bytes(), saved)

    def test_rejected_result_requires_one_combined_corrected_activation(self):
        self.artifacts = self.root
        path, trace = activation_fixtures.ActivationDelivery.rejected_trace(self)
        (self.root / "runtime_dispatches.json").write_text(json.dumps({"rejected_results": {
            "current_state_investigator": {"run_id": self.run["run_id"], "trace": str(path),
                                          "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}}}))
        assignment = self.repository / "corrected_assignment.json"
        assignment.write_text(json.dumps({"objective": "Repair this rejected contribution", "input_paths": []}))
        bundle = self.run["activation_packet_bundle"]
        dispatch = self.root / "activation_corrected.txt"
        command = [sys.executable, str(runtime.ROOT / "scripts/validate_worker_runtime.py"),
            "--activation-packet-bundle", bundle["path"], "--expected-agent", "current_state_investigator",
            "--expected-bundle-sha256", bundle["sha256"], "--assignment", str(assignment),
            "--dispatch-file", str(dispatch)]
        blocked = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(blocked.returncode, 2, blocked.stdout + blocked.stderr)
        self.assertFalse(dispatch.exists())
        recovery = ["--rejected-trace", str(path), "--provider-handle", activation_fixtures.HANDLE,
                    "--last-dispatch-at", activation_fixtures.DISPATCH, "--provider-status", "completed"]
        wrong = self.repository / "wrong_notice.txt"
        wrong.write_text("Incomplete launch")
        mismatch = subprocess.run(command + recovery + ["--activation-message", str(wrong)],
                                  capture_output=True, text=True)
        self.assertEqual(mismatch.returncode, 2)
        self.assertFalse(dispatch.exists())
        self.assertNotIn("activation_repairs", json.loads(self.packet_path.read_text()))
        allowed = subprocess.run(command + recovery, capture_output=True, text=True)
        self.assertEqual(allowed.returncode, 0, allowed.stdout + allowed.stderr)
        receipt = json.loads(allowed.stdout)
        self.assertEqual(receipt["recovery_authorization"]["Corrected dispatch SHA256"],
                         hashlib.sha256(dispatch.read_bytes()).hexdigest())
        again = subprocess.run(command + recovery, capture_output=True, text=True)
        self.assertEqual(again.returncode, 2)
        self.assertIn("activation_repair_limit_reached", again.stdout)

    def test_coordinator_reported_failure_does_not_claim_a_validator_found_it(self):
        result = subprocess.run([sys.executable, str(finalizer.ROOT / "scripts/finalize_work_record.py"),
            "--packet", str(self.packet_path), "--workflow-failure", "activation_sequence_nonconformant"],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertTrue(result.stdout.startswith("Workflow-framework handoff: failed; control failure reported by Coordinator"))
        receipt = json.loads((self.root / "finalization_failure.json").read_text())
        self.assertFalse(receipt["validation_performed"])
        self.assertEqual(receipt["reported_by"], "Coordinator")
