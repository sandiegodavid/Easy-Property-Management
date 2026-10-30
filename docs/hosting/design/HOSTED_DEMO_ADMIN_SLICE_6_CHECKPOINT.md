# Slice 6 implementation checkpoint — 2026-10-29

**Latest status — October 31:** Slice 6 is marked repository delivered in the design
and lifecycle runbook. The implementation is saved in commit `0d75ce95` on
`Admin_UI_Workflow`; the working tree was clean when continuation resumed. The
historical in-progress and uncommitted-work notes below are superseded by this
status and the final October 30 validation record. No Slice 6 implementation work
remains in this checkpoint. Live installation and Slice 7 qualification remain
outside repository delivery; neither is claimed or started by this continuation.

Slice 6 is **in progress**, not accepted or deployed. Work is saved as uncommitted edits on `Admin_UI_Workflow`. Preserve all edits. No live host, provider, invitation or capacity changes were performed.

## Implemented so far

- Closed recovery binding/report/check contracts; immutable handoffs, registered reports and onboarding completions, plus acknowledged recovery attention in the greenfield authority schema and credential-free control snapshots.
- Protected signed-report registration through a root-only broker operation. Persistent HTTP checklist/check/acknowledge endpoints accept IDs and revisions, never asserted success or report paths.
- Source-owned complete-onboarding action, with atomic binding/window/revision/fence/proof checks and receipt/audit. Original receipts reconcile after proof expiry. Canonical deployment fingerprints sort capability sets across processes.
- Private approved-binding verifier: target-UID offline backup, encrypted off-host archive read-back, isolated restore, encrypted approved-binding publication/read-back, private acceptance checks, signed success/failure reports and broker registration. Private CLI: `sudo /opt/epm/admin/venv/bin/python -I /opt/epm/admin/admin_console.py verify-onboarding --handoff HANDOFF_UUID`.
- Renewal and assisted email-replacement source commands revoke sessions and leave access inactive. Fixed target-only cutover publishes validated config, restarts the existing workspace, records inventory revision/baseline, and reconciles partial publication without a second source mutation.
- Root-only `access-admit` private operation takes `source_command` and an exact action credential; ordinary `operation-run/status` executes/checks it. Email replacement requires prior disable and independent exact replacement-policy verification. Old subject is cleared; new enrollment/recovery/completion remain required.
- Broken-source fallback stops the exact registered service but reports containment pending rather than fabricating a source receipt.
- Recovery ages evaluated by the existing private worker (20-hour warning, 24-hour overdue), independently of console visits. No automatic activation or disable on backup age.
- Admin detail includes recovery checklist and access confirmation forms; setup links to it after approval; ready instructions require a retained completion and active source. Generated Admin contracts updated.

## Validation already run

- Expanded focused command: hosted_access/tests + hosted_admin/tests + scripts/tests/test_admin_launcher.py + scripts/tests/test_host_inventory.py, excluding test_broker_concurrency.py: **379 passed, 2 skipped** (Linux-only storage qualification).
- New private verifier tests exercise real encrypted archive validation/isolated restore and binding encryption with a fake remote store: success and acceptance failure both register reports; no source activation.
- New cutover test uses real source receipts and inventory with simulated Linux effects; config-publication interruption resumes without a second source mutation.
- `npm run test:admin`: **20 passed**. The first run logged fixture-only missing `.status` exceptions; a FixtureDispatch adapter was then added to admin_browser_server.py and needs a clean rerun.
- New lifecycle browser test passes (checklist reload, explicit credential/completion, original operation identity, ready instructions).
- Ruff check and format passed on all 30 changed Python files at the last check. Frontend lint and typecheck passed before final small edits; format check found a new test needing Prettier, subsequently formatted.
- A final targeted pytest + lint + format:check + typecheck command was started; collect its completion if the session is still available. Record any new results accurately.

## Remaining before claiming delivery

