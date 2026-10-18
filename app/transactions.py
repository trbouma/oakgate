"""Read-only cash history presentation; never return secret journal fields."""
from datetime import datetime, timezone


def transaction_cards(history):
    cards = []
    for row in history:
        if not isinstance(row, dict):
            continue
        created = row.get('create_time')
        try:
            date = (datetime.fromtimestamp(float(created), timezone.utc)
                    if isinstance(created, (int, float)) else datetime.fromisoformat(str(created)))
            # Acorn formats history timestamps in the server's local timezone.
            date = date.astimezone(timezone.utc)
            timestamp, label, iso = date.timestamp(), date.strftime('%d %b %Y · %H:%M UTC'), date.isoformat()
        except (ValueError, TypeError, OverflowError, OSError):
            timestamp, label, iso = 0, 'Unknown date', ''
        def number(key, default=None):
            try:
                value = row.get(key)
                return int(value) if value is not None else default
            except (ValueError, TypeError, OverflowError):
                return default
        kind = str(row.get('tx_type', '')).upper()
        direction, sign, style = {'C': ('Received', '+', 'credit'), 'D': ('Sent', '−', 'debit'),
                                   'X': ('Failed', '', 'advisory')}.get(kind, ('Transaction', '', 'advisory'))
        amount, fees = number('amount'), number('fees', 0)
        if amount is not None and kind == 'D':
            amount += fees
        cards.append({'timestamp': timestamp, 'created': label, 'datetime': iso,
                      'direction': direction, 'sign': sign, 'style': style,
                      'amount': amount, 'fees': fees, 'balance': number('current_balance'),
                      'comment': str(row.get('comment') or '')})
    return sorted(cards, key=lambda card: card['timestamp'], reverse=True)[:10]
