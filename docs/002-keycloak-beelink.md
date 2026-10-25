# First Keycloak server on Beelink

For the consolidated current setup, see [Keycloak operations and sign-in flows](028-keycloak-operations.md).

Status: Initial development setup, 2026-10-17

## Scope

Start one Keycloak container on Beelink with persistent local storage. This is the first milestone; FastAPI, Google sign-in, PostgreSQL, and Redis are not required to reach it. The broader authentication design remains a future proposal.

Use Keycloak development mode and its embedded database for this initial experiment. Docker defaults to `0.0.0.0:8800` on Beelink, forwarding to container port 8080. Configure `KEYCLOAK_BIND_ADDRESS` and `KEYCLOAK_PORT` independently of the OakGate app settings. Nginx terminates HTTPS at `https://keycloak.safebox.dev` and forwards to port 8800. Restrict direct access to port 8800 to the Nginx proxy, since Keycloak trusts forwarded headers.

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
docker compose up -d keycloak
docker compose logs --tail=100 keycloak
```

The image is pinned to `26.8.0`, the version shown in the official Docker getting-started guide consulted for this setup. The bind mount retains realms and users across container recreation. Docker stores this data directly in `/mnt/lexar/keycloak`, rather than a Docker-managed named volume.

## External storage

Following Mainstay's configurable host-directory approach, `KEYCLOAK_DATA_DIR` selects the existing data directory on the Docker host. It is required, with no fallback; Beelink uses `/mnt/lexar/keycloak`, mounted at `/opt/keycloak/data` inside Keycloak.

On Beelink, before the first start:

```sh
mountpoint /mnt/lexar
# Continue only if the mount check succeeds.
sudo chown 1000:0 /mnt/lexar/keycloak
sudo chmod 700 /mnt/lexar/keycloak
```

These commands target the directory you already created. The pinned Keycloak image runs as UID 1000, GID 0 ([image source](https://github.com/keycloak/keycloak/blob/26.8.0/quarkus/container/Dockerfile)). These host permissions assume standard rootful Docker without user-namespace remapping.

Compose uses `create_host_path: false` so it will fail if the directory is missing instead of creating it. This does not prove the external drive is mounted: ensure `/mnt/lexar` is mounted before starting Docker at boot as well. The storage filesystem must support normal Linux ownership and database file locking.

This is a first-installation storage selection. If Keycloak has already stored users in the earlier `oakgate_keycloak_data` named volume, stop it and explicitly migrate that data before switching mounts; this configuration does not migrate it automatically. Keep the old volume until migration is verified. Stop Keycloak before making a filesystem backup of its embedded database.

## Update an existing deployment

From the repository directory on Beelink:

```sh
./refresh-containers.sh
```

Like Mainstay, the refresh script rejects tracked local changes and pulls with `--ff-only`, then delegates to `start-oakgate.sh --force-recreate`. Startup validates the Compose configuration, builds the FastAPI app on the deployment host, and shows container status; verify readiness using the checks below. The scripts preserve the existing `.env` file and external storage directory. Review release instructions before upgrading Keycloak versions.

## Open from your computer

Visit `https://keycloak.safebox.dev/admin/master/console/` from your browser. Sign in with `admin` and the password you configured.

Keycloak uses `KC_HOSTNAME` from `.env` (default: `https://keycloak.safebox.dev`) and accepts `X-Forwarded-*` headers from Nginx. Update any previously configured realm Frontend URL to the same HTTPS origin, or clear that override.

In the existing Nginx HTTPS server block, the proxy location should overwrite these headers:

```nginx
location / {
    proxy_pass http://127.0.0.1:8800;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Host $host;
    proxy_set_header X-Forwarded-Proto https;
    proxy_set_header X-Forwarded-Port 443;
    proxy_set_header X-Forwarded-For $remote_addr;
}
```

The upstream above assumes Nginx runs directly on Beelink. For containerized or remote Nginx, use its reachable address for Beelink instead of loopback. Keep your existing certificate directives. If Nginx runs directly on Beelink, the Docker binding can be narrowed to `127.0.0.1:8800:8080`; otherwise restrict access to the proxy through your network controls. The current `0.0.0.0` binding is retained until the proxy location is confirmed.

See [Keycloak reverse proxy configuration](https://www.keycloak.org/server/reverseproxy).

The bootstrap account is temporary. Create a permanent administrator in the `master` realm, give it the `admin` realm role, test it in a separate browser session, and remove the bootstrap account. Changing the bootstrap password in `.env` does not reset an existing administrator's password.

Create a realm named `oakgate` from the realm selector. Keep application users and future Google configuration in that realm, separate from `master`.

## Check that it works

After creating the `oakgate` realm, run on your computer:

```sh
curl --fail https://keycloak.safebox.dev/realms/oakgate/.well-known/openid-configuration
```

The response should be JSON with issuer `https://keycloak.safebox.dev/realms/oakgate`. Restart Keycloak with `docker compose restart keycloak` on Beelink and confirm that the realm and administrator still exist. `docker compose ps` and container logs help diagnose startup problems; Compose checks Keycloak readiness internally on port 9000 at `/health/ready`.

## Next step

Once the console and persistence checks pass, add Google as an identity provider and then the FastAPI client. With provider alias `google`, the Google broker callback will be `https://keycloak.safebox.dev/realms/oakgate/broker/google/endpoint`. Register the exact URI shown by Keycloak when configuring Google. Move to PostgreSQL and Keycloak production mode before relying on this service beyond development. This single-container setup is not a production deployment.

## References

- [Keycloak Docker quickstart](https://www.keycloak.org/getting-started/getting-started-docker)
- [Running Keycloak in a container](https://www.keycloak.org/server/containers)
- [Bootstrap administrator lifecycle](https://www.keycloak.org/server/bootstrap-admin-recovery)
