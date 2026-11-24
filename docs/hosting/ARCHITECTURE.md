# Hosted MVP Live Architecture & Accepted Decisions (`H01–H06`)

This document is the single authoritative architectural reference for the live Pilot 0 hosted platform (`H01–H06`). For future `H07–H12` design specifications, see [design/HOSTED_MVP_DESIGN.md](design/HOSTED_MVP_DESIGN.md). For step-by-step operational procedures and live host constants, see [operations/README.md](operations/README.md).

---

## 1. Production Topology

```text
Internet -> Cloudflare Edge -> Cloudflare Tunnel (epm-tunnel.service, LoadCredential)
              -> Caddy Gateway (epm-gateway.service, Unix admin socket, exact-host/method allowlists)
                  ├── admin.epmdemo.xyz   -> Shared Admin/Central container (epm-pilot0-admin:h0610)
                  │                            ├── Admin-lite UI & API (Google + TOTP MFA)
                  │                            ├── AdminControlBackupScheduler (24h jittered + hourly watchdog)
                  │                            ├── Admin Recovery Mode (D5 fallback via /run/epm/admin-recovery-authority.json)
                  │                            ├── POST /internal/recovery-status (SO_PEERCRED + Ed25519)
                  │                            └── Loopback /health/live & /health/ready (:8081)
                  ├── login.epmdemo.xyz   -> Shared Admin/Central container (central login + Firebase helpers)
                  └── <slug>.epmdemo.xyz  -> Isolated Operator container (epm-pilot0-operator:h0610)
                                               ├── Private bridge (10.248.<slot>.0/30), dedicated UID/GID
                                               ├── ext4 prjquota trees (workspace / control / scratch)
                                               ├── WorkspaceBackupScheduler (24h jittered + hourly watchdog)
                                               ├── Minimal Recovery Mode (503 recovery_mode_active on corrupt DB)
                                               ├── RO mount: /run/epm/maintenance-notice.json
                                               └── Loopback /health/live & /health/ready (:8081)

Host Services (systemd, Ubuntu 24.04 AMD64, single lifecycle owner, docker restart=no):
  ├── epm-backup-proxy.service   (uid=940, LoadCredential r2.json, SO_PEERCRED UID -> R2 prefix + Cloud KMS)
  ├── epm-host-guardian.service  (live HostAgent supervision, stop-only containment via StopRegistry)
  ├── epm-h03-identity.service   (shared Admin/Central lifecycle & ingress projection)
  ├── epm-gateway.service        (Caddy v2.11.9, fail-closed exact allowlists)
  ├── epm-tunnel.service         (cloudflared 2026.10.7, scoped tunnel credential)
  └── google-cloud-ops-agent     (metrics + redacted structured JSON logs -> Cloud Monitoring/Logging)
```

---

## 2. State & Store Ownership (6 SQLite Stores)

Executable DDL and table-level dictionaries live in [../database/overview.md](../database/overview.md). No runtime DDL or automatic schema recreation is permitted; schema resources are packaged explicitly per component under `application/database/`.

| Store (`HostedStore`) | Owner | Host Path (`epm-h02-host`) | Responsibility |
| --- | --- | --- | --- |
| `admin` | Admin / Central (`epm-pilot0-admin`) | `/srv/epm/data/host/h0312-identity/admin.sqlite` | Deployment metadata, approved `admin_principals`, `admin_sessions`, `operators`, `invitations`, `operations`, `capacity_profiles`/`snapshots`/`commitments`, `qualified_releases`, `workspace_recovery_status`, `managed_identity_sessions`, `admin_audit`. |
| `admin-recovery` | Admin (`epm-pilot0-admin`) | `/srv/epm/data/host/admin-recovery/admin-recovery.sqlite` | Isolated Admin control-plane backup catalog and restore state (independent of `admin.sqlite`). |
| `host-inventory` | Host Agent (`epm-gateway` / `epm-backup-proxy`) | `/srv/epm/data/host/inventory/inventory.sqlite` (root `0600`) & `/srv/epm/data/host/backup-proxy/inventory.sqlite` | Host/filesystem binding, `operator_principals` (`host_uid`/`host_gid`), `ingress_bindings`, `host_receipts`, quota project reservations, and `cleanup_verified_at`. |
| `business` | Operator (`epm-pilot0-operator`) | `/srv/epm/data/workspace/<operator_id>/active/database/property-management.sqlite` | Core property management business data (identical schema to local desktop app). |
| `hosted-access` | Operator (`epm-pilot0-operator`) | `/srv/epm/data/control/<operator_id>/access.sqlite` | `access_meta` (`effective_access`, `access_epoch`, `effective_policy_id`, `subject`), operator browser sessions, CSRF, and revocation freshness cache. |
| `recovery` | Operator (`epm-pilot0-operator`) | `/srv/epm/data/control/<operator_id>/recovery.sqlite` | `recovery_meta` (`source_generation`, `restore_generation`, `active_business_ref`, KMS key ref, R2 namespace prefix) and `backup_state` (`protection_state`, `last_point_id`, failure tracking). |

