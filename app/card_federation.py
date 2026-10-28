"""Issuer-bound POS operations. User wallet operations remain inside Acorn.

A remote debit is claimed durably before preparation. Replays only inspect the
original SendService journal; neither home automatically repeats an uncertain send.
"""
import asyncio
import hashlib
import json
import os
import re
import secrets
import time
from contextlib import closing

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app.card_payments import canonical_origin, digest, identity, pinned_issuer
from app.identity import verify_card_message
from app.nfc_cards import CardStore
from app.pos_api import invoke
from app.pos_store import POSStore
from app.request_store import RequestStore
from app.send import public_json

router = APIRouter()
PATH = '/api/cards/v1/pos'
OPS = {'balance', 'debit', 'debit-status', 'record-open', 'record-status', 'record-present', 'record-cancel'}


def remote_card(request, encoded):
    try:
        return pinned_issuer(encoded)[0] != request.app.state.settings.origin
    except ValueError:
        # The local validator still rejects malformed/legacy credentials.
        return False


async def transport(url, *, body=None):
    # Record previews can include a 5 MiB attachment encoded as base64. These
    # larger limits are confined to this fixed, issuer-pinned protocol endpoint.
    return await public_json(url, body=body, max_bytes=8 * 1024 * 1024, timeout=60)


async def call_remote(request, actor, card, operation, request_id, data, fetch=None):
    fetch = fetch or transport
    issuer, pin = pinned_issuer(card)
    info = await fetch(issuer + '/info')
    if info['service_identity']['npub'] != pin:
        raise ValueError('Card issuer identity changed')
    from app.pos_records import terminal
    name = await invoke(terminal, request, actor)
    body = {'issuer': issuer, 'nonce': secrets.token_hex(16), 'operation': operation,
            'card': card, 'request_id': request_id, 'terminal': actor['id'], 'name': name, 'data': data}
    envelope = {'origin': canonical_origin(request.app.state.settings.origin),
                'event': identity(request).card_message(body, 'pos-card-request')}
    reply = await fetch(issuer + PATH, body=envelope)
    result = verify_card_message(reply['event'], 'pos-card-result', pin)
    if set(result) != {'request', 'result'} or result['request'] != digest(body) or not isinstance(result['result'], dict):
        raise ValueError('Card response does not match request')
    await invoke(terminal, request, actor)
    return result['result']


def claim_attempt(custody, owner, ident, binding, material):
    with closing(custody.connect()) as db, db:
        fresh = db.execute('INSERT INTO wallet_requests VALUES(?,?,?,?,?) ON CONFLICT DO NOTHING',
                           (ident, owner, 'processing', time.time(),
                            custody.seal(owner, {**material, 'id': ident, 'binding': binding}))).rowcount == 1
    attempt = RequestStore(custody).get(owner, ident)
    if attempt.get('binding') != binding:
        raise ValueError('Payment attempt already bound to another instruction')
    return attempt, fresh


def save_attempt(custody, owner, attempt, state):
    with closing(custody.connect()) as db, db:
        db.execute('UPDATE wallet_requests SET state=?,encrypted=? WHERE id=? AND owner=?',
                   (state, custody.seal(owner, attempt), attempt['id'], owner))


