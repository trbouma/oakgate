# Records, folders, presentation and sharing

OakGate uses the same Acorn records and temporary-copy protocols as Safebox Web.
The custody model changes who retains the key, not the underlying record format.
All user-key operations remain in Acorn. Public OpenETR evidence is retrieved
and signature-checked through the explicit `stroma-nostr` dependency.

## User experience

Scan and Receive are stacked full-width actions beneath navigation. Add Record
appears only on the Records page for connected Acorns. All three use a minimum
56-pixel target height for access from either side of the screen.

- **Add Record** creates a labelled text or JSON record with an optional attachment.
  Labels are limited to 200 characters, text to 256 KiB and files to 25 MiB.
  Under the OakGate wallet lease, Acorn checks whether the label already exists;
  an existing label is rejected rather than overwritten. Acorn performs publication
  and verification. An uncertain save directs the user to check Records before
  retrying. This check does not provide atomic exclusion against another independent
  client writing to the same Acorn at the same time.

- **List** shows records newest first. **Folders** groups existing labels by `/`,
  with breadcrumbs. Folder names sort alphabetically; records retain timestamp
  order. These are label groups, not a separate folder database.
- **View** retains the existing image, PDF, pass, credential and mdoc previews.
- **Edit** updates text or JSON, preserving the label and record type. An optional
  file replaces the attachment; leaving it blank preserves the existing file.
  Text is limited to 256 KiB and files to 25 MiB. Acorn must confirm the published
  record before OakGate reports success. Reload after an uncertain save.
- **Delete** opens a separate confirmation page showing the record label, a
  required confirmation checkbox and Cancel. Only a CSRF-protected POST can
  delete. OakGate takes the wallet lease, rechecks the record reference against
  the user's Acorn and calls `Acorn.delete_record` for kind 37375. Success requires
  Acorn to report that the configured relay no longer returns the record. An
  uncertain outcome asks the user to reload Records before retrying. NIP-09 is
  advisory: historical relay copies may remain. Separately stored attachments
  and sharing copies are retained; this action does not claim complete erasure.
- **Present** creates a view-only presentation code for a compatible Safebox.
- **Share** creates a code that a compatible Safebox can import.
- **Check** computes the original file's SHA-256 locally and queries configured
  OpenETR relays for anchor events (1415) and publisher notices (1416). The user
  confirms disclosure of the fingerprint first. Neither file contents nor a
  private key are sent in the evidence query.

Present and Share copy one record and its attached file. New codes expire after two minutes in compatible clients. They are bearer secrets: anyone holding one can read
the copy. Presentation's view-only convention cannot prevent copying, and neither
expiry nor a successful deletion request proves removal from all storage.

**Active shares** retains the codes and Stop control across navigation, sign-out
and app restarts. Stopping calls Acorn's transfer-scoped deletion method; OakGate
removes its saved descriptor only after deletion is confirmed. It cannot recall
copies already received. An upload followed by a lost response or database failure
can leave an untracked copy; OakGate reports the outcome as uncertain and does not
automatically retry. The active Present/Share page shows a two-minute progress
bar and countdown, then submits the normal CSRF-protected Stop request through
Acorn. Reloading a new code does not extend its embedded expiry. Browser suspension
can delay that deletion request; expiry still applies in compatible clients.
Closing the page does not schedule background deletion. Unconfirmed deletion
retains the code for manual retry through Active shares. Older codes retain their
original embedded expiry, but an open page requests Stop within two minutes.
There is no background expiry/deletion worker yet.

OakGate's Scan action accepts the same Acorn presentation and transfer codes as
Safebox Web. Presentations render content and supported attachments without
importing them, and show the OpenETR evidence check. Transfers show their type,
attachment presence and expiry, with a **Store as** label before import. A label
already in this OakGate wallet is rejected before claiming the import ticket;
this is not atomic exclusion against another independent Acorn client. Each ticket
remains owner-bound and one-shot, including uncertain results. Import and temporary
copy deletion run through Acorn. Record renaming and folder moves are not added.

Check now uses Safebox Web's candidate/signer/publisher-notice presentation and
separates **Anchor found**, **No anchor found**, and **Check unavailable**. A local
record check still retrieves and hashes its original bytes before querying.
Timeouts return an unavailable check, not a message implying a failed save.
Matching anchors can show a public OpenETR evidence link and QR. That link contains
a fingerprint, not the private record or its sharing secret.

