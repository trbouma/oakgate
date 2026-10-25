"""Card login verification for the trusted Keycloak authenticator only.

No local-session shortcut: Keycloak validates the user and issues the OIDC token.
PIN failure counts are durable and never reset by a successful card login.
"""
import hashlib
import json
import math
import logging
import os
import re
import secrets
from app.database import DATABASE_ERRORS
import time
from contextlib import closing
from dataclasses import replace

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from app.auth import begin_login, current_session
from app.custody import identity_key
from app.nfc_routes import card_store
from app.oidc import KeycloakProvider
from starlette.concurrency import run_in_threadpool
from app.pos_store import POSDenied, POSStore
from app.recovery import session_binding
from app.wallet_routes import checked_form

router = APIRouter()
logger = logging.getLogger(__name__)


class LoginDenied(POSDenied):
    """Operator-only fixed reason; never include credentials or identity data."""
    def __init__(self, reason):
        self.reason = reason



def enabled():
    return os.getenv('OAKGATE_NFC_LOGIN_ENABLED', 'false').lower() == 'true'


def nfc_provider(request):
    settings = request.app.state.settings
    client = os.getenv('OAKGATE_NFC_CLIENT_ID', 'oakgate-nfc')
    secret = os.getenv('OAKGATE_NFC_CLIENT_SECRET', '')
    if not enabled() or not settings.secure or not secret or client == settings.client_id:
        raise ValueError('NFC login unavailable')
    return KeycloakProvider(replace(settings, client_id=client, client_secret=secret))


def schema(store):
    # Compatibility entry point: schema is validated/initialized by CustodyStore.
    return None


def enrolled(db, store, card_id, issuer):
    row = db.execute("""SELECT c.*, l.identity, l.state AS enrollment, p.verifier AS pin_verifier,
      p.pairing, p.acknowledged FROM nfc_cards c
      JOIN nfc_login_requests l ON l.card_id=c.id JOIN nfc_card_pins p ON p.card_id=c.id
      WHERE c.id=?""", (card_id,)).fetchone()
    if (not row or row['activated'] is None or row['revoked'] is not None
            or row['expires'] <= time.time() or row['acknowledged'] is None
            or row['enrollment'] not in ('requested', 'active')):
        raise LoginDenied('card_or_enrollment_inactive')
    POSStore._wallet(db, row['owner'], row['wallet_id'])
    identity = json.loads(store.custody.cipher.decrypt(row['identity']))
    user = identity['material']
    if (identity['owner'] != row['owner'] or identity_key(user) != row['owner']
            or user['iss'] != issuer):
        raise LoginDenied('identity_binding')
    return row, user


def activate(store, card_id, owner, issuer, *, require_pin=None):
    if require_pin is not None and type(require_pin) is not bool:
        raise POSDenied
    schema(store)
    with closing(store.custody.connect()) as db, db:
        db.execute('BEGIN IMMEDIATE')
        row, _ = enrolled(db, store, card_id, issuer)
        if row['owner'] != owner:
            raise POSDenied
        db.execute("UPDATE nfc_login_requests SET state='active' WHERE card_id=?", (card_id,))
        if require_pin is not None:
            db.execute('INSERT INTO nfc_login_policy(card_id,require_pin) VALUES(?,?) ON CONFLICT(card_id) DO UPDATE SET require_pin=excluded.require_pin', (card_id, int(require_pin)))
        db.execute('DELETE FROM nfc_login_attempts WHERE card_id=?', (card_id,))


