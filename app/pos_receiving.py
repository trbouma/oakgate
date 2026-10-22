"""Terminal-scoped receipt requests. Settlement remains in the existing workers."""
import asyncio
import json
import hashlib
import logging
import re
import secrets
import time
from contextlib import closing

from acorn.payment_request import decode_payment_request
from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool

from app.clear_routing import clear_availability
from app.pos_store import POSDenied, POSStore, digest
from app.receive import receipt_status
from app.receive_amount import receive_amount
from app.record_previews import _qr_svg
from app.request_store import RequestStore

log = logging.getLogger(__name__)
# Separate from cash sats: Clear assets have issuer-defined whole units.
CLEAR_MAX = 1_000_000


class TerminalRequests:
    def __init__(self, custody):
        self.custody = custody
        self.tickets = RequestStore(custody)
        with closing(custody.connect()) as db, db:
            db.execute('''CREATE TABLE IF NOT EXISTS pos_receipts (
                terminal TEXT NOT NULL, request_key TEXT NOT NULL, body_hash TEXT NOT NULL,
                id TEXT NOT NULL UNIQUE, owner TEXT NOT NULL, created REAL NOT NULL,
                PRIMARY KEY(terminal, request_key))''')

    def find(self, actor, key, payload=None):
        with closing(self.custody.connect()) as db:
            row = db.execute('SELECT * FROM pos_receipts WHERE terminal=? AND request_key=? AND owner=?',
                             (actor['id'], key, actor['owner'])).fetchone()
        if row and payload is not None and row['body_hash'] != digest(payload):
            raise HTTPException(409, 'This request already has a different amount. Start a new request.')
        return dict(row) if row else None

    def reserve(self, actor, key, payload):
        with closing(self.custody.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            terminal = db.execute('SELECT * FROM pos_terminals WHERE id=? AND revoked IS NULL', (actor['id'],)).fetchone()
            if not terminal or terminal['owner'] != actor['owner'] or terminal['wallet_id'] != actor['wallet_id']:
                raise POSDenied
            POSStore._wallet(db, actor['owner'], actor['wallet_id'])
            row = db.execute('SELECT * FROM pos_receipts WHERE terminal=? AND request_key=?', (actor['id'], key)).fetchone()
            if row:
                if row['body_hash'] != digest(payload):
                    raise HTTPException(409, 'Start a new request for a different amount.')
                return dict(row), False
            POSStore._limit(db, 'receipts:' + actor['id'], 120, 3600)
            ident = secrets.token_hex(16)
            db.execute('INSERT INTO pos_receipts VALUES(?,?,?,?,?,?)',
                       (actor['id'], key, digest(payload), ident, actor['owner'], time.time()))
            return dict(db.execute('SELECT * FROM pos_receipts WHERE id=?', (ident,)).fetchone()), True

    def finish(self, row, item):
        # The ticket ID is reserved before any external operation. A crash between
        # invoice creation and this commit can recover that exact invoice by ID.
        with closing(self.custody.connect()) as db, db:
            db.execute('INSERT OR IGNORE INTO wallet_requests VALUES(?,?,?,?,?)',
                       (row['id'], row['owner'], 'ready', row['created'],
                        self.custody.seal(row['owner'], {**item, 'id': row['id']})))


def cash_item(payment):
    return {'purpose': 'cash-request', 'code': payment['invoice'], 'payment_id': payment['id'],
            'amount': payment['amount'], 'display_name': 'Cash', 'display_unit': 'sats'}


async def options(request, actor):
    state = request.app.state
    rates = state.rates
    rows = await run_in_threadpool(rates.rows) if rates and rates.enabled else []
    currency = await run_in_threadpool(rates.store.currency, actor['owner'], rates.default_currency) if rates else 'SATS'
    assets, unavailable = [], False
    if state.ecash and state.ecash.clear_available:
        try:
            async with asyncio.timeout(12):
                assets = await state.send.clear_assets(actor['owner'])
            assets = [a for a in assets if clear_availability(a['mint']) != 'instance']
        except Exception:
            unavailable = True
    return {'assets': [{k: a[k] for k in ('id', 'display_name', 'display_unit')} for a in assets],
            'currencies': [{k: r[k] for k in ('code', 'symbol', 'description', 'fiat_per_btc')} for r in rows
                           if r['fiat_per_btc'] and not r['stale']],
            'currency': currency, 'cash_enabled': bool(state.payments and state.payments.config.enabled),
            'cash_min': state.payments.config.min_sat if state.payments else 1,
            'cash_max': state.payments.config.max_sat if state.payments else 0,
            'clear_max': CLEAR_MAX, 'clear_unavailable': unavailable}


async def read_receipt(request, actor, row, include_code=True):
    state = request.app.state
    store = await run_in_threadpool(TerminalRequests, state.wallets.store)
    try:
        item = await run_in_threadpool(store.tickets.get, actor['owner'], row['id'])
    except ValueError:
        payment = await run_in_threadpool(state.payments.store.get, row['id']) if state.payments else None
        if payment and payment['owner'] == actor['owner'] and payment.get('invoice') and payment['state'] in {'waiting', 'credited', 'complete'}:
            await run_in_threadpool(store.finish, row, cash_item(payment))
            item = await run_in_threadpool(store.tickets.get, actor['owner'], row['id'])
        else:
            return {'state': 'preparing' if time.time() - row['created'] < 90 else 'unconfirmed', 'request_key': row['request_key']}
    wallet = await run_in_threadpool(state.wallets.store.get, actor['owner'])
    if not wallet or hashlib.sha256(wallet['material']['npub'].encode()).hexdigest() != actor['wallet_id'] or wallet['status'] != 'active':
        raise POSDenied
    receipt = await receipt_status(request, state.wallets, actor['owner'], wallet['material'], item)
    return {'state': receipt, 'request_key': row['request_key'], **({'code': item['code'], 'qr': str(_qr_svg(item['code']))} if include_code else {}), 'amount': item['amount'],
            'display_name': item['display_name'], 'display_unit': item['display_unit']}


async def receive(request, actor, operation, payload):
    try:
        data = json.loads(payload)
    except (ValueError, TypeError):
        raise HTTPException(400, 'Invalid request') from None
    expected = set() if operation == 'receive-config' else {'request_key'} if operation == 'receipt' else {'request_key', 'amount', 'asset', 'currency', 'quoted_rate'}
    if not isinstance(data, dict) or set(data) != expected or any(not isinstance(v, str) or len(v) > 128 for v in data.values()):
        raise HTTPException(400, 'Invalid request')
    if operation == 'receive-config':
        return await options(request, actor)
    if not re.fullmatch(r'[a-zA-Z0-9_-]{16,80}', data['request_key']):
        raise HTTPException(400, 'Invalid request identifier')
    state = request.app.state
    store = await run_in_threadpool(TerminalRequests, state.wallets.store)
    row = await run_in_threadpool(store.find, actor, data['request_key'], payload if operation == 'receive' else None)
    if row:
        return await read_receipt(request, actor, row, operation == 'receive')
    if operation == 'receipt':
        raise HTTPException(404, 'Request not found on this terminal')
    rates = state.rates
    rows = await run_in_threadpool(rates.rows) if rates and rates.enabled else []
    try:
        units = receive_amount(data['amount'], 'SATS' if data['asset'] else data['currency'], rows, data['quoted_rate'])
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    asset = None
    if data['asset']:
        if not state.ecash or not state.ecash.clear_available or units > CLEAR_MAX:
            raise HTTPException(400, 'Clear receiving unavailable or amount exceeds the receiving limit.')
        async with asyncio.timeout(12):
            assets = await state.send.clear_assets(actor['owner'])
        asset = next((a for a in assets if a['id'] == data['asset'] and clear_availability(a['mint']) != 'instance'), None)
        if not asset:
            raise HTTPException(400, 'Choose an available Clear asset.')
    elif not state.payments or not state.payments.config.enabled or not state.payments.config.min_sat <= units <= state.payments.config.max_sat:
        raise HTTPException(400, 'Amount is outside the configured cash receiving limits.')
    row, created = await run_in_threadpool(store.reserve, actor, data['request_key'], payload)
    if created:
        # Never repeat an uncertain preparation. Only its original task may create
        # the request; subsequent calls recover persisted output, including after restart.
        try:
            if asset:
                wallet = await run_in_threadpool(state.wallets.store.get, actor['owner'])
                if not wallet or hashlib.sha256(wallet['material']['npub'].encode()).hexdigest() != actor['wallet_id']:
                    raise POSDenied
                state.wallets.relay(wallet['material']['relay'])
                async with asyncio.timeout(15):
                    code = await state.wallets.backend.create_clear_request(wallet['material'], units, asset, '')
                item = {'purpose': 'clear-request', 'code': code, 'request_id': decode_payment_request(code).payment_id,
                        'amount': units, 'mint': asset['mint'], 'unit': asset['unit'],
                        'display_name': asset['display_name'], 'display_unit': asset['display_unit']}
            else:
                item = cash_item(await state.payments.request_invoice(actor['owner'], units, request_id=row['id']))
            await run_in_threadpool(store.finish, row, item)
        except Exception as exc:
            log.warning('POS receipt preparation unconfirmed error_type=%s', type(exc).__name__)
    return await read_receipt(request, actor, row)
