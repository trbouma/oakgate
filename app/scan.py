"""Authenticated code acquisition; scanning never spends or imports automatically."""
import asyncio
import base64
import re
from types import SimpleNamespace
from app import record_previews as previews
from dataclasses import replace
from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse, Response

from app.custody import Busy
from app.auth import current_session
from app.record_routes import account
from app.wallet_routes import checked_form
from app.request_store import RequestStore
from app.record_settings import RecordSettings
from app.record_previews import _blob_preview_kind
from app.gs1 import product_associations, product_media_type, retrieve_product_artifact
from app.gs1_discovery import acquire_product, discover_product
from app.openetr import query_openetr_history, unavailable_openetr_history
from app.scan_codes import lightning_address_from_lnurl
from app.send import render as payment_form, PaymentInputError

router = APIRouter()


def render(request, session, name, status=200, **context):
    return request.app.state.templates.TemplateResponse(request=request, name=name,
        context={**session, 'active_page': 'scan', **context}, status_code=status)


def payload(form):
    encoded = str(form.get('acquired_payload', ''))
    if len(encoded) > 90000:
        raise ValueError('Code too long')
    value = base64.b64decode(encoded, validate=True).decode('utf-8') if encoded else str(form.get('lightning_payment', ''))
    if not value or len(value.encode()) > 65536:
        raise ValueError('Invalid code length')
    return value  # Do not strip GS1 group separators.


def https_url(code):
    if len(code) > 2048 or '\\' in code or any(c.isspace() or ord(c) < 32 for c in code):
        return None
    try:
        p = urlsplit(code)
        if p.scheme == 'https' and p.hostname and p.username is None and p.password is None and p.port in (None, 443):
            return code
    except ValueError:
        pass
    return None


@router.get('/account/scan', include_in_schema=False)
async def page(request: Request):
    session = await current_session(request)
    if not session:
        return RedirectResponse('/auth/login', 303)
    return render(request, session, 'scan_lightning_address.html')


@router.post('/account/scan', include_in_schema=False)
async def scan(request: Request):
    session, service, owner, material = await account(request)
    service.relay(material['relay'])
    form = await checked_form(request, session, max_bytes=200000)
    raw = ''
    recognized_payment = False
    try:
        raw = payload(form)
        code = raw.strip()
        recognized_payment = code.lower().startswith(('lnbc', 'lightning:lnbc', 'creqa', 'creqb1', 'bitcoin:'))
        if recognized_payment:
            async with asyncio.timeout(40):
                payment = await request.app.state.send.prepare_code(owner, code)
            return RedirectResponse('/account/send?payment='+payment['id'], 303)
        symbology = str(form.get('symbology', ''))[:32]
        mode = str(form.get('acquisition_mode', 'auto'))
        product = acquire_product(raw, mode, symbology) if len(raw) <= 2048 else None
        if product:
            return RedirectResponse('/account/product?' + urlencode({'link': raw, 'mode': mode, 'symbology': symbology}), 303)
        code = raw.strip()
        destination = https_url(code)
        if destination:
            return render(request, session, 'scan_result.html', destination=destination)
        address = code[10:].strip() if code.lower().startswith('lightning:') else code
        if address.lower().startswith('lnurl1'):
            address = lightning_address_from_lnurl(address)
        if re.fullmatch(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9.-]+', address) and len(address) <= 254:
            assets = await request.app.state.send.clear_assets(owner)
            return payment_form(request, session, assets=assets, values={'address': address})
        purpose = ('presentation' if code.startswith('acorn:record-presentation:') else
                   'transfer' if code.startswith('acorn:record-transfer:') else
                   'token' if code.startswith(('cashuA', 'cashuB', 'cashu:')) else None)
        if purpose:
            # Validate/decrypt only through Acorn, and only against configured storage.
            detail = None
            if purpose != 'token':
                async with asyncio.timeout(35):
                    detail = await service.backend.inspect_scanned_record(material, code, purpose == 'presentation')
            ident = RequestStore(service.store).save(owner, {'purpose': purpose, 'code': code})
            preview = presentation_preview(detail, ident) if purpose == 'presentation' else None
            history = None
            if detail and purpose == 'presentation' and detail.get('blob_sha256'):
                config = RecordSettings()
                try:
                    history = await asyncio.wait_for(query_openetr_history(detail['blob_sha256'], config.openetr_relays, timeout=5, limit=50), 16)
                except Exception:
                    history = unavailable_openetr_history(detail['blob_sha256'], config.openetr_relays)
            return render(request, session, 'scan_result.html', purpose=purpose, detail=detail, ticket=ident, preview=preview, history=history)
        message = 'Choose how to interpret this code.'
    except Exception as exc:
        message = str(exc) if isinstance(exc, PaymentInputError) else 'This code could not be reviewed. No payment was sent. Check the code and interpretation, or try again shortly.'
    if recognized_payment:
        return render(request, session, 'scan_payment_error.html', error=message,
            acquired_payload=base64.b64encode(raw.encode()).decode(), status=400)
    return render(request, session, 'scan_review.html', error=message, payload=raw,
        acquired_payload=base64.b64encode(raw.encode()).decode(), symbology=str(form.get('symbology', ''))[:32], acquisition_mode=str(form.get('acquisition_mode','auto')), status=400)


