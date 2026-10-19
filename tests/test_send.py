import asyncio
from contextlib import aclosing
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.send import SendService, public_json
from acorn.safebox_discovery import SafeboxNotFound
from test_wallets import setup, login, form
from test_ecash import ready


async def prepared(tmp_path):
    client, sessions, wallets, backend = setup(tmp_path)
    ready(backend)
    backend.mint = 'https://mint.safebox.dev'
    backend.direct_sending_available = True
    backend.send_payment = AsyncMock(return_value={})
    owner = await login(client, sessions)
    await client.post('/account/acorn/create', data=form())
    payload = {'names': {'alice': 'ab'*32}, 'relays': {'ab'*32: [wallets.default_relay]}}
    fetch = AsyncMock(return_value=payload)
    async def discover(address):
        if fetch.side_effect is not None or address.endswith(('@ordinary.example', '@primal.net')):
            raise SafeboxNotFound('No wallet directory')
        payload = fetch.return_value
        key = payload['names']['alice']
        caps = {'acorn-ecash-transfer': {'transports':['nip59'], 'kinds':[7378], 'units':['sat']}}
        clear = payload.get('clear', {}).get('alice')
        if clear and 'clear-token-transfer' in clear.get('protocols', []):
            caps['clear-token-transfer'] = {k:v for k,v in clear.items() if k != 'protocols'}
        def supports(capability, unit):
            descriptor = caps.get(capability)
            return bool(descriptor and (not descriptor.get('units') or unit in descriptor['units']))
        return SimpleNamespace(pubkey=key, relays=payload['relays'][key],
                               capabilities=caps, source='safebox-v1', supports=supports)
    service = SendService(wallets, 'https://oakgate.example', None, fetch,
                          discover=AsyncMock(side_effect=discover))
    return client, sessions, wallets, backend, owner, service, fetch


def test_direct_send_is_reviewed_and_one_shot(tmp_path):
    async def run():
        client, sessions, wallets, backend, owner, service, fetch = await prepared(tmp_path)
        async with aclosing(client):
            payment = await service.prepare(owner, 'alice@safebox.dev', '42', 'hello')
            assert payment['route'] == 'ecash'
            backend.send_payment.assert_not_awaited()
            assert (await service.send(owner, payment['id']))['state'] == 'sent'
            assert (await service.send(owner, payment['id']))['state'] == 'sent'
            backend.send_payment.assert_awaited_once()
            assert fetch.await_count == 0  # Direct sends use only wallet discovery.
            with pytest.raises(ValueError):
                await service.send('another-owner', payment['id'])
            assert wallets.store.acquire(owner)  # No stale owner lease.
    asyncio.run(run())


def test_uncertain_send_never_retries_or_falls_back(tmp_path):
    async def run():
        client, sessions, wallets, backend, owner, service, fetch = await prepared(tmp_path)
        async with aclosing(client):
            first = await service.prepare(owner, 'alice@safebox.dev', '42', '')
            second = await service.prepare(owner, 'alice@safebox.dev', '43', '')
            backend.send_payment.side_effect = TimeoutError('SECRET TOKEN')
            assert (await service.send(owner, first['id']))['state'] == 'unknown'
            assert (await service.send(owner, first['id']))['state'] == 'unknown'
            with pytest.raises(ValueError):
                await service.send(owner, second['id'])
            backend.send_payment.assert_awaited_once()
            assert fetch.await_count == 0
    asyncio.run(run())


