# Pilot 0 Admission, Capacity Review, Incident Triage & Retirement

**Owner:** `DC Technology` (`dctech92130@gmail.com`)  
**Scope:** Manual Operator admission, capacity checks, safe retry/seed failure handling, alert triage, runtime repair, audited break-glass, and 7-day workspace retirement on `epm-h02-host` (`epmdemo.xyz`).  
**Worksheet:** [PILOT_0_COST_AND_OPS_WORKSHEET.md](../qualification/reports/PILOT_0_COST_AND_OPS_WORKSHEET.md)

---

## 1. Pre-Admission Gate (Per Invited Operator)

1. **Verified Capacity Headroom (No Arbitrary Count Cap):**
   - Check Admin-lite **Cohort Overview** and host metrics (`disk/percent_used`, `memory/percent_used`, `cpu/utilization`).
   - Confirm qualified physical disk, inode, and RAM headroom remain above reserve margins (`HOSTED_MVP_H04_9_FREE_SIZING.json` + `HOSTED_MVP_H05_9_RECOVERY_SIZING.json`).
   - Five operators is an initial test target, **not** a hard cap. Admit a 6th+ operator only if qualified host resources permit; if capacity is unknown, stale, or exhausted, leave the request `Pending` (`Capacity review required`) and never overcommit.
2. **Google OAuth Testing Allowlist:**
   - Add the invited operator's exact Google email to **GCP Console → project `project-47b72bb7-ba90-42c9-910` → Google Auth Platform → Audience → Test users** (limit: 100 test users).
3. **Pilot 0 Disclosure (Zero Paid Claims):**
   - Confirm the operator understands Pilot 0 is Free, invitation-only, best-effort support, 24h nightly backup objective with platform-managed encryption keys (not zero-knowledge), shared announced maintenance window, and no contractual SLA.

### 1.1 Refresh or Revise Host Capacity

If **Add operator** reports an unavailable or stale capacity observation, check the snapshot revision, observation time, completeness, and referenced profile in Admin’s database. Compare the observation time with the profile’s maximum age. A fresh observation can still be unavailable if shared usage exceeds a pinned reserve.