**Post-Pilot 0 Schema Evolution Rule:** Once live operator workspaces exist, schema changes must evolve existing stores safely via forward-only Alembic migrations without recreating stores or losing data (see [design/mvp/implementation-contracts.md](design/mvp/implementation-contracts.md)).

---

## 3. Core Architectural Invariants & Accepted Decisions (`H01–H06`)

### Control Plane, Commands & Host Runtime (`H01–H02`)
- **Command & Effect Identity:** Every mutating Admin/Host command carries an explicit `idempotency_key` and canonical `semantic_hash`. Identical retries converge on the original identity; changed payloads on the same key fail closed (`409 Conflict`). Unknown completion stays `unknown` until verified from the owning source.
- **Single Lifecycle Owner:** All containers run with `docker restart=no` under systemd supervision (`epm-host-guardian.service`, `epm-h03-identity.service`). On policy drift, firewall loss, or quota/inventory uncertainty, guardian stops containers (`StopRegistry`) and fails closed.
- **Sandbox & Storage Isolation:** Each operator runs with a dedicated non-root UID/GID, read-only rootfs, dropped capabilities, `no-new-privileges`, pinned AppArmor/seccomp profiles, a dedicated private Docker bridge (`10.248.<slot>.0/30`), and three `ext4 prjquota` trees (`workspace`, `control`, `scratch`) mounted `rw,prjquota,nodev,nosuid,noexec` under `/srv/epm/data`. Stable `writer.lock` files prevent concurrent writers.
- **External Containment:** Business ingress requires both Admin `desired_access = 'enabled'` (`setup_state IN ('ready_for_claim', 'active')`, exact `access_epoch`, verified `protection_state IN ('healthy', 'unchanged')`) and independent gateway/host projection (`WorkspaceRouteManifest`, `desired_state = 'eligible'`). Caddy enforces exact host/method allowlists (`separate_exact_host_method_allowlists_v3`), denies WebSocket `Upgrade` and `/admin`, `/__/auth`, `/internal`, `/debug`, `/metrics` on operator origins, and refuses `HEAD` (`403`).