1. Finish final lint/type/format checks and rerun Admin browser suite after FixtureDispatch update; run broker concurrency focused regression outside sandbox (Unix socket bind is restricted inside sandbox).
2. Add focused private access-admission/assisted replacement orchestration and broken-access-store containment tests, including failure/resume and disable races. Root private admission was added after the 379-test run.
3. Check worker recovery observation bounds/latency and current-binding invalidation semantics, including stopped/corrupt source reads and restored authority generation. Review failure paths of the private helper; keep original failures and durable failure reports safe.
4. Complete operator/admin instructions and the focused validation matrix in a Slice 6 runbook. Document the exact JSON private assisted replacement/admit/run workflow, explicit cutover consequences, and source receipt reconciliation. Install admin_lifecycle.py beside admin_console.py in installation instructions.
5. Update design Slice 6 status only when these checks and end-to-end boundaries are complete. Do not alter Slice 7 or claim live qualification/deployment.

Keep only focused tests. No compatibility migration. Check account usage first on resume; save/stop at weekly remaining 2% or five-hour remaining 5%.

Stop threshold reached: five-hour used 95% (5% remaining); weekly used 92% (8% remaining). Final targeted pytest completed: **38 passed**. Frontend validation chain session `43257` was still running at stop; collect its result on resume rather than assuming it passed. All edits remain uncommitted.

## October 30 continuation

The earlier partial work was committed externally as `99c283ad`; this continuation started from a clean `Admin_UI_Workflow`. New continuation edits are uncommitted. No live host/provider or business data changes.

- Urgent disable/revoke receipt lookup and write failures now invoke the exact registered service containment fallback, preserving `admin_containment_pending` instead of fabricating a receipt. Wrong-allocation conflicts remain rejected without dispatch. Added broken-config, broken-receipt and failed-write tests.
- Recovery worker checks only the latest handoff per instance, reads each source once, resets acknowledgment on unavailable observations and audits the transition. Retains prior verified history when the source is unavailable. Same-clock report ordering uses registration row order so a later failed report cannot fall back to an older success.
- Reports now include opaque archive/binding references, pinned verifier digest and separate completion timestamps. Verified reports require every check after approval. Recovery age uses read-back completion. Private helper compares current binding before/after work, registers partial failure evidence and preserves the original failure if registration/restart cleanup also fails.
- Renewal/replacement orchestration tests now cover both actions and independent provider rejection before mutation. Interrupted cutovers resume their original source receipt and update inventory once.
- Checklist displays pinned binding and per-check outcomes; operator recovery rows expose policy state and acknowledgment. Admin release bundle now includes required `admin_lifecycle.py`; authority install instructions updated.

Validation this continuation:

- Initial final frontend lint, format and typecheck passed; repeated after continuation UI edits: all passed (203 source files). Generated contracts reproduced successfully after report contract changes.
- Clean full Admin browser rerun after FixtureDispatch: **20 passed**, no fixture ASGI exceptions. Later checklist changes have a focused console/lifecycle rerun in progress, session `20945`.
- New onboarding/cutover/runner focused tests: **27 passed** before the final report age/checklist adjustments.
- Broker concurrency alone: **3 passed**. Expanded focused backend run initially hit the sandbox Unix-socket restriction; rerun with escalation is in progress, session `58877` (collect result).
- Ruff check and format check passed on all seven continuation Python files. `bash -n application/scripts/epm-release-mac.sh` passed. Final diff check still required.

Remaining: collect final test results, fix failures if any, complete Slice 6 operations runbook (including exact private action-grant/access-admit/run JSON and manual edge revocation), focused verification matrix and cross-links/status. Inspect policy/evidence failure paths against the design before claiming completion; in particular distinguish app denial from provider edge revocation and do not imply the read-only provider adapter performs it. No live qualification; Slice 7 unchanged. Slice 6 remains **in progress**.

### October 30 stop — weekly remaining 2%

Stop threshold reached: weekly used 98%; five-hour used 33%. Work saved on the current branch as uncommitted edits. No running test sessions remain.

