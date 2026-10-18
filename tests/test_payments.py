import asyncio
import hashlib
import json
import time
from types import SimpleNamespace

import bolt11
import httpx
import pytest
from cryptography.fernet import Fernet
from stroma import Event, Keys
from acorn.b_dhke import step2_bob, verify
from acorn.secp import PrivateKey, PublicKey
from acorn.stroma_compat import ExtendedNIP44Encrypt

from app.config import AuthSettings
from app.custody import CustodyStore, HandleTaken
from app.main import create_app
from app.payment_config import PaymentSettings, DEFAULT_MINT, DEFAULT_ZAP_RELAYS
from app.payment_mint import CashuMint, MintCompatibilityError
from app.payment_store import PaymentBusy
from app.payments import PaymentService
from app.identity import ServiceIdentity

@pytest.fixture(autouse=True)
def service_key(monkeypatch):
    monkeypatch.setenv("OAKGATE_SERVICE_NSEC", "31" * 32)

from app.wallets import WalletService, AcornBackend
from app.zaps import encode_lnurl, validate_zap, public_relay


def invoice(amount, description, hashed=True):
    tags = bolt11.Tags()
    tags.add(bolt11.TagChar.payment_hash, '11'*32)
    tags.add(bolt11.TagChar.payment_secret, '22'*32)
    tags.add(bolt11.TagChar.description_hash if hashed else bolt11.TagChar.description,
             hashlib.sha256(description.encode()).hexdigest() if hashed else description)
    return bolt11.encode(bolt11.Bolt11(currency='bc', date=int(time.time()), amount_msat=amount*1000, tags=tags), private_key='03'*32)


class Mint(CashuMint):
    def __init__(self):
        super().__init__(require_description_hash=True)
        self.rows = {}
        self.signatures = {}
        self.key = PrivateKey(bytes.fromhex('02'*32), raw=True)
        self.issued = 0
        self.fail_after_issue = False
        self.hashed = True
        self.restorable = True
        self.calls = []

    async def request(self, mint, method, path, payload=None):
        self.calls.append((mint, method, path, payload))
        if path == '/v1/info':
            return {'nuts': {'9': {'supported': self.restorable}}}
        if path == '/v1/mint/quote/bolt11':
            q = str(len(self.rows)+1)
            row = {'quote': q, 'state': 'UNPAID', 'request': invoice(payload['amount'], payload.get('description', 'Cashu deposit'), self.hashed)}
            self.rows[q] = row
            return row.copy()
        if path.startswith('/v1/mint/quote/bolt11/'):
            return self.rows[path.rsplit('/',1)[1]].copy()
        if path == '/v1/keysets':
            return {'keysets': [{'id': '0011223344556677', 'unit': 'sat', 'active': True}]}
        if path.startswith('/v1/keys/'):
            return {'keysets': [{'id': '0011223344556677', 'keys': {str(2**i): self.key.pubkey.serialize().hex() for i in range(27)}}]}
        if path == '/v1/restore':
            outputs = [o for o in payload['outputs'] if o['B_'] in self.signatures]
            return {'outputs': list(reversed(outputs)), 'signatures': [self.signatures[o['B_']] for o in reversed(outputs)]}
        if path == '/v1/mint/bolt11':
            assert self.rows[payload['quote']]['state'] == 'PAID'
            signatures = []
            for output in payload['outputs']:
                c, e, s = step2_bob(PublicKey(bytes.fromhex(output['B_']), raw=True), self.key)
                sig = {'id': output['id'], 'amount': output['amount'], 'C_': c.serialize().hex(),
                       'dleq': {'e': e.private_key.hex(), 's': s.private_key.hex()}}
                self.signatures[output['B_']] = sig
                signatures.append(sig)
            self.issued += 1
            self.rows[payload['quote']]['state'] = 'ISSUED'
            if self.fail_after_issue:
                raise TimeoutError('PRIVATE quote')
            return {'signatures': signatures}
        raise AssertionError(path)


