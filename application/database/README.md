# Schema resource ownership

H02.2 implements the main-Admin and host-inventory current baselines. The other
three hosted resource sets remain **unimplemented scaffolds**, not initialized databases.
The [schema master](../../docs/database/README.md) owns table/column design;
[H01](../../docs/hosting/design/HOSTED_MVP_H01_DESIGN.md#h012--establish-independent-schema-resource-scaffolding)
owns this handoff. The business baseline, local launcher and old hosted-access consumer remain unchanged.
H02.4 adds explicit component packaging and installed verification. Existing ignored caches from older resource directories are
not executable resources and must not be used as fallbacks.

| Resource set / configuration | Revision namespace | Delivery / connection owner |
| --- | --- | --- |
| Existing `sqlite-migrations/`, `application/alembic.ini` | Existing business revision | Domain-owned business runner; unchanged |
| [admin-migrations/alembic.ini](admin-migrations/alembic.ini) | `admin_` | H02 complete Pilot 0 structural baseline/FK closure and protected deployment metadata; H03/H04 own identity/provisioning population/behavior, H05 protection observations |
| [admin-recovery-migrations/alembic.ini](admin-recovery-migrations/alembic.ini) | `admin_recovery_` | H05 Admin recovery service, independent of main Admin startup |
| [host-inventory-migrations/alembic.ini](host-inventory-migrations/alembic.ini) | `host_inventory_` | H02 restricted host agent only |
| [hosted-access-migrations/alembic.ini](hosted-access-migrations/alembic.ini) | `access_` | H03 owning operator source; H04 policy/accounting contributions |
| [recovery-migrations/alembic.ini](recovery-migrations/alembic.ini) | `recovery_` | H05 owning operator recovery engine, also local recovery composition |

Each store has its own version namespace and private connection. `alembic_version`
is local to that file, not a shared registry. There is no cross-store foreign key,
SQLite ATTACH or transaction spanning these stores. Never reuse the business runner
or open a damaged business/main-Admin DB merely to initialize its recovery store.

## Discovery and runner handoff

`app.platform.schema_resources.resource_config(HostedStore, application_directory=...)`
loads an implemented Admin/inventory set; `scaffold_config` discovers only the three
remaining unavailable sets. Both load exactly one configuration from a trusted installed application root, independent
of the current working directory. It returns configuration **only**; it does not
validate a database or report readiness. Missing/mismatched resource sets fail with
`SchemaResourcesUnavailable`, stable code `schema_resources_unavailable`, without
paths, credentials or connection URLs in the safe message. Unknown store IDs fail
before resource dispatch. No default URL or database path is included in an INI.

The three scaffold `env.py` entry points reject execution with the same unavailable
outcome. The two implemented environments also reject direct Alembic commands; only
the owning runner may supply an explicit connection/transaction. This includes raw
`upgrade`, `stamp`, `ensure_version` and offline SQL generation.
A supplied connection is not used; even an empty or version-looking destination
cannot be treated as matching. No scaffold delivers an empty revision, revision stamp or usable baseline. Alembic `heads` showing no heads is not successful initialization.

H02–H05 must replace each owning scaffold environment with a real runner/baseline,
resource-derived structural validation and initializer **together**, including focused
fresh/existing/failure tests. Remove superseded scaffold-only guards when their final
consumer is replaced; do not keep an unused alternate creator or compatibility path.
The inline hosted-access schema and its consumers move atomically in H03/H04.
No placeholder production route/CLI or startup initializer is registered by H01.2.

## Initialization contract

These requirements are implemented for main Admin and host inventory by
`app.platform.hosted_schema`; the remaining stores fail unavailable before inspecting
or creating a destination. Fixture version rows are not proof of matching.

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

## H02.2 owning runner usage

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
objects reject. Current complete dictionaries define 13 Admin and six inventory tables.
Only bootstrap/schema validation is delivered here; typed retained operation payloads,
authentication and resource effects remain with their owning later slices.

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
default local script modes and wheel metadata remain unchanged. See the
[candidate build runbook](../../docs/hosting/deployment/packaging-and-installation.md) and
[scoped evidence](../../docs/hosting/qualification/reports/HOSTED_MVP_H02_4_HANDOFF.md).
Shipping declared unavailable resource sets does not establish readiness or qualify a release.
