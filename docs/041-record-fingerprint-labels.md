# Category paths and fingerprint record labels

Record categories describe where a record belongs. A sharing fingerprint
distinguishes the sender–content–recipient combination without making the
sender's handle an identity or authority claim. A sender hint in the final leaf
helps the holder recognize which shared copy to select at the POS.

## Scope: OakGate application conventions

The path formation, sharing-label suffixes, display shortening and POS selection
rules in this document are **OakGate application conventions**. They are not
requirements of Acorn, Nostr or OpenETR, and do not define a universal record
namespace or a protocol-level folder hierarchy.

Acorn stores and manages the records and their labels, subject to its own API,
validation and security rules. OakGate interprets those labels as category paths,
generates recipient sharing labels, formats selection names and determines which
records match a POS request. A folder inferred from label prefixes is an OakGate
navigation aid, not a separate record unless an actual record exists at that label.

Other applications may use different naming and presentation conventions without
adopting OakGate's rules. Their records may need explicit renaming to participate
in OakGate's category-based selection; existing labels are not silently migrated.
Participating OakGate homes use the same conventions for local and cross-home
presentation. Label compatibility alone never grants access or establishes
authorship, provenance, integrity or OpenETR validity: Acorn authorization,
holder approval or card authorization, and evidence verification remain separate.

## Stored labels and display names

The full stored label, including category paths and fingerprint, is limited to
1,024 characters. Create, rename, QR import and NFC delivery enforce this bound;
oversized labels are rejected, never silently truncated. Display shortening
does not alter the stored label or fingerprint.

Deploy the corresponding Acorn record-transfer limit update before relying on
long-label sharing. Older Acorn versions reject transferred source labels over
200 characters. Commit and publish the Acorn change, then refresh OakGate's
`safebox-acorn` lock entry and rebuild; a local source test is not a deployed
dependency update. Both sending and receiving homes need compatible versions.
No database schema migration is required. Labels are metadata, but longer values
still increase encrypted event and request sizes and remain subject to relay
and transport limits.

New QR and NFC shares append `-<originator-handle>-<full-sharing-fingerprint>`
to the original label's leaf, without creating another folder. Hyphens in the
original category path become spaces; source records remain unchanged:

| Original label | Recipient label |
| --- | --- |
| `health` | `health-trbouma-<fingerprint>` |
| `benefits` | `benefits-trbouma-<fingerprint>` |
| `health/prescriptions` | `health/prescriptions-trbouma-<fingerprint>` |
| `health-care/prescription-record` | `health care/prescription record-trbouma-<fingerprint>` |

Leading/trailing slashes and segment-edge whitespace are normalized away.
In the new convention the first hyphen begins provenance; the last hyphen
separates the full digest. Handles may contain hyphens, but the suffix cannot
contain slashes. Re-sharing replaces a recognized suffix. Legacy digest-only or
simple handle/digest leaves are removed before applying the new suffix; a
digest-only label without a remaining category must be renamed before sharing.
Reserved naming shapes are filing conventions, not proof of provenance. Ambiguous
legacy names should be explicitly renamed before re-sharing. Existing stored
records are not renamed in bulk.

Hyphen normalization can map two original names to the same category (for example
`health-care` and `health care`). Existing destination-label collision checks
still reject overwrites. QR users can review/edit the suggested label; NFC senders
review the destination label before confirming delivery.

Handles use Acorn's 1–64-character ASCII letters/digits/underscore/hyphen format,
beginning with a letter or digit. Missing or invalid handles fall back to
`sender-<first-12-public-key-hex-characters>` when available, otherwise
`unknown-sender`. Untrusted handles cannot introduce path separators or markup.
This is a descriptive sender hint, not a verified issuer identity. Handles do
not enter the sharing fingerprint computation.

The stored fingerprint is the full 64-character SHA-256 digest. Lists, headings
and presentation selectors show a new leaf as `prescriptions-trbouma-A1B2C3D4`; legacy complete
hexadecimal path segments still display as `A1B2C3D4`. Only the fingerprint is
shortened, to its first eight characters in uppercase. This is a
compact recognition aid, not a unique identifier or an integrity check.
Two different full digests can have the same eight-character display. Full labels and opaque record IDs
remain in storage, signed coordination and authorization. Editable label fields
retain the full path so users can make an explicit naming choice.

POS matching is case-insensitive and includes the exact requested label,
root sharing records beginning with that path plus `-`, and direct child record
entries with or without a hyphen suffix. With Record category `pass` and subcategory
empty, this includes `pass`, `pass-trbouma-…`, `pass/trbouma-test1-…` and
`pass/trbouma-test2-…`, `pass/booga1` and `pass/test1-trbouma`.
Only actual Acorn records are listed: a derived folder `pass/events` is not a
record, but an actual record with that label is included. It excludes deeper
entries such as `pass/events/ticket-trbouma-…`, and unrelated `passport-…`.
Select subcategory `events` to request `pass/events` and its direct records.
The hyphen is a naming convention, not fingerprint or authority validation.
Slashes after the provenance suffix begins remain invalid for POS matching.
Request-path hyphens are normalized to spaces too. The same rule applies to local and
cross-home POS approval. Selection limits and exact stored-label
authorization remain unchanged. Generic editable labels remain supported; the
normalization applies to generated sharing labels, not silent global renaming.

