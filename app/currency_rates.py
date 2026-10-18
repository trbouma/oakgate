"""Shared last-known-good rates; display estimates only, never payment amounts."""
import asyncio
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import json
import logging
import os
import time

import httpx
from app.payment_config import secure_url

CURRENCY_METADATA = {
    "CAD": ("$", "Canadian dollar"),
    "USD": ("$", "United States dollar"),
    "EUR": ("€", "Euro"),
    "GBP": ("£", "British pound"),
    "JPY": ("¥", "Japanese yen"),
    "INR": ("₹", "Indian rupee"),
    "CNY": ("CN¥", "Chinese yuan (renminbi)"),
    "AUD": ("A$", "Australian dollar"),
    "CHF": ("Fr", "Swiss franc"),
    "SGD": ("S$", "Singapore dollar"),
    "HKD": ("HK$", "Hong Kong dollar"),
    "BRL": ("R$", "Brazilian real"),
}


class CurrencyRates:
    def __init__(self, store):
        self.store = store
        enabled = os.getenv('OAKGATE_CURRENCY_RATES_ENABLED', 'true').lower()
        if enabled not in {'true', 'false'}:
            raise ValueError('OAKGATE_CURRENCY_RATES_ENABLED must be true or false')
        self.enabled = enabled == 'true'
        self.source = secure_url(os.getenv('OAKGATE_CURRENCY_RATE_SOURCE_URL', 'https://blockchain.info/ticker'), 'https')
        self.default_currency = os.getenv('OAKGATE_DEFAULT_CURRENCY', 'USD').upper()
        if self.default_currency not in CURRENCY_METADATA:
            raise ValueError('Unsupported OAKGATE_DEFAULT_CURRENCY')
        self.interval = int(os.getenv('OAKGATE_CURRENCY_RATE_INTERVAL_SECONDS', '3600'))
        self.stale_seconds = int(os.getenv('OAKGATE_CURRENCY_RATE_STALE_SECONDS', '86400'))
        if self.interval < 60 or self.stale_seconds < 60:
            raise ValueError('Currency refresh/stale intervals must be at least 60 seconds')
        with closing(store.connect()) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS currency_rates (code TEXT PRIMARY KEY, symbol TEXT NOT NULL, description TEXT NOT NULL, fiat_per_btc TEXT, fetched_at REAL, source TEXT)')
            for code, (symbol, description) in CURRENCY_METADATA.items():
                db.execute('INSERT INTO currency_rates(code,symbol,description) VALUES(?,?,?) '
                           'ON CONFLICT(code) DO UPDATE SET symbol=excluded.symbol,description=excluded.description',
                           (code, symbol, description))

    async def refresh(self, client=None, now=None):
        if not self.enabled:
            return 0
        if client is None:
            async with httpx.AsyncClient(timeout=10, follow_redirects=False, trust_env=False) as owned:
                return await self.refresh(owned, now=now)
        async with client.stream('GET', self.source, timeout=10, follow_redirects=False) as response:
            response.raise_for_status()
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > 262144:
                    raise ValueError('Rate response is too large')
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise ValueError('Invalid rate response')
        valid = {}
        for code in CURRENCY_METADATA:
            item = payload.get(code)
            if not isinstance(item, dict):
                continue
            try:
                value = Decimal(str(item.get('15m')))
                # Bound malformed upstream values as well as rejecting NaN/infinity.
                if value.is_finite() and 0 < value < Decimal('1e18'):
                    valid[code] = str(value)
            except (InvalidOperation, ValueError):
                continue
        if not valid:
            raise ValueError('No valid rates received')
        observed = time.time() if now is None else now
        with closing(self.store.connect()) as db, db:
            for code, value in valid.items():
                db.execute('UPDATE currency_rates SET fiat_per_btc=?,fetched_at=?,source=? WHERE code=?',
                           (value, observed, self.source, code))
        return len(valid)

    def rows(self, now=None):
        now = time.time() if now is None else now
        with closing(self.store.connect()) as db:
            rows = db.execute('SELECT * FROM currency_rates ORDER BY code').fetchall()
        return [{**dict(row), 'stale': row['fetched_at'] is not None and now-row['fetched_at'] > self.stale_seconds,
                 'updated': datetime.fromtimestamp(row['fetched_at'], timezone.utc).strftime('%Y-%m-%d %H:%M UTC') if row['fetched_at'] is not None else None,
                 'formatted_rate': format(Decimal(row['fiat_per_btc']), ',.2f') if row['fiat_per_btc'] else None}
                for row in rows]

    def estimate(self, sats, currency, now=None):
        if not self.enabled or type(sats) is not int or sats < 0:
            return None
        row = next((row for row in self.rows(now) if row['code'] == currency), None)
        if not row or row['fiat_per_btc'] is None:
            return None
        amount = Decimal(sats) * Decimal(row['fiat_per_btc']) / Decimal(100_000_000)
        places = 0 if currency == 'JPY' else 2
        amount = amount.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
        return {**row, 'amount': format(amount, f',.{places}f')}

    async def run(self):
        while True:
            try:
                await self.refresh()
            except Exception as exc:
                logging.getLogger(__name__).warning('Rate refresh unavailable: %s', type(exc).__name__)
            await asyncio.sleep(self.interval)
