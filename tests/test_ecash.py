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


def test_slow_inbox_gets_cooldown_after_completion(tmp_path, monkeypatch):
    async def run():
        client, sessions, service, backend = setup(tmp_path)
        ready(backend)
        async with client:
            owner = await login(client, sessions)
            await client.post('/account/acorn/create', data=form())
            receiver = EcashReceiver(service)
            receiver.due()
            import time
            clock = [time.time()]
            monkeypatch.setattr('app.ecash.time.time', lambda: clock[0])
            async def slow(material):
                clock[0] += 40
            backend.receive_ecash.side_effect = slow
            await receiver.process(owner)
            with service.store.connect() as db:
                row = db.execute('SELECT next_poll FROM ecash_inboxes WHERE owner=?', (owner,)).fetchone()
            assert row['next_poll'] == clock[0] + receiver.interval
            assert receiver.due() == []
    asyncio.run(run())


def test_inbox_failure_backoff_and_wake_survive_completion(tmp_path):
    async def run():
        client, sessions, service, backend = setup(tmp_path)
        ready(backend)
        async with client:
            owner = await login(client, sessions)
            await client.post('/account/acorn/create', data=form())
            service.store.save_handle(owner, 'alice')
            receiver = EcashReceiver(service)
            receiver.due()
            backend.receive_ecash.side_effect = TimeoutError()
            await receiver.process(owner)
            import time
            with service.store.connect() as db:
                row = db.execute('SELECT next_poll,failures FROM ecash_inboxes WHERE owner=?', (owner,)).fetchone()
            assert row['failures'] == 1
            assert row['next_poll'] > time.time() + receiver.interval
            receiver.wake('alice')
            async def wake_during_run(material):
                receiver.wake('alice')
            backend.receive_ecash.side_effect = wake_during_run
            await receiver.process(owner)
            assert EcashReceiver(service).due() == [owner]
    asyncio.run(run())


def test_foreground_can_claim_between_inbox_phases(tmp_path, monkeypatch):
    async def run():
        client, sessions, service, backend = setup(tmp_path)
        ready(backend)
        backend.clear_receiving_available = True
        backend.receive_clear = AsyncMock()
        async with client:
            owner = await login(client, sessions)
            await client.post('/account/acorn/create', data=form())
            receiver = EcashReceiver(service)
            receiver.due()
            foreground = []
            async def foreground_claim(seconds):
                # Cash phase must have released the lease. A foreground send
                # wins; Clear is deferred without executing or losing its inbox.
                foreground.append(service.store.acquire(owner))
            monkeypatch.setattr('app.ecash.asyncio.sleep', foreground_claim)
            await receiver.process(owner)
            backend.receive_ecash.assert_awaited_once()
            backend.receive_clear.assert_not_awaited()
            from app.custody import Busy
            import pytest
            with pytest.raises(Busy):
                service.store.acquire(owner)
            service.store.release(owner, foreground[0])
            with service.store.connect() as db:
                assert db.execute('SELECT failures FROM ecash_inboxes').fetchone()['failures'] == 0
    asyncio.run(run())


def test_cancelled_inbox_drains_write_before_releasing_lease(tmp_path):
    async def run():
        client, sessions, service, backend = setup(tmp_path)
        ready(backend)
        async with client:
            owner = await login(client, sessions)
            await client.post('/account/acorn/create', data=form())
            receiver = EcashReceiver(service)
            receiver.due()
            entered = asyncio.Event()
            finish = asyncio.Event()
            async def blocked(material):
                entered.set()
                await finish.wait()
            backend.receive_ecash.side_effect = blocked
            task = asyncio.create_task(receiver.process(owner))
            await asyncio.wait_for(entered.wait(), 1)
            task.cancel()
            await asyncio.sleep(0)
            import pytest
            from app.custody import Busy
            assert not task.done()
            with pytest.raises(Busy):
                service.store.acquire(owner)
            finish.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            lease = service.store.acquire(owner)
            service.store.release(owner, lease)
            with service.store.connect() as db:
                db.execute('UPDATE ecash_inboxes SET next_poll=0')
            backend.receive_ecash.side_effect = None
            await EcashReceiver(service).process(owner)
            assert backend.receive_ecash.await_count == 2
    asyncio.run(run())


