"""Cash invoices and Clear requests, with durable automatic receipt processing."""
import asyncio
import re
import time
from app.wallets import WalletInputError
from app.custody import Busy
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
from acorn.payment_request import decode_payment_request
from app.record_routes import account
from app.wallet_routes import checked_form
from app.request_store import RequestStore
from app.record_previews import _qr_svg
from app.clear_routing import clear_availability

router = APIRouter()


def render(request, session, status=200, **context):
    return request.app.state.templates.TemplateResponse(request=request, name='receive.html',
        context={**session, 'active_page': 'receive', **context}, status_code=status)


@router.get('/account/receive', include_in_schema=False)
async def page(request: Request, ticket: str = ''):
    session, service, owner, material = await account(request)
    store = RequestStore(service.store)
    if ticket:
        try:
            item = store.get(owner, ticket)
            if item['purpose'] not in {'cash-request', 'clear-request'}:
                raise ValueError()
            state = await receipt_status(request, service, owner, material, item)
            return render(request, session, item=item, receipt_state=state, qr=_qr_svg(item['code']) if state != 'complete' else None)
        except ValueError:
            raise HTTPException(404, 'Request not found') from None
    try:
        assets = await request.app.state.send.clear_assets(owner)
    except Exception:
        assets = []
    recent = [i for i in store.recent(owner) if i['purpose'] in {'cash-request', 'clear-request'}][:10]
    return render(request, session, assets=assets, recent=recent)


@router.post('/account/receive', include_in_schema=False)
async def create(request: Request):
    session, service, owner, material = await account(request)
    form = await checked_form(request, session)
    amount = str(form.get('amount', ''))
    if not re.fullmatch('[1-9][0-9]{0,12}', amount):
        return render(request, session, message='Enter a positive whole-number amount.', status=400)
    service.relay(material['relay'])
    try:
        lease = service.store.acquire(owner)
    except Busy:
        return render(request, session, message='Your Acorn is busy. Try again shortly.', status=409)
    try:
        asset_id = str(form.get('asset', ''))
        async with asyncio.timeout(50):
            if asset_id:
                receiver = request.app.state.ecash
                if not receiver or not receiver.clear_available:
                    raise ValueError('Clear receiving unavailable')
                assets = await request.app.state.send.clear_assets(owner)
                asset = next((a for a in assets if a['id'] == asset_id), None)
                if asset is None:
                    raise ValueError('Select an existing Clear balance')
                if clear_availability(asset['mint']) == 'instance':
                    return render(request, session, message='This Clear balance is instance-only. Receive it using your receipt address on the Funds page.', status=422)
                description = str(form.get('description', '')).strip()
                if len(description) > 200:
                    raise ValueError('Description too long')
                code = await service.backend.create_clear_request(material, int(amount), asset, description)
                decoded = decode_payment_request(code)
                item = {'purpose': 'clear-request', 'code': code, 'request_id': decoded.payment_id,
                    'amount': int(amount), 'mint': asset['mint'], 'unit': asset['unit'],
                    'display_name': asset['display_name'], 'display_unit': asset['display_unit'],
                    'scope': clear_availability(asset['mint'])}
            else:
                payment = await request.app.state.payments.request_invoice(owner, int(amount))
                item = {'purpose': 'cash-request', 'code': payment['invoice'], 'payment_id': payment['id'],
                    'amount': int(amount), 'display_name': 'Cash', 'display_unit': 'sats'}
        ident = RequestStore(service.store).save(owner, item)
        return RedirectResponse('/account/receive?ticket='+ident, 303)
    except WalletInputError as exc:
        return render(request, session, message=str(exc), status=503)
    except Exception:
        return render(request, session, message='Could not create this request. Check the amount and receiving configuration, then try again.', status=400)
    finally:
        service.store.release(owner, lease)


async def receipt_status(request, service, owner, material, item):
    if item['purpose'] == 'cash-request':
        payment = request.app.state.payments.store.get(item['payment_id'])
        if not payment or payment['owner'] != owner:
            raise ValueError('Request not found')
        if payment.get('history_written'):
            return 'complete'
        if not payment.get('paid_at') and payment.get('expiry', 0) < time.time():
            return 'expired'
        return 'pending'
    try:
        async with asyncio.timeout(20):
            return await service.backend.clear_request_status(material, item)
    except Exception:
        return 'unavailable'


@router.get('/account/receive/status/{ticket}', include_in_schema=False)
async def status(request: Request, ticket: str):
    session, service, owner, material = await account(request)
    try:
        item = RequestStore(service.store).get(owner, ticket)
        if item['purpose'] not in {'cash-request', 'clear-request'}:
            raise ValueError()
        state = await receipt_status(request, service, owner, material, item)
        return JSONResponse({'state': state})
    except ValueError:
        raise HTTPException(404, 'Request not found') from None
