import json
import copy
import random
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from engine import Engine
from storage import Store
from bot import SurveyBot, Telegram
from presentation import caption, needs_details

class FakeTelegram:

    def __init__(self):
        self.calls = []

    def call(self, method, **args):
        self.calls.append((method, args))
        return {'message_id': len(self.calls)}

class SurveyTests(unittest.TestCase):

    def setUp(self):
        self.e = Engine()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)
        self.addCleanup(self.store.db.close)
        self.addCleanup(self.store.contacts.close)
        self.api = FakeTelegram()
        self.bot = SurveyBot(self.api, self.store)

    def test_welcome_details_do_not_start_or_change_answers(self):
        self.bot.start(1)
        welcome=self.api.calls[-1][1]
        self.assertLess(len(welcome['text']),240)
        self.assertIn('🐶',welcome['text'])
        self.assertNotIn('12 месяцев',welcome['text'])
        s=self.store.load(1)
        self.bot.handle({'callback_query':{'id':'privacy','data':'privacy','message':{'chat':{'id':1,'type':'private'}}}})
        self.assertIn('12 месяцев',self.api.calls[-1][1]['text'])
        self.assertEqual(self.store.load(1),s)
        self.bot.start(1)
        self.assertEqual(self.api.calls[-1][1]['text'],welcome['text'])
        self.bot.handle({'callback_query':{'id':'begin','data':'begin','message':{'chat':{'id':1,'type':'private'}}}})
        self.assertTrue(self.store.load(1)['started'])

    def test_no_episode_or_unknown(self):
        for v in ['c1', 'c6', None]:
            route = self.e.route({'Q08': v})
            self.assertNotIn('Q09', route)
            self.assertNotIn('Q14', route)
            self.assertIn('Q15a', route)
            self.assertIn('Q15b', route)

    def test_contact_route(self):
        for v in ['c2', None]:
            self.assertNotIn('Q33', self.e.route({'Q32': v}))
        self.assertIn('Q33', self.e.route({'Q32': 'c1'}))

    def test_remaining_bounds_contain_real_completions_in_all_modes(self):
        for mode in ('core',):
            for run in range(25):
                rng = random.Random(str(run) + mode)
                answers = {'S03': 'c1'}
                done = ['S03']
                prefixes = []
                while True:
                    route = self.e.route(answers, mode, 'progress-test')
                    qid = next((q for q in route if q not in done), None)
                    if qid is None:
                        break
                    prefixes.append((copy.deepcopy(answers), done[:]))
                    q = self.e.questions[qid]
                    if rng.random() < 0.15:
                        value = None
                    elif q.get('options'):
                        value = rng.choice(q['options'])['code']
                    else:
                        value = 'example' if q['type'] == 'text' else 0
                    if q['type'] == 'multi' and value is not None:
                        value = [value]
                    answers[qid] = self.e.validate(qid, value)
                    done.append(qid)
                    answers = self.e.prune(answers, mode)
                final = self.e.route(answers, mode, 'progress-test')
                last_high = None
                for known, completed in prefixes:
                    low, high = self.e.remaining_bounds(known, completed, mode, 'progress-test')
                    actual = sum((q not in completed for q in final))
                    self.assertLessEqual(low, actual, (mode, run, completed))
                    self.assertLessEqual(actual, high, (mode, run, completed))
                    if last_high is not None:
                        self.assertLess(high, last_high)
                    last_high = high
                self.assertEqual(self.e.remaining_bounds(answers, done, mode), (0, 0))

    def test_remaining_bounds_treat_screening_and_skips_correctly(self):
        self.assertEqual(self.e.remaining_bounds({}, []), (1, 1))
        self.assertEqual(self.e.remaining_bounds({'S03': None}, ['S03']), (0, 0))
        answers = {'S03': 'c1', 'Q08': None, 'Q26': None, 'Q32': None}
        done = self.e.route(answers)
        self.assertEqual(self.e.remaining_bounds(answers, done), (0, 0))
        self.assertNotIn('Q33', self.e.route(answers))

    def test_progress_header_resumes_and_does_not_change_on_toggle_or_note(self):
        s = self.at_question('Q12')
        header = self.bot.progress_header(s)
        self.assertIn('Осталось', self.api.calls[-1][1]['text'])
        self.assertIn('включая этот', header)
        self.callback(s, 'c1')
        s = self.store.load(1)
        self.assertEqual(header, self.bot.progress_header(s))
        self.callback(s, 'prevnote')
        s = self.store.load(1)
        self.assertIn('прогресс не меняется', self.api.calls[-1][1]['text'])
        self.assertEqual(header, self.bot.progress_header(s))
        self.callback(s, 'cancelnote')
        self.bot.start(1)
        self.assertTrue(self.api.calls[-1][1]['text'].startswith(header))

    def test_final_contact_counts_as_one_step_and_back_reopens_it(self):
        s = self.at_question('Q32')
        self.callback(s, 'c1')
        s = self.store.load(1)
        self.assertEqual(self.bot.current(s), 'Q33')
        self.assertIn('Осталось 1 вопрос', self.api.calls[-1][1]['text'])
        self.bot.answer(1, s, 'example-contact')
        s = self.store.load(1)
        self.assertIn('Опрос завершён', self.api.calls[-1][1]['text'])
        self.bot.back(1, s)
        self.assertIn('Осталось 1 вопрос', self.api.calls[-1][1]['text'])

    def test_screenout_complete(self):
        self.bot.start(1)
        s = self.store.load(1)
        s['started'] = True
        self.bot.answer(1, s, 'c4')
        state = self.store.load(1)
        self.assertTrue(state['complete'])
        self.assertTrue(state['screened_out'])

    def test_skipped_screening_ends_survey(self):
        self.bot.start(1)
        s = self.store.load(1)
        s['started'] = True
        self.bot.answer(1, s, None)
        self.assertTrue(self.store.load(1)['screened_out'])

    def test_toggle_updates_same_message(self):
        self.bot.start(1)
        s = self.store.load(1)
        s['started'] = True
        s['answers'] = {'S03': 'c1'}
        s['done'] = self.e.route(s['answers'])[:self.e.route(s['answers']).index('Q34')]
        self.bot.render(1, s)
        s = self.store.load(1)
        self.bot.handle({'callback_query': {'id': 'toggle', 'data': s['nonce'] + '|c1', 'message': {'chat': {'id': 1, 'type': 'private'}}}})
        self.assertEqual(self.api.calls[-1][0], 'editMessageText')

    def at_question(self, qid):
        self.bot.start(1)
        s = self.store.load(1)
        s['started'] = True
        s['answers'] = {'S03': 'c1', 'Q08': 'c2', 'Q09': 'c1'}
        route = self.e.route(s['answers'], seed=s['participant'])
        s['done'] = route[:route.index(qid)]
        self.store.save(1, s)
        self.bot.render(1, s)
        return self.store.load(1)

    def callback(self, s, action):
        self.bot.handle({'callback_query': {'id': 'test', 'data': s['nonce'] + '|' + action, 'message': {'chat': {'id': 1, 'type': 'private'}}}})

    def test_readable_labels_are_short_unique_and_not_truncated(self):
        for qid, q in self.e.questions.items():
            labels = [caption(qid, o) for o in q.get('options', [])]
            self.assertEqual(len(labels), len(set(labels)), qid)
            for label in labels:
                self.assertLessEqual(len(label), 28, (qid, label))
                self.assertFalse(label.isdigit(), (qid, label))
        self.assertEqual(caption('S03', {'code': 'c2', 'label': 'unused'}), 'Ухаживаем вместе')

    def test_text_buttons_keep_shuffled_codes_and_selection(self):
        s = self.at_question('Q34')
        args = self.api.calls[-1][1]
        options = self.e.options('Q34', s['participant'])
        option_rows = [row for row in args['reply_markup']['inline_keyboard'] if row[0]['callback_data'].split('|')[-1] in {o['code'] for o in options}]
        self.assertTrue(all((len(row) == 1 for row in option_rows)))
        self.assertEqual([row[0]['text'] for row in option_rows], [caption('Q34', o) for o in options])
        self.assertEqual([row[0]['callback_data'].split('|')[-1] for row in option_rows], [o['code'] for o in options])
        self.callback(s, options[0]['code'])
        buttons = [b['text'] for row in self.api.calls[-1][1]['reply_markup']['inline_keyboard'] for b in row]
        self.assertIn('✓ ' + caption('Q34', options[0]), buttons)
        self.assertNotIn('Добавить пояснение', buttons)

    def test_full_wording_can_expand_without_changing_answer(self):
        s = self.at_question('Q34')
        self.callback(s, 'details')
        s = self.store.load(1)
        self.assertEqual(self.api.calls[-1][0], 'editMessageText')
        for option in self.e.options('Q34', s['participant']):
            self.assertIn(option['label'], self.api.calls[-1][1]['text'])
        self.assertNotIn('Q34', s['answers'])
        self.callback(s, 'details')
        self.assertNotIn('show_options', self.store.load(1))

    def test_note_after_answer_keeps_next_question_and_context(self):
        s = self.at_question('Q11')
        code = self.e.options('Q11', s['participant'])[0]['code']
        self.bot.answer(1, s, [code])
        s = self.store.load(1)
        self.assertEqual(self.bot.current(s), 'Q12')
        self.assertNotIn('note_for', s)
        self.callback(s, 'prevnote')
        s = self.store.load(1)
        args = self.api.calls[-1][1]
        self.assertIn(self.e.questions['Q11']['title'], args['text'])
        self.assertIn(next((o['label'] for o in self.e.questions['Q11']['options'] if o['code'] == code)), args['text'])
        self.assertIn('Напишите пояснение сообщением', args['text'])
        with self.assertRaises(ValueError):
            self.bot.answer(1, s, 'x' * 501)
        self.assertEqual(s['note_for'], 'Q11')
        self.bot.start(1)
        self.assertEqual(self.store.load(1)['note_for'], 'Q11')
        self.bot.answer(1, self.store.load(1), 'Тестовое пояснение')
        state = self.store.load(1)
        self.assertEqual(state['answers']['Q11_note'], 'Тестовое пояснение')
        self.assertEqual(self.bot.current(state), 'Q12')
        self.bot.back(1, state)
        self.assertEqual(self.bot.current(self.store.load(1)), 'Q11')
        self.assertNotIn('Q11_note', self.store.load(1)['answers'])

    def test_cancel_note_preserves_next_selection_and_saved_note(self):
        s = self.at_question('Q11')
        self.bot.answer(1, s, ['c1'])
        s = self.store.load(1)
        self.callback(s, 'c1')
        s = self.store.load(1)
        s['answers']['Q11_note'] = 'Сохранённое'
        self.store.save(1, s)
        self.callback(s, 'prevnote')
        s = self.store.load(1)
        self.callback(s, 'cancelnote')
        s = self.store.load(1)
        self.assertEqual(s['selected'], ['c1'])
        self.assertEqual(s['answers']['Q11_note'], 'Сохранённое')
        self.assertEqual(self.bot.current(s), 'Q12')

    def test_question_option_cannot_be_recorded_as_note(self):
        s = self.at_question('Q11')
        self.bot.answer(1, s, ['c1'])
        s = self.store.load(1)
        self.callback(s, 'prevnote')
        s = self.store.load(1)
        self.callback(s, 'c2')
        self.assertEqual(self.store.load(1)['note_for'], 'Q11')
        self.assertNotIn('Q11_note', self.store.load(1)['answers'])

    def test_simulated_full_route_and_separate_contact(self):
        self.bot.start(1)
        s = self.store.load(1)
        s['started'] = True
        self.store.save(1, s)
        while not self.store.load(1)['complete']:
            s = self.store.load(1)
            qid = self.bot.current(s)
            q = self.e.questions[qid]
            if qid == 'S03':
                value = 'c1'
            elif qid == 'Q08':
                value = 'c2'
            elif qid == 'Q09':
                value = 'c1'
            elif qid == 'Q26':
                value = 'c1'
            elif qid == 'Q32':
                value = 'c1'
            elif qid == 'Q33':
                value = '@test_participant'
            elif q['type'] == 'single':
                value = q['options'][0]['code']
            elif q['type'] == 'multi':
                value = [q['options'][0]['code']]
            elif q['type'] == 'money':
                value = '0'
            else:
                value = None
            self.bot.answer(1, s, value)
        exported = json.dumps(self.store.export())
        self.assertNotIn('@test_participant', exported)
        self.assertNotIn('Q33', exported)
        self.assertNotIn('chat_id', exported)
        self.assertEqual(self.store.contacts.execute('SELECT contact FROM contacts').fetchone()[0], '@test_participant')
        self.store.delete(1)
        self.assertEqual(self.store.contacts.execute('SELECT count(*) FROM contacts').fetchone()[0], 0)

    def test_stale_callback_does_not_advance(self):
        self.bot.start(1)
        s = self.store.load(1)
        s['started'] = True
        self.bot.render(1, s)
        self.bot.handle({'callback_query': {'id': 'cb', 'data': 'old|c1', 'message': {'chat': {'id': 1, 'type': 'private'}}}})
        self.assertEqual(self.store.load(1)['done'], [])

    def test_unexpected_group_ignored(self):
        self.bot.handle({'message': {'chat': {'id': 2, 'type': 'group'}, 'text': '/start'}})
        self.assertIsNone(self.store.load(2))

    def test_failure_before_state_change_can_retry(self):
        self.bot.start(1)
        s = self.store.load(1)
        update = {'update_id': 50, 'callback_query': {'id': 'cb', 'data': 'begin', 'message': {'chat': {'id': 1, 'type': 'private'}}}}
        normal_call = self.api.call

        def fail(method, **args):
            raise RuntimeError('Simulated ACK failure')
        self.api.call = fail
        with self.assertRaises(RuntimeError):
            self.bot.process(update)
        self.assertEqual(self.store.offset(), 0)
        self.assertFalse(self.store.load(1)['started'])
        self.api.call = normal_call
        self.bot.process(update)
        self.assertTrue(self.store.load(1)['started'])
        self.assertEqual(self.store.offset(), 51)

    def test_source_and_optional_other_no_extra_steps(self):
        self.assertEqual(len(self.e.questions), 17)
        self.assertEqual(sum(('note' in q for q in self.e.questions.values())), 5)
        self.assertEqual(self.e.order, 'S03 Q01 Q03 Q34 Q04 Q08 Q09 Q11 Q12 Q13 Q15 Q15a Q15b Q16 Q27a Q32 Q33'.split())
        self.assertFalse(any((q.endswith('_other') for q in self.e.route({'Q34': ['c5']}))))
        self.assertEqual(self.e.validate('Q34_note', '  задача  '), 'задача')
        for qid, codes in [('Q34', ['c1', 'c6']), ('Q11', ['c1', 'c8']), ('Q12', ['c1', 'c9'])]:
            with self.assertRaises(ValueError):
                self.e.validate(qid, codes)

    def test_old_or_skipped_date_clears_case_answers_and_notes(self):
        for date in ('c5', None):
            a = {'S03': 'c1', 'Q08': 'c2', 'Q09': date, 'Q11': ['c1'], 'Q11_note': 'скрыто', 'Q15a': 'c3'}
            b = self.e.prune(a, 'core')
            self.assertNotIn('Q11', b)
            self.assertNotIn('Q11_note', b)
            self.assertEqual(b['Q15a'], 'c3')
        self.assertEqual(len(self.e.route({'S03': 'c1', 'Q08': 'c2', 'Q09': 'c1', 'Q32': 'c1'})), 17)
        self.assertEqual(len(self.e.route({'S03': 'c1', 'Q08': 'c1', 'Q32': 'c2'})), 11)

    def test_shuffle_preserves_special_tail(self):
        options = self.e.options('Q34', 'seed')
        self.assertEqual(options, self.e.options('Q34', 'seed'))
        self.assertEqual([o['code'] for o in options[-3:]], ['c5', 'c6', 'c7'])

    def test_old_sessions_require_explicit_reset_on_every_input(self):
        self.bot.start(1)
        s = self.store.load(1)
        s['version'] = 'old'
        s['done'] = ['removed']
        s['started'] = True
        self.store.save(1, s)
        inputs = [{'message': {'chat': {'id': 1, 'type': 'private'}, 'text': t}} for t in ['/start', '/back', '/skip', 'answer']]
        inputs.append({'callback_query': {'id': 'x', 'data': 'begin', 'message': {'chat': {'id': 1, 'type': 'private'}}}})
        for update in inputs:
            self.bot.handle(update)
            self.assertEqual(self.store.load(1), s)
            self.assertIn('Анкета сократилась', self.api.calls[-1][1]['text'])
        self.bot.handle({'message': {'chat': {'id': 1, 'type': 'private'}, 'text': '/delete'}})
        self.bot.start(1)
        self.assertEqual(self.store.load(1)['version'], self.e.instrument['version'])

    def test_delivery_failure_cannot_replay_contact_as_next_answer(self):
        s = self.at_question('Q32')
        self.bot.answer(1, s, 'c1')
        update = {'update_id': 100, 'message': {'chat': {'id': 1, 'type': 'private'}, 'text': '@synthetic'}}
        normal = self.api.call

        def fail(*a, **kw):
            raise RuntimeError('delivery failed')
        self.api.call = fail
        with self.assertRaises(RuntimeError):
            self.bot.process(update)
        state = self.store.load(1)
        self.assertTrue(state['complete'])
        self.assertEqual(self.store.offset(), 101)
        self.api.call = normal
        self.bot.process(update)
        self.assertEqual(self.store.load(1), state)
        self.assertNotIn('@synthetic', json.dumps(state))

