# Hosted Admin lifecycle and recovery

Slice 6 repository runbook, October 30, 2026. Repository validation is delivered;
this is not a live installation or acceptance record. Use the current
reviewed wheel and private authority schema. Install `admin_lifecycle.py` beside
`admin_console.py`, `admin_observations.py`, `host_admin.py` and `host_inventory.py`
under the protected `/opt/epm/admin` directory. The release bundle includes these
tools. Never install the test browser server on a real host.

## Complete onboarding

1. Open the assigned operator in the private console after exact verified identity
   approval. Approval alone leaves business access blocked.
2. Under **Verify onboarding recovery**, review instance/workspace, binding
   revision, approved subject, configuration digest and qualified release. Retain
   the same handoff through reloads. Run the exact command shown, for example:

   ```bash
   sudo /opt/epm/admin/venv/bin/python -I /opt/epm/admin/admin_console.py \
     verify-onboarding --handoff HANDOFF_UUID
   ```

3. Enter the encryption passphrase only at its private terminal prompt. The helper
   requires disabled access. It stops only the target writer, creates the existing
   encrypted archive as its service UID, publishes to the existing recovery store,
   independently reads/decrypts/validates the remote bytes and restores in isolated
   temporary storage. It separately encrypts, publishes, reads back and compares
   the approved-binding reference. Private acceptance verifies the registered
   release/configuration, protected ingress and provider policy. Failure produces
   a signed failure report; no browser assertion can mark a step verified.
4. Select **Check verification**. A changed binding needs a new handoff and fresh
   evidence. Failed, unknown, stale or overdue evidence cannot complete onboarding.
5. Select **Complete onboarding and enable access**, enter a reason and review the
   exact command. Obtain its one-use action credential through the existing
   `action-grant` private command using that exact JSON on stdin. Authorize, then
   explicitly confirm. The source atomically checks authority/revisions/window/
   binding/proof and records access, audit and original receipt. It issues no
   operator session.
6. If a response is lost, check the original operation rather than create another
   key. After confirmed completion, copy ready-to-use instructions and send them
   manually. Copying is not delivery. Verify a separate fresh operator sign-in and
   smoke check; contain/remediate a failure rather than alter acceptance history.

## Recovery attention

The private worker evaluates the latest handoff per instance every minute,
independently of browser visits. Read-back age warns at 20 hours and becomes
overdue at 24 hours. Acknowledgment records responsibility, not verification.
Unknown source state resets an earlier acknowledgment while retaining verified
archive history. Neither age nor acknowledgment changes business access.
Changing the pinned verifier, or losing/changing its protected report, makes the
retained evidence stale. Run a fresh private verification before activation;
historical reports and already-committed receipts remain available.

