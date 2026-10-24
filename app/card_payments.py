"""Signed, read-only NFC recipient resolution; settlement stays in SendService."""
import hashlib
import json
import os
import re
import secrets
from contextlib import closing
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.identity import verify_card_message
from app.nfc_cards import CardStore, card_header
from app.pos_store import POSStore
from app.send import public_json, PaymentInputError

router = APIRouter()
PATH = '/api/cards/v1/recipient'


def canonical_origin(value):
    if not isinstance(value, str) or len(value) > 200:
        raise ValueError('Invalid issuer')
    p = urlsplit(value)
    if (p.scheme != 'https' or not p.hostname or p.username or p.password
            or p.port not in (None,443) or p.path or p.query or p.fragment
            or value != 'https://' + p.hostname):
        raise ValueError('Invalid issuer')
    return value


def card_issuer(encoded):
    _, origin, _, _ = card_header(encoded)
    return canonical_origin(origin)


def pinned_issuer(encoded):
    _, origin, npub, _ = card_header(encoded)
    if not npub:
        raise PaymentInputError('This card has no pinned issuer key. Reissue it before receiving card payments.')
    return canonical_origin(origin), npub


def identity(request):
    service = request.app.state.payments
    if not service or not service.identity.npub:
        raise ValueError('Service identity is required')
    return service.identity


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


async def issue_destination(request, envelope, fetch=public_json):
    own = canonical_origin(request.app.state.settings.origin)
    sender = canonical_origin(envelope['origin'])
    signer = identity(request)
    info = {'service_identity': signer.public_info()} if sender == own else await fetch(sender+'/info')
    npub = info['service_identity']['npub']
    allowed = os.getenv('OAKGATE_CARD_TRUSTED_INSTANCES','').replace(',', ' ').split()
    if allowed and npub not in allowed:
        raise ValueError('Sending instance is not allowed')
    body = verify_card_message(envelope['event'], 'pay-to-card', npub)
    if (set(body) != {'issuer','nonce','card','amount','asset'} or body['issuer'] != own
            or not isinstance(body['nonce'],str) or not re.fullmatch(r'[a-f0-9]{32}',body['nonce'])
            or not isinstance(body['amount'],str) or not re.fullmatch(r'[1-9][0-9]{0,15}',body['amount'])
            or not isinstance(body['asset'],dict) or set(body['asset']) != {'mint','unit'}
            or any(not isinstance(v,str) or len(v)>2048 for v in body['asset'].values())
            or card_issuer(body['card']) != own):
        raise ValueError('Invalid payment instruction')
    pinned_origin, pinned_key = pinned_issuer(body['card'])
    if pinned_origin != own or pinned_key != signer.npub:
        raise ValueError('Card issuer key changed')
    store = await run_in_threadpool(CardStore, request.app.state.wallets.store, own)
    authority = await run_in_threadpool(store.balance_authority, None, body['card'])
    def destination():
        # Snapshot public handle and wallet binding together; no custody key access.
        with closing(store.custody.connect()) as db:
            row=db.execute('SELECT p.handle FROM user_preferences p JOIN wallets w ON w.owner=p.owner WHERE p.owner=? AND w.wallet_id=? AND w.status=\'active\'',(authority['owner'],authority['wallet_id'])).fetchone()
        if not row or not row['handle']:
            raise ValueError('Card wallet needs a receipt address')
        record = store.custody.get(authority['owner'])
        if not record or record['status'] != 'active' or hashlib.sha256(record['material']['npub'].encode()).hexdigest() != authority['wallet_id']:
            raise ValueError('Wallet changed')
        expected = request.app.state.wallets.backend.public_identity(record['material'])['hex']
        handle, pubkey, _ = request.app.state.ecash.wallet_destination(row['handle'])
        if pubkey != expected:
            raise ValueError('Receipt address changed')
        return {'address':handle+'@'+urlsplit(own).hostname,'pubkey':pubkey}
    result = await run_in_threadpool(destination)
    await run_in_threadpool(store.balance_authority, None, body['card'])
    return {'event':signer.card_message({'request':digest(body),**result},'card-recipient')}


@router.post(PATH, include_in_schema=False)
async def recipient(request: Request):
    try:
        def limit():
            with closing(request.app.state.wallets.store.connect()) as db, db:
                POSStore._limit(db,'card-recipient:'+ (request.client.host if request.client else 'unknown'),120,3600)
        await run_in_threadpool(limit)
        raw=bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw)>8192: raise ValueError('Too large')
        envelope=json.loads(raw)
        if not isinstance(envelope,dict) or set(envelope) != {'origin','event'}:
            raise ValueError('Invalid request')
        result=await issue_destination(request,envelope)
        return JSONResponse(result,headers={'Cache-Control':'no-store'})
    except Exception:
        raise HTTPException(400,'Card payment request unavailable or not authorized.') from None


async def resolve_card(request, owner, encoded, amount, asset, fetch=public_json):
    try:
        issuer, pinned_key = pinned_issuer(encoded)
        own=canonical_origin(request.app.state.settings.origin)
        signer=identity(request)
        if not re.fullmatch(r'[1-9][0-9]{0,15}',amount):raise ValueError('Invalid amount')
        selected={'mint':'','unit':'sat'}
        if asset:
            row=next((r for r in await request.app.state.send.clear_assets(owner) if r['id']==asset),None)
            if row is None: raise ValueError('Invalid asset')
            selected={k:row[k] for k in ('mint','unit')}
        body={'issuer':issuer,'nonce':secrets.token_hex(16),'card':encoded,'amount':amount,'asset':selected}
        envelope={'origin':own,'event':signer.card_message(body,'pay-to-card')}
        if issuer==own:
            if signer.npub != pinned_key:
                raise ValueError('Card issuer key changed')
            reply=await issue_destination(request,envelope,fetch)
        else:
            info=await fetch(issuer+'/info')
            if info['service_identity']['npub'] != pinned_key:
                raise ValueError('Card issuer key changed')
            reply=await fetch(issuer+PATH,body=envelope)
        destination=verify_card_message(reply['event'],'card-recipient',pinned_key)
        if (set(destination) != {'request','address','pubkey'} or destination['request']!=digest(body)
                or not isinstance(destination['address'],str) or destination['address'].split('@')[-1]!=urlsplit(issuer).hostname
                or not isinstance(destination['pubkey'],str) or not re.fullmatch(r'[a-f0-9]{64}',destination['pubkey'])):
            raise ValueError('Invalid destination')
        return destination
    except PaymentInputError:
        raise
    except Exception:
        raise PaymentInputError('Could not verify this card with its issuing wallet instance. No payment was sent. Check the card and try again.') from None
