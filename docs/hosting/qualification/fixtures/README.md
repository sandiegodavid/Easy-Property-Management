# H01.6 synthetic UI/API state contracts

[H01_UI_CONTRACTS.json](H01_UI_CONTRACTS.json) freezes 24 synthetic snapshots for
Admin list/add/detail and Operator Settings/recovery. They are **contract fixtures**,
not screens, HTTP routes, current access grants, deployed responses or proof that
focus/scroll/browser behavior works. Usage amounts, IDs, proof references, hashes, timestamps,
people and email addresses are fictional, not actual meter/qualification results; no credentials or business data are included.

[Fixture composition](../../../../application/apps/server/app/bootstrap/hosted_ui_contracts.py)
validates the strict versioned corpus and action-to-port mapping. It is not imported
by current application bootstrap. Each case pins a deployment and a discriminated
owning presentation DTO. Root collections are bounded to 64 cases/512 KiB; action
rows reject duplicates; extra fields, unknown controls and invalid combinations fail.
These are presentation contracts, not new executable database definitions or a copy
of the schema dictionary. The [schema master](../../../DATABASE_SCHEMA.md) still owns
storage; actual adapters/queries/authorization arrive in H03–H05. Current local Settings
and hosted-demo consumers remain unchanged.

## Field defaults and visible state

| Surface / delivery owner | Frozen operator-facing expectations |
| --- | --- |
| Admin list — H04 | Separate setup, desired access and source-effective access; operator/slug, Free usage/freshness, verified protection age, pinned release and original operation. Default list limit 50 with deployment/filter/capture/source-bound continuation. Initial loading and failed registry reads are not empty/zero directories. Source refresh is explicitly admitted as an asynchronous operation. |
| Add operator — H04 | Name, invited email, slug, support contact and qualified release. Default Free 50,000,000 bytes and empty portfolio; synthetic starting data is optional with a pinned seed bundle. No account-expiry/read-only/demo-mode/paid choices. Raw bounded invalid values, multiple field messages and revision-conflict inputs stay visible until reviewed, rather than being coerced or erased. |
| Admin detail — H04 | Independent readiness checks, usage/access/protection, supported provision/repair/status/identity/lifecycle and announced maintenance actions. Unknown/stale facts are not healthy checkmarks; enable remains unavailable until fresh complete readiness. Runtime repair is distinct from customer restore. |
| Operator Settings — H04 | Free pilot/50 MB usage and freshness, backup protection, support contact and announced maintenance only. One failed section does not hide other known sections. Over-allowance state preserves reads/support/cleanup; unknown usage is not zero. No upgrade purchase, per-operator schedule or idle-wake controls. |
| Operator recovery — H05 | Own eligible points, preview, qualified strong recent authentication and exact point/preview/intent confirmation; original restore status/lookup. Separate minimal recovery mode when business startup fails. Missing current identity/runtime/catalog/qualification keeps restore unavailable. No Admin approval, arbitrary destination/key selection or offline bypass. |

Setup codes follow the dictionary (`pending`, `preparing`, `ready_for_claim`, `active`,
`needs_attention`, `retired`). An onboarded account can have setup=`active` while
source access is disabled. `desired_enabled` is a presentation projection of Admin
intent, not another persisted access flag. The default requested access is enabled,
but the pending fixture's verified source access is **disabled** until readiness and
claim. Render setup in context (“Setup pending”, “Preparing”, “Ready to claim”,
“Set up”, “Needs attention”, “Retired”); separately render verified source access as
“Enabled”/“Disabled”, or “Unavailable” when unknown. Do not turn desired intent or
an old successful operation into a current access assertion.

`ready`/`stale` sections carry data with their actual capture/source context. A
`refreshing` section retains the previous known/stale snapshot; it does not claim a
new verified read. Initial loading carries no invented capture. Failed/unavailable
sections carry a safe unknown/unavailable reason and no fabricated data. Known zero
usage remains distinguishable from unknown/null. Last-known data uses stale state;
unknown does not masquerade as a healthy latest observation.

The raw add-form draft intentionally accepts invalid email/slug/text while editing.
Only the owning submit command validates consequential normalized values. Preserve
exact input, focus and scroll across independent refreshes, conflicts, failed reads
and unknown writes. In-flight/unknown submissions retain original operation identity;
checking/retrying cannot allocate a new key, reconstruct changed intent or replay
silently. A form/button state is convenience, not the server duplicate/authority guard.

## Action, authority and confirmation handoff

[ACTION_MAP.md](ACTION_MAP.md) maps every control to an actual H01.4 port/method,
command type, response shape, original-identity rule, authority, confirmation and
end-to-end delivery owner. Navigation to Add is side-effect free; only reviewed
submit creates the assignment operation. A read refresh of Settings goes through
current operator authentication and the owning source adapter; the private
`SourcePort.observe` service authority is supplied internally, never forged from
browser input. Recent authentication similarly uses the H03 managed-proof/browser
binding before the private Login port.

Admin source refresh maps to `AdminPort.execute(RefreshSource)` and returns its
pending/running/unknown original operation. Admin list reads cached verified registry
projections in bounded set-based queries, not one synchronous provider/source call
per row or browser polling used as authority. Change filters/page bounds by discarding
an incompatible continuation; keep capture/source context across a valid continuation.
The 1-row page snapshots illustrate these rules, not actual query-plan acceptance.

Control-plane recovery mappings are reserved to the separate H05 Admin recovery
entry point with current protected bootstrap/MFA, and are intentionally absent from
all five surfaced snapshots. They cannot appear as a customer-workspace repair/restore
button in operator detail. Operator recovery needs current operator/step-up authority;
an Admin session or projection never grants it. Disable/retire/rebind/repair/maintenance
mutations require explicit contextual confirmation; restore confirms exact previewed
point/workspace/action after recent qualified authentication. Persist only safe IDs/
references; labels must not display raw operation/record UUIDs, hashes or internal enums.

## Browser acceptance remains with the owners

H03 proves login/session pause, managed MFA and exact recent-auth/browser binding.
H04 proves the real Admin-lite and Settings workflows, desired-versus-applied labels,
independent loading/failure, multiple-field validation/focus, retained edits, original
outcome reconciliation, bounded paging, asynchronous refresh, keyboard/themes/narrow
layouts and stable focus/scroll. H05 proves recovery-mode startup and own-point
selection/preview/strong confirmation/progress with denied cross-role/workspace/path/
key/replay attempts. Use the [H01.5 proof plans](../specifications/README.md), including
actual deployed-browser evidence. The preservation flags are requirements, not a
substitute for rendered browser tests. No UI work is moved to a separate backlog.

Run the focused fixture checks from `application/`:

```bash
.venv/bin/python -m pytest apps/server/app/platform/tests/test_hosted_ui_contracts.py -q --tb=short
```

Changing DTO/default/action/fixture semantics requires updating this contract and
its focused tests together. H01.6 does not complete H03/H04/H05 or any release gate.
