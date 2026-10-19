import asyncio
import tomllib
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from stroma import Keys, fips_ipv6_address

from app.config import AuthSettings
from app.main import create_app
from app.sessions import MemoryStore
from app.version import APP_VERSION
from test_wallets import setup


def test_version_matches_package():
    config = tomllib.loads((Path(__file__).parents[1] / 'pyproject.toml').read_text())
    assert APP_VERSION == config['tool']['poetry']['version']


@pytest.mark.parametrize('management', ['independent', 'mainstay-managed'])
def test_public_identity_is_operator_identity_and_reads_no_private_state(tmp_path, monkeypatch, management):
    secret = '61' * 32
    monkeypatch.setenv('OAKGATE_SERVICE_NSEC', secret)
    async def run():
        client, sessions, wallets, backend = setup(tmp_path)
        app = client._transport.app
        app.state.settings = replace(app.state.settings, service_management=management)
        app.state.payments.config = replace(app.state.payments.config, enabled=False)
        wallets.store.insert('private-owner', {'npub':'private-user-npub','nsec':'USER-NSEC','phrase':'PRIVATE PHRASE','relay':wallets.default_relay}, 'active')
        def unavailable(*args, **kwargs): raise AssertionError('Public information must not read custody')
        monkeypatch.setattr(wallets.store, 'connect', unavailable)
        sessions.get = AsyncMock(side_effect=AssertionError('No session lookup'))
        async with client:
            response = await client.get('/info')
            assert response.status_code == 200
            data = response.json()
            npub = Keys(priv_k=secret).public_key_bech32()
            assert data['service_identity'] == {
                'npub':npub, 'fips_ipv6_address':fips_ipv6_address(npub),
                'type':'oakgate','management':management,'state':'uncommissioned',
                'descriptor_event_id':None,'operator':None}
            assert data['name'] == 'OakGate' and data['version'] == APP_VERSION
            assert 'recovery-disclosure' in data['capabilities']
            assert 'go-independent' not in data['capabilities']
            for private in (secret, 'USER-NSEC', 'PRIVATE PHRASE', 'private-owner', 'private-user-npub', 'client_secret'):
                assert private not in response.text
            assert response.headers['cache-control'] == 'no-store'
            assert response.headers['x-content-type-options'] == 'nosniff'
            assert 'access-control-allow-origin' not in response.headers
            health = await client.get('/health')
            assert health.json() == {'status':'ok','service':'oakgate','version':APP_VERSION}
            assert health.headers['cache-control'] == 'no-store'
            sessions.get.assert_not_awaited()
    asyncio.run(run())


def test_unconfigured_service_and_openapi(monkeypatch):
    import app.main as main
    monkeypatch.setattr(main, 'configured_service', lambda: None)
    app = create_app(AuthSettings('http://127.0.0.1:8801'), store=MemoryStore())
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='http://test') as client:
            info = (await client.get('/info')).json()
            assert info['service_identity'] == {'npub':None,'fips_ipv6_address':None,'type':'oakgate',
                'management':'independent','state':'unconfigured','descriptor_event_id':None,'operator':None}
            schema = (await client.get('/openapi.json')).json()
            assert schema['info']['version'] == APP_VERSION
            assert '/info' in schema['paths'] and '/health' in schema['paths']
    asyncio.run(run())


def test_management_configuration(monkeypatch):
    monkeypatch.setenv('OAKGATE_SERVICE_MANAGEMENT','mainstay-managed')
    assert AuthSettings.from_env().service_management == 'mainstay-managed'
    with pytest.raises(ValueError, match='SERVICE_MANAGEMENT'):
        AuthSettings('http://127.0.0.1:8801',service_management='commissioned')
