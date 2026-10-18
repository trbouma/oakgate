import asyncio
import base64
import hashlib
import re
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from authlib.jose import JsonWebKey, JsonWebToken
from redis.exceptions import ConnectionError as RedisConnectionError

from app.config import AuthSettings
from app.main import create_app
from app.oidc import KeycloakProvider
from app.sessions import MemoryStore, record_key


@pytest.fixture(scope='module')
def signing_key():
    return JsonWebKey.generate_key('RSA', 2048, is_private=True, options={'kid': 'test'})


class IdentityServer:
    issuer = 'https://identity.example/realms/oakgate'

    def __init__(self, key, changes=None):
        self.key = key
        self.changes = changes or {}
        self.authorization = {}
        self.exchanges = 0
        self.unavailable = False

    def handle(self, request):
        if self.unavailable:
            return httpx.Response(503)
        path = request.url.path
        if path.endswith('openid-configuration'):
            return httpx.Response(200, json={
                'issuer': self.issuer,
                'authorization_endpoint': self.issuer + '/authorize',
                'token_endpoint': self.issuer + '/token',
                'jwks_uri': self.issuer + '/keys',
                'end_session_endpoint': self.issuer + '/logout',
            })
        if path.endswith('/keys'):
            return httpx.Response(200, json={'keys': [self.key.as_dict(is_private=False)]})
        if path.endswith('/token'):
            self.exchanges += 1
            form = parse_qs(request.content.decode())
            assert form['redirect_uri'] == ['https://oakgate.example/auth/callback']
            assert form['grant_type'] == ['authorization_code']
            assert request.headers['authorization'].startswith('Basic ')
            challenge = base64.urlsafe_b64encode(hashlib.sha256(form['code_verifier'][0].encode()).digest()).rstrip(b'=').decode()
            assert challenge == self.authorization['code_challenge'][0]
            claims = {'iss': self.issuer, 'sub': 'stable-user-id', 'aud': 'oakgate-web',
                      'iat': int(time.time()), 'exp': int(time.time()) + 300,
                      'nonce': self.authorization['nonce'][0], 'name': '<script>Example</script>',
                      'email': 'person@example.com', 'email_verified': True}
            claims.update(self.changes)
            token = JsonWebToken(['RS256']).encode({'alg': 'RS256', 'kid': 'test'}, claims, self.key).decode()
            return httpx.Response(200, json={'access_token': 'never-in-browser', 'token_type': 'Bearer', 'id_token': token})
        raise AssertionError(str(request.url))


def setup(key, changes=None, session_ttl_seconds=604800):
    identity = IdentityServer(key, changes)
    settings = AuthSettings('https://oakgate.example', issuer=identity.issuer, client_secret='test-secret', session_ttl_seconds=session_ttl_seconds)
    store = MemoryStore()
    provider = KeycloakProvider(settings, transport=httpx.MockTransport(identity.handle))
    app = create_app(settings, store, provider)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=settings.origin)
    return client, identity, store, provider


async def begin(client, identity):
    response = await client.get('/auth/login')
    assert response.status_code == 303
    identity.authorization = parse_qs(urlsplit(response.headers['location']).query)
    assert identity.authorization['code_challenge_method'] == ['S256']
    assert identity.authorization['response_type'] == ['code']
    cookie = response.headers['set-cookie']
    assert 'HttpOnly' in cookie and 'Secure' in cookie and 'SameSite=lax' in cookie
    assert 'Domain=' not in cookie
    return identity.authorization['state'][0]


