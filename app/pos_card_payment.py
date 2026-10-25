"""Receipt-bound, same-home card debit. User-key operations stay in Acorn."""
import hashlib
import json
import time
from contextlib import closing

from fastapi import HTTPException
from app.pos_api import invoke
from app.pos_receiving import TerminalRequests, read_receipt
from app.nfc_cards import CardStore
from app.request_store import RequestStore
from app.card_payments import pinned_issuer


def reserve(custody, actor, receipt, authority):
    ident = hashlib.sha256(('pos-card-debit:' + receipt['id']).encode()).hexdigest()[:32]
    material = {'id': ident, 'purpose': 'pos-card-debit', 'payer': authority['owner'],
                'wallet_id': authority['wallet_id'], 'payment_id': None}
    with closing(custody.connect()) as db, db:
        inserted = db.execute(
            'INSERT INTO wallet_requests VALUES(?,?,?,?,?) ON CONFLICT DO NOTHING',
            (ident, actor['owner'], 'processing', time.time(), custody.seal(actor['owner'], material))).rowcount
    return RequestStore(custody).get(actor['owner'], ident), bool(inserted)


def update(custody, owner, attempt, state):
    with closing(custody.connect()) as db, db:
        db.execute('UPDATE wallet_requests SET state=?,encrypted=? WHERE id=? AND owner=?',
                   (state, custody.seal(owner, attempt), attempt['id'], owner))


async def pay(request, actor, payload):
    try:
        data = json.loads(payload)
        if (not isinstance(data, dict) or set(data) != {'request_key', 'card_payload'}
                or any(not isinstance(v, str) for v in data.values())
                or not 16 <= len(data['request_key']) <= 80 or len(data['card_payload']) > 600):
            raise ValueError()
    except (ValueError, TypeError):
        raise HTTPException(400, 'Invalid card payment request') from None
    state = request.app.state
    custody = state.wallets.store
    issuer, _ = pinned_issuer(data['card_payload'])
    if issuer != state.settings.origin:
        raise HTTPException(400, 'Use a card issued by this OakGate home.')
    cards = await invoke(CardStore, custody, state.settings.origin)
    # The merchant terminal authenticates the request; the presented bearer card
    # authorizes this debit. No PIN prompt in this initial same-home flow.
    authority = await invoke(cards.balance_authority, actor['id'], data['card_payload'], limit=True)
    if authority['owner'] == actor['owner']:
        raise HTTPException(400, 'Use a different wallet to pay this request.')
    tickets = TerminalRequests(custody)
    row = await invoke(tickets.find, actor, data['request_key'])
    if not row:
        raise HTTPException(404, 'Request not found on this terminal')
    item = await invoke(tickets.tickets.get, actor['owner'], row['id'])
    if item['purpose'] not in {'cash-request', 'clear-request'}:
        raise HTTPException(400, 'Unsupported receipt')
    attempt, fresh = await invoke(reserve, custody, actor, row, authority)
    if not fresh:
        # Never prepare or send again, including after a crash or with another card.
        if attempt.get('payment_id'):
            previous = await invoke(state.send.get, attempt['payer'], attempt['payment_id'])
            if previous['state'] == 'sent':
                return {'state': 'submitted'}
        return {'state': 'review' if attempt['state'] == 'review' or time.time()-attempt['created_at'] > 90 else attempt['state']}
    try:
        receipt = await read_receipt(request, actor, row, False)
        if receipt['state'] != 'pending':
            await invoke(update, custody, actor['owner'], attempt, 'review')
            return {'state': 'review'}
        # The code comes only from the merchant's durable receipt, never from
        # browser input. Explicit invoices stay Lightning; Clear uses its request.
        payment = await state.send.prepare_code(authority['owner'], item['code'])
        attempt['payment_id'] = payment['id']
        await invoke(update, custody, actor['owner'], attempt, 'processing')
        await invoke(cards.balance_authority, actor['id'], data['card_payload'])
        result = await state.send.send(authority['owner'], payment['id'])
        outcome = 'submitted' if result['state'] == 'sent' else 'review'
        await invoke(update, custody, actor['owner'], attempt, outcome)
        return {'state': outcome}
    except BaseException:
        # Persist the hold even on cancellation; a restored/retried request must
        # not authorize another debit. SendService owns payment reconciliation.
        await invoke(update, custody, actor['owner'], attempt, 'review')
        raise
