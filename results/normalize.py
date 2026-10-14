"""Strict native Forms destination normalization. No participant identifiers from chat."""
from collections import Counter
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import re
from sync import SCHEMA

ALIASES = json.loads((Path(__file__).parent/'google-normalization.json').read_text())
HEADERS = SCHEMA['metadata'] + [f['id'] for f in SCHEMA['fields']]
CONTACT_HEADERS = ['Источник','ID контакта','Дата','Код участника (Telegram)','Контакт','Согласие',
                   'Статус интервью','Время интервью','Заметки']
CONTACT_GOOGLE_HEADERS = ['ID контакта','Дата','Согласие','Контакт']


def norm(value):
    return ''.join(c for c in str(value).lower() if c.isalnum())


def mapping(headers):
    if not headers or norm(headers[0]) not in ('отметкавремени','timestamp'):
        raise ValueError('Missing native Google timestamp')
    descriptors=[]
    used=set()
    for field in SCHEMA['fields']:
        expected={norm(t) for t in ALIASES[field['id']]}
        matches=[i for i,t in enumerate(headers) if i and norm(t) in expected]
        if len(matches)!=1: raise ValueError('Missing/ambiguous current column: '+field['id'])
        index=matches[0]
        if index in used: raise ValueError('Repeated native column')
        used.add(index)
        descriptors.append((index,field['id'],field))
    return descriptors


def choice(raw, options, multi=False):
    if raw == '':
        return ''
    if not isinstance(raw, str):
        raise ValueError('Choice must be source text')
    if not multi:
        codes = {o['code'] for o in options if norm(o['label']) == norm(raw)}
        if len(codes) != 1:
            raise ValueError('Unknown or ambiguous choice')
        return next(iter(codes))
    # Labels may themselves contain commas. Only accept a unique complete segmentation.
    parts = raw.split(', ')
    @lru_cache(None)
    def parse(start):
        if start == len(parts):
            return {()}
        matches = set()
        for end in range(start+1, len(parts)+1):
            text = norm(', '.join(parts[start:end]))
            for option in options:
                if norm(option['label']) == text:
                    for tail in parse(end):
                        matches.add((option['code'],)+tail)
        return matches
    candidates = parse(0)
    if len(candidates) != 1:
        raise ValueError('Unknown or ambiguous checkbox export')
    codes = next(iter(candidates))
    if len(codes) != len(set(codes)):
        raise ValueError('Repeated checkbox option')
    return '; '.join(codes)


def source_rows(rows, namespace):
    counts = Counter()
    for raw in rows[1:]:
        if not any(v != '' for v in raw):
            continue
        stamp = raw[0] if raw else ''
        if isinstance(stamp, bool) or not isinstance(stamp, (int, float)) or not math.isfinite(stamp) or stamp <= 0:
            raise ValueError('Expected original numeric Forms timestamp')
        # Sheets date serials remain original. Ordinary value edits retain the same ID.
        token = format(float(stamp), '.17g')
        counts[token] += 1
        identity = hashlib.sha256(f'{namespace}:{token}:{counts[token]}'.encode()).hexdigest()[:24]
        yield raw, stamp, identity, counts[token]


def answers(rows):
    if not rows:
        raise ValueError('Missing raw Google header')
    descriptors = mapping(rows[0])
    output = []
    for raw, stamp, identity, occurrence in source_rows(rows, SCHEMA['version']):
        if len(raw) > len(rows[0]):
            raise ValueError('Unexpected source columns')
        values, warnings = {}, []
        for index,qid,field in descriptors:
            value = raw[index] if index < len(raw) else ''
            if field['type'] in ('single','multi'):
                values[qid] = choice(value,field['options'],field['type']=='multi')
            else:
                if not isinstance(value,str) or len(value)>500: raise ValueError('Invalid source text')
                values[qid]=value
        screened = values['S03'] not in ('c1', 'c2')
        no_episode = values['Q08'] not in ('c2','c3','c4','c5')
        stale_episode = values['Q09'] not in ('c1','c2','c3','c4')
        for field in SCHEMA['fields']:
            qid=field['id']; base=qid.split('_')[0]
            if (screened and base!='S03'
                or no_episode and base in ('Q09','Q11','Q12','Q13','Q15')
                or stale_episode and base in ('Q11','Q12','Q13','Q15')):
                values[qid]=''
            if field['type']=='multi' and values[qid]:
                codes=values[qid].split('; ')
                if len(codes)>1 and any(o.get('exclusive') and o['code'] in codes for o in field['options']):
                    warnings.append(qid+': взаимоисключающие варианты')
        if occurrence > 1: warnings.append('Совпадающие отметки времени; не менять порядок исходных строк')
        output.append(['Google',identity,stamp,stamp,SCHEMA['version'],'core','google_form',
                       'Не подходит' if screened else 'Завершена','Нет','; '.join(warnings)]
                      + [values[f['id']] for f in SCHEMA['fields']])
    return output


def contacts(rows):
    expected_consent = next(f['title'] for f in SCHEMA['fields'] if f['id']=='Q32')
    expected_contact = 'Оставьте один удобный способ связи: Telegram (@имя пользователя), email или номер телефона.'
    if (not rows or len(rows[0]) != 3 or norm(rows[0][0]) not in ('отметкавремени','timestamp')
        or norm(rows[0][1]) != norm(expected_consent) or norm(rows[0][2]) != norm(expected_contact)):
        raise ValueError('Contact raw schema mismatch')
    output = []
    for raw,stamp,identity,_ in source_rows(rows,'whoof-contact-v1'):
        if len(raw)>3: raise ValueError('Unexpected contact columns')
        consent = raw[1] if len(raw)>1 else ''
        contact = raw[2] if len(raw)>2 else ''
        if norm(consent) == norm('Да, можно связаться со мной'):
            if contact:
                if not isinstance(contact,str) or len(contact)>500: raise ValueError('Invalid contact')
                output.append(['Google',identity,stamp,'',contact,'Да, контакт для интервью'])
        elif consent and norm(consent) != norm('Нет, не хочу оставлять контакт'):
            raise ValueError('Unknown contact consent')
    return output


def merge_contacts(previous, incoming):
    notes = {}
    for row in previous:
        if not row or len(row)<2 or not row[1]: continue
        padded = row + ['']*(9-len(row))
        key = tuple(padded[:2])
        if key in notes: raise ValueError('Duplicate contact identity')
        if padded[0] not in ('Google','Telegram'): raise ValueError('Unsupported contact source')
        notes[key] = padded[6:9]
    return [r + notes.get(tuple(r[:2]), ['Не приглашён','','']) for r in incoming]