def test_scheduler_replaces_finished_work_without_waiting_for_slow_owner():
    async def run():
        from types import SimpleNamespace
        receiver = object.__new__(EcashReceiver)
        receiver.enabled = True
        receiver.clear_enabled = False
        receiver.wallets = SimpleNamespace(backend=SimpleNamespace(ecash_receiving_available=True))
        started = set()
        fifth = asyncio.Event()
        cancelled = asyncio.Event()
        async def process(owner):
            started.add(owner)
            if owner == 0:
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()
            if owner == 4:
                fifth.set()
        receiver.process = process
        receiver.due = lambda: [owner for owner in range(5) if owner not in started][:4]
        task = asyncio.create_task(receiver.run())
        try:
            await asyncio.wait_for(fifth.wait(), 3)
            assert not cancelled.is_set()
        finally:
            task.cancel()
            import pytest
            with pytest.raises(asyncio.CancelledError):
                await task
        assert cancelled.is_set()
    asyncio.run(run())


def test_separate_phases_continue_settlement_after_discovery_failure(tmp_path, monkeypatch, caplog):
    async def run():
        client, sessions, service, backend = setup(tmp_path)
        ready(backend)
        backend.inbox_phases = True
        backend.clear_receiving_available = True
        calls = []
        async def action(name, material):
            calls.append(name)
            if name == 'discover_clear':
                raise TimeoutError('SECRET provider detail')
            return {}
        from functools import partial
        for name in ('discover_ecash', 'discover_clear', 'settle_ecash', 'settle_clear'):
            setattr(backend, name, partial(action, name))
        async with client:
            owner = await login(client, sessions)
            await client.post('/account/acorn/create', data=form())
            receiver = EcashReceiver(service)
            receiver.due()
            async def gap(seconds):
                token = service.store.acquire(owner)
                service.store.release(owner, token)
            monkeypatch.setattr('app.ecash.asyncio.sleep', gap)
            await receiver.process(owner)
            assert calls == ['discover_ecash', 'discover_clear', 'settle_ecash', 'settle_clear']
            assert 'phase=discover_clear status=error elapsed=' in caplog.text
            assert 'phase=settle_clear status=complete elapsed=' in caplog.text
            assert 'SECRET' not in caplog.text
    asyncio.run(run())


def test_lease_renewal_cannot_steal_or_resurrect_ownership(tmp_path, monkeypatch):
    async def run():
        client, sessions, service, backend = setup(tmp_path)
        async with client:
            owner = await login(client, sessions)
            await client.post('/account/acorn/create', data=form())
            import time
            clock = [time.time()]
            monkeypatch.setattr('app.custody.time.time', lambda: clock[0])
            token = service.store.acquire(owner)
            clock[0] += 60
            service.store.renew(owner, token)
            clock[0] += 60
            from app.custody import Busy
            import pytest
            with pytest.raises(Busy):
                service.store.acquire(owner)
            clock[0] += 31
            with pytest.raises(Busy):
                service.store.renew(owner, token)
            replacement = service.store.acquire(owner)
            with pytest.raises(Busy):
                service.store.renew(owner, token)
            service.store.release(owner, replacement)
    asyncio.run(run())


def test_active_phase_renews_until_write_finishes(monkeypatch):
    async def run():
        from types import SimpleNamespace
        from unittest.mock import Mock
        finish = asyncio.Event()
        async def write(material):
            await finish.wait()
            return {'accepted_count': 1}
        renewals = []
        def renew(owner, lease):
            renewals.append((owner, lease))
            if len(renewals) == 2:
                finish.set()
        receiver = object.__new__(EcashReceiver)
        receiver.wallets = SimpleNamespace(
            store=SimpleNamespace(renew=Mock(side_effect=renew)),
            backend=SimpleNamespace(settle_clear=write))
        original_wait = asyncio.wait
        async def tick(tasks, timeout):
            return await original_wait(tasks, timeout=0.001)
        monkeypatch.setattr('app.ecash.asyncio.wait', tick)
        result = await receiver.phase('owner', 'lease', 'settle_clear', {})
        assert result == {'accepted_count': 1}
        assert len(renewals) >= 2
        assert all(pair == ('owner', 'lease') for pair in renewals)
    asyncio.run(run())


def test_lost_lease_stops_work_and_waits_for_cleanup(monkeypatch):
    async def run():
        from types import SimpleNamespace
        from unittest.mock import Mock
        from app.custody import Busy
        import pytest
        cleaned = asyncio.Event()
        async def write(material):
            try:
                await asyncio.Event().wait()
            finally:
                cleaned.set()
        receiver = object.__new__(EcashReceiver)
        receiver.wallets = SimpleNamespace(
            store=SimpleNamespace(renew=Mock(side_effect=Busy)),
            backend=SimpleNamespace(settle_clear=write))
        original_wait = asyncio.wait
        async def tick(tasks, timeout):
            return await original_wait(tasks, timeout=0.001)
        monkeypatch.setattr('app.ecash.asyncio.wait', tick)
        with pytest.raises(Busy):
            await receiver.phase('owner', 'lease', 'settle_clear', {})
        assert cleaned.is_set()
    asyncio.run(run())
