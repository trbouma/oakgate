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
- **Present** creates a view-only presentation code for a compatible Safebox.
- **Share** creates a code that a compatible Safebox can import.
- **Check** computes the original file's SHA-256 locally and queries configured
  OpenETR relays for anchor events (1415) and publisher notices (1416). The user
  confirms disclosure of the fingerprint first. Neither file contents nor a
  private key are sent in the evidence query.

Present and Share copy one record and its attached file. Codes expire after one
hour in compatible clients. They are bearer secrets: anyone holding one can read
the copy. Presentation's view-only convention cannot prevent copying, and neither
expiry nor a successful deletion request proves removal from all storage.

**Active shares** retains the codes and Stop control across navigation, sign-out
and app restarts. Stopping calls Acorn's transfer-scoped deletion method; OakGate
removes its saved descriptor only after deletion is confirmed. It cannot recall
copies already received. An upload followed by a lost response or database failure
can leave an untracked copy; OakGate reports the outcome as uncertain and does not
automatically retry. There is no background expiry/deletion worker yet.

This iteration supports sending codes to compatible Safebox clients. It does not
add an OakGate scanner/import flow, record renaming, folder moves or record deletion.

## Infrastructure configuration

```dotenv
OAKGATE_BLOSSOM_SERVER=https://blossom.getsafebox.app
OAKGATE_TRANSFER_SERVER=https://blossom.getsafebox.app
OAKGATE_OPENETR_RELAYS=wss://relay.openetr.org
```

The first server receives new/replacement encrypted attachments; the second
receives temporary encrypted sharing/presentation copies. Existing attachments
continue to resolve through Acorn. Transfers read existing blobs using Acorn's
public-only Stroma retrieval. Operators can select community-run infrastructure.
OpenETR uses 1–8 comma-separated public WSS relays. Queries are bounded, reject
private DNS destinations and redirects, and require no Google or OpenETR account.

Core Record Ruleset 1.0 and its presentation adapter are carried over from
Safebox Web (`app/openetr_rules.py`, `app/openetr.py`). OakGate displays candidate
anchors, publisher notices and inspectable findings. Unavailable evidence is not
reported as a clean check. Bounded discovery cannot establish completeness,
recognition, legal validity or ownership. This integration does not publish
OpenETR events or expose a user's private key to the evaluator.

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