async def remote_pay(request, actor, data):
    from app.pos_receiving import TerminalRequests, read_receipt
    from app.pos_records import terminal
    await invoke(terminal, request, actor)
    custody = request.app.state.wallets.store
    tickets = TerminalRequests(custody)
    row = await invoke(tickets.find, actor, data['request_key'])
    if not row:
        raise HTTPException(404, 'Request not found on this terminal')
    item = await invoke(tickets.tickets.get, actor['owner'], row['id'])
    if item['purpose'] not in {'cash-request', 'clear-request'}:
        raise ValueError('Unsupported receipt')
    issuer, pin = pinned_issuer(data['card_payload'])
    terms = {'code': item['code'], 'expires': int(row['created'] + 120)}
    binding = digest({'issuer': issuer, 'pin': pin, 'card': data['card_payload'], 'terms': terms})
    # Same namespace as local debit: changing card/home cannot bypass the hold.
    ident = hashlib.sha256(('pos-card-debit:' + row['id']).encode()).hexdigest()[:32]
    attempt, fresh = await invoke(claim_attempt, custody, actor['owner'], ident, binding,
                                  {'purpose': 'remote-pos-debit', 'payment_id': None})
    if fresh:
        receipt = await read_receipt(request, actor, row, False)
        if receipt['state'] != 'pending' or time.time() >= terms['expires']:
            await invoke(save_attempt, custody, actor['owner'], attempt, 'review')
            return {'state': 'review'}
    try:
        result = await call_remote(request, actor, data['card_payload'],
                                   'debit' if fresh else 'debit-status', row['id'], terms)
        if result.get('state') not in {'submitted', 'processing', 'review'}:
            raise ValueError('Invalid debit status')
        await invoke(save_attempt, custody, actor['owner'], attempt, result['state'])
        return result
    except BaseException:
        await invoke(save_attempt, custody, actor['owner'], attempt, 'review')
        raise


async def issuer_debit(request, sender, body, authority, recheck):
    custody = request.app.state.wallets.store
    owner = authority['owner']
    terms = body['data']
    if (set(terms) != {'code', 'expires'} or not isinstance(terms['code'], str)
            or len(terms['code']) > 12000 or type(terms['expires']) is not int
            or not terms['code'].lower().startswith(('lnbc', 'lntb', 'lnbcrt', 'creqa', 'creqb'))):
        raise ValueError('Invalid payment terms')
    ident = hashlib.sha256(('remote-card-debit:' + sender + ':' + body['terminal'] + ':' + body['request_id']).encode()).hexdigest()[:32]
    binding = digest({'card': body['card'], 'terms': terms, 'wallet_id': authority['wallet_id']})
    if body['operation'] == 'debit-status':
        try:
            attempt = await invoke(RequestStore(custody).get, owner, ident)
        except ValueError:
            return {'state': 'review'}  # Missing is not permission to send again.
        if attempt.get('binding') != binding:
            raise ValueError('Changed payment terms')
        fresh = False
    else:
        # Reject new expired instructions, but permit read-only status after expiry.
        if not time.time() < terms['expires'] <= time.time() + 125:
            raise ValueError('Payment instruction expired')
        attempt, fresh = await invoke(claim_attempt, custody, owner, ident, binding,
                                      {'purpose': 'federated-card-debit', 'payment_id': None})
    service = request.app.state.send
    if not fresh:
        if attempt.get('payment_id'):
            payment = await invoke(service.get, owner, attempt['payment_id'])
            if payment['state'] == 'sent':
                return {'state': 'submitted'}
        return {'state': 'processing' if attempt['state'] == 'processing' and time.time() - attempt['created_at'] < 90 else 'review'}
    try:
        payment = await service.prepare_code(owner, terms['code'])
        attempt['payment_id'] = payment['id']
        await invoke(save_attempt, custody, owner, attempt, 'processing')
        await recheck()
        if time.time() >= terms['expires']:
            raise ValueError('Payment instruction expired during preparation')
        result = await service.send(owner, payment['id'])
        outcome = 'submitted' if result['state'] == 'sent' else 'review'
        await invoke(save_attempt, custody, owner, attempt, outcome)
        return {'state': outcome}
    except BaseException:
        await invoke(save_attempt, custody, owner, attempt, 'review')
        raise


def session_key(sender, body):
    return 'card-federation-record:' + digest([sender, body['terminal'], body['request_id']])


