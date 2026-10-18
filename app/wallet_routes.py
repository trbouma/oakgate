import secrets
import re
import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, Response
from types import SimpleNamespace
from app import record_previews as previews
from starlette.exceptions import HTTPException

from app.auth import current_session, error_page
from app.custody import AlreadyConnected, Busy, HandleTaken, identity_key
from app.wallets import WalletInputError

router = APIRouter()


async def account_page(request, session, message=None, status=200):
    service = request.app.state.wallets
    context = {**session, 'wallet_enabled': service is not None, 'wallet': None,
               'lightning_address': None, 'balance': None, 'message': message, 'balance_error': False,
               'clear_balances': [], 'clear_error': False, 'active_page': 'balances',
               'default_relay': service.default_relay if service else ''}
    if service:
        try:
            handle = service.store.preference(identity_key(session['user']))
            if handle:
                context['user'] = {**session['user'], 'name': handle}
            record = service.store.get(identity_key(session['user']))
            if record:
                # Never pass recovery secrets or native wallet metadata to templates.
                context['wallet'] = {'npub': record['material']['npub'], 'status': record['status']}
                if record['status'] == 'active':
                    if handle and request.app.state.payments:
                        context['lightning_address'] = request.app.state.payments.address(handle)
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


@router.get('/account/records/{reference}', include_in_schema=False)
async def record_detail_page(request: Request, reference: str):
    session = await current_session(request)
    if not session:
        return RedirectResponse('/auth/login', status_code=303)
    if not re.fullmatch(r'[a-f0-9]{64}', reference):
        raise HTTPException(404, 'Record not found')
    service = request.app.state.wallets
    detail = None
    try:
        record = service.store.get(identity_key(session['user'])) if service else None
        if record and record['status'] == 'active':
            detail = await service.record_detail(record['material'], reference)
    except Exception:
        return error_page(request, 'This record is unavailable right now. Please return to Records and try again.', 503)
    if detail is None:
        return error_page(request, 'Record not found. Return to Records to see the current list.', 404)
    detail = await record_preview(service, record['material'], reference, detail)
    return request.app.state.templates.TemplateResponse(
        request=request, name='record.html', context={**session, 'active_page': 'records', 'record': detail})


async def preferences_page(request, session, message=None, status=200):
    service = request.app.state.wallets
    try:
        handle = service.store.preference(identity_key(session['user'])) if service else ''
    except Exception:
        return error_page(request, 'Preferences are unavailable right now.', 503)
    return request.app.state.templates.TemplateResponse(
        request=request, name='preferences.html', status_code=status,
        context={**session, 'active_page': 'preferences', 'handle': handle,
                 'preferences_enabled': service is not None, 'message': message})


@router.get('/account/preferences', include_in_schema=False)
async def get_preferences(request: Request):
    session = await current_session(request)
    if not session:
        return RedirectResponse('/auth/login', status_code=303)
    return await preferences_page(request, session)


@router.post('/account/preferences', include_in_schema=False)
async def save_preferences(request: Request):
    session = await current_session(request)
    if not session:
        return RedirectResponse('/auth/login', status_code=303)
    form = await checked_form(request, session)
    service = request.app.state.wallets
    if service is None:
        return error_page(request, 'Preferences storage has not been configured yet.', 503)
    try:
        service.store.save_handle(identity_key(session['user']), str(form.get('handle', '')))
    except HandleTaken:
        return await preferences_page(request, session, 'That handle is already taken. Please choose another.', 409)
    except ValueError as exc:
        return await preferences_page(request, session, str(exc), 400)
    except Exception:
        return error_page(request, 'Your preferences could not be saved. Please try again.', 503)
    return await preferences_page(request, session, 'Preferences saved.')