Review the snapshot marker, point references and individual completed-at times.
Later business writes can be outside that recovery point. The helper does not
automatically execute daily backups or hold an unattended passphrase. Use the
[manual recovery procedure](HOSTED_DEMO_OPERATIONS.md#daily-manual-recovery-points).
Refreshing the onboarding registry requires its private verification command and
disabled access; schedule that interruption explicitly, then verify recovery and
explicitly enable again. Never treat an archive filename or object listing as a
successful remote read-back or restore.

## Disable, revoke and re-enable

Disable/revoke needs session, CSRF, reason and explicit confirmation. Target fencing
precedes source effects; stale grants cannot undo it. Revoke invalidates existing
sessions while retaining the assignment. Disable blocks new business sessions too.
Retain all data/recovery artifacts. The source receipt confirms app denial;
**Disable stays Waiting** until independent provider denial verification. The
read-only adapter does not change Cloudflare. In the private Dashboard, keep the
exact-host Access application and audience, remove its allowance and configure a
single **Block / Include Everyone** policy without exclusions or requirements.
Do not delete the application, leave bypass/service-auth policies or remove the
origin's protection. Revoke provider sessions privately as required by the
existing operations procedure. The verifier proves the current deny-all policy
and observed public denial, not a historical provider-session deletion event.

Run the root-only helper for the original operation:

```bash
sudo /opt/epm/admin/venv/bin/python -I /opt/epm/admin/admin_console.py \
  verify-edge-denial --operation ORIGINAL_OPERATION_UUID
```

It checks the existing source receipt, inactive app, exact allocation/configuration,
Access application/audience, deny-all policy and public HTTP 403 with Cloudflare
response identification. It stores signed private evidence and a safe audit event;
the browser cannot assert success. Resume the same operation using the authenticated
`POST /resume` procedure in [the engine runbook](HOSTED_ADMIN_OPERATIONS.md#check-stop-and-resume-an-operation),
with its current operation revision (Disable needs no fresh action credential).
Run/check the original operation again. Evidence is valid for ten minutes and
invalidates on changed source revision/configuration; re-run verification if needed.
The original app mutation is not repeated. Provider failure leaves Disable pending.

The required API vocabulary is documented by Cloudflare's
[application policies API](https://developers.cloudflare.com/api/resources/zero_trust/subresources/access/subresources/applications/subresources/policies/methods/list/)
and [Access policies](https://developers.cloudflare.com/cloudflare-one/access-controls/policies/).

If source metadata or its access store cannot be read/written, urgent commands
stop only the exact registered service. **Containment pending** is deliberately
not a successful source receipt. Keep the service stopped, repair through private
maintenance, reconcile the original operation and independently confirm app and
edge denial. Do not reset the access/control databases or recreate the assignment.
If the console cannot read source status, use the root maintenance procedure;
do not guess a revision or claim that the UI completed a disable.

Enable requires explicit fresh action authorization, a healthy qualified runtime,
an unexpired window, current approved-binding recovery proof and onboarding
completion for the current binding. For a binding without completion, use
**Complete onboarding and enable access** instead. A disabled
assignment is never automatically restored. The operator needs fresh sign-in.
Before re-enabling, privately restore the exact-email Cloudflare allowance and
independently verify it through fresh recovery/acceptance. Never remove the app's
protection to make sign-in work.

## Renew a demo window

Select **Extend demo**, choose an explicit start and expiry (at most fourteen
days), review any overlap/gap and confirm with the exact action-bound credential.
The source first fences sessions/access and records an immutable receipt. The
private coordinator stops the target, atomically publishes its new configuration,
restarts the same workspace and independently observes the runtime before updating
inventory. Other instances are not restarted. Failures stay fenced; check/resume
the original operation to reconcile partial publication. Do not edit its dates
under the same key. The new binding requires fresh recovery verification and
explicit onboarding completion; renewal alone never grants access. Setup invitations
use the effective email and renewed start/expiry; the original setup remains history.

## Assisted sign-in email replacement

1. Explicitly disable first and verify source denial. Preserve the assignment,
   configuration and recovery points. Stage the exact replacement Cloudflare
   policy privately; no wildcard/group/bypass allowance. The coordinator verifies
   replacement email, application audience and protected ingress independently.
2. Review current source revision, binding revision and fence in the console.
   Construct the closed `CommandRequest` JSON below with real reviewed values:

   ```json
   {
     "operation_id": "00000000-0000-4000-8000-000000000001",
     "instance": "c",
     "action": "replace_email",
     "expected_revision": 2,
     "expected_binding_revision": 1,
     "fence": 1,
     "reason": "Reviewed replacement recipient",
     "confirmed": true,
     "replacement_email": "replacement@example.test"
   }
   ```

3. Run `sudo /opt/epm/admin/venv/bin/python -I
   /opt/epm/admin/admin_console.py action-grant`, supplying that exact JSON on stdin.
   Keep its credential only in the private terminal. Then run the same launcher
   with `operations`, supplying a bounded JSON request on stdin:

   ```json
   {"action":"access-admit","source_command":{},"credential":"ONE_USE_CREDENTIAL"}
   ```

   Replace `{}` with the entire reviewed command. Do not put the real credential
   in arguments, URLs, shared files, logs or saved shell history. Identical retries
   return original admission; changed intent conflicts.
4. Using `operations` again, supply
   `{"action":"operation-run","identifier":"ORIGINAL_OPERATION_UUID"}`.
   Check with `operation-status` and the same `identifier`. For paused work use
   the [reviewed resume procedure](HOSTED_ADMIN_OPERATIONS.md#check-stop-and-resume-an-operation),
   not a new key. A provider mismatch fails before source mutation. Interrupted
   publication reconciles the original source receipt before continuing.
5. Replacement clears the old subject/pending enrollments, revokes old sessions
   and leaves access inactive. Receive a new verified enrollment, approve that
   exact identity, create fresh binding recovery and explicitly complete onboarding.
   A typed replacement email never grants access.

## Focused validation matrix

| Area | Repository proof / qualification boundary |
| --- | --- |
| Happy paths | Current-binding signed recovery, independent remote bytes and isolated restore; explicit completion; renewal and replacement simulated target-only cutovers |
| Invalid combinations | Forged/foreign reports, missing checks, old binding/generation, failed/expired/superseded-verifier evidence, wrong provider policy and malformed browser assertions rejected; ordinary Enable cannot bypass initial or renewed-binding completion |
| Retry | Original source receipt survives control failure/proof expiry/verifier changes; interrupted config publication resumes without a second mutation; same-clock failed report wins |
| Transaction/containment | Source audit/receipt/access atomic; disable wins over stale completion; broken config/store stops exact target without fabricated success; cleanup preserves original failure |
| Persistence/recovery | Current schema validates immutable reports/completion; control recovery excludes credentials and restores disabled authority; encrypted binding reference stays separate from business archive |
| Bounds | One current handoff/source read per instance, at most 1,000 instances per worker observation; control projections do not read business records |
| UI | Persistent checklist, explicit authorization/confirmation, focused acknowledgment, original operation lookup and withheld ready instructions until completion; Complete onboarding before first activation, Enable for a completed binding; invitations use effective renewal/replacement email and window |
| Manual edge denial | Disable waits after its source commit; only the private read-only provider verifier releases the gate. Missing/bypass/allow/ambiguous applications fail; retry preserves one app mutation; stale/changed reports fail closed |
| Live gates | Real Linux ownership/mounts/systemd, provider mutation/denial, workload, reboot and third-operator rollout remain separate installation/Slice 7 qualification |
