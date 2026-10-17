from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import public_url

APP_DIR = Path(__file__).resolve().parent
LOGO = APP_DIR.parent / "assets" / "branding" / "oakgate-logo-flat.png"

app = FastAPI(
    title="OakGate",
    description="OpenID Access Gate — part of the Mainstay family.",
    version="0.1.0",
    servers=[{"url": public_url()}],
)
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")


@app.get("/", include_in_schema=False)
def home() -> FileResponse:
    return FileResponse(APP_DIR / "static" / "index.html")


@app.get("/logo.png", include_in_schema=False)
def logo() -> FileResponse:
    return FileResponse(LOGO, media_type="image/png")


@app.get("/health", tags=["Operations"])
def health() -> dict[str, str]:
    """Application liveness; does not claim Keycloak is available."""
    return {"status": "ok", "service": "oakgate"}
