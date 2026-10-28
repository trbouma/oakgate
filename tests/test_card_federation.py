"""Two independent stores/service keys; transport only is replaced in these tests."""
import asyncio
import hashlib
import json
import time
from types import SimpleNamespace as NS
from urllib.parse import urlsplit
from unittest.mock import AsyncMock

import pytest

from test_card_payments import instance
from app.card_federation import call_remote, execute, remote_pay
from app.nfc_cards import CardStore
from app.pos_store import POSStore
from app.pos_receiving import TerminalRequests
from app.sessions import MemoryStore


@pytest.fixture
def federation(tmp_path, monkeypatch):
    monkeypatch.setenv('OAKGATE_POS_ENABLED', 'true')
    merchant, mkey = instance(tmp_path/'merchant', 'https://merchant.example', '11'*32)
    issuer, ikey = instance(tmp_path/'issuer', 'https://issuer.example', '22'*32)
    for req in (merchant, issuer):
        state = req.app.state
        state.store = MemoryStore()
        state.pos_tasks = set()
        state.rates = None
        state.wallets.balance = AsyncMock(return_value=1234)
        state.wallets.clear_balances = AsyncMock(return_value=[])
    custody = issuer.app.state.wallets.store
    pos = POSStore(custody, 'https://pos.issuer.example')
    issuing_terminal = pos.provision('alice', 'Issuing desk').split('.')[1]
    cards = CardStore(custody, issuer.app.state.settings.origin)
    pair = urlsplit(cards.start(issuing_terminal, 'pair-request-00001')['pair_url']).fragment
    cards.approve(pair, 'alice'); cards.acknowledge_pin(pair, 'alice')
    card = cards.prepare(issuing_terminal, 'pair-request-00001')
    cards.verify(issuing_terminal, 'pair-request-00001', card['payload'])
    mpos = POSStore(merchant.app.state.wallets.store, 'https://pos.merchant.example')
    terminal = mpos.provision('alice', 'Market desk').split('.')[1]
    actor = {'id': terminal, 'owner': 'alice', 'wallet_id': hashlib.sha256(b'test-wallet').hexdigest()}
    sender = NS(prepare_code=AsyncMock(return_value={'id': 'payment-1'}),
                send=AsyncMock(return_value={'state': 'sent'}), get=lambda *args: {'state': 'sent'})
    issuer.app.state.send = sender
    exchanges = []
    async def fetch(url, *, body=None):
        if url == 'https://merchant.example/info': return {'service_identity': mkey.public_info()}
        if url == 'https://issuer.example/info': return {'service_identity': ikey.public_info()}
        assert url == 'https://issuer.example/api/cards/v1/pos'
        exchanges.append(body)
        return await execute(issuer, body, fetch)
    monkeypatch.setattr('app.card_federation.transport', fetch)
    return NS(merchant=merchant, issuer=issuer, actor=actor, card=card, cards=cards,
              sender=sender, mkey=mkey, ikey=ikey, fetch=fetch, exchanges=exchanges, mpos=mpos)


def test_remote_balance_and_revocation(federation):
    f = federation
    async def run():
        result = await call_remote(f.merchant, f.actor, f.card['payload'], 'balance', '', {})
        assert result['sats'] == 1234 and result['clear'] == []
        f.issuer.app.state.wallets.balance.assert_awaited_once()
        f.merchant.app.state.wallets.balance.assert_not_awaited()
        f.cards.revoke('alice', f.card['card_id'])
        with pytest.raises(Exception):
            await call_remote(f.merchant, f.actor, f.card['payload'], 'balance', '', {})
    asyncio.run(run())


def test_pins_signatures_binding_allowlist_and_terminal(federation, monkeypatch):
    f = federation
    async def run():
        async def rotated(url, **kwargs):
            assert not kwargs.get('body')
            return {'service_identity': f.mkey.public_info()}
        with pytest.raises(ValueError):
            await call_remote(f.merchant, f.actor, f.card['payload'], 'balance', '', {}, rotated)
        async def swapped(url, **kwargs):
            if kwargs.get('body'):
                return {'event': f.ikey.card_message({'request': 'wrong', 'result': {}}, 'pos-card-result')}
            return await f.fetch(url, **kwargs)
        with pytest.raises(ValueError):
            await call_remote(f.merchant, f.actor, f.card['payload'], 'balance', '', {}, swapped)
        monkeypatch.setenv('OAKGATE_CARD_TRUSTED_INSTANCES', f.ikey.npub)
        with pytest.raises(ValueError):
            await call_remote(f.merchant, f.actor, f.card['payload'], 'balance', '', {})
        monkeypatch.setenv('OAKGATE_CARD_TRUSTED_INSTANCES', f.mkey.npub)
        await call_remote(f.merchant, f.actor, f.card['payload'], 'balance', '', {})
        bad = f.exchanges[-1].copy()
        bad['event'] = {**bad['event'], 'content': '{}'}
        with pytest.raises(ValueError): await execute(f.issuer, bad, f.fetch)
        f.mpos.revoke('alice', f.actor['id'])
        with pytest.raises(Exception):
            await call_remote(f.merchant, f.actor, f.card['payload'], 'balance', '', {})
    asyncio.run(run())