Selection discovery uses the same paginated Acorn API as the Records browser,
including empty pages with continuation cursors. It completes the scan before
offering choices, with a 100-page budget and 40-second timeout. Relay failures,
repeated cursors, or exhausted budgets fail the request rather than presenting
a partial list as complete. Record references use the Acorn event IDs returned
by the paginated API; legacy hashed references remain supported by record lookup.

## Three explicit fingerprints

- **Record-content fingerprint**: SHA-256 of canonical UTF-8 JSON with
  `record_type`, `payload`, and `original_record_fingerprint` (null without an
  attachment). Keys are sorted, separators compact, Unicode unescaped and
  non-finite numbers rejected. Labels, handles and transfer expiry are excluded.
- **Original-record fingerprint**: SHA-256 of the original decrypted file bytes,
  or null for a text-only note. It is stable across sharing and metadata edits;
  replacing the original file produces a different original fingerprint. This
  is the fingerprint used for original-file/OpenETR verification.
- **Sharing fingerprint**: SHA-256 of the concatenation of the originator Acorn
  public-key bytes, record-content fingerprint bytes, and recipient Acorn
  public-key bytes, in that order. Each component is exactly 32 bytes. Hash raw
  bytes, not npub strings or hexadecimal text. Social NIP-05 keys are not used.

The sharing fingerprint supplies the suggested label suffix. The same sender,
content and recipient produce the same result, even across separate attempts.
Different senders or recipients produce different results. This identifies a
combination, not a unique issuance: two otherwise identical tickets for one
recipient would need a future issuance ID.

Acorn includes the originating wallet public key inside the encrypted transfer.
For QR sharing, the authenticated receiving Acorn computes the sharing
fingerprint during review. For NFC, the sending home first resolves the card's
recipient wallet and asks Acorn to compute it for that recipient. No private-key
operation is implemented in OakGate.

Recipient storage can change local metadata without changing the accepted label.
Recomputing a content fingerprint yields the same value if the defined content
is identical, and a different value if that content changes. It does not rewrite
receipt provenance. Re-sharing uses the current sender and new recipient.

These identifiers do not prove authorship, prevent forwarding, enforce ticket
ownership or implement redemption. The originator key is supplied metadata,
not a signature attestation. Those checks remain separate future work.

## Requests and selection

The POS Record category dropdown offers `whoami`, `myinfo`, `emergency`,
`health`, `benefits`, `member` and `pass`. An optional Subcategory field narrows
the selection: choosing `health` and entering `prescriptions` requests
`health/prescriptions`. Nested extensions such as `prescriptions/current` also
work. Leaving the field blank requests the parent category.

Matching is case-insensitive, normalizes optional outer slashes and respects path
boundaries. `health` includes an actual record named `health/prescriptions`, but
not the grandchild `health/prescriptions/current` or unrelated `healthcare`.
Request `health/prescriptions` to include its root and direct child records.
Folders derived from other labels are navigation aids, not selectable records.

A `/benefits` request can offer both `benefits/dental` (shown as `dental`) and
`benefits/<digest>` (shown as the shortened fingerprint). One match retains the
existing flow without a selector; multiple approved matches use the selector.
The operator still chooses Show Record to retrieve and display the selected
record. Options show the final label component, shortening a fingerprint as
described above; full stored labels and opaque selection IDs remain authoritative.

For QR requests, the holder explicitly approves which matching records to offer.
Only approved records reach the POS selector. For NFC requests, a validated card
makes all matching records in the requested category available under the existing
card-possession authorization policy. Neither path discloses deeper descendants
or unrelated categories. These rules apply locally and across participating homes.

There must be between one and 20 matching records before approval. Zero matches,
more than 20, or duplicate normalized labels fail selection rather than truncating
the choices. Narrow the subcategory when the result exceeds the limit. This
20-record selection limit is separate from the 100-page/40-second discovery
budget: discovery must finish before matching and approval proceed.

## Updates and explicit names

An accepted sharing label remains unchanged when content or attachments are
edited. Users can explicitly rename it. Ordinary custom labels also remain
unchanged. This preserves the originating sharing fingerprint independently of
the recipient's current record-content and original-file fingerprints.

A rename checks that the destination is unused, writes and confirms the new
record through Acorn, then requests removal of the old record through Acorn.
Existing attachment bytes are preserved when renaming without a replacement.
The old blob is not deleted. This is not an atomic relay transaction: a crash or
uncertain cleanup can leave both records. Check Records before retrying; OakGate
never overwrites a destination to complete a rename.

