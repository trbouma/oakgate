"""Fail-closed POS API foundation. No activation or wallet actions yet."""
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pos.config import pos_enabled


def create_router():
    enabled = pos_enabled()  # Configuration is applied at process startup.
    router = APIRouter(prefix='/api/pos/v1', include_in_schema=False)

    @router.get('/status')
    async def status():
        # Public deployment metadata only; no account or wallet information.
        return JSONResponse({'service': 'oakgate-pos-api', 'enabled': enabled,
                             'phase': 'foundation', 'activation_available': False},
                            headers={'Cache-Control': 'no-store'})

    @router.api_route('/{path:path}', methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'])
    async def unavailable(path: str):
        return JSONResponse({'detail': 'POS activation and payments are not available yet.' if enabled else 'POS is disabled.'},
                            status_code=503, headers={'Cache-Control': 'no-store'})

    return router
