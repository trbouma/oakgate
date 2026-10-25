"""Real PostgreSQL import tests; only a disposable *_test database is accepted."""
from contextlib import closing
import os
import sqlite3

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import BigInteger, Double, LargeBinary, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from app.custody import CustodyStore
from app.database import StorageError, cutover_marker, initialize_sqlite, postgres_engine
from app.db_migrations import upgrade, open_existing
from app.postgres_import import ImportRefused, import_database, verify_database
from app.postgres_schema import metadata


@pytest.fixture
def target():
    url = os.getenv('OAKGATE_TEST_POSTGRES_ADMIN_URL')
    if not url:
        pytest.skip('Set a disposable PostgreSQL administrator test URL')
    assert make_url(url).database.endswith('_test'), 'Refusing non-test database'
    engine = postgres_engine(url)
    with engine.begin() as db:
        for table in metadata.tables.values():
            db.execute(table.delete())
    yield url
    engine.dispose()


@pytest.fixture
def source(tmp_path):
    path = tmp_path/'custody.sqlite3'
    initialize_sqlite(path)
    upgrade(path, tmp_path/'before-baseline.sqlite3')
    # Cover every table/column, including bytes, nulls and non-integral timestamps.
    with closing(sqlite3.connect(path)) as db, db:
        for table in metadata.tables.values():
            values = []
            for column in table.columns:
                if column.nullable:
                    value = None
                elif isinstance(column.type, BigInteger):
                    value = 1
                elif isinstance(column.type, Double):
                    value = 1792961661.123456
                elif isinstance(column.type, LargeBinary):
                    value = b'\x00opaque\xff'
                else:
                    value = 'sample-' + column.name
                values.append(value)
            db.execute('INSERT INTO "'+table.name+'" VALUES ('+','.join('?' for _ in values)+')',values)
        db.execute("UPDATE outgoing_payments SET state='sending',started_at=1792961661.123456,request_key='dedupe'")
        db.execute("UPDATE incoming_payments SET state='paid',lease='inflight',lease_until=1992961661.5,history_written=0")
        db.execute("UPDATE wallets SET lease='wallet-lease',lease_until=1992961661.25")
        db.execute('UPDATE nfc_login_attempts SET failures=5')
        db.execute('UPDATE pos_audit SET id=45')
    return path


def run_import(source, target):
    return import_database(source, source.with_name('before-postgres.sqlite3'),target,writers_stopped=True)


def test_exact_import_wal_backup_fence_and_audit_sequence(source,target):
    with closing(sqlite3.connect(source)) as wal:
        wal.execute('PRAGMA journal_mode=WAL')
        wal.execute('PRAGMA wal_autocheckpoint=0')
        wal.execute("UPDATE outgoing_payments SET state='reviewed'")
        wal.commit()
        result=run_import(source,target)
    assert result['status']=='imported'
    assert len(result['tables'])==28
    assert all(t['rows']==1 for t in result['tables'].values())
    verified=verify_database(source,target,writers_stopped=True)
    assert result['tables']==verified['tables']
    assert cutover_marker(source).stat().st_mode & 0o777 == 0o600
    assert source.with_name('before-postgres.sqlite3').stat().st_mode & 0o777 == 0o600
    with closing(open_existing(source.with_name('before-postgres.sqlite3'))) as db:
        assert db.execute('SELECT state FROM outgoing_payments').fetchone()[0]=='reviewed'
    engine=postgres_engine(target)
    try:
        with engine.begin() as db:
            assert db.execute(text('SELECT failures FROM nfc_login_attempts')).scalar_one()==5
            assert db.execute(text('SELECT lease FROM wallets')).scalar_one()=='wallet-lease'
            assert db.execute(text('SELECT lease FROM incoming_payments')).scalar_one()=='inflight'
            assert db.execute(text("INSERT INTO pos_audit(terminal,action,at) VALUES('t','test',1) RETURNING id")).scalar_one()==46
        with pytest.raises(ImportRefused,match='differs'):
            verify_database(source,target,writers_stopped=True)
    finally: engine.dispose()
    with pytest.raises(StorageError,match='fenced'):
        CustodyStore(source.parent,Fernet.generate_key())
    with pytest.raises(ImportRefused,match='already fenced'):
        run_import(source,target)


