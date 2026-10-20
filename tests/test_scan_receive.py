import asyncio
import base64
import time
from contextlib import aclosing
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest

from app.send import SendService, PaymentInputError
from app.request_store import RequestStore
from app.wallets import AcornBackend
from app.clear_balances import asset_id
from app.zaps import encode_lnurl
from test_wallets import setup, login, form
from test_send import prepared


def test_scan_routes_and_csrf(tmp_path):
    async def run():
        client, sessions, wallets, backend = setup(tmp_path)
        async with aclosing(client):
            assert (await client.get('/account/scan')).status_code == 303
            await login(client, sessions)
            await client.post('/account/acorn/create', data=form())
            page = await client.get('/account')
            assert page.text.index('account-nav') < page.text.index('href="/account/scan"')
            assert 'href="/account/receive"' in page.text
            response = await client.post('/account/scan', data={'lightning_payment': 'alice@example.com'})
            assert response.status_code == 403
            for address in ['alice@example.com', 'lightning:alice@example.com', encode_lnurl('https://example.com/.well-known/lnurlp/alice')]:
                result = await client.post('/account/scan', data=form(lightning_payment=address))
                assert result.status_code == 200
                assert 'value="alice@example.com"' in result.text
                assert 'Confirm payment' not in result.text
            response = await client.post('/account/scan', data=form(lightning_payment='https://other.example/hello'))
            assert 'Open website' in response.text
            assert response.status_code == 200
            response = await client.post('/account/scan', data=form(lightning_payment='https://printed.invalid/01/09520123456788'))
            assert response.status_code == 303
            assert response.headers['location'].startswith('/account/product?')
            raw = '010005760602909610LOT\x1d17270131'
            response = await client.post('/account/scan', data=form(acquired_payload=base64.b64encode(raw.encode()).decode(), acquisition_mode='gs1'))
            assert response.status_code == 303
            assert '%1D' in response.headers['location']
            response = await client.post('/account/scan', data=form(lightning_payment='12345678'))
            assert response.status_code == 400
            assert 'GS1 element string' in response.text
    asyncio.run(run())


def test_scanned_invoice_review_and_rescan_deduplication(tmp_path, monkeypatch):
    async def run():
        client, sessions, wallets, backend, owner, service, fetch = await prepared(tmp_path)
        async with aclosing(client):
            monkeypatch.setattr('app.send.bolt11.decode', lambda code: SimpleNamespace(currency='bc', amount_msat=42000, date=int(time.time()), expiry=300))
            payment = await service.prepare_code(owner, 'lnbc-test')
            backend.send_payment.assert_not_awaited()
            fetch.assert_not_awaited()
            assert payment['amount'] == 42
            assert (await service.prepare_code(owner, 'LNBC-TEST'))['id'] == payment['id']
            assert (await service.send(owner, payment['id']))['state'] == 'sent'
            duplicate = await service.prepare_code(owner, 'lnbc-test')
            assert duplicate['state'] == 'sent'
            await service.send(owner, duplicate['id'])
            backend.send_payment.assert_awaited_once()
            with pytest.raises(ValueError):
                service.get('someone-else', payment['id'])
    asyncio.run(run())


@pytest.mark.parametrize('amount,currency,date', [(0,'bc',time.time()), (1001,'bc',time.time()), (42000,'tb',time.time()), (42000,'bc',0)])
def test_invalid_invoices_never_send(tmp_path, monkeypatch, amount, currency, date):
    async def run():
        client, sessions, wallets, backend, owner, service, fetch = await prepared(tmp_path)
        async with aclosing(client):
            monkeypatch.setattr('app.send.bolt11.decode', lambda code: SimpleNamespace(currency=currency, amount_msat=amount, date=date, expiry=300))
            with pytest.raises(PaymentInputError):
                await service.prepare_code(owner, 'lnbc-test')
            backend.send_payment.assert_not_awaited()
    asyncio.run(run())


