"""Small adapter around the pinned Acorn API."""
import asyncio
import hashlib
import json
import logging
import os
import time
from urllib.parse import urlsplit

import bolt11
from acorn.models import Proof
from acorn.acorn import Acorn

from app.custody import CustodyStore
from app.record_settings import RecordSettings
from app.clear_balances import ClearLabels
from app.payment_config import DEFAULT_MINT, secure_url

DEFAULT_RELAY = 'wss://spurline.safebox.dev'


class WalletInputError(Exception):
    pass


def normalize_relay(value):
    value = value.strip().rstrip('/')
    try:
        parsed = urlsplit(value)
        if (parsed.scheme != 'wss' or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or parsed.query or parsed.fragment or parsed.port not in (None, 443)):
            raise ValueError
    except ValueError:
        raise WalletInputError('Use a secure bootstrap relay URL beginning with wss://.') from None
    return value


class RecordReadLogger(logging.LoggerAdapter):
    def warning(self, msg, *args, **kwargs):
        # The pinned Acorn reader reports failures here and otherwise returns an
        # empty list. Surface an unavailable state instead of an empty wallet.
        if str(msg).startswith('op=get_user_records status=') and any(
            state in str(msg) for state in ('query_failed', 'decrypt_failed', 'unwrap_failed')
        ):
            raise RuntimeError('Records unavailable')
        super().warning(msg, *args, **kwargs)


