"""Encrypted payment journal in the custody database; Redis is not involved."""
import json
import secrets
import time
from contextlib import closing


class PaymentBusy(Exception):
    pass


class PaymentStore:
    def __init__(self, custody):
        self.custody = custody
        with closing(custody.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('''CREATE TABLE IF NOT EXISTS incoming_payments (
                id TEXT PRIMARY KEY, owner TEXT NOT NULL, zap_id TEXT UNIQUE,
                created REAL NOT NULL, state TEXT NOT NULL, encrypted BLOB NOT NULL,
                next_check REAL NOT NULL DEFAULT 0, lease TEXT, lease_until REAL NOT NULL DEFAULT 0)''')
            # Existing completed payments need a history-only delivery after
            # upgrade. This flag schedules that work without minting again.
            columns = {row['name'] for row in db.execute('PRAGMA table_info(incoming_payments)')}
            if 'history_written' not in columns:
                db.execute('ALTER TABLE incoming_payments ADD COLUMN history_written INTEGER NOT NULL DEFAULT 0')
            db.execute('CREATE INDEX IF NOT EXISTS incoming_due ON incoming_payments(state,next_check)')
            db.execute('CREATE INDEX IF NOT EXISTS incoming_owner ON incoming_payments(owner,created)')

    def decode(self, row):
        if row is None:
            return None
        payload = json.loads(self.custody.cipher.decrypt(row['encrypted']))
        if payload['owner'] != row['owner'] or payload['material']['id'] != row['id']:
            raise ValueError('Payment identity mismatch')
        return {**payload['material'], 'state': row['state'], 'owner': row['owner'], 'history_written': bool(row['history_written'])}

    def get(self, payment_id):
        with closing(self.custody.connect()) as db:
            return self.decode(db.execute('SELECT * FROM incoming_payments WHERE id=?', (payment_id,)).fetchone())

    def reserve(self, owner, payload, zap_id=None, *, request_id=None):
        now = time.time()
        with closing(self.custody.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            if request_id:
                row = db.execute('SELECT * FROM incoming_payments WHERE id=?', (request_id,)).fetchone()
                if row:
                    existing = self.decode(row)
                    if existing['owner'] != owner or existing['amount'] != payload['amount'] or existing['mint'] != payload['mint']:
                        raise ValueError('Request identity mismatch')
                    return existing, False
            if zap_id:
                row = db.execute('SELECT * FROM incoming_payments WHERE zap_id=?', (zap_id,)).fetchone()
                if row:
                    existing = self.decode(row)
                    if (existing['owner'] != owner or existing['amount'] != payload['amount']
                            or existing.get('zap') != payload.get('zap')):
                        raise ValueError('Zap already belongs to another payment')
                    return existing, False
            # Bound quote creation before contacting the mint. Only the internal POS
            # path supplies a reserved request ID and gets the higher terminal budget.
            if (db.execute('SELECT count(*) FROM incoming_payments WHERE owner=? AND created>?', (owner, now-3600)).fetchone()[0] >= (600 if request_id else 30)
                    or db.execute('SELECT count(*) FROM incoming_payments WHERE created>?', (now-60,)).fetchone()[0] >= 120):
                raise PaymentBusy
            item = {**payload, 'owner': owner, 'id': request_id or secrets.token_hex(16), 'state': 'creating'}
            db.execute('INSERT INTO incoming_payments(id,owner,zap_id,created,state,encrypted) VALUES(?,?,?,?,?,?)',
                       (item['id'], owner, zap_id, now, item['state'], self.custody.seal(owner, item)))
            return item, True

    def save(self, item, token=None, delay=0):
        with closing(self.custody.connect()) as db, db:
            query = 'UPDATE incoming_payments SET state=?,encrypted=?,next_check=?,history_written=? WHERE id=?'
            args = [item['state'], self.custody.seal(item['owner'], item), time.time()+delay, int(bool(item.get('history_written'))), item['id']]
            if token is not None:
                query += ' AND lease=? AND lease_until>?'
                args.extend([token, time.time()])
            if db.execute(query, args).rowcount != 1:
                raise PaymentBusy

    def due(self):
        with closing(self.custody.connect()) as db:
            return [row['id'] for row in db.execute(
                "SELECT id FROM incoming_payments WHERE (state IN ('waiting','credited') OR (state='complete' AND history_written=0)) AND next_check<=? AND lease_until<? ORDER BY next_check LIMIT 8",
                (time.time(), time.time()))]

    def claim(self, payment_id):
        token = secrets.token_hex(16)
        with closing(self.custody.connect()) as db, db:
            changed = db.execute('UPDATE incoming_payments SET lease=?,lease_until=? WHERE id=? AND lease_until<?',
                                 (token, time.time()+120, payment_id, time.time())).rowcount
            if not changed:
                raise PaymentBusy
        return token

    def release(self, payment_id, token):
        with closing(self.custody.connect()) as db, db:
            db.execute('UPDATE incoming_payments SET lease=NULL,lease_until=0 WHERE id=? AND lease=?', (payment_id, token))
