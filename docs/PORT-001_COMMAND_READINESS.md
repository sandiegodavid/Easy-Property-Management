# Portfolio inventory command readiness — UI-001 Slice 14

Delivered October 8, 2026. The approved concurrency scope is one shared Property
revision for Property identity/lifecycle, ownership replacement, and Space
inventory changes. PORT-003 Space status revisions remain independent.

## Command contracts

| Workflow | Required revision | Recorded result |
| --- | --- | --- |
| Property creation, including initial owners and Spaces | Property revision zero | Original Property representation at revision one |
| Property identity patch | Current Property revision | Original committed Property representation |
| Property archive/restore and Space cascades | Current Property revision | Original Property representation; one aggregate increment per effective command |
| Ownership replacement, including inline owners | Current Property revision | Original Property representation; relationships, inline Party creation, and receipt are atomic |
| Space add/edit/archive/restore | Current parent Property revision | Original Space representation plus committed `propertyRevision` |

Every command requires `expectedPropertyRevision` and a nonblank, trimmed
1–200-character `idempotencyKey` at HTTP and application boundaries. Revisions
are exact non-negative integers, not booleans or coercible strings. Creation
requires zero. The application argument is `expected_revision`.

Effective commands increment the Property revision exactly once and use one
injected UTC instant for timestamps, `asOf`, and property-local date decisions.
Unchanged edits, identical ownership sets, and already-achieved lifecycle states
preserve the owning revision/timestamp and record an immutable no-change receipt.
Archive confirmation, layout rules, effective-dated ownership safeguards, and
source-owned occupancy/archive guards remain enforced.

Successful commands return required `propertyRevision` and `operationId`.
Space results retain `revision` as the separate Space **status** revision. They
also carry `asOf` and `effectiveLocalDate`. Replay precedes lifecycle and stale
revision checks, returns the complete original response, and does not repeat
inline Party creation, cascades, ownership writes, or audits. Changed key reuse
returns `portfolio_inventory_payload_conflict` (409); stale Property revisions
return `portfolio_inventory_revision_conflict` (409) with the complete latest
Property representation in `currentStatus`.

Read-only recovery uses one indexed receipt SELECT, without loading current
Property/Space state or resubmitting a command:

- `GET /api/portfolio/inventory-operations/{operationId}`;
- `GET /api/portfolio/inventory-operations/by-key?idempotencyKey=...`, including
  lost creation responses where the Property ID is not yet known;
- `GET /api/properties/{propertyId}/inventory-operations/by-key?idempotencyKey=...`.

Typed requests, results, conflict envelopes, receipt responses, and stable
OpenAPI operation IDs are declared. No additional OPS recoverable forms or
consequential browser controls are registered by this slice.

## Current-format persistence

`properties.property_revision` is a required exact integer at least one.
`portfolio_inventory_operations` stores stable operation/Property/correlation
IDs, globally unique key, action, expected/result revisions, effective flag,
canonical request and original response JSON, SHA-256 fingerprints, and commit
time. Result revision equals expected revision plus the effective flag. A partial
unique index prevents duplicate effective revisions for one Property.

Receipt inserts, domain writes, inventory before/after witnesses, and the
`portfolio_inventory_operation/recorded` audit commit in the same immediate
transaction. Append-only triggers prevent update, delete, and replacement.
Receipt activity excludes keys and payload fingerprints; raw request/result JSON
is not copied into activity snapshots.

Exact schema validation covers column types/nullability/keys, checks, foreign
keys, unique definitions, index predicate, and trigger bodies. Retained validation
reconstructs revision and inventory chains, checks canonical fingerprints and
typed original results, requires correlated owning workflow/effect/receipt
audits, and verifies current Property, ownership, and Space inventory facts.
Independent status revision and status-writer timestamps do not masquerade as
inventory changes. Workspace open, backup/export, and restored-workspace
validation use this validator. Only the latest greenfield baseline is supported.

## Focused validation matrix

| Area | Proof |
| --- | --- |
| Happy paths | Property create/edit, ownership replacement, Space add/edit/archive/restore, and selective Property cascades |
| Invalid combinations | Existing archive/layout/source guards; required metadata, exact revision types, invalid keys, typed UUID/date inputs |
| Idempotency/retry | Complete original replay after later changes; globally changed reuse; concurrent same-key creation; no-change receipts |
| Concurrency | Space inventory changes stale the parent Property; status changes keep their independent Space revision |
| Temporal consistency | One injected instant, including a UTC/property-local date boundary, in ownership and returned results |
| Rollback | Receipt-audit failure and transaction-commit failure leave no partial cascades, revision, receipt, or audits |
| Persistence | Append-only guards; rewritten inventory/receipt/audit and weakened trigger rejection |
| Backup/restore | Encrypted archive preserves all receipt columns and original replay after intervening archive/restore |
| Query budgets | Single indexed read-only recovery SELECT; existing bounded Portfolio directory/paging and OPS projection tests |
| Integration | Existing Lease/status, Finance, Maintenance, Inspection, Owner-report, Provider, OPS, Audit, and workspace fixtures use explicit named inventory commands |

Only focused tests and changed-file Ruff checks are run; no full application suite
or frontend validation is claimed.