1. On the GCP host, measure CPU affinity, available RAM, process use, and free bytes and inodes on both boot and data mounts. Verify that the data mount is the expected project-quota filesystem. Match live Operator containers and workspace, control, and scratch trees to the Admin commitments. Measure attributable usage from cgroups, allocated filesystem blocks and inodes, and identifiable container logs. Charge unattributed usage to shared consumption. Keep all existing reservations in the calculation.
2. Build a new observation using the resource accounting in `application/deploy/hosted-mvp/gcp/capacity_observer.py`. In one Admin transaction, recheck the profile, snapshot and commitment revisions, save the per-Operator observations, and publish a strictly newer snapshot with `record_capacity_snapshot`. Read the result back. If measurement or reconciliation fails, leave admission closed and diagnose the failure. Do not extend the old timestamp without new measurements.
3. If measured use requires a reserve change, review and register a new immutable profile revision, preserve the recovery reserve and per-Operator budget unless separately approved, and publish a fresh snapshot referencing that revision (see [README.md](README.md#live-pilot-0-host-inventory--constants) for current live reserves and active headroom).
4. Run the existing admission planner with a proposed pending commitment using the pinned Free budget. A preview does not reserve capacity. Submit in Admin only after confirming the result and reload the form to pick up the latest snapshot. Admission rechecks the profile and commitments in its own transaction.

Periodic refresh remains manual today. See the [automation proposal](../design/pilot0-capacity-refresh.md).

---

## 2. Standard Manual Pilot 0 Admission Flow

> **Interactive Wizard:** Run `bash application/scripts/epm-pilot0-add-operator.sh` from your workstation to walk through Sections 1 and 2 step by step (IAP SSH queries, image resolution, `ManualProvisioner`, `recovery.sqlite`, backup principal registration, initial verified backup, health/projection/ingress checks, and claim binding) with resumable saved state.

Record start time, actor, and elapsed Admin minutes in [PILOT_0_COST_AND_OPS_WORKSHEET.md](../qualification/reports/PILOT_0_COST_AND_OPS_WORKSHEET.md).

### Step 1 — Create Assignment in Admin-lite
1. Sign in to `https://admin.epmdemo.xyz/` with Google + TOTP MFA.
2. Create the operator assignment with exact email, canonical `workspace_slug`, pinned Free 50 MB allowance, and the latest registered qualified Operator release shown in Admin-lite (see [README.md](README.md#live-pilot-0-host-inventory--constants) for the current catalog release ID). Choose **Empty workspace (default)** for real operators or **Synthetic sample portfolio** for demos (pinned seed `synthetic-demo-v1:2ad5ca6acec28823a2988c77e3c81e0bfc2bec61d43839db8e1324b73761aa5a`).
3. Confirm the operator appears in Admin-lite as **Pending**.

### Step 2 — Provision Workspace, Initialize `recovery.sqlite` & Register Backup Principal
Connect to `epm-h02-host` via IAP, then look up the pending IDs:

```bash
gcloud compute ssh epm-h02-host \
  --project=project-47b72bb7-ba90-42c9-910 \
  --zone=us-west1-b \
  --tunnel-through-iap
```

Run this query in the SSH session:

```bash
sudo /opt/epm/python/bin/python3 -c '
import sqlite3
conn = sqlite3.connect("/srv/epm/data/host/h0312-identity/admin.sqlite")
for row in conn.execute(
    "SELECT o.operator_id, o.workspace_id, o.workspace_slug, o.setup_state, op.operation_id, op.state "
    "FROM operators o JOIN operations op ON op.operator_id = o.operator_id "
    "ORDER BY o.created_at DESC LIMIT 5"
):
    print(row)
'
```

*(One-time, only for **Synthetic sample portfolio**)* Upload `application/demo/{dataset.json,seed.py}` to `/opt/epm/demo/` (`0644`, verify `sha256sum /opt/epm/demo/dataset.json` = `2ad5ca6acec28823a2988c77e3c81e0bfc2bec61d43839db8e1324b73761aa5a`).

Resolve the assignment's image before provisioning. The launcher checks the local Docker image against its assigned release and returns the immutable image ID. If resolution fails, stop and check the assignment and local image. Use this same image for provisioning, recovery initialization, and the initial backup. Use `workspace_root=/data/workspace/active` so `.workspace.server.lock` sits inside the writable bind mount.

```bash
export OPERATION_ID="<operation_id>"
export OPERATOR_ID="<operator_id>"
export WORKSPACE_ID="<workspace_id>"
export WORKSPACE_SLUG="<workspace_slug>"

OPERATOR_IMAGE="$(sudo /opt/epm/host-agent/bin/python -B /opt/epm/pilot0/launch_operator.py --resolve-image "$OPERATOR_ID")" &&
  export OPERATOR_IMAGE &&
  printf 'Assigned Docker image: %s\n' "$OPERATOR_IMAGE"
```

After the command prints the assigned image ID, run:

```bash
sudo mkdir -p "/srv/epm/data/workspace/$OPERATOR_ID" "/srv/epm/data/control/$OPERATOR_ID" "/srv/epm/data/scratch/$OPERATOR_ID"
sudo chown -R 65532:65532 "/srv/epm/data/workspace/$OPERATOR_ID" "/srv/epm/data/control/$OPERATOR_ID" "/srv/epm/data/scratch/$OPERATOR_ID"
sudo chmod 0700 "/srv/epm/data/workspace/$OPERATOR_ID" "/srv/epm/data/control/$OPERATOR_ID" "/srv/epm/data/scratch/$OPERATOR_ID"

sudo docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges \
  --user 65532:65532 --tmpfs /tmp:rw,nosuid,nodev,noexec,size=64m \
  --mount type=bind,source=/srv/epm/data/host/h0312-identity,target=/admin \
  --mount "type=bind,source=/srv/epm/data/workspace/$OPERATOR_ID,target=/data/workspace" \
  --mount "type=bind,source=/srv/epm/data/control/$OPERATOR_ID,target=/data/control" \
  --mount "type=bind,source=/srv/epm/data/scratch/$OPERATOR_ID,target=/data/scratch" \
  --mount type=bind,source=/opt/epm/demo,target=/demo,readonly \
  -e "OPERATION_ID=$OPERATION_ID" \
  --pull never --entrypoint /opt/epm/venv/bin/python "${OPERATOR_IMAGE:?Resolve the assigned image first}" -B -c '
import os, time
from pathlib import Path
from app.modules.host_agent.infrastructure.manual_provision import ManualProvisionConfig, ManualProvisioner, ProvisionPaths
from app.modules.hosted_admin.infrastructure.provisioning_admission import AdminEffectAdmission
from app.platform.config import application_root
from app.platform.sqlite_engine import create_sqlite_engine

engine = create_sqlite_engine(Path("/admin/admin.sqlite"))
try:
    admission = AdminEffectAdmission(engine, clock=lambda: time.time_ns() // 1_000_000)
    cfg = ManualProvisionConfig(
        paths_for=lambda _intent: ProvisionPaths(
            workspace_root=Path("/data/workspace/active"),
            control_root=Path("/data/control"),
            scratch_root=Path("/data/scratch"),
        ),
        application_directory=application_root(),
        clock=lambda: time.time_ns() // 1_000_000,
        dataset_path=Path("/demo/dataset.json"),
    )
    print("Provision outcome:", ManualProvisioner(admission, cfg).provision(os.environ["OPERATION_ID"]))
finally:
    engine.dispose()
'
```

Pick the next unused `HOST_UID` (e.g., `100001`), initialize `recovery.sqlite`, align `workspace_id` in `workspace.json` + `property-management.sqlite`, and register the backup principal in `/srv/epm/data/host/backup-proxy/inventory.sqlite`:

```bash
sudo python3 -c 'import sqlite3; print(sqlite3.connect("/srv/epm/data/host/backup-proxy/inventory.sqlite").execute("SELECT operator_id, host_uid FROM operator_principals").fetchall())'
export HOST_UID="<next-unused-uid-e.g.-100001>"

sudo rm -f "/srv/epm/data/control/$OPERATOR_ID/recovery.sqlite"
sudo docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges \
  --user 65532:65532 \
  --mount "type=bind,source=/srv/epm/data/control/$OPERATOR_ID,target=/data/control" \
  -e "OPERATOR_ID=$OPERATOR_ID" -e "WORKSPACE_ID=$WORKSPACE_ID" \
  --pull never --entrypoint /opt/epm/venv/bin/python "${OPERATOR_IMAGE:?Resolve the assigned image first}" -B -c '
import os, sqlite3
from pathlib import Path
from app.modules.workspace.infrastructure.hosted_recovery import kms_ref_to_db_ref
from app.platform.config import application_root
from app.platform.hosted_schema import initialize_store
from app.platform.schema_resources import HostedStore

op_id, ws_id = os.environ["OPERATOR_ID"], os.environ["WORKSPACE_ID"]
dep_id = "b77f7c7e-c89c-4d44-b337-e8d4f13ee46f"
kms_key = "projects/project-47b72bb7-ba90-42c9-910/locations/us-west1/keyRings/epm-h05-recovery/cryptoKeys/operator-workspace-kek"
rec_path = Path("/data/control/recovery.sqlite")
print("recovery.sqlite:", initialize_store(HostedStore.RECOVERY, rec_path, application_directory=application_root()))
rec = sqlite3.connect(str(rec_path))
rec.execute(
    "INSERT INTO recovery_meta (id, workspace_id, deployment_ref, source_generation, restore_generation, active_business_ref, encryption_key_ref, namespace_prefix, revision) "
    "VALUES (1, ?, ?, 1, 1, '\''active'\'', ?, ?, 1)",
    (ws_id, f"dep:{dep_id}", kms_ref_to_db_ref(kms_key), f"deployments/{dep_id}/operators/{op_id}/"),
)
rec.execute(
    "INSERT INTO backup_state (id, last_point_id, protected_business_revision, protected_files_generation, protected_source_generation, "
    "protection_state, dirty_since, last_checked_at, last_backup_attempt_at, consecutive_failures, last_error_code, revision) "
    "VALUES (1, NULL, NULL, NULL, NULL, '\''unknown'\'', NULL, NULL, NULL, 0, NULL, 1)"
)
rec.commit(); rec.close()
'

sudo -E python3 -c '
import json, os, sqlite3, time
from pathlib import Path
op_id, ws_id, uid = os.environ["OPERATOR_ID"], os.environ["WORKSPACE_ID"], int(os.environ["HOST_UID"])
now = int(time.time() * 1000)

ws_json = Path(f"/srv/epm/data/workspace/{op_id}/active/workspace.json")
data = json.loads(ws_json.read_text()); data["workspaceId"] = ws_id
ws_json.write_text(json.dumps(data, indent=2) + "\n")

biz = sqlite3.connect(f"/srv/epm/data/workspace/{op_id}/active/database/property-management.sqlite")
biz.execute("UPDATE workspace_metadata SET workspace_id = ?", (ws_id,)); biz.commit(); biz.close()

inv = sqlite3.connect("/srv/epm/data/host/backup-proxy/inventory.sqlite")
inv.execute(
    "INSERT INTO operator_principals (operator_id, workspace_id, host_uid, host_gid, assigned_at, retired_at, cleanup_verified_at, revision) "
    "VALUES (?, ?, ?, ?, ?, NULL, NULL, 1)",
    (op_id, ws_id, uid, uid, now),
)
inv.commit(); inv.close()
'
sudo chown -R 65532:65532 "/srv/epm/data/workspace/$OPERATOR_ID" "/srv/epm/data/control/$OPERATOR_ID" "/srv/epm/data/scratch/$OPERATOR_ID"
```

### Step 3 — Launch Container, Capture Initial Verified Backup & Verify Ingress
Run in the same SSH session as Step 2, or restore its variables and resolve `OPERATOR_IMAGE` again before stopping the container. The launcher uses the assigned image and refuses to replace a container running a different image. For an existing Operator release change, follow [the rollout runbook](pilot0-release-rollout.md#3-roll-live-pilot-0-operator-containers-epm-op-slug).

```bash
sudo /opt/epm/host-agent/bin/python -B /opt/epm/pilot0/launch_operator.py "$OPERATOR_ID"
sudo systemctl restart epm-h03-identity.service && sleep 20
sudo systemctl is-active epm-backup-proxy.service epm-h03-identity.service epm-gateway.service epm-tunnel.service epm-host-guardian.service

# Capture initial verified R2 + Cloud KMS recovery point under registered HOST_UID
sudo docker stop "epm-op-$WORKSPACE_SLUG"
sudo chown -R "$HOST_UID:$HOST_UID" "/srv/epm/data/workspace/$OPERATOR_ID" "/srv/epm/data/control/$OPERATOR_ID" "/srv/epm/data/scratch/$OPERATOR_ID" "/etc/epm/pilot0-operators/$OPERATOR_ID"
sudo docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges \
  --user "$HOST_UID:$HOST_UID" --tmpfs /tmp:rw,nosuid,nodev,noexec,size=32m \
  --mount "type=bind,source=/etc/epm/pilot0-operators/$OPERATOR_ID,target=/control,readonly" \
  --mount "type=bind,source=/srv/epm/data/workspace/$OPERATOR_ID,target=/data/workspace" \
  --mount "type=bind,source=/srv/epm/data/control/$OPERATOR_ID,target=/data/control" \
  --mount "type=bind,source=/srv/epm/data/scratch/$OPERATOR_ID,target=/data/scratch" \
  --mount type=bind,source=/run/epm-backup-proxy,target=/run/epm-backup-proxy \
  --pull never --entrypoint /opt/epm/venv/bin/python "${OPERATOR_IMAGE:?Resolve the assigned image first}" -B -c '
import time
from pathlib import Path
from app.modules.host_agent.infrastructure.backup_proxy import UnixBackupProxyClient
from app.modules.hosted_access.infrastructure.operator_entry import OperatorDeployment
from app.modules.hosted_access.infrastructure.shared_identity_entry import read_private
from app.modules.hosted_recovery.infrastructure.engine import ChunkedAeadBackupEngine
from app.modules.hosted_recovery.infrastructure.scheduler import WorkspaceBackupScheduler
from app.modules.workspace.infrastructure.hosted_recovery import HostedWorkspaceRecoveryService
from app.platform.sqlite_engine import create_sqlite_engine

cfg = OperatorDeployment.model_validate_json(read_private(Path("/control/deployment.json")))
b = cfg.binding; clock = lambda: time.time_ns() // 1_000_000
svc = HostedWorkspaceRecoveryService(
    recovery_engine=create_sqlite_engine(cfg.recovery_database),
    access_engine=create_sqlite_engine(cfg.access_database),
    backup_engine=ChunkedAeadBackupEngine(UnixBackupProxyClient(cfg.backup_proxy_socket, expected_proxy_uid=cfg.backup_proxy_uid)),
    operator_id=b.scope.operator_id, workspace_id=b.scope.workspace_id, deployment_id=b.deployment_id,
    workspace_root=Path("/data/workspace"), scratch_root=cfg.scratch_directory, release_ref=cfg.release_ref,
    business_schema_revision=cfg.business_schema_revision, access_schema_revision=cfg.access_schema_revision, clock=clock,
)
sched = WorkspaceBackupScheduler(svc, deployment_id=b.deployment_id, operator_id=b.scope.operator_id, workspace_id=b.scope.workspace_id, clock=clock, nightly_interval_ms=1000, jitter_window_seconds=0)
print("RUN_ONCE:", sched.run_once(), svc.read_protection_status())
'
sudo chown -R 65532:65532 "/srv/epm/data/workspace/$OPERATOR_ID" "/srv/epm/data/control/$OPERATOR_ID" "/srv/epm/data/scratch/$OPERATOR_ID" "/etc/epm/pilot0-operators/$OPERATOR_ID"
sudo docker start "epm-op-$WORKSPACE_SLUG" && sleep 12
```

Verify the running Operator, its Admin recovery-status projection, and public ingress separately. Run these commands in the VM SSH session. A new SSH session does not inherit shell variables, so set the slug from the Step 2 query if it is not already set:

```bash
export WORKSPACE_SLUG="<workspace_slug>"
```

1. **Probe container health endpoints.** Docker's `(healthy)` status checks `/health/live`; this command also checks readiness explicitly. Both should return `200`:

   ```bash
   sudo docker exec "epm-op-$WORKSPACE_SLUG" /opt/epm/venv/bin/python -c '
   import urllib.request
   for name in ("live", "ready"):
       with urllib.request.urlopen(f"http://127.0.0.1:8081/health/{name}", timeout=3) as response:
           print(name, response.status, response.read().decode())
   '
   ```

2. **Check Admin's latest recovery-status report.** This is an asynchronous monitoring projection, separate from the one-shot backup result printed in Step 3. The row should show `healthy` and a non-null `verified_at`:

   ```bash
   sudo /opt/epm/python/bin/python3 -c '
   import sqlite3, sys
   slug = sys.argv[1]
   if not slug:
       raise SystemExit("Set WORKSPACE_SLUG before running this query")
   conn = sqlite3.connect("/srv/epm/data/host/h0312-identity/admin.sqlite")
   row = conn.execute(
       "SELECT o.operator_id, o.workspace_id, r.protection_state, "
       "r.latest_point_ref, r.captured_at, r.verified_at, r.observed_at "
       "FROM operators o LEFT JOIN workspace_recovery_status r "
       "ON r.operator_id = o.operator_id WHERE o.workspace_slug = ?",
       (slug,),
   ).fetchone()
   print(row)
   conn.close()
   ' "$WORKSPACE_SLUG"
   ```

   If the row is absent or not `healthy`, do not treat the local `RUN_ONCE: True` snapshot as proof that Admin received the report. Check for `Best-effort protection summary relay unavailable` or `backup_proxy_unavailable` in the Operator logs; the relay warning means Admin's projection may be stale.

3. **Check public HTTPS ingress.** Expect `HTTP/2 303` and a `location` beginning `https://login.epmdemo.xyz/auth/start`:

   ```bash
   curl -sS -D - -o /dev/null "https://$WORKSPACE_SLUG.epmdemo.xyz/auth/start" | grep -i -E 'HTTP/|location:'
   ```

A `502` is a failed ingress check. Inspect the newest gateway error and Operator logs:

```bash
sudo journalctl -u epm-gateway.service --since "5 minutes ago" --no-pager
sudo docker logs --since 10m "epm-op-$WORKSPACE_SLUG"
```

For example, Caddy's `connect: connection refused` to the Operator address on port `8000` means the upstream was not accepting connections at that time, even if Docker's separate `/health/live` check passes. Retry the public check after the Operator is ready and confirm the latest gateway log has no new 502 for this hostname.

### Step 4 — Issue Invitation, Sync `assignment_revision` & Complete Claim
1. In Admin-lite, open the operator detail page, click **Issue / reissue invitation** (requires recent MFA sign-in), email the single-use claim URL from `dctech92130@gmail.com` with the Pilot 0 disclosure, and click **Mark delivered**.
2. **Sync `assignment_revision`** (issuing/delivering increments `operators.revision`):
   ```bash
   sudo /opt/epm/host-agent/bin/python -B /opt/epm/pilot0/launch_operator.py "$OPERATOR_ID"
   sudo systemctl restart epm-h03-identity.service && sleep 20
   ```
3. Have the operator open their claim URL and complete **Continue with Google**. If `operators.subject` is still `None` after first Google verification (Pilot 0 manual claim completion), bind their verified Firebase UID from `managed_identity_sessions` and relaunch:
   ```bash
   sudo -E python3 -c '
   import os, sqlite3, time
   op_id = os.environ["OPERATOR_ID"]; now = int(time.time() * 1000)
   ac = sqlite3.connect("/srv/epm/data/host/h0312-identity/admin.sqlite")
   row = ac.execute("SELECT issuer, subject FROM managed_identity_sessions WHERE operator_id = ? ORDER BY issued_at DESC LIMIT 1", (op_id,)).fetchone()
   assert row, "No verified managed_identity_sessions row found yet"
   issuer, sub = row
   ac.execute("UPDATE operators SET subject = ?, setup_state = '\''active'\'', revision = revision + 1, updated_at = ? WHERE operator_id = ?", (sub, now, op_id))
   ac.execute("UPDATE invitations SET state = '\''claimed'\'', claimed_issuer = ?, claimed_subject = ?, claimed_at = ?, revision = revision + 1 WHERE operator_id = ? AND state IN ('\''pending_delivery'\'', '\''sent'\'')", (issuer, sub, now, op_id))
   ac.commit(); ac.close()

   oc = sqlite3.connect(f"/srv/epm/data/control/{op_id}/access.sqlite")
   oc.execute("UPDATE access_meta SET subject = ?, effective_access = '\''enabled'\'', revision = revision + 1 WHERE id = 1", (sub,))
   oc.commit(); oc.close()
   print("Bound verified subject:", issuer, sub)
   '
   sudo chown -R 65532:65532 "/srv/epm/data/host/h0312-identity" "/srv/epm/data/control/$OPERATOR_ID"
   sudo /opt/epm/host-agent/bin/python -B /opt/epm/pilot0/launch_operator.py "$OPERATOR_ID"
   sudo systemctl restart epm-h03-identity.service && sleep 20
   ```
4. Have the operator open a fresh tab to `https://$WORKSPACE_SLUG.epmdemo.xyz/`, complete **Continue with Google**, and confirm Admin-lite reports **Active** and **Healthy** (or **Unchanged**).

### Exception Handling (Safe Retry & Seed Failure)
- **Lost-Response Create / Provision / Enable:** Never create a second assignment or slug. Inspect the original `operation_id` and `idempotency_key` in Admin-lite and retry with the exact original payload + `idempotency_key` (changed payload fails closed with `409 Conflict`).
- **Interrupted Fresh Seed:** Keep business ingress **disabled (`held`)** and state **`needs_attention`**. Run deliberate cleanup and reseed using the original reviewed identities — never auto-replay a seed over live business data.

---

## 3. Alert Triage Matrix & Support Break-Glass

| Alert Source | Signal | First-Response Action |
| --- | --- | --- |
| **Backup Overdue / Failure** (`epm_hosted_recovery_alerts`) | `backup_overdue`, `backup_failed`, `backup_unknown` | Inspect Cloud Logging for `hosted_recovery_alert` (operator ID, error code, consecutive failures). Check `epm-backup-proxy.service`, R2 reachability, and Cloud KMS IAM. Do not clear until a verified recovery point succeeds and `backup_recovered` emits. |
| **Host Guardian Containment** (`epm_host_guardian_containment`) | `runtime_containment_attention` | Inspect `journalctl -u epm-host-guardian.service` for contained container and reason. Verify no cross-operator breach; repair runtime before re-enabling ingress. |
| **Disk / Inode / RAM / CPU Headroom** | Disk/Inodes `> 80%`, RAM `> 85%`, CPU `> 85%` (10m) | Pause new Pilot 0 admissions immediately. Inspect per-tree `repquota -P /srv/epm/data`, Docker logs, and container RSS. Clear only after headroom returns below thresholds. |
| **Host-Loss Heartbeat** (`epm-pilot0-host-heartbeat`) | Uptime check failed `> 5m` | Check `epm-h02-host` VM status, `epm-tunnel.service`, and `epm-gateway.service`. If host is lost, run whole-host recovery in [backup-restore-and-maintenance.md](backup-restore-and-maintenance.md) (4h RTO objective). |

### Audited Support Break-Glass Policy (H06 D10)
1. **Metadata-Only Default:** Support inspects only non-content operational metadata (status, backup freshness, error codes, quota usage, redacted logs).
2. **Consented Troubleshooting:** Any broader troubleshooting requires explicit written operator consent (retained in ticket), recorded reason/actor/expiry in `admin_audit`, and zero offline decrypt or key export.
3. **Post-Incident Audit:** Verify temporary access is revoked on expiry and log elapsed support minutes in the Pilot 0 worksheet.

---

## 4. Deliberate Workspace Retirement (7-Day Hold — H06 D10)

Never hard-delete an active or newly retired workspace immediately:
1. **Day 0 (Disable & Fence):** Disable the operator in Admin-lite (revokes sessions and fences ingress). Capture one final verified recovery point via `epm-backup-proxy` and confirm `manifest_sha256` is recorded.
2. **Days 0–7 (Hold Window):** Retain disabled workspace data and encrypted R2 recovery points for **7 full days** (reversible via operator-authenticated re-enable/restore).
3. **Day 7+ (Final Retirement & Verified Cleanup):** Run explicit `retire_resources` through host-agent. Verify container removal, `ext4` project-quota tree cleanup (`cleanup_verified_at` recorded in `inventory.sqlite`), R2 prefix cleanup, and Google OAuth Testing allowlist removal. Record completion in `admin_audit` and the Pilot 0 worksheet.