@router.post('/account/scan/accept', include_in_schema=False)
async def accept(request: Request):
    session, service, owner, material = await account(request)
    form = await checked_form(request, session)
    store = RequestStore(service.store)
    ident = str(form.get('ticket', ''))
    item = store.get(owner, ident)
    if item['purpose'] not in {'transfer', 'token'} or form.get('confirmed') != 'yes':
        raise HTTPException(400, 'Confirm the import first')
    try:
        lease = service.store.acquire(owner)
    except Busy:
        return render(request, session, 'scan_result.html', message='Your Acorn is busy. Return to the review and try again shortly.', status=409)
    try:
        if not store.claim(owner, ident):
            return render(request, session, 'scan_result.html', message='This import was already submitted. Check your records or transactions before trying again.')
        async with asyncio.timeout(60):
            if item['purpose'] == 'transfer':
                await service.backend.accept_scanned_record(material, item['code'])
            else:
                result = await service.backend.accept_scanned_token(material, item['code'])
                if not result.get('accepted'):
                    raise ValueError('Acceptance unconfirmed')
        store.complete(owner, ident)
        return RedirectResponse('/account/records' if item['purpose'] == 'transfer' else '/account', 303)
    except Exception:
        return render(request, session, 'scan_result.html', message='The import could not be confirmed. Check records or transactions before trying again; a pending Clear receipt can still be recovered.', status=503)
    finally:
        service.store.release(owner, lease)


@router.get('/account/product', include_in_schema=False)
async def product_page(request: Request, link: str, mode: str = 'auto', symbology: str = '', anchor: str = ''):
    session = await current_session(request)
    if not session:
        return RedirectResponse('/auth/login', 303)
    try:
        product = acquire_product(link, mode, symbology)
        if product is None:
            raise ValueError()
    except ValueError:
        raise HTTPException(400, 'Use a supported GS1 barcode or Digital Link') from None
    config = RecordSettings()
    servers = (config.blossom,)
    history = artifact = discovery = selected = None
    associations = []
    scanned_digest = product.digest
    if not product.digest:
        discovery = await discover_product(product, config.openetr_relays, timeout=5, limit=50)
        for candidate in discovery['candidates']:
            candidate['url'] = '/account/product?' + urlencode(dict(link=link, mode=mode, symbology=symbology, anchor=candidate['id']))
        if anchor:
            selected = next((c for c in discovery['candidates'] if c['id'] == anchor), None)
            if selected is None:
                raise HTTPException(409, 'The selected anchor could not be revalidated. Scan again.')
            product = replace(product, digest=selected['digest'])
    if product.digest:
        async def lookup():
            try:
                return await asyncio.wait_for(query_openetr_history(product.digest, config.openetr_relays, timeout=5, limit=50), 16)
            except Exception:
                return unavailable_openetr_history(product.digest, config.openetr_relays)
        history, artifact = await asyncio.gather(lookup(), retrieve_product_artifact(product.digest, servers, timeout=5, max_bytes=25*1024*1024))
        associations = product_associations(product, history)
    media = product_media_type(artifact['data']) if artifact and artifact['status'] == 'verified' else None
    return render(request, session, 'product_information.html', product=product, openetr_history=history,
        artifact=artifact, associations=associations, relays=config.openetr_relays, servers=servers,
        blob_preview='video' if media == 'video/mp4' else _blob_preview_kind(media),
        blob_inline_url=f'/account/product/artifact/{product.digest}?inline=true' if product.digest else None,
        discovery=discovery, selected_candidate=selected, scanned_digest=scanned_digest,
        raw_payload=link, acquisition_mode=mode, symbology=symbology)


