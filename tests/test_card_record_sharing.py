import asyncio
import time
from unittest.mock import AsyncMock

import pytest

from test_card_federation import federation
from app import card_record_sharing as sharing
from app.card_payments import digest
from app.record_capabilities import RecordCapabilities
from app.request_store import RequestStore


@pytest.fixture
def network(federation, monkeypatch):
    f = federation
    f.rows = []
    service = f.issuer.app.state.wallets
    service.records = AsyncMock(side_effect=lambda _: list(f.rows))
    service.record_exists = AsyncMock(side_effect=lambda _, label: any(r['label']==label for r in f.rows))
    service.backend.inspect_scanned_record = AsyncMock(return_value={'expires_at': time.time()+120})
    async def accept(material, code, label):
        f.rows.append({'label': label, 'ref': 'a'*64})
        return {'status': 'OK'}
    service.backend.accept_scanned_record = AsyncMock(side_effect=accept)
    async def fetch(url, *, body=None):
        if url.endswith('/info'):
            return await f.fetch(url)
        assert url == 'https://issuer.example' + sharing.PATH
        return await sharing.execute(f.issuer, body, fetch)
    monkeypatch.setattr(sharing, 'transport', fetch)
    f.terms = {'descriptor': 'private-transfer-code', 'label': 'benefits/health',
               'expires': int(time.time()+120), 'wallet': f.actor['wallet_id']}
    f.ident = '1'*32
    return f


def test_two_home_resolution_delivery_and_replay(network):
    f = network
    async def run():
        result = await sharing.call(f.merchant, f.card['payload'], 'resolve', f.ident, {})
        assert result == {'recipient': 'alice', 'wallet': f.actor['wallet_id']}
        for op in ['deliver', 'deliver', 'status']:
            assert await sharing.call(f.merchant, f.card['payload'], op, f.ident, f.terms) == {'state': 'complete'}
        assert f.issuer.app.state.wallets.backend.accept_scanned_record.await_count == 1
    asyncio.run(run())


def test_local_delivery_uses_same_protocol(network):
    f = network
    async def run():
        assert await sharing.call(f.issuer, f.card['payload'], 'deliver', f.ident, f.terms) == {'state': 'complete'}
    asyncio.run(run())


def test_collision_is_case_insensitive_and_never_overwritten(network):
    f=network
    f.rows.append({'label': 'Benefits/Health', 'ref': 'b'*64})
    async def run():
        assert await sharing.call(f.merchant, f.card['payload'], 'deliver', f.ident, f.terms) == {'state': 'rejected'}
        assert await sharing.call(f.merchant, f.card['payload'], 'deliver', f.ident, f.terms) == {'state': 'rejected'}
        f.issuer.app.state.wallets.backend.accept_scanned_record.assert_not_awaited()
    asyncio.run(run())


def test_uncertain_write_is_never_retried(network):
    f=network
    async def uncertain(*args):
        f.rows.append({'label': f.terms['label'], 'ref':'a'*64})
        raise TimeoutError()
    f.issuer.app.state.wallets.backend.accept_scanned_record.side_effect=uncertain
    async def run():
        for op in ['deliver', 'status', 'deliver']:
            assert await sharing.call(f.merchant, f.card['payload'], op, f.ident, f.terms) == {'state':'review'}
        assert f.issuer.app.state.wallets.backend.accept_scanned_record.await_count == 1
        token=f.issuer.app.state.wallets.store.acquire('alice')
        f.issuer.app.state.wallets.store.release('alice',token)
    asyncio.run(run())


def test_missing_status_does_not_import(network):
    f=network
    async def run():
        assert await sharing.call(f.merchant,f.card['payload'],'status',f.ident,f.terms)=={'state':'review'}
        f.issuer.app.state.wallets.backend.accept_scanned_record.assert_not_awaited()
    asyncio.run(run())


def test_expired_and_changed_terms_rejected(network):
    f=network
    async def run():
        with pytest.raises(ValueError):
            await sharing.call(f.merchant,f.card['payload'],'deliver',f.ident,{**f.terms,'expires':1})
        await sharing.call(f.merchant,f.card['payload'],'deliver',f.ident,f.terms)
        with pytest.raises(ValueError):
            await sharing.call(f.merchant,f.card['payload'],'status',f.ident,{**f.terms,'label':'changed'})
    asyncio.run(run())


def test_home_allowlist(network,monkeypatch):
    f=network
    monkeypatch.setenv('OAKGATE_CARD_TRUSTED_INSTANCES',f.ikey.npub)
    async def run():
        with pytest.raises(ValueError):
            await sharing.call(f.merchant,f.card['payload'],'deliver',f.ident,f.terms)
        f.issuer.app.state.wallets.backend.accept_scanned_record.assert_not_awaited()
    asyncio.run(run())


