"""Clear display labels from mint keyset metadata; never change asset identity."""
import asyncio
import hashlib
import json
import ipaddress
import time
from urllib.parse import urlsplit

import aiohttp
from aiohttp.resolver import DefaultResolver


class PublicResolver(DefaultResolver):
    async def resolve(self, host, port=0, family=0):
        addresses = await super().resolve(host, port, family)
        if not addresses or any((not ipaddress.ip_address(row['host']).is_global or ipaddress.ip_address(row['host']).is_multicast) for row in addresses):
            raise OSError('Metadata endpoint must be public')
        return addresses


def metadata_url(mint):
    parsed = urlsplit(mint)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.query or parsed.fragment
            or parsed.port not in (None, 443)):
        raise ValueError('Invalid metadata endpoint')
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        address = None
    if address is not None and (not address.is_global or address.is_multicast):
        raise ValueError('Metadata endpoint must be public')
    return mint.rstrip('/') + '/v1/keysets'


async def fetch_keysets(mint):
    url = metadata_url(mint)
    # Validate resolved addresses at connection time, not in a separate DNS check.
    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(resolver=PublicResolver()),
        timeout=aiohttp.ClientTimeout(total=3), trust_env=False,
    ) as client:
        async with client.get(url, allow_redirects=False) as response:
            if response.status != 200:
                raise ValueError('Metadata unavailable')
            data = bytearray()
            async for chunk in response.content.iter_chunked(8192):
                data.extend(chunk)
                if len(data) > 65536:
                    raise ValueError('Metadata too large')
            import json
            payload = json.loads(data)
    if isinstance(payload, dict):
        payload = payload.get('keysets', [payload] if payload.get('id') else [])
    return [row for row in payload if isinstance(row, dict)] if isinstance(payload, list) else []


def balance_rows(balances):
    if not isinstance(balances, list):
        raise ValueError('Invalid Clear balances')
    rows = []
    for balance in balances:
        mint, unit = balance['mint'].rstrip('/'), balance['unit']
        if not isinstance(unit, str) or not unit:
            raise ValueError('Invalid Clear unit')
        keysets = balance.get('keysets') or [{'keyset': '', 'amount': balance['amount']}]
        for keyset in keysets:
            amount = keyset['amount']
            if type(amount) is not int or amount < 0:
                raise ValueError('Invalid Clear amount')
            rows.append({'mint': mint, 'unit': unit, 'keyset_id': str(keyset.get('keyset') or keyset.get('keyset_id') or ''),
                         'amount': amount, 'display_name': unit, 'display_unit': unit})
    return sorted(rows, key=lambda row: (row['mint'], row['unit'], row['keyset_id']))


class ClearLabels:
    def __init__(self, fetcher=fetch_keysets):
        self.fetcher = fetcher
        self.cache = {}

    async def keysets(self, mint):
        cached = self.cache.get(mint)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        try:
            rows = await asyncio.wait_for(self.fetcher(mint), timeout=4)
            ttl = 300
        except Exception:
            # Keep known labels through a transient metadata outage.
            rows, ttl = (cached[1] if cached else []), 30
        if mint not in self.cache and len(self.cache) >= 128:
            self.cache.pop(next(iter(self.cache)))
        self.cache[mint] = (time.monotonic() + ttl, rows)
        return rows

    async def resolve(self, balances):
        rows = balance_rows(balances)
        # Bound fanout for wallets containing many different mints. Unresolved
        # assets still display their full underlying units and amounts.
        mints = sorted({row['mint'] for row in rows})[:16]
        metadata = dict(zip(mints, await asyncio.gather(*(self.keysets(m) for m in mints))))
        for row in rows:
            candidates = [k for k in metadata.get(row['mint'], [])
                          if k.get('unit') == row['unit'] and k.get('id')
                          and (not row['keyset_id'] or k['id'] == row['keyset_id'])]
            if not candidates:
                continue
            selected = next((k for k in candidates if k.get('active', True)), candidates[0])
            for field, value, limit in (
                ('display_name', selected.get('friendly_alias') or selected.get('friendly_name'), 120),
                ('display_unit', selected.get('friendly_unit_alias'), 40),
            ):
                if isinstance(value, str) and 0 < len(value.strip()) <= limit:
                    row[field] = value.strip()
        return rows


def asset_id(mint, unit):
    return hashlib.sha256(json.dumps([mint.rstrip('/'), unit], separators=(',', ':')).encode()).hexdigest()


def payment_assets(rows):
    """Aggregate keysets by exact issuer/unit; friendly labels never identify value."""
    grouped = {}
    for row in rows:
        key = asset_id(row['mint'], row['unit'])
        if key not in grouped:
            grouped[key] = {**row, 'id': key, 'amount': 0}
        asset = grouped[key]
        asset['amount'] += row['amount']
        if asset['display_name'] != row['display_name']:
            asset['display_name'] = row['unit']
        if asset['display_unit'] != row['display_unit']:
            asset['display_unit'] = row['unit']
    return [row for row in grouped.values() if row['amount'] > 0]
