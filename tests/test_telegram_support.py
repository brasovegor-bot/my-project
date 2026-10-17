import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from telegram_support.state import State, validate_body
from telegram_support.worker import planner, preview


class SupportApprovalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'state.sqlite'
        self.state = State(self.path)

    def tearDown(self):
        self.state.db.close()
        self.temp.cleanup()

    def draft(self):
        return self.state.propose('first', 'Please investigate the read-only API response.')

    def test_foreign_sender_group_and_unshown_draft_cannot_approve(self):
        row = self.draft()
        command = '/approve ' + row['id']
        self.assertFalse(self.state.decide(command, 77, 77, 77))
        self.state.previewed(row['id'], 5)
        self.assertFalse(self.state.decide(command, 88, 77, 77))
        self.assertFalse(self.state.decide(command, 77, -100, 77))
        self.assertTrue(self.state.decide(command, 77, 77, 77))
        self.assertFalse(self.state.decide(command, 77, 77, 77))

    def test_preview_contains_exact_target_body_and_approval_id(self):
        row = self.draft()
        class Bot:
            chat_id = '77'
            def call(self, method, payload):
                self.payload = payload
                return {'chat': {'id': 77}, 'message_id': 4}
        bot = Bot()
        preview(bot, self.state, row)
        self.assertIn('https://t.me/gmgnagentapi', bot.payload['text'])
        self.assertIn(row['body'], bot.payload['text'])
        self.assertIn('/approve ' + row['id'], bot.payload['text'])
        self.assertEqual(self.state.rows('pending')[0]['preview_id'], 4)

    def test_approval_is_bound_to_immutable_body_and_source_dedup(self):
        row = self.draft()
        again = self.state.propose('first', 'A different draft cannot replace the first.')
        self.assertEqual(again['body'], row['body'])
        self.state.previewed(row['id'], 5)
        self.state.decide('/approve ' + row['id'], 77, 77, 77)
        self.state.db.execute('UPDATE messages SET body=? WHERE id=?', ('Changed text', row['id']))
        self.state.db.commit()
        with self.assertRaises(ValueError):
            self.state.begin_send(row['id'])

    def test_crash_after_send_marker_becomes_unknown_not_replayable(self):
        row = self.draft()
        self.state.previewed(row['id'], 5)
        self.state.decide('/approve ' + row['id'], 77, 77, 77)
        self.state.begin_send(row['id'])
        self.state.db.close()
        self.state = State(self.path)
        self.assertEqual(len(self.state.rows('delivery_unknown')), 1)
        with self.assertRaises(ValueError):
            self.state.begin_send(row['id'])
        self.assertEqual(self.state.rows('approved'), [])

    def test_receipt_and_scoped_thread_replies(self):
        row = self.draft()
        self.state.previewed(row['id'], 5)
        self.state.decide('/approve ' + row['id'], 77, 77, 77)
        self.state.begin_send(row['id'])
        self.state.finish_send(row['id'], 100)
        self.assertFalse(self.state.add_reply(101, 99, 'Unrelated private topic'))
        self.assertTrue(self.state.add_reply(102, 100, 'Relevant reply'))
        self.assertTrue(self.state.add_reply(103, 102, 'Reply to the same thread'))
        self.assertFalse(self.state.add_reply(103, 102, 'Duplicate'))
        self.assertEqual(self.state.sent_ids(), {100})
        status = json.dumps(self.state.status())
        self.assertNotIn(row['body'], status)
        self.assertNotIn('Relevant reply', status)
        self.assertFalse(self.state.status()['resolved'])

    def test_rejection_and_confidential_content(self):
        row = self.draft()
        self.state.previewed(row['id'], 5)
        self.assertTrue(self.state.decide('/reject ' + row['id'], 77, 77, 77))
        with self.assertRaises(ValueError):
            self.state.begin_send(row['id'])
        for body in ['0x' + '1' * 40, '-----BEGIN OPENSSH PRIVATE KEY-----\nabc', 'X-Amz-Signature=abc']:
            with self.assertRaises(ValueError):
                validate_body(body)

    def test_planner_has_no_shell_or_sensitive_environment_and_failure_is_closed(self):
        seen = {}
        def run(args, **kwargs):
            seen.update(args=args, **kwargs)
            output = Path(args[args.index('--output-last-message') + 1])
            output.write_text(json.dumps({'message': 'Which documented access requirement applies?'}))
            return SimpleNamespace(returncode=0)
        with patch.dict('os.environ', {'GMGN_API_KEY': 'do-not-forward', 'TELEGRAM_BOT_TOKEN': 'do-not-forward'}):
            with patch('telegram_support.worker.subprocess.run', side_effect=run):
                text = planner({'reply': 'untrusted support text'}, Path(self.temp.name))
        self.assertEqual(text, 'Which documented access requirement applies?')
        self.assertNotIn('GMGN_API_KEY', seen['env'])
        self.assertNotIn('TELEGRAM_BOT_TOKEN', seen['env'])
        self.assertIn('--ignore-user-config', seen['args'])
        self.assertIn('shell_tool', seen['args'])
        self.assertIn('unified_exec', seen['args'])
        self.assertIn('apps', seen['args'])
        self.assertIn('computer_use', seen['args'])
        self.assertIn('UNTRUSTED', seen['input'])
        with patch('telegram_support.worker.subprocess.run', return_value=SimpleNamespace(returncode=1)):
            with self.assertRaises(ValueError):
                planner({}, Path(self.temp.name))


if __name__ == '__main__':
    unittest.main()
