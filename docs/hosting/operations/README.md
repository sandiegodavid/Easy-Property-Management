# Hosted MVP Operations & Deployment Handbook

This directory is the single source of truth for provisioning, packaging, operating, monitoring, recovering, and qualifying the live Pilot 0 hosted environment (`epm-h02-host` / `epmdemo.xyz`).

## Handbook Index

| Guide | Covers |
| --- | --- |
| [host-provisioning-and-packaging.md](host-provisioning-and-packaging.md) | GCP VM/VPC/disk/`prjquota` setup, Cloud KMS, Cloudflare R2 & Secret Manager, D5 bootstrap authority, offline OCI packaging/builds, zero-checkout 6-store checks, and Pilot 0 host bring-up. |
| [host-services-and-networking.md](host-services-and-networking.md) | `systemd` units, `epm-backup-proxy.service`, `epm-host-guardian.service`, `service_runtime` CLI, Caddy/nftables/egress proxy, live HTTP security headers, and emergency containment. |
| [identity-and-admin-recovery.md](identity-and-admin-recovery.md) | Managed identity (`selection.json` re-pinning, Google OAuth Testing allowlist, mail quotas, 5-min provider outage handling), offline `admin_bootstrap` CLI, and Admin control-plane recovery. |
| [backup-restore-and-maintenance.md](backup-restore-and-maintenance.md) | Nightly schedulers, `recovery-status.sock` relay, Operator restore & Minimal Recovery Mode, Admin `repair_runtime`, whole-host control loss reconstruction, and 4-phase announced maintenance windows. |
| [observability-and-budgets.md](observability-and-budgets.md) | Structured redacted JSON logging, negative secret-leak audit, GCP Ops Agent, 3 log-based metrics, 7 Cloud Monitoring alert policies, external uptime check, and `$250/mo` before-credit budget. |
| [pilot0-admission-and-incidents.md](pilot0-admission-and-incidents.md) | End-to-end manual Pilot 0 Operator admission & capacity checks, safe retry/seed failure handling, alert triage matrix, runtime repair, audited break-glass policy, and 7-day retirement window. |
| [local-dev-and-qualification.md](local-dev-and-qualification.md) | Mac Docker Desktop lab, Lima native Linux qualification, Playwright UI verification gate, and native GCP qualification runners. |

---

## Live Pilot 0 Host Inventory & Constants

```bash
export PROJECT_ID="project-47b72bb7-ba90-42c9-910"
export PROJECT_NUMBER="732190125040"
export BILLING_ACCOUNT="0129C0-EFF863-71F114"
export ZONE="us-west1-b"
export INSTANCE="epm-h02-host"
export SUPPORT_EMAIL="dctech92130@gmail.com"
export OWNER_NAME="DC Technology"
```

