import asyncio
from contextlib import aclosing
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.clear_balances import asset_id, payment_assets
from app.ecash import EcashReceiver
from app.wallets import AcornBackend
from test_send import prepared
from test_wallets import form

MINT = 'https://clear.example'
UNIT = 'cmu:community'


async def clear_setup(tmp_path):
    client, sessions, wallets, backend, owner, service, fetch = await prepared(tmp_path)
    backend.clear_sending_available = True
    backend.clear_receiving_available = True
    backend.receive_clear = AsyncMock(return_value={'accepted_count': 1})
    backend.clear_balances = AsyncMock(return_value=[{'mint': MINT, 'unit': UNIT, 'amount': 12,
        'keysets': [{'keyset': 'one', 'amount': 5}, {'keyset': 'two', 'amount': 7}]}])
    wallets.clear_labels.fetcher = AsyncMock(return_value=[
        {'id': key, 'unit': UNIT, 'friendly_alias': 'Community credits', 'friendly_unit_alias': 'credits'}
        for key in ('one', 'two')])
    fetch.return_value = {'names': {'alice': 'ab'*32}, 'relays': {'ab'*32: [wallets.default_relay]},
        'clear': {'alice': {'protocols': ['clear-token-transfer'], 'transports': ['nip59'], 'kinds': [7379]}}}
    client._transport.app.state.send = service
    return client, wallets, backend, owner, service, fetch


def test_clear_review_send_and_duplicate_protection(tmp_path):
    async def run():
        client, wallets, backend, owner, service, fetch = await clear_setup(tmp_path)
        async with aclosing(client):
            key = asset_id(MINT, UNIT)
            page = await client.get('/account/send?asset='+key)
            assert 'Community credits' in page.text and '12 credits' in page.text
            assert f'value="{key}" selected' in page.text
            response = await client.post('/account/send', data=form(address='alice@other.example', amount='6', comment='Thanks', asset=key))
            assert response.status_code == 303
            url = response.headers['location']
            review = await client.get(url)
            assert 'Clear payment' in review.text and 'credits' in review.text
            assert MINT in review.text and UNIT in review.text
            assert '₿' not in review.text and 'SECRET' not in review.text
            payment_id = url.split('=')[1]
            backend.send_payment.assert_not_awaited()
            await client.post('/account/send/confirm', data=form(payment=payment_id))
            await client.post('/account/send/confirm', data=form(payment=payment_id))
            backend.send_payment.assert_awaited_once()
            sent = backend.send_payment.await_args.args[1]
            assert (sent['route'], sent['mint'], sent['unit'], sent['amount']) == ('clear', MINT, UNIT, 6)
            assert fetch.await_count == 0  # No LNURL or NIP-05 lookup for Clear.
    asyncio.run(run())


@pytest.mark.parametrize('failure', ['unit', 'protocol', 'relay', 'asset', 'amount'])
def test_incompatible_clear_never_falls_back_to_cash(tmp_path, failure):
    async def run():
        client, wallets, backend, owner, service, fetch = await clear_setup(tmp_path)
        async with aclosing(client):
            key, amount = asset_id(MINT, UNIT), '6'
            if failure == 'unit': fetch.return_value['clear']['alice']['units'] = ['another-unit']
            if failure == 'protocol': fetch.return_value['clear']['alice']['protocols'] = ['acorn-ecash-transfer']
            if failure == 'relay': fetch.return_value['relays']['ab'*32] = ['wss://unapproved.example']
            if failure == 'asset': key = 'tampered'
            if failure == 'amount': amount = '13'
            with pytest.raises(ValueError):
                await service.prepare(owner, 'alice@other.example', amount, '', asset=key)
            backend.send_payment.assert_not_awaited()
            assert all('/lnurl' not in call.args[0] for call in fetch.await_args_list)
            assert (await client.get('/account/send?asset=missing')).status_code == 409
    asyncio.run(run())


def test_signed_out_clear_receiving_survives_cash_failure(tmp_path):
    async def run():
        client, wallets, backend, owner, service, fetch = await clear_setup(tmp_path)
        async with aclosing(client):
            wallets.store.save_handle(owner, 'alice')
            client.cookies.clear()
            receiver = EcashReceiver(wallets)
            descriptor = receiver.discovery('alice')['clear']['alice']
            assert descriptor == {'protocols': ['clear-token-transfer'], 'transports': ['nip59'], 'kinds': [7379]}
            backend.receive_ecash.side_effect = RuntimeError('cash unavailable')
            receiver.due()
            await asyncio.gather(receiver.process(owner), receiver.process(owner))
            backend.receive_clear.assert_awaited_once()
            assert receiver.due() == []
            receiver.wake('alice')
            assert receiver.due() == [owner]
    asyncio.run(run())


