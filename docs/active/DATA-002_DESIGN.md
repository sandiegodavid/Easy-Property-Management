# DATA-002 — Spreadsheet Intake Design

## Purpose

`DATA-002` imports properties, owners, providers, and explicit property-owner relationships from a local Excel snapshot. It is a review-first create/link/skip capability, not a general migration, spreadsheet synchronization, or overwrite tool.

## Scope and boundaries

- Supported entities: property, owner (shared Party identity), provider (shared Party identity/profile), and explicit property-owner relationships.
- Provider import may include category values. Each distinct normalized source value requires a reviewed decision to map it to an existing active VEND-CAT-001 category, create a reviewed new category, or skip that value. The import never silently creates or fuzzy-matches a category.
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

For a provider row with reviewed categories, provider identity/profile creation and every selected category assignment commit atomically. An invalid, archived, ambiguous, or failed category decision blocks that provider row; the importer never leaves a newly created provider partially categorized. An operator may explicitly skip every category value and create an Uncategorized provider because VEND-CAT-001 permits zero categories and exposes that coverage state.

## Persistence and audit

Persist `import_batches`, `import_snapshots`, `import_row_decisions`, and `import_row_outcomes` with stable IDs, source digest, mapping version, actor/time, validation revision, and source row number. Outcomes are `created`, `linked`, `skipped`, `failed`, or `blocked`, with machine-readable reason codes and operator-facing explanation. Preserve enough normalized source evidence to explain a result without retaining arbitrary executable workbook content outside FILE-001 retention.

Each created/link decision and batch transition produces AUDIT-001 events. The batch state machine is `draft → validated → awaiting_confirmation → committing → completed|partially_completed|failed`; retries never repeat successful writes.

## APIs and UI handoff

Provide typed endpoints for source upload/select, snapshot preview, mapping/validation, decisions, confirmation, status, and result download/read. Responses include `asOf`, snapshot revision/digest, complete counts by outcome, bounded row cursors, and availability/error status. The UI entry points are the Properties, Owners, and Providers directories plus Settings → Import data; DATA-002 delivers the shared import UI; DATA-003 supplies Sheets acquisition.

## Security and verification

Reject unsupported/encrypted/corrupt files with actionable errors, enforce file/row/column bounds, never execute macros, never trust formula text as an instruction, and keep file paths and local secrets out of responses. Test missing requirements, duplicate/ambiguous matches, relationship ordering, link/skip immutability, partial commit/retry, lost response idempotency, row provenance, and source snapshot stability. DATA-002 is complete when no valid import can silently merge or overwrite an existing record.

## Included operator interface delivery

This UI is part of this functional backlog and its completion criteria. Reuse the delivered UI-001 shell, generated contracts, source-owned commands, Light/Dark themes, keyboard/focus behavior and recovery patterns. Validate real temporary-workspace reads/writes, stale revisions, lost responses, restart/restore and bounded queries; backend-only delivery is incomplete.

#### D43: Import properties, owners, and providers from spreadsheets

Importing properties, owners, and providers from Excel and Google Sheets is a focused follow-up MVP intake capability, separate from DATA-001's broader later import of leases, balances, and operational history. D44 and D45 define source access and existing-record behavior.

Provide Import in each of the three directories and Settings → Import data. The proposed shared flow is Select source, Choose sheet, Map columns, Validate and review, Confirm import, Results. Offer templates with explicit property/owner relationship keys; preview source rows, field mappings, relationships, and intended operations before committing. Import owner identities before dependent property relationships within a coordinated batch. Reuse shared party identity for owners/providers rather than silently duplicating people or organizations.

Never invent required fields, infer ownership shares, or silently merge ambiguous identities. Unknown optional information stays unknown. Rows with missing required values or unresolved relationships cannot be committed as valid records. Use create/link/skip with explicit duplicate review per D45; general overwrite/update imports are outside MVP. Produce a row-level outcome report and recoverable import history; retries must not duplicate successfully imported records. Preview source values as a snapshot and avoid executing spreadsheet macros or treating formulas as app instructions.

#### D45: Create, link, or skip; never silently overwrite

MVP imports create new valid records or explicitly link/skip existing ones after duplicate review. Linking means reusing the selected identity or record to satisfy a relationship; it does not authorize changing its existing fields or merging identities. Conflicting or ambiguous matches require resolution before affected rows can commit. Preserve property-to-owner relationships through explicit mapping. Present row-level validation errors and final import results, including created, linked, skipped, and failed outcomes. Retry only unfinished work without duplicating successful writes. General existing-record overwrite/update behavior is deferred.

Deliver the shared import review at `/imports/:importId/review`, reached from Properties, Owners, Providers and Settings → Import data. Include source/sheet selection, mapping, relationship/category and duplicate resolution, validation, confirmation, progress, row-level outcomes and resumable unfinished-row retries. Show complete totals with bounded pagination; errors preserve mappings and choices. DATA-003 supplies the Sheets acquisition step. Test ambiguous matches, required fields, partial outcomes and duplicate-safe retries.
