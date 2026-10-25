"""SQLite default and explicitly configured PostgreSQL storage.

Only SQL parameter binding/result adaptation lives here; wallet operations stay in
Acorn. No transaction is automatically retried after a database error.
"""
from collections.abc import Mapping
from contextlib import closing
import os
from pathlib import Path
import re
import sqlite3

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError, IntegrityError

from app.migrations.baseline import OBJECTS
from app.db_diagnostics import diagnostic

# Serialize short write transactions across every process sharing this database.
# Preserve SQLite's conservative exclusion first; narrower locking is future work.
WRITE_LOCK = 0x4F414B47415445

class StorageError(Exception):
    pass

class StorageIntegrityError(StorageError):
    pass

DATABASE_ERRORS = (sqlite3.Error, StorageError)
INTEGRITY_ERRORS = (sqlite3.IntegrityError, StorageIntegrityError)


def cutover_marker(path):
    return Path(str(Path(path).resolve()) + '.postgres-cutover')


def refuse_sqlite_cutover(path):
    if cutover_marker(path).exists():
        raise StorageError('SQLite is fenced for PostgreSQL cutover. Keep workers stopped and follow the migration guide; do not remove the marker to bypass this check.')


def initialize_sqlite(path):
    # Legacy SQLite bootstrap only. PostgreSQL never performs runtime DDL.
    with closing(sqlite3.connect(path, timeout=5)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        for item in OBJECTS:
            if item['type'] == 'table':
                db.execute(item['sql'].replace('CREATE TABLE ', 'CREATE TABLE IF NOT EXISTS ', 1))
        historical = {
            'incoming_payments': [('history_written', 'INTEGER NOT NULL DEFAULT 0')],
            'outgoing_payments': [('request_key', 'TEXT'), ('started_at', 'REAL')],
            'ecash_inboxes': [('failures', 'INTEGER NOT NULL DEFAULT 0')],
        }
        for table, additions in historical.items():
            columns = {r[1] for r in db.execute(f'PRAGMA table_info({table})')}
            for name, declaration in additions:
                if name not in columns:
                    db.execute(f'ALTER TABLE {table} ADD COLUMN {name} {declaration}')
        for item in OBJECTS:
            if item['type'] == 'index':
                sql = item['sql'].replace('CREATE UNIQUE INDEX ', 'CREATE UNIQUE INDEX IF NOT EXISTS ', 1)
                sql = sql.replace('CREATE INDEX ', 'CREATE INDEX IF NOT EXISTS ', 1)
                db.execute(sql)


def postgres_engine(value):
    try:
        url = make_url(value)
        if url.drivername != 'postgresql+psycopg' or not url.database:
            raise ValueError()
    except Exception:
        raise ValueError('Use an explicit postgresql+psycopg database URL') from None
    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5,
                         pool_timeout=5, hide_parameters=True, isolation_level="READ COMMITTED",
                         connect_args={'connect_timeout': 5, 'options': '-c search_path=public -c lock_timeout=5000 -c statement_timeout=30000 -c idle_in_transaction_session_timeout=30000'})


class Database:
    def __init__(self, directory, url=None):
        self.engine = None
        self.path = None
        if url:
            from app.postgres_migrations import verify
            self.engine = postgres_engine(url)
            phase = 'connection'
            try:
                with self.engine.connect() as connection:
                    phase = 'schema_and_permissions'
                    verify(connection, runtime=True)
            except Exception as error:
                self.engine.dispose()
                raise StorageError('PostgreSQL schema or runtime role is not ready; ' + diagnostic(error, phase)) from None
        else:
            directory = Path(directory)
            refuse_sqlite_cutover(directory / 'custody.sqlite3')
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.path = directory / 'custody.sqlite3'
            fd = os.open(self.path, os.O_CREAT | os.O_WRONLY, 0o600)
            os.close(fd)
            initialize_sqlite(self.path)

    def connect(self):
        if self.engine is not None:
            try:
                return PostgresConnection(self.engine.connect())
            except SQLAlchemyError:
                raise StorageError('Database connection unavailable') from None
        refuse_sqlite_cutover(self.path)
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        return db

    def close(self):
        if self.engine is not None:
            self.engine.dispose()


def statement(sql, parameters):
    # Preserve quoted text and identifiers. Never interpolate values into SQL.
    parts = re.split(r"('(?:''|[^'])*'|\"(?:\"\"|[^\"])*\")", sql)
    index = 0
    for offset in range(0, len(parts), 2):
        def bind(match):
            nonlocal index
            result = f':p{index}'
            index += 1
            return result
        parts[offset] = re.sub(r'\?', bind, parts[offset])
    if index != len(parameters):
        raise ValueError('Incorrect SQL parameter count')
    return text(''.join(parts)), {f'p{i}': value for i, value in enumerate(parameters)}


class Row(Mapping):
    def __init__(self, row):
        self.row = row
    def __getitem__(self, key):
        return self.row[key] if isinstance(key, (int, slice)) else self.row._mapping[key]
    def __iter__(self):
        return iter(self.row._mapping)
    def __len__(self):
        return len(self.row)


class Result:
    def __init__(self, result):
        self.result = result
        self.rowcount = result.rowcount
    def fetchone(self):
        row = self.result.fetchone()
        return Row(row) if row is not None else None
    def fetchall(self):
        return [Row(row) for row in self.result.fetchall()]
    def __iter__(self):
        return (Row(row) for row in self.result)


class PostgresConnection:
    def __init__(self, connection):
        self.connection = connection
        self.writing = False
    def __enter__(self):
        try:
            # READ COMMITTED takes a new snapshot after acquiring the lock, so a
            # waiter sees the prior holder's committed state before making decisions.
            self.connection.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': WRITE_LOCK})
            self.writing = True
            return self
        except SQLAlchemyError:
            self.connection.rollback()
            raise StorageError('Database write lock unavailable') from None
    def __exit__(self, kind, value, traceback):
        try:
            if kind is None:
                self.connection.commit()
            else:
                self.connection.rollback()
        except SQLAlchemyError:
            raise StorageError('Database transaction outcome could not be confirmed') from None
        finally:
            self.writing = False
    def execute(self, sql, parameters=()):
        if sql.strip().upper() == 'BEGIN IMMEDIATE':
            if not self.writing:
                raise StorageError('Write transaction context required')
            return None
        operation = sql.lstrip().split(None, 1)[0].upper()
        if operation not in {'SELECT', 'INSERT', 'UPDATE', 'DELETE'}:
            raise StorageError('Runtime schema/administration SQL is forbidden')
        if operation != 'SELECT' and not self.writing:
            raise StorageError('Write transaction context required')
        query, values = statement(sql, parameters)
        try:
            return Result(self.connection.execute(query, values))
        except IntegrityError:
            raise StorageIntegrityError('Database uniqueness or integrity constraint rejected the operation') from None
        except SQLAlchemyError:
            raise StorageError('Database operation failed') from None
    def close(self):
        # Closing a read transaction rolls it back, and returns the pooled connection.
        self.connection.close()
