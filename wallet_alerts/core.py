"""Validated trade events, a persistent outbox and Telegram delivery.

No GMGN endpoints are guessed here. Events must come from an authorized,
verified source that identifies swaps, not arbitrary token transfers.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import html
import json
import os
from pathlib import Path
import re
import sqlite3
import urllib.error
from urllib.parse import quote, urlsplit
import urllib.request

CHAINS = {
    'solana': 'https://solscan.io/tx/',
    'eth': 'https://etherscan.io/tx/',
    'base': 'https://basescan.org/tx/',
    'bsc': 'https://bscscan.com/tx/',
    'arbitrum': 'https://arbiscan.io/tx/',
    'hyperevm': None,
    'robinhood': None,
    'arc': None,
    'stable': None,
}
EVM_CHAINS = frozenset(CHAINS) - {'solana'}


def address_key(chain, address):
    if chain not in CHAINS:
        raise ValueError('Unsupported chain')
    if chain == 'solana':
        alphabet = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
        if not isinstance(address, str) or not 32 <= len(address) <= 44:
            raise ValueError('Invalid Solana address')
        value = 0
        for char in address:
            if char not in alphabet:
                raise ValueError('Invalid Solana address')
            value = value * 58 + alphabet.index(char)
        byte_length = (value.bit_length() + 7) // 8 + len(address) - len(address.lstrip('1'))
        if byte_length != 32:
            raise ValueError('Invalid Solana address')
        return address
    if not isinstance(address, str) or not re.fullmatch(r'0x[0-9a-fA-F]{40}', address):
        raise ValueError('Invalid EVM address')
    return address.lower()


def amount(value):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError('Invalid amount') from None
    if not result.is_finite() or result < 0 or result > Decimal('1e30'):
        raise ValueError('Invalid amount')
    return format(result, 'f')


def text_field(value, name, limit=160):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f'Invalid {name}')
    return value.strip()


@dataclass(frozen=True)
class Wallet:
    chain: str
    address: str
    label: str
    priority: bool = False


def load_wallets(path, *, allow_evm_scope=False):
    records = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if not isinstance(records, list):
        raise ValueError('Wallet configuration must be a list')
    result = {}
    for record in records:
        chain = record['chain']
        if chain == 'evm' and allow_evm_scope:
            key = address_key('eth', record['address'])  # Syntax check, no chain assignment.
        else:
            key = address_key(chain, record['address'])
        priority = record.get('priority', False)
        if type(priority) is not bool:
            raise ValueError('priority must be true or false')
        if (chain, key) in result:
            raise ValueError('Duplicate wallet in configuration')
        result[(chain, key)] = Wallet(chain, key, text_field(record['label'], 'label'), priority)
    return result


def load_priorities(path):
    """An EVM selection matches the address on supported GMGN EVM feeds.

    Events still require an actual chain. Never use ``evm`` as an API chain.
    """
    return load_wallets(path, allow_evm_scope=True)


@dataclass(frozen=True)
class Capitalization:
    usd: str
    kind: str
    as_of: str
    basis: str

    @classmethod
    def from_record(cls, record):
        if record['kind'] not in ('market_cap', 'fdv'):
            raise ValueError('Capitalization must distinguish market cap and FDV')
        basis = record.get('basis', 'provider_reported')
        if basis not in ('provider_reported', 'price_times_total_supply'):
            raise ValueError('Invalid capitalization basis')
        if basis == 'price_times_total_supply' and record['kind'] != 'fdv':
            raise ValueError('Total supply calculation is an FDV estimate, not circulating market cap')
        stamp = datetime.fromisoformat(record['as_of'].replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            raise ValueError('Capitalization time must include timezone')
        return cls(amount(record['usd']), record['kind'],
                   stamp.astimezone(timezone.utc).isoformat(), basis)


@dataclass(frozen=True)
class Trade:
    event_id: str
    chain: str
    wallet: str
    side: str
    token_address: str
    token_symbol: str
    token_amount: str
    quote_symbol: str | None
    quote_amount: str | None
    timestamp: str
    tx_hash: str
    gmgn_url: str | None = None
    capitalization: Capitalization | None = None
    usd_amount: str | None = None

    @classmethod
    def from_record(cls, record):
        chain = record['chain']
        if record['side'] not in ('buy', 'sell'):
            raise ValueError('Event must be a classified buy or sell, not a transfer')
        stamp = datetime.fromisoformat(record['timestamp'].replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            raise ValueError('Timestamp must include timezone')
        tx = text_field(record['tx_hash'], 'transaction hash', 100)
        if not re.fullmatch(r'[A-Za-z0-9]+', tx):
            raise ValueError('Invalid transaction hash')
        gmgn_url = record.get('gmgn_url')
        if gmgn_url is not None:
            parts = urlsplit(gmgn_url)
            if (parts.scheme != 'https' or parts.hostname not in ('gmgn.ai', 'www.gmgn.ai')
                    or parts.username or parts.password or len(gmgn_url) > 1500):
                raise ValueError('GMGN link must come from the verified GMGN source')
        quote_symbol, quote_amount = record.get('quote_symbol'), record.get('quote_amount')
        if (quote_symbol is None) != (quote_amount is None):
            raise ValueError('Quote quantity and denomination must be known together')
        return cls(
            text_field(record['event_id'], 'event_id', 200), chain,
            address_key(chain, record['wallet']), record['side'],
            address_key(chain, record['token_address']),
            text_field(record['token_symbol'], 'token_symbol', 40),
            amount(record['token_amount']), text_field(quote_symbol, 'quote_symbol', 40) if quote_symbol is not None else None,
            amount(quote_amount) if quote_amount is not None else None,
            stamp.astimezone(timezone.utc).isoformat(), tx, gmgn_url,
            Capitalization.from_record(record['capitalization'])
            if record.get('capitalization') is not None else None,
            amount(record['usd_amount']) if record.get('usd_amount') is not None else None,
        )

    @property
    def key(self):
        # A transaction can contain multiple swaps. event_id must identify the
        # individual swap in the verified source, not only the tx hash.
        return hashlib.sha256(json.dumps([self.chain, self.wallet, self.event_id]).encode()).hexdigest()


def format_message(trade, wallet):
    e = html.escape
    verb, icon = ('ПОКУПКА', '🟢') if trade.side == 'buy' else ('ПРОДАЖА', '🔴')
    time_utc = datetime.fromisoformat(trade.timestamp)
    from zoneinfo import ZoneInfo
    local = time_utc.astimezone(ZoneInfo('Europe/Moscow')).strftime('%d.%m.%Y %H:%M:%S')
    cap = trade.capitalization
    if cap is None:
        cap_line = 'Капитализация при сделке: <b>нет данных GMGN</b>'
    else:
        title = 'Капитализация' if cap.kind == 'market_cap' else 'FDV (полная оценка)'
        if cap.basis == 'price_times_total_supply':
            title += ' · расчёт'
        if cap.as_of == trade.timestamp:
            cap_line = f'{title} при сделке: <b>${e(cap.usd)}</b>'
        else:
            cap_time = datetime.fromisoformat(cap.as_of).astimezone(ZoneInfo('Europe/Moscow'))
            cap_line = (f'{title}: <b>${e(cap.usd)}</b>\n'
                        f'Оценка GMGN на {cap_time.strftime("%d.%m.%Y %H:%M:%S")} МСК; '
                        'капитализация при сделке неизвестна')
    quote_line = (f'Сумма сделки: <b>{e(trade.quote_amount)} {e(trade.quote_symbol)}</b>'
                  if trade.quote_amount is not None else 'Сумма в криптовалюте: <b>нет подтверждённых данных GMGN</b>')
    if trade.usd_amount is not None:
        quote_line += f'\nСумма в USD: <b>${e(trade.usd_amount)}</b>'
    message = (
        f'{icon} <b>{verb} · {e(trade.token_symbol)}</b>\n'
        f'Кошелёк: <b>{e(wallet.label)}</b>\n'
        f'Адрес: <code>{e(wallet.address)}</code>\n'
        f'Сеть: {e(trade.chain)}\n'
        f'Количество: <b>{e(trade.token_amount)} {e(trade.token_symbol)}</b>\n'
        f'{quote_line}\n'
        f'{cap_line}\n'
        f'Контракт токена: <code>{e(trade.token_address)}</code>\n'
        f'Время: {local} МСК\n'
        f'Транзакция: <code>{e(trade.tx_hash)}</code>'
    )
    if trade.gmgn_url:
        message += f'\n<a href="{e(trade.gmgn_url, quote=True)}">Открыть в GMGN</a>'
    return message


class DeliveryError(Exception):
    def __init__(self, code, retry_after=None):
        super().__init__(f'Telegram delivery error {code}')
        self.code, self.retry_after = code, retry_after


class Telegram:
    def __init__(self, token, chat_id):
        if not token or not chat_id:
            raise ValueError('Telegram token and chat ID are required')
        # Keep injected proxy bindings usable; do not reject placeholders as tokens.
        self.token, self.chat_id = token, str(chat_id)

    @classmethod
    def from_environment(cls):
        return cls(os.environ.get('TELEGRAM_BOT_TOKEN'), os.environ.get('TELEGRAM_CHAT_ID'))

    @classmethod
    def from_saved_recipient(cls, path):
        """Use a private recipient bound by the owner's confirmed /start.

        The binding records bot ID so replacing a bot token cannot silently
        send this user's alerts through another bot. No token is saved here.
        """
        binding = json.loads(Path(path).read_text(encoding='utf-8'))
        chat_id, bot_id = binding.get('chat_id'), binding.get('bot_id')
        if (type(chat_id) is not int or chat_id <= 0 or type(bot_id) is not int
                or bot_id <= 0 or binding.get('chat_type') != 'private'):
            raise ValueError('Invalid private Telegram recipient binding')
        client = cls(os.environ.get('TELEGRAM_BOT_TOKEN'), chat_id)
        me = client.call('getMe', {})
        if me.get('id') != bot_id or me.get('is_bot') is not True:
            raise ValueError('Telegram token does not match the recipient binding')
        return client

    def call(self, method, payload):
        if method not in ('getMe', 'getUpdates', 'sendMessage', 'getChat', 'getChatMember'):
            raise ValueError('Unsupported Telegram method')
        request = urllib.request.Request(
            f'https://api.telegram.org/bot{self.token}/{method}',
            data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                result = json.load(response)
        except urllib.error.HTTPError as exc:
            retry = None
            try:
                body = json.load(exc)
                retry = body.get('parameters', {}).get('retry_after')
            except (ValueError, TypeError):
                pass
            raise DeliveryError(exc.code, retry) from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            # Never include the request URL/token in error output.
            raise DeliveryError('connection_or_response') from None
        if not result.get('ok'):
            raise DeliveryError(result.get('error_code', 'response'),
                                result.get('parameters', {}).get('retry_after'))
        return result['result']

    def send(self, message):
        return self.call('sendMessage', {'chat_id': self.chat_id, 'text': message,
            'parse_mode': 'HTML', 'link_preview_options': {'is_disabled': True}})


class Outbox:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.execute('PRAGMA journal_mode=WAL')
        self.connection.executescript('''
            CREATE TABLE IF NOT EXISTS alerts (
                event_key TEXT PRIMARY KEY, body TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending', telegram_message_id INTEGER,
                created_at TEXT NOT NULL, error_code TEXT, next_attempt_at REAL NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS source_state (
                source TEXT PRIMARY KEY, cursor TEXT NOT NULL
            );
        ''')
        self.connection.commit()

    def close(self):
        self.connection.close()

    def enqueue(self, trade, wallets):
        wallet = wallets.get((trade.chain, trade.wallet))
        if wallet is None and trade.chain in EVM_CHAINS:
            wallet = wallets.get(('evm', trade.wallet))
        if not wallet or not wallet.priority:
            return False
        body = format_message(trade, wallet)
        with self.connection:
            row = self.connection.execute('INSERT OR IGNORE INTO alerts(event_key,body,created_at) '
                'VALUES(?,?,?)', (trade.key, body, datetime.now(timezone.utc).isoformat()))
        return row.rowcount == 1

    def deliver_one(self, client, now=None):
        import time
        now = time.time() if now is None else now
        row = self.connection.execute("SELECT event_key,body FROM alerts WHERE status='pending' "
            'AND next_attempt_at<=? ORDER BY created_at,event_key LIMIT 1', (now,)).fetchone()
        if not row:
            return False
        key, body = row
        try:
            message = client.send(body)
        except DeliveryError as exc:
            delay = max(float(exc.retry_after or 0), 5) if exc.code == 429 else 30
            with self.connection:
                self.connection.execute('UPDATE alerts SET error_code=?,next_attempt_at=? WHERE event_key=?',
                    (str(exc.code), now + delay, key))
            raise
        with self.connection:
            self.connection.execute("UPDATE alerts SET status='sent',telegram_message_id=?,error_code=NULL "
                                    'WHERE event_key=?', (message['message_id'], key))
        return True

    def counts(self):
        return dict(self.connection.execute('SELECT status,count(*) FROM alerts GROUP BY status').fetchall())

    def save_cursor(self, source, cursor):
        with self.connection:
            self.connection.execute('INSERT INTO source_state(source,cursor) VALUES(?,?) '
                'ON CONFLICT(source) DO UPDATE SET cursor=excluded.cursor', (source, cursor))

    def cursor(self, source):
        row = self.connection.execute('SELECT cursor FROM source_state WHERE source=?', (source,)).fetchone()
        return row[0] if row else None
