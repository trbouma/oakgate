"""One-use recovery disclosure after fresh, same-account OIDC authentication."""
import math
import time

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from app.auth import begin_login, cookie_name, current_session, error_page
from app.custody import identity_key
from app.sessions import record_key
from app.wallet_routes import checked_form

router = APIRouter()
REVEAL_TTL = 120


def session_binding(request):
    return record_key('session', request.cookies.get(cookie_name(request, 'session'), ''))


def grant_key(request):
    return record_key('recovery', session_binding(request))


async def finish_reauthentication(request, transaction, claims):
    session = await current_session(request)
    now = time.time()
    authenticated = claims.get('auth_time')
    if (not session or transaction.get('session_binding') != session_binding(request)
            or identity_key(session['user']) != transaction.get('owner')
            or identity_key(claims) != transaction.get('owner')
            or type(authenticated) not in (int, float) or not math.isfinite(authenticated)
            or authenticated < transaction['started_at'] - 30
            or not now - REVEAL_TTL <= authenticated <= now + 30):
        raise ValueError('Fresh same-account authentication required')
    await request.app.state.store.put(grant_key(request),
        {'owner': transaction['owner'], 'expires_at': now + REVEAL_TTL}, REVEAL_TTL)
    return RedirectResponse('/account/recovery', 303)


def wallet_record(request, session):
    service = request.app.state.wallets
    record = service.store.get(identity_key(session['user'])) if service else None
    return record if record and record['status'] == 'active' else None


def render(request, session, **context):
    return request.app.state.templates.TemplateResponse(request=request, name='recovery.html',
        context={**session, 'active_page': 'preferences', **context})


@router.get('/account/recovery', include_in_schema=False)
async def page(request: Request):
    session = await current_session(request)
    if not session:
        return RedirectResponse('/auth/login', 303)
    if not wallet_record(request, session):
        return error_page(request, 'Connect an Acorn before viewing recovery information.', 409)
    grant = await request.app.state.store.get(grant_key(request))
    ready = bool(grant and grant['owner'] == identity_key(session['user']) and grant['expires_at'] > time.time())
    return render(request, session, ready=ready)


@router.post('/account/recovery/verify', include_in_schema=False)
async def verify(request: Request):
    session = await current_session(request)
    if not session:
        return RedirectResponse('/auth/login', 303)
    await checked_form(request, session)
    if not wallet_record(request, session):
        return error_page(request, 'Connect an Acorn before viewing recovery information.', 409)
    await request.app.state.store.delete(grant_key(request))
    response = await begin_login(request, {'purpose': 'recovery', 'owner': identity_key(session['user']),
        'session_binding': session_binding(request), 'started_at': time.time()})
    if response.status_code != 303:
        return response
    # Keep form-action 'self' intact. The external authorization request is an
    # explicit link navigation, not a cross-origin form redirect.
    page = request.app.state.templates.TemplateResponse(request=request, name='recovery_verify.html',
        context={**session, 'active_page': 'preferences', 'authorization_url': response.headers['location']})
    page.raw_headers.extend((name, value) for name, value in response.raw_headers if name == b'set-cookie')
    return page


@router.post('/account/recovery/reveal', include_in_schema=False)
async def reveal(request: Request):
    session = await current_session(request)
    if not session:
        return RedirectResponse('/auth/login', 303)
    form = await checked_form(request, session)
    if form.get('acknowledge') != 'yes':
        return error_page(request, 'Confirm that you are in a private place before revealing recovery information.', 400)
    grant = await request.app.state.store.pop(grant_key(request))
    if not grant or grant['owner'] != identity_key(session['user']) or grant['expires_at'] <= time.time():
        return error_page(request, 'Verify your sign-in again before revealing recovery information.', 403)
    try:
        record = wallet_record(request, session)
        if not record:
            raise ValueError('Wallet unavailable')
        details = request.app.state.wallets.recovery_details(record['material'])
    except Exception:
        return error_page(request, 'Recovery information could not be verified. Please contact your OakGate operator.', 503)
    # Never persist the disclosed material in Redis, logs or redirect URLs.
    return render(request, session, details=details)
