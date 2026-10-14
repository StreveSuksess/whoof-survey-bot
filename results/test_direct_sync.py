"""Synthetic API isolation, normalization and retry checks. No real participant data."""
import copy
import json
import os
from pathlib import Path
import unittest
os.environ.setdefault('WHOOF_ANSWERS_ID','synthetic-answers-book')
os.environ.setdefault('WHOOF_CONTACTS_ID','synthetic-contacts-book')
import normalize as n
from direct_sync import sync_once, date_serial
from sheets_api import ANSWERS_ID, CONTACTS_ID, RAW_TAB, ANSWERS_RAW_TAB, Client, cell


def raw_headers():
    result=['Отметка времени']
    for f in n.SCHEMA['fields']: result.append(n.ALIASES[f['id']][-1])
    return result


def raw_row(values, stamp=46000.5):
    descriptors=n.mapping(raw_headers())
    return [stamp]+[values.get(qid,'') for _,qid,_ in descriptors]


def label(qid,code):
    return next(o['label'] for f in n.SCHEMA['fields'] if f['id']==qid for o in f['options'] if o['code']==code)


def contact_rows(contact='@synthetic_contact'):
    return [['Отметка времени',next(f['title'] for f in n.SCHEMA['fields'] if f['id']=='Q32'),
             'Оставьте один удобный способ связи: Telegram (@имя пользователя), email или номер телефона.'],
            [46000.5,'Да, можно связаться со мной',contact]]


class MemoryAPI:
    def __init__(self):
        self.books={ANSWERS_ID:{ANSWERS_RAW_TAB:[raw_headers(),raw_row({'S03':label('S03','c1')})],
                    **{t:[n.HEADERS] for t in ('Google','Telegram','Fillout','Все ответы')},'Сводка':[['Сводка']]},
                    CONTACTS_ID:{RAW_TAB:contact_rows(),'Google':[n.CONTACT_GOOGLE_HEADERS],
                                 'Контакты':[n.CONTACT_HEADERS]}}
        self.calls=[]; self.fail_answers=False; self.reads=[]
    def read(self,book,tabs):
        self.reads.append((book,tabs))
        return {'values':copy.deepcopy({t:self.books[book][t] for t in tabs}),'timezone':'Europe/Moscow','sheets':{}}
    def replace(self,book,view,replacements,statuses=None):
        if book==ANSWERS_ID and self.fail_answers: raise RuntimeError('Synthetic write interruption')
        self.calls.append((book,set(replacements)))
        for tab,rows in replacements.items():
            self.books[book][tab]=[self.books[book][tab][0]]+copy.deepcopy(rows)


