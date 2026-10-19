"""Reviewed, one-shot outgoing payments; all wallet operations use Acorn."""
import asyncio
import ipaddress
import json
import logging
import os
import re
import secrets
import socket
import time
from contextlib import closing
from urllib.parse import urlsplit

import bolt11
import httpx
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from acorn.safebox_discovery import resolve_safebox_address, SafeboxNotFound, SafeboxDiscoveryError, CASH, CLEAR

from app.auth import current_session, error_page
from app.custody import Busy, identity_key
from app.wallet_routes import checked_form
from app.clear_balances import payment_assets
from app.clear_routing import ClearRouteError, clear_availability

router = APIRouter()
logger = logging.getLogger(__name__)


async def public_json(url, params=None):
    """Pin a public DNS result to the TLS connection; never follow redirects."""
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.port not in (None, 443) or parsed.fragment):
        raise ValueError('Unsupported payment endpoint')
    hostname = parsed.hostname.encode('idna').decode()
    async with asyncio.timeout(12):
        addresses = await asyncio.get_running_loop().getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
        ips = list(dict.fromkeys(row[4][0] for row in addresses))
        if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
            raise ValueError('Payment endpoint must be public')
        target = httpx.URL(url).copy_with(host=ips[0])
        async with httpx.AsyncClient(timeout=10, follow_redirects=False, trust_env=False) as client:
            async with client.stream('GET', target, params=params, headers={'Host': hostname},
                                     extensions={'sni_hostname': hostname}) as response:
                response.raise_for_status()
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > 65536:
                        raise ValueError('Payment response too large')
                data = json.loads(body)
                if not isinstance(data, dict):
                    raise ValueError('Invalid payment response')
                return data


class PaymentInputError(ValueError):
    """Safe, application-authored payment guidance for display."""