class Publisher:
    def __init__(self):
        self.events = []
        self.home_ok = True
        self.public_ok = True
        self.history_ok = True
    async def __call__(self, relay, event, private=False):
        assert Event.load(event).is_valid()
        self.events.append((relay, event, private))
        return (self.home_ok and (self.history_ok or event['kind'] != 7377)) if private else self.public_ok


def setup(tmp_path):
    custody = CustodyStore(tmp_path, Fernet.generate_key())
    wallets = WalletService(custody)
    keys = Keys()
    material = {'nsec': keys.private_key_bech32(), 'npub': keys.public_key_bech32(), 'phrase': 'secret phrase', 'relay': wallets.default_relay}
    custody.insert('owner', material, 'active')
    custody.save_handle('owner', 'Alice')
    mint, publisher = Mint(), Publisher()
    original_wallet = wallets.backend.wallet
    def wallet_with_transport(material):
        wallet = original_wallet(material)
        wallet._publish_incoming_event = publisher
        return wallet
    wallets.backend.wallet = wallet_with_transport
    service = PaymentService(wallets, 'https://oakgate.example', mint=mint)
    async def publish_receipt(item, relay):
        return await publisher(relay, item['receipt'])
    service.identity.publish_receipt = publish_receipt
    discovery = service.discovery('ALICE')
    token = discovery['callback'].rsplit('/',1)[1]
    return SimpleNamespace(custody=custody, wallets=wallets, keys=keys, mint=mint, publisher=publisher,
                           service=service, discovery=discovery, token=token, material=material)


def zap(f, **changes):
    sender = Keys()
    event = Event(kind=9734, pub_key=sender.public_key_hex(), content='Thank you', tags=[
        ['p', f.keys.public_key_hex()], ['amount', '13000'], ['relays', 'wss://relay.damus.io'],
        ['lnurl', encode_lnurl('https://oakgate.example/.well-known/lnurlp/alice')],
        ['e', 'ab'*32], ['P', f.service.identity.pubkey],
    ], **changes)
    event.sign(sender.private_key_hex())
    return json.dumps(event.data(), separators=(',', ':'))


def test_restart_after_issuance_restores_same_proofs(tmp_path):
    async def run():
        f = setup(tmp_path)
        await f.service.invoice(f.token, '13000')
        pid = f.service.store.due()[0]
        item = f.service.store.get(pid)
        assert not f.publisher.events
        await f.service.process(pid)  # unpaid: no proofs or receipts
        assert not f.publisher.events and f.mint.issued == 0
        f.mint.rows[item['quote']]['state'] = 'PAID'
        f.mint.fail_after_issue = True
        await f.service.process(pid)
        assert f.mint.issued == 1 and not f.publisher.events
        restarted = PaymentService(f.wallets, 'https://oakgate.example', mint=f.mint)
        restarted.identity.publish_receipt = f.service.identity.publish_receipt
        await restarted.process(pid)
        complete = restarted.store.get(pid)
        assert complete['state'] == 'complete' and f.mint.issued == 1
        assert sum(p['amount'] for p in complete['proofs']) == 13
        for p in complete['proofs']:
            assert verify(f.mint.key, PublicKey(bytes.fromhex(p['C']), raw=True), p['secret'])
        wallet = f.wallets.backend.wallet(f.material)
        event = complete['proof_event']
        payload = json.loads(ExtendedNIP44Encrypt(wallet.k).decrypt(event['content'], for_pub_k=wallet.pubkey_hex))
        assert payload['mint'] == DEFAULT_MINT and sum(p['amount'] for p in payload['proofs']) == 13
        for secret in complete['prepared']['secrets']:
            assert secret['secret'].encode() not in f.custody.path.read_bytes()
        await restarted.process(pid)
        assert [event['kind'] for _, event, _ in f.publisher.events] == [7375, 7377]
    asyncio.run(run())


