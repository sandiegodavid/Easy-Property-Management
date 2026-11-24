# Schema ownership and acceptance contract

[Hosted MVP design index](../HOSTED_MVP_DESIGN.md) · [Schema catalog](../../../database/overview.md)

Part of the accepted HOSTED-001 design.

#### Schema ownership and acceptance contract

The [database schema master](../../../database/overview.md) is the single dictionary for store ownership, tables/columns, relationships, initialization, and schema acceptance. All six Pilot 0 stores are implemented and live; `H07–H11` design their additions before feature implementation, maintaining the same ownership map and dictionary.

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

