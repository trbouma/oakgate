# Go Independent: custody and leaving OakGate

Date: 2026-10-17  
Status: Agreed product direction; implementation deferred

## Purpose

OakGate is intended to be a forgiving, custodial application around the capabilities of safebox-acorn. Users sign in through Keycloak and use their safebox without routinely handling keys, recovery phrases, or relay configuration.

The product distinction is deliberate: safebox-web is described in this project as stateless with respect to retained user secrets such as the `nsec`; OakGate will retain the information needed to operate and recover a user's safebox. This note records product intent, not a verified inventory of either implementation.

Custody should remain a choice. **Go Independent** is the user-facing name for ending the relationship with OakGate while continuing to use the safebox independently. It is a lasting design requirement to consider as storage, identity, recovery, and background services are introduced. It is not part of the current implementation milestone.

## Managed by default

OakGate should retain the complete recovery information for each user's safebox. The expected inventory includes the `nsec`, recovery phrase, bootstrap relay, and any additional account metadata, configuration, or state required by safebox-acorn for independent recovery.

The exact inventory and the relationships between these items must be verified against safebox-acorn before implementation. We must not assume that a phrase alone reconstructs the same account or that a key plus a relay restores every capability.

During ordinary use, this information stays out of view. Users should be able to request their recovery information through a deliberate, freshly authenticated flow. Revealing it alone does not end custody or delete the account.

## Meaning of Go Independent

Go Independent means: “I will take responsibility for my safebox. Give me what I need, then delete the information OakGate holds about me.”

This is not simply an export feature. Providing recovery information is a prerequisite to ending custody. Completion means removing OakGate's retained credentials and user associations, ending its sessions and delegated access, and stopping activity it performs for that user.

The user's safebox must remain intact and usable independently. This operation must not delete its external records, empty it, or destroy assets merely to close the OakGate account. OakGate cannot promise deletion from systems it does not control, including the user's Google account or third-party relays.

## Intended experience

1. **Explain the choice.** Describe what the user will receive, what OakGate will delete, and what OakGate will no longer be able to recover afterward. Disclose any backup or log retention before confirmation.
2. **Reauthenticate.** Require fresh authentication before revealing secrets or accepting the departure request.
3. **Prepare independent recovery.** Provide the complete recovery material and practical instructions for operating outside OakGate. Avoid sending secrets through ordinary email or recording them in logs or analytics.
4. **Verify readiness.** Give the user an opportunity to restore the same safebox in an independent client and confirm that the required capabilities work. The exact verification method remains to be designed. Merely downloading information is not evidence of recovery.
5. **Confirm departure explicitly.** Use an unambiguous final action such as **Delete my OakGate account**. Before this point the user can cancel and remain managed.
6. **End custody.** Stop new operations, resolve or safely stop in-flight work, invalidate sessions, and remove the user's retained information through a coordinated deletion process.
7. **Report the outcome honestly.** Explain what was deleted, what is still pending, and what may remain under the disclosed retention policy. Do not label a partial failure as complete.

The handover must finish before destructive deletion begins. Once deletion starts, the process needs safe retries rather than a promise that the account can be restored.

## Deletion scope and limits

The intended scope includes recovery secrets, account profiles, safebox associations, app-owned identity links, sessions, tokens, cached copies, queued work, and user-specific application records. Implementers must inventory actual storage locations rather than treating deletion of one database row as sufficient.

Keycloak needs an explicit ownership boundary: delete a dedicated OakGate identity when appropriate, but do not delete a shared Mainstay identity or disrupt unrelated applications. Remove OakGate-specific access and associations in either case. This boundary must be decided before offering departure.

Backups and logs need a stated, bounded retention policy. Avoid placing secrets in logs from the outset. If retained copies cannot be erased immediately, disclose that limitation and the expected expiry. Restoring a backup must not silently reactivate a departed user's account or custody. Any minimal deletion record needed to prevent that must itself have a defined purpose, scope, and retention period; it is an exception to “delete everything,” not something to conceal.

Deletion is not independently provable to the user. OakGate can describe its process and report execution, but cannot prove that no operator, historical backup, or other party retained a copy. Do not claim guaranteed erasure or guaranteed exclusive control after departure. Any future key rotation or migration option must be assessed against safebox-acorn's actual capabilities and must not be presumed to exist.

## Implications for future implementation

- Keep a per-user inventory of stored information and the services that hold it.
- Protect recovery secrets at rest, restrict their use, and separate encryption-key management from ordinary application data. Select the concrete mechanism later.
- Associate jobs and delegated credentials with the user so departure can stop them reliably.
- Design account creation, identity linking, and backup restoration so an interrupted or completed departure cannot silently recreate custody.
- Make deletion resumable across application storage, Keycloak, and background services, with failures visible to the user or operator as appropriate.
- Keep recovery instructions and formats independent of a live OakGate login or an OakGate-only endpoint.

## Questions to settle before implementation

- What is the complete, tested safebox-acorn recovery inventory, including any state beyond the named secrets and relay?
- Which independent client and recovery procedure will be supported?
- How will in-flight operations be handled without losing user data or assets?
- Which identity records are OakGate-owned versus shared?
- What are the backup/log retention periods, deletion retry behavior, and restore safeguards?
- How can a user follow a pending deletion without retaining an ordinary active account?

## Future acceptance criteria

Before enabling Go Independent, demonstrate independent recovery of the same safebox, removal of application access and scheduled activity, safe handling of partial failures, and prevention of account resurrection after backup restoration. The user-facing explanation must accurately describe remaining retention and the limits of deletion assurances.

No routes, deletion jobs, credential storage, or UI controls are introduced by this note. The requirement should guide the custodial design from the beginning, even though implementation comes later.

## Family principles

The user must be free to choose independence at any time, with safe completion accounting for in-flight work. Neither Google nor a functioning OakGate login may be a permanent dependency of independent recovery. The [Mainstay principles](010-mainstay-principles.md) place this commitment alongside community operation and replaceable authentication, and distinguish the commitment from current implementation.
