import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from engine import Engine
from storage import Store
from bot import SurveyBot, Telegram
from presentation import caption, needs_details


class FakeTelegram:
    def __init__(self): self.calls=[]
    def call(self,method,**args): self.calls.append((method,args)); return {'message_id':len(self.calls)}


class SurveyTests(unittest.TestCase):
    def setUp(self):
        self.e=Engine(); self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store=Store(self.tmp.name); self.addCleanup(self.store.db.close); self.addCleanup(self.store.contacts.close); self.api=FakeTelegram(); self.bot=SurveyBot(self.api,self.store)
    def test_source_ids_and_notes(self):
        qs=self.e.instrument['questions']; self.assertEqual(len(qs),38)
        self.assertEqual(sum('note' in q for q in qs),17)
        self.assertFalse(any(q['id'] in ['Q18','Q19','Q20','Q21','Q22'] for q in qs))
    def test_no_episode_or_unknown(self):
        for v in ['c1','c6',None]:
            route=self.e.route({'Q08':v})
            self.assertNotIn('Q09',route); self.assertNotIn('Q14',route)
            self.assertIn('Q15a',route); self.assertIn('Q15b',route)
    def test_old_episode(self):
        route=self.e.route({'Q08':'c2','Q09':'c5'})
        self.assertIn('Q09',route); self.assertNotIn('Q10',route); self.assertIn('Q15a',route)
    def test_personal_wearable(self):
        for value in ['c1','c2']:
            self.assertIn('Q26a',self.e.route({'Q26':value}))
        for value in ['c3','c4','c5',None]:
            self.assertNotIn('Q26b',self.e.route({'Q26':value}))
    def test_modes(self):
        self.assertNotIn('Q28',self.e.route({},'core'))
        self.assertIn('Q28',self.e.route({},'concept')); self.assertNotIn('P01',self.e.route({},'concept'))
        self.assertIn('P01',self.e.route({},'price'))
    def test_contact_route(self):
        for v in ['c2',None]: self.assertNotIn('Q33',self.e.route({'Q32':v}))
        self.assertIn('Q33',self.e.route({'Q32':'c1'}))
    def test_multi_constraints(self):
        with self.assertRaises(ValueError): self.e.validate('Q07',['c1','c9'])
        with self.assertRaises(ValueError): self.e.validate('Q30',['c1','c2','c3','c4'])
        self.assertEqual(self.e.validate('Q30',['c1','c2','c2']),['c1','c2'])
    def test_expense_zero_not_unknown(self):
        self.assertEqual(self.e.validate('Q14','0'),0)
        self.assertEqual(self.e.validate('Q23','unknown'),'unknown')
        self.assertEqual(self.e.validate('Q23','refused'),'refused')
        for v in ['-1','NaN','inf','hello','1.123']: 
            with self.assertRaises(ValueError): self.e.validate('Q14',v)
    def test_other_and_special_followups(self):
        self.assertIn('Q07_other',self.e.route({'Q07':['c8']}))
        self.assertNotIn('Q07_other',self.e.route({'Q07':['c1']}))
        self.assertIn('Q17_other_frequency',self.e.route({'Q17_other':'Сервис'}))
        self.assertIn('Q17_other_frequency',self.e.route({'Q17_other':None}))
        self.assertIn('Q26a_action',self.e.route({'Q26':'c1','Q26a':'c1'}))
    def test_stable_shuffle_tail(self):
        a=self.e.options('Q07','seed'); self.assertEqual(a,self.e.options('Q07','seed'))
        self.assertEqual([o['code'] for o in a[-3:]],['c8','c9','c10'])
    def test_screenout_complete(self):
        self.bot.start(1); s=self.store.load(1); s['started']=True
        self.bot.answer(1,s,'c4'); state=self.store.load(1)
        self.assertTrue(state['complete']); self.assertTrue(state['screened_out'])
    def test_skipped_screening_ends_survey(self):
        self.bot.start(1); s=self.store.load(1); s['started']=True
        self.bot.answer(1,s,None)
        self.assertTrue(self.store.load(1)['screened_out'])
    def test_matrix_randomization_keeps_stable_row_codes(self):
        a=self.e.route({},seed='participant')
        self.assertEqual(a,self.e.route({},seed='participant'))
        rows=[qid for qid in a if qid in [f'Q17_{i}' for i in range(1,7)]]
        self.assertEqual(set(rows),{f'Q17_{i}' for i in range(1,7)})
    def test_toggle_updates_same_message(self):
        self.bot.start(1); s=self.store.load(1); s['started']=True
        s['answers']={'S03':'c1'}; s['done']=self.e.route(s['answers'])[:self.e.route(s['answers']).index('Q07')]
        self.bot.render(1,s); s=self.store.load(1)
        self.bot.handle({'callback_query':{'id':'toggle','data':s['nonce']+'|c1','message':{'chat':{'id':1,'type':'private'}}}})
        self.assertEqual(self.api.calls[-1][0],'editMessageText')

    def at_question(self,qid):
        self.bot.start(1); s=self.store.load(1); s['started']=True
        s['answers']={'S03':'c1','Q08':'c2','Q09':'c1'}
        route=self.e.route(s['answers'],seed=s['participant'])
        s['done']=route[:route.index(qid)]; self.store.save(1,s)
        self.bot.render(1,s)
        return self.store.load(1)

    def callback(self,s,action):
        self.bot.handle({'callback_query':{'id':'test','data':s['nonce']+'|'+action,
                        'message':{'chat':{'id':1,'type':'private'}}}})

    def test_readable_labels_are_short_unique_and_not_truncated(self):
        for qid,q in self.e.questions.items():
            labels=[caption(qid,o) for o in q.get('options',[])]
            self.assertEqual(len(labels),len(set(labels)),qid)
            for label in labels:
                self.assertLessEqual(len(label),28,(qid,label))
                self.assertFalse(label.isdigit(),(qid,label))
        self.assertEqual(caption('S03',{'code':'c2','label':'unused'}),'Ухаживаем вместе')

    def test_text_buttons_keep_shuffled_codes_and_selection(self):
        s=self.at_question('Q07'); args=self.api.calls[-1][1]
        options=self.e.options('Q07',s['participant'])
        option_rows=[row for row in args['reply_markup']['inline_keyboard']
                     if row[0]['callback_data'].split('|')[-1] in {o['code'] for o in options}]
        self.assertTrue(all(len(row)==1 for row in option_rows))
        self.assertEqual([row[0]['text'] for row in option_rows],[caption('Q07',o) for o in options])
        self.assertEqual([row[0]['callback_data'].split('|')[-1] for row in option_rows],[o['code'] for o in options])
        self.callback(s,options[0]['code'])
        buttons=[b['text'] for row in self.api.calls[-1][1]['reply_markup']['inline_keyboard'] for b in row]
        self.assertIn('✓ '+caption('Q07',options[0]),buttons)
        self.assertNotIn('Добавить пояснение',buttons)

    def test_full_wording_can_expand_without_changing_answer(self):
        s=self.at_question('Q05'); self.callback(s,'details'); s=self.store.load(1)
        self.assertEqual(self.api.calls[-1][0],'editMessageText')
        for option in self.e.options('Q05',s['participant']):
            self.assertIn(option['label'],self.api.calls[-1][1]['text'])
        self.assertNotIn('Q05',s['answers'])
        self.callback(s,'details'); self.assertNotIn('show_options',self.store.load(1))

    def test_money_specials_have_readable_buttons(self):
        s=self.at_question('Q14'); args=self.api.calls[-1][1]
        buttons=[b['text'] for row in args['reply_markup']['inline_keyboard'] for b in row]
        for o in self.e.options('Q14',s['participant']): self.assertIn(caption('Q14',o),buttons)
        self.callback(s,'unknown')
        self.assertEqual(self.store.load(1)['answers']['Q14'],'unknown')

    def test_note_after_answer_keeps_next_question_and_context(self):
        s=self.at_question('Q06'); code=self.e.options('Q06',s['participant'])[0]['code']
        self.callback(s,code); s=self.store.load(1)
        self.assertEqual(self.bot.current(s),'Q07')
        self.assertNotIn('note_for',s)
        self.callback(s,'prevnote'); s=self.store.load(1)
        args=self.api.calls[-1][1]
        self.assertIn(self.e.questions['Q06']['title'],args['text'])
        self.assertIn(next(o['label'] for o in self.e.questions['Q06']['options'] if o['code']==code),args['text'])
        self.assertIn('Напишите пояснение сообщением',args['text'])
        with self.assertRaises(ValueError): self.bot.answer(1,s,'x'*501)
        self.assertEqual(s['note_for'],'Q06')
        self.bot.start(1); self.assertEqual(self.store.load(1)['note_for'],'Q06')
        self.bot.answer(1,self.store.load(1),'Тестовое пояснение')
        state=self.store.load(1)
        self.assertEqual(state['answers']['Q06_note'],'Тестовое пояснение')
        self.assertEqual(self.bot.current(state),'Q07')
        self.bot.back(1,state)
        self.assertEqual(self.bot.current(self.store.load(1)),'Q06')
        self.assertNotIn('Q06_note',self.store.load(1)['answers'])

    def test_cancel_note_preserves_next_selection_and_saved_note(self):
        s=self.at_question('Q06'); self.callback(s,'c1'); s=self.store.load(1)
        self.callback(s,'c1'); s=self.store.load(1)  # select in next multi question
        s['answers']['Q06_note']='Сохранённое'; self.store.save(1,s)
        self.callback(s,'prevnote'); s=self.store.load(1)
        self.callback(s,'cancelnote'); s=self.store.load(1)
        self.assertEqual(s['selected'],['c1'])
        self.assertEqual(s['answers']['Q06_note'],'Сохранённое')
        self.assertEqual(self.bot.current(s),'Q07')

    def test_question_option_cannot_be_recorded_as_note(self):
        s=self.at_question('Q06'); self.callback(s,'c1'); s=self.store.load(1)
        self.callback(s,'prevnote'); s=self.store.load(1); self.callback(s,'c2')
        self.assertEqual(self.store.load(1)['note_for'],'Q06')
        self.assertNotIn('Q06_note',self.store.load(1)['answers'])

    def test_screenout_note_can_resume_and_edit_answer(self):
        self.bot.start(1); s=self.store.load(1); s['started']=True
        self.bot.answer(1,s,'c4'); s=self.store.load(1)
        self.callback(s,'prevnote'); s=self.store.load(1)
        self.assertEqual(s['note_for'],'S03')
        self.bot.start(1); self.assertEqual(self.store.load(1)['note_for'],'S03')
        self.callback(self.store.load(1),'back'); s=self.store.load(1)
        self.assertFalse(s['complete']); self.assertEqual(self.bot.current(s),'S03')
        self.callback(s,'c1'); self.assertEqual(self.bot.current(self.store.load(1)),'S04')

    def test_legacy_pre_toggle_does_not_force_note_screen(self):
        s=self.at_question('Q06'); s['want_note']='Q06'; self.store.save(1,s)
        self.callback(s,'c1'); s=self.store.load(1)
        self.assertNotIn('want_note',s); self.assertNotIn('note_for',s)
        self.assertEqual(self.bot.current(s),'Q07')

    def test_simulated_full_route_and_separate_contact(self):
        self.bot.start(1); s=self.store.load(1); s['started']=True; self.store.save(1,s)
        while not self.store.load(1)['complete']:
            s=self.store.load(1); qid=self.bot.current(s); q=self.e.questions[qid]
            if qid=='S03': value='c1'
            elif qid=='Q08': value='c2'
            elif qid=='Q09': value='c1'
            elif qid=='Q26': value='c1'
            elif qid=='Q32': value='c1'
            elif qid=='Q33': value='@test_participant'
            elif q['type']=='single': value=q['options'][0]['code']
            elif q['type']=='multi': value=[q['options'][0]['code']]
            elif q['type']=='money': value='0'
            else: value=None
            self.bot.answer(1,s,value)
        exported=json.dumps(self.store.export())
        self.assertNotIn('@test_participant',exported); self.assertNotIn('Q33',exported); self.assertNotIn('chat_id',exported)
        self.assertEqual(self.store.contacts.execute('SELECT contact FROM contacts').fetchone()[0],'@test_participant')
        self.store.delete(1); self.assertEqual(self.store.contacts.execute('SELECT count(*) FROM contacts').fetchone()[0],0)
    def test_stale_callback_does_not_advance(self):
        self.bot.start(1); s=self.store.load(1); s['started']=True; self.bot.render(1,s)
        self.bot.handle({'callback_query':{'id':'cb','data':'old|c1','message':{'chat':{'id':1,'type':'private'}}}})
        self.assertEqual(self.store.load(1)['done'],[])
    def test_backward_edit_prunes_hidden_answers(self):
        a={'Q08':'c1','Q09':'c1','Q10':'c2','Q14':10,'Q15b':'c3'}
        b=self.e.prune(a,'core'); self.assertNotIn('Q09',b); self.assertNotIn('Q14',b); self.assertIn('Q15b',b)
    def test_unexpected_group_ignored(self):
        self.bot.handle({'message':{'chat':{'id':2,'type':'group'},'text':'/start'}})
        self.assertIsNone(self.store.load(2))

    def test_send_failure_does_not_apply_text_answer_twice(self):
        self.bot.start(1); s=self.store.load(1); s['started']=True
        s['answers']={'S03':'c1'}
        route=self.e.route(s['answers']); s['done']=route[:route.index('Q17_other')]
        self.store.save(1,s)
        update={'update_id':100,'message':{'chat':{'id':1,'type':'private'},'text':'Тестовое решение'}}
        normal_call=self.api.call
        def fail(method,**args): raise RuntimeError('Simulated delivery failure')
        self.api.call=fail
        with self.assertRaises(RuntimeError): self.bot.process(update)
        persisted=self.store.load(1)
        self.assertEqual(persisted['answers']['Q17_other'],'Тестовое решение')
        self.assertEqual(self.store.offset(),101)
        self.api.call=normal_call
        self.bot.process(update)
        self.assertEqual(self.store.load(1),persisted)
        self.bot.start(1)
        self.assertEqual(self.bot.current(self.store.load(1)),'Q17_other_frequency')

    def test_failure_before_state_change_can_retry(self):
        self.bot.start(1); s=self.store.load(1)
        update={'update_id':50,'callback_query':{'id':'cb','data':'begin','message':{'chat':{'id':1,'type':'private'}}}}
        normal_call=self.api.call
        def fail(method,**args): raise RuntimeError('Simulated ACK failure')
        self.api.call=fail
        with self.assertRaises(RuntimeError): self.bot.process(update)
        self.assertEqual(self.store.offset(),0)
        self.assertFalse(self.store.load(1)['started'])
        self.api.call=normal_call; self.bot.process(update)
        self.assertTrue(self.store.load(1)['started'])
        self.assertEqual(self.store.offset(),51)