async def issuer_records(request, sender, origin, body, authority, recheck):
    from app.pos_records import LABELS, matching_records, choices, selection_id, presentation_lease, render_detail
    service, cache = request.app.state.wallets, request.app.state.store
    owner, operation, data = authority['owner'], body['operation'], body['data']
    key = session_key(sender, body)
    if operation == 'record-open':
        if (set(data) != {'label', 'expires'} or data['label'] not in LABELS
                or type(data['expires']) is not int or not time.time() < data['expires'] <= time.time() + 125):
            raise ValueError('Invalid record request')
        # Atomic short-lived claim. Replay cannot extend TTL or switch cards/categories.
        from app.emergency_contacts import claim
        if not await invoke(claim, service.store, key):
            raise ValueError('Record request already opened; check its status')
        holder = await invoke(service.store.get, owner)
        rows = matching_records(await service.records(holder['material']), data['label'])
        await recheck()
        source = {'owner': owner, 'npub': holder['material']['npub'], 'label': data['label'],
                  'card_hash': digest(body['card']), 'expires': data['expires'],
                  'records': [{'label': r['label'], 'ref': r['ref']} for r in rows], 'result': None}
        await cache.put(key, service.store.seal(owner, source).decode(), max(1, int(data['expires'] - time.time())))
        return {'state': 'ready', 'records': choices(rows), 'expires': data['expires']}
    if set(data) != {'record_id'} or not isinstance(data['record_id'], str) or len(data['record_id']) > 64:
        raise ValueError('Invalid record selection')
    sealed = await cache.get(key)
    if not sealed or await cache.get(key + ':closed'):
        raise HTTPException(404, 'Presentation expired')
    decoded = json.loads(service.store.cipher.decrypt(sealed.encode()))
    source = decoded['material']
    if decoded['owner'] != owner or source['card_hash'] != digest(body['card']) or source['expires'] <= time.time():
        raise ValueError('Presentation binding changed')
    if operation == 'record-cancel':
        await cache.put(key + ':closed', True, 125)
        await cache.delete(key)
        return {'state': 'cancelled'}
    if operation == 'record-status':
        return {'state': 'ready', 'records': choices(source['records']), 'expires': source['expires']}
    rows = source['records']
    selected = next((r for r in rows if selection_id(r) == data['record_id']), None) if data['record_id'] else rows[0] if len(rows) == 1 else None
    if not selected:
        raise ValueError('Select an approved record')
    record_id = selection_id(selected)
    if source['result'] and source['result']['record_id'] == record_id and source['result']['expires'] > time.time():
        return source['result']
    holder = await invoke(service.store.get, owner)
    rows = matching_records(await service.records(holder['material']), source['label'])
    if selected not in [{'label': r['label'], 'ref': r['ref']} for r in rows]:
        raise ValueError('Record changed')
    lease = await presentation_lease(service.store, owner)
    try:
        await recheck()
        cap = await service.record_action(holder['material'], 'create_record_capability', selected['ref'], 'present',
                                         await invoke(service.store.preference, owner) or None)
    finally:
        await invoke(service.store.release, owner, lease)
    async with asyncio.timeout(40):
        detail = await service.backend.inspect_scanned_record(holder['material'], cap['descriptor'], True)
    if detail['label'].lower() != selected['label'].lower():
        raise ValueError('Record label changed')
    result = await render_detail(detail, record_id, source['expires'])
    await recheck()
    if not await cache.get(key) or await cache.get(key + ':closed') or result['expires'] <= time.time():
        raise ValueError('Presentation closed or expired')
    source['result'] = result
    await cache.put(key, service.store.seal(owner, source).decode(), max(1, int(source['expires'] - time.time())))
    if await cache.get(key + ':closed'):
        await cache.delete(key)
        raise ValueError('Presentation closed')
    if detail['label'].lower() == 'emergency':
        from app.emergency_contacts import notify_contact
        result['notification'] = await notify_contact(request, key, source, result['contents'])
    from app.presentation_receipts import schedule_receipt
    # Issuer-generated receipt in the holder's own wallet, explicitly naming the
    # authenticated remote service. Never impersonate a remote merchant wallet.
    actor = {'owner': owner, '_remote_name': body['name'] + ' (' + origin + ')'}
    schedule_receipt(request, key + ':' + record_id, actor, source, detail['label'])
    return result


