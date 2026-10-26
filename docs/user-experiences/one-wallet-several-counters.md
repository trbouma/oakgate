---
title: One wallet, several counters
description: A small merchant turns affordable Android phones into individually revocable Cash and Clear payment terminals.
---

# One wallet, several counters

[![One merchant wallet connected to a shop counter, market stall and pop-up kiosk. Each affordable Android phone has its own activation key, accepts Cash or Clear over Wi-Fi or mobile data, and can be individually revoked without granting access to spend the merchant's funds.](../assets/user-experiences/one-wallet-several-counters.png)](../assets/user-experiences/one-wallet-several-counters.png){ .oakgate-experience-image }

[Open the full-size infographic](../assets/user-experiences/one-wallet-several-counters.png){ .md-button }

*Illustrated screens explain the experience; they are not exact application screenshots.*

Sam runs a small neighbourhood shop. On Saturdays, one colleague takes a stall
at the farmers' market while another sells at a nearby pop-up kiosk. Sam wants
all three counters to accept payments into the same merchant wallet, without
sharing his wallet login with the staff.

He already uses OakGate. For the counters, he buys three inexpensive Android
phones with current browser and security support. The shop phone uses Wi-Fi;
the market phones use mobile data or a reliable hotspot. Each opens the OakGate
POS website. None needs to hold his wallet private key.

*Sam and his shop are illustrative; this story follows the current POS workflow.*

## Three phones, one merchant wallet

In his wallet's Preferences, Sam creates a separate POS key for each device and
gives it a useful name: **Shop counter**, **Market stall**, and **Pop-up kiosk**.
On each terminal, he scans that terminal's activation QR code from his wallet.
Activation binds its credential to that browser.

The phones now show a payment keypad. Staff can choose Cash or an available
Clear asset, enter the amount, and display a request for the customer. They do
not need Sam's Google or email login, his recovery phrase, or access to his Funds
page. Sam keeps account administration on his own device.

## Cash at the shop, Clear at the market

At the shop, a customer buys a loaf of bread. The cashier selects Cash and enters
the price in local currency. OakGate shows the satoshi amount used to generate
the invoice. The customer scans the payment QR with a compatible wallet.

At the market, another customer pays using community-issued Clear credits. The
staff member selects the matching Clear balance and enters a whole-number amount
in that credit's units. Cash and Clear stay distinct: community credits are not
automatically converted to bitcoin or treated as having the same value.

The terminals show payment progress. **Payment detected** is an early indication;
final credit may follow in the background. Sam can check the resulting transactions
in his wallet. Receipts from all three locations go to that same Acorn.

For customers with a suitable OakGate card, an NFC-capable Android terminal can
also offer **Pay by NFC**. The current card-payment flow is limited to the same
OakGate home and does not request a payment PIN. QR receiving does not require NFC
hardware. [See the card experience](card-pairing-and-payments.md).

## A missing terminal does not mean a missing wallet

At closing time, the pop-up phone cannot be found. Sam opens Preferences on his
own phone, finds **Pop-up kiosk**, and revokes it. OakGate rejects further
authorized terminal operations from that device. The other two terminals remain
active, and the missing phone's credential does not authorize spending Sam's funds.

Revocation does not undo payments already submitted or invalidate every request
already copied by a customer. Those payments still need normal status checks and
settlement. Sam replaces the phone, creates a new terminal credential and activates
the new browser; he does not need to replace his wallet.

## His terminals, shared infrastructure

Sam has his own network of payment terminals: he chooses their names, who uses
them and when their access ends. He can use an existing OakGate home operated by
a provider; he does not need to run a separate home or server for each kiosk.

This is private in the sense of controlled terminal access. It is not a claim of
anonymous payments, private settlement rails or independence from the home operator.
OakGate coordinates custody and recovery, and Acorn performs wallet operations.
Nostr relays, Cashu and Lightning work underneath the relevant payment flows.
Blossom supports attachments and media in the wider record experience, rather
than being a required step in each checkout.

## What the protection means

The POS session does not contain Sam's custody keys or grant his account login
or general spending access. A lost device therefore has a smaller scope of access
than an unlocked merchant wallet. It should still be revoked promptly.

Today's POS also offers card issuance, confirmed card-balance lookups and
customer-card-authorized payment collection. Those are additional limited
capabilities: describing the device as completely harmless or incapable of any
data access would be misleading. Protect activation credentials, use a device
screen lock, and do not leave the merchant's signed-in wallet open on a staff POS.

Each device needs internet access and a reachable OakGate home. This is not an
offline checkout system. Clear receiving requires the intended asset to be
available to the merchant and compatible funding in the customer's wallet.
Current provisioning allows up to ten unrevoked terminals per wallet; larger
rollouts need operator review rather than a promise of unlimited devices.

[POS setup and activation](../024-pos-deployment.md) ·
[Card payment details](../025-pos-nfc-cards.md) ·
[Explore User Experiences](index.md)
