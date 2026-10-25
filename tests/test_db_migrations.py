"""Exercise real SQLite + Alembic, including crash rollback and opaque custody preservation."""
import ast
from contextlib import closing
import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from app import db_migrations as runner
from app.migrations.baseline import OBJECTS, REVISION, SchemaMismatch, validate, tokens


def database(tmp_path, full=True):
    path = tmp_path / 'custody.sqlite3'
    with sqlite3.connect(path) as db:
        for item in OBJECTS:
            if full or item['name'] == 'wallets':
                db.execute(item['sql'])
        db.execute("INSERT INTO wallets VALUES('owner','wallet',?,'active','lease',123)", (b'opaque-custody',))
    return path


def contents(path):
    with sqlite3.connect(path) as db:
        return {item['name']: list(db.execute('SELECT * FROM "' + item['name'] + '"'))
                for item in OBJECTS if item['type'] == 'table'}


def test_central_sqlite_bootstrap_matches_frozen_inventory(tmp_path):
    from app.database import initialize_sqlite
    path = tmp_path / 'schema.sqlite3'
    initialize_sqlite(path)
    with closing(sqlite3.connect(path)) as db:
        assert validate(db) == []


def test_adopt_preserves_custody_payment_recovery_and_card_state(tmp_path):
    path = database(tmp_path)
    with sqlite3.connect(path) as db:
        for state in ('sending', 'unknown', 'sent'):
            db.execute('INSERT INTO outgoing_payments VALUES(?,?,?,?,?,?,?)',
                       (state, 'owner', state, b'opaque-payment', 12, state, None))
        db.execute("INSERT INTO incoming_payments(id,owner,created,state,encrypted,history_written) VALUES('p','owner',12,'paid',?,1)", (b'opaque-incoming',))
        db.execute("INSERT INTO nfc_login_policy VALUES('card',0)")
        db.execute("INSERT INTO nfc_login_attempts VALUES('card',5)")
        db.execute("INSERT INTO nfc_issuer VALUES(1,?)", (b'issuer-secret',))
        db.execute("INSERT INTO nfc_card_pins VALUES('pair','card',?,NULL,1)", (b'pin-verifier',))
        db.execute("INSERT INTO user_preferences VALUES('owner','Handle','handle')")
    before = contents(path)
    backup = tmp_path / 'backup.sqlite3'
    result = runner.upgrade(path, backup)
    assert result['revision'] == REVISION
    assert contents(path) == before == contents(backup)
    assert backup.stat().st_mode & 0o777 == 0o600
    assert runner.check(path)['revision'] == REVISION
    assert runner.check(backup)['revision'] is None
    runner.upgrade(path, tmp_path / 'second-backup')
    assert contents(path) == before


def test_lazy_feature_tables_created_without_identity_generation(tmp_path):
    path = database(tmp_path, full=False)
    assert runner.check(path)['missing_objects']
    runner.upgrade(path, tmp_path / 'backup')
    assert runner.check(path)['missing_objects'] == []
    assert contents(path)['nfc_issuer'] == []
    assert contents(path)['service_identity'] == []
    assert contents(path)['wallets'][0][2] == b'opaque-custody'


@pytest.mark.parametrize('mutation', [
    'ALTER TABLE wallets ADD COLUMN unexpected TEXT',
    "CREATE TABLE unrelated(id TEXT)",
    "CREATE TRIGGER unexpected AFTER INSERT ON wallets BEGIN SELECT 1; END",
    'DROP INDEX outgoing_request; CREATE INDEX outgoing_request ON outgoing_payments(owner,request_key)',
    'DROP TABLE nfc_login_policy; CREATE TABLE nfc_login_policy(card_id TEXT PRIMARY KEY, require_pin INTEGER NOT NULL)',
    "CREATE TABLE alembic_version(version_num VARCHAR(32) NOT NULL PRIMARY KEY); INSERT INTO alembic_version VALUES('future')",
])
def test_drift_refused_before_backup_or_version_stamp(tmp_path, mutation):
    path = database(tmp_path)
    with sqlite3.connect(path) as db:
        db.executescript(mutation)
    backup = tmp_path / 'backup'
    before = path.read_bytes()
    with pytest.raises(SchemaMismatch):
        runner.upgrade(path, backup)
    assert path.read_bytes() == before
    assert not backup.exists()


