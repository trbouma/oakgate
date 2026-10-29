"""Wallet-approved cross-home presentations, separate from card bearer authority."""
import asyncio
import json
import os
import re
import secrets
import time
from contextlib import closing
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from app.card_payments import canonical_origin, digest, identity
from app.card_federation import transport
from app.identity import verify_card_message
from app.pos_api import invoke
from app.pos_store import POSStore
from app.pos_records import key, load, sealed_put, unseal, terminal, matching_records, choices, selection_id, presentation_lease, render_detail
from pos.config import pos_enabled

router = APIRouter()
PATH = '/api/records/v1/presentation'
TOKEN = r'[A-Za-z0-9_-]{43}'


def destination(code):
    p = urlsplit(code)
    origin = canonical_origin(p.scheme + '://' + p.netloc)
    if p.path != '/account/record-request' or p.query or not re.fullmatch(TOKEN, p.fragment):
        raise ValueError('Invalid presentation request')
    return origin, p.fragment


def allowed(pin):
    peers = os.getenv('OAKGATE_CARD_TRUSTED_INSTANCES', '').replace(',', ' ').split()
    if peers and pin not in peers:
        raise ValueError('Instance is not allowed')


async def rpc(request, origin, pin, operation, ident, data, fetch=None):
    fetch = fetch or transport
    canonical_origin(origin)
    info = await fetch(origin + '/info')
    if info['service_identity']['npub'] != pin:
        raise ValueError('Instance identity changed')
    allowed(pin)
    body = {'target': origin, 'nonce': secrets.token_hex(16), 'operation': operation,
            'request_id': ident, 'data': data}
    reply = await fetch(origin + PATH, body={'origin': canonical_origin(request.app.state.settings.origin),
                       'event': identity(request).card_message(body, 'wallet-record-request')})
    result = verify_card_message(reply['event'], 'wallet-record-result', pin)
    if set(result) != {'request', 'result'} or result['request'] != digest(body) or not isinstance(result['result'], dict):
        raise ValueError('Presentation response does not match request')
    return result['result']


async def put_private(request, kind, token, owner, value, expires):
    if expires <= time.time():
        raise ValueError('Request expired')
    sealed = request.app.state.wallets.store.seal(owner, value)
    await request.app.state.store.put(key(kind, token), sealed.decode() if isinstance(sealed, bytes) else sealed,
                                      max(1, int(expires - time.time())))


async def private(request, kind, token, owner=None):
    if not isinstance(token, str) or not re.fullmatch(TOKEN, token):
        raise ValueError('Invalid request')
    sealed = await request.app.state.store.get(key(kind, token))
    if not sealed:
        raise ValueError('Request expired')
    value = json.loads(request.app.state.wallets.store.cipher.decrypt(sealed.encode()))
    if owner is not None and value['owner'] != owner:
        raise ValueError('Wrong wallet')
    data = value['material']
    if data['expires'] <= time.time():
        raise ValueError('Request expired')
    return value['owner'], data


async def begin(request, owner, code):
    origin, ident = destination(code)
    pin = (await transport(origin + '/info'))['service_identity']['npub']
    terms = await rpc(request, origin, pin, 'details', ident, {})
    from app.pos_records import category_path
    if (set(terms) != {'name', 'label', 'expires'} or not category_path(terms['label'])
            or not isinstance(terms['name'], str) or not 1 <= len(terms['name']) <= 60
            or type(terms['expires']) is not int or not time.time() < terms['expires'] <= time.time() + 125):
        raise ValueError('Invalid presentation terms')
    token = secrets.token_urlsafe(32)
    await put_private(request, 'wallet-approval', token, owner,
                      {**terms, 'origin': origin, 'pin': pin, 'request_id': ident}, terms['expires'])
    return token


async def wallet_action(request, owner, token, action, selected=None):
    _, item = await private(request, 'wallet-approval', token, owner)
    service = request.app.state.wallets
    holder = await invoke(service.store.get, owner)
    if not holder or holder['status'] != 'active':
        raise ValueError('Wallet unavailable')
    matches = matching_records(await service.records(holder['material']), item['label'])
    if action == 'details':
        return {'name': item['name'] + ' (' + item['origin'] + ')', 'label': item['label'],
                'expires': item['expires'], 'records': choices(matches)}
    if (not isinstance(selected, list) or not selected or len(selected) > 20
            or any(not isinstance(v, str) for v in selected) or len(set(selected)) != len(selected)):
        raise ValueError('Select records to present')
    rows = [r for r in matches if selection_id(r) in selected]
    if len(rows) != len(selected):
        raise ValueError('Records changed')
    # Consume approval before granting; a lost response cannot authorize another presenter.
    if not await request.app.state.store.pop(key('wallet-approval', token)):
        raise ValueError('Approval already used')
    grant = secrets.token_urlsafe(32)
    source = {**item, 'npub': holder['material']['npub'],
              'records': [{'label': r['label'], 'ref': r['ref']} for r in rows]}
    await put_private(request, 'wallet-grant', grant, owner, source, item['expires'])
    result = await rpc(request, item['origin'], item['pin'], 'accept', item['request_id'],
                       {'grant': grant, 'records': choices(rows)})
    return result


