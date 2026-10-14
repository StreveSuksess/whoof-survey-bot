"""Time-injected reminder tests; never contact Telegram or real participants."""
import tempfile
import unittest
from unittest.mock import patch
from bot import SurveyBot
from storage import Store
from test_survey import FakeTelegram


class ReminderTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store=self.open_store(); self.api=FakeTelegram()
        self.bot=SurveyBot(self.api,self.store)

    def open_store(self):
        store=Store(self.tmp.name)
        self.addCleanup(store.db.close); self.addCleanup(store.contacts.close)
        return store

    def callback(self,data):
        return {'callback_query':{'id':'test','data':data,'message':{'chat':{'id':1,'type':'private'}}}}

    def begin(self):
        with patch('storage.time.time',return_value=0):
            self.bot.start(1); self.bot.handle(self.callback('begin'))
        return self.store.load(1)

    def test_threshold_and_restart_never_repeat(self):
        self.begin(); self.api.calls.clear()
        self.bot.send_due_reminder(now=86399); self.assertEqual(self.api.calls,[])
        self.bot.send_due_reminder(now=86400); self.assertEqual(len(self.api.calls),1)
        rows=self.api.calls[0][1]['reply_markup']['inline_keyboard']
        self.assertEqual([b['text'] for row in rows for b in row],['Продолжить','Не напоминать'])
        restarted=SurveyBot(self.api,self.open_store())
        restarted.send_due_reminder(now=999999); self.assertEqual(len(self.api.calls),1)

    def test_activity_resets_deadline_but_render_does_not(self):
        self.begin()
        with patch('storage.time.time',return_value=100):
            self.bot.handle({'message':{'chat':{'id':1,'type':'private'},'text':'/help'}})
        with patch('storage.time.time',return_value=200): self.bot.render(1,self.store.load(1))
        self.api.calls.clear(); self.bot.send_due_reminder(now=86400)
        self.assertEqual(self.api.calls,[])
        self.bot.send_due_reminder(now=86500); self.assertEqual(len(self.api.calls),1)

    def test_intro_complete_screened_out_and_old_version_excluded(self):
        for field,value in [('started',False),('complete',True),('screened_out',True),('version','old')]:
            self.store.delete(1); s=self.begin(); s[field]=value; self.store.save(1,s)
            self.api.calls.clear(); self.bot.send_due_reminder(now=86400)
            self.assertEqual(self.api.calls,[],field)

    def test_resume_uses_current_state_and_never_rearms(self):
        s=self.begin(); self.bot.send_due_reminder(now=86400)
        data=self.api.calls[-1][1]['reply_markup']['inline_keyboard'][0][0]['callback_data']
        s=self.store.load(1); s['answers']={'S03':'c1'}; s['done']=['S03']; s['selected']=['c1']
        self.store.save(1,s); expected=self.bot.current(s)
        self.bot.handle(self.callback(data))
        resumed=self.store.load(1)
        self.assertEqual(resumed['answers'],s['answers']); self.assertEqual(resumed['selected'],['c1'])
        self.assertEqual(resumed['render_key'],expected)
        self.assertEqual(self.api.calls[-1][0],'sendMessage')
        self.api.calls.clear(); self.bot.send_due_reminder(now=9999999999)
        self.assertEqual(self.api.calls,[])

    def test_resume_preserves_optional_note_and_selections(self):
        s=self.begin(); s['answers']={'S03':'c1','Q34':'c2'}; s['done']=['S03','Q34']
        s['note_for']='Q34'; s['selected']=['c2']; self.store.save(1,s)
        self.bot.handle(self.callback('reminder:resume:'+s['participant']))
        actual=self.store.load(1)
        self.assertEqual(actual['note_for'],'Q34')
        self.assertEqual(actual['answers'],s['answers']); self.assertEqual(actual['selected'],['c2'])
        self.assertIn('Необязательное пояснение',self.api.calls[-1][1]['text'])

    def test_ack_failure_does_not_checkpoint_answer(self):
        self.begin(); s=self.store.load(1)
        update=self.callback(s['nonce']+'|c1'); update['update_id']=50
        with patch.object(self.api,'call',side_effect=RuntimeError('unavailable')):
            with self.assertRaises(RuntimeError): self.bot.process(update)
        self.assertEqual(self.store.offset(),0)
        self.assertEqual(self.store.load(1)['answers'],{})

    def test_opt_out_preserves_answers_contacts_and_survives_restart(self):
        s=self.begin(); self.store.save_contact(s['participant'],'synthetic contact')
        self.bot.send_due_reminder(now=86400)
        data=self.api.calls[-1][1]['reply_markup']['inline_keyboard'][1][0]['callback_data']
        self.bot.handle(self.callback(data))
        self.assertEqual(self.store.load(1),s)
        self.assertEqual(self.store.contacts.execute('SELECT COUNT(*) FROM contacts').fetchone()[0],1)
        self.api.calls.clear(); SurveyBot(self.api,self.open_store()).send_due_reminder(now=9999999999)
        self.assertEqual(self.api.calls,[])

    def test_advance_opt_out(self):
        with patch('storage.time.time',return_value=0):
            self.bot.start(1)
            self.bot.handle({'message':{'chat':{'id':1,'type':'private'},'text':'/noremind'}})
            self.bot.handle(self.callback('begin'))
        self.api.calls.clear(); self.bot.send_due_reminder(now=86400)
        self.assertEqual(self.api.calls,[])

    def test_stale_callback_does_not_recreate_or_reopen(self):
        s=self.begin(); data='reminder:resume:'+s['participant']
        self.store.delete(1); self.bot.handle(self.callback(data)); self.assertIsNone(self.store.load(1))
        newer=self.begin(); self.bot.handle(self.callback(data)); self.assertEqual(self.store.load(1),newer)
        newer['complete']=True; self.store.save(1,newer)
        self.bot.handle(self.callback('reminder:resume:'+newer['participant']))
        self.assertTrue(self.store.load(1)['complete'])

    def test_failed_send_is_not_retried(self):
        self.begin()
        with patch.object(self.bot,'send',side_effect=RuntimeError('unavailable')) as send:
            self.bot.send_due_reminder(now=86400); self.assertEqual(send.call_count,1)
            self.bot.send_due_reminder(now=9999999999); self.assertEqual(send.call_count,1)

    def test_claim_is_atomic_and_delete_removes_metadata(self):
        s=self.begin(); other=self.open_store()
        self.assertTrue(self.store.claim_reminder(1,s['participant'],86400))
        self.assertFalse(other.claim_reminder(1,s['participant'],86400))
        self.store.delete(1)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM survey_reminders').fetchone()[0],0)
        self.begin(); self.api.calls.clear(); self.bot.send_due_reminder(now=86400)
        self.assertEqual(len(self.api.calls),1)

    def test_existing_session_seed_and_activity_do_not_checkpoint_offset(self):
        s=self.begin(); self.store.db.execute('DELETE FROM survey_reminders'); self.store.db.commit()
        with patch('storage.time.time',return_value=50): self.store.save(1,s)
        SurveyBot(self.api,self.open_store())
        self.api.calls.clear(); self.bot.send_due_reminder(now=86449); self.assertEqual(self.api.calls,[])
        with self.store.update(42): self.store.reminder_activity(1,s['participant'],now=60)
        self.assertEqual(self.store.offset(),0)
        self.bot.send_due_reminder(now=86460); self.assertEqual(len(self.api.calls),1)
        self.assertEqual(self.store.load(1),s)
        self.assertEqual(self.store.export(),[])


if __name__=='__main__': unittest.main()
