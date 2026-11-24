# Pilot 0 Admission & Capacity Review Runbook (H06.8)

**Owner:** Named Pilot 0 Operational Owner (D4)  
**Scope:** Manual admission, provisioning completion, safe retry, and capacity review for invited Free Pilot 0 operators on `epm-h02-host` (`epmdemo.xyz`).  
**Design Authority:** [HOSTED_MVP_H06_DESIGN.md](../design/HOSTED_MVP_H06_DESIGN.md) (D1, D2, D4, D9) · [operations_economics.md](../qualification/specifications/operations_economics.md)

---

## 1. Pre-Admission Gate (Per Invited Operator)

Before adding a new operator in Admin-lite, confirm every prerequisite:
1. **Verified Capacity Headroom (No Arbitrary Count Cap):**
   - Check Admin-lite **Cohort Overview** and host metrics (`agent.googleapis.com/disk/percent_used`, `memory/percent_used`, `cpu/utilization`).
   - Confirm qualified physical disk, inode, and RAM headroom remain above reserve margins (`HOSTED_MVP_H04_9_FREE_SIZING.json` + `HOSTED_MVP_H05_9_RECOVERY_SIZING.json`).
   - **Rule:** Five operators is an initial test target, **not** a hard cap. Admit a 6th+ operator **only** if qualified host resources permit; if capacity is unknown, stale, or exhausted, leave the request `Pending` with explicit reason `Capacity review required` and **never** overcommit.
2. **Google OAuth Testing Allowlist (D1):**
   - Add the invited operator's exact email address to the Google Auth Platform **Testing** users allowlist in GCP project `project-47b72bb7-ba90-42c9-910` (limit: 100 test users).
3. **Zero Paid Claims (Out of Scope):**
   - Confirm the operator understands Pilot 0 is Free, invitation-only, best-effort support, 24h nightly backup objective with platform-managed encryption keys (not zero-knowledge), shared announced maintenance window, and no contractual SLA (D4).

---

## 2. Standard Manual Admission Flow

Record start time, actor, and elapsed minutes in [PILOT_0_COST_AND_OPS_WORKSHEET.md](../qualification/reports/PILOT_0_COST_AND_OPS_WORKSHEET.md).

1. **Create Assignment in Admin-lite:**
   - Sign in to Admin-lite with Google + TOTP MFA.
   - Create the operator assignment with exact email, canonical slug, pinned Free 50 MB allowance, qualified Operator release (`epm-pilot0-operator:h0610`), and choice of **Empty workspace (default)** (recommended for real Pilot 0 operators) or **Synthetic sample portfolio** (demo/sample workspaces only).
   - If choosing **Synthetic sample portfolio**, supply the **Pinned seed bundle reference** in the form `synthetic-demo-v1:<sha256>` computed from `application/demo/dataset.json`:
     ```bash
     printf 'synthetic-demo-v1:%s\n' "$(shasum -a 256 application/demo/dataset.json | awk '{print $1}')"
     # Current pinned value:
     # synthetic-demo-v1:2ad5ca6acec28823a2988c77e3c81e0bfc2bec61d43839db8e1324b73761aa5a
     ```
   - Submit **Create operator** and confirm the new operator appears in the Admin-lite list with your chosen `workspace_slug` and status **Pending** (the internal `operator_id`, `workspace_id`, and `operation_id` are not displayed in the UI; retrieve them from `admin.sqlite` in Step 2 below).
