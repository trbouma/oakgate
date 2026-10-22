"""POS receipt ownership, signed amounts and crash-safe retry regression tests."""
import asyncio
import json
import time
from contextlib import closing
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from app.pos_api import create_router
from app.pos_store import POSStore
from app.pos_receiving import TerminalRequests, receive
from app.request_store import RequestStore
from test_pos_activation import device, proof
from test_payments import setup


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv('OAKGATE_SERVICE_NSEC', '31'*32)
    monkeypatch.setenv('OAKGATE_POS_ENABLED','true')
    monkeypatch.setenv('OAKGATE_POS_PUBLIC_URL','https://pos.example')
    fixture = setup(tmp_path)
    service, mint = fixture.service, fixture.mint
    # setup() returns the payment service; use its real journal and fake mint.
    store = POSStore(service.wallets.store, 'https://pos.example')
    pair=device(); key=store.provision('owner','Counter')
    session=store.activate(key,pair[1],**proof(pair[0],store.activation_challenge(key,pair[1])))['session']
    app=FastAPI(); app.state.pos=store; app.state.pos_tasks=set(); app.state.wallets=service.wallets
    app.state.payments=service; app.state.rates=None; app.state.ecash=None; app.state.send=None
    app.include_router(create_router())
    return app, service, mint, store, pair, session, key.split('.')[1]


def body(key='test-request-000001', **kwargs):
    return dict(request_key=key, amount='100', asset='', currency='SATS', quoted_rate='', **kwargs)


async def call(env, op, data, *, session=None, pair=None):
    app, service, mint, store, default_pair, default_session, _=env
    pair=pair or default_pair; session=session or default_session
    payload=json.dumps(data,separators=(',',':'))
    challenge=store.challenge(session,op,payload)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='https://oakgate.example') as client:
        return await client.post('/api/pos/v1/'+op,json={'payload':payload,**proof(pair[0],challenge)},headers={'Authorization':'Bearer '+session})


def test_cash_retry_concurrency_restart_and_receipt(env):
    async def run():
        first,second=await asyncio.gather(call(env,'receive',body()),call(env,'receive',body()))
        assert first.status_code==second.status_code==200
        again=await call(env,'receive',body())
        assert again.json()['code'].startswith('lnbc')
        assert len(env[2].rows)==1
        with closing(env[1].wallets.store.connect()) as db:
            assert db.execute('SELECT count(*) FROM wallet_requests').fetchone()[0]==1
        assert 'owner' not in again.json() and 'payment_id' not in again.json()
        # Lose only the POS ticket after a simulated crash: recover the exact quote.
        with closing(env[1].wallets.store.connect()) as db, db:
            db.execute('DELETE FROM wallet_requests')
        recovered=await call(env,'receive',body())
        assert recovered.json()['code']==again.json()['code'] and len(env[2].rows)==1
        row=TerminalRequests(env[1].wallets.store).find({'id':env[6],'owner':'owner'},body()['request_key'])
        payment=env[1].store.get(row['id']); payment['paid_at']=time.time(); env[1].store.save(payment)
        status=await call(env,'receipt',{'request_key':body()['request_key']})
        assert status.json()['state']=='detected' and 'code' not in status.json()
        payment['history_written']=True; env[1].store.save(payment)
        assert len(env[2].rows)==1
    asyncio.run(run())


def test_body_tamper_duplicate_key_and_limits(env):
    async def run():
        app,service,mint,store,pair,session,_=env
        payload=json.dumps(body(),separators=(',',':'))
        challenge=store.challenge(session,'receive',payload)
        altered=json.dumps({**body(),'amount':'200'},separators=(',',':'))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='https://oakgate.example') as client:
            response=await client.post('/api/pos/v1/receive',json={'payload':altered,**proof(pair[0],challenge)},headers={'Authorization':'Bearer '+session})
            assert response.status_code==403
        assert not mint.rows
        assert (await call(env,'receive',body())).status_code==200
        assert (await call(env,'receive',{**body(),'amount':'200'})).status_code==409
        for change in ({'amount':'0'},{'amount':'1.5'},{'amount':'1000001'},{'asset':'social-npub'},{'owner':'other'}):
            assert (await call(env,'receive',{**body('test-request-000002'),**change})).status_code==400
        assert len(mint.rows)==1
    asyncio.run(run())


def test_terminal_isolation_revocation_and_unknown_request(env):
    async def run():
        await call(env,'receive',body())
        store=env[3]; pair=device(); key=store.provision('owner','Other')
        token=store.activate(key,pair[1],**proof(pair[0],store.activation_challenge(key,pair[1])))['session']
        assert (await call(env,'receipt',{'request_key':body()['request_key']},session=token,pair=pair)).status_code==404
        assert (await call(env,'receipt',{'request_key':'unknown-request-0000'})).status_code==404
        challenge=store.challenge(env[5],'receipt',json.dumps({'request_key':body()['request_key']}))
        store.revoke('owner',env[6])
        async with httpx.AsyncClient(transport=httpx.ASGITransport(env[0]),base_url='https://oakgate.example') as client:
            response=await client.post('/api/pos/v1/receipt',json={'payload':json.dumps({'request_key':body()['request_key']}),**proof(env[4][0],challenge)},headers={'Authorization':'Bearer '+env[5]})
            assert response.status_code==403
        assert len(env[2].rows)==1
    asyncio.run(run())