def test_clear_disabled_is_not_advertised_or_processed(tmp_path, monkeypatch):
    async def run():
        client, wallets, backend, owner, service, fetch = await clear_setup(tmp_path)
        async with aclosing(client):
            wallets.store.save_handle(owner, 'alice')
            monkeypatch.setenv('OAKGATE_CLEAR_RECEIVE_ENABLED', 'false')
            receiver = EcashReceiver(wallets)
            assert 'clear' not in receiver.discovery('alice')
            receiver.due()
            await receiver.process(owner)
            backend.receive_clear.assert_not_awaited()
            backend.receive_ecash.assert_awaited_once()
    asyncio.run(run())


def test_acorn_receipt_retry_does_not_duplicate_accepted_receipts(monkeypatch):
    async def run():
        backend = AcornBackend()
        pending = [{'event_id':'a'}, {'event_id':'b'}]
        attempts = []
        async def accept(event_id):
            attempts.append(event_id)
            if event_id == 'a': raise RuntimeError('mint offline')
            pending[:] = [row for row in pending if row['event_id'] != event_id]
            return {'accepted': True}
        wallet = SimpleNamespace(sweep_clear_transfers=AsyncMock(),
            get_clear_receipts=AsyncMock(side_effect=lambda **kwargs: list(pending)),
            accept_pending_clear_receipt=AsyncMock(side_effect=accept))
        monkeypatch.setattr(backend, 'wallet', lambda material: wallet)
        monkeypatch.setattr('app.wallets.time.time', lambda: 0)
        result = await backend.receive_clear({'relay': 'wss://relay.example'})
        assert result['accepted_count'] == 1
        await backend.receive_clear({'relay': 'wss://relay.example'})
        assert attempts.count('b') == 1 and attempts.count('a') == 2
        wallet.get_clear_receipts.assert_awaited_with(status='pending')
        wallet.sweep_clear_transfers.assert_awaited_with(relays=['wss://relay.example'], limit=100, max_pages=10)
    asyncio.run(run())


def test_clear_send_delegates_exact_asset_to_acorn(monkeypatch):
    async def run():
        backend = AcornBackend()
        wallet = SimpleNamespace(send_clear_transfer=AsyncMock(return_value={'status':'OK','event_id':'id'}))
        monkeypatch.setattr(backend, 'wallet', lambda material: wallet)
        await backend.send_payment({}, {'route':'clear','mint':MINT,'unit':UNIT,'amount':6,
            'pubkey':'ab'*32,'relay':'wss://relay.example','comment':'Thanks'})
        wallet.send_clear_transfer.assert_awaited_once_with(amount=6,recipient='ab'*32,mint=MINT,unit=UNIT,
            relay='wss://relay.example',comment='Thanks')
    asyncio.run(run())


def test_asset_labels_cannot_merge_different_issuers():
    rows = [{'mint':mint,'unit':UNIT,'amount':5,'display_name':'Same name','display_unit':'credits'}
            for mint in (MINT, 'https://other.example')]
    assets = payment_assets(rows)
    assert len(assets) == 2 and assets[0]['id'] != assets[1]['id']


@pytest.mark.parametrize("supported", [True, False])
def test_clear_uses_wallet_directory_without_social_lookup(tmp_path, supported):
    from acorn.safebox_discovery import build_safebox_document, parse_safebox_document
    from stroma import Keys
    async def run():
        client, wallets, backend, owner, service, fetch = await clear_setup(tmp_path)
        async with aclosing(client):
            address = "alice@other.example"
            pubkey = Keys(priv_k="01" * 32).public_key_hex()
            destination = parse_safebox_document(build_safebox_document(address, pubkey, [wallets.default_relay], clear=True, clear_units=[UNIT if supported else "other-unit"]), address)
            service.discover = AsyncMock(return_value=destination)
            if supported:
                payment = await service.prepare(owner, address, "6", "", asset=asset_id(MINT, UNIT))
                assert payment["pubkey"] == pubkey
                assert payment["route"] == "clear"
                await service.send(owner, payment["id"])
                backend.send_payment.assert_awaited_once()
            else:
                with pytest.raises(ValueError):
                    await service.prepare(owner, address, "6", "", asset=asset_id(MINT, UNIT))
                backend.send_payment.assert_not_awaited()
            fetch.assert_not_awaited()
    asyncio.run(run())
