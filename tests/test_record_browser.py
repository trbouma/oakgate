import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from cryptography.fernet import Fernet
from starlette.exceptions import HTTPException
from app.record_browser import load_page
from app.wallets import AcornBackend


def test_cursor_encrypted_scoped_and_empty_page_continues():
    async def run():
        cache = {}
        async def put(key, value, ttl):
            assert ttl == 900
            cache[key] = value
        store = SimpleNamespace(put=put, get=AsyncMock(side_effect=lambda key:cache.get(key)))
        service = SimpleNamespace(store=SimpleNamespace(cipher=Fernet(Fernet.generate_key())),
            records_page=AsyncMock(return_value={'records':[], 'next_cursor':'PRIVATE_CURSOR'}))
        request = SimpleNamespace(query_params={}, app=SimpleNamespace(state=SimpleNamespace(store=store)))
        material = {'npub':'wallet', 'relay':'wss://home.example'}
        page = await load_page(request, service, 'owner', material)
        assert not page['has_page_token']
        assert page['next_page_url']
        assert 'PRIVATE_CURSOR' not in str(cache) + page['next_page_url']
        token = page['next_page_url'].split('page=')[1]
        request.query_params = {'page':token}
        service.records_page.return_value = {'records':[], 'next_cursor':None}
        page = await load_page(request, service, 'owner', material)
        assert page['has_page_token'] and page['next_page_url'] is None
        service.records_page.assert_awaited_with(material, 'PRIVATE_CURSOR')
        for owner, wallet, query in [
            ('other',material,{'page':token}),
            ('owner',{**material,'npub':'other'},{'page':token}),
            ('owner',{**material,'relay':'wss://other.example'},{'page':token}),
            ('owner',material,{'page':token,'view':'folders'}),
            ('owner',material,{'page':'f'*32}),
        ]:
            request.query_params=query
            with pytest.raises(HTTPException) as exc:
                await load_page(request, service, owner, wallet)
            assert exc.value.status_code == 400
    asyncio.run(run())


def test_direct_detail_and_metadata_only_page():
    async def run():
        row={'id':'a'*64,'tag':['health/current'],'timestamp':123,'payload':'PRIVATE'}
        wallet=SimpleNamespace(get_user_record=AsyncMock(return_value=row),
            get_user_records_page=AsyncMock(return_value={'records':[row],'next_cursor':'next'}))
        backend=AcornBackend()
        backend.wallet=lambda material:wallet
        material={'relay':'wss://home.example'}
        detail=await backend.record_detail(material,'a'*64)
        assert detail['contents']=='PRIVATE'
        wallet.get_user_records_page.assert_not_awaited()
        wallet.get_user_record.assert_awaited_once_with(event_id='a'*64,relay=material['relay'])
        result=await backend.records_page(material,'cursor')
        assert result=={'records':[{'label':'health/current','timestamp':123,'ref':'a'*64}],'next_cursor':'next'}
        wallet.get_user_records_page.assert_awaited_once_with(page_size=100,cursor='cursor',relay=material['relay'])
    asyncio.run(run())


def test_legacy_link_search_continues_past_empty_page_and_revalidates():
    async def run():
        row={'id':'a'*64,'tag':'note','payload':'hello'}
        wallet=SimpleNamespace(get_user_record=AsyncMock(side_effect=[None,row]),
            get_user_records_page=AsyncMock(side_effect=[
                {'records':[],'next_cursor':'next'}, {'records':[row],'next_cursor':None}]))
        backend=AcornBackend()
        backend.wallet=lambda material:wallet
        assert (await backend.record_detail({'relay':'wss://home.example'},backend.record_ref(row)))['contents']=='hello'
        assert wallet.get_user_record.await_count==2
        assert wallet.get_user_record.await_args.kwargs['event_id']==row['id']
        assert wallet.get_user_records_page.await_args.kwargs['cursor']=='next'
    asyncio.run(run())


def test_legacy_search_failure_is_not_missing():
    async def run():
        wallet=SimpleNamespace(get_user_record=AsyncMock(return_value=None),
            get_user_records_page=AsyncMock(return_value={'records':[],'next_cursor':'repeat'}))
        backend=AcornBackend()
        backend.wallet=lambda material:wallet
        with pytest.raises(ValueError,match='did not advance'):
            await backend.record_detail({'relay':'wss://home.example'},'a'*64)
        wallet.get_user_records_page.side_effect=TimeoutError()
        with pytest.raises(TimeoutError):
            await backend.record_detail({'relay':'wss://home.example'},'a'*64)
    asyncio.run(run())


def test_records_route_renders_paging_after_empty_discovery(tmp_path):
    from test_wallets import setup, login, form
    async def run():
        client,sessions,service,backend=setup(tmp_path)
        backend.records_page=AsyncMock(side_effect=[
            {'records':[],'next_cursor':'next'},
            {'records':[{'label':'Later record','timestamp':1,'ref':'a'*64}],'next_cursor':None}])
        async with client:
            await login(client,sessions)
            await client.post('/account/acorn/create',data=form())
            page=await client.get('/account/records')
            assert page.status_code==200
            assert 'No records on this page.' in page.text
            assert 'Next page' in page.text and 'First page' not in page.text
            import re
            link=re.search(r'href="(/account/records\?page=[a-f0-9]+)"',page.text).group(1)
            page=await client.get(link)
            assert page.status_code==200
            assert 'Later record' in page.text and 'First page' in page.text
            assert '/account/records/'+ 'a'*64 in page.text
    asyncio.run(run())