def test_injected_failure_rolls_back_ddl_and_version(tmp_path, monkeypatch):
    path = database(tmp_path, full=False)
    original = runner.check(path)
    real_upgrade = command.upgrade
    def interrupted(*args, **kwargs):
        real_upgrade(*args, **kwargs)
        raise RuntimeError('injected failure before commit')
    monkeypatch.setattr(command, 'upgrade', interrupted)
    with pytest.raises(RuntimeError, match='injected'):
        runner.upgrade(path, tmp_path / 'backup')
    assert runner.check(path) == original


def test_backup_includes_uncheckpointed_wal(tmp_path):
    path = database(tmp_path)
    with closing(sqlite3.connect(path)) as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute("INSERT INTO nfc_login_attempts VALUES('card',4)")
        db.commit()
        runner.upgrade(path, tmp_path / 'backup')
        assert contents(tmp_path / 'backup')['nfc_login_attempts'] == [('card', 4)]


def test_missing_path_wrong_database_and_existing_backup_refused(tmp_path):
    missing = tmp_path / 'missing'
    with pytest.raises(FileNotFoundError):
        runner.check(missing)
    assert not missing.exists()
    wrong = tmp_path / 'wrong'
    sqlite3.connect(wrong).close()
    with pytest.raises(SchemaMismatch):
        runner.upgrade(wrong, tmp_path / 'backup')
    path = database(tmp_path)
    backup = tmp_path / 'exists'
    backup.write_text('preserve')
    with pytest.raises(FileExistsError):
        runner.upgrade(path, backup)
    assert backup.read_text() == 'preserve'
    assert runner.check(path)['revision'] is None


def test_unique_index_failure_does_not_stamp(tmp_path):
    path = database(tmp_path)
    with sqlite3.connect(path) as db:
        db.execute('DROP INDEX outgoing_request')
        for ident in ('a', 'b'):
            db.execute("INSERT INTO outgoing_payments VALUES(?,'owner','unknown',?,1,'same',NULL)", (ident,b'opaque'))
    from sqlalchemy.exc import IntegrityError
    with pytest.raises(IntegrityError):
        runner.upgrade(path, tmp_path / 'backup')
    assert runner.check(path)['revision'] is None
    assert contents(path) == contents(tmp_path / 'backup')


def test_direct_stamp_without_verified_runner_rejected():
    cfg = Config()
    cfg.set_main_option('script_location', str(Path(__file__).parents[1] / 'app/migrations'))
    with pytest.raises(RuntimeError, match='Use python -m app.db_migrations'):
        command.stamp(cfg, REVISION)


def test_revision_creates_fresh_schema_transactionally(tmp_path):
    from sqlalchemy import create_engine
    engine = create_engine('sqlite:///' + str(tmp_path / 'fresh.sqlite3'))
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql('BEGIN IMMEDIATE')
            cfg = Config()
            cfg.set_main_option('script_location', str(Path(__file__).parents[1] / 'app/migrations'))
            cfg.attributes.update(connection=connection, oakgate_verified=True)
            command.upgrade(cfg, REVISION)
            assert validate(connection.connection.driver_connection) == []
            connection.commit()
    finally:
        engine.dispose()
    assert runner.check(tmp_path / 'fresh.sqlite3')['revision'] == REVISION


def test_active_writer_blocks_adoption_without_creating_backup(tmp_path, monkeypatch):
    from sqlalchemy.exc import OperationalError
    path = database(tmp_path)
    real_open = runner.open_existing
    def short_wait(*args, **kwargs):
        db = real_open(*args, **kwargs)
        db.execute('PRAGMA busy_timeout=1')
        return db
    monkeypatch.setattr(runner, 'open_existing', short_wait)
    with closing(sqlite3.connect(path)) as writer:
        writer.execute('BEGIN IMMEDIATE')
        with pytest.raises(OperationalError):
            runner.upgrade(path, tmp_path / 'backup')
        writer.rollback()
    assert not (tmp_path / 'backup').exists()
    assert runner.check(path)['revision'] is None
