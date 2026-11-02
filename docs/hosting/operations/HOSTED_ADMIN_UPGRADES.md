# Existing-operator release upgrades

Repository-delivered workflow for HOSTED-DEMO-ADMIN Slice 7. This runbook does not
establish live installation or qualification. Installing release artifacts, changing host
profiles and promoting the operator ceiling remain private operations. Upgrade
one registered synthetic operator at a time; never use this for production data.

The Admin portal supports either one operator or a bounded bulk selection.
Bulk upgrades remain serial and use the same child operations and source receipts;
no browser control installs releases or promotes capacity.

## Private installation prerequisites

Install the current Admin wheel and protected `admin_console.py` plus its existing
inventory/lifecycle tools. Both source and target releases must support the current
access schema, operation-owned maintenance protocol and fixed `upgrade_source`
compatibility probe. Unsupported formats block readiness; this greenfield project
provides no compatibility migration. Do not replace a live access store to make
readiness pass.

Use the normal [authority installation](HOSTED_ADMIN_AUTHORITY.md) and
[lifecycle/recovery configuration](HOSTED_ADMIN_LIFECYCLE.md). Keep the root-owned
private directory `/var/lib/epm-admin/upgrades` outside all operator volumes.

The private independent release/host qualification collector must publish signed
`ReleaseQualification` reports through the existing protected verifier registry.
Each report binds the installed manifest, session-compatibility evidence digest,
host environment, profile, qualified operator count and observation/expiry. A
browser assertion or editing a catalog does not qualify a release. Applicable live
qualification is required for the current count and target profile; Slice 9 alone
can promote the operator ceiling.

A root-owned, mode-0600 `upgrades/catalog.json` contains at most 50 unique report
IDs, for example `{"reports":["QUALIFICATION_REPORT_UUID"]}`. IDs resolve through
`/var/lib/epm-admin/qualification-reports`; the verifier signature and current tool
pin are rechecked. Choices show specific blockers for stale qualification, changed
artifacts or a mismatched host/profile. Refresh the signed capacity/inventory
observation privately when required, including after inventory reconciliation.

Provision `/var/lib/epm-admin/upgrades/passphrase-INSTANCE` as a root-owned private
file with the recovery passphrase (12–1,024 characters, optional trailing newline).
Do not put it in browser fields, argv, environment variables or logs. Configure
`/etc/epm/recovery-INSTANCE.json`, encrypted off-host publication/read-back and
owner-private staging outside the bounded business volume. Missing configuration,
credentials or staging space leaves the operation blocked for private remediation.

## Operator workflow

1. Open the operator's **Runtime and capacity → Upgrade release**. A pending
   operation links directly to **View upgrade progress**. Pick an eligible
   installed target and select **Check readiness**. The durable readiness job runs
   asynchronously while the operator continues working.
2. Review current → target release and compatibility. Arrange a maintenance
   window and ask the operator to save unfinished work. Select **Keep valid
   sessions**, or **Require sign-in again**. Preservation is unavailable when
   compatibility/security qualification requires revocation.
3. Confirm the interruption and review the exact decision. Obtain its one-use
   action credential privately, paste it into **Action credential**, then select
   **Start upgrade**. The browser never executes the shell wizard.
4. Watch durable checkpoints: revalidation/reservation, pause, drain/stop, encrypted
   recovery, stopped-target validation, release selection, restart, verification,
   explicit acceptance. Closing the page or losing IAP does not cancel the job.
   A lost response retains the original command key in the URL; check that
   submission or open Operations before retrying. Never submit a new upgrade to
   guess whether the first one committed.
5. The target runs with ordinary access still paused. Review independent archive
   read-back/decryption, isolated restore, encrypted approved-binding read-back,
   current runtime/isolation, exact Access audience/email policy and protected
   tunnel routing. Choose **Accept upgrade and restore access** only if the prior
   authorization remains valid; otherwise choose **Accept upgrade and keep access
   disabled**. Acceptance never revives expired/revoked sessions or overrides an
   intervening Disable, identity change or sign-out.