class SendService:
    def __init__(self, wallets, origin, receiver, fetch=public_json, discover=resolve_safebox_address):
        self.wallets, self.origin, self.receiver, self.fetch = wallets, origin, receiver, fetch
        self.discover = discover
        # Legacy-domain opt-in applies only after safebox.json returns 404.
        # Never list domains whose social and wallet identities have split.
        self.legacy_domains = {v.strip().lower() for v in os.getenv('OAKGATE_SAFEBOX_DOMAINS', 'safebox.dev').split(',') if v.strip()}
        with closing(wallets.store.connect()) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS outgoing_payments (id TEXT PRIMARY KEY, owner TEXT NOT NULL, state TEXT NOT NULL, encrypted BLOB NOT NULL, created REAL NOT NULL)')

    async def clear_assets(self, owner):
        record = self.wallets.store.get(owner)
        if not record or record['status'] != 'active':
            return []
        return payment_assets(await self.wallets.clear_balances(record['material']))

    async def prepare(self, owner, address, amount, comment, asset=''):
        if not re.fullmatch(r'[1-9][0-9]{0,15}', amount):
            raise PaymentInputError('Enter a positive whole-number amount.')
        selected = None
        if asset:
            if not getattr(self.wallets.backend, 'clear_sending_available', False):
                raise PaymentInputError('Clear sending is unavailable.')
            selected = next((row for row in await self.clear_assets(owner) if row['id'] == asset), None)
            if selected is None or int(amount) > selected['amount']:
                raise PaymentInputError('The selected Clear balance is unavailable or insufficient.')
        elif int(amount) > 1000000:
            raise PaymentInputError('Enter an amount between 1 and 1,000,000 sats.')
        address = address.strip().lower()
        if len(address) > 254 or not re.fullmatch(r'[a-z0-9_.+-]+@[a-z0-9.-]+', address):
            raise PaymentInputError('Enter a Lightning address such as name@example.com. Website addresses are not supported here.')
        if len(comment) > 255:
            raise PaymentInputError('Keep the comment to 255 characters or fewer.')
        name, domain = address.split('@')
        payment = {'id': secrets.token_urlsafe(24), 'owner': owner, 'address': address,
                   'amount': int(amount), 'comment': comment, 'expires': time.time()+300}
        local = domain == urlsplit(self.origin).hostname
        if selected and not local and clear_availability(selected['mint']) == 'instance':
            raise ClearRouteError('This Clear balance is available only within this OakGate instance and cannot be sent outside it. No value was sent.')
        payload = None
        if local and self.receiver and self.receiver.available:
            try:
                payload = self.local_directory(name)
                payment['discovery_source'] = 'local-wallet'
            except ValueError:
                pass
        elif not local:
            try:
                destination = await self.discover(address)
                capability = CLEAR if selected else CASH
                unit = selected['unit'] if selected else 'sat'
                if destination.supports(capability, unit):
                    descriptor = destination.capabilities[capability]
                    payload = {'names': {name: destination.pubkey},
                               'relays': {destination.pubkey: list(destination.relays)},
                               ('clear' if selected else 'safebox'): {
                                   name: {**descriptor, 'protocols': [capability]}}}
                payment['discovery_source'] = destination.source
            except SafeboxNotFound:
                if domain in self.legacy_domains:
                    try:
                        payload = await self.fetch(f'https://{domain}/.well-known/nostr.json', {'name': name})
                        if (not isinstance(payload, dict) or not isinstance(payload.get('names'), dict)
                                or not isinstance(payload.get('relays', {}), dict)):
                            raise ValueError('Invalid legacy wallet directory')
                        legacy_key = payload['names'].get(name)
                        if legacy_key is not None and (
                                not isinstance(legacy_key, str) or not re.fullmatch(r'[0-9a-fA-F]{64}', legacy_key)):
                            raise ValueError('Invalid legacy wallet key')
                        if legacy_key and not isinstance(payload.get('relays', {}).get(legacy_key, []), list):
                            raise ValueError('Invalid legacy relay hints')
                        payment['discovery_source'] = 'legacy-nip05'
                    except httpx.HTTPStatusError as exc:
                        if exc.response.status_code != 404:
                            raise PaymentInputError('Legacy wallet discovery is unavailable. No payment was sent.') from None
                    except (ValueError, httpx.HTTPError, OSError, TimeoutError):
                        raise PaymentInputError('Legacy wallet discovery is unavailable. No payment was sent.') from None
            except SafeboxDiscoveryError:
                raise PaymentInputError('Wallet discovery is unavailable or invalid. No payment was sent. Try again later.') from None
        if selected:
            payment.update(self.clear_destination(payload, name, selected))
            self.check_clear_route(payment)
        if payload and not selected:
            names = payload.get('names', {})
            pubkey = names.get(name) if isinstance(names, dict) else None
            descriptors = payload.get('safebox', {})
            descriptor = descriptors.get(name, {}) if isinstance(descriptors, dict) else {}
            advertised = (isinstance(descriptor, dict) and isinstance(descriptor.get('protocols'), list)
                          and 'acorn-ecash-transfer' in descriptor['protocols'])
            relay_map = payload.get('relays', {})
            hints = relay_map.get(pubkey, []) if isinstance(relay_map, dict) and isinstance(pubkey, str) else []
            relay = next((r for r in hints if isinstance(r, str) and r in self.wallets.allowed_relays), None) if isinstance(hints, list) else None
            if (isinstance(pubkey, str) and re.fullmatch(r'[0-9a-fA-F]{64}', pubkey)
                    and relay and (advertised or domain in self.legacy_domains)
                    and getattr(self.wallets.backend, 'direct_sending_available', False)):
                payment.update(route='ecash', pubkey=pubkey.lower(), relay=relay)
        if payment.get('route') not in {'ecash', 'clear'}:
            metadata = await self.fetch(f'https://{domain}/.well-known/lnurlp/{name}')
            msat = payment['amount'] * 1000
            if (metadata.get('tag') != 'payRequest' or not isinstance(metadata.get('metadata'), str)
                    or not int(metadata.get('minSendable', 0)) <= msat <= int(metadata.get('maxSendable', 0))):
                raise PaymentInputError('The recipient cannot accept this amount.')
            comment_limit = int(metadata.get('commentAllowed') or 0)
            provider_comment = comment if comment_limit > 0 else ''
            if provider_comment and comment_limit < len(provider_comment):
                raise PaymentInputError('This recipient does not support a comment of that length.')
            callback = metadata.get('callback')
            if not isinstance(callback, str):
                raise PaymentInputError('Recipient did not provide a payment endpoint.')
            # public_json validates and pins the callback independently, even
            # when the provider uses a different public hostname.
            params = dict(httpx.URL(callback).params)
            params['amount'] = str(msat)
            params.pop('comment', None)
            if provider_comment:
                params['comment'] = provider_comment
            response = await self.fetch(callback, params)
            invoice = response.get('pr', '')
            if not isinstance(invoice, str) or len(invoice) > 10000:
                raise PaymentInputError('Invalid invoice')
            decoded = bolt11.decode(invoice)
            if decoded.currency != 'bc' or decoded.amount_msat != msat or decoded.date + decoded.expiry <= time.time():
                raise PaymentInputError('Invoice network, amount or expiry does not match the request.')
            payment.update(route='lightning', invoice=invoice,
                           expires=min(payment['expires'], decoded.date + decoded.expiry))
        with closing(self.wallets.store.connect()) as db, db:
            # An unresolved attempt must be investigated before another payment
            # is prepared; an old confirmation never silently becomes reusable.
            if db.execute("SELECT 1 FROM outgoing_payments WHERE owner=? AND state IN ('sending','unknown')", (owner,)).fetchone():
                raise PaymentInputError('A previous payment needs review. Check Acorn transaction history before sending again.')
            db.execute('INSERT INTO outgoing_payments VALUES(?,?,?,?,?)',
                       (payment['id'], owner, 'prepared', self.wallets.store.cipher.encrypt(json.dumps(payment).encode()), time.time()))
        return payment

    def local_directory(self, name):
        name, pubkey, relay = self.receiver.wallet_destination(name)
        payload = {'names': {name: pubkey}, 'relays': {pubkey: [relay]}}
        for enabled, field, protocol, kind in (
            (self.receiver.cash_available, 'safebox', CASH, 7378),
            (self.receiver.clear_available, 'clear', CLEAR, 7379),
        ):
            if enabled:
                payload[field] = {name: {'protocols': [protocol], 'transports': ['nip59'], 'kinds': [kind]}}
        return payload

    def clear_destination(self, payload, name, asset):
        if not isinstance(payload, dict):
            raise ValueError('Recipient does not advertise Clear support.')
        names, descriptors, relay_map = (payload.get(k, {}) for k in ('names', 'clear', 'relays'))
        if not all(isinstance(v, dict) for v in (names, descriptors, relay_map)):
            raise ValueError('Invalid Clear recipient')
        pubkey, descriptor = names.get(name), descriptors.get(name)
        if not isinstance(pubkey, str) or not re.fullmatch(r'[0-9a-fA-F]{64}', pubkey) or not isinstance(descriptor, dict):
            raise ValueError('Invalid Clear recipient')
        for field, value in (('protocols', 'clear-token-transfer'), ('transports', 'nip59'), ('kinds', 7379)):
            if not isinstance(descriptor.get(field), list) or value not in descriptor[field]:
                raise ValueError('Incompatible Clear recipient')
        units = descriptor.get('units', [])
        if not isinstance(units, list) or (units and asset['unit'] not in units):
            raise ValueError('Recipient does not support this Clear unit')
        hints = relay_map.get(pubkey, [])
        relay = next((v for v in hints if isinstance(v, str) and v in self.wallets.allowed_relays), None) if isinstance(hints, list) else None
        if not relay:
            raise ValueError('No approved relay for this Clear recipient')
        return {'route': 'clear', 'pubkey': pubkey.lower(), 'relay': relay,
                'asset': asset['id'], 'mint': asset['mint'], 'unit': asset['unit'],
                'display_name': asset['display_name'], 'display_unit': asset['display_unit']}

    def check_clear_route(self, payment):
        if clear_availability(payment['mint']) != 'instance':
            return
        name, domain = payment['address'].split('@')
        if domain != urlsplit(self.origin).hostname:
            raise ClearRouteError('This Clear balance is available only within this OakGate instance and cannot be sent outside it. No value was sent.')
        # An address on our domain is insufficient: it must still resolve to
        # the active local Acorn shown at review. Never silently retarget it.
        try:
            if not self.receiver or not self.receiver.clear_available:
                raise ValueError('Receiving unavailable')
            destination = self.clear_destination(self.local_directory(name), name, {**payment, 'id': payment['asset']})
            if destination['pubkey'] != payment['pubkey'] or destination['relay'] != payment['relay']:
                raise ValueError('Recipient changed')
        except ValueError:
            raise ClearRouteError('The local Clear recipient is no longer available as reviewed. No value was sent. Please start again.') from None

    def get(self, owner, payment_id):
        with closing(self.wallets.store.connect()) as db:
            row = db.execute('SELECT * FROM outgoing_payments WHERE id=? AND owner=?', (payment_id, owner)).fetchone()
        if not row:
            raise ValueError('Payment not found')
        payment = json.loads(self.wallets.store.cipher.decrypt(row['encrypted']))
        if payment['owner'] != owner or payment['id'] != payment_id:
            raise ValueError('Payment identity mismatch')
        return {**payment, 'state': row['state']}

    async def send(self, owner, payment_id):
        self.get(owner, payment_id)  # Authorize before acquiring a wallet lease.
        lease = self.wallets.store.acquire(owner)
        claimed = False
        try:
            payment = self.get(owner, payment_id)
            if payment['state'] != 'prepared':
                return payment
            if payment['expires'] <= time.time():
                raise ValueError('Payment confirmation expired. Start again.')
            record = self.wallets.store.get(owner)
            if not record or record['status'] != 'active':
                raise ValueError('Connect an Acorn first.')
            self.wallets.relay(record['material']['relay'])
            if payment['route'] == 'clear':
                self.check_clear_route(payment)
            with closing(self.wallets.store.connect()) as db, db:
                db.execute('BEGIN IMMEDIATE')
                if db.execute("SELECT 1 FROM outgoing_payments WHERE owner=? AND state IN ('sending','unknown')", (owner,)).fetchone():
                    raise ValueError('A previous payment needs review before another can be sent.')
                changed = db.execute("UPDATE outgoing_payments SET state='sending' WHERE id=? AND owner=? AND state='prepared'", (payment_id, owner)).rowcount
            if not changed:
                return self.get(owner, payment_id)
            claimed = True
            async with asyncio.timeout(60):
                await self.wallets.backend.send_payment(record['material'], payment)
            state = 'sent'
            # A local recipient need not wait for its next regular inbox poll.
            if self.receiver and payment['route'] in {'clear', 'ecash'} and payment['address'].split('@')[1] == urlsplit(self.origin).hostname:
                try:
                    self.receiver.wake(payment['address'].split('@')[0])
                except Exception:
                    logger.warning('Recipient inbox wake deferred to regular polling')
        except BaseException as exc:
            if not claimed:
                raise
            state = 'unknown'
            logger.warning('Outgoing payment needs review error_type=%s', type(exc).__name__)
            if isinstance(exc, asyncio.CancelledError):
                raise
        finally:
            if claimed:
                with closing(self.wallets.store.connect()) as db, db:
                    db.execute("UPDATE outgoing_payments SET state=? WHERE id=? AND owner=?", (locals().get('state', 'unknown'), payment_id, owner))
            self.wallets.store.release(owner, lease)
        return self.get(owner, payment_id)


