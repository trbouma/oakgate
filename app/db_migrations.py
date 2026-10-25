"""Explicit, offline maintenance adoption of OakGate's SQLite schema."""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.exc import SQLAlchemyError

from app.migrations.baseline import REVISION, SchemaMismatch, validate


def open_existing(path, mode='ro'):
    path = Path(path).resolve(strict=True)
    if not path.is_file():
        raise ValueError('Database must be an existing file')
    return sqlite3.connect(path.as_uri() + '?mode=' + mode, uri=True,
                           timeout=5, isolation_level=None)


def check(path):
    with closing(open_existing(path)) as db:
        db.execute('BEGIN')
        missing = validate(db)
        versioned = db.execute("SELECT 1 FROM sqlite_master WHERE name='alembic_version'").fetchone()
        revision = db.execute('SELECT version_num FROM alembic_version').fetchone() if versioned else None
        return {'revision': revision[0] if revision else None,
                'baseline': REVISION, 'missing_objects': [x['name'] for x in missing]}


def backup_database(path, backup):
    backup = Path(backup).absolute()
    # Exclusive creation prevents overwriting either the source or an old backup.
    fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)
    with closing(open_existing(path)) as source, closing(sqlite3.connect(backup)) as target:
        source.backup(target)
        if list(target.execute('PRAGMA integrity_check')) != [('ok',)]:
            raise SchemaMismatch('Backup integrity check failed; no migration performed')
    return str(backup)


def upgrade(path, backup):
    # BEGIN IMMEDIATE serializes the whole validation/backup/DDL/version operation.
    # All app/worker writers must also be stopped before maintenance.
    engine = create_engine('sqlite://', creator=lambda: open_existing(path, 'rw'), poolclass=NullPool)
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql('BEGIN IMMEDIATE')
            try:
                validate(connection.connection.driver_connection)
                saved = backup_database(path, backup)
                config = Config()
                config.set_main_option('script_location', str(Path(__file__).parent / 'migrations'))
                config.attributes.update(connection=connection, oakgate_verified=True)
                command.upgrade(config, REVISION)
                if validate(connection.connection.driver_connection):
                    raise SchemaMismatch('Incomplete baseline after upgrade')
                connection.commit()
                return {'revision': REVISION, 'backup': saved}
            except BaseException:
                connection.rollback()
                raise
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    for name in ('check', 'upgrade'):
        cmd = sub.add_parser(name)
        cmd.add_argument('--database', required=True, type=Path)
        if name == 'upgrade':
            cmd.add_argument('--backup', required=True, type=Path)
            cmd.add_argument('--writers-stopped', required=True, action='store_true',
                             help='Confirm app and every other writer are stopped')
    args = parser.parse_args()
    try:
        result = check(args.database) if args.action == 'check' else upgrade(args.database, args.backup)
    except SQLAlchemyError:
        parser.exit(1, 'Migration failed; transaction rolled back. Keep the backup and investigate before retrying.\n')
    except (ValueError, OSError, sqlite3.Error) as error:
        parser.exit(1, f'Migration refused: {error}\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
