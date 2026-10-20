"""Operator-selected record infrastructure, independent of the login provider."""
import os
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