def test_debit_duplicate_concurrent_and_changed_terms(federation):
    f = federation
    async def run():
        terms = {'code': 'lnbc-test', 'expires': int(time.time())+120}
        async def pay(terms=terms):
            return await call_remote(f.merchant, f.actor, f.card['payload'], 'debit', 'receipt-00000000001', terms)
        results = await asyncio.gather(pay(), pay())
        assert any(r['state'] == 'submitted' for r in results)
        assert (await pay())['state'] == 'submitted'
        assert (await call_remote(f.merchant, f.actor, f.card['payload'], 'debit-status', 'receipt-00000000001', terms))['state'] == 'submitted'
        f.sender.prepare_code.assert_awaited_once_with('alice', 'lnbc-test')
        f.sender.send.assert_awaited_once_with('alice', 'payment-1')
        with pytest.raises(ValueError): await pay({**terms, 'code': 'lnbc-different'})
    asyncio.run(run())


@pytest.mark.parametrize('phase', ['prepare', 'send'])
def test_uncertain_payment_never_repeated(federation, phase):
    f = federation
    async def run():
        terms = {'code': 'creqB-test', 'expires': int(time.time())+120}
        target = f.sender.prepare_code if phase == 'prepare' else f.sender.send
        target.side_effect = TimeoutError()
        f.sender.get = lambda *args: {'state': 'unknown'}
        with pytest.raises(TimeoutError):
            await call_remote(f.merchant, f.actor, f.card['payload'], 'debit', 'receipt-00000000001', terms)
        for op in ('debit', 'debit-status'):
            assert (await call_remote(f.merchant, f.actor, f.card['payload'], op, 'receipt-00000000001', terms))['state'] == 'review'
        assert target.await_count == 1
        if phase == 'prepare': f.sender.send.assert_not_awaited()
    asyncio.run(run())


def test_acquirer_lost_reply_uses_status_only(federation, monkeypatch):
    f = federation
    async def run():
        tickets = TerminalRequests(f.merchant.app.state.wallets.store)
        row, _ = tickets.reserve(f.actor, 'request-key-00001', '{}')
        tickets.finish(row, {'purpose': 'cash-request', 'code': 'lnbc-test', 'amount': 10})
        monkeypatch.setattr('app.pos_receiving.read_receipt', AsyncMock(return_value={'state':'pending'}))
        dropped = False
        async def lost_reply(url, **kwargs):
            nonlocal dropped
            result = await f.fetch(url, **kwargs)
            if kwargs.get('body') and not dropped:
                dropped = True
                raise TimeoutError()
            return result
        monkeypatch.setattr('app.card_federation.transport', lost_reply)
        data = {'request_key': 'request-key-00001', 'card_payload': f.card['payload']}
        with pytest.raises(TimeoutError): await remote_pay(f.merchant, f.actor, data)
        assert (await remote_pay(f.merchant, f.actor, data))['state'] == 'submitted'
        ops = [json.loads(e['event']['content'])['operation'] for e in f.exchanges]
        assert ops == ['debit', 'debit-status']
        f.sender.send.assert_awaited_once()
    asyncio.run(run())