@router.get('/account/transactions', include_in_schema=False)
async def transactions_page(request: Request):
    from app.transactions import transaction_cards
    session = await current_session(request)
    if not session:
        return RedirectResponse('/auth/login', status_code=303)
    service = request.app.state.wallets
    context = {**session, 'active_page': 'balances', 'connected': False,
               'balance': None, 'balance_error': False, 'history_error': False, 'transactions': []}
    try:
        owner = identity_key(session['user'])
        record = service.store.get(owner) if service else None
        if record and record['status'] == 'active':
            context['connected'] = True
            balance, history = await asyncio.gather(service.balance(record['material']),
                                                    service.transactions(record['material']), return_exceptions=True)
            if isinstance(balance, Exception):
                context['balance_error'] = True
            else:
                context['balance'] = balance
            if isinstance(history, Exception):
                context['history_error'] = True
                history = []
            context['transactions'] = transaction_cards(history)
    except Exception:
        return error_page(request, 'Cash transactions are unavailable right now. Please try again shortly.', 503)
    return request.app.state.templates.TemplateResponse(request=request, name='transactions.html', context=context)


async def record_preview(service, material, reference, detail):
    detail = dict(detail)
    value = SimpleNamespace(**detail)
    media_type = previews._effective_blob_media_type(detail.get('blob_type'), value)
    detail.update(blob_type=media_type, blob_preview=previews._blob_preview_kind(media_type),
                  blob_fingerprint=previews._blob_recognition_fingerprint(detail.get('origsha256')),
                  pkpass_preview=None, json_credential_preview=None, mdoc_preview=None,
                  blob_url=f'/account/records/{reference}/file',
                  blob_inline_url=f'/account/records/{reference}/file?inline=true')
    renderers = {
        previews.PKPASS_MIME_TYPE: ('pkpass_preview', previews._pkpass_preview),
        previews.VC_MIME_TYPE: ('json_credential_preview', previews._json_credential_preview),
        previews.VP_MIME_TYPE: ('json_credential_preview', previews._json_credential_preview),
        previews.MDOC_CBOR_MIME_TYPE: ('mdoc_preview', previews._mdoc_preview),
    }
    if detail.get('has_blob') and media_type in renderers:
        try:
            result = await service.record_blob(material, reference)
            if not result:
                raise ValueError('File unavailable')
            field, renderer = renderers[media_type]
            detail[field] = renderer(result[2])
            detail['preview_error'] = detail[field] is None
        except Exception:
            detail['preview_error'] = True
    return detail


@router.get('/account/records/{reference}/file', include_in_schema=False)
async def record_file(request: Request, reference: str, inline: bool = False):
    session = await current_session(request)
    if not session:
        return Response(status_code=401, headers={'Cache-Control': 'no-store'})
    if not re.fullmatch(r'[a-f0-9]{64}', reference):
        raise HTTPException(404, 'Record file not found')
    service = request.app.state.wallets
    try:
        record = service.store.get(identity_key(session['user'])) if service else None
        if not record or record['status'] != 'active':
            raise HTTPException(404, 'Record file not found')
        result = await service.record_blob(record['material'], reference)
        if not result:
            raise HTTPException(404, 'Record file not found')
        detail, media_type, data = result
        media_type = previews._effective_blob_media_type(media_type, SimpleNamespace(**detail))
        if not re.fullmatch(r'[a-z0-9!#$&^_.+-]+/[a-z0-9!#$&^_.+-]+', media_type):
            media_type = 'application/octet-stream'
        allowed = previews._blob_preview_kind(media_type) is not None
        headers = previews._blob_download_headers(detail['label'], media_type, inline=inline and allowed)
        headers.update({'Cache-Control':'no-store', 'X-Content-Type-Options':'nosniff',
                        'Referrer-Policy':'no-referrer',
                        'Content-Security-Policy': "default-src 'none'; sandbox"})
        return Response(data, media_type=media_type, headers=headers)
    except HTTPException:
        raise
    except Exception:
        return error_page(request, 'This record file is unavailable right now. Please try again.', 503)
