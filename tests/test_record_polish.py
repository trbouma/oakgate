import asyncio
import hashlib
from contextlib import aclosing
from unittest.mock import AsyncMock

import pytest
from app import openetr, record_routes, scan
from app.record_settings import RecordSettings
from app.record_capabilities import RecordCapabilities
from app.request_store import RequestStore
from app.wallets import AcornBackend
from test_wallets import setup, login, form
from test_record_actions import REF, DETAIL
from test_openetr import signed, DIGEST


def test_record_check_rich_evidence_and_unavailable(tmp_path, monkeypatch):
    async def run():
        client, sessions, service, backend = setup(tmp_path)
        backend.record_detail = AsyncMock(return_value=DETAIL)
        backend.record_blob = AsyncMock(return_value=(DETAIL, 'text/plain', b'original'))
        digest = hashlib.sha256(b'original').hexdigest()
        anchor = signed(tags=[['o',digest],['action','issue']], content='<script>untrusted</script>')
        query = AsyncMock(return_value=openetr.build_openetr_history(digest,[anchor],['wss://relay.example']))
        monkeypatch.setattr(record_routes, 'query_openetr_history', query)
        monkeypatch.setenv('OAKGATE_OPENETR_QUERY_LIMIT','37')
        async with aclosing(client):
            await login(client,sessions)
            await client.post('/account/acorn/create',data=form())
            result = await client.get(f'/account/records/{REF}/check')
            assert result.status_code == 200
            assert 'name="confirmed"' not in result.text
            assert 'record-check-found' in result.text
            assert f'href="/account/records/{REF}" aria-label="Anchor found' in result.text
            assert 'Anchor found' in result.text and 'Anchor and Signer' in result.text
            assert '<details class="openetr-check-details">' in result.text
            summary = result.text.split('<details class="openetr-check-details">')[0]
            assert 'record-anchor-check' in summary
            assert '&lt;script&gt;untrusted&lt;/script&gt;' in summary
            assert 'not recognized authority' not in summary
            assert 'https://openetr.org/etr/'+digest in result.text
            assert '&lt;script&gt;untrusted&lt;/script&gt;' in result.text
            assert '<script>untrusted</script>' not in result.text
            assert query.await_args.kwargs['limit'] == 37
            assert query.await_args.kwargs['digest_source'] == 'computed'
            query.side_effect = TimeoutError()
            result = await client.get(f'/account/records/{REF}/check')
            assert result.status_code == 200 and 'Check unavailable' in result.text
            assert 'No anchor found' not in result.text and 'uncertain' not in result.text
            assert 'record-anchor-check' not in result.text
    asyncio.run(run())


def test_scanner_evidence_links_are_bounded_and_do_not_import(tmp_path, monkeypatch):
    async def run():
        client, sessions, service, backend = setup(tmp_path)
        query = AsyncMock(return_value=openetr.build_openetr_history(DIGEST,[],[]))
        monkeypatch.setattr(scan,'query_openetr_history',query)
        monkeypatch.setenv('OAKGATE_OPENETR_PUBLIC_BASE_URL','https://verify.example/etr')
        async with aclosing(client):
            assert (await client.get('/account/check/'+DIGEST)).status_code == 303
            await login(client,sessions)
            await client.post('/account/acorn/create',data=form())
            response = await client.post('/account/scan',data=form(lightning_payment='https://verify.example/etr/'+DIGEST))
            assert response.status_code == 303
            assert response.headers['location'] == '/account/check/'+DIGEST
            query.assert_not_awaited()
            result = await client.get(response.headers['location'])
            assert result.status_code == 200 and 'has not retrieved or verified the original file' in result.text
            assert 'No anchor found' in result.text
            for code in ['https://verify.example.evil/etr/'+DIGEST, 'https://verify.example/etr/'+DIGEST+'?server=https://evil.example']:
                result = await client.post('/account/scan',data=form(lightning_payment=code))
                assert result.status_code == 200 and 'Open website' in result.text
            assert query.await_count == 1
    asyncio.run(run())


