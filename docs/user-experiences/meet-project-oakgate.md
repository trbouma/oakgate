---
title: Meet Project OakGate
description: The custodial version of Safebox makes everyday use familiar while keeping safebox-acorn at its core and independence in its design.
---

# Meet Project OakGate

[![Project OakGate wraps familiar sign-in, everyday Funds and Records, and managed recovery around safebox-acorn. The same Acorn core supports managed use and a path to individual independence. Nostr, Cashu and Blossom work in the background. Recovery disclosure is available; the complete Go Independent workflow is planned.](../assets/user-experiences/meet-project-oakgate.png)](../assets/user-experiences/meet-project-oakgate.png){ .oakgate-experience-image }

[Open the full-size infographic](../assets/user-experiences/meet-project-oakgate.png){ .md-button }

*The illustration explains the product direction. Screens are illustrative; the complete Go Independent workflow is planned.*

Leah wants somewhere to receive a payment, hold community credits, and keep a
record someone has shared with her. She is comfortable signing into a website.
Managing a private key and choosing a relay would be unfamiliar first steps.

**Project OakGate is the custodial version of Safebox.** It gives Leah a familiar
way to use a safebox, with a provider taking responsibility for holding her
recovery material and operating her wallet on her behalf. Underneath that
experience is **safebox-acorn**, the same core component used by Safebox Web.

*Leah is an illustrative user. Her story introduces the experience and the
choice of responsibility behind it.*

## Start with something familiar

Leah opens OakGate and signs in using one of the options offered by her provider,
such as Google or an email-and-password account. She can create a new Acorn or
connect an existing one using its recovery information.

Once connected, the everyday interface is straightforward: **Funds**, **Records**
and **Messages**. She has a receipt address that looks like an email address.
She can show a payment request, receive Cash or Clear, and open a shared record.
She does not need to understand the protocols before using these features.

OakGate's custody also allows it to receive and settle supported payments while
Leah is away. She does not have to keep her browser open for every incoming
payment to be processed.

## A provider takes responsibility

When Leah forgets her sign-in password, the configured identity provider offers
its account-recovery process. Keycloak connects those sign-in options to OakGate;
Google is one possible provider, not the identity of her underlying Acorn.

OakGate separately retains encrypted wallet secrets and recovery information.
Account recovery helps Leah regain access to the service. Acorn recovery material
serves a different purpose: recovering the underlying safebox.

This convenience involves trust. The operator can use her wallet on her behalf
and must protect its secrets, maintain backups, and keep the service available.
Encryption at rest does not make OakGate non-custodial. Leah chooses a provider
she is willing to trust with those responsibilities.

## The same Acorn underneath

OakGate adds a custodial layer around **safebox-acorn**. Acorn still performs the
wallet operations, including operations that use the user's private key.
OakGate coordinates access and background work without inventing a different
wallet architecture.

Safebox Web uses that shared foundation with a different boundary: it does not
persist the user's private key server-side, and uses it during an authenticated
session. OakGate intentionally retains the material needed to operate the wallet
for the user. The distinction is who takes responsibility for custody.

The supporting infrastructure stays mostly out of Leah's way:

- **Nostr relays** carry wallet messages and record events.
- **Cashu** supports the token operations behind Cash and Clear funds. Lightning
  provides a payment route for Cash when an invoice is used.
- **Blossom** supports record attachments and media.

These components can be operated by communities and service providers. They are
shared foundations for the experience, rather than concepts Leah must learn to
complete her first payment.

## Independence remains part of the design

Later, Leah may want to take responsibility for her own safebox. The intention
is that choosing convenience today should preserve a practical path to
independence through Acorn.

Today, OakGate can disclose her recovery phrase, bootstrap relay and recovery
mode after fresh authentication. Those details belong together and must be kept
private. Viewing them does not end custody or remove OakGate's access.

**Go Independent** is the planned next step: help Leah verify independent
recovery, safely finish outstanding activity, and then end custody and remove
OakGate's retained information and delegated access. The complete workflow is
not available yet. Recovery also depends on the relevant relay, mint and media
state being available; a phrase alone is not a promise that every asset or
attachment can be restored.

Even after a future departure, a provider cannot prove that no historical copy
of a secret remains. The process must explain retention and deletion limits
honestly.

For Leah, the promise guiding Project OakGate is simple: **a welcoming place to
start, with the same Acorn foundation supporting a path to taking responsibility
herself.**

[Try the card experience](card-pairing-and-payments.md) ·
[Explore a merchant's terminals](one-wallet-several-counters.md) ·
[Custody models](../006-custody-models.md) ·
[Recovery disclosure today](../016-recovery-disclosure.md) ·
[Go Independent design](../004-go-independent.md)
