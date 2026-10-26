"""Best-effort access notices through Acorn; never send the emergency contents."""
import asyncio
import hashlib
import re
import time
from contextlib import closing
from datetime import datetime, timezone
from urllib.parse import urlsplit

from app.database import INTEGRITY_ERRORS
from app.messages import available, resolver
from app.pos_api import invoke


def contact_address(text):
    """One explicit contact directive in text or a JSON string; ambiguous is skipped."""
    from acorn.safebox_discovery import normalize_safebox_address
    values = re.findall(r'(?:^|[\s"\'])contact:([^\s"\'<>]+)', text)
    if len(values) != 1 or len(values[0]) > 254:
        return None
    try:
        return normalize_safebox_address(values[0])
    except ValueError:
        return None


def claim(store, ident):
    # Use the existing durable one-use message journal, not a volatile Redis lock.
    digest = hashlib.sha256(('pos-emergency:' + ident).encode()).hexdigest()
    with closing(store.connect()) as db, db:
        try:
            db.execute('INSERT INTO wallet_message_submissions VALUES (?,?)', (digest, time.time()))
        except INTEGRITY_ERRORS:
            return False
    return True


async def notify_contact(request, ident, source, text):
    address = contact_address(text)
    if not address:
        return 'No single valid contact: address was found; no notification sent.'
    service = request.app.state.wallets
    lease = None
    try:
        if not available(service):
            raise ValueError('Messaging unavailable')
        if not await invoke(claim, service.store, ident):
            return 'Contact notification already attempted; delivery is not confirmed here.'
        async with asyncio.timeout(6):
            destination = await resolver(request)(address)
        lease = await invoke(service.store.acquire, source['owner'])
        record = await invoke(service.store.get, source['owner'])
        if not record or record['status'] != 'active' or record['material']['npub'] != source['npub']:
            raise ValueError('Wallet unavailable')
        handle = await invoke(service.store.preference, source['owner'])
        sender = f'{handle}@{urlsplit(request.app.state.settings.origin).hostname}' if handle else None
        when = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
        message = (f'My emergency record was accessed through an OakGate POS terminal at {when}. '
                   'This is an automated access notice, not confirmation of an emergency. '
                   f'Reference: {ident[:12]}')
        service.relay(record['material']['relay'])
        async with asyncio.timeout(15):
            await service.backend.send_wallet_message(record['material'], destination, message, sender)
        return 'Contact notification published to the wallet relay; reading is not confirmed.'
    except Exception:
        # A timeout may have published. Never automatically create another message.
        return 'Contact notification could not be confirmed. Do not rely on it for emergency assistance.'
    finally:
        if lease:
            try:
                await invoke(service.store.release, source['owner'], lease)
            except Exception:
                pass  # The bounded custody lease expires; do not hide the emergency record.
