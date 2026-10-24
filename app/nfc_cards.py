"""Owner-approved POS issuance and read-only balance access with NFC credentials.

No Acorn private key is read. The card's random secret is deliberately NOT an
NWC signing key or spending authorization. Explicitly enrolled cards can also
be used with their server-verified PIN through app/nfc_login.py.
"""
import base64
import hashlib
import json
import re
import secrets
import struct
import time
from contextlib import closing
from urllib.parse import urlsplit

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from app.pos_store import POSDenied, POSStore, digest

MIME = 'application/vnd.oakgate.card'
DOMAIN = b'oakgate/nfc/credential/v1\x00'
DOMAIN_V2 = b'oakgate/nfc/credential/v2\x00'
PAIR_TTL = 600
CARD_TTL = 365 * 86400
MAX_BYTES = 400



def card_header(encoded):
    """Read bounded public routing data; issuer authenticates this header with AEAD."""
    from app.identity import social_public_identity
    if not isinstance(encoded, str) or len(encoded) > 536:
        raise ValueError('Invalid card')
    raw = base64.b64decode(encoded, validate=True)
    if not 100 <= len(raw) <= MAX_BYTES or raw[:4] not in (b'OGC1', b'OGC2'):
        raise ValueError('Invalid card')
    size = int.from_bytes(raw[4:6], 'big')
    end = 6 + size
    pinned = raw[:4] == b'OGC2'
    header_end = end + (63 if pinned else 0)
    if not 1 <= size <= 200 or len(raw) != header_end + 92:
        raise ValueError('Invalid card length')
    origin = raw[6:end].decode()
    npub = raw[end:header_end].decode('ascii') if pinned else None
    if pinned and social_public_identity(npub)['npub'] != npub:
        raise ValueError('Invalid issuer public key')
    return raw, origin, npub, header_end


def pairing_code(value):
    if not isinstance(value, str) or not re.fullmatch(r'ogpair1\.[a-f0-9]{32}\.[A-Za-z0-9_-]{43}', value):
        raise POSDenied
    _, ident, secret = value.split('.')
    return ident, secret


def pairing_destination(value, origin):
    """Only this instance's fixed callback page; never fetch a supplied URL."""
    parsed = urlsplit(value)
    if value.startswith(origin + '/account/cards/pair#') and parsed.path == '/account/cards/pair' and not parsed.query:
        pairing_code(parsed.fragment)
        return value
    return None