def render(request, session, payment=None, message=None, status=200, assets=None, selected_asset="", values=None):
    # Pass only display fields, never invoices or encrypted journal contents.
    display = {k: payment[k] for k in ('id', 'address', 'amount', 'route', 'state', 'mint', 'unit', 'display_name', 'display_unit') if k in payment} if payment else None
    return request.app.state.templates.TemplateResponse(request=request, name='send.html',
        context={**session, 'active_page': 'balances', 'payment': display, 'message': message, 'assets': assets or [], 'selected_asset': selected_asset, 'values': values or {}}, status_code=status)


@router.get('/account/send', include_in_schema=False)
async def page(request: Request, payment: str = '', asset: str = ''):
    session = await current_session(request)
    if not session:
        return RedirectResponse('/auth/login', 303)
    service = request.app.state.send
    if not service:
        return error_page(request, 'Payments are not configured.', 503)
    try:
        item = service.get(identity_key(session['user']), payment) if payment else None
        assets = await service.clear_assets(identity_key(session['user'])) if not item else []
        if asset and not item and not any(row['id'] == asset for row in assets):
            return error_page(request, 'This Clear balance is no longer available. Return to Balances and choose an asset again.', 409)
        return render(request, session, item, assets=assets, selected_asset=asset)
    except ValueError:
        return error_page(request, 'Payment not found.', 404)
    except Exception:
        if asset:
            return error_page(request, 'Clear balances are unavailable. Return to Balances and try again.', 503)
        return render(request, session, message='Clear balances are unavailable. Refresh to try again.')


