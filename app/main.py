from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from redis.exceptions import RedisError

from app.auth import current_session, error_page, router
from app.config import AuthSettings
from app.oidc import KeycloakProvider
from app.sessions import MemoryStore, RedisStore

APP_DIR = Path(__file__).resolve().parent
LOGO = APP_DIR.parent / "assets" / "branding" / "oakgate-logo-flat.png"


def create_app(settings=None, store=None, provider=None):
    settings = settings or AuthSettings.from_env()
    store = store or (RedisStore(settings.redis_url) if settings.redis_url else MemoryStore())

    @asynccontextmanager
    async def lifespan(app):
        yield
        await store.close()

    app = FastAPI(title="OakGate", description="OpenID Access Gate — part of the Mainstay family.",
                  version="0.1.0", servers=[{"url": settings.origin}], lifespan=lifespan)
    app.state.settings = settings
    app.state.store = store
    app.state.provider = provider or KeycloakProvider(settings)
    app.state.templates = Jinja2Templates(directory=APP_DIR / "templates")
    app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
    app.include_router(router)

    @app.middleware("http")
    async def private_responses(request, call_next):
        response = await call_next(request)
        if request.url.path == "/" or request.url.path.startswith(("/auth/", "/account", "/api/me")):
            response.headers["Cache-Control"] = "no-store"
            # no-referrer makes browsers submit HTML forms with Origin: null.
            # Keep the account form's origin available for logout validation,
            # while suppressing callback URLs (which can contain login codes).
            response.headers["Referrer-Policy"] = (
                "strict-origin" if request.url.path == "/account" else "no-referrer"
            )
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
    def health():
        """Application liveness, independent of Keycloak and session storage."""
        return {"status": "ok", "service": "oakgate"}

    return app


app = create_app()