def test_clear_request_review_friendly_units_one_shot_and_route_guards(tmp_path):
    async def run():
        client, sessions, wallets, backend, owner, service, fetch = await prepared(tmp_path)
        async with aclosing(client):
            review = dict(requested_amount=12, proof_amount=13, receiver_input_fee=1, mint='https://clear.example', unit='cmu-test', keyset='01abc', recipient_pubkey='bc'*32, relays=[wallets.default_relay], single_use=True, payment_request_id='request-1')
            backend.inspect_clear_request = AsyncMock(return_value=review)
            service.clear_assets = AsyncMock(return_value=[dict(mint=review['mint'], unit=review['unit'], display_name='Satellite Shares', display_unit='shares')])
            payment = await service.prepare_code(owner, 'creqA-test')
            assert payment['display_unit'] == 'shares'
            assert payment['proof_amount'] == 13
            backend.send_payment.assert_not_awaited()
            await service.send(owner, payment['id'])
            duplicate = await service.prepare_code(owner, 'creqB1-same-id')
            assert duplicate['id'] == payment['id']
            await service.send(owner, duplicate['id'])
            backend.send_payment.assert_awaited_once()
            assert not service.discover.called and not fetch.called
            backend.inspect_clear_request.return_value = {**review, 'relays':['wss://unapproved.example']}
            with pytest.raises(PaymentInputError):
                await service.prepare_code(owner, 'creqA-other')
            backend.inspect_clear_request.return_value = {**review, 'mint':'http://clear-mint:3338'}
            with pytest.raises(PaymentInputError):
                await service.prepare_code(owner, 'creqA-other')
    asyncio.run(run())


def test_record_import_owner_bound_and_not_repeated(tmp_path):
    async def run():
        client, sessions, wallets, backend = setup(tmp_path)
        async with aclosing(client):
            owner = await login(client, sessions)
            await client.post('/account/acorn/create', data=form())
            backend.inspect_scanned_record = AsyncMock(return_value={'label':'Test record','record_type':'note'})
            backend.accept_scanned_record = AsyncMock(return_value={'stored':True})
            response = await client.post('/account/scan', data=form(lightning_payment='acorn:record-transfer:secret'))
            assert response.status_code == 200
            backend.accept_scanned_record.assert_not_awaited()
            item = RequestStore(wallets.store).recent(owner)[0]
            assert item['purpose'] == 'transfer'
            assert 'acorn:record-transfer:secret' not in response.text
            assert (await client.post('/account/scan/accept', data=form(ticket=item['id'], confirmed='yes'))).status_code == 303
            await client.post('/account/scan/accept', data=form(ticket=item['id'], confirmed='yes'))
            backend.accept_scanned_record.assert_awaited_once()
            with pytest.raises(ValueError):
                RequestStore(wallets.store).get('other-owner', item['id'])
    asyncio.run(run())


def test_clear_requests_advertise_polled_inbox_and_status_requires_history(monkeypatch):
    async def run():
        backend = AcornBackend()
        create = __import__('unittest.mock', fromlist=['Mock']).Mock(return_value='creqA-test')
        import inspect
        create.__signature__ = inspect.Signature([inspect.Parameter('encoding', inspect.Parameter.KEYWORD_ONLY)])
        wallet = SimpleNamespace(create_payment_request=create,
            get_clear_receipts=AsyncMock(return_value=[{'event_id':'evt','payment_request_id':'req','status':'accepted','mint':'https://mint.example','unit':'cmu-test'}]),
            get_clear_transaction_history=AsyncMock(return_value=[]))
        monkeypatch.setattr(backend,'wallet',lambda material: wallet)
        await backend.create_clear_request({'relay':'wss://spurline.safebox.dev'},12,{'mint':'https://mint.example','unit':'cmu-test'},'Shares')
        assert create.call_args.kwargs['relays'] == ['wss://spurline.safebox.dev']
        item = {'request_id':'req','mint':'https://mint.example','unit':'cmu-test','amount':12}
        assert await backend.clear_request_status({},item) == 'review'
        wallet.get_clear_transaction_history.return_value = [{'source_event':'evt','direction':'in','operation':'accept','mint':item['mint'],'unit':item['unit'],'amount':12}]
        assert await backend.clear_request_status({},item) == 'complete'
    asyncio.run(run())


