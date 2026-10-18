import secrets
import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from starlette.exceptions import HTTPException

from app.auth import current_session, error_page
from app.custody import AlreadyConnected, Busy, identity_key
from app.wallets import WalletInputError

router = APIRouter()


async def account_page(request, session, message=None, status=200):
    service = request.app.state.wallets
    context = {**session, 'wallet_enabled': service is not None, 'wallet': None,
               'balance': None, 'message': message, 'balance_error': False,
               'clear_balances': [], 'clear_error': False, 'active_page': 'balances',
               'default_relay': service.default_relay if service else ''}
    if service:
        try:
            record = service.store.get(identity_key(session['user']))
            if record:
                # Never pass recovery secrets or native wallet metadata to templates.
                context['wallet'] = {'npub': record['material']['npub'], 'status': record['status']}
                if record['status'] == 'active':
                    cash, clear = await asyncio.gather(
                        service.balance(record['material']),
                        service.clear_balances(record['material']), return_exceptions=True)
                    if isinstance(cash, Exception):
                        context['balance_error'] = True
                    else:
                        context['balance'] = cash
                    if isinstance(clear, Exception):
                        context['clear_error'] = True
                    else:
                        context['clear_balances'] = clear
        except Exception:
            return error_page(request, 'Safebox storage is unavailable. Please try again shortly.', 503)
    return request.app.state.templates.TemplateResponse(
        request=request, name='account.html', context=context, status_code=status)


async def checked_form(request, session):
    # Bound request size before parsing; never echo or log a submitted phrase.
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 8192:
            raise HTTPException(413, 'Form is too large')
    request._body = bytes(body)
    if request.headers.get('content-type', '').split(';')[0] != 'application/x-www-form-urlencoded':
        raise HTTPException(415, 'Use the account page form')
    form = await request.form(max_fields=8, max_files=0)
    csrf = form.get('csrf', '')
    origin = request.headers.get('origin')
    if (not isinstance(csrf, str) or not secrets.compare_digest(csrf, session['csrf'])
            or (origin and origin != request.app.state.settings.origin)):
        raise HTTPException(403, 'Please use the form on your account page')
    return form


@router.post('/account/acorn/{action}', include_in_schema=False)
async def manage_wallet(request: Request, action: str):
    session = await current_session(request)
    if not session:
        return RedirectResponse('/auth/login', status_code=303)
    form = await checked_form(request, session)
    service = request.app.state.wallets
    if service is None:
        return error_page(request, 'Safebox storage has not been configured yet.', 503)
    owner = identity_key(session['user'])
    try:
        record = service.store.get(owner)
        if action == 'retry':
            if not record:
                return RedirectResponse('/account', status_code=303)
            await service.initialize(owner)
        elif action in {'create', 'connect'}:
            if record:
                return RedirectResponse('/account', status_code=303)
            if form.get('custody') != 'accept':
                raise WalletInputError('Confirm that OakGate may store your safebox recovery information.')
            if action == 'create':
                material = await service.backend.prepare(service.default_relay)
                service.store.insert(owner, material, 'pending')
                await service.initialize(owner)
            else:
                relay = service.relay(str(form.get('relay', '')))
                material = service.backend.recover(str(form.get('phrase', '')), relay,
                                                   legacy=form.get('legacy') == 'yes')
                # Loading must succeed; recovery must never create a replacement.
                await service.balance(material)
                service.store.insert(owner, material, 'active')
        else:
            raise HTTPException(404)
    except WalletInputError as exc:
        return await account_page(request, session, message=str(exc), status=400)
    except AlreadyConnected:
        return await account_page(request, session, message='An Acorn is already connected to an OakGate account. No connection was replaced.', status=409)
    except Busy:
        return await account_page(request, session, message='Setup is already running. Please wait, then refresh this page.', status=409)
    except HTTPException:
        raise
    except Exception:
        # Acorn and relay exceptions can contain private payloads. Do not expose them.
        return await account_page(request, session, message='We could not finish this request. For an existing Acorn, check the phrase and bootstrap relay. If new Acorn setup is pending, use Retry setup; its recovery information is already saved.', status=503)
    return RedirectResponse('/account', status_code=303)


@router.get('/account/records', include_in_schema=False)
async def records_page(request: Request):
    session = await current_session(request)
    if not session:
        return RedirectResponse('/auth/login', status_code=303)
    service = request.app.state.wallets
    context = {**session, 'active_page': 'records', 'records': [],
               'records_error': False, 'connected': False}
    if service:
        try:
            record = service.store.get(identity_key(session['user']))
            if record and record['status'] == 'active':
                context['connected'] = True
                try:
                    context['records'] = await service.records(record['material'])
                except Exception:
                    context['records_error'] = True
        except Exception:
            return error_page(request, 'Safebox storage is unavailable. Please try again shortly.', 503)
    return request.app.state.templates.TemplateResponse(
        request=request, name='records.html', context=context)
