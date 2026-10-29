"""Card-directed record receipt, with durable one-attempt delivery journals.

The service key authenticates homes; only Acorn decrypts/imports user records.
An uncertain write is never replayed. Status cannot initiate an import.
"""
import asyncio
import hashlib
import json
import logging
import os
import re
import secrets
import time
from contextlib import closing, suppress

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.card_federation import claim_attempt, save_attempt
from app.card_payments import canonical_origin, digest, identity, pinned_issuer
from app.identity import verify_card_message
from app.nfc_cards import CardStore
from app.pos_api import invoke
from app.pos_store import POSStore
from app.record_capabilities import RecordCapabilities
from app.record_routes import account
from app.request_store import RequestStore
from app.send import public_json
from app.wallet_routes import checked_form

logger = logging.getLogger(__name__)
router = APIRouter()
PATH = '/api/cards/v1/records'


def attempt_id(prefix, *parts):
    return digest([prefix, *parts])[:32]


async def transport(url, *, body=None):
    return await public_json(url, body=body, timeout=60)


async def protected(request, coroutine):
    # Keep the wallet write alive if the browser/remote caller disconnects.
    task = asyncio.create_task(coroutine)
    request.app.state.pos_tasks.add(task)
    def done(task):
        request.app.state.pos_tasks.discard(task)
        if not task.cancelled():
            task.exception()
    task.add_done_callback(done)
    return await asyncio.shield(task)


async def call(request, card, operation, ident, data, fetch=None):
    fetch = fetch or transport
    issuer, pin = pinned_issuer(card)
    own, signer = canonical_origin(request.app.state.settings.origin), identity(request)
    info = {'service_identity': signer.public_info()} if issuer == own else await fetch(issuer + '/info')
    if info['service_identity']['npub'] != pin:
        raise ValueError('Card issuer identity changed')
    body = dict(issuer=issuer, card=card, operation=operation, id=ident,
                nonce=secrets.token_hex(16), data=data)
    envelope = {'origin': own, 'event': signer.card_message(body, 'card-record-request')}
    reply = (await execute(request, envelope, fetch) if issuer == own
             else await fetch(issuer + PATH, body=envelope))
    result = verify_card_message(reply['event'], 'card-record-result', pin)
    if set(result) != {'request', 'result'} or result['request'] != digest(body) or not isinstance(result['result'], dict):
        raise ValueError('Invalid record receipt response')
    return result['result']


async def execute(request, envelope, fetch=None):
    fetch = fetch or transport
    if not isinstance(envelope, dict) or set(envelope) != {'origin', 'event'}:
        raise ValueError('Invalid envelope')
    own, signer = canonical_origin(request.app.state.settings.origin), identity(request)
    origin = canonical_origin(envelope['origin'])
    info = {'service_identity': signer.public_info()} if origin == own else await fetch(origin + '/info')
    sender = info['service_identity']['npub']
    allowed = os.getenv('OAKGATE_CARD_TRUSTED_INSTANCES', '').replace(',', ' ').split()
    if allowed and sender not in allowed:
        raise ValueError('Home not allowed')
    body = verify_card_message(envelope['event'], 'card-record-request', sender)
    if (set(body) != {'issuer', 'card', 'operation', 'id', 'nonce', 'data'}
            or body['issuer'] != own or body['operation'] not in {'resolve', 'deliver', 'status'}
            or any(not isinstance(body[k], str) for k in ('id', 'nonce', 'card'))
            or not re.fullmatch('[a-f0-9]{32}', body['id'])
            or not re.fullmatch('[a-f0-9]{32}', body['nonce']) or len(body['card']) > 600
            or not isinstance(body['data'], dict) or pinned_issuer(body['card']) != (own, signer.npub)):
        raise ValueError('Invalid record instruction')
    service = request.app.state.wallets
    def limit():
        with closing(service.store.connect()) as db, db:
            POSStore._limit(db, 'card-record:' + sender, 120, 3600)
    await invoke(limit)
    cards = await invoke(CardStore, service.store, own)
    authority = await invoke(cards.balance_authority, None, body['card'])
    async def recheck():
        if await invoke(cards.balance_authority, None, body['card']) != authority:
            raise ValueError('Card binding changed')
        holder = await invoke(service.store.get, authority['owner'])
        if (not holder or holder['status'] != 'active'
                or hashlib.sha256(holder['material']['npub'].encode()).hexdigest() != authority['wallet_id']):
            raise ValueError('Wallet changed')
        return holder['material']
    material = await recheck()
    if body['operation'] == 'resolve':
        if body['data']:
            raise ValueError('Invalid resolution')
        handle = await invoke(service.store.preference, authority['owner'])
        result = {'recipient': handle or 'Card wallet', 'wallet': authority['wallet_id']}
    else:
        result = await receive(request, sender, body, authority, recheck, material)
    await recheck()
    return {'event': signer.card_message({'request': digest(body), 'result': result}, 'card-record-result')}


