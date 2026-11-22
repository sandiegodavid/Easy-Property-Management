# Managed Identity Operations and Qualification Runbook (H03)

This runbook documents the repeatable operational and qualification procedures for the H03 managed identity plane (Admin origin, Central login origin, Operator auth-only boundary, Unix identity relays, and provider integration).

- Design authority: [HOSTED_MVP_H03_DESIGN.md](../design/HOSTED_MVP_H03_DESIGN.md)
- Proof specification: [identity_handoff.md](../qualification/specifications/identity_handoff.md)
- Admin account/factor recovery: [admin-account-recovery.md](admin-account-recovery.md)
- Network and host services: [network-and-host-services.md](network-and-host-services.md)

---

## 1. Component Proof and Validation Matrix

Run the H03.12 revision-2 component proof driver from `application/`:

```bash
cd application
PYTHONPATH=apps/server:. .venv/bin/python deploy/hosted-mvp/identity/qualify_identity_proof.py \
  --output ../docs/hosting/qualification/reports/HOSTED_MVP_H03_12_COMPONENT_PROOF_<YYYY-MM-DD>.json \
  --companion ../docs/hosting/qualification/reports/HOSTED_MVP_H03_12_COMPONENT_ASSERTIONS_<YYYY-MM-DD>.json
```

Validate the generated report using the read-only proof CLI:

```bash
cd application
PYTHONPATH=apps/server .venv/bin/python -m app.platform.hosted_proofs validate \
  --spec ../docs/hosting/qualification/specifications/identity_handoff.json \
  --report ../docs/hosting/qualification/reports/HOSTED_MVP_H03_12_COMPONENT_PROOF_<YYYY-MM-DD>.json
```

Expected exit code: `0` (`Valid component report: passed.`).

Run the Playwright UI component suites (requires local port binding outside a network-isolated sandbox):

```bash
cd application
npx playwright test --config playwright.components.config.ts \
  apps/web/component-tests/admin-identity.spec.ts \
  apps/web/component-tests/central-identity.spec.ts \
  apps/web/component-tests/managed-security.spec.ts \
  apps/web/component-tests/recovery.spec.ts
```

---

## 2. Candidate Packaging and Pinning

Whenever identity, gateway, or `host_agent` code changes:

1. Rebuild the pinned artifacts:
   - Admin OCI image (`application/deploy/hosted-mvp/Dockerfile.admin`)
   - Operator OCI image (`application/deploy/hosted-mvp/Dockerfile.operator`)
   - Offline Host Agent bundle (`application/deploy/hosted-mvp/archive_agent.py`)
2. Record exact SHA-256 digests for the git commit, OCI manifests, image config digests, Host Agent bundle, Caddy binary, and `cloudflared` binary in the qualification report.
3. Never promote component proof results or stale pre-change digests as deployed acceptance.

---

## 3. Native Linux Qualification (Disposable Lima Guest)

Run on a disposable native Linux guest (e.g., `epm-h03-12`) as `root` with no preexisting `table inet epm_h02` nftables policy:

1. **Shared identity routing, firewall, Cloudflare header rules, and egress proxy**:
   ```bash
   PYTHONPATH=/path/to/application/apps/server:/path/to/application/deploy/hosted-mvp/gateway \
     python3 /path/to/application/deploy/hosted-mvp/gateway/qualify_shared_identity.py \
     <synthetic-image-sha256> /usr/bin/caddy
   ```
   Verifies:
   - Matching `Cf-Connecting-Ip` + `X-Forwarded-For` returns `200`; missing, mismatched, comma-separated, or repeated headers return `403`.
   - Cross-origin paths, wrong methods, and non-tunnel local UIDs are denied.
   - `probe_as_gateway` and qualification children drop both UID and GID (never `gid=0`).
   - Private central egress proxy rejects unregistered destinations and unauthorized local callers.

2. **Two-phase reboot regeneration and post-drift closure**:
   - Phase 1 (before reboot):
     ```bash
     PYTHONPATH=/path/to/application/apps/server:/path/to/application/deploy/hosted-mvp/gateway \
       python3 /path/to/application/deploy/hosted-mvp/gateway/qualify_identity_reboot.py \
       before --caddy /usr/bin/caddy --image <synthetic-image-sha256>
     ```
   - Reboot the guest (`sudo reboot`).
   - Phase 2 (after reboot):
     ```bash
     PYTHONPATH=/path/to/application/apps/server:/path/to/application/deploy/hosted-mvp/gateway \
       python3 /path/to/application/deploy/hosted-mvp/gateway/qualify_identity_reboot.py \
       after --caddy /usr/bin/caddy
     ```
   Verifies:
   - Ephemeral `/run` projections are absent after reboot and regenerate byte-for-byte on startup.
   - Unix relay socket retains root ownership, assigned group, mode `0660`, and peer-UID enforcement.
   - After mutating `control_meta.login_origin` in `admin.sqlite`, `bootstrap.refresh()` removes all `reverse_proxy` entries, live Caddy returns `403` on Admin and login origins, and `ServiceRuntime.run("verify-shared")` rejects the drifted state.

