import asyncio
import hashlib
from unittest.mock import AsyncMock

import pytest
from app.wallets import AcornBackend
from app.record_capabilities import RecordCapabilities
from app import record_routes, openetr
from test_wallets import setup, login, form

REF = 'a' * 64
DETAIL = {'label': 'Personal/Notes', 'contents': 'hello', 'payload': 'hello', 'has_blob': True,
          'record_type': 'credential', 'origsha256': hashlib.sha256(b'original').hexdigest()}


def test_record_workflows_and_owner_isolation(tmp_path, monkeypatch):
    async def run():
        client, sessions, service, backend = setup(tmp_path)
        backend.records = AsyncMock(return_value=[{'label': 'Personal/Notes', 'ref': REF, 'timestamp': 2},
                                                  {'label': 'Other', 'ref': 'b'*64, 'timestamp': 1}])
        backend.record_detail = AsyncMock(return_value=DETAIL)
        backend.update_record = AsyncMock(return_value={'verified': True})
        backend.create_record_capability = AsyncMock(return_value={'descriptor': 'PRIVATE-BEARER', 'expires_at': 2000000000, 'label': 'Personal/Notes'})
        backend.stop_record_capability = AsyncMock(return_value={'transfer_deleted': True})
        backend.record_blob = AsyncMock(return_value=(DETAIL, 'application/pdf', b'original'))
        query = AsyncMock(return_value=openetr.build_openetr_history(DETAIL['origsha256'], [], []))
        monkeypatch.setattr(record_routes, 'query_openetr_history', query)
        async with client:
            assert (await client.get(f'/account/records/{REF}/edit')).status_code == 401
            owner = await login(client, sessions)
            await client.post('/account/acorn/create', data=form())
            folders = await client.get('/account/records?view=folders')
            assert 'Personal' in folders.text and 'Folder →' in folders.text
            leaf = await client.get('/account/records?view=folders&folder=Personal')
            assert '>Notes ' in leaf.text and '>Other ' not in leaf.text
            edit = await client.get(f'/account/records/{REF}/edit')
            assert 'hello</textarea>' in edit.text
            assert (await client.post(f'/account/records/{REF}/edit', data={'confirmed':'yes'})).status_code == 403
            assert (await client.post(f'/account/records/{REF}/edit', data=form(confirmed='yes', payload='{', format='json'))).status_code == 400
            backend.update_record.assert_not_awaited()
            saved = await client.post(f'/account/records/{REF}/edit', data=form(confirmed='yes', payload='updated', format='text'))
            assert saved.status_code == 303
            assert backend.update_record.await_args.args[1:] == (REF, 'updated', None, None)
            saved = await client.post(f'/account/records/{REF}/edit', data=form(confirmed='yes', payload='{}', format='json'), files={'attachment':('doc.pdf', b'PDF', 'application/pdf')})
            assert saved.status_code == 303
            assert backend.update_record.await_args.args[2:] == ({}, b'PDF', 'application/pdf')
            for action in ('present', 'share'):
                assert (await client.get(f'/account/records/{REF}/{action}')).status_code == 200
                backend.create_record_capability.assert_not_awaited() if action == 'present' else None
                created = await client.post(f'/account/records/{REF}/{action}', data=form(confirmed='yes'))
                assert created.status_code == 303
                url = created.headers['location']
                page = await client.get(url)
                assert 'PRIVATE-BEARER' in page.text and 'no-store' in page.headers['cache-control']
            assert b'PRIVATE-BEARER' not in service.store.path.read_bytes()
            other = await login(client, sessions, sub='other')
            # A different connected account must not retrieve or revoke this capability.
            service.store.insert(other, {'npub': 'other', 'relay': service.default_relay}, 'active')
            assert (await client.get(url)).status_code == 404
            assert (await client.post(url+'/stop', data=form())).status_code == 404
            backend.stop_record_capability.assert_not_awaited()
            await login(client, sessions)
            backend.stop_record_capability.return_value = {'transfer_deleted': False}
            assert (await client.post(url+'/stop', data=form())).status_code == 503
            assert (await client.get(url)).status_code == 200
            backend.stop_record_capability.return_value = {'transfer_deleted': True}
            assert (await client.post(url+'/stop', data=form())).status_code == 303
            assert (await client.get(url)).status_code == 404
            assert (await client.get(f'/account/records/{REF}/check')).status_code == 200
            query.assert_not_awaited()
            checked = await client.post(f'/account/records/{REF}/check', data=form(confirmed='yes'))
            assert checked.status_code == 200 and 'No anchor found' in checked.text
            assert query.await_args.args[0] == hashlib.sha256(b'original').hexdigest()
            backend.record_blob.return_value = (DETAIL, 'application/pdf', b'tampered')
            assert (await client.post(f'/account/records/{REF}/check', data=form(confirmed='yes'))).status_code == 409
            backend.record_detail.return_value = None
            assert (await client.post(f'/account/records/{REF}/edit', data=form(confirmed='yes', payload='x'))).status_code == 404
    asyncio.run(run())