6. After acceptance, open tabs say a new version is ready and require explicit
   reload before business mutations. Compatible saved standalone forms resume by
   their original recovery IDs. Uncertain submissions retain original identifiers
   and must reconcile normally; nothing is automatically resubmitted. Operator
   sign-in verification is separate from release acceptance.

## Upgrade selected operators

1. Open **Operators**. Select rows, or **Select this page**, across directory pages.
   Selection remains explicit when filters change; no action selects hidden or
   future matches. The limit is 50 distinct registered operators per batch. Use
   **Clear selection** to start over. Open **Upgrade selected operators**.
2. Review names and selection-time release/access information. Move operators
   earlier/later or remove them, choose one installed target and select **Check
   batch readiness**. Each member is checked independently without interrupting
   access. Unsupported formats, changed inventory, conflicting maintenance,
   missing recovery configuration and stale qualification block that member.
   Resolve its named remedy or skip an unstarted member, then check again. If its
   selected inventory revision changed, create a new reviewed selection for it;
   existing batch membership is never rewritten silently.
3. Once every included member is ready, review the complete ordered list,
   readiness-time access states and each session choice. Preservation defaults
   only where qualified. Enter an agreed maintenance window in your browser's
   local time, a reason and confirmation. The command retains exact UTC seconds.
   Select **Review batch**, obtain its exact **batch-grant** privately and select
   **Start batch**. This grant covers that forward plan, not future acceptance,
   rollback or changes to membership. A later window needs a new reviewed grant.
4. The **Batch upgrade progress** page shows ten operators per page, aggregate
   accepted/restored/disabled/skipped/recovery counts, observation times and the
   original child links. An operator starts only inside the admitted window.
   The source pause checks the window again after slow readiness. Unstarted
   operators continue working normally. Open **View upgrade batches** from the
   directory to find the durable history after losing the URL or local selection.
5. When the current child awaits acceptance, open **Review and accept this
   operator**. Its existing checkpoint/recovery view offers **Accept and continue**
   or **Accept with access disabled and continue**, with a separate fresh child
   action credential. Return using **Return to batch progress**. The next child
   starts only after the original source result is reconciled. Rollback remains
   an independently authorized operation on that operator's current bytes, with
   its own acceptance; the queue then waits for explicit review.
6. **Pause after this operator** and **Cancel remaining operators** durably stop
   new admissions, including a race with a slow readiness check. They do not abort
   the current backup or remove its gate. Cancellation marks only unstarted
   members skipped. To resume a paused/blocked queue, finish the current child's
   recovery, **Check readiness again**, review the remaining plan and new window,
   and authorize **Review and resume batch**. Root qualification/capacity reports
   must remain current, including after inventory reconciliation; a batch never
   signs or manufactures refreshed evidence to advance itself.
7. After a failure, **Skip [operator]** requires explicit review, reason and its
   own grant. For a started member the worker first durably fences it, obtains its
   exclusive worker claim, stops/verifies only its service and reconciles the exact
   private reservation against the observed release. Only then is the execution
   slot released and the member marked skipped. Cleanup failure or authority loss
   keeps the slot blocked. A freshly authorized retry reconciles that same child;
   it never replaces the original failure, gate, data or receipt. A canceled batch
   can still receive this cleanup retry without restarting its queue.

**Skip is not recovery or acceptance.** If the operator remains paused after a
skip, use the private recovery procedures to repair and verify it; do not clear
its gate based on a skip result. The retired child's automatic resume/acceptance
is fenced. Choose and accept a compatible rollback before skipping if you need
that normal UI recovery path. A window that expires after admission but before
source pause similarly requires explicit review/containment rather than a late
automatic interruption. A fresh batch can select an unstarted/skipped operator
only after any retained gate or private maintenance conflict is reconciled.

