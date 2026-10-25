# Commission a new PostgreSQL instance

## Fresh installations only

Use `./init-instance.sh` **on the Linux deployment host** with Python 3 and a local
Docker Compose daemon. No host Poetry installation is required. It prepares both
OakGate and Keycloak on PostgreSQL from the beginning. This is not an upgrade,
restore, H2 conversion or SQLite import tool. Existing deployments use their
normal refresh scripts and the separate migration guides.

The workflow is deliberately staged. Keycloak must be running before an operator
can create the realm and clients. App/POS stay stopped until that setup is done.
A healthy container is not proof that Google, email, NFC or payments work.

The current implementation is tested with mocked container lifecycle operations,
real Compose rendering, and fresh native PostgreSQL 14 provisioning. An actual
PostgreSQL 17/Keycloak 26.8.0 container commissioning rehearsal is still required
on staging; no containers were built or run in the development environment.


## Deployment considerations

A home owns its custody and user namespace, but need not operate every underlying
server. Database hosting and identity hosting are independent choices. The simple
default is one bundled PostgreSQL server with two separate databases and roles,
and a Keycloak container managed by the home.

The wizard currently implements that bundled default only. The external-service
choices below define intended setup behavior; they are not supported wizard
switches yet. Do not work around its fixed provisioning targets by substituting
an existing production database into the fresh-instance workflow.

### Three conditional decisions

| Decision | Default | Alternative |
| --- | --- | --- |
| Where does OakGate store data? | Dedicated database on bundled PostgreSQL | Dedicated database on an existing PostgreSQL server |
| Who operates Keycloak? | Home-managed Keycloak container | Existing Keycloak service |
| If Keycloak is home-managed, where does it store data? | Separate database on bundled PostgreSQL | Dedicated database on an existing PostgreSQL server |

“Bundled” or “internal database” means PostgreSQL, not Keycloak's embedded H2
store. New home-managed production Keycloak deployments use PostgreSQL from the
outset. If Keycloak is external, its operator owns database selection, migrations
and backups; OakGate should not ask for or receive that database's credentials.

Examples include a fully bundled home, both databases on an organization's
existing PostgreSQL server with local Keycloak, or a home database with external
Keycloak. Home-managed Keycloak may use a different PostgreSQL server from
OakGate. If neither needs bundled PostgreSQL, the future wizard should omit that
container rather than start an unused database.

### Database isolation and responsibility

Each independent home requires its own OakGate database, restricted runtime role,
controlled migration role, custody encryption keys and service identity. Sharing
a PostgreSQL server must not mean sharing OakGate tables or credentials across
homes. Keycloak uses a separate database and role from OakGate, even when both
reside on the same server. Database separation is logical isolation; the server
administrator remains trusted and shared resource exhaustion can affect all users
of that server.

For an existing PostgreSQL service, the operator must choose between explicitly
authorized creation of new dedicated databases/roles or connection to ones already
provisioned by its administrator. Verify the selected target, schema state and
permissions before any writes. Refuse an unexpected populated target; do not reset
or adopt it as a fresh install. Never require persistent superuser credentials in
the application runtime merely to simplify setup.

Validate server/tool compatibility, private routing, remote TLS with certificate
and hostname verification, connection limits, latency and recovery arrangements.
Record who performs database upgrades, capacity management, backups and restore.
A managed server does not automatically supply a tested recovery plan for OakGate's
custody keys, identity associations or payment journal.

### Identity isolation and shared accounts

An existing Keycloak server can provide a separate realm for an independent user
population, or an existing realm for shared accounts and possible single sign-on.
Each home needs its own configured clients, exact callback URLs and appropriate
scopes. Sharing a realm does not automatically share Acorns, handles or custody:
those remain in each home's application database. A home and its satellites share
that application population through the home API, not simply by choosing the same
Keycloak server.

The identity operator controls authentication and is therefore part of the home's
trust boundary. Agree availability, account-recovery responsibility, administrator
access and change procedures. Preserve the issuer and subject mapping; an issuer
change is not an ordinary endpoint edit. Avoid modifying realm-wide flows or
policies for one home without assessing other clients.