def test_zap_only_after_credit_same_event_on_retries(tmp_path):
    async def run():
        f = setup(tmp_path)
        raw = zap(f)
        original_invoice = await f.service.invoice(f.token, '13000', raw)
        assert await f.service.invoice(f.token, '13000', raw) == original_invoice
        assert len(f.mint.rows) == 1
        pid = f.service.store.due()[0]
        item = f.service.store.get(pid)
        f.mint.rows[item['quote']]['state'] = 'PAID'
        f.publisher.home_ok = False
        await f.service.process(pid)
        assert all(private for _, _, private in f.publisher.events)
        proof_id = f.publisher.events[0][1]['id']
        f.publisher.home_ok = True
        f.publisher.public_ok = False
        await f.service.process(pid)
        credited = f.service.store.get(pid)
        assert credited['state'] == 'credited'
        assert credited['proof_event']['id'] == proof_id
        receipt = credited['receipt']
        assert receipt['kind'] == 9735 and receipt['pubkey'] == f.service.identity.pubkey
        assert receipt['pubkey'] != f.keys.public_key_hex()
        assert ['p', f.keys.public_key_hex()] in receipt['tags']
        assert ['description', raw] in receipt['tags'] and ['bolt11', original_invoice] in receipt['tags']
        assert ['P', json.loads(raw)['pubkey']] in receipt['tags']
        assert bolt11.decode(original_invoice).description_hash == hashlib.sha256(raw.encode()).hexdigest()
        f.publisher.public_ok = True
        await f.service.process(pid)
        assert f.service.store.get(pid)['state'] == 'complete'
        assert f.mint.issued == 1
        public = [(relay, event) for relay, event, private in f.publisher.events if not private]
        assert {relay for relay, _ in public} == set(DEFAULT_ZAP_RELAYS)
        assert {event['id'] for _, event in public} == {receipt['id']}
    asyncio.run(run())


def test_address_ownership_and_callback_snapshot(tmp_path):
    async def run():
        f = setup(tmp_path)
        f.custody.save_handle('owner', 'Another')
        with pytest.raises(HandleTaken):
            f.custody.save_handle('someone-else', 'Alice')
        with pytest.raises(ValueError):
            f.service.discovery('Alice')
        await f.service.invoice(f.token, '13000')
        row = f.service.store.get(f.service.store.due()[0])
        assert row['owner'] == 'owner'
        assert f.discovery['metadata'] == row['description']
        assert f.service.address('Another') == 'another@oakgate.example'
    asyncio.run(run())


@pytest.mark.parametrize('amount', ['0', '-1', '1001', '1000000001', '1.5', 'abc', '1'*100])
def test_amount_rejected_before_mint(tmp_path, amount):
    async def run():
        f = setup(tmp_path)
        with pytest.raises(ValueError):
            await f.service.invoice(f.token, amount)
        assert not f.mint.calls
    asyncio.run(run())


def test_bad_zaps_never_request_invoices(tmp_path):
    async def run():
        f = setup(tmp_path)
        bad = json.loads(zap(f))
        bad['content'] = 'tampered'
        for raw in (json.dumps(bad), '{}', '[]', 'not-json', 'x'*17000):
            with pytest.raises((ValueError, TypeError)):
                await f.service.invoice(f.token, '13000', raw)
        signed = json.loads(zap(f))
        with pytest.raises(ValueError):
            validate_zap(json.dumps(signed), 14000, f.keys.public_key_hex(), '')
        with pytest.raises(ValueError):
            validate_zap(json.dumps(signed), 13000, Keys().public_key_hex(), '')
        assert not f.mint.calls
    asyncio.run(run())


def test_strict_mint_compatibility(tmp_path):
    async def run():
        f = setup(tmp_path)
        f.mint.hashed = False
        with pytest.raises(MintCompatibilityError, match='description-hash'):
            await f.service.invoice(f.token, '13000')
        assert not f.service.store.due() and f.mint.issued == 0
        f.mint.restorable = False
        with pytest.raises(MintCompatibilityError, match='NUT-09'):
            await f.service.invoice(f.token, '13000')
    asyncio.run(run())


