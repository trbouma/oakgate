"""Encrypted bearer descriptors in the existing backed-up custody database."""
import json
import secrets
from contextlib import closing

class RecordCapabilities:
    def __init__(self, store):
        self.store = store

    def save(self, owner, data):
        ident = secrets.token_hex(16)
        with closing(self.store.connect()) as db, db:
            db.execute('INSERT INTO record_capabilities VALUES(?,?,?)',
                       (ident, owner, self.store.seal(owner, {**data, 'id': ident})))
        return ident

    def list(self, owner):
        with closing(self.store.connect()) as db:
            rows = db.execute('SELECT * FROM record_capabilities WHERE owner=?', (owner,)).fetchall()
        result = []
        for row in rows:
            payload = json.loads(self.store.cipher.decrypt(row['encrypted']))
            if payload['owner'] != owner or payload['material']['id'] != row['id']:
                raise ValueError('Capability identity mismatch')
            result.append(payload['material'])
        return result

    def get(self, owner, ident):
        return next((item for item in self.list(owner) if item['id'] == ident), None)

    def remove(self, owner, ident):
        with closing(self.store.connect()) as db, db:
            db.execute('DELETE FROM record_capabilities WHERE owner=? AND id=?', (owner, ident))
