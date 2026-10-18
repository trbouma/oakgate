"""Durable encrypted custody, independent of ephemeral sign-in sessions."""
import hashlib
import re
import json
import os
import secrets
import sqlite3
import time
from contextlib import closing
from pathlib import Path

from cryptography.fernet import Fernet


class AlreadyConnected(Exception):
    pass


class HandleTaken(Exception):
    pass


class Busy(Exception):
    pass


def identity_key(user):
    return hashlib.sha256(json.dumps([user['iss'], user['sub']], separators=(',', ':')).encode()).hexdigest()


class CustodyStore:
    def __init__(self, directory, encryption_key):
        self.cipher = Fernet(encryption_key)
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = directory / 'custody.sqlite3'
        # Create with restrictive permissions before SQLite opens the file.
        fd = os.open(self.path, os.O_CREAT | os.O_WRONLY, 0o600)
        os.close(fd)
        with closing(self.connect()) as db, db:
            db.execute('''CREATE TABLE IF NOT EXISTS wallets (
                owner TEXT PRIMARY KEY, wallet_id TEXT NOT NULL UNIQUE,
                encrypted BLOB NOT NULL, status TEXT NOT NULL,
                lease TEXT, lease_until REAL NOT NULL DEFAULT 0)''')

            db.execute('CREATE TABLE IF NOT EXISTS user_preferences (owner TEXT PRIMARY KEY, handle TEXT NOT NULL, normalized_handle TEXT NOT NULL UNIQUE)')

    def preference(self, owner):
        with closing(self.connect()) as db:
            row = db.execute('SELECT handle FROM user_preferences WHERE owner=?', (owner,)).fetchone()
        return row['handle'] if row else ''

    def save_handle(self, owner, handle):
        handle = handle.strip()
        if handle and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{2,31}', handle):
            raise ValueError('Use 3–32 letters, numbers, hyphens or underscores, starting with a letter or number.')
        try:
            with closing(self.connect()) as db, db:
                if not handle:
                    db.execute('DELETE FROM user_preferences WHERE owner=?', (owner,))
                else:
                    db.execute('INSERT INTO user_preferences(owner,handle,normalized_handle) VALUES(?,?,?) '
                               'ON CONFLICT(owner) DO UPDATE SET handle=excluded.handle,normalized_handle=excluded.normalized_handle',
                               (owner, handle, handle.lower()))
        except sqlite3.IntegrityError:
            raise HandleTaken from None

    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        return db

    def seal(self, owner, material):
        return self.cipher.encrypt(json.dumps({'owner': owner, 'material': material}).encode())

    def get(self, owner):
        with closing(self.connect()) as db:
            row = db.execute('SELECT * FROM wallets WHERE owner=?', (owner,)).fetchone()
        if row is None:
            return None
        payload = json.loads(self.cipher.decrypt(row['encrypted']))
        if payload['owner'] != owner:
            raise ValueError('Custody identity mismatch')
        return {'material': payload['material'], 'status': row['status']}

    def insert(self, owner, material, status):
        wallet_id = hashlib.sha256(material['npub'].encode()).hexdigest()
        try:
            with closing(self.connect()) as db, db:
                db.execute('INSERT INTO wallets(owner,wallet_id,encrypted,status) VALUES(?,?,?,?)',
                           (owner, wallet_id, self.seal(owner, material), status))
        except sqlite3.IntegrityError:
            raise AlreadyConnected from None

    def acquire(self, owner):
        token = secrets.token_urlsafe(24)
        with closing(self.connect()) as db, db:
            changed = db.execute('UPDATE wallets SET lease=?,lease_until=? WHERE owner=? AND lease_until<?',
                                 (token, time.time() + 90, owner, time.time())).rowcount
        if not changed:
            raise Busy
        return token

    def release(self, owner, token, active=False):
        with closing(self.connect()) as db, db:
            db.execute("UPDATE wallets SET lease=NULL,lease_until=0,status=CASE WHEN ? THEN 'active' ELSE status END WHERE owner=? AND lease=?",
                       (active, owner, token))
