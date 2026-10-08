# OPS-001 implementation slices and validation

Status: partial implementation — October 7, 2026. OPS-001 is not complete.

## Delivered foundation slice

The foundation was implemented in this order: contracts/ports, application commands,
current-baseline persistence, focused tests, then runtime/schema/archive integration.

- Typed readiness bootstrap and preference GET/PUT, with read-only revision-0 defaults.
- Atomic revisions, durable idempotent operation results and correlated metadata-only audit.
- Registered incomplete forms: `task.create`, `maintenance.issue.create`, and
  `communication.record`, version 1. These do not create official records or domain drafts.
- Recovery list/load/save/discard, bounded explicit expiry, and unresolved-attempt retention.
- Maintenance, Communications and Task creation provide source-owned receipts.
  Recoverable Task creation now requires revision zero and a UUID key, persists
  its original response atomically, and replays independently of later Task changes.
  Other Task commands are not thereby enabled. See
  [UI readiness slice 7](UI-001_IMPLEMENTATION_MATRIX.md#slice-7-recoverable-task-creation)
  for concurrent retry, rollback, retained validation and encrypted restore proofs.
- Current greenfield baseline includes `operator_preferences`,
  `operator_recovery_records`, and append-only `operator_operations`.
  Receipts are retained indefinitely, exceeding the minimum 30-day requirement.
- The subsequent coverage slice adds append-only `operator_coverage_reviews`,
  retaining review commands, evidence revisions, operation results, the original
  property time zone, and correlated audit identity. See
  [the UI readiness matrix](UI-001_IMPLEMENTATION_MATRIX.md#slice-5-area-specific-coverage-and-durable-reviews)
  for its source-owned contracts and focused acceptance proofs.
- Runtime composition and workspace-open/archive/restore schema validation include OPS records.
- Batched directory and overview coverage is delivered in
  [UI readiness slice 6](UI-001_IMPLEMENTATION_MATRIX.md#slice-6-batched-directory-and-overview-coverage).
  Counted card previews and independently paged overview coverage share bounded
  source batches, effective membership, the caller's read snapshot and review policy.
- Recovery cursors bind filters, workspace, runtime epoch, audit marker and captured instant;
  they expire after 15 minutes and use the last returned record, not the excluded record.

## Foundation acceptance matrix

| Area | Focused proof |
| --- | --- |
| Happy paths | Preferences and all three incomplete forms; typed API save; production bootstrap composition |
| Bootstrap read failures | Busy/unavailable preference reads after successful production startup retain the typed 200 readiness envelope, safe retry action and validated identity; ordinary errors and unexpected programming failures still propagate; a later successful read restores readiness |
| Invalid combinations | Unknown/duplicate navigation IDs; hidden Home/Settings; unregistered payload fields; boolean revisions; missing source; oversized payload |
| Recovery size errors | Nested oversized strings and participant/link arrays return 413 below the 64 KiB total cap; other malformed values return 422; rejected requests commit no recovery, operation or audit rows; exact size boundaries are accepted |
| Idempotency/retry | Replay after a newer preference change; mismatched key and stale revision conflicts; concurrent same-key recovery submission commits one mutation and receipt |
| Rollback/snapshot | Audit failure rolls back recovery update and receipt; a concurrent writer between count and slice cannot change the established read snapshot |
| Persistence/schema | Exact columns, primary/foreign keys, checks, uniqueness, indexes, append-only triggers; fingerprints/revision/audit replay integrity; tampered payload rejected |
| Recovery retained history | All persisted source, form/schema, attempt/fingerprint and canonical receipt fields match immutable results; revision-ordered transitions preserve evidence and reject later-operation laundering; current-schema and workspace-open tamper tests |
| Backup/restore | Encrypted LOCAL-002 round trip preserves preference/recovery/receipt rows and correlated audits; original receipt replays after restore |
| Restore rejection | Authenticated encrypted archive with rewritten recovery source revision and recomputed inventory is rejected by archive validation and restore before destination publication |
| Query/size bounds | Recovery count/selection/marker stays within four SQL statements for 1 versus 100 records; metadata pages do not select payloads; 100-active-record admission cap |
| Time/freshness | Explicit 30-day expiry; unresolved outcomes cannot expire/discard; gap-free cursor pages; filter, audit, epoch and 15-minute expiry conflicts |
| Privacy | Audit snapshots omit payload, owning request fingerprint, attempt key and owning receipt content; registered schemas reject credentials/file/domain-state fields |

## Remaining slices

These are not implemented or advertised as available capabilities:

1. Source-owned transaction-aware directory/overview readers, including owner/tenant/address
   filtering, property-local effective relationships, bounded nested collections and counts.
2. Finance composition on the same deferred snapshot, including large owner scopes and explicit
   whole-property money periods; Task previews on the shared connection and instant.
3. Initial registered metadata search types with independent bounded group cursors and availability.
4. Focused integration proofs for collection snapshot consistency, independent overview failures,
   directory/search query ceilings, effective-date invalidation and coverage backup/restore.

The complete server suite is intentionally not run; the request limits validation to focused tests.
