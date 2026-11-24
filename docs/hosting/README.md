# Hosted MVP Documentation (`HOSTED-001`)

**Status:** Pilot 0 (`H01–H06`) **LIVE / GO** (6/6 live GCP launch-day gates complete, 2026-11-24) · **H07–H12** gated on the 4-week Pilot 0 repeat-use evaluation.

Easy Property Management runs as a single-operator hosted workspace per customer: one isolated Operator container and private SQLite + file tree per operator on an Ubuntu 24.04 GCE host (`epm-h02-host`, `epmdemo.xyz`), fronted by Cloudflare Tunnel + Caddy and protected by off-host encrypted Cloudflare R2 + GCP Cloud KMS recovery.

## Documentation Map

| Area | Start Here | What It Covers |
| --- | --- | --- |
| **Live Architecture & Decisions** | [ARCHITECTURE.md](ARCHITECTURE.md) | Production topology, 6-store ownership, security & isolation boundaries, identity/session contracts, logical storage formula, off-host recovery architecture, and accepted decisions (`H01–H06`). |
| **Operations & Deployment Handbook** | [operations/README.md](operations/README.md) | Live Pilot 0 host inventory, pinned digests, GCP provisioning & packaging, host services & networking, identity & Admin recovery, backup/restore & maintenance windows, observability & `$250/mo` budget, Pilot 0 admission & incidents, and local/Lima/GCP qualification. |
| **Future Specification (`H07–H12`)** | [design/HOSTED_MVP_DESIGN.md](design/HOSTED_MVP_DESIGN.md) | Accepted MVP specification ([`design/mvp/`](design/README.md)): H07 automated provisioning, H08 Paid 1/2 sizing & 15-min RPO, H09 Stripe billing, H10 per-operator release scheduling, H11 Free idle suspension/wake, and H12 100-operator qualification. |
| **Qualification & Live Evidence** | [qualification/README.md](qualification/README.md) | [Acceptance register](qualification/HOSTED_MVP_ACCEPTANCE.md), machine-checked proof specifications (`specifications/`), UI contract fixtures (`fixtures/`), and live Pilot 0 GO evidence + 4-week worksheet (`reports/`). |
| **Database Dictionaries** | [../database/overview.md](../database/overview.md) | Executable DDL dictionaries for all hosted SQLite stores (`admin`, `admin-recovery`, `host-inventory`, `hosted-access`, `recovery`, and `business`). |

## Delivery Status (`H01–H12`)

| Slice | Scope | Status |
| --- | --- | --- |
| **H01–H02** | Hosted contracts, command/operation envelopes, offline OCI packaging, GCE/ext4 `prjquota` host, Docker sandbox, Caddy gateway, egress proxy, guardian, and capacity baseline | **Done** |
| **H03** | Managed identity (`admin.epmdemo.xyz` + `login.epmdemo.xyz`), Google + TOTP MFA for Admin, Google/email-link auth (`100/day` provider / `90/24h` app ceiling), one-use handoff, Unix relays, and session/CSRF/CSP enforcement | **Done** |
| **H04** | Free v1 50 MB logical storage admission, Admin-lite operator management, manual provisioning (`ManualProvisioner`), synthetic demo seeding, and Operator Settings | **Done** |
| **H05** | Encrypted off-host recovery (Cloudflare R2 + Cloud KMS + `SO_PEERCRED` `epm-backup-proxy`), Minimal Recovery Mode, clean-runtime repair (`repair_runtime`), Admin control recovery, and verified-backup ingress gate | **Done** |
| **H06** | Live Pilot 0 launch: production OCI images, live GCP KMS/R2/Observability/Alerts/`$250/mo` budget, nightly schedulers, async protection relay, shared maintenance notice, Pilot 0 UI, and 6/6 live launch-day gates | **Done — Pilot 0 LIVE (GO)** |
| **H07–H12** | Automated provisioning & transactional mail (`H07`), Paid 1/2 sizing & 15-min RPO (`H08`), Stripe billing (`H09`), per-operator release scheduling (`H10`), Free idle suspension/wake (`H11`), paid pilot & 100-operator qualification (`H12`) | **Planned** (gated on 4-week Pilot 0 evaluation; see [delivery-plan.md](design/mvp/delivery-plan.md)) |

## Pilot 0 Operating Envelope

- **Platform & Domain:** `e2-standard-2` (`epm-h02-host`, `us-west1-b`, Ubuntu 24.04 AMD64, 20 GiB boot + 50 GiB `ext4 prjquota` data disk) serving `epmdemo.xyz` (`admin.epmdemo.xyz`, `login.epmdemo.xyz`, `<slug>.epmdemo.xyz`).
- **Owner & Support:** `DC Technology` (`dctech92130@gmail.com`).
- **Budget Ceiling:** `<= $250/month` gross spend before GCP credits during Pilot 0 (`<= $300/month` target for 100-operator scale in H12); baseline estimate `~$56–$62/month`.
- **Scope Guardrails:** Free invitation-only pilot; no hard-coded 5-operator cap (capacity-based admission); no Stripe/paid UI, automated provisioning scheduler, per-operator update scheduling, idle suspension/wake, or Tenant/Owner portals in Pilot 0.
- **4-Week Expansion Gate (before H07+):** `>= 5` genuine invited Free operators, `>= 3` weekly recurring operators for 4 consecutive weeks (non-content committed business-mutation delta `> 0`), 0 unresolved critical isolation/data-loss defects, verified nightly backup freshness + `>= 1` live restore drill, and gross spend `<= $250/month` before credits.
