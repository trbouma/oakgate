"""Validate receive amounts and convert current fiat quotes to whole sats."""
import re
from decimal import Decimal, ROUND_HALF_UP

from app.localization import N_

MAX_AMOUNT = 9_999_999_999_999


def receive_amount(amount, currency, rows=(), quoted_rate=''):
    if currency == 'SATS':
        if not re.fullmatch(r'[1-9][0-9]{0,12}', amount):
            raise ValueError(N_('Enter a positive whole-number amount.'))
        return int(amount)
    if not re.fullmatch(r'(?:0|[1-9][0-9]{0,12})(?:\.[0-9]{1,2})?', amount) or Decimal(amount) <= 0:
        raise ValueError(N_('Enter a positive amount with up to two decimal places.'))
    row = next((r for r in rows if r['code'] == currency), None)
    if not row or not row['fiat_per_btc'] or row['stale']:
        raise ValueError(N_('Currency rate unavailable. Choose SATS or try again later.'))
    if quoted_rate != row['fiat_per_btc']:
        raise ValueError(N_('The currency rate changed. Review the sats amount and try again.'))
    sats = int((Decimal(amount) * 100_000_000 / Decimal(quoted_rate)).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    if not 1 <= sats <= MAX_AMOUNT:
        raise ValueError(N_('The converted amount must be at least 1 sat and within the supported limit.'))
    return sats
