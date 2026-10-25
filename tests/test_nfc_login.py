import asyncio
import secrets
import time
from contextlib import closing, aclosing
from urllib.parse import urlsplit
from concurrent.futures import ThreadPoolExecutor

import pytest
from app.custody import identity_key
from app.nfc_cards import CardStore
from app.nfc_login import activate, verify_card
from app.pos_store import POSDenied
from test_nfc_cards import cards

ISSUER = 'https://keycloak.safebox.dev/realms/oakgate'
USER = {'iss': ISSUER, 'sub': 'existing-keycloak-subject'}


def issued(cards, *, requested=True):
    store, _, terminal = cards
    owner = identity_key(USER)
    with closing(store.custody.connect()) as db, db:
        db.execute("INSERT INTO wallets VALUES(?, 'login-wallet', X'00', 'active', NULL, 0)", (owner,))
    key = 'login-pairing-0001'
    code = urlsplit(store.start(terminal, key)['pair_url']).fragment
    pin = store.approve(code, owner, enroll=requested, login_identity=USER)['pin']
    store.acknowledge_pin(code, owner)
    card = store.prepare(terminal, key)
    store.verify(terminal, key, card['payload'])
    return store, owner, card, pin


def attempt(store, card, pin, nonce=None):
    return verify_card(store, card['payload'], pin, nonce or secrets.token_hex(32), ISSUER)


def test_pending_and_explicit_activation_replay_and_restart(cards):
    store, owner, card, pin = issued(cards)
    with pytest.raises(POSDenied): attempt(store, card, pin)
    with pytest.raises(POSDenied): activate(store, card['card_id'], 'other', ISSUER)
    activate(store, card['card_id'], owner, ISSUER)
    nonce = secrets.token_hex(32)
    assert attempt(store, card, pin, nonce) == USER['sub']
    restarted = CardStore(store.custody, store.origin)
    with pytest.raises(POSDenied): attempt(restarted, card, pin, nonce)
    assert attempt(restarted, card, pin) == USER['sub']


def test_durable_pin_limit_cannot_be_reset_by_success(cards):
    store, owner, card, pin = issued(cards)
    activate(store, card['card_id'], owner, ISSUER)
    wrong = '0000' if pin != '0000' else '0001'
    for _ in range(4):
        with pytest.raises(POSDenied): attempt(store, card, wrong)
    assert attempt(store, card, pin) == USER['sub']
    with pytest.raises(POSDenied): attempt(store, card, wrong)
    with pytest.raises(POSDenied): attempt(CardStore(store.custody, store.origin), card, pin)
    activate(store, card['card_id'], owner, ISSUER)
    assert attempt(store, card, pin) == USER['sub']


def test_concurrent_wrong_guesses_are_bounded(cards):
    store, owner, card, pin = issued(cards)
    activate(store, card['card_id'], owner, ISSUER)
    wrong = '0000' if pin != '0000' else '0001'
    def guess(_):
        with pytest.raises(POSDenied): attempt(store, card, wrong)
    with ThreadPoolExecutor(max_workers=8) as pool: list(pool.map(guess, range(12)))
    with closing(store.custody.connect()) as db:
        assert db.execute('SELECT failures FROM nfc_login_attempts').fetchone()[0] == 5


@pytest.mark.parametrize('change', ['revoked','expired','withdrawn','wallet','issuer','identity','unverified'])
def test_no_login_after_authority_changes(cards, change):
    store, owner, card, pin = issued(cards)
    activate(store, card['card_id'], owner, ISSUER)
    with closing(store.custody.connect()) as db, db:
        if change == 'revoked': db.execute('UPDATE nfc_cards SET revoked=1')
        if change == 'expired': db.execute('UPDATE nfc_cards SET expires=0')
        if change == 'withdrawn': db.execute("UPDATE nfc_login_requests SET state='withdrawn'")
        if change == 'wallet': db.execute("UPDATE wallets SET wallet_id='different' WHERE owner=?", (owner,))
        if change == 'unverified': db.execute('UPDATE nfc_cards SET activated=NULL')
        if change in ('issuer','identity'):
            user = {**USER, 'iss' if change=='issuer' else 'sub': 'different'}
            db.execute('UPDATE nfc_login_requests SET identity=?', (store.custody.seal(owner,user),))
    with pytest.raises(POSDenied): attempt(store, card, pin)


def test_no_optin_no_enrollment(cards):
    store, owner, card, pin = issued(cards, requested=False)
    with pytest.raises(POSDenied): activate(store, card['card_id'], owner, ISSUER)
    with pytest.raises(POSDenied): attempt(store, card, pin)


