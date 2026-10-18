import asyncio
from unittest.mock import AsyncMock

import pytest

from app.clear_balances import ClearLabels, PublicResolver, metadata_url
from app.wallets import AcornBackend
from test_wallets import setup, login, form


def balances():
    return [{'mint':'https://mint.example', 'unit':'cmu-original', 'amount':1250,
             'keysets':[{'keyset':'old','amount':1000}, {'keyset':'new','amount':250}]}]


def test_aliases_match_exact_keyset_and_preserve_amounts():
    async def run():
        fetch = AsyncMock(return_value={'unused': True})
        fetch.return_value = [
            {'id':'wrong','unit':'cmu-original','friendly_alias':'Wrong'},
            {'id':'old','unit':'cmu-original','friendly_alias':'Community meals', 'friendly_unit_alias':'meals', 'active':False},
            {'id':'new','unit':'cmu-original','friendly_name':'Lunch credits','friendly_unit_alias':'lunches'},
        ]
        resolver = ClearLabels(fetch)
        rows = await resolver.resolve(balances())
        by_id = {r['keyset_id']:r for r in rows}
        assert by_id['old']['display_name'] == 'Community meals'
        assert by_id['old']['display_unit'] == 'meals'
        assert by_id['old']['amount'] == 1000
        assert by_id['new']['display_unit'] == 'lunches'
        assert by_id['new']['amount'] == 250
        assert all(r['unit'] == 'cmu-original' for r in rows)
        await resolver.resolve(balances())
        fetch.assert_awaited_once()
    asyncio.run(run())


def test_metadata_failure_and_missing_alias_fallback():
    async def run():
        resolver = ClearLabels(AsyncMock(side_effect=TimeoutError))
        rows = await resolver.resolve(balances())
        assert rows[0]['display_unit'] == 'cmu-original'
        assert sum(row['amount'] for row in rows) == 1250
        resolver = ClearLabels(AsyncMock(return_value=[{'id':'new','unit':'wrong','friendly_alias':'Wrong'}]))
        assert all(row['display_name'] == 'cmu-original' for row in await resolver.resolve(balances()))
        resolver = ClearLabels(AsyncMock(return_value=[{'id':'old','unit':'cmu-original','friendly_alias':'x'*121,'friendly_unit_alias':'x'*41}]))
        assert all(row['display_name'] == 'cmu-original' for row in await resolver.resolve(balances()))
        assert await resolver.resolve([]) == []
    asyncio.run(run())


@pytest.mark.parametrize('mint', ['http://mint.example','https://localhost:8000','https://127.0.0.1','https://[::1]', 'https://169.254.169.254', 'https://user:pass@mint.example','https://mint.example?secret=x'])
def test_unsafe_metadata_endpoint_rejected(mint):
    with pytest.raises(ValueError):
        metadata_url(mint)


def test_private_dns_rejected_at_connection(monkeypatch):
    async def run():
        from aiohttp.resolver import DefaultResolver
        monkeypatch.setattr(DefaultResolver, 'resolve', AsyncMock(return_value=[{'host':'192.168.1.2'}]))
        resolver = PublicResolver()
        try:
            with pytest.raises(OSError):
                await resolver.resolve('mint.example',443)
        finally:
            await resolver.close()
    asyncio.run(run())


def test_clear_balance_rendering_and_independent_failures(tmp_path):
    async def run():
        client, sessions, service, backend = setup(tmp_path)
        backend.clear_balances = AsyncMock(return_value=balances())
        service.clear_labels = ClearLabels(AsyncMock(return_value=[
            {'id':'old','unit':'cmu-original','friendly_alias':'Community meals','friendly_unit_alias':'meals'},
            {'id':'new','unit':'cmu-original','friendly_alias':'<script>bad</script>','friendly_unit_alias':'credits'},
        ]))
        async with client:
            await login(client,sessions)
            await client.post('/account/acorn/create',data=form())
            page = await client.get('/account')
            assert '1,234' in page.text and '1,000' in page.text and 'meals' in page.text
            assert 'Community meals' in page.text and 'cmu-original' in page.text
            assert '&lt;script&gt;bad&lt;/script&gt;' in page.text
            assert '<script>bad</script>' not in page.text
            assert 'SECRET-' not in page.text
            backend.clear_balances.side_effect = TimeoutError
            page = await client.get('/account')
            assert 'Clear balances unavailable' in page.text and '1,234' in page.text
            backend.down = True
            backend.clear_balances.side_effect = None
            page = await client.get('/account')
            assert 'Balance unavailable' in page.text and 'Community meals' in page.text
            backend.clear_balances.return_value = []
            assert 'No Clear balances yet.' in (await client.get('/account')).text
    asyncio.run(run())


def test_adapter_uses_acorn_clear_reader():
    async def run():
        backend = AcornBackend()
        class Wallet:
            get_clear_balances = AsyncMock(return_value=balances())
        wallet = Wallet()
        backend.wallet = lambda material: wallet
        assert await backend.clear_balances({}) == balances()
        wallet.get_clear_balances.assert_awaited_once_with()
    asyncio.run(run())
