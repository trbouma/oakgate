"""Operator-controlled receiving settings, independent of sign-in."""
import os
from dataclasses import dataclass
from urllib.parse import urlsplit

DEFAULT_MINT = 'https://mint.safebox.dev'
DEFAULT_ZAP_RELAYS = ('wss://relay.primal.net', 'wss://relay.damus.io', 'wss://nos.lol')


def secure_url(value, scheme):
    value = value.strip().rstrip('/')
    p = urlsplit(value)
    if (p.scheme != scheme or not p.hostname or p.username is not None or p.password is not None
            or p.query or p.fragment or p.port not in (None, 443)):
        raise ValueError(f'Expected a {scheme} URL without credentials, query or custom port')
    return value


@dataclass(frozen=True)
class PaymentSettings:
    mint: str = DEFAULT_MINT
    relays: tuple = DEFAULT_ZAP_RELAYS
    min_sat: int = 1
    max_sat: int = 1_000_000
    poll_seconds: int = 5
    require_description_hash: bool = False
    enabled: bool = True

    def __post_init__(self):
        object.__setattr__(self, 'mint', secure_url(self.mint, 'https'))
        object.__setattr__(self, 'relays', tuple(dict.fromkeys(secure_url(r, 'wss') for r in self.relays)))
        if not self.relays or len(self.relays) > 10:
            raise ValueError('Configure 1–10 public zap relays')
        if not 1 <= self.min_sat <= self.max_sat <= 100_000_000 or not 2 <= self.poll_seconds <= 60:
            raise ValueError('Invalid receiving limits or polling interval')

    @classmethod
    def from_env(cls):
        def flag(name, default):
            value = os.getenv(name, default).strip().lower()
            if value not in ('true', 'false'):
                raise ValueError(f'{name} must be true or false')
            return value == 'true'

        return cls(require_description_hash=flag('OAKGATE_REQUIRE_DESCRIPTION_HASH', 'false'),
                   enabled=flag('OAKGATE_PAYMENTS_ENABLED', 'true'),
                   mint=os.getenv('OAKGATE_BOOTSTRAP_MINT', DEFAULT_MINT),
                   relays=tuple(r.strip() for r in os.getenv('OAKGATE_ZAP_RELAYS', ','.join(DEFAULT_ZAP_RELAYS)).split(',') if r.strip()),
                   min_sat=int(os.getenv('OAKGATE_RECEIVE_MIN_SAT', '1')),
                   max_sat=int(os.getenv('OAKGATE_RECEIVE_MAX_SAT', '1000000')),
                   poll_seconds=int(os.getenv('OAKGATE_PAYMENT_POLL_SECONDS', '5')))
