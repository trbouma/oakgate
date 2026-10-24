import asyncio

import httpx

from app.main import app


def get(path):
    async def request():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            return await client.get(path)
    return asyncio.run(request())


def test_liveness_does_not_require_keycloak_or_secrets():
    response = get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "oakgate", "version": "0.1.0"}


def test_landing_page_assets_are_available():
    home = get("/")
    assert home.status_code == 200
    assert 'href="/auth/options"' in home.text
    assert get("/static/style.css").status_code == 200
    logo = get("/logo.png")
    assert logo.headers["content-type"] == "image/png"
    assert logo.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert get("/.env").status_code == 404
    assert get("/static/../.env").status_code == 404


def test_api_schema_documents_health():
    schema = get("/openapi.json").json()
    assert schema["info"]["title"] == "OakGate"
    assert "/health" in schema["paths"]


def test_container_explicitly_uses_asyncio_loop():
    import json
    from pathlib import Path
    dockerfile = (Path(__file__).resolve().parents[1] / 'Dockerfile').read_text()
    command = json.loads(next(line[4:] for line in dockerfile.splitlines() if line.startswith('CMD ')))
    assert command[command.index('--loop') + 1] == 'asyncio'
