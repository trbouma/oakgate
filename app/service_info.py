"""Public Mainstay service contract, with an explicit non-secret field list."""
from app.version import APP_VERSION

# Software capabilities, not claims about configuration, health or settlement.
CAPABILITIES = (
    'oidc-authentication', 'custodial-acorn', 'recovery-disclosure',
    'acorn-records', 'cash-payments', 'clear-payments', 'lightning-address',
    'nostr-zap-receipts', 'wallet-messaging',
)


def information(app):
    payments = app.state.payments
    management = app.state.settings.service_management
    identity = payments.identity.public_info(management) if payments else {
        'npub': None, 'fips_ipv6_address': None, 'type': 'oakgate',
        'management': management, 'state': 'unconfigured',
        'descriptor_event_id': None, 'operator': None,
    }
    return {'name': 'OakGate', 'version': APP_VERSION,
            'description': 'A custodial application for Safebox Acorns with replaceable OpenID sign-in.',
            'capabilities': list(CAPABILITIES), 'service_identity': identity}
