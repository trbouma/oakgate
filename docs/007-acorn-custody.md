# Connect an Acorn to OakGate

Date: 2026-10-17

After signing in, a user can connect an existing Acorn with its recovery phrase and bootstrap relay, or create a new Acorn. Each Keycloak identity can hold one connection. The account page reads the connected Acorn's cash balance in sats and displays Clear balances separately.

## User experience

**Connect an existing Acorn** derives the key with Acorn's recovery function and loads the existing wallet from the supplied relay. Invalid phrases, missing wallet records, and relay failures leave the account unconnected. This operation never creates a replacement wallet. The optional legacy checkbox corresponds to Acorn's older key derivation.

**Create a new Acorn** defaults to `wss://spurline.safebox.dev`. OakGate uses Acorn to generate a 24-word phrase and native wallet metadata. It encrypts and saves that material before publishing to the relay. An interrupted setup remains pending; **Retry setup** uses the same identity and metadata, even after an app restart. Relay readback must succeed before the connection is marked active.

Both choices require the user to acknowledge custody. Once connected, the choices are replaced by the cash balance and a refresh link. A relay failure shows an unavailable balance, not zero. The displayed amount is Acorn's relay-loaded cash-proof balance; OakGate does not check spendability with each mint or combine Clear balances with cash.

## Local development

Use `poetry install` and configure these values in `.env.dev`:

```dotenv
OAKGATE_CUSTODY_KEY=<generated Fernet key>
OAKGATE_DATA_DIR=.oakgate
OAKGATE_BOOTSTRAP_RELAY=wss://spurline.safebox.dev
OAKGATE_ALLOWED_RELAYS=wss://spurline.safebox.dev
```

Generate a key once with:

```sh
poetry run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Restart `./dev.sh` after changing the environment. Keep the key: regenerating it does not migrate existing encrypted data. `.env.dev` and `.oakgate/` are ignored by Git. Without a custody key, sign-in still works and the account page explains that storage is not configured.

## Deploy on Beelink

Prepare a separate directory on the mounted external drive:

```sh
mountpoint /mnt/bitcoin
# Continue only if the mount check succeeds.
sudo install -d -o 10001 -g 10001 -m 700 /mnt/bitcoin/oakgate
```

Add the same settings to Beelink's `.env`, using `OAKGATE_DATA_DIR=/mnt/bitcoin/oakgate` and a separately generated deployment key. If Poetry is unavailable on Beelink, generate the key with the command above on your development machine and transfer it privately. Do not replace the existing Keycloak or OIDC secrets.

```sh
docker compose up -d --build app
```

Compose maps this host directory to `/app/data`. The image installs the locked Acorn dependency during its build on Beelink. No local Docker build is needed. Keycloak keeps its existing `/mnt/bitcoin/keycloak` mount; Redis remains disposable session storage.

A new host must create the app data directory before starting Compose, even if custody has not yet been enabled. Docker will not silently create an incorrectly owned directory.

## Storage and identity

The SQLite custody store encrypts the `nsec`, submitted or generated phrase, bootstrap relay, public identity, derivation mode, and initial creation metadata using Fernet. The encryption key is supplied separately through the environment. Database indexes contain hashes of the identity pair and wallet public key, plus setup status and a short operation lease.

The owner is Keycloak's exact `(issuer, subject)` pair, never an email address. Uniqueness constraints prevent replacing an existing connection or associating the same Acorn with a second OakGate identity. A database lease serializes setup retries across processes; network operations have a shorter timeout than the lease.

Recovery material is never put in login sessions, browser cookies, HTML responses, or URLs. The account template receives only public identity, status, and balance. Request sizes are bounded and all setup actions require authentication and a session-bound CSRF token. Provider exception details are not returned or logged by these routes.

Encryption protects the stored database, not against a compromised application process that holds the key. Back up the database and key separately. Stop the app or use SQLite's backup API when taking a consistent database backup. Losing either can prevent OakGate from recovering its custody records. Keep test wallets separate from production wallets.

## Bootstrap relays

`OAKGATE_ALLOWED_RELAYS` is a comma-separated list of exact operator-approved `wss://` URLs. The default bootstrap relay must be in that list. To connect an Acorn on another relay, the operator must first add its URL and restart the app. User-submitted URLs cannot make arbitrary requests from the server into the operator's network. Approve only trusted relay endpoints; this allowlist is not a general-purpose outbound network sandbox.

## Scope and validation

OakGate pins safebox-acorn to revision `20c0663c55ddd188e1486f7ebdb540c173c19527`. The adapter uses `generate_seed_phrase_and_nsec`, `recover_nsec_from_seed`, `create_instance`, `set_wallet_info`, `load_data`, and `get_balance`. Creation captures Acorn's native metadata locally before publishing; this preserves all generated metadata on retries. The adapter isolates Acorn's mutable class defaults for each wallet instance.

Automated tests cover real offline Acorn generation and derivation, encrypted restart recovery, ownership isolation, duplicate connections, pending setup retries, unavailable balances, and request protections. Relay operations are simulated in the suite. A live create/connect/readback test on your relay remains part of deployment verification; no funded wallet or recovery phrase is used by these tests.

This slice does not implement payments, Nostr Wallet Connect, secret revelation, connection replacement, deletion, or Go Independent. Stored recovery material keeps the [Go Independent design](004-go-independent.md) possible, but the full independent recovery and deletion workflow is still to be built. Additional Acorn recovery state may be required as further capabilities are introduced.

