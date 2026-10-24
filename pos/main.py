"""Isolated POS browser app: encrypted terminal sessions, no account or wallet keys."""
from pos.protocol import CARD_OPS
import json
from pathlib import Path

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from pos.config import POSSettings

COOKIE = '__Host-oakgate_pos'
TTL = 7 * 86400
ROOT = Path(__file__).resolve().parent
FIELDS = {'activation-challenges': {'credential', 'public_key'},
          'activate': {'credential', 'public_key', 'challenge', 'signature'},
          'challenges': {'operation'}, 'config': {'challenge', 'signature'},
          'logout': {'challenge', 'signature'},
          **{op: {'payload', 'challenge', 'signature'} for op in ('receive-config', 'receive', 'receipt', *CARD_OPS)}}


def create_app(settings=None, transport=None):
    settings = settings or POSSettings.from_env()
    cipher = Fernet(settings.cookie_key.encode()) if settings.enabled else None
    app = FastAPI(title='OakGate POS', docs_url=None, redoc_url=None, openapi_url=None)
    app.mount('/static', StaticFiles(directory=ROOT / 'static'), name='static')

    @app.get('/scanner/{filename}')
    async def scanner_asset(filename: str):
        # Share the bundled QR decoder only, not the account application's static surface.
        if filename not in {'qr-scanner.min.js', 'qr-scanner-worker.min.js'}:
            raise HTTPException(404)
        return FileResponse(ROOT.parent / 'app/static' / filename, media_type='text/javascript')

    @app.get('/shared/receive-keypad.js')
    async def keypad():
        return FileResponse(ROOT.parent / 'app/static/receive-keypad.js', media_type='text/javascript')

    @app.middleware('http')
    async def headers(request, call_next):
        response = await call_next(request)
        response.headers.update({'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer',
            'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': 'DENY',
            'Permissions-Policy': 'camera=(self), nfc=(self), microphone=()',
            'Content-Security-Policy': "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; worker-src 'self' blob:; media-src 'self' blob:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"})
        return response

    def token(request):
        value = request.cookies.get(COOKIE, '')
        if not cipher or len(value) > 1024:
            raise HTTPException(403, 'Activate this terminal to continue.')
        try:
            result = cipher.decrypt(value.encode('ascii'), ttl=TTL).decode('ascii')
            if not result.startswith('oakgate-pos-session-v1:'):
                raise ValueError
            return result.split(':', 1)[1]
        except (InvalidToken, ValueError, UnicodeError):
            raise HTTPException(403, 'Activate this terminal to continue.') from None

    async def backend(path, *, data=None, session=None):
        headers = {'Authorization': 'Bearer ' + session} if session else {}
        try:
            async with httpx.AsyncClient(timeout=65, follow_redirects=False, trust_env=False, transport=transport) as client:
                if data is None:
                    result = await client.get(settings.api_url + '/api/pos/v1/' + path)
                else:
                    result = await client.post(settings.api_url + '/api/pos/v1/' + path, json=data, headers=headers)
            if result.status_code in {400, 403, 404, 409, 429, 503}:
                detail = {400: 'Check the amount and currency, or refresh the receiving options.', 404: 'Request not found on this terminal.', 409: 'This request already has a different amount. Start a new request.', 403: 'Authorization failed. Check the key, device or revocation status.',
                          429: 'Too many attempts. Please wait a minute.', 503: 'OakGate POS is unavailable. Please try again shortly.'}
                raise HTTPException(result.status_code, detail[result.status_code])
            result.raise_for_status()
            value = result.json()
            if not isinstance(value, dict):
                raise ValueError
            return value
        except (httpx.HTTPError, ValueError):
            raise HTTPException(503, 'Cannot reach OakGate. Please try again shortly.') from None

    @app.get('/health')
    async def health():
        return {'status': 'ok', 'service': 'oakgate-pos'}

    @app.get('/ready')
    async def ready():
        if not settings.enabled:
            return {'status': 'disabled', 'activation_available': False}
        try:
            payload = await backend('status')
            if payload.get('service') != 'oakgate-pos-api' or payload.get('enabled') is not True:
                raise HTTPException(503)
        except HTTPException:
            return JSONResponse({'status': 'unavailable', 'activation_available': False}, status_code=503)
        return {'status': 'connected', 'phase': 'receiving',
                'activation_available': payload.get('activation_available') is True, 'payments_available': payload.get('payments_available') is True}

    @app.get('/api/session')
    async def session_state(request: Request):
        try:
            token(request)
            active = True
        except HTTPException:
            active = False
        return {'enabled': settings.enabled, 'session_present': active}

    @app.post('/api/{operation}')
    async def proxy(request: Request, operation: str):
        if request.headers.get('origin') != settings.public_url or request.url.query:
            raise HTTPException(403, 'Use this POS site to continue.')
        if operation == 'forget':
            # Local cookie clearing is available even if the feature/backend is down.
            response = JSONResponse({'status': 'local-session-cleared'})
            response.delete_cookie(COOKIE, path='/', secure=True, httponly=True, samesite='strict')
            return response
        if not settings.enabled:
            raise HTTPException(503, 'Point of sale is disabled.')
        if operation not in FIELDS:
            raise HTTPException(404, 'Unknown POS operation')
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 8192:
                raise HTTPException(413, 'Request too large')
        if request.headers.get('content-type', '').split(';')[0] != 'application/json':
            raise HTTPException(415, 'JSON required')
        try:
            data = json.loads(body)
        except (ValueError, UnicodeError):
            raise HTTPException(400, 'Invalid request') from None
        if (not isinstance(data, dict) or set(data) not in ([FIELDS[operation], {'operation', 'payload'}] if operation == 'challenges' else [FIELDS[operation]])
                or any(not isinstance(v, str) or len(v) > 1024 for v in data.values())):
            raise HTTPException(400, 'Invalid request')
        session = None if operation in {'activation-challenges', 'activate'} else token(request)
        payload = await backend(operation, data=data, session=session)
        if operation == 'activate':
            secret = payload.get('session')
            if not isinstance(secret, str) or len(secret) > 128:
                raise HTTPException(503, 'Activation could not be confirmed. Enter your key again on this device.')
            response = JSONResponse({'status': 'activated'})
            response.set_cookie(COOKIE, cipher.encrypt(('oakgate-pos-session-v1:' + secret).encode()).decode(),
                                max_age=TTL, secure=True, httponly=True, samesite='strict', path='/')
            return response
        # Only explicit public fields cross back to browser JavaScript.
        allowed = {'activation-challenges': {'challenge', 'message'}, 'challenges': {'challenge', 'message'},
                   'config': {'name', 'fingerprint', 'scope', 'payments_available'}, 'logout': {'status'},
                   'receive-config': {'assets', 'currencies', 'currency', 'cash_enabled', 'cash_min', 'cash_max', 'clear_max', 'clear_unavailable'},
                   **{op: {'state', 'request_key', 'code', 'qr', 'amount', 'display_name', 'display_unit'} for op in ('receive', 'receipt')},
                   **{op: {'state','pair_code','pair_url','qr','expires','wallet_label','payload','mime','byte_count','card_id','sats','local','clear','clear_unavailable'} for op in CARD_OPS}}[operation]
        response = JSONResponse({k: v for k, v in payload.items() if k in allowed})
        if operation == 'logout':
            response.delete_cookie(COOKIE, path='/', secure=True, httponly=True, samesite='strict')
        return response

    @app.get('/', response_class=HTMLResponse)
    async def home():
        return HTMLResponse((ROOT / 'templates/index.html').read_text())

    @app.get('/logo.png')
    async def logo():
        return FileResponse(ROOT.parent / 'assets/branding/oakgate-logo-flat.png')

    return app


app = create_app()
