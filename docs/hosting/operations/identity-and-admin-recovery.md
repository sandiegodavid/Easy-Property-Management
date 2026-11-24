# Managed Identity Operations & Admin Account/Control Recovery

This guide covers managed identity operations (`admin.epmdemo.xyz`, `login.epmdemo.xyz`), Google OAuth allowlist & mail-quota management, provider outage handling, offline Admin principal recovery (`admin_bootstrap`), and Admin control-plane recovery.

---

## 1. Provider Configuration, OAuth Allowlist & Mail Quotas

### Google OAuth Consent & Test-User Allowlist (Pilot 0)
- Google OAuth consent screen runs in **Testing** mode in GCP project `project-47b72bb7-ba90-42c9-910` (limit: 100 test users; Production verification is deferred until before H12).
- Before an invited Pilot 0 operator can sign in, add their exact Google email address under **GCP Console → Google Auth Platform → Audience → Test users**.
- Remove retired operators from the Test users allowlist on Day 7+ retirement.

### Email-Link Quota & Re-Pinning `selection.json`
- **Confirmed provider allowance:** `100 sends/day` (`provider_sends_per_day: 100`); tracked application ceiling: `90 sends / rolling 24h` (`deployment_sends_per_day: 90`); resend cooldown `60s`; per-destination `5/hour`; per-network `20/hour`.
- In Pilot 0, Operator sign-in uses **Continue with Google** (the email-link send route is omitted on `login.epmdemo.xyz`).
- Whenever `/etc/epm/h0312/provider.json` changes on `epm-h02-host`, update it atomically (preserving mode/owner) and re-pin its SHA-256 in both `application/deploy/hosted-mvp/identity/selection.json` and `/etc/epm/h0312/setup.json`:
  ```bash
  gcloud compute ssh epm-h02-host \
    --project=project-47b72bb7-ba90-42c9-910 --zone=us-west1-b --tunnel-through-iap \
    --command="sudo python3 -c '
  import json, os, hashlib
  p = \"/etc/epm/h0312/provider.json\"
  st = os.stat(p)
  d = json.loads(open(p, \"rb\").read())
  d[\"provider_email_sends_per_day\"] = 100
  new_raw = (json.dumps(d, indent=2) + \"\n\").encode(\"utf-8\")
  tmp = p + \".tmp\"
  with open(tmp, \"wb\") as f: f.write(new_raw)
  os.chmod(tmp, st.st_mode & 0o7777); os.chown(tmp, st.st_uid, st.st_gid)
  os.replace(tmp, p)
  print(\"NEW_SHA256=\" + hashlib.sha256(new_raw).hexdigest())
  '"
  ```
  Verify locally:
  ```bash
  cd application
  PYTHONPATH=apps/server .venv/bin/pytest \
    apps/server/app/modules/hosted_access/tests/test_identity_contracts.py \
    apps/server/app/modules/hosted_access/tests/test_provider_boundaries.py
  ```

### Provider Outage Procedure (`5-minute` Freshness Window)
- Revocation freshness is strictly bounded to **5 minutes (`300000 ms`)**.
- During an Identity Platform outage:
  - Existing sessions remain usable only until their existing `revocation_valid_until` deadline expires.
  - Once expired, requests fail closed (`503` / session paused) without extending deadlines and without falsely revoking sessions.
  - Server-authenticated HTTP `401`/`403` from Identity Platform (e.g., brief bearer refresh lag) maps to `503 ProviderUnavailable`, not `401 ProviderDenied`.
  - Once connectivity recovers, active sessions resume normally without forced re-onboarding.

---

## 2. Offline Admin Principal & Factor Recovery (`admin_bootstrap`)

Admin principals are bound by exact verified realm alias (`identity-epmdemo-v1`) and provider subject UID (never email alone).

1. **Stop the owning Admin writer** (`sudo systemctl stop epm-h03-identity.service`) before running offline mutations.
2. **Inspect the principal** (as the Admin store owner, using canonical paths):
   ```bash
   python -m app.modules.hosted_access.infrastructure.admin_bootstrap inspect \
     --database "$EPM_ADMIN_DATABASE" \
     --writer-lock "$EPM_ADMIN_WRITER_LOCK" \
     --setup "$EPM_IDENTITY_SETUP" \
     --application-directory "$EPM_APPLICATION_DIRECTORY" \
     --subject "$EPM_PROVIDER_SUBJECT"
   ```
3. **Actions (same base arguments):**
   - **Initial setup:** `bootstrap` with the explicitly approved subject (idempotent if already enabled).
   - **Lost TOTP factor or suspected compromise:** run `suspend --expected-revision <inspected_revision>`. This disables the principal and advances the generation checked by all Admin sessions.
   - **Provider recovery:** Revoke existing provider sessions and compromised factors in Firebase/Google Identity Platform; confirm control of the recovered account and verify its exact subject UID.
   - **Restore or replace:** For the same subject, inspect the suspended principal and run `restore --expected-revision <current_revision>`. If the subject changed, leave the old principal suspended and `bootstrap` the replacement explicitly.
4. **Restart Admin** (`sudo systemctl start epm-h03-identity.service`), complete fresh Google + TOTP sign-in, and confirm previously issued Admin sessions are rejected.

*(Principal mutations and `admin_audit` entries commit together; on a lost response, inspect the current state and revision before retrying.)*

---

## 3. Admin Control-Plane Recovery (Damaged `admin.sqlite`, D5)

To enable automatic D5 recovery-mode fallback, the protected Admin deployment JSON (`0600`) includes:

```json
{
  "admin_recovery_database": "/control/admin-recovery/admin-recovery.sqlite",
  "bootstrap_authority": "/run/epm/admin-recovery-authority.json",
  "control_root": "/control/admin-control",
  "scratch_root": "/control/admin-scratch",
  "backup_proxy_socket": "/control/backup-proxy/backup-proxy.sock",
  "backup_proxy_uid": 940,
  "release_ref": "rel-hosted-mvp"
}
```

When `admin.sqlite` is missing or corrupted on boot:
1. `shared_identity_entry.py` automatically falls back to `create_admin_recovery_app()` on `admin.epmdemo.xyz` (authenticating strictly against `/run/epm/admin-recovery-authority.json` + Google + TOTP MFA + live Firebase revocation) and returns `503 {"code":"admin_recovery_mode_active"}` on `login.epmdemo.xyz`.
2. Sign in to `https://admin.epmdemo.xyz/`, open **Control recovery**, click **Reconstruct catalog** if `admin-recovery.sqlite` was also rebuilt, select a verified control point, click **Preview control restore**, complete bootstrap MFA step-up, click **Confirm control restore**, verify the restored registry, and click **Accept control restore**.
3. For whole-host replacement where the entire host was lost, see [backup-restore-and-maintenance.md](backup-restore-and-maintenance.md#4-whole-host-control-loss-reconstruction-cli).
