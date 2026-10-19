import asyncio
from unittest.mock import AsyncMock

from app.ecash import EcashReceiver
from app.wallets import AcornBackend
from test_wallets import setup, login, form


def ready(backend):
    backend.ecash_receiving_available = True
    backend.public_identity = lambda material: {'hex': 'ab' * 32}
    backend.receive_ecash = AsyncMock(return_value={'finalized': {'confirmed_count': 1}})


def test_discovery_and_signed_out_receiving(tmp_path):
    async def run():
        client, sessions, service, backend = setup(tmp_path)
        ready(backend)
        async with client:
            owner = await login(client, sessions)
            await client.post('/account/acorn/create', data=form())
            service.store.save_handle(owner, 'Alice')
            client.cookies.clear()
            receiver = EcashReceiver(service)
            response = await client.get('/.well-known/nostr.json?name=Alice')
            assert response.status_code == 200
            assert response.json()['names'] == {'alice': 'ab' * 32}
            assert 'mints' not in response.json()['safebox']['alice']
            assert response.json()['relays']['ab' * 32] == [service.default_relay]
            assert 'SECRET' not in response.text
            assert response.headers['access-control-allow-origin'] == '*'
            assert receiver.due() == [owner]
            await asyncio.gather(receiver.process(owner), receiver.process(owner))
            backend.receive_ecash.assert_awaited_once()
            assert receiver.due() == []
            # Schedule state survives receiver restarts; no session is required.
            assert EcashReceiver(service).due() == []
            service.store.save_handle(owner, '')
            assert (await client.get('/.well-known/nostr.json?name=alice')).status_code == 404
            assert (await client.get('/.well-known/nostr.json?name=alice&name=bob')).status_code == 404
    asyncio.run(run())


def test_feature_gate_does_not_advertise_unavailable_receiver(tmp_path, monkeypatch):
    async def run():
        client, sessions, service, backend = setup(tmp_path)
        async with client:
            owner = await login(client, sessions)
            await client.post('/account/acorn/create', data=form())
            service.store.save_handle(owner, 'alice')
            assert (await client.get('/.well-known/nostr.json?name=alice')).status_code == 404
            ready(backend)
            monkeypatch.setenv('OAKGATE_ECASH_RECEIVE_ENABLED', 'false')
            receiver = EcashReceiver(service)
            assert not receiver.available
            await receiver.process(owner)
            backend.receive_ecash.assert_not_awaited()
    asyncio.run(run())


def test_failure_releases_lease_and_retries_without_secret_logs(tmp_path, caplog):
    async def run():
        client, sessions, service, backend = setup(tmp_path)
        ready(backend)
        async with client:
            owner = await login(client, sessions)
            await client.post('/account/acorn/create', data=form())
            receiver = EcashReceiver(service)
            receiver.due()
            backend.receive_ecash.side_effect = RuntimeError('SECRET-BEARER-TOKEN')
            await receiver.process(owner)
            token = service.store.acquire(owner)
            service.store.release(owner, token)
            with service.store.connect() as db:
                db.execute('UPDATE ecash_inboxes SET next_poll=0')
            backend.receive_ecash.side_effect = None
            assert receiver.due() == [owner]
            await receiver.process(owner)
            assert backend.receive_ecash.await_count == 2
            assert 'SECRET-BEARER' not in caplog.text
    asyncio.run(run())


def test_adapter_stages_then_reconciles_through_acorn(monkeypatch):
    async def run():
        from types import SimpleNamespace
        backend = AcornBackend()
        monkeypatch.setattr(AcornBackend, 'ecash_receiving_available', property(lambda self: True))
        wallet = SimpleNamespace(sweep_ecash_transfers=AsyncMock(return_value={}),
                                 reconcile_continuity_receipts=AsyncMock(return_value={}))
        monkeypatch.setattr(backend, 'wallet', lambda material: wallet)
        await backend.receive_ecash({'relay': 'wss://relay.example'})
        wallet.sweep_ecash_transfers.assert_awaited_once_with(
            relays=['wss://relay.example'], finalize=False, limit=100, max_pages=10)
        wallet.reconcile_continuity_receipts.assert_awaited_once_with()
    asyncio.run(run())
