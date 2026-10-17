"""Interactive VPS-only QR login. Never enter codes or secrets in the chat."""
import asyncio
import getpass
import json
import os
from pathlib import Path
import secrets
import time


def home():
    path = Path.home() / '.config' / 'gmgn-support'
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)
    return path


async def setup():
    from telethon import TelegramClient
    from telethon.errors import SessionPasswordNeededError
    import qrcode
    from wallet_alerts.core import Telegram
    os.umask(0o077)
    directory = home()
    config_file = directory / 'config.json'
    if config_file.exists():
        raise ValueError('Configuration already exists; do not replace the connected identity')
    print('Use credentials from https://my.telegram.org/apps for your OWN application.')
    api_id = int(getpass.getpass('Telegram API ID (hidden): '))
    api_hash = getpass.getpass('Telegram API hash (hidden): ').strip()
    if api_id <= 0 or len(api_hash) != 32 or any(c not in '0123456789abcdefABCDEF' for c in api_hash):
        raise ValueError('Invalid application credentials')
    account = TelegramClient(str(directory / 'account'), api_id, api_hash)
    await account.connect()
    try:
        if not await account.is_user_authorized():
            print('Select the NEW dedicated Telegram account on your phone first.')
            print('Telegram > Settings > Devices > Link Desktop Device. Scan this QR.')
            qr = await account.qr_login()
            picture = qrcode.QRCode(border=2)
            picture.add_data(qr.url)
            picture.print_ascii(invert=True)
            try:
                await qr.wait(timeout=90)
            except SessionPasswordNeededError:
                await account.sign_in(password=getpass.getpass('Telegram 2FA password (hidden, only here): '))
        me = await account.get_me()
        if me.bot:
            raise ValueError('A dedicated user account is required')
        print('Connected user account ID:', me.id)
        if input('Confirm this is the NEW dedicated account (yes/no): ').strip() != 'yes':
            raise ValueError('Account identity not confirmed')
        target = await account.get_entity('gmgnagentapi')
        if getattr(target, 'username', '').lower() != 'gmgnagentapi' or not getattr(target, 'megagroup', False):
            raise ValueError('Official group identity mismatch')
        token = getpass.getpass('Your Telegram CONTROL bot token (hidden, only here): ').strip()
        bot = Telegram(token, 1)
        identity = bot.call('getMe', {})
        if not identity.get('is_bot'):
            raise ValueError('Control bot identity mismatch')
        nonce = secrets.token_hex(10)
        print('In YOUR private chat with @' + identity['username'] + ', send:')
        print('/start ' + nonce)
        print('Do not run another getUpdates consumer for this bot.')
        offset = 0
        bound = None
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline and bound is None:
            updates = bot.call('getUpdates', {'offset': offset, 'timeout': 0, 'limit': 100,
                                             'allowed_updates': ['message']})
            for update in updates:
                offset = max(offset, update['update_id'] + 1)
                message = update.get('message', {})
                sender = message.get('from', {})
                chat = message.get('chat', {})
                if (message.get('text') == '/start ' + nonce and chat.get('type') == 'private'
                        and sender.get('is_bot') is False and sender.get('id') == chat.get('id')):
                    bound = chat['id']
                    print('Owner private chat ID:', bound)
                    break
            if bound is None:
                await asyncio.sleep(2)
        if bound is None or input('Confirm this is YOUR private chat ID (yes/no): ').strip() != 'yes':
            raise ValueError('Owner binding not confirmed')
        config = dict(api_id=api_id, api_hash=api_hash, account_id=me.id, target_id=target.id,
                      bot_token=token, bot_id=identity['id'], owner_id=bound, initial_offset=offset)
        with config_file.open('x', encoding='utf-8') as stream:
            json.dump(config, stream)
        config_file.chmod(0o600)
        print('Setup saved privately. No support messages sent.')
        print('Join https://t.me/gmgnagentapi from the NEW account if group rules permit.')
    finally:
        await account.disconnect()


def main():
    try:
        asyncio.run(setup())
    except (Exception, KeyboardInterrupt) as exc:
        # Exceptions from HTTP/Telegram libraries can include sensitive values.
        print('Setup stopped:', type(exc).__name__, '(no credentials logged).')
        raise SystemExit(1)


if __name__ == '__main__':
    main()
