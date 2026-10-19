import asyncio
from contextlib import aclosing
import builtins

import pytest
from stroma import Keys
from acorn.safebox_discovery import parse_safebox_document, CASH, CLEAR
from test_wallets import setup, login, form
from test_ecash import ready


async def directory_setup(tmp_path):
    client, sessions, service, backend = setup(tmp_path)
    ready(backend)
    pubkey = Keys(priv_k='01'*32).public_key_hex()
    backend.public_identity = lambda material: {'hex': pubkey}
    owner = await login(client, sessions)
    await client.post('/account/acorn/create', data=form())
    service.store.save_handle(owner, 'alice')
    client.cookies.clear()
    return client, service, backend, owner, pubkey


def test_dual_publication_signed_out_and_retirement(tmp_path):
    async def run():
        client, service, backend, owner, pubkey = await directory_setup(tmp_path)
        async with aclosing(client):
            before = (await client.get('/.well-known/nostr.json?name=alice')).json()
            response = await client.get('/.well-known/safebox.json?name=Alice', headers={'host':'other.example'})
            assert response.status_code == 200
            result = parse_safebox_document(response.json(), 'alice@oakgate.example')
            assert result.pubkey == pubkey and result.supports(CASH, 'sat')
            assert not result.supports(CLEAR) and not result.supports('safebox-wallet-message')
            for key, value in [('access-control-allow-origin','*'), ('cache-control','no-store'), ('x-content-type-options','nosniff')]:
                assert response.headers[key] == value
            assert all(secret not in response.text for secret in ('SECRET', 'owner', 'phrase', 'nsec'))
            assert (await client.get('/.well-known/nostr.json?name=alice')).json() == before
            service.store.save_handle(owner, '')
            assert (await client.get('/.well-known/safebox.json?name=alice')).status_code == 404
    asyncio.run(run())


@pytest.mark.parametrize('query', ['', '?name=alice&name=bob', '?name=', '?name=a%40b', '?name='+'x'*65])
def test_bad_name_is_400(tmp_path, query):
    async def run():
        client, *_ = await directory_setup(tmp_path)
        async with aclosing(client):
            response = await client.get('/.well-known/safebox.json'+query)
            assert response.status_code == 400 and response.json() == {'error':'invalid_name'}
    asyncio.run(run())


def test_capability_gates_and_invalid_config(tmp_path):
    async def run():
        client, service, backend, owner, pubkey = await directory_setup(tmp_path)
        async with aclosing(client):
            receiver = client._transport.app.state.ecash
            backend.clear_receiving_available = True
            result = (await client.get('/.well-known/safebox.json?name=alice')).json()
            assert parse_safebox_document(result, 'alice@oakgate.example').supports(CLEAR, 'ANY')
            assert 'mints' not in str(result)
            receiver.enabled = False
            assert (await client.get('/.well-known/safebox.json?name=alice')).status_code == 404
            receiver.enabled = True
            backend.public_identity = lambda material: {'hex':'ff'*32}
            response = await client.get('/.well-known/safebox.json?name=alice')
            assert response.status_code == 503 and response.json() == {'error':'unavailable'}
    asyncio.run(run())


def test_old_acorn_fails_new_endpoint_only(tmp_path, monkeypatch):
    async def run():
        client, *_ = await directory_setup(tmp_path)
        real_import = builtins.__import__
        def old_import(name, *args, **kwargs):
            if name == 'acorn.safebox_discovery':
                raise ModuleNotFoundError(name)
            return real_import(name, *args, **kwargs)
        monkeypatch.setattr(builtins, '__import__', old_import)
        async with aclosing(client):
            assert (await client.get('/.well-known/safebox.json?name=alice')).status_code == 503
            assert (await client.get('/.well-known/nostr.json?name=alice')).status_code == 200
    asyncio.run(run())


def test_wallet_directory_does_not_consume_social_directory(tmp_path, monkeypatch):
    async def run():
        client, service, backend, owner, pubkey = await directory_setup(tmp_path)
        async with aclosing(client):
            receiver = client._transport.app.state.ecash
            social_key = Keys(priv_k='02'*32).public_key_hex()
            monkeypatch.setattr(receiver, 'discovery', lambda name: {'names': {'alice': social_key}})
            assert (await client.get('/.well-known/nostr.json?name=alice')).json()['names']['alice'] == social_key
            result = (await client.get('/.well-known/safebox.json?name=alice')).json()
            assert result['pubkey'] == pubkey and pubkey != social_key
    asyncio.run(run())