def test_public_routes_limits_and_cors(tmp_path):
    async def run():
        f = setup(tmp_path)
        app = create_app(settings=AuthSettings('https://oakgate.example'), wallets=f.wallets)
        app.state.payments = f.service
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='https://oakgate.example') as client:
            response = await client.get('/.well-known/lnurlp/Alice', headers={'host': 'evil.example'})
            data = response.json()
            assert data['callback'].startswith('https://oakgate.example/')
            assert data['nostrPubkey'] == f.service.identity.pubkey and data['allowsNostr']
            assert response.headers['access-control-allow-origin'] == '*'
            assert response.headers['cache-control'] == 'no-store'
            assert (await client.get('/.well-known/lnurlp/missing')).json()['status'] == 'ERROR'
            result = (await client.get(data['callback'], params={'amount': '13000'})).json()
            assert bolt11.decode(result['pr']).amount_msat == 13000
            assert (await client.get(data['callback']+'?amount=1000&amount=2000')).json()['status'] == 'ERROR'
            assert data['commentAllowed'] == 255
            commented = (await client.get(data['callback'], params={'amount':'1000','comment':'hello'})).json()
            assert bolt11.decode(commented['pr']).amount_msat == 1000
            rows = [f.service.store.get(pid) for pid in f.service.store.due()]
            assert any(row.get('comment') == 'hello' for row in rows)
            assert (await client.get(data['callback'], params={'amount':'1000','comment':'x'*256})).json()['status'] == 'ERROR'
            for i in range(28):
                f.service.store.reserve('owner', {'amount': 1})
            assert (await client.get(data['callback'], params={'amount':'1000'})).json()['status'] == 'ERROR'
    asyncio.run(run())


def test_payment_lease_and_expired_paid_recovery(tmp_path):
    async def run():
        f = setup(tmp_path)
        await f.service.invoice(f.token, '13000')
        pid = f.service.store.due()[0]
        token = f.service.store.claim(pid)
        with pytest.raises(PaymentBusy):
            f.service.store.claim(pid)
        await f.service.process(pid)
        assert f.mint.issued == 0
        f.service.store.release(pid, token)
        item = f.service.store.get(pid)
        item['expiry'] = 1
        f.service.store.save(item)
        f.mint.rows[item['quote']]['state'] = 'PAID'
        await f.service.process(pid)
        assert f.service.store.get(pid)['state'] == 'complete'
    asyncio.run(run())


@pytest.mark.parametrize('relay', ['ws://relay.damus.io','wss://127.0.0.1','wss://[::1]','wss://user:pass@relay.damus.io', 'wss://localhost', 'wss://relay.damus.io:8080'])
def test_relay_boundary(relay):
    with pytest.raises(ValueError): public_relay(relay)


def test_bootstrap_mint_is_configurable():
    backend = AcornBackend('https://mint.example')
    wallet = backend.wallet({'nsec': Keys().private_key_bech32(), 'relay': 'wss://spurline.safebox.dev'})
    assert wallet.home_mint == 'https://mint.example'
    assert PaymentSettings().mint == DEFAULT_MINT


def test_compatibility_mode_accepts_plain_invoice_and_publishes_receipt(tmp_path):
    async def run():
        f = setup(tmp_path)
        f.mint.require_description_hash = False
        f.mint.hashed = False
        raw = zap(f)
        pr = await f.service.invoice(f.token, '13000', raw)
        assert bolt11.decode(pr).description_hash is None
        pid = f.service.store.due()[0]
        item = f.service.store.get(pid)
        assert item['description_hash_bound'] is False
        f.mint.rows[item['quote']]['state'] = 'PAID'
        await f.service.process(pid)
        assert f.service.store.get(pid)['state'] == 'complete'
        assert all(['description', raw] in event['tags'] for _, event, private in f.publisher.events if not private)
        assert PaymentSettings().require_description_hash is False
        assert CashuMint().require_description_hash is False
    asyncio.run(run())


