# Public service contract

OakGate follows the Mainstay HTTP service envelope with two unauthenticated JSON
endpoints. Neither reads user custody records, queries sessions, contacts relays,
or probes identity providers and mints. Both explicitly disable caching and use
`X-Content-Type-Options: nosniff`; neither enables cross-origin access by default.

## Health

`GET /health` returns `status`, `service` and `version`:

```json
{"status": "ok", "service": "oakgate", "version": "0.1.0"}
```

This reports process liveness after startup initialization. It does not establish
Redis/Keycloak availability, external reachability, commissioning, successful
settlement or backup recoverability. The app, health response, information
response and OpenAPI use one runtime version, checked against package metadata
by a test. Operators still need end-to-end deployment checks.

## Information

`GET /info` returns `name`, `version`, `description`, `capabilities`, and the
Mainstay `service_identity` object. Capabilities describe implemented software
features, not which ones are currently configured or ready for use. They do not
advertise Go Independent or commissioning.

The identity object contains exactly:

- `npub`: the persisted operator service identity, never a user Acorn identity;
- `fips_ipv6_address`: Stroma's deterministic address derived from that identity,
  not a claim of network reachability;
- `type`: `oakgate`;
- `management`: `independent` by default, or explicitly `mainstay-managed`;
- `state`: `unconfigured` without a bound identity, otherwise `uncommissioned`;
- `descriptor_event_id` and `operator`: both null until verified commissioning
  support exists.

Information uses the same identity already initialized and bound to SQLite for
zap receipts. It remains visible when Lightning receiving is disabled. Without
configured custody storage there is no initialized identity to report; public
identity fields remain null. An environment key alone is not a durable binding.
Existing startup protection against removal or replacement of a bound identity
remains in force.

## Configuration

```dotenv
OAKGATE_SERVICE_MANAGEMENT=independent
```

Use `mainstay-managed` only for a deployment actually managed by Mainstay.
This is an operator-provided management label, not verified commissioning or
permission to operate on Mainstay's behalf. No setting can make OakGate report
`commissioned`. Existing `OAKGATE_SERVICE_NSEC` remains the only service key.
No new key, database migration or credential is needed for these endpoints.

The responses deliberately exclude user identities, recovery phrases, private
keys, tokens, storage paths, account counts and connection strings. This adds
public discovery only; management/control APIs are not exposed.