def test_receive_invoice_uses_durable_journal_and_clear_receipt_tickets(tmp_path):
    async def run():
        from test_payments import Mint
        client, sessions, wallets, backend = setup(tmp_path)
        async with aclosing(client):
            owner = await login(client,sessions)
            await client.post('/account/acorn/create',data=form())
            app = client._transport.app
            app.state.payments.mint = Mint()
            response = await client.post('/account/receive',data=form(amount='42'))
            assert response.status_code == 303
            item = RequestStore(wallets.store).recent(owner)[0]
            stored = app.state.payments.store.get(item['payment_id'])
            assert stored['owner'] == owner and stored['state'] == 'waiting'
            assert stored['prepared'] and stored['invoice'] == item['code']
            response = await client.get(response.headers['location'])
            assert response.status_code == 200 and '>Waiting for payment</p>' in response.text
            assert 'SECRET-NSEC' not in response.text and 'SECRET-PHRASE' not in response.text
            other = await login(client,sessions,sub='other')
            await client.post('/account/acorn/create',data=form())
            assert (await client.get('/account/receive?ticket='+item['id'])).status_code == 404
    asyncio.run(run())


def test_receive_clear_request_and_status(tmp_path):
    async def run():
        from acorn.acorn import Acorn
        client, sessions, wallets, backend = setup(tmp_path)
        async with aclosing(client):
            owner = await login(client, sessions)
            await client.post('/account/acorn/create', data=form())
            app = client._transport.app
            backend.clear_receiving_available = True
            mint, unit = 'https://clear.example', 'cmu-test'
            asset = dict(id=asset_id(mint,unit), mint=mint, unit=unit, display_name='Satellite Shares', display_unit='shares', amount=100)
            app.state.send.clear_assets = AsyncMock(return_value=[asset])
            code = Acorn(nsec=Acorn.generate_recovery_material()['nsec'], home_relay=wallets.default_relay).create_payment_request(12, unit=unit, mint=mint, relays=[wallets.default_relay])
            backend.create_clear_request = AsyncMock(return_value=code)
            backend.clear_request_status = AsyncMock(return_value='pending')
            response = await client.post('/account/receive', data=form(amount='12',asset=asset['id']))
            assert response.status_code == 303
            item = RequestStore(wallets.store).recent(owner)[0]
            assert item['purpose'] == 'clear-request'
            assert item['request_id']
            page = await client.get(response.headers['location'])
            assert 'Satellite Shares' in page.text and 'shares' in page.text
            assert 'receive-status.js' in page.text
            assert '>Waiting for payment</p>' in page.text
            backend.clear_request_status.side_effect = RuntimeError('Lookup failed')
            page = await client.get(response.headers['location'])
            assert '>Checking payment status</p>' in page.text
            backend.clear_request_status.side_effect = None
            backend.clear_request_status.return_value = 'complete'
            result = await client.get('/account/receive/status/'+item['id'])
            assert result.json() == {'state':'complete'}
            assert code not in result.text
            page = await client.get(response.headers['location'])
            assert '>Received</p>' in page.text
            assert 'data-receive-pending' not in page.text
    asyncio.run(run())


def test_clear_adapter_uses_acorn_and_rechecks_terms(monkeypatch):
    async def run():
        backend = AcornBackend()
        review = dict(mint='https://mint.example', unit='cmu-test', keyset='01test', requested_amount=12, proof_amount=13, recipient_pubkey='bc'*32, relays=['wss://spurline.safebox.dev'])
        wallet = SimpleNamespace(inspect_payment_request=AsyncMock(return_value=review), send_payment_request=AsyncMock(return_value={'status':'OK','event_id':'evt'}))
        monkeypatch.setattr(backend,'wallet',lambda material:wallet)
        payment = {'route':'clear-request','request':'creqA-test','review':review}
        assert await backend.send_payment({},payment) == {'event_id':'evt'}
        wallet.send_payment_request.assert_awaited_once_with('creqA-test', memo='Paid from OakGate')
        wallet.inspect_payment_request.return_value = {**review,'proof_amount':14}
        with pytest.raises(ValueError):
            await backend.send_payment({},payment)
        assert wallet.send_payment_request.await_count == 1
    asyncio.run(run())