Scanning an exact `OAKGATE_OPENETR_PUBLIC_BASE_URL/<sha256>` link opens an OakGate
evidence check using configured relays. A scanned fingerprint does not prove
possession or verification of the original bytes. Unrecognized HTTPS links stay
on the external-link review page; they cannot select relays or storage servers.
GS1 Digital Link, GTIN and element-string discovery remain available, alongside
Lightning addresses/invoices, Cashu tokens and Clear payment requests.

Present/Share pages have tap-to-copy QR codes and Copy code buttons, expiry
information, progress feedback on Stop, and a best-effort leave-page warning.
Expired codes no longer show a usable QR, but remain in Active shares so deletion
can be retried. Closing a presentation view does not revoke the sender's copy.

## Infrastructure configuration

```dotenv
OAKGATE_BLOSSOM_SERVER=https://grove.safebox.dev
OAKGATE_TRANSFER_SERVER=https://grove.safebox.dev
OAKGATE_OPENETR_RELAYS=wss://relay.openetr.org
OAKGATE_OPENETR_PUBLIC_BASE_URL=https://openetr.org/etr
OAKGATE_OPENETR_QUERY_TIMEOUT_SECONDS=5
OAKGATE_OPENETR_QUERY_LIMIT=100
OAKGATE_OPENETR_BLOSSOM_SERVERS=https://grove.safebox.dev
OAKGATE_RECORD_ALLOWED_SERVERS=https://grove.safebox.dev
```

The first server receives new/replacement encrypted attachments; the second
receives temporary encrypted sharing/presentation copies. Existing attachments
continue to resolve through Acorn. Transfers read existing blobs using Acorn's
public-only Stroma retrieval. Operators can select community-run infrastructure.
Record evidence pages also discover optional witness receipts (experimental kind
1418, Spurline receipt profiles v1–v3) for qualifying anchors and publisher notices.
The expandable **Witness events** section checks each receipt's signature, event
ID and commitment to the subject's exact signature. It displays the witness signer,
claimed observation time, clock basis/uncertainty, authorization and policy
references, retrieval sources and signed event JSON. Copies of one receipt are
deduplicated; different witness receipts remain individually visible.

Witness discovery uses only `OAKGATE_OPENETR_RELAYS`. To discover receipts issued
by Spurline, include `wss://spurline.safebox.dev` in that comma-separated setting.
No relay URLs in received events are followed. Profile and witness lookups run
concurrently after anchor discovery, with the existing timeout and result limit;
witness subject discovery is capped at 200 event IDs. Partial failures and reached
limits are reported separately from core record verification.

These checks do **not** establish commissioning, authorization validity, policy
acceptability or truthful timestamps, and do not change Core Record Ruleset
results. System-clock receipts explicitly have unspecified accuracy. Missing
receipts do not establish that no witness exists. Unsupported or invalid receipts
are excluded with a warning rather than represented as verified witnesses.

OpenETR uses 1–8 comma-separated public WSS relays. Queries are bounded, reject
private DNS destinations and redirects, and require no Google or OpenETR account.

Core Record Ruleset 1.0 and its presentation adapter are carried over from
Safebox Web (`app/openetr_rules.py`, `app/openetr.py`). OakGate displays candidate
anchors, publisher notices and inspectable findings. Unavailable evidence is not
reported as a clean check. Bounded discovery cannot establish completeness,
recognition, legal validity or ownership. This integration does not publish
OpenETR events or expose a user's private key to the evaluator.

## Nginx upload limits

Add this directive inside the existing HTTPS `server` block for **each** host:
`oakgate.safebox.dev` and `grove.safebox.dev`. Keep their existing TLS and upstream
settings.

```nginx
client_max_body_size 110M;
```

The upload passes through two proxies: browser → OakGate, then Acorn → Grove
for encrypted storage. Temporary sharing copies also use the configured transfer
server. A limit at either proxy can cause **413 Request Entity Too Large**.
A successful browser preview does not test either upload: the preview is local.
In the deployed setup, raising this Nginx limit resolved attachment-save failures.

This is the proxy request-body limit, not the application file allowance.
OakGate continues to limit attachments to **25 MiB**, form requests to **26 MiB**,
and record text to **256 KiB**. Grove may enforce its own application limits.
The larger proxy allowance provides room for request and encryption overhead;
it does not enable 110 MiB attachments in OakGate.

