# Home and satellite instances

## Agreed direction

One home, one user population, many satellite access points.

A home operates the custodial service. A satellite extends its reach with a local
domain, branding and selected services, without running an independent custody
system. A clinic, community centre, merchant or event can establish its own
presence while relying on the home operator for identity, storage and recovery.

This is an agreed design direction. General satellite enrollment, API access,
branding and address aliases are not implemented by this note. Existing POS
device enrollment provides a starting point, not a complete satellite platform.

## Responsibilities

| Responsibility | Home | Satellite |
| --- | --- | --- |
| Identity | Owns canonical user mapping; uses its configured Keycloak realm | Uses the home's sign-in service |
| Handles | Enforces uniqueness centrally | Requests changes through the home API |
| Custody | Holds protected wallet material and executes Acorn operations | Holds no user private keys or custody encryption keys |
| Storage | Owns its database and authoritative user/payment state | Has no direct home database access |
| Processing | Authorizes operations, coordinates workers and recovery | Submits permitted requests and displays their status |
| Presentation | Provides the core service and operator identity | Provides approved branding, domain and local experience |
| Operations | Owns backups, upgrades and account recovery | Maintains its frontend, domain and delegated credentials |

A satellite may provide a full user interface or a narrow service such as POS.
Its capabilities must be explicit; a POS enrollment credential does not imply
permission to offer a full wallet interface. The underlying Acorn architecture
remains the same. All operations involving user private keys remain behind
Acorn methods at the home, and Nostr operations continue to use Stroma.

## Home deployment choices

Home responsibility does not require dedicated physical servers. A home may use
bundled or externally managed PostgreSQL and Keycloak while retaining its own
custody database, keys and service identity. Sharing infrastructure between homes
does not turn those homes into satellites or combine their handle namespaces.
See [deployment considerations](035-new-instance.md#deployment-considerations)
for the planned wizard choices, isolation requirements and current support limits.

## One user population

The same person signs into the same account and opens the same Acorn through
any authorized satellite. The home owns the canonical user identifier and maps
it to the Keycloak issuer and subject. Email addresses, satellite domains and
branding are not custody identifiers.

Handles are unique across the home and all its satellites. Enrollment, handle
changes and reservations go through one home API and authoritative database
constraint; satellites cannot independently allocate handles. A concurrent
claim must produce one winner and a clear conflict response, not two accounts.
Preferences and permissions are centrally managed. Site-specific branding or
preferences may be scoped separately without creating a new user identity.

An independently operated service with its own user population, custody or
ability to continue independently is another home instance. Communication
between homes uses the Mainstay service contracts; it is not satellite access.

## Shared login

Satellites use the home's Keycloak issuer. Normally each satellite has a separate
OIDC client, exact registered callback URLs and permissions appropriate to its
role. Browser applications use a flow suitable for their client type; secrets
must not be embedded in browser code. An existing Keycloak session can provide
single sign-on, subject to browser behavior and authentication policy.

Each site maintains its own session rather than sharing broad cross-domain
cookies. The home API validates token issuer, signature, lifetime, intended
audience and scopes, then checks the user's authority for the requested resource.
A valid login alone does not grant access to every wallet or every home API.

Dedicated terminals can use scoped device enrollment instead of interactive
user login. Client registration, device enrollment and user authorization are
distinct permissions. Revoking a satellite must revoke its delegated access
without deleting users or breaking their home login.

## Addresses and discovery

Each user retains a canonical receipt address at the home. For example,
`alice@home.example` remains the primary address even when the user visits a
satellite at `community.example`. If enabled, `alice@community.example` is an
alias for that same user and Acorn, not a second wallet or identity.

The home must explicitly register and verify satellite domains before serving
aliases. Satellites delegate authoritative discovery to the home rather than
maintaining competing registries. Removing a satellite or losing its domain
must not change the canonical account, handle, Acorn or home receipt address.
Aliases stop working when removed; they cannot be promised permanent availability.

The existing separation remains mandatory:

- NIP-05 resolves the user's configured social public key.
- `safebox.json` resolves the Acorn public key and relays for wallet messages,
  record sharing and direct wallet transfers.
- Lightning-address discovery advertises payment capabilities. Direct ecash
  requires the wallet discovery contract; ordinary Lightning remains available
  where appropriate. An explicit Lightning invoice is paid as an invoice.

Do not infer a wallet destination from a social public key or reintroduce legacy
NIP-05 wallet fallback through a satellite. Service public keys identify services;
a domain is a routing location, not a replacement for a pinned service identity.
Any future domain move or service-key rotation needs an explicit continuity path.

## Trust and visibility

Branding does not grant access to users' funds, records or account information.
A site operator receives only the capabilities required for the site's services.
Membership in the common population does not make a shared user directory or
cross-user data available to every satellite operator.

The interface must identify the home operator responsible for custody and
account recovery, even when the satellite has its own brand. Users should be
able to reach the canonical home directly and see which site is requesting an
operation. Sensitive actions require suitable user confirmation and home-side
policy; presenting a branded page is not authorization.

A compromised satellite frontend can still mislead users or misuse its granted
access. Minimize token lifetime and scope, support central revocation, rate limits
and audit trails, and avoid retaining sensitive user data at satellites. API
permissions must be enforced at the home, never solely by hidden UI controls.
Satellite removal does not itself end custody. Go Independent remains a separate,
explicit home-managed process with the established recovery and deletion limits.

## Availability and payment recovery

Satellites depend on home connectivity. When it is unavailable, show that clearly;
do not claim a payment succeeded or accept offline financial instructions that
might execute unexpectedly later. Independent offline operation is out of scope.

The home owns payment state, idempotency and worker coordination. A timeout at a
satellite is an unknown result, not evidence of failure. Reconnection must query
the original operation or retry with its original idempotency reference, rather
than submit a new payment. Discovery, detection and final settlement retain their
distinct meanings in the UI.

The home backup plan protects authoritative identity and custody state. Satellite
configuration and domain recovery should be recoverable without copying custody
keys. Do not run a restored home alongside its live workers. Satellite access
should remain disabled until restored revocations and payment state are reconciled.

## Work before implementation

1. Define satellite registration, domain verification, operator roles and removal.
2. Define API audiences, scopes, resource authorization and idempotency contracts
   for each satellite type, including full user interfaces and dedicated POS.
3. Specify Keycloak client provisioning, session handling and central revocation.
4. Define branding configuration and visible home-operator disclosure.
5. Specify canonical-address and alias discovery behavior, including caching and
   domain removal, while preserving the social/wallet identity separation.
6. Test concurrent handle claims, cross-user access denial, duplicate submissions,
   outages, satellite compromise and home restoration before offering the model.

See [Mainstay client roles](021-mainstay-client-roles.md),
[Safebox discovery](018-safebox-address-discovery.md),
[POS design](023-receive-only-pos.md),
[backup and recovery](036-backup-and-recovery-plan.md), and
[Go Independent](004-go-independent.md).
