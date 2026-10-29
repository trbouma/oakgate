---
title: Comparing OakGate cards with payment and ID cards
description: A policy brief comparing payment, record and sign-in capabilities, with implementation status and trust distinctions.
---

# Comparing OakGate cards with payment and ID cards

*Policy brief · 28 October 2026*

**OakGate brings payments, records and account access together through a low-cost
card connected to a trusted custodial wallet.** Its value is the breadth of that
experience: a person can pay, receive funds, receive records and show a record
without carrying a phone. That breadth does not make the card equivalent to a bank card or a
high-assurance government identity credential.

This brief compares each card **together with its supporting service**, not the
plastic alone. For OakGate, that includes the home instance, Acorn and participating
terminals. For payment cards, it includes the issuer and payment network. Government
IDs vary substantially; the table distinguishes conventional identification from
electronic ID systems where relevant.

## Capability comparison

**Current** means implemented in OakGate, subject to enrollment, configuration and
participating services. The project owner has confirmed that NFC record sharing
works in deployment. Cross-home support is implemented and covered by automated
tests; live interoperability should still be checked between participating homes.

| User action | OakGate NFC card | Credit card | Debit card | Government ID card |
| --- | --- | --- | --- | --- |
| **Receive a payment** | **Current.** A payer reads the card to resolve its wallet and sends Everyday Funds or supported Community Credits. | **Limited / issuer-dependent.** Refunds and account credits are supported; general incoming transfers are not a universal credit-card function. | **Supported where eligible.** Refunds and push-to-card services can credit the linked account. | **Not a standard ID function.** It may identify someone eligible for a payment, but delivery requires a payment service. |
| **Send a payment** | **Current.** Tap to authorize payment from the linked Acorn at a participating POS, using supported funds or credits. | **Core function.** Pay merchants using an issuer-provided credit facility; transfers depend on the service. | **Core function.** Pay merchants from the linked account; transfers depend on the service. | **Not a standard ID function.** Combined ID/payment programs require additional payment capabilities. |
| **Present a record** | **Current.** Present supported records such as membership, a pass, benefits or emergency information; the POS can show attachments and OpenETR information. | **Not a general record wallet.** Card/account details or issuer benefits do not provide arbitrary record presentation. | **Not a general record wallet.** Payment credentials do not normally present independent membership, health or other records. | **Core identity function.** Present issuer-defined identity or entitlement information. Electronic disclosure depends on the ID system. |
| **Receive a record** | **Current.** An issuer scans a paired card and confirms delivery of a record to its linked Acorn; the holder does not need a phone. New shares use category paths with recipient-specific sharing fingerprints, and existing labels are protected. Cross-home delivery is supported. | **Not a standard card function.** Statements and receipts in an issuer app are separate services. | **Not a standard card function.** Statements and receipts in a banking app are separate services. | **Not generally an open record inbox.** Issuer updates or linked document services are system-specific. |
| **Sign in** | **Current with explicit enrollment.** The existing Keycloak card-login flow supports a server-verified PIN. A paired card is not automatically enrolled for login. | **Service-specific.** Some issuer authentication schemes use card credentials or readers; general-purpose sign-in is not universal. | **Service-specific.** Some banking authentication schemes use the card; broader sign-in requires integration. | **Supported by some electronic IDs.** For example, Estonian eID supports online authentication. A conventional photo ID alone does not provide digital sign-in. |