def test_zap_same_id_different_serialization_rejected(tmp_path):
    async def run():
        f = setup(tmp_path)
        raw = zap(f)
        await f.service.invoice(f.token, '13000', raw)
        with pytest.raises(ValueError):
            await f.service.invoice(f.token, '13000', json.dumps(json.loads(raw), indent=2))
        assert len(f.mint.rows) == 1
    asyncio.run(run())


def test_paused_payments_and_configuration(tmp_path, monkeypatch):
    f = setup(tmp_path)
    paused = PaymentService(f.wallets, 'https://oakgate.example', config=PaymentSettings(enabled=False))
    assert paused.address('alice') is None
    with pytest.raises(ValueError): paused.discovery('alice')
    monkeypatch.setenv('OAKGATE_REQUIRE_DESCRIPTION_HASH', 'true')
    assert PaymentSettings.from_env().require_description_hash
    monkeypatch.setenv('OAKGATE_PAYMENTS_ENABLED', 'invalid')
    with pytest.raises(ValueError): PaymentSettings.from_env()


def test_handle_reserved_before_first_address_lookup(tmp_path):
    custody = CustodyStore(tmp_path, Fernet.generate_key())
    keys = Keys()
    custody.save_handle('one', 'Alice')
    custody.insert('one', {'nsec': keys.private_key_bech32(), 'npub': keys.public_key_bech32()}, 'active')
    custody.save_handle('one', 'Bob')
    for handle in ('Alice', 'Bob'):
        with pytest.raises(HandleTaken): custody.save_handle('two', handle)
    custody.save_handle('one', '')
    with pytest.raises(HandleTaken): custody.save_handle('two', 'Bob')


def test_invalid_mint_signatures_never_credited(tmp_path):
    async def run():
        f = setup(tmp_path)
        await f.service.invoice(f.token, '13000')
        pid = f.service.store.due()[0]
        item = f.service.store.get(pid)
        f.mint.rows[item['quote']]['state'] = 'PAID'
        original = f.mint.request
        async def corrupt(mint, method, path, payload=None):
            result = await original(mint, method, path, payload)
            if path == '/v1/mint/bolt11':
                result['signatures'][0]['dleq']['s'] = '01'*32
            return result
        f.mint.request = corrupt
        await f.service.process(pid)
        assert f.service.store.get(pid)['state'] == 'waiting'
        assert not f.publisher.events
    asyncio.run(run())


def test_worker_lifecycle_starts_and_cancels(tmp_path):
    async def run():
        f = setup(tmp_path)
        app = create_app(settings=AuthSettings('https://oakgate.example'), wallets=f.wallets)
        started, stopped = asyncio.Event(), asyncio.Event()
        async def worker():
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()
        app.state.payments.run = worker
        async with app.router.lifespan_context(app):
            await asyncio.wait_for(started.wait(), 1)
        assert stopped.is_set()
    asyncio.run(run())


@pytest.mark.parametrize('comment', [None, '', 'Thanks!', '⚡'*255])
def test_payment_comments_preserve_metadata_and_zap_binding(tmp_path, comment):
    async def run():
        f = setup(tmp_path)
        raw = zap(f)
        await f.service.invoice(f.token, '13000', comment=comment)
        ordinary = f.service.store.get(f.service.store.due()[0])
        assert ordinary['comment'] == comment
        assert ordinary['description'] == f.discovery['metadata']
        pr = await f.service.invoice(f.token, '13000', raw, comment=comment)
        rows = [f.service.store.get(pid) for pid in f.service.store.due()]
        zapped = next(row for row in rows if row['zap'])
        assert zapped['comment'] == comment and zapped['description'] == raw
        assert bolt11.decode(pr).description_hash == hashlib.sha256(raw.encode()).hexdigest()
        with pytest.raises(ValueError, match='comment'):
            await f.service.invoice(f.token, '13000', comment='x'*256)
        assert len(f.mint.rows) == 2
    asyncio.run(run())