## Duplicate receipt

An existing label is a conflict, not proof of a duplicate: its recipient may
have edited the record. OakGate never overwrites it or infers receipt from a
matching suffix. QR users can choose another label; NFC delivery rejects the
collision. Existing durable attempt status prevents replay of the same delivery;
uncertain writes still require review, not automatic retry.

QR and NFC receipt perform an exact-label lookup through Acorn against the
recipient's home relay before importing, independently of the bounded record
list. The adapter checks again immediately before calling Acorn's import method.
A failed lookup stops the import; it is never treated as an unused label. NFC
post-import confirmation also uses the exact-label lookup, rather than searching
a potentially truncated listing.

The listing-based case-insensitive check remains an additional user-interface
safeguard. Acorn's underlying labels are case-sensitive: this change protects the
exact stored label even when it is absent from the listing, but does not provide
a complete case-insensitive namespace index. The existing OakGate wallet lease
serializes local writers. Relay lookup followed by publication is not an atomic
create-if-absent operation against independent clients using the same Acorn;
this does not claim cross-client transactional exclusion.

Durable NFC delivery attempts retain their originally confirmed terms. Updating
software does not change labels on an in-flight or uncertain delivery.

## Example: a prescription shared with a patient

A doctor keeps a record labelled `/prescription/patient`, with a prescription PDF
as its original file. On sharing it with the patient's Acorn, the suggested
recipient label is `prescription/<sharing fingerprint>`.

| Situation | Result |
| --- | --- |
| Same doctor Acorn, unchanged content, same patient Acorn | Same sharing fingerprint and suggested label. If that label still exists, the share is flagged as a collision and never overwrites it. |
| Same doctor and patient, but a new prescription PDF | New original-record fingerprint, new record-content fingerprint and new sharing fingerprint. The new copy can be stored alongside the earlier prescription. |
| Same PDF, but the doctor changes the record's text or structured payload | Original-record fingerprint stays the same; record-content and sharing fingerprints change. |
| Identical content from a different doctor's Acorn | Different sharing fingerprint because the originating Acorn key differs. |
| Same content sent to a different patient's Acorn | Different sharing fingerprint because the receiving Acorn key differs. |
| Patient edits their received copy | The accepted label stays unchanged unless explicitly renamed. Its suffix no longer describes the current content; it preserves the sharing identifier assigned at receipt. |

This is label collision protection, not a permanent duplicate-delivery registry.
If the recipient renames or removes the first copy, its former suggested label
may become available again. A QR recipient can also explicitly choose another
label. Durable delivery recovery separately protects an already-submitted NFC
attempt from being imported again.

The example does not automatically supersede, revoke or invalidate an earlier
prescription. It does not establish the doctor's credentials or clinical
validity. Original-file verification remains a separate OpenETR operation.

`/prescription/patient` is a valid example sharing path. For the current POS
category picker, use `/health/prescriptions/patient`: `health` is an enabled root,
whereas a top-level `prescription` request is not currently enabled.

## Example: the same ticket sent to many recipients

An organizer can share identical ticket content with hundreds of Acorns. Each
recipient gets a different sharing fingerprint, while the original-file and
record-content fingerprints remain common to all identical copies. A suggested
source label such as `pass/ticket` becomes `pass/<sharing fingerprint>`, keeping
each receipt distinct by wallet.

Sending the same content to the same wallet again produces the same suggested
label. Two separately issued, otherwise identical tickets for one wallet would
need an issuance identifier in the content or a future extension. Ticket
ownership, non-transferability, usage tracking, redemption and revocation are
outside this feature.

## Text notes without an original file

A simple text note has a record-content fingerprint and a sharing fingerprint;
its original-record fingerprint is null. The same collision and edit rules
apply. No attachment or OpenETR anchor is needed to share the note.

## Deployment

This requires the additive `record_content_fingerprint`, `original_record_fingerprint`, and
`sharing_fingerprint` fields returned
by Acorn's `inspect_record_transfer`. Acorn's existing label, originator handle and
acceptance behavior are unchanged, so safebox-web callers remain compatible.

1. Commit and push the safebox-acorn change first.
2. In OakGate, run `poetry update safebox-acorn`, then commit the updated lockfile
   with the OakGate changes. The dependency remains on `main`.
3. Rebuild app and POS on participating homes. No database migration or card
   re-pairing is needed.

The current local source tests do not update the deployable lockfile. Until Acorn
is pushed and the lockfile refreshed, new fingerprint-based sharing cannot be
considered ready for container deployment. Existing record reads and ordinary
presentation flows do not require the additive transfer metadata.

Older transfer envelopes without an originator public key remain readable and
importable by Acorn, but cannot produce a recipient-specific sharing fingerprint.
OakGate requires a newly generated sharing code for this naming flow; it does
not substitute a social key, file digest, or guessed identity. Existing durable
NFC attempts retain their confirmed labels and recovery state.
