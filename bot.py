"""Whoof quantitative Telegram bot, using persistent polling state."""
import argparse
import fcntl
import http.client
import json
import os
import secrets
import time
from pathlib import Path

from engine import Engine
from presentation import caption, needs_details
from storage import Store


class Telegram:
    def __init__(self,token):
        self.path='/bot'+token+'/'
        self.connection=None

    def close(self):
        if self.connection:
            self.connection.close(); self.connection=None

    def call(self,method,**args):
        try:
            if self.connection is None:
                self.connection=http.client.HTTPSConnection('api.telegram.org',timeout=65)
            self.connection.request('POST',self.path+method,body=json.dumps(args).encode(),
                                    headers={'Content-Type':'application/json'})
            response=self.connection.getresponse()
            status=response.status
            # Fully consume the response before reusing the TLS connection.
            body=response.read()
            if response.will_close: self.close()
            result=json.loads(body)
        except (OSError,http.client.HTTPException,ValueError):
            self.close()
            # Do not repeat a send: Telegram may already have delivered it.
            raise RuntimeError('Telegram connection unavailable') from None
        if status>=400:
            retry=result.get('parameters',{}).get('retry_after')
            if retry: time.sleep(min(retry,30))
            raise RuntimeError(f'Telegram request failed ({status}); retry safely') from None
        if not result.get('ok'): raise RuntimeError('Telegram rejected request')
        return result['result']