## Clear balances and friendly units

The account page calls Acorn's `get_clear_balances()` to read held Clear proofs. Each mint, canonical unit, and keyset remains a separate balance, even if friendly labels happen to be identical. Clear amounts are never added to cash or to other units. Pending receipts are not included, and displaying a balance does not perform a payment or check mint spendability.

Following Safebox Web, OakGate reads `/v1/keysets` from the mint and matches the balance's exact unit and keyset ID. `friendly_alias` (or `friendly_name`) supplies the name; `friendly_unit_alias` supplies the displayed unit. The issuer and expandable asset details keep the underlying mint, unit, and keyset visible. Missing or unavailable metadata falls back to the canonical unit without hiding the amount.

Metadata requests use public HTTPS endpoints, validate DNS answers at connection time, disallow redirects, and have short timeouts and a 64 KiB response limit. Private-network mints still have balances displayed, but their friendly labels are not fetched by this initial implementation. Labels are cached in memory for five minutes; failures are retried after 30 seconds. No wallet secrets are sent to the mint metadata endpoint.

Cash and Clear reads run independently. A Clear relay failure displays “Clear balances unavailable,” while a successful empty result displays “No Clear balances yet.” The **Refresh balances** link reloads both. Tests cover exact label matching, fallback behavior, escaping, and partial outages; verify the displayed friendly names against your live mint after deployment.

## Records

The signed-in account navigation switches between **Balances**, **Records**, and **Preferences**. Records lists user-record labels in descending event-timestamp order, with alphabetical ordering for ties. It reads Acorn's standard stored user records (kind 37375); Acorn filters its internal wallet records. The list shows labels only. Clicking a label opens a read-only detail page with the record payload rendered as escaped text or indented JSON. HTML is not executed, and external content is not fetched. There is no editing or deletion.

Detail URLs contain an opaque record reference and resolve only against the signed-in user's Acorn user-record listing, not arbitrary internal labels. Missing records return 404; unavailable reads return 503 without exposing provider errors.

The reader uses Acorn's configured record query limit and does not paginate older relay results in this first version. Reported relay/decryption failures show an unavailable state rather than an empty list. The responsive list wraps long labels, and both navigation links remain available on phone and desktop layouts.

## Preferences and unique handles

Preferences lets a signed-in user set, change, or clear a custom OakGate handle. A saved handle is used in the account greeting. It does not change the Acorn public identity or Keycloak account.

Handles use 3–32 ASCII letters, numbers, hyphens, or underscores, beginning with a letter or number. Surrounding whitespace is removed. Display capitalization is preserved, while lowercase normalization makes `Tim` and `tim` the same claim. Clearing or changing a handle releases the old name for reuse; these are display preferences, not immutable identifiers or login credentials.

The existing persistent SQLite database (`/mnt/bitcoin/oakgate/custody.sqlite3` on Beelink) contains a separate `user_preferences` table, created automatically at startup. Each row is keyed by the hash of the exact Keycloak issuer/subject pair. A UNIQUE constraint on `normalized_handle` enforces uniqueness across all users sharing this database, including simultaneous requests. Failed claims preserve the user's previous handle. Multiple independent database copies do not share a handle namespace.

Handle fields are stored as ordinary text for indexing; custody secrets remain encrypted separately. Database backups include preferences, and any future Go Independent deletion must remove the preference row as well. No new mount, secret, or environment setting is required, but the existing custody storage must be configured before preferences can be saved.

See [Identity mapping storage and backups](008-identity-storage-backups.md) for the Google-to-Keycloak ownership chain, Redis session lifecycle, and coordinated recovery requirements.


## Cash transaction history

Click the cash balance to open **Cash transactions**. The page shows the current balance and the ten newest transactions as cards, read only from the user’s Acorn relay history. OakGate’s local payment journal is not included. A received payment appears here only when a transaction-history entry exists in the Acorn. OakGate now calls Acorn’s `add_tx_history()` to write that native entry after crediting each incoming Lightning payment or zap, and backfills retained completed payments after upgrade. History writes are verified and retried without repeating the payment. Cards show direction, date (UTC), sats, fees, available historical balance and notes; a missing historical balance is shown as a dash. Sent amounts include fees, following Safebox Web's presentation.

Click the balance on the transaction page to return to the main Balances page. Cash history is read-only, protected by the existing account session, and never includes private keys, proofs or payment preimages. If Acorn history is unavailable, the page shows an error rather than substituting local journal entries or reporting an empty history. Clear balance headings, amounts and details are centred on the main page.

## Record file previews

Record details use the same presentation helpers and locally served PDF.js viewer
as Safebox Web: images, PDFs, Apple Wallet passes, JSON VC/VP credentials and
mdoc containers (including mDL and EUDI PID). Other file types remain downloadable.
Plain text stays escaped; record HTML and SVG never execute in the page.
Credential previews decode contents but do not verify issuer or holder proofs.

Every file request authenticates the session and resolves the opaque record
reference within that user's Acorn. Acorn retrieves and decrypts files through
its `get_record_blobdata(public_only=True)` path, using bounded Stroma Blossom
retrieval with public-address checks. Private HTTP/local Blossom routes require
a future explicitly trusted infrastructure policy. Preview failures leave the
record readable and downloads retryable. No decrypted files are saved to disk
or placed in a shared application cache.

This requires the Acorn revision introducing `public_only`; publish that change
and update OakGate's lockfile before deploying. Previews do not add sharing,
editing, deletion or credential-verification workflows.