After editing the Nginx configuration, validate and reload on each proxy host:

```bash
sudo nginx -t && sudo systemctl reload nginx
```

For container-managed Nginx, run the equivalent validation and reload in that
Nginx container. Rebuilding OakGate or restarting Keycloak is not necessary for
an Nginx-only change.

If a 413 persists, inspect the effective configuration with `sudo nginx -T`:
check both hostnames and any matching upload `location` blocks for a smaller
`client_max_body_size` override. Check the access/error logs on both proxies to
identify which rejected the upload. Check Records before retrying an uncertain
save, then verify that the saved attachment opens correctly.

## Storage and backups

Records remain in the Acorn, not a new OakGate content database. Temporary bearer
codes are encrypted with the operator custody key in the `record_capabilities`
table of the existing `custody.sqlite3`. Each descriptor is bound to both its
owner's issuer/subject identity and an opaque capability ID. Backup the consistent
SQLite database and the custody key as described in the identity/storage note.
The server-side owner binding prevents one user from viewing or stopping another
user's sharing copy. Redis remains session storage only.

## Acorn dependency and deployment order

This feature includes changes in the sibling **safebox-acorn** repository:

- Prevent uncertain saves from deleting existing or newly uploaded attachments.
- Run synchronous Blossom upload/deletion calls off the application event loop.
- Add `public_only` to record transfer/presentation creation.
- Advertise these guarantees with `Acorn.record_workflows_version = 1`.

Publish those Acorn changes to `main` first. Then, in OakGate:

```sh
poetry update safebox-acorn
poetry run python -c 'from acorn.acorn import Acorn; assert Acorn.record_workflows_version >= 1'
poetry run pytest
```

Commit the updated lockfile with OakGate. Its dependency declaration stays on
`main`; the lockfile must resolve to the published changes for a reproducible
container build. Until then OakGate blocks Edit, Present and Share instead of
using an unsafe older implementation. Source-override development tests do not
establish that the installed or container dependency has been updated.

On the deployed machine, use `./refresh-app.sh`; Keycloak does not need a restart.
Before testing against valuable records, exercise editing an attached disposable
record and presenting/sharing it with another Safebox, then confirm Stop behavior
against the selected Blossom service.

## Record transfers and address discovery