async def execute(request, envelope, fetch=None):
    from pos.config import pos_enabled
    if not pos_enabled():
        raise HTTPException(503, 'POS operations are disabled')
    fetch = fetch or transport
    if not isinstance(envelope, dict) or set(envelope) != {'origin', 'event'}:
        raise ValueError('Invalid envelope')
    origin = canonical_origin(envelope['origin'])
    info = await fetch(origin + '/info')
    sender = info['service_identity']['npub']
    allowed = os.getenv('OAKGATE_CARD_TRUSTED_INSTANCES', '').replace(',', ' ').split()
    if allowed and sender not in allowed:
        raise ValueError('Acquiring instance is not allowed')
    body = verify_card_message(envelope['event'], 'pos-card-request', sender)
    if (set(body) != {'issuer', 'nonce', 'operation', 'card', 'request_id', 'terminal', 'name', 'data'}
            or body['operation'] not in OPS or not isinstance(body['data'], dict)
            or any(not isinstance(body[k], str) for k in ('issuer', 'nonce', 'card', 'request_id', 'terminal', 'name'))
            or not re.fullmatch('[a-f0-9]{32}', body['nonce'])
            or not re.fullmatch('[A-Za-z0-9_-]{1,80}', body['terminal'])
            or len(body['card']) > 600 or not 1 <= len(body['name']) <= 60
            or (body['operation'] != 'balance' and not re.fullmatch('[A-Za-z0-9_-]{16,80}', body['request_id']))):
        raise ValueError('Invalid instruction')
    own = canonical_origin(request.app.state.settings.origin)
    signer = identity(request)
    if body['issuer'] != own or pinned_issuer(body['card']) != (own, signer.npub):
        raise ValueError('Wrong issuer')
    custody = request.app.state.wallets.store
    def limit():
        with closing(custody.connect()) as db, db:
            POSStore._limit(db, 'card-federation:' + sender, 1200, 3600)
    await invoke(limit)
    cards = await invoke(CardStore, custody, own)
    authority = await invoke(cards.balance_authority, None, body['card'])
    async def recheck():
        fresh = await invoke(cards.balance_authority, None, body['card'])
        if fresh != authority:
            raise ValueError('Card wallet changed')
    if body['operation'] == 'balance':
        if body['data'] or body['request_id']:
            raise ValueError('Invalid balance request')
        from app.nfc_routes import read_card_balance
        result = await read_card_balance(request, authority, recheck)
    elif body['operation'].startswith('debit'):
        result = await issuer_debit(request, sender, body, authority, recheck)
    else:
        result = await issuer_records(request, sender, origin, body, authority, recheck)
    await recheck()
    return {'event': signer.card_message({'request': digest(body), 'result': result}, 'pos-card-result')}


@router.post(PATH, include_in_schema=False)
async def endpoint(request: Request):
    def limit_peer():
        with closing(request.app.state.wallets.store.connect()) as db, db:
            POSStore._limit(db, 'card-federation-peer:' + (request.client.host if request.client else 'unknown'), 1200, 3600)
    await invoke(limit_peer)
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 24000:
            raise HTTPException(413)
    try:
        envelope = json.loads(raw)
        # A disconnected acquirer must not cancel an in-flight issuer payment.
        task = asyncio.create_task(execute(request, envelope))
        request.app.state.pos_tasks.add(task)
        def done(task):
            request.app.state.pos_tasks.discard(task)
            if not task.cancelled():
                task.exception()
        task.add_done_callback(done)
        result = await asyncio.shield(task)
        return JSONResponse(result, headers={'Cache-Control': 'no-store'})
    except Exception:
        raise HTTPException(400, 'Card operation unavailable or not authorized.') from None
