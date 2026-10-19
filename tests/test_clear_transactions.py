import asyncio
from contextlib import aclosing
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.clear_balances import asset_id
from app.wallets import AcornBackend
from test_clear_payments import clear_setup, MINT, UNIT
from test_wallets import login


def test_clear_history_is_scoped_ordered_and_safe(tmp_path):
    async def run():
        client, wallets, backend, owner, service, fetch = await clear_setup(tmp_path)
        backend.clear_transactions = AsyncMock(return_value=[
            {'mint': MINT, 'unit': UNIT, 'timestamp': 100+i, 'direction': 'in',
             'amount': i, 'memo': '<script>note</script>', 'token': 'SECRET'} for i in range(12)
        ] + [{'mint': 'https://other.example', 'unit': UNIT, 'timestamp': 999, 'amount': 999, 'memo': 'OTHER ASSET'}])
        url = '/account/clear-transactions?asset='+asset_id(MINT, UNIT)
        async with aclosing(client):
            home = await client.get('/account')
            assert url in home.text
            page = await client.get(url)
            assert page.status_code == 200 and page.headers['cache-control'] == 'no-store'
            assert page.text.count('<article class="transaction-card') == 10
            assert '+11' in page.text and '+1 <span>' not in page.text
            assert 'credits' in page.text and 'Community credits' in page.text
            assert '12 <span>' in page.text and 'href="/account" aria-label=' in page.text
            assert 'OTHER ASSET' not in page.text and 'SECRET' not in page.text
            assert '&lt;script&gt;note&lt;/script&gt;' in page.text
            assert (await client.get('/account/clear-transactions?asset=invalid')).status_code == 404
            backend.clear_balances.return_value = []
            page = await client.get(url)
            assert page.status_code == 200 and '0 <span>' in page.text
            assert page.text.count('<article class="transaction-card') == 10
            client.cookies.clear()
            assert (await client.get(url)).headers['location'] == '/auth/login'
    asyncio.run(run())


def test_clear_history_partial_failure_and_owner_isolation(tmp_path):
    async def run():
        client, wallets, backend, owner, service, fetch = await clear_setup(tmp_path)
        backend.clear_transactions = AsyncMock(side_effect=RuntimeError('PRIVATE'))
        url = '/account/clear-transactions?asset='+asset_id(MINT, UNIT)
        async with aclosing(client):
            page = await client.get(url)
            assert page.status_code == 200 and '12 <span>' in page.text
            assert 'history is unavailable' in page.text and 'PRIVATE' not in page.text
            assert 'No Clear transactions yet.' not in page.text
            # A different identity has no connected Acorn and cannot read history.
            await login(client, client._transport.app.state.store, sub='different-owner')
            assert (await client.get(url)).headers['location'] == '/account'
            backend.clear_transactions.assert_awaited_once()
    asyncio.run(run())


def test_clear_history_adapter_uses_acorn(monkeypatch):
    backend = AcornBackend()
    wallet = SimpleNamespace(get_clear_transaction_history=AsyncMock(return_value=[]))
    monkeypatch.setattr(backend, 'wallet', lambda material: wallet)
    assert asyncio.run(backend.clear_transactions({})) == []
    wallet.get_clear_transaction_history.assert_awaited_once_with()
