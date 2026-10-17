"""Durable approvals and receipts. No model is allowed to approve a message."""
from datetime import datetime, timezone
import hashlib
import json
import re
import secrets
import sqlite3

TARGET = 'gmgnagentapi'


def now():
    return datetime.now(timezone.utc).isoformat()


def validate_body(body):
    if not isinstance(body, str) or not 1 <= len(body.strip()) <= 2800:
        raise ValueError('Invalid message length')
    # Supplemental guard. Human review remains mandatory for every message.
    if re.search(r'-----BEGIN .*PRIVATE KEY-----|\b\d{6,}:[A-Za-z0-9_-]{25,}|\bgmg[_A-Za-z0-9]{20,}|\b0x[a-fA-F0-9]{40}\b|X-Amz-Signature=', body):
        raise ValueError('Potential confidential content')
    return body.strip()


class State:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS messages (
          id TEXT PRIMARY KEY, source_key TEXT UNIQUE NOT NULL, body TEXT NOT NULL,
          digest TEXT NOT NULL, status TEXT NOT NULL, reply_to INTEGER,
          preview_id INTEGER, receipt_id INTEGER, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS replies (
          id INTEGER PRIMARY KEY, text TEXT NOT NULL, parent INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, at TEXT NOT NULL,
          stage TEXT NOT NULL, message_id TEXT, detail TEXT);
        ''')
        self.db.commit()
        # A crash after marking sending is not evidence of rejection. No replay.
        self.db.execute("UPDATE messages SET status='delivery_unknown' WHERE status='sending'")
        self.db.commit()

    def get(self, key, default=None):
        row = self.db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def put(self, key, value):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)', (key, json.dumps(value)))

    def event(self, stage, message_id=None, detail=None):
        with self.db:
            self.db.execute('INSERT INTO events(at,stage,message_id,detail) VALUES (?,?,?,?)',
                            (now(), stage, message_id, detail))

    def propose(self, source_key, body, reply_to=None):
        body = validate_body(body)
        message_id = secrets.token_hex(6)
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO messages VALUES (?,?,?,?,?,?,?,?,?)',
                (message_id, source_key, body, hashlib.sha256(body.encode()).hexdigest(),
                 'pending', reply_to, None, None, now()))
        row = self.db.execute('SELECT * FROM messages WHERE source_key=?', (source_key,)).fetchone()
        return dict(row)

    def rows(self, status):
        return [dict(r) for r in self.db.execute('SELECT * FROM messages WHERE status=? ORDER BY created_at', (status,))]

    def previewed(self, message_id, receipt_id):
        if type(receipt_id) is not int:
            raise ValueError('Invalid preview receipt')
        with self.db:
            self.db.execute("UPDATE messages SET preview_id=? WHERE id=? AND status='pending'", (receipt_id, message_id))

    def decide(self, command, sender_id, chat_id, owner_id):
        if sender_id != owner_id or chat_id != owner_id:
            return False
        match = re.fullmatch(r'/(approve|reject) ([0-9a-f]{12})', command.strip())
        if not match:
            return False
        action, message_id = match.groups()
        with self.db:
            result = self.db.execute("UPDATE messages SET status=? WHERE id=? AND status='pending' AND preview_id IS NOT NULL",
                ('approved' if action == 'approve' else 'rejected', message_id))
        if result.rowcount:
            self.event('owner_' + action, message_id)
        return result.rowcount == 1

    def begin_send(self, message_id):
        row = self.db.execute('SELECT * FROM messages WHERE id=?', (message_id,)).fetchone()
        if not row or row['status'] != 'approved':
            raise ValueError('Exact message has not been approved')
        if row['digest'] != hashlib.sha256(row['body'].encode()).hexdigest():
            raise ValueError('Approved body changed')
        validate_body(row['body'])
        with self.db:
            self.db.execute("UPDATE messages SET status='sending' WHERE id=?", (message_id,))
        self.event('sending', message_id)
        return dict(row)

    def finish_send(self, message_id, receipt_id):
        if type(receipt_id) is not int or receipt_id <= 0:
            raise ValueError('Invalid receipt')
        with self.db:
            result = self.db.execute("UPDATE messages SET status='sent',receipt_id=? WHERE id=? AND status='sending'",
                (receipt_id, message_id))
        if result.rowcount != 1:
            raise ValueError('Unexpected send state')
        self.event('sent_receipt_verified', message_id)

    def uncertain(self, message_id):
        with self.db:
            self.db.execute("UPDATE messages SET status='delivery_unknown' WHERE id=? AND status='sending'", (message_id,))
        self.event('delivery_unknown_no_replay', message_id)

    def sent_ids(self):
        return {r[0] for r in self.db.execute("SELECT receipt_id FROM messages WHERE status='sent'")}

    def add_reply(self, message_id, parent, text):
        known = self.sent_ids() | {r[0] for r in self.db.execute('SELECT id FROM replies')}
        if parent not in known or not isinstance(text, str) or not text.strip():
            return False
        with self.db:
            result = self.db.execute('INSERT OR IGNORE INTO replies VALUES (?,?,?)', (message_id, text[:6000], parent))
        return result.rowcount == 1

    def status(self):
        return {'counts': {r[0]: r[1] for r in self.db.execute('SELECT status,count(*) FROM messages GROUP BY status')},
                'last_events': [dict(r) for r in self.db.execute('SELECT * FROM events ORDER BY id DESC LIMIT 15')],
                'resolved': False}
