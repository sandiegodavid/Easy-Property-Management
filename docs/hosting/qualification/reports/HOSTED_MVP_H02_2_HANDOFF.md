# H02.2 — Main-Admin and inventory structural resources

H02.2 delivers current greenfield schema resources and protected initialization on
`hosted_mvp`, starting at `52a62d89d6a8b336d481b871a2eb8e0607250a05`.
This is local structural/transaction validation, **not native host qualification,
authentication, provisioning or release approval**.

## Delivered behavior

- `admin_0001_initial` contains all 13 main-Admin tables, including identity,
  operations and monitoring dependencies. Local FKs remain enabled. The nullable
  assignment operation reference permits insert-assignment → insert-operation →
  link-operation in one owning transaction without disabling FK enforcement.
- `host_inventory_0001_initial` contains host identity, operator principals, resource
  bindings, project assignments, ingress authority and host receipts. It includes
  distinct UID/GID and project allocations, composite workspace/generation FKs,
  unique active bindings, initial held ingress, monotonic fences and consistent
  observed revision/state fields.
- Immutable intent, terminal receipts/results, append-only audit/events and retained
  allocation identities have resource-owned triggers. `INSERT OR REPLACE` cannot
  bypass those guards. Project release requires recorded retirement/verified cleanup;
  recording that proof is still the later owning adapter's responsibility.
- Shared column checks and all DDL live under `application/database/`. Runtime modules
  invoke resources or reflect existing tables; no alternate creator, `create_all`,
  startup fallback, compatibility migration or direct stamp path was added.
- Resource discovery checks owning identity, namespace, canonical installed paths,
  absence of a default URL, sole current baseline and shared definitions. An
  in-memory preflight also verifies the baseline's declared table inventory before
  touching a destination. Missing, syntactically broken or empty-upgrade resources
  cannot reserve a store file.
- The owning initializer exclusively reserves a fresh 0600 regular file in a
  canonical caller-owned private directory. Symlinks, hardlinks, FIFOs, nonprivate
  paths and existing empty/partial files reject. It uses a real SQLite transaction
  for DDL and version writes; failed baseline or commit rolls back and retains the
  reservation for explicit inspection, never silently adopts or deletes it.
- Matching reinit opens SQLite read-only in a snapshot. Exact `sqlite_schema`
  tables/columns/checks/FKs/indexes/triggers are compared with the same baseline run
  in memory; revision text alone is insufficient. FK checks and SQLite quick-check
  run without mutation. Extra attached stores and temporary objects reject.
- Caller-owned schema and protected metadata transactions are never committed or
  closed by helpers. Separate `DeploymentMetadata`/`HostMetadata` bindings insert only
  their singleton, return unchanged on exact retry and reject a different binding.
  Schema initialization itself leaves all owning tables empty; it grants nothing.

The two implemented environments reject raw Alembic upgrade/stamp/ensure-version
and offline commands. Only the owning runner supplies the explicit connection and
transaction; an INI URL or caller-supplied engine is not an alternate initialization path.
The remaining access and two recovery stores retain their unavailable guards. Old
hosted-access inline resources remain in use until their owning H03/H04 replacement.

## Validation matrix

| Area | Focused proof |
| --- | --- |
| Happy path | Both real baselines initialize, return the owning revision/fingerprint, match every dictionary table/column and reinit without changing bytes, mtime or metadata. No automatic authority seed. |
| Invalid combinations | Wrong store/revision/shape, missing index/trigger, broken/missing resources, malformed origins, unsafe paths, invalid UUID/hash/state/actor/payload, wrong assignment/release/workspace and mismatched ingress generation/receipt reject. |
| Retry/idempotency | Matching protected bindings do not update; mismatch leaves the original. Unique kind/key and immutable intent/terminal result guards reject replacement. Owning command replay behavior is H02.3/H04. |
| Rollback | Actual SQLite DDL and version rollback in supplied transactions; fault injection after baseline and at commit; retained failed files are not retried as fresh. Metadata mutation/rollback preserves caller ownership. |
| Persistence/schema | Closed action/state vocabularies, partial unique indexes, same-store FK closure, live invitation uniqueness, cleanup ordering, guarded ingress observations and append-only evidence. Tampered retained FK rows fail reinit. |
| Backup/restore handoff | SQLite snapshot copies preserve metadata and validate with identical owning resources. This is not encrypted/off-host or authenticated restore qualification; H05 still owns those gates. |
| Query/N+1 | Validation uses at most six statements on the tested target connection, independent of table/row iteration. Baseline-derived template generation is separate bounded in-memory DDL, not provider or database fan-out in a list request. |

See [machine-readable evidence](HOSTED_MVP_H02_2_VALIDATION.json) for exact source
hashes, commands, environment, counts and changed Python lint scope. The final
focused run passed **489 tests**; Ruff check and format check passed for all 13
changed Python files. No frontend
files or generated contracts changed; frontend checks are not applicable. Only the
focused schema/resource/hosted-contract suites ran, not the full server suite.

## Owning APIs and next gates

Usage and installed-resource requirements are in the [database guide](../../../../application/database/README.md#h022-owning-runner-usage).
Structural readiness is deliberately separate from physical and identity readiness:

- H02.3 adds admitted-intent authentication, durable effect execution/reconciliation,
  real allocation and current-fence checks. These baselines dispatch no effects.
- H02.4 stages each revision, INI, environment and shared `hosted_ddl.py` together;
  existing business wheel staging is unchanged and is not hosted-image acceptance.
- H02.5–H02.9 verify actual protected device/mount identities, quota enforcement,
  sandbox, gateway/restart policy and native/Docker/GCP behavior before any start.
- H03/H04 populate identities/policies/operators/releases and validate typed retained
  operation payloads and application lifecycles. H05 owns recovery authority and
  protection observations. Initializers seed no qualified releases, identities or sessions. Explicit synthetic
  test-only release fixtures exercise FK closure and are not promoted.

No VM inspection/reset, cloud provisioning, customer ingress or public initializer
route was introduced. Historical H01 and native qualification reports remain unchanged.
