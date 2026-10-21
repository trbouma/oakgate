"""Operator-selected record infrastructure, independent of the login provider."""
import os
import re
from app.payment_config import secure_url
from app.zaps import public_relay

class RecordSettings:
    def __init__(self):
        self.blossom = secure_url(os.getenv('OAKGATE_BLOSSOM_SERVER', 'https://grove.safebox.dev'), 'https')
        self.transfer_server = secure_url(os.getenv('OAKGATE_TRANSFER_SERVER', self.blossom), 'https')
        self.openetr_relays = tuple(public_relay(value.strip()) for value in
            os.getenv('OAKGATE_OPENETR_RELAYS', 'wss://relay.openetr.org').split(',') if value.strip())
        if not 1 <= len(self.openetr_relays) <= 8:
            raise ValueError('Configure 1–8 OAKGATE_OPENETR_RELAYS')

        self.openetr_public_base = secure_url(os.getenv('OAKGATE_OPENETR_PUBLIC_BASE_URL', 'https://openetr.org/etr'), 'https')
        self.openetr_timeout = float(os.getenv('OAKGATE_OPENETR_QUERY_TIMEOUT_SECONDS', '5'))
        self.openetr_limit = int(os.getenv('OAKGATE_OPENETR_QUERY_LIMIT', '100'))
        if not 1 <= self.openetr_timeout <= 15 or not 1 <= self.openetr_limit <= 200:
            raise ValueError('OpenETR timeout must be 1–15 seconds and limit 1–200')
        self.openetr_servers = self.servers('OAKGATE_OPENETR_BLOSSOM_SERVERS', self.blossom)
        self.allowed_servers = tuple(dict.fromkeys((self.blossom, self.transfer_server,
            *self.servers('OAKGATE_RECORD_ALLOWED_SERVERS', self.transfer_server))))

    @staticmethod
    def servers(name, default):
        values = tuple(dict.fromkeys(secure_url(v.strip(), 'https') for v in
                       os.getenv(name, default).split(',') if v.strip()))
        if not 1 <= len(values) <= 8:
            raise ValueError(f'Configure 1–8 {name}')
        return values

    def evidence_url(self, digest):
        if not re.fullmatch('[0-9a-f]{64}', digest):
            raise ValueError('Expected a SHA-256 fingerprint')
        return self.openetr_public_base + '/' + digest

    def scanned_digest(self, value):
        # Only interpret the operator's configured verifier, never arbitrary
        # scanned URLs as artifact sources or alternate relay configuration.
        prefix = self.openetr_public_base + '/'
        if value.startswith(prefix):
            digest = value[len(prefix):]
            if re.fullmatch('[0-9a-fA-F]{64}', digest):
                return digest.lower()
        return None