### Managed Identity & Session Security (`H03`, updated in `H06.1`)
- **Origins & Providers:** `admin.epmdemo.xyz` (Admin-lite: Google + TOTP MFA required), `login.epmdemo.xyz` (Central sign-in & one-use handoff), and `<slug>.epmdemo.xyz` (Operator origin). Opaque realm alias (`identity-epmdemo-v1`); Google OAuth runs in **Testing** mode (allowlist up to 100 test users) for Pilot 0.
- **Email-Link Quota (H06.1 Re-Pin):** Provider allowance is `100/day` (`provider_sends_per_day: 100`); application ceiling is `90/rolling-24h` (`deployment_sends_per_day: 90`), with 60s resend cooldown, 5/hr per-destination, and 20/hr per-network caps. In Pilot 0, Operator sign-in uses **Continue with Google** (the email-link send route is omitted; invitations are emailed manually by the operational owner).
- **Session & Freshness Bounds:** 30-day session ceiling, `<= 14`-day provider proof freshness, **5-minute (`300000 ms`) revocation freshness window** (fail closed `503` on provider outage without falsely revoking sessions), 32-session cap with atomic replacement, `__Host-` cookies, CSRF protection, and strict security headers (`HSTS`, `Permissions-Policy`, `nosniff`, `no-referrer`, `Cache-Control: no-store`, strict `CSP` on all routes except Firebase's `/__/auth/handler` and `/__/auth/iframe` which omit `CSP` so Google/TOTP popups function).
- **Redacted Structured Logging:** All hosted services emit single-line JSON logs via `app.platform.hosted_logging`, redacting `__Host-*` cookies, `Bearer` tokens, JWTs, DEKs, and R2/provider secrets.

### Free Storage Admission & Capacity (`H04`)
- **Logical Storage Formula (H04 D6):** Free v1 allowance is `50,000,000` bytes (`50 MB`) logical storage, computed as:
  `SQLite active bytes ((page_count - freelist_count) * page_size) + sum(distinct content_sha256 local available attachment blobs)`.
- **Two-Layer Storage Enforcement:** Operator logical storage admission runs inside the application against `access_meta.effective_policy_id`, backed independently by host `ext4 prjquota` physical byte/inode ceilings (`HOSTED_MVP_H04_9_FREE_SIZING.json` + `HOSTED_MVP_H05_9_RECOVERY_SIZING.json`).
- **Capacity-Based Admission (No Arbitrary Cap):** 5 or 6 operators is an initial test target, not a hard-coded product limit. New admissions require a complete `capacity_snapshot` and verified disk/inode/RAM headroom; unknown or exhausted headroom holds requests as `Capacity review required`.
- **Seeding:** Real Pilot 0 operators default to **Empty workspace**; optional **Synthetic sample portfolio** requires the pinned `synthetic-demo-v1:<sha256>` seed reference. Interrupted seeding stays `disabled` / `needs_attention` and never auto-replays over live data.

### Off-Host Encrypted Recovery & Maintenance (`H05–H06`)
- **Encryption & Proxy Isolation (H05 D1–D3):** Chunked `AES-256-GCM` backups with per-point DEKs wrapped by GCP Cloud KMS (`operator-workspace-kek` for workspaces, `admin-control-kek` for Admin control). `epm-backup-proxy.service` (`uid=940`) holds R2 credentials via systemd `LoadCredential` and fences every caller to its exact R2 prefix via kernel `SO_PEERCRED` UID → `operator_principals` in `inventory.sqlite`. Containers never see R2 credentials or cross-operator prefixes.
- **Operator-Authorized Restore Only (H05 D1/D10):** There is **no** Admin offline decrypt or customer workspace restore bypass. Workspace restore requires Operator authentication + strong step-up (10-min step-up, 10-min preview, 5-min confirm TTLs), stages into a fresh `incarnation-N` (preserving `prior-N` for 7 days), fences the old writer, and switches atomically.
- **Minimal Recovery Mode & Clean-Runtime Repair:** If `property-management.sqlite` is corrupt or missing, the Operator container boots into Minimal Recovery Mode (`503 recovery_mode_active`) and never initializes an empty DB. Admin's `repair_runtime` rebuilds the container while preserving `operator_id`, `workspace_id`, UID/GID, and data trees.
- **Admin Control Recovery (H05 D5):** If `admin.sqlite` is unreadable, `shared_identity_entry.py` automatically falls back to `create_admin_recovery_app()`, authenticating against `/run/epm/admin-recovery-authority.json` (persisted at `/etc/epm/admin-recovery-authority.json`) + Google + TOTP MFA + live Firebase revocation, while returning `503 admin_recovery_mode_active` on `login.epmdemo.xyz`.
- **Nightly Schedulers & Async Relay (H06 D6–D7):** `WorkspaceBackupScheduler` (Operator) and `AdminControlBackupScheduler` (Admin) run jittered 24-hour captures (`free-nightly-v1` / `admin-nightly-v1`) and hourly overdue watchdogs (28-hour overdue threshold, 7-point retention for workspaces, 14-point policy target). Operator backups are fully independent of Admin availability and report signed summaries asynchronously over `recovery-status.sock` (`POST /internal/recovery-status`, `SO_PEERCRED` + Ed25519).
- **Shared Maintenance Window (H06 D5):** `/run/epm/maintenance-notice.json` (`0644`, `<= 8 KiB`, mounted read-only into Operator containers) drives `announced` banners and `in_progress` (`Updating your workspace`) UX while preserving unfinished client drafts.
- **Audited Break-Glass & 7-Day Retirement (H06 D10):** Support defaults to metadata-only; any broader troubleshooting requires written operator consent and audited time-boxed `admin_audit` entries. Retired workspaces are disabled with a final verified backup on Day 0, held 7 full days, and explicitly retired (`retire_resources` + `cleanup_verified_at`) on Day 7+.
