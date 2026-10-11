"""Read-only SQLite snapshot sender. Runs separately from the Telegram poller."""
import argparse
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import sqlite3
import time
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
SCHEMA = json.loads((ROOT / 'schema.json').read_text())
FIELDS = {f['id']: f for f in SCHEMA['fields']}


def clean_value(field, value):
    if value is None:
        return ''
    kind = field['type']
    codes = {o['code'] for o in field['options']}
    if kind == 'single':
        if value not in codes:
            raise ValueError('Invalid single-choice code')
        return value
    if kind == 'multi':
        if not isinstance(value, list) or any(v not in codes for v in value):
            raise ValueError('Invalid multiple-choice codes')
        return '; '.join(dict.fromkeys(value))
    if kind == 'money':
        if value in ('unknown', 'refused'):
            return value
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value < 10**12:
            raise ValueError('Invalid amount')
        return value
    if not isinstance(value, str) or len(value) > 1000:
        raise ValueError('Invalid text')
    return value


def snapshot(directory, test_ids=()):
    """Fail closed on corrupt/locked sources; never turn a failed read into an empty snapshot."""
    directory = Path(directory).resolve()
    tests = set(test_ids)
    with sqlite3.connect((directory / 'responses.sqlite').as_uri() + '?mode=ro', uri=True, timeout=10) as db:
        db.execute('BEGIN')
        states = db.execute('SELECT state,updated FROM sessions').fetchall()
    records, consented = [], set()
    for raw, updated in states:
        state = json.loads(raw)
        if not state.get('started'):
            continue
        participant = state['participant']
        if not re.fullmatch(r'[a-f0-9]{16}', participant):
            raise ValueError('Invalid participant ID')
        answers = state['answers']
        if 'Q33' in answers:
            raise ValueError('Contact found in main database')
        if state['version'] != SCHEMA['version'] or state['mode'] != 'core':
            raise ValueError('Unsupported instrument version/mode')
        status = 'Не подходит' if state.get('screened_out') else 'Завершена' if state.get('complete') else 'Не завершена'
        # The current database records the last state change, not the start time.
        row = ['Telegram', participant, '', updated * 1000, state['version'], state['mode'],
               state.get('channel', 'direct'), status, 'Да' if participant in tests else 'Нет',
               'Дата ответа не записывалась; Обновлено — последнее изменение анкеты']
        row += [clean_value(f, answers.get(f['id'])) for f in SCHEMA['fields']]
        records.append(row)
        if answers.get('Q32') == 'c1':
            consented.add(participant)
    with sqlite3.connect((directory / 'contacts.sqlite').as_uri() + '?mode=ro', uri=True, timeout=10) as db:
        db.execute('BEGIN')
        stored_contacts = db.execute('SELECT participant,contact,consent,created FROM contacts').fetchall()
    contacts = []
    for participant, contact, consent, created in stored_contacts:
        if participant in consented and consent == 'Q32:c1':
            if not isinstance(contact, str) or len(contact) > 500:
                raise ValueError('Invalid contact')
            contacts.append(['Telegram', participant, created * 1000, participant, contact, consent])
    return dict(protocol=1, generation=time.time_ns() // 1000,
                records=sorted(records, key=lambda r: r[1]), contacts=sorted(contacts, key=lambda r: r[1]))


def envelope(payload, secret):
    body = json.dumps(payload, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    signature = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return json.dumps(dict(body=body, signature=signature), ensure_ascii=False).encode()


def send(payload, endpoint, secret):
    if not re.fullmatch(r'https://script\.google\.com/macros/s/[A-Za-z0-9_-]+/exec', endpoint):
        raise ValueError('Expected the deployed Google Apps Script URL')
    if len(secret) < 32:
        raise ValueError('Sync secret is too short')
    body = envelope(payload, secret)
    if len(body) > 1_500_000 or len(payload['records']) > 1000:
        raise ValueError('Snapshot exceeds configured capacity; no data sent')
    request = Request(endpoint, data=body, headers={'Content-Type': 'application/json'}, method='POST')
    with urlopen(request, timeout=60) as response:
        result = json.loads(response.read(4096))
    if result.get('ok') is not True or result.get('generation') != payload['generation']:
        raise RuntimeError('Receiver did not confirm this snapshot')
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', default='/var/lib/whoof-survey')
    args = parser.parse_args()
    # Separate lock; never acquire the bot's poller lock.
    with open(Path(args.data) / 'sheets-sync.lock', 'a') as lock:
        os.chmod(lock.name, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        data = snapshot(args.data, filter(None, os.getenv('WHOOF_TEST_IDS', '').split(',')))
        result = send(data, os.environ['WHOOF_SHEETS_ENDPOINT'], os.environ['WHOOF_SHEETS_SECRET'])
        print(f"Sheets sync confirmed: {result['answers']} answers; {result['contacts']} contacts")


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # No participant values, credentials, request bodies or URLs in journals.
        print(f'Sheets sync failed ({type(error).__name__}); will retry on next timer run')
        raise SystemExit(1)
