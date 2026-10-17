# First Keycloak server on Beelink

Status: Initial development setup, 2026-10-17

## Scope

Start one Keycloak container on Beelink with persistent local storage. This is the first milestone; FastAPI, Google sign-in, PostgreSQL, and Redis are not required to reach it. The broader authentication design remains a future proposal.

Use Keycloak development mode and its embedded database for this initial experiment. Docker publishes `0.0.0.0:8800` on Beelink, forwarding to container port 8080. Other machines can connect directly using Beelink's VPN IP or hostname. The host binding covers all IPv4 interfaces; use your host firewall or VPN access controls to limit who can reach it.

Prerequisites: Docker Engine and the Docker Compose plugin on Beelink, plus SSH access from your computer. Run the deployment commands yourself over your existing SSH connection. Port 8800 must be available on Beelink.

## Start on Beelink

After the setup files have been committed and pushed, clone the repository on Beelink:

```sh
git clone https://github.com/trbouma/oakgate.git
cd oakgate
cp .env.example .env
chmod 600 .env
openssl rand -hex 24
```

Put the generated password in `.env` as `KC_BOOTSTRAP_ADMIN_PASSWORD`. The file is ignored by Git. Prepare storage as described below, then start Keycloak:

```sh
docker compose up -d
docker compose logs --tail=100 keycloak
```

The image is pinned to `26.8.0`, the version shown in the official Docker getting-started guide consulted for this setup. The bind mount retains realms and users across container recreation. Docker stores this data directly in `/mnt/bitcoin/keycloak`, rather than a Docker-managed named volume.

## External storage

Following Mainstay's configurable host-directory approach, `KEYCLOAK_DATA_DIR` selects the existing data directory on the Docker host. Its default is `/mnt/bitcoin/keycloak`, mounted at `/opt/keycloak/data` inside Keycloak. Set it in `.env` if a different location is needed.

On Beelink, before the first start:

```sh
mountpoint /mnt/bitcoin
# Continue only if the mount check succeeds.
sudo chown 1000:0 /mnt/bitcoin/keycloak
sudo chmod 700 /mnt/bitcoin/keycloak
```

These commands target the directory you already created. The pinned Keycloak image runs as UID 1000, GID 0 ([image source](https://github.com/keycloak/keycloak/blob/26.8.0/quarkus/container/Dockerfile)). These host permissions assume standard rootful Docker without user-namespace remapping.

Compose uses `create_host_path: false` so it will fail if the directory is missing instead of creating it. This does not prove the external drive is mounted: ensure `/mnt/bitcoin` is mounted before starting Docker at boot as well. The storage filesystem must support normal Linux ownership and database file locking.

This is a first-installation storage selection. If Keycloak has already stored users in the earlier `oakgate_keycloak_data` named volume, stop it and explicitly migrate that data before switching mounts; this configuration does not migrate it automatically. Keep the old volume until migration is verified. Stop Keycloak before making a filesystem backup of its embedded database.

## Update an existing deployment

From the repository directory on Beelink:

```sh
./refresh-containers.sh
```

Like Mainstay, the refresh script rejects tracked local changes and pulls with `--ff-only`, then delegates to `start-oakgate.sh --force-recreate`. Startup validates the Compose configuration and shows container status; verify readiness using the checks below. The scripts preserve the existing `.env` file and external storage directory. Review release instructions before upgrading Keycloak versions.

## Open from your computer

Visit `http://<beelink-vpn-ip-or-hostname>:8800/admin/` from another machine on your network or VPN. Replace the placeholder with Beelink's actual reachable address. Sign in with `admin` and the password you configured.

Development mode derives URLs from incoming requests, so redirects no longer point to localhost. Use the same address consistently. A previously configured realm Frontend URL, if any, must also be updated. For future OIDC clients, select a fixed HTTPS hostname before registering callbacks.

The bootstrap account is temporary. Create a permanent administrator in the `master` realm, give it the `admin` realm role, test it in a separate browser session, and remove the bootstrap account. Changing the bootstrap password in `.env` does not reset an existing administrator's password.

Create a realm named `oakgate` from the realm selector. Keep application users and future Google configuration in that realm, separate from `master`.

## Check that it works

Run on your computer, replacing `BEELINK_ADDRESS` with the same IP or hostname used in your browser:

```sh
curl --fail http://BEELINK_ADDRESS:8800/realms/oakgate/.well-known/openid-configuration
```

The response should be JSON with issuer `http://BEELINK_ADDRESS:8800/realms/oakgate`. Restart Keycloak with `docker compose restart keycloak` on Beelink and confirm that the realm and administrator still exist. `docker compose ps` and container logs help diagnose startup problems; this initial file does not define a readiness probe.

## Next step

Once the console and persistence checks pass, add Google as an identity provider and then the FastAPI client. For Google sign-in over the network, choose a stable HTTPS URL and update the issuer and callback registrations together; the current HTTP URL is for initial Keycloak setup. Move to PostgreSQL and Keycloak production mode before relying on this service beyond development. This single-container setup is not a production deployment.

## References

- [Keycloak Docker quickstart](https://www.keycloak.org/getting-started/getting-started-docker)
- [Running Keycloak in a container](https://www.keycloak.org/server/containers)
- [Bootstrap administrator lifecycle](https://www.keycloak.org/server/bootstrap-admin-recovery)