If NFC login is enabled on an external Keycloak service, its operator must support
and install the compatible OakGate authenticator, configure the dedicated client
flow, and provide protected backchannel connectivity to the correct home. Standard
OIDC compatibility alone does not make OakGate NFC login available. Confirm
multi-home provider configuration and isolation before offering that combination.

### Future wizard behavior

Ask these choices before generating infrastructure credentials or Compose files.
Present a non-secret plan showing what will be created, what will be connected,
which services will run locally, and who owns backup and recovery for each part.
Confirm that plan before building containers or modifying any external service.

Generate only the required services and configuration. External-service validation
must distinguish connectivity, authentication, schema/role readiness and end-to-end
login; a healthy local container cannot prove all of them. Refresh and shutdown
operations must never stop or migrate externally managed services. Keep maintenance
credentials separate from runtime access and omit all actual secret values from
commissioning reports.

Remote dependencies add network and operator dependencies. Define outage behavior,
monitoring and coordinated maintenance, and preserve payment uncertainty holds
through connection failures. The [backup plan](036-backup-and-recovery-plan.md)
applies regardless of where the databases run. Document any limits on independent
restore when a shared Keycloak realm serves several homes.

## Home instance readiness

A fresh production home uses PostgreSQL for both OakGate and Keycloak from the
outset. SQLite is a development/legacy option, not the production commissioning
path. A home can operate on its own; future satellites are not a prerequisite.

| Area | Available now | Operator work or remaining validation |
| --- | --- | --- |
| Configuration | Guided prepare/check, generated secrets and private state | Review infrastructure defaults and back up keys |
| Databases | Separate databases/roles and initial OakGate migrations | Rehearse actual PostgreSQL 17 container provisioning |
| Authentication | PostgreSQL-backed Keycloak with NFC provider image | Configure realm, clients, email and optional Google/NFC |
| Startup | Explicit confirmation and bounded service health checks | Test real login, custody and payment behavior |
| Backups | Documented inventory, retention and restore plan | Implement scheduling, encryption, off-host copies and alerts; test restore |
| Operations | Refresh scripts and health checks | Assign operator, monitor external dependencies and rehearse upgrades |

The installation tooling is ready for a controlled staging commissioning run.
It is not yet evidence of a fully commissioned enterprise deployment. Do not open
public registration until the acceptance and recovery checks below pass.

### Before running the wizard

- [ ] Record the home operator, support contact and maintenance responsibility.
- [ ] Select the permanent app and Keycloak domains; changing the issuer later
  requires an identity migration. Reserve the POS origin the wizard requires,
  even if POS is initially disabled.
- [ ] Prepare a Linux host with Python 3, Git, Docker Engine and a Compose version
  supporting the supplied files and health waits. Record the deployed revision.
- [ ] Confirm mounted SSD storage, free space, reboot mount behavior and firewall
  rules. Private database and Redis ports must not be exposed publicly.
- [ ] Set up DNS, TLS and Nginx routes, correct forwarded headers and upload limits.
  See [Keycloak operations](028-keycloak-operations.md) and
  [record workflows](011-record-workflows.md).
- [ ] Choose verified SMTP sending credentials and an independently recoverable
  administrator account. Google and NFC are optional sign-in methods.
- [ ] Review mint, relay and media endpoints and who operates each dependency.
  Home commissioning does not deploy a mint, Lightning node, relay or blob server.
- [ ] Choose off-host backup storage, protected recovery-key custody and an alert
  destination independent of this home. Follow the
  [backup plan](036-backup-and-recovery-plan.md).

### Commissioning record

Keep a private operator checklist recording date, software/image versions, public
origins, enabled features, checks passed and unresolved issues. Record references
to secret storage, never actual passwords, card tokens, wallet keys or phrases.
Use disposable accounts and small test amounts for the acceptance checks.

A home is ready for invited users only after the complete fresh container sequence
has passed on staging, all enabled login/payment features pass, an encrypted
backup is available off-host, and a restore drill proves identity and payment
recovery without starting duplicate live workers. Agree monitoring, retention and
recovery targets before representing the deployment as enterprise-ready.

## 1. Prepare and review configuration

Clone the repository into a new deployment directory. Mount the SSD first and
choose a unique project name and unused ports. If this host already runs OakGate,
use a different project name, storage directories, domains and ports. The bootstrap
refuses containers belonging to the selected project and refuses nonempty storage.