@router.post('/account/send', include_in_schema=False)
async def prepare(request: Request):
    session = await current_session(request)
    if not session:
        return RedirectResponse('/auth/login', 303)
    form = await checked_form(request, session)
    service = request.app.state.send
    if not service:
        return error_page(request, 'Payments are not configured.', 503)
    owner = identity_key(session['user'])
    record = service.wallets.store.get(owner)
    if not record or record['status'] != 'active':
        return render(request, session, message='Connect an Acorn first.', status=400)
    try:
        async with asyncio.timeout(35):
            payment = await service.prepare(owner, str(form.get('address', '')), str(form.get('amount', '')), str(form.get('comment', '')), asset=str(form.get('asset', '')))
        return RedirectResponse('/account/send?payment='+payment['id'], 303)
    except Exception as exc:
        # Preparation has not submitted a payment. Keep the authenticated shell
        # and selected asset; never expose provider responses or decoder errors.
        if isinstance(exc, (PaymentInputError, ClearRouteError)):
            message = str(exc)
            status = 422 if isinstance(exc, ClearRouteError) else 400
        else:
            logger.warning('Payment preparation failed error_type=%s', type(exc).__name__)
            message = 'Could not prepare this payment. No payment was sent. Check the Lightning address and amount, or try again shortly.'
            status = 400
        asset = str(form.get('asset', ''))
        try:
            async with asyncio.timeout(5):
                assets = await service.clear_assets(owner)
        except Exception:
            assets = []
        if asset and not any(row['id'] == asset for row in assets):
            assets.append({'id': asset, 'display_name': 'Selected Clear balance unavailable',
                           'amount': 0, 'display_unit': '', 'mint': ''})
        return render(request, session, message=message, status=status,
                      assets=assets, selected_asset=asset,
                      values={k: str(form.get(k, '')) for k in ('address', 'amount', 'comment')})


@router.post('/account/send/confirm', include_in_schema=False)
async def confirm(request: Request):
    session = await current_session(request)
    if not session:
        return RedirectResponse('/auth/login', 303)
    form = await checked_form(request, session)
    service = request.app.state.send
    if not service:
        return error_page(request, 'Payments are not configured.', 503)
    try:
        payment = await service.send(identity_key(session['user']), str(form.get('payment', '')))
        return RedirectResponse('/account/send?payment='+payment['id'], 303)
    except ClearRouteError as exc:
        return error_page(request, str(exc), 422)
    except Busy:
        return render(request, session, message='Your Acorn is busy. Return to this confirmation shortly.', status=409)
    except ValueError:
        return render(request, session, message='This confirmation is unavailable or expired. Check your transactions before starting again.', status=400)
