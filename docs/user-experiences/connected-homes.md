---
title: Independent homes, one connected experience
description: How an OakGate app, card and POS work together across independent homes while custody stays at home.
---

# Independent homes. One connected experience.

[![An OakGate wallet and card belong to Home A. A merchant's POS belongs to Home B. Home B sends signed requests to Home A and receives verified results. Both homes keep separate databases and keys; Acorn performs wallet operations. Nostr, Cashu and Blossom work underneath.](../assets/user-experiences/connected-homes.png)](../assets/user-experiences/connected-homes.png){ .oakgate-experience-image }

[Open the full-size infographic](../assets/user-experiences/connected-homes.png){ .md-button }

*An illustrated architecture, not a product screenshot or a promise of universal
acceptance. Participating homes verify one another; the issuing home must be online.*

## One familiar tap at a new counter

Maya uses a community-operated OakGate home for her Everyday Funds, Community
Credits and records. Her app and card belong to that home. At a market across
town, the merchant has chosen a different OakGate operator for his wallet and POS.

He creates a request, and Maya taps her card. She does not need to register with
the merchant's home, move her wallet there or learn a new payment interface.
The terminal knows how to reach the issuer encoded on her card. Its own home
verifies that issuer's public key and sends a signed request. Maya's home checks
the card and policy, then carries out the operation through her Acorn.

For Maya and the merchant, this is one familiar experience. Underneath, two
independent operators are cooperating. The merchant's POS follows its receipt
status, while the issuer keeps the sending operation and recovery state.

## Funds and records travel through the same experience

At another participating counter, Maya can confirm a balance lookup or tap to
show a membership record. The POS's **Check a Record** tab can request a category
such as `member` or `benefits`. If several records match, staff choose which to
display. If only one matches, the flow stays simple. Images, PDFs and available
OpenETR information appear using the same presentation interface.

Her private keys never travel to the merchant. Records remain in her Acorn,
although any record or balance disclosed to the merchant can be seen and retained
by that party. A presentation receipt can appear in her wallet identifying the
remote home and its terminal. That receipt is best-effort, not a guaranteed audit trail.

## A network of homes, not one central account

Each home has its own service identity, users, custody data and operating policy.
The public key is the issuer identity; the card's domain supplies the contact path.
A changed key fails verification. The current implementation does not automatically
relocate cards when an issuer changes domains.

Homes can exchange roles: the merchant's home can issue cards that another home
accepts. Each issuer decides which signed requests to permit. Compatible credit
assets still matter; a credit issued for one program is not automatically spendable
at every counter. A home can limit participation to known service identities.

## Quietly working underneath

Acorn performs wallet and private-key operations. Stroma supplies the Nostr
operations used by the family. Nostr relays carry wallet messages and events;
Cashu supports funds and credit operations; Blossom serves record media. Explicit
Lightning invoices continue to use Lightning. These details stay out of the normal
tap-and-receive experience while remaining documented for operators.

## What this means today

Cross-home NFC payments, balances and record requests are implemented and covered
by automated tests with independent homes and keys. Actual deployments still need
live two-home acceptance checks. Both homes must be updated and reachable online.
Card issuance and login remain home-local. Wallet record QR approval works across participating homes. General satellite
support and the complete Go Independent departure workflow remain separate work.

Cards are inexpensive, copyable bearer credentials. POS payment and disclosure
currently do not prompt for a PIN; a valid copied card can be used through an
accepted home. Users can revoke cards, and operators can restrict participating
homes. Familiar interaction does not remove those trust choices.

[Read the operating model and deployment checklist](../039-cross-home-pos.md){ .md-button .md-button--primary }
[Understand the card trust model](../029-nfc-card-trust.md){ .md-button }

## Present with your phone instead

Maya can also open **Scan** in her own OakGate wallet and scan another home's POS
record request. Her wallet shows the terminal and its domain. She approves one
record, or selects which matching records to disclose, while staying signed in
at her own home. The other POS can then show those records with the same previews
and OpenETR information. Her private key stays with her home and all wallet-key
operations go through Acorn.

Use the OakGate wallet scanner for this flow: a native phone camera opens the
requesting home's website instead. Both homes must support the protocol and
accept each other's service identity. See [setup, trust and testing details](../039-cross-home-pos.md#wallet-qr-presentations-between-homes).