2. **Run Supported Provisioning Completion on `epm-h02-host`:**
   - SSH into `epm-h02-host` via IAP and look up the pending `operation_id`, `operator_id`, `workspace_id`, and `workspace_slug`:
     ```bash
     gcloud compute ssh epm-h02-host \
       --project=project-47b72bb7-ba90-42c9-910 \
       --zone=us-west1-b \
       --tunnel-through-iap
     ```
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
   - *(One-time, only if using **Synthetic sample portfolio**)* Upload `application/demo/dataset.json` and `application/demo/seed.py` from your local repo to `/opt/epm/demo/` on `epm-h02-host` via IAP `gcloud compute scp`:
     ```bash
     # From your local repo root:
     gcloud compute scp application/demo/dataset.json application/demo/seed.py \
       epm-h02-host:/tmp/ \
       --project=project-47b72bb7-ba90-42c9-910 \
       --zone=us-west1-b \
       --tunnel-through-iap

     gcloud compute ssh epm-h02-host \
       --project=project-47b72bb7-ba90-42c9-910 \
       --zone=us-west1-b \
       --tunnel-through-iap \
       --command='sudo install -D -m 0644 /tmp/dataset.json /opt/epm/demo/dataset.json && sudo install -D -m 0644 /tmp/seed.py /opt/epm/demo/seed.py && rm -f /tmp/dataset.json /tmp/seed.py && sha256sum /opt/epm/demo/dataset.json'
     # Expected SHA-256: 2ad5ca6acec28823a2988c77e3c81e0bfc2bec61d43839db8e1324b73761aa5a
     ```
   - Export the pending `OPERATION_ID` and `OPERATOR_ID` and run `ManualProvisioner` inside the qualified `epm-pilot0-operator:h0610` image (which carries the `business`, `hosted-access`, and `recovery` schema resources; use `workspace_root=/data/workspace/active` so `.workspace.server.lock` lives inside the writable bind mount):
     ```bash
     export OPERATION_ID="<operation_id-from-above>"
     export OPERATOR_ID="<operator_id-from-above>"
     sudo mkdir -p "/srv/epm/data/workspace/$OPERATOR_ID" "/srv/epm/data/control/$OPERATOR_ID" "/srv/epm/data/scratch/$OPERATOR_ID"
     sudo chown -R 65532:65532 "/srv/epm/data/workspace/$OPERATOR_ID" "/srv/epm/data/control/$OPERATOR_ID" "/srv/epm/data/scratch/$OPERATOR_ID"
     sudo chmod 0700 "/srv/epm/data/workspace/$OPERATOR_ID" "/srv/epm/data/control/$OPERATOR_ID" "/srv/epm/data/scratch/$OPERATOR_ID"

     sudo docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges \
       --user 65532:65532 \
       --tmpfs /tmp:rw,nosuid,nodev,noexec,size=64m \
       --mount type=bind,source=/srv/epm/data/host/h0312-identity,target=/admin \
       --mount "type=bind,source=/srv/epm/data/workspace/$OPERATOR_ID,target=/data/workspace" \
       --mount "type=bind,source=/srv/epm/data/control/$OPERATOR_ID,target=/data/control" \
       --mount "type=bind,source=/srv/epm/data/scratch/$OPERATOR_ID,target=/data/scratch" \
       --mount type=bind,source=/opt/epm/demo,target=/demo,readonly \
       -e "OPERATION_ID=$OPERATION_ID" \
       --entrypoint /opt/epm/venv/bin/python epm-pilot0-operator:h0610 -B -c '
     import os, time
     from pathlib import Path
     from app.modules.host_agent.infrastructure.manual_provision import (
         ManualProvisionConfig, ManualProvisioner, ProvisionPaths,
     )
     from app.modules.hosted_admin.infrastructure.provisioning_admission import AdminEffectAdmission
     from app.platform.config import application_root
     from app.platform.sqlite_engine import create_sqlite_engine

     op_id = os.environ["OPERATION_ID"]
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
         outcome = ManualProvisioner(admission, cfg).provision(op_id)
         print("Provision outcome:", outcome)
     finally:
         engine.dispose()
     '
     ```
   - Align the workspace ID created by `WorkspaceService.initialize(in_place=True)` with Admin's assigned `WORKSPACE_ID` (both `workspace.json` and `property-management.sqlite` `workspace_metadata.workspace_id` must match `binding.scope.workspace_id`), initialize `recovery.sqlite` (`recovery_meta` + `backup_state`), and register the operator's backup principal in `/srv/epm/data/host/backup-proxy/inventory.sqlite`:
     ```bash
     # Check already-assigned host_uid values first (pick the next unused integer, e.g. 100001):
     sudo python3 -c 'import sqlite3; print(sqlite3.connect("/srv/epm/data/host/backup-proxy/inventory.sqlite").execute("SELECT operator_id, host_uid FROM operator_principals").fetchall())'

     export WORKSPACE_ID="<workspace_id-from-above>"
     export HOST_UID="<next-unused-uid-e.g.-100001>"

     # Initialize recovery.sqlite inside the operator image
     sudo rm -f "/srv/epm/data/control/$OPERATOR_ID/recovery.sqlite"
     sudo docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges \
       --user 65532:65532 \
       --mount "type=bind,source=/srv/epm/data/control/$OPERATOR_ID,target=/data/control" \
       -e "OPERATOR_ID=$OPERATOR_ID" -e "WORKSPACE_ID=$WORKSPACE_ID" \
       --entrypoint /opt/epm/venv/bin/python epm-pilot0-operator:h0610 -B -c '
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
         "INSERT INTO recovery_meta "
         "(id, workspace_id, deployment_ref, source_generation, restore_generation, active_business_ref, encryption_key_ref, namespace_prefix, revision) "
         "VALUES (1, ?, ?, 1, 1, '\''active'\'', ?, ?, 1)",
         (ws_id, f"dep:{dep_id}", kms_ref_to_db_ref(kms_key), f"deployments/{dep_id}/operators/{op_id}/"),
     )
     rec.execute(
         "INSERT INTO backup_state "
         "(id, last_point_id, protected_business_revision, protected_files_generation, protected_source_generation, "
         "protection_state, dirty_since, last_checked_at, last_backup_attempt_at, consecutive_failures, last_error_code, revision) "
         "VALUES (1, NULL, NULL, NULL, NULL, '\''unknown'\'', NULL, NULL, NULL, 0, NULL, 1)"
     )
     rec.commit(); rec.close()
     '

     # Align workspace_id and register backup principal
     sudo -E python3 -c '
     import json, os, sqlite3, time
     from pathlib import Path
     op_id, ws_id, uid = os.environ["OPERATOR_ID"], os.environ["WORKSPACE_ID"], int(os.environ["HOST_UID"])
     now = int(time.time() * 1000)

     ws_json = Path(f"/srv/epm/data/workspace/{op_id}/active/workspace.json")
     data = json.loads(ws_json.read_text())
     data["workspaceId"] = ws_id
     ws_json.write_text(json.dumps(data, indent=2) + "\n")

     biz = sqlite3.connect(f"/srv/epm/data/workspace/{op_id}/active/database/property-management.sqlite")
     biz.execute("UPDATE workspace_metadata SET workspace_id = ?", (ws_id,))
     biz.commit(); biz.close()

     inv = sqlite3.connect("/srv/epm/data/host/backup-proxy/inventory.sqlite")
     inv.execute(
         "INSERT INTO operator_principals "
         "(operator_id, workspace_id, host_uid, host_gid, assigned_at, retired_at, cleanup_verified_at, revision) "
         "VALUES (?, ?, ?, ?, ?, NULL, NULL, 1)",
         (op_id, ws_id, uid, uid, now),
     )
     inv.commit(); inv.close()
     '
     sudo chown -R 65532:65532 "/srv/epm/data/workspace/$OPERATOR_ID" "/srv/epm/data/control/$OPERATOR_ID" "/srv/epm/data/scratch/$OPERATOR_ID"
     ```
   - Confirm `epm-backup-proxy.service` is `active` and points to `/srv/epm/data/host/backup-proxy/inventory.sqlite` (leaving `/srv/epm/data/host/inventory/inventory.sqlite` at `0600 root:root` for `epm-gateway.service`):
     ```bash
     sudo systemctl is-active epm-backup-proxy.service
     sudo grep '"inventory"' /etc/epm/backup-proxy.json
     # Expect:
     # active
     #   "inventory": "/srv/epm/data/host/backup-proxy/inventory.sqlite",
     ```