class TelegramTransportTests(unittest.TestCase):

    def test_server_closed_connection_is_recreated(self):
        with patch('bot.http.client.HTTPSConnection') as factory:
            response = factory.return_value.getresponse.return_value
            response.status = 200
            response.will_close = True
            response.read.return_value = b'{"ok":true,"result":true}'
            api = Telegram('test-secret')
            api.call('getMe')
            api.call('getMe')
            self.assertEqual(factory.call_count, 2)
            self.assertIsNone(api.connection)

    def test_rate_limit_is_reported_without_resending(self):
        with patch('bot.http.client.HTTPSConnection') as factory, patch('bot.time.sleep') as sleep:
            response = factory.return_value.getresponse.return_value
            response.status = 429
            response.will_close = False
            response.read.return_value = b'{"ok":false,"parameters":{"retry_after":5}}'
            api = Telegram('test-secret')
            with self.assertRaisesRegex(RuntimeError, '429'):
                api.call('sendMessage', chat_id=1, text='Test')
            sleep.assert_called_once_with(5)
            self.assertEqual(factory.return_value.request.call_count, 1)

    def test_serial_calls_reuse_https_connection(self):
        with patch('bot.http.client.HTTPSConnection') as factory:
            connection = factory.return_value
            response = connection.getresponse.return_value
            response.status = 200
            response.will_close = False
            response.read.return_value = b'{"ok":true,"result":{"message_id":1}}'
            api = Telegram('test-secret')
            api.call('answerCallbackQuery', callback_query_id='cb')
            api.call('sendMessage', chat_id=1, text='Test')
            self.assertEqual(factory.call_count, 1)
            self.assertEqual(connection.request.call_count, 2)
            self.assertEqual(response.read.call_count, 2)
            self.assertEqual(factory.call_args.args, ('api.telegram.org',))

    def test_failed_send_is_not_retried_and_error_hides_secret(self):
        with patch('bot.http.client.HTTPSConnection') as factory:
            connection = factory.return_value
            connection.getresponse.side_effect = OSError('test-secret')
            api = Telegram('test-secret')
            with self.assertRaises(RuntimeError) as error:
                api.call('sendMessage', chat_id=1, text='Test')
            self.assertNotIn('test-secret', str(error.exception))
            self.assertEqual(connection.request.call_count, 1)
            connection.close.assert_called_once()
            self.assertIsNone(api.connection)
if __name__ == '__main__':
    unittest.main()
