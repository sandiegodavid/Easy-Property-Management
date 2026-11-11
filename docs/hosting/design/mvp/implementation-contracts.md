# H02 quota reuse and schema implementation contracts

[Hosted MVP design index](../HOSTED_MVP_DESIGN.md) · [Schema catalog](../../../database/README.md)

Part of the accepted HOSTED-001 design. Requirements here do not establish implementation, deployment or qualification; Pilot 0 exceptions are in the [delivery plan](delivery-plan.md).

#### H02 project-quota reuse contract

Use the [selective quota import](../../qualification/HOSTED_PROJECT_QUOTA_REUSE.md),
from `Admin_UI_Workflow` at `cba6a7bf2561de06634abbddff0b60782949e6fc`, as an
implementation input rather than rebuilding the low-level Linux quota work. The
[import manifest](../../qualification/PROJECT_QUOTA_IMPORT_MANIFEST.json) records exact
upstream blobs/hashes and unchanged historical evidence. Importing these files did
not implement H02, register a runtime capability or qualify project-backed sources.

| Imported material | H02 treatment |
| --- | --- |
| `project_quota.py` | Reuse protected ext4 filesystem/binding checks, inheritance, hard byte/inode limit operations and observations behind the restricted host-agent port. Actual resource IDs/roots come from protected inventory, never browser requests. |
| `project_sandbox.py` plus `quota_sandbox_exec.c` | Preserve the combined sandbox/security intent and ioctl escape protections. The old systemd profile and launcher are not a ready-made Docker policy; design and requalify the complete container/host boundary. |
| `quota_actor.py` and `project_quota_qualification.py` | Reuse adversarial UID workloads and disposable native harness for EDQUOT, deleted-open usage, unsafe binding/enforcement rejection, isolation/escape, remount and actual reboot tests. Keep explicit root-Linux opt-in and fresh disposable-image guards. |
| Focused tests and historical reports | Keep regression inputs and evidence byte-for-byte with original pins. The current import's 23 passing contract tests/Ruff checks are not a new native quota pass. |

The historical post-reboot run passed only for its local ARM64 Linux kernel,
filesystem, tools, sources and systemd/seccomp boundary. Imported `project_quota.py`,
`project_quota_qualification.py` and `project_sandbox.py` differ from that report's
source hashes; `quota_actor.py` and the C launcher match. Never relabel the historical
pass as proof of the current files, Google VM or Docker runtime. Preserve failed runs
and exact source/tool/configuration pins when producing new qualification evidence.

H02 detailed design must define these steps before integration:

1. Map ProjectBinding/host operations to the current inventory, project-ID uniqueness,
   source fences and private resource roots in the [schema master](../../../database/README.md).
   Retaining the old package namespace for import reproducibility does not authorize
   importing the old Admin schema/router/provisioning implementation.
2. Rerun current-source primitive qualification in an isolated Linux laboratory. Use
   Docker Desktop for ordinary Mac development and retain `epm-quota-test` for native
   tests, stopped when unused. Preserve its baseline before installing Docker or
   changing kernel/filesystem/tools; record and requalify the changed environment.
3. Qualify actual non-root Docker UID mappings, capabilities, mount/project mutation
   denial, syscall/ioctl restrictions, inheritance and cross-workspace isolation.
   Bound every writable path, including container layers/tmpfs, SQLite/WAL, uploads,
   scratch, logs and private auth/recovery storage. Neither CPU/RAM limits nor old
   systemd evidence alone prove the persistent storage boundary.
4. Re-prove enforcement, resource identity and persistence after container replacement
   and host reboot on the exact admitted Google Cloud host/kernel/filesystem/Docker
   configuration. Never format or change features on an existing data filesystem
   through Add operator; any host preparation needs its own reviewed H02 setup plan.
5. Measure physical byte/inode ceilings and operational/restore reserves for Free 50 MB
   and the admitted warm population; synthetic fault-test limits are not production
   profiles. H04 owns logical metering/reservations. The old source-ledger/collector
   stack was not imported and needs separate design/review before any later reuse.
6. Publish current component/native/cloud results and limitations in the
   [acceptance register](../../qualification/HOSTED_MVP_ACCEPTANCE.md). No production
   quota activation or application-only fallback is admitted before the applicable
   current-runtime and native-host gates pass.

This reuse contract supplements the [accepted H02 detailed design](../HOSTED_MVP_H02_DESIGN.md),
which defines container/network/IAM/schema-resource/local-launch boundaries. The
[foundation guides](../../foundation/README.md) consolidate delivered behavior,
operations and exactly scoped evidence by topic. Accepted requirements alone do not
establish proof; this documentation does not perform VM/cloud changes or new runs.

#### Schema ownership and acceptance contract

The [database schema master](../../../database/README.md) is the single dictionary for
store ownership, tables/columns, relationships, initialization and schema acceptance.
[H01 detailed design](../HOSTED_MVP_H01_DESIGN.md) defines the corresponding use cases,
source inventory, typed contracts, UI handoff and proof plans. Both are design, not
complete hosted schema resources. Keep later feature additions in the master rather than
duplicating column lists in individual slices.

