"""Terminal isolation, explicit approval and ephemeral record disclosure."""
import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

from app.sessions import MemoryStore
from app.pos_records import fulfil, key, load, router
from test_pos_receiving import env, call


def setup_records(env, monkeypatch, label="WhoAmI"):
    app=env[0]; app.state.store=MemoryStore(); app.state.settings=SimpleNamespace(origin='https://oakgate.example', secure=True)
    app.include_router(router)
    service=app.state.wallets
    calls=[]
    async def records(material):
        return [{'label':label,'ref':'a'*64}]
    async def action(material, name, *args):
        calls.append((name,args))
        return {'descriptor':'acorn:record-presentation:test','expires_at':9999999999}
    async def inspect(material, code, presentation):
        assert presentation is True
        return {'label':label,'payload':{'name':'Alice','text':'<script>never execute</script>'},'blob_data':None,'expires_at':9999999999}
    monkeypatch.setattr(service,'records',records)
    monkeypatch.setattr(service,'record_action',action)
    monkeypatch.setattr(service.backend,'inspect_scanned_record',inspect,raising=False)
    return SimpleNamespace(app=app), calls


@pytest.mark.parametrize("requested,label", [("whoami","WhoAmI"),("myinfo","MyInfo"),("emergency","Emergency"),("member","Member"),("pass","PASS"),("health","HeAlTh"),("benefits","BeNeFiTs")])
def test_start_approve_present_and_replace(env,monkeypatch,requested,label):
    request,calls=setup_records(env,monkeypatch,label)
    async def run():
        start=await call(env,'record-start',{'label':requested});assert start.status_code==200
        ident=start.json()['request_id'];assert '/account/record-request' not in start.json().get('url','')
        assert (await call(env,'record-status',{'request_id':ident})).json()['state']=='waiting'
        assert (await call(env,'record-present',{'request_id':ident})).status_code==409
        await fulfil(request,ident,'owner')
        assert calls[0][0]=='create_record_capability' and calls[0][1][1]=='present'
        assert (await call(env,'record-status',{'request_id':ident})).json()['state']=='ready'
        shown=await call(env,'record-present',{'request_id':ident})
        assert shown.status_code==200 and shown.json()['label']==label
        assert 'Alice' in shown.json()['contents'] and 'descriptor' not in shown.json()
        encrypted=await request.app.state.store.get(key('result',ident));assert 'Alice' not in encrypted
        with pytest.raises(HTTPException):await fulfil(request,ident,'owner')
        await call(env,'record-start',{'label':'whoami'})
        assert (await call(env,'record-present',{'request_id':ident})).status_code==404
        assert await request.app.state.store.get(key('result',ident)) is None
    asyncio.run(run())


def test_scope_expiry_revoke_and_cross_terminal(env,monkeypatch):
    request,_=setup_records(env,monkeypatch)
    async def run():
        assert (await call(env,'record-start',{'label':'private-key'})).status_code==400
        ident=(await call(env,'record-start',{'label':'whoami'})).json()['request_id']
        item=await load(request,ident)
        with pytest.raises(HTTPException):await load(request,ident,{**item['actor'],'id':'other'})
        item['expires']=0
        assert (await call(env,'record-status',{'request_id':ident})).status_code==404
        ident=(await call(env,'record-start',{'label':'whoami'})).json()['request_id']
        env[3].revoke('owner',env[6])
        from app.pos_store import POSDenied
        with pytest.raises(HTTPException) as error:await load(request,ident)
        assert error.value.status_code==403
    asyncio.run(run())


