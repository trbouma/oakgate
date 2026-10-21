import asyncio
import json
import time
from unittest.mock import AsyncMock

import httpx
import pytest
from cryptography.fernet import Fernet, InvalidToken

from app.config import AuthSettings
from app.custody import AlreadyConnected, Busy, CustodyStore, identity_key
from app.main import create_app
from app.sessions import MemoryStore, record_key
from app.wallets import AcornBackend, WalletService, WalletInputError, DEFAULT_RELAY


class Backend:
    def __init__(self):
        self.created = 0
        self.initialized = []
        self.down = False
        self.amount = 1234

    def default_handle(self, material, *, attempt=0):
        return f'producefront{(939 + attempt) % 1000}'

    def public_identity(self, material):
        return {'hex': 'ab' * 32, 'npub': material['npub']}

    async def prepare(self, relay):
        self.created += 1
        return {'nsec': 'SECRET-NSEC', 'phrase': 'SECRET-PHRASE', 'relay': relay,
                'npub': 'npub-test', 'initial_wallet_info': 'PRIVATE-METADATA'}

    def recover(self, phrase, relay, legacy=False):
        if phrase != 'SECRET-PHRASE':
            raise WalletInputError('Check the recovery phrase and its word order.')
        return {'nsec': 'SECRET-NSEC', 'phrase': phrase, 'relay': relay, 'npub': 'npub-test', 'legacy': legacy}

    async def initialize(self, material):
        self.initialized.append(material.copy())
        if self.down:
            raise RuntimeError('SECRET-PHRASE provider details')
        return 0

    async def quote_ecash_transfer(self, material, amount):
        return {'version':1, 'recipient_amount':amount, 'token_amount':amount,
                'sender_fee':0, 'receiver_fee':0, 'total_fee':0, 'total_amount':amount}

    async def clear_balances(self, material):
        return []

    async def balance(self, material):
        if self.down:
            raise RuntimeError('SECRET-NSEC provider details')
        return self.amount


def setup(tmp_path):
    store = CustodyStore(tmp_path, Fernet.generate_key())
    backend = Backend()
    service = WalletService(store, backend)
    sessions = MemoryStore()
    settings = AuthSettings('https://oakgate.example', client_secret='test')
    app = create_app(settings=settings, store=sessions, wallets=service)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=settings.origin)
    return client, sessions, service, backend


async def login(client, sessions, sub='user-1', issuer='https://identity.example'):
    user = {'iss': issuer, 'sub': sub, 'name': 'Example', 'email': 'same@example.com'}
    token = issuer + sub
    await sessions.put(record_key('session', token), {'user': user, 'csrf': 'csrf-test', 'expires_at': time.time()+300}, 300)
    client.cookies.clear()
    client.cookies.set('__Host-oakgate_session', token)
    return identity_key(user)


def form(**kwargs):
    return {'csrf': 'csrf-test', 'custody': 'accept', **kwargs}


def test_create_persists_and_retry_is_same_wallet(tmp_path):
    async def run():
        client, sessions, service, backend = setup(tmp_path)
        async with client:
            owner = await login(client, sessions)
            page = await client.get('/account')
            assert 'Create my Acorn' in page.text and 'Connect my Acorn' in page.text
            assert DEFAULT_RELAY in page.text
            backend.down = True
            response = await client.post('/account/acorn/create', data=form())
            assert response.status_code == 503
            assert service.store.get(owner)['status'] == 'pending'
            assert 'Retry setup' in response.text
            assert 'SECRET-' not in response.text and 'PRIVATE-METADATA' not in response.text
            backend.down = False
            result = await client.post('/account/acorn/retry', data=form())
            assert result.status_code == 303
            assert service.store.get(owner)['status'] == 'active'
            assert backend.initialized[0] == backend.initialized[1]
            await client.post('/account/acorn/create', data=form())
            assert backend.created == 1
            page = await client.get('/account')
            assert '1,234' in page.text and 'sats' in page.text
            assert 'SECRET-' not in page.text
            backend.down = True
            page = await client.get('/account')
            assert 'Balance unavailable' in page.text
            assert 'cash-balance' not in page.text
    asyncio.run(run())


