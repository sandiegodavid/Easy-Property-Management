# H06.4 Operations Runbook — Verifying HTTP Security Headers & Redacted Structured Logs

**Applies to:** HOSTED-001 Slice H06.4 (Caddy gateway, Admin, Central, Operator APIs & `epm-host-guardian`)  
**Checkpoint:** [HOSTED_MVP_H06_4_CHECKPOINT_2026-11-23.md](../qualification/reports/HOSTED_MVP_H06_4_CHECKPOINT_2026-11-23.md)  
**Related Runbooks:** [H06_3_SCHEDULER_RELAY_AND_MAINTENANCE_RUNBOOK.md](H06_3_SCHEDULER_RELAY_AND_MAINTENANCE_RUNBOOK.md) · [H06_2_HOST_SERVICES_OPERATIONS_RUNBOOK.md](H06_2_HOST_SERVICES_OPERATIONS_RUNBOOK.md)

---

## 1. Verify Live HTTP Security Headers After Any Deployment or Gateway Refresh

After refreshing Caddy (`epm-ingress-projection.service` / `epm-gateway.service`) or deploying new Admin/Operator containers on `epm-h02-host`, confirm all required security headers are present on every public origin:

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

Expected values:
- `Strict-Transport-Security: max-age=31536000; includeSubDomains`
- `Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=(), usb=()`
- `X-Content-Type-Options: nosniff`
- `Cache-Control: no-store`
- `Referrer-Policy: no-referrer`
- `Content-Security-Policy`: strict `default-src 'none'; ...; frame-ancestors 'none'; base-uri 'none'` (with `script-src` only on Admin/Central HTML routes, and `form-action 'none'` on JSON API routes).

---

## 2. Inspect & Audit Redacted Structured JSON Logs on `epm-h02-host`

Hosted services emit single-line JSON log records formatted by `app.platform.hosted_logging` (`component`, `event`, `severity`, `timestamp_ms`, redacted fields), ready for GCP Ops Agent / Cloud Logging ingestion (H06.7).

1. **Inspect guardian containment & recovery alert streams:**
   ```bash
   sudo journalctl -u epm-host-guardian.service -n 50 --no-pager
   sudo journalctl -u epm-h03-identity.service --grep="hosted_recovery_alert" -n 50 --no-pager
   ```

2. **Spot-check for zero secret leakage in host logs:**
   ```bash
   sudo journalctl -u 'epm-*' --since "24 hours ago" --no-pager \
     | grep -E '(__Host-[A-Za-z0-9_.-]+=(?!\[REDACTED\])|Bearer (?!\[REDACTED\])|eyJ[A-Za-z0-9_-]{8,}\.)' \
     && echo "WARNING: unredacted token pattern found" \
     || echo "OK: zero unredacted token/cookie patterns found"
   ```

3. **Run local negative log-redaction & security-header regression gate before release:**
   ```bash
   cd application
   PYTHONPATH=apps/server .venv/bin/pytest \
     apps/server/app/modules/hosted_access/tests/test_h06_security_headers_and_logging.py
   ```