A batch is **Completed** only when all selected members reached their intended
accepted target. Otherwise the summary distinguishes skipped and failed/recovery
outcomes. There is no atomic rollback of previously accepted operators. Browser
loss, logout and reconnect do not resubmit or cancel a committed plan. Identity
revocation and control restore fence the coordinator and children; restoring the
Admin identity alone never resumes the queue.

## Private command path

The Admin UI shows the exact reviewed `UpgradeCommand`. To authorize it, send this
JSON on stdin to the installed private launcher (`sudo .../admin_console.py
operations`):

```json
{"action":"upgrade-grant","upgrade":{"id":"COMMAND_UUID","instance":"INSTANCE","action":"start","expected_revision":2,"operation":"READINESS_OPERATION_UUID","session_handling":"preserve","confirmed":true,"reason":"Agreed maintenance window"}}
```

Supply the returned credential to the UI. Alternatively, private administration
uses `{"action":"upgrade-admit","upgrade":EXACT_COMMAND,"credential":"..."}`
through the same stdin-only launcher. This shares the same service and deployment
adapter as HTTP; it has no arbitrary command/path parameters. Readiness uses
`action: "check"`, a target `release` and the registered inventory revision;
`start` references its successful readiness operation. `accept` and `rollback`
reference the original upgrade and its current operation revision. Acceptance
also supplies `restore_access: true` or `false`. Every new decision needs its own
UUID, reviewed revision, reason, confirmation and exact action credential.

Use existing private `operation-status`, `operation-run` and `resume-grant` commands
with the original operation UUID. Resume is explicit and requires its reviewed
revision plus the resume credential. A lookup/GET never dispatches work.

### Private bulk fallback

The same stdin-only launcher accepts the exact reviewed `BatchCommand` under
`batch-grant` (issue a one-use credential) or `batch-admit` (supply the command and
its credential). Copy the complete request from **Obtain an action credential
privately**; it includes the immutable member order, expected batch revision,
per-member session choices, UTC window, reason and command UUID. Keep the original
UUID for a retry. Never pass the credential in argv or an environment variable.

Read and bounded worker examples, replacing `BATCH_UUID` with the retained ID:

```json
{"action":"batch-list","page":0}
```

```json
{"action":"batch-status","identifier":"BATCH_UUID"}
```

```json
{"action":"batch-run","identifier":"BATCH_UUID"}
```

History pages contain ten batches; advance `page` by ten. `batch-status` returns
at most 50 members and performs no host effects. `batch-run` performs a bounded
coordinator tick for that original batch, including pending containment; it does
not authorize resume or acceptance. Use the existing `operation-run` with a
child's original UUID for its deployment checkpoints when working privately.
Child acceptance/rollback still use their normal separately authorized contracts.
Status lookup and reopening the page never dispatch either operation.

## Failure and rollback

Before pause, cancellation releases the private maintenance reservation without
stopping the operator. After pause, cancellation is unavailable: use controlled
resume, rollback or private intervention. Emergency Disable/sign-out remains
available, including for another operator during long recovery work.

Rollback is a separate durable operation preserving the forward history and its
original gate owner. It stops only this service, proves the previous release can
read the current workspace, selects it, restarts still paused, verifies it and
awaits explicit acceptance. It never restores an older business archive. A data
restore requires a separate explicit private recovery operation and revocation.

If forward acceptance reconciled inventory but failed before removing the source
gate, rollback accepts that pinned target revision. Its acceptance records a new
expected-revision reconciliation back to the original release, preserving the
forward receipt. Interrupted reconciliation retries use the same rollback
reservation; concurrent disablement remains effective.

If restoring access was rejected after a concurrent authority change, review a
new **keep access disabled** acceptance decision. The earlier decision and source
receipt remain immutable. Retry of a committed acceptance returns that original
receipt, even after proof ages out. A control-store restore preserves evidence but
fences authority/jobs; it cannot automatically reopen access.

