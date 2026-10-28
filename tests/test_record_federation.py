import asyncio
import json
import time
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
from test_card_federation import federation
from app import record_federation as rf
from app.pos_records import operation, key, unseal, load


@pytest.fixture
def homes(federation, monkeypatch):
    f = federation
    w = f.issuer.app.state.wallets
    w.records = AsyncMock(return_value=[{'label':'Benefits/Health','ref':'health'}, {'label':'Benefits/Dental','ref':'dental'}])
    w.record_action = AsyncMock(side_effect=lambda m, op, ref, *args: {'descriptor': ref})
    w.backend.inspect_scanned_record = AsyncMock(side_effect=lambda m, ref, p: {
        'label':'Benefits/' + ref.title(), 'payload':ref, 'blob_data':None, 'expires_at':time.time()+120})
    f.receipts = []
    monkeypatch.setattr('app.presentation_receipts.schedule_receipt', lambda *args: f.receipts.append(args))
    async def fetch(url, *, body=None):
        for home, signer in ((f.merchant,f.mkey),(f.issuer,f.ikey)):
            if url == home.app.state.settings.origin + '/info':
                return {'service_identity':signer.public_info()}
            if url == home.app.state.settings.origin + rf.PATH:
                return await rf.execute(home, body, fetch)
        raise AssertionError(url)
    monkeypatch.setattr(rf, 'transport', fetch)
    f.transport = fetch
    return f


async def start(f):
    item = await operation(f.merchant, f.actor, 'record-start', json.dumps({'label':'benefits'}))
    ident = item['request_id']
    token = await rf.begin(f.issuer, 'alice', 'https://merchant.example/account/record-request#'+ident)
    return ident, token


def test_wallet_approval_selection_display_and_cancel(homes):
    f = homes
    async def run():
        ident, token = await start(f)
        details = await rf.wallet_action(f.issuer, 'alice', token, 'details')
        assert 'https://merchant.example' in details['name']
        assert len(details['records']) == 2
        f.issuer.app.state.wallets.record_action.assert_not_awaited()
        selected = details['records'][0]['id']
        await rf.wallet_action(f.issuer, 'alice', token, 'approve', [selected])
        with pytest.raises(ValueError):
            await rf.wallet_action(f.issuer, 'alice', token, 'approve', [selected])
        status = await operation(f.merchant, f.actor, 'record-status', json.dumps({'request_id':ident}))
        assert len(status['records']) == 1
        with pytest.raises(ValueError):
            await operation(f.merchant, f.actor, 'record-present', json.dumps({'request_id':ident,'record_id':details['records'][1]['id']}))
        result = await operation(f.merchant, f.actor, 'record-present', json.dumps({'request_id':ident}))
        assert result['contents'] == 'dental'
        assert await operation(f.merchant, f.actor, 'record-present', json.dumps({'request_id':ident})) == result
        assert len(f.receipts) == 1
        assert f.issuer.app.state.wallets.record_action.await_count == 1
        item = await load(f.merchant, ident)
        remote = unseal(f.merchant, item, await f.merchant.app.state.store.get(key('wallet-remote',ident)))
        await operation(f.merchant, f.actor, 'record-cancel', json.dumps({'request_id':ident}))
        with pytest.raises(ValueError):
            await rf.private(f.issuer,'wallet-grant',remote['grant'])
    asyncio.run(run())


def test_owner_binding_replacement_and_single_record(homes):
    f=homes
    async def run():
        ident, token = await start(f)
        with pytest.raises(ValueError):
            await rf.wallet_action(f.issuer,'someone-else',token,'details')
        d=await rf.wallet_action(f.issuer,'alice',token,'details')
        await operation(f.merchant,f.actor,'record-start',json.dumps({'label':'benefits'}))
        with pytest.raises(Exception):
            await rf.wallet_action(f.issuer,'alice',token,'approve',[d['records'][0]['id']])
        f.issuer.app.state.wallets.records.return_value=[{'label':'Benefits/Health','ref':'health'}]
        ident,token=await start(f)
        d=await rf.wallet_action(f.issuer,'alice',token,'details')
        assert len(d['records'])==1
        await rf.wallet_action(f.issuer,'alice',token,'approve',[d['records'][0]['id']])
        assert (await operation(f.merchant,f.actor,'record-present',json.dumps({'request_id':ident})))['contents']=='health'
    asyncio.run(run())


