import json
import tempfile
import unittest
from pathlib import Path
from engine import Engine
from storage import Store
from bot import SurveyBot


class FakeTelegram:
    def __init__(self): self.calls=[]
    def call(self,method,**args): self.calls.append((method,args)); return {'message_id':len(self.calls)}


class SurveyTests(unittest.TestCase):
    def setUp(self):
        self.e=Engine(); self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store=Store(self.tmp.name); self.api=FakeTelegram(); self.bot=SurveyBot(self.api,self.store)
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


if __name__=='__main__': unittest.main()
