import asyncio
import logging
from unittest.mock import AsyncMock

import pytest

from app.wallets import AcornBackend, RecordReadLogger
from test_wallets import setup, login, form


def test_record_adapter_returns_only_labels_newest_first():
    async def run():
        backend = AcornBackend()
        class Wallet:
            logger = logging.getLogger('test-records')
            get_user_records = AsyncMock(return_value=[
                {'tag':['Old'], 'timestamp':10, 'payload':'PRIVATE'},
                {'tag':'Newest', 'timestamp':30, 'content':'SECRET'},
                {'tag':['Middle','ignored'], 'timestamp':20},
                {'tag':[], 'timestamp':50},
            ])
        wallet=Wallet()
        backend.wallet=lambda material: wallet
        assert [{k:v for k,v in row.items() if k != 'ref'} for row in await backend.records({})] == [
            {'label':'Newest','timestamp':30}, {'label':'Middle','timestamp':20}, {'label':'Old','timestamp':10}]
        wallet.get_user_records.assert_awaited_once_with(record_kind=37375, reverse=True)
    asyncio.run(run())


def test_acorn_read_failure_does_not_become_empty_list():
    logger=RecordReadLogger(logging.getLogger('test-records'), {})
    for reason in ('query_failed', 'decrypt_failed', 'unwrap_failed'):
        with pytest.raises(RuntimeError, match='Records unavailable'):
            logger.warning('op=get_user_records status='+reason+' error=%s', 'private details')


def test_records_page_navigation_privacy_and_states(tmp_path):
    async def run():
        client,sessions,service,backend=setup(tmp_path)
        backend.records=AsyncMock(return_value=[{'label':'<script>Newest</script>','timestamp':30}, {'label':'Old','timestamp':10}])
        async with client:
            assert (await client.get('/account/records')).headers['location']=='/auth/login'
            await login(client,sessions)
            assert 'Connect or create an Acorn' in (await client.get('/account/records')).text
            await client.post('/account/acorn/create',data=form())
            page=await client.get('/account/records')
            assert page.status_code==200
            assert page.headers['cache-control']=='no-store'
            assert page.headers['referrer-policy']=='strict-origin'
            assert 'href="/account/records" aria-current="page"' in page.text
            assert '&lt;script&gt;Newest&lt;/script&gt;' in page.text
            assert page.text.index('Newest&lt;') < page.text.index('>Old <span')
            assert 'SECRET' not in page.text
            balances=await client.get('/account')
            assert 'href="/account" aria-current="page"' in balances.text
            backend.records.return_value=[]
            assert 'No records yet.' in (await client.get('/account/records')).text
            backend.records.side_effect=TimeoutError('PRIVATE')
            page=await client.get('/account/records')
            assert 'Records are unavailable' in page.text and 'No records yet' not in page.text
            assert 'PRIVATE' not in page.text
            await login(client,sessions,sub='someone-else')
            assert 'Connect or create an Acorn' in (await client.get('/account/records')).text
    asyncio.run(run())


@pytest.mark.parametrize('outer_slash', ['', '/'])
def test_folder_includes_its_own_record_and_children(outer_slash):
    from types import SimpleNamespace
    from app.wallet_routes import folder_view
    rows = [
        {'label':outer_slash+'member', 'ref':'parent', 'timestamp':30},
        {'label':outer_slash+'member/current', 'ref':'child', 'timestamp':20},
        {'label':outer_slash+'member/archive/old', 'ref':'nested', 'timestamp':10},
        {'label':outer_slash+'membership', 'ref':'other', 'timestamp':5},
    ]
    result = folder_view(rows, SimpleNamespace(query_params={'view':'folders', 'folder':'/member/'}))
    assert [(r['label'], r['ref']) for r in result['records']] == [('member','parent'), ('current','child')]
    assert [f['label'] for f in result['folders']] == ['archive']
    root = folder_view(rows, SimpleNamespace(query_params={'view':'folders'}))
    assert any(r['ref']=='parent' for r in root['records'])
    assert any(f['label']=='member' for f in root['folders'])
    assert rows[0]['label'] == outer_slash+'member'


def test_nested_folder_keeps_exact_record_reference():
    from types import SimpleNamespace
    from app.wallet_routes import folder_view
    rows = [{'label':'health/prescriptions', 'ref':'exact'},
            {'label':'health/prescriptions/current', 'ref':'child'}]
    result = folder_view(rows, SimpleNamespace(query_params={'view':'folders','folder':'health/prescriptions'}))
    assert [(r['label'],r['ref']) for r in result['records']] == [('prescriptions','exact'),('current','child')]



def test_folder_records_sorted_alphabetically_not_by_timestamp():
    from types import SimpleNamespace
    from app.wallet_routes import folder_view
    rows=[{'label':'Benefits/Zebra','ref':'z','timestamp':30},
          {'label':'Benefits/apple','ref':'a','timestamp':10},
          {'label':'Benefits/Dental','ref':'d','timestamp':20}]
    result=folder_view(rows,SimpleNamespace(query_params={'view':'folders','folder':'Benefits'}))
    assert [r['label'] for r in result['records']]==['apple','Dental','Zebra']
    assert [r['ref'] for r in rows]==['z','a','d']
