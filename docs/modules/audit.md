# Audit history and read markers

## Responsibility

Audit retains append-only before/after evidence, changed fields, actor/source, timestamp, optional reason and shared operation correlation. A domain service owns the mutation and supplies registered snapshot/activity policies; Audit does not decide domain eligibility or provide operation idempotency storage.

## Transaction and privacy rules

Business writes and required audit events share one transaction and fail closed. Database triggers reject ordinary update/delete/replacement of audit history. Sensitive evidence disclosure commits its read audit before returning data. Failed writes cannot emit successful business-change history.

The bounded hosted demo adds `hosted_operator` with a canonical provisioned operator UUID as its portable actor reference, never an email, provider subject or session credential. A provider-neutral task-local invocation scope reaches synchronous application calls through the threadpool; Audit resolves that trusted scope for changes and bulk summaries. It is reset after the invocation and does not replace source-owned eligibility, revisions, idempotency or transaction checks. Local invocations retain their existing actor behavior. Replaying a receipt does not replace its original audit attribution. Current-baseline constraints and retained-data validation reject malformed hosted references.

Registered contextual snapshot and global activity policies differ. Contextual history explains permitted prior values; global activity must not leak raw evidence, credentials, file locators, retained command requests or private notes. Use explicit field allowlists and secret rejection, with policy versions retained for portable history.

## Reads and portability

`/api/audit/events/{entity_type}/{entity_id}` supplies record history and `/events` supplies filtered activity. Correlation joins events from a coordinated operation. Read-only views cannot edit history. Stable event IDs/policies survive encrypted backup and restore.

`SQLiteAuditReadMarker` exposes an opaque append marker inside a caller's snapshot for bounded view invalidation. It is not an event timestamp or business revision. Combine it with runtime epoch and normalized filters for cursor validation; do not use maximum occurred-at time as a monotonic marker.

The local database/file owner can modify files outside the app; append-only controls and retained validation protect ordinary application behavior, rather than claiming regulatory tamper-proof storage.

## Implementation map

- [Domain values and invariants](../../application/apps/server/app/modules/audit/domain).
- [Use cases and application ports](../../application/apps/server/app/modules/audit/application).
- [HTTP contracts](../../application/apps/server/app/modules/audit/api).
- [Persistence and source adapters](../../application/apps/server/app/modules/audit/infrastructure).

## Validation

The following executable specifications are the starting point for focused validation. This documentation consolidation did not rerun them or establish feature completion.

- [test_audit.py](../../application/apps/server/app/modules/audit/tests/test_audit.py).

Use the [shared validation matrix](../platform/persistence.md#validation-matrix) when changing this boundary. Core browser acceptance is recorded in [browser validation](../ui/validation.md); later capability acceptance remains in [active work](../active/README.md).
