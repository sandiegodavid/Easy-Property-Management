# Hosting documentation

Updated November 22, 2026. Single entry point for the **HOSTED-001** hosted-MVP
architecture, implementation designs, infrastructure runbooks, and qualification evidence.

## Current Delivery Status

**Pilot 0 releases at H06** (invited Free operators within qualified capacity, Admin-lite,
nightly verified off-host backups and rehearsed restore, warm containers, one announced
maintenance window; no Stripe, idle-wake, or per-operator update scheduling).

| Slice | Scope | Status & Latest Evidence |
| --- | --- | --- |
| **H01** | Baseline, store ownership, schema resources, contracts, proof specs | **Done** — [Design](design/HOSTED_MVP_H01_DESIGN.md) · [Handoff](qualification/reports/HOSTED_MVP_H01_7_HANDOFF_2026-11-11.md) |
| **H02** | Container, ext4 `prjquota` storage, and Cloudflare gateway foundation | **Done** — [Design](design/HOSTED_MVP_H02_DESIGN.md) · [Foundation guides](foundation/README.md) · [Handoff](qualification/reports/HOSTED_MVP_H02_11_HANDOFF.md) |
| **H03** | Managed identity, Admin Google+TOTP MFA, central-login handoff, sessions & draft fencing | **Done** — [Design](design/HOSTED_MVP_H03_DESIGN.md) · [Exit review](qualification/reports/HOSTED_MVP_H03_12_EXIT_REVIEW_2026-11-22.md) |
| **H04** | Admin-lite UI/API, manual provisioning, Free 50 MB logical + physical `prjquota` sizing, Operator Settings | **Done** — [Design](design/HOSTED_MVP_H04_DESIGN.md) · [Exit review](qualification/reports/HOSTED_MVP_H04_10_EXIT_REVIEW_2026-11-22.md) |
| **H05** | Nightly verified off-host recovery, separate Admin recovery DB, operator-authorized restore | **Component proof done (live GCP pending)** — [Design](design/HOSTED_MVP_H05_DESIGN.md) · [Exit review](qualification/reports/HOSTED_MVP_H05_11_EXIT_REVIEW.md) · [Runbook](runbooks/H05_RECOVERY_OPERATIONS_RUNBOOK.md) |
| **H06** | Pilot 0 release, observability, support, maintenance window, and operations/economics gate | **GO (6/6 live GCP gates complete)** — [Design](design/HOSTED_MVP_H06_DESIGN.md) · [H06.10 exit review](qualification/reports/HOSTED_MVP_H06_10_EXIT_REVIEW.md) · [H06.10 launch runbook](runbooks/H06_10_PILOT0_LAUNCH_GATES_RUNBOOK.md) · [Acceptance register](qualification/HOSTED_MVP_ACCEPTANCE.md) |
| **H07–H12** | Provisioning automation, paid tiers/Stripe, independent updates, idle wake, paid pilot | **Planned** — [Delivery plan](design/mvp/delivery-plan.md) |

> Business ingress for Operator workspaces remains **closed (`held`)** and backup protection
> remains honestly **`unavailable`** until H05 supplies the verified recovery-point gate.

## Navigation

| Area | Purpose |
| --- | --- |
| [Design index](design/README.md) | Accepted MVP architecture (`mvp/`), slice designs (H01–H04), and delivery plan |
| [Foundation guides](foundation/README.md) | Delivered H02 container, storage, gateway, identity-contract, and capacity reference by topic |
| [Deployment runbooks](deployment/README.md) | Image packaging, offline agent installation, protected launch, Linux labs, and GCP host setup |
| [Operations runbooks](operations/README.md) | Runtime supervision, gateway/egress services, identity qualification, and Admin account recovery |
| [Qualification & evidence](qualification/README.md) | Acceptance register, proof specifications, UI contract fixtures, and latest exit reviews |
| [Database schema master](../database/overview.md) | Store ownership and per-store SQLite dictionaries (business, Admin, access, inventory) |
| [SQLite upgrade research](research/SQLITE_SCHEMA_UPGRADE_WORKFLOW_2026-10-31.md) | Technical input for H10 release upgrades (subordinate to current one-writer and recovery rules) |

Initial platform: Google Compute Engine (`epm-h02-host`, stopped when not qualifying),
Docker with persistent ext4 `prjquota` trees, Cloudflare edge/Tunnel/R2, Firebase/Google
managed identity, and Stripe (H09). Launch and 100-operator gross budget targets are
\$250 and \$300/month before credits.
