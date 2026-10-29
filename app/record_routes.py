"""Authenticated record workflows; all custody operations delegate to Acorn."""
import asyncio
import hashlib
import json
import logging
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from starlette.exceptions import HTTPException
from fastapi.responses import RedirectResponse
from starlette.datastructures import UploadFile

from app.auth import current_session, error_page
from app.custody import Busy, identity_key
from app.wallets import WalletInputError
from app.wallet_routes import checked_form
from app.record_capabilities import RecordCapabilities
from app.record_settings import RecordSettings
from app.record_previews import _qr_svg
from app.openetr import query_openetr_history, unavailable_openetr_history

router = APIRouter()

async def account(request):
    session = await current_session(request)
    if not session:
        raise HTTPException(401, 'Please sign in')
    service = request.app.state.wallets
    owner = identity_key(session['user'])
    record = service.store.get(owner) if service else None
    if not record or record['status'] != 'active':
        raise HTTPException(404, 'Connect an Acorn first')
    return session, service, owner, record['material']

async def selected(request, reference):
    session, service, owner, material = await account(request)
    if not re.fullmatch('[a-f0-9]{64}', reference):
        raise HTTPException(404, 'Record not found')
    detail = await service.record_detail(material, reference)
    if detail is None:
        raise HTTPException(404, 'Record changed or no longer exists. Return to Records.')
    return session, service, owner, material, detail

def render(request, session, **context):
    return request.app.state.templates.TemplateResponse(request=request, name='record_action.html',
        context={**session, 'active_page': 'records', **context})

def render_new(request, session, **context):
    return request.app.state.templates.TemplateResponse(request=request, name='record_new.html',
        context={**session, 'active_page': 'records', **context})


@router.get('/account/add-record', include_in_schema=False)
async def new_record_form(request: Request):
    session, service, owner, material = await account(request)
    return render_new(request, session)


@router.post('/account/add-record', include_in_schema=False)
async def new_record(request: Request):
    session, service, owner, material = await account(request)
    form, token = None, None
    try:
        form = await checked_form(request, session, max_bytes=26 * 1024 * 1024, multipart=True)
        label = form.get('label', '')
        if not isinstance(label, str) or not label.strip() or len(label.strip()) > 200 or any(ord(c) < 32 for c in label):
            raise HTTPException(400, 'Enter a record label of 1–200 characters.')
        label = label.strip()
        payload = form.get('payload', '')
        if not isinstance(payload, str) or len(payload.encode()) > 262144:
            raise HTTPException(400, 'Record text must be at most 256 KiB.')
        format = form.get('format', 'text')
        if format not in {'text', 'json'}:
            raise HTTPException(400, 'Choose text or JSON.')
        if format == 'json':
            try:
                payload = json.loads(payload, parse_constant=lambda value: (_ for _ in ()).throw(ValueError()))
            except (ValueError, RecursionError):
                raise HTTPException(400, 'Enter valid JSON.') from None
        data, mime = None, None
        upload = form.get('attachment')
        if isinstance(upload, UploadFile) and upload.filename:
            data = await upload.read(25 * 1024 * 1024 + 1)
            if not data or len(data) > 25 * 1024 * 1024:
                raise HTTPException(400, 'Choose a nonempty file up to 25 MiB.')
            mime = upload.content_type or 'application/octet-stream'
        token = service.store.acquire(owner)
        result = await service.record_action(material, 'create_record', label, payload, data, mime)
        if not isinstance(result, dict) or result.get('verified') is not True:
            raise RuntimeError('Save not verified')
        return RedirectResponse('/account/records', status_code=303)
    except HTTPException:
        raise
    except WalletInputError as exc:
        return error_page(request, str(exc), 409)
    except Busy:
        return error_page(request, 'Another Acorn operation is in progress. Please wait and reload.', 409)
    except Exception as exc:
        logging.getLogger(__name__).warning('Record creation unconfirmed error_type=%s', type(exc).__name__)
        return error_page(request, 'The record could not be confirmed. Check Records before trying again.', 503)
    finally:
        if token:
            service.store.release(owner, token)
        if form is not None:
            await form.close()


