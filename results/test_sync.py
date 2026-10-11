import hashlib
import hmac
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from storage import Store
import sync


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.state = dict(participant='0123456789abcdef', version=sync.SCHEMA['version'],
                          mode='core', started=True, complete=True, screened_out=False,
                          answers={'S03': 'c1', 'Q14': 0, 'Q23': 'refused', 'Q32': 'c1',
                                   'Q01_note': 'Длинное пояснение', 'Q07': ['c1', 'c2']})
        self.store.save(987654321, self.state)
        self.store.save_contact(self.state['participant'], '@private_test_contact')

    def tearDown(self):
        self.store.db.close()
        self.store.contacts.close()
        self.temp.cleanup()

    def test_zero_refusal_notes_and_codes(self):
        result = sync.snapshot(self.temp.name)
        fields = dict(zip(sync.FIELDS, result['records'][0][10:]))
        self.assertEqual(fields['Q14'], 0)
        self.assertEqual(fields['Q23'], 'refused')
        self.assertEqual(fields['Q01_note'], 'Длинное пояснение')
        self.assertEqual(fields['Q07'], 'c1; c2')
        self.assertEqual(result['records'][0][2], '')

    def test_contacts_and_chat_id_separated(self):
        result = sync.snapshot(self.temp.name)
        self.assertNotIn('987654321', json.dumps(result))
        self.assertNotIn('@private_test_contact', json.dumps(result['records']))
        self.assertEqual(result['contacts'][0][4], '@private_test_contact')
        self.assertEqual(result['contacts'][0][5], 'Q32:c1')

    def test_replay_stable_rows_and_updates(self):
        first = sync.snapshot(self.temp.name)
        self.assertEqual(first['records'], sync.snapshot(self.temp.name)['records'])
        self.state['answers']['Q14'] = 320
        self.store.save(987654321, self.state)
        changed = sync.snapshot(self.temp.name)
        self.assertEqual(first['records'][0][1], changed['records'][0][1])
        self.assertNotEqual(first['records'], changed['records'])

    def test_deletion_reconciles_both_sources(self):
        self.store.delete(987654321)
        result = sync.snapshot(self.temp.name)
        self.assertEqual(result['records'], [])
        self.assertEqual(result['contacts'], [])

    def test_revoked_consent_excludes_stale_contact(self):
        self.state['answers']['Q32'] = 'c2'
        self.store.save(987654321, self.state)
        self.assertEqual(sync.snapshot(self.temp.name)['contacts'], [])

    def test_intro_not_exported_and_test_flag(self):
        self.assertEqual(sync.snapshot(self.temp.name, [self.state['participant']])['records'][0][8], 'Да')
        self.state['started'] = False
        self.store.save(987654321, self.state)
        self.assertEqual(sync.snapshot(self.temp.name)['records'], [])

    def test_missing_or_corrupt_source_fails_closed(self):
        self.store.db.execute('UPDATE sessions SET state=?', ('not JSON',))
        self.store.db.commit()
        with self.assertRaises(ValueError):
            sync.snapshot(self.temp.name)
        with tempfile.TemporaryDirectory() as empty:
            with self.assertRaises(sqlite3.OperationalError):
                sync.snapshot(empty)

    def test_snapshot_does_not_write_databases(self):
        paths = [Path(self.temp.name) / name for name in ('responses.sqlite', 'contacts.sqlite')]
        before = [p.read_bytes() for p in paths]
        sync.snapshot(self.temp.name)
        self.assertEqual(before, [p.read_bytes() for p in paths])

    def test_exclusive_source_lock_never_emits_empty_snapshot(self):
        db = sqlite3.connect(Path(self.temp.name) / 'responses.sqlite')
        try:
            db.execute('BEGIN EXCLUSIVE')
            with self.assertRaises(sqlite3.OperationalError):
                sync.snapshot(self.temp.name)
        finally:
            db.rollback()
            db.close()

    def test_signature_covers_exact_unicode_body(self):
        payload = sync.snapshot(self.temp.name)
        secret = 'synthetic-test-key-never-used-in-production'
        envelope = json.loads(sync.envelope(payload, secret))
        expected = hmac.new(secret.encode(), envelope['body'].encode(), hashlib.sha256).hexdigest()
        self.assertEqual(envelope['signature'], expected)
        self.assertEqual(json.loads(envelope['body']), payload)
        with self.assertRaises(ValueError):
            sync.send(payload, 'http://example.com', secret)


if __name__ == '__main__':
    unittest.main()
