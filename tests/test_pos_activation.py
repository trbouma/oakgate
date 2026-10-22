"""Device-proof, owner isolation and restart/replay regression tests. No live wallets."""
import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import html
import json
import re
import subprocess
import time

import httpx
import pytest
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils

from app.custody import CustodyStore
from app.pos_store import POSStore, POSDenied, POSLimited, verify
from pos.config import POSSettings
from pos.main import create_app as create_pos, COOKIE
from test_wallets import setup, login, form


def b64(raw):
    return base64.urlsafe_b64encode(raw).decode().rstrip('=')


def device():
    private = ec.generate_private_key(ec.SECP256R1())
    public = b64(private.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))
    return private, public


def proof(private, challenge):
    signature = private.sign(challenge['message'].encode(), ec.ECDSA(hashes.SHA256()))
    r, s = utils.decode_dss_signature(signature)
    return {'challenge': challenge['challenge'], 'signature': b64(r.to_bytes(32,'big') + s.to_bytes(32,'big'))}


@pytest.fixture
def store(tmp_path):
    custody = CustodyStore(tmp_path, Fernet.generate_key())
    with closing(custody.connect()) as db, db:
        db.execute("INSERT INTO wallets(owner,wallet_id,encrypted,status) VALUES('alice','wallet-a',X'00','active')")
    return POSStore(custody, 'https://pos.example')


def activate(store, key=None, pair=None):
    key = key or store.provision('alice', 'Counter')
    pair = pair or device()
    challenge = store.activation_challenge(key, pair[1])
    session = store.activate(key, pair[1], **proof(pair[0], challenge))['session']
    return key, pair, session


def config(store, session, pair):
    challenge = store.challenge(session, 'config')
    return store.authorized(session, 'config', **proof(pair[0], challenge))


def test_store_contains_only_verifiers_and_public_device_information(store):
    key, pair, session = activate(store)
    assert config(store, session, pair)['scope'] == 'receive-only'
    with closing(store.connect()) as db:
        dump = '\n'.join(db.iterdump())
    assert key.split('.')[-1] not in dump and session not in dump
    assert pair[1] in dump
    listing = store.listing('alice')
    assert listing[0]['status'] == 'Active'
    assert len(listing[0]['fingerprint']) == 64
    assert store.listing('bob') == []
    assert 'verifier' not in listing[0] and 'public_key' not in listing[0]


def test_bound_key_copied_cookie_and_replay_are_rejected(store):
    key, pair, session = activate(store)
    other = device()
    with pytest.raises(POSDenied): store.activation_challenge(key, other[1])
    challenge = store.challenge(session, 'config')
    with pytest.raises(POSDenied): store.authorized(session, 'config', **proof(other[0], challenge))
    valid = proof(pair[0], challenge)
    assert store.authorized(session, 'config', **valid)['name'] == 'Counter'
    with pytest.raises(POSDenied): store.authorized(session, 'config', **valid)
    with pytest.raises(POSDenied): store.challenge(session, 'requests')
    challenge = store.challenge(session, 'config')
    with pytest.raises(POSDenied): store.authorized(session, 'logout', **proof(pair[0], challenge))


def test_concurrent_first_activation_only_one_device_wins(store):
    key = store.provision('alice', 'Counter')
    pairs = [device(), device()]
    challenges = [store.activation_challenge(key, pair[1]) for pair in pairs]
    def attempt(i):
        try:
            return store.activate(key, pairs[i][1], **proof(pairs[i][0], challenges[i]))
        except POSDenied:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, range(2)))
    assert sum(result is not None for result in results) == 1