Do not copy an old `.env` or old wallet database into this fresh deployment.

```sh
./init-instance.sh prepare
```

The prompts collect the project name, three public HTTPS origins, an existing
storage root, host bind address/ports, POS enablement and NFC-login preference.
Use loopback for Nginx on this machine, or an appropriate VPN address/`0.0.0.0`
for a proxy on another machine. IPv4 binding is supported by this wizard.
The script shows the non-secret plan and asks for `PREPARE NEW INSTANCE` before
creating anything. It then writes a **mode-0600 `.env`** and private initialization
state. It refuses to overwrite either file.

Every setting from `.env.example` is included. The script generates independent
custody/POS encryption keys, operator service identity, PostgreSQL passwords,
Keycloak bootstrap-admin password and NFC backchannel secret. Optional values
remain deliberately blank where allowed. The web client secret, and NFC client
secret if enabled, remain blank until they are obtained from Keycloak.

Review the generated settings privately before bootstrap, especially trusted
relays, bootstrap mint, media servers, limits, currency, host bindings and public
URLs. The supplied community-service defaults are choices to review, not services
created by this script. No user Acorn or user private key is generated here.
Back up the private configuration and keys separately from database backups.

The script prints commands to create four dedicated, **empty** directories owned
initially by the commissioning operator. Review and run them on the host:

- app data/work directory;
- PostgreSQL cluster directory;
- an unused H2 compatibility path required by base Compose interpolation;
- Keycloak PostgreSQL work directory.

It never creates the storage root; verify the disk is mounted before running the
printed commands. After confirmation, bootstrap changes only the empty app and
Keycloak work-directory ownership to the image users. PostgreSQL's entrypoint
initializes its own directory. Do not run the entire wizard with sudo.

```sh
./init-instance.sh check
```

This validates the required configuration and renders Compose without building
or starting services. It does not test DNS, SMTP, OAuth credentials or payment
providers. The generated dotenv dialect intentionally forbids interpolation,
quoted values and placeholders; never source `.env` as shell code.

## 2. Bootstrap infrastructure

Prepare DNS/TLS and Nginx routing for the three public origins. Keycloak must have
correct forwarded HTTPS headers; retain the NFC/backchannel and upload-limit
instructions in the existing deployment notes. Confirm selected host ports are free.

```sh
./init-instance.sh bootstrap
```

The script checks the local Docker endpoint, empty directories, available host
ports and absence of existing project containers. It prints the plan and asks for
**`BUILD NEW INSTANCE` before any build, pull or container run**.

On confirmation it:

1. Builds app and the same-version NFC-capable Keycloak image, and POS if enabled.
2. Prepares ownership of the new empty application/work directories using a
   short-lived root maintenance container; it does not run application workers.
3. Starts private PostgreSQL and Redis with bounded health waits.
4. Provisions separate `oakgate` and `keycloak` databases/roles. OakGate's initial
   Alembic schema is created through its guarded migration runner, without SQLite.
5. Grants runtime DML/revision/sequence permissions and verifies the restricted
   OakGate role. The schema-owning `oakgate_migrator` role is disabled (`NOLOGIN`,
   no retained password) after initialization; future migrations require explicit
   administrator-controlled access. Keycloak owns its separate schema and manages
   its own schema migrations.
6. Starts Keycloak in production `start` mode with PostgreSQL. App and POS do not start.

Maintenance secrets are passed to the helper through stdin, never command-line
arguments. The database container has no public port. Normal app/POS containers
receive no bootstrap administrator or migration credential. The generated
`COMPOSE_FILE` preserves all four overrides for subsequent refreshes.

Wait for the completion message and open the printed Keycloak admin-console URL.
Read the bootstrap username/password privately from `.env`. Do not paste secrets
or full configuration into logs/chat. Rotate/replace the bootstrap administrator
according to your operational policy after establishing normal admin access.

## 3. Configure Keycloak sign-in (operator steps)

In the admin console, create realm **`oakgate`**. Keep the master realm for
administration. Use your configured public origins in every entry below;
`APP_ORIGIN` and `KEYCLOAK_ORIGIN` are explanatory placeholders, not literal values.

### Standard web client

Create the configured client ID (default `oakgate-web`):

