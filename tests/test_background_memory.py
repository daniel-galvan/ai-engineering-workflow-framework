"""MEMORY.md is background guidance, never authorization for historical sources."""

import json
import tempfile
import unittest
from pathlib import Path

from scripts.runtime_checks import background_memory_paths, context_trace_errors
from scripts.provider_runtime import _preflight_order_errors, parent_context_audit
from scripts.validation.common import FORBIDDEN_REPORT_CONTEXT_PATTERNS
from scripts.merge_techops_result import validated_result
from scripts.worker_runtime_evidence import worker_response_value, _materialize_worker_response


MEMORY = '/repo/.codex/memories/MEMORY.md'


class BackgroundMemory(unittest.TestCase):
    def trace(self, command, output=''):
        return {'tool_trace': [
            {'type': 'custom_tool_call', 'name': 'exec', 'call_id': 'read',
             'input': 'text(await tools.exec_command(' + json.dumps({'cmd': command}) + '));'},
            {'type': 'custom_tool_call_output', 'call_id': 'read', 'output': output},
        ]}

    def test_registry_reads_and_pointer_output_are_allowed(self):
        pointers = '/repo/.codex/memories/rollout_summaries/old.md\n/repo/.codex/sessions/old.jsonl'
        for command in ('cat ' + MEMORY, 'cat MEMORY.md ' + MEMORY,
                        'head -n 20 ' + MEMORY, 'sed -n 1,20p ' + MEMORY,
                        'nl -ba ' + MEMORY + ' | sed -n 1,20p',
                        'rg -n "ECHO-2364|workflow-framework" ' + MEMORY,
                        'cat "$CODEX_HOME"/memories/MEMORY.md',
                        'cat "${CODEX_HOME}/memories/MEMORY.md"',
                        r'cat "%CODEX_HOME%\memories\MEMORY.md"'):
            with self.subTest(command=command):
                self.assertEqual(context_trace_errors(self.trace(command, pointers)), [])

    def test_v5_compound_read_is_allowed(self):
        command = ('ls -l /repo/.thoughts/ITEM-1 | head -40\n'
                   'cat /repo/.thoughts/ITEM-1/assignment.json || true\n'
                   'rg -n "ECHO-2364|workflow-framework" ' + MEMORY + ' | head -20')
        self.assertEqual(context_trace_errors(self.trace(command)), [])

    def test_registry_does_not_authorize_following_a_pointer(self):
        for path, label in (('/repo/.codex/sessions/old.jsonl', 'session_log'),
                            ('/repo/.codex/memories/rollout_summaries/old.md', 'memory_directory'),
                            ('/repo/.codex/memories/raw_memories.md', 'memory_path')):
            with self.subTest(path=path):
                trace = self.trace('cat ' + MEMORY, path)
                trace['tool_trace'].append({'tool': 'exec_command', 'arguments': {'cmd': 'cat ' + path}})
                self.assertIn('forbidden_context_reference:' + label, context_trace_errors(trace))
                self.assertIn('forbidden_context_reference:' + label,
                              context_trace_errors(self.trace('cat ' + MEMORY + '; cat ' + path)))

    def test_registry_exception_does_not_allow_writes_or_helpers(self):
        for command in ('rm ' + MEMORY, 'echo replaced > ' + MEMORY,
                        'cat ' + MEMORY + '; echo replaced >> ' + MEMORY,
                        'cat ' + MEMORY + '; python3 -c "open(\'' + MEMORY + '\',\'w\').write(\'x\')"',
                        'sed -n "1p;w /tmp/copy" ' + MEMORY,
                        'rg --pre /tmp/helper issue ' + MEMORY,
                        'cat ' + MEMORY + '/old.jsonl', 'cat ' + MEMORY + '.backup',
                        'cat /repo/.thoughts/OLD/runs/MEMORY.md',
                        'cat /repo/.codex/memories/rollout_summaries/MEMORY.md',
                        'cat /repo/.thoughts/OLD/runs/memories/MEMORY.md'):
            with self.subTest(command=command):
                self.assertTrue(context_trace_errors(self.trace(command)))

    def test_background_does_not_become_task_evidence(self):
        self.assertTrue(any(pattern.search(MEMORY) for _, pattern in FORBIDDEN_REPORT_CONTEXT_PATTERNS))
        self.assertIn('forbidden_context_reference:memory_citation', context_trace_errors(
            {'events': [{'evidence': '<oai-mem-citation>MEMORY.md:1-3</oai-mem-citation>'}]}))

    def test_analytical_merge_requires_current_sources_for_findings(self):
        root = Path(__file__).resolve().parents[1]
        packet = json.loads((root / 'templates/finalization_packet.json').read_text())
        packet['identity'].update({'Run ID': 'current', 'Lifecycle': 'planning'})
        bindings = {'playbook': 'feature_delivery', 'worker_contracts': {'current_state_investigator': {}}}
        result = {'run_id': 'current', 'worker_result': dict.fromkeys(packet['worker_results'][0], 'Current facts'),
                  'evidence': [{**dict.fromkeys(packet['evidence'][0], 'Current facts'),
                                'Evidence ID': 'E-FC-1', 'Source': MEMORY}],
                  'claims': [], 'decisions': [], 'actions': []}
        result['worker_result'].update({'Worker': 'feature-context', 'Outcome': 'complete'})
        for source in (MEMORY, 'MEMORY.md:10-20'):
            result['evidence'][0]['Source'] = source
            with self.assertRaisesRegex(ValueError, 'background_memory_not_task_evidence:E-FC-1'):
                validated_result(packet, result, bindings, 'current_state_investigator')
        result['evidence'][0]['Source'] = '/repo/current.py:20'
        validated_result(packet, result, bindings, 'current_state_investigator')

    def test_background_citation_stays_outside_the_analytical_envelope(self):
        envelope = {'output': 'Verified current source', 'result': {'run_id': 'current'}}
        citation = ('\n<oai-mem-citation>\n<citation_entries>\nMEMORY.md:1-2|note=[style guidance]\n'
                    '</citation_entries>\n<rollout_ids>\n</rollout_ids>\n</oai-mem-citation>')
        self.assertEqual(worker_response_value(json.dumps(envelope) + citation, Path('unused')), envelope)
        with tempfile.TemporaryDirectory() as directory:
            response = json.dumps(envelope) + citation
            receipt = _materialize_worker_response(Path(directory), 'worker', '2026-11-05T00:00:00Z',
                                                   response, {}, Path('unused'))
            self.assertEqual(Path(receipt['response_path']).read_text(), response)
            self.assertEqual(json.loads(Path(receipt['path']).read_text()), envelope['result'])
            self.assertEqual(Path(receipt['output_path']).read_text(), envelope['output'])
        for suffix in (citation.replace('MEMORY.md', 'rollout_summaries/old.md'),
                       citation + 'more prose', citation.replace('</citation_entries>', ''),
                       citation + citation):
            with self.assertRaisesRegex(ValueError, 'worker_final_response_json_invalid'):
                worker_response_value(json.dumps(envelope) + suffix, Path('unused'))

    def test_only_standalone_background_reads_can_precede_preflight(self):
        audit = lambda command: _preflight_order_errors(
            [{'name': 'exec_command', 'arguments': {'cmd': command}}], Path('/framework'), {})
        self.assertEqual(audit('rg -n issue ' + MEMORY), [])
        for command in ('cat ' + MEMORY + ' /repo/code.py',
                        'cat ' + MEMORY + '; cat /repo/code.py',
                        'rg -n issue ' + MEMORY + ' /repo'):
            self.assertIn('parent_framework_content_before_preflight', audit(command))

    def test_parent_read_does_not_authorize_a_linked_chat(self):
        parent = '00000000-0000-0000-0000-000000000001'
        other = '00000000-0000-0000-0000-000000000002'
        rows = [{'type': 'session_meta', 'payload': {'id': parent}},
                {'type': 'turn_context', 'payload': {'turn_id': parent}},
                {'type': 'response_item', 'payload': {'type': 'function_call', 'name': 'exec_command',
                    'arguments': json.dumps({'cmd': 'cat ' + MEMORY})}}]
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'current.jsonl'
            def audit():
                source.write_text(''.join(json.dumps(row) + '\n' for row in rows))
                return parent_context_audit(source, related_run_thread_ids=())
            self.assertEqual(audit()['status'], 'passed')
            rows.append({'type': 'response_item', 'payload': {'type': 'function_call',
                'name': 'mcp__codex_app__read_thread', 'arguments': json.dumps({'threadId': other})}})
            self.assertIn('parent_unassigned_thread_read:' + other, audit()['errors'])


if __name__ == '__main__':
    unittest.main()
