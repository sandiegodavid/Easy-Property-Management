# Hosted MVP validation matrix

[Hosted MVP design index](../HOSTED_MVP_DESIGN.md) · [Schema catalog](../../../database/README.md)

Part of the accepted HOSTED-001 design. Requirements here do not establish implementation, deployment or qualification; Pilot 0 exceptions are in the [delivery plan](delivery-plan.md).

### Required validation matrix

Apply this matrix to the capability being admitted. Pilot 0 must pass identity,
isolation, persistence, retry, backup/restore, multi-device conflict and operational
cost gates using its simpler workflows. Billing, paid retention, individual scheduling
and idle-wake cases remain later-stage gates, not Pilot 0 requirements. Mark deferred
cases as not applicable to Pilot 0 rather than claiming they passed.

| Area | Required evidence |
| --- | --- |
| Happy paths | Admit an additional Pilot 0 operator (including a sixth) when qualified capacity permits; Admin creates/claims a Free workspace; independent devices work; paid checkout applies verified benefits; both portals agree on usage/status; scheduling/wake and restore succeed. |
| Invalid combinations | Excess/unknown capacity held for review and concurrent admissions cannot double-spend commitments. Wrong host/identity, unknown/reserved slug, unready workspace, invalid tier, over-budget capacity, unsafe mount/path, invalid image/schema and forged billing/invitation/handoff are rejected. |
| Idempotency/retry | Lost responses, duplicate clicks/events, out-of-order subscription updates, invitation resend, interrupted Docker/config publication and worker restart preserve one operation/effect. Changed input under the same key conflicts. |
| Transactions and failure | Business/audit/receipt rollback, quota failure during commit, staged-file cleanup, unknown external effects, stale worker leases, later disable, schema-failure rollback and post-reopen write preservation. |
| Persistence/schema | Current exact store schemas, separate authority, proper SQLite/WAL capture, one writer, committed runtime policy, supported image/schema combinations and no portable-backup credentials. |
| Backup/restore | Internal backup/restore independent of Admin availability; damaged-business-DB authenticated recovery mode; unavailable/auth-damaged runtime fails closed with no offline restore/decrypt bypass; checkpoint reconciliation after commit-before-crash and file-only changes; interrupted locator switch and no second writer. Database plus files, incremental chain/key availability, promised retention, actual off-host-point age, corrupted/missing objects, separate Admin recovery DB/catalog and current recovery-authority bootstrap, loss of main Admin without losing recovery state, loss of recovery store/whole host and no revival of historical sessions/grants. |
| Authentication/isolation | Cross-subdomain login/CSRF/replay/open-redirect tests; host-only cookies; another operator's API/cache/file denial; container/host-agent authority and direct-origin access denial; MFA-protected Admin. After Admin disable, a locally forced enabled flag/old cookie cannot bypass external denial; test long-lived connections, unreachable source, failed containment, restart/replacement persistence, stale enable replay and fresh authorized re-enable. Partial containment/source outcomes remain visible and cannot report completed disablement. |
| Per-tier storage sizing | For 50,000,000 / 200,000,000 / 1,000,000,000 logical bytes, record per-tree allocated-byte/inode peaks at full allowance, workload/configuration pins, justified margins and actual enforced limits. Independently exhaust bytes and inodes at proposed real ceilings, prove rollback/data/receipt integrity and bounded cleanup/retry/reopen, and qualify separate backup/restore reservations. Preserve input and truthful logical usage/availability in operator/Admin UI. Follow the [complete sizing gate](subscriptions-storage-and-runtime.md#per-tier-physical-storage-sizing-acceptance); trial constants are not production qualification. |
| Billing/storage | Payment-before-apply, capacity reservation expiry, confirmed versus unknown delivery/refund, grace/end-of-period changes, over-quota retention, request versus account limits, physical ceilings and no silent deletion. |
| Multi-device/updates | Independent Admin/Operator/Tenant/Owner version assignments, compatible old/new portal-to-runtime combinations, incompatible pairing rejection and component-only rollback without business-data rollback; stale edits/takeover, visible/hidden tabs, refresh failure with stale values, scheduled/inactive upgrades, unfinished forms, active uploads and no automatic replay after interruption. Verify bounded automatic reconnection only after readiness/current authorization, original-result lookup for uncertain submissions, draft-preserving asset reload and current-contract revalidation; expired sessions and later disable remain enforced. |
| Query budget/performance | Bounded set-based Admin projections without per-row workspace/provider calls; bounded polling/reconciliation; headroom under admitted workload, sleeping/warm mix and simultaneous wake-up pressure. |
| UX/accessibility | Clear Pending/Applied/Failed/Unknown/degraded states, retained input/focus/scroll, both themes, keyboard/narrow views, comprehensible quota/billing/update/recovery messages. Verify maintenance notice, Updating state, safe reload prompt, actionable failure/unknown status and support, no diagnostic disclosure to operators and no blocking announcement for an inactive operator after a successful update. |
| Operational economics | Before-credit spend at launch and growth; realistic backup bytes/traffic; actionable external alerts, restart/boot behavior, operator/control recovery drill and a documented response when capacity/cost exceeds assumptions. |

This plan does not itself change code, schemas, cloud configuration or deployment.
The backlog now authorizes HOSTED-001 implementation in the [delivery-plan order](delivery-plan.md#implementation-slices). Final technical selection of quota/backup mechanisms, host sizing and
transactional email is an implementation proof gate, not permission to omit the promised
workflow. New product/price promises need measured acceptance before publication.