def test_backchannel_auth_bounds_and_no_session(cards, monkeypatch):
    from test_wallets import setup
    from types import SimpleNamespace
    store, owner, card, pin = issued(cards)
    activate(store, card['card_id'], owner, ISSUER)
    monkeypatch.setenv('OAKGATE_NFC_LOGIN_ENABLED','true')
    monkeypatch.setenv('OAKGATE_NFC_BACKCHANNEL_SECRET','s'*64)
    from app.main import create_app
    from app.config import AuthSettings
    from app.sessions import MemoryStore
    import httpx
    app = create_app(settings=AuthSettings(store.origin, client_secret='test'), store=MemoryStore())
    app.state.wallets = SimpleNamespace(store=store.custody)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=store.origin) as c:
            body = {'card':card['payload'], 'pin':pin,'nonce':secrets.token_hex(32),'issuer':ISSUER,'client_id':'oakgate-nfc'}
            assert (await c.post('/api/cards/v1/login/verify',json=body)).status_code == 401
            c.headers['Authorization'] = 'Bearer '+'s'*64
            for bad in ([], {'x':'y'}, {**body,'issuer':'wrong'}, {**body,'client_id':'oakgate-web'}):
                assert (await c.post('/api/cards/v1/login/verify',json=bad)).status_code == 401
            assert (await c.post('/api/cards/v1/login/verify',content='x'*2049)).status_code == 400
            r = await c.post('/api/cards/v1/login/verify',json=body)
            assert r.status_code == 200 and r.json()['sub'] == USER['sub']
            assert 'set-cookie' not in r.headers and 'no-store' in r.headers['cache-control']
            assert (await c.post('/api/cards/v1/login/verify',json=body)).status_code == 401
            monkeypatch.setenv('OAKGATE_NFC_LOGIN_ENABLED','false')
            assert (await c.post('/api/cards/v1/login/verify',json={**body,'nonce':secrets.token_hex(32)})).status_code == 401
    asyncio.run(run())


from test_auth import signing_key
from test_recovery import connected
from app.pos_store import POSStore
from app.identity import ServiceIdentity
from html import unescape
import re
from urllib.parse import parse_qs


@pytest.mark.parametrize('require_pin', [True, False])
@pytest.mark.parametrize('failure', [None, 'stale', 'other-account', 'missing', 'session'])
def test_enrollment_requires_fresh_normal_oidc(tmp_path, signing_key, monkeypatch, failure, require_pin):
    monkeypatch.setenv('OAKGATE_NFC_LOGIN_ENABLED','true')
    async def run():
        c, identity, sessions, session, material, wallets = await connected(tmp_path, signing_key)
        async with aclosing(c):
            owner = identity_key(session['user'])
            ServiceIdentity(wallets.store, '11'*32)
            terminal = POSStore(wallets.store,'https://pos.example').provision(owner,'Counter').split('.')[1]
            store = CardStore(wallets.store,'https://oakgate.example')
            key = 'login-pairing-0001'
            code = urlsplit(store.start(terminal,key)['pair_url']).fragment
            store.approve(code,owner,enroll=True,login_identity=session['user'])
            store.acknowledge_pin(code,owner)
            card=store.prepare(terminal,key); store.verify(terminal,key,card['payload'])
            path='/account/cards/'+card['card_id']+'/login/activate'
            assert (await c.post(path,data={'csrf':'wrong'})).status_code == 403
            assert (await c.post(path,data={'csrf':session['csrf'],'require_pin':'no'})).status_code == 400
            page=await c.post(path,data={'csrf':session['csrf'],'require_pin':'yes' if require_pin else 'no','acknowledge_card_only':'yes'})
            assert store.listing(owner)[0]['require_pin'] == 1
            assert page.status_code == 200
            url=unescape(re.search(r'href="(https://identity.example[^"]+)"',page.text)[1])
            identity.authorization=parse_qs(urlsplit(url).query)
            assert identity.authorization['client_id']==['oakgate-web']
            assert identity.authorization['prompt']==['login'] and identity.authorization['max_age']==['0']
            identity.changes['auth_time']=int(time.time())
            if failure=='stale': identity.changes['auth_time']-=600
            if failure=='other-account': identity.changes['sub']='different'
            if failure=='missing': del identity.changes['auth_time']
            if failure=='session':
                from app.sessions import record_key
                await sessions.delete(record_key('session',c.cookies.get('__Host-oakgate_session')))
            args={'state':identity.authorization['state'][0],'code':'reauth'}
            response=await c.get('/auth/callback',params=args)
            assert response.status_code == (400 if failure else 303)
            assert store.listing(owner)[0]['login_request'] == ('requested' if failure else 'active')
            assert store.listing(owner)[0]['require_pin'] == (1 if failure else int(require_pin))
            assert (await c.get('/auth/callback',params=args)).status_code==400
    asyncio.run(run())


