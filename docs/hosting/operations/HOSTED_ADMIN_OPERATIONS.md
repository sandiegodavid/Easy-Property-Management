# Durable private Admin operations

Slice 3 repository implementation, October 28, 2026. This runbook describes the
operation engine and private qualification boundary. It does not qualify a host,
raise the live operator ceiling, install a collector or expose an Admin management
UI. [Slice 4](../design/HOSTED_DEMO_ADMIN_DESIGN.md#ordered-implementation-slices)
owns that UI; Slice 5 installs provisioning adapters; Slice 7 executes real host
qualification. Continue using the existing private maintenance/recovery procedures.

## Storage and execution

The current private authority store also owns the operation journal, per-target
revision/fence, allocation reservations, ordered steps, safe append-only audit,
qualification plans, evidence references and immutable command receipts. It remains
outside business workspaces. Business schemas are unchanged. Use the current
schema in isolated installation/qualification; an older private schema is rejected,
not silently upgraded or reset.

Source-access admission consumes its action authorization and records its immutable
intent and operation in the same immediate transaction. Identical keys return the
original admission/result; changed source requests or allocation specifications
conflict. One unfinished ordinary operation can own a target. Reservations remain
owned after failure, cancellation and completion; no automatic deletion or release
of resources is implied.

A worker records a step's desired-spec digest and intent, ends its transaction,
then inspects the exact owning resource/receipt. Only verified absence permits
application. It inspects again before checkpointing verified success. Unknown or
contradictory observations pause for explicit reconciliation; a timeout does not
mean that no resource was created. Source adapters use the existing protected
instance inventory, fixed source-command transport and shared host maintenance
lock. They reconcile the original source receipt before retrying.

Workers have a 60-second claim and an independent private filesystem lock. A live
worker retains exclusive execution even after its claim time passes. After a
process dies, the claim must expire before a replacement reconciles its effect.
Every run performs at most one registered step. Source subprocesses retain their
bounded timeout/process-group termination. A lookup or sign-in never starts work.

Priority disable/revoke records a target fence before waiting for source effects;
it supersedes pending grant work. Workers check target and administrator authority
both before and after effects. A stale in-flight effect is contained through a
source-owned disable command. Failed containment stays visible as
`admin_containment_pending`; it is not reported as successful cancellation.
Session expiry/logout does not revoke admitted work. Administrator revocation does.

## Check, stop and resume an operation

The authenticated private HTTP service provides:

- `GET /admin-api/operations`: at most 50 recent safe operation summaries for the
  signed-in administrator, without workspace/provider fan-out.
- `GET /admin-api/operations/by-key/{id}` and
  `GET /admin-api/operations/{id}`: exact original operation, ordered checkpoints,
  safe status/error/result and revision. Source command keys and operation IDs are
  the same UUID. Reads require the Admin session and CSRF header.
- `POST /cancel`: `operation_id` and `expected_revision`; returns 202 after a
  durable safe-stop request. This does not delete resources or claim that access
  is already contained.
- `POST /resume`: the same selectors, plus a fresh one-use `credential` for
  grant-capable work. Returns 202 after admitting the reviewed continuation.
  Cancelled/superseded work cannot resume. No requested settings change on resume.

Use the launcher/session/CSRF procedure in
[Private Admin authority](HOSTED_ADMIN_AUTHORITY.md). Keep credentials out of URLs,
command-line arguments, logs and browser storage. Review the current operation
revision before every control action. An expired or failed claim is not permission
to create a new operation key.

Root-only worker/qualification commands run through the same peer-authenticated
broker. On the VM, using the installed release's Python:

```sh
sudo /opt/epm/releases/<installed-release>/venv/bin/python -I \
  /opt/epm/admin/admin_console.py operations
```

Provide one bounded JSON request on standard input (at most 16 KiB). Do not pass a
credential as an argument or put it in a persistent command transcript. The command
prints safe JSON, except grant actions intentionally print a short-lived credential
to the private terminal. Operator processes and the unprivileged Admin HTTP peer
cannot call these private actions.

| Request `action` | Other fields | Effect |
| --- | --- | --- |
| `operation-status` | `identifier` | Read durable status |
| `operation-run` | `identifier` | Reconcile/execute one admitted source step |
| `operation-stop` | `identifier`, `expected_revision` | Request safe stop at the reviewed revision, verify source-access denial and complete it |
| `resume-grant` | `identifier` | Issue a five-minute grant bound to the exact operation/request/revision; use it with authenticated `/resume` |

Provisioning and qualification-test steps have a closed step vocabulary and
transactional reservation/admission port. The private worker refuses those kinds
until their Slice 5 effect adapters are installed. There is no generic execute,
unit, path, shell, compensation or delete RPC.

## Private qualification commands

The initial qualified ceiling is an explicit installation input, at most two;
it is not inferred from running instances. Keep ordinary C admission blocked.
Only a fresh, capacity-fitting controlled test plan may bypass the ordinary count.
It never bypasses the memory/disk envelope, identity isolation or reservation
uniqueness. The full accepted procedure remains in
[Private path from two to three](../design/HOSTED_DEMO_ADMIN_DESIGN.md#private-path-from-a-ceiling-of-two-to-three).

| Request `action` | Other fields | Result/gate |
| --- | --- | --- |
| `capacity-initialize` | `ceiling` (0–2) | Initialize the current private capacity record using verified fresh host observations |
| `qualification-create` | `plan` | Persist a bounded plan/reservation; the plan UUID is its exact replay key |
| `qualification-status` | `identifier` | Read plan revision/state and registered evidence times |
| `qualification-command` | `command`, optional `credential` | Start/resume/abort/retire/promote with immutable command receipt |
| `qualification-evidence` | `identifier` | Load and register one protected verifier report by UUID; no caller-supplied result/assertion |
| `qualification-grant` | exact `command` | Issue an action-bound five-minute grant for explicit resume/promotion |

`plan` follows `QualificationPlan` in
[application/qualification.py](../../../application/apps/server/app/modules/hosted_admin/application/qualification.py).
It requires a UUID, installed release/profile and environment fingerprint, exactly
three distinct controlled tester emails/exact hostnames, three instances/six
browsers, a test window of at most one day, evidence-directory UUID,
maintenance/rollback references, workload digest and total memory/disk budgets.
It cannot contain an executable, provider credential or arbitrary file path.
Retained normal identities/hosts and live plan assignments cannot be reassigned.

`command` follows `QualificationCommand` in that file: UUID `operation_id`,
`qualification_id`, `action`, `expected_revision`, `expected_capacity_revision`,
nonblank reason and `confirmed: true`. Review status before constructing it.
An identical completed command returns its original receipt without another grant;
a changed command under that key conflicts. Start/resume checks the current test
window/environment/capacity. Resume requires fresh authorization. Abort preserves
failed evidence and reservations; it cannot reactivate anything.

Retire requires independently verified test retirement and A/B restoration.
Promotion additionally requires passed load, isolation, recovery, revocation,
mount-failure, reboot and rollout evidence, all current for the exact environment;
no conflicting live plan; restored ordinary services on the tested profile;
current physical headroom; and a fresh grant bound to the exact promotion command.
The ceiling changes to three atomically with its audit and immutable receipt.
Failed evidence stays failed; use a new reviewed plan for another qualification.
No command provisions C, invites testers, restarts A/B or changes VM size itself.

## Trusted measurement/evidence input

The broker reads only the fixed root-private directory
`/var/lib/epm-admin/qualification-reports`. Installation must provision an approved
private collector and protect its signing key. There is deliberately no Admin
HTTP/CLI command to sign an administrator's declaration or manufacture evidence.
Without approved collector output, capacity/qualification commands fail closed.
Executing and registering real Linux/Cloudflare acceptance is Slice 7 work.

The collector publishes:

- `verifier.key`: at least 32 private random bytes, excluded from control recovery.
- `verifier.json`: the installed approved collector's `verifier_digest`.
- `capacity.json`: a signed `CapacitySnapshot`, tied to the canonical digest of
  the current registered inventory. Observations must be less than five minutes
  old and inventory-clear. Capacity includes retained commitments and recovery
  staging, not just free workspace bytes.
- `<evidence-uuid>.json`: signed `QualificationEvidence` including exact plan,
  environment, observation/expiry, outcome and artifact digest.
- `<evidence-uuid>.evidence`: the matching protected measurement artifact, at most
  8 MiB. Registration and promotion verify its exact SHA-256.

Each JSON envelope has exactly `payload`, `verifier_digest`, `inventory_digest`
and `signature`. The signature is hex HMAC-SHA256 using `verifier.key` over the
canonical sorted compact JSON of the other three fields. Report JSON is bounded
to 64 KiB. Files must be private regular files, with protected real-directory
ancestors. Symlinks, nonregular files, unpinned verifiers, mismatched signatures,
changed artifacts and stale evidence fail closed. Listing an object or typing
“passed” is not an accepted measurement.

The approved collector is responsible for measuring effective host/release/profile
identity and independent workload/provider/recovery outcomes. These repository
protocol tests do not assert that such a collector has been qualified or installed
on the live host. Root can intentionally bypass host policy; the system does not
claim to defend against a malicious root administrator.

## Retained control data and recovery

Opening the current store verifies exact schema/immutability triggers, canonical
operation intents/hashes, ordered step identities, checkpoint/result consistency,
source-admission receipt consistency, reservation specifications and initial audit
evidence. Missing/corrupt control data is not treated as an empty inventory.

`control_recovery.snapshot_control` projects only durable operation/admission,
reservation, qualification/capacity and safe audit records for the separate private
encrypted host-control artifact. It exports no grants, sessions, authorization
records, token hashes or verifier key. This library projection does not create a
plaintext output file or a new business/archive format. The existing private
archive workflow must encrypt it; end-to-end host artifact tooling remains part
of lifecycle/recovery delivery, not an additional business backup here.

`restore_control` accepts the projection only into a fresh empty private store for
the same administrator. It validates before commit, disables identity authority,
clears claims and pauses unfinished operations, aborts unfinished qualification
plans, and resets ordinary capacity to zero. Fresh identity restoration alone
cannot run old work: explicit revision review/authorization and source receipt/
resource reconciliation remain necessary. Restore never starts a worker, enables
business access, revives a session or silently promotes capacity.

## Focused validation matrix

| Area | Focused proof |
| --- | --- |
| Happy paths | Source receipt completes one verified step; multi-step adapter checkpoints in order; explicit test plan starts without raising the ordinary ceiling; evidence-backed promotion raises it once |
| Invalid combinations | Changed source/allocation intent, duplicate reservation, wrong target/operation revision, unknown adapter, missing qualification, over-budget capacity, unknown private RPC and unsafe checkpoint payload are rejected |
| Idempotency/retry | Lost control commit reconciles the exact original effect; changed key payload conflicts; identical plan/promotion returns its original receipt; live worker locks prevent duplicate execution after lease expiry |
| Concurrency/rollback | Provider work holds no SQLite write transaction; disable/cancel/revoke fences an in-flight grant and invokes containment; reservation/admission and promotion/audit failures roll back together |
| Persistence/schema | Current schema/triggers and canonical intents; missing ordered steps rejected; immutable operation/step result/evidence/receipt/audit; reservations retained after cancellation |
| Recovery | Credential-free projection round trip; imported unfinished work remains paused and administrator disabled; no old sessions, automatic jobs or capacity grants restored |
| Authority | Root-only qualification RPC denies operator and HTTP peers; session/CSRF/revision checks protect status/control routes; fresh action authorization is required after identity revocation |
| Evidence/capacity | Unknown/stale inventory, insufficient memory/disk, duplicate tester identities, failed/expired/tampered/missing evidence, wrong environment, missing restoration and unqualified ordinary C all fail closed |
| Query bound | Recent operations use one limited control-store projection; exact operation lookup loads only that operation/its fixed steps; neither read fans out to providers/workspaces |
| Browser boundary | Existing isolated private sign-in keyboard/reload/logout, credential privacy, expiration/revocation and transport-denial tests remain the focused browser regression; management/progress UI is Slice 4 |

Run only the focused Admin, affected private-tool and source-command suites; use
`npm run test:admin` for the existing private sign-in browser boundary. No live
qualification, IAP, Cloudflare, host resources or business data is changed by these
focused fixtures.

Recorded October 28, 2026: **192 focused Python tests passed** across Hosted Admin,
the affected private inventory/maintenance/launcher tools and owning access source
commands; **3 private Admin Playwright tests passed**. Ruff check and format check
passed for the changed Python boundary, and `git diff --check` passed. The full
application suites were not run. No live deployment or qualification was performed.
