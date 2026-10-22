import asyncio
import os
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from redis.exceptions import RedisError

from app.payment_review import router as payment_review_router
from app.scan import router as scan_router
from app.receive import router as receive_router
from app.pos_api import create_router as pos_router
from app.pos_store import POSStore
from pos.config import origin
from app.messages import router as message_router
from app.recovery import router as recovery_router
from app.auth import current_session, error_page, router
from app.config import AuthSettings
from app.version import APP_VERSION
from app.service_info import information
from app.currency_rates import CurrencyRates
from app.ecash import EcashReceiver, router as ecash_router
from app.send import SendService, router as send_router
from app.templating import localization_context
from app.oidc import KeycloakProvider
from app.sessions import MemoryStore, RedisStore
from app.wallets import configured_service
from app.wallet_routes import router as wallet_router
from app.record_routes import router as record_router
from app.payments import PaymentService, router as payment_router

APP_DIR = Path(__file__).resolve().parent
LOGO = APP_DIR.parent / "assets" / "branding" / "oakgate-logo-flat.png"


def create_app(settings=None, store=None, provider=None, wallets=None):
    settings = settings or AuthSettings.from_env()
    store = store or (RedisStore(settings.redis_url) if settings.redis_url else MemoryStore())

    @asynccontextmanager
    async def lifespan(app):
        worker = asyncio.create_task(app.state.payments.run()) if app.state.payments and app.state.payments.config.enabled else None
        rates_worker = asyncio.create_task(app.state.rates.run()) if app.state.rates and app.state.rates.enabled else None
        ecash_worker = asyncio.create_task(app.state.ecash.run()) if app.state.ecash and app.state.ecash.enabled else None
        try:
            yield
        finally:
            if worker:
                worker.cancel()
                with suppress(asyncio.CancelledError):
                    await worker
            if rates_worker:
                rates_worker.cancel()
                with suppress(asyncio.CancelledError):
                    await rates_worker
            if ecash_worker:
                ecash_worker.cancel()
                with suppress(asyncio.CancelledError):
                    await ecash_worker
            await store.close()

    app = FastAPI(title="OakGate", description="OpenID Access Gate — part of the Mainstay family.",
                  version=APP_VERSION, servers=[{"url": settings.origin}], lifespan=lifespan)
    app.state.wallets = wallets if wallets is not None else configured_service()
    pos_origin = origin(os.getenv('OAKGATE_POS_PUBLIC_URL', 'https://pos.oakgate.safebox.dev'), 'OAKGATE_POS_PUBLIC_URL')
    app.state.pos = POSStore(app.state.wallets.store, pos_origin) if app.state.wallets else None
    app.state.ecash = EcashReceiver(app.state.wallets) if app.state.wallets else None
    app.state.send = SendService(app.state.wallets, settings.origin, app.state.ecash) if app.state.wallets else None
    app.state.rates = CurrencyRates(app.state.wallets.store) if app.state.wallets else None
    app.state.payments = PaymentService(app.state.wallets, settings.origin) if app.state.wallets else None
    app.state.settings = settings
    app.state.store = store
    app.state.provider = provider or KeycloakProvider(settings)
    app.state.templates = Jinja2Templates(directory=APP_DIR / "templates", context_processors=[localization_context])
    app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
    app.include_router(router)
    app.include_router(recovery_router)
    app.include_router(wallet_router)
    app.include_router(message_router)
    app.include_router(record_router)
    app.include_router(payment_router)
    app.include_router(ecash_router)
    app.include_router(send_router)
    app.include_router(payment_review_router)
    app.include_router(scan_router)
    app.include_router(receive_router)
    app.include_router(pos_router())

    @app.middleware("http")
    async def private_responses(request, call_next):
        response = await call_next(request)
        if request.url.path == "/" or request.url.path.startswith(("/auth/", "/account", "/api/me")):
            response.headers["Cache-Control"] = "no-store"
            # no-referrer makes browsers submit HTML forms with Origin: null.
            # Keep the account form's origin available for logout validation,
            # while suppressing callback URLs (which can contain login codes).
            response.headers["Referrer-Policy"] = (
                "strict-origin" if request.url.path.startswith("/account") else "no-referrer"
            )
        if request.url.path.startswith('/account/recovery'):
            response.headers['Cache-Control'] = 'no-store, private, max-age=0'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Referrer-Policy'] = 'strict-origin'
            response.headers['X-Frame-Options'] = 'DENY'
            response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'"
        if request.url.path.startswith(('/account/pos', '/api/pos/')):
            response.headers['Cache-Control'] = 'no-store, private'
            response.headers['Referrer-Policy'] = 'no-referrer'
            response.headers['X-Frame-Options'] = 'DENY'
        response.headers["Content-Language"] = getattr(request.state, "language", "en")
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(RedisError)
    async def unavailable_store(request, exc):
        return error_page(request, "Your session service is unavailable. Please try again shortly.", 503)

    @app.get("/", include_in_schema=False)
    async def home(request: Request):
        if await current_session(request):
            return RedirectResponse("/account", status_code=303)
        return FileResponse(APP_DIR / "static" / "index.html")

    @app.get("/logo.png", include_in_schema=False)
    def logo():
        return FileResponse(LOGO, media_type="image/png")

    @app.get("/health", tags=["Operations"])
    async def health():
        """Application liveness, independent of Keycloak and session storage."""
        return JSONResponse({"status": "ok", "service": "oakgate", "version": APP_VERSION},
                            headers={"Cache-Control": "no-store"})

    @app.get("/info", tags=["Operations"])
    def info():
        """Public identity and supported software features, not readiness."""
        return JSONResponse(information(app), headers={"Cache-Control": "no-store"})

    return app


app = create_app()