class TelegramTransportTests(unittest.TestCase):
    def test_server_closed_connection_is_recreated(self):
        with patch('bot.http.client.HTTPSConnection') as factory:
            response=factory.return_value.getresponse.return_value
            response.status=200; response.will_close=True
            response.read.return_value=b'{"ok":true,"result":true}'
            api=Telegram('test-secret')
            api.call('getMe'); api.call('getMe')
            self.assertEqual(factory.call_count,2)
            self.assertIsNone(api.connection)

    def test_rate_limit_is_reported_without_resending(self):
        with patch('bot.http.client.HTTPSConnection') as factory, patch('bot.time.sleep') as sleep:
            response=factory.return_value.getresponse.return_value
            response.status=429; response.will_close=False
            response.read.return_value=b'{"ok":false,"parameters":{"retry_after":5}}'
            api=Telegram('test-secret')
            with self.assertRaisesRegex(RuntimeError,'429'): api.call('sendMessage',chat_id=1,text='Test')
            sleep.assert_called_once_with(5)
            self.assertEqual(factory.return_value.request.call_count,1)

    def test_serial_calls_reuse_https_connection(self):
        with patch('bot.http.client.HTTPSConnection') as factory:
            connection=factory.return_value; response=connection.getresponse.return_value
            response.status=200; response.will_close=False
            response.read.return_value=b'{"ok":true,"result":{"message_id":1}}'
            api=Telegram('test-secret')
            api.call('answerCallbackQuery',callback_query_id='cb')
            api.call('sendMessage',chat_id=1,text='Test')
            self.assertEqual(factory.call_count,1)
            self.assertEqual(connection.request.call_count,2)
            self.assertEqual(response.read.call_count,2)
            self.assertEqual(factory.call_args.args,('api.telegram.org',))

    def test_failed_send_is_not_retried_and_error_hides_secret(self):
        with patch('bot.http.client.HTTPSConnection') as factory:
            connection=factory.return_value
            connection.getresponse.side_effect=OSError('test-secret')
            api=Telegram('test-secret')
            with self.assertRaises(RuntimeError) as error: api.call('sendMessage',chat_id=1,text='Test')
            self.assertNotIn('test-secret',str(error.exception))
            self.assertEqual(connection.request.call_count,1)
            connection.close.assert_called_once()
            self.assertIsNone(api.connection)


if __name__=='__main__': unittest.main()
