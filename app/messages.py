"""Wallet messaging UI; all user-key operations are delegated to Acorn."""
import asyncio
import hashlib
import json
from app.database import INTEGRITY_ERRORS
import time
from contextlib import closing
from datetime import datetime, timezone
from urllib.parse import urlsplit
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from app.auth import current_session, error_page
from app.custody import identity_key, Busy
from app.wallet_routes import checked_form

router = APIRouter()


def available(service):
    return bool(service and getattr(service.backend, 'messaging_available', False))


def resolver(request):
    service = request.app.state.wallets
    async def resolve(address):
        from acorn.safebox_discovery import normalize_safebox_address
        address = normalize_safebox_address(address)
        name, domain = address.split('@')
        if domain == urlsplit(request.app.state.settings.origin).hostname:
            _, pubkey, relay = request.app.state.ecash.wallet_destination(name)
            return {'pubkey': pubkey, 'relays': [relay]}
        from acorn.wallet_messages import resolve_wallet_message
        destination = await resolve_wallet_message(address)
        # Preserve OakGate's operator-approved relay boundary.
        routes = [r for r in destination['relays'] if r in service.allowed_relays]
        if not routes:
            raise ValueError('No approved wallet relay')
        return {**destination, 'relays': routes}
    return resolve


async def page(request, session, notice=None, status=200):
    service = request.app.state.wallets
    owner = identity_key(session['user'])
    record = service.store.get(owner) if service else None
    connected = bool(record and record['status'] == 'active')
    enabled = available(service)
    rows, failed = [], False
    if connected and enabled:
        try:
            service.relay(record['material']['relay'])
            async with asyncio.timeout(30):
                rows = await service.backend.wallet_messages(record['material'], resolver(request))
            rows = sorted(rows, key=lambda row: row['created_at'], reverse=True)
            for row in rows:
                row['date'] = datetime.fromtimestamp(row['created_at'], timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
        except Exception:
            failed = True
    return request.app.state.templates.TemplateResponse(request=request, name='messages.html', status_code=status,
        context={**session, 'active_page': 'messages', 'connected': connected, 'enabled': enabled,
                 'messages': rows, 'failed': failed, 'notice': notice})


@router.get('/account/messages', include_in_schema=False)
async def inbox(request: Request):
    session = await current_session(request)
    if not session:
        return RedirectResponse('/auth/login', status_code=303)
    notice = 'Message published to the wallet relay. This does not confirm it has been read.' if request.query_params.get('sent') == '1' else None
    return await page(request, session, notice)


@router.post('/account/messages', include_in_schema=False)
async def send(request: Request):
    session = await current_session(request)
    if not session:
        return RedirectResponse('/auth/login', status_code=303)
    form = await checked_form(request, session, max_bytes=65536)
    service = request.app.state.wallets
    if not available(service):
        return error_page(request, 'Wallet messaging requires the updated Safebox Acorn component.', 503)
    owner = identity_key(session['user'])
    record = service.store.get(owner)
    if not record or record['status'] != 'active':
        return error_page(request, 'Connect or create an Acorn first.', 400)
    address, message = str(form.get('recipient', '')).strip(), str(form.get('message', '')).strip()
    if len(address) > 254 or not message or len(message) > 4000:
        return await page(request, session, 'Enter a wallet address and a message of 1 to 4000 characters.', 400)
    try:
        token = service.store.cipher.decrypt(str(form.get('submission', '')).encode(), ttl=600)
        token = json.loads(token)
        if token['owner'] != owner:
            raise ValueError()
        digest = hashlib.sha256(token['nonce'].encode()).hexdigest()
    except Exception:
        return error_page(request, 'This form has expired. Open Wallet messages again.', 400)
    try:
        async with asyncio.timeout(6):
            destination = await resolver(request)(address)
    except Exception:
        return await page(request, session, 'This address does not have an available wallet messaging route. No message was sent.', 400)
    try:
        lease = service.store.acquire(owner)
    except Busy:
        return error_page(request, 'Your wallet is busy. Please wait before trying again.', 409)
    try:
        # No plaintext or recipient stored. A consumed form cannot be replayed,
        # including after a crash or uncertain publication outcome.
        with closing(service.store.connect()) as db, db:
            db.execute('DELETE FROM wallet_message_submissions WHERE created < ?', (time.time()-86400,))
            try:
                db.execute('INSERT INTO wallet_message_submissions VALUES (?,?)', (digest, time.time()))
            except INTEGRITY_ERRORS:
                return error_page(request, 'This message was already submitted. Check with the recipient before sending again.', 409)
        handle = service.store.preference(owner)
        sender = f'{handle}@{urlsplit(request.app.state.settings.origin).hostname}' if handle else None
        service.relay(record['material']['relay'])
        async with asyncio.timeout(30):
            await service.backend.send_wallet_message(record['material'], destination, message, sender)
    except Exception:
        return error_page(request, 'Message delivery could not be confirmed. It may have reached the relay. Check with the recipient before sending again.', 502)
    finally:
        service.store.release(owner, lease)
    return RedirectResponse('/account/messages?sent=1', status_code=303)
