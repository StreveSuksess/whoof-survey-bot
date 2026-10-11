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
from sheets_api import ANSWERS_ID, CONTACTS_ID, RAW_TAB, Client, cell


def raw_headers():
    result=['Отметка времени']
    for f in n.SCHEMA['fields']:
        if f['type']=='money':
            result += [f['title'],'Сумма, ₽' if f['id']=='Q14' else 'Сумма общих расходов, ₽']
        elif f['id'].endswith('_note'):
            result.append('Хотите пояснить ответ или описать случай?')
        else: result.append(n.ALIASES[f['id']][-1])
    return result


def raw_row(values, stamp=46000.5):
    descriptors=n.mapping(raw_headers())
    return [stamp]+[values.get(qid,'') for qid,_,_ in descriptors]


def label(qid,code):
    return next(o['label'] for f in n.SCHEMA['fields'] if f['id']==qid for o in f['options'] if o['code']==code)


def contact_rows(contact='@synthetic_contact'):
    return [['Отметка времени',next(f['title'] for f in n.SCHEMA['fields'] if f['id']=='Q32'),
             'Оставьте один удобный способ связи: Telegram (@имя пользователя), email или номер телефона.'],
            [46000.5,'Да, можно связаться со мной',contact]]


class MemoryAPI:
    def __init__(self):
        self.books={ANSWERS_ID:{RAW_TAB:[raw_headers(),raw_row({'S03':label('S03','c1')})],
                    **{t:[n.HEADERS] for t in ('Google','Telegram','Fillout','Все ответы')},'Сводка':[['Сводка']]},
                    CONTACTS_ID:{RAW_TAB:contact_rows(),'Google':[n.CONTACT_GOOGLE_HEADERS],
                                 'Контакты':[n.CONTACT_HEADERS]}}
        self.calls=[]; self.fail_answers=False
    def read(self,book,tabs):
        return {'values':copy.deepcopy(self.books[book]),'timezone':'Europe/Moscow','sheets':{}}
    def replace(self,book,view,replacements,statuses=None):
        if book==ANSWERS_ID and self.fail_answers: raise RuntimeError('Synthetic write interruption')
        self.calls.append((book,set(replacements)))
        for tab,rows in replacements.items():
            self.books[book][tab]=[self.books[book][tab][0]]+copy.deepcopy(rows)


class DirectTests(unittest.TestCase):
    def test_actual_browser_copied_headers(self):
        root=Path(__file__).parent
        self.assertEqual(len(n.mapping(json.loads((root/'live-main-headers.json').read_text()))),70)
        self.assertEqual(n.contacts([json.loads((root/'live-contact-headers.json').read_text())]),[])

    def test_google_zero_refusal_and_hidden_amount(self):
        rows=[raw_headers(),raw_row({'S03':label('S03','c1'),'Q08':label('Q08','c2'),
              'Q09':label('Q09','c1'),'Q14_status':'Укажу сумму','Q14':0,
              'Q23_status':'Не хочу отвечать.','Q23':120})]
        values=dict(zip((f['id'] for f in n.SCHEMA['fields']),n.answers(rows)[0][10:]))
        self.assertEqual(values['Q14'],0); self.assertEqual(values['Q23'],'refused')

    def test_screening_clears_hidden_fields_and_note_occurrences(self):
        row=n.answers([raw_headers(),raw_row({'S03':label('S03','c3'),'Q01_note':'hidden'})])[0]
        self.assertEqual(row[7],'Не подходит'); self.assertEqual(row[10+next(i for i,f in enumerate(n.SCHEMA['fields']) if f['id']=='Q01_note')],'')
        self.assertEqual(len(n.mapping(raw_headers())),70)

    def test_comma_inside_multi_label_and_ambiguous_fails(self):
        opts=[dict(code='a',label='A, B'),dict(code='b',label='C')]
        self.assertEqual(n.choice('A, B, C',opts,True),'a; b')
        opts += [dict(code='c',label='A'),dict(code='d',label='B')]
        with self.assertRaises(ValueError): n.choice('A, B, C',opts,True)

    def test_id_survives_value_edit_and_unique_timestamp_deletion(self):
        a=raw_row({'S03':label('S03','c1')},46000.1)
        b=raw_row({'S03':label('S03','c1')},46000.2)
        original=n.answers([raw_headers(),a,b])
        changed=raw_row({'S03':label('S03','c1'),'Q01_note':'new'},46000.2)
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
        self.assertTrue(all(RAW_TAB not in tabs for _,tabs in api.calls))

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
        api=MemoryAPI(); api.books[ANSWERS_ID][RAW_TAB][0][4]='unexpected'
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
