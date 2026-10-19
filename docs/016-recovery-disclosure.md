# Recovery disclosure

Preferences → View recovery information allows an active Acorn holder to reveal
their stored recovery phrase, bootstrap relay and standard/legacy recovery mode.
This is disclosure only. OakGate keeps custody and continues receiving payments;
Go Independent, deletion and settlement-aware departure remain planned.

## Fresh authentication and deliberate disclosure

A normal OakGate session does not authorize disclosure. The user submits a
CSRF-protected verification request, follows a continuation link to the configured
Keycloak provider, and signs in again. OakGate requests `prompt=login` and
`max_age=0`. The validated, signed ID token must contain a recent `auth_time`;
it must identify the same issuer/subject and the same still-active browser
session that started verification. A different account is rejected without
switching the current session. Missing/stale authentication evidence fails closed.

Reauthentication creates a two-minute, one-use authorization in the session
store. It contains the owner identifier and expiry, never the recovery phrase.
The user then acknowledges being in a private place and submits the reveal form.
The server consumes authorization atomically before reading and displaying
recovery information. Replayed forms, expired grants and logged-out sessions
cannot reveal it again. Starting verification again removes the prior grant.

The continuation link keeps the recovery page's `form-action 'self'` restriction
intact: identity-provider navigation is a link, rather than an external form
redirect. The existing callback URL is reused; no new client redirect URL or
environment variable is required. Keycloak must honor fresh authentication and
return `auth_time`. Test the deployed provider/broker flow before relying on it;
this does not independently attest to Google's authentication ceremony.

## Acorn owns recovery semantics

The adapter asks Acorn to recover the public identity from the stored phrase
and explicit legacy flag and compares it with the connected Acorn identity.
Incomplete or mismatched material produces a generic error instead of a reveal.
OakGate neither derives keys nor guesses recovery mode. No nsec is included in
the response. Save all three displayed fields together.

The tests cover standard and legacy identity recovery. This verifies the key
mapping, not a complete independent restoration of funds, records or blobs.
Those still depend on the correct relay, mint, storage state and availability.

## Handling the disclosed secret

Recovery responses disable caching and framing and restrict scripts and resources
to the app origin. The phrase is rendered only in the authorized POST response,
not ordinary Preferences/GET responses, URLs, hidden inputs or Redis. It is not
logged. Browser-side code removes it after two minutes, when hidden manually,
on leaving the tab, and before/after a browser history cache restoration.

These display controls require JavaScript and cannot revoke a screenshot,
clipboard copy, browser extension access or previously delivered response bytes.
The screen explains the risk and asks the user to keep a safe private copy.
There is no automatic clipboard, download or recovery verification marker.
Existing encrypted custody storage and backup requirements remain unchanged.

## Acceptance checks

Automated checks exercise signed OIDC reauthentication, account/session mismatch,
missing/stale authentication time, CSRF, expired and repeated grants, standard
and legacy recovery, and mismatched stored material. A synthetic browser flow
checks navigation and mobile disclosure/hiding. Live Keycloak reauthentication
and independent wallet restoration remain deployment acceptance checks.
