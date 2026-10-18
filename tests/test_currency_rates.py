import asyncio
from contextlib import closing
from unittest.mock import AsyncMock

import httpx
import pytest
from cryptography.fernet import Fernet

from app.currency_rates import CurrencyRates, CURRENCY_METADATA
from app.custody import CustodyStore, HandleTaken
from test_wallets import setup, login, form


def test_rates_validation_partial_refresh_restart_and_staleness(tmp_path):
    async def run():
        key = Fernet.generate_key()
        store = CustodyStore(tmp_path, key)
        rates = CurrencyRates(store)
        assert len(rates.rows()) == len(CURRENCY_METADATA)
        assert rates.estimate(1234, 'CAD') is None
        payload = {'CAD': {'15m': 70000}, 'USD': {'15m': 50000}, 'EUR': {'15m': 'NaN'},
                   'GBP': {'15m': -2}, 'JPY': {'15m': 'Infinity'}}
        transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
        async with httpx.AsyncClient(transport=transport) as client:
            assert await rates.refresh(client, now=1000) == 2
            assert rates.estimate(1234, 'CAD', now=1001)['amount'] == '0.86'
            assert rates.estimate(0, 'USD', now=1001)['amount'] == '0.00'
            assert not rates.estimate(1234, 'CAD', now=1001)['stale']
            assert rates.estimate(1234, 'CAD', now=1000+rates.stale_seconds+1)['stale']
            payload.clear(); payload.update({'USD': {'15m': 60000}})
            assert await rates.refresh(client, now=2000) == 1
            cad = rates.estimate(1234, 'CAD', now=2001)
            assert cad['fiat_per_btc'] == '70000' and cad['fetched_at'] == 1000
            payload.clear(); payload.update({'CAD': {'15m': True}, 'USD': {'15m': 0}})
            with pytest.raises(ValueError):
                await rates.refresh(client, now=3000)
            assert rates.estimate(1234,'CAD',now=3001)['fetched_at'] == 1000
        restored = CurrencyRates(CustodyStore(tmp_path,key))
        assert restored.estimate(1234,'CAD',now=3001)['amount'] == '0.86'
        assert restored.estimate(-1,'CAD') is None
    asyncio.run(run())


@pytest.mark.parametrize('status,body',[(503,b'Unavailable'),(302,b''),(200,b'not json'),(200,b'x'*262145)])
def test_failed_provider_does_not_erase_cache(tmp_path,status,body):
    async def run():
        rates=CurrencyRates(CustodyStore(tmp_path,Fernet.generate_key()))
        with closing(rates.store.connect()) as db,db:
            db.execute("UPDATE currency_rates SET fiat_per_btc='50000',fetched_at=1000 WHERE code='USD'")
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(status,content=body))) as client:
            with pytest.raises(Exception):
                await rates.refresh(client)
        assert rates.estimate(100000,'USD',now=1001)['amount']=='50.00'
    asyncio.run(run())


def test_currency_preference_atomic_and_independent_of_handle(tmp_path):
    key=Fernet.generate_key();store=CustodyStore(tmp_path,key)
    assert store.currency('alice')=='USD'
    store.save_handle('alice','Alice',language='fr',currency='CAD')
    store.save_handle('bob','Bob',language='de',currency='EUR')
    with pytest.raises(HandleTaken):
        store.save_handle('alice','Bob',language='es',currency='JPY')
    assert store.currency('alice')=='CAD' and store.language('alice')=='fr'
    with pytest.raises(ValueError):
        store.save_handle('alice','NewName',currency='INVALID')
    store.save_handle('alice','')
    assert CustodyStore(tmp_path,key).currency('alice')=='CAD'
    assert store.currency('bob')=='EUR'


def test_preferences_balance_and_public_rates_do_not_fetch_provider(tmp_path):
    async def run():
        client,sessions,service,backend=setup(tmp_path)
        rates=client._transport.app.state.rates
        backend.transactions=AsyncMock(return_value=[])
        rates.refresh=AsyncMock()
        with closing(service.store.connect()) as db,db:
            db.execute("UPDATE currency_rates SET fiat_per_btc='70000',fetched_at=1,source='https://rates.example/ticker' WHERE code='CAD'")
        async with client:
            public=await client.get('/rates')
            assert public.status_code==200 and '70,000.00' in public.text and 'Possibly stale' in public.text
            rates.refresh.assert_not_awaited()
            owner=await login(client,sessions)
            await client.post('/account/acorn/create',data=form())
            page=await client.get('/account/preferences')
            assert 'id="currency"' in page.text and 'CAD — Canadian dollar' in page.text
            assert (await client.post('/account/preferences',data=form(handle='',currency='CAD',language='en'))).status_code==200
            assert service.store.currency(owner)=='CAD'
            await login(client,sessions)
            balance=await client.get('/account')
            assert '≈ $0.86' in balance.text and '₿ 1,234' in balance.text and 'href="/rates"' in balance.text
            assert balance.text.index('≈ $0.86')<balance.text.index('₿ 1,234')
            tx=await client.get('/account/transactions')
            assert '≈ $0.86' in tx.text and 'href="/account"' in tx.text
            assert (await client.post('/account/preferences',data=form(handle='',currency='NOPE'))).status_code==400
            assert service.store.currency(owner)=='CAD'
            assert (await client.post('/account/preferences',data={'currency':'EUR'})).status_code==403
            # A user may save a currency without a connected Acorn, and is isolated from others.
            other=await login(client,sessions,sub='other')
            assert service.store.currency(other)=='USD'
            assert (await client.post('/account/preferences',data=form(handle='',currency='EUR'))).status_code==200
            assert service.store.currency(owner)=='CAD'
            rates.refresh.assert_not_awaited()
            await login(client,sessions)
            rates.enabled=False
            assert '≈ $' not in (await client.get('/account')).text
            assert '₿ 1,234' in (await client.get('/account')).text
    asyncio.run(run())


def test_worker_refreshes_immediately_survives_failure_and_cancels(tmp_path,monkeypatch):
    async def run():
        rates=CurrencyRates(CustodyStore(tmp_path,Fernet.generate_key()))
        rates.refresh=AsyncMock(side_effect=RuntimeError('offline'))
        sleep=AsyncMock(side_effect=asyncio.CancelledError())
        monkeypatch.setattr('app.currency_rates.asyncio.sleep',sleep)
        with pytest.raises(asyncio.CancelledError):
            await rates.run()
        rates.refresh.assert_awaited_once()
        sleep.assert_awaited_once_with(3600)
    asyncio.run(run())
