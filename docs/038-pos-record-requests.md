# POS record requests

The **Check a Record** tab lets an activated terminal request a `whoami`, `myinfo`, `emergency`, `health`, `benefits`, `member` or `pass` record.
This is a presentation for viewing, not a record transfer or a payment instruction.
`whoami` is the default. `myinfo` holds additional information the wallet holder
chooses to present beyond their `whoami` record. All seven labels are explicitly
enabled in the dropdown and server allowlist.

## Default record meanings and naming decision

| Label | Meaning | Typical content |
| --- | --- | --- |
| `whoami` | Introduce myself. | Identity information the holder chooses to present |
| `myinfo` | Share more about me. | Additional information, presented separately |
| `emergency` | Information when help is needed. | Emergency information and optional contact directive |
| `health` | Health information I choose to share. | A separate holder-created health record; no emergency-contact notification |
| `benefits` | Benefits information I choose to share. | A holder-provided benefits record; no automatic eligibility decision |
| `member` | **I belong.** | Membership or affiliation, without necessarily including a name or other identity details |
| `pass` | **I have access.** | Admission, access or another entitlement |

`pass` was chosen over `admission` because it is broader and does not imply
an event-specific workflow. `admission` is not an alias or a supported request
label. These are conventional record names, not new record types or schemas.
The dropdown starts with `whoami`; adding choices does not create records in a
wallet automatically.

A holder can update `pass` through the existing record editor to reflect its
current use. An attached original record can be backed by OpenETR verification:
the POS uses the same attachment digest lookup and verification display as other
presentations. This change adds no automatic entitlement decision. An operator
still interprets the record and verification evidence; OpenETR results alone do
not prove entitlement or the truth of every claim.

`member` can omit identifying content, and requesting it does not also request
`whoami`. This is a content choice, not an anonymity guarantee: existing wallet,
card, custody and presentation-receipt behaviour is unchanged. Selection is between whole records, not selective disclosure of fields inside a record.

Both choices use existing case-insensitive unique-label matching, QR approval,
local or federated NFC presentation, two-minute expiry, and holder receipts through Acorn.
The emergency-contact notification remains exclusive to `emergency`; a contact
directive inside `member` or `pass` does not trigger it.

Event rules, usage tracking, consuming a pass, entitlement revocation and more
sophisticated privacy behaviour are outside this change. Existing card/terminal
revocation checks and presentation expiry continue to apply.

Rebuild **app and POS** to enable both choices. No settings, database migration,
Acorn changes or terminal re-provisioning are required.

## Prepare the records in your wallet

Create a record labeled **whoami** with the information you want to use to
introduce yourself. You may attach an image, such as a photo, for the terminal to
preview. Create **myinfo** separately for additional information you wish to
present. The terminal requests one selected record at a time; choosing `myinfo`
does not automatically disclose `whoami` as well. Create **member** or **pass**
with the membership or entitlement information you want to present. Matching is
case-insensitive, including `Member` and `PASS`; keep only one record per label.

Keep only information you intend to present in these records. NFC presentation
does not currently require a PIN. The card points to the Acorn; record contents
and attachments are not written onto the card.