@router.get('/account/product/artifact/{digest}', include_in_schema=False)
async def artifact(request: Request, digest: str, inline: bool = False):
    if not await current_session(request):
        return RedirectResponse('/auth/login', 303)
    if not re.fullmatch('[0-9a-f]{64}', digest):
        raise HTTPException(400, 'Invalid digest')
    result = await retrieve_product_artifact(digest, [RecordSettings().blossom], timeout=5, max_bytes=25*1024*1024)
    if result['status'] != 'verified':
        raise HTTPException(404, 'No digest-verified artifact available')
    media = product_media_type(result['data'])
    disposition = 'inline' if inline and (media == 'video/mp4' or _blob_preview_kind(media)) else 'attachment'
    return Response(result['data'], media_type=media or 'application/octet-stream', headers={
        'Content-Disposition': f'{disposition}; filename="{digest}"',
        'Content-Security-Policy': "sandbox; default-src 'none'", 'X-Content-Type-Options': 'nosniff'})


def presentation_preview(detail, ticket):
    media = previews._effective_blob_media_type(detail.get('blob_type'), SimpleNamespace(**detail))
    result = dict(label=detail['label'], has_blob=detail.get('has_original'), blob_type=media,
        blob_preview=previews._blob_preview_kind(media), blob_fingerprint=previews._blob_recognition_fingerprint(detail.get('blob_sha256')),
        blob_url=f'/account/scan/presentation/{ticket}/file', blob_inline_url=f'/account/scan/presentation/{ticket}/file?inline=true',
        pkpass_preview=None, json_credential_preview=None, mdoc_preview=None)
    renderers = {previews.PKPASS_MIME_TYPE: ('pkpass_preview', previews._pkpass_preview),
        previews.VC_MIME_TYPE: ('json_credential_preview', previews._json_credential_preview),
        previews.VP_MIME_TYPE: ('json_credential_preview', previews._json_credential_preview),
        previews.MDOC_CBOR_MIME_TYPE: ('mdoc_preview', previews._mdoc_preview)}
    if media in renderers:
        key, renderer = renderers[media]
        try:
            result[key] = renderer(detail.get('blob_data'))
        except Exception:
            pass  # Unsupported previews retain an authenticated download link.
    return result


@router.get('/account/scan/presentation/{ticket}/file', include_in_schema=False)
async def presentation_file(request: Request, ticket: str, inline: bool = False):
    session, service, owner, material = await account(request)
    try:
        item = RequestStore(service.store).get(owner, ticket)
        if item['purpose'] != 'presentation':
            raise ValueError()
        async with asyncio.timeout(35):
            detail = await service.backend.inspect_scanned_record(material, item['code'], True)
        data = detail.get('blob_data')
        if not isinstance(data, bytes) or len(data) > 25*1024*1024:
            raise ValueError()
        preview = presentation_preview(detail, ticket)
        media = preview['blob_type']
        if not media or not re.fullmatch(r'[a-z0-9!#$&^_.+-]+/[a-z0-9!#$&^_.+-]+', media):
            media = 'application/octet-stream'
        headers = previews._blob_download_headers(detail['label'], media, inline=inline and bool(preview['blob_preview']))
        headers.update({'Content-Security-Policy': "default-src 'none'; sandbox", 'X-Content-Type-Options': 'nosniff'})
        return Response(data, media_type=media, headers=headers)
    except Exception:
        raise HTTPException(404, 'Presentation unavailable or expired') from None
