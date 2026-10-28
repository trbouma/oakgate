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
from app.custody import identity_key, Busy
from app.pos_api import invoke
from app.pos_store import POSDenied, POSStore
from app.record_previews import _qr_svg
from app.record_settings import RecordSettings
from app.sessions import record_key
from app.wallet_routes import checked_form
from pos.config import pos_enabled

def preview_attachment(blob, declared_type):
    """Select a bounded preview; PDF.js still validates and parses PDF bytes."""
    media = str(declared_type or '').split(';', 1)[0].strip().lower()
    if media in {'', 'application/octet-stream', 'binary/octet-stream', 'application/x-pdf'} and blob.startswith(b'%PDF-'):
        media = 'application/pdf'
    if len(blob) > 5 * 1024 * 1024:
        return None, 'This attachment exceeds the 5 MiB POS preview limit.'
    if media not in {'image/jpeg', 'image/png', 'image/webp', 'image/gif', 'application/pdf'}:
        return None, 'This attachment format is not supported by the POS preview.'
    return {'type': media, 'data': base64.b64encode(blob).decode()}, ''


router = APIRouter()
TTL = 120
# Deliberate disclosure scope. Never accept arbitrary/internal Acorn labels.
LABELS = {'whoami', 'myinfo', 'emergency', 'health', 'benefits', 'member', 'pass'}


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


def selection_id(row):
    return hashlib.sha256((row['label'] + '\0' + row['ref']).encode()).hexdigest()[:24]


def matching_records(rows, category):
    matches = [row for row in rows if row['label'].lower() == category
               or row['label'].lower().startswith(category + '/')]
    if not matches or len(matches) > 20 or len({r['label'].lower() for r in matches}) != len(matches):
        raise HTTPException(404, 'No unambiguous record selection is available (maximum 20 records).')
    return sorted(matches, key=lambda row: row['label'].lower())


def choices(rows):
    return [{'id': selection_id(row), 'label': row['label']} for row in rows]


async def presentation_lease(store, owner):
    # A just-published presentation receipt may briefly hold the same wallet.
    # Retry acquisition only, never retry the Acorn operation itself.
    for attempt in range(31):
        try:
            return await invoke(store.acquire, owner)
        except Busy:
            if attempt == 30:
                raise
            await asyncio.sleep(0.1)


async def verify_presenter(request, actor, source):
    service = request.app.state.wallets
    row = await invoke(service.store.get, source['owner'])
    if not row or row['status'] != 'active' or row['material']['npub'] != source['npub']:
        raise HTTPException(403)
    if source.get('card_payload'):
        from app.nfc_routes import card_store
        cards = await card_store(request)
        auth = await invoke(cards.balance_authority, actor['id'], source['card_payload'])
        if auth['owner'] != source['owner']:
            raise HTTPException(403)
    return row


