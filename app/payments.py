"""Lightning address receiving directly into each user's custodial Acorn."""
import asyncio
import json
import logging
import re
import time
from urllib.parse import urlsplit

from cryptography.fernet import InvalidToken
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from stroma import Keys

from app.payment_config import PaymentSettings
from app.payment_mint import CashuMint, MintCompatibilityError, proof_event
from app.payment_store import PaymentStore, PaymentBusy
from app.zaps import encode_lnurl, validate_zap, receipt, publish_event, public_relay

logger = logging.getLogger(__name__)
router = APIRouter()
MAX_COMMENT_CHARS = 255
HEADERS = {'Access-Control-Allow-Origin': '*', 'Cache-Control': 'no-store'}


class PaymentService:
    def __init__(self, wallets, origin, config=None, mint=None, publisher=None):
        self.wallets = wallets
        self.origin = origin.rstrip('/')
        self.config = config or PaymentSettings.from_env()
        self.store = PaymentStore(wallets.store)
        self.mint = mint or CashuMint(self.config.require_description_hash)
        self.publisher = publisher or publish_event
        self.relays = [public_relay(r) for r in self.config.relays]

    def address(self, handle):
        parsed = urlsplit(self.origin)
        if not self.config.enabled or parsed.scheme != 'https' or parsed.port is not None:
            return None
        return f'{handle.lower()}@{parsed.hostname}' if handle else None

    def discovery(self, handle):
        handle = handle.lower()
        if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{2,31}', handle) or not self.address(handle):
            raise ValueError('Lightning address not found')
        owner = self.wallets.store.address_owner(handle)
        wallet = self.wallets.store.get(owner) if owner else None
        if not wallet or wallet['status'] != 'active':
            raise ValueError('Lightning address not found')
        self.wallets.relay(wallet['material']['relay'])
        pubkey = Keys(priv_k=wallet['material']['nsec']).public_key_hex()
        address = self.address(handle)
        metadata = json.dumps([['text/plain', f'Payment to {address}'], ['text/identifier', address]], separators=(',', ':'))
        snapshot = {'owner': owner, 'handle': handle, 'metadata': metadata, 'pubkey': pubkey}
        token = self.wallets.store.cipher.encrypt(json.dumps(snapshot).encode()).decode()
        return {'tag': 'payRequest', 'callback': f'{self.origin}/lnurl/callback/{token}',
                'minSendable': self.config.min_sat * 1000, 'maxSendable': self.config.max_sat * 1000,
                'metadata': metadata, 'commentAllowed': MAX_COMMENT_CHARS, 'allowsNostr': True, 'nostrPubkey': pubkey}

    async def invoice(self, token, amount, nostr=None, comment=None):
        if comment is not None and len(comment) > MAX_COMMENT_CHARS:
            raise ValueError('Payment comment is too long')
        if not self.config.enabled:
            raise ValueError('Receiving payments is paused')
        if len(token) > 4096 or not re.fullmatch(r'[0-9]{1,12}', amount):
            raise ValueError('Invalid payment request')
        try:
            snapshot = json.loads(self.wallets.store.cipher.decrypt(token.encode(), ttl=900))
        except (InvalidToken, ValueError):
            raise ValueError('Payment link expired; resolve the Lightning address again') from None
        msat = int(amount)
        if msat % 1000 or not self.config.min_sat * 1000 <= msat <= self.config.max_sat * 1000:
            raise ValueError('Use a whole-satoshi amount within the advertised limits')
        wallet = self.wallets.store.get(snapshot['owner'])
        if not wallet or wallet['status'] != 'active':
            raise ValueError('Acorn unavailable')
        self.wallets.relay(wallet['material']['relay'])
        if Keys(priv_k=wallet['material']['nsec']).public_key_hex() != snapshot['pubkey']:
            raise ValueError('Acorn identity changed')
        zap, targets = None, self.relays.copy()
        if nostr is not None:
            zap, requested = validate_zap(nostr, msat, snapshot['pubkey'],
                                          encode_lnurl(f"{self.origin}/.well-known/lnurlp/{snapshot['handle']}"))
            targets = list(dict.fromkeys(targets + requested))
        item, created = self.store.reserve(snapshot['owner'], {
            'amount': msat // 1000, 'mint': self.config.mint, 'zap': nostr, 'comment': comment,
            'description': nostr if zap else snapshot['metadata'], 'relays': targets,
        }, zap['id'] if zap else None)
        if not created:
            if item.get('invoice') and item.get('expiry', 0) > time.time() and item['state'] == 'waiting' and not item.get('paid_at'):
                return item['invoice']
            raise ValueError('Zap already submitted or invoice unavailable; create a new zap request')
        try:
            async with asyncio.timeout(45):
                item.update(await self.mint.quote(item['mint'], item['amount'], item['description']))
                item['prepared'] = await self.mint.prepare(item)
                item['state'] = 'waiting'
                self.store.save(item)
        except BaseException:
            # No invoice has been returned to a payer yet. Never enqueue an
            # unverified or incompletely persisted quote for settlement.
            item['state'] = 'failed'
            self.store.save(item)
            raise
        return item['invoice']

    async def process(self, payment_id):
        try:
            token = self.store.claim(payment_id)
        except PaymentBusy:
            return
        item = None
        try:
            item = self.store.get(payment_id)
            if item['state'] not in ('waiting', 'credited'):
                return
            async with asyncio.timeout(60):
                await self.settle(item, token)
        except Exception as exc:
            # Never log exception text: mint errors may contain quote secrets,
            # invoices or bearer proofs. The opaque journal id supports diagnosis.
            logger.warning('Payment retry id=%s error_type=%s', payment_id, type(exc).__name__)
            if item:
                self.store.save(item, token, delay=30)
        finally:
            self.store.release(payment_id, token)

    async def settle(self, item, token):
        wallet_record = self.wallets.store.get(item['owner'])
        if not wallet_record or wallet_record['status'] != 'active':
            raise ValueError('Recipient unavailable')
        material = wallet_record['material']
        relay = self.wallets.relay(material['relay'])
        if item['state'] == 'waiting':
            if not item.get('paid_at'):
                state = await self.mint.state(item)
                if state.get('state') not in ('PAID', 'ISSUED') and state.get('paid') is not True:
                    # Keep old unpaid invoices recoverable, but stop hot polling.
                    delay = self.config.poll_seconds if item['expiry'] > time.time() else 3600
                    self.store.save(item, token, delay=delay)
                    return
                item['paid_at'] = int(time.time())
                self.store.save(item, token)
            if 'proofs' not in item:
                item['proofs'] = await self.mint.issue(item)
                self.store.save(item, token)
            if 'proof_event' not in item:
                wallet = self.wallets.backend.wallet(material)
                item['proof_event'] = proof_event(wallet, item['mint'], item['proofs'])
                # The exact signed event survives publication/acknowledgment loss.
                self.store.save(item, token)
            if not await self.publisher(relay, item['proof_event'], private=True):
                raise RuntimeError('Proof delivery not confirmed')
            item['state'] = 'credited'
            self.store.save(item, token)
        if item['zap']:
            if 'receipt' not in item:
                item['receipt'] = receipt(item['zap'], item['invoice'], material['nsec'], item['paid_at'])
                item['acknowledged'] = []
                self.store.save(item, token)
            # All configured/default relays plus safe client hints; retry failures
            # independently. Publication failure never remints or recredits funds.
            pending = [r for r in item['relays'] if r not in item['acknowledged']]
            for start in range(0, len(pending), 4):
                batch = pending[start:start+4]
                results = await asyncio.gather(*(self.publisher(r, item['receipt']) for r in batch), return_exceptions=True)
                item['acknowledged'].extend(r for r, ok in zip(batch, results) if ok is True)
                self.store.save(item, token)
            if len(item['acknowledged']) != len(item['relays']):
                self.store.save(item, token, delay=60)
                return
        item['state'] = 'complete'
        self.store.save(item, token)

    async def run(self):
        while True:
            try:
                due = self.store.due()
                await asyncio.gather(*(self.process(payment_id) for payment_id in due))
            except Exception as exc:
                logger.warning('Payment worker retry error_type=%s', type(exc).__name__)
            await asyncio.sleep(1)


