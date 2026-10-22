# Deploy and activate POS terminals

The separate `pos` service supports browser-bound device activation, encrypted terminal cookies and revocation. Receipt requests and payment collection are **not implemented yet**. Existing OakGate payment recovery and settlement remain unchanged.

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

To enable activation, generate a **separate** cookie encryption key, save it as `OAKGATE_POS_COOKIE_KEY`, and set `OAKGATE_POS_ENABLED=true`:

```sh
poetry run python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

Alternatively, on Beelink with the existing app running:

```sh
docker compose exec app python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

Keep this key in `.env` and your protected configuration backup. Do not reuse the custody encryption key or commit secrets. This operator key encrypts the terminal session cookie. It is separate from the activation key an individual user creates in Preferences.

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

Adjust the host if bound only to a VPN address. `/health` reports local process health and is the Docker check. `/ready` returns `disabled` when switched off, `connected` when enabled and OakGate is reachable with its flag enabled, or HTTP 503 with `unavailable` otherwise. A healthy container alone does not confirm connectivity. When ready, `activation_available` is true; `payments_available` remains false.

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

Use `127.0.0.1:8804` instead when Nginx runs on Beelink. Validate and reload Nginx through your normal deployment process. POS does not trust forwarded headers or derive security-sensitive URLs from them. The configured public HTTPS origin is used for CSRF and device-proof audience checks and must match the browser address exactly. Compose supplies that same origin to both app and POS.

Open the public hostname and check `/ready` through HTTPS. Then activate a terminal:

1. Sign in to the main OakGate app and ensure an Acorn is connected.
2. Open **Preferences → POS terminals**, name the device and choose **Create POS key**.
3. Save the displayed key privately; the key and its QR code are shown only once.
4. On the intended device, open the HTTPS POS site, choose **Scan activation code**
   and allow camera access. Point it at the QR code shown in Preferences. A valid
   scan starts activation automatically. Manual key entry remains available.
   Complete first activation within 24 hours.
5. Verify the terminal name and device fingerprint match the entry in Preferences.
6. Reload the POS page to check browser storage persistence. Test **Log out of terminal**,
   then sign in again using the saved key on the same browser.

Normal logout invalidates the server session but retains the browser device key.
A different browser cannot activate a bound key. If browser data is cleared or the
key is lost, revoke the terminal in Preferences and create a replacement.
**Clear local session** is an outage escape hatch that removes only the browser
cookie; use Preferences to revoke server access. Seven-day sessions require
reactivation using the original credential and browser key when they expire.

The current screen confirms activation and explains that payment collection is
coming next. It does not show balances, records or account navigation.

## Disable or stop

Set `OAKGATE_POS_ENABLED=false` and refresh both app and POS so both processes load the new setting. To stop only the POS web service:

```sh
docker compose stop pos
```

Stopping POS does not stop OakGate settlement. Terminal revocation is available in Preferences even while disabled. See the [design note](023-receive-only-pos.md).

## Activation QR privacy and camera behavior

The QR contains only the raw `ogpos1.…` activation credential, never an activation
URL. Scan it from the POS page rather than the phone's general camera app. Treat
the QR like the written key: the first browser to activate it becomes bound.
There is no public QR endpoint and the one-time response is not cacheable.

The scanner uses OakGate's bundled QR decoder and worker locally, without
third-party scripts or uploading video frames. Camera access starts only after
pressing the scan button. The camera stops on a valid scan, manual activation,
cancellation, page exit or backgrounding. Unrelated QR codes are rejected locally
and are never opened as links. If access is denied or the camera is unavailable,
enter the key manually. Test the camera flow on the intended iPad/Safari device
after deployment; automated tests exercise decoder callbacks and cancellation,
not physical camera hardware.