def test_lnurl_fallback_checks_invoice_and_metadata(tmp_path, monkeypatch):
    async def run():
        client, sessions, wallets, backend, owner, service, fetch = await prepared(tmp_path)
        async with aclosing(client):
            fetch.side_effect = [
                {'tag': 'payRequest', 'minSendable': 1000, 'maxSendable': 100000,
                 'metadata': '[]', 'callback': 'https://pay.example/callback?token=x'},
                {'pr': 'invoice'} ]
            monkeypatch.setattr('app.send.bolt11.decode', lambda value: SimpleNamespace(
                currency='bc', amount_msat=42000, date=int(time.time()), expiry=300, description_hash=None))
            payment = await service.prepare(owner, 'alice@other.example', '42', '')
            assert payment['route'] == 'lightning'
            assert fetch.await_args.args[1] == {'token': 'x', 'amount': '42000'}
            await service.send(owner, payment['id'])
            assert backend.send_payment.await_args.args[1]['invoice'] == 'invoice'
            fetch.side_effect = [
                {'tag': 'payRequest', 'minSendable': 1000, 'maxSendable': 100000,
                 'metadata': '[]', 'callback': 'https://pay.example'}, {'pr': 'invoice'} ]
            monkeypatch.setattr('app.send.bolt11.decode', lambda value: SimpleNamespace(
                currency='bc', amount_msat=43000, date=int(time.time()), expiry=300, description_hash=None))
            with pytest.raises(ValueError, match='amount'):
                await service.prepare(owner, 'alice@other.example', '42', '')
    asyncio.run(run())


def test_generic_nip05_is_not_proof_of_acorn_support(tmp_path):
    async def run():
        client, sessions, wallets, backend, owner, service, fetch = await prepared(tmp_path)
        async with aclosing(client):
            with pytest.raises(ValueError):
                await service.prepare(owner, 'alice@ordinary.example', '42', '')
            assert fetch.await_count == 1  # Only LNURL; unlisted NIP-05 is never consulted.
            assert '/.well-known/lnurlp/' in fetch.await_args.args[0]
            backend.send_payment.assert_not_awaited()
    asyncio.run(run())


def test_route_requires_csrf_and_owner_confirmation(tmp_path):
    async def run():
        client, sessions, wallets, backend, owner, service, fetch = await prepared(tmp_path)
        async with aclosing(client):
            # Use the service attached to the app via the ASGI transport.
            client._transport.app.state.send = service
            assert (await client.post('/account/send', data={'amount': '42'})).status_code == 403
            response = await client.post('/account/send', data=form(address='alice@safebox.dev', amount='42', comment=''))
            assert response.status_code == 303
            url = response.headers['location']
            page = await client.get(url)
            assert 'Confirm payment' in page.text and 'Direct ecash' in page.text
            assert 'SECRET' not in page.text
            payment_id = url.split('=')[1]
            await login(client, sessions, sub='other')
            assert (await client.get(url)).status_code == 404
            response = await client.post('/account/send/confirm', data=form(payment=payment_id))
            assert response.status_code == 400
            backend.send_payment.assert_not_awaited()
    asyncio.run(run())


def test_public_fetch_rejects_private_dns(monkeypatch):
    async def run():
        monkeypatch.setattr(asyncio.get_running_loop(), 'getaddrinfo', AsyncMock(
            return_value=[(2, 1, 6, '', ('127.0.0.1', 443))]))
        with pytest.raises(ValueError, match='public'):
            await public_json('https://recipient.example/.well-known/nostr.json')
        with pytest.raises(ValueError):
            await public_json('http://recipient.example')
    asyncio.run(run())


def test_public_fetch_pins_address_and_preserves_tls_hostname(monkeypatch):
    async def run():
        monkeypatch.setattr(asyncio.get_running_loop(), 'getaddrinfo', AsyncMock(
            return_value=[(2, 1, 6, '', ('93.184.216.34', 443))]))
        original = httpx.AsyncClient
        def respond(request):
            assert request.url.host == '93.184.216.34'
            assert request.headers['host'] == 'recipient.example'
            assert request.extensions['sni_hostname'] == 'recipient.example'
            return httpx.Response(200, json={'names': {}})
        monkeypatch.setattr('app.send.httpx.AsyncClient', lambda **kwargs: original(
            **kwargs, transport=httpx.MockTransport(respond)))
        assert await public_json('https://recipient.example/.well-known/nostr.json') == {'names': {}}
    asyncio.run(run())


def test_direct_capability_needs_no_bootstrap_mint_match(tmp_path):
    async def run():
        client, sessions, wallets, backend, owner, service, fetch = await prepared(tmp_path)
        async with aclosing(client):
            fetch.return_value = {
                'names': {'alice': 'ab' * 32},
                'relays': {'ab' * 32: [wallets.default_relay]},
                'safebox': {'alice': {'protocols': ['acorn-ecash-transfer']}}}
            payment = await service.prepare(owner, 'alice@another-safebox.example', '42', '')
            assert payment['route'] == 'ecash'
            assert 'mints' not in payment
            assert fetch.await_count == 0
    asyncio.run(run())