async def receive(request, sender, body, authority, recheck, material):
    service, terms = request.app.state.wallets, body['data']
    owner = authority['owner']
    if (set(terms) != {'descriptor', 'label', 'expires', 'wallet'}
            or not isinstance(terms['descriptor'], str) or len(terms['descriptor']) > 12000
            or not isinstance(terms['label'], str) or not 1 <= len(terms['label']) <= 200
            or terms['label'] != terms['label'].strip() or any(ord(c) < 32 for c in terms['label'])
            or type(terms['expires']) is not int or terms['wallet'] != authority['wallet_id']):
        raise ValueError('Invalid record terms')
    ident = attempt_id('card-record-in', sender, body['id'])
    binding = digest({'card': body['card'], 'terms': terms})
    if body['operation'] == 'status':
        try:
            attempt = await invoke(RequestStore(service.store).get, owner, ident)
        except ValueError:
            return {'state': 'review'}
        fresh = False
        if attempt.get('binding') != binding:
            raise ValueError('Changed terms')
    else:
        if not time.time() < terms['expires'] <= time.time() + 125:
            raise ValueError('Sharing code expired')
        attempt, fresh = await invoke(claim_attempt, service.store, owner, ident, binding,
                                      {'purpose': 'card-record-in', 'label': terms['label']})
    if not fresh:
        state = attempt['state']
        if state == 'processing' and time.time() - attempt['created_at'] > 180:
            state = 'review'
        return {'state': state if state in {'complete', 'processing', 'rejected'} else 'review'}
    lease = renewal = None
    writing = False
    lease_ok = True
    try:
        lease = await invoke(service.store.acquire, owner)
        async def renew():
            nonlocal lease_ok
            try:
                while True:
                    await asyncio.sleep(20)
                    await invoke(service.store.renew, owner, lease)
            except Exception:
                lease_ok = False
        renewal = asyncio.create_task(renew())
        inspected = await service.backend.inspect_scanned_record(material, terms['descriptor'])
        if inspected['expires_at'] < time.time():
            raise ValueError('Sharing code expired')
        rows = await service.records(material)
        if any(r['label'].casefold() == terms['label'].casefold() for r in rows):
            raise ValueError('Record label already exists')
        await recheck()
        await invoke(service.store.renew, owner, lease)
        if not lease_ok or time.time() >= terms['expires']:
            raise ValueError('Sharing preparation expired')
        writing = True
        # No cancellation timeout around an Acorn write. On an uncertain result,
        # retain the attempt for review instead of importing the descriptor again.
        result = await service.backend.accept_scanned_record(material, terms['descriptor'], terms['label'])
        if not isinstance(result, dict) or result.get('status') != 'OK':
            raise ValueError('Acorn did not confirm import')
        rows = await service.records(material)
        if not any(r['label'] == terms['label'] for r in rows):
            raise ValueError('Record not yet confirmed')
        await recheck()
        await invoke(save_attempt, service.store, owner, attempt, 'complete')
        return {'state': 'complete'}
    except Exception as exc:
        logger.warning('Card record receipt phase=%s error_type=%s', 'import' if writing else 'prepare', type(exc).__name__)
        state = 'review' if writing else 'rejected'
        await invoke(save_attempt, service.store, owner, attempt, state)
        return {'state': state}
    finally:
        if renewal:
            renewal.cancel()
            with suppress(asyncio.CancelledError):
                await renewal
        if lease:
            await invoke(service.store.release, owner, lease)


@router.post(PATH, include_in_schema=False)
async def endpoint(request: Request):
    def limit_peer():
        with closing(request.app.state.wallets.store.connect()) as db, db:
            POSStore._limit(db, 'card-record-peer:' + (request.client.host if request.client else 'unknown'), 120, 3600)
    await invoke(limit_peer)
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 24000:
            raise HTTPException(413)
    try:
        result = await protected(request, execute(request, json.loads(raw)))
        return JSONResponse(result, headers={'Cache-Control': 'no-store'})
    except Exception:
        raise HTTPException(400, 'Record delivery unavailable or not authorized.') from None


def render(request, session, ident, item=None, state=None):
    return request.app.state.templates.TemplateResponse(request=request, name='record_card.html',
        context={**session, 'active_page': 'records', 'ident': ident, 'item': item, 'state': state},
        headers={'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer'})


