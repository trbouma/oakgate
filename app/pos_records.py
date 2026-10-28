"""Short-lived, terminal-bound record presentations; all wallet crypto stays in Acorn."""
import asyncio
import base64
import hashlib
import json
import re
import secrets
import time
from contextlib import closing

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app.auth import current_session
from app.custody import identity_key
from app.pos_api import invoke
from app.pos_store import POSDenied, POSStore
from app.record_previews import _qr_svg
from app.record_settings import RecordSettings
from app.sessions import record_key
from app.wallet_routes import checked_form
from pos.config import pos_enabled

router = APIRouter()
TTL = 120
# Deliberate disclosure scope. Never accept arbitrary/internal Acorn labels.
LABELS = {'whoami', 'myinfo', 'emergency', 'member', 'pass'}


def key(kind, ident):
    return record_key('pos-record-' + kind, ident)


def terminal(request, actor):
    with closing(request.app.state.wallets.store.connect()) as db:
        row = db.execute('SELECT * FROM pos_terminals WHERE id=? AND revoked IS NULL', (actor['id'],)).fetchone()
        if not row or row['owner'] != actor['owner'] or row['wallet_id'] != actor['wallet_id']:
            raise POSDenied
        POSStore._wallet(db, actor['owner'], actor['wallet_id'])
        return row['name']