3. **Launch the Live Operator Container, Capture Initial Verified Backup & Refresh Routes:**
   - Export `WORKSPACE_SLUG` (matching Step 1/2, e.g., `demo-a`), launch the isolated `epm-pilot0-operator:h0610` container on its dedicated private Docker bridge (`10.248.<slot>.0/30`), and restart `epm-h03-identity.service` so Central, Caddy, and the Cloudflare Tunnel pick up the new operator. `/opt/epm/pilot0/launch_operator.py` automatically reads `access_epoch`/`revision`/`subject` from `admin.sqlite`, binds `/run/epm-operator-sockets/$OPERATOR_ID` for `/opt/epm/pilot0/pilot0_relay.py` (UID `65532`), wires `recovery_database` + `/run/epm-backup-proxy/backup-proxy.sock` + `/run/epm-central-identity/recovery-status.sock`, and reuses existing `tls.pem`/`tls.key` on relaunch:
     ```bash
     export WORKSPACE_SLUG="<workspace_slug-from-above>"

     sudo /opt/epm/host-agent/bin/python -B /opt/epm/pilot0/launch_operator.py "$OPERATOR_ID"
     sudo systemctl restart epm-h03-identity.service
     sleep 20
     sudo systemctl is-active epm-backup-proxy.service epm-h03-identity.service epm-gateway.service epm-tunnel.service epm-host-guardian.service
     ```
   - Capture the initial verified R2 + Cloud KMS recovery point (using the registered `$HOST_UID` so `epm-backup-proxy` authorizes the operator namespace), then start `epm-op-$WORKSPACE_SLUG` so it publishes `protection_state = 'healthy'` to Central's `admin.sqlite`:
     ```bash
     sudo docker stop "epm-op-$WORKSPACE_SLUG"
     sudo chown -R "$HOST_UID:$HOST_UID" "/srv/epm/data/workspace/$OPERATOR_ID" "/srv/epm/data/control/$OPERATOR_ID" "/srv/epm/data/scratch/$OPERATOR_ID" "/etc/epm/pilot0-operators/$OPERATOR_ID"
     sudo docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges \
       --user "$HOST_UID:$HOST_UID" --tmpfs /tmp:rw,nosuid,nodev,noexec,size=32m \
       --mount "type=bind,source=/etc/epm/pilot0-operators/$OPERATOR_ID,target=/control,readonly" \
       --mount "type=bind,source=/srv/epm/data/workspace/$OPERATOR_ID,target=/data/workspace" \
       --mount "type=bind,source=/srv/epm/data/control/$OPERATOR_ID,target=/data/control" \
       --mount "type=bind,source=/srv/epm/data/scratch/$OPERATOR_ID,target=/data/scratch" \
       --mount type=bind,source=/run/epm-backup-proxy,target=/run/epm-backup-proxy \
       --entrypoint /opt/epm/venv/bin/python epm-pilot0-operator:h0610 -B -c '
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
     b = cfg.binding
     clock = lambda: time.time_ns() // 1_000_000
     svc = HostedWorkspaceRecoveryService(
         recovery_engine=create_sqlite_engine(cfg.recovery_database),
         access_engine=create_sqlite_engine(cfg.access_database),
         backup_engine=ChunkedAeadBackupEngine(UnixBackupProxyClient(cfg.backup_proxy_socket, expected_proxy_uid=cfg.backup_proxy_uid)),
         operator_id=b.scope.operator_id, workspace_id=b.scope.workspace_id, deployment_id=b.deployment_id,
         workspace_root=Path("/data/workspace"), scratch_root=cfg.scratch_directory, release_ref=cfg.release_ref,
         business_schema_revision=cfg.business_schema_revision, access_schema_revision=cfg.access_schema_revision,
         clock=clock,
     )
     sched = WorkspaceBackupScheduler(
         svc, deployment_id=b.deployment_id, operator_id=b.scope.operator_id, workspace_id=b.scope.workspace_id,
         clock=clock, nightly_interval_ms=1000, jitter_window_seconds=0,
     )
     print("RUN_ONCE:", sched.run_once(), svc.read_protection_status())
     '
     sudo chown -R 65532:65532 "/srv/epm/data/workspace/$OPERATOR_ID" "/srv/epm/data/control/$OPERATOR_ID" "/srv/epm/data/scratch/$OPERATOR_ID" "/etc/epm/pilot0-operators/$OPERATOR_ID"
     sudo docker start "epm-op-$WORKSPACE_SLUG"
     sleep 12
     ```
   - Confirm `/health/live` and `/health/ready` both return `200`, `workspace_recovery_status` in `admin.sqlite` reports `healthy`, and public HTTPS ingress redirects cleanly (`HTTP/2 303` → `https://login.epmdemo.xyz/auth/start?...`):
     ```bash
     sudo docker exec "epm-op-$WORKSPACE_SLUG" /opt/epm/venv/bin/python -B -c \
       "import http.client
     for path in ('/health/live', '/health/ready'):
         c = http.client.HTTPConnection('127.0.0.1', 8081, timeout=2)
         c.request('GET', path)
         r = c.getresponse()
         print(path, r.status, r.read().decode())"

     sudo python3 -c '
     import sqlite3
     c = sqlite3.connect("/srv/epm/data/host/h0312-identity/admin.sqlite")
     print(c.execute("SELECT operator_id, protection_state, source_epoch, verified_at FROM workspace_recovery_status").fetchall())
     '

     curl -sS -D - -o /dev/null "https://$WORKSPACE_SLUG.epmdemo.xyz/auth/start" | grep -i -E 'HTTP/|location:'
     # Expect: HTTP/2 303 + location: https://login.epmdemo.xyz/auth/start?flow=...&source=...
     ```
   - *(One-time / if `curl` above does not return `303`)* Confirm **Cloudflare DNS** routes `*.epmdemo.xyz` (CNAME, Proxied) to `d87e220e-e2a9-48c5-a67b-318255777bce.cfargotunnel.com` (`epm-h02-qualification`) and **Cloudflare Zero Trust → Access → Applications** has no Access gate blocking `$WORKSPACE_SLUG.epmdemo.xyz`.
   - Confirm Admin-lite (`https://admin.epmdemo.xyz/`) shows the operator status as **Ready** (`ready_for_claim`).

