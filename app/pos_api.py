"""POS authorization; card debit additionally requires a presented bearer card."""
from pos.protocol import CARD_OPS, RECORD_OPS
import json
import asyncio
import os
from app.database import DATABASE_ERRORS
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
    if (not isinstance(data, dict) or set(data) not in (allowed if isinstance(allowed, list) else [set(allowed)])
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
    except DATABASE_ERRORS:
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
                             'phase': 'receiving', 'activation_available': available,
                             'payments_available': available}, headers={'Cache-Control': 'no-store'})

    @router.post('/api/pos/v1/{operation}')
    async def operation(request: Request, operation: str):
        store = storage(request)
        # Bounded attempt rate even when a credential or proof is invalid. Use the
        # actual peer, never untrusted forwarded headers. POS peers share this budget.
        await invoke(store.limit_source, request.client.host if request.client else 'unknown', operation not in {'activation-challenges', 'activate'})
        if request.url.query:
            raise HTTPException(400, 'Queries are not supported')
        fields = {'activation-challenges': {'credential', 'public_key'},
                  'activate': {'credential', 'public_key', 'challenge', 'signature'},
                  'challenges': {'operation'}, 'config': {'challenge', 'signature'},
                  'logout': {'challenge', 'signature'},
                  **{op: {'payload', 'challenge', 'signature'} for op in ('receive-config', 'receive', 'receipt', *CARD_OPS, *RECORD_OPS)}}
        if operation not in fields:
            raise HTTPException(503, 'POS operation is unavailable.')
        if operation == 'challenges':
            fields['challenges'] = [{'operation'}, {'operation', 'payload'}]
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
                result = await invoke(store.challenge, token, data['operation'], data.get('payload', '{}'))
            elif operation in RECORD_OPS:
                actor = await invoke(store.receiving_authority, token, operation, data['challenge'], data['signature'], data['payload'])
                from app.pos_records import operation as record_operation
                try:
                    result = await record_operation(request, actor, operation, data['payload'])
                except HTTPException:
                    raise
                except POSDenied:
                    raise HTTPException(403, 'Record authorization failed.') from None
                except Exception:
                    raise HTTPException(503, 'Record request unavailable. Create a new request.') from None
            elif operation in CARD_OPS and operation != 'card-pay':
                actor = await invoke(store.receiving_authority, token, operation, data['challenge'], data['signature'], data['payload'])
                from app.nfc_routes import card_operation
                result = await card_operation(request, actor, operation, data['payload'])
            elif operation in {'receive-config', 'receive', 'receipt', 'card-pay'}:
                actor = await invoke(store.receiving_authority, token, operation, data['challenge'], data['signature'], data['payload'])
                from app.pos_receiving import receive
                # Keep request creation alive if the terminal disconnects. The journal
                # prevents another request on retry; shutdown drains these tasks.
                if operation == 'card-pay':
                    from app.pos_card_payment import pay
                    task = asyncio.create_task(pay(request, actor, data['payload']))
                else:
                    task = asyncio.create_task(receive(request, actor, operation, data['payload']))
                request.app.state.pos_tasks.add(task)
                def done(task):
                    request.app.state.pos_tasks.discard(task)
                    if not task.cancelled():
                        task.exception()
                task.add_done_callback(done)
                try:
                    result = await asyncio.shield(task)
                except POSDenied:
                    raise HTTPException(403, 'Terminal authorization failed.') from None
                except POSLimited:
                    raise HTTPException(429, 'Too many requests. Please wait before creating another.') from None
                except ValueError:
                    raise HTTPException(400, 'Card payment could not be completed. Check the paying wallet before trying again.') from None
                except (TimeoutError,) + DATABASE_ERRORS:
                    raise HTTPException(503, 'Receipt service is busy. Retry the same request.') from None
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
