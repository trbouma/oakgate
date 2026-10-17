"""Small adapter around the pinned Acorn API. No payment operations."""
import asyncio
import json
import logging
import os
from urllib.parse import urlsplit

from acorn.acorn import Acorn
from acorn.func_utils import generate_seed_phrase_and_nsec, recover_nsec_from_seed
from stroma import Keys

from app.custody import CustodyStore

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


class AcornBackend:
    def wallet(self, material):
        wallet = Acorn(nsec=material['nsec'], home_relay=material['relay'],
                       relays=[material['relay']], logging_level=logging.CRITICAL + 1)
        # Acorn declares these mutable defaults on the class; isolate each user.
        wallet.known_mints = {}
        wallet.user_records = []
        return wallet

    async def prepare(self, relay):
        phrase, nsec = generate_seed_phrase_and_nsec(strength=256)
        material = {'nsec': nsec, 'phrase': phrase, 'relay': relay,
                    'npub': Keys(priv_k=nsec).public_key_bech32(), 'legacy': False}
        wallet = self.wallet(material)
        # Let Acorn construct its native metadata, but save it durably before
        # publishing. Retrying reuses this payload, including the generated nut key.
        async def capture(label, label_info, **kwargs):
            material['initial_wallet_info'] = label_info
            return {}
        wallet.set_wallet_info = capture
        await wallet.create_instance(seed_phrase=phrase)
        return material

    def recover(self, phrase, relay, legacy=False):
        phrase = ' '.join(phrase.strip().split())
        if len(phrase) > 512:
            raise WalletInputError('Check the recovery phrase and its word order.')
        try:
            nsec = recover_nsec_from_seed(phrase, legacy=legacy)
        except (ValueError, TypeError):
            raise WalletInputError('Check the recovery phrase and its word order.') from None
        return {'nsec': nsec, 'phrase': phrase, 'relay': relay,
                'npub': Keys(priv_k=nsec).public_key_bech32(), 'legacy': legacy}

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
        default_relay=os.getenv('OAKGATE_BOOTSTRAP_RELAY', DEFAULT_RELAY),
        allowed_relays=[r.strip() for r in os.getenv('OAKGATE_ALLOWED_RELAYS', os.getenv('OAKGATE_BOOTSTRAP_RELAY', DEFAULT_RELAY)).split(',') if r.strip()],
    )
