# Host Services, Networking, Security Headers & Containment

This guide covers operating the `systemd` host service graph, `epm-backup-proxy.service`, `epm-host-guardian.service`, Caddy/nftables/egress projection, live HTTP security header verification, and emergency containment on `epm-h02-host`.

---

## 1. Production Systemd Service Graph

All host daemons run under dedicated unprivileged OS identities with dropped capabilities, isolated `LoadCredential` secrets (never in argv/env or containers), and zero read access to operator business data or another service's credentials.

| Unit | Role |
| --- | --- |
| `epm-gateway.service` | Caddy `v2.11.9` running as unprivileged `User=epm-caddy` listening via private Unix admin socket; fail-closed exact host/method allowlists; `notify` readiness; reads only the generated Caddy projection (`/run/epm-projections/caddy/config.json`) produced by root-owned `epm-ingress-projection.service` / `service_runtime`. |
| `epm-tunnel.service` | `cloudflared` `2026.10.7`; receives exact 3-field Tunnel JSON via `LoadCredential` at `/run/credentials/epm-tunnel.service/tunnel.json`; exact routing + deny catch-all. |
| `epm-backup-proxy.service` | Dedicated user `epm-backup-proxy` (`uid=940`); receives R2 creds via `LoadCredential=r2.json:/etc/epm/secrets/r2.json`; listens on `/run/epm-backup-proxy/backup-proxy.sock`; resolves caller R2 prefix strictly via kernel `SO_PEERCRED` UID → `/srv/epm/data/host/backup-proxy/inventory.sqlite`. Zero dependency on Admin or ingress. |
| `epm-host-guardian.service` | Live `HostAgent` supervision (`--registry /srv/epm/data/host/stops --config /etc/epm/host-services.json`); verifies containers against `inventory.sqlite`, Caddy `Gateway`, and `ext4 prjquota`; stops containers on drift/uncertainty. |
| `epm-h03-identity.service` | Runs the shared `epm-pilot0-admin:<release>` container (`admin.epmdemo.xyz` + `login.epmdemo.xyz`; see [README.md](README.md) for current digest), projects `v3` Admin/Central/Operator routes, and relays UID-authenticated Admin source-inspection reads. |
| `epm-ingress-projection.service` | Prerequisite unit that regenerates protected Caddy/Tunnel/egress projections atomically (`ProjectionPublisher`, root `0640`, fsynced) after network setup. |
| `google-cloud-ops-agent.service` | Ships host metrics and redacted structured JSON logs to GCP Cloud Monitoring & Cloud Logging. |

---

## 2. `service_runtime` CLI & Networking Invariants

The `service_runtime` CLI runs from `/opt/epm/host-agent/bin/python` against root-owned `/etc/epm/host-services.json` (`0600` in `0700` dir):

```bash
sudo /opt/epm/host-agent/bin/python -B \
  -m app.modules.host_agent.infrastructure.service_runtime <action> \
  --config /etc/epm/host-services.json
```

- **Actions:** `network` (applies `br_netfilter` sysctls + `nftables` dual-stack bridge policy), `refresh` (regenerates protected projections), `verify` / `verify-shared` (verifies live gateway/firewall/shared-identity state), `contain` (stops exact registered runtimes).
- **Ordered Refresh:** During setup and boot, refreshes run `gateway -> egress -> tunnel` to avoid contention on the exclusive inventory lock.
- **Egress Proxy Policy:** `outbound_hosts` defaults empty with no wildcard support. The proxy admits conventional clear-SNI TLS ClientHello only (rejects ECH, SNI mismatch, redirects, and DNS rebinding), performs no TLS interception, and drops all direct metadata (`169.254.169.254`) or public routes from operator bridges.

---

## 3. Operating `epm-backup-proxy.service`

