"""NIP-57 validation and bounded, public-only receipt delivery."""
import asyncio
import ipaddress
import json
import re
import secrets
from urllib.parse import urlsplit

import aiohttp
from bech32 import bech32_encode, convertbits
from stroma import Event, Keys

from app.clear_balances import PublicResolver
from app.payment_config import secure_url


def encode_lnurl(url):
    return bech32_encode('lnurl', convertbits(url.encode(), 8, 5, True)).upper()


def public_relay(value):
    value = secure_url(value, 'wss')
    host = urlsplit(value).hostname
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if '.' not in host or host.endswith(('.localhost', '.local')):
            raise ValueError('Relay must be public')
    else:
        if not address.is_global or address.is_multicast:
            raise ValueError('Relay must be public')
    return value


def validate_zap(raw, amount_msat, recipient, lnurl):
    if len(raw.encode()) > 16384:
        raise ValueError('Zap request is too large')
    payload = json.loads(raw)
    if not isinstance(payload, dict) or type(payload.get('created_at')) is not int:
        raise ValueError('Invalid zap event')
    tags = payload.get('tags')
    if (not isinstance(tags, list) or len(tags) > 64 or
            any(not isinstance(t, list) or not t or any(not isinstance(v, str) for v in t) for t in tags)):
        raise ValueError('Invalid zap tags')
    event = Event.load(payload)
    if event.kind != 9734 or not event.is_valid():
        raise ValueError('Invalid zap signature')
    def tag(name, required=False):
        values = [t for t in tags if t[0] == name]
        if len(values) > 1 or (required and not values) or (values and len(values[0]) < 2):
            raise ValueError('Invalid zap tag')
        return values[0] if values else None
    if tag('p', True)[1] != recipient:
        raise ValueError('Zap recipient does not match this Acorn')
    if tag('P') and tag('P')[1] != recipient:
        raise ValueError('Zap provider does not match this Acorn')
    if tag('amount') and tag('amount')[1] != str(amount_msat):
        raise ValueError('Zap amount does not match the invoice')
    if tag('lnurl') and tag('lnurl')[1].lower() != lnurl.lower():
        raise ValueError('Zap address does not match')
    if tag('e') and not re.fullmatch('[0-9a-f]{64}', tag('e')[1]):
        raise ValueError('Invalid event id')
    if tag('a') and not re.fullmatch(r'\d+:[0-9a-f]{64}:.*', tag('a')[1]):
        raise ValueError('Invalid event coordinate')
    tag('k')
    relays = []
    for value in tag('relays', True)[1:11]:
        try:
            relays.append(public_relay(value))
        except ValueError:
            continue
    return payload, list(dict.fromkeys(relays))


def receipt(raw, invoice, nsec, paid_at):
    request = json.loads(raw)
    keys = Keys(priv_k=nsec)
    tags = [t for t in request['tags'] if t[0] in ('p', 'e', 'a', 'k')]
    tags += [['P', request['pubkey']], ['bolt11', invoice], ['description', raw]]
    event = Event(kind=9735, pub_key=keys.public_key_hex(), created_at=paid_at, content='', tags=tags)
    event.sign(keys.private_key_hex())
    return event.data()


async def publish_event(relay, event, *, private=False):
    """Check the signed event is readable, or receive an OK for public receipts.

    Home relays are operator-allowlisted. Payer-provided public destinations also
    enforce public DNS at connection time and reject HTTP redirects.
    """
    if not private:
        public_relay(relay)
    async def no_redirect(session, context, params):
        raise ValueError('Relay redirects are not supported')
    trace = aiohttp.TraceConfig()
    trace.on_request_redirect.append(no_redirect)
    connector = aiohttp.TCPConnector(resolver=PublicResolver()) if not private else aiohttp.TCPConnector()
    async with aiohttp.ClientSession(connector=connector, trace_configs=[trace], trust_env=False,
                                     timeout=aiohttp.ClientTimeout(total=8)) as client:
        async with asyncio.timeout(8):
            async with client.ws_connect(relay, max_msg_size=262144) as socket:
                await socket.send_json(['EVENT', event])
                sub = secrets.token_hex(8)
                if private:
                    await socket.send_json(['REQ', sub, {'ids': [event['id']], 'limit': 1}])
                async for message in socket:
                    if message.type != aiohttp.WSMsgType.TEXT:
                        continue
                    data = json.loads(message.data)
                    if not isinstance(data, list) or not data:
                        continue
                    if data[0] == 'OK' and len(data) >= 3 and data[1] == event['id']:
                        if data[2] is True:
                            # Re-query after acknowledgment if the initial REQ
                            # raced the relay's write transaction.
                            if private:
                                await socket.send_json(['REQ', sub, {'ids': [event['id']], 'limit': 1}])
                            else:
                                return True
                    if (private and data[0] == 'EVENT' and len(data) == 3
                            and data[1] == sub and isinstance(data[2], dict)
                            and data[2].get('id') == event['id'] and Event.load(data[2]).is_valid()):
                        return True
    return False
