# H06.2 Operations Runbook — `epm-backup-proxy.service`, Admin D5 Recovery Fallback & Guardian Supervision

**Applies to:** HOSTED-001 Slice H06.2 (Host service wiring on `epm-h02-host`)  
**Checkpoint:** [HOSTED_MVP_H06_2_CHECKPOINT_2026-11-23.md](../qualification/reports/HOSTED_MVP_H06_2_CHECKPOINT_2026-11-23.md)  
**Related Runbooks:** [H06_1_GCP_RECOVERY_PROVISIONING_RUNBOOK.md](H06_1_GCP_RECOVERY_PROVISIONING_RUNBOOK.md) · [H05_RECOVERY_OPERATIONS_RUNBOOK.md](H05_RECOVERY_OPERATIONS_RUNBOOK.md)

---

## 1. Deploy & Verify `epm-backup-proxy.service`

`epm-backup-proxy.service` runs under dedicated unprivileged user `epm-backup-proxy`, loads R2 credentials via systemd `LoadCredential=r2.json:/etc/epm/secrets/r2.json` (never passing secrets in argv/env or into containers), and has zero dependency on Admin or ingress services.

1. **Fetch scoped R2 credentials from GCP Secret Manager into root-only `/etc/epm/secrets/r2.json` (`0600`):**
   ```bash
   sudo PYTHONPATH=/opt/epm/host-agent/lib/python3.14/site-packages \
     /opt/epm/host-agent/bin/python -c \
     "import runpy; runpy.run_path('/opt/epm/app/deploy/hosted-mvp/gcp/install_services.py')['r2_credential']('project-47b72bb7-ba90-42c9-910')"
   ```

2. **Write protected `/etc/epm/backup-proxy.json` (`0640`, `root:epm-backup-proxy`):**
   ```json
   {
     "socket": "/run/epm-backup-proxy/backup-proxy.sock",
     "inventory": "/srv/epm/data/host/inventory/inventory.sqlite",
     "deployment_id": "b77f7c7e-c89c-4d44-b337-e8d4f13ee46f",
     "admin_uid": 959,
     "operator_key_refs": [
       "projects/project-47b72bb7-ba90-42c9-910/locations/us-west1/keyRings/epm-h05-recovery/cryptoKeys/operator-workspace-kek"
     ],
     "control_key_refs": [
       "projects/project-47b72bb7-ba90-42c9-910/locations/us-west1/keyRings/epm-h05-recovery/cryptoKeys/admin-control-kek"
     ]
   }
   ```

3. **Enable, start, and verify the socket:**
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now epm-backup-proxy.service
   sudo systemctl status epm-backup-proxy.service --no-pager
   sudo ls -la /run/epm-backup-proxy/backup-proxy.sock
   ```

---

## 2. Admin Deployment Configuration & D5 Recovery-Mode Fallback

To enable live Admin-lite control APIs, Admin control-plane backup/recovery, and automatic D5 recovery-mode fallback (if `admin.sqlite` is missing or corrupted), include these fields in the protected Admin deployment JSON (`0600`):

```json
{
  "admin_recovery_database": "/srv/epm/data/host/admin-recovery/admin-recovery.sqlite",
  "bootstrap_authority": "/run/epm/admin-recovery-authority.json",
  "control_root": "/srv/epm/data/host/admin-control",
  "scratch_root": "/srv/epm/data/host/admin-scratch",
  "backup_proxy_socket": "/run/epm-backup-proxy/backup-proxy.sock",
  "backup_proxy_uid": "<UID_OF_epm-backup-proxy>",
  "release_ref": "rel-hosted-mvp"
}
```

- **Normal boot:** `shared_identity_entry.py` wires live `AdminWorkspaceReadiness` (requiring `desired_access = 'enabled'`, `setup_state IN ('ready_for_claim', 'active')`, exact `access_epoch`, and verified `protection_state IN ('healthy', 'unchanged')`), `AdminControlService`, `AdminControlRecoveryService`, and D5 `authenticate_recovery`.
- **Damaged/missing `admin.sqlite` boot:** `shared_identity_entry.py` automatically falls back to `create_admin_recovery_app()` on the Admin host (authenticating strictly against `/run/epm/admin-recovery-authority.json` + Google + TOTP MFA + live Firebase revocation) and returns `503 {"code":"admin_recovery_mode_active"}` on the central login host until Admin is restored.

---

## 3. Operating `epm-host-guardian.service` (Production Supervision & Emergency Containment)

- **Production supervision mode:** `epm-host-guardian.service` runs `supervisor --registry /srv/epm/data/host/stops --config /etc/epm/host-services.json`, composing a live `HostAgent` that verifies running containers against `host_inventory.sqlite`, Caddy `Gateway`, and ext4 `PrivateStorage` quotas.
- **Inspect structured JSON containment alerts:**
  ```bash
  sudo journalctl -u epm-host-guardian.service -n 50 --no-pager
  ```
  Containment events emit single-line JSON (`{"component":"epm-host-guardian","event":"runtime_containment_attention","severity":"critical",...}`) with zero secrets, ready for Cloud Monitoring log-based alerts (H06.7).
- **Manual emergency containment (stop all tracked Operator containers immediately):**
  ```bash
  sudo /opt/epm/host-agent/bin/python -B \
    -m app.modules.host_agent.infrastructure.supervisor \
    --registry /srv/epm/data/host/stops --contain-all
  ```
