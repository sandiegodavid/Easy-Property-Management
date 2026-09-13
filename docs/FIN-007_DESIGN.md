# FIN-007 — Prepaid Checks

## Purpose

`FIN-007` records a future-dated physical check that the operator has received for one complete `FIN-001` rent-expectation period. It makes the check actionable when its date arrives without treating the check as received rent, income, or a FIN-001 receipt before the operator confirms deposit.

The MVP is US-only: checks and their source expectations use USD, and every date rule uses the lease property's stored US IANA time zone.

## Scope and boundaries

FIN-007 owns a check's scheduled, deposited, returned, voided, and replaced lifecycle; its safe masked check reference; its reminder; and its atomic handoff to FIN-001 when deposited.

It does not scan, store, or attach a check image; validate a bank account; initiate a deposit; reconcile a bank feed; create an expected payment method; or accept a check that covers a partial or multiple expectation periods. `FILE-001` is not used for physical-check evidence in this slice. `FIN-006` owns only the immutable `check` payment-method snapshot on the FIN-001 receipt.

A `scheduled` check has a derived deposit eligibility rather than a time-driven database mutation:

| Derived eligibility | Rule |
| --- | --- |
| `not_yet_eligible` | The property's local current date is before `checkDatedOn`. |
| `eligible` | The property's local current date is on or after `checkDatedOn` and the check remains scheduled. |
| `not_applicable` | The check is no longer scheduled. |

This lets UI-001 show a deposit queue without a background job silently changing financial state.

## Core rules

### One check, one expectation, one active lifecycle

A prepaid check belongs to exactly one active `rent_expectation`. Its `amountMinor` and `currencyCode` must exactly equal that expectation's immutable amount and USD currency, and its coverage is the expectation's complete inclusive period. One check never spans, combines, or partially covers periods. A second scheduled check for the same expectation is rejected unless it is an explicit replacement for a returned or voided predecessor.

The `payerPartyId` must be an active participant of the expectation's lease at creation and is retained as an immutable snapshot reference. Third-party payer selection is deferred. The service validates the participant and the expectation through transaction-aware owning-module ports in the same immediate transaction; it does not import lease or party persistence.

`receivedOn` is the property-local day the operator took custody of the physical check. `checkDatedOn` is the printed date and must be strictly after `receivedOn`. This is the MVP's future-dated rule. Both dates must be valid US-local calendar dates and `receivedOn` cannot be after the local current date.

The stored reference uses FIN-006's safe masked-reference grammar. FIN-007 never persists a raw check number, routing number, account number, bank name, image, or free-text financial credential.

### Lifecycle and corrections

| State | Allowed next action | Rule |
| --- | --- | --- |
| `scheduled` | deposit, void, replace | Deposit is permitted only when eligibility is `eligible`. Void and replacement require a bounded operator reason. |
| `deposited` | return | Deposit is an immutable handoff; it is not edited or voided directly. |
| `returned` | replace | Returning the check voids its linked FIN-001 receipt in the same transaction. |
| `voided` | replace | A voided check never creates or voids income because it was never deposited. |
| `replaced` | none | A predecessor is immutable history. |

Replacement creates a new scheduled check and records a one-way `replacesPrepaidCheckId` relationship. The predecessor moves to `replaced`; a check has at most one replacement. The replacement must target the same expectation and payer and obey the original check-date rules. Branching, cycles, and replacing a deposited check are rejected with `409`.

Returning a deposited check requires `returnedOn`, which is no later than the property-local current date, and a bounded return reason. The service atomically changes the check to `returned`, voids the linked FIN-001 receipt with a FIN-007-specific reason, preserves the receipt/allocation history, dismisses any pending reminder, and appends correlated audit events. A receipt that has been independently voided cannot be silently returned again; the operator receives a lifecycle conflict.

### Deposit handoff to FIN-001

Deposit is one immediate transaction and one correlation ID across FIN-007, FIN-001, TASK-001, and AUDIT-001:

1. Re-read the scheduled check, expectation, lease, payer, and property-local date inside the transaction.
2. Confirm that the check is eligible, the expectation is active, and its exact amount is still open.
3. Create one new FIN-001 receipt, or select one explicitly supplied compatible receipt. A compatible existing receipt is active, belongs to the same lease, has USD amount equal to the check amount, uses the FIN-006 `check` method snapshot, and has exactly one full allocation to this expectation. It must not already be linked to another prepaid check.
4. When creating a receipt, FIN-007 uses a finance-owned internal handoff command and a durable operation idempotency record. It does not bypass FIN-001's likely-duplicate protection: a likely duplicate returns a typed conflict with bounded candidate identifiers for operator resolution.
5. Allocate the full check amount to the one expectation, link the check to the receipt, set `depositedOn`, dismiss the pending reminder, and append all domain audit events.

The receipt's FIN-006 method kind is `check`. FIN-007 retains the masked check reference, so the receipt does not duplicate check-specific lifecycle data. A scheduled or eligible check creates neither a receipt nor income. A returned check reverses its linked receipt through FIN-001's void workflow; it never erases the financial record.

### Idempotency, conflicts, and audit

