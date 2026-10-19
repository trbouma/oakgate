import asyncio
import re
from unittest.mock import AsyncMock
import pytest
from stroma import Keys
WALLET_KEY = Keys(priv_k="01"*32).public_key_hex()
from test_wallets import setup, login, form
from app.wallets import AcornBackend


def submission(page):
    return re.search(r'name="submission" value="([^"]+)"', page.text).group(1)


def test_wallet_messages_auth_csrf_and_replay(tmp_path):
    async def run():
        client, sessions, service, backend = setup(tmp_path)
        backend.messaging_available = True
        backend.wallet_messages = AsyncMock(return_value=[{'sender':'a'*64,'claimed_sender':'alice@example.com',
            'verification':'mismatch','created_at':1,'content':'<script>private message</script>'}])
        backend.send_wallet_message = AsyncMock(return_value={'status':'published'})
        backend.public_identity = lambda material: {'hex':WALLET_KEY}
        async with client:
            assert (await client.get('/account/messages')).status_code == 303
            owner = await login(client,sessions)
            assert 'Connect or create' in (await client.get('/account/messages')).text
            await client.post('/account/acorn/create',data=form())
            service.store.save_handle(owner,'alice')
            page = await client.get('/account/messages')
            assert page.headers['cache-control'] == 'no-store'
            assert '&lt;script&gt;' in page.text and '<script>private' not in page.text
            assert 'Address does not match sender wallet' in page.text
            data = form(recipient='alice@oakgate.example',message='hello',submission=submission(page))
            assert (await client.post('/account/messages',data={**data,'csrf':'bad'})).status_code == 403
            result = await client.post('/account/messages',data=data)
            assert result.status_code == 303
            args = backend.send_wallet_message.await_args.args
            assert args[1]['pubkey'] == WALLET_KEY and args[2:] == ('hello','alice@oakgate.example')
            assert (await client.post('/account/messages',data=data)).status_code == 409
            assert backend.send_wallet_message.await_count == 1
            directory = (await client.get('/.well-known/safebox.json?name=alice')).json()
            assert directory['capabilities']['safebox-wallet-message']['kinds'] == [14]
            await login(client,sessions,sub='other')
            assert 'Connect or create' in (await client.get('/account/messages')).text
    asyncio.run(run())


def test_uncertain_send_consumes_form_and_hides_errors(tmp_path):
    async def run():
        client,sessions,service,backend = setup(tmp_path)
        backend.messaging_available = True
        backend.wallet_messages = AsyncMock(return_value=[])
        backend.send_wallet_message = AsyncMock(side_effect=RuntimeError('SECRET-NSEC'))
        backend.public_identity = lambda m: {'hex':WALLET_KEY}
        async with client:
            owner = await login(client,sessions)
            await client.post('/account/acorn/create',data=form())
            service.store.save_handle(owner,'alice')
            data = form(recipient='alice@oakgate.example',message='hello',submission=submission(await client.get('/account/messages')))
            response = await client.post('/account/messages',data=data)
            assert response.status_code == 502 and 'SECRET-NSEC' not in response.text
            assert (await client.post('/account/messages',data=data)).status_code == 409
            assert backend.send_wallet_message.await_count == 1
    asyncio.run(run())


def test_backend_only_delegates_to_acorn():
    async def run():
        backend=AcornBackend()
        wallet=type('Wallet',(),{})()
        wallet.get_wallet_messages=AsyncMock(return_value=[])
        wallet.send_wallet_message=AsyncMock(return_value={'status':'published'})
        backend.wallet=lambda material:wallet
        resolve=AsyncMock()
        await backend.wallet_messages({},resolve)
        wallet.get_wallet_messages.assert_awaited_once_with(limit=50,resolver=resolve)
        await backend.send_wallet_message({}, {'pubkey':'a'*64,'relays':['wss://relay.example']},'hello','me@example.com')
        wallet.send_wallet_message.assert_awaited_once_with('a'*64,'hello',relays=['wss://relay.example'],sender='me@example.com')
    asyncio.run(run())


def test_missing_dependency_does_not_advertise_messages(tmp_path):
    async def run():
        client,sessions,service,backend=setup(tmp_path)
        async with client:
            await login(client,sessions)
            await client.post('/account/acorn/create',data=form())
            assert 'requires the updated' in (await client.get('/account/messages')).text
    asyncio.run(run())


def test_external_resolution_uses_acorn_wallet_directory_and_approved_relays(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace
    from app.messages import resolver
    async def run():
        client, sessions, service, backend = setup(tmp_path)
        lookup = AsyncMock(return_value={'pubkey': WALLET_KEY, 'relays': [service.default_relay, 'wss://unapproved.example']})
        monkeypatch.setitem(sys.modules, 'acorn.wallet_messages', SimpleNamespace(resolve_wallet_message=lookup))
        request = SimpleNamespace(app=client._transport.app)
        result = await resolver(request)('alice@other.example')
        assert result == {'pubkey': WALLET_KEY, 'relays': [service.default_relay]}
        lookup.assert_awaited_once_with('alice@other.example')
        lookup.return_value = {'pubkey': WALLET_KEY, 'relays': ['wss://unapproved.example']}
        with pytest.raises(ValueError, match='No approved'):
            await resolver(request)('alice@other.example')
        lookup.side_effect = ValueError('No wallet directory')
        with pytest.raises(ValueError, match='No wallet directory'):
            await resolver(request)('alice@other.example')
        await client.aclose()
    asyncio.run(run())
