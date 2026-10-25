"""PostgreSQL schema v1. SQLite history remains in migrations/baseline_0001.json."""
from sqlalchemy import MetaData, Table, Column, Text, BigInteger, Double, LargeBinary, Identity, PrimaryKeyConstraint, UniqueConstraint, CheckConstraint, Index, text

metadata = MetaData()

currency_rates = Table('currency_rates', metadata,
    Column('code', Text, nullable=True),
    Column('symbol', Text, nullable=False),
    Column('description', Text, nullable=False),
    Column('fiat_per_btc', Text, nullable=True),
    Column('fetched_at', Double, nullable=True),
    Column('source', Text, nullable=True),
    PrimaryKeyConstraint('code'),
)

ecash_inboxes = Table('ecash_inboxes', metadata,
    Column('owner', Text, nullable=True),
    Column('next_poll', Double, nullable=False, server_default=text('0')),
    Column('failures', BigInteger, nullable=False, server_default=text('0')),
    PrimaryKeyConstraint('owner'),
)

incoming_payments = Table('incoming_payments', metadata,
    Column('id', Text, nullable=True),
    Column('owner', Text, nullable=False),
    Column('zap_id', Text, nullable=True),
    Column('created', Double, nullable=False),
    Column('state', Text, nullable=False),
    Column('encrypted', LargeBinary, nullable=False),
    Column('next_check', Double, nullable=False, server_default=text('0')),
    Column('lease', Text, nullable=True),
    Column('lease_until', Double, nullable=False, server_default=text('0')),
    Column('history_written', BigInteger, nullable=False, server_default=text('0')),
    PrimaryKeyConstraint('id'),
    UniqueConstraint('zap_id'),
)

Index('incoming_due', incoming_payments.c.state, incoming_payments.c.next_check, unique=False)
Index('incoming_owner', incoming_payments.c.owner, incoming_payments.c.created, unique=False)
lightning_handles = Table('lightning_handles', metadata,
    Column('normalized_handle', Text, nullable=True),
    Column('owner', Text, nullable=False),
    PrimaryKeyConstraint('normalized_handle'),
)

nfc_card_pins = Table('nfc_card_pins', metadata,
    Column('pairing', Text, nullable=True),
    Column('card_id', Text, nullable=True),
    Column('verifier', LargeBinary, nullable=False),
    Column('disclosure', LargeBinary, nullable=True),
    Column('acknowledged', BigInteger, nullable=True),
    PrimaryKeyConstraint('pairing'),
    UniqueConstraint('card_id'),
)

nfc_cards = Table('nfc_cards', metadata,
    Column('id', Text, nullable=True),
    Column('owner', Text, nullable=False),
    Column('wallet_id', Text, nullable=False),
    Column('terminal', Text, nullable=False),
    Column('verifier', Text, nullable=False),
    Column('payload_hash', Text, nullable=False),
    Column('payload', LargeBinary, nullable=True),
    Column('created', BigInteger, nullable=False),
    Column('expires', BigInteger, nullable=False),
    Column('activated', BigInteger, nullable=True),
    Column('revoked', BigInteger, nullable=True),
    PrimaryKeyConstraint('id'),
)

Index('nfc_card_owner', nfc_cards.c.owner, unique=False)
nfc_issuer = Table('nfc_issuer', metadata,
    Column('id', BigInteger, nullable=True),
    Column('encrypted', LargeBinary, nullable=False),
    PrimaryKeyConstraint('id'),
)

nfc_login_attempts = Table('nfc_login_attempts', metadata,
    Column('card_id', Text, nullable=True),
    Column('failures', BigInteger, nullable=False, server_default=text('0')),
    PrimaryKeyConstraint('card_id'),
)

nfc_login_nonces = Table('nfc_login_nonces', metadata,
    Column('nonce', Text, nullable=True),
    Column('expires', Double, nullable=False),
    PrimaryKeyConstraint('nonce'),
)

nfc_login_policy = Table('nfc_login_policy', metadata,
    Column('card_id', Text, nullable=True),
    Column('require_pin', BigInteger, nullable=False),
    PrimaryKeyConstraint('card_id'),
    CheckConstraint('require_pin IN (0,1)'),
)

nfc_login_requests = Table('nfc_login_requests', metadata,
    Column('pairing', Text, nullable=True),
    Column('card_id', Text, nullable=True),
    Column('identity', LargeBinary, nullable=False),
    Column('requested', BigInteger, nullable=False),
    Column('state', Text, nullable=False, server_default=text("'requested'")),
    PrimaryKeyConstraint('pairing'),
    UniqueConstraint('card_id'),
)

nfc_pairings = Table('nfc_pairings', metadata,
    Column('id', Text, nullable=True),
    Column('terminal', Text, nullable=False),
    Column('request_key', Text, nullable=False),
    Column('verifier', Text, nullable=False),
    Column('invitation', LargeBinary, nullable=True),
    Column('created', Double, nullable=False),
    Column('expires', Double, nullable=False),
    Column('state', Text, nullable=False),
    Column('owner', Text, nullable=True),
    Column('wallet_id', Text, nullable=True),
    Column('card_id', Text, nullable=True),
    PrimaryKeyConstraint('id'),
    UniqueConstraint('terminal','request_key'),
)