4. **Add Google OAuth Allowlist Entry, Deliver Claim URL & Sync Assignment Revision (D1, D2):**
   - In GCP Console (`project-47b72bb7-ba90-42c9-910` → **Google Auth Platform → Audience → Test users**), add the operator's exact Google email address.
   - In Admin-lite (`https://admin.epmdemo.xyz/`), open the operator detail page, click **Issue / reissue invitation**, copy the single-use invitation claim URL, email it manually from `dctech92130@gmail.com` (including the D4 Pilot 0 disclosure), and click **Mark delivered**. *(Note: **Issue / reissue invitation** is a sensitive Admin action requiring a recent MFA sign-in; if it displays `Start Admin sign-in again.`, click **Sign out**, sign back in with Google + TOTP MFA, and click **Issue / reissue invitation** again.)*
   - **Sync `assignment_revision` after issuing/delivering the invitation:** Issuing and marking an invitation delivered increments `operators.revision` in `admin.sqlite`. Re-run `launch_operator.py` and restart `epm-h03-identity.service` so both the Operator container and Central hold the matching `assignment_revision` before the operator clicks **Continue with Google**:
     ```bash
     sudo /opt/epm/host-agent/bin/python -B /opt/epm/pilot0/launch_operator.py "$OPERATOR_ID"
     sudo systemctl restart epm-h03-identity.service
     sleep 20
     sudo systemctl is-active epm-h03-identity.service
     ```
   - *(Note: Pilot 0 uses **Continue with Google**; the email sign-in link route is intentionally held/omitted.)*