| Setting | Value |
| --- | --- |
| Protocol | OpenID Connect |
| Client authentication | On |
| Standard flow | On |
| Implicit flow, direct access grants, service accounts | Off |
| Root/Home URL | `APP_ORIGIN` |
| Valid redirect URI | `APP_ORIGIN/auth/callback` (exact, no wildcard) |
| Valid post-logout redirect URI | `APP_ORIGIN/` |
| Web origins | Empty for the server-side flow |
| PKCE method | S256 |
| ID-token signature algorithm | RS256 |

Disable Full scope allowed and configure only needed role scopes; retain the
standard identity scopes OakGate uses. Save and obtain the generated client secret
from Credentials. Keep it privately until activation prompts for it. Use a
separate client for local-development callbacks rather than production wildcards.

### Email registration and recovery

Configure SMTP in **oakgate → Realm settings → Email**, using the mail provider's
verified sending domain/sender. Test delivery. Then deliberately enable registration,
email verification and forgot-password recovery in the realm's login settings.
Test a new account and a recovery email before inviting users. Mail configuration
in `master` alone does not configure the application realm.

### Optional Google identity provider

Create the Google OAuth web client and add Google's provider in the oakgate realm.
Use the exact redirect URI displayed by Keycloak, normally:
`KEYCLOAK_ORIGIN/realms/oakgate/broker/google/endpoint`.
Google credentials stay in Keycloak; they are not OakGate's client secret.
Configure consent/test users as needed in Google and test the provider before
opening registration. Google is optional; email login must work independently.

### Optional NFC login

If selected during prepare, the image already contains the OakGate NFC provider.
Create the separate confidential client (default `oakgate-nfc`), same exact app
callback/logout URLs and its own client secret. Follow the dedicated
[NFC flow procedure](027-keycloak-nfc-login.md): create the dedicated card/PIN
browser flow, add OakGate NFC execution, and select it only as the NFC client's
browser-flow override. Do not replace the normal web client's browser flow.
The backchannel URL/secret are wired by Compose. Card enrollment and an actual
login test follow once OakGate is active.

For more detail, use [Keycloak operations and flows](028-keycloak-operations.md)
and [web sign-in setup](005-keycloak-sign-in.md), substituting your domains.

## 4. Activate OakGate and optional POS

Do not edit generated configuration after bootstrap during commissioning. Activation
checks its recorded digest so domains, keys and database destinations cannot change
silently between stages. It prompts privately for client credentials itself.

```sh
./init-instance.sh activate
```

Enter the `oakgate-web` secret and, if enabled, the `oakgate-nfc` secret. The script
validates public OIDC discovery over HTTPS and verifies the issuer exactly. This
is **not** an OAuth login or client-secret validation. Confirm the reviewed
configuration by typing **`START OAKGATE`**. Only then does it save credentials,
check database runtime access and start app/POS with bounded health waits.

Perform acceptance checks:

- [ ] Email/password login, verification and recovery.
- [ ] Google login if configured, account page and logout.
- [ ] New Acorn creation/recovery disclosure and correct receipt address.
- [ ] Small new Cash/Clear payment and receipt indication/history.
- [ ] Record upload/view/share with the intended media server.
- [ ] POS activation if enabled; NFC enrollment/login if enabled.
- [ ] PostgreSQL backups for both databases, role recovery, operator keys and a
  tested restore to an isolated environment.

After completion, use the normal refresh scripts. Do not rerun prepare/bootstrap
for upgrades or delete commissioning state to make an existing instance look new.

## Interrupted or failed setup

The state is saved before the first build/start. Bootstrap refuses to replay a
partially completed run; provisioning refuses existing roles, databases or schema.
There is no destructive reset or force flag. A lock prevents simultaneous wizard
runs. Preserve `.env`, state and any created storage; inspect the failing step
locally. The database helper may leave partial roles/schema after an interrupted
operation, so an automatic retry would be unsafe.

A failure during activation likewise retains the credentials/configuration and
state for explicit inspection and recovery with normal targeted Compose commands.
Do not regenerate keys, clear volumes, rerun grants blindly or share secret-bearing
logs. Infrastructure readiness does not replace the manual Keycloak setup or end-to-end
acceptance tests. Existing-instance migrations remain separate procedures.