def test_share_import_label_collision_and_one_shot(tmp_path):
    async def run():
        client, sessions, service, backend = setup(tmp_path)
        backend.inspect_scanned_record = AsyncMock(return_value={'label':'Existing', 'record_type':'note','has_original':True,'expires_at':2000000000,'sharing_fingerprint':'a'*64})
        backend.accept_scanned_record = AsyncMock(return_value={'stored':True})
        backend.records = AsyncMock(return_value=[{'label':'Existing'}])
        async with aclosing(client):
            owner = await login(client,sessions)
            await client.post('/account/acorn/create',data=form())
            result = await client.post('/account/scan',data=form(lightning_payment='acorn:record-transfer:private'))
            assert result.status_code == 200 and 'Store as' in result.text and 'Expires' in result.text
            ticket = RequestStore(service.store).recent(owner)[0]
            result = await client.post('/account/scan/accept',data=form(ticket=ticket['id'],confirmed='yes',label='Existing'))
            assert result.status_code == 409 and 'Choose another label' in result.text
            backend.accept_scanned_record.assert_not_awaited()
            assert RequestStore(service.store).get(owner,ticket['id'])['state'] == 'ready'
            result = await client.post('/account/scan/accept',data=form(ticket=ticket['id'],confirmed='yes',label='Imported/Copy'))
            assert result.status_code == 303
            assert backend.accept_scanned_record.await_args.kwargs == {'label':'Imported/Copy'}
            await client.post('/account/scan/accept',data=form(ticket=ticket['id'],confirmed='yes',label='Another copy'))
            backend.accept_scanned_record.assert_awaited_once()
    asyncio.run(run())


def test_configured_transfer_servers_delegate_to_acorn(monkeypatch):
    async def run():
        monkeypatch.setenv('OAKGATE_RECORD_ALLOWED_SERVERS','https://peer.example')
        backend = AcornBackend()
        wallet = type('Wallet',(),{'inspect_record_transfer':AsyncMock(), 'accept_record_transfer':AsyncMock(), 'record_exists':AsyncMock(return_value=False)})()
        backend.wallet = lambda material: wallet
        await backend.inspect_scanned_record({},'private')
        assert 'https://peer.example' in wallet.inspect_record_transfer.await_args.kwargs['allowed_servers']
        await backend.accept_scanned_record({'relay':'wss://home.example'},'private',label='Imported')
        assert wallet.accept_record_transfer.await_args.kwargs['record_name'] == 'Imported'
    asyncio.run(run())


@pytest.mark.parametrize('name,value',[
    ('OAKGATE_OPENETR_QUERY_TIMEOUT_SECONDS','0'),
    ('OAKGATE_OPENETR_QUERY_TIMEOUT_SECONDS','nan'),
    ('OAKGATE_OPENETR_QUERY_LIMIT','10000'),
    ('OAKGATE_OPENETR_PUBLIC_BASE_URL','http://unsafe.example/etr'),
    ('OAKGATE_RECORD_ALLOWED_SERVERS','https://user:password@example.com'),
])
def test_invalid_record_settings_fail_closed(monkeypatch,name,value):
    monkeypatch.setenv(name,value)
    with pytest.raises(ValueError): RecordSettings()


def test_expired_share_keeps_stop_but_hides_qr(tmp_path):
    async def run():
        client,sessions,service,backend = setup(tmp_path)
        async with aclosing(client):
            owner=await login(client,sessions)
            await client.post('/account/acorn/create',data=form())
            ident=RecordCapabilities(service.store).save(owner,{'descriptor':'secret','expires_at':1,'label':'Test','purpose':'share'})
            response=await client.get('/account/record-shares/'+ident)
            assert 'This code has expired' in response.text
            assert 'record-copy-qr' not in response.text
            assert 'data-share-progress' not in response.text
            assert 'data-stop-record-sharing' in response.text
            assert 'no-store' in response.headers['cache-control']
    asyncio.run(run())


