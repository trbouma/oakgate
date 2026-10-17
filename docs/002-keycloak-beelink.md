# First Keycloak server on Beelink

Status: Initial development setup, 2026-10-17

## Scope

Start one Keycloak container on Beelink with persistent local storage. This is the first milestone; FastAPI, Google sign-in, PostgreSQL, and Redis are not required to reach it. The broader authentication design remains a future proposal.

Use Keycloak development mode and its embedded database for this initial experiment. Docker publishes the service only on Beelink's loopback interface. Reach it through an SSH tunnel over your VPN, so the browser sees a consistent `http://localhost:8080` address. Direct access using Beelink's VPN address is intentionally not configured in this first setup.

Prerequisites: Docker Engine and the Docker Compose plugin on Beelink, plus SSH access from your computer. The SSH hostname and VPN type still need to be confirmed.

## Start on Beelink

Copy or clone the OakGate repository to Beelink, then run these commands from its root:

```sh
cp .env.example .env
chmod 600 .env
openssl rand -hex 24
```

Put the generated password in `.env` as `KC_BOOTSTRAP_ADMIN_PASSWORD`. The file is ignored by Git. Then start Keycloak:

```sh
docker compose up -d
docker compose logs --tail=100 keycloak
```

The image is pinned to `26.8.0`, the version shown in the official Docker getting-started guide consulted for this setup. The named volume retains realms and users across container recreation. Do not use `docker compose down -v` unless you intend to delete this data.

## Open from your computer

Replace `YOUR_BEELINK_SSH_TARGET` with your actual SSH alias or `user@vpn-hostname`:

```sh
ssh -N -o ExitOnForwardFailure=yes -L 8080:127.0.0.1:8080 YOUR_BEELINK_SSH_TARGET
```

Keep that terminal open, then visit <http://localhost:8080/admin/>. Port 8080 must be free on your computer. Sign in with `admin` and the password you configured.

The bootstrap account is temporary. Create a permanent administrator in the `master` realm, give it the `admin` realm role, test it in a separate browser session, and remove the bootstrap account. Changing the bootstrap password in `.env` does not reset an existing administrator's password.

Create a realm named `oakgate` from the realm selector. Keep application users and future Google configuration in that realm, separate from `master`.

## Check that it works

With the tunnel open, run on your computer:

```sh
curl --fail http://localhost:8080/realms/oakgate/.well-known/openid-configuration
```

The response should be JSON with issuer `http://localhost:8080/realms/oakgate`. Restart Keycloak with `docker compose restart keycloak` on Beelink and confirm that the realm and administrator still exist. `docker compose ps` and container logs help diagnose startup problems; this initial file does not define a readiness probe.

## Next step

Once the console and persistence checks pass, add Google as an identity provider and then the FastAPI client. The tunnel keeps a localhost callback available for initial development. Before using a shared VPN hostname, choose a stable HTTPS URL and update the issuer and callback registrations together. Move to PostgreSQL and Keycloak production mode before relying on this service beyond development. This single-container setup is not a production deployment.

## References

- [Keycloak Docker quickstart](https://www.keycloak.org/getting-started/getting-started-docker)
- [Running Keycloak in a container](https://www.keycloak.org/server/containers)
- [Bootstrap administrator lifecycle](https://www.keycloak.org/server/bootstrap-admin-recovery)