def test_missing_ambiguous_and_concurrent_approval(env,monkeypatch):
    request,calls=setup_records(env,monkeypatch)
    async def run():
        ident=(await call(env,'record-start',{'label':'whoami'})).json()['request_id']
        results=await asyncio.gather(fulfil(request,ident,'owner'),fulfil(request,ident,'owner'),return_exceptions=True)
        assert sum(isinstance(r,dict) for r in results)==1
        assert len(calls)==1
        for rows in [[],[{'label':'whoami','ref':'a'},{'label':'WHOAMI','ref':'b'}]]:
            async def listing(material):return rows
            monkeypatch.setattr(request.app.state.wallets,'records',listing)
            ident=(await call(env,'record-start',{'label':'whoami'})).json()['request_id']
            with pytest.raises(HTTPException):await fulfil(request,ident,'owner')
            assert (await call(env,'record-status',{'request_id':ident})).json()['state']=='unavailable'
        assert len(calls)==1
    asyncio.run(run())


def test_replacement_during_preparation_never_discloses(env,monkeypatch):
    request,_=setup_records(env,monkeypatch)
    async def run():
        began=asyncio.Event();release=asyncio.Event()
        async def action(material,name,*args):
            if name=='create_record_capability':began.set();await release.wait()
            return {'descriptor':'secret'}
        monkeypatch.setattr(request.app.state.wallets,'record_action',action)
        ident=(await call(env,'record-start',{'label':'whoami'})).json()['request_id']
        task=asyncio.create_task(fulfil(request,ident,'owner'));await began.wait()
        await call(env,'record-start',{'label':'whoami'});release.set()
        with pytest.raises(HTTPException):await task
        assert await request.app.state.store.get(key('presentation',ident)) is None
    asyncio.run(run())


def test_nfc_revalidates_after_presentation_and_rejects_revoked_card(env,monkeypatch):
    request,_=setup_records(env,monkeypatch)
    from app.pos_store import POSDenied
    class Cards:
        checks=0
        def balance_authority(self,*args,**kwargs):
            self.checks+=1
            if self.checks==3:raise POSDenied
            return {'owner':'owner','wallet_id':'wallet'}
    cards=Cards()
    async def card_store(request):return cards
    monkeypatch.setattr('app.nfc_routes.card_store',card_store)
    async def run():
        ident=(await call(env,'record-start',{'label':'whoami'})).json()['request_id']
        result=await call(env,'record-nfc',{'request_id':ident,'card_payload':'card'})
        assert result.status_code==403 and cards.checks==3
        assert await request.app.state.store.get(key('presentation',ident)) is None
    asyncio.run(run())


def test_wallet_callback_requires_login_csrf_and_approval(env,monkeypatch):
    request,calls=setup_records(env,monkeypatch)
    session=None
    async def current(request):return session
    monkeypatch.setattr('app.pos_records.current_session',current)
    monkeypatch.setattr('app.pos_records.identity_key',lambda user:'owner')
    async def run():
        nonlocal session
        ident=(await call(env,'record-start',{'label':'whoami'})).json()['request_id']
        async with httpx.AsyncClient(transport=httpx.ASGITransport(request.app),base_url='https://oakgate.example') as client:
            url='/account/record-request/'
            assert (await client.post(url+'approve',data={'csrf':'token','request_id':ident})).status_code==401
            session={'csrf':'token','user':{}}
            assert (await client.post(url+'approve',data={'csrf':'wrong','request_id':ident})).status_code==403
            details=await client.post(url+'details',data={'csrf':'token','request_id':ident})
            assert details.json()['label']=='whoami' and not calls
            assert (await client.post(url+'approve',data={'csrf':'token','request_id':ident})).status_code==200
            assert len(calls)==1
    asyncio.run(run())


def test_wallet_scanner_recognizes_only_same_home_record_request(tmp_path):
    from test_wallets import setup, login, form
    from contextlib import aclosing
    async def run():
        client,sessions,wallets,backend=setup(tmp_path)
        async with aclosing(client):
            await login(client,sessions)
            await client.post('/account/acorn/create',data=form())
            origin=client._transport.app.state.settings.origin
            code=origin+'/account/record-request#'+'a'*43
            response=await client.post('/account/scan',data=form(lightning_payment=code))
            assert response.status_code==303
            assert response.headers['location']=='/account/record-request#'+'a'*43
            response=await client.post('/account/scan',data=form(lightning_payment='https://other.example/account/record-request#'+'a'*43))
            assert response.status_code==200 and 'Open website' in response.text
    asyncio.run(run())


