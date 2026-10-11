# Persistence, transactions and portable validation

## Current implementation

The server uses SQLAlchemy over SQLite in an external workspace. The current Alembic baseline, model metadata, exact-schema checks and retained-data validators describe one latest greenfield schema. New work updates them together; there is no legacy-format compatibility requirement.

The shared engine enables SQLite foreign keys, a 5,000 ms busy timeout and deterministic Unicode normalization for indexed matching/sorting. One server owns the workspace writer lock. Domain writes open immediate transactions and validate lifecycle/revision inside that boundary. Read compositions use one deferred snapshot and one captured UTC instant. Never combine independently transactional reads and claim one consistent response. No transaction remains open across HTTP page requests.

## Cross-module operations

Application protocols expose consumer-neutral facts or narrowly defined coordinated commands. Bootstrap composes concrete adapters. Source modules own their tables and policies; consumers own eligibility, workflow and response shaping. Do not import another module's ORM model to enforce a rule.

Lease/Portfolio timeline, owner-report/Finance receipt and source/Task/File effects retain the caller connection, one correlation and atomic required audit/results. Physical file publication has explicit operation-owned rollback leases because filesystem/object storage is outside SQLite. External keyring/provider effects require explicit uncertainty handling; database rollback cannot undo them.

## Revisions and original results

A command's source revision protects its defined aggregate/scope. Several revisions can participate in one workflow: Property inventory, Space status, Lease, Inspection, rent ledger, Expense, deposit account and catalog revisions are distinct. Use the displayed source revisions rather than a timestamp or unrelated aggregate revision.

A UUID operation key identifies a semantic request. Canonical fingerprints use normalized business input and exclude generated publication/record IDs where the domain contract requires it. Identical replay reads immutable original output before current-state validation; changed key reuse conflicts. Effective revision/no-op rules differ by module: Inspection advances for every accepted new command; several other domains retain revision for semantic no-ops. Preserve the source rule.

OPS prepares/reconciles attempts; it never executes business writes. Missing/lost responses are unknown until an owning receipt resolves them. Never reconstruct an original receipt from current records or retry a consequential action under a new key automatically.

## Backup and integrity

Workspace opening checks the exact schema, constraints/indexes/triggers and retained domain/audit/receipt consistency. Backup/restore includes portable records and verified content but excludes secrets. Runtime epoch rotates after reopen/restore. File verification and sensitive disclosure use their own documented boundaries.

## Validation matrix

| Area | Required proof when changing the boundary |
| --- | --- |
| Happy paths | Each accepted lifecycle transition and source-owned consequence |
| Invalid combinations | Context membership, state, paired fields, limits and revisions rejected before effects |
| Retry and idempotency | Same key returns original result; changed request conflicts; no duplicate effects/audit |
| Transaction rollback | Fault in domain, required child, audit or commit leaves no partial business success; physical publication cleanup is accounted for |
| Persistence/schema | Baseline/model/expected-table agreement, checks/indexes/immutable triggers and retained receipt/lineage validation |
| Backup/restore | Stable IDs, domain state, evidence, audit and receipts preserved; secrets excluded; runtime continuations invalidated |
| Query bounds | Fixed query count or declared budget, source-side counts/filters and no per-row hydration |

The module guides link the existing executable tests. Active feature designs record new acceptance obligations. Historical validation reports are archived evidence with their original dates, not a claim that this consolidation reran tests.

## Code entry points

- [SQLite engine](../../application/apps/server/app/platform/sqlite_engine.py).
- [Baseline registration](../../application/apps/server/app/platform/product_migrations.py).
- [Current schema](../../application/database/sqlite-migrations/versions/0001_initial_schema.py).
- [Workspace validation and archives](../../application/apps/server/app/modules/workspace/application).
- [Bootstrap composition](../../application/apps/server/app/bootstrap/api.py).
- [Implementation quality policy](../CODE_QUALITY.md).