Administrator generation and target fences are rechecked after slow verification
and immediately before the source resume command. Control and source stores are
separate: no control transaction spans the source process call. If authority is
revoked after that source command commits, the worker stops only the affected
service and retains its original receipt for explicit recovery. Restoring the
Admin identity alone cannot resume work admitted under the revoked generation.

Root-owned markers retain exact maintenance/disable commands before source effects.
Inventory reservations coordinate with private deploy/backup/cleanup under brief
host locks; no host lock spans remote recovery publication or restore drills.
Reconciliation records the observed runtime and original allocation identities
before opening the gate. Both releases and the recovery chain remain protected
from cleanup, including after interrupted or completed upgrades. There is no
implicit retention/deletion policy for this chain.

## Focused verification matrix

| Area | Repository proof |
| --- | --- |
| Happy paths | Real access/inventory stores with isolated Linux effects: target upgrade, preserved sessions, keep-disabled acceptance and current-release recovery handoff |
| Invalid combinations | Wrong allocation/binding, stale/changed qualification, changed artifact, unsupported schema/probe result and exact action-credential checks fail closed |
| Retry/restart | Lost start response, original acceptance receipts, fresh keep-disabled decisions and restart after every effect before its checkpoint writes |
| Transactions | Immutable source maintenance/access receipt/audit; failed control checkpoint leaves original intent; independent rollback preserves forward history, including interrupted acceptance after inventory reconciliation and lost replies at both rollback reconciliation boundaries |
| Persistence/restore | Typed execution/plan/evidence/link validation; credential-free control snapshot and restored authority fencing; encrypted remote read-back and isolated business restore |
| Recovery failures | Truncated remote bytes and failed isolated restore retain failed proof; verifier pin/signature changes cannot provide current evidence; suspect content never becomes success |
| Coordination/isolation | Durable private-maintenance reservation, unrelated inventory unchanged, target-only service commands, cleanup protection for both releases, pre-pause cancel and concurrent Disable; Admin revocation at runtime/recovery/onboarding/source-intent boundaries leaves the gate closed; revocation after source commit contains the target and preserves its receipt |
| Bounded reads | Five SELECTs for an upgrade status projection with either 1 or 100 unrelated operations; at most three evidence rows; maximum 50 local installed-release reports; no business/provider reads in status polling |
| Bulk coordination | Explicit 1–50-member order, serial original children, required revocation and disabled-member acceptance; pause/cancel races, window checks, rollback of admission/link writes, fair scheduling and safe skip containment with unrelated inventory unchanged |
| Bulk retained history | Immutable decision events, admission-to-plan/session/window bindings and skip proofs; tampered membership, target, sessions, receipts, state, admission time and transitions rejected on restore |
| Bulk reads/UI | Three SELECTs for 1/10/50-member status reads without host calls; ten-batch history pages, bounded request/response frames, private fallback, member paging, stale-read input retention, explicit queue controls in both appearances |
| Browser | Eligible/blocked choices, failed-readiness remediation, default/required session handling, explicit confirmation, lost response lookup, reload without resubmission, fresh sign-in after upgrade, expiry/revocation during maintenance with preserved forms, narrow viewport, accessible native progress and explicit acceptance |

Validated November 1, 2026: the expanded focused Hosted Admin/source-command/
maintenance/compatibility/launcher run passed **319 tests, with 1 skipped** for
explicit root Linux loop-mount qualification. The final batch suite passed
**26 tests** after adding disabled-member and accepted-rollback coverage; these counts overlap.
The focused Admin bulk/single-upgrade/lifecycle browser run passed **6 tests**.
Ruff check/format, frontend lint, format:check, full frontend typecheck and
workspace-independent generated-contract checks passed. No full application
suite was run.

Review follow-up on November 1, 2026: **87 focused backend tests** (upgrade
deployment/service and host inventory) and **23 hosted-session browser tests**
passed. These are separate, overlapping focused selections, not a full-suite run.

These are isolated repository tests. The real Linux service/mount lifecycle,
private credential installation, cloud routing, recovery destination and target
release/profile must be qualified before a live upgrade is claimed safe.