- Expanded focused backend rerun outside sandbox: **252 passed, 1 skipped** in 23.16 seconds. Includes all Hosted Admin tests (broker concurrency included), owning source-command tests and private launcher/inventory tests. Skip is the opt-in Linux volume qualification on macOS.
- Final console/lifecycle browser rerun outside sandbox: **12 passed** in 44.5 seconds after the checklist presentation changes. Full Admin suite earlier this continuation: **20 passed**. No fixture ASGI errors.
- Final frontend lint/format/typecheck passed (203 source files); generated contracts reproduced. Changed Python Ruff check/format check passed. Release shell syntax and final `git diff --check` passed.
- Added draft runbook `docs/hosting/operations/HOSTED_ADMIN_LIFECYCLE.md` with exact private admission/run shapes, recovery/renewal/rebind consequences and focused matrix. It explicitly remains in progress. Installation now names admin_lifecycle.py and release bundle includes it.

Next continuation: review runbook accuracy and add cross-links/status only after remaining integration checks. Verify the release-bundle inclusion with its focused packaging regression, review acknowledgment response freshness (acknowledge currently returns its pre-update view), ensure unknown/stale attention is surfaced consistently and check the manual edge-revocation boundary against the design. Finish error-path/policy checks before claiming Slice 6 delivered. Do not broaden to Slice 7 or deploy. Check usage limits first; preserve all saved edits.

## Final October 30 continuation — stop at weekly remaining 2%

- Fixed acknowledgment response freshness and rejected an acknowledgment if the
  attention state changed during its source check. Last successful individual
  archive/read-back/restore/binding timestamps survive later failed attempts;
  failed/latest policy state still blocks activation. Added age and race tests.
- Replaced the overview's hard-coded unverified recovery panel with current-page
  observations. Recovery needs attention includes enabled operators with failed,
  stale or unknown evidence. Polling preserves reviewed revisions and the original
  access operation instead of remounting the action form.
- User explicitly chose: **Disable remains pending until independently verified
  manual Cloudflare denial**. Added `edge_denial.py`, read-only deny-policy/public
  denial verification and root-only `verify-edge-denial --operation UUID` launcher.
  `SourceEffect` leaves Disable waiting after its app receipt; explicit resume
  completes it without repeating the source mutation. Every private verification
  creates a distinct signed artifact, linked by safe audit reference, bound to the
  exact operation/configuration/source revision and valid for ten minutes. Missing,
  changed, expired or unverifiable evidence fails closed. No browser assertion,
  provider write token or automatic Cloudflare mutation was introduced.
- Pending operation UI shows the fixed private command and explicit resume step.
  Updated lifecycle operations instructions, console/provisioning links and Slice 6
  repository delivery status. Added release-bundle regression for admin_lifecycle.py.

Validation:

- Expanded backend boundaries before the final edge gate: **314 passed, 1 skipped**.
- Admin/launcher/release regressions with the gate: **255 passed, 1 skipped**.
- After unique signed edge-artifact linkage: edge/onboarding **19 passed**; after
  final launcher extraction: edge/launcher **12 passed**. Skip is opt-in Linux volume
  qualification on macOS. No full application suite was run.
- Console/lifecycle browser regressions **13 passed**; new pending-disable browser
  regression **1 passed**. These are focused runs, not a new full Admin-suite total.
- Final frontend lint/format/typecheck passed (203 source files); generated
  contracts reproduced without a workspace. Final Ruff check passed, and all
  twelve changed/new Python files passed format check. Release shell syntax passed.
- All test sessions completed. Latest diff check passed before this checkpoint edit.

Stop limits: weekly used 98% (2% remaining); five-hour used 53% (47% remaining).
Work remains uncommitted, including new edge verifier/tests and lifecycle runbook.
No live hosts, provider policies, invitations, data or qualified ceiling changed.
Only installation/Slice 7 qualification remains outside repository delivery.
