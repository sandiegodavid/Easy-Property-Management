# DATA-002 — Spreadsheet Intake Design

## Purpose

`DATA-002` imports properties, owners, providers, and explicit property-owner relationships from a local Excel snapshot. It is a review-first create/link/skip capability, not a general migration, spreadsheet synchronization, or overwrite tool.

## Scope and boundaries

- Supported entities: property, owner (shared Party identity), provider (shared Party identity/profile), and explicit property-owner relationships.
- Leases, balances, financial history, operational history, bulk updates, overwrite/merge behavior, macros, and formula-as-instruction behavior are out of scope and remain DATA-001 or source-domain work.
- Files are accepted through FILE-001, parsed in a bounded worker/service boundary, and never executed.

## Import lifecycle

1. Upload an Excel file and select a worksheet.
2. Capture an immutable reviewed snapshot: workbook file ID/content digest, sheet name, header row, normalized cell values, parser version, and row numbers.
3. Map source columns to an entity template. Required mappings and property-owner relationship keys are explicit.
4. Validate values, relationship references, duplicate candidates, and intended operation per row.
5. Review all proposed creates, explicit links, and skips. Ambiguous identity or relationship matches block affected rows.
6. Confirm the reviewed snapshot using its revision/digest. Commit eligible rows in a coordinated, resumable batch.
7. Return a durable row-level outcome report; retry only incomplete/failed rows using the original batch idempotency key.

Import owner identity records before dependent property-owner relationships. Linking reuses a selected existing record solely to satisfy the stated relationship; it never changes that record's fields. Unknown optional values remain unknown; required fields are never invented.

## Persistence and audit

Persist `import_batches`, `import_snapshots`, `import_row_decisions`, and `import_row_outcomes` with stable IDs, source digest, mapping version, actor/time, validation revision, and source row number. Outcomes are `created`, `linked`, `skipped`, `failed`, or `blocked`, with machine-readable reason codes and operator-facing explanation. Preserve enough normalized source evidence to explain a result without retaining arbitrary executable workbook content outside FILE-001 retention.

Each created/link decision and batch transition produces AUDIT-001 events. The batch state machine is `draft → validated → awaiting_confirmation → committing → completed|partially_completed|failed`; retries never repeat successful writes.

## APIs and UI handoff

Provide typed endpoints for source upload/select, snapshot preview, mapping/validation, decisions, confirmation, status, and result download/read. Responses include `asOf`, snapshot revision/digest, complete counts by outcome, bounded row cursors, and availability/error status. The UI entry points are the Properties, Owners, and Providers directories plus Settings → Import data; UI-001 renders the shared flow but owns no import policy.

## Security and verification

Reject unsupported/encrypted/corrupt files with actionable errors, enforce file/row/column bounds, never execute macros, never trust formula text as an instruction, and keep file paths and local secrets out of responses. Test missing requirements, duplicate/ambiguous matches, relationship ordering, link/skip immutability, partial commit/retry, lost response idempotency, row provenance, and source snapshot stability. DATA-002 is complete when no valid import can silently merge or overwrite an existing record.
