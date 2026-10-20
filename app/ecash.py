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
            db.execute('BEGIN IMMEDIATE')
            db.execute('CREATE TABLE IF NOT EXISTS ecash_inboxes (owner TEXT PRIMARY KEY, next_poll REAL NOT NULL DEFAULT 0)')

            columns = {row['name'] for row in db.execute('PRAGMA table_info(ecash_inboxes)')}
            if 'failures' not in columns:
                db.execute('ALTER TABLE ecash_inboxes ADD COLUMN failures INTEGER NOT NULL DEFAULT 0')

    @property
    def cash_available(self):
        return self.enabled and bool(getattr(self.wallets.backend, 'ecash_receiving_available', False))

    @property
    def clear_available(self):
        return self.enabled and self.clear_enabled and bool(getattr(self.wallets.backend, 'clear_receiving_available', False))

    @property
    def available(self):
        return self.cash_available or self.clear_available or bool(getattr(self.wallets.backend, 'messaging_available', False))

    def wallet_destination(self, name):
        name = name.lower()
        if not self.available or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{2,31}', name):
            raise ValueError('Address unavailable')
        owner = self.wallets.store.address_owner(name)
        record = self.wallets.store.get(owner) if owner else None
        if not record or record['status'] != 'active':
            raise ValueError('Address unavailable')
        relay = self.wallets.relay(record['material']['relay'])
        pubkey = self.wallets.backend.public_identity(record['material'])['hex']
        return name, pubkey, relay

    def discovery(self, name):
        name = name.lower()
        if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{2,31}', name):
            raise ValueError('Address unavailable')
        owner = self.wallets.store.address_owner(name)
        social = self.wallets.store.social_npub(owner) if owner else ''
        if social:
            from app.identity import social_public_identity
            # Social NIP-05 must not advertise wallet capabilities or relays.
            return {'names': {name: social_public_identity(social)['hex']}}
        name, pubkey, relay = self.wallet_destination(name)
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

    def claim_poll(self, owner, marker):
        with closing(self.wallets.store.connect()) as db, db:
            return db.execute('UPDATE ecash_inboxes SET next_poll=? WHERE owner=? AND next_poll<=?',
                              (marker, owner, time.time())).rowcount

    def finish_poll(self, owner, marker, failed, deferred):
        with closing(self.wallets.store.connect()) as db, db:
            row = db.execute('SELECT failures FROM ecash_inboxes WHERE owner=?', (owner,)).fetchone()
            failures = min(row['failures'] + 1, 5) if failed else 0
            delay = 5 if deferred and not failed else max(self.interval, min(self.interval * 2 ** failures, 300))
            db.execute('UPDATE ecash_inboxes SET next_poll=?,failures=? WHERE owner=? AND next_poll=?',
                       (time.time() + delay, failures, owner, marker))

    async def database(self, method, *args):
        started = time.monotonic()
        try:
            return await asyncio.to_thread(method, *args)
        finally:
            elapsed = time.monotonic() - started
            if elapsed >= 0.25:
                logger.warning('Acorn inbox database=%s elapsed=%.3fs', method.__name__, elapsed)

    async def phase(self, owner, lease, method, material):
        """Drain writes on shutdown while retaining exclusive custody ownership."""
        task = asyncio.create_task(getattr(self.wallets.backend, method)(material))
        started = time.monotonic()
        status = 'error'
        cancelled = False
        try:
            while not task.done():
                try:
                    await asyncio.wait({task}, timeout=15)
                except asyncio.CancelledError:
                    # Do not interrupt a receipt/proof write during graceful shutdown.
                    cancelled = True
                await self.database(self.wallets.store.renew, owner, lease)
                if not task.done():
                    logger.warning('Acorn inbox phase=%s status=running elapsed=%.3fs',
                                   method, time.monotonic() - started)
            result = task.result()
            status = 'retry' if isinstance(result, dict) and result.get('retry_pending') else 'complete'
            if cancelled:
                raise asyncio.CancelledError
            return result
        finally:
            if not task.done():
                # Lease loss is exceptional: stop work rather than permit overlap.
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            logger.warning('Acorn inbox phase=%s status=%s elapsed=%.3fs',
                           method, status, time.monotonic() - started)
            if cancelled:
                raise asyncio.CancelledError

    async def process(self, owner):
        # Threaded SQLite commits cannot be cancelled. Drain the pass so a lease
        # acquired by a completing thread always reaches its matching release.
        task = asyncio.create_task(self._process(owner))
        cancelled = False
        while True:
            try:
                await asyncio.shield(task)
                break
            except asyncio.CancelledError:
                if task.done():
                    raise
                cancelled = True
            except Exception:
                if cancelled:
                    raise asyncio.CancelledError
                raise
        if cancelled:
            raise asyncio.CancelledError

    async def _process(self, owner):
        if not self.available:
            return
        try:
            lease = await self.database(self.wallets.store.acquire, owner)
        except Busy:
            return
        # Reserve a retry after crashes; active work is protected by renewed leases.
        marker = time.time() + 90 + self.interval
        claimed = False
        failed = False
        deferred = False
        try:
            # Recheck after claiming to prevent two processes sweeping a stale
            # due list. The owner lease also serializes other custody mutations.
            changed = await self.database(self.claim_poll, owner, marker)
            if not changed:
                return
            claimed = True
            record = await self.database(self.wallets.store.get, owner)
            if not record or record['status'] != 'active':
                return
            self.wallets.relay(record['material']['relay'])
            if getattr(self.wallets.backend, 'inbox_phases', False):
                phases = ((self.cash_available, 'discover_ecash'),
                          (self.clear_available, 'discover_clear'),
                          (self.cash_available, 'settle_ecash'),
                          (self.clear_available, 'settle_clear'))
            else:
                phases = ((self.cash_available, 'receive_ecash'),
                          (self.clear_available, 'receive_clear'))
            for enabled, method in phases:
                if not enabled:
                    continue
                if lease is None:
                    # Give foreground requests a chance between inbox phases.
                    # Never queue behind a user payment or steal its lease.
                    await asyncio.sleep(1)
                    try:
                        lease = await self.database(self.wallets.store.acquire, owner)
                    except Busy:
                        deferred = True
                        break
                    record = await self.database(self.wallets.store.get, owner)
                    if not record or record['status'] != 'active':
                        break
                    self.wallets.relay(record['material']['relay'])
                try:
                    result = await self.phase(owner, lease, method, record['material'])
                    if isinstance(result, dict) and result.get('retry_pending'):
                        failed = True
                except Exception as exc:
                    failed = True
                    logger.warning('Acorn inbox phase=%s retry error_type=%s', method, type(exc).__name__)
                finally:
                    await self.database(self.wallets.store.release, owner, lease)
                    lease = None
        except Exception as exc:
            failed = True
            # Never log bearer tokens, decrypted events, keys or provider text.
            logger.warning('Acorn inbox retry error_type=%s', type(exc).__name__)
        finally:
            try:
                if claimed:
                    # Start cooldown after work finishes, not before network
                    # waits. Conditional update preserves wake() during a run.
                    await self.database(self.finish_poll, owner, marker, failed, deferred)
            finally:
                if lease is not None:
                    await self.database(self.wallets.store.release, owner, lease)

    async def run(self):
        if not self.available:
            logger.warning('Direct ecash receiving unavailable; required Acorn methods are missing')
            return
        tasks = {}
        try:
            while True:
                try:
                    for owner, task in list(tasks.items()):
                        if task.done():
                            del tasks[owner]
                            await task
                    for owner in await self.database(self.due):
                        if len(tasks) >= 4:
                            break
                        if owner not in tasks:
                            tasks[owner] = asyncio.create_task(self.process(owner))
                except Exception as exc:
                    logger.warning('Acorn inbox scheduler retry error_type=%s', type(exc).__name__)
                await asyncio.sleep(1)
        finally:
            # Finish cancellation cleanup before shutdown releases application state.
            for task in tasks.values():
                task.cancel()
            await asyncio.gather(*tasks.values(), return_exceptions=True)


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


