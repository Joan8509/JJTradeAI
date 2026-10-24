from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import vps_private_runtime as runtime


def config():
    return {'format': 1, 'owner_sid': 'S-1-5-21-1-2-3-500', 'feed': 'iex',
            'ALPACA_API_KEY': 'test-key', 'ALPACA_API_SECRET': 'test-secret',
            'TELEGRAM_BOT_TOKEN': '123:test_fake_token', 'TELEGRAM_CHAT_ID': '456'}


class PrivateRuntimeTests(unittest.TestCase):
    def test_identity_mismatch_and_malformed_fields_fail(self):
        sample = config()
        self.assertEqual(runtime.validate_config(sample, sample['owner_sid']), sample)
        with self.assertRaises(ValueError):
            runtime.validate_config(sample, 'S-1-5-21-9-500')
        for field in runtime.FIELDS:
            broken = {**sample, field: ''}
            with self.assertRaises(ValueError):
                runtime.validate_config(broken, broken['owner_sid'])

    def test_no_gate_never_loads_secrets_or_worker(self):
        with patch.object(runtime, 'authorized', return_value=False), \
             patch.object(runtime, 'load_config') as load, patch.object(runtime.runpy, 'run_path') as run:
            self.assertEqual(runtime.run_worker('collector'), 5)
            load.assert_not_called()
            run.assert_not_called()

    def test_role_environments_have_no_cross_role_secrets(self):
        sample = config()
        inherited = {'PATH': 'somewhere', 'ALPACA_STALE': 'bad', 'TELEGRAM_ALERTS_ENABLED': 'true'}
        collector = runtime.worker_environment('collector', sample, inherited)
        radar = runtime.worker_environment('radar', sample, inherited)
        self.assertNotIn('TELEGRAM_BOT_TOKEN', collector)
        self.assertNotIn('TELEGRAM_ALERTS_ENABLED', collector)
        self.assertNotIn('ALPACA_API_SECRET', radar)
        self.assertNotIn('ALPACA_STALE', collector)
        for args in (runtime.worker_arguments('collector'), runtime.worker_arguments('radar')):
            self.assertTrue(all(value not in args for value in (sample[n] for n in runtime.FIELDS)))
        self.assertIn('--data-only', runtime.worker_arguments('collector'))

    def test_probe_writes_only_safe_receipt_without_starting_worker(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(runtime, 'PRIVATE', Path(tmp)), \
             patch.object(runtime, 'VAULT', Path(tmp) / 'vault'), \
             patch.object(runtime, 'load_config', return_value=config()), \
             patch.object(runtime, 'historical_chats', return_value={'456'}), \
             patch.object(runtime, 'session_id', return_value=0), \
             patch.object(runtime.runpy, 'run_path') as run, \
             patch('socket.socket.connect', side_effect=AssertionError('No network')):
            runtime.VAULT.write_bytes(b'ciphertext-placeholder')
            self.assertEqual(runtime.check('collector', 'fresh-test'), 0)
            output = (Path(tmp) / 'collector.probe.json').read_text()
            receipt = json.loads(output)
            self.assertEqual(receipt['status'], 'LOCAL_ACCESS_OK')
            self.assertFalse(receipt['worker_started'])
            self.assertFalse(receipt['network_used'])
            for field in runtime.FIELDS:
                self.assertNotIn(config()[field], output)
            run.assert_not_called()

    def test_probe_failure_never_serializes_exception(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(runtime, 'PRIVATE', Path(tmp)), \
             patch.object(runtime, 'load_config', side_effect=ValueError('secret-in-exception')):
            self.assertEqual(runtime.check('radar', 'new'), 2)
            self.assertNotIn('secret-in-exception', (Path(tmp) / 'radar.probe.json').read_text())

    def test_chat_mismatch_blocks_probe(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(runtime, 'PRIVATE', Path(tmp)), \
             patch.object(runtime, 'load_config', return_value=config()), \
             patch.object(runtime, 'historical_chats', return_value={'789'}):
            self.assertEqual(runtime.check('radar', 'mismatch'), 2)

    def test_historical_chat_extraction_is_readonly(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'db.db'
            with closing(sqlite3.connect(path)) as db, db:
                db.execute('CREATE TABLE bollinger_phone_notifications (event_key TEXT)')
                db.execute("INSERT INTO bollinger_phone_notifications VALUES ('v1|456|ALPACA|iex|QQQ|2026-10-14T14:00:00+00:00|SUPERIOR')")
            before = path.read_bytes()
            self.assertEqual(runtime.historical_chats(path), {'456'})
            self.assertEqual(before, path.read_bytes())

    def test_incomplete_gate_never_authorizes(self):
        with tempfile.TemporaryDirectory() as tmp:
            gate = Path(tmp) / 'gate.json'
            gate.write_text(json.dumps({'pc_writers_stopped': True}))
            self.assertFalse(runtime.authorized('collector', gate))

    def test_raw_worker_logs_are_not_persisted(self):
        stream = runtime.DiscardedWorkerOutput()
        for text in ('secret-fragment', ':and-more', '\n'):
            self.assertEqual(stream.write(text), len(text))
            stream.flush()
        self.assertFalse(hasattr(stream, 'buffer'))
