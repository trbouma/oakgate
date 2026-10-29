"""Short-lived encrypted pagination tokens bound to one owner's record view."""
import json
import re
import secrets
from urllib.parse import urlencode

from starlette.exceptions import HTTPException
from app.sessions import record_key


async def load_page(request, service, owner, material):
    view = 'folders' if request.query_params.get('view') == 'folders' else 'list'
    folder = request.query_params.get('folder','')[:1024].strip('/') if view == 'folders' else ''
    scope = {'owner':owner,'npub':material['npub'],'relay':material['relay'],'view':view,'folder':folder}
    cursor = None
    token = request.query_params.get('page')
    has_page_token = token is not None
    if token is not None:
        try:
            if not re.fullmatch('[a-f0-9]{32}',token):
                raise ValueError()
            encrypted = await request.app.state.store.get(record_key('record-page',token))
            state = json.loads(service.store.cipher.decrypt(encrypted.encode()))
            if state['scope'] != scope:
                raise ValueError()
            cursor = state['cursor']
        except Exception:
            raise HTTPException(400,'Record page expired or unavailable. Open Records again.') from None
    result = await service.records_page(material,cursor)
    next_url = None
    params = {'view':'folders','folder':folder} if view == 'folders' else {}
    if result['next_cursor'] is not None:
        token = secrets.token_hex(16)
        encrypted = service.store.cipher.encrypt(json.dumps({'scope':scope,'cursor':result['next_cursor']}).encode()).decode()
        await request.app.state.store.put(record_key('record-page',token),encrypted,900)
        next_url = '/account/records?' + urlencode({**params,'page':token})
    return {**result,'next_page_url':next_url, 'first_page_url':'/account/records'+('?' + urlencode(params) if params else ''),
            'paged_records':True, 'has_page_token':has_page_token}