@pytest.mark.parametrize('is_zap', [False, True])
def test_native_acorn_history_and_restart_retry(tmp_path, monkeypatch, is_zap):
    async def run():
        from stroma import NIP44Encrypt
        import importlib
        acorn_module = importlib.import_module('acorn.acorn')
        f = setup(tmp_path)
        await f.service.invoice(f.token, '13000', zap(f) if is_zap else None, comment='Received with thanks')
        pid = f.service.store.due()[0]
        item = f.service.store.get(pid)
        f.mint.rows[item['quote']]['state'] = 'PAID'
        f.publisher.history_ok = False
        await f.service.process(pid)
        pending = f.service.store.get(pid)
        assert pending['state'] == 'credited' and not pending['history_written']
        assert f.mint.issued == 1
        first_id = pending['history_event']['id']
        f.publisher.history_ok = True
        restarted = PaymentService(f.wallets, 'https://oakgate.example', mint=f.mint)
        restarted.identity.publish_receipt = f.service.identity.publish_receipt
        await restarted.process(pid)
        done = restarted.store.get(pid)
        assert done['state'] == 'complete' and done['history_written']
        assert done['history_event']['id'] == first_id and f.mint.issued == 1
        assert sum(event['kind'] == 7375 for _, event, _ in f.publisher.events) == 1
        wallet = f.wallets.backend.wallet(f.material)
        payload = json.loads(NIP44Encrypt(wallet.k).decrypt(done['history_event']['content'], wallet.pubkey_hex))
        assert payload['amount'] == 13 and payload['tx_type'] == 'C'
        assert payload['comment'] == 'Received with thanks' and payload['current_balance'] is None
        assert payload['invoice'] == done['invoice'] and payload['create_time'] == done['paid_at']
        class Relay:
            def __init__(self, relays): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            async def query(self, filters):
                assert filters[0]['kinds'] == [7377]
                return [Event.load(done['history_event'])]
        monkeypatch.setattr(acorn_module, 'ClientPool', Relay)
        history = await wallet.get_tx_history()
        assert history[0]['amount'] == 13 and history[0]['comment'] == 'Received with thanks'
        from app.transactions import transaction_cards
        assert transaction_cards(history)[0]['direction'] == 'Received'
        before = len(f.publisher.events)
        await restarted.process(pid)
        assert len(f.publisher.events) == before and pid not in restarted.store.due()
    asyncio.run(run())


def test_completed_payment_backfills_history_without_minting(tmp_path):
    async def run():
        from contextlib import closing
        f = setup(tmp_path)
        await f.service.invoice(f.token, '13000')
        pid = f.service.store.due()[0]
        item = f.service.store.get(pid)
        f.mint.rows[item['quote']]['state'] = 'PAID'
        await f.service.process(pid)
        old = f.service.store.get(pid)
        old.pop('history_event')
        old.pop('history_written')
        # Simulate an encrypted row created by the pre-history implementation.
        with closing(f.custody.connect()) as db, db:
            db.execute('UPDATE incoming_payments SET encrypted=?,history_written=0,next_check=0 WHERE id=?',
                       (f.custody.seal(old['owner'], old), pid))
        f.publisher.events.clear()
        restarted = PaymentService(f.wallets, 'https://oakgate.example', mint=f.mint)
        restarted.identity.publish_receipt = f.service.identity.publish_receipt
        assert pid in restarted.store.due()
        await restarted.process(pid)
        assert f.mint.issued == 1
        assert [event['kind'] for _, event, _ in f.publisher.events] == [7377]
        assert restarted.store.get(pid)['history_written']
    asyncio.run(run())


def test_history_schema_upgrade_preserves_old_rows(tmp_path):
    from contextlib import closing
    from app.payment_store import PaymentStore
    custody = CustodyStore(tmp_path, Fernet.generate_key())
    item = {'id': 'old-payment', 'owner': 'owner', 'state': 'complete', 'amount': 1}
    with closing(custody.connect()) as db, db:
        db.execute("CREATE TABLE incoming_payments (id TEXT PRIMARY KEY, owner TEXT NOT NULL, zap_id TEXT UNIQUE, created REAL NOT NULL, state TEXT NOT NULL, encrypted BLOB NOT NULL, next_check REAL NOT NULL DEFAULT 0, lease TEXT, lease_until REAL NOT NULL DEFAULT 0)")
        db.execute("INSERT INTO incoming_payments(id,owner,created,state,encrypted) VALUES(?,?,0,'complete',?)", (item['id'], item['owner'], custody.seal('owner', item)))
    store = PaymentStore(custody)
    assert store.get('old-payment')['amount'] == 1
    assert not store.get('old-payment')['history_written']
    assert store.due() == ['old-payment']
    assert PaymentStore(custody).due() == ['old-payment']


