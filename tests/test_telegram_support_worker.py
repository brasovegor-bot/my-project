"""Exercise the complete tick with fake Telegram transport, never live sends."""
import asyncio
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

from telegram_support.state import State
from telegram_support.worker import tick


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.state = State(self.directory / 'state.sqlite')
        self.config = dict(bot_token='test', owner_id=77, bot_id=11, api_id=1,
                           api_hash='test', account_id=88, target_id=99, initial_offset=0)
        self.updates = []
        self.sent = []
        self.fail = False
        self.restricted = False
        self.messages = []
        outer = self

        class Bot:
            def __init__(self, token, owner):
                self.chat_id = owner
            def call(self, method, payload):
                if method == 'getMe':
                    return dict(id=11, is_bot=True)
                if method == 'getUpdates':
                    updates, outer.updates = outer.updates, []
                    return updates
                if method == 'sendMessage':
                    return dict(chat=dict(id=77), message_id=9)
                raise AssertionError(method)

        class Account:
            async def connect(self): pass
            async def disconnect(self): pass
            async def is_user_authorized(self): return True
            async def get_me(self): return NS(id=88, bot=False)
            async def get_entity(self, target):
                return NS(id=99, username='gmgnagentapi', default_banned_rights=NS(
                    view_messages=False, send_messages=outer.restricted, send_plain=False))
            async def get_permissions(self, target, own):
                return NS(has_left=False, is_banned=False, is_admin=False,
                          has_default_permissions=True)
            async def send_message(self, target, body, **kwargs):
                outer.sent.append((target.id, body, kwargs))
                if outer.fail:
                    raise ConnectionError('ambiguous delivery')
                return NS(id=100, raw_text=body, peer_id=NS(channel_id=99))
            async def iter_messages(self, *args, **kwargs):
                for message in outer.messages:
                    if message.id > kwargs['min_id']:
                        yield message

        self.bot_patch = patch('telegram_support.worker.Telegram', Bot)
        self.account_patch = patch('telethon.TelegramClient', lambda *a, **kw: Account())
        self.bot_patch.start()
        self.account_patch.start()

    def tearDown(self):
        self.account_patch.stop()
        self.bot_patch.stop()
        self.state.db.close()
        self.temp.cleanup()

    def run_tick(self):
        asyncio.run(tick(self.directory, self.state, self.config))

    def approve(self, row, sender=77):
        self.updates.append(dict(update_id=2, message=dict(text='/approve ' + row['id'],
                            **{'from': dict(id=sender), 'chat': dict(id=77)})))

    def test_real_tick_waits_for_owner_sends_exactly_once_and_scopes_replies(self):
        self.run_tick()
        row = self.state.rows('pending')[0]
        self.assertEqual(self.sent, [])
        self.approve(row, sender=999)
        self.run_tick()
        self.assertEqual(self.sent, [])
        self.approve(row)
        self.run_tick()
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0][:2], (99, row['body']))
        self.messages = [NS(id=101, sender_id=999, raw_text='unrelated secret',
                            reply_to=NS(reply_to_msg_id=50)),
                         NS(id=102, sender_id=999, raw_text='Which CLI version?',
                            reply_to=NS(reply_to_msg_id=100))]
        with patch('telegram_support.worker.planner', return_value='We used the official CLI.') as plan:
            self.run_tick()
        self.assertNotIn('unrelated secret', str(plan.call_args))
        self.assertIn('Which CLI version?', str(plan.call_args))
        self.assertEqual(len(self.sent), 1)  # new draft also requires approval
        self.assertEqual(self.state.rows('pending')[0]['reply_to'], 102)

    def test_ambiguous_send_is_never_replayed(self):
        self.run_tick()
        self.approve(self.state.rows('pending')[0])
        self.fail = True
        with self.assertRaises(ConnectionError):
            self.run_tick()
        self.run_tick()
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(len(self.state.rows('delivery_unknown')), 1)

    def test_default_group_send_ban_blocks_even_approved_draft(self):
        self.run_tick()
        self.approve(self.state.rows('pending')[0])
        self.restricted = True
        self.run_tick()
        self.assertEqual(self.sent, [])
        self.assertEqual(len(self.state.rows('approved')), 1)
