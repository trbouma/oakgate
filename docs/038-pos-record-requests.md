# POS record requests

The **Check a Record** tab lets an activated terminal request a `whoami`, `myinfo` or `emergency` record.
This is a presentation for viewing, not a record transfer or a payment instruction.
`whoami` is the default. `myinfo` holds additional information the wallet holder
chooses to present beyond their `whoami` record. All three labels are explicitly
enabled in the dropdown and server allowlist.

## Prepare the records in your wallet

Create a record labeled **whoami** with the information you want to use to
introduce yourself. You may attach an image, such as a photo, for the terminal to
preview. Create **myinfo** separately for additional information you wish to
present. The terminal requests one selected record at a time; choosing `myinfo`
does not automatically disclose `whoami` as well.

Keep only information you intend to present in these records. NFC presentation
does not currently require a PIN. The card points to the Acorn; record contents
and attachments are not written onto the card.

For an illustrated example, see [From a wallet to a card](user-experiences/card-pairing-and-payments.md#a-record-with-the-same-card)
and [One wallet, several counters](user-experiences/one-wallet-several-counters.md#one-terminal-for-payments-and-record-checks).

## Operator experience

1. Select **whoami**, **myinfo** or **emergency**, then **Create Request**. A new request clears the previous
   displayed record and invalidates the previous request on this terminal.
2. The holder scans the QR using their OakGate wallet or phone camera. The wallet
   displays the terminal name and requested label and asks for approval. A holder
   who is signed out signs in in another tab and returns to the request.
3. Alternatively, on a compatible secure NFC browser, choose **Request by NFC**
   and ask the holder to tap their valid, activated OakGate card. This first
   iteration supports same-home cards only and does not ask for a PIN.
4. When ready, choose **Present Record**. Acorn retrieves the presentation for
   display, without importing it into the merchant's wallet.
5. Create a new request or select **Stop Request** to remove the display.

Requests last two minutes. The display also clears on expiry, when leaving the
record tab, or when the browser becomes hidden. Late responses cannot restore a
cleared display. Switching back to Point of Sale does not change a payment journal.

## Record selection and verification

Labels are compared in lowercase: `whoami`, `WhoAmI` and `WHOAMI` match; `myinfo` and `MyInfo` also match. A missing
record or multiple matching labels produces an unavailable result rather than
selecting an arbitrary record. Only user records returned through Acorn's existing
record-listing methods are eligible; the terminal cannot request internal wallet
records or arbitrary labels.

The existing Acorn public-only presentation method creates a short-lived
presentation. Record text and JSON are displayed as text, never executable HTML.
Raster image attachments up to 5 MiB are previewed; other attachments show an
unsupported-preview notice. OpenETR checks use the computed attachment digest and
show the ruleset result and details. A retrieval failure is not evidence that no
anchor exists. A successful presentation or an OpenETR result alone does not prove
that a person's identity or the claims in a record are true.

## Authorization and privacy

Every terminal operation uses the existing browser-bound signed challenge and
terminal session. Request state is bound to the terminal and merchant wallet;
one terminal cannot retrieve another terminal's request. QR approval requires an
authenticated wallet session and CSRF validation. The QR contains a random invitation
in its URL fragment, not a record, wallet key or external callback destination.
OakGate's scanner recognizes this same-home request URL directly.

An NFC tap authorizes disclosure of the selected `whoami` or `myinfo` record in this iteration.
This is an additional bearer-card capability: holders should keep only information
they intend to present in that record. A lost or copied card can disclose that
record until revoked. The card and wallet are checked again after preparation and
before retrieval, including cached retrieval. Stronger card consent/PIN policy can
be introduced later; it is not implied by the current implementation.

An atomic one-use claim prevents two QR approvals or NFC taps from replacing the
presenter. Expired, cancelled or superseded requests cannot deliver late results.
No request can authorize spending or change the user's original record.

Request metadata lives briefly in the configured Redis/session store. Presentation
descriptors, NFC credentials needed for revalidation and retrieved record content
are encrypted with the custody envelope before temporary storage and expire with
the request. Browser results are not persisted in local or session storage. The POS
service receives only the display fields, never an Acorn private key or descriptor.
All user-key operations remain in Acorn, and OpenETR uses the existing Stroma path.
Clearing a display cannot erase screenshots or information already seen; expiry of
a presentation is not a claim of physical deletion of all media-server copies.

## Deployment and checks

Rebuild and refresh **both the OakGate app and POS service**. There are no new
environment variables or database migrations. Existing activated terminals do
not need to be re-provisioned; reload the terminal after deploying both services. The existing record transfer server,
allowed storage servers and OpenETR settings apply. Redis must be available for
production; losing ephemeral request state requires a new request, not recovery of
a payment or a change to the user's Acorn.

Test an ordinary QR approval and NFC tap on the actual terminal. Also test a missing
record, a revoked card, expiry and starting a new request while a previous lookup
is pending. Automated tests cover these authorization and stale-response boundaries;
the operator has reported successful NFC presentation on the deployed terminal.
Repeat the QR, NFC and expiry checks on each target deployment and browser.


## Emergency record and contact notification

Create a record labeled `emergency` (case-insensitive), containing only information
you intend to disclose without a PIN. Add exactly one `contact:<safebox address>`
directive, for example on its own line:

```text
contact:alex@wallet.example
```

A JSON string containing the same directive is also accepted. The address must
stand alone without trailing punctuation. Missing, invalid or multiple directives
skip notification. Attachments are not searched for contact instructions.

After an emergency presentation is acquired and authorized for display, OakGate
attempts one access notice from the holder's Acorn through the existing wallet
messaging adapter and Stroma giftwrap. The notice contains the access time and
request reference, not record contents, medical details or attachments. It may
identify the sender by their configured wallet handle. Creating a request, polling
status or preparing a presentation alone does not send a notice. A lost response
can mean an access notice was published even if the screen did not render.

Contact resolution uses the existing same-home wallet lookup or `safebox.json`
with the approved relay policy. There is no NIP-05/social-key fallback. The address
may also be NIP-05 compliant; NIP-05 alone does not make it a wallet destination.

A durable, one-use `wallet_message_submissions` entry is consumed before the
notification attempt. Concurrent/repeated presentation calls do not send again for
that request, including after uncertain publication. There is no automatic retry:
a crash, busy wallet or network failure may leave a notice unsent. A new request
is a new access and can generate another notice. This is best-effort notification,
not a reliable emergency alarm. Publication does not confirm delivery or reading.
The POS still displays the record if notification fails, with a separate status.
Notification lookup/publication has a bounded wait of up to about 21 seconds.

Rebuild the app and POS to add the `emergency` choice. No new environment variables,
database migration or terminal enrollment are required. There is no email integration.
See [A day at the beach](user-experiences/a-day-at-the-beach.md) for the illustrated story.
