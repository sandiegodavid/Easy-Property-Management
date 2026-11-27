# Schema resource ownership

[Schema master](overview.md) · [Lifecycle and retention](lifecycle-and-validation.md) · [Executable resources](../../application/database/)

H02.2 implements main Admin and host inventory. H03.2 extends the current Admin
identity baseline and implements hosted access. H05.1 implements both recovery
resource sets (`admin_recovery_0001_initial` and `recovery_0001_initial`), completing
structural baselines for all five hosted stores (`unavailableSchemas = []`).
The [schema master](overview.md) owns table/column design;
[Hosted Live Architecture](../hosting/ARCHITECTURE.md#2-state--store-ownership-6-sqlite-stores)
summarizes the delivered 6-store ownership boundary. The business baseline and local launcher remain unchanged; the obsolete hosted-demo
initializer is closed and its runtime DDL removed.
H02.4 adds explicit component packaging and installed verification. Existing ignored caches from older resource directories are
not executable resources and must not be used as fallbacks.

| Resource set / configuration | Revision namespace | Delivery / connection owner |
| --- | --- | --- |
| Existing `sqlite-migrations/`, `application/alembic.ini` | Existing business revision | Domain-owned business runner (includes `FIN-009` late-fee tables and immutability triggers in `0001_initial_schema`) |
| [admin-migrations/alembic.ini](../../application/database/admin-migrations/alembic.ini) | `admin_` | H02 complete Pilot 0 structural baseline/FK closure and protected deployment metadata; H03/H04 own identity/provisioning population/behavior, H05 protection observations |
| [admin-recovery-migrations/alembic.ini](../../application/database/admin-recovery-migrations/alembic.ini) | `admin_recovery_` | H05 Admin recovery service, independent of main Admin startup |
| [host-inventory-migrations/alembic.ini](../../application/database/host-inventory-migrations/alembic.ini) | `host_inventory_` | H02 restricted host agent only |
| [hosted-access-migrations/alembic.ini](../../application/database/hosted-access-migrations/alembic.ini) | `access_` | H03 owning operator source; H04 policy/accounting contributions |
| [recovery-migrations/alembic.ini](../../application/database/recovery-migrations/alembic.ini) | `recovery_` | H05 owning operator recovery engine, also local recovery composition |

Each store has its own version namespace and private connection. `alembic_version`
is local to that file, not a shared registry. There is no cross-store foreign key,
SQLite ATTACH or transaction spanning these stores. Never reuse the business runner
or open a damaged business/main-Admin DB merely to initialize its recovery store.

## Discovery and runner handoff

`app.platform.schema_resources.resource_config(HostedStore, application_directory=...)`
loads all five implemented hosted store sets (`ADMIN`, `ADMIN_RECOVERY`, `HOST_INVENTORY`,
`HOSTED_ACCESS`, `RECOVERY`); `scaffold_config` remains available only for unimplemented
scaffolds (currently none). Both load exactly one configuration from a trusted installed application root, independent
of the current working directory. It returns configuration **only**; it does not
validate a database or report readiness. Missing/mismatched resource sets fail with
`SchemaResourcesUnavailable`, stable code `schema_resources_unavailable`, without
paths, credentials or connection URLs in the safe message. Unknown store IDs fail
before resource dispatch. No default URL or database path is included in an INI.

All five implemented `env.py` environments reject direct Alembic commands; only
the owning runner may supply an explicit connection/transaction. This includes raw
`upgrade`, `stamp`, `ensure_version` and offline SQL generation.
A supplied connection is not used; even an empty or version-looking destination
cannot be treated as matching. No scaffold delivers an empty revision, revision stamp or usable baseline. Alembic `heads` showing no heads is not successful initialization.

H02–H05 replace each owning scaffold environment with a real runner/baseline,
resource-derived structural validation and initializer **together**, including focused
fresh/existing/failure tests. Remove superseded scaffold-only guards when their final
consumer is replaced; do not keep an unused alternate creator or compatibility path.
H03.2 removes the inline hosted-access creator and closes the obsolete consumer.
No placeholder production route/CLI or startup initializer is registered by H01.2.

## Initialization contract

These requirements are implemented for all five hosted stores (`ADMIN`, `ADMIN_RECOVERY`,
`HOST_INVENTORY`, `HOSTED_ACCESS`, `RECOVERY`) by `app.platform.hosted_schema`.
Fixture version rows are not proof of matching.

| Input / condition | Required implemented behavior |
| --- | --- |
| Missing/incomplete owning resources | Fail `schema_resources_unavailable` before file/engine/transaction creation; never fall back to business, old inline DDL, a cache or another store. |
| New private destination | Validate protected canonical path/ownership, exclusively reserve a fresh file and run the complete owning baseline with foreign keys/constraints. Validate exact store/revision/structure before reporting schema-ready. No automatic identity or access grant. |
| Already matching store | Validate exact owning store, revision and resource-derived structure read-only; return already initialized without baseline replay, revision stamping or business-row changes. Validate deployment identity separately through the owning application initializer. |
| Wrong store, revision or structure | Fail closed, leave bytes intact, no upgrade/migration/relabel/reset; greenfield initialization is not deployed-data migration. A version row alone is insufficient. |
| Interrupted initialization / empty or partial file | Never automatically adopt, stamp or overwrite. Fail closed and retain evidence; explicit owner-reviewed cleanup may prepare a genuinely new destination for a new initialization attempt. |
| Baseline or commit failure | Do not report ready. Roll back owning transactional work; preserve the failed reservation/partial state for explicit inspection if cleanup cannot be proven. No automatic retry against a partial file or another store. |
| Caller-owned connection | Use only the explicitly owned store/transaction, do not commit/close another owner's connection; reject cross-store attachments. Actual rollback/constraint proofs belong to the owning runner. |

Schema creation and protected data initialization are distinct commands/contracts.
After complete schema validation, owning application transactions may insert explicit
protected deployment/host/recovery bindings, bootstrap principal, Free policy or
qualified release assignments according to the master. They may not invent operator
or workspace identities, enable an account, create sessions or seed business records.
Provisioning/claim supplies those later using current authority and original receipts.
No remaining scaffold performs either step. H02.2 adds separate typed
`bind_deployment` and `bind_host` adapters; neither grants readiness or access.

## Owning runner usage

<a id="h022-owning-runner-usage"></a>

From trusted application/bootstrap composition, supply an absolute canonical installed
application root and destination beneath a caller-owned private (0700) directory:

```python
from app.platform.hosted_schema import initialize_store
from app.platform.schema_resources import HostedStore

result = initialize_store(
    HostedStore.ADMIN,
    private_admin_directory / "admin.sqlite",
    application_directory=installed_application_root,
)
```

This creates only the schema in a fresh exclusive 0600 regular file. Existing empty,
partial, wrong-store/revision/shape, linked or nonprivate files reject without reset.
Failed initialization retains its reserved file for explicit owner inspection. Matching
reinit uses SQLite read-only mode and does not replay DDL or bind metadata.

For an explicitly caller-owned SQLite connection, enable foreign keys before beginning
an actual SQLite transaction (`BEGIN IMMEDIATE` for creation). `create_schema` neither
commits nor closes it; SQLAlchemy autobegin alone is insufficient for transactional DDL.
`validate_schema` requires an actual caller-owned SQLite snapshot and checks the
current resource-derived sqlite_schema inventory, owning revision, foreign keys and
quick-check without mutation. Attached stores and temporary
objects reject. The current resource sets define 22 Admin, six Admin recovery, six
inventory, nine hosted-access and six Operator recovery tables. Structural validation alone grants no identity or resource authority; use
the owning service/host contracts and their separate qualification evidence.

After schema creation, the explicit protected `DeploymentMetadata`/`HostMetadata`
contracts may be bound through their owning infrastructure adapters in a caller-owned
transaction. Matching metadata returns without update; mismatches never rebind/reset.
Physical host/device/quota proof is still required before any resource authority/start.
No public initializer endpoint or automatic startup fallback is registered.

## Component packaging requirements

H02 must declare and stage the complete resource set for each component, not scan all
folders or infer readiness from the current wheel. Admin needs main Admin plus separate
Admin recovery; the restricted host agent needs inventory; hosted Operator needs
business, hosted access and operator recovery. Production local Operator keeps only
its declared business/local recovery requirements, without enabling hosted authority.
Development uses the same owning resources with isolated synthetic stores.

Package each selected INI/environment and all real revision files as one immutable,
manifest-pinned set; keep maximum revision identifiers within 32 characters. Verify
component identity, required schema revisions and complete structural resources in a
fresh installed environment with no checkout/CWD dependency. Missing/wrong resources
must reject before destination access. Include negative packaging tests and keep
unimplemented sets unavailable: shipping an empty `versions/` does not qualify a release.
No secrets, store contents, default URLs, runtime fallback DDL or alternate test schema
may ship. H02.4 implements explicit `--component` staging/installation verification,
per-component file/hash manifests and actual installed OCI/agent-bundle checks. The
default local script modes and wheel metadata remain unchanged. See
[Host Provisioning & Packaging](../hosting/operations/host-provisioning-and-packaging.md) and
[Pilot 0 Exit Review](../hosting/qualification/reports/HOSTED_MVP_H06_10_EXIT_REVIEW.md).
Shipping declared unavailable resource sets does not establish readiness or qualify a release.

## Store-specific resource notes

Shared discovery, transaction, file-safety and packaging rules above apply to every
set. Each set owns its INI, environment and revisions; no default database URL is
supplied. Revision IDs are limited to 32 characters. Keep one current greenfield
baseline per implemented store, without compatibility revisions or downgrade paths.

### Main Admin

[Resources](../../application/database/admin-migrations/) · [Dictionary](admin-registry.md) · [Live Architecture](../hosting/ARCHITECTURE.md#2-state--store-ownership-6-sqlite-stores)

`admin_0001_initial` contains 22 tables across control metadata, identity flows, admission, and operational audit. The owning
revision and [shared column helper](../../application/database/hosted_ddl.py) define
all DDL. Schema creation seeds no identity, policy, operator, release assignment or
session. Protected deployment binding is separate and cannot grant authentication.
The installed set includes its INI, environment, revision and shared helper; installed
wheel staging alone is not hosted-image qualification.

### Host inventory

[Resources](../../application/database/host-inventory-migrations/) · [Dictionary](host-inventory.md) · [Live Architecture](../hosting/ARCHITECTURE.md#2-state--store-ownership-6-sqlite-stores)

`host_inventory_0001_initial` contains six tables for host identity, operator
principals, resource/project allocations, ingress and child-effect receipts. Schema
creation seeds none of those authority records. Protected host/filesystem metadata
binding is a separate caller-owned transaction. Actual device, mount, quota and host
checks remain mandatory before resource authority or container starts. Do not mistake
schema readiness for the host agent's operational qualification.

### Hosted access

[Resources](../../application/database/hosted-access-migrations/) · [Dictionary](operator-access.md) · [Live Architecture](../hosting/ARCHITECTURE.md#2-state--store-ownership-6-sqlite-stores)

`access_0001_initial` contains nine initially empty tables. Schema creation seeds no
operator, policy, usage measurement or session. The owning initialize-binding command
supplies verified identity and fixed Free applied policy, inserting disabled,
subject-null metadata with the admitted epoch. Structural readiness grants no login.

Local audit-to-receipt and replacement-to-predecessor FKs use RESTRICT. Central,
business and inventory references remain logical, including draft session ownership.
Reverse-reference indexes support reconciliation and explicit cleanup. Receipts/audit
are immutable and retained, including against INSERT OR REPLACE.

Owning services enforce typed/secret-free JSON, authenticated admission, registered
scope, live-session cap, renewal lineage, five-minute binding expiry from emission
(not stored here), CAS and terminal-attempt retention for at least 24 hours plus
reconciliation. SQL checks stored bounds, not external evidence.

Focused resource tests cover valid/invalid rows, lifetimes, uniqueness, local FKs,
immutable retries, rollback, drift and SQLite backup/restore. Index inventory checks
cover lookup budgets; runtime query budgets, login retries and backup secret exclusion
remain owning-service validation.

### Admin recovery

[Resources](../../application/database/admin-recovery-migrations/) · [Dictionary](admin-recovery.md)

`admin_recovery_0001_initial` (implemented in H05.1) contains six initially empty tables
in the `admin_recovery_` revision namespace: `admin_recovery_meta`,
`control_recovery_operations`, `control_recovery_points`, `control_restore_operations`,
`control_backup_state` and `control_recovery_audit`. The owning revision and
[shared column helper](../../application/database/hosted_ddl.py) define all DDL, with
no cross-database foreign keys to `admin.sqlite`. Schema creation seeds no deployment
binding, authority policy, recovery points or sessions. Triggers enforce immutability,
retention, monotonic generations/revisions, terminal operation/restore locks and
append-only audit; `schema_validation.py` enforces constant-query cross-table consistency
and duplicate-key-free JSON validation.

### Operator recovery

[Resources](../../application/database/recovery-migrations/) · [Dictionary](operator-recovery.md)

`recovery_0001_initial` (implemented in H05.1) contains six initially empty tables in
the `recovery_` revision namespace: `recovery_meta`, `recovery_operations`,
`recovery_points`, `backup_state`, `restore_operations` and `recovery_audit`. The owning
revision and [shared column helper](../../application/database/hosted_ddl.py) define all
DDL separately from business and hosted-access data. Schema creation seeds no workspace
binding, encryption key reference, recovery points or operations. Triggers enforce
immutability, retention, monotonic generations/revisions, terminal operation/restore
locks and append-only audit; `schema_validation.py` enforces constant-query cross-table
consistency and duplicate-key-free JSON validation.
