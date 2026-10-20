import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from app.wallets import AcornBackend, WalletInputError
from test_wallets import setup, login, form


def test_record_create_adapter_rejects_overwrite_and_delegates():
    async def run():
        wallet = SimpleNamespace(record_exists=AsyncMock(return_value=False), put_record=AsyncMock(return_value={'verified': True}))
        backend = AcornBackend()
        backend.wallet = lambda material: wallet
        assert await backend.create_record({}, 'Notes', 'Text') == {'verified': True}
        wallet.put_record.assert_awaited_once_with('Notes', 'Text', record_type='generic', record_kind=37375,
            return_result=True, blob_data=None, blob_type=None)
        wallet.record_exists.return_value = True
        with pytest.raises(WalletInputError, match='already exists'):
            await backend.create_record({}, 'Notes', 'Replacement')
        assert wallet.put_record.await_count == 1
        wallet.record_exists.side_effect = TimeoutError()
        with pytest.raises(TimeoutError):
            await backend.create_record({}, 'Unknown', 'Do not overwrite')
        assert wallet.put_record.await_count == 1
    asyncio.run(run())


def test_new_record_form_save_and_guards(tmp_path):
    async def run():
        client, sessions, service, backend = setup(tmp_path)
        backend.create_record = AsyncMock(return_value={'verified': True})
        async with client:
            assert (await client.get('/account/add-record')).status_code == 401
            owner = await login(client, sessions)
            assert (await client.get('/account/add-record')).status_code == 404
            await client.post('/account/acorn/create', data=form())
            page = await client.get('/account/add-record')
            assert page.status_code == 200
            assert 'data-progress-message=' in page.text
            assert 'href="/account/add-record" aria-current="page"' in page.text
            assert 'href="/account/scan"' in page.text and 'href="/account/receive"' in page.text
            response = await client.post('/account/add-record', data=form(label=' Notes ', format='json', payload='{"text":"hello"}'),
                files={'attachment': ('note.txt', b'hello', 'text/plain')})
            assert response.status_code == 303 and response.headers['location'] == '/account/records'
            assert backend.create_record.call_args.args[1:] == ('Notes', {'text': 'hello'}, b'hello', 'text/plain')
            for data, status in [(form(label=''), 400), (form(label='Test', format='json', payload='NaN'), 400),
                                 ({'csrf': 'bad', 'label': 'Test'}, 403)]:
                assert (await client.post('/account/add-record', data=data)).status_code == status
            lease = service.store.acquire(owner)
            assert (await client.post('/account/add-record', data=form(label='Busy'))).status_code == 409
            service.store.release(owner, lease)
            assert backend.create_record.await_count == 1
            backend.create_record.return_value = {'verified': False}
            response = await client.post('/account/add-record', data=form(label='Uncertain'))
            assert response.status_code == 503 and 'Check Records' in response.text
            lease = service.store.acquire(owner)
            service.store.release(owner, lease)
    asyncio.run(run())