def test_service_identity_binding(tmp_path):
    from contextlib import closing
    store = CustodyStore(tmp_path, Fernet.generate_key())
    first = ServiceIdentity(store, '41' * 32)
    assert first.npub.startswith('npub1') and first.fips_address.startswith('fd')
    assert ServiceIdentity(store, '41' * 32).pubkey == first.pubkey
    for secret in ('', '42' * 32):
        with pytest.raises(RuntimeError, match='bound to this database'):
            ServiceIdentity(store, secret)
    with pytest.raises(ValueError, match='invalid'):
        ServiceIdentity(store, 'not-a-key')
    with closing(store.connect()) as db:
        row = dict(db.execute('SELECT * FROM service_identity').fetchone())
    assert row == {'id': 1, 'npub': first.npub}


def test_unconfigured_identity_disables_only_zaps(tmp_path, monkeypatch):
    monkeypatch.delenv('OAKGATE_SERVICE_NSEC')
    f = setup(tmp_path)
    assert not f.discovery['allowsNostr'] and 'nostrPubkey' not in f.discovery
    async def run():
        assert await f.service.invoice(f.token, '13000')
        with pytest.raises(ValueError, match='identity'):
            await f.service.invoice(f.token, '13000', '{}')
    asyncio.run(run())


def test_zap_provider_is_service_not_recipient(tmp_path):
    f = setup(tmp_path)
    raw = zap(f)
    validate_zap(raw, 13000, f.keys.public_key_hex(),
                 encode_lnurl('https://oakgate.example/.well-known/lnurlp/alice'),
                 provider=f.service.identity.pubkey)
    with pytest.raises(ValueError, match='provider'):
        validate_zap(raw, 13000, f.keys.public_key_hex(), '', provider=f.keys.public_key_hex())


def test_service_receipt_transport_and_foreign_receipt_rejection(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock
    import app.identity as identity_module
    f = setup(tmp_path)
    identity = ServiceIdentity(f.custody)
    item = {'zap': zap(f), 'invoice': 'test-invoice', 'paid_at': 123,
            'service_pubkey': identity.pubkey}
    item['receipt'] = identity.receipt(item)
    relay = SimpleNamespace(publish=AsyncMock(return_value=SimpleNamespace(accepted=True)))
    monkeypatch.setattr(identity_module, 'RelayClient', lambda *args, **kwargs: relay)
    async def run():
        assert await identity.publish_receipt(item, 'wss://relay.damus.io')
        assert relay.publish.await_args.args[0].pub_key == identity.pubkey
        with pytest.raises(ValueError, match='public'):
            await identity.publish_receipt(item, 'wss://127.0.0.1')
        item['service_pubkey'] = f.keys.public_key_hex()
        with pytest.raises(ValueError, match='service'):
            await identity.publish_receipt(item, 'wss://relay.damus.io')
        with pytest.raises(ValueError, match='service'):
            identity.receipt(item)
    asyncio.run(run())


def test_old_callback_cannot_change_zap_signer(tmp_path):
    f = setup(tmp_path)
    snapshot = json.loads(f.custody.cipher.decrypt(f.token.encode()))
    snapshot.pop('service_pubkey')
    old_token = f.custody.cipher.encrypt(json.dumps(snapshot).encode()).decode()
    async def run():
        with pytest.raises(ValueError, match='identity'):
            await f.service.invoice(old_token, '13000', zap(f))
    asyncio.run(run())
