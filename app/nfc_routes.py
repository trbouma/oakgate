"""Same-instance wallet approval callback and owner card revocation."""
import json
import asyncio
import hashlib
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from app.auth import current_session
from app.custody import identity_key
from app.pos_api import invoke
from app.wallet_routes import checked_form
from app.record_previews import _qr_svg
from app.nfc_cards import CardStore
from app.clear_balances import payment_assets
from pos.config import pos_enabled

router = APIRouter()

async def card_store(request, *, enabled=True):
    wallets = request.app.state.wallets
    if not wallets or not request.app.state.settings.secure or (enabled and not pos_enabled()):
        raise HTTPException(503, 'Card issuance is unavailable.')
    return await invoke(CardStore, wallets.store, request.app.state.settings.origin)

async def card_operation(request, actor, operation, payload):
    try:
        data = json.loads(payload)
    except ValueError:
        raise HTTPException(400, 'Invalid card request') from None
    if operation == 'card-balance':
        if (not isinstance(data, dict) or set(data) != {'card_payload', 'confirmed'}
                or not isinstance(data['card_payload'], str) or data['confirmed'] != 'yes'):
            raise HTTPException(400, 'Confirm the card balance lookup first.')
        store = await card_store(request)
        authority = await invoke(store.balance_authority, actor['id'], data['card_payload'], limit=True)
        service = request.app.state.wallets
        record = await invoke(service.store.get, authority['owner'])
        if (not record or record['status'] != 'active'
                or hashlib.sha256(record['material']['npub'].encode()).hexdigest() != authority['wallet_id']):
            raise HTTPException(403, 'This card is no longer available.')
        async def clear_balances():
            try:
                async with asyncio.timeout(12):
                    rows = payment_assets(await service.clear_balances(record['material']))
                return [{**{k: row[k] for k in ('id', 'display_name', 'display_unit', 'mint', 'unit')},
                         'amount': str(row['amount'])} for row in rows], False
            except Exception:
                return [], True
        try:
            async with asyncio.timeout(40):
                sats, (clear, clear_unavailable) = await asyncio.gather(
                    service.balance(record['material']), clear_balances())
            if type(sats) is not int or sats < 0:
                raise ValueError('Invalid balance')
        except Exception:
            raise HTTPException(503, 'Balance unavailable. Please tap the card and try again.') from None
        # Do not disclose a result if the card or either wallet was revoked/replaced during lookup.
        await invoke(store.balance_authority, actor['id'], data['card_payload'])
        local = None
        rates = request.app.state.rates
        if rates:
            try:
                currency = await invoke(rates.store.currency, authority['owner'], rates.default_currency)
                estimate = await invoke(rates.estimate, sats, currency)
                if estimate and not estimate['stale']:
                    local = {k: estimate[k] for k in ('code', 'symbol', 'amount')}
            except Exception:
                pass  # A missing/stale exchange rate must not hide the cash balance.
        return {'sats': sats, 'local': local, 'clear': clear, 'clear_unavailable': clear_unavailable}
    fields = {'request_key', 'card_payload'} if operation == 'card-verify' else {'request_key'}
    if (not isinstance(data, dict) or set(data) != fields or any(not isinstance(v,str) for v in data.values())
            or not 16 <= len(data['request_key']) <= 80):
        raise HTTPException(400, 'Invalid card request')
    store = await card_store(request)
    args = [actor['id'], data['request_key']]
    if operation == 'card-verify':
        args.append(data['card_payload'])
    method = {'card-start':store.start, 'card-status':store.status, 'card-prepare':store.prepare,
              'card-verify':store.verify, 'card-cancel':store.cancel}[operation]
    result = await invoke(method, *args)
    if result.get('pair_url'):
        result['qr'] = str(_qr_svg(result['pair_url']))
    return result

@router.get('/account/cards/pair', include_in_schema=False)
async def pair_page(request: Request):
    session = await current_session(request)
    # The fragment is never sent to the server. A signed-out visitor is asked to
    # sign in in another tab and return, so it cannot become an OIDC redirect URL.
    return request.app.state.templates.TemplateResponse(request=request, name='card_pair.html',
        context={**(session or {}), 'pair_signed_in': bool(session), 'active_page':'preferences'})

@router.post('/account/cards/pair/{action}', include_in_schema=False)
async def callback(request: Request, action: str):
    session = await current_session(request)
    if not session:
        raise HTTPException(401, 'Sign in to OakGate, then scan this pairing code again.')
    form = await checked_form(request, session)
    if set(form) != {'csrf','pair_code'} or not isinstance(form['pair_code'],str):
        raise HTTPException(400,'Invalid pairing request')
    store = await card_store(request)
    if action == 'details':
        result = await invoke(store.inspect, form['pair_code'])
    elif action == 'approve':
        result = await invoke(store.approve, form['pair_code'], identity_key(session['user']))
    else:
        raise HTTPException(404)
    return JSONResponse(result)

@router.get('/account/cards', include_in_schema=False)
async def cards(request: Request):
    session = await current_session(request)
    if not session:
        return RedirectResponse('/auth/login',303)
    store = await card_store(request, enabled=False)
    entries = await invoke(store.listing, identity_key(session['user']))
    return request.app.state.templates.TemplateResponse(request=request,name='cards.html',
        context={**session,'cards':entries,'active_page':'preferences'})

@router.post('/account/cards/{ident}/revoke', include_in_schema=False)
async def revoke(request: Request, ident: str):
    session = await current_session(request)
    if not session:
        return RedirectResponse('/auth/login',303)
    await checked_form(request,session)
    store = await card_store(request, enabled=False)
    await invoke(store.revoke,identity_key(session['user']),ident)
    return RedirectResponse('/account/cards',303)