def error(reason):
    return JSONResponse({'status': 'ERROR', 'reason': reason}, headers=HEADERS)


@router.get('/.well-known/lnurlp/{handle}', include_in_schema=False)
async def resolve(request: Request, handle: str):
    service = request.app.state.payments
    if service is None:
        return error('Receiving payments is not configured')
    try:
        return JSONResponse(service.discovery(handle), headers=HEADERS)
    except ValueError:
        return error('Lightning address not found or unavailable')
    except Exception:
        return error('Receiving payments is temporarily unavailable')


@router.get('/lnurl/callback/{token}', include_in_schema=False)
async def callback(request: Request, token: str, amount: str = '', nostr: str | None = None):
    service = request.app.state.payments
    if service is None:
        return error('Receiving payments is not configured')
    if len(request.scope.get('query_string', b'')) > 24576:
        return error('Payment request is too large')
    comment = request.query_params.get('comment')
    if comment is not None and len(comment) > MAX_COMMENT_CHARS:
        return error(f'Payment comments must be {MAX_COMMENT_CHARS} characters or fewer')
    if any(len(request.query_params.getlist(k)) != 1 for k in request.query_params):
        return error('Duplicate payment parameters')
    try:
        invoice = await service.invoice(token, amount, nostr, comment=comment)
        return JSONResponse({'pr': invoice, 'routes': []}, headers=HEADERS)
    except MintCompatibilityError as exc:
        return error(str(exc))
    except PaymentBusy:
        return error('Too many payment requests; please try again later')
    except (ValueError, InvalidToken):
        return error('Invalid or expired payment request; check the address, amount and zap')
    except Exception:
        return error('Could not create an invoice; please try again shortly')


@router.options('/.well-known/lnurlp/{handle}', include_in_schema=False)
@router.options('/lnurl/callback/{handle}', include_in_schema=False)
async def options(handle: str):
    return Response(headers={**HEADERS, 'Access-Control-Allow-Methods': 'GET, OPTIONS',
                             'Access-Control-Allow-Headers': 'Content-Type'})