def test_restart_logout_revocation_wallet_replacement_and_expiry(store):
    key, pair, session = activate(store)
    # New instance retains authority, while consumed challenges stay consumed.
    replacement = POSStore(type('Custody', (), {'connect': staticmethod(store.connect)})(), store.audience)
    assert config(replacement, session, pair)['payments_available'] is False
    challenge = store.challenge(session, 'logout')
    assert store.authorized(session, 'logout', **proof(pair[0], challenge))['status'] == 'signed-out'
    with pytest.raises(POSDenied): config(store, session, pair)
    key, pair, session = activate(store, key, pair)
    with closing(store.connect()) as db, db:
        db.execute("UPDATE wallets SET wallet_id='replacement' WHERE owner='alice'")
    with pytest.raises(POSDenied): config(store, session, pair)
    with closing(store.connect()) as db, db:
        db.execute("UPDATE wallets SET wallet_id='wallet-a' WHERE owner='alice'")
    with pytest.raises(POSDenied): store.revoke('bob', key.split('.')[1])
    store.revoke('alice', key.split('.')[1])
    with pytest.raises(POSDenied): config(store, session, pair)
    with pytest.raises(POSDenied): store.activation_challenge(key, pair[1])
    new = store.provision('alice', 'New')
    with closing(store.connect()) as db, db:
        db.execute('UPDATE pos_terminals SET activation_until=0')
    with pytest.raises(POSDenied): store.activation_challenge(new, pair[1])


def test_challenge_and_session_expiry_fail_closed(store):
    key, pair, session = activate(store)
    challenge = store.challenge(session, 'config')
    with closing(store.connect()) as db, db: db.execute('UPDATE pos_challenges SET expires=0')
    with pytest.raises(POSDenied): store.authorized(session, 'config', **proof(pair[0], challenge))
    with closing(store.connect()) as db, db: db.execute('UPDATE pos_sessions SET expires=0')
    with pytest.raises(POSDenied): store.challenge(session, 'config')


def test_source_and_provisioning_limits(store):
    for _ in range(120): store.limit_source('proxy')
    with pytest.raises(POSLimited): store.limit_source('proxy')
    for i in range(10): store.provision('alice', str(i))
    with pytest.raises(POSLimited): store.provision('alice', 'excess')
    with pytest.raises(POSDenied): store.provision('missing-owner', 'bad')


def test_real_webcrypto_signatures_are_compatible(store):
    key = store.provision('alice', 'WebCrypto')
    # Test keys only. Node uses the same Web Crypto ECDSA P1363 format as browsers.
    code = """
    const {webcrypto} = require('node:crypto');
    (async () => {
      const pair = await webcrypto.subtle.generateKey({name:'ECDSA',namedCurve:'P-256'}, false,['sign','verify']);
      const message = 'oakgate-pos-proof-v1 interoperability';
      const sig = await webcrypto.subtle.sign({name:'ECDSA',hash:'SHA-256'},pair.privateKey,new TextEncoder().encode(message));
      console.log(JSON.stringify({key:Buffer.from(await webcrypto.subtle.exportKey('raw',pair.publicKey)).toString('base64url'),
        signature:Buffer.from(sig).toString('base64url'),message,extractable:pair.privateKey.extractable}));
    })();
    """
    result = subprocess.run(['node', '-e', code], capture_output=True, text=True, check=True)
    value = json.loads(result.stdout)
    assert value['extractable'] is False
    verify(value['key'], value['message'], value['signature'])
    with pytest.raises(POSDenied): verify(value['key'], 'tampered', value['signature'])


