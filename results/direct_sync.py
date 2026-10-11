"""Independent direct Sheets worker. Raw Forms tabs and bot data are read-only."""
import argparse
from datetime import datetime, timedelta, timezone
import fcntl
import os
from pathlib import Path
from zoneinfo import ZoneInfo
import normalize
from sheets_api import Client, ANSWERS_ID, CONTACTS_ID, RAW_TAB
from sync import snapshot


def date_serial(milliseconds, tz):
    if milliseconds == '': return ''
    date = datetime.fromtimestamp(milliseconds/1000,timezone.utc).astimezone(ZoneInfo(tz))
    return (date.replace(tzinfo=None)-datetime(1899,12,30)).total_seconds()/86400


def check_header(rows, header):
    if not rows or rows[0] != header:
        raise ValueError('Derived header mismatch')


def sync_once(client, payload):
    answers_view = client.read(ANSWERS_ID,[RAW_TAB,'Google','Telegram','Fillout','Все ответы','Сводка'])
    contacts_view = client.read(CONTACTS_ID,[RAW_TAB,'Google','Контакты'])
    av, cv = answers_view['values'], contacts_view['values']
    for name in ('Google','Telegram','Fillout','Все ответы'): check_header(av[name],normalize.HEADERS)
    check_header(cv['Контакты'],normalize.CONTACT_HEADERS)
    check_header(cv['Google'],normalize.CONTACT_GOOGLE_HEADERS)
    google_rows = normalize.answers(av[RAW_TAB])
    google_contacts = normalize.contacts(cv[RAW_TAB])
    tg_rows = [list(r) for r in payload['records']]
    tg_contacts = [list(r) for r in payload['contacts']]
    if len(tg_rows)>1000 or len(google_rows)>10000: raise ValueError('Configured capacity exceeded')
    for row in tg_rows:
        row[2] = date_serial(row[2],answers_view['timezone'])
        row[3] = date_serial(row[3],answers_view['timezone'])
    for row in tg_contacts:
        row[2] = date_serial(row[2],contacts_view['timezone'])
    fillout = []
    for raw in av['Fillout'][1:]:
        row = raw+['']*(len(normalize.HEADERS)-len(raw))
        if not row[1]: continue
        if len(row)!=len(normalize.HEADERS) or row[0]!='Fillout': raise ValueError('Invalid manual Fillout record')
        fillout.append(row)
    all_rows = google_rows+tg_rows+fillout
    keys = [tuple(r[:2]) for r in all_rows]
    if len(keys)!=len(set(keys)): raise ValueError('Duplicate source identity')
    merged_contacts = normalize.merge_contacts(cv['Контакты'][1:],google_contacts+tg_contacts)
    contact_google = [[r[1],r[2],r[5],r[4]] for r in google_contacts]
    # Validate all values before either write. String cells cannot execute formulas.
    from sheets_api import cell
    for row in all_rows+merged_contacts+contact_google:
        for value in row: cell(value)
    stamp = datetime.now(timezone.utc).isoformat(timespec='seconds')
    # Each workbook is atomic. Any cross-file failure is reconciled on the next full run.
    client.replace(CONTACTS_ID,contacts_view,{'Google':contact_google,'Контакты':merged_contacts})
    client.replace(ANSWERS_ID,answers_view,{'Google':google_rows,'Telegram':tg_rows,'Все ответы':all_rows},
                   ['Автоматически; '+stamp,'Автоматически; '+stamp,'Ручной импорт; интеграция отключена'])
    return {'google':len(google_rows),'telegram':len(tg_rows),'contacts':len(merged_contacts)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data',default='/var/lib/whoof-survey')
    parser.add_argument('--check-only',action='store_true',help='Read and validate live sources without writing')
    args = parser.parse_args()
    key = os.environ['GOOGLE_APPLICATION_CREDENTIALS']
    mode = Path(key).stat().st_mode & 0o777
    if mode & 0o007 or mode & 0o020: raise ValueError('Credential file permissions too broad')
    client = Client(key)
    with open(Path(args.data)/'sheets-sync.lock','a') as lock:
        os.chmod(lock.name,0o600)
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        payload = snapshot(args.data,filter(None,os.getenv('WHOOF_TEST_IDS','').split(',')))
        if args.check_only:
            class ReadOnly:
                def read(self,*a): return client.read(*a)
                def replace(self,*a,**kw): return None
            result = sync_once(ReadOnly(),payload)
            print('Read-only validation passed:',result)
        else:
            result = sync_once(client,payload)
            print('Sheets sync confirmed:',result)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Never print request bodies, contacts, credentials or URLs.
        print(f'Sheets sync failed ({type(error).__name__}); next timer run will retry')
        raise SystemExit(1)
