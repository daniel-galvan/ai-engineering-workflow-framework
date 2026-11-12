"""Fresh starts preserve prior files without turning archival into recovery."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.prepare_run import _archive_existing_run
from scripts import prepare_run as preparation
from scripts import finalize_work_record as finalizer


class FreshStartArchival(unittest.TestCase):
    def test_prior_decision_availability_is_preserved_without_reading_history(self):
        for supplied in (False, True):
            with self.subTest(supplied=supplied), tempfile.TemporaryDirectory() as directory:
                repository = Path(directory)
                root = repository / '.thoughts' / 'ITEM-77'
                old = root / 'runs' / 'ITEM-77-old' / 'decisions.md'
                old.parent.mkdir(parents=True)
                old.write_text('Prior decision is not automatically read')
                inputs = [{'Input ID': 'IN-1', 'Input or artifact': 'Current issue',
                           'Source or path': 'User', 'Authority': 'User', 'Status': 'Registered'}]
                if supplied:
                    inputs.append({'Input ID': 'IN-2', 'Input or artifact': 'User-selected prior decision',
                                   'Source or path': str(old), 'path': str(old),
                                   'sha256': hashlib.sha256(old.read_bytes()).hexdigest(), 'Authority': 'User',
                                   'Classification': 'decision continuity', 'Status': 'Registered'})
                run = preparation.prepare_run(repository, 'ITEM-77', 'techops_issue_remediation', None, False,
                                              input_data={'inputs': inputs})
                self.assertEqual(run['prior_decisions_unreviewed'], not supplied)
                resumed = preparation.prepare_run(repository, 'ITEM-77', 'techops_issue_remediation', None, True)
                self.assertEqual(resumed['prior_decisions_unreviewed'], not supplied)
                if supplied:
                    rows = json.loads(Path(resumed['run_input_manifest']['path']).read_text())['inputs']
                    selected = next(row for row in rows if row['Input ID'] == 'IN-2')
                    self.assertEqual(Path(selected['path']).read_text(), old.read_text())
                    self.assertEqual(Path(selected['Original source path']).resolve(), old.resolve())
                packet_path = Path(resumed['finalization_packet'])
                packet = json.loads(packet_path.read_text())
                packet['handoff']['established'] = []
                finalizer._normalize_packet(packet, {'runtime_closure': [], 'terminal_observations': []}, packet_path)
                notice = 'Earlier run decisions were not reviewed; no prior decision source was supplied.'
                self.assertEqual(notice in packet['handoff']['established'], not supplied)
                self.assertEqual(old.read_text(), 'Prior decision is not automatically read')

    def test_incomplete_and_unpublished_attempts_are_preserved_without_import(self):
        for state in ("prepared", "orphaned", "malformed", "unpublished"):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / '.thoughts' / 'ITEM-77'
                root.mkdir(parents=True)
                (root / 'old_findings.md').write_text('OLD_FINDINGS_ARE_HISTORY_ONLY')
                if state != 'orphaned':
                    (root / 'role_bindings.json').write_text(json.dumps({'run_id': 'ITEM-77-prior',
                        'parent_context': {'parent_thread_id': '00000000-0000-0000-0000-000000000009',
                                           'provider_session': '/never/read/old-chat.jsonl'}}))
                    (root / 'finalization_packet.json').write_text(json.dumps({'identity': {
                        'Run ID': 'ITEM-77-prior', 'State': '' if state == 'prepared' else 'completed'},
                        'workers': [], 'claims': [{'Claim': 'Prior findings must stay opaque'}]}))
                    (root / 'work_record.md').write_text('Old incomplete or unpublished report')
                if state == 'malformed':
                    (root / 'role_bindings.json').write_bytes(b'{unfinished JSON')
                    (root / 'runtime_dispatches.json').write_bytes(b'{unfinished JSON')
                before = {p.name: p.read_bytes() for p in root.iterdir()}
                read_text = Path.read_text
                def control_only(path, *args, **kwargs):
                    if path.parent == root and path.name not in {'role_bindings.json', 'runtime_dispatches.json'}:
                        raise AssertionError('No prior analytical content reads: ' + path.name)
                    return read_text(path, *args, **kwargs)
                with patch('scripts.provider_runtime.read_runtime_events', side_effect=AssertionError('No old session reads')), \
                     patch.object(Path, 'read_text', control_only):
                    archive = Path(_archive_existing_run(root, False, fresh_start=True))
                for name, content in before.items():
                    self.assertEqual((archive / name).read_bytes(), content)
                self.assertEqual({p.name for p in root.iterdir()}, {'runs'})

    def test_explicit_active_worker_blocks_before_any_files_move(self):
        for status in (None, 'running', {'pending_init': 'Starting'}):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / '.thoughts' / 'ITEM-77'
                root.mkdir(parents=True)
                (root / 'work_record.md').write_text('Keep current writer files intact')
                ledger = {'events': [], 'thread_mappings': {'/root/worker': '00000000-0000-0000-0000-000000000001'},
                    'failed_dispatches': [], 'timing': {'open_worker_intervals': 1 if status is None else 0}}
                if status is not None:
                    ledger['inventories'] = [{'Observed at': '2026-11-01T00:00:02Z', 'raw_response': {'agents': [
                        {'agent_name': '/root/worker', 'agent_status': status}]}}]
                (root / 'runtime_dispatches.json').write_text(json.dumps(ledger))
                before = {p.name: p.read_bytes() for p in root.iterdir()}
                with self.assertRaisesRegex(ValueError, 'run_already_active'):
                    _archive_existing_run(root, False, fresh_start=True)
                self.assertEqual({p.name: p.read_bytes() for p in root.iterdir()}, before)

    def test_terminal_status_allows_archival_when_activity_end_events_are_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / '.thoughts' / 'ITEM-77'
            root.mkdir(parents=True)
            ledger = {'events': [{'Operation': 'spawn_agent', 'Provider handle': '/root/worker',
                'Thread ID': '00000000-0000-0000-0000-000000000001', 'Last dispatch at': '2026-11-01T00:00:01Z'}],
                'failed_dispatches': [], 'thread_mappings': {'/root/worker': '00000000-0000-0000-0000-000000000001'},
                'timing': {'open_worker_intervals': 1}, 'inventories': [{'Observed at': '2026-11-01T00:00:02Z',
                    'raw_response': {'agents': [{'agent_name': '/root/worker', 'agent_status': 'completed'}]}}]}
            (root / 'runtime_dispatches.json').write_text(json.dumps(ledger))
            original = (root / 'runtime_dispatches.json').read_bytes()
            archive = Path(_archive_existing_run(root, False, fresh_start=True))
            self.assertEqual((archive / 'runtime_dispatches.json').read_bytes(), original)

    def test_archive_move_failure_restores_every_prior_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / '.thoughts' / 'ITEM-77'
            root.mkdir(parents=True)
            for name in ('first.md', 'second.md'):
                (root / name).write_text('Original ' + name)
            original = {p.name: p.read_bytes() for p in root.iterdir()}
            move, calls = preparation.shutil.move, []
            def interrupted(source, destination):
                calls.append(source)
                if len(calls) == 2:
                    raise OSError('Controlled archive interruption')
                return move(source, destination)
            with patch.object(preparation.shutil, 'move', side_effect=interrupted):
                with self.assertRaisesRegex(OSError, 'Controlled archive interruption'):
                    _archive_existing_run(root, False, fresh_start=True)
            self.assertEqual({p.name: p.read_bytes() for p in root.iterdir() if p.is_file()}, original)
            self.assertEqual(list((root / 'runs').iterdir()), [])

    def test_archive_name_collision_preserves_both_attempts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / '.thoughts' / 'ITEM-77'
            prior = root / 'runs' / 'ITEM-77-prior'
            prior.mkdir(parents=True)
            (prior / 'earlier.md').write_text('Earlier archive')
            (root / 'role_bindings.json').write_text(json.dumps({'run_id': 'ITEM-77-prior'}))
            archive = Path(_archive_existing_run(root, False, fresh_start=True))
            self.assertNotEqual(archive, prior)
            self.assertEqual((prior / 'earlier.md').read_text(), 'Earlier archive')
            self.assertTrue((archive / 'role_bindings.json').is_file())