@pytest.mark.parametrize('label', ['member', 'pass', 'health', 'benefits'])
def test_membership_and_pass_use_existing_nfc_presentation(env, monkeypatch, label):
    request,_=setup_records(env,monkeypatch,label.upper())
    class Cards:
        def balance_authority(self,*args,**kwargs):
            return {'owner':'owner','wallet_id':'wallet'}
    async def card_store(request):return Cards()
    monkeypatch.setattr('app.nfc_routes.card_store',card_store)
    async def no_emergency_notice(*args):
        pytest.fail('Only emergency records may notify a contact')
    monkeypatch.setattr('app.emergency_contacts.notify_contact',no_emergency_notice)
    async def run():
        ident=(await call(env,'record-start',{'label':label})).json()['request_id']
        response=await call(env,'record-nfc',{'request_id':ident,'card_payload':'test-card'})
        assert response.status_code==200 and response.json()['state']=='ready'
        response=await call(env,'record-present',{'request_id':ident})
        assert response.status_code==200 and response.json()['label']==label.upper()
        assert 'notification' not in response.json()
        assert (await call(env,'record-start',{'label':'admission'})).status_code==400
    asyncio.run(run())


@pytest.mark.parametrize('media', ['image/png', 'application/pdf; charset=binary'])
def test_present_includes_anchor_profile_and_statement(env, monkeypatch, media):
    request, _ = setup_records(env, monkeypatch)
    async def inspect(*args):
        return {'label': 'whoami', 'payload': '', 'blob_data': b'example',
                'blob_type': media, 'expires_at': 9999999999}
    async def history(*args, **kwargs):
        return {'verification': {'aggregate_state': 'anchored'}, 'candidate_graphs': [
            {'signer_profile': {'display_name': 'Community Centre', 'name': 'centre'},
             'anchor': {'author': 'npub-example', 'content': 'Membership confirmed.', 'created_at': '2026-10-27 15:44 UTC'}},
            {'signer_profile': None,
             'anchor': {'author': 'npub-fallback', 'content': 'Second statement.'}},
        ]}
    monkeypatch.setattr(request.app.state.wallets.backend, 'inspect_scanned_record', inspect)
    monkeypatch.setattr('app.openetr.query_openetr_history', history)
    async def run():
        ident = (await call(env, 'record-start', {'label': 'whoami'})).json()['request_id']
        await fulfil(request, ident, 'owner')
        response = await call(env, 'record-present', {'request_id': ident})
        assert response.status_code == 200
        assert response.json()['attachment']['type'] == media.split(';')[0]
        assert response.json()['publishers'] == [
            {'name': 'Community Centre', 'statement': 'Membership confirmed.',
             'signer': 'npub-example', 'anchored_at': '2026-10-27 15:44 UTC',
             'profile': {'display_name': 'Community Centre', 'name': 'centre', 'about': None, 'address': None}},
            {'name': 'npub-fallback', 'statement': 'Second statement.',
             'signer': 'npub-fallback', 'anchored_at': '',
             'profile': {'display_name': None, 'name': None, 'about': None, 'address': None}},
        ]
    asyncio.run(run())


@pytest.mark.parametrize('media', [None, '', 'application/octet-stream', 'binary/octet-stream', 'application/x-pdf', 'application/pdf; charset=binary'])
def test_pdf_preview_recognizes_generic_content_types(media):
    from app.pos_records import preview_attachment
    attachment, note = preview_attachment(b'%PDF-1.7\nexample', media)
    assert attachment['type'] == 'application/pdf'
    assert note == ''


def test_preview_rejection_distinguishes_size_and_format():
    from app.pos_records import preview_attachment
    assert '5 MiB' in preview_attachment(b'x' * (5 * 1024 * 1024 + 1), 'application/pdf')[1]
    for blob, media in [(b'<html>test</html>', None), (b'%PDF-1.7', 'text/html')]:
        attachment, note = preview_attachment(blob, media)
        assert attachment is None
        assert 'format' in note