class AcornBackend:
    def __init__(self, mint=DEFAULT_MINT):
        self.mint = secure_url(mint, 'https')
        self.record_settings = RecordSettings()

    def wallet(self, material):
        wallet = Acorn(nsec=material['nsec'], home_relay=material['relay'],
                       relays=[material['relay']], mints=[self.mint], logging_level=logging.CRITICAL + 1,
                       blossom_home_server=self.record_settings.blossom,
                       blossom_xfer_server=self.record_settings.transfer_server)
        # Acorn declares these mutable defaults on the class; isolate each user.
        wallet.known_mints = {}
        wallet.user_records = []
        return wallet

    def public_identity(self, material):
        return self.wallet(material).public_identity()

    @property
    def messaging_available(self):
        return all(callable(getattr(Acorn, name, None)) for name in
                   ('send_wallet_message', 'get_wallet_messages'))

    async def wallet_messages(self, material, resolver):
        return await self.wallet(material).get_wallet_messages(limit=50, resolver=resolver)

    async def send_wallet_message(self, material, destination, message, sender):
        return await self.wallet(material).send_wallet_message(
            destination['pubkey'], message, relays=destination['relays'], sender=sender)

    @property
    def ecash_receiving_available(self):
        return all(callable(getattr(Acorn, method, None)) for method in
                   ('sweep_ecash_transfers', 'reconcile_continuity_receipts'))

    async def receive_ecash(self, material):
        if not self.ecash_receiving_available:
            raise RuntimeError('Acorn receiving methods are unavailable')
        wallet = self.wallet(material)
        # Persist receipts first, then let Acorn redeem with their issuing mints.
        # Successful redemption determines acceptance; OakGate adds no mint policy.
        received = await wallet.sweep_ecash_transfers(
            relays=[material['relay']], finalize=False, limit=100, max_pages=10)
        finalized = await wallet.reconcile_continuity_receipts()
        # Both proof persistence and credit history belong to Acorn. Do not
        # synthesize a second transaction in OakGate.
        return {'received': received, 'finalized': finalized}

    @property
    def clear_receiving_available(self):
        return all(callable(getattr(Acorn, method, None)) for method in
                   ('sweep_clear_transfers', 'get_clear_receipts', 'accept_pending_clear_receipt'))

    async def receive_clear(self, material):
        wallet = self.wallet(material)
        try:
            async with asyncio.timeout(5):
                await wallet.sweep_clear_transfers(relays=[material['relay']], limit=100, max_pages=10)
        except Exception as exc:
            logging.getLogger(__name__).warning('Clear discovery pending error_type=%s', type(exc).__name__)
        pending = await wallet.get_clear_receipts(status='pending')
        # Rotate a bounded batch so an unavailable mint cannot permanently
        # prevent other receipts being attempted. Acorn owns durable retry state.
        pending = sorted(pending, key=lambda row: str(row['event_id']))
        offset = (int(time.time()) // 30 * 2) % len(pending) if pending else 0
        batch = (pending[offset:] + pending[:offset])[:2]
        accepted = 0
        for receipt in batch:
            try:
                async with asyncio.timeout(20):
                    result = await wallet.accept_pending_clear_receipt(receipt['event_id'])
                if result.get('accepted'):
                    accepted += 1
            except Exception as exc:
                logging.getLogger(__name__).warning('Clear receipt pending error_type=%s', type(exc).__name__)
        return {'accepted_count': accepted}

    @property
    def clear_sending_available(self):
        return callable(getattr(Acorn, 'send_clear_transfer', None))

    @property
    def direct_sending_available(self):
        return callable(getattr(Acorn, 'send_ecash_transfer', None))

    async def send_payment(self, material, payment):
        wallet = self.wallet(material)
        if payment['route'] == 'clear':
            result = await wallet.send_clear_transfer(
                amount=payment['amount'], recipient=payment['pubkey'],
                mint=payment['mint'], unit=payment['unit'],
                relay=payment['relay'], comment=payment['comment'])
            if not isinstance(result, dict) or result.get('status') != 'OK':
                raise RuntimeError('Clear transfer outcome unresolved')
            return {'event_id': result.get('event_id')}
        await wallet.load_data(force_profile_creation=False)
        if payment['route'] == 'ecash':
            result = await wallet.send_ecash_transfer(
                amount=payment['amount'], recipient=payment['pubkey'],
                relay=payment['relay'], comment=payment['comment'], nonce=payment['id'])
            if not isinstance(result, dict) or result.get('status') != 'OK':
                raise RuntimeError('Transfer outcome unresolved')
            return {'event_id': result.get('event_id')}
        result = await wallet.pay_multi_invoice(payment['invoice'], comment=payment['comment'])
        return {'payment_hash': result[2]}

    async def payment_proofs(self, material, item, *, prepare=False):
        wallet = self.wallet(material)
        proofs = [Proof(**p) for p in item['proofs']]
        wallet.known_mints = {proof.id: item['mint'] for proof in proofs}
        if prepare:
            events = await wallet.add_proofs_obj(proofs, prepare_only=True)
            return events[0]
        await wallet.add_proofs_obj(proofs, prepared_events=[item['proof_event']], verify=True)
        return True

    async def payment_history(self, material, item, *, prepare=False):
        wallet = self.wallet(material)
        comment = item.get('comment')
        if not comment and item.get('zap'):
            comment = json.loads(item['zap']).get('content')
        result = await wallet.add_tx_history(
            tx_type='C', amount=item['amount'],
            comment=comment or ('Nostr zap received' if item.get('zap') else 'Lightning payment received'),
            invoice=item['invoice'], payment_hash=bolt11.decode(item['invoice']).payment_hash,
            description_hash=f"cashu-mint:{item['mint']}:{item['quote']}",
            created_at=item['paid_at'], use_wallet_balance=False, prepare_only=prepare,
            prepared_event=None if prepare else item['history_event'], verify=True)
        return result if prepare else True


    async def prepare(self, relay):
        material = {**Acorn.generate_recovery_material(strength=256), 'relay': relay}
        wallet = self.wallet(material)
        # Let Acorn construct its native metadata, but save it durably before
        # publishing. Retrying reuses this payload, including the generated nut key.
        async def capture(label, label_info, **kwargs):
            material['initial_wallet_info'] = label_info
            return {}
        wallet.set_wallet_info = capture
        await wallet.create_instance(seed_phrase=material['phrase'])
        return material

    def recover(self, phrase, relay, legacy=False):
        phrase = ' '.join(phrase.strip().split())
        if len(phrase) > 512:
            raise WalletInputError('Check the recovery phrase and its word order.')
        try:
            material = Acorn.recover_material(phrase, legacy=legacy)
        except (ValueError, TypeError):
            raise WalletInputError('Check the recovery phrase and its word order.') from None
        return {**material, 'relay': relay}

    async def initialize(self, material):
        wallet = self.wallet(material)
        existing = await wallet.get_wallet_info(label='wallet')
        if existing is None:
            await wallet.set_wallet_info(label='wallet', label_info=material['initial_wallet_info'], verify=True)
        # A publish acknowledgment alone does not establish a usable wallet.
        await wallet.load_data()
        return self.cash(wallet)

    async def balance(self, material):
        wallet = self.wallet(material)
        await wallet.load_data(force_profile_creation=False)
        return self.cash(wallet)

    async def clear_balances(self, material):
        wallet = self.wallet(material)
        return await wallet.get_clear_balances()

    async def clear_transactions(self, material):
        history = await self.wallet(material).get_clear_transaction_history()
        if not isinstance(history, list):
            raise ValueError('Invalid Clear transaction history')
        return history

    async def transactions(self, material):
        wallet = self.wallet(material)
        history = await wallet.get_tx_history()
        if not isinstance(history, list):
            raise ValueError('Invalid transaction history')
        return history

    async def records(self, material):
        wallet = self.wallet(material)
        wallet.logger = RecordReadLogger(wallet.logger, {})
        records = await wallet.get_user_records(record_kind=37375, reverse=True)
        labels = []
        for record in records:
            tag = record.get('tag')
            label = tag[0] if isinstance(tag, list) and tag else tag
            if not isinstance(label, str) or not label.strip():
                continue
            timestamp = int(record.get('timestamp', 0))
            labels.append({'label': label, 'timestamp': timestamp, 'ref': self.record_ref(record)})
        return sorted(labels, key=lambda row: (-row['timestamp'], row['label']))

    @staticmethod
    def record_ref(record):
        # Opaque URL identifier; labels and contents stay out of request URLs.
        identity = record.get('id') or json.dumps([record.get('tag'), record.get('timestamp')])
        return hashlib.sha256(str(identity).encode()).hexdigest()

    async def record_detail(self, material, reference):
        wallet = self.wallet(material)
        wallet.logger = RecordReadLogger(wallet.logger, {})
        # Only records returned by Acorn's user-record reader are accessible.
        # Do not expose an arbitrary label lookup that could reveal wallet secrets.
        for record in await wallet.get_user_records(record_kind=37375, reverse=True):
            if self.record_ref(record) != reference:
                continue
            tag = record.get('tag')
            label = tag[0] if isinstance(tag, list) and tag else tag
            if not isinstance(label, str) or not label.strip():
                continue
            payload = record.get('payload', record.get('content', ''))
            text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, indent=2)
            return {'label': label, 'contents': text, 'has_blob': bool(record.get('blobsha256') or record.get('blobref')),
                    'blob_type': record.get('effective_mime') or record.get('blobtype'), 'origsha256': record.get('origsha256'),
                    'payload': payload, 'record_type': record.get('type', 'generic')}
        return None

    async def record_blob(self, material, reference):
        # Reauthorize the opaque reference against this Acorn on every request.
        detail = await self.record_detail(material, reference)
        if not detail or not detail.get('has_blob'):
            return None
        wallet = self.wallet(material)
        media_type, data = await wallet.get_record_blobdata(
            record_name=detail['label'], record_kind=37375, public_only=True)
        if not data:
            return None
        if len(data) > 25 * 1024 * 1024:
            raise ValueError('Record file is too large')
        return detail, media_type, data

    @property
    def record_workflows_available(self):
        return getattr(Acorn, 'record_workflows_version', 0) >= 1

    async def update_record(self, material, reference, payload, attachment=None, media_type=None):
        detail = await self.record_detail(material, reference)
        if detail is None:
            raise WalletInputError('This record changed. Reload Records before editing again.')
        return await self.wallet(material).put_record(
            detail['label'], payload, record_type=detail.get('record_type', 'generic'),
            record_kind=37375, preserve_existing_blob=True, return_result=True,
            blob_data=attachment, blob_type=media_type)

    async def create_record_capability(self, material, reference, purpose):
        detail = await self.record_detail(material, reference)
        if detail is None:
            raise WalletInputError('This record changed. Reload Records and try again.')
        wallet = self.wallet(material)
        method = wallet.create_record_presentation if purpose == 'present' else wallet.create_record_transfer
        return await method(detail['label'], expires_in=3600,
                            blossom_transfer_server=self.record_settings.transfer_server, public_only=True)

    async def stop_record_capability(self, material, descriptor):
        return await self.wallet(material).delete_record_transfer(descriptor,
            allowed_servers=[self.record_settings.transfer_server])

    @staticmethod
    def cash(wallet):
        # load_data reads cash proofs; Clear balances remain separate.
        amount = wallet.get_balance()
        if not isinstance(amount, int) or amount < 0:
            raise ValueError('Invalid balance')
        return amount