def test_copy_failure_rolls_back_but_retains_backup_and_fence(source,target,monkeypatch):
    import app.postgres_import as importer
    def fail(*args): raise RuntimeError('injected before commit')
    monkeypatch.setattr(importer,'compare',fail)
    with pytest.raises(RuntimeError): run_import(source,target)
    assert cutover_marker(source).exists()
    assert source.with_name('before-postgres.sqlite3').exists()
    engine=postgres_engine(target)
    try:
        with engine.connect() as db:
            assert db.execute(text('SELECT count(*) FROM wallets')).scalar_one()==0
    finally: engine.dispose()
    with closing(open_existing(source)) as db:
        assert db.execute('SELECT count(*) FROM wallets').fetchone()[0]==1


def test_lost_commit_response_can_be_verified_without_reimport(source,target,monkeypatch):
    from sqlalchemy.engine import Connection
    original=Connection._commit_impl
    with monkeypatch.context() as patch:
        def lost(connection):
            original(connection)
            raise SQLAlchemyError('lost commit acknowledgement')
        patch.setattr(Connection,'_commit_impl',lost)
        with pytest.raises(SQLAlchemyError): run_import(source,target)
    assert verify_database(source,target,writers_stopped=True)['status']=='verified'
    with pytest.raises(ImportRefused,match='already fenced'): run_import(source,target)


def test_nonempty_target_is_never_replaced(source,target):
    engine=postgres_engine(target)
    try:
        with engine.begin() as db:
            db.execute(text("INSERT INTO user_display_preferences VALUES('existing','fr')"))
        with pytest.raises(ImportRefused,match='contains application rows'): run_import(source,target)
        assert not cutover_marker(source).exists()
        assert not source.with_name('before-postgres.sqlite3').exists()
        with engine.connect() as db:
            assert db.execute(text('SELECT language FROM user_display_preferences')).scalar_one()=='fr'
    finally: engine.dispose()


@pytest.mark.parametrize('sql',[
    'UPDATE wallets SET owner=NULL',
    "UPDATE nfc_login_attempts SET failures='not-an-integer'",
    "UPDATE wallet_requests SET encrypted='not-bytes'",
])
def test_invalid_sqlite_values_rejected_before_fence(source,target,sql):
    with closing(sqlite3.connect(source)) as db, db: db.execute(sql)
    with pytest.raises(ImportRefused): run_import(source,target)
    assert not cutover_marker(source).exists()


def test_unadopted_source_rejected(source,target):
    with closing(sqlite3.connect(source)) as db, db: db.execute('DELETE FROM alembic_version')
    with pytest.raises(ImportRefused,match='adopted'): run_import(source,target)
    assert not cutover_marker(source).exists()


def test_existing_backup_never_overwritten(source,target):
    backup=source.with_name('before-postgres.sqlite3')
    backup.write_bytes(b'keep')
    with pytest.raises(FileExistsError): run_import(source,target)
    assert backup.read_bytes()==b'keep'
    assert not cutover_marker(source).exists()


def test_writers_acknowledgement_required(tmp_path):
    with pytest.raises(ImportRefused,match='Stop every'):
        import_database(tmp_path/'missing',tmp_path/'backup','not-a-url')


def test_existing_sqlite_store_checks_cutover_fence_on_next_connection(tmp_path):
    store=CustodyStore(tmp_path,Fernet.generate_key())
    cutover_marker(store.path).write_text('in progress')
    with pytest.raises(StorageError,match='fenced'): store.connect()


def test_verification_detects_changed_ciphertext_without_count_change(source,target):
    run_import(source,target)
    engine=postgres_engine(target)
    try:
        with engine.begin() as db:
            db.execute(text('UPDATE wallets SET encrypted=:value'),{'value':b'changed'})
        with pytest.raises(ImportRefused,match='Data differs in table: wallets'):
            verify_database(source,target,writers_stopped=True)
    finally: engine.dispose()


def test_sequence_restart_rolls_back_with_failed_import(source,target,monkeypatch):
    import app.postgres_import as importer
    engine=postgres_engine(target)
    try:
        with engine.begin() as db:
            db.execute(text('ALTER SEQUENCE pos_audit_id_seq RESTART WITH 123'))
        def fail(*args): raise RuntimeError('injected after sequence restart')
        monkeypatch.setattr(importer,'sequence_next',fail)
        with pytest.raises(RuntimeError): run_import(source,target)
        with engine.connect() as db:
            assert db.execute(text('SELECT last_value FROM pos_audit_id_seq')).scalar_one()==123
            assert db.execute(text('SELECT count(*) FROM pos_audit')).scalar_one()==0
        assert cutover_marker(source).exists()
    finally: engine.dispose()
