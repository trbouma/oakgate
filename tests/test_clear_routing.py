import asyncio
import json
from contextlib import aclosing

import pytest

from app.clear_balances import asset_id
from app.clear_routing import clear_availability
from app.ecash import EcashReceiver
from test_clear_payments import clear_setup, MINT, UNIT
from test_wallets import form


@pytest.mark.parametrize('mint,scope', [
    ('http://clear:3338', 'instance'), ('https://localhost', 'instance'),
    ('https://wallet.localhost.', 'instance'), ('https://127.0.0.1', 'instance'),
    ('http://[::1]:3338', 'instance'), ('http://mint.example', 'instance'),
    ('https://mint.example:bad', 'instance'), ('https://u:p@mint.example', 'instance'),
    ('https://mint.example?route=x', 'instance'), ('invalid', 'instance'),
    ('https://192.168.1.5', 'local'), ('http://10.0.0.2:3338', 'local'),
    ('https://[fd00::1]', 'local'), ('https://169.254.1.2', 'local'),
    ('https://mint.local', 'local'), ('https://mint.lan', 'local'),
    ('https://mint.internal', 'local'), ('https://mint.home.arpa', 'local'),
    ('https://mint.example', 'across-networks'), ('https://mint.example:8443', 'across-networks'),
])
def test_scope_matches_safebox_web(mint, scope):
    assert clear_availability(mint) == scope


@pytest.mark.parametrize('mint', ['http://clear:3338', 'https://localhost', 'http://127.0.0.1:3338', 'http://[::1]:3338'])
def test_instance_only_external_send_stops_before_discovery_or_export(tmp_path, mint):
    async def run():
        client, wallets, backend, owner, service, fetch = await clear_setup(tmp_path)
        backend.clear_balances.return_value[0]['mint'] = mint
        async with aclosing(client):
            response = await client.post('/account/send', data=form(address='alice@other.example', amount='1', asset=asset_id(mint, UNIT)))
            assert response.status_code == 422
            assert 'only within this OakGate instance' in response.text and 'No value was sent' in response.text
            fetch.assert_not_awaited()
            backend.send_payment.assert_not_awaited()
            with wallets.store.connect() as db:
                assert db.execute('SELECT count(*) FROM outgoing_payments').fetchone()[0] == 0
    asyncio.run(run())


@pytest.mark.parametrize('mint', ['https://clear.example', 'http://10.0.0.2:3338', 'https://mint.lan'])
def test_public_and_local_network_routes_remain_eligible(tmp_path, mint):
    async def run():
        client, wallets, backend, owner, service, fetch = await clear_setup(tmp_path)
        backend.clear_balances.return_value[0]['mint'] = mint
        async with aclosing(client):
            payment = await service.prepare(owner, 'alice@other.example', '1', '', asset=asset_id(mint, UNIT))
            assert (await service.send(owner, payment['id']))['state'] == 'sent'
            backend.send_payment.assert_awaited_once()
            assert backend.send_payment.await_args.args[1]['mint'] == mint
    asyncio.run(run())


@pytest.mark.parametrize('change', [None, 'handle', 'identity', 'disabled'])
def test_instance_only_local_recipient_is_checked_again_at_confirmation(tmp_path, change):
    async def run():
        client, wallets, backend, owner, service, fetch = await clear_setup(tmp_path)
        mint = 'http://clear:3338'
        backend.clear_balances.return_value[0]['mint'] = mint
        wallets.store.save_handle(owner, 'alice')
        service.receiver = EcashReceiver(wallets)
        async with aclosing(client):
            payment = await service.prepare(owner, 'alice@oakgate.example', '1', '', asset=asset_id(mint, UNIT))
            if change == 'handle': wallets.store.save_handle(owner, 'renamed')
            if change == 'identity': backend.public_identity = lambda material: {'hex': 'cd'*32}
            if change == 'disabled': service.receiver.clear_enabled = False
            response = await client.post('/account/send/confirm', data=form(payment=payment['id']))
            if change:
                assert response.status_code == 422
                assert 'No value was sent' in response.text
                assert service.get(owner, payment['id'])['state'] == 'prepared'
                backend.send_payment.assert_not_awaited()
            else:
                assert response.status_code == 303
                backend.send_payment.assert_awaited_once()
            fetch.assert_not_awaited()
    asyncio.run(run())


def test_preexisting_confirmation_cannot_bypass_guard(tmp_path):
    async def run():
        client, wallets, backend, owner, service, fetch = await clear_setup(tmp_path)
        async with aclosing(client):
            payment = await service.prepare(owner, 'alice@other.example', '1', '', asset=asset_id(MINT, UNIT))
            # Simulate an instance-only payment prepared by the previous release.
            payment['mint'] = 'http://clear:3338'
            payment['asset'] = asset_id(payment['mint'], UNIT)
            with wallets.store.connect() as db, db:
                db.execute('UPDATE outgoing_payments SET encrypted=? WHERE id=?',
                           (wallets.store.cipher.encrypt(json.dumps(payment).encode()), payment['id']))
            response = await client.post('/account/send/confirm', data=form(payment=payment['id']))
            assert response.status_code == 422
            backend.send_payment.assert_not_awaited()
            assert service.get(owner, payment['id'])['state'] == 'prepared'
    asyncio.run(run())
