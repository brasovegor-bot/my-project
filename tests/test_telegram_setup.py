import json
from pathlib import Path
import tempfile
import unittest

from wallet_alerts.telegram_setup import bind_started_chat


def start(chat_id):
    return {'message': {'chat': {'id': chat_id, 'type': 'private'},
                        'from': {'id': chat_id, 'is_bot': False}, 'text': '/start'}}


class TelegramBindingTests(unittest.TestCase):
    def test_requires_one_private_chat_and_preserves_existing_recipient(self):
        me = {'id': 777, 'username': 'examplebot', 'is_bot': True}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'recipient.json'
            for updates in ([], [start(1001), start(1002)]):
                with self.assertRaises(ValueError):
                    bind_started_chat(updates, me, path)
                self.assertFalse(path.exists())
            binding = bind_started_chat([start(1001), start(1001)], me, path)
            self.assertEqual(binding['chat_id'], 1001)
            self.assertEqual(binding['bot_id'], 777)
            self.assertNotIn('token', binding)
            with self.assertRaises(ValueError):
                bind_started_chat([start(1002)], me, path)
            self.assertEqual(json.loads(path.read_text())['chat_id'], 1001)

    def test_rejects_group_or_forged_private_sender(self):
        me = {'id': 777, 'is_bot': True}
        with tempfile.TemporaryDirectory() as folder:
            for update in (start(1001), start(1002)):
                if update['message']['chat']['id'] == 1001:
                    update['message']['chat']['type'] = 'group'
                else:
                    update['message']['from']['id'] = 9999
                with self.assertRaises(ValueError):
                    bind_started_chat([update], me, Path(folder) / 'recipient.json')


if __name__ == '__main__':
    unittest.main()