def test_adapter_leaves_mint_selection_to_acorn(monkeypatch):
    from app.wallets import AcornBackend
    async def run():
        backend = AcornBackend()
        wallet = SimpleNamespace(load_data=AsyncMock(),
            send_ecash_transfer=AsyncMock(return_value={'status': 'OK', 'event_id': 'event'}))
        monkeypatch.setattr(backend, 'wallet', lambda material: wallet)
        await backend.send_payment({}, {'route': 'ecash', 'amount': 42, 'pubkey': 'ab'*32,
                                        'relay': 'wss://relay.example', 'comment': 'hello', 'id': 'attempt'})
        wallet.send_ecash_transfer.assert_awaited_once_with(
            amount=42, recipient='ab'*32, relay='wss://relay.example', comment='hello', nonce='attempt')
    asyncio.run(run())


def test_primal_style_unbound_hash_can_be_reviewed(tmp_path, monkeypatch):
    async def run():
        client, sessions, wallets, backend, owner, service, fetch = await prepared(tmp_path)
        async with aclosing(client):
            fetch.side_effect = [
                {'tag': 'payRequest', 'minSendable': 1000, 'maxSendable': 11000000000,
                 'metadata': '[]', 'callback': 'https://primal.net/lnurlp/trbouma/callback'},
                {'pr': 'invoice'}]
            monkeypatch.setattr('app.send.bolt11.decode', lambda value: SimpleNamespace(
                currency='bc', amount_msat=42000, date=int(time.time()), expiry=300, description_hash='ab'*32))
            client._transport.app.state.send = service
            response = await client.post('/account/send', data=form(address='trbouma@primal.net', amount='42'))
            assert response.status_code == 303
            page = await client.get(response.headers['location'])
            assert 'Confirm payment' in page.text and 'Lightning' in page.text
            backend.send_payment.assert_not_awaited()
    asyncio.run(run())


@pytest.mark.parametrize('failure', [TimeoutError('SECRET'), ValueError('SECRET decoder input'), httpx.ConnectError('SECRET')])
def test_prepare_error_keeps_session_and_form_without_provider_secrets(tmp_path, failure):
    async def run():
        client, sessions, wallets, backend, owner, service, fetch = await prepared(tmp_path)
        async with aclosing(client):
            fetch.side_effect = failure
            client._transport.app.state.send = service
            response = await client.post('/account/send', data=form(address='trbouma@primal.net', amount='42', comment='hello'))
            assert response.status_code == 400
            assert 'Account navigation' in response.text and 'No payment was sent' in response.text
            assert 'value="trbouma@primal.net"' in response.text and 'value="42"' in response.text
            assert 'value="hello"' in response.text and 'SECRET' not in response.text
            assert 'Let&#39;s try that again' not in response.text
            assert (await client.get('/account/send')).status_code == 200
            backend.send_payment.assert_not_awaited()
    asyncio.run(run())


def test_website_address_gets_clear_guidance(tmp_path):
    async def run():
        client, sessions, wallets, backend, owner, service, fetch = await prepared(tmp_path)
        async with aclosing(client):
            client._transport.app.state.send = service
            response = await client.post('/account/send', data=form(address='trbouma.shakepay.me', amount='42'))
            assert response.status_code == 400 and 'Website addresses are not supported here' in response.text
            assert 'Account navigation' in response.text
            fetch.assert_not_awaited()
    asyncio.run(run())


