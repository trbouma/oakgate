# Project status

OakGate is an early-stage project. This page separates working foundations from intended capabilities.

| Area | Current state |
| --- | --- |
| FastAPI app | Landing page, logo, `/health`, and `/docs` implemented |
| Local development | Python 3.12, Poetry lockfile, automatic reload, HTTP tests |
| Container deployment | Dockerfile and Compose service prepared; build on deployment host |
| Keycloak | Instance running behind Nginx HTTPS; `oakgate` realm created |
| Google provider | Configured in Keycloak; realm login tested |
| App sign-in | Code flow with PKCE, server-side sessions, account page and logout implemented; application client setup and live verification required |
| Acorn integration and custody | Create/connect, encrypted recovery storage, and cash and Clear balance display with friendly units implemented; live relay verification pending |
| Lightning receiving and zaps | Direct-to-Acorn receiving and durable restart recovery implemented; compatibility mode default; live paid settlement and client verification pending |
| Recovery information | Phrase, nsec, relay, and native creation metadata encrypted at rest; complete independent recovery workflow pending |
| Go Independent | Design note agreed; implementation deferred |
| Documentation | MkDocs site prepared; publication depends on GitHub Pages deployment |

## Next milestones

1. Configure the `oakgate-web` client and verify app login/logout using the [setup guide](005-keycloak-sign-in.md).
2. Verify create/connect and balance readback against the deployed bootstrap relay.
3. Extend the initial custody inventory and independently verify recovery before adding further capabilities.
4. Keep Go Independent requirements visible as identity, storage, background jobs, and backups are introduced.

These are development intentions, not a release schedule. The current application is not yet a custodial safebox service.
