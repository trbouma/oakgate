# Product direction

OakGate is a custodial application around safebox-acorn. Its purpose is to make a user's safebox more forgiving to use: familiar sign-in, retained recovery information, and less day-to-day key management.

OakGate is positioned as the primary Mainstay client for everyday use, with Safebox Web as the experimental non-custodial client. Both retain the shared Acorn architecture and the commitment to user independence. See [Mainstay client roles](021-mainstay-client-roles.md) for the product responsibilities and implementation boundaries.

## What OakGate takes responsibility for

The intended service associates an authenticated user with their safebox and retains the material needed to use and recover it. The expected recovery inventory includes the `nsec`, recovery phrase, bootstrap relay, and any additional state needed by Acorn. That inventory still needs to be verified against Acorn's implementation.

Keys and recovery details should stay out of the normal interface until the user requests them. A familiar login should open the user's existing safebox rather than require the user to handle secrets on each visit.

## A distinct custody model

| Responsibility | Safebox Web model described for this project | OakGate's intended model |
| --- | --- | --- |
| Retained user `nsec` | Not retained by the app | Protected and retained by the service |
| Everyday access | User manages key access | User signs in through Keycloak |
| Recovery | User responsibility | Managed recovery information |
| Leaving | User already holds responsibility | Explicit Go Independent process |

Custody introduces responsibilities for account recovery, protection of stored secrets, and ending access. Authentication alone does not implement these responsibilities.

The [custody models comparison](006-custody-models.md) explains the shared safebox-acorn architecture, identity-provider recovery, and the tradeoffs for unattended services such as Nostr Wallet Connect.

## An exit designed from the beginning

**Go Independent** means taking responsibility for the safebox and asking OakGate to delete the information it holds about the user. Recovery comes first; deletion follows explicit confirmation. Showing recovery material by itself does not end custody.

The complete [Go Independent design note](004-go-independent.md) records the intended experience, deletion boundaries, backup considerations, and open questions. It is an agreed direction with implementation deferred.

## What exists today

The FastAPI app supports Keycloak sign-in, connecting or creating an Acorn, encrypted recovery storage, and cash-balance display. See [Connect an Acorn](007-acorn-custody.md) for setup and verification limits. Complete independent recovery and Go Independent remain future work; see [project status](project-status.md).

## Mainstay commitments

Custody is a choice, community operation is a first-class deployment model, and Google is a replaceable upstream sign-in provider. The [Mainstay principles and review](010-mainstay-principles.md) records these requirements, the safe provider-transition boundary, and the gaps still to close. The user must retain a path to independence; the complete workflow is not implemented yet.

## Home and satellite deployment

A home can serve one user population through multiple branded satellite sites.
Satellites extend access through scoped APIs and shared sign-in; the home retains
custody, handle uniqueness, storage and recovery responsibility. This is planned
architecture, not deployed satellite support. See
[Home and satellite instances](037-home-and-satellite-instances.md).
