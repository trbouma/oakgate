"""Compatibility imports; durable Cashu protocol execution belongs to Acorn.

OakGate persists the opaque checkpoint and coordinates settlement. Keeping these
names preserves existing integration hooks without retaining protocol logic.
"""
from acorn.minting import DurableCashuMint as CashuMint, MintCompatibilityError

__all__ = ['CashuMint', 'MintCompatibilityError']
