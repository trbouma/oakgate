---
title: Security Statement
description: User agency, custodial trust and the path to independence in OakGate.
---

# Security Statement

**You have agency over your data—including your funds and records. Choosing a
trusted service to help manage them should be your choice, not a surrender of
that agency.** This principle guides OakGate's design and the responsibilities
of anyone operating it.

## Help with the complexity. Choice stays with you.

OakGate is designed for people who want familiar sign-in, recoverable access and
simple everyday payments and record sharing. You can rely on a provider to look
after the technical details while you use Everyday Funds, Community Credits and
the records that matter to you.

This is a custodial relationship: OakGate retains the secrets needed to operate
your Acorn on your behalf. That enables background payment receipt and convenient
access without asking you to manage private keys each day. It also means choosing
an operator you trust with significant responsibility.

## What that trust means

Custody does not make the operator unable to access your wallet. OakGate protects
stored recovery material with encryption, but the running service can use it.
An operator with sufficient access—or someone who compromises that access—could
read private information or exercise wallet authority. Encryption at rest does
not remove this trust.

A responsible provider must protect your information, explain its use and
retention, maintain reliable recovery and backups, and make access and revocation
choices understandable. You should know who operates your home instance, how to
contact them, and what happens if their service becomes unavailable.

OakGate is in active development. Successful demonstrations and automated tests
are not an independent security audit or an enterprise certification. Use small
test balances and non-critical records until your deployment has been reviewed
for its intended use.

## The same Acorn, with a path to independence

OakGate uses the same safebox-acorn foundation as independent clients. Funds and
records do not become an OakGate-only format simply because you choose custody.
Google is an optional login provider, not your Acorn's cryptographic identity.
Community-operated infrastructure and replaceable services remain Mainstay
principles.

**Available today:** you can request your recovery phrase, bootstrap relay and
recovery mode after fresh authentication. Keep a secure independent copy before
you need it. Disclosure alone does not stop custody or remove the provider's
access. Restoring all capabilities also depends on the relevant relay, storage
and mint state; a phrase alone is not a guarantee of complete recovery.

**Our commitment:** you should be able to end the custodial relationship and
continue independently. The complete **Go Independent** workflow remains planned.
It must verify independent recovery, handle pending payments safely, stop
background activity, revoke delegated access and remove retained custody data
without destroying your external Acorn.

Providers must be honest about deletion: backups may have disclosed retention
periods, and no service can prove that every historical copy of a secret was
erased. Giving you recovery information is not proof that only you now control
it. See [Go Independent](004-go-independent.md) for the intended process and its
remaining work.

## Everyday tools, clear boundaries

A paired card or POS terminal can make everyday interactions easier, but its
permissions matter. Inexpensive NFC cards can be copied. A PIN protects only the
flows that check it; some current payment and record-presentation flows rely on
the card credential without a PIN. Review the [card trust model](029-nfc-card-trust.md)
and revoke a lost or compromised card promptly.

Presenting a record shares information with its recipient. Closing the display
cannot erase a copy they made. An OpenETR anchor identifies signed evidence and
a publisher's statement; it does not independently establish that the statement
is true or that the publisher is a recognized authority.

## Read the full policy

This brief explains the user-facing choices. The repository's
[Security and Custodial Trust policy (SECURITY.md)](https://github.com/trbouma/oakgate/blob/main/SECURITY.md)
sets out vulnerability reporting, technical boundaries, residual risks and
operator responsibilities in more detail.

For current capabilities and remaining acceptance checks, see
[Project status](project-status.md). For how these choices fit the wider
architecture, see [Mainstay principles](010-mainstay-principles.md).

## Connected homes, distinct responsibilities

A participating OakGate home can accept signed POS requests from another home,
or contact a foreign card's issuer. The issuer retains the wallet's private keys
and checks card validity and its acceptance policy. The merchant's home receives
the operation result, including any explicitly requested balances or records.
These homes do not share an account session or custody database.

Current card-based POS payments and disclosure do not require a PIN. A copied
card may therefore be usable through an accepted home. Signatures verify the
service, not the physical tag or independent holder consent. Revocation and the
issuer's optional allowlist remain important choices. See
[the cross-home trust model](039-cross-home-pos.md#trust-and-holder-agency).

## Comparing card capabilities

See the [card capabilities policy brief](card-capabilities-policy-brief.md) for a
comparison with credit cards, debit cards and government IDs, including the
distinction between current features, earlier demonstrations and planned integration.
