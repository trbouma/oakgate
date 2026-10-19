# Clear payments

OakGate users can send a Clear balance to a compatible payment address and
receive Clear transfers while signed out. This uses the same Acorn transfer
protocol as Safebox Web. OakGate's custody model allows the inbox worker to
accept transfers without waiting for the recipient to open their wallet.

## Sending

Choose Send beside a Clear balance, or select a Clear asset on the Send payment
page. Enter the recipient address, a whole-unit amount, and an optional comment.
Review shows the friendly asset name and units; expandable asset details identify
the exact issuing mint and protocol unit. Assets from different mints remain
separate even if their friendly names match.

OakGate checks the recipient's NIP-05 directory for `clear-token-transfer`,
`nip59`, and kind `7379` support, along with a usable approved relay. Optional
recipient unit restrictions are respected. Clear payments never fall back to
Lightning or cash. No payment is made until confirmation.

The adapter calls Acorn's `send_clear_transfer` with the selected mint, unit,
amount and recipient. Acorn handles proof selection, encryption, publication and
native Clear history through Stroma. OakGate uses the existing encrypted outgoing
journal and owner lease to prevent duplicate confirmation. An uncertain send is
not automatically retried; it requires review before another send.

## Automatic receiving

OakGate advertises Clear capabilities for active handles alongside existing cash
capabilities. It does not advertise a mint allowlist: the policy remains to trust
any mint from which Acorn can successfully receive.

The background worker calls `sweep_clear_transfers`, reads pending receipts with
`get_clear_receipts`, and calls `accept_pending_clear_receipt`. Only Acorn handles
tokens, swaps, proof persistence, user Nostr events and Clear transaction history.
Its receipt and history checks handle retries; OakGate adds no separate credit
entry. Clear transfers are not added to the cash transaction page.

The worker processes a bounded batch of pending receipts on each pass. A failed
mint remains pending for another attempt, and a cash-receiving failure does not
prevent the Clear phase. Settlement does not require a browser or Redis session.
Sending to another local OakGate handle wakes that recipient's inbox for prompt
processing. External transfers are found through regular polling, normally every
30 seconds. Queue load and relay/mint availability still determine settlement
time; delivery success alone is not proof of redemption. Refresh Balances after
settlement to see the spendable amount.

## Configuration and deployment

```dotenv
OAKGATE_ECASH_RECEIVE_ENABLED=true
OAKGATE_CLEAR_RECEIVE_ENABLED=true
OAKGATE_ECASH_POLL_SECONDS=30
```

Both receive switches default to true. The ecash switch controls the shared inbox
worker; setting it to false disables both cash and Clear background receiving.
The Clear switch disables only Clear receipt processing and capability discovery.
Relay selection continues to use `OAKGATE_ALLOWED_RELAYS`; it is separate from
mint acceptance. Existing bootstrap mint settings do not restrict Clear issuers.

No new dependency or Acorn source change is required. After committing and
pushing, deploy with `./refresh-app.sh`. Test a small Clear transfer with the
recipient signed out, then check the recipient balance and native Acorn history.
Automated tests use fake mint/relay responses and do not move real funds.

Existing custody database and encryption-key backup requirements still apply.
Incoming receipts, proofs and Clear history remain in Acorn's relay-backed state;
Redis is not their durable store. Each Clear balance opens its native Acorn transaction history, showing the latest
10 entries for that exact mint and unit. The balance links back home. A pending-receipt
page is not included.

## Route scope guard

OakGate follows Safebox Web's advisory route classification. Loopback,
localhost, single-label container names, malformed URLs, and ordinary public
HTTP routes are instance-only. Private/link-local IPs and `.local`, `.lan`,
`.internal`, or `.home.arpa` names are local-network routes. Other well-formed
HTTPS routes are classified across-networks. This is not a DNS lookup or proof
that a recipient can reach or redeem at the mint.

Instance-only Clear balances can be sent only to a connected, active recipient
in this OakGate instance. External sends are rejected before review, without
exporting value or falling back to Lightning. Confirmation repeats the check,
including for older prepared payments, and verifies that the local handle still
maps to the reviewed Acorn and relay. A shared domain suffix or relay does not
establish shared-instance membership. OakGate does not yet consume Mainstay's
cross-service deployment context.

Like Safebox Web, local-network routes remain eligible for external transfers;
the classification alone cannot establish shared-network access. Capability,
unit, relay and amount checks continue to apply. Receiving and redemption retain
the existing Acorn policy: accept any mint from which Acorn can successfully
receive. No mint allowlist is added.