@router.get('/account/records/{reference}/{action}', include_in_schema=False)
async def record_form(request: Request, reference: str, action: str):
    if action not in {'edit', 'present', 'share', 'check', 'delete'}:
        raise HTTPException(404)
    try:
        session, service, owner, material, detail = await selected(request, reference)
        if action != 'check' and not getattr(service.backend, 'record_workflows_available', True):
            raise HTTPException(503, 'The operator must update the Acorn dependency before enabling record changes and sharing.')
        return render(request, session, action=action, reference=reference, record=detail)
    except HTTPException:
        raise
    except Exception:
        return error_page(request, 'This record is unavailable. Return to Records and try again.', 503)

@router.post('/account/records/{reference}/{action}', include_in_schema=False)
async def record_action(request: Request, reference: str, action: str):
    if action not in {'edit', 'present', 'share', 'check', 'delete'}:
        raise HTTPException(404)
    form = None
    token = None
    try:
        session, service, owner, material, detail = await selected(request, reference)
        form = await checked_form(request, session,
            max_bytes=26 * 1024 * 1024 if action == 'edit' else 8192, multipart=action == 'edit')
        if form.get('confirmed') != 'yes':
            raise HTTPException(400, 'Please confirm this action')
        if action == 'check':
            result = await service.record_blob(material, reference)
            if not result:
                raise HTTPException(400, 'OpenETR checks require an attached original file.')
            digest = hashlib.sha256(result[2]).hexdigest()
            if detail.get('origsha256') and digest != detail['origsha256'].lower():
                raise HTTPException(409, 'The file does not match the recorded fingerprint.')
            config = RecordSettings()
            try:
                history = await asyncio.wait_for(query_openetr_history(digest, config.openetr_relays,
                    timeout=config.openetr_timeout, limit=config.openetr_limit, digest_source="computed"), config.openetr_timeout * 3 + 1)
            except Exception:
                history = unavailable_openetr_history(digest, config.openetr_relays)
            history["verification"]["artifact"]["digest_source"] = "computed"
            url = config.evidence_url(digest)
            return render(request, session, action='checked', reference=reference, record=detail,
                history=history, durable_url=url, durable_qr=_qr_svg(url), bytes_verified=True)
        if not getattr(service.backend, 'record_workflows_available', True):
            raise HTTPException(503, 'The operator must update the Acorn dependency before enabling record changes and sharing.')
        token = service.store.acquire(owner)
        if action == 'delete':
            result = await service.record_action(material, 'delete_record', reference)
            if not isinstance(result, dict) or result.get('verified') is not True:
                return error_page(request, 'Deletion could not be confirmed. Reload Records before trying again.', 503)
            return RedirectResponse('/account/records', status_code=303)
        if action == 'edit':
            payload = form.get('payload', '')
            if not isinstance(payload, str) or len(payload.encode()) > 262144:
                raise HTTPException(400, 'Record text must be at most 256 KiB.')
            format = form.get('format', 'text')
            if format not in {'json', 'text'}:
                raise HTTPException(400, 'Choose text or JSON.')
            if format == 'json':
                try:
                    payload = json.loads(payload, parse_constant=lambda value: (_ for _ in ()).throw(ValueError()))
                except (ValueError, RecursionError):
                    raise HTTPException(400, 'Enter valid JSON.') from None
            upload = form.get('attachment')
            data, mime = None, None
            if isinstance(upload, UploadFile) and upload.filename:
                data = await upload.read(25 * 1024 * 1024 + 1)
                if not data or len(data) > 25 * 1024 * 1024:
                    raise HTTPException(400, 'Choose a nonempty file up to 25 MiB.')
                mime = upload.content_type or 'application/octet-stream'
            label = form.get('label')
            if label is not None and not isinstance(label, str):
                raise HTTPException(400, 'Choose a valid label')
            args = (reference, payload, data, mime) if label is None else (reference, payload, data, mime, label)
            result = await service.record_action(material, 'update_record', *args)
            if not isinstance(result, dict) or result.get('verified') is not True:
                raise RuntimeError('Save not verified')
            return RedirectResponse('/account/records', status_code=303)
        result = await service.record_action(material, 'create_record_capability', reference, action, service.store.preference(owner) or None)
        ident = RecordCapabilities(service.store).save(owner, {**result, 'purpose': action})
        return RedirectResponse('/account/record-shares/' + ident, status_code=303)
    except HTTPException:
        raise
    except Busy:
        return error_page(request, 'Another Acorn operation is in progress. Please wait and reload.', 409)
    except Exception:
        if action == 'check':
            return error_page(request, 'The original file could not be checked. No record was changed. Try again later.', 503)
        if action == 'delete':
            return error_page(request, 'Deletion could not be confirmed. Reload Records before trying again.', 503)
        return error_page(request, 'The operation could not be confirmed. Its outcome may be uncertain. '
            'Reload Records or Active shares before trying again. An unconfirmed sharing copy may remain on the storage server.', 503)
    finally:
        if token:
            service.store.release(owner, token)
        if form is not None:
            await form.close()

