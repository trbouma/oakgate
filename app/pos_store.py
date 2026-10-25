"""Durable receive-only terminal authority; never reads or decrypts wallet material."""
from pos.protocol import CARD_OPS
import base64
import hashlib
import json
import secrets
import time
from contextlib import closing

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils

SESSION_TTL = 7 * 86400
ACTIVATION_TTL = 86400
CHALLENGE_TTL = 60


class POSDenied(Exception):
    pass


class POSLimited(Exception):
    pass


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def decode(value):
    if not isinstance(value, str) or len(value) > 512:
        raise POSDenied
    try:
        return base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True)
    except ValueError:
        raise POSDenied from None


def public_key(value):
    raw = decode(value)
    if len(raw) != 65 or raw[0] != 4:
        raise POSDenied
    try:
        return ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), raw)
    except ValueError:
        raise POSDenied from None


def verify(key, message, signature):
    raw = decode(signature)
    if len(raw) != 64:
        raise POSDenied
    der = utils.encode_dss_signature(int.from_bytes(raw[:32], 'big'), int.from_bytes(raw[32:], 'big'))
    try:
        public_key(key).verify(der, message.encode(), ec.ECDSA(hashes.SHA256()))
    except InvalidSignature:
        raise POSDenied from None


class POSStore:
    def __init__(self, custody, audience):
        self.connect = custody.connect
        self.audience = audience

    @staticmethod
    def _limit(db, name, maximum, window):
        now = time.time()
        db.execute('DELETE FROM pos_limits WHERE expires < ?', (now,))
        row = db.execute('SELECT count FROM pos_limits WHERE bucket=?', (name,)).fetchone()
        if row and row['count'] >= maximum:
            raise POSLimited
        db.execute('INSERT INTO pos_limits VALUES(?,1,?) ON CONFLICT(bucket) DO UPDATE SET count=pos_limits.count+1',
                   (name, now + window))

    def limit_source(self, source, receiving=False):
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            self._limit(db, ('receive-source:' if receiving else 'source:') + digest(source), 1200 if receiving else 120, 60)

    @staticmethod
    def _wallet(db, owner, wallet_id=None):
        row = db.execute("SELECT wallet_id FROM wallets WHERE owner=? AND status='active'", (owner,)).fetchone()
        if not row or (wallet_id is not None and row['wallet_id'] != wallet_id):
            raise POSDenied
        return row['wallet_id']

    def provision(self, owner, name):
        name = name.strip()
        if not name or len(name) > 60 or any(ord(c) < 32 for c in name):
            raise ValueError('Use a terminal name of 1–60 characters.')
        token = secrets.token_urlsafe(32)
        ident = secrets.token_hex(16)
        now = time.time()
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            wallet = self._wallet(db, owner)
            self._limit(db, 'owner:' + owner, 10, 3600)
            if db.execute('SELECT count(*) FROM pos_terminals WHERE owner=? AND revoked IS NULL', (owner,)).fetchone()[0] >= 10:
                raise POSLimited
            db.execute('INSERT INTO pos_terminals(id,owner,wallet_id,name,verifier,created,activation_until) VALUES(?,?,?,?,?,?,?)',
                       (ident, owner, wallet, name, digest(token), now, now + ACTIVATION_TTL))
            db.execute('INSERT INTO pos_audit(terminal,action,at) VALUES(?,?,?)', (ident, 'provisioned', now))
        return 'ogpos1.' + ident + '.' + token

    def listing(self, owner):
        with closing(self.connect()) as db:
            rows = db.execute('SELECT id,name,fingerprint,activated,last_seen,revoked,activation_until,wallet_id FROM pos_terminals WHERE owner=? ORDER BY created DESC LIMIT 100', (owner,)).fetchall()
            wallet = db.execute("SELECT wallet_id FROM wallets WHERE owner=? AND status='active'", (owner,)).fetchone()
        result = []
        for row in rows:
            item = dict(row)
            item['status'] = ('Revoked' if item['revoked'] else 'Wallet unavailable' if not wallet or wallet['wallet_id'] != item['wallet_id']
                              else 'Active' if item['activated'] else 'Expired' if item['activation_until'] < time.time() else 'Awaiting activation')
            item.pop('wallet_id')
            result.append(item)
        return result

    def revoke(self, owner, ident):
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT id FROM pos_terminals WHERE id=? AND owner=?', (ident, owner)).fetchone()
            if not row:
                raise POSDenied
            db.execute('UPDATE pos_terminals SET revoked=COALESCE(revoked,?) WHERE id=?', (time.time(), ident))
            db.execute('DELETE FROM pos_sessions WHERE terminal=?', (ident,))
            db.execute('DELETE FROM pos_challenges WHERE terminal=?', (ident,))
            db.execute('INSERT INTO pos_audit(terminal,action,at) VALUES(?,?,?)', (ident, 'revoked', time.time()))

    def _terminal(self, db, ident):
        row = db.execute('SELECT * FROM pos_terminals WHERE id=? AND revoked IS NULL', (ident,)).fetchone()
        if not row:
            raise POSDenied
        self._wallet(db, row['owner'], row['wallet_id'])
        return row

    def _credential(self, db, credential):
        try:
            version, ident, secret = credential.split('.')
        except (ValueError, AttributeError):
            raise POSDenied from None
        if version != 'ogpos1':
            raise POSDenied
        row = self._terminal(db, ident)
        if not secrets.compare_digest(row['verifier'], digest(secret)):
            raise POSDenied
        if not row['public_key'] and row['activation_until'] < time.time():
            raise POSDenied
        return row

    def _session(self, db, token):
        row = db.execute('SELECT * FROM pos_sessions WHERE verifier=? AND expires>?', (digest(token), time.time())).fetchone()
        if not row:
            raise POSDenied
        return row, self._terminal(db, row['terminal'])

    def _challenge(self, db, row, session, operation, key, payload='{}'):
        now = time.time()
        db.execute('DELETE FROM pos_challenges WHERE expires<?', (now,))
        db.execute('DELETE FROM pos_sessions WHERE expires<?', (now,))
        self._limit(db, 'challenge:' + row['id'], 120, 60)
        nonce = secrets.token_urlsafe(32)
        path = '/api/pos/v1/' + operation
        # Browser signs the exact UTF-8 string returned here. No client serialization ambiguity.
        body = json.dumps([row['id'], key], separators=(',', ':')) if operation == 'activate' else payload
        message = json.dumps(['oakgate-pos-proof-v1', self.audience, row['id'], session,
                              'POST', path, '', digest(body), nonce, int(now + CHALLENGE_TTL)], separators=(',', ':'))
        db.execute('INSERT INTO pos_challenges VALUES(?,?,?,?,?,?,?)',
                   (nonce, row['id'], session, operation, key, message, now + CHALLENGE_TTL))
        return {'challenge': nonce, 'message': message}

    def activation_challenge(self, credential, key):
        public_key(key)
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = self._credential(db, credential)
            if row['public_key'] and row['public_key'] != key:
                raise POSDenied
            return self._challenge(db, row, '', 'activate', key)

    def _consume(self, db, ident, session, operation, key, challenge, signature, payload=None):
        row = db.execute('SELECT * FROM pos_challenges WHERE id=? AND expires>?', (challenge, time.time())).fetchone()
        if not row or (row['terminal'], row['session'], row['operation'], row['public_key']) != (ident, session, operation, key):
            raise POSDenied
        if (json.loads(row['message'])[1] != self.audience
                or (payload is not None and json.loads(row['message'])[7] != digest(payload))):
            raise POSDenied
        verify(key, row['message'], signature)
        db.execute('DELETE FROM pos_challenges WHERE id=?', (challenge,))

    def activate(self, credential, key, challenge, signature):
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = self._credential(db, credential)
            if row['public_key'] and row['public_key'] != key:
                raise POSDenied
            self._consume(db, row['id'], '', 'activate', key, challenge, signature)
            now = time.time()
            fingerprint = hashlib.sha256(decode(key)).hexdigest()
            db.execute('UPDATE pos_terminals SET public_key=?,fingerprint=?,activated=COALESCE(activated,?),last_seen=? WHERE id=?',
                       (key, fingerprint, now, now, row['id']))
            # Reactivation replaces prior sessions, including a session whose HTTP response was lost.
            db.execute('DELETE FROM pos_sessions WHERE terminal=?', (row['id'],))
            db.execute('DELETE FROM pos_challenges WHERE terminal=?', (row['id'],))
            token, sid = secrets.token_urlsafe(32), secrets.token_hex(16)
            db.execute('INSERT INTO pos_sessions VALUES(?,?,?,?)', (sid, row['id'], digest(token), now + SESSION_TTL))
            db.execute('INSERT INTO pos_audit(terminal,action,at) VALUES(?,?,?)', (row['id'], 'activated', now))
            return {'session': token, 'expires_in': SESSION_TTL}

    def challenge(self, token, operation, payload='{}'):
        if operation not in ({'config', 'logout', 'receive-config', 'receive', 'receipt'} | CARD_OPS):
            raise POSDenied
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            session, terminal = self._session(db, token)
            return self._challenge(db, terminal, session['id'], operation, terminal['public_key'], payload)

    def authorized(self, token, operation, challenge, signature):
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            session, terminal = self._session(db, token)
            self._consume(db, terminal['id'], session['id'], operation, terminal['public_key'], challenge, signature)
            if operation == 'logout':
                db.execute('DELETE FROM pos_sessions WHERE id=?', (session['id'],))
                db.execute('DELETE FROM pos_challenges WHERE session=?', (session['id'],))
                db.execute('INSERT INTO pos_audit(terminal,action,at) VALUES(?,?,?)', (terminal['id'], 'logged-out', time.time()))
                return {'status': 'signed-out'}
            if operation != 'config':
                raise POSDenied
            db.execute('UPDATE pos_terminals SET last_seen=? WHERE id=?', (time.time(), terminal['id']))
            return {'name': terminal['name'], 'fingerprint': terminal['fingerprint'],
                    'scope': 'receive-only', 'payments_available': True}

    def receiving_authority(self, token, operation, challenge, signature, payload):
        """Internal authority only; never serialize this result to the terminal."""
        if operation not in ({'receive-config', 'receive', 'receipt'} | CARD_OPS):
            raise POSDenied
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            session, terminal = self._session(db, token)
            self._consume(db, terminal['id'], session['id'], operation,
                          terminal['public_key'], challenge, signature, payload)
            return {k: terminal[k] for k in ('id', 'owner', 'wallet_id')}
