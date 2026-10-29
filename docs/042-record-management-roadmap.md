# Record management: deferred improvements

Status: parked, 29 October 2026. Expected near-term use is dozens of records per
Acorn. Further scaling work should follow observed needs, not delay other product
work. This note records implementation status, not confirmation of deployment.

## What is in place

- Exact Acorn collision checks before accepting shared records, independent of
  the bounded label list. Lookup failure does not mean a label is available.
- Acorn paginated user-record discovery and safe direct retrieval, preserving
  ownership checks and internal-record protections.
- OakGate Records pages use paginated discovery; new detail links use direct
  retrieval. Older hashed links retain a bounded compatibility search.
- Owner-, wallet-, relay- and view-bound encrypted continuation tokens, with a
  15-minute lifetime. Attachments are fetched on demand.
- Folder parents that contain a record remain selectable alongside children.
- Sharing fingerprints and compact display labels work with record paths.

See [Records and sharing](011-record-workflows.md#paginated-browsing-and-direct-reads)
and [Record paths and fingerprints](041-record-fingerprint-labels.md).

## Next work, when needed

| Priority | Follow-up | Revisit when |
| --- | --- | --- |
| 1 | Migrate POS record selection and remaining sharing discovery to Acorn pagination. Preserve the simple single-match flow and make result limits explicit. | A valid matching record is missing from a selection, or wallets routinely require multiple pages. |
| 2 | Improve folder browsing across pages. Current folders describe the current page; navigating into one starts a new traversal. Evaluate category-aware discovery or a rebuildable index rather than eagerly loading every record on every request. | Users find page-scoped folders confusing or cannot easily find older records. |
| 3 | Measure realistic relay performance with larger disposable wallets before choosing caching or indexing. | Record browsing becomes noticeably slow or growth beyond dozens is expected. |
| 4 | Reduce reliance on legacy hashed-link searches. New event-ID links are direct; an old link or a missing ID may still trigger a bounded discovery scan. | Old bookmarks cause slow requests or compatibility search failures. |
| 5 | Review concurrent import collision handling. An exact preflight check is not an atomic reservation across independent clients. | Concurrent sharing/imports produce actual conflicts, or stronger no-overwrite guarantees become a requirement. |

These are deferred proposals, not implemented capabilities. Existing POS match
limits and other bounded readers remain in effect. There is no claim of complete
large-wallet discovery outside the migrated wallet Records page.

## How to resume

1. Review `AcornBackend.records_page`, `record_detail`, `record_exists`, and the
   remaining `records` callers in `app/wallets.py` and the POS/sharing routes.
   Inspect the installed Acorn implementation as well as its dependency lock.
2. Reproduce the reported issue with a disposable Acorn. Include empty filtered
   pages, many events sharing a timestamp, nested paths, parent records, and
   internal records. Never use production private keys in fixtures or logs.
3. Measure list, direct-detail, folder and POS-selection latency separately.
   Track relay query counts, timeouts and memory; avoid downloading attachments
   during discovery. Test hundreds or thousands only as scale scenarios, not as
   a statement of present usage.
4. Extend Acorn APIs where required. Keep user-key operations in Acorn and
   Nostr transport in Stroma. Any cache or index must remain reconstructible and
   must not become the authoritative copy of the user's records.
5. Preserve missing-versus-unavailable behavior, ownership and internal-record
   checks, encrypted cursor scoping, case-insensitive presentation matching,
   fingerprint labels, and QR/NFC compatibility. Do not change payment recovery.
6. Run the record and POS regression tests and `tests/test_acorn_boundary.py`,
   then the full suite. Verify using the installed dependency, not only a local
   source override. Check the docs build and test the deployed app separately.

## Acceptance checks for future changes

- A matching record beyond the first discovery page can be selected without
  disclosing unrelated or internal records to the POS.
- One matching record retains the simple existing experience; multiple matches
  remain selectable with compact, recognizable labels.
- Empty filtered pages with continuation are not treated as the end of discovery.
- Folder parents and children remain reachable across page boundaries.
- Foreign-owner, internal, deleted and unavailable records are handled safely.
- Existing QR and NFC sharing/presentation flows and Safebox Web compatibility
  remain covered by regression tests.

For now, commit/deploy the current changes and smoke-test list navigation,
opening a record and folder browsing. No additional scale work is required just
because the APIs support larger wallets.

## Optional helper index

A future PostgreSQL index could hold owner-scoped labels, paths, event IDs,
timestamps and attachment types for fast search and folder browsing. Populate it
through Acorn, update it after confirmed app operations, and reconcile external
changes with complete paginated scans. Incomplete scans must not prune entries.
Opening or acting on a result must recheck the record and authority through Acorn.

This is parked until usage justifies it. The index must be rebuildable and remain
separate from durable payment recovery and custody state. It follows
[Apps help; they do not rule](010-mainstay-principles.md#apps-help-they-do-not-rule).
