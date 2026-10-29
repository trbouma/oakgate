import asyncio
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock

import pytest
from cryptography.fernet import Fernet

from app.custody import CustodyStore, HandleTaken
from app.wallets import AcornBackend
from test_wallets import setup, login, form


def test_handle_uniqueness_restart_and_release(tmp_path):
    key=Fernet.generate_key()
    store=CustodyStore(tmp_path,key)
    store.save_handle('one',' Tim ')
    assert CustodyStore(tmp_path,key).preference('one')=='Tim'
    with pytest.raises(HandleTaken): store.save_handle('two','tim')
    store.save_handle('two','Alice')
    with pytest.raises(HandleTaken): store.save_handle('two','TIM')
    assert store.preference('two')=='Alice'
    store.save_handle('one','')
    store.save_handle('two','tim')
    assert store.preference('two')=='tim'
    def claim(owner):
        try:
            CustodyStore(tmp_path,key).save_handle(owner,'Shared')
            return True
        except HandleTaken: return False
    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(claim,['three','four']))==[False,True]


@pytest.mark.parametrize('handle',['ab','x'*33,'a b','<script>','éclair','_name','a/b'])
def test_invalid_handles(tmp_path,handle):
    with pytest.raises(ValueError):
        CustodyStore(tmp_path,Fernet.generate_key()).save_handle('owner',handle)


def test_preferences_and_detail_authorization(tmp_path):
    async def run():
        client,sessions,service,backend=setup(tmp_path)
        reference='a'*64
        backend.record_detail=AsyncMock(return_value={'label':'My record','contents':'<script>alert(1)</script>\nline two'})
        async with client:
            for url in ['/account/preferences','/account/records/'+reference]:
                assert (await client.get(url)).headers['location']=='/auth/login'
            owner=await login(client,sessions)
            assert (await client.post('/account/preferences',data=form(csrf='wrong',handle='Tim'))).status_code==403
            assert (await client.post('/account/preferences',data=form(handle='Tim'),headers={'origin':'https://evil.example'})).status_code==403
            assert (await client.post('/account/preferences',data=form(handle='Tim'))).status_code==200
            assert service.store.preference(owner)=='Tim'
            assert 'Hello, Tim.' not in (await client.get('/account')).text
            assert 'Your Funds' in (await client.get('/account')).text
            await client.post('/account/acorn/create',data=form())
            page=await client.get('/account/records/'+reference)
            assert page.status_code==200 and page.headers['cache-control']=='no-store'
            assert '&lt;script&gt;' in page.text and '<script>' not in page.text
            assert 'href="/account/records"' in page.text
            backend.record_detail.return_value=None
            assert (await client.get('/account/records/'+'b'*64)).status_code==404
            assert (await client.get('/account/records/not-valid')).status_code==404
            backend.record_detail.side_effect=TimeoutError('PRIVATE')
            page=await client.get('/account/records/'+reference)
            assert page.status_code==503 and 'PRIVATE' not in page.text
            await login(client,sessions,sub='someone-else')
            assert (await client.post('/account/preferences',data=form(handle='tim'))).status_code==409
            assert (await client.get('/account/records/'+reference)).status_code==404
    asyncio.run(run())


def test_real_adapter_detail_uses_filtered_records_only():
    async def run():
        import logging
        class Wallet:
            logger=logging.getLogger('records-test')
            get_user_records=AsyncMock(return_value=[{'id':'1'*64,'tag':['Note'],'timestamp':5,'payload':{'message':'hello','count':3}}])
            get_user_record=AsyncMock(side_effect=lambda **kw: {'id':'1'*64,'tag':['Note'],'timestamp':5,'payload':{'message':'hello','count':3}} if kw['event_id']=='1'*64 else None)
            get_user_records_page=AsyncMock(return_value={'records':[{'id':'1'*64,'tag':['Note'],'timestamp':5}], 'next_cursor':None})
        backend=AcornBackend()
        backend.wallet=lambda material: Wallet()
        rows=await backend.records({})
        detail=await backend.record_detail({'relay':'wss://home.example'},rows[0]['ref'])
        assert detail['label']=='Note' and '"message": "hello"' in detail['contents']
        assert await backend.record_detail({'relay':'wss://home.example'},'f'*64) is None
    asyncio.run(run())
