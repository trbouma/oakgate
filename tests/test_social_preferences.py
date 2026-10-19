import asyncio
from contextlib import aclosing
from unittest.mock import AsyncMock

import pytest
from cryptography.fernet import Fernet
from stroma import Keys

from app.custody import CustodyStore, HandleTaken
from app.identity import social_public_identity
from app.send import SendService
from test_wallets import setup, login, form
from test_ecash import ready

SOCIAL = Keys(priv_k='02'*32)
WALLET = Keys(priv_k='01'*32)


@pytest.mark.parametrize('value', ['nsec1secret', 'ab'*32, 'npub1bad', '<script>', 'npub1'+'q'*58, 'npub1'+'x'*100])
def test_rejects_invalid_or_private_input(value):
    with pytest.raises(ValueError, match='public npub'):
        social_public_identity(value)


def test_public_validation_and_storage_are_separate_and_atomic(tmp_path):
    key = Fernet.generate_key()
    store = CustodyStore(tmp_path, key)
    store.save_handle('alice', 'Alice', social_npub=' '+SOCIAL.public_key_bech32().upper()+' ')
    assert CustodyStore(tmp_path, key).social_npub('alice') == SOCIAL.public_key_bech32()
    assert store.social_npub('bob') == ''
    store.save_handle('bob', 'Bob')
    with pytest.raises(HandleTaken):
        store.save_handle('bob', 'alice', social_npub=SOCIAL.public_key_bech32())
    assert store.social_npub('bob') == ''
    with pytest.raises(ValueError):
        store.save_handle('alice', 'Changed', social_npub='nsec1secret')
    assert store.preference('alice') == 'Alice'
    store.save_handle('alice', 'Renamed')
    assert store.social_npub('alice') == SOCIAL.public_key_bech32()
    store.save_handle('alice', 'Renamed', social_npub='')
    assert store.social_npub('alice') == ''
    assert store.get('alice') is None  # A public preference cannot create custody.


def test_social_preference_cannot_retarget_wallet_or_local_payment(tmp_path):
    async def run():
        client, sessions, wallets, backend = setup(tmp_path)
        ready(backend)
        backend.public_identity = lambda material: {'hex': WALLET.public_key_hex()}
        backend.direct_sending_available = True
        backend.send_payment = AsyncMock(return_value={})
        async with aclosing(client):
            assert (await client.get('/account/preferences')).status_code == 303
            owner = await login(client, sessions)
            await client.post('/account/acorn/create', data=form())
            original_wallet = wallets.store.get(owner)
            wallets.store.save_handle(owner, 'alice')
            before = (await client.get('/.well-known/safebox.json?name=alice')).json()
            data = form(handle='alice', social_npub=SOCIAL.public_key_bech32())
            assert (await client.post('/account/preferences', data={**data,'csrf':'bad'})).status_code == 403
            assert wallets.store.social_npub(owner) == ''
            assert (await client.post('/account/preferences', data=data, headers={'origin':'https://evil.example'})).status_code == 403
            response = await client.post('/account/preferences', data=data)
            assert response.status_code == 200 and SOCIAL.public_key_bech32() in response.text
            assert wallets.store.get(owner) == original_wallet
            assert (await client.get('/.well-known/safebox.json?name=alice')).json() == before
            social = await client.get('/.well-known/nostr.json?name=Alice')
            assert social.json() == {'names': {'alice': SOCIAL.public_key_hex()}}
            assert social.headers['access-control-allow-origin'] == '*'
            assert social.headers['cache-control'] == 'no-store'
            receiver = client._transport.app.state.ecash
            sender = SendService(wallets, 'https://oakgate.example', receiver)
            payment = await sender.prepare(owner, 'alice@oakgate.example', '1', '')
            assert payment['pubkey'] == WALLET.public_key_hex() and payment['route'] == 'ecash'
            assert payment['discovery_source'] == 'local-wallet'
            invalid = await client.post('/account/preferences', data=form(handle='Changed',social_npub='nsec1secret'))
            assert invalid.status_code == 400 and 'nsec1secret' not in invalid.text
            assert wallets.store.preference(owner) == 'alice'
            other = await login(client, sessions, sub='other')
            assert SOCIAL.public_key_bech32() not in (await client.get('/account/preferences')).text
            await client.post('/account/preferences', data=form(handle='bob',social_npub=WALLET.public_key_bech32()))
            assert wallets.store.social_npub(owner) == SOCIAL.public_key_bech32()
            assert wallets.store.social_npub(other) == WALLET.public_key_bech32()
            client.cookies.clear()
            assert (await client.get('/.well-known/nostr.json?name=alice')).json() == social.json()
            # A retired handle cannot keep advertising a social identity.
            wallets.store.save_handle(owner, '')
            assert (await client.get('/.well-known/nostr.json?name=alice')).status_code == 404
            wallets.store.save_handle(owner, 'alice', social_npub='')
            restored = (await client.get('/.well-known/nostr.json?name=alice')).json()
            assert restored['names']['alice'] == WALLET.public_key_hex()
            assert (await client.get('/.well-known/safebox.json?name=alice')).json() == before
    asyncio.run(run())
