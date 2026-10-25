"""Offline, exact-copy import into a migrated, empty PostgreSQL target.

No wallet service is constructed and no external payment is retried. A durable
SQLite fence is deliberately retained on every failure after it is created.
"""
import argparse
from contextlib import closing
import hashlib
import json
import math
import os
from pathlib import Path
import struct

from sqlalchemy import BigInteger, Double, LargeBinary, Text, select, text

from app.database import WRITE_LOCK, cutover_marker, postgres_engine
from app.db_migrations import backup_database, open_existing
from app.migrations.baseline import REVISION as SQLITE_REVISION, validate
from app.postgres_migrations import REVISION, verify as verify_schema
from app.postgres_schema import metadata


class ImportRefused(ValueError):
    """Only non-sensitive diagnostic messages belong in this exception."""


def validate_source(db):
    if validate(db):
        raise ImportRefused('Source schema is incomplete; adopt the SQLite baseline first.')
    versioned = db.execute("SELECT 1 FROM sqlite_master WHERE name='alembic_version'").fetchone()
    if not versioned or list(db.execute('SELECT version_num FROM alembic_version')) != [(SQLITE_REVISION,)]:
        raise ImportRefused('Source must have the adopted SQLite baseline.')


def checked_row(table, values):
    result = {}
    for column, value in zip(table.columns, values):
        if value is None:
            if not column.nullable:
                raise ImportRefused('Null in required column: ' + table.name + '.' + column.name)
        elif isinstance(column.type, BigInteger):
            if type(value) is not int or not -(2**63) <= value < 2**63:
                raise ImportRefused('Invalid integer in ' + table.name + '.' + column.name)
        elif isinstance(column.type, Double):
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ImportRefused('Invalid timestamp in ' + table.name + '.' + column.name)
            value = float(value)
        elif isinstance(column.type, Text):
            if not isinstance(value, str) or '\x00' in value:
                raise ImportRefused('Invalid text in ' + table.name + '.' + column.name)
            value.encode('utf-8', errors='strict')
        elif isinstance(column.type, LargeBinary):
            if not isinstance(value, bytes):
                raise ImportRefused('Invalid encrypted bytes in ' + table.name + '.' + column.name)
        else:
            raise ImportRefused('Unreviewed column type')
        result[column.name] = value
    return result


def rows(db, table):
    # Names come only from the frozen metadata, never from CLI input.
    columns = ','.join('"' + c.name + '"' for c in table.columns)
    cursor = db.execute('SELECT ' + columns + ' FROM "' + table.name + '"')
    while batch := cursor.fetchmany(500):
        yield [checked_row(table, row) for row in batch]


def row_hash(row):
    h = hashlib.sha256()
    for value in row.values():
        if value is None:
            tag, data = b'n', b''
        elif isinstance(value, bytes):
            tag, data = b'b', value
        elif isinstance(value, str):
            tag, data = b's', value.encode('utf-8')
        elif isinstance(value, int):
            tag, data = b'i', str(value).encode('ascii')
        else:
            tag, data = b'f', struct.pack('!d', value)
        h.update(tag + len(data).to_bytes(8, 'big') + data)
    return h.digest()


def fingerprint(records):
    # Sorting hashes makes comparison independent of database collation/order.
    # Only fixed-size hashes are retained, not decrypted data or record bodies.
    hashes = sorted(row_hash(row) for row in records)
    return len(hashes), hashlib.sha256(b''.join(hashes)).hexdigest()


def source_fingerprints(db):
    return {table.name: fingerprint(row for batch in rows(db, table) for row in batch)
            for table in metadata.tables.values()}


def compare(db, target):
    report = {}
    for table in metadata.tables.values():
        expected = fingerprint(row for batch in rows(db, table) for row in batch)
        with target.execute(select(table).execution_options(stream_results=True)) as cursor:
            actual = fingerprint(checked_row(table, tuple(row)) for row in cursor)
        if actual != expected:
            raise ImportRefused('Data differs in table: ' + table.name)
        report[table.name] = {'rows': expected[0], 'sha256': expected[1]}
    return report


def lock_target(target):
    target.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': WRITE_LOCK})
    verify_schema(target)
    # Also exclude direct SQL writers that do not use the application's lock.
    names = ','.join('public."' + name + '"' for name in sorted(metadata.tables))
    target.execute(text('LOCK TABLE ' + names + ' IN SHARE ROW EXCLUSIVE MODE'))


