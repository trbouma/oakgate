# POS record requests

The **Check a Record** tab lets an activated terminal request a `whoami` record.
This is a presentation for viewing, not a record transfer or a payment instruction.
Only `whoami` is enabled in the dropdown and server allowlist in this first version.

## Operator experience

1. Select **whoami**, then **Create Request**. A new request clears the previous
   displayed record and invalidates the previous request on this terminal.
2. The holder scans the QR using their OakGate wallet or phone camera. The wallet
   displays the terminal name and requested label and asks for approval. A holder
   who is signed out signs in in another tab and returns to the request.
3. Alternatively, on a compatible secure NFC browser, choose **Request by NFC**
   and ask the holder to tap their valid, activated OakGate card. This first
   iteration supports same-home cards only and does not ask for a PIN.
4. When ready, choose **Present Record**. Acorn retrieves the presentation for
   display, without importing it into the merchant's wallet.
5. Create a new request or select **Clear request** to remove the display.

Requests last two minutes. The display also clears on expiry, when leaving the
record tab, or when the browser becomes hidden. Late responses cannot restore a
cleared display. Switching back to Point of Sale does not change a payment journal.

## Record selection and verification

Labels are compared in lowercase: `whoami`, `WhoAmI` and `WHOAMI` match. A missing
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

An NFC tap authorizes disclosure of the designated `whoami` record in this iteration.
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
environment variables or database migrations. The existing record transfer server,
allowed storage servers and OpenETR settings apply. Redis must be available for
production; losing ephemeral request state requires a new request, not recovery of
a payment or a change to the user's Acorn.

Test an ordinary QR approval and NFC tap on the actual terminal. Also test a missing
record, a revoked card, expiry and starting a new request while a previous lookup
is pending. Automated tests cover these authorization and stale-response boundaries;
physical NFC and live relay/media behavior still need deployment verification.
