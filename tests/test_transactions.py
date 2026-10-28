import asyncio
from unittest.mock import AsyncMock

from app.transactions import transaction_cards
from test_wallets import setup, login, form


def test_acorn_history_order_limit_and_no_secret_fields():
    history = [{'create_time': 100+i, 'tx_type': 'D', 'amount': i, 'fees': 2,
                'current_balance': 100, 'invoice': f'invoice-{i}', 'preimage': 'PRIVATE'} for i in range(12)]
    history[-1]['tx_type'] = 'C'
    cards = transaction_cards(history)
    assert len(cards) == 10
    assert cards[0]['amount'] == 11 and cards[0]['direction'] == 'Received'
    assert cards[1]['amount'] == 12 and cards[1]['direction'] == 'Sent'
    assert 'PRIVATE' not in str(cards) and 'invoice' not in str(cards)
    assert cards[-1]['timestamp'] == 102


def test_cash_page_authorization_links_and_partial_errors(tmp_path):
    async def run():
        client, sessions, service, backend = setup(tmp_path)
        backend.transactions = AsyncMock(return_value=[{'create_time': 100+i, 'tx_type':'C', 'amount':i, 'comment':'<script>note</script>'} for i in range(14)])
        async with client:
            assert (await client.get('/account/transactions')).headers['location'] == '/auth/login'
            await login(client, sessions)
            assert 'Connect an Acorn' in (await client.get('/account/transactions')).text
            await client.post('/account/acorn/create', data=form())
            home = await client.get('/account')
            assert 'href="/account/transactions"' in home.text
            page = await client.get('/account/transactions')
            assert page.status_code == 200 and page.headers['cache-control'] == 'no-store'
            assert page.text.count('<article class="transaction-card') == 10
            assert '1,234' in page.text and 'href="/account" aria-label="1,234 sats. Back' in page.text
            assert 'Balance after' not in page.text
            assert '&lt;script&gt;note&lt;/script&gt;' in page.text and '<script>' not in page.text
            backend.transactions.side_effect = RuntimeError('PRIVATE-NSEC')
            page = await client.get('/account/transactions')
            assert 'history is unavailable' in page.text and '1,234' in page.text and 'PRIVATE' not in page.text
            await login(client, sessions, sub='someone-else')
            assert 'Connect an Acorn' in (await client.get('/account/transactions')).text
            assert backend.transactions.await_count == 2
    asyncio.run(run())


def test_local_journal_never_appears_even_when_acorn_is_empty_or_unavailable(tmp_path):
    async def run():
        client, sessions, service, backend = setup(tmp_path)
        backend.transactions = AsyncMock(return_value=[])
        from app.payment_store import PaymentStore
        store = PaymentStore(service.store)
        async with client:
            owner = await login(client, sessions)
            await client.post('/account/acorn/create', data=form())
            item, _ = store.reserve(owner, {'amount': 9999, 'paid_at': 100, 'comment': 'LOCAL JOURNAL ENTRY'})
            item['state'] = 'complete'
            store.save(item)
            page = await client.get('/account/transactions')
            assert 'No cash transactions yet.' in page.text
            assert 'LOCAL JOURNAL ENTRY' not in page.text and '9,999' not in page.text
            backend.transactions.side_effect = RuntimeError('Unavailable')
            page = await client.get('/account/transactions')
            assert 'Acorn transaction history is unavailable' in page.text
            assert 'LOCAL JOURNAL ENTRY' not in page.text and 'No cash transactions yet.' not in page.text
            assert store.get(item['id'])['state'] == 'complete'
    asyncio.run(run())


def test_recorded_balance_including_zero_is_shown(tmp_path):
    async def run():
        client, sessions, service, backend = setup(tmp_path)
        backend.transactions = AsyncMock(return_value=[
            {'create_time': 100, 'tx_type': 'D', 'amount': 10, 'current_balance': 0},
            {'create_time': 101, 'tx_type': 'C', 'amount': 10, 'current_balance': 1234},
        ])
        async with client:
            await login(client, sessions)
            await client.post('/account/acorn/create', data=form())
            page = await client.get('/account/transactions')
            assert page.text.count('Balance after') == 2
            assert '<dd>0 sats</dd>' in page.text
            assert '<dd>1,234 sats</dd>' in page.text
    asyncio.run(run())
