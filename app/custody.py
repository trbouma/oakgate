"""Durable encrypted custody, independent of ephemeral sign-in sessions."""
from app.localization import N_
from app.currency_rates import CURRENCY_METADATA
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
from app.localization import SUPPORTED_LANGUAGES, supported_language


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

            db.execute('CREATE TABLE IF NOT EXISTS user_social_preferences (owner TEXT PRIMARY KEY, npub TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS user_currency_preferences (owner TEXT PRIMARY KEY, currency TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS user_display_preferences (owner TEXT PRIMARY KEY, language TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS lightning_handles (normalized_handle TEXT PRIMARY KEY, owner TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS user_preferences (owner TEXT PRIMARY KEY, handle TEXT NOT NULL, normalized_handle TEXT NOT NULL UNIQUE)')
            db.execute("INSERT OR IGNORE INTO lightning_handles(normalized_handle,owner) SELECT p.normalized_handle,p.owner FROM user_preferences p JOIN wallets w ON p.owner=w.owner WHERE w.status='active'")

    def preference(self, owner):
        with closing(self.connect()) as db:
            row = db.execute('SELECT handle FROM user_preferences WHERE owner=?', (owner,)).fetchone()
        return row['handle'] if row else ''

    def language(self, owner):
        with closing(self.connect()) as db:
            row = db.execute('SELECT language FROM user_display_preferences WHERE owner=?', (owner,)).fetchone()
        return supported_language(row['language']) if row else 'en'

    def currency(self, owner, default='USD'):
        with closing(self.connect()) as db:
            row = db.execute('SELECT currency FROM user_currency_preferences WHERE owner=?', (owner,)).fetchone()
        return row['currency'] if row and row['currency'] in CURRENCY_METADATA else default

    def social_npub(self, owner):
        with closing(self.connect()) as db:
            row = db.execute('SELECT npub FROM user_social_preferences WHERE owner=?', (owner,)).fetchone()
        return row['npub'] if row else ''

    def ensure_default_handle(self, owner, pubkey_hex):
        """Allocate once, atomically, without replacing a user's chosen handle."""
        from app.handles import default_handle_from_pubkey
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT handle FROM user_preferences WHERE owner=?', (owner,)).fetchone()
            if existing:
                return existing['handle']
            for attempt in range(1000):
                handle = default_handle_from_pubkey(pubkey_hex, attempt=attempt)
                reserved = db.execute('SELECT owner FROM lightning_handles WHERE normalized_handle=?', (handle,)).fetchone()
                if reserved and reserved['owner'] != owner:
                    continue
                if db.execute('SELECT 1 FROM user_preferences WHERE normalized_handle=?', (handle,)).fetchone():
                    continue
                db.execute('INSERT INTO user_preferences(owner,handle,normalized_handle) VALUES(?,?,?)',
                           (owner, handle, handle))
                db.execute("INSERT OR IGNORE INTO lightning_handles(normalized_handle,owner) SELECT ?,owner FROM wallets WHERE owner=? AND status='active'", (handle, owner))
                return handle
            raise HandleTaken

    def save_handle(self, owner, handle, *, language=None, currency=None, social_npub=None):
        if social_npub is not None:
            from app.identity import social_public_identity
            social_npub = social_npub.strip()
            if social_npub:
                social_npub = social_public_identity(social_npub)['npub']
        if currency is not None and currency not in CURRENCY_METADATA:
            raise ValueError(N_('Choose a supported currency.'))
        if language is not None and language not in SUPPORTED_LANGUAGES:
            raise ValueError(N_('Choose a supported language.'))
        handle = handle.strip()
        if handle and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{2,31}', handle):
            raise ValueError('Use 3–32 letters, numbers, hyphens or underscores, starting with a letter or number.')
        try:
            with closing(self.connect()) as db, db:
                db.execute('BEGIN IMMEDIATE')
                if social_npub is not None:
                    if social_npub:
                        db.execute('INSERT INTO user_social_preferences(owner,npub) VALUES(?,?) '
                                   'ON CONFLICT(owner) DO UPDATE SET npub=excluded.npub', (owner, social_npub))
                    else:
                        db.execute('DELETE FROM user_social_preferences WHERE owner=?', (owner,))
                if currency is not None:
                    db.execute('INSERT INTO user_currency_preferences(owner,currency) VALUES(?,?) '
                               'ON CONFLICT(owner) DO UPDATE SET currency=excluded.currency', (owner, currency))
                if language is not None:
                    db.execute('INSERT INTO user_display_preferences(owner,language) VALUES(?,?) '
                               'ON CONFLICT(owner) DO UPDATE SET language=excluded.language', (owner, language))
                reserved = db.execute('SELECT owner FROM lightning_handles WHERE normalized_handle=?', (handle.lower(),)).fetchone()
                if reserved and reserved['owner'] != owner:
                    raise HandleTaken
                if not handle:
                    db.execute('DELETE FROM user_preferences WHERE owner=?', (owner,))
                else:
                    db.execute('INSERT INTO user_preferences(owner,handle,normalized_handle) VALUES(?,?,?) '
                               'ON CONFLICT(owner) DO UPDATE SET handle=excluded.handle,normalized_handle=excluded.normalized_handle',
                               (owner, handle, handle.lower()))
                    db.execute("INSERT OR IGNORE INTO lightning_handles(normalized_handle,owner) SELECT ?,owner FROM wallets WHERE owner=? AND status='active'", (handle.lower(), owner))
        except sqlite3.IntegrityError:
            raise HandleTaken from None

    def address_owner(self, handle):
        # Once advertised for payments, a handle cannot be reassigned to someone
        # else. Renaming/removing it disables discovery but preserves reservation.
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT p.owner FROM user_preferences p JOIN wallets w ON p.owner=w.owner WHERE p.normalized_handle=? AND w.status='active'", (handle,)).fetchone()
            if not row:
                return None
            db.execute('INSERT OR IGNORE INTO lightning_handles(normalized_handle,owner) VALUES(?,?)', (handle, row['owner']))
            reserved = db.execute('SELECT owner FROM lightning_handles WHERE normalized_handle=?', (handle,)).fetchone()
            if reserved['owner'] != row['owner']:
                raise HandleTaken
            return row['owner']

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
                if status == 'active':
                    db.execute('INSERT OR IGNORE INTO lightning_handles(normalized_handle,owner) SELECT normalized_handle,owner FROM user_preferences WHERE owner=?', (owner,))
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
            db.execute("INSERT OR IGNORE INTO lightning_handles(normalized_handle,owner) SELECT p.normalized_handle,p.owner FROM user_preferences p JOIN wallets w ON p.owner=w.owner WHERE p.owner=? AND w.status='active'", (owner,))
