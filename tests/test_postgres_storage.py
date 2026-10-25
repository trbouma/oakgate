"""Opt-in real PostgreSQL tests. Requires a disposable *_test database, pre-migrated.

OAKGATE_TEST_POSTGRES_URL is a restricted runtime role, never a production URL.
No test talks to a live wallet, relay or mint.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import os
from pathlib import Path
import secrets
import time
from urllib.parse import urlsplit

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.engine import make_url

from app.custody import CustodyStore, AlreadyConnected, Busy, HandleTaken, identity_key
from app.database import StorageError, StorageIntegrityError, statement
from app.postgres_schema import metadata


@pytest.fixture
def pg(monkeypatch, tmp_path):
    url = os.getenv('OAKGATE_TEST_POSTGRES_URL')
    if not url:
        pytest.skip('Set OAKGATE_TEST_POSTGRES_URL to a migrated disposable PostgreSQL database')
    if not make_url(url).database.endswith('_test'):
        pytest.fail('Refusing to clear a database whose name does not end in _test')
    original = CustodyStore.__init__
    created = []
    def construct(self, directory, encryption_key, *, database_url=None):
        original(self, directory, encryption_key, database_url=database_url or url)
        created.append(self)
    monkeypatch.setattr(CustodyStore, '__init__', construct)
    monkeypatch.setenv('OAKGATE_SERVICE_NSEC', '31'*32)
    store = CustodyStore(tmp_path, Fernet.generate_key())
    with closing(store.connect()) as db, db:
        for name in metadata.tables:
            db.execute('DELETE FROM ' + name)
    yield store
    for store in created:
        store.database.close()


def test_postgres_bytes_precision_rows_and_rollback(pg):
    stamp = 1792961661.123456
    with closing(pg.connect()) as db, db:
        db.execute('INSERT INTO wallet_requests VALUES(?,?,?,?,?)', ('r','owner','ready',stamp,b'\x00secret\xff'))
    with closing(pg.connect()) as db:
        row = db.execute('SELECT * FROM wallet_requests').fetchone()
        assert row['encrypted'] == b'\x00secret\xff'
        assert row['created'] == stamp  # SQLite REAL must become double, not PG float4.
        assert row[0] == dict(row)['id'] == 'r'
    with pytest.raises(RuntimeError):
        with closing(pg.connect()) as db, db:
            db.execute("UPDATE wallet_requests SET state='sent'")
            raise RuntimeError('crash')
    with closing(pg.connect()) as db:
        assert db.execute('SELECT state FROM wallet_requests').fetchone()[0] == 'ready'
    with closing(pg.connect()) as db, db:
        with pytest.raises(StorageError, match='forbidden'):
            db.execute('CREATE TABLE forbidden(id INTEGER)')


def test_postgres_lease_and_handle_competition(pg):
    pg.insert('alice', {'npub':'wallet-a'}, 'active')
    pg.insert('bob', {'npub':'wallet-b'}, 'active')
    def acquire(_):
        try: return pg.acquire('alice')
        except Busy: return None
    with ThreadPoolExecutor(max_workers=8) as pool:
        tokens = list(pool.map(acquire, range(16)))
    winners = [t for t in tokens if t]
    assert len(winners) == 1
    pg.release('alice', 'wrong-token')
    with pytest.raises(Busy): pg.acquire('alice')
    pg.release('alice', winners[0])
    assert pg.acquire('alice')
    def handle(owner):
        try: pg.save_handle(owner, 'Shared'); return owner
        except HandleTaken: return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert len([x for x in pool.map(handle, ['alice','bob']) if x]) == 1
    with pytest.raises(AlreadyConnected): pg.insert('other', {'npub':'wallet-a'}, 'active')


def test_postgres_incoming_claim_and_pos_receipt_idempotency(pg):
    from app.payment_store import PaymentStore, PaymentBusy
    from app.pos_store import POSStore
    from app.pos_receiving import TerminalRequests
    pg.insert('owner', {'npub':'wallet'}, 'active')
    payments = PaymentStore(pg)
    item, _ = payments.reserve('owner', {'amount':10})
    def claim(_):
        try: return payments.claim(item['id'])
        except PaymentBusy: return None
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert len([x for x in pool.map(claim,range(16)) if x]) == 1
    terminals = POSStore(pg,'https://pos.example')
    ident = terminals.provision('owner','Counter').split('.')[1]
    with closing(pg.connect()) as db:
        actor = dict(db.execute('SELECT * FROM pos_terminals WHERE id=?',(ident,)).fetchone())
    requests = TerminalRequests(pg)
    def reserve(_): return requests.reserve(actor,'unique-request','same-payload')
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(reserve,range(16)))
    assert len({r[0]['id'] for r in results}) == 1
    assert sum(r[1] for r in results) == 1


def test_postgres_nfc_pin_replay_revocation_and_restart(pg):
    from app.identity import ServiceIdentity
    from app.nfc_cards import CardStore
    from app.nfc_login import activate, verify_card
    from app.pos_store import POSStore, POSDenied
    ServiceIdentity(pg,'31'*32)
    user={'iss':'https://keycloak.example/realms/oakgate','sub':'holder'}
    owner=identity_key(user)
    pg.insert(owner, {'npub':'holder-wallet'}, 'active')
    pg.insert('merchant', {'npub':'merchant-wallet'}, 'active')
    terminal=POSStore(pg,'https://pos.example').provision('merchant','Counter').split('.')[1]
    cards=CardStore(pg,'https://oakgate.example')
    code=urlsplit(cards.start(terminal,'pair-request-0001')['pair_url']).fragment
    pin=cards.approve(code,owner,enroll=True,login_identity=user)['pin']
    cards.acknowledge_pin(code,owner)
    card=cards.prepare(terminal,'pair-request-0001')
    cards.verify(terminal,'pair-request-0001',card['payload'])
    activate(cards,card['card_id'],owner,user['iss'])
    nonce=secrets.token_hex(32)
    assert verify_card(cards,card['payload'],pin,nonce,user['iss'])=='holder'
    with pytest.raises(POSDenied): verify_card(cards,card['payload'],pin,nonce,user['iss'])
    wrong='0000' if pin!='0000' else '0001'
    def guess(_):
        with pytest.raises(POSDenied): verify_card(cards,card['payload'],wrong,secrets.token_hex(32),user['iss'])
    with ThreadPoolExecutor(max_workers=8) as pool: list(pool.map(guess,range(12)))
    with closing(pg.connect()) as db:
        assert db.execute('SELECT failures FROM nfc_login_attempts').fetchone()[0]==5
    restarted=CardStore(pg,cards.origin)
    with pytest.raises(POSDenied): verify_card(restarted,card['payload'],pin,secrets.token_hex(32),user['iss'])
    activate(restarted,card['card_id'],owner,user['iss'])
    assert verify_card(restarted,card['payload'],pin,secrets.token_hex(32),user['iss'])=='holder'
    restarted.revoke(owner,card['card_id'])
    with pytest.raises(POSDenied): verify_card(restarted,card['payload'],pin,secrets.token_hex(32),user['iss'])


# Run the same end-to-end business regressions against the real PG runtime role.
@pytest.mark.parametrize('module,name', [
    ('test_send','test_direct_send_is_reviewed_and_one_shot'),
    ('test_send','test_uncertain_send_never_retries_or_falls_back'),
    ('test_send','test_changed_direct_fee_quote_cannot_send_or_hold_wallet'),
    ('test_payment_review','test_review_releases_global_hold_but_never_retries_original_or_matching_intent'),
    ('test_payment_review','test_prepared_duplicate_cannot_escape_recovery_quarantine'),
    ('test_payment_review','test_late_sender_cannot_overwrite_reviewed_record'),
    ('test_payments','test_payment_lease_and_expired_paid_recovery'),
    ('test_payments','test_completed_payment_backfills_history_without_minting'),
    ('test_payments','test_zap_only_after_credit_same_event_on_retries'),
])
def test_postgres_business_regressions(pg,tmp_path,module,name):
    import importlib
    getattr(importlib.import_module(module),name)(tmp_path)


def test_postgres_mint_response_loss_restores_without_second_issue(pg,tmp_path):
    from test_payments import setup
    from app.payments import PaymentService
    async def run():
        f=setup(tmp_path)
        await f.service.invoice(f.token,'13000')
        pid=f.service.store.due()[0]
        item=f.service.store.get(pid)
        f.mint.rows[item['quote']]['state']='PAID'
        f.mint.fail_after_issue=True
        await f.service.process(pid)
        assert f.mint.issued==1
        restarted=PaymentService(f.wallets,'https://oakgate.example',mint=f.mint)
        await restarted.process(pid)
        assert f.mint.issued==1
        assert restarted.store.get(pid)['state']=='complete'
        await restarted.process(pid)
        assert f.mint.issued==1
    asyncio.run(run())


def test_bound_parameters_do_not_rewrite_literals():
    query, values=statement("SELECT '?' AS literal, ? AS value", ('secret?value',))
    assert str(query)=="SELECT '?' AS literal, :p0 AS value"
    assert values=={'p0':'secret?value'}


def test_postgres_commit_response_loss_is_not_retried(pg,monkeypatch):
    from sqlalchemy.exc import SQLAlchemyError
    with closing(pg.connect()) as db:
        commit=db.connection.commit
        calls=[]
        def lose_response():
            calls.append(1)
            commit()
            raise SQLAlchemyError('simulated connection loss after commit')
        monkeypatch.setattr(db.connection,'commit',lose_response)
        with pytest.raises(StorageError,match='outcome'):
            with db:
                db.execute('INSERT INTO wallet_requests VALUES(?,?,?,?,?)',('once','owner','ready',1,b'opaque'))
        assert calls==[1]
    with closing(pg.connect()) as db:
        assert db.execute("SELECT count(*) FROM wallet_requests WHERE id='once'").fetchone()[0]==1


def test_postgres_schema_and_privileged_role_fail_closed(pg,tmp_path):
    from app.database import postgres_engine
    from app.postgres_migrations import initialize,verify
    from sqlalchemy import text
    url=os.getenv('OAKGATE_TEST_POSTGRES_ADMIN_URL')
    if not url: pytest.skip('Set the administrator URL for the disposable test database')
    assert make_url(url).database==make_url(os.environ['OAKGATE_TEST_POSTGRES_URL']).database
    with pytest.raises(StorageError,match='not ready'):
        CustodyStore(tmp_path/'no-fallback',Fernet.generate_key(),database_url=url)
    assert not (tmp_path/'no-fallback').exists()
    with pytest.raises(ValueError,match='empty'): initialize(url)
    engine=postgres_engine(url)
    try:
        with engine.connect() as connection:
            transaction=connection.begin()
            connection.execute(text('DROP INDEX outgoing_request'))
            with pytest.raises(ValueError,match='index mismatch'): verify(connection)
            transaction.rollback()
    finally: engine.dispose()


def test_invalid_postgres_configuration_never_creates_sqlite(tmp_path):
    with pytest.raises(ValueError,match='explicit'):
        CustodyStore(tmp_path/'no-fallback',Fernet.generate_key(),database_url='sqlite:///other.sqlite3')
    assert not (tmp_path/'no-fallback').exists()
