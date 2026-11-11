# Supported manual operations and economics proof — H04/H06

Case authority: [operations_economics.json](operations_economics.json). H04 owns the
supported application workflow; H06 owns pilot rehearsal/support/economic review.
Apply the [common invocation/report/safety rules](README.md). No billing, idle-wake,
individual scheduling or additional module gate is added to Pilot 0.

## Setup and invocation

Use qualified pinned H02–H05 artifacts in a private synthetic pilot environment with
named test Admin/operator/support actors, exact capacity envelope, fixed scenario
clock and safe mail/identity resources. Use one empty and one small synthetic operator.
Pin operation request keys/revisions, allowed manual tooling/runbook revision, unit
cost/price inputs (with effective date/currency) and measurement interval. Actual GCP
cost/provider facts must be captured at run time by H06, not inferred from this plan.

```bash
.venv/bin/python -m app.platform.hosted_proofs execute --spec ../docs/hosting/qualification/specifications/operations_economics.json --inputs /private/proof/inputs.json --output /private/proof/report.json --phase manual
```

Currently exits 3. H04/H06 provide actual manual/GCP/browser driver and runbook steps;
record operator actions/elapsed time through the immutable private scenario manifest.

| Case | Rehearsal and pass/fail observation |
| --- | --- |
| `manual_add_claim_disable` | Add empty/default Free and optional synthetic assignment, complete verified readiness/protection then invitation/claim, disable and try stale session. Pending never appears effectively active; supported manual completion cannot bypass source checks. |
| `lost_response_retry_original` | Lose create/provision/enable response, inspect original operation and retry matching/changed payload. One resource/seed/invitation effect; changed intent conflicts and unknown completion remains explicit. |
| `seed_failure_disabled` | Interrupt the small fresh seed once, keep access disabled/needs attention, inspect owned resources and deliberately cleanup/reseed with reviewed original identities. No seed-stage journal, automatic replay or overwrite of live business data. |
| `announced_maintenance_restart` | Announce one window, drain current work, restart/replace compatible runtime, preserve original outcome/drafts and restore service. Record actual outage and retained bytes/receipts. |
| `runtime_repair_support` | Follow named support/runbook for failed runtime; preserve identity and private stores, fresh operator auth and scoped restore selection if needed. No Admin customer restore bypass or generic shell UI. |
| `backup_alert_support` | Make capture/provider/key unavailable and exceed monitored point-age bound; safe alert/status stays degraded, support can locate original failure and prove verified recovery before clearing it. |
| `gross_spend_admin_minutes` | Record metered VM/storage/object/network/mail costs before credits, Admin/support minutes and measurement interval in integer USD micros/minutes. Separate observed charges from estimates/prices; compare gross launch envelope without declaring viability from one run. |
| `sixth_capacity_not_cap` | Rehearse first five then sixth admission under measured warm capacity. Admit if qualified resources permit; otherwise pending with reason, never enforce a hidden count cap. |
| `unknown_capacity_pending` | Unavailable/stale capacity and simultaneous pending/unknown operations cannot reuse headroom or become healthy/zero. Existing readers/cleanup remain safe. |

## Evidence / cleanup

Retain sanitized screenshots/operation timelines, support procedure revision, actual
resource/cost interval facts and recorded manual minutes. Negative controls must
fail visibly without duplicate effects. No real invitees/customer records, charges,
production cloud changes or support messages are authorized by writing/running the
H01 document validator. Clean up only registered test resources after preserving
failures; do not claim a four-week demand/pilot or paid acceptance from this rehearsal.
