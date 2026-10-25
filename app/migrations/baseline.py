"""Frozen 0001 schema validation. Keep this contract immutable for this revision."""
import json
from pathlib import Path
import re
import sqlite3

REVISION = '0001_sqlite_baseline'
OBJECTS = json.loads(Path(__file__).with_name('baseline_0001.json').read_text())

class SchemaMismatch(ValueError):
    pass


def tokens(sql):
    # Ignore formatting/case outside SQL strings, not constraints or predicates.
    return tuple(t if t.startswith("'") else t.upper() for t in
                 re.findall(r"'(?:''|[^'])*'|[A-Za-z_][A-Za-z_0-9]*|[0-9]+|[^\s]", sql.rstrip(';')))


def objects(db):
    return {row[1]: dict(zip(('type', 'name', 'table', 'sql'), row)) for row in db.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_master WHERE sql IS NOT NULL AND substr(name,1,7) != 'sqlite_'")}


def validate(db, *, require_wallets=True):
    actual = objects(db)
    expected = {item['name']: item for item in OBJECTS}
    if require_wallets and 'wallets' not in actual:
        raise SchemaMismatch('Not an initialized OakGate database: wallets table missing')
    if list(db.execute('PRAGMA integrity_check')) != [('ok',)]:
        raise SchemaMismatch('SQLite integrity check failed; stop and investigate')
    if list(db.execute('PRAGMA foreign_key_check')):
        raise SchemaMismatch('Foreign-key check failed; stop and investigate')
    version = actual.pop('alembic_version', None)
    if version:
        columns = list(db.execute('PRAGMA table_info(alembic_version)'))
        if columns != [(0, 'version_num', 'VARCHAR(32)', 1, None, 1)]:
            raise SchemaMismatch('Unexpected Alembic version table')
        revisions = list(db.execute('SELECT version_num FROM alembic_version'))
        if revisions not in ([], [(REVISION,)]):
            raise SchemaMismatch('Unknown or multiple Alembic revisions; use matching migration code')
    unknown = sorted(set(actual) - set(expected))
    if unknown:
        raise SchemaMismatch('Unexpected schema objects: ' + ', '.join(unknown))
    for name, item in actual.items():
        ref = expected[name]
        if item['type'] != ref['type'] or item['table'] != ref['table'] or tokens(item['sql']) != tokens(ref['sql']):
            raise SchemaMismatch('Schema differs from baseline: ' + name)
    missing = [item for item in OBJECTS if item['name'] not in actual]
    if version and list(db.execute('SELECT version_num FROM alembic_version')) and missing:
        raise SchemaMismatch('Versioned database has missing schema objects')
    return missing
