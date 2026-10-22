# Deploy the POS foundation

The separate `pos` service provides a landing page, health check and connection check to OakGate. Device activation, cookies and receipt requests are **not implemented yet**. Enabling the switch does not enable payment collection. Existing OakGate payment recovery and settlement remain unchanged.

POS uses the same repository and Dockerfile, with its own application entry point and independently built service image. It has no custody volume, wallet keys, OIDC secrets or settlement worker. The Compose `pos` profile keeps it out of the default deployment.

## Configure Beelink

After committing and pushing these changes, add these values to the deployment `.env`:

```dotenv
OAKGATE_POS_ENABLED=false
OAKGATE_POS_PUBLIC_URL=https://pos.oakgate.safebox.dev
OAKGATE_POS_BIND_ADDRESS=127.0.0.1
OAKGATE_POS_PORT=8804
OAKGATE_POS_API_URL=http://app:8000
OAKGATE_POS_COOKIE_KEY=
```

Use the Beelink VPN address or `0.0.0.0` for the bind address if Nginx runs on another machine. Restrict access to the intended proxy network. The API URL is the internal Compose address, not the browser-facing URL. Keep existing OakGate and Keycloak data directory settings unchanged.

To enable the connection check, generate a **separate** cookie encryption key, save it as `OAKGATE_POS_COOKIE_KEY`, and set `OAKGATE_POS_ENABLED=true`:

```sh
poetry run python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

Alternatively, on Beelink with the existing app running:

```sh
docker compose exec app python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

Keep this key in `.env` and your protected configuration backup. Do not reuse the custody encryption key or commit secrets. The key is validated now and reserved for future POS cookies; no terminal cookies are issued in this foundation.

## Deploy independently

From the OakGate checkout on Beelink, with a clean tracked working tree:

```sh
mountpoint /mnt/lexar
./refresh-app.sh
./refresh-pos.sh
```

The app refresh loads the dedicated POS API and enablement flag. The POS refresh builds only the POS service and waits up to 120 seconds for Docker health. It leaves OakGate, Keycloak and Redis running. Use `--timeout 300` if required. Do not run refresh scripts concurrently. Both scripts pull fast-forward changes first, so commit and push before deploying.

For a manual POS start without a Git refresh:

```sh
docker compose up -d --build --no-deps pos
```

Explicitly targeting `pos` activates its profile. Do not enable `COMPOSE_PROFILES=pos` globally; use the dedicated refresh script. No Docker build or container startup is required in the development environment.

## Check the service

```sh
docker compose ps pos
curl --max-time 5 http://127.0.0.1:8804/health
curl --max-time 5 http://127.0.0.1:8804/ready
```

Adjust the host if bound only to a VPN address. `/health` reports local process health and is the Docker check. `/ready` returns `disabled` when switched off, `connected` when enabled and OakGate is reachable with its flag enabled, or HTTP 503 with `unavailable` otherwise. A healthy container alone does not confirm connectivity. All responses explicitly leave activation unavailable.

## Nginx

Create the DNS record and TLS virtual host for `pos.oakgate.safebox.dev`. Inside that HTTPS server block, use:

```nginx
location / {
    proxy_pass http://100.70.55.66:8804;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
    proxy_set_header X-Forwarded-Port 443;
}
```

Use `127.0.0.1:8804` instead when Nginx runs on Beelink. Validate and reload Nginx through your normal deployment process. The foundation does not trust forwarded headers or derive security-sensitive URLs from them; the configured public HTTPS origin will be used for future activation.

Open the public hostname and check `/ready` through HTTPS. The page deliberately offers no account login or key-entry form yet.

## Disable or stop

Set `OAKGATE_POS_ENABLED=false` and refresh both app and POS so both processes load the new setting. To stop only the POS web service:

```sh
docker compose stop pos
```

Stopping POS does not stop OakGate settlement. Terminal credential revocation and device management will be implemented with the receive-only authorization flow described in the [design note](023-receive-only-pos.md).