@router.post('/account/record-shares/{ident}/card', include_in_schema=False)
async def prepare(request: Request, ident: str):
    session, service, owner, _ = await account(request)
    form = await checked_form(request, session)
    try:
        share = await invoke(RecordCapabilities(service.store).get, owner, ident)
        if share['purpose'] != 'share' or share['expires_at'] <= time.time():
            raise ValueError('Expired')
        card = form.get('card', '')
        target = await call(request, card, 'resolve', ident, {})
        if (set(target) != {'recipient', 'wallet'} or not isinstance(target['recipient'], str)
                or len(target['recipient']) > 200 or not re.fullmatch('[a-f0-9]{64}', target['wallet'])):
            raise ValueError('Invalid wallet')
        issuer, pin = pinned_issuer(card)
        item = {'purpose': 'card-record-out', 'share': ident, 'card': card, 'issuer': issuer,
                'pin': pin, 'recipient': target['recipient'], 'terms': {
                    'descriptor': share['descriptor'], 'label': share['label'],
                    'expires': int(share['expires_at']), 'wallet': target['wallet']}}
        ticket = await invoke(RequestStore(service.store).save, owner, item)
        return RedirectResponse('/account/record-card/' + ticket, 303)
    except Exception:
        return render(request, session, ident, state='unavailable')
    finally:
        await form.close()


async def ticket(request, ident):
    session, service, owner, _ = await account(request)
    try:
        item = await invoke(RequestStore(service.store).get, owner, ident)
    except ValueError:
        raise HTTPException(404, 'Record delivery not found') from None
    if item.get('purpose') != 'card-record-out':
        raise HTTPException(404)
    return session, service, owner, item


@router.get('/account/record-card/{ident}', include_in_schema=False)
async def review(request: Request, ident: str):
    session, service, owner, item = await ticket(request, ident)
    return render(request, session, ident, item, 'ready' if item['state'] == 'ready' else item['state'])


async def deliver(request, service, owner, item, allow_start=True):
    # Claim across every review ticket for this share, not just this browser form.
    ident = attempt_id('card-record-out', owner, item['share'])
    binding = digest({'card': item['card'], 'terms': item['terms']})
    if allow_start:
        attempt, fresh = await invoke(claim_attempt, service.store, owner, ident, binding,
                                      {'purpose': 'card-record-out-attempt', 'ticket': item['id']})
    else:
        attempt = await invoke(RequestStore(service.store).get, owner, ident)
        if attempt.get('binding') != binding:
            raise ValueError('Changed recipient or record')
        fresh = False
    if fresh:
        share = await invoke(RecordCapabilities(service.store).get, owner, item['share'])
        if share['expires_at'] <= time.time() or share['descriptor'] != item['terms']['descriptor']:
            raise ValueError('Sharing copy expired or changed')
    result = await call(request, item['card'], 'deliver' if fresh else 'status', ident, item['terms'])
    if result.get('state') not in {'complete', 'processing', 'review', 'rejected'}:
        raise ValueError('Invalid status')
    await invoke(save_attempt, service.store, owner, attempt, result['state'])
    await invoke(save_attempt, service.store, owner, item, result['state'])
    return result['state']


@router.post('/account/record-card/{ident}', include_in_schema=False)
async def confirm(request: Request, ident: str):
    session, service, owner, item = await ticket(request, ident)
    form = await checked_form(request, session)
    try:
        if form.get('confirmed') != 'yes':
            raise HTTPException(400, 'Confirm record sharing')
        # Mark the review ticket before work; refresh then shows Check status.
        allow_start = await invoke(RequestStore(service.store).claim, owner, ident)
        try:
            state = await protected(request, deliver(request, service, owner, item, allow_start))
        except Exception:
            state = 'review'
        return render(request, session, ident, item, state)
    finally:
        await form.close()


@router.get('/account/record-shares/{ident}/card', include_in_schema=False)
async def previous(request: Request, ident: str):
    session, service, owner, _ = await account(request)
    # Only encrypted owner-bound tickets are read; card secrets never enter URLs.
    try:
        attempt = await invoke(RequestStore(service.store).get, owner, attempt_id('card-record-out', owner, ident))
        if attempt.get('ticket'):
            return RedirectResponse('/account/record-card/' + attempt['ticket'], 303)
    except ValueError:
        pass
    rows = await invoke(RequestStore(service.store).recent, owner)
    item = next((r for r in rows if r.get('purpose') == 'card-record-out' and r.get('share') == ident), None)
    if item:
        return RedirectResponse('/account/record-card/' + item['id'], 303)
    return render(request, session, ident, state='unavailable')