def test_acorn_adapter_preserves_attachment_type_and_delegates():
    async def run():
        backend = AcornBackend()
        wallet = type('Wallet', (), {'put_record': AsyncMock(return_value={'verified': True}),
            'create_record_presentation': AsyncMock(), 'create_record_transfer': AsyncMock(),
            'delete_record_transfer': AsyncMock()})()
        backend.wallet = lambda material: wallet
        backend.record_detail = AsyncMock(return_value=DETAIL)
        await backend.update_record({}, REF, {'new': 'value'})
        kwargs = wallet.put_record.await_args.kwargs
        assert kwargs['preserve_existing_blob'] and kwargs['record_type'] == 'credential'
        assert kwargs['blob_data'] is None and kwargs['return_result']
        await backend.create_record_capability({}, REF, 'present')
        assert wallet.create_record_presentation.await_args.kwargs['public_only']
        wallet.create_record_transfer.assert_not_awaited()
        backend.record_detail.return_value = None
        with pytest.raises(Exception):
            await backend.update_record({}, REF, 'bad')
        assert wallet.put_record.await_count == 1
    asyncio.run(run())


def test_openetr_uses_stroma_and_distinguishes_unavailable(monkeypatch):
    async def run():
        calls = []
        class Relay:
            def __init__(self, url, **kwargs):
                self.url = url
                assert kwargs['session_factory'] and kwargs['max_msg_size'] == 262144
            async def query(self, filters):
                calls.append(filters)
                if self.url.endswith('down.example'):
                    raise TimeoutError()
                return []
        monkeypatch.setattr(openetr, 'RelayClient', Relay)
        result = await openetr.query_openetr_history('b'*64, ['wss://up.example', 'wss://down.example'])
        assert result['warnings'] and result['verification']['retrieval']['complete'] is None
        assert calls[0]['kinds'] == [1415, 1416]
        result = await openetr.query_openetr_history('b'*64, ['wss://down.example'])
        assert result['error'] and result['verification']['aggregate_state'] == 'unverifiable'
    asyncio.run(run())


def test_old_dependency_cannot_write_or_share(tmp_path):
    async def run():
        client, sessions, service, backend = setup(tmp_path)
        backend.record_workflows_available = False
        backend.record_detail = AsyncMock(return_value=DETAIL)
        backend.update_record = AsyncMock()
        backend.create_record_capability = AsyncMock()
        async with client:
            await login(client, sessions)
            await client.post('/account/acorn/create', data=form())
            for action in ('edit', 'present', 'share'):
                assert (await client.get(f'/account/records/{REF}/{action}')).status_code == 503
                response = await client.post(f'/account/records/{REF}/{action}', data=form(confirmed='yes', payload='x'))
                assert response.status_code == 503 and 'update the Acorn dependency' in response.text
            backend.update_record.assert_not_awaited()
            backend.create_record_capability.assert_not_awaited()
    asyncio.run(run())


def test_record_delete_requires_confirmation_and_verified_result(tmp_path):
    async def run():
        client, sessions, service, backend = setup(tmp_path)
        backend.record_detail = AsyncMock(return_value=DETAIL)
        backend.delete_record = AsyncMock(return_value={'verified': True})
        async with client:
            url = f'/account/records/{REF}/delete'
            assert (await client.get(url)).status_code == 401
            owner = await login(client, sessions)
            await client.post('/account/acorn/create', data=form())
            page = await client.get(url)
            assert page.status_code == 200
            assert 'name="confirmed"' in page.text and 'Cancel' in page.text
            backend.delete_record.assert_not_awaited()
            assert (await client.post(url, data=form())).status_code == 400
            assert (await client.post(url, data={'confirmed': 'yes', 'csrf': 'wrong'})).status_code == 403
            backend.delete_record.assert_not_awaited()
            lease = service.store.acquire(owner)
            assert (await client.post(url, data=form(confirmed='yes'))).status_code == 409
            service.store.release(owner, lease)
            backend.delete_record.assert_not_awaited()
            backend.record_detail.return_value = None
            assert (await client.post(url, data=form(confirmed='yes'))).status_code == 404
            backend.delete_record.assert_not_awaited()
            backend.record_detail.return_value = DETAIL
            backend.delete_record.return_value = {'verified': False}
            response = await client.post(url, data=form(confirmed='yes'))
            assert response.status_code == 503 and 'Deletion could not be confirmed' in response.text
            backend.delete_record.return_value = {'verified': True}
            response = await client.post(url, data=form(confirmed='yes'))
            assert response.status_code == 303 and response.headers['location'] == '/account/records'
            assert backend.delete_record.await_args.args[1:] == (REF,)
            lease = service.store.acquire(owner)
            service.store.release(owner, lease)
    asyncio.run(run())


def test_delete_adapter_uses_acorn_and_checks_relay_confirmation():
    from types import SimpleNamespace
    from app.wallets import WalletInputError
    async def run():
        backend = AcornBackend()
        backend.record_detail = AsyncMock(return_value=DETAIL)
        wallet = SimpleNamespace(delete_record=AsyncMock(return_value={
            'status': 'DELETE_REQUESTED', 'hidden_on': ['wss://home.example']}))
        backend.wallet = lambda material: wallet
        material = {'relay': 'wss://home.example'}
        assert await backend.delete_record(material, REF) == {'verified': True}
        wallet.delete_record.assert_awaited_once_with(label=DETAIL['label'], record_kind=37375,
            relays=['wss://home.example'], delete_blob=False)
        wallet.delete_record.return_value = {'status': 'DELETE_REQUESTED', 'hidden_on': []}
        assert await backend.delete_record(material, REF) == {'verified': False}
        backend.record_detail.return_value = None
        with pytest.raises(WalletInputError):
            await backend.delete_record(material, REF)
        assert wallet.delete_record.await_count == 2
    asyncio.run(run())
