# Backup, recovery and retirement

[Hosted MVP design index](../HOSTED_MVP_DESIGN.md) · [Schema catalog](../../../DATABASE_SCHEMA.md)

Part of the accepted HOSTED-001 design. Requirements here do not establish implementation, deployment or qualification; Pilot 0 exceptions are in the [delivery plan](delivery-plan.md).

In this guide: [Backup, recovery and retirement](#backup-recovery-and-retirement) · [Internal workspace backup and recovery](#internal-workspace-backup-and-recovery) · [Authenticated recovery mode and failure handling](#authenticated-recovery-mode-and-failure-handling)

## Backup, recovery and retirement

<a id="8-backup-recovery-and-retirement"></a>

Use unattended, platform-managed encryption keys, scoped identities and separately
protected key custody. No operator-entered passphrase is required for scheduled backup
or automated recovery. This is not customer-managed-key or zero-knowledge encryption.
Choose a proven incremental/deduplicated encrypted backup implementation only after a
component proof; encrypting whole independent archives before deduplication can defeat
the expected savings. Include GCP upload traffic and retained bytes in the cost model.

### Internal workspace backup and recovery

The operator service owns routine workspace backup and self-service restore. An internal
background runner performs scheduled consistent capture, encryption/upload, verification
and retention without holding the SQLite writer during slow transfer or blocking normal
UI reads. It is not a second uncoordinated business writer. There is no always-running
outside workspace-backup/recovery service or mandatory Admin dispatch per operation.

A private per-operator recovery SQLite store, outside the business tree being restored,
keeps operation receipts, verified points, backup checkpoint and restore progress. Its
schema resources live under `application/database/recovery-migrations/`. The service
reports bounded protection summaries asynchronously to Admin; Admin downtime does not
stop backup or restore. Admin monitors/supports but does not own routine workspace jobs.
Authentication/access state remains separately protected and is not restored with data.

Track the protected business revision, retained-file generation and source incarnation,
not an in-memory dirty bit alone. If consistent comparison proves no changes, reuse
verified content instead of uploading another full copy; nightly verification/retention
may reference the same immutable content. Keep actual capture/verification times and
show “unchanged since verified point” separately from a fresh capture. Unknown or unreadable
state never counts as unchanged. A crash can leave committed changes unprotected; startup
must reconcile/catch up and surface degraded protection until destination verification.
A planned stop/upgrade completes backup of unprotected changes before stopping. Retain
seven nightly recovery points where produced, and never expire the only usable point
just because no new data required a replacement. Retained object references govern cleanup.

A recovery point is a completed, verified off-host database-and-file state with manifest,
workspace identity, schema/release compatibility, exact content references, digest and
key reference. Never copy an actively changing SQLite file as though it were a snapshot.
Use supported consistent capture and stable/versioned file references; hold writer gates
only as required for consistency, not throughout a slow upload. Publish the point last.

Free has a roughly 24-hour recovery-point objective while nightly protection is healthy.
Paid has a 15-minute objective for recent data. Schedule frequent enough to include
capture/upload/verification time; “cron every 15 minutes” alone cannot prove it. Retain
fine-grained paid points for 24 hours and thin older points to the daily history in the
catalog. Do not promise every historical 15-minute point throughout 30/90 days.

Monitor the latest **completed recoverable off-host point**, current-versus-protected
source/file generations and proof freshness, and test restores. Show genuinely verified
unchanged state separately; never refresh capture time or infer unchanged merely because
the container is stopped.
On protection failure keep the workspace usable, mark degraded protection and alert Admin;
never show a stale successful job as healthy. These are engineering objectives, not
unconditional guarantees or a contractual SLA. Alert/recovery procedures must expose
actual achieved protection and unresolved incidents.

Operators select and authorize recovery of their own workspace without Admin approval.
Settings → Data & Backup lists verified eligible recovery points (latest selected by
default), with capture time/property-independent display zone, protection status and
clear warning that newer changes will be rolled back. Show a restore preview with
workspace, selected point, current source revision and affected devices; require recent
authentication and explicit confirmation bound to that exact preview. Never restore
from a missing, corrupt, unverified, incompatible or different-workspace point.

Admit one idempotent restore operation; present progress and original-result lookup
across devices. The job validates capacity/keys/compatibility, fences and drains all
workspace writers/background dispatch, retains the current state, restores
to a separate private destination, validates complete data/files and ownership, then
switches bindings. Preserve a healthy pre-state through consistent capture; if the business DB is damaged,
keep the original tree intact as pre-restore/forensic state rather than requiring it to
be a valid backup. If that preservation or safe destination allocation fails, stop and
expose technical assistance; never overwrite the only source copy. Reject conflicting restore/upgrade jobs.
Failures retain the original safe binding or a fenced Needs attention state, never an
unvalidated destination. No automatic replay of user writes after restore.

Reconcile current identity/subscription and revoke affected app sessions before
reopening; an archive cannot restore old sessions, paid grants or enabled flags. The
operator signs in again to inspect and accept the restored workspace. Retain pre-restore
state until acceptance and the defined recovery cleanup; restoring that state requires
another explicit reviewed operation if newer writes exist. Future payment collection
stays fenced until provider/mandate reconciliation succeeds. Tenant/owner sessions
have no authority to restore a workspace. This self-service capability applies to Free
and paid plans alike; available recovery points follow their plan/retained history.

### Authenticated recovery mode and failure handling

Start a minimal recovery mode in the same operator service/image when business DB
validation/open fails. Bootstrap authentication, the private recovery store, recovery UI,
verified-backup list and original-operation status before business service composition;
never require a healthy business DB to render them. It uses current hosted identity/access
(or the existing local loopback/OS-owner boundary), not an authentication bypass. If auth
or recovery metadata cannot be validated, fail closed: no restore or decryption bypass
is offered. Support repairs the service/identity boundary before an operator can retry.

The internal engine drains requests/jobs, closes all business DB connections and owns an
exclusive workspace recovery gate during restore. A crash-safe locator/intent protocol
switches a validated separate business directory inside the existing protected persistent
mount; no Docker socket, generic host shell or mount privilege goes into the operator
container. Unavoidable host binding changes use the restricted registered-ID helper,
not an Admin approval/dispatch workflow for ordinary recovery. Restart inspects retained
operation/phase/locator evidence before any normal business opening, so interrupted
restore cannot silently initialize an empty workspace or start competing writers.

The current hosting scope excludes a dedicated offline operator-workspace restore or
decrypt/export command. Do not expose an offline-recovery endpoint, hidden Admin action,
CLI flag or environment switch that impersonates an operator or skips authorization.
If a container cannot start, support repairs/recreates its runtime from a qualified
image while retaining private data/control directories, then the operator reauthenticates
in recovery mode. If current identity/binding cannot be established, recovery stays
unavailable rather than accepting historical credentials from a backup.

#### Clean runtime rebuild, then authenticated restore

When the Operator container cannot start, use **Repair runtime**, not “reset operator
to empty.” Support/qualified host tooling performs this infrastructure operation; it
cannot choose or authorize a business recovery point. The operator subsequently restores
through the authenticated recovery screen:

1. Record a retry-safe runtime-repair operation bound to the existing operator/workspace,
   registered resource binding, qualified compatible release and expected source fence.
   Stop/fence the former runtime; never start another writer on an uncertain stop.
2. Retain the original business tree, access/recovery stores and protected key references.
   Replace only the failed runtime/container from the qualified image. Preserve the
   operator/workspace IDs, subscription and current disabled/enabled intent; do not run
   Add operator, synthetic seed, business initialization or account re-enrollment as a
   shortcut. Missing identity/control state first needs separately verified repair.
3. Start minimal recovery mode without opening/migrating/initializing the business DB.
   Revoke old app sessions and require current operator authentication and the same
   strong-step-up/exact-action confirmation as any restore. Runtime-repair authority
   never grants access to decrypted business records or authorizes rollback.
4. The operator selects a verified own-workspace backup. Allocate an empty **separate
   restore destination**, verify key/manifest/schema compatibility, then run the normal
   internal restore/validation/switchover. Do not overwrite or delete the original tree.
5. Reopen only after current authority and integrity checks pass; retain previous data
   until acceptance and controlled cleanup. No automatic return to business service just
   because a replacement container is healthy. Conflicts/failures remain inspectable
   under the original repair/restore operation identities.

Recovery requires a usable verified backup and available keys; runtime replacement
cannot manufacture missing data. An empty staging directory is not a new empty portfolio
and never changes workspace identity. H02/H05 must qualify this sequence, including
container replacement, missing auth metadata, incompatible backups and interruption;
H05 still needs its detailed design before implementation.

For host loss, privileged platform tooling may rebuild infrastructure and protected
control state, but cannot authorize a customer workspace rollback or provide a customer
backup plaintext-export feature. Mount only the verified workspace/control resources
into their registered operator runtime; any missing catalog reconstruction occurs there,
after fresh operator authentication, through verified own-workspace manifests. No
permanently running outside workspace recovery service is required.

#### Recovery security release gate

Require current own-workspace identity, recent strong step-up authentication qualified
in H03/H05 and single-use confirmation bound to the exact point, workspace, source epoch
and preview. A normal logged-in cookie or Admin session alone is insufficient. Reject
cross-workspace points, expired/replayed confirmations, arbitrary filesystem/object/key
references and untrusted redirect/download destinations. The service chooses destination
roots and scoped key/object references; browser/API callers never supply them. Recovery
produces only the registered workspace, not downloadable plaintext archives or attacker-
selected storage. Use least-privilege own-prefix object access and protected key custody;
no platform-wide decryption/bucket credentials in any portal/container.

Audit every authorization/attempt/outcome without secrets or business contents. Test
stolen-session-only attempts, forged Admin/user roles, cross-workspace object/key IDs,
replay, path/symlink escape, development adapter enablement and tampered manifests. H05
must pass an explicit security review and these negative tests before enabling restore;
otherwise show it unavailable. Later offline customer-recovery capability requires a
new explicit design/security decision, not a default H05 fallback.

These controls reduce exposure; do not promise zero probability of attack or protection
from a fully compromised host/platform administrator. Platform-managed keys retain a
privileged trust boundary, as already disclosed; removing a command does not create
zero-knowledge encryption. This limitation must remain clear in the security review.

#### Separate Admin backup and recovery store

Admin backup/recovery uses a separate private SQLite database/schema, owned by the
Admin service and located outside the main Admin DB and its restore destinations.
`application/database/admin-recovery-migrations/` exclusively defines its versioned
schema; no runtime DDL. Its control_recovery_points, control_restore_operations,
control_recovery_operations, checkpoint/meta and audit tables remain available when
main Admin state is corrupt or being replaced. See the [schema master](../../../database/admin-recovery.md#admin-recovery-database--h05).

Normal Admin backup and authenticated recovery mode can run in the same Admin service;
no additional service/VM is required. Bootstrap this store and the protected current
recovery-authority binding before opening main Admin data. Strong Admin MFA/step-up and
explicit point/target confirmation cannot depend on old principal/session rows from
that damaged DB or its archive. H03/H05 must qualify current identity/revocation and
protected bootstrap policy; otherwise Admin recovery is unavailable. Operator identities
never grant platform recovery authority.

The recovery DB owns operation identities/checkpoints/audit, with only local FKs; main
Admin, inventory, principal and release IDs are logical references with owning validation.
Do not require a main Admin operations/admin_audit transaction to admit or finish recovery.
Restore main Admin into a separate destination, validate schema/data/source bindings,
advance control fences, revoke historical sessions and reconcile providers/pending work
before reopening. Keep prior main Admin data and this recovery DB until acceptance;
never replace the recovery DB with the main Admin archive or replay old jobs/grants.

If the Admin service cannot start, existing restricted platform recovery tooling uses
the same protected store/engine with exclusive ownership and fresh recovery authority;
this is not an offline customer-workspace restore/decrypt command. Whole-host loss still
requires off-host manifests and independently protected bootstrap/key custody: initialize
an explicit fresh recovery incarnation and reconstruct verified catalog evidence without
automatically importing runnable operations. A separate local file alone is not host-loss
protection. H05 rehearses both main-DB-only loss and loss of the recovery DB/entire host.

The Admin registry, mappings, admitted versions/configuration, subscription references,
infrastructure operation history and the separate Admin recovery catalog need
encrypted off-host protection/reconstruction evidence. Workspace recovery metadata is protected/reconstructible through
its own manifests, not dependent on an Admin catalog of every workspace point.
Keep keys/credentials and reproducible infrastructure recovery available outside the
failed VM. A business archive alone cannot rebuild routing/ownership. Reconstruct and
reconcile host/provider/source state before reopening access; never replay queued grants
or unknown jobs automatically from an old control snapshot.

Target recovery within four hours as a measured engineering objective, not a 24/7
contractual promise. Externally alert on host loss and automate understood repairs.
Host-loss recovery must remain executable without its hosted Admin portal. Avoid
unattended cross-host takeover until fencing and restore correctness are proven;
never start a second writer merely because a health probe timed out.

Distinguish **Disable access**, **Cancel subscription** and **Retire workspace**.
Retirement needs explicit workspace confirmation, reason, export opportunity and scheduled
deletion date, with an initial seven-day recovery window. Explain primary versus backup
expiry and retained operational audit. Do not immediately recycle ownership or slugs.
An inactive Free account is not automatically deleted; Admin reviews retirement.
Retained disabled data still consumes monitored capacity.