For an illustrated example, see [From a wallet to a card](user-experiences/card-pairing-and-payments.md#a-record-with-the-same-card)
and [One wallet, several counters](user-experiences/one-wallet-several-counters.md#one-terminal-for-payments-and-record-checks).

## Operator experience

1. Select **whoami**, **myinfo**, **emergency**, **health**, **benefits**, **member** or **pass**, then **Create Request**. A new request clears the previous
   displayed record and invalidates the previous request on this terminal.
2. The holder scans the QR using their OakGate wallet or phone camera. The wallet
   displays the terminal name and matching records and asks for approval. With
   multiple matches, the holder checks which records to share; nothing is checked
   by default. With one match, approval remains a single action. A holder
   who is signed out signs in in another tab and returns to the request.
3. Alternatively, on a compatible secure NFC browser, choose **Request by NFC**
   and ask the holder to tap their valid, activated OakGate card. This first
   flow supports local and remote OakGate cards through the signed issuer protocol and does not ask for a PIN.
4. When multiple approved records are available, choose one in **Record to display**,
   then **Show Record**. With only one, no selector is shown: choose **Show Record**. Acorn retrieves the presentation for
   display, without importing it into the merchant's wallet.
5. Create a new request or select **Close Request** to remove the display.

Requests last two minutes. The display also clears on expiry, when leaving the
record tab, or when the browser becomes hidden. Late responses cannot restore a
cleared display. Switching back to Point of Sale does not change a payment journal.

## Record selection and verification

A category matches its exact label and slash descendants, case-insensitively.
For example, `benefits` matches `benefits`, `Benefits/Dental` and
`benefits/health`, but not `benefits-other`. The exact match is displayed as
**General** in the POS selector, and descendants as **Dental** or **health** using
their stored spelling. Case-variant duplicates remain ambiguous and are rejected.
No match, or more than 20 matches, requires a new request after adjusting records.
Only user records returned through Acorn are eligible.

The wallet holder may approve one or several matches. The POS receives only the
approved labels and opaque selection IDs; unapproved record IDs cannot be used.
An NFC presentation makes all matches in the requested category available to the
terminal. With one match (or one approved record), the existing flow is unchanged.
With multiple matches, contents and attachments are acquired through Acorn only
when **Show Record** is selected. Switching selections immediately clears the
previous preview, including PDFs, and stale responses cannot restore it.

The two-minute request deadline does not restart when switching records. Each
record has its own OpenETR lookup and best-effort presentation receipt, with
receipt duplicate protection scoped to the request and selected record. Only the
exact `emergency` record triggers its contact directive; descendants do not.
No new schema, configuration, Acorn API or terminal provisioning is required.
Rebuild both **app** and **pos** and create a fresh request after deployment.

The existing Acorn public-only presentation method creates a short-lived
presentation. Record text and JSON are displayed as text, never executable HTML.
Raster image and PDF attachments up to 5 MiB are previewed; other attachments
show an unsupported-preview notice. PDFs use the wallet's bundled PDF.js library
with canvas rendering and Previous/Next controls for multi-page documents. No
external PDF viewer is loaded. Closing, replacing or expiring the request, or
leaving the page, clears the preview and releases the PDF document. OpenETR checks use the computed attachment digest and
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

An NFC tap authorizes disclosure of all matching records in the requested allowlisted category.
This is an additional bearer-card capability: holders should keep only information
they intend to present in that category. A lost or copied card can disclose that
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


## Holder presentation receipts

When the POS acquires any supported record (`whoami`, `myinfo`, `emergency`, `member` or `pass`)
for display, it schedules a private message to the holder's Acorn. This happens
for both QR approval and NFC presentation. The terminal owner's Acorn sends the
receipt through the existing Acorn/Stroma wallet messaging method. The destination
is the holder's known Acorn public key and bootstrap relay, without an address or
social NIP-05 lookup. No wallet handle is required for the holder.

The receipt includes the record label, terminal name, access time in UTC and a
request reference. It contains no record contents, attachment or presentation
capability. The holder sees it under **Your Receipts**, newest first. Tap a compact
row to expand its full text and sender details. Only a verified wallet address is
used as the collapsed sender label; otherwise a shortened wallet public key is
shown. Compose is hidden for now; the existing protected send endpoint remains.

Receipts are sent in the background and do not delay presentation. A durable
one-use submission marker prevents duplicate messages for the same request,
including concurrent accesses and uncertain publication. Emergency contact notices
and holder receipts have separate markers and recipients. Opening a new request
represents another access and may produce another receipt.

This is a recent, best-effort presentation history, not a complete audit archive.
The inbox reads up to 50 recent wallet messages from Acorn's bounded relay window.
A crash, busy wallet, relay outage or revoked terminal can prevent a receipt;
uncertain publication is not automatically retried. A receipt reports server-side
access for presentation, not proof that a person viewed the screen. Other wallet
messages can make claims too: sender signatures identify their wallet, not the
truth of their contents. This flow covers POS record requests, not every possible
record view or sharing flow elsewhere.

Deploy the rebuilt app for the compact inbox and holder receipts. No schema,
configuration or terminal enrollment changes are needed.


## Health record requests

Create a record labeled `health` to use this request. It follows the same
case-insensitive, single-record QR approval or local or federated NFC presentation flow,
including attachment preview and available OpenETR evidence. It does not create
or infer medical information, request other records, or notify an emergency
contact. Only `emergency` triggers the contact directive.

Include only information the holder intends to disclose at participating
terminals. NFC presentation uses the existing card-possession policy without a
PIN; selecting `health` does not add stronger authorization or a clinical
verification claim.


## Benefits record requests

Create a record labeled `benefits` to use this request. The terminal requests
only that record, with the same case-insensitive matching, QR approval or
local or federated NFC presentation, attachment previews and OpenETR information as other
record requests. It does not determine eligibility, grant benefits or trigger
emergency-contact notifications. The existing card-possession and disclosure
rules apply; this label adds no new authorization policy.

For remote cards, see [Federated POS card operations](026-nfc-card-payments.md#federated-pos-card-operations). The issuer produces the presentation and a holder receipt identifying the acquiring service. QR wallet approval and card issuance remain home-local.