def test_nfc_login_uses_separate_oidc_client_and_preserves_subject(signing_key, monkeypatch):
    from test_auth import setup
    from app.oidc import KeycloakProvider
    from dataclasses import replace
    from app.sessions import record_key
    import httpx
    c, identity, sessions, provider = setup(signing_key)
    identity.changes['aud']='oakgate-nfc'
    alternate = KeycloakProvider(replace(provider.settings, client_id='oakgate-nfc',client_secret='nfc-secret'), transport=httpx.MockTransport(identity.handle))
    monkeypatch.setattr('app.nfc_login.nfc_provider', lambda request: alternate)
    async def run():
        async with aclosing(c):
            response=await c.get('/auth/nfc')
            identity.authorization=parse_qs(urlsplit(response.headers['location']).query)
            assert identity.authorization['client_id']==['oakgate-nfc']
            response=await c.get('/auth/callback',params={'state':identity.authorization['state'][0],'code':'card-login'})
            assert response.status_code==303
            session=await sessions.get(record_key('session',c.cookies.get('__Host-oakgate_session')))
            assert session['user']['sub']=='stable-user-id' and session['user']['iss']==identity.issuer
    asyncio.run(run())



def test_login_choice_is_opt_in(signing_key, monkeypatch):
    from test_auth import setup
    c, _, _, _ = setup(signing_key)
    async def run():
        async with aclosing(c):
            monkeypatch.setenv('OAKGATE_NFC_LOGIN_ENABLED','false')
            assert (await c.get('/auth/options')).status_code == 303
            assert (await c.get('/auth/nfc')).status_code == 503
            monkeypatch.setenv('OAKGATE_NFC_LOGIN_ENABLED','true')
            page=await c.get('/auth/options')
            assert page.status_code==200 and 'href="/auth/nfc"' in page.text and 'href="/auth/login"' in page.text
    asyncio.run(run())


def test_diagnostics_do_not_expose_credentials(cards, monkeypatch, caplog):
    import httpx
    from types import SimpleNamespace
    from app.main import create_app
    from app.config import AuthSettings
    from app.sessions import MemoryStore
    store, owner, card, pin = issued(cards)
    activate(store, card['card_id'], owner, ISSUER)
    monkeypatch.setenv('OAKGATE_NFC_LOGIN_ENABLED','true')
    secret = 'private-backchannel-secret-'*3
    monkeypatch.setenv('OAKGATE_NFC_BACKCHANNEL_SECRET',secret)
    app = create_app(settings=AuthSettings(store.origin,client_secret='test'),store=MemoryStore())
    app.state.wallets = SimpleNamespace(store=store.custody)
    wrong = '0000' if pin != '0000' else '0001'
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url=store.origin) as c:
            body={'card':card['payload'],'pin':wrong,'nonce':secrets.token_hex(32),'issuer':ISSUER,'client_id':'oakgate-nfc'}
            assert (await c.post('/api/cards/v1/login/verify',json=body)).status_code == 401
            assert 'phase=backchannel_auth' in caplog.text
            caplog.clear()
            c.headers['Authorization']='Bearer '+secret
            r=await c.post('/api/cards/v1/login/verify',json=body)
            assert r.status_code==401 and 'pin_incorrect' not in r.text
            assert 'phase=pin_incorrect' in caplog.text
            for sensitive in (pin,wrong,secret,card['payload'],owner,USER['sub']):
                assert sensitive not in caplog.text
    asyncio.run(run())


def test_card_only_is_explicit_persistent_and_reversible(cards):
    store, owner, card, pin = issued(cards)
    activate(store, card['card_id'], owner, ISSUER)
    with pytest.raises(POSDenied): attempt(store, card, '')
    with pytest.raises(POSDenied): activate(store, card['card_id'], 'another-user', ISSUER, require_pin=False)
    assert store.listing(owner)[0]['require_pin'] == 1
    activate(store, card['card_id'], owner, ISSUER, require_pin=False)
    restarted = CardStore(store.custody,store.origin)
    assert restarted.listing(owner)[0]['require_pin'] == 0
    nonce = secrets.token_hex(32)
    assert attempt(restarted,card,'',nonce) == USER['sub']
    with pytest.raises(POSDenied): attempt(restarted,card,'',nonce)
    activate(store,card['card_id'],owner,ISSUER,require_pin=True)
    with pytest.raises(POSDenied): attempt(store,card,'')
    assert attempt(store,card,pin) == USER['sub']


@pytest.mark.parametrize('change',['withdrawn','revoked','expired','wallet'])
def test_card_only_preserves_authority_checks(cards,change):
    store,owner,card,pin=issued(cards)
    activate(store,card['card_id'],owner,ISSUER,require_pin=False)
    with closing(store.custody.connect()) as db,db:
        if change=='withdrawn': db.execute("UPDATE nfc_login_requests SET state='withdrawn'")
        if change=='revoked': db.execute('UPDATE nfc_cards SET revoked=1')
        if change=='expired': db.execute('UPDATE nfc_cards SET expires=0')
        if change=='wallet': db.execute("UPDATE wallets SET wallet_id='replaced' WHERE owner=?",(owner,))
    with pytest.raises(POSDenied): attempt(store,card,'')