---

## 4. GCP Shared Identity Runtime Operations

Target qualification host: `epm-h02-host` (`us-west1-b`) with persistent data disk `epm-h02-host-data` mounted at `/srv/epm/data` (`ext4`, `rw,prjquota,nodev,nosuid,noexec`).

### Routine Health & Boundary Verification
1. Verify data mount and project quota support before starting services:
   ```bash
   findmnt -no TARGET,FSTYPE,OPTIONS,UUID /srv/epm/data
   ```
2. Verify systemd units and shared registration:
   ```bash
   systemctl status epm-h03-identity.service caddy.service cloudflared.service
   ```
3. Verify public HTTPS edge posture (over verified TLS):
   - `GET https://admin.epmdemo.xyz/` -> `200`
   - `GET https://login.epmdemo.xyz/__/auth/handler` -> `200`
   - `GET https://admin.epmdemo.xyz/api/admin/session` (anonymous) -> `401`
   - `POST https://login.epmdemo.xyz/auth/email-link` (when email send is held) -> `403`
   - Unregistered / former Operator hostnames -> `403`

### Stopping the Qualification VM
Always return `epm-h02-host` to `TERMINATED` when interactive qualification is not actively running (retaining `epm-h02-host-data` with auto-delete disabled).

---

## 5. Provider Operational Checks & Incident Handling

### Google OAuth Consent & Test-User Allowlist
- Confirm Google OAuth consent screen remains in **Testing** publishing status during qualification and only approved test accounts are listed in the test-user allowlist.
- Record sanitized readback evidence (project ID, enabled providers, authorized domains, Testing status, and allowlist count — never raw tokens or private credentials).

### Mail Quota & Resend Cooldown
- Configured provider daily allowance: **10 sends/day** (billing enabled).
- Tracked application ceiling: **9 sends / rolling 24 hours** (`deployment_sends_per_day: 9` in `application/deploy/hosted-mvp/identity/selection.json`).
- Per-destination resend cooldown: **60 seconds**; per-destination hourly cap: **5/hour**; per-network hourly cap: **20/hour**.
- Never test with real customer addresses; use only dedicated test accounts.

### Provider Outage Procedure (`provider_outage_deadlines`)
- Revocation freshness window is strictly bounded to **5 minutes** (`300000 ms`).
- During a provider outage:
  - Existing sessions remain usable only until their existing `revocation_valid_until` deadline expires.
  - Once expired, requests fail closed (`503` / session paused) without extending deadlines and without falsely revoking sessions.
  - Server-authenticated HTTP `401`/`403` from Identity Platform (e.g., brief bearer refresh lag) maps to `503 ProviderUnavailable`, not `401 ProviderDenied`.
- To qualify live outage behavior: block central egress to Identity Platform after establishing an active Admin session, confirm access continues before the 5-minute deadline, confirm access pauses (`503`) once the deadline passes, then restore egress and confirm recovery without false revocation.

### Admin Account / Factor Recovery
Follow [admin-account-recovery.md](admin-account-recovery.md) for offline principal suspension, generation bump, and fresh Google + TOTP re-verification.

---

## 6. Sealing Configuration and Selecting the Identity-Only Projection

Perform only after **all** H03.12 gates pass against the same pinned candidate commit:

1. Compute the SHA-256 digest of the protected provider configuration file (never commit secrets to git).
2. Update `application/deploy/hosted-mvp/identity/selection.json`:
   - Set `provider_config_sha256` to the sealed digest.
   - Transition `configuration_state` from `"selected_not_verified"` to `"verified"`.
3. Update the H03.12 exit review report in `docs/hosting/qualification/reports/` with:
   - Exact candidate/binary/projection digests,
   - Component proof report + `hosted_proofs validate` output,
   - Native Lima reboot/isolation/drift results,
   - Deployed GCP live Google/TOTP, email-link, outage-deadline, OAuth Testing, and log-redaction evidence.
4. Keep H04/H05-owned deployed workspace-session, eligible-claim, and recovery step-up cases explicitly marked `unavailable` until H04/H05 qualification completes.
