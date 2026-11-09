"""Shared lifecycle contracts through shipped commands, without live tickets or chat reads."""

import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from tests import test_packaged_lifecycle as packaging
from tests import test_planning_command_path as planning


PLAYBOOKS = (('feature_delivery', None), ('feature_delivery', 'specification_assessment'),
             ('techops_issue_remediation', None), ('sentry_issue_remediation', None),
             ('technical_spike', None), ('vulnerability_investigation', None))


class RuntimeLifecycleContract(unittest.TestCase):
    def test_published_worker_runs_allow_the_next_fresh_run_without_old_chat_access(self):
        for playbook in ("feature_delivery", "techops_issue_remediation"):
            for remediation in (False, True):
                with self.subTest(playbook=playbook, remediation=remediation):
                    planning.PlanningCommandPath().planning_path(
                        playbook, continue_to_remediation=remediation, start_next_run=True)

    def append(self, kind, **payload):
        with self.source.open('a') as stream:
            stream.write(json.dumps({'timestamp': datetime.now(timezone.utc).isoformat(),
                                     'type': kind, 'payload': payload}) + '\n')

    def new_turn(self, new_chat=False):
        if new_chat:
            self.parent = str(uuid4())
            self.source = self.sessions / ('rollout-' + self.parent + '.jsonl')
            self.append('session_meta', id=self.parent, cwd=str(self.worktree))
        self.append('turn_context', turn_id=str(uuid4()))
        self.append('response_item', type='message', role='user', content=[{
            'type': 'input_text', 'text': 'Controlled lifecycle contract; use only current supplied inputs.'}])

    def command(self, script, *args, stdin=None, expected=0):
        arguments = [sys.executable, str(self.package / 'scripts' / script), *map(str, args)]
        command = shlex.join(arguments)
        # Provider records must retain the literal stdin transport, not silently omit its inputs.
        if stdin is not None:
            command += " <<'CONTRACT_INPUT_JSON'\n" + stdin + '\nCONTRACT_INPUT_JSON'
        call = str(uuid4())
        self.append('response_item', type='function_call', name='exec_command', call_id=call,
                    arguments=json.dumps({'cmd': command, 'workdir': str(self.worktree)}))
        environment = {**os.environ, 'CODEX_THREAD_ID': self.parent, 'CODEX_SESSION_ID': '',
                       'CODEX_HOME': str(self.sessions.parent)}
        result = subprocess.run(arguments, cwd=self.worktree, input=stdin, env=environment,
                                capture_output=True, text=True, timeout=30)
        self.append('event_msg', type='item_completed', item={'type': 'CommandExecution',
                    'command': ['bash', '-lc', command], 'status': 'completed' if result.returncode == 0 else 'failed',
                    'exit_code': result.returncode, 'aggregated_output': result.stdout})
        self.append('response_item', type='function_call_output', call_id=call, output=result.stdout)
        self.assertEqual(result.returncode, expected, script + '\n' + result.stdout + result.stderr)
        return result.stdout

    def projection(self, item):
        result = json.loads(self.command('prepare_run.py', '--status-projection',
                            '--execution-repository', self.main, '--work-item', item))
        self.assertEqual(result['prior_thread_ids'], [], 'A closed run must not trigger old-chat reads')
        call = str(uuid4())
        self.append('response_item', type='custom_tool_call', name='exec', call_id=call,
                    input=result['projection'])
        # With no identities, the generated program must not call a provider at all.
        if shutil.which('node'):
            program = ("const tools = new Proxy({}, {get() {throw new Error('Old chat access');}});\n"
                       "const text = value => process.stdout.write(value);\n" + result['projection'])
            observed = subprocess.run(['node', '--input-type=module', '-'], input=program,
                                      capture_output=True, text=True, timeout=10)
            self.assertEqual(observed.returncode, 0, observed.stderr)
            self.assertEqual(json.loads(observed.stdout), [])
        self.append('response_item', type='custom_tool_call_output', call_id=call,
                    output=[{'type': 'text', 'text': '[]'}])

    def prepare(self, playbook, item, profile, inputs=None, continuation=False, objective=None):
        args = ['--execution-repository', self.main, '--work-item', item, '--playbook', playbook,
                '--execution-profile', profile, '--lifecycle', 'planning']
        if objective:
            args.extend(['--workflow-objective', objective, '--requested-outcome', objective])
        if playbook == 'technical_spike':
            args.extend(['--primary-question', 'What behavior does this controlled source implement?',
                         '--started-at', self.started_at])
        if continuation:
            args.extend(['--continuation', '--input-manifest', self.main / '.thoughts' / item / 'run_inputs.json'])
            stdin = None
        else:
            args.extend(['--input-json', '-'])
            stdin = json.dumps(inputs)
        return json.loads(self.command('prepare_run.py', *args, stdin=stdin))

    def end_failure(self, run):
        packet = Path(run['finalization_packet'])
        self.command('finalize_work_record.py', '--packet', packet, '--workflow-failure',
                     'controlled_pre_dispatch_failure', expected=2)
        root = Path(run['artifact_root'])
        failure = json.loads((root / 'finalization_failure.json').read_text())
        self.assertEqual(failure['runtime_closure'], 'terminal')
        response = root / 'handoff_response.md'
        published = self.command('finalize_work_record.py', '--packet', packet, '--publish-response', response)
        self.assertEqual(published.encode(), response.read_bytes())
        self.assertEqual(json.loads((root / 'handoff_delivery.json').read_text())['status'], 'verified')

    def workspace(self, directory):
        root = Path(directory).resolve()
        self.package = packaging.PackagedLifecycle().package(directory)
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.main = root / 'project with spaces'
        self.main.mkdir()
        self.worktree = root / 'active worktree'
        self.sessions = root / 'native' / 'sessions'
        self.sessions.mkdir(parents=True)
        for args in (('init', '-q'), ('config', 'user.name', 'Contract fixture'),
                     ('config', 'user.email', 'fixture@example.invalid'),
                     ('commit', '--allow-empty', '-qm', 'Contract baseline'),
                     ('worktree', 'add', '--detach', str(self.worktree))):
            subprocess.run(['git', '-C', str(self.main), *args], check=True, capture_output=True)
        guide = root / "guide's notes.md"
        guide.write_text('Current supplied guidance — keep quoted inputs intact.\n')
        inputs = {'schema_version': 1, 'status': 'explicit', 'inputs': [
            {'Input ID': 'IN-001', 'Input or artifact': 'Current independent request',
             'Source or path': 'Current user request', 'Authority': 'User', 'Status': 'Verified'},
            {'Input ID': 'IN-002', 'Input or artifact': 'Current supplied guidance',
             'Source or path': str(guide), 'Authority': 'User', 'Status': 'Readable',
             'Classification': 'supporting artifact', 'Asset source': True},
        ]}
        return inputs

    def test_fresh_start_archives_incomplete_attempts_across_playbooks_and_profiles(self):
        with tempfile.TemporaryDirectory() as directory:
            inputs = self.workspace(directory)
            for index, (playbook, objective) in enumerate(PLAYBOOKS):
                for profile in ('standard', 'deep'):
                    with self.subTest(playbook=playbook, profile=profile, objective=objective):
                        item = f'NEW-{index}-{profile}'
                        artifact_root = self.main / '.thoughts' / item
                        artifact_root.mkdir(parents=True)
                        old_id = item + '-prior'
                        (artifact_root / 'role_bindings.json').write_text(json.dumps({'run_id': old_id,
                            'parent_context': {'parent_thread_id': str(uuid4()), 'provider_session': '/never/open/old-chat.jsonl'}}))
                        (artifact_root / 'finalization_packet.json').write_text(json.dumps({'identity': {
                            'Run ID': old_id, 'State': '', 'Workflow outcome': ''}, 'workers': []}))
                        (artifact_root / 'work_record.md').write_text('PREVIOUS_FINDINGS_MUST_NOT_BECOME_INPUTS')
                        (artifact_root / 'unfinished.bin').write_bytes(b'preserve incomplete bytes\xff')
                        previous = {p.name: p.read_bytes() for p in artifact_root.iterdir()}
                        self.new_turn(new_chat=True)
                        self.command('run_preflight.py')
                        self.projection(item)
                        supplied = json.loads(json.dumps(inputs))
                        if objective:
                            supplied['inputs'].append({'Input ID': 'RUN-GOAL-001',
                                'Input or artifact': 'Requested outcome: ' + objective,
                                'Source or path': 'Current user request', 'Authority': 'Explicit user outcome',
                                'Classification': 'requested outcome', 'Expected use': 'Validate playbook and objective selection',
                                'Status': 'Registered'})
                        run = self.prepare(playbook, item, profile, supplied, objective=objective)
                        self.assertEqual(run['artifact_root'], str(artifact_root))
                        self.assertEqual(run['source_checkout'], str(self.worktree))
                        self.assertNotEqual(run['run_id'], old_id)
                        archive = Path(run['archived_prior_run'])
                        self.assertEqual(archive, artifact_root / 'runs' / old_id)
                        for name, content in previous.items():
                            self.assertEqual((archive / name).read_bytes(), content)
                        packet = json.loads(Path(run['finalization_packet']).read_text())
                        self.assertNotIn('recovery', packet)
                        self.assertNotIn('reentry', packet)
                        self.assertNotIn('PREVIOUS_FINDINGS', json.dumps(packet))
                        self.assertFalse((self.worktree / '.thoughts').exists())

    def test_start_end_recover_and_start_again_across_playbooks_and_profiles(self):
        with tempfile.TemporaryDirectory() as directory:
            inputs = self.workspace(directory)
            for index, (playbook, objective) in enumerate(PLAYBOOKS):
                for profile in ('standard', 'deep'):
                    with self.subTest(playbook=playbook, objective=objective, profile=profile):
                        item = f'CONTRACT-{index}-{profile}'
                        self.new_turn(new_chat=True)
                        self.command('run_preflight.py')
                        self.projection(item)
                        supplied = json.loads(json.dumps(inputs))
                        if objective:
                            supplied['inputs'].append({'Input ID': 'RUN-GOAL-001',
                                'Input or artifact': 'Requested outcome: ' + objective,
                                'Source or path': 'Current user request', 'Authority': 'Explicit user outcome',
                                'Classification': 'requested outcome', 'Expected use': 'Validate playbook and objective selection',
                                'Status': 'Registered'})
                        run = self.prepare(playbook, item, profile, supplied, objective=objective)
                        self.assertEqual(run['source_checkout'], str(self.worktree))
                        self.assertEqual(Path(run['artifact_root']), self.main / '.thoughts' / item)
                        self.assertIn('runtime_evidence', run)
                        self.end_failure(run)
                        artifact_root = Path(run['artifact_root'])
                        failure_bytes = (artifact_root / 'finalization_failure.json').read_bytes()
                        start = run['runtime_evidence']['run_started_at']
                        original_id = run['run_id']
                        self.new_turn()
                        self.command('run_preflight.py')
                        self.projection(item)
                        recovered = self.prepare(playbook, item, profile, continuation=True, objective=objective)
                        self.assertEqual(recovered['run_id'], original_id)
                        self.assertEqual(recovered['runtime_evidence']['run_started_at'], start)
                        self.assertFalse((artifact_root / 'finalization_failure.json').exists())
                        self.assertEqual(Path(recovered['recovered_failure']).read_bytes(), failure_bytes)
                        self.end_failure(recovered)
                        previous = {p.name: p.read_bytes() for p in artifact_root.iterdir() if p.is_file()}
                        self.new_turn(new_chat=True)
                        self.command('run_preflight.py')
                        self.projection(item)
                        fresh = self.prepare(playbook, item, profile, supplied, objective=objective)
                        self.assertNotEqual(fresh['run_id'], original_id)
                        archive = Path(fresh['archived_prior_run'])
                        for name, content in previous.items():
                            self.assertEqual((archive / name).read_bytes(), content)
                        self.assertNotIn('recovery', json.loads(Path(fresh['finalization_packet']).read_text()))
                        self.assertFalse((self.worktree / '.thoughts').exists())