def test_remote_records_categories_selection_preview_and_close(federation, monkeypatch):
    f = federation
    receipts = []
    monkeypatch.setattr('app.presentation_receipts.schedule_receipt', lambda *args: receipts.append(args))
    wallet = f.issuer.app.state.wallets
    wallet.records = AsyncMock(return_value=[{'label':'Benefits/Health','ref':'health'}, {'label':'Benefits/Dental','ref':'dental'}])
    wallet.record_action = AsyncMock(side_effect=lambda material, op, ref, *args: {'descriptor': ref})
    wallet.backend.inspect_scanned_record = AsyncMock(side_effect=lambda m, ref, p: {
        'label': 'Benefits/' + ref.title(), 'payload': ref, 'blob_data': None, 'expires_at': time.time()+120})
    async def run():
        rid = 'record-request-0000001'
        async def call(op, data): return await call_remote(f.merchant, f.actor, f.card['payload'], op, rid, data)
        opened = await call('record-open', {'label':'benefits', 'expires':int(time.time())+120})
        assert len(opened['records']) == 2
        wallet.record_action.assert_not_awaited()
        assert (await call('record-status', {'record_id':''}))['records'] == opened['records']
        with pytest.raises(ValueError): await call('record-present', {'record_id':'forged'})
        result = await call('record-present', {'record_id':opened['records'][0]['id']})
        assert result['contents'] == 'dental' and result['label'] == 'Benefits/Dental'
        assert (await call('record-present', {'record_id':opened['records'][0]['id']})) == result
        assert len(receipts) == 1 and 'merchant.example' in receipts[0][2]['_remote_name']
        assert (await call('record-present', {'record_id':opened['records'][1]['id']}))['contents'] == 'health'
        assert (await call('record-cancel', {'record_id':''}))['state'] == 'cancelled'
        with pytest.raises(Exception): await call('record-status', {'record_id':''})
    asyncio.run(run())


def test_remote_record_single_revoke_and_expiry(federation, monkeypatch):
    f = federation
    wallet = f.issuer.app.state.wallets
    wallet.records = AsyncMock(return_value=[{'label':'WhoAmI','ref':'identity'}])
    async def run():
        opened = await call_remote(f.merchant, f.actor, f.card['payload'], 'record-open', 'record-request-0000001', {'label':'whoami','expires':int(time.time())+120})
        assert len(opened['records']) == 1
        with pytest.raises(ValueError):
            await call_remote(f.merchant, f.actor, f.card['payload'], 'record-open', 'record-request-0000002', {'label':'whoami','expires':int(time.time())-1})
        f.cards.revoke('alice', f.card['card_id'])
        with pytest.raises(Exception):
            await call_remote(f.merchant, f.actor, f.card['payload'], 'record-present', 'record-request-0000001', {'record_id':''})
    asyncio.run(run())


def test_pos_routes_forward_foreign_cards_and_keep_local_request_binding(federation, monkeypatch):
    from app.nfc_routes import card_operation
    from app.pos_records import operation, load
    f = federation
    monkeypatch.setattr('app.presentation_receipts.schedule_receipt', lambda *args: None)
    wallet = f.issuer.app.state.wallets
    wallet.records = AsyncMock(return_value=[{'label':'WhoAmI','ref':'identity'}])
    wallet.record_action = AsyncMock(return_value={'descriptor':'presentation'})
    wallet.backend.inspect_scanned_record = AsyncMock(return_value={
        'label':'WhoAmI','payload':'Alice','blob_data':None,'expires_at':time.time()+120})
    async def run():
        result = await card_operation(f.merchant, f.actor, 'card-balance', json.dumps({'card_payload':f.card['payload'],'confirmed':'yes'}))
        assert result['sats'] == 1234
        with pytest.raises(Exception):
            await card_operation(f.merchant, f.actor, 'card-balance', json.dumps({'card_payload':f.card['payload'],'confirmed':'no'}))
        start = await operation(f.merchant, f.actor, 'record-start', json.dumps({'label':'whoami'}))
        rid = start['request_id']
        ready = await operation(f.merchant, f.actor, 'record-nfc', json.dumps({'request_id':rid,'card_payload':f.card['payload']}))
        assert len(ready['records']) == 1
        assert (await operation(f.merchant, f.actor, 'record-present', json.dumps({'request_id':rid})))['contents'] == 'Alice'
        # Replacement invalidates the old request on the acquiring home.
        await operation(f.merchant, f.actor, 'record-start', json.dumps({'label':'benefits'}))
        with pytest.raises(Exception): await load(f.merchant, rid, f.actor)
    asyncio.run(run())


def test_revocation_during_preparation_and_balance_read(federation):
    f = federation
    async def run():
        async def prepare(*args):
            f.cards.revoke('alice', f.card['card_id'])
            return {'id':'payment-1'}
        f.sender.prepare_code.side_effect = prepare
        with pytest.raises(Exception):
            await call_remote(f.merchant, f.actor, f.card['payload'], 'debit', 'receipt-00000000001', {'code':'lnbc-test','expires':int(time.time())+120})
        f.sender.send.assert_not_awaited()
    asyncio.run(run())