def test_connect_and_identity_isolation(tmp_path):
    async def run():
        client, sessions, service, backend = setup(tmp_path)
        async with client:
            owner = await login(client, sessions)
            response = await client.post('/account/acorn/connect', data=form(phrase='SECRET-PHRASE', relay=DEFAULT_RELAY))
            assert response.status_code == 303
            assert service.store.get(owner)['material']['phrase'] == 'SECRET-PHRASE'
            assert backend.created == 0 and backend.initialized == []
            await login(client, sessions, issuer='https://another-issuer.example')
            page = await client.get('/account')
            assert 'Connect my Acorn' in page.text and '1,234' not in page.text
            response = await client.post('/account/acorn/connect', data=form(phrase='SECRET-PHRASE', relay=DEFAULT_RELAY))
            assert response.status_code == 409
            assert service.store.get(owner)['status'] == 'active'
    asyncio.run(run())


def test_recovery_failure_does_not_create_or_store(tmp_path):
    async def run():
        client, sessions, service, backend = setup(tmp_path)
        async with client:
            owner = await login(client, sessions)
            response = await client.post('/account/acorn/connect', data=form(phrase='wrong', relay=DEFAULT_RELAY))
            assert response.status_code == 400
            backend.down = True
            response = await client.post('/account/acorn/connect', data=form(phrase='SECRET-PHRASE', relay=DEFAULT_RELAY))
            assert response.status_code == 503
            assert 'SECRET-PHRASE' not in response.text
            assert service.store.get(owner) is None
            assert backend.created == 0 and backend.initialized == []
    asyncio.run(run())


def test_auth_csrf_consent_and_relay_guards(tmp_path):
    async def run():
        client, sessions, service, backend = setup(tmp_path)
        async with client:
            response = await client.post('/account/acorn/create', data=form())
            assert response.headers['location'] == '/auth/login'
            owner = await login(client, sessions)
            for route in ('create', 'connect', 'retry'):
                response = await client.post('/account/acorn/'+route, data=form(csrf='wrong'))
                assert response.status_code == 403
                response = await client.post('/account/acorn/'+route, data=form(), headers={'origin': 'https://evil.example'})
                assert response.status_code == 403
            assert (await client.post('/account/acorn/create', data=form(custody=''))).status_code == 400
            for relay in ('http://127.0.0.1', 'wss://127.0.0.1', 'wss://user:pass@spurline.safebox.dev', 'wss://evil.example', DEFAULT_RELAY+'?token=secret'):
                assert (await client.post('/account/acorn/connect', data=form(phrase='SECRET-PHRASE', relay=relay))).status_code == 400
            assert (await client.post('/account/acorn/connect', data=form(phrase='x'*9000, relay=DEFAULT_RELAY))).status_code == 413
            assert backend.created == 0 and service.store.get(owner) is None
    asyncio.run(run())


def test_ciphertext_restart_uniqueness_and_leases(tmp_path):
    key = Fernet.generate_key()
    store = CustodyStore(tmp_path, key)
    material = {'nsec': 'SECRET-NSEC', 'phrase': 'SECRET-PHRASE', 'relay': DEFAULT_RELAY, 'npub':'npub-test'}
    store.insert('owner', material, 'pending')
    raw = store.path.read_bytes()
    assert b'SECRET-NSEC' not in raw and b'SECRET-PHRASE' not in raw
    restarted = CustodyStore(tmp_path, key)
    assert restarted.get('owner')['material'] == material
    assert restarted.get('someone-else') is None
    with pytest.raises(AlreadyConnected):
        store.insert('another-owner', material, 'active')
    lease = store.acquire('owner')
    with pytest.raises(Busy):
        restarted.acquire('owner')
    restarted.release('owner', 'wrong-token', active=True)
    assert store.get('owner')['status'] == 'pending'
    store.release('owner', lease, active=True)
    assert restarted.get('owner')['status'] == 'active'
    with pytest.raises(InvalidToken):
        CustodyStore(tmp_path, Fernet.generate_key()).get('owner')


