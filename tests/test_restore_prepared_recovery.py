"""Restore only an undispatched planning recovery, preserving both generations."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import restore_prepared_recovery as repair


class RestorePreparedRecovery(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.prior, self.current = 'ITEM-old', 'ITEM-new'
        parent = {'provider_session': str(self.root / 'parent.jsonl'),
                  'parent_thread_id': '00000000-0000-0000-0000-000000000001'}
        bindings = {'run_id': self.prior, 'parent_context': parent,
                    'runtime_evidence': {'run_started_at': '2026-11-06T00:00:00Z'}}
        packet = {'identity': {'Run ID': self.prior, 'Lifecycle': 'planning', 'State': 'ready_for_implementation'}}
        (self.root / 'finalization_packet.json').write_text(json.dumps(packet))
        (self.root / 'role_bindings.json').write_text(json.dumps(bindings))
        (self.root / 'notes.md').write_text('Accepted original findings\n')
        self.original = {name: (self.root / name).read_bytes()
                         for name in ('finalization_packet.json', 'role_bindings.json', 'notes.md')}
        self.archive = repair._archive_recovery(self.root, self.prior)
        packet = {'identity': {'Run ID': self.current, 'Lifecycle': 'planning', 'State': 'in_progress'},
                  'recovery': {'Prior run ID': self.prior, 'Prior artifacts': str(self.archive)}}
        bindings['run_id'] = self.current
        (self.root / 'finalization_packet.json').write_text(json.dumps(packet))
        (self.root / 'role_bindings.json').write_text(json.dumps(bindings))
        (self.root / 'notes.md').write_text('Prepared recovery notes\n')
        self.before = {name: (self.root / name).read_bytes() for name in self.original}
        self.ledger = {'events': [], 'failed_dispatches': []}
        probe = patch.object(repair, 'read_runtime_events', return_value=self.ledger)
        probe.start()
        self.addCleanup(probe.stop)
        identity = patch.object(repair, 'validate_prepared_provider_source')
        self.identity = identity.start()
        self.addCleanup(identity.stop)

    def test_preview_then_restore_preserves_both_generations(self):
        preview = repair.restore(self.root, self.current, self.prior, check_only=True)
        self.assertEqual(preview['status'], 'verified')
        self.assertFalse((self.root / 'runs' / self.current).exists())
        for name in self.before:
            self.assertEqual((self.root / name).read_bytes(), self.before[name])
        result = repair.restore(self.root, self.current, self.prior)
        self.assertEqual(result['run_id'], self.prior)
        self.identity.assert_called_once()
        for name in self.original:
            self.assertEqual((self.root / name).read_bytes(), self.original[name])
        preserved = self.root / 'runs' / self.current
        manifest = json.loads((preserved / 'archive_manifest.json').read_text())
        for row in manifest['files']:
            self.assertEqual((preserved / row['snapshot']).read_bytes(), self.before[row['path']])

    def test_dispatch_or_corrupt_archive_blocks_before_mutation(self):
        for failure in ('dispatch', 'hash', 'path'):
            with self.subTest(failure=failure):
                if failure == 'dispatch':
                    self.ledger['events'] = [{'Operation': 'spawn_agent'}]
                manifest_path = self.archive / 'archive_manifest.json'
                manifest_bytes = manifest_path.read_bytes()
                manifest = json.loads(manifest_bytes)
                if failure == 'hash':
                    manifest['files'][0]['sha256'] = '0' * 64
                if failure == 'path':
                    manifest['files'][0]['path'] = '../outside'
                manifest_path.write_text(json.dumps(manifest))
                with self.assertRaises(ValueError):
                    repair.restore(self.root, self.current, self.prior)
                for name in self.before:
                    self.assertEqual((self.root / name).read_bytes(), self.before[name])
                self.assertFalse((self.root / 'runs' / self.current).exists())
                self.ledger['events'] = []
                manifest_path.write_bytes(manifest_bytes)

    def test_failed_restore_rolls_back_current_files(self):
        replace = repair._replace
        calls = 0

        def fail_once(path, data):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError('simulated restore failure')
            return replace(path, data)

        with patch.object(repair, '_replace', side_effect=fail_once), self.assertRaises(OSError):
            repair.restore(self.root, self.current, self.prior)
        for name in self.before:
            self.assertEqual((self.root / name).read_bytes(), self.before[name])
        self.assertTrue((self.root / 'runs' / self.current / 'archive_manifest.json').is_file())