async def remote_operation(request, actor, operation, ident, item, source, record_id=''):
    if operation == 'record-cancel':
        for kind in ('request', 'claim', 'presentation', 'result', 'failed', 'remote', 'wallet-remote'):
            await request.app.state.store.delete(key(kind, ident))
        try:
            await rpc(request, source['origin'], source['pin'], 'cancel', ident, {'grant': source['grant']})
        except Exception:
            pass  # Issuer grant still expires at the original deadline.
        return {'state': 'cancelled'}
    if operation == 'record-status':
        return {'state': 'ready', 'records': source['records'], 'expires': item['expires']}
    if operation != 'record-present':
        raise HTTPException(409, 'This request already has a presenter.')
    record_id = record_id or (source['records'][0]['id'] if len(source['records']) == 1 else '')
    if record_id not in {r['id'] for r in source['records']}:
        raise ValueError('Select an approved record')
    result = await rpc(request, source['origin'], source['pin'], 'present', ident,
                       {'grant': source['grant'], 'record_id': record_id})
    await load(request, ident, actor)
    if result.get('record_id') != record_id or result.get('expires', 0) <= time.time():
        raise ValueError('Invalid presentation')
    result['expires'] = min(result['expires'], item['expires'])
    return result


async def present(request, sender, origin, ident, data):
    owner, source = await private(request, 'wallet-grant', data['grant'])
    if (source['pin'], source['origin'], source['request_id']) != (sender, origin, ident):
        raise ValueError('Grant belongs to another request')
    service = request.app.state.wallets
    async def holder():
        row = await invoke(service.store.get, owner)
        if not row or row['status'] != 'active' or row['material']['npub'] != source['npub']:
            raise ValueError('Wallet changed')
        await private(request, 'wallet-grant', data['grant'], owner)
        return row
    async def check_request():
        terms = await rpc(request, origin, sender, 'details', ident, {})
        if terms != {k: source[k] for k in ('name', 'label', 'expires')}:
            raise ValueError('Request changed')
    await check_request()
    row = await holder()
    selected = next((r for r in source['records'] if selection_id(r) == data['record_id']), None)
    if not selected:
        raise ValueError('Record not approved')
    cache_id = digest([data['grant'], data['record_id']])
    cached = await request.app.state.store.get(key('wallet-result', cache_id))
    if cached:
        result = json.loads(service.store.cipher.decrypt(cached.encode()))['material']
        if result['expires'] <= time.time():
            raise ValueError('Presentation expired')
        return result
    lease = await presentation_lease(service.store, owner)
    try:
        row = await holder()
        cached = await request.app.state.store.get(key('wallet-result', cache_id))
        if cached:
            result = json.loads(service.store.cipher.decrypt(cached.encode()))['material']
            if result['expires'] <= time.time():
                raise ValueError('Presentation expired')
            return result
        matches = matching_records(await service.records(row['material']), source['label'])
        if not any(r['ref'] == selected['ref'] and r['label'] == selected['label'] for r in matches):
            raise ValueError('Record changed')
        capability = await service.record_action(row['material'], 'create_record_capability', selected['ref'], 'present',
                                                await invoke(service.store.preference, owner) or None)
        detail = await service.backend.inspect_scanned_record(row['material'], capability['descriptor'], True)
        if detail['label'].lower() != selected['label'].lower():
            raise ValueError('Record changed')
        result = await render_detail(detail, data['record_id'], source['expires'])
        await holder()
        await check_request()
        await put_private(request, 'wallet-result', cache_id, owner, result, result['expires'])
    finally:
        await invoke(service.store.release, owner, lease)
    from app.presentation_receipts import schedule_receipt
    local_source = {'owner': owner, 'npub': source['npub']}
    if detail['label'].strip('/').split('/')[0].casefold() == 'emergency':
        from app.emergency_contacts import notify_contact
        result['notification'] = await notify_contact(request, cache_id, local_source, result['contents'])
    schedule_receipt(request, cache_id, {'owner': owner, '_remote_name': source['name'] + ' (' + origin + ')'},
                     local_source, detail['label'])
    return result


