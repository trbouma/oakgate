# Receipts and wallet messaging

OakGate calls its received wallet messages **Receipts**, with the heading
**Your Receipts**. This compact inbox includes receipts for record presentations;
the compose form is hidden. The underlying transport remains private messaging
between Acorn wallets. Receipt wording does not make every message proof of a
completed payment or a complete presentation audit. The sender key is the Acorn key, never the social npub in
Preferences. Google and Keycloak authenticate access to OakGate; they are not
message identities.

## Resolution and private-key boundary

External recipient addresses require a version-1 `safebox.json` entry advertising
`safebox-wallet-message` with NIP-17 / kind 14. Acorn owns the public resolver;
OakGate retains only operator-approved relay routes. Add a recipient's public
relay to the existing approved bootstrap-relay configuration when needed.
Local addresses resolve directly to their registered Acorn and approved relay.
NIP-05 is never a fallback, including for older instances. Older recipients must
publish the wallet messaging capability before address-based delivery works.

The adapter in `app/wallets.py` invokes Acorn `send_wallet_message` and
`get_wallet_messages`. Acorn owns message formatting, signing, encryption,
decryption, authenticated reading and publication. Sending uses Stroma's
`GiftWrap` with `jitter_seconds=0`, kind 14 rumour and kind 1059 outer event.
The `safebox.dm` version-1 envelope interoperates with Safebox Web. Its existing
Acorn methods remain unchanged.

The inbox always shows the authenticated sender wallet key. Claimed addresses
are marked verified, mismatched or unverified using wallet discovery, never the
social cache. Verification describes the current address association, not a
permanent identity guarantee. Payment-shaped messages are excluded. Message
content is escaped text and cannot trigger payments or other actions.

## Delivery and storage

The inbox shows up to 50 recent messages from Acorn's bounded relay query. It is
not a complete archive or a sent-message history. Refresh to check for new
messages. Relay publication does not prove delivery to a device or reading.

CSRF and origin checks protect sends. The existing busy indicator disables
repeat clicks. A ten-minute form token is bound to the authenticated owner; its
hash is consumed in the application database before sending. This blocks replay across app workers
and restarts, including when the delivery result is uncertain. Consumed hashes
are retained for one day and pruned on subsequent sends. No message plaintext,
recipient, or new user key is stored in that table. The wallet operation lease
prevents concurrent submissions. An uncertain send is never automatically retried.

## Deploy in order

1. Commit and push the new Safebox Acorn API to `main`.
2. In OakGate run `poetry update safebox-acorn` and commit the updated lockfile.
3. Rebuild the app with `./refresh-app.sh` and confirm the messaging capability
   appears in a real handle's `safebox.json` response.
4. Test a small text message in both directions with Safebox Web.

The source change is not yet in OakGate's published dependency lock. Older locked
Acorn versions leave the page unavailable and omit the messaging capability;
they do not silently use older social-address methods. Source-override tests are
integration checks only and do not establish deployment readiness. No Stroma
change is needed: the locked version already exposes the zero-jitter GiftWrap.