5. **Confirm Claim, Bind Verified Subject & Activate First Session:**
   - Have the invited operator open their claim URL (`https://$WORKSPACE_SLUG.epmdemo.xyz/auth/start#invitation=...`) and complete **Continue with Google** with their allowlisted Google account.
   - Confirm their verified Google session was recorded in `admin.sqlite` (and check whether `operators.subject` is still `None`):
     ```bash
     sudo -E python3 -c '
     import os, sqlite3
     op_id = os.environ["OPERATOR_ID"]
     c = sqlite3.connect("/srv/epm/data/host/h0312-identity/admin.sqlite")
     print("operator:", c.execute("SELECT operator_id, workspace_slug, setup_state, subject, revision FROM operators WHERE operator_id = ?", (op_id,)).fetchone())
     print("verified sessions:", c.execute("SELECT issuer, subject, email_key FROM managed_identity_sessions WHERE operator_id = ? ORDER BY issued_at DESC LIMIT 2", (op_id,)).fetchall())
     '
     ```
   - If `operators.subject` is still `None` after their first Google verification (Pilot 0 manual claim completion), bind their verified Firebase UID from `managed_identity_sessions` to `operators` (`setup_state = 'active'`), `invitations` (`state = 'claimed'`), and the operator's `access.sqlite` (`effective_access = 'enabled'`), then relaunch the operator and restart `epm-h03-identity.service`:
     ```bash
     sudo -E python3 -c '
     import os, sqlite3, time
     op_id = os.environ["OPERATOR_ID"]
     now = int(time.time() * 1000)
     ac = sqlite3.connect("/srv/epm/data/host/h0312-identity/admin.sqlite")
     row = ac.execute(
         "SELECT issuer, subject FROM managed_identity_sessions WHERE operator_id = ? ORDER BY issued_at DESC LIMIT 1",
         (op_id,),
     ).fetchone()
     assert row, "No verified managed_identity_sessions row found for operator yet"
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
     sudo systemctl restart epm-h03-identity.service
     sleep 20
     sudo systemctl is-active epm-h03-identity.service
     sudo docker ps --filter "name=epm-op-$WORKSPACE_SLUG"
     ```
   - Have the operator open a fresh tab to `https://$WORKSPACE_SLUG.epmdemo.xyz/`, click **Continue with Google**, and click **Continue to your workspace** (on both confirmation screens) to land in `/home`.
   - Confirm Admin-lite transitions **Pending → Ready → Active** and protection status reports **Healthy** (or **Unchanged**), or verify in `admin.sqlite`:
     ```bash
     sudo /opt/epm/python/bin/python3 -c '
     import sqlite3
     conn = sqlite3.connect("/srv/epm/data/host/h0312-identity/admin.sqlite")
     for row in conn.execute(
         "SELECT o.operator_id, o.workspace_slug, o.setup_state, o.desired_access, o.subject, r.protection_state "
         "FROM operators o LEFT JOIN workspace_recovery_status r ON r.operator_id = o.operator_id "
         "ORDER BY o.updated_at DESC LIMIT 5"
     ):
         print(row)
     '
     ```

---

## 3. Exception Handling (Safe Retry & Seed Failure)

### Lost-Response Create / Provision / Enable (`lost_response_retry_original`)
- **Never** create a second assignment with a new slug or new `operation_id`.
- Inspect the original `operation_id` and `idempotency_key` in Admin-lite.
- Retry with the **exact original payload and `idempotency_key`**:
  - Identical payload returns the original identity and converges without duplicating containers, quotas, or invitations.
  - Changed payload on the same `idempotency_key` fails closed with `409 Conflict`.
  - Unknown completion stays visibly `unknown` until verified by source inspection.

### Interrupted Fresh Seed (`seed_failure_disabled`)
- If optional synthetic portfolio seeding fails or is interrupted:
  - Keep business ingress **disabled (`held`)** and state **`needs_attention`**.
  - Inspect owned resources for the original `operator_id` / `workspace_id`.
  - Run deliberate cleanup and reseed using the **original reviewed identities** — never auto-replay a seed over live operator business data.
