"""Small Sheets REST client restricted to the two Whoof workbooks."""
import math
import os
from urllib.parse import quote

ANSWERS_ID = os.getenv('WHOOF_ANSWERS_ID','')
CONTACTS_ID = os.getenv('WHOOF_CONTACTS_ID','')
RAW_TAB = 'Ответы на форму (1)'
ALLOWED = {ANSWERS_ID: {'Google','Telegram','Все ответы','Сводка'},
           CONTACTS_ID: {'Google','Контакты'}}


def cell(value):
    if value == '' or value is None:
        return {}
    if isinstance(value, bool):
        raise ValueError('Unexpected boolean')
    if isinstance(value, (int,float)):
        if not math.isfinite(value): raise ValueError('Nonfinite cell')
        return {'userEnteredValue': {'numberValue': value}}
    if not isinstance(value,str): raise ValueError('Unexpected cell type')
    # Explicit stringValue prevents formula interpretation, including contact @names.
    return {'userEnteredValue': {'stringValue': value}}


class Client:
    def __init__(self, key_path):
        if not ANSWERS_ID or not CONTACTS_ID or ANSWERS_ID==CONTACTS_ID:
            raise ValueError('Configure two distinct workbook IDs privately')
        from google.oauth2 import service_account
        from google.auth.transport.requests import AuthorizedSession
        credentials = service_account.Credentials.from_service_account_file(
            key_path, scopes=['https://www.googleapis.com/auth/spreadsheets'])
        self.session = AuthorizedSession(credentials)

    def request(self, method, book, suffix='', **kwargs):
        if book not in ALLOWED: raise ValueError('Workbook not allowed')
        response = self.session.request(method,
            'https://sheets.googleapis.com/v4/spreadsheets/'+book+suffix, timeout=30, **kwargs)
        response.raise_for_status()
        return response.json()

    def read(self, book, tabs):
        metadata = self.request('GET',book,params={'fields':
            'properties(timeZone),sheets(properties(sheetId,title,gridProperties))'})
        sheets = {s['properties']['title']:s['properties'] for s in metadata['sheets']}
        if any(t not in sheets for t in tabs): raise ValueError('Required tab missing')
        ranges = ["'"+t.replace("'","''")+"'!A1:ZZ" for t in tabs]
        result = self.request('GET',book,'/values:batchGet',params={
            'ranges':ranges,'valueRenderOption':'UNFORMATTED_VALUE','dateTimeRenderOption':'SERIAL_NUMBER'})
        values = {tab:r.get('values',[]) for tab,r in zip(tabs,result['valueRanges'])}
        if len(values)!=len(tabs): raise ValueError('Incomplete range read')
        return {'sheets':sheets,'values':values,'timezone':metadata['properties']['timeZone']}

    def replace(self, book, view, replacements, statuses=None):
        requests = []
        for tab, rows in replacements.items():
            if tab not in ALLOWED[book] or tab == 'Сводка': raise ValueError('Derived tab not allowed')
            prop = view['sheets'][tab]
            width = len(view['values'][tab][0])
            if any(len(row)!=width for row in rows): raise ValueError('Row width mismatch')
            old_count = len(view['values'][tab])-1
            needed = len(rows)+1
            if needed>prop['gridProperties']['rowCount']:
                requests.append({'appendDimension':{'sheetId':prop['sheetId'],'dimension':'ROWS',
                    'length':needed-prop['gridProperties']['rowCount']}})
            if max(old_count,len(rows)):
                requests.append({'updateCells':{'range':{'sheetId':prop['sheetId'],
                    'startRowIndex':1,'endRowIndex':max(old_count,len(rows))+1,
                    'startColumnIndex':0,'endColumnIndex':width},
                    'rows':[{'values':[cell(v) for v in row]} for row in rows],
                    'fields':'userEnteredValue'}})
        if statuses:
            if book!=ANSWERS_ID: raise ValueError('Wrong summary workbook')
            requests.append({'updateCells':{'range':{'sheetId':view['sheets']['Сводка']['sheetId'],
                'startRowIndex':4,'endRowIndex':7,'startColumnIndex':3,'endColumnIndex':4},
                'rows':[{'values':[cell(v)]} for v in statuses],'fields':'userEnteredValue'}})
        if not requests: return
        self.request('POST',book,':batchUpdate',json={'requests':requests})