async def load(request, ident, actor=None):
    if not isinstance(ident, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', ident):
        raise HTTPException(404, 'Record request unavailable.')
    store = request.app.state.store
    item = await store.get(key('request', ident))
    if (not item or item['expires'] <= time.time()
            or await store.get(key('current', item['actor']['id'])) != ident
            or (actor is not None and item['actor'] != actor)):
        raise HTTPException(404, 'Record request expired or replaced.')
    await invoke(terminal, request, item['actor'])
    return item


async def sealed_put(request, kind, ident, item, value):
    custody = request.app.state.wallets.store
    sealed = custody.seal(item['actor']['owner'], value)
    if isinstance(sealed, bytes):
        sealed = sealed.decode()
    await request.app.state.store.put(key(kind, ident), sealed, max(1, int(item['expires'] - time.time())))


def unseal(request, item, value):
    decoded = json.loads(request.app.state.wallets.store.cipher.decrypt(value.encode()))
    if decoded['owner'] != item['actor']['owner']:
        raise HTTPException(403)
    return decoded['material']


async def fulfil(request, ident, owner, card_check=None, card_payload=None):
    item = await load(request, ident)
    # Atomic one-use claim prevents concurrent QR approvals/NFC taps overwriting a presenter.
    if not await request.app.state.store.pop(key('claim', ident)):
        raise HTTPException(409, 'This request has already been answered. Create a new request.')
    service = request.app.state.wallets
    descriptor = None
    lease = None
    material = None
    try:
        record = await invoke(service.store.get, owner)
        if not record or record['status'] != 'active':
            raise HTTPException(404, 'Connect an Acorn first.')
        material = record['material']
        if card_check:
            await card_check()
        rows = await service.records(material)
        matches = [row for row in rows if row['label'].lower() == item['label']]
        # A duplicate case-variant is ambiguous: do not disclose an arbitrary record.
        if len(matches) != 1:
            raise HTTPException(404, 'A unique matching record was not found.')
        lease = await invoke(service.store.acquire, owner)
        result = await service.record_action(material, 'create_record_capability', matches[0]['ref'], 'present',
                                            await invoke(service.store.preference, owner) or None)
        descriptor = result['descriptor']
        await load(request, ident)
        if card_check:
            await card_check()
        current = await invoke(service.store.get, owner)
        if not current or current['status'] != 'active' or current['material']['npub'] != material['npub']:
            raise HTTPException(403)
        await sealed_put(request, 'presentation', ident, item, {'descriptor': descriptor, 'owner': owner,
                         'npub': material['npub'], 'card_payload': card_payload})
        return {'state': 'ready'}
    except Exception:
        await request.app.state.store.put(key('failed', ident), True, TTL)
        if descriptor and material:
            try:
                await service.record_action(material, 'stop_record_capability', descriptor)
            except Exception:
                pass  # Acorn's short-lived presentation remains subject to its expiry.
        raise
    finally:
        if lease:
            await invoke(service.store.release, owner, lease)


async def operation(request, actor, operation, payload):
    try:
        data = json.loads(payload)
    except ValueError:
        raise HTTPException(400, 'Invalid record request') from None
    fields = {'label'} if operation == 'record-start' else {'request_id', 'card_payload'} if operation == 'record-nfc' else {'request_id'}
    if not isinstance(data, dict) or set(data) != fields or any(not isinstance(v, str) for v in data.values()):
        raise HTTPException(400, 'Invalid record request')
    store = request.app.state.store
    if operation == 'record-start':
        if data['label'] not in LABELS:
            raise HTTPException(400, 'Unsupported record label')
        await invoke(terminal, request, actor)
        old = await store.get(key('current', actor['id']))
        if old:
            for kind in ('request', 'claim', 'presentation', 'result', 'failed'):
                await store.delete(key(kind, old))
        ident = secrets.token_urlsafe(32)
        item = {'actor': actor, 'label': data['label'], 'expires': int(time.time()) + TTL}
        await store.put(key('request', ident), item, TTL)
        await store.put(key('claim', ident), True, TTL)
        await store.put(key('current', actor['id']), ident, TTL)
        url = request.app.state.settings.origin + '/account/record-request#' + ident
        return {'state': 'waiting', 'request_id': ident, 'expires': item['expires'], 'qr': str(_qr_svg(url))}
    ident = data['request_id']
    item = await load(request, ident, actor)
    if operation == 'record-cancel':
        for kind in ('request', 'claim', 'presentation', 'result', 'failed'):
            await store.delete(key(kind, ident))
        return {'state': 'cancelled'}
    if operation == 'record-status':
        state = ('ready' if await store.get(key('presentation', ident)) else
                 'displayed' if await store.get(key('result', ident)) else
                 'unavailable' if await store.get(key('failed', ident)) else 'waiting')
        return {'state': state, 'expires': item['expires']}
    if operation == 'record-nfc':
        from app.nfc_routes import card_store
        cards = await card_store(request)
        auth = await invoke(cards.balance_authority, actor['id'], data['card_payload'], limit=True)
        async def recheck():
            fresh = await invoke(cards.balance_authority, actor['id'], data['card_payload'])
            if fresh != auth:
                raise HTTPException(403)
        return await fulfil(request, ident, auth['owner'], recheck, data['card_payload'])
    if operation != 'record-present':
        raise HTTPException(400)
    sealed = await store.get(key('presentation', ident))
    if not sealed:
        raise HTTPException(409, 'No presentation is ready.')
    service = request.app.state.wallets
    source = unseal(request, item, sealed)
    async def verify_source():
        row = await invoke(service.store.get, source['owner'])
        if not row or row['status'] != 'active' or row['material']['npub'] != source['npub']:
            raise HTTPException(403)
        if source.get('card_payload'):
            from app.nfc_routes import card_store
            cards = await card_store(request)
            auth = await invoke(cards.balance_authority, actor['id'], source['card_payload'])
            if auth['owner'] != source['owner']:
                raise HTTPException(403)
    await verify_source()
    cached = await store.get(key('result', ident))
    if cached:
        result = unseal(request, item, cached)
        if result['expires'] <= time.time():
            raise HTTPException(404)
        await load(request, ident, actor)
        return result
    merchant = await invoke(service.store.get, actor['owner'])
    descriptor = source['descriptor']
    async with asyncio.timeout(40):
        detail = await service.backend.inspect_scanned_record(merchant['material'], descriptor, True)
    if detail['label'].lower() != item['label']:
        raise HTTPException(409)
    contents = detail.get('payload', '')
    text = contents if isinstance(contents, str) else json.dumps(contents, ensure_ascii=False, indent=2)
    if len(text.encode()) > 262144:
        raise HTTPException(413)
    result = {'state': 'displayed', 'label': detail['label'], 'contents': text,
              'expires': min(item['expires'], detail['expires_at']), 'attachment': None,
              'attachment_note': '', 'verification': None, 'publishers': []}
    blob = detail.get('blob_data')
    if blob:
        # Raster images and PDFs are previewed. Never execute HTML/SVG from a presented record.
        media = detail.get('blob_type', '').split(';', 1)[0].strip().lower()
        if media in {'image/jpeg', 'image/png', 'image/webp', 'image/gif', 'application/pdf'} and len(blob) <= 5 * 1024 * 1024:
            result['attachment'] = {'type': media, 'data': base64.b64encode(blob).decode()}
        else:
            result['attachment_note'] = 'This attachment cannot be previewed on this terminal.'
        from app.openetr import query_openetr_history, unavailable_openetr_history
        config = RecordSettings()
        digest = hashlib.sha256(blob).hexdigest()
        try:
            async with asyncio.timeout(config.openetr_timeout * 3 + 1):
                history = await query_openetr_history(digest, config.openetr_relays, timeout=config.openetr_timeout,
                                                     limit=config.openetr_limit, digest_source='computed')
        except Exception:
            history = unavailable_openetr_history(digest, config.openetr_relays)
        result['verification'] = history.get('verification')
        result['publishers'] = [
            {
                'name': (graph.get('signer_profile') or {}).get('display_name')
                        or (graph.get('signer_profile') or {}).get('name')
                        or graph['anchor']['author'],
                'statement': graph['anchor']['content'],
                'signer': graph['anchor']['author'],
                'anchored_at': graph['anchor'].get('created_at', ''),
                'profile': {field: (graph.get('signer_profile') or {}).get(field)
                            for field in ('name', 'display_name', 'about', 'address')},
            }
            for graph in history.get('candidate_graphs', [])
        ]
    await load(request, ident, actor)
    await verify_source()
    if result['expires'] <= time.time():
        raise HTTPException(404)
    await sealed_put(request, 'result', ident, item, result)
    if item['label'] == 'emergency':
        from app.emergency_contacts import notify_contact
        result['notification'] = await notify_contact(request, ident, source, text)
        await sealed_put(request, 'result', ident, item, result)
    from app.presentation_receipts import schedule_receipt
    schedule_receipt(request, ident, actor, source, detail['label'])
    return result


@router.get('/account/record-request', include_in_schema=False)
async def request_page(request: Request):
    session = await current_session(request)
    return request.app.state.templates.TemplateResponse(request=request, name='record_request.html',
        context={**(session or {}), 'request_signed_in': bool(session), 'active_page': 'records'})


@router.post('/account/record-request/{action}', include_in_schema=False)
async def callback(request: Request, action: str):
    session = await current_session(request)
    if not session:
        raise HTTPException(401, 'Sign in and scan the request again.')
    if not pos_enabled() or not request.app.state.wallets:
        raise HTTPException(503)
    form = await checked_form(request, session)
    try:
        if set(form) != {'csrf', 'request_id'} or action not in {'details', 'approve'}:
            raise HTTPException(400)
        ident = form['request_id']
        item = await load(request, ident)
        if action == 'details':
            return JSONResponse({'name': await invoke(terminal, request, item['actor']), 'label': item['label'], 'expires': item['expires']})
        try:
            return JSONResponse(await fulfil(request, ident, identity_key(session['user'])))
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(503, 'The presentation could not be prepared. Ask for a new request.') from None
    finally:
        await form.close()
