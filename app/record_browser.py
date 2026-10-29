"""Short-lived encrypted pagination tokens bound to one owner's record view."""
import asyncio
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
    pending = []
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
            pending = state.get('pending', [])
        except Exception:
            raise HTTPException(400,'Record page expired or unavailable. Open Records again.') from None
    # A relay batch is not a UI page: internal records and folder filtering can
    # leave just a handful of visible records. Collect 20 plus one lookahead so
    # Next page never means only a trailing empty relay query.
    rows = []
    batches = 0
    exhausted = has_page_token and cursor is None
    visited = {cursor} if cursor is not None else set()
    async with asyncio.timeout(40):
        while True:
            for row in pending:
                label = row['label'].strip('/')
                if view != 'folders' or not folder or label == folder or label.startswith(folder + '/'):
                    rows.append(row)
            if (view != 'folders' and len(rows) > 20) or exhausted:
                break
            if batches >= 100:
                raise ValueError('Record discovery exceeded its page budget')
            result = await service.records_page(material, cursor)
            batches += 1
            next_cursor = result['next_cursor']
            if next_cursor is not None and next_cursor in visited:
                raise ValueError('Record discovery cursor did not advance')
            if next_cursor is not None:
                visited.add(next_cursor)
            cursor = next_cursor
            exhausted = cursor is None
            pending = result['records']
    if view == 'folders':
        # Sort before pagination, not just within each newest-first relay batch.
        # Continuations retain the remaining metadata in encrypted session state.
        rows.sort(key=lambda row: (row['label'].strip('/').casefold(), row['label'].strip('/'), row.get('ref', '')))
    overflow = rows[20:]
    result = {'records': rows[:20]}
    next_url = None
    params = {'view':'folders','folder':folder} if view == 'folders' else {}
    if overflow:
        token = secrets.token_hex(16)
        encrypted = service.store.cipher.encrypt(json.dumps({'scope':scope,'cursor':cursor,'pending':overflow}).encode()).decode()
        await request.app.state.store.put(record_key('record-page',token),encrypted,900)
        next_url = '/account/records?' + urlencode({**params,'page':token})
    return {**result,'next_page_url':next_url, 'first_page_url':'/account/records'+('?' + urlencode(params) if params else ''),
            'paged_records':True, 'has_page_token':has_page_token}