def test_login_account_and_logout(signing_key):
    async def run():
        client, identity, store, _ = setup(signing_key)
        async with client:
            assert (await client.get('/api/me')).status_code == 401
            assert (await client.get('/account')).headers['location'] == '/auth/login'
            state = await begin(client, identity)
            result = await client.get('/auth/callback', params={'state': state, 'code': 'one-use-code'})
            assert result.status_code == 303
            assert result.headers['location'] == '/account'
            session_cookie = client.cookies.get('__Host-oakgate_session')
            assert 'never-in-browser' not in result.headers['set-cookie']
            assert result.headers['cache-control'] == 'no-store'
            assert result.headers['referrer-policy'] == 'no-referrer'
            me = await client.get('/api/me')
            assert me.json()['sub'] == 'stable-user-id'
            assert me.json()['iss'] == identity.issuer
            page = await client.get('/account')
            assert '&lt;script&gt;Example&lt;/script&gt;' in page.text
            assert page.headers['referrer-policy'] == 'strict-origin'
            csrf = re.search(r'name="csrf" value="([^"]+)"', page.text)[1]
            assert (await client.post('/auth/logout', data={'csrf': 'bad'})).status_code == 403
            assert (await client.post('/auth/logout', data={'csrf': csrf}, headers={'origin': 'https://evil.example'})).status_code == 403
            assert (await client.get('/api/me')).status_code == 200
            assert (await client.post('/auth/logout', data={'csrf': csrf}, headers={'origin': 'null'})).status_code == 403
            logout = await client.post('/auth/logout', data={'csrf': csrf}, headers={'origin': 'https://oakgate.example'})
            assert logout.status_code == 303
            assert logout.headers['location'].startswith(identity.issuer + '/logout?')
            assert await store.get(record_key('session', session_cookie)) is None
            assert (await client.get('/api/me')).status_code == 401
    asyncio.run(run())


@pytest.mark.parametrize('changes', [
    {'iss': 'https://evil.example'}, {'aud': 'another-client'}, {'nonce': 'wrong'},
    {'exp': int(time.time()) - 120}, {'azp': 'another-client'}, {'sub': ''},
])
def test_invalid_identity_cannot_create_session(signing_key, changes):
    async def run():
        client, identity, _, _ = setup(signing_key, changes)
        async with client:
            state = await begin(client, identity)
            response = await client.get('/auth/callback', params={'state': state, 'code': 'code'})
            assert response.status_code == 400
            assert (await client.get('/api/me')).status_code == 401
            assert client.cookies.get('__Host-oakgate_session') is None
    asyncio.run(run())


def test_callback_binding_and_replay(signing_key):
    async def run():
        client, identity, _, _ = setup(signing_key)
        async with client:
            state = await begin(client, identity)
            binding = client.cookies.get('__Host-oakgate_login')
            client.cookies.clear()
            assert (await client.get('/auth/callback', params={'state': state, 'code': 'code'})).status_code == 400
            assert identity.exchanges == 0
            client.cookies.set('__Host-oakgate_login', binding)
            assert (await client.get('/auth/callback', params={'state': 'wrong', 'code': 'code'})).status_code == 400
            assert identity.exchanges == 0
            client.cookies.clear()
            client.cookies.set('__Host-oakgate_login', binding)
            assert (await client.get('/auth/callback', params={'state': state, 'code': 'code'})).status_code == 303
            client.cookies.clear()
            client.cookies.set('__Host-oakgate_login', binding)
            assert (await client.get('/auth/callback', params={'state': state, 'code': 'code'})).status_code == 400
            assert identity.exchanges == 1
    asyncio.run(run())


def test_expired_session_and_provider_outage(signing_key):
    async def run():
        client, identity, store, provider = setup(signing_key)
        async with client:
            state = await begin(client, identity)
            await client.get('/auth/callback', params={'state': state, 'code': 'code'})
            key = record_key('session', client.cookies.get('__Host-oakgate_session'))
            session = await store.get(key)
            identity.unavailable = True
            provider.metadata_until = 0
            response = await client.post('/auth/logout', data={'csrf': session['csrf']})
            assert response.status_code == 200
            assert await store.get(key) is None
            assert (await client.get('/api/me')).status_code == 401
            identity.unavailable = False
            state = await begin(client, identity)
            await client.get('/auth/callback', params={'state': state, 'code': 'code'})
            key = record_key('session', client.cookies.get('__Host-oakgate_session'))
            session = await store.get(key)
            session['expires_at'] = time.time() - 1
            assert (await client.get('/api/me')).status_code == 401
    asyncio.run(run())