class WalletService:
    def __init__(self, store, backend=None, default_relay=DEFAULT_RELAY, allowed_relays=None):
        self.store = store
        self.backend = backend or AcornBackend()
        self.clear_labels = ClearLabels()
        self.default_relay = normalize_relay(default_relay)
        self.allowed_relays = {normalize_relay(v) for v in (allowed_relays or [default_relay])}
        if self.default_relay not in self.allowed_relays:
            raise ValueError('Default bootstrap relay must be allowed')

    def relay(self, value):
        relay = normalize_relay(value)
        # Only operator-approved endpoints can receive server-originated requests.
        if relay not in self.allowed_relays:
            raise WalletInputError('This bootstrap relay is not enabled by the OakGate operator.')
        return relay

    async def balance(self, material):
        self.relay(material['relay'])
        return await asyncio.wait_for(self.backend.balance(material), timeout=40)

    async def clear_balances(self, material):
        self.relay(material['relay'])
        balances = await asyncio.wait_for(self.backend.clear_balances(material), timeout=40)
        return await self.clear_labels.resolve(balances)

    def recovery_details(self, material):
        """Disclose only material that Acorn verifies restores this identity."""
        relay = self.relay(material['relay'])
        phrase, legacy = material.get('phrase'), material.get('legacy')
        if not isinstance(phrase, str) or not phrase.strip() or type(legacy) is not bool:
            raise ValueError('Recovery material is incomplete')
        recovered = self.backend.recover(phrase, relay, legacy=legacy)
        if self.backend.public_identity(recovered) != self.backend.public_identity(material):
            raise ValueError('Recovery material does not match this Acorn')
        return {'phrase': ' '.join(phrase.split()), 'relay': relay, 'legacy': legacy}

    async def clear_transactions(self, material):
        self.relay(material['relay'])
        return await asyncio.wait_for(self.backend.clear_transactions(material), timeout=40)

    async def transactions(self, material):
        self.relay(material['relay'])
        return await asyncio.wait_for(self.backend.transactions(material), timeout=40)

    async def records(self, material):
        self.relay(material['relay'])
        return await asyncio.wait_for(self.backend.records(material), timeout=40)

    async def record_detail(self, material, reference):
        self.relay(material['relay'])
        return await asyncio.wait_for(self.backend.record_detail(material, reference), timeout=40)

    async def record_blob(self, material, reference):
        self.relay(material['relay'])
        return await asyncio.wait_for(self.backend.record_blob(material, reference), timeout=40)

    async def record_action(self, material, action, *args):
        self.relay(material['relay'])
        if action not in {'update_record', 'create_record_capability', 'stop_record_capability'}:
            raise ValueError('Unknown record action')
        return await asyncio.wait_for(getattr(self.backend, action)(material, *args), timeout=60)

    async def initialize(self, owner):
        token = self.store.acquire(owner)
        active = False
        try:
            record = self.store.get(owner)
            self.relay(record['material']['relay'])
            if record['status'] == 'active':
                return
            await asyncio.wait_for(self.backend.initialize(record['material']), timeout=40)
            active = True
        finally:
            self.store.release(owner, token, active=active)


def configured_service():
    key = os.getenv('OAKGATE_CUSTODY_KEY', '').strip()
    if not key or key.startswith('<'):
        return None
    return WalletService(
        CustodyStore(os.getenv('OAKGATE_DATA_DIR', '.oakgate'), key),
        backend=AcornBackend(os.getenv('OAKGATE_BOOTSTRAP_MINT', DEFAULT_MINT)),
        default_relay=os.getenv('OAKGATE_BOOTSTRAP_RELAY', DEFAULT_RELAY),
        allowed_relays=[r.strip() for r in os.getenv('OAKGATE_ALLOWED_RELAYS', os.getenv('OAKGATE_BOOTSTRAP_RELAY', DEFAULT_RELAY)).split(',') if r.strip()],
    )
