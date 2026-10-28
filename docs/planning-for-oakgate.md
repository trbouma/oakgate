---
title: Planning for OakGate
description: Decide who operates your home, where identity and data live, and how infrastructure and recovery will be maintained before deploying Project OakGate.
---

# Planning for OakGate

Deploying Project OakGate means taking responsibility for a custodial service.
Before building containers, decide who will operate it, which infrastructure it
will depend on, and how users regain access when something goes wrong.

For a new production home, plan for **PostgreSQL from the outset for both OakGate
and home-managed Keycloak**. The installation wizard provisions the bundled
configuration in stages. It does not replace identity-provider setup, backup
operations or end-to-end acceptance checks.

## Choose the service you will operate

A **home** owns a user population, its wallet associations, custody material and
payment state. It needs an accountable operator, a support contact and a recovery
plan. Branding and a domain alone are not enough to provide that service.

A **satellite** is the planned model for extending a home's reach with a local
presence and branding, while keeping the same user population and custody at the
home. General satellite deployment is not implemented yet. Existing POS terminals
are supported delegated devices, not a complete satellite platform.

Start with a home today. If you intend to serve multiple sites later, plan around
one canonical home and its identity namespace. An independent deployment with
its own custody and users is another home, even if it shares infrastructure.
See [Home and satellite instances](037-home-and-satellite-instances.md).

## Plan participation in the OakGate network

Independent homes can serve one another's cards without merging users or custody.
Decide whether to accept any verified signing home or restrict remote requests
using `OAKGATE_CARD_TRUSTED_INSTANCES`. Plan public HTTPS reachability, stable
service identities, clock synchronization, compatible payment assets and live
two-home acceptance tests. A separate login or shared database is not required
for the visitor. See [Cross-home cards and POS](039-cross-home-pos.md).

The goal is one familiar app/card/POS experience across participating homes.
This does not imply universal credit acceptance, offline operation, shared
accounts or already-implemented satellite deployment.

## Decide where identity and data will live

| Decision | Bundled commissioning path today | Existing infrastructure option |
| --- | --- | --- |
| OakGate database | Dedicated database and restricted application role on bundled PostgreSQL | Dedicated database and roles on an existing PostgreSQL service |
| Sign-in service | Home-managed Keycloak | Existing Keycloak service with agreed realm/client configuration |
| Home-managed Keycloak database | Separate database and role on bundled PostgreSQL | Dedicated database on an existing PostgreSQL service |

These are independent architectural choices. **The current wizard implements the
bundled path only.** Existing-service combinations require a separately reviewed
configuration and provisioning procedure; they are not wizard switches. Do not
point the fresh-instance wizard at an existing populated database.

Sharing a PostgreSQL server must not mean sharing custody tables or credentials
between independent homes. Sharing Keycloak can provide common accounts, but does
not by itself combine wallets or handle namespaces. If Keycloak is externally
managed, its operator owns its database and backups; OakGate does not need that
database's credentials.