def test_concurrent_delivery_only_imports_once(network):
    f=network
    async def run():
        results=await asyncio.gather(*(sharing.call(f.merchant,f.card['payload'],'deliver',f.ident,f.terms) for _ in range(2)))
        assert {'state':'complete'} in results
        assert f.issuer.app.state.wallets.backend.accept_scanned_record.await_count==1
    asyncio.run(run())


def test_sender_retry_only_queries_status(network):
    f=network
    custody=f.merchant.app.state.wallets.store
    share=RecordCapabilities(custody).save('alice',{'purpose':'share','descriptor':f.terms['descriptor'],'expires_at':f.terms['expires']})
    data={'purpose':'card-record-out','share':share,'card':f.card['payload'],'terms':f.terms}
    ident=RequestStore(custody).save('alice',data)
    item=RequestStore(custody).get('alice',ident)
    async def run():
        assert await sharing.deliver(f.merchant,f.merchant.app.state.wallets,'alice',item)=='complete'
        assert await sharing.deliver(f.merchant,f.merchant.app.state.wallets,'alice',item,False)=='complete'
        assert f.issuer.app.state.wallets.backend.accept_scanned_record.await_count==1
    asyncio.run(run())


def test_browser_disconnect_does_not_cancel_write(network):
    f=network
    async def run():
        started,release=asyncio.Event(),asyncio.Event()
        async def accept(*args):
            started.set();await release.wait()
            f.rows.append({'label':f.terms['label'],'ref':'a'*64})
            return {'status':'OK'}
        f.issuer.app.state.wallets.backend.accept_scanned_record.side_effect=accept
        task=asyncio.create_task(sharing.protected(f.merchant,sharing.call(f.merchant,f.card['payload'],'deliver',f.ident,f.terms)))
        await started.wait();task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        release.set()
        await asyncio.gather(*f.merchant.app.state.pos_tasks)
        assert await sharing.call(f.merchant,f.card['payload'],'status',f.ident,f.terms)=={'state':'complete'}
    asyncio.run(run())


def test_web_review_requires_owner_csrf_and_confirmation(tmp_path, monkeypatch):
    from test_wallets import setup, login, form
    monkeypatch.setattr(sharing, 'pinned_issuer', lambda card: ('https://issuer.example', 'public-key'))
    calls = AsyncMock(return_value={'recipient':'alice', 'wallet':'a'*64})
    monkeypatch.setattr(sharing, 'call', calls)
    async def run():
        client,sessions,service,backend=setup(tmp_path)
        async with client:
            assert (await client.get('/account/record-card/'+'a'*32)).status_code==401
            owner=await login(client,sessions)
            backend.inspect_scanned_record = AsyncMock(return_value={'label':'member', 'originator_handle':'tom', 'sharing_fingerprint':'a'*64})
            await client.post('/account/acorn/create',data=form())
            ident=RecordCapabilities(service.store).save(owner,{'purpose':'share','label':'member','descriptor':'private-code','expires_at':int(time.time()+120)})
            url='/account/record-shares/'+ident+'/card'
            assert (await client.post(url,data={'card':'secret'})).status_code==403
            page=await client.post(url,data=form(card='secret'))
            assert page.status_code==303
            ticket_url=page.headers['location']
            review=await client.get(ticket_url)
            assert 'AAAAAAAA' in review.text
            assert 'Confirm sharing' in review.text and 'https://issuer.example' in review.text
            assert 'private-code' not in review.text and 'secret' not in review.text
            assert (await client.post(ticket_url,data=form())).status_code==400
            calls.return_value={'state':'complete'}
            result=await client.post(ticket_url,data=form(confirmed='yes'))
            assert result.status_code==200 and 'Record received' in result.text
            assert calls.await_args.args[2]=='deliver'
            assert calls.await_args.args[4]['label']=='a'*64
            result=await client.post(ticket_url,data=form(confirmed='yes'))
            assert calls.await_args.args[2]=='status'
            other=await login(client,sessions,sub='other')
            service.store.insert(other,{'npub':'other','relay':'wss://relay.example'},'active')
            assert (await client.get(ticket_url)).status_code==404
            assert (await client.post(ticket_url,data=form(confirmed='yes'))).status_code==404
    asyncio.run(run())


def test_revoked_card_cannot_receive(network):
    f=network
    f.cards.revoke('alice',f.card['card_id'])
    async def run():
        with pytest.raises(Exception):
            await sharing.call(f.merchant,f.card['payload'],'deliver',f.ident,f.terms)
        f.issuer.app.state.wallets.backend.accept_scanned_record.assert_not_awaited()
    asyncio.run(run())