def test_remote_record_preview_matches_pdf_and_anchor_rendering(federation, monkeypatch):
    f = federation
    monkeypatch.setattr('app.presentation_receipts.schedule_receipt', lambda *args: None)
    monkeypatch.setattr('app.openetr.query_openetr_history', AsyncMock(return_value={
        'verification':'anchored','candidate_graphs':[{'signer_profile':{'display_name':'Clinic'},
        'anchor':{'author':'npub-test','content':'Membership verified','created_at':'today'}}]}))
    wallet = f.issuer.app.state.wallets
    wallet.records = AsyncMock(return_value=[{'label':'member','ref':'ref'}])
    wallet.record_action = AsyncMock(return_value={'descriptor':'presentation'})
    wallet.backend.inspect_scanned_record = AsyncMock(return_value={
        'label':'member','payload':'Alice','blob_data':b'%PDF-1.4\nexample','blob_type':'application/pdf','expires_at':time.time()+120})
    async def run():
        await call_remote(f.merchant, f.actor, f.card['payload'], 'record-open', 'record-request-0000001', {'label':'member','expires':int(time.time())+120})
        result = await call_remote(f.merchant, f.actor, f.card['payload'], 'record-present', 'record-request-0000001', {'record_id':''})
        assert result['attachment']['type'] == 'application/pdf'
        assert result['publishers'][0]['name'] == 'Clinic'
        assert result['publishers'][0]['statement'] == 'Membership verified'
    asyncio.run(run())


def test_remote_records_closed_during_retrieval_do_not_return(federation, monkeypatch):
    f = federation
    monkeypatch.setattr('app.presentation_receipts.schedule_receipt', lambda *args: None)
    wallet = f.issuer.app.state.wallets
    wallet.records = AsyncMock(return_value=[{'label':'whoami','ref':'ref'}])
    wallet.record_action = AsyncMock(return_value={'descriptor':'presentation'})
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        async def inspect(*args):
            entered.set(); await release.wait()
            return {'label':'whoami','payload':'Alice','blob_data':None,'expires_at':time.time()+120}
        wallet.backend.inspect_scanned_record = inspect
        async def call(op, data): return await call_remote(f.merchant, f.actor, f.card['payload'], op, 'record-request-0000001', data)
        await call('record-open', {'label':'whoami','expires':int(time.time())+120})
        task = asyncio.create_task(call('record-present', {'record_id':''}))
        await entered.wait()
        await call('record-cancel', {'record_id':''})
        release.set()
        with pytest.raises(ValueError): await task
        with pytest.raises(Exception): await call('record-status', {'record_id':''})
    asyncio.run(run())


def test_http_disconnect_does_not_cancel_issuer_debit(federation):
    import httpx
    from fastapi import FastAPI
    from app.card_federation import router, PATH
    f = federation
    async def run():
        app = FastAPI()
        for k, v in vars(f.issuer.app.state).items(): setattr(app.state, k, v)
        app.include_router(router)
        entered, release = asyncio.Event(), asyncio.Event()
        async def send(*args):
            entered.set(); await release.wait()
            return {'state':'sent'}
        f.sender.send.side_effect = send
        terms = {'code':'lnbc-test', 'expires':int(time.time())+120}
        body = {'issuer':'https://issuer.example','nonce':'ab'*16,'operation':'debit',
                'card':f.card['payload'],'request_id':'receipt-00000000001','terminal':f.actor['id'],
                'name':'Market desk','data':terms}
        envelope = {'origin':'https://merchant.example','event':f.mkey.card_message(body,'pos-card-request')}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://issuer.example') as client:
            task = asyncio.create_task(client.post(PATH,json=envelope))
            await asyncio.wait_for(entered.wait(),2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError): await task
            release.set()
            await asyncio.gather(*list(app.state.pos_tasks))
            status = await call_remote(f.merchant, f.actor, f.card['payload'], 'debit-status', 'receipt-00000000001', terms)
            assert status['state'] == 'submitted'
            f.sender.send.assert_awaited_once()
            assert (await client.post(PATH,content=b'x'*24001)).status_code == 413
            assert (await client.post(PATH,json={'origin':'https://merchant.example','event':{}})).status_code == 400
    asyncio.run(run())


def test_missing_debit_status_never_creates_payment(federation):
    f = federation
    async def run():
        status = await call_remote(f.merchant, f.actor, f.card['payload'], 'debit-status', 'receipt-00000000001',
                                   {'code':'lnbc-test','expires':int(time.time())-120})
        assert status['state'] == 'review'
        f.sender.prepare_code.assert_not_awaited()
        f.sender.send.assert_not_awaited()
    asyncio.run(run())
