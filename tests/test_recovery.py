import asyncio
from contextlib import aclosing
import json
import re
from html import unescape
import time
from urllib.parse import parse_qs, urlsplit

import pytest
from cryptography.fernet import Fernet
from acorn.acorn import Acorn
from app.custody import CustodyStore, identity_key
from app.sessions import record_key
from app.wallets import WalletService
from test_auth import setup, begin, signing_key


async def connected(tmp_path, signing_key, legacy=False):
    client, identity, store, provider = setup(signing_key)
    state = await begin(client, identity)
    await client.get('/auth/callback', params={'state': state, 'code': 'initial'})
    sid = client.cookies.get('__Host-oakgate_session')
    session = await store.get(record_key('session', sid))
    custody = CustodyStore(tmp_path, Fernet.generate_key())
    wallets = WalletService(custody)
    material = Acorn.generate_recovery_material()
    if legacy: material = Acorn.recover_material(material['phrase'], legacy=True)
    material['relay'] = wallets.default_relay
    custody.insert(identity_key(session['user']), material, 'active')
    client._transport.app.state.wallets = wallets
    return client, identity, store, session, material, wallets


async def verify(client, identity, session):
    response = await client.post('/account/recovery/verify', data={'csrf': session['csrf']})
    assert response.status_code == 200
    identity.authorization = parse_qs(urlsplit(unescape(re.search(r'id="recovery-authorize" href="([^"]+)"', response.text)[1])).query)
    assert identity.authorization['prompt'] == ['login']
    assert identity.authorization['max_age'] == ['0']
    return await client.get('/auth/callback', params={'state': identity.authorization['state'][0], 'code': 'reauth'})


def form(session):
    return {'csrf': session['csrf'], 'acknowledge': 'yes'}


@pytest.mark.parametrize('legacy', [False, True])
def test_one_time_reveal_and_verified_recovery(tmp_path, signing_key, legacy):
    async def run():
        client, identity, store, session, material, wallets = await connected(tmp_path, signing_key, legacy)
        async with aclosing(client):
            assert material['phrase'] not in (await client.get('/account/recovery')).text
            assert (await client.post('/account/recovery/reveal', data=form(session))).status_code == 403
            identity.changes['auth_time'] = int(time.time())
            assert (await verify(client, identity, session)).headers['location'] == '/account/recovery'
            page = await client.get('/account/recovery')
            assert 'Reveal recovery information' in page.text and material['phrase'] not in page.text
            assert material['phrase'] not in json.dumps(store.records)
            assert (await client.post('/account/recovery/reveal', data={'csrf':'bad','acknowledge':'yes'})).status_code == 403
            assert (await client.post('/account/recovery/reveal', data={'csrf':session['csrf']})).status_code == 400
            page = await client.post('/account/recovery/reveal', data=form(session))
            assert page.status_code == 200
            assert material['phrase'] in page.text and material['relay'] in page.text
            assert ('Legacy key derivation' if legacy else 'Standard key derivation') in page.text
            assert material['nsec'] not in page.text
            assert 'no-store' in page.headers['cache-control'] and page.headers['x-frame-options'] == 'DENY'
            assert "frame-ancestors 'none'" in page.headers['content-security-policy']
            assert "form-action 'self';" in page.headers['content-security-policy']
            assert (await client.post('/account/recovery/reveal', data=form(session))).status_code == 403
            assert material['phrase'] not in (await client.get('/account/recovery')).text
            assert wallets.store.get(identity_key(session['user']))['status'] == 'active'
    asyncio.run(run())


@pytest.mark.parametrize('change', ['missing', 'old', 'future', 'other-user', 'new-session', 'logout'])
def test_reauth_rejects_stale_identity_or_session(tmp_path, signing_key, change):
    async def run():
        client, identity, store, session, material, wallets = await connected(tmp_path, signing_key)
        async with aclosing(client):
            if change != 'missing': identity.changes['auth_time'] = int(time.time())
            if change == 'old': identity.changes['auth_time'] -= 600
            if change == 'future': identity.changes['auth_time'] += 600
            if change == 'other-user': identity.changes['sub'] = 'another-user'
            response = await client.post('/account/recovery/verify', data={'csrf':session['csrf']})
            identity.authorization = parse_qs(urlsplit(unescape(re.search(r'id="recovery-authorize" href="([^"]+)"', response.text)[1])).query)
            old_sid = client.cookies.get('__Host-oakgate_session')
            if change == 'logout': await store.delete(record_key('session', old_sid))
            if change == 'new-session':
                await store.put(record_key('session','replacement'), session, 600)
                client.cookies.set('__Host-oakgate_session','replacement',domain='oakgate.example',path='/')
            response = await client.get('/auth/callback', params={'state':identity.authorization['state'][0],'code':'reauth'})
            assert response.status_code == 400 and material['phrase'] not in response.text
            response = await client.post('/account/recovery/reveal',data=form(session))
            assert response.status_code in (403,303) and material['phrase'] not in response.text
    asyncio.run(run())


def test_expired_grant_and_mismatched_recovery_fail_closed(tmp_path, signing_key):
    async def run():
        client, identity, store, session, material, wallets = await connected(tmp_path, signing_key)
        async with aclosing(client):
            identity.changes['auth_time'] = int(time.time())
            await verify(client, identity, session)
            for key, (expiry, value) in list(store.records.items()):
                if key.startswith('oakgate:recovery:'): value['expires_at'] = 0
            assert (await client.post('/account/recovery/reveal',data=form(session))).status_code == 403
            await verify(client, identity, session)
            original = wallets.store.get
            def corrupt(owner):
                record = original(owner)
                record['material']['phrase'] = Acorn.generate_recovery_material()['phrase']
                return record
            wallets.store.get = corrupt
            page = await client.post('/account/recovery/reveal',data=form(session))
            assert page.status_code == 503 and material['phrase'] not in page.text
    asyncio.run(run())


def test_csrf_and_cross_origin_cannot_start_recovery(tmp_path, signing_key):
    async def run():
        client, identity, store, session, material, wallets = await connected(tmp_path, signing_key)
        async with aclosing(client):
            assert (await client.post('/account/recovery/verify',data={'csrf':'wrong'})).status_code == 403
            assert (await client.post('/account/recovery/verify',data={'csrf':session['csrf']},headers={'origin':'https://other.example'})).status_code == 403
    asyncio.run(run())


def test_missing_recovery_mode_is_not_guessed(tmp_path, signing_key):
    async def run():
        client, identity, store, session, material, wallets = await connected(tmp_path, signing_key)
        async with aclosing(client):
            del material['legacy']
            with pytest.raises(ValueError, match='incomplete'):
                wallets.recovery_details(material)
    asyncio.run(run())