@router.get('/account/record-shares', include_in_schema=False)
async def capabilities(request: Request):
    session, service, owner, material = await account(request)
    return render(request, session, action='shares', shares=RecordCapabilities(service.store).list(owner))

@router.get('/account/record-shares/{ident}', include_in_schema=False)
async def capability(request: Request, ident: str):
    session, service, owner, material = await account(request)
    item = RecordCapabilities(service.store).get(owner, ident)
    if not item:
        raise HTTPException(404, 'Share not found')
    return render(request, session, action='capability', item=item, qr=_qr_svg(item['descriptor']),
                  expired=item['expires_at'] <= datetime.now(timezone.utc).timestamp(),
                  remaining_seconds=max(0, min(120, item['expires_at'] - datetime.now(timezone.utc).timestamp())),
                  expiry=datetime.fromtimestamp(item['expires_at'], timezone.utc).strftime('%Y-%m-%d %H:%M UTC'))

@router.post('/account/record-shares/{ident}/stop', include_in_schema=False)
async def stop_capability(request: Request, ident: str):
    session, service, owner, material = await account(request)
    form = await checked_form(request, session)
    await form.close()
    store = RecordCapabilities(service.store)
    item = store.get(owner, ident)
    if not item:
        raise HTTPException(404, 'Share not found')
    try:
        result = await service.record_action(material, 'stop_record_capability', item['descriptor'])
        if not result.get('transfer_deleted'):
            raise RuntimeError('Deletion unconfirmed')
        store.remove(owner, ident)
    except Exception as exc:
        # Log only exception classes/statuses, never descriptor secrets or URLs.
        cause = exc
        seen = set()
        kinds = []
        http_status = None
        while cause is not None and id(cause) not in seen:
            seen.add(id(cause))
            kinds.append(type(cause).__name__)
            response = getattr(cause, 'response', None)
            candidate = getattr(cause, 'status_code', None) or getattr(response, 'status_code', None)
            if isinstance(candidate, int):
                http_status = candidate
            cause = cause.__cause__ or cause.__context__
        logging.getLogger(__name__).warning('Record share stop unconfirmed error_types=%s http_status=%s',
            '/'.join(kinds), http_status or 'unknown')
        message = ('Your Acorn is busy. Please wait and try stopping the share again.' if isinstance(exc, Busy)
                   else 'Deletion could not be confirmed. You are still signed in. The sharing code is retained so you can retry. '
                        'If another wallet already accepted this share, its temporary copy may already have been removed.')
        return error_page(request, message, 409 if isinstance(exc, Busy) else 503,
                          return_url=f'/account/record-shares/{ident}', return_label='Back to share')
    return RedirectResponse('/account/record-shares', status_code=303)
