import secrets
import time
from urllib.parse import urlencode

import httpx
from authlib.common.errors import AuthlibBaseError
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.sessions import record_key

router = APIRouter()
LOGIN_TTL = 600
AUTH_FAILURES = (AuthlibBaseError, httpx.HTTPError, ValueError, KeyError, TypeError)


def cookie_name(request, kind):
    return ("__Host-oakgate_" if request.app.state.settings.secure else "oakgate_dev_") + kind


def set_cookie(request, response, kind, value, ttl):
    response.set_cookie(cookie_name(request, kind), value, max_age=ttl,
                        secure=request.app.state.settings.secure,
                        httponly=True, samesite="lax", path="/")


def clear_cookie(request, response, kind):
    response.delete_cookie(cookie_name(request, kind), path="/",
                           secure=request.app.state.settings.secure,
                           httponly=True, samesite="lax")


def error_page(request, message, status=400):
    return request.app.state.templates.TemplateResponse(
        request=request, name="message.html", context={"message": message}, status_code=status)


async def current_session(request):
    value = request.cookies.get(cookie_name(request, "session"))
    if not value:
        return None
    session = await request.app.state.store.get(record_key("session", value))
    if session and session["expires_at"] > time.time():
        if not hasattr(request.state, 'language'):
            from app.custody import identity_key
            import sqlite3
            service = request.app.state.wallets
            try:
                request.state.language = service.store.language(identity_key(session['user'])) if service else 'en'
            except sqlite3.Error:
                # A preference read must not prevent sign-out or session recovery.
                request.state.language = 'en'
        return session
    return None


@router.get("/auth/login", include_in_schema=False)
async def login(request: Request):
    return await begin_login(request)


async def begin_login(request, extra=None):
    if not request.app.state.settings.enabled:
        return error_page(request, "Sign-in is not configured yet. Please try again after setup is complete.", 503)
    transaction = {"state": secrets.token_urlsafe(32), "nonce": secrets.token_urlsafe(32),
                   "verifier": secrets.token_urlsafe(64)}
    transaction.update(extra or {})
    try:
        url = await request.app.state.provider.authorize(transaction)
        binding = secrets.token_urlsafe(32)
        await request.app.state.store.put(
            record_key("login", binding + transaction["state"]), transaction, LOGIN_TTL)
    except AUTH_FAILURES:
        return error_page(request, "The sign-in service is unavailable. Please try again.", 503)
    response = RedirectResponse(url, status_code=303)
    set_cookie(request, response, "login", binding, LOGIN_TTL)
    return response


@router.get("/auth/callback", include_in_schema=False)
async def callback(request: Request):
    state = request.query_params.get("state", "")
    binding = request.cookies.get(cookie_name(request, "login"), "")
    transaction = None
    if state and binding and len(state) <= 256 and len(binding) <= 256:
        transaction = await request.app.state.store.pop(record_key("login", binding + state))
    if not transaction:
        response = error_page(request, "This sign-in has expired or was already used. Please start again.")
    elif request.query_params.get("error"):
        response = error_page(request, "Sign-in was cancelled or declined. You can try again.")
    else:
        try:
            code = request.query_params.get("code")
            if not code or not request.app.state.settings.enabled:
                raise ValueError("Missing code or client configuration")
            claims = await request.app.state.provider.exchange(code, transaction)
            if claims["exp"] <= time.time():
                raise ValueError("Expired identity")
            if transaction.get('purpose') == 'recovery':
                from app.recovery import finish_reauthentication
                response = await finish_reauthentication(request, transaction, claims)
                clear_cookie(request, response, "login")
                return response
            # The validated ID token establishes identity at sign-in. OakGate
            # owns a separate fixed-lifetime session; it does not reuse tokens.
            ttl = request.app.state.settings.session_ttl_seconds
            user = {"iss": claims["iss"], "sub": claims["sub"],
                    "name": claims.get("name") or claims.get("preferred_username") or "OakGate user",
                    "email": claims.get("email"), "email_verified": claims.get("email_verified") is True}
            session_id = secrets.token_urlsafe(32)
            await request.app.state.store.put(record_key("session", session_id),
                {"user": user, "csrf": secrets.token_urlsafe(32), "expires_at": time.time() + ttl}, ttl)
            old = request.cookies.get(cookie_name(request, "session"))
            if old:
                await request.app.state.store.delete(record_key("session", old))
            response = RedirectResponse("/account", status_code=303)
            set_cookie(request, response, "session", session_id, ttl)
        except AUTH_FAILURES:
            response = error_page(request, "We could not verify this sign-in. Please start again.")
    clear_cookie(request, response, "login")
    return response


@router.get("/account", include_in_schema=False)
async def account(request: Request):
    session = await current_session(request)
    if not session:
        return RedirectResponse("/auth/login", status_code=303)
    from app.wallet_routes import account_page
    return await account_page(request, session)


@router.get("/api/me", tags=["Account"])
async def me(request: Request):
    session = await current_session(request)
    if not session:
        return JSONResponse({"detail": "Sign-in required"}, status_code=401)
    return session["user"]


@router.post("/auth/logout", include_in_schema=False)
async def logout(request: Request):
    session = await current_session(request)
    if not session:
        response = RedirectResponse("/", status_code=303)
        clear_cookie(request, response, "session")
        return response
    form = await request.form(max_fields=5, max_files=0)
    csrf = form.get("csrf", "")
    origin = request.headers.get("origin")
    if (not isinstance(csrf, str) or not secrets.compare_digest(csrf, session["csrf"])
            or (origin and origin != request.app.state.settings.origin)):
        return error_page(request, "Please sign out using the button on your account page.", 403)
    value = request.cookies[cookie_name(request, "session")]
    await request.app.state.store.delete(record_key("session", value))
    # Local logout succeeds even when the provider is unavailable.
    try:
        metadata = await request.app.state.provider.metadata()
        url = metadata["end_session_endpoint"] + "?" + urlencode({
            "client_id": request.app.state.settings.client_id,
            "post_logout_redirect_uri": request.app.state.settings.origin + "/",
        })
        response = RedirectResponse(url, status_code=303)
    except AUTH_FAILURES:
        response = error_page(request, "You are signed out of OakGate. The identity service could not be reached, so its sign-in session may still be active.", 200)
    clear_cookie(request, response, "session")
    clear_cookie(request, response, "login")
    return response