def test_storage_outage_fails_closed(signing_key):
    async def run():
        client, identity, store, _ = setup(signing_key)
        async def unavailable(*args):
            raise RedisConnectionError('private connection details')
        store.get = unavailable
        async with client:
            client.cookies.set('__Host-oakgate_session', 'opaque-id')
            response = await client.get('/api/me')
            assert response.status_code == 503
            assert 'private connection details' not in response.text
            assert (await client.get('/health')).status_code == 200
    asyncio.run(run())


def test_bad_signature_is_rejected(signing_key):
    async def run():
        client, identity, _, provider = setup(signing_key)
        wrong = JsonWebKey.generate_key('RSA', 2048, is_private=True, options={'kid': 'test'})
        async def wrong_keys(force=False):
            return {'keys': [wrong.as_dict(is_private=False)]}
        provider.keys = wrong_keys
        async with client:
            state = await begin(client, identity)
            response = await client.get('/auth/callback', params={'state': state, 'code': 'code'})
            assert response.status_code == 400
            assert (await client.get('/api/me')).status_code == 401
    asyncio.run(run())


def test_rotated_signing_key_is_refetched(signing_key):
    async def run():
        client, identity, _, provider = setup(signing_key)
        old = JsonWebKey.generate_key('RSA', 2048, is_private=True, options={'kid': 'old'})
        provider.cached_keys = {'keys': [old.as_dict(is_private=False)]}
        provider.keys_until = time.time() + 300
        async with client:
            state = await begin(client, identity)
            assert (await client.get('/auth/callback', params={'state': state, 'code': 'code'})).status_code == 303
            assert (await client.get('/api/me')).status_code == 200
    asyncio.run(run())


def test_cancelled_and_expired_login(signing_key):
    async def run():
        client, identity, store, _ = setup(signing_key)
        async with client:
            state = await begin(client, identity)
            assert (await client.get('/auth/callback', params={'state': state, 'error': 'access_denied'})).status_code == 400
            assert identity.exchanges == 0
            state = await begin(client, identity)
            key = record_key('login', client.cookies.get('__Host-oakgate_login') + state)
            _, transaction = store.records[key]
            store.records[key] = (time.time() - 1, transaction)
            assert (await client.get('/auth/callback', params={'state': state, 'code': 'code'})).status_code == 400
            assert identity.exchanges == 0
    asyncio.run(run())


@pytest.mark.parametrize('lifetime', [604800, 3600])
def test_fixed_application_session_outlives_id_token(signing_key, monkeypatch, lifetime):
    async def run():
        client, identity, store, _ = setup(signing_key, session_ttl_seconds=lifetime)
        async with client:
            state = await begin(client, identity)
            result = await client.get('/auth/callback', params={'state': state, 'code': 'code'})
            assert result.status_code == 303
            cookie = next(v for v in result.headers.get_list('set-cookie') if '__Host-oakgate_session=' in v)
            assert f'Max-Age={lifetime}' in cookie
            key = record_key('session', client.cookies.get('__Host-oakgate_session'))
            expires, session = store.records[key]
            assert abs(session['expires_at'] - time.time() - lifetime) < 2
            assert abs(expires - session['expires_at']) < 1
            # The fixture ID token expires after five minutes. Local access
            # remains valid after that, without refreshing or extending expiry.
            original_expiry = session['expires_at']
            monkeypatch.setattr(time, 'time', lambda: original_expiry - 1)
            assert (await client.get('/api/me')).status_code == 200
            assert session['expires_at'] == original_expiry
            monkeypatch.setattr(time, 'time', lambda: original_expiry + 1)
            assert (await client.get('/api/me')).status_code == 401
    asyncio.run(run())