For external services, agree private connectivity, verified TLS, permissions,
capacity, maintenance windows and recovery responsibilities. See the detailed
[deployment considerations](035-new-instance.md#deployment-considerations).

## Reserve domains and plan the network

Choose stable public HTTPS origins for the wallet, Keycloak and optional POS.
The current wizard asks for all three origins, even when POS is initially disabled.
The Keycloak issuer forms part of the user-to-wallet mapping: changing it later
requires a deliberate identity migration, not simply a DNS edit.

Prepare DNS, certificates and reverse-proxy routes before commissioning. Decide
whether the proxy connects over loopback or a private network, and choose unused
host ports. Keep PostgreSQL and Redis private. Public listeners should expose
only the intended service through the chosen network and firewall policy.

For Nginx, preserve the forwarded host, protocol and port settings Keycloak needs
to recognize HTTPS. Set upload limits consistently for OakGate and the media
server; the documented 100 MiB upload allowance uses `client_max_body_size 110M;`
at the proxy. See [Keycloak operations](028-keycloak-operations.md) and
[record workflows](011-record-workflows.md).

## Prepare storage and configuration

Use SSD-backed storage for active databases and payment journals. OakGate's
[storage latency incident](022-storage-latency-incident.md) showed how shared
rotational storage can turn database writes into long waits and payment delays.
Choose capacity based on expected users, records, payment activity, retention and
measured load; this project does not publish a validated enterprise sizing tier.

On a deployment such as Beelink, `/mnt/lexar` is an example storage root, not a
required path. Confirm the disk is mounted, has sufficient space and returns
correctly after reboot. Give each service a dedicated directory with the required
ownership. Keep a missing mount from silently becoming a new empty data location.

Keep instance-specific paths, domains and settings in `.env` and the supported
Compose overrides rather than hard-coded edits to tracked deployment files.
Protect `.env`, exclude secrets from Git and preserve the selected `COMPOSE_FILE`
configuration across updates. Separate runtime database access from migration
and administrative access.

Store custody encryption keys, service identity and other credentials in protected
operator storage, with recoverable copies separate from database archives. A
backup of encrypted wallet data without its matching custody key is insufficient.
Never put actual secret values in the planning record or support logs.

## Choose sign-in and account recovery

Plan a dedicated application realm and exact client callback URLs. Decide whether
users will register themselves, which email-verification policy applies, and who
handles account recovery and administrator access.

Email registration and password recovery need an SMTP provider, an authenticated
sending domain and tested delivery. Google is optional and requires its own
provider configuration. NFC sign-in is also optional: it requires the compatible
OakGate Keycloak provider, a separate client flow, protected backchannel access
and card enrollment. Ordinary OIDC compatibility alone does not supply NFC login.

Keep an independently recoverable administrator account. Test the enabled sign-in
and recovery flows before inviting users. See [Keycloak operations and flows](028-keycloak-operations.md).

## Choose the supporting services

OakGate commissioning does not deploy every dependency used by an Acorn. Review
endpoints and operating responsibility rather than assuming community defaults
are included infrastructure.

| Capability | Plan for |
| --- | --- |
| Acorn bootstrap and wallet messages | Suitable Nostr relays, availability and retention expectations |
| Cash payments | A Cashu mint and its Lightning service; if self-operated, include node availability and recovery |
| Clear payments | The intended Clear mint and community-issued units |
| Record attachments and sharing | A suitable Blossom/Grove service, upload limits and media retention |
| OpenETR verification | Required relay and media endpoints and timeout behavior |
| Local currency display | Rate source availability and stale-rate behavior |

For each service, record who operates it, its public endpoint, and what happens
when it is unavailable. Community-run and externally operated services are valid
choices, but their storage, keys and backups are not covered automatically by an
OakGate database backup.

Choose whether to enable POS and NFC at launch. Card issuance and reading require
compatible NFC devices and browsers; a normal payment QR display does not. Test
with the actual phones or terminals you intend to use and review the
[card trust model](029-nfc-card-trust.md).

## Plan recovery before opening registration

Agree acceptable data loss and recovery time, off-host encrypted backup storage,
retention, alerting and who can restore the service. Back up both databases,
required roles, protected configuration and keys, and any infrastructure you
operate. A second directory on the same disk is not an independent backup.

The [backup and recovery plan](036-backup-and-recovery-plan.md) is a plan, not an
installed backup service. Schedule and monitor backups, then rehearse restoration
in isolation. Payment journals and recovery checkpoints matter: do not run a
restored copy alongside live payment workers or treat an uncertain payment as
permission to send it again.

Explain custody and its limits to users. Recovery disclosure is available today;
the complete Go Independent departure workflow remains planned. Enterprise use
requires measured operational readiness, not just healthy containers.

## Your deployment planning checklist

Record decisions and references to protected secret storage, never the secrets.

- [ ] Home operator, support contact and intended user population agreed.
- [ ] Database and Keycloak hosting choices documented with responsible operators.
- [ ] Wallet, identity and POS origins reserved; DNS, TLS and routing prepared.
- [ ] Linux host, Git, Python 3, Docker Engine and compatible Compose available.
- [ ] SSD storage, permissions, mount behavior, capacity and private ports checked.
- [ ] SMTP, registration, recovery and optional Google/NFC flows planned.
- [ ] Mint, relay, media and rate-service dependencies selected.
- [ ] POS/NFC device requirements and enabled capabilities agreed.
- [ ] Cross-home acceptance policy, connectivity and interoperability tests planned.
- [ ] Secrets, backups, retention, restore drills and monitoring assigned.
- [ ] Staging acceptance checks and a controlled launch agreed.

Once these decisions are made, follow [Commission a new PostgreSQL instance](035-new-instance.md).
It walks through preparation, infrastructure bootstrap, manual Keycloak setup and
application activation. Use [Local development and documentation](getting-started.md)
for a development checkout. Existing installations should follow the relevant
migration or refresh procedure rather than rerun fresh-instance commissioning.
