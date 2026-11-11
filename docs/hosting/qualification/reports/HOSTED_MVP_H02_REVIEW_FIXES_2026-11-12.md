# H02.1–H02.8 review fixes — November 12, 2026

Scope: the two findings in
[pending review comments](../../../../pending_code_review_comments/HOSTED_MVP_H02_1-H02_8_c31fa04e_REVIEW_COMMENTS.txt).
No general re-review, new hosted workflow, live host change or migration was performed.

## Durable start reconciliation

An authenticated, currently admitted stop that physically verifies containment now
atomically records its applied receipt and marks older pending/unknown starts for
the same binding/generation/scope as `superseded`. The terminal receipt retains the
original request/hash and unknown observation, adding the verified stop child ID,
containment evidence reference and timestamp. It does not claim the historical
start never ran, and cannot replay it. Only fresh admitted work at the current
revision/access fence may subsequently start or repair the runtime.

A failed or unknown stop clears nothing. Stops do not resolve unrelated unknown
creation, limit or ingress effects. A result-transaction failure rolls back the
stop receipt, binding update and supersession together; the pending stop retries
through inspection, not effect replay.

The current greenfield inventory baseline and typed receipt now admit `superseded`,
require containment metadata and make terminal superseded rows immutable. No
compatibility migration or adoption path was added. The owning
[inventory dictionary](../../../database/host-inventory.md#verified-containment-and-current-supervision)
records the current contract.

## Current supervision authority

The protected stop-only projection remains immutable and retains its first start
command for exact target identity/emergency containment. `HostAgent.supervise()`
resolves that identity through the owning inventory to an actual applied start at
the current access epoch and preceding binding revision. It does not manufacture
current authority by copying an epoch into historical intent. The inventory singleton
covers that lookup and physical verification; no database writer spans OS effects.

A successfully restarted container survives guardian polling after a newer held
fence. Current qualification, physical sandbox and external-deny verification remain
mandatory: missing/stale authority still stops the exact protected container and
retains attention. The standalone guardian's containment-only default is unchanged.

## Focused validation matrix

| Area | Evidence |
| --- | --- |
| Happy paths | Real SQLite inventory/HostAgent with NativeEffects, RuntimeAuthority, Gateway, StopRegistry and Supervisor; synthetic physical adapters. Unknown start → verified stop → fresh successful start at epochs 1 and 2. Known start → stop → newer held fence → restart → guardian keeps it running. |
| Invalid combinations | Unknown stop leaves start unknown. Superseded receipt without containment identity fails typed validation. Corrupted current external denial stops the runtime despite the old projection's valid identity. |
| Idempotency/retry | Old start returns the same terminal receipt without another start. Retained request/unknown observation and stop projection bytes stay unchanged. Stop result retry is inspect-only. |
| Transaction rollback | Injected failure after supersession writes rolls back stop/result/binding and original-start resolution together; retry completes coherently. |
| Persistence/schema | Actual latest-baseline DDL, required supersession metadata, terminal update prohibition and owning schema validation exercised. No schema compatibility path. |
| Backup/restore | Existing inventory snapshot/receipt regression included. No business backup format or restore implementation changed; no new native/H05 recovery proof claimed. |
| Query bounds | Current supervision selects only the matching command in SQL, not a hydrated history list; no per-row domain projection or new cross-store query. No new scale benchmark claimed. |

Result: **277 focused tests passed in 72.37 seconds**, including all six new
regressions. No failed tests remain in that focused run.

Focused files: `test_agent.py`, `test_native_receipts.py`, `test_runtime_effects.py`,
`test_supervisor.py`, `test_gateway.py`, and platform `test_hosted_schema.py`.
The two legacy attention fixtures now establish an initialized container and applied
start, rather than invoking supervision on a prepared resource with no runtime.

Ruff check and format check pass for all six changed Python files using
`application/pyproject.toml`, without suppressions or rule changes. No frontend
source/tooling changed and no full suite ran.

These source/schema changes require rebuilding and applicable requalification of
future candidates; earlier image/native reports retain their historical pins and
are not updated into a pass for these fixes. Existing held ingress and H03–H05
identity/access/recovery gates remain unchanged.