def test_tampering_peer_policy_and_grant_binding(homes, monkeypatch):
    f=homes
    async def run():
        ident,token=await start(f)
        d=await rf.wallet_action(f.issuer,'alice',token,'details')
        await rf.wallet_action(f.issuer,'alice',token,'approve',[d['records'][0]['id']])
        item=await load(f.merchant,ident)
        source=unseal(f.merchant,item,await f.merchant.app.state.store.get(key('wallet-remote',ident)))
        with pytest.raises(ValueError):
            await rf.rpc(f.merchant,'https://issuer.example',f.ikey.npub,'present','a'*43,
                         {'grant':source['grant'],'record_id':d['records'][0]['id']})
        with pytest.raises(ValueError):
            await rf.rpc(f.merchant,'https://issuer.example',f.mkey.npub,'details',ident,{})
        async def swapped(url, **kwargs):
            if kwargs:
                return {'event':f.ikey.card_message({'request':'wrong','result':{}},'wallet-record-result')}
            return await f.transport(url)
        with pytest.raises(ValueError):
            await rf.rpc(f.merchant,'https://issuer.example',f.ikey.npub,'present',ident,{},swapped)
        monkeypatch.setenv('OAKGATE_CARD_TRUSTED_INSTANCES', f.ikey.npub)
        with pytest.raises(ValueError):
            await rf.begin(f.issuer,'alice','https://merchant.example/account/record-request#'+ident)
        # Neither a second wallet approval nor an NFC attempt may replace the presenter.
        with pytest.raises(Exception):
            await operation(f.merchant,f.actor,'record-nfc',json.dumps({'request_id':ident,'card_payload':f.card['payload']}))
    asyncio.run(run())


@pytest.mark.parametrize('url', ['http://merchant.example/account/record-request#'+'a'*43,
    'https://user@merchant.example/account/record-request#'+'a'*43,
    'https://merchant.example:8080/account/record-request#'+'a'*43,
    'https://merchant.example/account/record-request?url=x#'+'a'*43])
def test_invalid_destination(url):
    with pytest.raises(ValueError): rf.destination(url)


def test_replacement_blocks_direct_grant_reuse_and_expiry(homes):
    f=homes
    async def run():
        ident,token=await start(f)
        d=await rf.wallet_action(f.issuer,'alice',token,'details')
        await rf.wallet_action(f.issuer,'alice',token,'approve',[d['records'][0]['id']])
        item=await load(f.merchant,ident)
        source=unseal(f.merchant,item,await f.merchant.app.state.store.get(key('wallet-remote',ident)))
        await operation(f.merchant,f.actor,'record-start',json.dumps({'label':'benefits'}))
        with pytest.raises(Exception):
            await rf.rpc(f.merchant,'https://issuer.example',f.ikey.npub,'present',ident,
                         {'grant':source['grant'],'record_id':d['records'][0]['id']})
        f.issuer.app.state.wallets.record_action.assert_not_awaited()
        ident,token=await start(f)
        _,ticket=await rf.private(f.issuer,'wallet-approval',token,'alice')
        ticket['expires']=0
        sealed=f.issuer.app.state.wallets.store.seal('alice',ticket)
        await f.issuer.app.state.store.put(key('wallet-approval',token),sealed.decode() if isinstance(sealed,bytes) else sealed,120)
        with pytest.raises(ValueError): await rf.wallet_action(f.issuer,'alice',token,'details')
    asyncio.run(run())


def test_remote_wallet_callback_requires_session_and_csrf(tmp_path, monkeypatch):
    from test_wallets import setup, login, form
    monkeypatch.setenv('OAKGATE_POS_ENABLED','true')
    action=AsyncMock(return_value={'state':'ready'})
    monkeypatch.setattr(rf,'wallet_action',action)
    async def run():
        client,sessions,service,backend=setup(tmp_path)
        async with client:
            data={'remote':'1','request_id':'a'*43,'selected':'["record"]'}
            assert (await client.post('/account/record-request/approve',data=data)).status_code==401
            await login(client,sessions)
            assert (await client.post('/account/record-request/approve',data=data)).status_code==403
            action.assert_not_awaited()
            assert (await client.post('/account/record-request/approve',data={'csrf':'csrf-test',**data})).status_code==200
            action.assert_awaited_once()
    asyncio.run(run())
