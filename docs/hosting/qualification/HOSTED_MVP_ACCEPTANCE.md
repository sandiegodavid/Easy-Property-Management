# Hosted MVP Acceptance Register (`HOSTED-001`)

**Updated:** 2026-11-24 · **Pilot 0 (`H01–H06`) Status: GO (6/6 live GCP launch-day gates complete)** · **`H07–H12` Status: Planned (gated on 4-week Pilot 0 evaluation)**

This register tracks actual qualification evidence separately from design requirements ([HOSTED_MVP_DESIGN.md](../design/HOSTED_MVP_DESIGN.md)). A skipped test is never a passing gate; new code or configuration requires fresh proof rather than relabeling old runs.

---

## Stage-Specific Release Gates

| Stage | Required Evidence | Status |
| --- | --- | --- |
| **H01–H05 Preparation** | Private container/storage/ext4 `prjquota` isolation, managed identity & Admin MFA, Admin-lite manual provisioning/retry, Free 50 MB logical + physical sizing, encrypted off-host R2 + Cloud KMS recovery (`SO_PEERCRED` `epm-backup-proxy`), and rehearsed operator/control-plane restore. | **Complete** |
| **H06 — Pilot 0** | Immutable `docker_linux` 6-store OCI images, live GCP observability (3 log-based metrics, 7 alert policies, uptime check, `$250/mo` before-credit budget, Ops Agent), live GCP 17-case `recovery.json` + live R2/KMS proxy proof, deployed 4-browser positive `identity_handoff.json`, live GCP 9-case `operations_economics.json`, and sealed operational owner/worksheet. | **GO (6/6 live GCP gates complete, 2026-11-24)** — see [H06.10 Exit Review](reports/HOSTED_MVP_H06_10_EXIT_REVIEW.md) |
| **H07–H12 — Full Hosted Target** | Automated provisioning & transactional mail (`H07`), Paid 1/2 sizing & 15-min RPO (`H08`), Stripe billing (`H09`), per-operator release scheduling (`H10`), Free idle suspension/wake (`H11`), paid pilot & 100-operator qualification (`H12`). | **Not established** (gated on 4-week Pilot 0 repeat-use evaluation) |
| **Portal Follow-Up** | `PORTAL-001/002`, `FIN-009`, and `PAY-001/002` source/privacy/payment/browser gates (outside HOSTED-001 / Pilot 0). | **Not established** |

---

## Pilot 0 Live Launch-Day Gates (`H06.10` — 6/6 Complete)

All six live GCP launch-day gates passed on `epm-h02-host` (`epmdemo.xyz`) with 47/47 H06 code-review findings closed:

1. **Owner & Economics Baseline:** [PILOT_0_COST_AND_OPS_WORKSHEET.md](reports/PILOT_0_COST_AND_OPS_WORKSHEET.md) (`DC Technology`, `dctech92130@gmail.com`, GCP credits expiry `January 22, 2027`, baseline estimate `~$56–$62/mo` vs `$250/mo` ceiling).
2. **Immutable Production OCI Images & Zero-Checkout 6-Store Proof:** [HOSTED_MVP_H06_10_DOCKER_LINUX_IMAGE_SCHEMA.json](reports/HOSTED_MVP_H06_10_DOCKER_LINUX_IMAGE_SCHEMA.json) (`epm-pilot0-admin:h0610`, `epm-pilot0-operator:h0610`, `host-agent.tar.gz`).
3. **Live GCP Observability, Alerts, Budget & Ops Agent:** [HOSTED_MVP_H06_10_LIVE_OBSERVABILITY.json](reports/HOSTED_MVP_H06_10_LIVE_OBSERVABILITY.json) (channel `10994584444383148615`, 7/7 alert policies, 3 log-based metrics, uptime check, `$250/mo` budget, Ops Agent active).
4. **Live GCP 17-Case `recovery.json` + Live R2/Cloud KMS Proof:** [HOSTED_MVP_H06_10_GCP_RECOVERY_17.json](reports/HOSTED_MVP_H06_10_GCP_RECOVERY_17.json) + [HOSTED_MVP_H06_6_LIVE_R2_KMS_RECOVERY.json](reports/HOSTED_MVP_H06_6_LIVE_R2_KMS_RECOVERY.json) + [HOSTED_MVP_H05_9_RECOVERY_SIZING.json](reports/HOSTED_MVP_H05_9_RECOVERY_SIZING.json).
5. **Live Deployed 4-Browser Positive `identity_handoff.json`:** [HOSTED_MVP_H06_10_DEPLOYED_BROWSER_IDENTITY.json](reports/HOSTED_MVP_H06_10_DEPLOYED_BROWSER_IDENTITY.json) (Google + TOTP MFA on `admin.epmdemo.xyz` & `login.epmdemo.xyz`, logout revocation, uninvited denial).
6. **Live GCP Linux 9-Case `operations_economics.json`:** [HOSTED_MVP_H06_10_GCP_OPERATIONS_ECONOMICS.json](reports/HOSTED_MVP_H06_10_GCP_OPERATIONS_ECONOMICS.json) + [HOSTED_MVP_H04_9_FREE_SIZING.json](reports/HOSTED_MVP_H04_9_FREE_SIZING.json).

---

## Remaining Gates Before `H07–H12` Expansion

| Gate | Required Result | Status |
| --- | --- | --- |
| **Pilot 0 4-Week Demand Gate** | `>= 5` genuine invited Free operators, `>= 3` weekly recurring users for 4 consecutive weeks, 0 unresolved critical isolation/data-loss defects, verified nightly backup + live restore drill, gross spend `<= $250/mo` before credits. | **In progress** (tracked in [PILOT_0_COST_AND_OPS_WORKSHEET.md](reports/PILOT_0_COST_AND_OPS_WORKSHEET.md)) |
| **Automated Onboarding (`H07`)** | Durable jobs/reservations, deduplicated transactional mail, automatic claim/readiness activation, safe reconciliation. | Not established |
| **Paid Tier Sizing & 15-Min RPO (`H08`)** | Independently qualified `200 MB` and `1 GB` physical `prjquota` profiles, downgrade overage retention, 15-min recent RPO + 30/90-day daily thinning. | Not established |
| **Stripe Billing (`H09`)** | Verified webhook inbox, confirmed payment before paid benefits, prorated upgrades, scheduled downgrade/cancel, 7-day renewal grace. | Not established |
| **Independent Releases (`H10`)** | Canary/bounded batches, per-operator update window/timezone/deferral, forward-only schema evolution without recreating Pilot 0 stores. | Not established |
| **Free Idle Suspension & Wake (`H11`)** | All-device activity tracking, polling-free idle detection (~15 min), deduplicated gateway wake, safe waking UX. | Not established |
| **Paid Pilot & 100-Operator Scale (`H12`)** | Google OAuth Production verification, `>= 1` informed paid subscriber, ~20 active of 100 burst/cost qualification within `$300/mo` gross target. | Not established |

Apply the [design validation matrix](../design/mvp/validation.md#required-validation-matrix) across every future gate. Keep secrets and customer data outside all reports.