Credit and debit cards differ in the source of spending power: credit involves
borrowing, while debit generally draws on an existing account. See the
[CFPB comparison](https://www.consumerfinance.gov/ask-cfpb/how-are-prepaid-cards-debit-cards-and-credit-cards-different-en-433/).
Receiving money should not be scored as a blanket “no” for either category:
credit-card accounts can receive refunds and other credits, and eligible debit
cards can receive transfers through services such as Visa Direct. See
[CFPB on credit balances](https://www.consumerfinance.gov/ask-cfpb/what-is-a-credit-balance-on-my-credit-card-bill-en-42/)
and [Visa Direct capabilities](https://www.visa.co.uk/supporting-info/visa-direct/visa-direct-faq.html).

Government electronic IDs should likewise not be reduced to printed photo cards.
Estonia's Information System Authority describes card-based online authentication
and digital signing, including support for several European eID cards. See
[RIA's Web eID description](https://www.ria.ee/en/state-information-system/electronic-identity-eid-and-trust-services/digidoc-applications-and-web).
The comparison is about typical product roles, not an exhaustive inventory of
special-purpose or combined cards in every jurisdiction.

## What makes OakGate different

A single paired credential can connect several everyday activities to the same
Acorn. A community member could receive program credits, spend them at a
participating outlet, and present a membership record using a card, bracelet or
pendant. The record need not be a statement of legal identity: `member` can express
“I belong,” while `pass` can express “I have access.” What a verifier accepts still
depends on the record, its issuer and the program's policy.

The physical card contains an opaque credential and issuer-routing information.
**Funds, records and the Acorn private key are not stored on the tag.** The home
instance performs authorized wallet operations through Acorn. Record receipt
means delivery into the associated wallet—not writing a health document or
membership file onto the card.

OakGate now supports both QR sharing and **card-directed record issuance**. The
sender opens a record, chooses Share to NFC Card, scans the recipient's card and
confirms the destination. New shares use the same category-and-fingerprint convention as QR
sharing—for example, `member/<digest>`—with a compact fingerprint shown before
confirmation. Existing records are not overwritten. An uncertain delivery is
checked rather than automatically repeated. The recipient can later present or
manage the received record through their wallet and supported card flows.

The [enrolled Keycloak sign-in flow](027-keycloak-nfc-login.md) is also implemented.
Deployments must enable and test it explicitly.

## Capability and security assurance are different questions

OakGate deliberately supports inexpensive, copyable NFC memory tags. They are
not cryptographic smart cards or FIDO2 authenticators. The custodial home can
revoke a credential and enforce server-side policy, but encryption of the tag
payload does not stop someone copying that payload.

Current card-based payments, balance lookup, record presentation and record
receipt do not prompt for a PIN. Record issuance requires the sender to confirm
after scanning; possession of a copied card credential could nevertheless allow
unwanted records to be sent to the linked wallet. Login requires separate enrollment and uses the configured PIN policy;
an explicitly enabled card-only policy increases the consequences of a copied
card. A four-digit PIN with server-side controls is an additional protection,
not a claim of equivalence to a hardware-backed government eID.

Record presentation also does not by itself establish government-recognized
identity. OpenETR can show a publisher's signed statement and verification
information; the relying party must decide whether that publisher and statement
are appropriate for the decision being made.

These are online, participating-service experiences. The holder can leave their
phone behind, but the terminal and supporting services still require connectivity.
Cross-home acceptance is governed by the participating instances, supported assets
and configured policies; it is not universal payment-network acceptance.

## Policy implications

For community programs, OakGate's opportunity is a consistent interface for funds
and records with a form factor that does not require personal smartphone ownership.
Operators should define which actions each credential can authorize, how lost
credentials are revoked, how sensitive records are protected, and what happens
when connectivity or a home service is unavailable.

User agency remains the governing principle. Custody is a choice to rely on an
operator, not a transfer of the user's claim to their funds and records. OakGate
retains the shared Acorn architecture and recovery-disclosure capability; the full
**Go Independent** departure and deletion workflow remains planned. A comparison
of card features should not imply that this workflow is already complete, or that
banking protections and official-ID recognition automatically apply to OakGate.

[Read the Security Statement](security-statement.md){ .md-button }
[Card trust and security](029-nfc-card-trust.md){ .md-button }
[Cross-home wallets, cards and POS](039-cross-home-pos.md){ .md-button }
[Current project status](project-status.md){ .md-button }

See [Share records to NFC cards](040-nfc-record-sharing.md) for the flow, consent model and uncertain-delivery handling.
