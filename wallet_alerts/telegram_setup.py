"""Bind the owner's confirmed private /start and verify one test delivery.

Run binding only after the user has confirmed starting their bot. It refuses
ambiguous chats and changing an existing recipient. No token is written to disk.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from .core import DeliveryError, Telegram, load_priorities


def bind_started_chat(updates, me, path):
    candidates = set()
    for update in updates:
        message = update.get('message', {})
        chat, sender = message.get('chat', {}), message.get('from', {})
        command = str(message.get('text', '')).split(' ', 1)[0]
        if (chat.get('type') == 'private' and command == '/start'
                and sender.get('is_bot') is False and sender.get('id') == chat.get('id')
                and type(chat.get('id')) is int and chat['id'] > 0):
            candidates.add(chat['id'])
    if len(candidates) != 1:
        raise ValueError('Need exactly one confirmed private /start chat; recipient is ambiguous or absent')
    binding = dict(chat_id=candidates.pop(), chat_type='private', bot_id=me['id'],
                   bot_username=me.get('username'), bound_at=datetime.now(timezone.utc).isoformat())
    path = Path(path)
    if path.exists():
        previous = json.loads(path.read_text(encoding='utf-8'))
        if previous.get('chat_id') != binding['chat_id'] or previous.get('bot_id') != binding['bot_id']:
            raise ValueError('Existing recipient differs; changing it needs an explicit user instruction')
        return previous
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as handle:
        os.chmod(path, 0o600)
        json.dump(binding, handle, ensure_ascii=False, indent=2)
    return binding


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bind-confirmed-start', action='store_true')
    parser.add_argument('--send-test', action='store_true')
    parser.add_argument('--directory', type=Path, default=Path('data/gmgn'))
    args = parser.parse_args()
    directory = args.directory
    path = directory / 'telegram_recipient.json'
    try:
        if args.bind_confirmed_start:
            client = Telegram(os.environ.get('TELEGRAM_BOT_TOKEN'), 'unused_for_read_methods')
            me = client.call('getMe', {})
            if me.get('is_bot') is not True:
                raise ValueError('Telegram account is not a bot')
            updates = client.call('getUpdates', {'timeout': 0, 'limit': 100, 'allowed_updates': ['message']})
            bind_started_chat(updates, me, path)
        client = Telegram.from_saved_recipient(path)
        print('Telegram bot identity and private recipient verified; token not written to disk.')
        if args.send_test:
            receipt_path = directory / 'telegram_test_delivery.json'
            if receipt_path.exists():
                print('A previous test receipt exists; not sending another test automatically.')
                return
            count = len(load_priorities(directory / 'priorities.json'))
            response = client.send(f'✅ <b>Telegram подключён</b>\n\nСохранён твой выбор: '
                f'<b>{count} кошельков</b>.\nПодписки и настройки GMGN остаются без изменений.\n\n'
                'Получение сделок из GMGN пока недоступно. Мониторинг ещё не запущен.\n\n'
                'Это проверочное сообщение.')
            if str(response.get('chat', {}).get('id')) != client.chat_id:
                raise ValueError('Unexpected Telegram test recipient')
            receipt = dict(status='sent_and_acknowledged_by_telegram', message_id=response.get('message_id'),
                           checked_at=datetime.now(timezone.utc).isoformat(), recipient_verified=True)
            receipt_path.write_text(json.dumps(receipt, indent=2), encoding='utf-8')
            print('Test message sent and acknowledged by Telegram for the bound private chat.')
    except DeliveryError as exc:
        parser.exit(1, f'Telegram operation failed: {exc.code}\n')
    except (OSError, ValueError, KeyError, TypeError):
        parser.exit(1, 'Recipient binding/configuration could not be verified; no unverified recipient is used.\n')


if __name__ == '__main__':
    main()