def test_real_acorn_offline_generation_and_recovery():
    async def run():
        backend = AcornBackend()
        material = await backend.prepare(DEFAULT_RELAY)
        assert len(material['phrase'].split()) == 24
        recovered = backend.recover(material['phrase'], DEFAULT_RELAY)
        assert recovered['nsec'] == material['nsec']
        assert recovered['npub'] == material['npub']
        tags = json.loads(material['initial_wallet_info'])
        assert ['seedphrase', material['phrase']] in tags
        first, second = backend.wallet(material), backend.wallet(material)
        first.known_mints['test'] = 'test'
        first.user_records.append('test')
        assert second.known_mints == {} and second.user_records == []
        first.get_wallet_info = AsyncMock(return_value=None)
        first.set_wallet_info = AsyncMock()
        first.load_data = AsyncMock()
        backend.wallet = lambda _: first
        assert await backend.initialize(material) == 0
        first.set_wallet_info.assert_awaited_once_with(label='wallet', label_info=material['initial_wallet_info'], verify=True)
        first.get_wallet_info = AsyncMock(return_value=material['initial_wallet_info'])
        first.set_wallet_info.reset_mock()
        await backend.initialize(material)
        first.set_wallet_info.assert_not_awaited()
        first.load_data.assert_awaited()
    asyncio.run(run())


def test_default_handle_survives_setup_retry_and_can_be_changed(tmp_path):
    async def run():
        client, sessions, service, backend = setup(tmp_path)
        async with client:
            owner = await login(client, sessions)
            backend.down = True
            await client.post('/account/acorn/create', data=form())
            expected = backend.default_handle({})
            assert service.store.preference(owner) == expected
            backend.down = False
            await client.post('/account/acorn/retry', data=form())
            assert service.store.preference(owner) == expected
            assert service.store.address_owner(expected) == owner
            service.store.save_handle(owner, 'my-custom-handle')
            await client.post('/account/acorn/retry', data=form())
            assert service.store.preference(owner) == 'my-custom-handle'
    asyncio.run(run())


def test_default_handle_collision_reservation_and_existing_preference(tmp_path):
    store = CustodyStore(tmp_path, Fernet.generate_key())
    candidate = lambda *, attempt=0: f'producefront{(939 + attempt) % 1000}'
    preferred = candidate()
    store.insert('first', {'npub': 'first'}, 'active')
    store.save_handle('first', preferred)
    store.save_handle('first', 'renamed')
    # The old receipt address remains reserved even though no longer displayed.
    assert store.ensure_default_handle('second', candidate) == candidate(attempt=1)
    assert store.ensure_default_handle('third', candidate) == candidate(attempt=2)
    store.save_handle('custom', 'ChosenName')
    assert store.ensure_default_handle('custom', candidate) == 'ChosenName'



def test_default_handle_adapter_delegates_to_acorn(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock
    backend = AcornBackend()
    method = Mock(return_value='producefront940')
    monkeypatch.setattr(backend, 'wallet', lambda material: SimpleNamespace(default_handle=method))
    assert backend.default_handle({}, attempt=1) == 'producefront940'
    method.assert_called_once_with(attempt=1)


def test_default_handle_missing_acorn_api_gives_upgrade_instruction(monkeypatch):
    from types import SimpleNamespace
    backend = AcornBackend()
    monkeypatch.setattr(backend, 'wallet', lambda material: SimpleNamespace())
    with pytest.raises(WalletInputError, match='updated safebox-acorn'):
        backend.default_handle({})