class SurveyBot:
    def __init__(self,api,store,mode='core'):
        if mode != 'core': raise ValueError('Invalid mode')
        self.api,self.store,self.mode=api,store,mode
        self.engine=Engine()

    def process(self,update):
        update_id=update['update_id']
        if update_id < self.store.offset(): return
        with self.store.update(update_id):
            try: self.handle(update)
            except ValueError as e:
                msg=update.get('message') or update.get('callback_query',{}).get('message')
                if msg: self.send(msg['chat']['id'],str(e))
            self.store.offset(update_id+1)

    def send(self,chat,text,rows=None):
        return self.api.call('sendMessage',chat_id=chat,text=text,reply_markup={'inline_keyboard':rows or []})

    def start(self,chat,channel='direct'):
        s=self.store.load(chat)
        if s:
            if self.outdated(s): return self.version_notice(chat)
            if s.get('note_for'): return self.render(chat,s)
            if s.get('complete'):
                return self.send(chat,'Спасибо, ваши ответы уже сохранены. /delete удаляет анкету и контакт. Для новой анкеты сначала удалите текущую.')
            return self.render(chat,s)
        s=dict(participant=secrets.token_hex(8),version=self.engine.instrument['version'],mode=self.mode,
               channel=channel[:64],answers={},done=[],nonce='',started=False,complete=False,screened_out=False)
        self.store.save(chat,s)
        text=self.engine.instrument['intro']+'\n\n'+self.engine.instrument['privacy']+'\n\nВ каждом вопросе видно, сколько осталось. Число уточняется по вашим ответам; пояснения необязательны.\n\nМожно остановиться и продолжить через /start. /back — предыдущий ответ, /skip — пропустить. /delete — удалить данные. Ориентир полной анкеты — 5–7 минут; время уточним в пробном прохождении.'
        return self.send(chat,text,[[dict(text='Начать опрос',callback_data='begin')]])

    def outdated(self,s):
        return s.get('version') != self.engine.instrument['version'] or s.get('mode') != 'core'

    def version_notice(self,chat):
        return self.send(chat,'Анкета сократилась. Чтобы пройти новую версию с начала, отправьте /delete, затем /start. Текущие ответы и контакт будут удалены только по вашей команде /delete.')

    def current(self,s):
        route=self.engine.route(s['answers'],s['mode'],s['participant'])
        return next((q for q in route if q not in s['done']),None)

    def previous_note(self,s):
        qid=s['done'][-1] if s['done'] else None
        return qid if qid and self.engine.questions[qid].get('note') else None

    def progress_header(self,s):
        if 'S03' not in s['done']:
            return 'Проверка участия · один вопрос\n\n'
        low,high=self.engine.remaining_bounds(s['answers'],s['done'],s['mode'],s['participant'])
        route=self.engine.route(s['answers'],s['mode'],s['participant'])
        answered=len(set(s['done']).intersection(route))
        filled=8*answered//max(1,answered+high)
        bar='▰'*filled+'▱'*(8-filled)
        count=str(low) if low==high else f'{low}–{high}'
        word='вопросов'
        if low==high:
            if low%10==1 and low%100!=11: word='вопрос'
            elif low%10 in (2,3,4) and low%100 not in (12,13,14): word='вопроса'
        return f'{bar}  Вопрос {answered+1}\nОсталось {count} {word}, включая этот.\n\n'

    def render_message(self,chat,s,key,text,rows):
        """Update buttons in place when toggling a choice; preserve the chat history."""
        if s.get('render_key')==key and s.get('render_message_id'):
            result=self.api.call('editMessageText',chat_id=chat,message_id=s['render_message_id'],
                                 text=text,reply_markup={'inline_keyboard':rows})
        else:
            result=self.send(chat,text,rows)
        if isinstance(result,dict) and result.get('message_id'):
            s['render_message_id']=result['message_id']; s['render_key']=key
            self.store.save(chat,s)
        return result

    def render(self,chat,s):
        if not s.get('started'): return self.send(chat,'Можно начать опрос или вернуться позже.',[[dict(text='Начать',callback_data='begin')]])
        if s.get('note_for'):
            q=self.engine.questions[s['note_for']]
            s['nonce']=secrets.token_hex(3); self.store.save(chat,s)
            value=s['answers'].get(s['note_for'])
            codes=value if isinstance(value,list) else [value]
            labels=[o['label'] for o in self.engine.options(s['note_for'],s['participant']) if o['code'] in codes]
            answer='; '.join(labels) if labels else ('Пропущен' if value is None else str(value))
            text='Необязательное пояснение · прогресс не меняется\n\n'+q['title']+'\n\nВаш ответ: '+answer+'\n\n'+q['note']+'\n\nНапишите пояснение сообщением (до 500 символов). «К опросу» — продолжить без пояснения.'
            rows=[[dict(text='К опросу',callback_data=s['nonce']+'|cancelnote'),dict(text='Изменить ответ',callback_data=s['nonce']+'|back')]]
            return self.render_message(chat,s,'note:'+s['note_for'],text,rows)
        # Migrate an old explanation pre-toggle without touching saved answers.
        s.pop('want_note',None)
        qid=self.current(s)
        if qid is None:
            s['complete']=True; s['screened_out']=s['answers'].get('S03') not in ('c1','c2')
            s['nonce']=secrets.token_hex(3)
            self.store.save(chat,s)
            rows=[[dict(text='Пояснить ответ',callback_data=s['nonce']+'|prevnote')]] if self.previous_note(s) else []
            return self.send(chat,('Проверка завершена.\n\n' if s['screened_out'] else 'Опрос завершён ✅\n\n')+'Спасибо! '+('Для продолжения исследования нужно подтвердить, что вы регулярно участвуете в уходе за собакой.' if s['screened_out'] else 'Ответы сохранены и помогут понять реальные задачи владельцев собак.'),rows)
        q=self.engine.questions[qid]
        s['nonce']=secrets.token_hex(3)
        s.setdefault('selected',[])
        self.store.save(chat,s)
        prefix=''
        if qid=='Q32': prefix=self.engine.instrument['invitation']+'\n\n'
        if qid=='Q01': prefix=self.engine.instrument['selection_instruction']+'\n\n'
        text=self.progress_header(s)+prefix+q['title']
        if q.get('help'): text+='\n\n'+q['help']
        rows=[]
        options=self.engine.options(qid,s['participant'])
        # Meaningful captions, one per row; exact source wording is expandable.
        if options:
            if q['type']=='money': text+='\n\nНапишите сумму в рублях или выберите специальный ответ.'
            if s.get('show_options')==qid:
                text+='\n\n'+('\n'.join('• '+o['label'] for o in options))
            for o in options:
                selected=o['code'] in s['selected']
                label=('✓ ' if selected else '')+caption(qid,o)
                rows.append([dict(text=label,callback_data=s['nonce']+'|'+o['code'])])
        if q.get('inline_other'): text+='\n\nСвой вариант после ответа можно пояснить по желанию.'
        if q['type']=='multi':
            text+='\n\n'+('Выберите до трёх ответов' if q.get('max_choices') else 'Можно выбрать несколько ответов')+', затем нажмите «Готово».'
            rows.append([dict(text='Готово',callback_data=s['nonce']+'|done')])
        if q.get('special'): rows.append([dict(text=q['special'],callback_data=s['nonce']+'|unsure')])
        if needs_details(qid,options):
            rows.append([dict(text='Свернуть варианты' if s.get('show_options')==qid else 'Полные варианты',callback_data=s['nonce']+'|details')])
        if self.previous_note(s):
            rows.append([dict(text='Пояснить прошлый ответ',callback_data=s['nonce']+'|prevnote')])
        if q['type']=='text': text+=f'\n\nМожно написать ответ или пропустить. До {q.get("max_length",500)} символов.'
        rows.append([dict(text='Пропустить',callback_data=s['nonce']+'|skip'),dict(text='Назад',callback_data=s['nonce']+'|back')])
        return self.render_message(chat,s,qid,text,rows)

    def answer(self,chat,s,value):
        if s.get('note_for'):
            qid=s['note_for']; value=self.engine.validate(qid+'_note',value)
            s.pop('note_for'); s['answers'][qid+'_note']=value
            self.store.save(chat,s); return self.render(chat,s)
        qid=self.current(s)
        if qid is None: return self.render(chat,s)
        value=self.engine.validate(qid,value)
        if qid=='Q33':
            if value and s['answers'].get('Q32')=='c1': self.store.save_contact(s['participant'],value)
            else: self.store.remove_contact(s['participant'])
        else: s['answers'][qid]=value
        if qid=='Q32' and value!='c1': self.store.remove_contact(s['participant'])
        s['done'].append(qid); s['selected']=[]
        s['answers']=self.engine.prune(s['answers'],s['mode'])
        s.pop('want_note',None); s.pop('show_options',None)
        self.store.save(chat,s)
        return self.render(chat,s)

    def back(self,chat,s):
        s['complete']=False; s['screened_out']=False
        s.pop('note_for',None); s.pop('want_note',None); s['selected']=[]
        if s['done']:
            qid=s['done'].pop()
            if qid=='Q33': self.store.remove_contact(s['participant'])
            s['answers'].pop(qid,None); s['answers'].pop(qid+'_note',None)
            s['answers']=self.engine.prune(s['answers'],s['mode'])
            allowed=set(self.engine.route(s['answers'],s['mode']))
            s['done']=[q for q in s['done'] if q in allowed]
        self.store.save(chat,s)
        return self.render(chat,s)

    def handle(self,update):
        cb=update.get('callback_query'); msg=update.get('message') or (cb or {}).get('message')
        if not msg or msg.get('chat',{}).get('type')!='private': return
        chat=msg['chat']['id']; text=msg.get('text','') if not cb else ''
        s=self.store.load(chat)
        if cb:
            # Acknowledge even obsolete callbacks so the client stops spinning.
            self.api.call('answerCallbackQuery',callback_query_id=cb['id'])
            if not s: return self.start(chat)
            if self.outdated(s): return self.version_notice(chat)
            action=cb.get('data','')
            if action=='begin' and not s.get('started'):
                s['started']=True; self.store.save(chat,s); return self.render(chat,s)
            nonce,sep,action=action.partition('|')
            if not sep or nonce!=s['nonce']: return self.send(chat,'Этот вопрос уже изменился. Отвечайте на последнее сообщение или нажмите /start.')
            if action=='prevnote' and not s.get('note_for'):
                qid=self.previous_note(s)
                if not qid: return
                s['note_for']=qid; self.store.save(chat,s); return self.render(chat,s)
            if s.get('note_for'):
                if action=='back': return self.back(chat,s)
                if action=='skip': return self.answer(chat,s,None)
                if action=='cancelnote':
                    s.pop('note_for'); self.store.save(chat,s); return self.render(chat,s)
                return self.send(chat,'Сейчас можно написать пояснение сообщением или нажать «К опросу».')
            if s.get('complete'): return
            if action=='back': return self.back(chat,s)
            if action=='skip': return self.answer(chat,s,None)
            qid=self.current(s); q=self.engine.questions[qid]
            if action=='details':
                if s.get('show_options')==qid: s.pop('show_options')
                else: s['show_options']=qid
                return self.render(chat,s)
            if action=='note': return self.render(chat,s)  # Refresh legacy buttons.
            if action=='unsure': return self.answer(chat,s,q.get('special'))
            if q['type']=='multi':
                selected=s['selected']
                if action=='done': return self.answer(chat,s,selected or None)
                option=next((o for o in q['options'] if o['code']==action),None)
                if option is None: return
                if action in selected: selected.remove(action)
                elif option.get('exclusive'): selected[:]=[action]
                else:
                    selected[:]=[c for c in selected if not any(o.get('exclusive') and o['code']==c for o in q['options'])]
                    selected.append(action)
                try: self.engine.validate(qid,selected)
                except ValueError as e:
                    selected.remove(action); self.store.save(chat,s); return self.send(chat,str(e))
                self.store.save(chat,s); return self.render(chat,s)
            return self.answer(chat,s,action)
        if text.startswith('/start'):
            payload=text.split(maxsplit=1)
            return self.start(chat,payload[1] if len(payload)>1 else 'direct')
        if text=='/delete':
            self.store.delete(chat); return self.send(chat,'Анкета и контакт удалены из локального хранилища Whoof. Для новой анкеты — /start.')
        if text=='/help': return self.send(chat,'/start — начать или продолжить\n/back — предыдущий ответ\n/skip — пропустить\n/note текст — пояснение к предыдущему ответу\n/delete — удалить анкету и контакт')
        if not s: return self.start(chat)
        if self.outdated(s): return self.version_notice(chat)
        if s.get('complete') and not s.get('note_for'): return self.send(chat,'Ответы уже сохранены. /delete — удалить данные.')
        if text=='/back': return self.back(chat,s)
        if text=='/skip': return self.answer(chat,s,None)
        if text.startswith('/note '):
            if s.get('note_for'): return self.answer(chat,s,text[6:])
            qid=s['done'][-1] if s['done'] else None
            if not qid or not self.engine.questions[qid].get('note'): return self.send(chat,'У предыдущего вопроса нет отдельного пояснения.')
            s['answers'][qid+'_note']=self.engine.validate(qid+'_note',text[6:]); self.store.save(chat,s)
            return self.send(chat,'Пояснение сохранено к предыдущему вопросу. Продолжайте отвечать на текущий вопрос.')
        if not s.get('started'): return self.render(chat,s)
        if s.get('note_for') or self.engine.questions[self.current(s)]['type'] in ('text','money'):
            return self.answer(chat,s,text)
        return self.send(chat,'Выберите ответ кнопкой в последнем вопросе. /skip — пропустить.')


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--export',type=Path); parser.add_argument('--data',default=str(Path(__file__).parent/'data'))
    args=parser.parse_args(); store=Store(args.data); store.purge_expired()
    if args.export:
        args.export.parent.mkdir(parents=True,exist_ok=True)
        args.export.write_text(json.dumps(store.export(),ensure_ascii=False,indent=2)); os.chmod(args.export,0o600)
        print('Completed responses exported without chat identifiers or contacts.'); return
    # Keep this descriptor open for the process lifetime; a crash releases flock.
    lock=os.open(store.directory/'poller.lock',os.O_CREAT|os.O_RDWR,0o600)
    try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError: parser.error('Another poller is using this data directory.')
    token=os.environ.get('TELEGRAM_BOT_TOKEN')
    if not token: parser.error('Set TELEGRAM_BOT_TOKEN locally; never commit the token.')
    api=Telegram(token); bot=SurveyBot(api,store,os.environ.get('SURVEY_MODE','core'))
    # Never delete or overwrite an existing webhook automatically.
    if api.call('getWebhookInfo').get('url'): parser.error('An existing webhook is active; stop it explicitly before polling.')
    print('Whoof bot ready; stop with Ctrl-C. No answers are printed.')
    offset=store.offset(); last_purge=time.monotonic()
    while True:
        try:
            updates=api.call('getUpdates',offset=offset,timeout=25,allowed_updates=['message','callback_query'])
            for update in updates:
                bot.process(update)
                offset=store.offset()
            if time.monotonic()-last_purge>3600: store.purge_expired(); last_purge=time.monotonic()
        except RuntimeError as e:
            offset=store.offset()
            print(str(e)); time.sleep(5)
        except KeyboardInterrupt: break


if __name__=='__main__': main()
