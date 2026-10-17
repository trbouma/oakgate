# Connect an Acorn to OakGate

Date: 2026-10-17

After signing in, a user can connect an existing Acorn with its recovery phrase and bootstrap relay, or create a new Acorn. Each Keycloak identity can hold one connection. The account page reads the connected Acorn's cash balance in sats.

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
