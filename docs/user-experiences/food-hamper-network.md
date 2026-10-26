---
title: A hamper. A choice. A little dignity.
description: A city-backed food hamper credit connects aid workers, families and participating food banks.
---

# A hamper. A choice. A little dignity.

[![Six-panel comic: the city funds food hamper credits, aid workers distribute them to families, a parent pays at a food bank, and the food bank redeems collected credits with the city.](../assets/user-experiences/food-hamper-network.png)](../assets/user-experiences/food-hamper-network.png){ .oakgate-experience-image }

[Open the full-size comic](../assets/user-experiences/food-hamper-network.png){ .md-button }

*An illustrative program and fictional characters, not an announcement of a live
municipal service. The story describes the city's proposed operating commitments;
the implementation notes below distinguish those commitments from software guarantees.*

## One city, many places to turn

The city already helps fund food banks and not-for-profit agencies. Its next step
is to connect them into one coordinated food support program, while letting each
organization keep serving its own neighbourhood.

The city commits funding for a **food hamper credit**: one credit entitles its
holder to a standard hamper at a participating food bank, with an agreed funding
value of approximately **$25 in local currency**. The credit is a Clear asset for
this particular program. It is not a bitcoin balance or a promise that every shop
will accept it.

“We'll back the credits,” the city coordinator tells the partner agencies.
“You help them reach the people who need them.”

The city arranges issuance through its Clear mint and treasury process. Allocated
credits move into the wallets of authorized aid workers and agencies. Issuance
and distribution are kept within the program's approved funding.

## Support without another story at the counter

Sam is raising a child and has had a difficult month. At a neighbourhood agency,
aid worker Jo listens, establishes eligibility under the program's rules and
provides a food hamper credit to Sam's wallet.

Jo explains which food banks participate and how to use it. Sam can pay with the
wallet on a phone, or with an already provisioned NFC card at a compatible
terminal. The card is a way to use the wallet; it does not need to carry a name,
a case file or a description of why Sam received support.

“This is yours to use,” Jo says. “Choose a participating food bank that works
for you.”

Sam does not need Jo to accompany them. At the checkout, the credit is enough
under this program's rules. The personal conversation stays with the agency.

## “One hamper, please.”

The next day, Sam visits a participating food bank on the way home from school.
The counter looks ordinary: bags of fresh produce, pantry staples and a small
Android phone running the OakGate point-of-sale app.

The volunteer selects **Food Hamper**, enters **1** and creates a Clear payment
request. Sam scans it with the wallet or taps the NFC card when invited.

“One hamper, please.”

“Of course.”

The terminal shows the payment's progress. Once receipt is confirmed according
to the food bank's checkout procedure, the volunteer hands over the hamper.
There is no case-history questionnaire at the counter and no need to present a
`whoami`, `myinfo` or other personal record to pay.

For Sam, the experience is paying with something they hold—much like handing over
cash. The food bank is accepting a city-backed program credit, not deciding Sam's
eligibility again in front of a queue.

## The food bank gets the means to keep helping

The credits collected at the counter arrive in a wallet controlled by the food
bank's treasurer. Several counters can collect into that wallet, each using its
own activated terminal. Staff do not need the treasurer's account login to
accept payments.

At the agreed settlement interval, the treasurer submits collected credits for
redemption with the city. The city checks the claim under the program's rules,
accounts for the surrendered credits so they cannot be reimbursed twice, and
transfers the agreed funds to the food bank through its normal funding process.

The food bank uses that money to replenish supplies and continue the program.
The financial backing comes from the city's commitment and budget, not from the
phone or the token format.

**City funding → aid-worker allocation → family purchase → food-bank collection
→ city reimbursement.**

## Privacy is part of the service

The intended experience protects dignity by separating the eligibility
conversation from the purchase. The participating food bank needs to accept the
right credit; it does not need the family's personal history attached to it.
The city can organize reimbursement around participating organizations and
redeemed credits rather than asking families to retell their circumstances at
every counter.

This is a privacy objective, not a claim of complete anonymity. OakGate is
custodial: its operator holds wallet keys and can have access to account and
transaction information. Agencies may hold eligibility records, and services can
retain operational metadata. A real deployment must decide who may see that
information, how long it is retained and how eligibility records are kept apart
from payment records. Clear payments alone do not eliminate these responsibilities.

## What needs to be agreed before launch

OakGate already supplies the wallet, Clear payment and simple POS building blocks.
The city and participating organizations still need to establish the program:

- **Backing and value:** the funded issuance limit, what one hamper includes and
  the reimbursement rate and timing. “Approximately $25” describes this example;
  the actual agreement must be explicit.
- **Participation:** which food banks accept credits and which treasurers may
  redeem them. In this story, only participating food banks offer goods for these
  credits and qualify for city reimbursement. Current transferable Clear credits
  do not, by themselves, cryptographically prevent transfers to other wallets.
- **Distribution:** who may allocate credits, how eligibility is assessed and how
  lost cards or accounts are supported without humiliating recipients.
- **Settlement:** how credits are surrendered and retired or otherwise accounted
  for exactly once, how claims are reconciled, and how the city pays the food bank.
  This article does not add an automated municipal reimbursement workflow.
- **Privacy and service:** what each organization actually needs to know, along
  with training, connectivity and a fallback procedure when a terminal is offline.

The visible experience can stay simple. Acorn performs wallet operations, Clear
provides the program's credits, and the underlying protocols work quietly behind
the terminal. The point is a connected community service where support reaches
families and food banks can keep their doors open.

[One wallet, several counters](one-wallet-several-counters.md) ·
[Explore User Experiences](index.md)