H01 owns the logical schema design and store boundaries needed for Pilot 0, not
implementation of all future tables. Accepted H02 D1 delivers the complete main-Admin
structural baseline/FK closure and inventory baseline from the master. H03–H05 retain
their owning population/behavior and access/recovery resource delivery before H06.
H02 does not become an independent schema designer. Its candidate images are not
qualified production releases while required later resources/assets are unavailable;
repeat full all-store/image qualification after delivery and before H06. H07–H11 design their additions
before feature implementation, maintaining the same ownership map and dictionary.
H06 and H12 retain schema/version pins with release evidence rather than adding
new domain tables merely for qualification.

| Store/boundary | H01 Pilot 0 design | Later owning additions |
| --- | --- | --- |
| Admin/control registry | H02 delivers one complete Pilot 0 structural baseline, including identity/operations FK closure and protected deployment metadata. H03/H04 own verified identity, Free policy, operator/provisioning and operational behavior; H05 owns protection summaries. Candidate artifacts never seed fake qualified releases. | H07 automation jobs/claims/reservations/effect references; H09 subscription desired state/provider references; H10 releases, schedules and rollout operations; H11 runtime lifecycle operations. |
| Admin recovery store | Separate admin_recovery_meta, control backup checkpoint, control_recovery_operations, control_recovery_points, control_restore_operations and control_recovery_audit; H05 owns persistence/authenticated recovery mode while main Admin data is replaced. | H10 release/schema compatibility must include this store. Off-host manifests/bootstrap reconstruct a lost catalog with previous jobs inert. |
| Protected inventory | H02 owns registered host/container/directory identities, operator UID/GID mapping, resource limits, monotonic ingress fences and parent/child effect receipts. Protected gateway/runtime files are generated projections. H04 integrates admitted provisioning/access results through owning commands. | H07 reconciliation observations; H08 physical allocation changes; H10/H11 verified release/runtime effects. No second editable registry in config files. |
| Per-operator hosted-access/control | Effective account/identity assignment, invitation/session/revocation facts, source fences and bounded Free storage admission/operation receipts; H03/H04 deliver them. | H08 metering/reservations/overage; H09 effective subscription capability; H10/H11 applicable execution/runtime fences. Operator processes never open the Admin DB. |
| Per-operator recovery store | Private recovery_meta, checkpoint, operation/audit, recovery_points and restore_operations outside business data; H05 implements internal normal/authenticated recovery modes; no offline operator restore/decrypt entry point. Admin owns only summary projection and separate platform/control recovery. | H08 paid cadence/retention qualification; H10 pre-upgrade point links. Immutable manifests permit explicit catalog reconstruction without a central workspace catalog. |
| Operator business workspace | Existing owning module tables remain domain authority; identify any required interface/schema changes explicitly. Keep live hosted credentials/session authority outside portable business records. | Portal/Finance/Payments changes belong to their functional backlogs, not HOSTED-001. Do not add billing or session tables to the business baseline. |

For each persisted record, the owning slice must deliver:

- An updated relationship diagram and data dictionary: purpose/owner, column name,
  type, units/time basis, nullability/default, primary/foreign/semantic identity,
  uniqueness/check constraints, indexes, lifecycle/retention and sensitive fields.
  Cross-store identifiers are logical references with validation/reconciliation,
  not unsupported cross-database foreign keys or atomic-commit claims.
- One authoritative schema definition and reproducible initialization/version check
  per store, following the business workspace's versioned Alembic/resource pattern
  where SQLite is used. Keep every executable definition under `application/database/`, with separate main Admin, Admin recovery,
  host-inventory, hosted-access and per-operator recovery resource sets alongside the business baseline.
  Runtime modules consume/validate these resources; no inline DDL, ORM `create_all`
  or alternate startup schema definitions. Document exact
  resource/code paths as they are implemented and package them with the release.
- Initial population ownership/order, transaction boundaries, revisions/fences,
  operation keys/semantic hashes and safe retries. Free policy/assignment must exist
  before activation; desired state is distinct from verified effective state.
- Focused proof of fresh initialization, valid/invalid combinations and constraints,
  duplicate/changed-key retries, transaction rollback, supported schema/version
  rejection, persistence after restart, consistent backup/restore and bounded indexed
  query behavior without per-operator lookups. Include code/schema/artifact pins.

Before the first deployment keep the latest greenfield format/baseline only; no
legacy-data migration or compatibility project. Once Pilot 0 contains real records,
subsequent releases must evolve those actual stores safely, qualify upgrades from
admitted versions and preserve accepted writes. Do not recreate a deployed Pilot 0
store to avoid an upgrade. Update the schema dictionary/diagram and matching resource,
model, validators and tests together; schema acceptance is part of the slice, not
an unspecified documentation task after completion.

HOSTED-001 completion requires H01–H12 acceptance; H06 is a limited release, not
completion of paid automation. PORTAL-001/002 can prepare contracts after H03, but
public paid portal activation requires the relevant H07–H12 hosted gates and their
own payment/privacy acceptance. These portal features are not included in Pilot 0.

