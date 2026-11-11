"""Recorded provider call shapes: historical data is not current tool activity."""

import json
import pprint
import hashlib
import shlex
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

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

    def test_only_source_instruction_probe_does_not_allow_artifact_probes_or_archive_reads(self):
        instruction = self.repository / "AGENTS.md"
        safe = f"if test -f {instruction}; then cat {instruction}; else printf 'absent\\n'; fi"
        def errors(command):
            return runtime.context_trace_errors({"tool_trace": [{"type": "function_call", "name": "exec_command",
                "arguments": {"cmd": command, "workdir": str(self.repository)}}]}, artifact_root=self.root)
        self.assertEqual(errors(safe), [])
        artifact_instruction = self.root.parent / "AGENTS.md"
        artifact_probe = f"if test -f {artifact_instruction}; then cat {artifact_instruction}; else printf 'absent\\n'; fi"
        self.assertIn("forbidden_context_reference:archived_artifact", errors(artifact_probe))
        archive = self.root / "runs" / "prior" / "notes.md"
        for command in (safe + "; cat " + str(archive),
                        safe.replace("then cat " + str(instruction), "then cat " + str(archive)),
                        safe.replace("printf 'absent\\n'", "cat " + str(archive))):
            with self.subTest(command=command):
                self.assertIn("forbidden_context_reference:archived_artifact", errors(command))

    def test_source_instruction_presence_check_does_not_read_archives(self):
        instructions = (self.repository / "AGENTS.md",)
        paths = " ".join(shlex.quote(str(path)) for path in instructions)
        command = (f'for path in {paths}; do if [ -f "$path" ]; then printf \'FILE %s\\n\' "$path"; '
                   'else printf \'MISSING %s\\n\' "$path"; fi; done')

        def errors(value):
            trace = {"tool_trace": [{"type": "function_call", "name": "exec_command",
                "arguments": {"cmd": value, "workdir": str(self.repository)}}]}
            return runtime.context_trace_errors(trace, artifact_root=self.root)

        self.assertEqual(errors(command), [])
        archive = self.root / "runs" / "prior" / "notes.md"
        self.assertIn("forbidden_context_reference:archived_artifact", errors(command + "; cat " + str(archive)))
        other = self.repository / "other" / "AGENTS.md"
        row = {"type": "function_call", "name": "exec_command", "arguments": {
            "cmd": command.replace(str(instructions[0]), str(other)), "workdir": str(self.repository)}}
        self.assertEqual(runtime._ancestor_instruction_reads(row, self.root, include_probes=True), [])

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
            self.assertEqual(parent_context_audit(source, artifact_root=self.root, input_paths=(approved,),
                                                  related_run_thread_ids=())["status"], "passed")
            self.assertIn("forbidden_context_reference:archived_artifact",
                          parent_context_audit(source, artifact_root=self.root, related_run_thread_ids=())["errors"])
            call["input"] += "await tools.exec_command({cmd:'cat /repo/.thoughts/OTHER/runs/old/analysis.md'});"
            source.write_text("".join(json.dumps(row) + "\n" for row in header + [{"type": "response_item", "payload": call}]))
            self.assertIn("forbidden_context_reference:archived_artifact",
                          parent_context_audit(source, artifact_root=self.root, input_paths=(approved,),
                                               related_run_thread_ids=())["errors"])

    def test_parent_patch_operations_are_parsed_without_treating_written_prose_as_reads(self):
        from scripts.provider_runtime import parent_context_audit
        source = self.repository / "parent.jsonl"
        header = [{"type": "session_meta", "payload": {"id": SOURCE}},
                  {"type": "turn_context", "payload": {"turn_id": "00000000-0000-0000-0000-000000000002"}}]
        patch = "*** Begin Patch\n*** Add File: " + str(self.root / "notes.md") + "\n+Do not read raw_memories.md or .thoughts/OLD/runs/analysis.md\n*** End Patch"
        for direct in (False, True):
            with self.subTest(direct=direct):
                call = {"type": "custom_tool_call", "name": "apply_patch" if direct else "exec",
                        "input": patch if direct else "text(await tools.apply_patch(" + json.dumps(patch) + "));"}
                source.write_text("".join(json.dumps(row) + "\n" for row in header + [{"type": "response_item", "payload": call}]))
                self.assertEqual(parent_context_audit(source, artifact_root=self.root,
                                                      related_run_thread_ids=())["status"], "passed")
                forbidden = dict(call)
                forbidden["input"] = forbidden["input"].replace(str(self.root / "notes.md"), str(self.root / "runs/old/notes.md"))
                source.write_text("".join(json.dumps(row) + "\n" for row in header + [{"type": "response_item", "payload": forbidden}]))
                self.assertIn("forbidden_context_reference:archived_artifact",
                              parent_context_audit(source, artifact_root=self.root,
                                                   related_run_thread_ids=())["errors"])
        call["input"] = "await tools.apply_patch(" + json.dumps(patch) + "); await tools.exec_command({cmd:'cat /repo/.codex/memories/raw_memories.md'});"
        call["name"] = "exec"
        source.write_text("".join(json.dumps(row) + "\n" for row in header + [{"type": "response_item", "payload": call}]))
        self.assertIn("forbidden_context_reference:memory_path",
                      parent_context_audit(source, artifact_root=self.root, related_run_thread_ids=())["errors"])

    def test_parent_allows_only_current_session_status_projection_reference(self):
        from scripts.provider_runtime import parent_context_audit
        source = self.repository / ".codex" / "sessions" / "current.jsonl"
        source.parent.mkdir(parents=True)
        header = [{"type": "session_meta", "payload": {"id": SOURCE}},
                  {"type": "turn_context", "payload": {"turn_id": "00000000-0000-0000-0000-000000000002"}}]
        script = Path(__file__).resolve().parents[1] / "scripts" / "prepare_run.py"
        command = shlex.join(["python3", str(script), "--status-projection", "--execution-repository",
                              str(self.repository), "--work-item", "ITEM-1", "--provider-session", str(source)])
        audit = lambda: parent_context_audit(source, artifact_root=self.root, related_run_thread_ids=())
        for flags in ((), ("--continuation",), ("--continuation", "--planning-recovery")):
            with self.subTest(flags=flags):
                invocation = command + " " + " ".join(flags)
                call = {"type": "custom_tool_call", "name": "exec", "input":
                        "const result = await tools.exec_command(" + json.dumps({"cmd": invocation}) + "); text(result.output);"}
                source.write_text("".join(json.dumps(row) + "\n" for row in header + [{"type": "response_item", "payload": call}]))
                self.assertEqual(audit()["status"], "passed")

                for invalid in (invocation.replace(str(source), str(source.parent / "prior.jsonl")),
                                invocation + "; cat " + shlex.quote(str(source)),
                                invocation + " --unsupported-option"):
                    call["input"] = "const result = await tools.exec_command(" + json.dumps({"cmd": invalid}) + "); text(result.output);"
                    source.write_text("".join(json.dumps(row) + "\n" for row in header + [{"type": "response_item", "payload": call}]))
                    self.assertIn("forbidden_context_reference:session_log", audit()["errors"])

        call["input"] = ("const result = await tools.exec_command(" + json.dumps({"cmd": command})
                         + "); text(result.output); await tools.exec_command(" + json.dumps({"cmd": "cat " + str(source)}) + ");")
        source.write_text("".join(json.dumps(row) + "\n" for row in header + [{"type": "response_item", "payload": call}]))
        self.assertIn("forbidden_context_reference:session_log", audit()["errors"])

    def test_parent_allows_assigned_source_ancestor_policy_but_rejects_extra_output(self):
        source = self.repository / "src" / "module" / "current.py"
        source.parent.mkdir(parents=True)
        source.write_text("current source\n")
        instructions = source.parent / "AGENTS.md"
        policy = ("Do not read /Users/example/.codex/memories/raw_memories.md or "
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
        quoted = json.dumps({"thread": {"turns": [{"command": "cat /repo/.codex/memories/raw_memories.md"}]}})
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

    def test_approval_justification_punctuation_does_not_change_command_paths(self):
        justification = 'Allow creating current-run artifacts inside ' + str(self.root) + '.'
        def audit(command, reason=justification):
            arguments = {'cmd': command, 'sandbox_permissions': 'require_escalated', 'justification': reason}
            rows = [
                {'type': 'function_call', 'name': 'exec_command', 'arguments': arguments},
                {'type': 'function_call', 'name': 'exec_command', 'arguments': json.dumps(arguments)},
                {'type': 'custom_tool_call', 'name': 'exec',
                 'input': 'const r=await tools.exec_command(' + json.dumps(arguments) + '); text(r.output);'},
            ]
            return [runtime.context_trace_errors({'tool_trace': [row]}, artifact_root=self.root) for row in rows]
        self.assertEqual(audit('cat ' + str(self.root / 'run_inputs.json')), [[], [], []])
        for command, reason in (
                ('cat ' + str(self.root) + '.', justification),
                ('cat ' + str(self.root / 'runs/prior/notes.md'), justification),
                (justification, justification),
                ('cat ' + str(self.root.parent / 'OTHER/runs/old.md'), justification)):
            for errors in audit(command, reason):
                self.assertIn('forbidden_context_reference:archived_artifact', errors)

    def test_approval_metadata_never_authorizes_or_counts_as_source_access(self):
        paths = ['/repo/.codex/sessions/old.jsonl', '/repo/.codex/memories/raw_memories.md',
                 '/repo/.thoughts/OTHER/runs/old/report.md']
        for target in paths:
            for punctuation in ('', '.', ':', ' (read permission requested)'):
                args = {'cmd': 'pwd', 'justification': 'Permission for ' + target + punctuation}
                rows = [
                    {'type': 'function_call', 'name': 'exec_command', 'arguments': args},
                    {'type': 'function_call', 'name': 'exec_command', 'arguments': json.dumps(args)},
                    {'type': 'custom_tool_call', 'name': 'exec',
                     'input': 'await tools.exec_command(' + json.dumps(args) + ')'},
                ]
                for row in rows:
                    with self.subTest(target=target, punctuation=punctuation, shape=row['type']):
                        self.assertEqual(runtime.context_trace_errors({'tool_trace': [row]}), [])
                args['cmd'] = 'cat ' + target
                self.assertTrue(runtime.context_trace_errors({'tool_trace': [rows[0]]}))
            self.assertTrue(runtime.context_trace_errors({'evidence': target}))

    def test_serialized_objective_punctuation_does_not_hide_executable_artifact_paths(self):
        objective = "Keep café artifacts inside " + str(self.root) + ". Do not read prior runs."
        body = ("import json\nfrom pathlib import Path\nr=Path(" + repr(str(self.root)) + ")\n"
                "a={'objective':" + repr(objective) + ", 'input_paths': []}\n"
                "(r/'assignment.json').write_text(json.dumps(a,indent=2))\n")
        command = "python3 - <<'PY'\n" + body + "PY"
        trace = {"tool_trace": self.paired('await tools.exec_command(' + json.dumps({"cmd": command}) + ')', "")}
        self.assertEqual(runtime.context_trace_errors(trace, artifact_root=self.root), [])
        native = {"tool_trace": [{"type": "function_call", "name": "exec_command", "call_id": "native",
                                  "arguments": {"cmd": command}}]}
        self.assertEqual(runtime.context_trace_errors(native, artifact_root=self.root), [])
        for extra in ("Path(" + repr(str(self.root) + ".") + ").read_text()\n",
                      "Path(" + repr(str(self.root) + ".") + ").write_text('bad')\n",
                      "exec(a['objective'])\n", "alias=a\n",
                      "json.dumps=lambda value: value\n",
                      "Path(" + repr(objective) + ").read_text()\n",
                      "sorted([a],key=eval)\n"):
            changed = {"tool_trace": self.paired('await tools.exec_command(' + json.dumps({
                "cmd": "python3 - <<'PY'\n" + body + extra + "PY"}) + ')', "")}
            with self.subTest(extra=extra):
                self.assertIn("forbidden_context_reference:archived_artifact",
                              runtime.context_trace_errors(changed, artifact_root=self.root))
        expanded = command.replace("<<'PY'", "<<PY").replace("Do not read prior runs.",
                   "$(cat " + str(self.root) + ". )")
        changed = {"tool_trace": self.paired('await tools.exec_command(' + json.dumps({"cmd": expanded}) + ')', "")}
        self.assertIn("forbidden_context_reference:archived_artifact",
                      runtime.context_trace_errors(changed, artifact_root=self.root))
        for forbidden in (str(self.root.parent / "OTHER") + ".", str(self.root) + "/runs/prior/notes.md"):
            changed = {"tool_trace": self.paired('await tools.exec_command(' + json.dumps({
                "cmd": command.replace(str(self.root) + ".", forbidden)}) + ')', "")}
            self.assertIn("forbidden_context_reference:archived_artifact",
                          runtime.context_trace_errors(changed, artifact_root=self.root))

    def test_quoted_json_assignment_objective_is_prose_not_a_path(self):
        assignment = self.root / 'assignment.json'
        objective = 'Keep artifacts under ' + str(self.root) + '. Continue.'
        def audit(body, suffix=''):
            cmd = 'cat > ' + shlex.quote(str(assignment)) + " <<'EOF'\n" + json.dumps(body) + '\nEOF' + suffix
            return runtime.context_trace_errors({'tool_trace': [{'type': 'function_call', 'name': 'exec_command',
                'arguments': {'cmd': cmd}}]}, artifact_root=self.root)
        self.assertEqual(audit({'objective': objective, 'input_paths': []}), [])
        self.assertIn('forbidden_context_reference:archived_artifact',
                      audit({'objective': objective, 'input_paths': [str(self.root) + '.']}))
        self.assertIn('forbidden_context_reference:archived_artifact',
                      audit({'objective': objective, 'input_paths': []}, '\ncat ' + str(self.root) + '.'))

    def test_quoted_assignment_text_is_data_but_its_paths_and_operations_are_audited(self):
        assignment = self.root / 'assignment.json'
        archive = str(self.root / 'runs' / 'previous' / 'result.json')
        session = '/Users/example/.codex/sessions/previous.jsonl'
        def audit(body, extra=''):
            command = ('cat > ' + shlex.quote(str(assignment)) + " <<'EOF'\n" + json.dumps(body)
                       + '\nEOF' + extra)
            return runtime.context_trace_errors({'tool_trace': [{'type': 'function_call', 'name': 'exec_command',
                'arguments': {'cmd': command}}]}, artifact_root=self.root)
        self.assertEqual(audit({'objective': 'Do not read ' + archive + ' or ' + session, 'input_paths': []}), [])
        self.assertIn('forbidden_context_reference:archived_artifact',
                      audit({'objective': 'Use these inputs', 'input_paths': [archive]}))
        self.assertIn('forbidden_context_reference:session_log',
                      audit({'objective': 'Use these inputs', 'input_paths': [session]}))
        self.assertIn('forbidden_context_reference:session_log',
                      audit({'objective': 'Do not read ' + session, 'input_paths': []}, '\ncat ' + session))

    def test_shared_objective_prose_is_allowed_only_when_used_as_serialized_data(self):
        prose = "Keep scratch inside " + str(self.root) + ". Use assigned inputs."
        body = ("import json\nfrom pathlib import Path\nr=Path(" + repr(str(self.root)) + ")\n"
                "common=" + repr(prose) + "\n"
                "(r/'review.json').write_text(json.dumps({'objective':'Review.'+common}))\n"
                "(r/'validate.json').write_text(json.dumps({'objective':common+' Validate.'}))\n")
        def audit(source):
            return runtime.context_trace_errors({"tool_trace": self.paired(
                'await tools.exec_command(' + json.dumps({"cmd": "python3 - <<'PY'\n" + source + "PY"}) + ')', "")},
                artifact_root=self.root)
        self.assertEqual(audit(body), [])
        for extra in ("Path(common).read_text()\n", "alias=common\n", "common='changed'\n",
                      "(r/'bad.json').write_text(json.dumps({'input_paths':[common]}))\n",
                      "(r/'bad.json').write_text(json.dumps({'objective':Path(common).read_text()}))\n"):
            with self.subTest(extra=extra):
                self.assertIn("forbidden_context_reference:archived_artifact", audit(body + extra))
        self.assertIn("forbidden_context_reference:archived_artifact",
                      audit(body.replace(str(self.root) + ".", str(self.root) + "/runs/prior/notes.md")))

    def test_python_packet_and_ancestor_instruction_checks_remain_read_only(self):
        targets = ["AGENTS.md"]
        body = ("import json\nfrom pathlib import Path\np=Path('.thoughts/ITEM-1/activation.txt')\n"
                "for line in p.read_text().splitlines():\n try:\n  d=json.loads(line)\n"
                "  print(list(d))\n except ValueError: pass\n"
                "for p in [" + ",".join("Path(" + repr(path) + ")" for path in targets) + "]:\n"
                " if p.exists(): print(p.read_text())")
        def audit(source):
            cmd = "python3 - <<'PY'\n" + source + "\nPY"
            return runtime.context_trace_errors({"tool_trace": self.paired(
                'await tools.exec_command(' + json.dumps({"cmd": cmd}) + ')', "")}, artifact_root=self.root)
        self.assertEqual(audit(body), [])
        for changed in (body + "\nPath('.thoughts/ITEM-1/runs/prior/notes.md').write_text('x')",
                        body + "\nPath('.thoughts/ITEM-1/runs/prior/notes.md').read_text()"):
            self.assertIn("forbidden_context_reference:archived_artifact", audit(changed))

    def test_bound_failure_reason_punctuation_is_not_an_artifact_operation(self):
        package = self.repository / "package"
        (self.root / "role_bindings.json").write_text(json.dumps({"framework_package": {"root": str(package)}}))
        reason = "Audit mentioned " + str(self.root) + ". No archive was read."
        command = shlex.join(["python3", str(package / "scripts/finalize_work_record.py"), "--packet",
                              str(self.root / "finalization_packet.json"), "--workflow-failure", reason])
        def trace(cmd):
            return {"tool_trace": self.paired('await tools.exec_command(' + json.dumps({"cmd": cmd}) + ')', "")}
        self.assertEqual(runtime.context_trace_errors(trace(command), artifact_root=self.root), [])
        for invalid in (command + "; cat " + str(self.root) + ".",
                        command[:command.index("--workflow-failure")] + '--workflow-failure "$(cat ' + str(self.root) + '. )"',
                        command.replace(str(package), str(self.repository / "other-package")),
                        command.replace(str(self.root / "finalization_packet.json"), str(self.root) + "."),
                        command.replace(str(self.root) + ". No", str(self.root) + "/runs/old. No")):
            self.assertIn("forbidden_context_reference:archived_artifact",
                          runtime.context_trace_errors(trace(invalid), artifact_root=self.root))

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
            trace = {"tool_trace": self.paired(code, "Current report\n/Users/example/.codex/memories/raw_memories.md")}
            self.assertIn("forbidden_context_reference:memory_path", runtime.context_trace_errors(trace))

    def test_memory_and_session_log_reads_require_exact_run_inputs(self):
        for target, error in (
            ("/repo/.codex/memories/raw_memories.md", "memory_path"),
            ("/repo/.codex/sessions/prior.jsonl", "session_log"),
        ):
            with self.subTest(target=target):
                command = "cat " + target
                code = "await tools.exec_command(" + json.dumps({"cmd": command}) + ")"
                trace = {"tool_trace": self.paired(code, "previous chat content")}
                self.assertIn("forbidden_context_reference:" + error, runtime.context_trace_errors(trace))
                self.assertNotIn("forbidden_context_reference:" + error,
                                 runtime.context_trace_errors(trace, input_paths=(target,)))

    def test_no_match_memory_search_is_always_forbidden(self):
        memory = "/repo/.codex/memories/raw_memories.md"
        command = "rg -n ITEM " + memory
        trace = {"tool_trace": self.paired(
            "await tools.exec_command(" + json.dumps({"cmd": command}) + ")", "")}
        self.assertIn("forbidden_context_reference:memory_path", runtime.context_trace_errors(trace))

    def test_worker_response_rejects_memory_citation_suffix(self):
        from scripts.worker_runtime_evidence import worker_response_value
        envelope = {"output": "Current-run evidence only.", "result": {"run_id": "run"}}
        suffix = "\n<oai-mem-citation>\n<citation_entries>\nraw_memories.md:1-2|note=[context]\n</citation_entries>\n<rollout_ids>\n</rollout_ids>\n</oai-mem-citation>"
        with self.assertRaisesRegex(ValueError, "worker_final_response_json_invalid"):
            worker_response_value(json.dumps(envelope) + suffix, Path("unused-session.jsonl"))

    def test_codex_home_memory_paths_are_rejected_when_quoted(self):
        for command, expected in (
            ('cat "$CODEX_HOME/memories/raw_memories.md"', "memory_path"),
            ('rg -n issue "${CODEX_HOME}/memories/notes.md"', "memory_directory"),
            (r'cat "%CODEX_HOME%\memories\raw_memories.md"', "memory_path"),
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
                 'cat "${CODEX_HOME}/memories/raw_memories.md"'}]
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
                'tools.exec_command({cmd:"cat /repo/.codex/memories/raw_memories.md"})]);')
        trace["tool_trace"] = self.paired(code, "cat /repo/.codex/memories/raw_memories.md")
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
        quoted = json.dumps({"thread": {"command": "cat /repo/.codex/memories/raw_memories.md"}})
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

    def instruction_read_trace(self, input_paths=()):
        trace = self.dispatch_trace(list(input_paths))
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
        command = ('ls -la .thoughts/ITEM-1; if test -f AGENTS.md; then echo "--- AGENTS.md"; cat AGENTS.md; fi')
        call = 'await tools.exec_command(' + json.dumps({"cmd": command, "workdir": str(self.repository)}) + ')'
        rows = self.paired(call, '.thoughts/ITEM-1:\ntotal 0\n--- AGENTS.md')
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

    def test_artifact_paths_are_not_allowed_instruction_ancestors(self):
        allowed = activation_fixtures.runtime_checks._allowed_instruction_paths(self.root, [])
        self.assertIn((self.repository / "AGENTS.md").resolve(), allowed)
        for path in (self.root.parent / "AGENTS.md", self.root / "AGENTS.md"):
            with self.subTest(path=path):
                self.assertNotIn(path.resolve(), allowed)
        source = self.repository / "src" / "current.py"
        source.parent.mkdir(parents=True)
        self.assertIn((source.parent / "AGENTS.md").resolve(),
                      activation_fixtures.runtime_checks._allowed_instruction_paths(self.root, [str(source)]))

    def test_assigned_source_ancestor_instructions_are_policy_not_archive_reads(self):
        trace = self.instruction_read_trace()
        source = self.repository / "src" / "module" / "current.py"
        source.parent.mkdir(parents=True)
        source.write_text("current source")
        instructions = source.parent / "AGENTS.md"
        policy = ("Do not read /Users/example/.codex/memories/raw_memories.md or "
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

    def test_packet_audit_projection_is_metadata_and_does_not_authorize_log_reads(self):
        trace = self.instruction_read_trace()
        packet_path = self.root / 'finalization_packet.json'
        packet = json.loads(packet_path.read_text())
        session = '/Users/example/.codex/sessions/worker.jsonl'
        audit = {'Worker': 'feature-context', 'Trace retrieval': session}
        packet['runtime_audits'] = [audit]
        packet_path.write_text(json.dumps(packet))
        command = "jq '{identity,runtime_audits}' " + str(packet_path)
        call = 'const r = await tools.exec_command(' + json.dumps({'cmd': command}) + '); text(r.output);'
        projected = {key: packet[key] for key in ('identity', 'runtime_audits')}
        rows = self.paired(call, [{'type': 'input_text', 'text': json.dumps(projected)}])
        rows[0]['call_id'] = rows[1]['call_id'] = 'audit-projection'
        trace['tool_trace'].extend(rows)
        self.assertEqual(runtime.trace_errors(trace), [])
        # Later audit registration must not invalidate the earlier metadata read.
        packet['runtime_audits'].append({'Worker': 'handoff', 'Trace retrieval': 'trace.json'})
        packet_path.write_text(json.dumps(packet))
        self.assertEqual(runtime.trace_errors(trace), [])
        changed = json.loads(json.dumps(trace))
        changed['tool_trace'].append({'type': 'function_call', 'name': 'exec_command', 'arguments': {'cmd': 'cat ' + session}})
        self.assertIn('forbidden_context_reference:session_log', runtime.trace_errors(changed))
        for altered in ('audit', 'other_field', 'source'):
            changed = json.loads(json.dumps(trace))
            value = json.loads(changed['tool_trace'][-1]['output'][0]['text'])
            if altered == 'audit':
                value['runtime_audits'][0]['Trace retrieval'] = session + '.other'
            elif altered == 'other_field':
                value['identity']['leaked'] = session
            else:
                changed['tool_trace'][-2]['input'] = changed['tool_trace'][-2]['input'].replace(
                    str(packet_path), str(self.root / 'runs/prior/finalization_packet.json'))
            changed['tool_trace'][-1]['output'][0]['text'] = json.dumps(value)
            self.assertIn('forbidden_context_reference:session_log', runtime.trace_errors(changed))

    def test_packet_read_provenance_resolves_fixed_paths_but_not_locator_dereferences(self):
        base = self.instruction_read_trace()
        path = self.root / 'finalization_packet.json'
        packet = json.loads(path.read_text())
        session = '/Users/example/.codex/sessions/current-worker.jsonl'
        packet['runtime_audits'] = [{'Worker': 'context', 'Trace retrieval': session}]
        path.write_text(json.dumps(packet))
        program = ("from pathlib import Path\nbase=Path(" + repr(str(self.root))
                   + ")\nfor name in ('finalization_packet.json',):\n print((base/name).read_text())")
        readers = ('git -C ' + str(self.repository) + ' status --short && cat ' + str(path),
                   "python3 - <<'PY'\n" + program + "\nPY", shlex.join([sys.executable, '-c', program]),
                   shlex.join(['python3', '-c', "from pathlib import Path\nfor name in [" + repr(str(path))
                               + "]:\n p=Path(name); print(p.read_text() if p.is_file() else 'absent')"]),
                   shlex.join(['python3', '-c', "from pathlib import Path; paths=[" + repr(str(path))
                               + "]; [print(Path(p).read_text()) for p in paths]"]),
                   shlex.join(['python3', '-c', "from pathlib import Path; paths=[" + repr(str(path))
                               + "," + repr(str(self.root / 'optional.json'))
                               + "]; [print(Path(p).read_text() if Path(p).is_file() else 'absent') for p in paths]"]))
        for command in readers:
            for nested in (False, True):
                with self.subTest(command=command, nested=nested):
                    output = json.dumps(packet, indent=2)
                    if nested:
                        output = json.dumps({'output': output, 'exit_code': 0})
                    call = 'const r = await tools.exec_command(' + json.dumps({'cmd': command}) + '); text(r.output);'
                    trace = json.loads(json.dumps(base))
                    trace['tool_trace'].extend(self.paired(call, [{'type': 'input_text', 'text': output}]))
                    self.assertEqual(runtime.trace_errors(trace), [])
                    for suffix in ('; cat ' + session, '; cat /repo/.thoughts/OTHER/runs/old.md'):
                        changed = json.loads(json.dumps(trace))
                        changed['tool_trace'][-2]['input'] = 'await tools.exec_command(' + json.dumps({'cmd': command + suffix}) + ')'
                        self.assertTrue(runtime.trace_errors(changed))
                    from scripts.runtime_checks import _read_targets
                    inline = shlex.join([sys.executable, '-c', program])
                    self.assertEqual(_read_targets(inline + '|cat<foreign'), [])
                    self.assertEqual(_read_targets(shlex.join(['/tmp/python3', '-c', program])), [])
                    for unsafe in (
                        "import json\np=json.load(open(" + repr(str(path))
                            + "))\nprint(json.load(open(p['runtime_audits'][0]['Trace retrieval'])))",
                        "from pathlib import Path\nbase=Path(" + repr(str(self.root))
                            + ")\nname=json.load(open('input.json'))['file']\nprint((base/name).read_text())",
                        "from pathlib import Path\nPath=eval\nprint(Path('input.json').read_text())",
                        *('from pathlib import Path\nimport json\np=json.load(open(' + repr(str(path))
                          + '))\npaths=[' + repr(str(path)) + ']\n' + mutation
                          + "\nfor name in paths:\n print(Path(name).read_text())" for mutation in (
                              "paths[:] += [p['runtime_audits'][0]['Trace retrieval']]",
                              "for paths[0] in [p['runtime_audits'][0]['Trace retrieval']]: pass"))):
                        changed = json.loads(json.dumps(trace))
                        changed['tool_trace'][-2]['input'] = 'await tools.exec_command(' + json.dumps({
                            'cmd': "python3 - <<'PY'\n" + unsafe + "\nPY"}) + ')'
                        self.assertIn('forbidden_context_reference:session_log', runtime.trace_errors(changed))

    def test_constructed_historical_paths_are_audited_as_accesses(self):
        for method in ('read_text', 'is_file'):
            code = ("from pathlib import Path; p=Path('/Users/example/.codex')/'sessions'/'prior.jsonl'; "
                    + "print(p." + method + "())")
            command = shlex.join(['python3', '-c', code])
            trace = {'tool_trace': [{'type': 'function_call', 'name': 'exec_command',
                                     'arguments': {'cmd': command}}]}
            with self.subTest(method=method):
                self.assertIn('forbidden_context_reference:session_log', runtime.context_trace_errors(trace))
        code = ("from pathlib import Path; p=Path(" + repr(str(self.root.parent))
                + ")/'OTHER'/'notes.md'; print(p.read_text())")
        trace = {'tool_trace': [{'type': 'function_call', 'name': 'exec_command',
                                 'arguments': {'cmd': shlex.join(['python3', '-c', code])}}]}
        self.assertIn('forbidden_context_reference:archived_artifact',
                      runtime.context_trace_errors(trace, artifact_root=self.root))
        command = shlex.join(['python3', '-c', "from pathlib import Path; p=Path("
                              + repr(str(self.root)) + ")/'AGENTS.md'; print(p.is_file())"])
        trace['tool_trace'][0]['arguments']['cmd'] = command
        self.assertIn('forbidden_context_reference:archived_artifact',
                      runtime.context_trace_errors(trace, artifact_root=self.root))

    def test_json_reads_keep_current_source_provenance_and_audit_constructed_paths(self):
        trace = self.instruction_read_trace()
        packet_path = self.root / 'finalization_packet.json'
        packet = json.loads(packet_path.read_text())
        packet['runtime_audits'] = [{'Worker': 'context',
                                     'Trace retrieval': '/Users/example/.codex/sessions/current.jsonl'}]
        packet_path.write_text(json.dumps(packet))
        for expression in (f'json.load(open({str(packet_path)!r}))',
                           f'json.loads(Path({str(packet_path)!r}).read_text())'):
            code = 'import json; from pathlib import Path; print(json.dumps(' + expression + '))'
            call = 'const r = await tools.exec_command(' + json.dumps({
                'cmd': shlex.join(['python3', '-c', code])}) + '); text(r.output);'
            current = json.loads(json.dumps(trace))
            current['tool_trace'].extend(self.paired(call, [{'type': 'text', 'text': json.dumps(packet)}]))
            with self.subTest(expression=expression):
                self.assertEqual(runtime.trace_errors(current), [])
        code = ("import json; from pathlib import Path; "
                "p=Path('/Users/example/.codex')/'sessions'/'prior.jsonl'; print(p.read_text())")
        command = shlex.join(['python3', '-c', code])
        self.assertIn('forbidden_context_reference:session_log', runtime.context_trace_errors({
            'tool_trace': [{'type': 'function_call', 'name': 'exec_command', 'arguments': {'cmd': command}}]}))

    def test_hashed_fixed_file_reads_preserve_source_provenance(self):
        trace = self.instruction_read_trace()
        packet = self.root / 'finalization_packet.json'
        content = json.loads(packet.read_text())
        content['reentry'] = {'Prior artifacts': str(self.root / 'runs' / 'old')}
        content['runtime_audits'] = [{'Trace retrieval': '/Users/example/.codex/sessions/current.jsonl'}]
        packet.write_text(json.dumps(content))
        code = ("from pathlib import Path\nimport hashlib\npaths=[" + repr(str(packet)) + "]\n"
                "for p in paths:\n data=Path(p).read_bytes()\n"
                " print(f'{p} {hashlib.sha256(data).hexdigest()} {data.decode()}')")
        call = 'const r = await tools.exec_command(' + json.dumps({'cmd': "python3 - <<'PY'\n" + code + "\nPY"}) + '); text(r.output);'
        trace['tool_trace'].extend(self.paired(call, [{'type': 'text', 'text': packet.read_text()}]))
        self.assertEqual(runtime.trace_errors(trace), [])
        trace['tool_trace'][-2]['input'] = call.replace(repr(str(packet)), repr('/Users/example/.codex/sessions/old.jsonl'))
        self.assertIn('forbidden_context_reference:session_log', runtime.trace_errors(trace))
        extra = code + "\nprint(Path('/repo/.thoughts/OTHER/runs/old').read_bytes())"
        trace['tool_trace'][-2]['input'] = 'const r = await tools.exec_command(' + json.dumps({
            'cmd': "python3 - <<'PY'\n" + extra + "\nPY"}) + '); text(r.output);'
        self.assertIn('forbidden_context_reference:archived_artifact', runtime.trace_errors(trace))

    def test_registered_current_snapshot_output_is_not_an_archive_read(self):
        content = b'/Users/example/.codex/sessions/old.jsonl\n'
        digest = hashlib.sha256(content).hexdigest()
        snapshot = self.root / 'input_snapshots' / digest / 'result.json'
        snapshot.parent.mkdir(parents=True)
        snapshot.write_bytes(content)
        bundle = Path(self.run['activation_packet_bundle']['path'])
        data = json.loads(bundle.read_text())
        data['packets']['current_state_investigator']['run_input_manifest']['inputs'].append({
            'path': str(snapshot), 'sha256': digest, 'Expected use': 'Revalidate saved evidence'})
        bundle.write_text(json.dumps(data))
        binding_path = self.root / 'role_bindings.json'
        binding = json.loads(binding_path.read_text())
        binding['activation_packet_bundle']['sha256'] = hashlib.sha256(bundle.read_bytes()).hexdigest()
        binding_path.write_text(json.dumps(binding))
        trace = self.instruction_read_trace()
        call = 'const r = await tools.exec_command(' + json.dumps({'cmd': 'cat ' + str(snapshot)}) + '); text(r.output);'
        trace['tool_trace'].extend(self.paired(call, [{'type': 'text', 'text': content.decode()}]))
        self.assertEqual(runtime.trace_errors(trace), [])
        snapshot.write_text('modified')
        self.assertIn('forbidden_context_reference:session_log', runtime.trace_errors(trace))

    def test_current_file_read_with_unspecified_workdir_is_auditable(self):
        trace = self.instruction_read_trace()
        path = self.root / 'finalization_packet.json'
        call = 'text(await tools.exec_command(' + json.dumps({'cmd': 'cat ' + str(path), 'workdir': None}) + '));'
        trace['tool_trace'].extend(self.paired(call, [{'type': 'text', 'text': path.read_text()}]))
        self.assertEqual(runtime.trace_errors(trace), [])

    def test_packet_metadata_reads_compose_with_repository_checks_without_allowing_log_reads(self):
        base = self.instruction_read_trace()
        path = self.root / 'finalization_packet.json'
        packet = json.loads(path.read_text())
        session = '/Users/example/.codex/sessions/worker.jsonl'
        packet['runtime_audits'] = [{'Worker': 'context', 'Trace retrieval': session}]
        path.write_text(json.dumps(packet))
        for reader in ('cat ' + str(path), "sed -n '1,999p' " + str(path)):
            for separator in (' && ', '; ', '\n'):
                with self.subTest(reader=reader, separator=separator):
                    command = 'git status --short --branch' + separator + 'git rev-parse HEAD' + separator + reader
                    call = 'const r = await tools.exec_command(' + json.dumps({'cmd': command}) + '); text(r.output);'
                    trace = json.loads(json.dumps(base))
                    trace['tool_trace'].extend(self.paired(call, [{'type': 'input_text', 'text':
                        '## main\nrevision\n' + json.dumps(packet)}]))
                    self.assertEqual(runtime.trace_errors(trace), [])
                    for unsafe in ('; cat ' + session, '; cat /repo/.thoughts/OTHER/runs/old/notes.md',
                                   '; python3 -c "print(open(\'' + session + '\').read())"'):
                        changed = json.loads(json.dumps(trace))
                        changed['tool_trace'][-2]['input'] = 'const r = await tools.exec_command(' + json.dumps({
                            'cmd': command + unsafe}) + '); text(r.output);'
                        self.assertTrue(any(error.startswith('forbidden_context_reference:')
                                            for error in runtime.trace_errors(changed)))

    def test_mixed_source_search_and_packet_read_preserve_metadata_provenance(self):
        trace = self.instruction_read_trace([str(self.repository)])
        source = self.repository / 'code.txt'
        source.write_text('renderSubject\n')
        packet_path = self.root / 'finalization_packet.json'
        packet = json.loads(packet_path.read_text())
        packet['runtime_audits'] = [{'Worker': 'context', 'Trace retrieval': '/Users/example/.codex/sessions/current.jsonl'}]
        packet_path.write_text(json.dumps(packet))
        command = "rg -n 'renderSubject|normalize' " + str(source) + ' | head -n 20; cat ' + str(packet_path)
        call = 'text(await tools.exec_command(' + json.dumps({'cmd': command}) + '));'
        output = [{'type': 'input_text', 'text': json.dumps({'exit_code': 0, 'output':
            '1:renderSubject\n' + json.dumps(packet)})}]
        # The code scope is a directory; legitimate reads inside it need not be listed one file at a time.
        content = Path(trace['spawn']['dispatch_file']).read_text()
        self.assertIn(str(self.repository), content)
        trace['tool_trace'].extend(self.paired(call, output))
        self.assertEqual(runtime.trace_errors(trace), [])
        external = self.repository.parent / 'external-data'
        external.write_text('/Users/example/.codex/sessions/foreign.jsonl')
        (self.repository / 'foreign-link').symlink_to(external)
        (self.repository / '*').write_text('A real wildcard-named file must not make expansion trustworthy.')
        for suffix in ('; cat /Users/example/.codex/sessions/foreign.jsonl', '; cat /repo/.thoughts/OTHER/runs/old.md',
                       '; cat ' + str(self.repository / '*'), '; cat ' + str(self.repository / 'foreign-link')):
            changed = json.loads(json.dumps(trace))
            changed['tool_trace'][-2]['input'] = 'text(await tools.exec_command(' + json.dumps({'cmd': command + suffix}) + '));'
            self.assertTrue(any(error.startswith('forbidden_context_reference:') for error in runtime.trace_errors(changed)))

    def test_batched_guarded_source_reads_preserve_current_packet_provenance(self):
        base = self.instruction_read_trace([str(self.repository)])
        source = self.repository / 'module' / 'code.txt'
        source.parent.mkdir()
        source.write_text('current source')
        external = self.repository.parent / 'external-source'
        external.write_text('external source')
        link = source.parent / 'foreign-link'
        link.symlink_to(external)
        packet = self.root / 'finalization_packet.json'
        session = '/Users/example/.codex/sessions/current-worker.jsonl'
        data = json.loads(packet.read_text())
        data['runtime_audits'] = [{'Worker': 'context', 'Trace retrieval': session}]
        packet.write_text(json.dumps(data))
        command = ('for p in ' + str(source.parent / 'AGENTS.md')
                   + '; do if test -f "$p"; then cat "$p"; fi; done; cat ' + str(source))
        def audit(first, second):
            trace = json.loads(json.dumps(base))
            call = ('text(await tools.exec_command(' + json.dumps({'cmd': first}) + '));\n'
                    'text(await tools.exec_command(' + json.dumps({'cmd': second}) + '));')
            # The provider can truncate a combined result even when both source operations are legitimate.
            output = 'Warning: truncated output (original token count: 10000)\n' + json.dumps({
                'exit_code': 0, 'output': json.dumps(data)})
            trace['tool_trace'].extend(self.paired(call, [{'type': 'text', 'text': output}]))
            return runtime.trace_errors(trace)
        self.assertEqual(audit(command, 'cat ' + str(packet)), [])
        for unsafe in ('cat ' + session, command + '; cat ' + session,
                       command.replace(str(source), str(self.repository / '*')),
                       command.replace(str(source), str(link)),
                       command.replace(str(source.parent / 'AGENTS.md'), '$HOME/AGENTS.md'),
                       command.replace('then cat "$p"', 'then cat ' + session)):
            with self.subTest(unsafe=unsafe):
                self.assertIn('forbidden_context_reference:session_log', audit(unsafe, 'cat ' + str(packet)))

    def test_packet_read_batched_with_repository_status_preserves_metadata_provenance(self):
        trace = self.instruction_read_trace([str(self.repository)])
        packet = self.root / 'finalization_packet.json'
        data = json.loads(packet.read_text())
        session = '/Users/example/.codex/sessions/current.jsonl'
        archive = str(self.root / 'runs' / 'prior')
        data['runtime_audits'] = [{'Trace retrieval': session}]
        data['recovery'] = {'Prior artifacts': archive}
        packet.write_text(json.dumps(data))
        def audit(extra=''):
            current = json.loads(json.dumps(trace))
            call = ('text(await tools.exec_command(' + json.dumps({'cmd': 'cat ' + str(packet)}) + '));\n'
                    'text(await tools.exec_command(' + json.dumps({'cmd': 'git status --short --branch\ngit rev-parse HEAD' + extra}) + '));')
            current['tool_trace'].extend(self.paired(call, [{'type': 'input_text', 'text': json.dumps(data)}]))
            return runtime.trace_errors(current)
        self.assertEqual(audit(), [])
        self.assertIn('forbidden_context_reference:session_log', audit('; cat ' + session))
        self.assertIn('forbidden_context_reference:archived_artifact', audit('; cat ' + archive + '/secret'))

    def test_current_artifact_json_inspection_treats_search_literals_as_data(self):
        path = self.root / 'trace.json'
        path.write_text(json.dumps({'tool_trace': []}))
        code = ('import json,sys; d=json.load(open(sys.argv[1])); '
                'print([x for x in d.get("tool_trace",[]) if "/.codex/sessions" in str(x)])')
        command = shlex.join(['python3', '-c', code, str(path)])
        def errors(value):
            return runtime.context_trace_errors({'tool_trace': [{'type': 'function_call', 'name': 'exec_command',
                'arguments': {'cmd': value}}]}, artifact_root=self.root)
        self.assertEqual(errors(command), [])
        diagnostic = ('import json\np=' + repr(str(path)) + '; d=json.load(open(p)); '
                      's=json.dumps(d); i=s.find("/.codex/sessions"); '
                      'print(s[max(0,i-20):i+30])')
        for invocation in (shlex.join(['python3', '-c', diagnostic]),
                           "python3 - <<'PY'\n" + diagnostic + "\nPY"):
            self.assertEqual(errors(invocation), [])
            self.assertIn('forbidden_context_reference:session_log', errors(
                invocation + '\ncat /Users/example/.codex/sessions/foreign.jsonl'))
            self.assertIn('forbidden_context_reference:session_log', errors(invocation.replace(
                repr(str(path)), repr('/Users/example/.codex/sessions/foreign.jsonl'))))
        for unsafe in (command + '; cat /Users/example/.codex/sessions/foreign.jsonl',
                       'python3 -c "import json; d=json.load(open(\'' + str(path)
                           + '\')); print(\'$(cat /Users/example/.codex/sessions/foreign.jsonl)\' == \'\')"',
                       'python3 -c "import json; d=json.load(open(\'' + str(path)
                           + '\')); print(\'`cat /Users/example/.codex/sessions/foreign.jsonl`\' == \'\')"',
                       shlex.join(['python3', '-c', code, '/Users/example/.codex/sessions/foreign.jsonl']),
                       shlex.join(['python3', '-c', code + '; eval("open(\'/Users/example/.codex/sessions/foreign.jsonl\').read()")', str(path)]),
                       shlex.join(['python3', '-c', code + '; str=eval; str("open(\'/Users/example/.codex/sessions/foreign.jsonl\').read()")', str(path)]),
                       shlex.join(['python3', '-c', 'import json; p=' + repr(str(path))
                           + '; p="/Users/example/.codex/sessions/foreign.jsonl"+""; print(json.load(open(p)))'])):
            self.assertIn('forbidden_context_reference:session_log', errors(unsafe))

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

    def test_pretty_current_packet_metadata_keeps_actual_archive_reads_blocked(self):
        packet_path = self.root / "finalization_packet.json"
        packet = json.loads(packet_path.read_text())
        reference = str(self.root / "runs" / "prior")
        packet.update({"reentry": {"Prior run ID": "prior", "Prior artifacts": reference},
                       "integration_decision": {}, "handoff": {},
                       "claims": [{"Claim ID": "review-result", "Claim": "review accepted"}]})
        packet_path.write_text(json.dumps(packet))
        program = (f"import json,pprint; p=json.load(open({str(packet_path)!r}));\n"
                   "for k in ['integration_decision','reentry','handoff']: print('\\n'+k+':'); pprint.pp(p[k]);\n"
                   "for k in ['claims']:\n print('\\n'+k+' relevant:');\n for x in p[k]:\n"
                   "  s=str(x)\n  if 'review' in s.lower(): pprint.pp(x)\n")
        command = "python3 -c " + shlex.quote(program)
        call = 'const r = await tools.exec_command(' + json.dumps({"cmd": command,
            "workdir": str(self.repository)}) + '); text(r.output);'
        output = "".join("\n" + field + ":\n" + pprint.pformat(packet[field], sort_dicts=False) + "\n"
                         for field in ("integration_decision", "reentry", "handoff"))
        output += "\nclaims relevant:\n" + pprint.pformat(packet["claims"][0], sort_dicts=False) + "\n"
        trace = self.instruction_read_trace()
        trace["tool_trace"].extend(self.paired(call, [{"type": "input_text", "text":
            "Script completed\nWall time 0.3 seconds\nOutput:\n"}, {"type": "input_text", "text": output}]))
        self.assertEqual(runtime.trace_errors(trace), [])
        self.assertEqual(runtime.context_trace_errors({"tool_trace": trace["tool_trace"][-2:]},
                                                      artifact_root=self.root), [])
        secret = str(self.root / "runs" / "secret")
        for change in ("forged", "extra_output", "archive_read", "indirect_read", "extra_read", "write", "mixed",
                       "interpreter", "shadow", "callback", "attribute", "class"):
            changed = json.loads(json.dumps(trace))
            if change == "forged": changed["tool_trace"][-1]["output"][1]["text"] = output.replace(reference, secret)
            elif change == "extra_output": changed["tool_trace"][-1]["output"][1]["text"] += "\n" + secret
            elif change == "mixed": changed["tool_trace"][-2]["input"] += ' await tools.exec_command({"cmd":"cat ' + secret + '"});'
            else:
                bad = program
                if change == "archive_read": bad = bad.replace(str(packet_path), secret)
                elif change == "indirect_read": bad += "json.load(open(p['reentry']['Prior artifacts']))\n"
                elif change == "extra_read": bad += "json.load(open('/tmp/unassigned.json'))\n"
                elif change == "write": bad += "open('/tmp/side-effect','w').write('x')\n"
                elif change == "shadow": bad += "for json.dumps in [eval]: json.dumps('payload')\n"
                elif change == "callback": bad += "sorted(['payload'], key=eval)\n"
                elif change == "attribute": bad += "pprint.pp.__globals__.get('secret')\n"
                elif change == "class": bad += "type('Proxy',(),{})\n"
                cmd = ("/tmp/python3" if change == "interpreter" else "python3") + " -c " + shlex.quote(bad)
                changed["tool_trace"][-2]["input"] = 'const r = await tools.exec_command(' + json.dumps({
                    "cmd": cmd, "workdir": str(self.repository)}) + '); text(r.output);'
            with self.subTest(change=change):
                self.assertIn("forbidden_context_reference:archived_artifact", runtime.trace_errors(changed))
                self.assertIn("forbidden_context_reference:archived_artifact", runtime.context_trace_errors(
                    {"tool_trace": changed["tool_trace"][-2:]}, artifact_root=self.root))

    def test_pretty_reentry_mask_preserves_wrapping_unicode_and_other_references(self):
        from scripts.runtime_checks import _without_pretty_reentry_reference
        reentry = {"Prior artifacts": str(self.root / "runs" / "priór with spaces"), "Approval reference": "approved"}
        text = "reentry:\n" + pprint.pformat(reentry, width=30) + "\n"
        masked = _without_pretty_reentry_reference(text, reentry)
        self.assertIn("[current packet archive reference]", masked)
        self.assertNotIn("priór", masked)
        self.assertNotIn("priór", _without_pretty_reentry_reference(pprint.pformat(reentry), reentry))
        nested = pprint.pformat({"identity": {"State": "in_progress"}, "reentry": reentry})
        self.assertNotIn("priór", _without_pretty_reentry_reference(nested, reentry))
        extra = str(self.root / "runs" / "another")
        self.assertTrue(_without_pretty_reentry_reference(text + extra, reentry).endswith(extra))
        self.assertEqual(_without_pretty_reentry_reference(text, {**reentry, "Approval reference": "changed"}), text)

    def test_bounded_current_packet_reads_keep_archive_access_guard(self):
        packet_path = self.root / "finalization_packet.json"
        packet = json.loads(packet_path.read_text())
        packet["reentry"] = {"Prior artifacts": str(self.root / "runs" / "prior")}
        packet_path.write_text(json.dumps(packet, indent=2) + "\n")
        for tool in ("head -n 90", "tail -n 90", "head -90", "tail --lines=90"):
            trace = self.instruction_read_trace()
            call = 'const r = await tools.exec_command(' + json.dumps({
                "cmd": tool + " .thoughts/ITEM-1/finalization_packet.json", "workdir": str(self.repository)}) + '); text(r.output);'
            lines = packet_path.read_text().splitlines(keepends=True)
            output = "".join(lines[:90] if tool.startswith("head") else lines[-90:])
            trace["tool_trace"].extend(self.paired(call, output))
            self.assertEqual(runtime.trace_errors(trace), [])
            trace["tool_trace"][-2]["input"] = call.replace(
                '.thoughts/ITEM-1/finalization_packet.json', '.thoughts/ITEM-1/runs/prior/finalization_packet.json')
            self.assertIn("forbidden_context_reference:archived_artifact", runtime.trace_errors(trace))
            trace["tool_trace"][-2]["input"] = call.replace(
                '.thoughts/ITEM-1/finalization_packet.json', '.thoughts/ITEM-1/finalization_packet.json; cat .thoughts/ITEM-1/runs/prior/notes.md')
            self.assertIn("forbidden_context_reference:archived_artifact", runtime.trace_errors(trace))
        for command in ("tail -f packet.json", "tail -n $COUNT packet.json", "tail -n 2 packet.json > copy",
                        "tail --lines=2 --follow packet.json"):
            self.assertEqual(runtime._read_targets(command), [])

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
        paths = [self.repository / "AGENTS.md"]
        policy = "Do not read .thoughts/ITEM-1/runs/prior/notes.md.\n"
        paths[0].write_text(policy)
        program = ("from pathlib import Path\nfor p in [" + ", ".join(f"Path({str(p)!r})" for p in paths) + "]:\n"
                   "    print(f'--- {p} exists={p.is_file()}')\n    if p.is_file(): print(p.read_text())")
        command = "python3 - <<'PY'\n" + program + "\nPY"
        output = "".join(f"--- {p} exists={p.is_file()}\n" + (p.read_text() + "\n" if p.is_file() else "") for p in paths)
        call = lambda cmd: 'await tools.exec_command(' + json.dumps({"cmd": cmd, "workdir": str(self.repository)}) + ')'
        trace = {"tool_trace": self.paired(call(command), output)}
        self.assertEqual(runtime.context_trace_errors(trace, artifact_root=self.root), [])
        mixed = command.replace("from pathlib import Path\n", "import json\nfrom pathlib import Path\nprint('current bindings')\n")
        mixed = mixed.replace("--- {p}", "AGENTS_CHECK {p}").replace(
            "if p.is_file():", f"if p.is_file() and p != Path({str(paths[0])!r}):")
        self.assertEqual(runtime.context_trace_errors(
            {"tool_trace": self.paired(call(mixed), output)}, artifact_root=self.root), [])
        unrecognized = (mixed.replace("for p in", "Path = other_reader\nfor p in"),
                        mixed.replace("for p in", "import evil as Path\nfor p in"),
                        mixed.replace("for p in", "exec('Path = other_reader')\nfor p in"),
                        mixed.replace("for p in", "Path.read_text = other_reader\nfor p in"),
                        command.replace("p.read_text()", "p.write_text('changed')"),
                        command.replace(str(paths[0]), str(self.root.parent / "AGENTS.md")))
        for unsafe in unrecognized:
            with self.subTest(command=unsafe):
                row = {"type": "function_call", "name": "exec_command", "arguments": {
                    "cmd": unsafe, "workdir": str(self.repository)}}
                self.assertEqual(runtime._ancestor_instruction_reads(row, self.root), [])
        archived = command + "\ncat .thoughts/ITEM-1/runs/prior/notes.md"
        self.assertIn("forbidden_context_reference:archived_artifact", runtime.context_trace_errors(
            {"tool_trace": self.paired(call(archived), "")}, artifact_root=self.root))
        paths[0].unlink()
        archived = self.root / "runs/prior/notes.md"
        archived.parent.mkdir(parents=True)
        archived.write_text("old analysis")
        paths[0].symlink_to(archived)
        row = {"type": "function_call", "name": "exec_command", "arguments": {
            "cmd": command, "workdir": str(self.repository)}}
        self.assertEqual(runtime._ancestor_instruction_reads(row, self.root), [])

    def test_python_literal_path_list_reads_only_assigned_ancestor_instructions(self):
        paths = [str(self.repository / "AGENTS.md")]
        program = ("from pathlib import Path\npaths = " + repr(paths) + "\n"
                   "for value in paths:\n    path = Path(value)\n    if path.is_file():\n"
                   "        print(f'===== {value} =====')\n        print(path.read_text())\n"
                   "    else:\n        print(f'ABSENT {value}')")
        call = lambda script: 'await tools.exec_command(' + json.dumps({
            "cmd": "python3 - <<'PY'\n" + script + "\nPY", "workdir": str(self.repository)}) + ')'
        output = "".join("ABSENT " + value + "\n" for value in paths)
        self.assertEqual(runtime.context_trace_errors(
            {"tool_trace": self.paired(call(program), output)}, artifact_root=self.root), [])
        for unsafe in (program + "\nprint(open('.thoughts/ITEM-1/runs/prior/secret').read())",
                       program.replace(paths[0], str(self.root.parent / 'AGENTS.md')),
                       program.replace("path.read_text()", "path.write_text('changed')")):
            with self.subTest(script=unsafe):
                row = {"type": "function_call", "name": "exec_command", "arguments": {
                    "cmd": unsafe, "workdir": str(self.repository)}}
                if ".thoughts/ITEM-1/runs/prior/secret" in unsafe:
                    self.assertIn("forbidden_context_reference:archived_artifact", runtime.context_trace_errors(
                        {"tool_trace": self.paired(call(unsafe), "")}, artifact_root=self.root))
                else:
                    self.assertEqual(runtime._ancestor_instruction_reads(row, self.root), [])

    def test_ancestor_filename_probe_is_not_an_archive_read(self):
        for directory in ("", str(self.repository) + "/"):
            trace = self.instruction_read_trace()
            command = (f'for f in {directory}AGENTS.md; do if [ -f "$f" ]; '
                       'then printf "%s\\n" "$f"; fi; done')
            call = 'await tools.exec_command(' + json.dumps({"cmd": command, "workdir": str(self.repository)}) + ')'
            rows = self.paired(call, directory + 'AGENTS.md')
            rows[0]["call_id"] = rows[1]["call_id"] = "probe"
            self.assertEqual(runtime._ancestor_instruction_reads(rows[0], self.root), [])
            self.assertTrue(runtime._ancestor_instruction_reads(rows[0], self.root, include_probes=True))
            trace["tool_trace"].extend(rows)
            self.assertEqual(runtime.trace_errors(trace), [])

    def test_ancestor_probe_after_other_commands_keeps_archive_restrictions(self):
        probe = ('for f in AGENTS.md; '
                 'do if test -f "$f"; then printf \'%s\\n\' "$f"; fi; done')
        prefix = ('python3 -c \'import json; p=json.load(open(".thoughts/ITEM-1/finalization_packet.json")); '
                  'print(json.dumps({"state":"current"}))\' '
                  '&& test ! -e .thoughts/ITEM-1/documenter_assignment.json '
                  '&& printf \'assignment path unused\\n\' ')
        for separator in ('&& ', '; ', '\n'):
            command = prefix + separator + probe
            rows = self.paired('await tools.exec_command(' + json.dumps({
                'cmd': command, 'workdir': str(self.repository)}) + ')', 'AGENTS.md')
            self.assertEqual(runtime.context_trace_errors({'tool_trace': rows}, artifact_root=self.root), [])
            for bad in (command + '; cat .thoughts/ITEM-1/runs/prior/notes.md',
                        'cat .thoughts/OTHER/notes.md; ' + command,
                        'cd other; cat .thoughts/ITEM-1/runs/prior/notes.md; ' + command,
                        'eval "cd other"; cat .thoughts/ITEM-1/runs/prior/notes.md; ' + command,
                        command.replace('AGENTS.md', '.thoughts/ITEM-1/runs/prior/AGENTS.md')):
                rejected = self.paired('await tools.exec_command(' + json.dumps({
                    'cmd': bad, 'workdir': str(self.repository)}) + ')', '')
                self.assertIn('forbidden_context_reference:archived_artifact',
                              runtime.context_trace_errors({'tool_trace': rejected}, artifact_root=self.root))

    def test_echo_ancestor_probe_with_literal_quotes_is_not_an_archive_read(self):
        for condition, output in (("test -f $p", "echo $p"),
                                  (r'test -f \"$p\"', r'echo \"$p\"')):
            trace = self.instruction_read_trace()
            command = ('for p in AGENTS.md; '
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
        command = ('for f in AGENTS.md; '
                   'do if [[ -f "$f" ]]; then printf \'%s\\n\' "$f"; fi; done')
        call = 'await tools.exec_command(' + json.dumps({"cmd": command, "workdir": str(self.repository)}) + ')'
        trace["tool_trace"].extend(self.paired(call, ""))
        self.assertEqual(runtime.trace_errors(trace), [])
        trace["tool_trace"][-2]["input"] = call.replace('fi; done',
            'fi; done; cat .thoughts/ITEM-1/runs/prior/notes.md')
        self.assertIn("forbidden_context_reference:archived_artifact", runtime.trace_errors(trace))

    def test_negated_instruction_probe_keeps_archive_restrictions(self):
        trace = self.instruction_read_trace()
        command = ('for f in AGENTS.md; '
                   'do test ! -f "$f" || printf \'%s\\n\' "$f"; done')
        call = 'await tools.exec_command(' + json.dumps({"cmd": command, "workdir": str(self.repository)}) + ')'
        trace["tool_trace"].extend(self.paired(call, ""))
        self.assertEqual(runtime.trace_errors(trace), [])
        trace["tool_trace"][-2]["input"] = call.replace('done', 'done; cat .thoughts/ITEM-1/runs/prior/notes.md')
        self.assertIn("forbidden_context_reference:archived_artifact", runtime.trace_errors(trace))

    def test_ancestor_instructions_are_reads_not_historical_analysis(self):
        (self.repository / "AGENTS.md").write_text("Current source policy\n")
        for command in (
            'for file in AGENTS.md; do if [ -f "$file" ]; then printf \'%s\\n\' "--- $file"; cat "$file"; else printf \'%s\\n\' "absent: $file"; fi; done',
            'for p in AGENTS.md; do if test -f "$p"; then printf \'FOUND %s\\n\' "$p"; cat "$p"; fi; done',
            'for p in AGENTS.md; do if test -f "$p"; then echo "Checking $p"; cat "$p"; fi; done',
            'cat AGENTS.md',
            'cat AGENTS.md; sed -n "1,20p" AGENTS.md',
            'for p in AGENTS.md; do\nif [ -f "$p" ]; then\ncat "$p";\nfi;\ndone',
        ):
            with self.subTest(command=command):
                trace = self.instruction_read_trace()
                call = 'const r = await tools.exec_command(' + json.dumps({"cmd": command, "workdir": str(self.repository)}) + '); text(r.output);'
                rows = self.paired(call, '--- AGENTS.md\nCurrent source policy')
                rows[0]["call_id"] = rows[1]["call_id"] = "ancestor"
                trace["tool_trace"].extend(rows)
                self.assertEqual(runtime.trace_errors(trace), [])

    def test_instruction_exception_does_not_allow_writes_or_other_work_items(self):
        for command in (
            'for f in .thoughts/AGENTS.md; do if [ -f "$f" ]; then cat "$f"; else echo changed > "$f"; fi; done',
            'for f in .thoughts/AGENTS.md; do if [ -f "$f" ]; then cat "$f"; else printf "%n" f; fi; done',
            'for f in .thoughts/AGENTS.md; do if [ -f "$f" ]; then cat "$f"; else cat .thoughts/ITEM-1/runs/prior/notes.md; fi; done',
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
        (self.repository / "AGENTS.md").write_text(policy)
        trace = self.instruction_read_trace()
        call = 'await tools.exec_command(' + json.dumps({"cmd": 'cat AGENTS.md',
                                                        "workdir": str(self.repository)}) + ')'
        rows = self.paired(call, policy)
        rows[0]["call_id"] = rows[1]["call_id"] = "policy"
        trace["tool_trace"].extend(rows)
        self.assertEqual(runtime.context_trace_errors(trace), [])
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
        session_day = (start + timedelta(seconds=1)).astimezone().strftime("%Y/%m/%d")
        session_dir = self.repository / ".codex" / "sessions" / session_day
        session_dir.mkdir(parents=True)
        parent = session_dir / f"rollout-parent-{SOURCE}.jsonl"
        parent.write_text("\n".join(json.dumps(row) for row in [
            {"timestamp": time(0), "type": "session_meta", "payload": {"id": SOURCE}},
            {"timestamp": time(1), "type": "response_item", "payload": {"type": "function_call", "namespace": "collaboration", "name": "spawn_agent",
             "arguments": json.dumps({"task_name": "evidence_topology", "agent_type": role, "message": "opaque",
                 "model": "gpt-6-luna", "reasoning_effort": "high", "fork_turns": "none"})}},
            {"timestamp": time(1), "type": "event_msg", "payload": {"item": {"type": "SubAgentActivity",
             "kind": "started", "agent_path": handle, "agent_thread_id": child}}},
        ]) + "\n")
        session = session_dir / f"rollout-child-{child}.jsonl"
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
                 "cmd": 'for p in AGENTS.md; do if test -f "$p"; then printf \'FOUND %s\\n\' "$p"; cat "$p"; fi; done',
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
        collector_command = [sys.executable, run["runtime_evidence"]["collector"], "--provider-session", str(parent),
            "--parent-thread-id", SOURCE, "--started-at", time(0), "--ledger", run["runtime_evidence"]["ledger"],
            "--worker-thread-id", child, "--observation", str(observation), "--agent", role,
            "--trace", str(trace_path)]
        result = subprocess.run(collector_command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        exported = json.loads(trace_path.read_text())
        self.assertEqual(exported["audit"], {"status": "passed", "errors": []})
        self.assertNotIn("activation_packet_delivered", exported["spawn"])
        self.assertEqual(runtime.trace_errors(exported, require_freshness=True), [])
        unassigned = collector_command.copy()
        unassigned[unassigned.index("--worker-thread-id") + 1] = SOURCE
        unassigned[unassigned.index("--trace") + 1] = str(root / "unassigned.json")
        rejected = subprocess.run(unassigned, capture_output=True, text=True)
        self.assertEqual(rejected.returncode, 2, rejected.stdout + rejected.stderr)
        self.assertEqual(json.loads(rejected.stdout)["reason"], "worker_thread_id_not_dispatched_in_current_run")

    def test_computed_tool_access_cannot_get_the_source_output_exception(self):
        trace = self.dispatch_trace(["codex://threads/" + SOURCE])
        code = ('await tools.mcp__codex_app__read_thread({threadId:"' + SOURCE + '"}); '
                'await tools["exec_command"]({cmd:"cat /repo/.codex/memories/raw_memories.md"})')
        trace["tool_trace"] = self.paired(code, "/repo/.codex/memories/raw_memories.md")
        self.assertTrue(any(error.startswith("forbidden_context_reference:memory_")
                            for error in runtime.context_trace_errors(trace)))

    def test_worker_thread_reads_require_an_assigned_source(self):
        trace = self.dispatch_trace(["codex://threads/" + SOURCE])
        other = "00000000-0000-0000-0000-000000000002"
        for name, args in (("read_thread", {"threadId": SOURCE}),
                           ("wait_threads", {"targets": [{"threadId": SOURCE}], "timeoutMs": 0})):
            with self.subTest(name=name):
                trace["tool_trace"] = [{"type": "function_call", "name": "mcp__codex_app__" + name,
                                        "arguments": args}]
                self.assertEqual(runtime.context_trace_errors(trace), [])
                trace["tool_trace"][0]["arguments"] = (
                    {"threadId": other} if name == "read_thread" else {"targets": [{"threadId": other}]})
                self.assertIn("context_unassigned_thread_read:" + other, runtime.context_trace_errors(trace))

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
                                          "/repo/.codex/memories/raw_memories.md")
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

    def test_engineering_guidance_is_not_a_required_product_asset_or_jira_source(self):
        inputs = {
            "GUIDE": {"Input or artifact": "ITEM-1 Jira development guidance",
                     "Classification": "engineering guidance", "Asset source": True,
                     "Source or path": str(self.repository / "guide.md"),
                     "Authority": "User-supplied context"},
            "SPEC": {"Input or artifact": "Product specification", "Classification": "supporting artifact",
                     "Source or path": str(self.repository / "requirements.md"),
                     "Authority": "User-supplied context"},
        }
        self.assertFalse(assets._supplied_asset_reference(inputs["GUIDE"]))
        self.assertEqual(assets._expected_jira_input_ids(inputs, "ITEM-1"), set())
        self.assertEqual(assets._expected_asset_input_ids(inputs), {"SPEC"})
        inputs["SPEC"]["Asset source"] = True
        self.assertEqual(assets._expected_asset_input_ids(inputs), {"SPEC"})
        inputs["GUIDE"]["Classification"] = "supporting artifact"
        self.assertEqual(assets._expected_asset_input_ids(inputs), {"SPEC", "GUIDE"})

    def test_code_scope_is_excluded_from_asset_inventory_and_directory_scans(self):
        code_dir = self.repository / "journeys"
        code_dir.mkdir()
        (code_dir / "main.go").write_text("package journeys\n")
        inputs = {
            "CODE-001": {"Classification": "code scope", "Asset source": True,
                         "Source or path": str(code_dir)},
            "LEGACY-001": {"Classification": "repository scope", "Asset source": True,
                           "Source or path": str(code_dir)},
            "DOC-001": {"Classification": "supporting artifact", "Asset source": True,
                        "Source or path": str(self.repository / "guide.md")},
        }
        self.assertEqual(assets._expected_asset_input_ids(inputs), {"DOC-001"})
        manifest = {
            "schema_version": 1,
            "status": "awaiting_input",
            "work_item": "ITEM-1",
            "sources": [{
                "source_id": "SRC-CODE",
                "input_id": "CODE-001",
                "kind": "directory",
                "locator": str(code_dir),
                "requiredness": "supporting",
                "discovery_status": "partial",
                "discovery_method": "classification check",
                "limitation": "This path is code scope, not an asset source.",
                "asset_ids": [],
                "evidence_refs": ["EV-001"],
            }],
            "assets": [],
            "gate": {
                "inventory_complete": False,
                "all_assets_accounted_for": True,
                "all_available_assets_reviewed": True,
                "all_material_assets_linked": True,
                "reviewed_before_plan": False,
                "unresolved_asset_ids": [],
                "blocking_source_ids": ["SRC-CODE"],
            },
        }
        with patch.object(assets, "_check_source_files", side_effect=AssertionError("code scope was scanned")) as scan:
            errors = assets.validate_asset_manifest(
                manifest,
                expected_input_ids=inputs,
                expected_inputs=inputs,
                expected_evidence_ids=["EV-001"],
            )
        scan.assert_not_called()
        self.assertIn("code scope input CODE-001 cannot be declared as an asset source", errors)
        self.assertIn("code scope input LEGACY-001 cannot be declared as an asset source", errors)

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