def test_changed_issuer_pin_is_rejected_before_sending_card(network,monkeypatch):
    f=network
    fetch=AsyncMock(return_value={'service_identity':f.mkey.public_info()})
    monkeypatch.setattr(sharing,'transport',fetch)
    async def run():
        with pytest.raises(ValueError,match='identity changed'):
            await sharing.call(f.merchant,f.card['payload'],'deliver',f.ident,f.terms)
        assert fetch.await_count==1
        assert fetch.await_args.args[0].endswith('/info')
    asyncio.run(run())


def test_storage_rejection_does_not_import(network):
    f=network
    f.issuer.app.state.wallets.backend.inspect_scanned_record.side_effect=ValueError('Storage not allowed')
    async def run():
        assert await sharing.call(f.merchant,f.card['payload'],'deliver',f.ident,f.terms)=={'state':'rejected'}
        f.issuer.app.state.wallets.backend.accept_scanned_record.assert_not_awaited()
    asyncio.run(run())


def test_sender_status_with_no_attempt_never_starts_import(network):
    f=network
    item={'id':'a'*32,'share':'b'*32,'card':f.card['payload'],'terms':f.terms}
    async def run():
        with pytest.raises(ValueError):
            await sharing.deliver(f.merchant,f.merchant.app.state.wallets,'alice',item,False)
        f.issuer.app.state.wallets.backend.accept_scanned_record.assert_not_awaited()
    asyncio.run(run())




def test_prefixed_label_is_imported_and_collision_protected(network):
    f = network
    f.terms['label'] = 'tom/benefits/health'
    async def run():
        assert await sharing.call(f.merchant, f.card['payload'], 'deliver', f.ident, f.terms) == {'state':'complete'}
        assert f.issuer.app.state.wallets.backend.accept_scanned_record.await_args.args[2] == 'tom/benefits/health'
        assert await sharing.call(f.merchant, f.card['payload'], 'deliver', '2'*32, f.terms) == {'state':'rejected'}
        assert f.issuer.app.state.wallets.backend.accept_scanned_record.await_count == 1
    asyncio.run(run())


def test_existing_sharing_label_is_not_overwritten(network):
    from app.record_labels import content_fingerprint
    f=network
    fingerprint=content_fingerprint({'note':'same'})
    f.terms['label']='benefits/'+fingerprint
    f.rows.append({'label':f.terms['label'],'ref':'a'*64})
    service=f.issuer.app.state.wallets
    service.backend.inspect_scanned_record.return_value.update(fingerprint=fingerprint)
    service.record_detail=AsyncMock(return_value={'has_blob':False,'payload':{'note':'same'},'record_type':'generic'})
    async def run():
        assert await sharing.call(f.merchant,f.card['payload'],'deliver',f.ident,f.terms)=={'state':'rejected'}
        assert await sharing.call(f.merchant,f.card['payload'],'status',f.ident,f.terms)=={'state':'rejected'}
        service.backend.accept_scanned_record.assert_not_awaited()
        service.backend.inspect_scanned_record.return_value['fingerprint']='b'*64
        assert await sharing.call(f.merchant,f.card['payload'],'deliver','3'*32,f.terms)=={'state':'rejected'}
    asyncio.run(run())


def test_exact_collision_outside_listing_blocks_nfc_import(network):
    f=network
    service=f.issuer.app.state.wallets
    service.record_exists=AsyncMock(return_value=True)
    async def run():
        assert await sharing.call(f.merchant,f.card['payload'],'deliver',f.ident,f.terms)=={'state':'rejected'}
        service.records.assert_not_awaited()
        service.backend.accept_scanned_record.assert_not_awaited()
    asyncio.run(run())


def test_nfc_lookup_failure_never_imports(network):
    f=network
    service=f.issuer.app.state.wallets
    service.record_exists=AsyncMock(side_effect=TimeoutError())
    async def run():
        assert await sharing.call(f.merchant,f.card['payload'],'deliver',f.ident,f.terms)=={'state':'rejected'}
        service.backend.accept_scanned_record.assert_not_awaited()
    asyncio.run(run())


def test_nfc_confirmation_does_not_depend_on_listing(network):
    f=network
    service=f.issuer.app.state.wallets
    service.records=AsyncMock(return_value=[])
    async def run():
        assert await sharing.call(f.merchant,f.card['payload'],'deliver',f.ident,f.terms)=={'state':'complete'}
        service.records.assert_awaited_once()
        assert service.record_exists.await_count == 2
        service.backend.accept_scanned_record.assert_awaited_once()
    asyncio.run(run())
