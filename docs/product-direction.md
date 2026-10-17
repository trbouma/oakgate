# Product direction

OakGate is a custodial application around safebox-acorn. Its purpose is to make a user's safebox more forgiving to use: familiar sign-in, retained recovery information, and less day-to-day key management.

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

## An exit designed from the beginning

**Go Independent** means taking responsibility for the safebox and asking OakGate to delete the information it holds about the user. Recovery comes first; deletion follows explicit confirmation. Showing recovery material by itself does not end custody.

The complete [Go Independent design note](004-go-independent.md) records the intended experience, deletion boundaries, backup considerations, and open questions. It is an agreed direction with implementation deferred.

## What exists today

The running foundation is a FastAPI app and a separate Keycloak server. The custodial model above is a design goal, not a claim that OakGate currently stores or recovers user safeboxes. See [project status](project-status.md).