outgoing_payments = Table('outgoing_payments', metadata,
    Column('id', Text, nullable=True),
    Column('owner', Text, nullable=False),
    Column('state', Text, nullable=False),
    Column('encrypted', LargeBinary, nullable=False),
    Column('created', Double, nullable=False),
    Column('request_key', Text, nullable=True),
    Column('started_at', Double, nullable=True),
    PrimaryKeyConstraint('id'),
)

Index('outgoing_request', outgoing_payments.c.owner, outgoing_payments.c.request_key, unique=True, postgresql_where=text('request_key IS NOT NULL'))
pos_audit = Table('pos_audit', metadata,
    Column('id', BigInteger, Identity(), nullable=True),
    Column('terminal', Text, nullable=False),
    Column('action', Text, nullable=False),
    Column('at', Double, nullable=False),
    PrimaryKeyConstraint('id'),
)

pos_challenges = Table('pos_challenges', metadata,
    Column('id', Text, nullable=True),
    Column('terminal', Text, nullable=False),
    Column('session', Text, nullable=False),
    Column('operation', Text, nullable=False),
    Column('public_key', Text, nullable=False),
    Column('message', Text, nullable=False),
    Column('expires', Double, nullable=False),
    PrimaryKeyConstraint('id'),
)

pos_limits = Table('pos_limits', metadata,
    Column('bucket', Text, nullable=True),
    Column('count', BigInteger, nullable=False),
    Column('expires', Double, nullable=False),
    PrimaryKeyConstraint('bucket'),
)

pos_receipts = Table('pos_receipts', metadata,
    Column('terminal', Text, nullable=False),
    Column('request_key', Text, nullable=False),
    Column('body_hash', Text, nullable=False),
    Column('id', Text, nullable=False),
    Column('owner', Text, nullable=False),
    Column('created', Double, nullable=False),
    PrimaryKeyConstraint('terminal','request_key'),
    UniqueConstraint('id'),
)

pos_sessions = Table('pos_sessions', metadata,
    Column('id', Text, nullable=True),
    Column('terminal', Text, nullable=False),
    Column('verifier', Text, nullable=False),
    Column('expires', Double, nullable=False),
    PrimaryKeyConstraint('id'),
    UniqueConstraint('verifier'),
)

pos_terminals = Table('pos_terminals', metadata,
    Column('id', Text, nullable=True),
    Column('owner', Text, nullable=False),
    Column('wallet_id', Text, nullable=False),
    Column('name', Text, nullable=False),
    Column('verifier', Text, nullable=False),
    Column('created', Double, nullable=False),
    Column('activation_until', Double, nullable=False),
    Column('public_key', Text, nullable=True),
    Column('fingerprint', Text, nullable=True),
    Column('activated', Double, nullable=True),
    Column('last_seen', Double, nullable=True),
    Column('revoked', Double, nullable=True),
    PrimaryKeyConstraint('id'),
)

Index('pos_terminal_owner', pos_terminals.c.owner, unique=False)
record_capabilities = Table('record_capabilities', metadata,
    Column('id', Text, nullable=True),
    Column('owner', Text, nullable=False),
    Column('encrypted', LargeBinary, nullable=False),
    PrimaryKeyConstraint('id'),
)

service_identity = Table('service_identity', metadata,
    Column('id', BigInteger, nullable=True),
    Column('npub', Text, nullable=False),
    PrimaryKeyConstraint('id'),
    CheckConstraint('id=1'),
)

user_currency_preferences = Table('user_currency_preferences', metadata,
    Column('owner', Text, nullable=True),
    Column('currency', Text, nullable=False),
    PrimaryKeyConstraint('owner'),
)

user_display_preferences = Table('user_display_preferences', metadata,
    Column('owner', Text, nullable=True),
    Column('language', Text, nullable=False),
    PrimaryKeyConstraint('owner'),
)

user_preferences = Table('user_preferences', metadata,
    Column('owner', Text, nullable=True),
    Column('handle', Text, nullable=False),
    Column('normalized_handle', Text, nullable=False),
    PrimaryKeyConstraint('owner'),
    UniqueConstraint('normalized_handle'),
)

user_social_preferences = Table('user_social_preferences', metadata,
    Column('owner', Text, nullable=True),
    Column('npub', Text, nullable=False),
    PrimaryKeyConstraint('owner'),
)

wallet_message_submissions = Table('wallet_message_submissions', metadata,
    Column('token', Text, nullable=True),
    Column('created', Double, nullable=False),
    PrimaryKeyConstraint('token'),
)

wallet_requests = Table('wallet_requests', metadata,
    Column('id', Text, nullable=True),
    Column('owner', Text, nullable=False),
    Column('state', Text, nullable=False),
    Column('created', Double, nullable=False),
    Column('encrypted', LargeBinary, nullable=False),
    PrimaryKeyConstraint('id'),
)

wallets = Table('wallets', metadata,
    Column('owner', Text, nullable=True),
    Column('wallet_id', Text, nullable=False),
    Column('encrypted', LargeBinary, nullable=False),
    Column('status', Text, nullable=False),
    Column('lease', Text, nullable=True),
    Column('lease_until', Double, nullable=False, server_default=text('0')),
    PrimaryKeyConstraint('owner'),
    UniqueConstraint('wallet_id'),
)


# PostgreSQL requires primary keys to be non-null; reject null keys at import.
# Only audit IDs are generated. Identity/key rows have explicit IDs.
for table in metadata.tables.values():
    for column in table.primary_key:
        column.nullable = False
        if table.name != 'pos_audit':
            column.autoincrement = False