1. **Fetch R2 credentials into `/etc/epm/secrets/r2.json` (`0600`):**
   ```bash
   sudo PYTHONPATH=/opt/epm/host-agent/lib/python3.14/site-packages \
     /opt/epm/host-agent/bin/python -c \
     "import runpy; runpy.run_path('/opt/epm/app/deploy/hosted-mvp/gcp/install_services.py')['r2_credential']('project-47b72bb7-ba90-42c9-910')"
   ```
2. **Production `/etc/epm/backup-proxy.json` (`0640 root:epm-backup-proxy`):**
   ```json
   {
     "socket": "/run/epm-backup-proxy/backup-proxy.sock",
     "inventory": "/srv/epm/data/host/backup-proxy/inventory.sqlite",
     "deployment_id": "b77f7c7e-c89c-4d44-b337-e8d4f13ee46f",
     "admin_uid": 65532,
     "operator_key_refs": [
       "projects/project-47b72bb7-ba90-42c9-910/locations/us-west1/keyRings/epm-h05-recovery/cryptoKeys/operator-workspace-kek"
     ],
     "control_key_refs": [
       "projects/project-47b72bb7-ba90-42c9-910/locations/us-west1/keyRings/epm-h05-recovery/cryptoKeys/admin-control-kek"
     ]
   }
   ```
   *(Keeping `/srv/epm/data/host/backup-proxy/inventory.sqlite` separate from `/srv/epm/data/host/inventory/inventory.sqlite` lets `epm-gateway.service`'s inventory remain `0600 root:root`.)*
3. **Enable & verify:**
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now epm-backup-proxy.service
   sudo systemctl status epm-backup-proxy.service --no-pager
   sudo ls -la /run/epm-backup-proxy/backup-proxy.sock
   ```

---

## 4. Operating `epm-host-guardian.service` & Emergency Containment

- **Inspect containment alerts** (single-line JSON `{"component":"epm-host-guardian","event":"runtime_containment_attention","severity":"critical",...}`):
  ```bash
  sudo journalctl -u epm-host-guardian.service -n 50 --no-pager
  ```
- **Manual emergency stop-all** (requires neither readable inventory nor config; stops all tracked Operator containers via `StopRegistry`):
  ```bash
  sudo /opt/epm/host-agent/bin/python -B \
    -m app.modules.host_agent.infrastructure.supervisor \
    --registry /srv/epm/data/host/stops --contain-all
  ```

---

## 5. Verifying Live HTTP Security Headers

Run after any deployment or gateway refresh (note: use `GET`, not `HEAD`/`-I`, because Caddy rejects `HEAD` with `403`):

```bash
for URL in \
  https://admin.epmdemo.xyz/auth/start \
  https://login.epmdemo.xyz/auth/status \
  https://admin.epmdemo.xyz/api/admin/session; do
  echo "=== $URL ==="
  curl -sS -D - -o /dev/null "$URL" | grep -iE \
    '^(strict-transport-security|permissions-policy|x-content-type-options|content-security-policy|cache-control|referrer-policy):'
done
```

Expected headers:
- `Strict-Transport-Security: max-age=31536000; includeSubDomains`
- `Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=(), usb=()`
- `X-Content-Type-Options: nosniff`
- `Cache-Control: no-store`
- `Referrer-Policy: no-referrer`
- `Content-Security-Policy`: strict `default-src 'none'; ...; frame-ancestors 'none'; base-uri 'none'` (`script-src` only on Admin/Central HTML routes; `form-action 'none'` on JSON API routes; intentionally omitted on Firebase's `/__/auth/handler` and `/__/auth/iframe` so Google/TOTP popups function).

Routine public edge posture checks:
- `GET https://admin.epmdemo.xyz/` → `200`
- `GET https://login.epmdemo.xyz/__/auth/handler` → `200`
- `GET https://admin.epmdemo.xyz/api/admin/session` (anonymous) → `401`
- `POST https://login.epmdemo.xyz/auth/email-link` (Pilot 0 email send omitted) → `403`
- Unregistered / retired operator hostnames → `403`
