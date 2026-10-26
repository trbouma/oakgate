# Local currency and exchange rates

Choose **Preferences → Local currency**, then save. OakGate stores the currency
in `user_currency_preferences` in the instance's configured application database
(PostgreSQL in the deployed home, or SQLite where configured), keyed
by issuer/subject identity, alongside the account's language preference. It is
not a cookie, an Acorn field, or a Google/Keycloak setting. It persists across
sessions and devices even if the user clears their handle. Language, currency
and handle changes are committed together, or all rolled back on validation failure.

**Everyday Funds** (the Cash balance) shows an approximate currency amount prominently, with the
Bitcoin symbol and exact sats underneath. The same display appears at the top of
the cash transactions page. Existing balance links retain their behavior. **Community Credits** (Clear
assets) keep their own friendly units; they are not converted as if they were sats.
Cash transactions remain exclusively Acorn's history; current exchange rates do
not rewrite historical values or change existing invoices.

## Initialization and refresh

Following Safebox Web, OakGate initializes a shared currency table with metadata
for CAD, USD, EUR, GBP, JPY, INR, CNY, AUD, CHF, SGD, HKD and BRL. Rates start empty,
not with invented seed prices. Startup launches a background refresh and repeats
it hourly by default. Pages read the database cache and never wait on the provider.
No wallet identities, balances or preferences are sent to the rate provider.

The default provider is `https://blockchain.info/ticker`, using each currency's
`15m` fiat-per-BTC field as Safebox Web does. Responses are bounded and validated;
only valid positive finite rates replace cached values. A partial response preserves
the old rates and timestamps for omitted currencies. A provider error leaves all
last-known-good rates intact, including across app restarts. HTTP redirects are not
followed. A compatible operator-selected HTTPS feed can replace the default.

Rates older than 24 hours are marked stale. If the chosen rate is missing or rate
display is disabled, the exact sats balance remains visible without a fabricated
fiat value. Conversion uses decimal arithmetic; JPY estimates use whole yen and
other supported currencies use two decimal places. Balance estimates are informational. Receive entry separately validates a current
rate to create a new invoice, as described below.

The public `/rates` page lists values for one BTC, currency descriptions, last
successful refresh timestamps, stale markers and sources. Links appear at the
bottom of the account home page and the public landing page. Viewing Rates does
not read an Acorn or trigger a rate fetch.

## Configuration and deployment

```dotenv
OAKGATE_CURRENCY_RATES_ENABLED=true
OAKGATE_DEFAULT_CURRENCY=USD
OAKGATE_CURRENCY_RATE_SOURCE_URL=https://blockchain.info/ticker
OAKGATE_CURRENCY_RATE_INTERVAL_SECONDS=3600
OAKGATE_CURRENCY_RATE_STALE_SECONDS=86400
```

USD matches Safebox Web's default and applies only until a user chooses a currency.
Both intervals must be at least 60 seconds. Supported currencies are shared with
Safebox Web's metadata list. To disable background queries and fiat display, set
`OAKGATE_CURRENCY_RATES_ENABLED=false`; saved preferences and cached data are retained.

The tables are created automatically without altering existing wallet mappings or
language preferences. Normal SQLite backups include currency preferences and cached
rates; the cache itself can be rebuilt. No new dependencies or Acorn changes are
required. After committing and pushing, deploy with `./refresh-app.sh`. Keycloak
can stay running. Until the first successful refresh, balances fall back to sats.

## Receive amounts

Cash requests default to the account's preferred local currency. Users can
select any listed currency or SATS. Currency entry accepts up to two decimal
places (including JPY on this entry screen); SATS and Clear accept positive
whole numbers. Switching currencies or balances clears the entered amount.
The right-aligned keypad hides its decimal key for whole-number entry.

The sats preview rounds to the nearest whole sat, with halves rounded up. The
server validates the amount and recalculates the same conversion using the
current stored rate before creating an invoice through the existing payment
service. Missing, disabled or stale rates cannot create fiat-denominated
requests. If the rate changed since display, creation stops and the refreshed
form asks the user to review the new sats amount. No browser-supplied converted
sats value is trusted. The durable request and invoice remain denominated in
sats; existing receipt detection and settlement recovery are unchanged.
