# Category paths and fingerprint record labels

Record categories describe where a record belongs. A sharing fingerprint
distinguishes the sender–content–recipient combination without making the
sender's handle part of that filing path.

## Stored labels and display names

New QR and NFC shares replace the final label segment with the full sharing
fingerprint. `/health/current` becomes `health/<sharing fingerprint>`, and
`health/prescriptions/current` becomes `health/prescriptions/<sharing fingerprint>`.
The parent path is preserved; the sender's leaf name is not appended to it.
Leading/trailing slashes are normalized away. A single-segment label such as
`current` becomes just `<sharing fingerprint>`; use a parent path when the
received record should be filed in a category. Re-sharing replaces the final
digest instead of appending another. No existing records are renamed in bulk; legacy sender-prefixed
paths remain unchanged until explicitly edited.

The stored fingerprint is the full 64-character SHA-256 digest. Lists, headings
and presentation selectors recognize complete hexadecimal path segments and show
only the first eight characters in uppercase, matching the original-file
fingerprint display (for example, `A1B2C3D4`). This is a
compact recognition aid, not a unique identifier or an integrity check.
Two different full digests can have the same eight-character display. Full labels and opaque record IDs
remain in storage, signed coordination and authorization. Editable label fields
retain the full path so users can make an explicit naming choice.

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
boundaries. `/health` matches `health/prescriptions/...`, but not `healthcare`.
`/health/prescriptions/<digest>` can select a specific record.

A `/benefits` request can offer both `benefits/dental` (shown as `dental`) and
`benefits/<digest>` (shown as the shortened fingerprint). One match retains the
existing direct display flow; multiple matches use the selector. Wallet approval
still controls which records are offered. A shortened name never changes the
selected record's identity. Existing selection limits and cross-home checks apply.

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
