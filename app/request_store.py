"""Encrypted, owner-bound request tickets in the backed-up custody database."""
import json
import secrets
import time
from contextlib import closing

class RequestStore:
    def __init__(self, custody):
        self.custody = custody

    def save(self, owner, data):
        ident = secrets.token_hex(16)
        with closing(self.custody.connect()) as db, db:
            db.execute('INSERT INTO wallet_requests VALUES(?,?,?,?,?)', (ident, owner, 'ready', time.time(), self.custody.seal(owner, {**data, 'id': ident})))
        return ident

    def get(self, owner, ident):
        with closing(self.custody.connect()) as db:
            row = db.execute('SELECT * FROM wallet_requests WHERE id=? AND owner=?', (ident, owner)).fetchone()
        if not row:
            raise ValueError('Request not found')
        decoded = json.loads(self.custody.cipher.decrypt(row['encrypted']))
        if decoded['owner'] != owner or decoded['material']['id'] != ident:
            raise ValueError('Request identity mismatch')
        return {**decoded['material'], 'state': row['state'], 'created_at': row['created']}

    def detected(self, owner, ident):
        with closing(self.custody.connect()) as db, db:
            db.execute("UPDATE wallet_requests SET state='detected' WHERE id=? AND owner=? AND state='ready'", (ident, owner))

    def claim(self, owner, ident):
        with closing(self.custody.connect()) as db, db:
            return db.execute("UPDATE wallet_requests SET state='review' WHERE id=? AND owner=? AND state='ready'", (ident, owner)).rowcount == 1

    def complete(self, owner, ident):
        with closing(self.custody.connect()) as db, db:
            db.execute("UPDATE wallet_requests SET state='complete' WHERE id=? AND owner=?", (ident, owner))

    def recent(self, owner):
        with closing(self.custody.connect()) as db:
            ids = [r['id'] for r in db.execute('SELECT id FROM wallet_requests WHERE owner=? ORDER BY created DESC LIMIT 30', (owner,))]
        return [self.get(owner, ident) for ident in ids]
