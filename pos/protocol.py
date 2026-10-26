"""Shared operation names; no account application imports in the POS service."""
CARD_OPS = frozenset({"card-start", "card-status", "card-prepare", "card-verify", "card-cancel", "card-balance", "card-pay"})

RECORD_OPS = frozenset({"record-start", "record-status", "record-nfc", "record-present", "record-cancel"})