def test_crash_before_invoice_is_not_reexecuted(env):
    async def run():
        payload=json.dumps(body(),separators=(',',':'))
        requests=TerminalRequests(env[1].wallets.store)
        with closing(env[1].wallets.store.connect()) as db:
            wallet=db.execute("SELECT wallet_id FROM wallets WHERE owner='owner'").fetchone()[0]
        row,_=requests.reserve({'id':env[6],'owner':'owner','wallet_id':wallet},body()['request_key'],payload)
        with closing(env[1].wallets.store.connect()) as db, db:
            db.execute('UPDATE pos_receipts SET created=?',(time.time()-200,))
        result=await call(env,'receive',body())
        assert result.json()['state']=='unconfirmed' and not env[2].rows
    asyncio.run(run())


def test_clear_request_uses_acorn_and_options_never_expose_balances(env, monkeypatch):
    async def run():
        app=env[0]; calls=[]
        async def assets(owner):
            return [{'id':'asset-1','mint':'https://clear.example','unit':'cmu-test','amount':999,
                     'display_name':'Care','display_unit':'care credits'}]
        async def create(material,units,asset,description):
            calls.append((units,asset['unit'])); return 'creqBmock'
        async def state(material,item): return 'detected'
        app.state.send=SimpleNamespace(clear_assets=assets)
        app.state.ecash=SimpleNamespace(clear_available=True,wake_owner=lambda owner:None)
        monkeypatch.setattr(app.state.wallets.backend,'create_clear_request',create)
        monkeypatch.setattr(app.state.wallets.backend,'clear_request_status',state)
        monkeypatch.setattr('app.pos_receiving.decode_payment_request',lambda code:SimpleNamespace(payment_id='clear-request-1'))
        options=(await call(env,'receive-config',{})).json()
        assert options['assets']==[{'id':'asset-1','display_name':'Care','display_unit':'care credits'}]
        assert '999' not in json.dumps(options)
        payload={**body(),'asset':'asset-1'}
        result=await call(env,'receive',payload)
        assert result.json()['code']=='creqBmock' and result.json()['state']=='detected'
        await call(env,'receive',payload)
        assert calls==[(100,'cmu-test')] and not env[2].rows
    asyncio.run(run())


def test_proxy_round_trip_for_receiving(env):
    from cryptography.fernet import Fernet
    from pos.config import POSSettings
    from pos.main import create_app
    async def run():
        app,_,mint,store,_,_,_=env
        key=store.provision('owner','Proxy counter'); pair=device()
        pos=create_app(POSSettings(True,'https://pos.example','https://oakgate.example',Fernet.generate_key().decode()),httpx.ASGITransport(app))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(pos),base_url='https://pos.example',headers={'Origin':'https://pos.example'}) as browser:
            challenge=(await browser.post('/api/activation-challenges',json={'credential':key,'public_key':pair[1]})).json()
            activated=await browser.post('/api/activate',json={'credential':key,'public_key':pair[1],**proof(pair[0],challenge)})
            assert activated.status_code==200
            for op,data in [('receive-config',{}),('receive',body()),('receipt',{'request_key':body()['request_key']})]:
                payload=json.dumps(data,separators=(',',':'))
                challenge=(await browser.post('/api/challenges',json={'operation':op,'payload':payload})).json()
                response=await browser.post('/api/'+op,json={'payload':payload,**proof(pair[0],challenge)})
                assert response.status_code==200, response.text
                assert 'owner' not in response.json() and 'nsec' not in response.text and 'wallet_id' not in response.text
                assert response.headers['cache-control']=='no-store'
            assert len(mint.rows)==1
    asyncio.run(run())


def test_failed_quote_never_creates_a_second_quote(env, monkeypatch):
    async def run():
        calls=[]
        async def failed(*args):
            calls.append(1); raise TimeoutError('private detail')
        monkeypatch.setattr(env[2],'quote',failed)
        await call(env,'receive',body())
        await call(env,'receive',body())
        assert calls==[1]
        with closing(env[1].wallets.store.connect()) as db:
            assert db.execute('SELECT state FROM incoming_payments').fetchone()[0]=='failed'
    asyncio.run(run())


def test_fiat_conversion_is_server_checked(env):
    async def run():
        env[0].state.rates=SimpleNamespace(enabled=True,rows=lambda:[{'code':'CAD','fiat_per_btc':'150000','stale':False}])
        payload={**body(),'amount':'1.50','currency':'CAD','quoted_rate':'150000'}
        response=await call(env,'receive',payload)
        assert response.json()['amount']==1000
        assert (await call(env,'receive',{**payload,'request_key':'test-request-000002','quoted_rate':'100000'})).status_code==400
        assert len(env[2].rows)==1
    asyncio.run(run())


def test_disconnect_does_not_cancel_original_preparation(env, monkeypatch):
    async def run():
        started=asyncio.Event(); release=asyncio.Event()
        original=env[2].quote
        async def delayed(*args):
            started.set(); await release.wait(); return await original(*args)
        monkeypatch.setattr(env[2],'quote',delayed)
        attempt=asyncio.create_task(call(env,'receive',body()))
        await started.wait(); attempt.cancel()
        with pytest.raises(asyncio.CancelledError): await attempt
        assert env[0].state.pos_tasks
        release.set(); await asyncio.gather(*env[0].state.pos_tasks)
        result=await call(env,'receive',body())
        assert result.json()['code'].startswith('lnbc') and len(env[2].rows)==1
    asyncio.run(run())
