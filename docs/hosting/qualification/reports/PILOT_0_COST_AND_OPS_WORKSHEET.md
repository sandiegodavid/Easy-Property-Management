# Pilot 0 Before-Credit Cost, Admin-Minutes & 4-Week Adoption Worksheet

**Owner:** `DC Technology`  
**Support Contact (`EPM_SUPPORT_CONTACT`):** `dctech92130@gmail.com`  
**Deployment:** `epm-h02-host` (`project-47b72bb7-ba90-42c9-910` / Project Number `732190125040`, Billing Account `0129C0-EFF863-71F114`, `us-west1-b`, `epmdemo.xyz`)  
**Gross Monthly Launch Budget Target (Before Credits):** `$250.00 / month` (`250_000_000` USD micros)  
**GCP Credits Expiry Date (D9):** `January 22, 2027`

> **Accounting Rules (D9 / `operations_economics.md`):**
> - Record all monetary amounts in **integer USD micros** (`$1.00 = 1_000_000` micros) **before credits** (never subtract promotional credits when evaluating viability).
> - Separate **observed billed charges** from **unit price estimates** (with effective date and currency).
> - Measure weekly recurring use **strictly via aggregate non-content workspace business-mutation counts** (weekly delta in committed business DB revision / audit event count). **Exclude** seeded/demo assignments, Admin checks, and read-only background polling. No session recording or ad tracking.

---

## 1. Unit Price Reference Baseline (Effective Date: 2026-11-23, Currency: USD)

| Resource | SKU / Service | Unit Price (Est.) | Monthly Gross Est. (USD Micros) | Source |
| --- | --- | --- | --- | --- |
| Compute VM (`e2-standard-2`, 2 vCPU / 8 GB, `us-west1`) | GCE On-Demand (730h/mo) | ~$0.067 / hr | `48_910_000` ($48.91) | GCP Pricing |
| Boot Disk (20 GB `pd-balanced`) + Data Disk (50 GB `pd-balanced`) | GCE Persistent Disk | ~$0.10 / GB-mo | `7_000_000` ($7.00) | GCP Pricing |
| Cloud KMS (2 active keys: `operator-workspace-kek`, `admin-control-kek`) | Cloud KMS Software Keys | $0.06 / key-mo + ops | `150_000` ($0.15) | GCP Pricing |
| Secret Manager (2 active secrets: tunnel + R2) | GCP Secret Manager | $0.06 / version-mo | `150_000` ($0.15) | GCP Pricing |
| Cloud Logging & Monitoring (30d retention, 1 VM) | GCP Operations Suite | Free tier / low vol | `0` – `5_000_000` ($0–$5) | GCP Pricing |
| Cloudflare R2 (`epm-hosted-recovery`, Pilot 0 encrypted chunks) | R2 Storage + Class A/B | $0.015/GB-mo (10 GB free) | `0` – `1_000_000` ($0–$1) | Cloudflare Pricing |
| Cloudflare DNS + Tunnel + Universal SSL | Cloudflare Free | $0.00 | `0` | Cloudflare Pricing |
| Firebase / Identity Platform (Google + Email-Link, ≤100/day) | Blaze Free Tier (50k MAU) | $0.00 | `0` | GCP/Firebase Pricing |
| **Estimated Baseline Total (Before Credits)** | | | **`~56_210_000`–`62_210_000` ($56–$62/mo)** | **Well within `$250/mo` envelope** |

---

## 2. Weekly Observed Gross Spend Log (Before Credits)

| Week | Interval (UTC) | GCE VM + Disk (USD Micros) | KMS + Secrets + Logs (USD Micros) | R2 Storage + Ops (USD Micros) | Network / Mail (USD Micros) | **Total Observed Gross (USD Micros)** | Budget Utilization vs `$250/mo` | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Rehearsal (H06.10) | `2026-11-24T03:35Z` – `2026-11-24T05:18Z` | `111_667` (est. 100m `e2-standard-2` @ `$0.067/hr`; reconcile w/ GCP billing export) | `0` (within KMS/Logs free tier) | `0` (5 disposable R2 objects cleaned) | `0` | **`111_667` (est. `$0.11` before credits)** | `0.04%` | All 6 live GCP Gates (1–6) executed on `epm-h02-host`; VM stopped after run. |
| Week 1 | *TBD* | | | | | | | |
| Week 2 | *TBD* | | | | | | | |
| Week 3 | *TBD* | | | | | | | |
| Week 4 | *TBD* | | | | | | | |

---

## 3. Admin & Support Minutes Log

| Date (UTC) | Actor | Task Category (`admission`, `retry`, `maintenance`, `incident`, `recovery`, `retirement`) | Operator ID (or `cohort`) | Elapsed Minutes (Int) | Outcome (`completed`, `needs_attention`, `unknown`) | Follow-Up / Friction Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `2026-11-24T03:35Z` | `DC Technology` | `admission` / `recovery` / `maintenance` | `cohort` (rehearsal) | `45` | `completed` | Executed live GCP Gates 1–4 & 6 (Observability/Ops Agent/Budget, OCI builds & zero-checkout proof, 17-case `recovery.json`, 9-case `operations_economics.json`). |
| `2026-11-24T04:26Z` | `DC Technology` | `admission` / `incident` | `cohort` (Gate 5) | `50` | `completed` | Executed live deployed 4-browser Gate 5 rehearsal on `epmdemo.xyz`; caught & fixed Firebase helper CSP in `firebase_helpers.py`, rebuilt `epm-pilot0-admin:h0610` (`sha256:225064371680...`), verified Google + TOTP MFA sign-in, session isolation, fail-closed capacity/release checks, sign-out revocation, and uninvited denial. VM stopped. |

---

## 4. Four-Week Adoption & Reliability Gate Tracker

**Expansion Gate (to justify H07–H12 investment):**
- [ ] **≥ 5** genuine invited Free operators admitted within qualified capacity.
- [ ] **≥ 3** operators performing recurring business work weekly for **4 consecutive weeks** (non-content committed business-mutation delta > 0; demos/polling excluded).
- [ ] **0** unresolved critical data-loss or cross-operator isolation defects.
- [ ] Nightly backup freshness verified and ≥ 1 live restore drill rehearsed.
- [ ] Observed gross spend before credits within `$250/month` and Admin minutes per operator sustainable.

| Operator Alias (No PII) | Admitted Date | Week 1 Mutations (>0?) | Week 2 Mutations (>0?) | Week 3 Mutations (>0?) | Week 4 Mutations (>0?) | 4-Week Recurring? | Backup Freshness | Support Incidents |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `op-01` | *TBD* | | | | | | | |
| `op-02` | *TBD* | | | | | | | |
| `op-03` | *TBD* | | | | | | | |
| `op-04` | *TBD* | | | | | | | |
| `op-05` | *TBD* | | | | | | | |