def test_owner_provisioning_and_end_to_end_cookie_activation(tmp_path, monkeypatch):
    monkeypatch.setenv('OAKGATE_POS_ENABLED','true')
    monkeypatch.setenv('OAKGATE_POS_PUBLIC_URL','https://pos.example')
    async def run():
        account, sessions, wallets, backend = setup(tmp_path)
        async with account:
            owner = await login(account, sessions)
            assert (await account.post('/account/pos', data=form(name='Counter'))).status_code == 403
            await account.post('/account/acorn/create', data=form())
            assert (await account.post('/account/pos', data=form(name='Counter',csrf='bad'))).status_code == 403
            assert (await account.post('/account/pos', data=form(name='Counter'), headers={'Origin':'https://evil.example'})).status_code == 403
            created = await account.post('/account/pos', data=form(name='Counter'))
            assert created.status_code == 200 and 'no-store' in created.headers['cache-control']
            key = html.unescape(re.search(r'<textarea[^>]+>(.*?)</textarea>', created.text).group(1))
            assert 'Create POS key' in (await account.get('/account/preferences')).text
            assert key not in (await account.get('/account/preferences')).text
            settings = POSSettings(True,'https://pos.example','https://oakgate.example',Fernet.generate_key().decode())
            pos = create_pos(settings, httpx.ASGITransport(account._transport.app))
            async with httpx.AsyncClient(transport=httpx.ASGITransport(pos), base_url='https://pos.example') as browser:
                pair = device()
                data = {'credential':key,'public_key':pair[1]}
                assert (await browser.post('/api/activation-challenges',json=data)).status_code == 403
                headers = {'Origin':'https://pos.example'}
                challenge = (await browser.post('/api/activation-challenges',json=data,headers=headers)).json()
                activated = await browser.post('/api/activate',json={**data,**proof(pair[0],challenge)},headers=headers)
                assert activated.status_code == 200
                assert activated.json() == {'status':'activated'}
                cookie = activated.headers['set-cookie']
                assert all(flag in cookie for flag in ['HttpOnly','Secure','SameSite=strict','Path=/'])
                assert 'Domain=' not in cookie and key not in cookie
                assert (await browser.get('/api/session')).json()['session_present']
                challenge = (await browser.post('/api/challenges',json={'operation':'config'},headers=headers)).json()
                response = await browser.post('/api/config',json=proof(pair[0],challenge),headers=headers)
                assert response.json()['name'] == 'Counter'
                assert set(response.json()) == {'name','fingerprint','scope','payments_available'}
                assert (await browser.post('/api/config',json=proof(pair[0],challenge),headers=headers)).status_code == 403
                for path in ('/account','/account/recovery','/api/requests'):
                    assert (await browser.get(path)).status_code in {404,405}
                # Owner isolation and immediate revocation.
                await login(account,sessions,sub='other')
                assert (await account.post('/account/pos/'+key.split('.')[1]+'/revoke',data=form())).status_code == 403
                await login(account,sessions)
                assert (await account.post('/account/pos/'+key.split('.')[1]+'/revoke',data=form())).status_code == 303
                assert (await browser.post('/api/challenges',json={'operation':'config'},headers=headers)).status_code == 403
                assert (await browser.post('/api/forget',json={},headers=headers)).status_code == 200
                assert not (await browser.get('/api/session')).json()['session_present']
    asyncio.run(run())


def test_challenges_do_not_survive_audience_change(store):
    key, pair, session = activate(store)
    challenge = store.challenge(session, 'config')
    store.audience = 'https://another-pos.example'
    with pytest.raises(POSDenied): store.authorized(session, 'config', **proof(pair[0], challenge))


def test_disabled_api_rejects_existing_session_and_new_activation(store, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.pos_api import create_router
    key, pair, session = activate(store)
    challenge = store.challenge(session, 'config')
    monkeypatch.setenv('OAKGATE_POS_ENABLED', 'false')
    app = FastAPI()
    app.state.pos = store
    app.include_router(create_router())
    with TestClient(app) as client:
        for path, data in [('config', proof(pair[0], challenge)),
                           ('activation-challenges', {'credential':key, 'public_key':pair[1]}),
                           ('requests', {})]:
            assert client.post('/api/pos/v1/' + path, json=data, headers={'Authorization':'Bearer '+session}).status_code == 503
        assert client.get('/api/pos/v1/status').json()['activation_available'] is False
    # Turning access off has not removed recovery/credential records.
    assert store.listing('alice')[0]['status'] == 'Active'


def test_reactivation_replaces_old_session_and_challenges(store):
    key, pair, first = activate(store)
    outstanding = store.challenge(first, 'config')
    _, _, second = activate(store, key, pair)
    with pytest.raises(POSDenied): store.authorized(first, 'config', **proof(pair[0], outstanding))
    assert config(store, second, pair)['name'] == 'Counter'