async def execute(request, envelope, fetch=None):
    if not pos_enabled():
        raise ValueError('POS disabled')
    fetch = fetch or transport
    if not isinstance(envelope, dict) or set(envelope) != {'origin', 'event'}:
        raise ValueError('Invalid envelope')
    origin = canonical_origin(envelope['origin'])
    sender = (await fetch(origin + '/info'))['service_identity']['npub']
    allowed(sender)
    body = verify_card_message(envelope['event'], 'wallet-record-request', sender)
    if (set(body) != {'target', 'nonce', 'operation', 'request_id', 'data'}
            or body['target'] != canonical_origin(request.app.state.settings.origin)
            or not isinstance(body['nonce'], str) or not re.fullmatch('[a-f0-9]{32}', body['nonce'])
            or not isinstance(body['request_id'], str) or not re.fullmatch(TOKEN, body['request_id'])
            or not isinstance(body['data'], dict)):
        raise ValueError('Invalid request')
    op, ident, data = body['operation'], body['request_id'], body['data']
    def limit():
        with closing(request.app.state.wallets.store.connect()) as db, db:
            POSStore._limit(db, 'wallet-federation:' + sender, 1200, 3600)
    await invoke(limit)
    if op in {'details', 'accept'}:
        item = await load(request, ident)
        if op == 'details':
            if data:
                raise ValueError('Invalid details request')
            result = {'name': await invoke(terminal, request, item['actor']), 'label': item['label'], 'expires': item['expires']}
        else:
            if (set(data) != {'grant', 'records'} or not isinstance(data['grant'], str)
                    or not re.fullmatch(TOKEN, data['grant']) or not isinstance(data['records'], list)
                    or not 1 <= len(data['records']) <= 20):
                raise ValueError('Invalid approval')
            seen = set()
            for r in data['records']:
                if (not isinstance(r, dict) or set(r) != {'id', 'label'} or not isinstance(r['id'], str)
                        or not re.fullmatch('[a-f0-9]{24}', r['id']) or r['id'] in seen
                        or not isinstance(r['label'], str) or len(r['label']) > 512
                        or not (r['label'].strip('/').casefold() == item['label'] or r['label'].strip('/').casefold().startswith(item['label'] + '/'))):
                    raise ValueError('Invalid approved record')
                seen.add(r['id'])
            source = {'origin': origin, 'pin': sender, **data}
            previous = await request.app.state.store.get(key('wallet-remote', ident))
            if previous:
                if unseal(request, item, previous) != source:
                    raise ValueError('Request already answered')
            else:
                if not await request.app.state.store.pop(key('claim', ident)):
                    raise ValueError('Request already answered')
                await load(request, ident)
                await sealed_put(request, 'wallet-remote', ident, item, source)
            result = {'state': 'ready', 'records': data['records']}
    elif op in {'present', 'cancel'}:
        expected = {'grant', 'record_id'} if op == 'present' else {'grant'}
        if set(data) != expected or any(not isinstance(v, str) for v in data.values()):
            raise ValueError('Invalid grant request')
        _, source = await private(request, 'wallet-grant', data['grant'])
        if (source['pin'], source['origin'], source['request_id']) != (sender, origin, ident):
            raise ValueError('Wrong grant binding')
        if op == 'cancel':
            await request.app.state.store.delete(key('wallet-grant', data['grant']))
            result = {'state': 'cancelled'}
        else:
            result = await present(request, sender, origin, ident, data)
    else:
        raise ValueError('Unsupported operation')
    return {'event': identity(request).card_message({'request': digest(body), 'result': result}, 'wallet-record-result')}


@router.post(PATH, include_in_schema=False)
async def endpoint(request: Request):
    def limit_peer():
        with closing(request.app.state.wallets.store.connect()) as db, db:
            POSStore._limit(db, 'wallet-federation-peer:' + (request.client.host if request.client else 'unknown'), 1200, 3600)
    await invoke(limit_peer)
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 24000:
            raise HTTPException(413)
    try:
        async with asyncio.timeout(65):
            result = await execute(request, json.loads(raw))
        return JSONResponse(result, headers={'Cache-Control': 'no-store'})
    except Exception:
        raise HTTPException(400, 'Presentation unavailable or not authorized.') from None
