# HOSTED-001 Slice H06.8 Checkpoint — Pilot 0 Operations Runbooks & Cost/Admin-Minutes/Adoption Worksheets

**Date:** 2026-11-23  
**Slice:** `H06.8` (of [HOSTED_MVP_H06_DESIGN.md](../../design/HOSTED_MVP_H06_DESIGN.md))  
**Status:** Complete (ready for `H06.9`)

---

## 1. Deliverables Completed

- **Pilot 0 Admission & Capacity Review Runbook:** [H06_8_PILOT0_ADMISSION_AND_CAPACITY_RUNBOOK.md](../../runbooks/H06_8_PILOT0_ADMISSION_AND_CAPACITY_RUNBOOK.md)
  - Covers capacity-based admission (no hidden 5-operator cap; fail-closed `Capacity review required` when headroom is unknown/stale/exhausted), D1 Google OAuth Testing allowlist, D2 manual invitation claim URL email, D4 Pilot 0 disclosure, lost-response idempotent retry (`lost_response_retry_original`), and interrupted fresh-seed cleanup (`seed_failure_disabled`).
- **Pilot 0 Incident Response, Support Triage, Break-Glass & Retirement Runbook:** [H06_8_INCIDENT_SUPPORT_AND_RETIREMENT_RUNBOOK.md](../../runbooks/H06_8_INCIDENT_SUPPORT_AND_RETIREMENT_RUNBOOK.md)
  - Covers the 4-source alert triage matrix (backup alerts, host guardian containment, disk/RAM/CPU headroom, external host-loss heartbeat), `repair_runtime` without silent DB reinit, operator-authenticated recovery mode with zero offline Admin decrypt bypass (H05 D1 / D10), metadata-only default support with consented audited break-glass, and deliberate retirement (`disable` → final verified recovery point → 7-day hold → `retire_resources` + verified cleanup).
- **Pilot 0 Announced Shared Maintenance Window & Cohort Release Runbook:** [H06_8_ANNOUNCED_MAINTENANCE_WINDOW_RUNBOOK.md](../../runbooks/H06_8_ANNOUNCED_MAINTENANCE_WINDOW_RUNBOOK.md)
  - Covers immutable artifact + 9-case `image_schema.json` prerequisites, `/run/epm/maintenance-notice.json` (`announced` → `in_progress` → cleared), cohort email notice, work draining + draft preservation (`Updating your workspace`), verified pre-update recovery points, pinned digest rollout, and post-reopen write preservation (no destructive rollback after reopen).
- **Before-Credit Cost, Admin-Minutes & 4-Week Adoption Worksheet:** [PILOT_0_COST_AND_OPS_WORKSHEET.md](PILOT_0_COST_AND_OPS_WORKSHEET.md)
  - Separates observed billed gross charges (integer USD micros, before credits) from unit-price estimates (`~$56–$62/mo` baseline vs `$250/mo` launch envelope), tracks GCP credits expiry date (D9), Admin/support minutes per task, and privacy-preserving 4-week recurring-use adoption (≥5 genuine invited operators, ≥3 weekly active for 4 consecutive weeks via aggregate non-content business-mutation counts, excluding demos/polling).

---

## 2. Validation Results

- Documentation-only slice; all 4 deliverables cross-checked against [HOSTED_MVP_H06_DESIGN.md](../../design/HOSTED_MVP_H06_DESIGN.md) (D1–D10) and [operations_economics.md](../specifications/operations_economics.md).
- `epm-h02-host` remained **STOPPED** throughout H06.8.

---

## 3. Next Slice

Proceed to **H06.9 — 9-Case `operations_economics.json` Qualification** (`qualify_h06_pilot0.py` + `HOSTED_MVP_H06_9_OPERATIONS_ECONOMICS.json`).
