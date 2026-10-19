"""NIP-05 discovery and session-independent Acorn inbox processing."""
import asyncio
import logging
import os
import re
import time
from contextlib import closing

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.custody import Busy

logger = logging.getLogger(__name__)
router = APIRouter()
HEADERS = {'Access-Control-Allow-Origin': '*', 'Cache-Control': 'no-store'}


class EcashReceiver:
    def __init__(self, wallets):
        self.wallets = wallets
        value = os.getenv('OAKGATE_ECASH_RECEIVE_ENABLED', 'true').lower().strip()
        if value not in {'true', 'false'}:
            raise ValueError('OAKGATE_ECASH_RECEIVE_ENABLED must be true or false')
        self.enabled = value == 'true'
        clear = os.getenv('OAKGATE_CLEAR_RECEIVE_ENABLED', 'true').strip().lower()
        if clear not in {'true', 'false'}:
            raise ValueError('OAKGATE_CLEAR_RECEIVE_ENABLED must be true or false')
        self.clear_enabled = clear == 'true'
        self.interval = int(os.getenv('OAKGATE_ECASH_POLL_SECONDS', '30'))
        if not 10 <= self.interval <= 3600:
            raise ValueError('Ecash polling interval must be 10–3600 seconds')
        with closing(wallets.store.connect()) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS ecash_inboxes (owner TEXT PRIMARY KEY, next_poll REAL NOT NULL DEFAULT 0)')

    @property
    def cash_available(self):
        return self.enabled and bool(getattr(self.wallets.backend, 'ecash_receiving_available', False))

    @property
    def clear_available(self):
        return self.enabled and self.clear_enabled and bool(getattr(self.wallets.backend, 'clear_receiving_available', False))

    @property
    def available(self):
        return self.cash_available or self.clear_available

    def discovery(self, name):
        name = name.lower()
        if not self.available or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{2,31}', name):
            raise ValueError('Address unavailable')
        owner = self.wallets.store.address_owner(name)
        record = self.wallets.store.get(owner) if owner else None
        if not record or record['status'] != 'active':
            raise ValueError('Address unavailable')
        relay = self.wallets.relay(record['material']['relay'])
        pubkey = self.wallets.backend.public_identity(record['material'])['hex']
        payload = {'names': {name: pubkey}, 'relays': {pubkey: [relay]}}
        if self.cash_available:
            payload['safebox'] = {name: {'protocols': ['acorn-ecash-transfer'],
                'transports': ['nip59'], 'kinds': [7378], 'units': ['sat']}}
        if self.clear_available:
            # No issuer/unit allowlist: successful Acorn redemption is the policy.
            payload['clear'] = {name: {'protocols': ['clear-token-transfer'],
                'transports': ['nip59'], 'kinds': [7379]}}
        return payload

    def wake(self, handle):
        owner = self.wallets.store.address_owner(handle)
        if owner:
            with closing(self.wallets.store.connect()) as db, db:
                db.execute('INSERT INTO ecash_inboxes(owner,next_poll) VALUES(?,0) '
                           'ON CONFLICT(owner) DO UPDATE SET next_poll=0', (owner,))

    def due(self):
        with closing(self.wallets.store.connect()) as db, db:
            db.execute("INSERT OR IGNORE INTO ecash_inboxes(owner) SELECT owner FROM wallets WHERE status='active'")
            return [r['owner'] for r in db.execute(
                "SELECT e.owner FROM ecash_inboxes e JOIN wallets w ON w.owner=e.owner WHERE w.status='active' AND e.next_poll<=? AND w.lease_until<? ORDER BY e.next_poll,e.owner LIMIT 4",
                (time.time(), time.time()))]

    async def process(self, owner):
        if not self.available:
            return
        try:
            lease = self.wallets.store.acquire(owner)
        except Busy:
            return
        try:
            # Recheck after claiming to prevent two processes sweeping a stale
            # due list. The owner lease also serializes other custody mutations.
            with closing(self.wallets.store.connect()) as db, db:
                changed = db.execute('UPDATE ecash_inboxes SET next_poll=? WHERE owner=? AND next_poll<=?',
                                     (time.time() + self.interval, owner, time.time())).rowcount
            if not changed:
                return
            record = self.wallets.store.get(owner)
            if not record or record['status'] != 'active':
                return
            self.wallets.relay(record['material']['relay'])
            for enabled, method, timeout in (
                (self.cash_available, 'receive_ecash', 30),
                (self.clear_available, 'receive_clear', 45),
            ):
                if not enabled:
                    continue
                try:
                    async with asyncio.timeout(timeout):
                        await getattr(self.wallets.backend, method)(record['material'])
                except Exception as exc:
                    logger.warning('Acorn inbox phase=%s retry error_type=%s', method, type(exc).__name__)
        except Exception as exc:
            # Never log bearer tokens, decrypted events, keys or provider text.
            logger.warning('Acorn inbox retry error_type=%s', type(exc).__name__)
        finally:
            self.wallets.store.release(owner, lease)

    async def run(self):
        if not self.available:
            logger.warning('Direct ecash receiving unavailable; required Acorn methods are missing')
            return
        while True:
            try:
                await asyncio.gather(*(self.process(owner) for owner in self.due()))
            except Exception as exc:
                logger.warning('Acorn inbox scheduler retry error_type=%s', type(exc).__name__)
            await asyncio.sleep(1)


@router.get('/.well-known/nostr.json', include_in_schema=False)
async def nip05(request: Request, name: str = ''):
    receiver = request.app.state.ecash
    try:
        if receiver is None:
            raise ValueError('Unavailable')
        if len(request.query_params.getlist('name')) != 1:
            raise ValueError('Invalid name')
        return JSONResponse(receiver.discovery(name), headers=HEADERS)
    except ValueError:
        return JSONResponse({'names': {}}, status_code=404, headers=HEADERS)
    except Exception:
        return JSONResponse({'names': {}}, status_code=503, headers=HEADERS)