def fence(path, backup):
    marker = cutover_marker(path)
    fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as out:
        json.dump({'version': 1, 'source': str(Path(path).resolve()),
                   'backup': str(Path(backup).resolve()),
                   'instruction': 'Keep SQLite fenced. Verify PostgreSQL before startup; no automatic rollback.'}, out)
        out.flush()
        os.fsync(out.fileno())
    directory = os.open(marker.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return marker


def sequence_next(target):
    last, called = target.execute(text('SELECT last_value,is_called FROM public.pos_audit_id_seq')).one()
    return last + 1 if called else last


def import_database(path, backup, url, *, writers_stopped=False):
    if not writers_stopped:
        raise ImportRefused('Stop every SQLite and PostgreSQL writer before importing.')
    if cutover_marker(path).exists():
        raise ImportRefused('Source already fenced. Run verify; do not repeat the import.')
    engine = postgres_engine(url)
    try:
        with closing(open_existing(path, 'rw')) as source:
            source.execute('BEGIN IMMEDIATE')
            validate_source(source)
            expected = source_fingerprints(source)  # Validate types before making a fence.
            with engine.begin() as target:
                lock_target(target)
                if any(target.execute(select(table).limit(1)).first() is not None for table in metadata.tables.values()):
                    raise ImportRefused('PostgreSQL target contains application rows; refusing to overwrite.')
                saved = backup_database(path, backup)
                with closing(open_existing(saved)) as copy:
                    copy.execute('BEGIN')
                    validate_source(copy)
                    if source_fingerprints(copy) != expected:
                        raise ImportRefused('Backup does not exactly match the locked source.')
                marker = fence(path, saved)
                for table in metadata.tables.values():
                    for batch in rows(source, table):
                        target.execute(table.insert(), batch)
                report = compare(source, target)
                maximum = target.execute(text('SELECT max(id) FROM pos_audit')).scalar_one()
                next_id = max(1, (maximum or 0) + 1)
                if next_id >= 2**63:
                    raise ImportRefused('Audit sequence is exhausted.')
                # ALTER RESTART is transactional, unlike setval. Never reset other state.
                target.execute(text('ALTER SEQUENCE public.pos_audit_id_seq RESTART WITH ' + str(next_id)))
                if sequence_next(target) != next_id:
                    raise ImportRefused('Audit sequence verification failed.')
            # The enclosing transaction has committed before success is returned.
            return {'status': 'imported', 'revision': REVISION, 'backup': saved,
                    'sqlite_fence': str(marker), 'tables': report,
                    'next_step': 'Run verify while writers remain stopped; do not restart SQLite.'}
    finally:
        engine.dispose()


def verify_database(path, url, *, writers_stopped=False):
    if not writers_stopped or not cutover_marker(path).exists():
        raise ImportRefused('Verification requires stopped writers and the original fenced SQLite source.')
    engine = postgres_engine(url)
    try:
        with closing(open_existing(path, 'rw')) as source:
            source.execute('BEGIN IMMEDIATE')
            validate_source(source)
            with engine.begin() as target:
                lock_target(target)
                report = compare(source, target)
                maximum = target.execute(text('SELECT max(id) FROM pos_audit')).scalar_one()
                if sequence_next(target) <= (maximum or 0):
                    raise ImportRefused('Audit sequence is behind imported rows.')
            return {'status': 'verified', 'revision': REVISION, 'tables': report}
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    for action in ('import', 'verify'):
        cmd = sub.add_parser(action)
        cmd.add_argument('--database', required=True, type=Path)
        cmd.add_argument('--writers-stopped', required=True, action='store_true')
        if action == 'import':
            cmd.add_argument('--backup', required=True, type=Path)
    args = parser.parse_args()
    url = os.getenv('OAKGATE_MIGRATION_DATABASE_URL', '')
    try:
        if args.action == 'import':
            result = import_database(args.database, args.backup, url, writers_stopped=args.writers_stopped)
        else:
            result = verify_database(args.database, url, writers_stopped=args.writers_stopped)
    except ImportRefused as error:
        parser.exit(1, str(error) + '\nKeep writers stopped and preserve any backup/fence.\n')
    except Exception:
        # Driver exceptions may include credentials, values or encrypted blobs.
        parser.exit(1, 'Database operation could not be confirmed. Keep writers stopped and preserve backup/fence. Do not retry import or restore SQLite automatically; inspect the target and run verify.\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
