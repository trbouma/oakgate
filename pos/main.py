"""Deployable POS shell. Never imports OakGate's wallet application."""
from pathlib import Path
import httpx
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from pos.config import POSSettings


def create_app(settings=None, transport=None):
    settings = settings or POSSettings.from_env()
    app = FastAPI(title='OakGate POS', docs_url=None, redoc_url=None, openapi_url=None)

    @app.get('/health')
    async def health():
        return {'status': 'ok', 'service': 'oakgate-pos'}

    @app.get('/ready')
    async def ready():
        # Explicit diagnostics, separate from local Docker liveness. No proxying
        # arbitrary routes and no wallet credentials are sent to this endpoint.
        if not settings.enabled:
            return JSONResponse({'status': 'disabled', 'activation_available': False}, headers={'Cache-Control': 'no-store'})
        try:
            async with httpx.AsyncClient(timeout=3, follow_redirects=False, trust_env=False, transport=transport) as client:
                response = await client.get(settings.api_url + '/api/pos/v1/status')
                response.raise_for_status()
                payload = response.json()
                if payload.get('service') != 'oakgate-pos-api' or payload.get('enabled') is not True:
                    raise ValueError('Backend not enabled')
        except (httpx.HTTPError, ValueError, AttributeError):
            return JSONResponse({'status': 'unavailable', 'activation_available': False}, status_code=503,
                                headers={'Cache-Control': 'no-store'})
        return JSONResponse({'status': 'connected', 'phase': 'foundation', 'activation_available': False},
                            headers={'Cache-Control': 'no-store'})

    @app.get('/', response_class=HTMLResponse)
    async def home():
        heading = 'Terminal setup is coming next' if settings.enabled else 'Point of sale is disabled'
        detail = ('The POS service is running. Device activation and payment collection are not available yet.'
                  if settings.enabled else 'An operator must enable this service before terminal setup can begin.')
        return HTMLResponse(f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>OakGate POS</title>
<style> :root{{color-scheme:dark;font-family:system-ui,sans-serif;background:#171914;color:#eef0e8}}
body{{margin:0;min-height:100vh;display:grid;place-items:center}} main{{max-width:480px;margin:24px;text-align:center}}
img{{width:64px;height:64px}} .brand{{font-size:12px;letter-spacing:.15em;color:#b7baae}}
section{{margin-top:24px;padding:28px;border:1px solid #4a4f42;border-radius:18px;background:#22251e}}
h1{{font-size:24px}} p{{line-height:1.6;color:#b7baae}} a{{color:#bfd78c}}</style></head>
<body><main><img src="/logo.png" alt=""><p class="brand">MAINSTAY / OAKGATE POS</p>
<section><h1>{heading}</h1><p>{detail}</p><a href="/ready">Check service connection</a></section>
</main></body></html>''', headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"})

    @app.get('/logo.png')
    async def logo():
        return FileResponse(Path(__file__).resolve().parents[1] / 'assets/branding/oakgate-logo-flat.png')

    return app


app = create_app()