Every create, deposit, return, void, and replace command carries a client-generated UUID `idempotencyKey`. FIN-007 persists a Finance-owned immutable operation record containing the action, target aggregate, canonical request fingerprint, result identifiers, and correlation ID. A retry with the same semantic payload returns the original result without new rows or events; a changed payload returns typed `409`. The audit ledger is evidence, never the idempotency source of truth.

All successful writes are fail-closed on their required audit event. Global activity redacts amount, payer, masked reference, reasons, idempotency keys, receipt IDs, and task IDs. Contextual prepaid-check history can display the permitted masked reference and operator reasons. No raw check data may appear in an audit reason.

## Data model and integrity

The greenfield baseline adds Finance-owned `prepaid_checks` and `prepaid_check_operations` tables. `prepaid_checks` stores the stable identifiers and immutable check facts (`rent_expectation_id`, lease/property context snapshots as needed for bounded reads, `payer_party_id`, `received_on`, `check_dated_on`, amount, currency, masked reference), lifecycle timestamps/reasons, linked receipt, replacement lineage, and reminder task ID. `prepaid_check_operations` provides idempotency independent of the audit table.

The database, SQLAlchemy metadata, Alembic baseline, exact schema validator, and FIN-007 data validator enforce the current contract, including:

- positive USD amount and a safe masked-reference shape;
- `check_dated_on > received_on` and bounded valid dates;
- one scheduled check per expectation and one linked receipt per deposited check;
- exhaustive state/nullability pairs for deposit, return, void, and replacement fields;
- same-expectation, nonbranching replacement lineage, with cycle detection during latest-format validation;
- operation-key uniqueness and immutable request-fingerprint matching; and
- foreign-key integrity, including `PRAGMA foreign_key_check` during product validation.

Unexpected tables, weakened constraints, malformed lifecycle rows, invalid references, or check/receipt/expectation inconsistencies reject workspace open, backup, and restore. Existing archived facts remain readable even when their lease later changes lifecycle; those later changes surface as warnings rather than rewriting history.

## TASK-001 reminder

Creating a check atomically creates one all-day TASK-001 reminder due on `checkDatedOn` in the property's local time zone. The task is linked to the prepaid check through a typed FIN-007 entity reference and has a concise non-sensitive title. It is an operator reminder, not a financial state transition.

If the operator independently completes or dismisses the task while the check remains scheduled, FIN-007 respects that acknowledgement and does not recreate it. A deposit, return, void, or replacement dismisses a still-pending reminder in the same transaction. Task creation, lifecycle changes, and audit events share the check operation correlation ID.

## API and typed contracts

The backend provides:

- `POST /api/prepaid-checks` to create a scheduled check;
- `GET /api/prepaid-checks` with bounded cursor pagination and filters for lease, property, space, payer, expectation, lifecycle state, and derived eligibility;
- `GET /api/prepaid-checks/{prepaidCheckId}`;
- `POST /api/prepaid-checks/{prepaidCheckId}/deposit`;
- `POST /api/prepaid-checks/{prepaidCheckId}/return`;
- `POST /api/prepaid-checks/{prepaidCheckId}/void`; and
- `POST /api/prepaid-checks/{prepaidCheckId}/replace`.

All payloads forbid unknown fields, use strict booleans for destructive confirmations, and require UUID idempotency keys. Responses include the immutable check facts, lifecycle, derived eligibility, expectation period summary, linked receipt summary when present, and reminder status. They never expose raw check or bank information.

Malformed data returns `422`; missing records return `404`; lifecycle, duplicate, stale, idempotency, schedule, and concurrent conflicts return typed `409`; an oversized page returns `422`; and a missing required confirmation returns `422`. Errors carry stable machine-readable codes rather than requiring UI-001 to parse prose.

## UI-001 scope

`UI-001` delivers the deferred operator workflow before `DASH-001`:

- a prepaid-check queue grouped by not-yet-eligible and eligible checks;
- create, deposit, return, void, and replacement actions with explicit confirmations;
- expectation-period, payer, receipt, and reminder context;
- duplicate-conflict resolution without automatic income creation; and
- FIN-006 receipt-method suggestion/prefill alongside the related FIN-001 receipt workflow.

The UI may present a local-day eligibility cue and task acknowledgement, but cannot mutate a check merely by viewing it.

## Dependencies, portability, and acceptance criteria

FIN-007 directly requires `AUDIT-001`, `TASK-001`, `FIN-001`, and `FIN-006`; it inherits the executed-lease, participant, property, and US time-zone boundaries through FIN-001's transaction-aware ports. It has no direct persistence dependency on lease, portfolio, party, task, or audit adapters.

Implementation extends the current greenfield Alembic baseline, product schema/data validator, archive manifest validation, encrypted backup/restore coverage, OpenAPI contract, and architecture documentation. It adds no migration, adoption, or compatibility path.

Acceptance coverage includes complete-period enforcement; local-date eligibility; active participant validation; deposit receipt/allocation correlation; duplicate and idempotency conflicts; return/receipt-void atomicity; replacement lineage; reminder lifecycle; global/contextual audit privacy; malformed-schema/data rejection; and encrypted backup/restore of check, operation, receipt link, task link, and correlated audit history.