class CardStore:
    def __init__(self, custody, origin):
        self.custody, self.origin = custody, origin.rstrip('/')
        if urlsplit(self.origin).scheme != 'https' or len(self.origin.encode()) > 200:
            raise ValueError('Card issuance requires a short HTTPS OakGate origin')
        with closing(custody.connect()) as db, db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS nfc_issuer (id INTEGER PRIMARY KEY, encrypted BLOB NOT NULL);
            CREATE TABLE IF NOT EXISTS nfc_pairings (
              id TEXT PRIMARY KEY, terminal TEXT NOT NULL, request_key TEXT NOT NULL,
              verifier TEXT NOT NULL, invitation BLOB, created REAL NOT NULL, expires REAL NOT NULL,
              state TEXT NOT NULL, owner TEXT, wallet_id TEXT, card_id TEXT,
              UNIQUE(terminal,request_key));
            CREATE TABLE IF NOT EXISTS nfc_cards (
              id TEXT PRIMARY KEY, owner TEXT NOT NULL, wallet_id TEXT NOT NULL,
              terminal TEXT NOT NULL, verifier TEXT NOT NULL, payload_hash TEXT NOT NULL,
              payload BLOB, created INTEGER NOT NULL, expires INTEGER NOT NULL,
              activated INTEGER, revoked INTEGER);
            CREATE TABLE IF NOT EXISTS nfc_card_pins (
              pairing TEXT PRIMARY KEY, card_id TEXT UNIQUE,
              verifier BLOB NOT NULL, disclosure BLOB, acknowledged INTEGER);
            CREATE TABLE IF NOT EXISTS nfc_login_requests (
              pairing TEXT PRIMARY KEY, card_id TEXT UNIQUE, identity BLOB NOT NULL,
              requested INTEGER NOT NULL, state TEXT NOT NULL DEFAULT 'requested');
            CREATE INDEX IF NOT EXISTS nfc_card_owner ON nfc_cards(owner);
            ''')
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT encrypted FROM nfc_issuer WHERE id=1').fetchone()
            if not row:
                key = secrets.token_bytes(32)
                db.execute('INSERT INTO nfc_issuer VALUES(1,?)', (custody.cipher.encrypt(DOMAIN + key),))
            else:
                value = custody.cipher.decrypt(row['encrypted'])
                if not value.startswith(DOMAIN) or len(value) != len(DOMAIN)+32:
                    raise ValueError('Invalid NFC issuer key')
                key = value[len(DOMAIN):]
        self.cipher = AESGCM(key)

    def _issuer_npub(self, db):
        from app.identity import social_public_identity
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='service_identity'").fetchone():
            raise ValueError('Configure OAKGATE_SERVICE_NSEC before issuing cards')
        row = db.execute('SELECT npub FROM service_identity WHERE id=1').fetchone()
        if not row:
            raise ValueError('Configure OAKGATE_SERVICE_NSEC before issuing cards')
        return social_public_identity(row['npub'])['npub']

    def _terminal(self, db, ident):
        row = db.execute('SELECT * FROM pos_terminals WHERE id=? AND revoked IS NULL', (ident,)).fetchone()
        if not row:
            raise POSDenied
        POSStore._wallet(db, row['owner'], row['wallet_id'])
        return row

    def _pair(self, db, terminal, request_key):
        self._terminal(db, terminal)
        row = db.execute('SELECT * FROM nfc_pairings WHERE terminal=? AND request_key=?', (terminal, request_key)).fetchone()
        if not row:
            raise POSDenied
        return row

    def _live(self, db, row):
        if row['state'] == 'cancelled' or row['expires'] <= time.time():
            raise POSDenied
        if row['owner']:
            POSStore._wallet(db, row['owner'], row['wallet_id'])

    def _cleanup(self, db):
        db.execute('UPDATE nfc_card_pins SET disclosure=NULL WHERE pairing IN (SELECT id FROM nfc_pairings WHERE expires<?)', (time.time(),))
        db.execute('UPDATE nfc_pairings SET invitation=NULL WHERE expires<?', (time.time(),))
        db.execute('UPDATE nfc_cards SET payload=NULL, revoked=COALESCE(revoked,?) WHERE activated IS NULL AND id IN (SELECT card_id FROM nfc_pairings WHERE expires<?)', (int(time.time()), time.time()))

    def start(self, terminal, request_key):
        if not re.fullmatch(r'[a-zA-Z0-9_-]{16,80}', request_key):
            raise POSDenied
        with closing(self.custody.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            self._terminal(db, terminal)
            self._cleanup(db)
            row = db.execute('SELECT * FROM nfc_pairings WHERE terminal=? AND request_key=?', (terminal, request_key)).fetchone()
            if not row:
                POSStore._limit(db, 'card-start:' + terminal, 30, 3600)
                ident, secret = secrets.token_hex(16), secrets.token_urlsafe(32)
                code = 'ogpair1.' + ident + '.' + secret
                db.execute('INSERT INTO nfc_pairings(id,terminal,request_key,verifier,invitation,created,expires,state) VALUES(?,?,?,?,?,?,?,?)',
                           (ident, terminal, request_key, digest(secret), self.custody.cipher.encrypt(code.encode()), time.time(), time.time()+PAIR_TTL, 'waiting'))
        return self.status(terminal, request_key)

    def inspect(self, code):
        ident, secret = pairing_code(code)
        with closing(self.custody.connect()) as db:
            row = db.execute('SELECT * FROM nfc_pairings WHERE id=?', (ident,)).fetchone()
            if not row or not secrets.compare_digest(row['verifier'], digest(secret)):
                raise POSDenied
            terminal = self._terminal(db, row['terminal'])
            self._live(db, row)
            if row['state'] not in {'waiting', 'pin_pending', 'approved'}:
                raise POSDenied
            return {'terminal_name': terminal['name'], 'pair_code': row['id'][:6].upper(), 'expires': row['expires']}

    def approve(self, code, owner, *, enroll=False, login_identity=None):
        if type(enroll) is not bool:
            raise POSDenied
        if enroll:
            from app.custody import identity_key
            if (not isinstance(login_identity, dict) or not all(isinstance(login_identity.get(k), str) and login_identity[k] for k in ('iss','sub'))
                    or identity_key(login_identity) != owner):
                raise POSDenied
        ident, secret = pairing_code(code)
        with closing(self.custody.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM nfc_pairings WHERE id=?', (ident,)).fetchone()
            if not row or not secrets.compare_digest(row['verifier'], digest(secret)):
                raise POSDenied
            self._terminal(db, row['terminal']); self._live(db, row)
            wallet = POSStore._wallet(db, owner)
            if row['state'] != 'waiting':
                if row['owner'] == owner and row['wallet_id'] == wallet:
                    if row['state'] == 'pin_pending':
                        saved = db.execute('SELECT disclosure FROM nfc_card_pins WHERE pairing=?', (ident,)).fetchone()
                        return {'state': 'pin_pending', 'pin': self.custody.cipher.decrypt(saved['disclosure']).decode()}
                    if row['state'] in {'approved', 'prepared', 'issued'}:
                        return {'state': 'approved'}
                raise POSDenied
            POSStore._limit(db, 'card-approve:' + owner, 10, 3600)
            if enroll:
                db.execute('INSERT INTO nfc_login_requests(pairing,identity,requested) VALUES(?,?,?)',
                           (ident, self.custody.seal(owner, {k: login_identity[k] for k in ('iss','sub')}), int(time.time())))
            pin = f'{secrets.randbelow(10000):04d}'
            salt = secrets.token_bytes(16)
            derived = hashlib.scrypt(pin.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
            # Encrypt even the salted verifier: a DB-only theft must not permit a 10k-PIN search.
            verifier = self.custody.cipher.encrypt(b'oakgate/card-pin/scrypt-v1\x00' + ident.encode() + salt + derived)
            db.execute('INSERT INTO nfc_card_pins(pairing,verifier,disclosure) VALUES(?,?,?)',
                       (ident, verifier, self.custody.cipher.encrypt(pin.encode())))
            db.execute("UPDATE nfc_pairings SET state='pin_pending',owner=?,wallet_id=?,invitation=NULL WHERE id=?", (owner, wallet, ident))
        return {'state': 'pin_pending', 'pin': pin}

    def acknowledge_pin(self, code, owner):
        ident, secret = pairing_code(code)
        with closing(self.custody.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM nfc_pairings WHERE id=?', (ident,)).fetchone()
            if not row or not secrets.compare_digest(row['verifier'], digest(secret)) or row['owner'] != owner:
                raise POSDenied
            self._terminal(db, row['terminal']); self._live(db, row)
            if row['state'] == 'pin_pending':
                db.execute('UPDATE nfc_card_pins SET disclosure=NULL,acknowledged=? WHERE pairing=?', (int(time.time()),ident))
                db.execute("UPDATE nfc_pairings SET state='approved' WHERE id=?", (ident,))
            elif row['state'] not in {'approved','prepared','issued'}:
                raise POSDenied
        return {'state': 'approved'}

    def status(self, terminal, request_key):
        with closing(self.custody.connect()) as db, db:
            self._cleanup(db)
            row = self._pair(db, terminal, request_key)
            result = {'state': row['state'], 'pair_code': row['id'][:6].upper(), 'expires': row['expires']}
            if row['state'] == 'cancelled':
                return result
            if row['expires'] <= time.time() and row['state'] != 'issued':
                return {**result, 'state': 'expired'}
            if row['owner']:
                POSStore._wallet(db, row['owner'], row['wallet_id'])
                handle = db.execute('SELECT handle FROM user_preferences WHERE owner=?', (row['owner'],)).fetchone()
                result['wallet_label'] = handle['handle'] if handle else 'Wallet holder'
            if row['state'] == 'waiting':
                code = self.custody.cipher.decrypt(row['invitation']).decode()
                result['pair_url'] = self.origin + '/account/cards/pair#' + code
            if row['card_id']:
                card = db.execute('SELECT * FROM nfc_cards WHERE id=?', (row['card_id'],)).fetchone()
                result['card_id'] = card['id']
                if card['revoked']:
                    result['state'] = 'revoked'
                elif row['state'] == 'prepared':
                    raw = self.custody.cipher.decrypt(card['payload'])
                    result.update(payload=base64.b64encode(raw).decode(), mime=MIME, byte_count=len(raw))
            return result

    def prepare(self, terminal, request_key):
        with closing(self.custody.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = self._pair(db, terminal, request_key)
            self._live(db, row)
            if row['state'] not in {'approved', 'prepared', 'issued'}:
                raise POSDenied
            if row['state'] == 'approved':
                ident, secret = secrets.token_bytes(16), secrets.token_bytes(32)
                issued = int(time.time()); expires = issued + CARD_TTL
                header = b'OGC2' + struct.pack('>H', len(self.origin.encode())) + self.origin.encode() + self._issuer_npub(db).encode('ascii')
                nonce = secrets.token_bytes(12)
                raw = header + nonce + self.cipher.encrypt(nonce, ident + secret + struct.pack('>QQ', issued, expires), DOMAIN_V2 + header)
                if len(raw) > MAX_BYTES:
                    raise ValueError('Card too large')
                db.execute('INSERT INTO nfc_cards VALUES(?,?,?,?,?,?,?,?,?,NULL,NULL)',
                           (ident.hex(),row['owner'],row['wallet_id'],terminal,hashlib.sha256(secret).hexdigest(),hashlib.sha256(raw).hexdigest(),self.custody.cipher.encrypt(raw),issued,expires))
                db.execute("UPDATE nfc_pairings SET state='prepared',card_id=? WHERE id=?", (ident.hex(),row['id']))
                db.execute('UPDATE nfc_card_pins SET card_id=? WHERE pairing=?', (ident.hex(),row['id']))
                db.execute('UPDATE nfc_login_requests SET card_id=? WHERE pairing=?', (ident.hex(),row['id']))
        return self.status(terminal, request_key)

    def _decode(self, encoded):
        try:
            raw, origin, npub, header_end = card_header(encoded)
            if origin != self.origin:
                raise ValueError()
            if npub:
                with closing(self.custody.connect()) as db:
                    if npub != self._issuer_npub(db):
                        raise ValueError('Issuer identity changed')
            domain = DOMAIN_V2 if npub else DOMAIN
            data = self.cipher.decrypt(raw[header_end:header_end+12], raw[header_end+12:], domain+raw[:header_end])
            if len(data)!=64:
                raise ValueError()
            ident, secret=data[:16].hex(),data[16:48]
            issued,expires=struct.unpack('>QQ',data[48:])
            if not issued <= time.time() < expires or expires-issued != CARD_TTL:
                raise ValueError()
        except Exception:
            raise POSDenied from None
        return raw, ident, secret

    def balance_authority(self, terminal, encoded, *, limit=False):
        raw, ident, secret = self._decode(encoded)
        with closing(self.custody.connect()) as db, db:
            if terminal is not None:
                self._terminal(db, terminal)
            card = db.execute('SELECT * FROM nfc_cards WHERE id=?', (ident,)).fetchone()
            if (not card or card['activated'] is None or card['revoked'] is not None
                    or card['expires'] <= time.time()
                    or not secrets.compare_digest(card['payload_hash'], hashlib.sha256(raw).hexdigest())
                    or not secrets.compare_digest(card['verifier'], hashlib.sha256(secret).hexdigest())):
                raise POSDenied
            POSStore._wallet(db, card['owner'], card['wallet_id'])
            if limit:
                POSStore._limit(db, 'card-balance:' + terminal, 60, 3600)
            return {'owner': card['owner'], 'wallet_id': card['wallet_id']}

    def verify(self, terminal, request_key, encoded):
        raw, ident, secret = self._decode(encoded)
        with closing(self.custody.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row=self._pair(db,terminal,request_key)
            if row['state'] != 'issued':
                self._live(db,row)
            else:
                POSStore._wallet(db,row['owner'],row['wallet_id'])
            card=db.execute('SELECT * FROM nfc_cards WHERE id=?',(ident,)).fetchone()
            if (row['state'] not in {'prepared','issued'} or row['card_id']!=ident or not card or card['revoked']
                    or card['owner']!=row['owner'] or card['wallet_id']!=row['wallet_id']
                    or not secrets.compare_digest(card['payload_hash'],hashlib.sha256(raw).hexdigest())
                    or not secrets.compare_digest(card['verifier'],hashlib.sha256(secret).hexdigest())):
                raise POSDenied
            db.execute('UPDATE nfc_cards SET activated=COALESCE(activated,?),payload=NULL WHERE id=?',(int(time.time()),ident))
            db.execute("UPDATE nfc_pairings SET state='issued',invitation=NULL WHERE id=?",(row['id'],))
        return self.status(terminal,request_key)

    def cancel(self, terminal, request_key):
        with closing(self.custody.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE'); row=self._pair(db,terminal,request_key)
            if row['state']=='issued':
                return {'state':'issued'}
            db.execute("UPDATE nfc_pairings SET state='cancelled',invitation=NULL WHERE id=?",(row['id'],))
            db.execute('UPDATE nfc_card_pins SET disclosure=NULL WHERE pairing=?', (row['id'],))
            db.execute('UPDATE nfc_cards SET revoked=COALESCE(revoked,?),payload=NULL WHERE id=? AND activated IS NULL',(int(time.time()),row['card_id']))
        return {'state':'cancelled'}

    def listing(self, owner):
        with closing(self.custody.connect()) as db:
            rows=db.execute('SELECT c.id,c.created,c.expires,c.activated,c.revoked,l.state AS login_request FROM nfc_cards c LEFT JOIN nfc_login_requests l ON l.card_id=c.id WHERE c.owner=? ORDER BY c.created DESC LIMIT 100',(owner,)).fetchall()
        return [dict(r) for r in rows]

    def revoke(self, owner, ident):
        with closing(self.custody.connect()) as db, db:
            if not db.execute('UPDATE nfc_cards SET revoked=COALESCE(revoked,?),payload=NULL WHERE owner=? AND id=?',(int(time.time()),owner,ident)).rowcount:
                raise POSDenied


    def withdraw_login_request(self, owner, ident):
        with closing(self.custody.connect()) as db, db:
            if not db.execute('SELECT id FROM nfc_cards WHERE owner=? AND id=?',(owner,ident)).fetchone():
                raise POSDenied
            db.execute("UPDATE nfc_login_requests SET state='withdrawn' WHERE card_id=?", (ident,))
