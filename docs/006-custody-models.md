# OakGate and safebox-web custody models

Date: 2026-10-17  
Status: Product design; initial custody storage implemented, unattended services and Go Independent deferred

## The same safebox-acorn architecture

OakGate and safebox-web use the same underlying safebox-acorn architecture. The distinction is who retains the user's secrets, who takes responsibility for recovery, and who can act on the user's behalf when they are away.

OakGate provides a **custodial cloak** around safebox-acorn for users who choose to place more trust in a provider. It is intended to make the same capabilities accessible through familiar sign-in, managed recovery, and services that can keep operating without an open browser. This choice does not require a different safebox architecture underneath.

Safebox-web takes the non-custodial approach: the service does not retain the user's secret information. Users keep responsibility for their keys and recovery material. Here, “does not store secrets” describes retained service-side custody; it does not mean that an authorized operation never needs access to a key while it runs.

## Identity recovery and safebox recovery

OakGate uses Keycloak to connect to an identity provider such as Google. That provider has its own account-recovery process. A user who loses access to their sign-in can follow that process to regain their identity account and, subject to OakGate's access controls, return to their existing safebox.

OakGate would separately retain the material needed to operate and recover that safebox: the `nsec`, recovery phrase, bootstrap relay, and any other required Acorn configuration or state. These details stay out of the ordinary interface unless the user requests them. The complete recovery inventory must be verified against safebox-acorn before implementing storage.

These are two connected recovery responsibilities. The identity provider recovers access to the identity account; OakGate preserves the safebox material and its association with that identity. Recovering a Google account cannot reconstruct secrets that OakGate has lost. Conversely, possession of the safebox recovery material should support independent use without relying on a live OakGate login.

In safebox-web, recovering a sign-in account cannot replace a missing safebox secret. The user must retain sufficient recovery material themselves. If all usable copies are lost, the non-custodial service has no retained copy to return.

## Practical tradeoffs

| Consideration | OakGate custodial model | safebox-web non-custodial model |
| --- | --- | --- |
| Everyday access | Familiar identity-provider sign-in; keys handled by the service | User supplies or manages access to their own keys |
| Retained secrets | Provider holds the `nsec`, recovery phrase, and required recovery information | Service retains no user secret information |
| Recovery burden | Shared between the identity provider, OakGate, and the user | User is responsible for preserving recovery material |
| Unattended services | Provider can operate authorized services while the user is away | Requires a user-operated online signer or an explicit delegation arrangement |
| Trust | User trusts the provider to protect and correctly use retained secrets | User relies less on a provider's continued custody, while still trusting the software they use |
| Failure exposure | Provider compromise, misuse, outages, or account lockout can affect access and control | Lost secrets, unsafe backups, or compromise of the user's device can defeat recovery or control |
| Operational burden | Provider manages secret storage, service availability, recovery, and deletion | User manages secret protection and any independent online services |
| Leaving | Requires a deliberate handover and end to provider custody | User already carries responsibility for their secrets |

OakGate's main advantage is convenience with a more forgiving recovery experience. Retaining secrets also makes the provider a valuable target and gives it substantial authority. A compromised identity account may become a route to the safebox, so ordinary sign-in, recovery, revealing secrets, and changing custody need deliberately designed access controls.

Safebox-web's main advantage is that its operator has no retained store of user secrets to lose, misuse, or withhold. The cost is greater responsibility for the user. Non-custody does not eliminate trust in delivered software, nor protect a secret that is exposed on a compromised device.

## Online services and Nostr Wallet Connect

A major limitation of the non-custodial web model is unattended operation. When the user closes the browser, safebox-web cannot continue performing secret-dependent operations on their behalf without an available signer or delegated authority.

Nostr Wallet Connect illustrates this tradeoff. A wallet service needs to remain online to receive requests and carry out authorized operations. The protocol does not inherently require custody, but the service needs an available source of the authority required to act. A web app that retains no secrets cannot, by itself, promise that service while the user is absent.

A non-custodial user can run their own online wallet service or signer. That preserves their control but adds setup, availability, and operational responsibilities. Delegating authority to another service is another choice, with its own trust boundary.

OakGate's intended custodial model makes it possible for the provider to run such services for the user. Storing a key alone does not implement Nostr Wallet Connect: request handling, user consent, spending limits, revocation, and reliable background operation still need to be built. Custody enables that product direction; it does not imply permission for unrestricted activity.

## Custody remains a choice

Neither model is the right fit for every user. Some people prefer responsibility for their own secrets and infrastructure. Others prefer a familiar account and a provider that takes on recovery and online operation. OakGate offers that second relationship while preserving the underlying safebox-acorn architecture.

The [Go Independent](004-go-independent.md) design keeps the path out of custody visible from the beginning. A user should be able to obtain and verify the complete recovery material, take responsibility for their safebox, and ask OakGate to stop acting for them and destroy the information it holds about them.

That departure must include background services and delegated access, not just the account record. Deletion cannot prove that no provider ever retained a copy, and any backup retention must be disclosed. The shared architecture supports the intended continuity of the safebox, but the actual independent recovery procedure still needs to be implemented and tested.

## Current implementation boundary

OakGate's Keycloak and Google sign-in and sign-out flow is working. The [initial Acorn integration](007-acorn-custody.md) implements creation, connection by recovery phrase, encrypted secret storage, and cash-balance display. Complete independent recovery, unattended wallet services, and Go Independent remain product requirements. This comparison should guide those future implementation decisions.
