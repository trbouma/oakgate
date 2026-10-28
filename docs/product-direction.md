# Product direction

OakGate is a custodial application around safebox-acorn. Its purpose is to make a user's safebox more forgiving to use: familiar sign-in, retained recovery information, and less day-to-day key management.

OakGate is positioned as the primary Mainstay client for everyday use, with Safebox Web as the experimental non-custodial client. Both retain the shared Acorn architecture and the commitment to user independence. See [Mainstay client roles](021-mainstay-client-roles.md) for the product responsibilities and implementation boundaries.

## User-facing language

**Everyday Funds** is the user-facing name for Cash; **Community Credits** is the
user-facing name for Clear balances. Both appear under **Your Funds**. Everyday
Funds are bitcoin-denominated, with an approximate local-currency display;
Community Credits retain each issuer's friendly name and unit. They are not
combined or automatically converted into one another.

Use these names in introductions, stories and balance descriptions. Keep **Cash**
and **Clear** for protocol, product and configuration references, and when quoting
controls that still display those terms, such as the POS asset selector.
Existing infographics may use the earlier names; their accompanying text explains
the correspondence. Configuration keys, API fields, record labels and asset
identifiers are unchanged.

## What OakGate takes responsibility for

The service associates an authenticated user with their Acorn and retains encrypted custody material, including the private key and recovery information. Recovery disclosure is implemented. A complete independent restoration rehearsal remains necessary to verify that the retained inventory is sufficient.

Keys and recovery details should stay out of the normal interface until the user requests them. A familiar login should open the user's existing safebox rather than require the user to handle secrets on each visit.

## A distinct custody model

| Responsibility | Safebox Web model described for this project | OakGate model |
| --- | --- | --- |
| Retained user `nsec` | Not retained by the app | Protected and retained by the service |
| Everyday access | User manages key access | User signs in through Keycloak |
| Recovery | User responsibility | Managed recovery information |
| Leaving | User already holds responsibility | Recovery disclosure available; full Go Independent process planned |

Custody introduces responsibilities for account recovery, protection of stored secrets, and ending access. Authentication alone does not implement these responsibilities.

The [custody models comparison](006-custody-models.md) explains the shared safebox-acorn architecture, identity-provider recovery, and the tradeoffs for unattended services such as Nostr Wallet Connect.

## An exit designed from the beginning

**Go Independent** means taking responsibility for the safebox and asking OakGate to delete the information it holds about the user. Recovery comes first; deletion follows explicit confirmation. Showing recovery material by itself does not end custody.

The complete [Go Independent design note](004-go-independent.md) records the intended experience, deletion boundaries, backup considerations, and open questions. It is an agreed direction with implementation deferred.

## What exists today

The FastAPI app supports Keycloak sign-in, connecting or creating an Acorn, encrypted recovery storage, Everyday Funds and Community Credits, payments, records, wallet messages and POS workflows. See [Connect an Acorn](007-acorn-custody.md) for setup and verification limits. Complete independent recovery and Go Independent remain future work; see [project status](project-status.md).

## Mainstay commitments

Custody is a choice, community operation is a first-class deployment model, and Google is a replaceable upstream sign-in provider. The [Mainstay principles and review](010-mainstay-principles.md) records these requirements, the safe provider-transition boundary, and the gaps still to close. The user must retain a path to independence; the complete workflow is not implemented yet.

## A connected experience across independent homes

The user-facing goal is a familiar app, card and POS experience across participating
OakGate homes. One home can serve a foreign card through its issuer, and can serve
requests from a foreign POS through that POS's home. Signed requests connect the
services while custody, private keys and user accounts remain with each home.
Current support covers NFC POS payments, balances and scoped record presentation;
local issuance/login and home-local QR approval retain their existing boundaries.

See [the illustrated architecture](user-experiences/connected-homes.md) and
[cross-home operating model](039-cross-home-pos.md). Participation policies and
compatible credit assets apply; seamless experience is the design goal, not a
claim of universal acceptance or completed live testing.

## Home and satellite deployment

A home can serve one user population through multiple branded satellite sites.
Satellites extend access through scoped APIs and shared sign-in; the home retains
custody, handle uniqueness, storage and recovery responsibility. This is planned
architecture, not deployed satellite support. See
[Home and satellite instances](037-home-and-satellite-instances.md).
