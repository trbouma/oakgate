"""Receive-only POS authorization; no payment or wallet operations exposed."""
import json
import os
import sqlite3
from functools import partial

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from app.auth import current_session, error_page
from app.custody import identity_key
from app.pos_store import POSDenied, POSLimited
from pos.config import pos_enabled, origin


async def json_body(request, allowed):
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
    if (not isinstance(data, dict) or set(data) != set(allowed)
            or any(not isinstance(v, str) or len(v) > 1024 for v in data.values())):
        raise HTTPException(400, 'Invalid request')
    return data


async def invoke(fn, *args, **kwargs):
    try:
        return await run_in_threadpool(partial(fn, *args, **kwargs))
    except POSDenied:
        raise HTTPException(403, 'Terminal authorization failed. Check the key, device or revocation status.') from None
    except POSLimited:
        raise HTTPException(429, 'Too many attempts or terminals. Please wait or revoke an unused terminal.') from None
    except sqlite3.Error:
        raise HTTPException(503, 'Terminal storage is unavailable. Try again shortly.') from None


def create_router():
    enabled = pos_enabled()
    router = APIRouter(include_in_schema=False)
    public_url = origin(os.getenv('OAKGATE_POS_PUBLIC_URL', 'https://pos.oakgate.safebox.dev'), 'OAKGATE_POS_PUBLIC_URL', https=enabled)

    def storage(request):
        service = getattr(request.app.state, 'pos', None)
        if not enabled or service is None:
            raise HTTPException(503, 'POS is unavailable.')
        return service

    @router.get('/api/pos/v1/status')
    async def status(request: Request):
        available = enabled and getattr(request.app.state, 'pos', None) is not None
        return JSONResponse({'service': 'oakgate-pos-api', 'enabled': enabled,
                             'phase': 'activation', 'activation_available': available,
                             'payments_available': False}, headers={'Cache-Control': 'no-store'})

    @router.post('/api/pos/v1/{operation}')
    async def operation(request: Request, operation: str):
        store = storage(request)
        # Bounded attempt rate even when a credential or proof is invalid. Use the
        # actual peer, never untrusted forwarded headers. POS peers share this budget.
        await invoke(store.limit_source, request.client.host if request.client else 'unknown')
        if request.url.query:
            raise HTTPException(400, 'Queries are not supported')
        fields = {'activation-challenges': {'credential', 'public_key'},
                  'activate': {'credential', 'public_key', 'challenge', 'signature'},
                  'challenges': {'operation'}, 'config': {'challenge', 'signature'},
                  'logout': {'challenge', 'signature'}}
        if operation not in fields:
            raise HTTPException(503, 'POS payments are not available yet.')
        data = await json_body(request, fields[operation])
        if operation in {'activation-challenges', 'activate'}:
            args = [data['credential'], data['public_key']]
            if operation == 'activate':
                args += [data['challenge'], data['signature']]
            result = await invoke(store.activation_challenge if operation == 'activation-challenges' else store.activate, *args)
        else:
            auth = request.headers.get('authorization', '')
            if not auth.startswith('Bearer ') or len(auth) > 256:
                raise HTTPException(403, 'Terminal authorization required')
            token = auth[7:]
            if operation == 'challenges':
                result = await invoke(store.challenge, token, data['operation'])
            else:
                result = await invoke(store.authorized, token, operation, data['challenge'], data['signature'])
        return JSONResponse(result, headers={'Cache-Control': 'no-store'})

    @router.api_route('/api/pos/v1/{path:path}', methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'])
    async def unavailable(path: str):
        raise HTTPException(503, 'POS operation is unavailable.')

    async def owner(request):
        session = await current_session(request)
        return session

    @router.post('/account/pos')
    async def provision(request: Request):
        from app.wallet_routes import checked_form
        session = await owner(request)
        if not session:
            return RedirectResponse('/auth/login', status_code=303)
        store = storage(request)
        form = await checked_form(request, session)
        name = form.get('name', '')
        if not isinstance(name, str):
            raise HTTPException(400, 'Invalid terminal name')
        try:
            credential = await invoke(store.provision, identity_key(session['user']), name)
        except ValueError:
            return error_page(request, 'Use a terminal name of 1–60 characters.', 400, return_url='/account/preferences', return_label='Back to Preferences')
        except HTTPException as exc:
            return error_page(request, 'Connect an active Acorn before creating a terminal.' if exc.status_code == 403 else exc.detail, exc.status_code, return_url='/account/preferences', return_label='Back to Preferences')
        from app.record_previews import _qr_svg
        qr = _qr_svg(credential)
        return request.app.state.templates.TemplateResponse(request=request, name='pos_created.html',
            context={**session, 'active_page': 'preferences', 'credential': credential, 'pos_url': public_url, 'activation_qr': qr})

    @router.post('/account/pos/{terminal}/revoke')
    async def revoke(request: Request, terminal: str):
        from app.wallet_routes import checked_form
        session = await owner(request)
        if not session:
            return RedirectResponse('/auth/login', status_code=303)
        # Owner can revoke even while the feature is disabled.
        service = getattr(request.app.state, 'pos', None)
        if service is None:
            raise HTTPException(503, 'POS storage unavailable')
        await checked_form(request, session)
        await invoke(service.revoke, identity_key(session['user']), terminal)
        return RedirectResponse('/account/preferences', status_code=303)

    return router
