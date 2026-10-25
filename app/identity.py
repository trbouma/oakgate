"""Operator service identity and public-only social key validation. No custody keys."""
import asyncio
import json
import time
import os
import ipaddress
from contextlib import closing

import aiohttp
from stroma import Event, Keys, RelayClient, fips_ipv6_address
from aiohttp.resolver import DefaultResolver
from app.zaps import public_relay


class PublicResolver(DefaultResolver):
    async def resolve(self, host, port=0, family=0):
        addresses = await super().resolve(host, port, family)
        if not addresses or any(not ipaddress.ip_address(row['host']).is_global
                                or ipaddress.ip_address(row['host']).is_multicast for row in addresses):
            raise OSError('Relay must resolve to public addresses')
        return addresses


class ServiceIdentity:
    def __init__(self, store, secret=None):
        secret = os.getenv('OAKGATE_SERVICE_NSEC', '').strip() if secret is None else secret
        try:
            self._keys = Keys(priv_k=secret) if secret else None
        except Exception:
            raise ValueError('OAKGATE_SERVICE_NSEC is invalid') from None
        self.pubkey = self._keys.public_key_hex() if self._keys else None
        self.npub = self._keys.public_key_bech32() if self._keys else None
        self.fips_address = fips_ipv6_address(self.npub) if self.npub else None
        # Like Clear, bind the public identity to the database in one transaction.
        with closing(store.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT npub FROM service_identity WHERE id=1').fetchone()
            if row and row['npub'] != self.npub:
                raise RuntimeError('OAKGATE_SERVICE_NSEC is missing or does not match the identity bound to this database')
            if not row and self.npub:
                db.execute('INSERT INTO service_identity(id,npub) VALUES(1,?)', (self.npub,))

    def public_info(self, management='independent'):
        return {
            'npub': self.npub,
            'fips_ipv6_address': self.fips_address,
            'type': 'oakgate',
            'management': management,
            'state': 'uncommissioned' if self.npub else 'unconfigured',
            'descriptor_event_id': None,
            'operator': None,
        }

    def card_message(self, payload, purpose):
        if not self._keys:
            raise ValueError('Service identity is not configured')
        event = Event(kind=27235, pub_key=self.pubkey, created_at=int(time.time()),
                      tags=[['t', 'oakgate-card-v1'], ['purpose', purpose]],
                      content=json.dumps(payload, sort_keys=True, separators=(',', ':')))
        event.sign(self._keys)
        return event.data()

    def receipt(self, item):
        if not self._keys or item.get('service_pubkey') != self.pubkey:
            raise ValueError('Zap was not issued by this OakGate service identity')
        request = Event.load(item['zap'])
        if request.kind != 9734 or not request.is_valid():
            raise ValueError('Invalid zap request')
        tags = [t for t in request.tags if t[0] in ('p', 'e', 'a', 'k')]
        tags += [['P', request.pub_key], ['bolt11', item['invoice']], ['description', item['zap']]]
        event = Event(kind=9735, pub_key=self.pubkey, created_at=item['paid_at'], content='', tags=tags)
        event.sign(self._keys)
        return event.data()

    async def publish_receipt(self, item, relay):
        event = Event.load(item['receipt'])
        if (not event.is_valid() or event.kind != 9735 or event.pub_key != self.pubkey
                or item.get('service_pubkey') != self.pubkey
                or ['bolt11', item['invoice']] not in list(event.tags)
                or ['description', item['zap']] not in list(event.tags)):
            raise ValueError('Receipt does not match this service payment')
        public_relay(relay)
        async def no_redirect(session, context, params):
            raise ValueError('Relay redirects are not supported')
        trace = aiohttp.TraceConfig()
        trace.on_request_redirect.append(no_redirect)
        def session_factory(**kwargs):
            return aiohttp.ClientSession(connector=aiohttp.TCPConnector(resolver=PublicResolver()),
                                         trace_configs=[trace], trust_env=False, **kwargs)
        async with asyncio.timeout(8):
            result = await RelayClient(relay, timeout=8, session_factory=session_factory,
                                       max_msg_size=262144).publish(event)
        return result.accepted


def social_public_identity(value):
    """Validate a user-supplied public npub only; never accept or derive a secret."""
    value = value.strip()
    if value == value.upper():
        value = value.lower()
    if len(value) != 63 or not value.startswith('npub1'):
        raise ValueError('Enter a valid public npub, not a private key.')
    try:
        key = Keys(pub_k=value)
        return {'npub': key.public_key_bech32(), 'hex': key.public_key_hex()}
    except Exception:
        raise ValueError('Enter a valid public npub, not a private key.') from None


def verify_card_message(value, purpose, npub):
    """Public-only Stroma validation against an HTTPS-discovered instance identity."""
    event = Event.load(value)
    if (event.kind != 27235 or not event.is_valid()
            or event.pub_key != social_public_identity(npub)['hex']
            or abs(event.created_at - int(time.time())) > 90
            or list(event.tags) != [['t', 'oakgate-card-v1'], ['purpose', purpose]]):
        raise ValueError('Invalid card message')
    payload = json.loads(event.content)
    if not isinstance(payload, dict):
        raise ValueError('Invalid card message')
    return payload
