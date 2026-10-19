"""NIP-57 request validation. OakGate service identity signs receipts."""
import ipaddress
import json
import re
from urllib.parse import urlsplit

from bech32 import bech32_encode, convertbits
from stroma import Event

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


def validate_zap(raw, amount_msat, recipient, lnurl, *, provider=None):
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
    # The callback selects the credited wallet; p identifies the social target.
    if not re.fullmatch(r'[0-9a-fA-F]{64}', tag('p', True)[1]):
        raise ValueError('Invalid zap recipient public key')
    if tag('P') and tag('P')[1] != (provider or recipient):
        raise ValueError('Zap provider does not match this service')
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
