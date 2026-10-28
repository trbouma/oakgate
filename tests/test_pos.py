import os
import subprocess
import sys

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.pos_api import create_router
from pos.config import POSSettings
from pos.main import create_app


@pytest.fixture(autouse=True)
def clean_pos_env(monkeypatch):
    for name in list(os.environ):
        if name.startswith('OAKGATE_POS_'):
            monkeypatch.delenv(name)


def enabled_settings():
    return POSSettings(True, 'https://pos.example.com', 'http://app:8000', Fernet.generate_key().decode())


def test_disabled_by_default_and_no_account_surface():
    settings = POSSettings.from_env()
    assert settings.enabled is False
    def forbidden(request):
        pytest.fail('Disabled POS must not contact OakGate')
    with TestClient(create_app(settings, httpx.MockTransport(forbidden))) as client:
        assert client.get('/health').json()['status'] == 'ok'
        assert client.get('/ready').json()['status'] == 'disabled'
        response = client.get('/')
        assert client.get('/api/session').json() == {'enabled': False, 'session_present': False}
        assert 'set-cookie' not in response.headers
        assert client.get('/logo.png').status_code == 200
        for path in ('/account', '/auth/login', '/docs', '/openapi.json', '/receive'):
            assert client.get(path).status_code == 404


@pytest.mark.parametrize('name,value', [
    ('OAKGATE_POS_ENABLED', 'maybe'),
    ('OAKGATE_POS_PUBLIC_URL', 'https://user:secret@example.com'),
    ('OAKGATE_POS_API_URL', 'http://app:8000/account'),
    ('OAKGATE_POS_API_URL', 'http://app:8000?x=1'),
])
def test_rejects_invalid_configuration(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError):
        POSSettings.from_env()


def test_enabled_requires_https_and_separate_key(monkeypatch):
    monkeypatch.setenv('OAKGATE_POS_ENABLED', 'true')
    with pytest.raises(ValueError, match='COOKIE_KEY'):
        POSSettings.from_env()
    key = Fernet.generate_key().decode()
    monkeypatch.setenv('OAKGATE_POS_COOKIE_KEY', key)
    settings = POSSettings.from_env()
    assert settings.enabled and key not in repr(settings)
    monkeypatch.setenv('OAKGATE_POS_PUBLIC_URL', 'http://pos.example.com')
    with pytest.raises(ValueError):
        POSSettings.from_env()


def test_connection_check_only_calls_metadata_endpoint():
    def backend(request):
        assert str(request.url) == 'http://app:8000/api/pos/v1/status'
        assert 'authorization' not in request.headers
        return httpx.Response(200, json={'service': 'oakgate-pos-api', 'enabled': True})
    with TestClient(create_app(enabled_settings(), httpx.MockTransport(backend))) as client:
        response = client.get('/ready')
        assert response.status_code == 200
        assert response.json() == {'status': 'connected', 'phase': 'receiving', 'activation_available': False, 'payments_available': False}


@pytest.mark.parametrize('failure', ['disabled', 'redirect', 'invalid', 'timeout'])
def test_connection_failures_are_safe(failure):
    calls = []
    def backend(request):
        calls.append(request)
        if failure == 'timeout':
            raise httpx.ReadTimeout('private backend information', request=request)
        if failure == 'redirect':
            return httpx.Response(302, headers={'Location': 'https://unexpected.example.com'})
        if failure == 'invalid':
            return httpx.Response(200, text='private backend information')
        return httpx.Response(200, json={'service': 'oakgate-pos-api', 'enabled': False})
    with TestClient(create_app(enabled_settings(), httpx.MockTransport(backend))) as client:
        response = client.get('/ready')
        assert response.status_code == 503
        assert response.json() == {'status': 'unavailable', 'activation_available': False}
        assert len(calls) == 1


@pytest.mark.parametrize('enabled', ['true', 'false'])
def test_backend_without_storage_never_exposes_activation_or_payments(monkeypatch, enabled):
    monkeypatch.setenv('OAKGATE_POS_ENABLED', enabled)
    backend = FastAPI()
    backend.include_router(create_router())
    with TestClient(backend) as client:
        assert client.get('/api/pos/v1/status').json()['enabled'] is (enabled == 'true')
        for path in ('activate', 'requests', 'config', 'logout', 'requests/123'):
            for method in ('get', 'post', 'delete'):
                assert getattr(client, method)('/api/pos/v1/' + path).status_code == 503


def test_pos_does_not_import_custody_application():
    result = subprocess.run([sys.executable, '-c',
        "import sys; import pos.main; assert 'app.main' not in sys.modules; assert 'app.wallets' not in sys.modules; assert 'acorn.acorn' not in sys.modules"],
        capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('detail,expected', [
    ({'code':'same-wallet'}, {'code':'same-wallet','message':'This card belongs to the receiving wallet. Use a different card. No payment was sent.'}),
    ({'code':'unknown','message':'private backend detail'}, 'Check the amount and currency, or refresh the receiving options.'),
])
def test_card_rejection_proxy_allowlist(detail, expected):
    from pos.main import COOKIE
    settings=enabled_settings()
    def backend(request):
        return httpx.Response(400,json={'detail':detail})
    with TestClient(create_app(settings,httpx.MockTransport(backend)),base_url=settings.public_url) as client:
        cookie=Fernet(settings.cookie_key.encode()).encrypt(b'oakgate-pos-session-v1:test').decode()
        client.cookies.set(COOKIE,cookie)
        response=client.post('/api/card-pay',headers={'Origin':settings.public_url},
                             json={'payload':'{}','challenge':'test','signature':'test'})
        assert response.status_code==400
        assert response.json()['detail']==expected


def test_record_presentation_proxy_preserves_publishers_and_filters_private_fields():
    from pos.main import COOKIE
    settings = enabled_settings()
    publishers = [{'name': 'Community Centre', 'statement': 'Membership confirmed.'}]
    def backend(request):
        return httpx.Response(200, json={
            'state': 'displayed', 'label': 'whoami',
            'verification': {'aggregate_state': 'anchored'},
            'publishers': publishers, 'private_internal_data': 'must not pass',
        })
    with TestClient(create_app(settings, httpx.MockTransport(backend)),
                    base_url=settings.public_url) as client:
        cookie = Fernet(settings.cookie_key.encode()).encrypt(b'oakgate-pos-session-v1:test').decode()
        client.cookies.set(COOKIE, cookie)
        response = client.post('/api/record-present', headers={'Origin': settings.public_url},
                               json={'payload': '{}', 'challenge': 'test', 'signature': 'test'})
        assert response.status_code == 200
        assert response.json() == {
            'state': 'displayed', 'label': 'whoami',
            'verification': {'aggregate_state': 'anchored'}, 'publishers': publishers,
        }


def test_pos_serves_only_pdf_library_assets():
    with TestClient(create_app(POSSettings.from_env())) as client:
        for path in ('pdf.mjs', 'pdf.worker.mjs', 'standard_fonts/FoxitSerif.pfb'):
            assert client.get('/pdf-assets/' + path).status_code == 200
        assert client.get('/pdf-assets/record-actions.js').status_code == 404
        assert "script-src 'self'" in client.get('/').headers['content-security-policy']
