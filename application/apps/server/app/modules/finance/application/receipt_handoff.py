"""Transaction-scoped FIN-001 receipt operations shared by finance workflows."""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.modules.finance.domain.models import (
    FinanceConflictError,
    FinanceError,
    FinanceNotFoundError,
    RecordReceiptCommand,
    RentReceipt,
)


def record_receipt_in_transaction(
    tx,
    command: RecordReceiptCommand,
    *,
    now: Callable[[], datetime],
    correlation_id: str,
    audit_reason: str,
    duplicate_conflict: Callable[[list[RentReceipt]], FinanceConflictError] | None = None,
) -> RentReceipt:
    """Apply the FIN-001 receipt policy without opening a second transaction."""
    if command.received_by_party_id and not tx.party_exists(command.received_by_party_id):
        raise FinanceNotFoundError("Recipient party was not found.")
    duplicates = tx.likely_duplicate_receipts(
        lease_id=command.lease_id,
        received_on=command.received_on,
        amount_minor=command.amount_minor,
        received_by_party_id=command.received_by_party_id,
    )
    if duplicates and not command.duplicate_confirmed:
        if duplicate_conflict is not None:
            raise duplicate_conflict(duplicates)
        raise FinanceConflictError("A matching active receipt already exists; explicit duplicate confirmation is required.")
    if not duplicates and command.duplicate_confirmed:
        raise FinanceConflictError("Duplicate confirmation is not applicable because no matching receipt exists.")

    for allocation in command.allocations:
        expectation = tx.expectation(allocation.expectation_id)
        if expectation is None:
            raise FinanceNotFoundError("Allocated expectation was not found.")
        if expectation.lease_id != command.lease_id or expectation.currency_code != "USD" or expectation.voided_at:
            raise FinanceConflictError("Allocation target is not eligible.")
        if tx.allocated_amount(expectation.id) + allocation.amount_minor > expectation.expected_amount_minor:
            raise FinanceConflictError("Allocation exceeds expected rent.")
    zone = tx.lease_time_zone(command.lease_id)
    if zone is None:
        raise FinanceConflictError("Receipt lease property is unavailable.")
    if date.fromisoformat(command.received_on) > now().astimezone(ZoneInfo(zone)).date():
        raise FinanceError("Received date cannot be in the future.")
    if command.replaces_receipt_id:
        replaced = tx.receipt(command.replaces_receipt_id)
        if not replaced:
            raise FinanceNotFoundError("Replaced receipt was not found.")
        if not replaced.voided_at or replaced.lease_id != command.lease_id or replaced.currency_code != "USD":
            raise FinanceConflictError("Replacement must target a voided receipt on the same lease.")
        if tx.replacement_exists(replaced.id):
            raise FinanceConflictError("A replacement receipt already exists.")

    created_at = now().astimezone(UTC).isoformat()
    receipt = RentReceipt(
        id=str(uuid4()), lease_id=command.lease_id,
        idempotency_key=command.idempotency_key,
        received_on=command.received_on, amount_minor=command.amount_minor,
        currency_code="USD", payment_method_kind=command.payment_method_kind,
        payment_method_label=command.payment_method_label,
        masked_reference=command.masked_reference,
        other_payment_method_note=command.other_payment_method_note,
        received_by_party_id=command.received_by_party_id,
        replaces_receipt_id=command.replaces_receipt_id, notes=command.notes,
        voided_at=None, void_reason=None, created_at=created_at,
    )
    tx.insert_receipt(receipt)
    audit_snapshot = receipt.to_dict()
    if duplicates:
        audit_snapshot = {
            **audit_snapshot,
            "duplicateConfirmed": True,
            "duplicateReason": command.duplicate_reason,
            "duplicateCandidateReceiptIds": [item.id for item in duplicates],
        }
    tx.record_change(
        entity_type="rent_receipt", entity_id=receipt.id, action="recorded",
        before=None, after=audit_snapshot, reason=audit_reason, correlation_id=correlation_id,
    )
    for allocation in command.allocations:
        row = {
            "id": str(uuid4()), "receipt_id": receipt.id,
            "expectation_id": allocation.expectation_id,
            "amount_minor": allocation.amount_minor, "created_at": created_at,
        }
        tx.insert_allocation(row)
        tx.record_change(
            entity_type="rent_receipt_allocation", entity_id=row["id"], action="created",
            before=None,
            after={"id": row["id"], "receiptId": receipt.id, "expectationId": allocation.expectation_id,
                   "amountMinor": allocation.amount_minor, "createdAt": created_at},
            reason=audit_reason, correlation_id=correlation_id,
        )
    return receipt


def void_receipt_in_transaction(tx, receipt: RentReceipt, *, now: Callable[[], datetime], reason: str, correlation_id: str) -> RentReceipt:
    if receipt.voided_at is not None:
        raise FinanceConflictError("Receipt is already voided.")
    updated = RentReceipt(**{**receipt.__dict__, "voided_at": now().astimezone(UTC).isoformat(), "void_reason": reason})
    tx.replace_receipt(updated)
    tx.record_change(
        entity_type="rent_receipt", entity_id=updated.id, action="voided",
        before=receipt.to_dict(), after=updated.to_dict(), reason=None, correlation_id=correlation_id,
    )
    return updated


def compatible_prepaid_receipt(tx, *, receipt_id: str, lease_id: str, expectation_id: str, amount_minor: int) -> RentReceipt:
    receipt = tx.receipt(receipt_id)
    if receipt is None or receipt.voided_at is not None or receipt.lease_id != lease_id or receipt.amount_minor != amount_minor or receipt.currency_code != "USD" or receipt.payment_method_kind != "check" or tx.prepaid_check_by_receipt(receipt.id) is not None:
        raise FinanceConflictError("Selected receipt is not compatible with this prepaid check.")
    allocations = tx.receipt_allocations(receipt.id)
    if len(allocations) != 1 or allocations[0]["expectation_id"] != expectation_id or allocations[0]["amount_minor"] != amount_minor:
        raise FinanceConflictError("Selected receipt must fully allocate this expectation exactly once.")
    return receipt