def test_evidence_lookup_provenance_and_profile_binding(monkeypatch):
    async def run():
        anchor = signed(tags=[["o", DIGEST], ["action", "issue"]])
        profile = signed(kind=0, tags=[], content='{"name":"Verified publisher"}')
        calls = []
        class Client:
            def __init__(self, *args, **kwargs): pass
            async def query(self, filters):
                calls.append(filters)
                return [profile] if filters["kinds"] == [0] else [anchor]
        monkeypatch.setattr(openetr, 'RelayClient', Client)
        result = await openetr.query_openetr_history(DIGEST, ['wss://relay.example'])
        assert result['verification']['artifact']['digest_source'] == 'supplied'
        assert result['candidate_graphs'][0]['signer_profile']['display_name'] is None
        assert result['candidate_graphs'][0]['signer_profile']['name'] == 'Verified publisher'
        assert calls[1]['authors'] == [anchor.pub_key]
        result = await openetr.query_openetr_history(DIGEST, ['wss://relay.example'], digest_source='computed')
        assert result['verification']['artifact']['digest_source'] == 'computed'
        async def unavailable(self, filters): raise TimeoutError()
        monkeypatch.setattr(Client, 'query', unavailable)
        result = await openetr.query_openetr_history(DIGEST, ['wss://relay.example'], digest_source='computed')
        assert result['error'] and result['verification']['artifact']['digest_source'] == 'computed'
    asyncio.run(run())


def test_sharing_fingerprint_suggests_editable_import_label(tmp_path):
    async def run():
        client, sessions, service, backend = setup(tmp_path)
        backend.inspect_scanned_record = AsyncMock(return_value={'label':'Certificate','originator_handle':'alice','record_type':'note','has_original':False,'sharing_fingerprint':'b'*64})
        backend.accept_scanned_record = AsyncMock(return_value={'stored':True})
        backend.records = AsyncMock(return_value=[])
        async with aclosing(client):
            owner = await login(client,sessions)
            await client.post('/account/acorn/create',data=form())
            result = await client.post('/account/scan',data=form(lightning_payment='acorn:record-transfer:private'))
            assert result.status_code == 200
            assert ('value="' + 'b'*64 + '"') in result.text
            assert 'Shared by' in result.text
            ticket = RequestStore(service.store).recent(owner)[0]
            assert ticket['label'] == 'b'*64
            result = await client.post('/account/scan/accept',data=form(ticket=ticket['id'],confirmed='yes',label='My chosen label'))
            assert result.status_code == 303
            assert backend.accept_scanned_record.await_args.kwargs == {'label':'My chosen label'}
    asyncio.run(run())


@pytest.mark.parametrize('lookup_failure', [False, True])
def test_qr_exact_collision_or_lookup_failure_blocks_import_outside_listing(tmp_path, lookup_failure):
    async def run():
        client,sessions,service,backend=setup(tmp_path)
        backend.inspect_scanned_record=AsyncMock(return_value={'label':'health/current','sharing_fingerprint':'a'*64,'record_type':'note','has_original':False})
        backend.accept_scanned_record=AsyncMock()
        backend.records=AsyncMock(return_value=[])
        backend.record_exists=AsyncMock(side_effect=TimeoutError() if lookup_failure else None, return_value=True)
        async with aclosing(client):
            owner=await login(client,sessions)
            await client.post('/account/acorn/create',data=form())
            await client.post('/account/scan',data=form(lightning_payment='acorn:record-transfer:private'))
            ticket=RequestStore(service.store).recent(owner)[0]
            result=await client.post('/account/scan/accept',data=form(ticket=ticket['id'],confirmed='yes',label='health/old'))
            assert result.status_code == (503 if lookup_failure else 409)
            backend.accept_scanned_record.assert_not_awaited()
            backend.records.assert_not_awaited()
            backend.record_exists.assert_awaited_once()
            assert RequestStore(service.store).get(owner,ticket['id'])['state']=='ready'
    asyncio.run(run())


@pytest.mark.parametrize('failure', ['collision', 'unavailable'])
def test_adapter_rechecks_exact_label_before_transfer_mutation(failure):
    from types import SimpleNamespace
    async def run():
        backend=AcornBackend()
        wallet=SimpleNamespace(record_exists=AsyncMock(return_value=True,
            side_effect=TimeoutError() if failure=='unavailable' else None), accept_record_transfer=AsyncMock())
        backend.wallet=lambda material:wallet
        with pytest.raises(Exception):
            await backend.accept_scanned_record({'relay':'wss://home.example'},'private',label='health/old')
        wallet.record_exists.assert_awaited_once_with('health/old',record_kind=37375,relays=['wss://home.example'])
        wallet.accept_record_transfer.assert_not_awaited()
    asyncio.run(run())
