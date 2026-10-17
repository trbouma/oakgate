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
| Acorn integration and custody | Product direction agreed; implementation pending |
| Recovery information | Inventory and storage design pending |
| Go Independent | Design note agreed; implementation deferred |
| Documentation | MkDocs site prepared; publication depends on GitHub Pages deployment |

## Next milestones

1. Configure the `oakgate-web` client and verify app login/logout using the [setup guide](005-keycloak-sign-in.md).
2. Inspect Acorn's account and recovery capabilities before choosing custodial storage.
3. Establish the first sign-in → create or retrieve safebox → display status flow.
4. Keep Go Independent requirements visible as identity, storage, background jobs, and backups are introduced.

These are development intentions, not a release schedule. The current application is not yet a custodial safebox service.