def verify_card(store, payload, pin, nonce, issuer):
    # Only OGC2 cards pin the issuer identity. Card parsing never contacts a relay.
    try:
        raw, card_id, _ = store._decode(payload)
    except POSDenied:
        raise LoginDenied('card_decode') from None
    if not raw.startswith(b'OGC2') or (pin != '' and not re.fullmatch(r'[0-9]{4}', pin)):
        raise LoginDenied('card_version_or_pin_format')
    try:
        authority = store.balance_authority(None, payload)
    except POSDenied:
        raise LoginDenied('card_or_wallet_inactive') from None
    schema(store)
    accepted = None
    with closing(store.custody.connect()) as db, db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('DELETE FROM nfc_login_nonces WHERE expires < ?', (time.time(),))
        if db.execute('SELECT 1 FROM nfc_login_nonces WHERE nonce=?', (nonce,)).fetchone():
            raise LoginDenied('replayed_challenge')
        db.execute('INSERT INTO nfc_login_nonces VALUES(?,?)', (nonce, time.time()+600))
        row, user = enrolled(db, store, card_id, issuer)
        if row['enrollment'] != 'active' or row['owner'] != authority['owner']:
            raise LoginDenied('enrollment_not_active')
        db.execute('INSERT INTO nfc_login_attempts(card_id) VALUES(?) ON CONFLICT DO NOTHING', (card_id,))
        failures = db.execute('SELECT failures FROM nfc_login_attempts WHERE card_id=?', (card_id,)).fetchone()[0]
        policy = db.execute('SELECT require_pin FROM nfc_login_policy WHERE card_id=?', (card_id,)).fetchone()
        require_pin = policy is None or policy['require_pin'] != 0
        if not require_pin:
            accepted = user['sub']
        elif pin == '':
            raise LoginDenied('pin_required')
        elif failures < 5:
            # Commit the failed attempt even when denying. Exceptions inside this
            # transaction would roll back the very guard that prevents guessing.
            value = store.custody.cipher.decrypt(row['pin_verifier'])
            prefix = b'oakgate/card-pin/scrypt-v1\x00' + row['pairing'].encode()
            if not value.startswith(prefix) or len(value) != len(prefix)+48:
                raise LoginDenied('pin_verifier_invalid')
            salt, expected = value[len(prefix):len(prefix)+16], value[-32:]
            actual = hashlib.scrypt(pin.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
            if secrets.compare_digest(actual, expected):
                accepted = user['sub']
            else:
                db.execute('UPDATE nfc_login_attempts SET failures=failures+1 WHERE card_id=?', (card_id,))
    if accepted is None:
        raise LoginDenied('pin_locked' if failures >= 5 else 'pin_incorrect')
    return accepted


@router.get('/auth/nfc', include_in_schema=False)
async def login(request: Request):
    try:
        nfc_provider(request)
    except ValueError:
        raise HTTPException(503, 'Card sign-in is unavailable. Use Google or email.') from None
    return await begin_login(request, {'purpose': 'nfc-login'})


@router.post('/api/cards/v1/login/verify', include_in_schema=False)
async def verify(request: Request):
    secret = os.getenv('OAKGATE_NFC_BACKCHANNEL_SECRET', '')
    if (not enabled() or len(secret) < 32 or not secrets.compare_digest(
            request.headers.get('authorization', ''), 'Bearer ' + secret)):
        logger.warning('NFC login rejected phase=backchannel_auth')
        raise HTTPException(401, 'Card sign-in could not be verified.')
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 2048:
            raise HTTPException(400, 'Invalid request')
    try:
        data = json.loads(body)
        if (not isinstance(data, dict) or set(data) != {'card', 'pin', 'nonce', 'issuer', 'client_id'}
                or any(not isinstance(v, str) for v in data.values())
                or not re.fullmatch(r'[a-f0-9]{64}', data['nonce'])
                or data['issuer'] != request.app.state.settings.issuer
                or data['client_id'] != os.getenv('OAKGATE_NFC_CLIENT_ID', 'oakgate-nfc')):
            raise ValueError()
        store = await card_store(request, enabled=False)
        sub = await run_in_threadpool(verify_card, store, data['card'], data['pin'], data['nonce'], data['issuer'])
        return JSONResponse({'sub': sub, 'nonce': data['nonce'], 'issuer': data['issuer']})
    except LoginDenied as exc:
        logger.warning('NFC login rejected phase=%s', exc.reason)
        raise HTTPException(401, 'Card sign-in could not be verified.') from None
    except (ValueError, TypeError, KeyError, POSDenied) as exc:
        logger.warning('NFC login rejected phase=request_or_binding error_type=%s', type(exc).__name__)
        raise HTTPException(401, 'Card sign-in could not be verified.') from None
    except DATABASE_ERRORS as exc:
        logger.warning('NFC login unavailable phase=storage error_type=%s', type(exc).__name__)
        raise HTTPException(503, 'Card sign-in is temporarily unavailable.') from None


@router.post('/account/cards/{ident}/login/activate', include_in_schema=False)
async def activate_start(request: Request, ident: str):
    session = await current_session(request)
    if not session:
        return RedirectResponse('/auth/login', 303)
    form = await checked_form(request, session)
    if (set(form) - {'csrf', 'require_pin', 'acknowledge_card_only'}
            or form.get('require_pin') not in (None, 'yes', 'no')
            or (form.get('require_pin') == 'no' and form.get('acknowledge_card_only') != 'yes')):
        raise HTTPException(400, 'Confirm the risk before enabling card-only sign-in.')
    require_pin = None if 'require_pin' not in form else form['require_pin'] == 'yes'
    if not enabled() or not re.fullmatch(r'[a-f0-9]{32}', ident):
        raise HTTPException(403, 'Card sign-in is unavailable.')
    response = await begin_login(request, {'purpose': 'nfc-enroll', 'card_id': ident, 'require_pin': require_pin,
        'owner': identity_key(session['user']), 'session_binding': session_binding(request),
        'started_at': time.time()})
    if response.status_code != 303:
        return response
    page = request.app.state.templates.TemplateResponse(request=request, name='card_login_verify.html',
        context={**session, 'card_only': require_pin is False, 'authorization_url': response.headers['location']})
    page.raw_headers.extend((k, v) for k, v in response.raw_headers if k == b'set-cookie')
    return page


async def finish_activation(request, transaction, claims):
    session = await current_session(request)
    auth_time = claims.get('auth_time')
    if (not enabled() or not session or session_binding(request) != transaction['session_binding']
            or identity_key(session['user']) != transaction['owner']
            or identity_key(claims) != transaction['owner']
            or type(auth_time) not in (int, float) or not math.isfinite(auth_time)
            or not max(transaction['started_at']-30, time.time()-120) <= auth_time <= time.time()+30):
        raise ValueError('Fresh same-account authentication required')
    store = await card_store(request, enabled=False)
    try:
        await run_in_threadpool(activate, store, transaction['card_id'], transaction['owner'], claims['iss'], require_pin=transaction.get('require_pin'))
    except POSDenied:
        raise ValueError('Card enrollment unavailable') from None
    return RedirectResponse('/account/cards', 303)