| Resource | Live Value |
| --- | --- |
| **Owner & Support (`EPM_SUPPORT_CONTACT`)** | `DC Technology` · `dctech92130@gmail.com` · GCP credits expire `January 22, 2027` |
| **VM & OS** | `epm-h02-host` (ID `6955052781247608210`), `e2-standard-2` (2 vCPU / 8 GiB RAM), `us-west1-b`, Ubuntu 24.04 AMD64 (`7.0.0-1017-gcp`), Docker `29.9.3`, Python `3.14.10` (`/opt/epm/python/bin/python3`), Caddy `2.11.9`, `cloudflared` `2026.10.7`, Ops Agent `2.73.0~ubuntu24.04` |
| **Disks & Data Mount** | 20 GiB boot + 50 GiB `epm-h02-host-data` (`epm-h02-data`, auto-delete `false`), mounted at `/srv/epm/data` (`ext4`, `rw,prjquota,nodev,nosuid,noexec`, UUID `8d2fd2e0-274b-4535-90d5-da78aa6bd9b6`) |
| **Network & SSH** | VPC `epm-h02-network` / subnet `epm-h02-subnet` (`10.80.0.0/24`); IAP-only TCP/22 (`35.235.240.0/20`) — always pass `--tunnel-through-iap` |
| **Domain & Cloudflare Tunnel** | `epmdemo.xyz` (`admin.epmdemo.xyz`, `login.epmdemo.xyz`, `<slug>.epmdemo.xyz`); Tunnel `epm-h02-qualification` (`d87e220e-e2a9-48c5-a67b-318255777bce`), `*.epmdemo.xyz` CNAME → `d87e220e-e2a9-48c5-a67b-318255777bce.cfargotunnel.com` |
| **Deployment & Host IDs** | Host ID `5a245678-b983-49d3-ab57-818b6c6bdc67` · Deployment ID `b77f7c7e-c89c-4d44-b337-e8d4f13ee46f` · Realm alias `identity-epmdemo-v1` |
| **Cloud KMS** | Keyring `epm-h05-recovery` (`us-west1`), keys `operator-workspace-kek` and `admin-control-kek` (90-day rotation) |
| **Cloudflare R2 & Secrets** | Bucket `epm-hosted-recovery` (WNAM, account `af47b25f59f829ac1fea7ceee6b2a6e3`), token `epm-h05-backup-proxy`, GCP Secret `epm-h05-r2-credentials`; Tunnel secret `epm-tunnel-d87e220e-e2a9-48c5-a67b-318255777bce` |
| **Monitoring & Budget IDs** | Email channel `10994584444383148615` · Uptime check `epm-pilot0-host-heartbeat-LjGDGoURNUM` · `$250/mo` Budget `7b2ec8a9-1f99-4e31-a74b-040623e8d33a` · 7 alert policies (see [observability-and-budgets.md](observability-and-budgets.md)) |
| **Pinned Pilot 0 Artifacts** | `epm-pilot0-admin:h0610` (`sha256:22506437168079fc65f56a2a0d9dacad61749bd5ca46484fae1f1ebf492cc70f`) · `epm-pilot0-operator:h0610` (`sha256:7b0e6791a60ddf3faac7d7633e992fcbcb0fd557021aaf001b2f144a7427864e`) · `host-agent.tar.gz` (`sha256:61af280717f49de0577b0291d3a1e2716fc4c0990174a18bdbd7bffbf3c74314`) |
| **Pinned Policy, Release & Seed** | Free v1 policy `05038762-822b-5aa1-8906-99c94decabbc` · Qualified release `00000000-0000-4000-8000-000000000610` · Synthetic demo seed `synthetic-demo-v1:2ad5ca6acec28823a2988c77e3c81e0bfc2bec61d43839db8e1324b73761aa5a` |

---

## VM Start / Stop & Critical Operational Gotchas

```bash
# Start VM (only when actively running live operations or Pilot 0 is serving)
gcloud compute instances start "$INSTANCE" --project="$PROJECT_ID" --zone="$ZONE"

# SSH / SCP (always via IAP)
gcloud compute ssh "$INSTANCE" --project="$PROJECT_ID" --zone="$ZONE" --tunnel-through-iap

# Stop VM when idle during qualification
gcloud compute instances stop "$INSTANCE" --project="$PROJECT_ID" --zone="$ZONE" --format='value(name,status)'
```

1. **Host Python Version:** Always use `/opt/epm/python/bin/python3` (Python 3.14) or `/opt/epm/host-agent/bin/python` on `epm-h02-host` — never Ubuntu's system `/usr/bin/python3` (3.12).
2. **macOS Tarballs:** Always pass `COPYFILE_DISABLE=1 tar --no-xattrs --exclude='._*'` when packaging from macOS; AppleDouble `._*` files cause `schema_resources.py` and `hosted_package.py` to reject the tree.
3. **macOS Temp Paths in Local Tests:** Resolve `tempfile.TemporaryDirectory` via `Path(td).resolve()` and `chmod(0o700)` before calling `initialize_store()`.
4. **Caddy GET-Only & Cold JWKS:** `HEAD` (`curl -I`) returns `403` by design. Cold `POST /auth/complete` may hit Caddy's 5s upstream timeout once before JWKS warms in memory.
5. **Atomic Writes & Service Ordering:** Always write `/run/epm/maintenance-notice.json`, `/etc/epm/h0312/provider.json`, and bearer files via temp file + `os.replace`. Service refresh order is `gateway -> egress -> tunnel`.