def test_presentation_renders_attachment_and_file_is_owner_bound(tmp_path, monkeypatch):
    async def run():
        client, sessions, wallets, backend = setup(tmp_path)
        async with aclosing(client):
            owner = await login(client,sessions)
            await client.post('/account/acorn/create',data=form())
            backend.inspect_scanned_record = AsyncMock(return_value={'label':'Certificate','record_type':'note','payload':{'text':'<script>bad</script>'},'has_original':True,'blob_type':'image/png','blob_data':b'PNG','blob_sha256':'ab'*32})
            monkeypatch.setattr('app.scan.query_openetr_history',AsyncMock(return_value={'candidate_graphs':[]}))
            response = await client.post('/account/scan',data=form(lightning_payment='acorn:record-presentation:secret'))
            assert response.status_code == 200
            assert '<script>bad</script>' not in response.text
            ticket = RequestStore(wallets.store).recent(owner)[0]['id']
            assert '/account/scan/presentation/'+ticket+'/file?inline=true' in response.text
            response = await client.get('/account/scan/presentation/'+ticket+'/file?inline=true')
            assert response.content == b'PNG'
            assert 'sandbox' in response.headers['content-security-policy']
            await login(client,sessions,sub='other')
            await client.post('/account/acorn/create',data=form())
            assert (await client.get('/account/scan/presentation/'+ticket+'/file')).status_code == 404
    asyncio.run(run())


def test_expired_unused_review_can_refresh_without_reviving_old_confirmation(tmp_path, monkeypatch):
    async def run():
        from contextlib import closing
        import json
        client, sessions, wallets, backend, owner, service, fetch = await prepared(tmp_path)
        async with aclosing(client):
            monkeypatch.setattr('app.send.bolt11.decode',lambda code:SimpleNamespace(currency='bc',amount_msat=42000,date=int(time.time()),expiry=300))
            first = await service.prepare_code(owner,'lnbc-test')
            first['expires'] = 0
            with closing(wallets.store.connect()) as db, db:
                db.execute('UPDATE outgoing_payments SET encrypted=? WHERE id=?',(wallets.store.cipher.encrypt(json.dumps(first).encode()),first['id']))
            second = await service.prepare_code(owner,'lnbc-test')
            assert second['id'] != first['id']
            with pytest.raises(ValueError,match='expired'):
                await service.send(owner,first['id'])
            await service.send(owner,second['id'])
            backend.send_payment.assert_awaited_once()
    asyncio.run(run())


@pytest.mark.parametrize('prefix',['creqA','CREQB1','creqb1'])
@pytest.mark.parametrize('symbology',['qr_code','data_matrix','code_128'])
def test_payment_codes_bypass_barcode_interpretation(tmp_path,prefix,symbology):
    async def run():
        client,sessions,wallets,backend=setup(tmp_path)
        async with aclosing(client):
            await login(client,sessions)
            await client.post('/account/acorn/create',data=form())
            sender=client._transport.app.state.send
            sender.prepare_code=AsyncMock(return_value={'id':'review-ticket'})
            code=prefix+'test'
            response=await client.post('/account/scan',data=form(acquired_payload=base64.b64encode(code.encode()).decode(),symbology=symbology,acquisition_mode='gs1'))
            assert response.status_code == 303
            assert response.headers['location']=='/account/send?payment=review-ticket'
            assert sender.prepare_code.await_args.args[1]==code
            sender.prepare_code.side_effect=PaymentInputError('This Clear request needs a matching balance.')
            response=await client.post('/account/scan',data=form(lightning_payment=code,symbology=symbology))
            assert response.status_code==400
            assert 'payment request was recognized' in response.text
            assert 'Code interpretation' not in response.text
            assert 'matching balance' in response.text
    asyncio.run(run())


def test_clear_creation_uses_b_or_explicit_dependency_message():
    import inspect
    from acorn.acorn import Acorn
    from acorn.payment_request import decode_payment_request
    from app.wallets import WalletInputError
    async def run():
        backend=AcornBackend()
        material={**Acorn.generate_recovery_material(),'relay':'wss://spurline.safebox.dev'}
        asset={'mint':'https://clear.safebox.dev','unit':'cmu-shares'}
        if 'encoding' not in inspect.signature(Acorn.create_payment_request).parameters:
            with pytest.raises(WalletInputError,match='updated safebox-acorn'):
                await backend.create_clear_request(material,12,asset,'Satellite Shares')
        else:
            code=await backend.create_clear_request(material,12,asset,'Satellite Shares')
            assert code.startswith('CREQB1')
            request=decode_payment_request(code)
            assert request.amount==12 and request.unit=='cmu-shares'
            assert request.mints==('https://clear.safebox.dev',)
    asyncio.run(run())