@pytest.mark.parametrize('advertised', [{}, {'commentAllowed': 0}, {'commentAllowed': None}, {'commentAllowed': 100}])
def test_provider_comments_follow_advertised_support(tmp_path, monkeypatch, advertised):
    async def run():
        client, sessions, wallets, backend, owner, service, fetch = await prepared(tmp_path)
        async with aclosing(client):
            fetch.side_effect = [
                {'tag': 'payRequest', 'minSendable': 1000, 'maxSendable': 100000,
                 'metadata': '[]', 'callback': 'https://pay.example/callback?token=x&comment=old', **advertised},
                {'pr': 'invoice'}]
            monkeypatch.setattr('app.send.bolt11.decode', lambda value: SimpleNamespace(
                currency='bc', amount_msat=42000, date=int(time.time()), expiry=300))
            payment = await service.prepare(owner, 'alice@other.example', '42', 'hello')
            assert payment['route'] == 'lightning'
            params = fetch.await_args.args[1]
            assert params['amount'] == '42000' and params['token'] == 'x'
            if advertised.get('commentAllowed'):
                assert params['comment'] == 'hello'
            else:
                assert 'comment' not in params
            backend.send_payment.assert_not_awaited()
    asyncio.run(run())


def test_wallet_directory_pins_recipient_for_confirmation(tmp_path):
    from acorn.safebox_discovery import build_safebox_document, parse_safebox_document
    from stroma import Keys
    async def run():
        client, sessions, wallets, backend, owner, service, fetch = await prepared(tmp_path)
        async with aclosing(client):
            key = Keys(priv_k="01" * 32).public_key_hex()
            address = "alice@safebox.dev"
            destination = parse_safebox_document(build_safebox_document(address, key, [wallets.default_relay]), address)
            service.discover = AsyncMock(return_value=destination)
            payment = await service.prepare(owner, address, "42", "")
            assert payment["pubkey"] == key
            assert payment["discovery_source"] == "safebox-v1"
            fetch.assert_not_awaited()
            service.discover.side_effect = AssertionError("Confirmation must use the prepared recipient")
            await service.send(owner, payment["id"])
            assert backend.send_payment.await_args.args[1]["pubkey"] == key
            service.discover.assert_awaited_once()
    asyncio.run(run())


@pytest.mark.parametrize("reason", ["invalid schema", "unknown version", "timeout", "HTTP 410", "HTTP 429", "HTTP 503"])
def test_wallet_directory_errors_stop_before_payment(tmp_path, reason):
    from acorn.safebox_discovery import SafeboxDiscoveryError
    async def run():
        client, sessions, wallets, backend, owner, service, fetch = await prepared(tmp_path)
        async with aclosing(client):
            service.discover = AsyncMock(side_effect=SafeboxDiscoveryError(reason))
            with pytest.raises(ValueError, match="No payment was sent"):
                await service.prepare(owner, "alice@safebox.dev", "42", "")
            fetch.assert_not_awaited()
            backend.send_payment.assert_not_awaited()
    asyncio.run(run())


@pytest.mark.parametrize('source', ['legacy-nip05', None])
def test_old_prepared_wallet_payment_is_not_sent(tmp_path, source):
    import json
    from contextlib import closing
    async def run():
        client, sessions, wallets, backend, owner, service, fetch = await prepared(tmp_path)
        async with aclosing(client):
            payment = await service.prepare(owner, 'alice@safebox.dev', '42', '')
            payment['discovery_source'] = source
            with closing(wallets.store.connect()) as db, db:
                db.execute('UPDATE outgoing_payments SET encrypted=? WHERE id=?',
                    (wallets.store.cipher.encrypt(json.dumps(payment).encode()), payment['id']))
            with pytest.raises(ValueError, match='retired wallet discovery'):
                await service.send(owner, payment['id'])
            backend.send_payment.assert_not_awaited()
            assert service.get(owner, payment['id'])['state'] == 'prepared'
    asyncio.run(run())


def test_404_never_uses_social_directory_even_with_old_configuration(tmp_path, monkeypatch):
    monkeypatch.setenv('OAKGATE_SAFEBOX_DOMAINS','safebox.dev')
    async def run():
        client, sessions, wallets, backend, owner, service, fetch = await prepared(tmp_path)
        async with aclosing(client):
            service.discover = AsyncMock(side_effect=SafeboxNotFound('404'))
            # A social directory response is deliberately unusable as LNURL metadata.
            with pytest.raises(ValueError):
                await service.prepare(owner,'alice@safebox.dev','42','')
            assert fetch.await_count == 1
            assert fetch.await_args.args[0].endswith('/.well-known/lnurlp/alice')
            backend.send_payment.assert_not_awaited()
    asyncio.run(run())
