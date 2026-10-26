import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from test_nfc_cards import cards, pair
from app.pos_store import POSDenied
from app.pos_receiving import TerminalRequests
from app.pos_card_payment import pay


@pytest.fixture
def payment(cards, monkeypatch):
    store, pos, terminal = cards
    issued, _ = pair(cards)
    store.verify(terminal, 'pair-request-key-0001', issued['payload'])
    actor = {'id': terminal, 'owner': 'merchant', 'wallet_id': 'wallet-merchant'}
    tickets = TerminalRequests(store.custody)
    row, _ = tickets.reserve(actor, 'receipt-request-0001', '{}')
    tickets.finish(row, {'purpose': 'clear-request', 'code': 'server-owned-code', 'amount': 10})
    sender = SimpleNamespace(prepare_code=AsyncMock(return_value={'id': 'outgoing-1'}),
                             send=AsyncMock(return_value={'state': 'sent'}),
                             get=lambda *args: {'state': 'sent'})
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        settings=SimpleNamespace(origin=store.origin), wallets=SimpleNamespace(store=store.custody), send=sender)))
    monkeypatch.setattr('app.pos_card_payment.read_receipt', AsyncMock(return_value={'state':'pending'}))
    payload = json.dumps({'request_key': 'receipt-request-0001', 'card_payload': issued['payload']})
    return request, actor, payload, sender, store, issued


def test_receipt_bound_one_shot_and_concurrent_retry(payment):
    async def run():
        request, actor, payload, sender, *_ = payment
        results = await asyncio.gather(pay(request, actor, payload), pay(request, actor, payload))
        assert any(r['state']=='submitted' for r in results)
        assert (await pay(request, actor, payload))['state']=='submitted'
        sender.prepare_code.assert_awaited_once_with('alice', 'server-owned-code')
        sender.send.assert_awaited_once_with('alice', 'outgoing-1')
    asyncio.run(run())


def test_ambiguous_preparation_does_not_retry(payment):
    async def run():
        request, actor, payload, sender, *_ = payment
        sender.prepare_code.side_effect = TimeoutError()
        with pytest.raises(TimeoutError): await pay(request, actor, payload)
        assert (await pay(request, actor, payload))['state']=='review'
        sender.prepare_code.assert_awaited_once()
        sender.send.assert_not_awaited()
    asyncio.run(run())


def test_revocation_before_send_prevents_debit(payment):
    async def run():
        request, actor, payload, sender, store, issued = payment
        async def prepare(*args):
            store.revoke('alice', issued['card_id'])
            return {'id':'outgoing-1'}
        sender.prepare_code.side_effect=prepare
        with pytest.raises(HTTPException): await pay(request, actor, payload)
        sender.send.assert_not_awaited()
    asyncio.run(run())


@pytest.mark.parametrize('receipt_state', ['detected','complete','expired','unavailable'])
def test_nonpending_receipt_cannot_debit(payment, monkeypatch, receipt_state):
    async def run():
        request, actor, payload, sender, *_ = payment
        monkeypatch.setattr('app.pos_card_payment.read_receipt',AsyncMock(return_value={'state':receipt_state}))
        assert (await pay(request, actor, payload))['state']=='review'
        sender.prepare_code.assert_not_awaited()
    asyncio.run(run())


def test_browser_cannot_choose_destination_or_amount(payment):
    async def run():
        request, actor, payload, sender, *_ = payment
        for field in ('amount','code','owner','asset'):
            data=json.loads(payload);data[field]='attacker'
            with pytest.raises(HTTPException): await pay(request, actor, json.dumps(data))
        sender.send.assert_not_awaited()
    asyncio.run(run())


def test_other_terminal_and_revoked_card_denied(payment):
    async def run():
        request, actor, payload, sender, store, issued = payment
        other = {**actor, 'id':'another-terminal'}
        with pytest.raises(HTTPException): await pay(request, other, payload)
        store.revoke('alice',issued['card_id'])
        with pytest.raises(HTTPException): await pay(request, actor, payload)
        sender.send.assert_not_awaited()
    asyncio.run(run())


def test_unknown_send_never_repeated(payment):
    async def run():
        request, actor, payload, sender, *_ = payment
        sender.send.return_value={'state':'unknown'}
        sender.get=lambda *args:{'state':'unknown'}
        assert (await pay(request, actor, payload))['state']=='review'
        assert (await pay(request, actor, payload))['state']=='review'
        sender.send.assert_awaited_once()
    asyncio.run(run())


def test_card_pay_requires_signed_body_and_one_use_challenge(env, monkeypatch):
    import httpx
    from test_pos_activation import proof
    async def run():
        app, _, _, store, pair, session, _ = env
        handler=AsyncMock(return_value={'state':'submitted'})
        monkeypatch.setattr('app.pos_card_payment.pay',handler)
        payload=json.dumps({'request_key':'receipt-request-0001','card_payload':'opaque'})
        challenge=store.challenge(session,'card-pay',payload)
        signed=proof(pair[0],challenge)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='https://oakgate.example') as client:
            headers={'Authorization':'Bearer '+session}
            bad=await client.post('/api/pos/v1/card-pay',json={'payload':payload+' ',**signed},headers=headers)
            assert bad.status_code==403
            handler.assert_not_awaited()
            challenge=store.challenge(session,'card-pay',payload)
            data={'payload':payload,**proof(pair[0],challenge)}
            assert (await client.post('/api/pos/v1/card-pay',json=data,headers=headers)).status_code==200
            assert (await client.post('/api/pos/v1/card-pay',json=data,headers=headers)).status_code==403
            handler.assert_awaited_once()
    asyncio.run(run())


from test_pos_receiving import env


def test_same_wallet_rejected_before_reservation_or_send(payment, monkeypatch):
    from contextlib import closing
    async def run():
        request, actor, payload, sender, store, _ = payment
        monkeypatch.setattr('app.pos_card_payment.CardStore.balance_authority',
                            lambda *args, **kwargs: {'owner':actor['owner'],'wallet_id':actor['wallet_id']})
        with pytest.raises(HTTPException) as exc:
            await pay(request, actor, payload)
        assert exc.value.status_code == 400
        assert exc.value.detail == {'code':'same-wallet'}
        sender.prepare_code.assert_not_awaited()
        sender.send.assert_not_awaited()
        with closing(store.custody.connect()) as db:
            assert db.execute("SELECT count(*) FROM wallet_requests WHERE state='processing'").fetchone()[0] == 0
    asyncio.run(run())
