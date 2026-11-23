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
   - Create the operator assignment with exact email, canonical slug, pinned Free 50 MB allowance, and choice of **empty** (default) or **small synthetic portfolio**.
   - Record the returned `operator_id`, `workspace_id`, and `operation_id`.
2. **Run Supported Provisioning Completion:**
   - Execute the supported host-agent provisioning sequence for the recorded `operator_id` / `operation_id` (no generic shell, no public Docker socket).
   - Confirm `host_inventory.sqlite` binds a dedicated UID/GID, ext4 `prjquota` trees (`workspace`, `control`, `scratch`), and private container runtime.
   - Confirm the initial verified recovery point succeeds via `epm-backup-proxy` before enabling business ingress.
3. **Verify Readiness & Enable Ingress:**
   - Confirm `/health/ready` returns `200` on loopback inside the operator container and Admin-lite shows status **Ready** (never bypass source readiness or protection checks).
4. **Deliver Out-of-Band Invitation Claim URL (D2):**
   - Copy the single-use invitation claim URL from Admin-lite.
   - Send the invitation email manually from the real owned Pilot 0 support mailbox (`EPM_SUPPORT_CONTACT`) including the D4 Pilot 0 disclosure.
5. **Confirm Claim & First Active Session:**
   - Wait for the invited verified identity to claim the exact assignment.
   - Confirm Admin-lite transitions **Pending → Ready → Active** and protection status reports **Healthy** (or **Unchanged**).

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