async def fulfil(request, ident, owner, card_check=None, card_payload=None, selected=None):
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
        matches = matching_records(rows, item['label'])
        if not card_check:
            if selected is None:
                if len(matches) != 1:
                    raise HTTPException(400, 'Select the records to present.')
            else:
                if (not isinstance(selected, list) or not selected or len(selected) > 20
                        or any(not isinstance(v, str) for v in selected)
                        or len(set(selected)) != len(selected)):
                    raise HTTPException(400, 'Invalid selection.')
                approved = [row for row in matches if selection_id(row) in selected]
                if len(approved) != len(selected):
                    raise HTTPException(409, 'Records changed. Scan a new request.')
                matches = approved
        # Multiple matches only disclose the approved index; create a capability on selection.
        if len(matches) == 1:
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
                         'npub': material['npub'], 'card_payload': card_payload,
                         'records': [{'label': r['label'], 'ref': r['ref']} for r in matches]})
        return {'state': 'ready', 'records': choices(matches)}
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
    valid_fields = [fields, fields | {'record_id'}] if operation == 'record-present' else [fields]
    if not isinstance(data, dict) or set(data) not in valid_fields or any(not isinstance(v, str) for v in data.values()):
        raise HTTPException(400, 'Invalid record request')
    store = request.app.state.store
    if operation == 'record-start':
        if data['label'] not in LABELS:
            raise HTTPException(400, 'Unsupported record label')
        await invoke(terminal, request, actor)
        old = await store.get(key('current', actor['id']))
        if old:
            for kind in ('request', 'claim', 'presentation', 'result', 'failed', 'remote', 'wallet-remote'):
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
    wallet_remote = await store.get(key('wallet-remote', ident))
    if wallet_remote:
        from app.record_federation import remote_operation
        return await remote_operation(request, actor, operation, ident, item,
                                      unseal(request, item, wallet_remote), data.get('record_id', ''))
    # Remote state is encrypted and retains the original local request lifetime.
    remote_sealed = await store.get(key('remote', ident))
    if remote_sealed:
        from app.card_federation import call_remote
        source = unseal(request, item, remote_sealed)
        if operation in {'record-status', 'record-present', 'record-cancel'}:
            if operation == 'record-cancel':
                # Closing locally must work even when the issuer is offline. Its
                # copy retains the original two-minute expiry, never extended.
                for kind in ('request', 'claim', 'presentation', 'result', 'failed', 'remote', 'wallet-remote'):
                    await store.delete(key(kind, ident))
                try:
                    await call_remote(request, actor, source['card'], operation, ident, {'record_id': ''})
                except Exception:
                    pass
                return {'state': 'cancelled'}
            result = await call_remote(request, actor, source['card'], operation, ident,
                                       {'record_id': data.get('record_id', '')})
            await load(request, ident, actor)
            return result
        raise HTTPException(409, 'This request already has a presenter.')
    if operation == 'record-cancel':
        for kind in ('request', 'claim', 'presentation', 'result', 'failed', 'remote', 'wallet-remote'):
            await store.delete(key(kind, ident))
        return {'state': 'cancelled'}
    if operation == 'record-status':
        sealed = await store.get(key('presentation', ident))
        if sealed:
            source = unseal(request, item, sealed)
            await verify_presenter(request, actor, source)
            await load(request, ident, actor)
            return {'state': 'ready', 'expires': item['expires'], 'records': choices(source['records'])}
        return {'state': 'unavailable' if await store.get(key('failed', ident)) else 'waiting', 'expires': item['expires']}
    if operation == 'record-nfc':
        from app.card_federation import remote_card, call_remote
        if remote_card(request, data['card_payload']):
            if not await store.pop(key('claim', ident)):
                raise HTTPException(409, 'This request already has a presenter.')
            await sealed_put(request, 'remote', ident, item, {'card': data['card_payload']})
            result = await call_remote(request, actor, data['card_payload'], 'record-open', ident,
                                       {'label': item['label'], 'expires': item['expires']})
            await load(request, ident, actor)
            return result
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
        return await verify_presenter(request, actor, source)
    await verify_source()
    records = source['records']
    requested = data.get('record_id')
    selected = next((r for r in records if selection_id(r) == requested), None) if requested else records[0] if len(records) == 1 else None
    if selected is None:
        raise HTTPException(400, 'Select an approved record.')
    record_id = selection_id(selected)
    cached = await store.get(key('result', ident))
    if cached:
        result = unseal(request, item, cached)
        if result.get('record_id') == record_id:
            if result['expires'] <= time.time():
                raise HTTPException(404)
            await load(request, ident, actor)
            return result
    merchant = await invoke(service.store.get, actor['owner'])
    descriptor = source['descriptor']
    if not descriptor:
        holder = await verify_source()
        matches = matching_records(await service.records(holder['material']), item['label'])
        if not any(r['ref'] == selected['ref'] and r['label'] == selected['label'] for r in matches):
            raise HTTPException(409, 'Record changed. Create a new request.')
        lease = await presentation_lease(service.store, source['owner'])
        try:
            await load(request, ident, actor)
            holder = await verify_source()
            capability = await service.record_action(holder['material'], 'create_record_capability', selected['ref'], 'present',
                                                    await invoke(service.store.preference, source['owner']) or None)
            descriptor = capability['descriptor']
        finally:
            await invoke(service.store.release, source['owner'], lease)
    await load(request, ident, actor)
    await verify_source()
    async with asyncio.timeout(40):
        detail = await service.backend.inspect_scanned_record(merchant['material'], descriptor, True)
    if detail['label'].lower() != selected['label'].lower():
        raise HTTPException(409)
    result = await render_detail(detail, record_id, item['expires'])
    await load(request, ident, actor)
    await verify_source()
    if result['expires'] <= time.time():
        raise HTTPException(404)
    await sealed_put(request, 'result', ident, item, result)
    if detail['label'].lower() == 'emergency':
        from app.emergency_contacts import notify_contact
        result['notification'] = await notify_contact(request, ident, source, result['contents'])
        await sealed_put(request, 'result', ident, item, result)
    from app.presentation_receipts import schedule_receipt
    schedule_receipt(request, ident + ':' + record_id, actor, source, detail['label'])
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
        if form.get('remote') == '1':
            if action not in {'details', 'approve'} or set(form) not in ({'csrf', 'request_id', 'remote'}, {'csrf', 'request_id', 'remote', 'selected'}):
                raise HTTPException(400)
            from app.record_federation import wallet_action
            try:
                selected = json.loads(form['selected']) if 'selected' in form else None
                result = await wallet_action(request, identity_key(session['user']), form['request_id'], action, selected)
                return JSONResponse(result, headers={'Cache-Control': 'no-store'})
            except Exception:
                raise HTTPException(400, 'Presentation unavailable. Scan a new request.') from None
        if set(form) not in ({'csrf', 'request_id'}, {'csrf', 'request_id', 'selected'}) or action not in {'details', 'approve'}:
            raise HTTPException(400)
        ident = form['request_id']
        item = await load(request, ident)
        if action == 'details':
            holder = await invoke(request.app.state.wallets.store.get, identity_key(session['user']))
            if not holder or holder['status'] != 'active':
                raise HTTPException(404, 'Connect an Acorn first.')
            matches = matching_records(await request.app.state.wallets.records(holder['material']), item['label'])
            await load(request, ident)
            return JSONResponse({'name': await invoke(terminal, request, item['actor']), 'label': item['label'], 'expires': item['expires'], 'records': choices(matches)})
        try:
            try:
                selected = json.loads(form['selected']) if 'selected' in form else None
            except ValueError:
                raise HTTPException(400, 'Invalid selection.') from None
            return JSONResponse(await fulfil(request, ident, identity_key(session['user']), selected=selected))
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(503, 'The presentation could not be prepared. Ask for a new request.') from None
    finally:
        await form.close()


async def render_detail(detail, record_id, expires):
    contents = detail.get('payload', '')
    text = contents if isinstance(contents, str) else json.dumps(contents, ensure_ascii=False, indent=2)
    if len(text.encode()) > 262144:
        raise HTTPException(413)
    result = {'state': 'displayed', 'record_id': record_id, 'label': detail['label'], 'contents': text,
              'expires': min(expires, detail['expires_at']), 'attachment': None,
              'attachment_note': '', 'verification': None, 'publishers': []}
    blob = detail.get('blob_data')
    if blob:
        result['attachment'], result['attachment_note'] = preview_attachment(blob, detail.get('blob_type'))
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
    return result