Sharing and presentation use Acorn-generated transfer descriptors carried in
QR codes or links. They do not resolve a recipient through NIP-05 or the wallet
directory. Future address-based record delivery must use explicit wallet
capabilities in `safebox.json`, not a social key. See the
[resolution contract](018-safebox-address-discovery.md#which-lookup-serves-which-purpose)
for how this differs from payments and wallet messages.


## Deployment and smoke test

These settings are passed into the app by Compose. Update `.env`, then rebuild
and recreate only OakGate with `./refresh-app.sh`; Keycloak and Redis need no
restart. This change uses the existing Acorn presentation/transfer APIs and does
not require a new Acorn commit or any change to Safebox Web.

Public OpenETR artifacts may live on a different Grove/Blossom server from private
wallet attachments. List those public sources in `OAKGATE_OPENETR_BLOSSOM_SERVERS`.
For cross-application Present/Share, both applications must trust the server that
hosts the temporary encrypted copy. Add approved remote servers to
`OAKGATE_RECORD_ALLOWED_SERVERS`; OakGate's own Blossom and transfer servers are
always included. Merely scanning a code never authorizes a new server. Limits:
1–8 servers per list, 1–15 seconds per query, 1–200 events per query.

After deployment, use two test Acorns with a harmless record and attachment:

1. Open Check; compare the file fingerprint and candidate/signer evidence with
   Safebox Web. Test an unanchored file as well as a known OpenETR record.
2. Present in each application and scan in the other. Confirm the preview opens
   without adding a record to the receiver, then stop the presentation.
3. Share in each direction; choose a new destination label and import once.
   Confirm the record and file appear in the receiver's Acorn. Resubmitting the
   same ticket must not import again.
4. Copy/scan an OpenETR evidence link and a GS1 code with a known published anchor.
   Compare artifact retrieval and candidate selection against Safebox Web.
5. Repeat on a phone; test clipboard fallback, expiration and unavailable relays.

Real camera permission, deployed relay contents and cross-instance server access
require this deployment smoke test; isolated regression tests cannot prove them.


## Originator handle suggestions

New shares and presentations include the sender's current OakGate handle as
optional metadata inside Acorn's encrypted transfer envelope. The QR descriptor
still carries only the bearer capability; the handle is read after decryption.
On acceptance, OakGate suggests `handle/existing label` in **Store as**, which the
recipient may edit. Existing labels remain protected against overwrites. If the
combined label exceeds the 200-character limit, the original label is suggested.
The handle is a display hint, not verified authorship or a social identity claim.

Publish the optional `originator_handle` Acorn API change first, then run
`poetry update safebox-acorn` in OakGate and commit its lockfile before deployment.
Old envelopes decode without a handle; older Acorn readers ignore the extra
optional field. Safebox Web's existing calls and default import labels are unchanged.

## Sharing fingerprints and recipient labels

QR and NFC receipt labels use a fingerprint of the originating Acorn key,
record content and receiving Acorn key. Repeated unchanged shares to the same
wallet suggest the same label; changed content or a different wallet changes
the sharing fingerprint. Recipient edits preserve the accepted label, and the
original-file fingerprint remains separate for verification.

See [Record paths and fingerprints](041-record-fingerprint-labels.md) for the
precise contract, collision handling, text-only notes, prescription and ticket
examples, and deployment requirements.


## Paginated browsing and direct reads

The wallet Records page uses Acorn's `get_user_records_page` against the wallet's
bootstrap relay. Relay batches request up to 100 events, but browser pages contain
up to **20 visible records**, assembled across batches after internal-record and
selected-folder filtering. **Next page** appears only after finding another visible
record. Overflow metadata is retained in the encrypted continuation state so no
records are dropped when a relay batch crosses a browser-page boundary.

Searches are bounded to 100 relay batches and 40 seconds per browser request.
Lookup failures or exhausted search budgets are reported as unavailable, not an
empty wallet. **First page** refreshes discovery from the start. Folders are grouped
from the current page's records, so a page may show fewer than 20 distinct entries.
Opening a folder collects matching metadata across relay batches and sorts paths
alphabetically (case-insensitive) before pagination. This avoids alphabetical order
restarting with each newest-first relay batch. Remaining metadata stays in the
encrypted continuation state; attachments are not fetched. The same search bounds
apply, so very large folders may require future indexing work. The regular List
view remains newest-first. Pagination is not a snapshot when records change during browsing.

Continuation links contain a random token. The underlying cursor and buffered label/reference metadata are encrypted
with the instance custody cipher in the session store, expires after 15 minutes,
and is bound to the owner, Acorn public key, relay, view and selected folder.
An expired or mismatched link must be reopened from Records.

New detail links use the event ID and Acorn's `get_user_record`, which verifies
ownership and preserves internal-record protections. OakGate never uses an
internal-capable record reader. List responses contain labels, timestamps and
references only; attachments are fetched on demand. Existing hashed detail links
remain supported by a paginated compatibility search and safe direct re-read.
That search is bounded to 200 pages and the service's 40-second read timeout;
failures remain unavailable rather than being reported as an empty wallet.

This change covers wallet list and detail views. Existing bounded discovery used
by POS selection and other sharing workflows is unchanged. It requires the
updated safebox-acorn dependency and an app rebuild; no database migration or
payment recovery changes are involved.

Deferred work and the checklist for resuming it are recorded in the
[Record management roadmap](042-record-management-roadmap.md).

## EPUB attachment previews

Wallet record views, scanned presentations and POS record presentations support
`application/epub+zip` attachments as a text-only chapter reader. Chapters follow
the EPUB spine reading order; the first chapter opens automatically. This is a
reading aid, not an additional verification claim. Original-file fingerprints
and OpenETR verification retain their existing meanings.

The preview does not execute scripts, fetch external resources or render embedded
HTML. Illustrations, fixed layouts and DRM-protected books are not supported.
The wallet retains the original-file download. Unsupported or malformed books
show an unavailable-preview message. POS previews retain their 5 MiB attachment
limit; wallet parsing accepts at most 25 MiB. Parsing also limits archive expansion
to 64 MiB, 2,000 entries, 1 MiB per parsed resource, 200 chapters and 500,000 text
characters. Plain XML document-type declarations are accepted without loading external DTDs;
internal DTD subsets and custom entity definitions are rejected. Rebuild both app and POS when deploying this
viewer update. No user-key operations or Acorn storage formats change.
