"""User-reviewed release of account holds; never retries an uncertain transfer."""
from datetime import datetime, timezone
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse
from app.auth import current_session
from app.custody import identity_key, Busy
from app.wallet_routes import checked_form
from app.send import PaymentInputError

router = APIRouter()

def display(item):
    fields = ('id','address','amount','route','state','mint','unit','display_name','display_unit','review_outcome','review_checked_at','review_history_available')
    result = {k:item[k] for k in fields if k in item}
    result['date'] = datetime.fromtimestamp(item['created'],timezone.utc).strftime('%d %b %Y · %H:%M UTC')
    return result

def render(request, session, items, message=None, cards=None, available=None, status=200):
    return request.app.state.templates.TemplateResponse(request=request,name='payment_review.html',context={**session,
        'active_page':'balances','items':[display(i) for i in items], 'message':message,
        'cards':cards,'available':available},status_code=status)

@router.get('/account/payment-review',include_in_schema=False)
async def page(request: Request):
    session=await current_session(request)
    if not session:
        return RedirectResponse('/auth/login',303)
    service=request.app.state.send
    return render(request,session,service.review_items(identity_key(session['user'])) if service else [])

@router.post('/account/payment-review/{ident}/{action}',include_in_schema=False)
async def action(request: Request, ident: str, action: str):
    session=await current_session(request)
    if not session:
        return RedirectResponse('/auth/login',303)
    form=await checked_form(request,session)
    service=request.app.state.send
    owner=identity_key(session['user'])
    if service is None or action not in {'check','resolve'}:
        raise HTTPException(404)
    try:
        service.get(owner,ident)
    except ValueError:
        raise HTTPException(404,'Payment not found') from None
    try:
        if action=='check':
            item,cards,available=await service.check_payment(owner,ident)
            return render(request,session,[item],cards=cards,available=available)
        if form.get('acknowledge') != 'yes':
            raise PaymentInputError('Confirm that this payment must not be sent again.')
        service.resolve_payment(owner,ident,str(form.get('outcome','')))
        return RedirectResponse('/account/payment-review',303)
    except Busy:
        return render(request,session,[service.get(owner,ident)],message='A payment or wallet operation may still be running. Wait a moment and check again.',status=409)
    except PaymentInputError as exc:
        return render(request,session,[service.get(owner,ident)],message=str(exc),status=400)