class DirectTests(unittest.TestCase):
    def test_current_columns_ignore_preserved_removed_columns(self):
        live=json.loads((Path(__file__).parent/'live-main-headers.json').read_text())
        self.assertEqual(len(n.mapping(live)),21)
        headers=raw_headers()+['Старый вопрос о расходах']
        self.assertEqual(len(n.mapping(headers)),21)
        with self.assertRaises(ValueError): n.mapping(headers+[headers[4]])
        with self.assertRaises(ValueError): n.mapping(headers[:4]+headers[5:])

    def test_unknown_zero_and_skipped_are_different(self):
        values=[]
        for code in ('c1','c6',''):
            raw=label('Q08',code) if code else ''
            row=n.answers([raw_headers(),raw_row({'S03':label('S03','c1'),'Q08':raw})])[0]
            values.append(row[n.HEADERS.index('Q08')])
        self.assertEqual(values,['c1','c6',''])

    def test_screening_and_old_or_missing_date_clear_case_notes(self):
        for date in ('c5',''):
            row=n.answers([raw_headers(),raw_row({'S03':label('S03','c1'),'Q08':label('Q08','c2'),
                'Q09':label('Q09',date) if date else '', 'Q11':label('Q11','c1'),'Q11_note':'hidden','Q15a':label('Q15a','c3')})])[0]
            self.assertEqual(row[n.HEADERS.index('Q11_note')],'')
            self.assertEqual(row[n.HEADERS.index('Q15a')],'c3')
        row=n.answers([raw_headers(),raw_row({'S03':label('S03','c3'),'Q34_note':'hidden'})])[0]
        self.assertEqual(row[7],'Не подходит')
        self.assertEqual(row[n.HEADERS.index('Q34_note')],'')

    def test_comma_inside_multi_label_and_ambiguous_fails(self):
        opts=[dict(code='a',label='A, B'),dict(code='b',label='C')]
        self.assertEqual(n.choice('A, B, C',opts,True),'a; b')
        opts += [dict(code='c',label='A'),dict(code='d',label='B')]
        with self.assertRaises(ValueError): n.choice('A, B, C',opts,True)

    def test_id_survives_value_edit_and_unique_timestamp_deletion(self):
        a=raw_row({'S03':label('S03','c1')},46000.1)
        b=raw_row({'S03':label('S03','c1')},46000.2)
        original=n.answers([raw_headers(),a,b])
        changed=raw_row({'S03':label('S03','c1'),'Q34_note':'new'},46000.2)
        self.assertEqual(original[1][1],n.answers([raw_headers(),changed])[0][1])
        duplicate=n.answers([raw_headers(),a,a])
        self.assertNotEqual(duplicate[0][1],duplicate[1][1])

    def test_replay_deletion_notes_and_contact_separation(self):
        api=MemoryAPI(); payload={'records':[],'contacts':[]}
        sync_once(api,payload)
        row=api.books[CONTACTS_ID]['Контакты'][1]; row[6:]=['Приглашён','понедельник','Нужен вечер']
        first=copy.deepcopy(api.books)
        sync_once(api,payload)
        self.assertEqual(first,api.books)
        self.assertNotIn('@synthetic_contact',str(api.books[ANSWERS_ID]))
        api.books[CONTACTS_ID][RAW_TAB]=contact_rows()[:1]
        sync_once(api,payload)
        self.assertEqual(len(api.books[CONTACTS_ID]['Контакты']),1)
        self.assertTrue(all(RAW_TAB not in tabs and ANSWERS_RAW_TAB not in tabs for _,tabs in api.calls))
        self.assertTrue(all('Fillout' not in tabs for _,tabs in api.reads))

    def test_cross_file_retry_preserves_notes(self):
        api=MemoryAPI(); payload={'records':[],'contacts':[]}
        api.fail_answers=True
        with self.assertRaises(RuntimeError): sync_once(api,payload)
        api.books[CONTACTS_ID]['Контакты'][1][8]='keep'
        api.fail_answers=False
        sync_once(api,payload)
        self.assertEqual(api.books[CONTACTS_ID]['Контакты'][1][8],'keep')
        self.assertEqual(len(api.books[ANSWERS_ID]['Все ответы']),2)

    def test_empty_contact_is_optional_and_timestamp_is_stable(self):
        self.assertEqual(n.contacts(contact_rows('')),[])

    def test_telegram_update_converts_dates_and_does_not_duplicate(self):
        api=MemoryAPI()
        row=['Telegram','0123456789abcdef','',1700000000000,n.SCHEMA['version'],
             'core','direct','Завершена','Нет','']+['']*len(n.SCHEMA['fields'])
        payload={'records':[row],'contacts':[['Telegram',row[1],1700000000000,row[1],'@tg_synthetic','Q32:c1']]}
        sync_once(api,payload); sync_once(api,payload)
        self.assertEqual(len(api.books[ANSWERS_ID]['Telegram']),2)
        self.assertAlmostEqual(api.books[ANSWERS_ID]['Telegram'][1][3],date_serial(row[3],'Europe/Moscow'))
        self.assertNotIn('@tg_synthetic',str(api.books[ANSWERS_ID]))
        payload={'records':[],'contacts':[]}; sync_once(api,payload)
        self.assertEqual(len(api.books[ANSWERS_ID]['Telegram']),1)

    def test_schema_error_before_any_write(self):
        api=MemoryAPI(); api.books[ANSWERS_ID][ANSWERS_RAW_TAB][0][4]='unexpected'
        with self.assertRaises(ValueError): sync_once(api,{'records':[],'contacts':[]})
        self.assertEqual(api.calls,[])

    def test_injection_literal_dates_and_write_allowlist(self):
        for value in ('=IMPORTXML("https://example.com")','@name','+123'):
            self.assertEqual(cell(value),{'userEnteredValue':{'stringValue':value}})
        self.assertAlmostEqual(date_serial(0,'Europe/Moscow'),25569.125)
        client=Client.__new__(Client)
        with self.assertRaises(ValueError): client.request('GET','unauthorized')
        with self.assertRaises(ValueError): client.replace(ANSWERS_ID,{}, {RAW_TAB:[]})

    def test_atomic_clear_only_derived_values(self):
        client=Client.__new__(Client); calls=[]
        client.request=lambda *args,**kwargs: calls.append(kwargs['json'])
        view={'sheets':{'Telegram':{'sheetId':10,'gridProperties':{'rowCount':100}}},
              'values':{'Telegram':[n.HEADERS,['old']*len(n.HEADERS)]}}
        client.replace(ANSWERS_ID,view,{'Telegram':[]})
        update=calls[0]['requests'][0]['updateCells']
        self.assertEqual(update['range']['startRowIndex'],1)
        self.assertEqual(update['range']['endRowIndex'],2)
        self.assertEqual(update['fields'],'userEnteredValue')
        self.assertEqual(update['rows'],[])


if __name__=='__main__': unittest.main()
