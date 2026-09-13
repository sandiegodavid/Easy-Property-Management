# FIN-006 — Recorded Rent-Payment Methods

## Purpose

`FIN-006` makes each recorded `FIN-001` rent receipt easier to understand by recording how the operator confirmed it was paid. It is a descriptive, immutable receipt snapshot—not a payment account, payment instruction, bank integration, or collection workflow.

The US-only MVP supports `automatic_bank_payment`, `bank_transfer`, `check`, `cash`, `online_payment`, and `other`. `other` requires a trimmed 1–200 character operator note explaining the method.

## Scope and boundaries

FIN-006 adds actual payment-method fields directly to the existing `rent_receipts` record and its create, detail, and list contracts. It creates no payment-method table and no expected-method lifecycle. A method belongs to one immutable receipt snapshot; receipt correction remains FIN-001's confirmed void-and-replace workflow.

FIN-006 does not initiate, authorize, verify, reconcile, or schedule payment; store bank, card, routing, account, processor-token, or credential data; create a payment-provider connection; attach documents; or determine whether a tenant has paid. `PAY-001` owns future provider authorization and payment initiation, `FIN-004` owns bank-feed reconciliation, and `FILE-001` remains available only to a later owning workflow.

`automatic_bank_payment` means an externally arranged payment that the operator has confirmed as received. It is neither an instruction to debit an account nor evidence of a live bank connection.

## Receipt method snapshot

Every new rent receipt requires:

| Field | Rule |
| --- | --- |
| `payment_method_kind` | Required closed value: `automatic_bank_payment`, `bank_transfer`, `check`, `cash`, `online_payment`, or `other`. |
| `payment_method_label` | Optional trimmed operator-facing label, 1–100 characters when present, such as `Tenant portal` or `Personal check`. |
| `masked_reference` | Optional 1–80 character safe reference using an optional plain-language ASCII label, followed by at least two `•` or `*` masking characters and at most four final ASCII digits. It must never contain a raw account, routing, card, credential, token, or processor secret. Typical values are `•••• 1234` and `Check •••• 9182`. |
| `other_payment_method_note` | Required trimmed 1–200 character explanation exactly when `payment_method_kind = other`; null for every other kind. |

`cash` normally has no reference. A reference is optional for every kind because an operator may know the method but not a safe masked identifier. The API rejects a raw-looking reference rather than attempting to retain or transform it.

The snapshot is part of the receipt's canonical idempotency payload. Reusing an idempotency key with a changed kind, label, masked reference, or `other` note returns typed `409`; it never returns the old receipt as though the payload matched. Likely-duplicate detection compares active receipts by lease, received-on date, amount, and recipient—deliberately excluding payment method and allocations. If it finds a candidate, the operator must send `duplicateConfirmed: true` and a bounded `duplicateReason`; the confirmation and candidate IDs are retained in the contextual receipt audit event.

`received_by_party_id` continues to mean who received the money. It is independent of the actual payment method and is not a payer, bank, or payment-provider identity.

## Operator convenience without hidden state

There is no server-side default during receipt creation. A direct API caller must supply the required method snapshot. For convenience, `GET /api/leases/{leaseId}/rent-receipts/payment-method-suggestion` returns the full method snapshot from the lease's latest non-voided receipt, ordered by `receivedOn`, then `createdAt`, then ID. It returns `204` when no such receipt exists.

The UI uses that response only to prefill a new receipt form. The operator may replace any suggested value before submission; the suggestion is not an expected method, obligation, or inferred recurring instruction.

## FIN-007 prepaid-check handoff

`FIN-007` is the authoritative design for a future-dated prepaid check, its reminder, and its scheduled/deposited/returned/voided/replaced lifecycle. It does not create income while scheduled. Deposit performs the correlated FIN-001 receipt/allocation handoff, whose immutable method snapshot uses `check`; FIN-007 alone retains the check-specific lifecycle and masked reference. See [FIN-007_DESIGN.md](FIN-007_DESIGN.md).

## API and errors

`POST /api/rent-receipts` requires the method snapshot fields above. `GET /api/rent-receipts` and `GET /api/rent-receipts/{receiptId}` return the same fields. Receipt correction creates a separate replacement snapshot. The suggestion route is read-only and never creates a record.

All request models forbid unknown fields and use typed response models. Malformed method fields return `422`; missing lease or receipt records return `404`; changed idempotency payloads, stale receipt lifecycle, invalid correction order, and concurrent allocation conflicts return typed `409` errors.

## Audit, privacy, and portability

Receipt creation, allocations, voids, replacements, and FIN-007's future check-to-receipt handoff append their audit changes in the same immediate transaction and correlation ID. FIN-006 adds no independent audit entity: method fields are part of the `rent_receipt` snapshot.

General activity redacts method label, masked reference, `other` note, receipt amount, idempotency key, recipient, and correction references. Contextual receipt history can show the complete permitted masked snapshot to the local operator. No event reason may contain those values, and the current receipt snapshot policy must be registered before a write succeeds.

The current greenfield baseline, SQLAlchemy model, exact schema validator, product validator, archive validation, encrypted backup/export/restore, and API/OpenAPI contracts include the new receipt columns. Regression coverage includes direct-command validation, prefill ordering, idempotency mismatch, void/replacement history, privacy presentation, current-schema rejection, and backup/restore. No adoption or compatibility path is added.

## UI-001

`UI-001` adds receipt-method selection and prefill to its FIN-001 **Record receipt** workflow. It shows the last-receipt suggestion as editable form data, enforces the `other` note and safe masked-reference rules, and never presents the feature as automatic payment setup or payment initiation.

## Dependencies and acceptance criteria

FIN-006 requires `AUDIT-001`, `LEASE-001`, `FIN-001`, `LOCAL-001`, and `LOCAL-002`. It remains a Finance-owned extension of immutable FIN-001 receipt facts and uses the existing transaction-aware lease read port; it does not import leasing, parties, or connector persistence.

FIN-006 is complete when every new receipt has a validated immutable actual-method snapshot; prefill is convenient but never hidden state; audit/activity/backup behavior protects masked information; receipt corrections retain their own snapshots; FIN-007 has an authoritative one-check/one-expectation handoff; and UI-001 delivers the operator selection workflow.
