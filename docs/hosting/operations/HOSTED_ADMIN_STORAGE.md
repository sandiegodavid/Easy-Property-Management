# Protected storage policies and reservations — Slice 8B

Repository implementation, November 2, 2026. This is private infrastructure for
[the storage slices](../design/HOSTED_DEMO_ADMIN_DESIGN.md#8b--define-policy-protected-inventory-and-commitments).
It does not record a deployment, qualify a production profile, or enable quota
changes from either portal. Slice 8C owns source growth accounting; 8D onward owns
safe storage changes and their UI. Existing loop-image allocations retain their
current behavior. The source refuses project-quota writes until accounting is
implemented and qualified. Do not change a live configuration to bypass that gate.

## Protected inputs

Use the existing root broker, [authority installation](HOSTED_ADMIN_AUTHORITY.md)
and [private operations transport](HOSTED_ADMIN_OPERATIONS.md). Configuration,
verification reports and host inventory must remain root-controlled. Neither
portal may supply project IDs, UIDs, filesystem paths or qualification claims.

The owning contracts are `hosted_access/application/storage_policy.py` and
`hosted_admin/application/storage.py`. They define the exact current schema:

- Tier IDs `50mb`, `200mb`, `1gb` mean **50,000,000**, **200,000,000** and
  **1,000,000,000** logical bytes. They are distinct from kernel allocation limits.
- A `TierProfile` pins release, sandbox, measurement and qualification digests,
  workspace/scratch/control hard byte and inode ceilings, transaction bounds and
  concurrency. Unmeasured candidates have unavailable ceilings and cannot admit
  an allocation. The 256 MiB scratch value is a candidate, not a production grant.
- A `StoragePolicy` pins the instance/workspace/operator and original operation,
  filesystem UUID, policy revision, tier/profile digest and three nonnested
  project directories with exact project IDs, UIDs and directory inodes.
- Source configuration sets `storage_backend=project_quota`, `storage_image=null`
  and the typed policy. Inventory stores that policy as canonical JSON. The
  workspace/control paths and identities must match the source. Shared mounts
  require the same filesystem identity; project IDs and directory trees cannot
  overlap another allocation. A qualified existing root filesystem may use `/`
  as the shared mount; project directories and other allocation paths must remain
  private non-root paths. Loop-image mounts still cannot be `/`. Legacy adoption
  cannot create this backend.

`/etc/epm/storage-control.json` has three required keys:

| Key | Protected content |
| --- | --- |
| `filesystems` | Up to 10 `FilesystemBudget` records: exact UUID and mount, recovery headroom, remaining shared overhead, retained-image growth, administrative/control/log growth and inode commitment |
| `profiles` | Up to 100 profile IDs mapped to signed `ProfileReport` artifact UUIDs |
| `bindings` | Up to 1,000 instance keys mapped to signed `BindingReport` artifact UUIDs |

These are remaining growth commitments, not occupied-byte estimates. Accounting
keeps measured allocation, remaining project growth and host budgets separate.
The live collector additionally reserves the full observed reclaimable footprint
(bytes and inodes) as uncertainty: quota and free-space reads are not atomic, and
a concurrent deletion/checkpoint may already have increased free space. This
conservative surcharge prevents spending that occupied-space credit twice. It may
reject an otherwise feasible allocation until a coherent writer barrier permits a
tighter observation; it does not alter reported usage or claim atomic sampling.
Admission retains the greater of 20% total capacity, required recovery space and
16 MiB after commitments and uncertainty. Stopped/disabled allocations still
reserve capacity. Unknown or stale usage fails admission. Reserved projects may
have unset limits, but still undergo exact identity checks and reserve their full
admitted ceilings; active-project observations require enforced limits.

Reports use the existing protected verifier/HMAC artifact store:

- `ProfileReport`: exact profile and digest, artifact UUID, environment hash,
  observed time and expiry. Registration/reservation verify it against the
  protected mapping and current collector environment. A fixture is not evidence.
- `BindingReport`: exact instance, policy digest, inventory/source binding and
  Admin revisions/fence, installed release and sandbox digests, observation and
  expiry. Admission requires fresh observations (less than five minutes old).
- `CleanupReport`: exact cleanup command fingerprint, original operation/policy,
  inventory revision, project identities/ceilings/usage, observation and expiry;
  independently verified no-open-files and directory-absence flags. The root
  adapter also checks actual directory absence and zero allocated blocks/inodes.

No production reports or ceilings are supplied by Slice 8B. Report production and
qualification must finish in the later slices before use on a real host.

## Private command sequence

The installed root command reads a single bounded JSON request on standard input:

```sh
sudo /opt/epm/admin/venv/bin/python -I /opt/epm/admin/admin_console.py operations
```

Use the installed private interpreter path if it differs. Keep credentials out of
arguments, URLs, logs and saved transcripts. Inspect exact typed requests against
the owning contracts; there is no generic shell or arbitrary quota command.

| `action` | Request fields | Effect |
| --- | --- | --- |
| `storage-profile-register` | `report_id` | Validate a mapped signed report and retain its immutable profile/evidence |
| `storage-grant` | Exactly one of `storage_reservation` / `storage` | Issue one action-bound credential for that exact fingerprint |
| `storage-reserve` | `storage_reservation`, `credential` | Recheck authority, source binding, profile and capacity; atomically retain original intent, three project reservations and audit evidence |
| `storage-command` | `storage`, `credential` | Admit an expected-revision action and perform its bounded root effect outside SQLite |

A reservation uses the original UUID as both `id` and `policy.operation_id`,
`expected_revision=0`, a recovery reference, reason and reviewed source authority.
Subsequent `StorageCommand` objects contain a new command `id`, original
`operation_id`, current `expected_revision`, reason and one of:

1. `apply`: reserved → active after exact ceilings and enforcement verify.
   Its pre-apply observation checks filesystem/directory/project attribution but
   permits unset limits; its final proof always requires the strict target limits.
   An interruption after any project is applied can retry the original command.
2. `reconcile`: reserved/active → active after inspecting the original intent.
3. `retire`: reserved/active → retiring; no bytes are deleted or reclaimed.
4. `finish_retirement`: retiring → retired only with verified cleanup evidence.

Each command requires its own exact grant. Apply/reconciliation require the source
maintenance gate owned by the original operation. Effects recheck generation and
protected bindings; release upgrades and quota effects exclude each other. Action
admission is durable before effects; a crash or failed reply is an unknown outcome,
not permission to discard the reservation or generate a replacement upload/key.

Retry the **same** admitted command first. Its completed receipt replays unchanged;
a changed request conflicts. Explicit fresh reconciliation may resolve an uncertain
attempt without erasing its history. For a retiring allocation, ordinary reconcile
cannot reactivate it. After authority/control restoration, a new current-generation
`finish_retirement` command and exact grant may replace an interrupted cleanup. It
requires fresh command-bound cleanup proof, and retains the original attempt; only
successful verified retirement resolves the earlier pending cleanup. Original reservation retries return the original
reserved result, even after the allocation advances. Inspect current state separately.
Project identities remain retained after verified retirement; no automatic reuse or
cleanup is performed. Occupied bytes are never counted as reclaimed by retirement.

Authenticated broker messages `storage_inspect` and `storage_apply` use the Admin
session/CSRF boundary; apply takes only the registered operation command above.
No public Admin HTTP route or browser control exposes them yet. Inspection reads
bounded control metadata only: unknown usage is null, older observations are stale,
and enforcement/project bytes are distinct from logical allowance and host space.
It never runs a scan or silently refreshes a quota.

## Recovery and validation

Current control snapshots preserve profiles, reservations, project identities,
immutable attempts/receipts, revision events and audit evidence. Restore validates
canonical requests, mappings, proofs, event chains and exact results atomically.
Restored authority remains disabled; snapshots do not authorize kernel replay.
After private authority restoration, obtain fresh protected observations and review
explicit reconciliation. Never edit retained intents or delete reservations to make
admission pass. Current-schema validation rejects old formats; no compatibility
migration or live-store rewrite is included.

Focused repository proof (synthetic profiles and mocked effects are not host qualification):

| Area | Coverage |
| --- | --- |
| Happy paths | Reserve, first apply with zero limits, inspect, reconcile, retire, verified cleanup; project root-mount configuration/inventory round trip; root-only JSON transport and exact grants |
| Invalid combinations | Wrong backend/source identity, conflicting mount/filesystem/project/nested paths, unsafe broker fields, stale/expired evidence, missing maintenance gate |
| Retry/authority | Immutable original receipts, changed request conflicts, partial first-apply retry, interrupted cleanup across authority/control restore with fresh proof, CSRF/session/action grants, mutual release/quota exclusion |
| Rollback/races | Concurrent duplicate admission, quota/free-space reclamation interleavings for blocks/inodes, SQL-trigger failure restores credential/reservation/audit, original uncertain attempt retained |
| Persistence | Canonical profiles/intents, correlated audit/revision chains, exact usage/proof/result; corrupt mappings/history rejected |
| Backup/restore | Populated reservation and completed lifecycle snapshots, retained identities, disabled restored authority, failed restore rollback |
| Bounds | Three inspection SELECTs at 1/10/50 allocations, no collector calls; bounded inventory, reservations and action admissions |

Real kernel/sandbox proof remains in [Slice 8A qualification](../qualification/HOSTED_PROJECT_QUOTA_QUALIFICATION.md).
Later source-accounting and final deployment qualification remain required.