@router.get('/.well-known/safebox.json', include_in_schema=False)
async def safebox_directory(request: Request):
    """Wallet directory always uses the Acorn binding, never the social preference."""
    from urllib.parse import urlsplit
    headers = {**HEADERS, 'X-Content-Type-Options': 'nosniff'}
    def failure(code, status):
        return JSONResponse({'error': code}, status_code=status, headers=headers)
    names = request.query_params.getlist('name')
    if len(names) != 1:
        return failure('invalid_name', 400)
    try:
        from acorn.safebox_discovery import build_safebox_document, normalize_safebox_name, parse_safebox_document
    except ImportError:
        # Allow old locked Acorn installations to retain all existing behaviour.
        return failure('discovery_dependency_unavailable', 503)
    try:
        name = normalize_safebox_name(names[0])
    except ValueError:
        return failure('invalid_name', 400)
    receiver = request.app.state.ecash
    if receiver is None or not receiver.available:
        return failure('not_found', 404)
    try:
        name, pubkey, relay = receiver.wallet_destination(name)
    except ValueError:
        return failure('not_found', 404)
    except Exception:
        return failure('unavailable', 503)
    try:
        origin = urlsplit(request.app.state.settings.origin)
        if origin.scheme != 'https' or origin.port is not None:
            return failure('not_found', 404)
        address = f'{name}@{origin.hostname}'
        if receiver.cash_available or receiver.clear_available:
            payload = build_safebox_document(address, pubkey, [relay],
                cash=receiver.cash_available, clear=receiver.clear_available)
        else:
            payload = {'version': 1, 'address': address, 'pubkey': pubkey,
                       'relays': [relay], 'capabilities': {}}
        if getattr(receiver.wallets.backend, 'messaging_available', False):
            payload['capabilities']['safebox-wallet-message'] = {'transports': ['nip17'], 'kinds': [14]}
        payload = parse_safebox_document(payload, address).to_dict()
        return JSONResponse(payload, headers=headers)
    except Exception:
        return failure('unavailable', 503)
