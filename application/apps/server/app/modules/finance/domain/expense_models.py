"""FIN-002 recorded-expense values, commands, and immutable records."""

from __future__ import annotations

import re
import unicodedata
from hashlib import sha256
import json
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from app.modules.finance.domain.models import FinanceError

_AMOUNT = re.compile(r"(?:0|[1-9][0-9]{0,7})\.[0-9]{2}")


def normalized_label(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().casefold()


def category_normalized_name(value: str) -> str:
    result = normalized_label(value)
    if not 1 <= len(result) <= 100:
        raise FinanceError(
            "Normalized category name must be between 1 and 100 characters."
        )
    return result


def text(value: str | None, label: str, limit: int, *, required: bool = False) -> str | None:
    if value is None:
        if required:
            raise FinanceError(f"{label} is required.")
        return None
    if not isinstance(value, str) or not (result := value.strip()) or len(result) > limit:
        raise FinanceError(f"{label} must be between 1 and {limit} characters.")
    return result


def identifier(value: str | None, label: str, *, required: bool = True) -> str | None:
    if value is None and not required:
        return None
    try:
        return str(UUID(value))
    except (TypeError, ValueError, AttributeError) as error:
        raise FinanceError(f"{label} must be a UUID.") from error


def local_date(value: str, label: str) -> str:
    if not isinstance(value, str):
        raise FinanceError(f"{label} must be an ISO date.")
    try:
        result = date.fromisoformat(value)
    except ValueError as error:
        raise FinanceError(f"{label} must be an ISO date.") from error
    if result < date(1900, 1, 1):
        raise FinanceError(f"{label} must be on or after 1900-01-01.")
    return result.isoformat()


def amount_minor(value: str) -> int:
    if not isinstance(value, str) or _AMOUNT.fullmatch(value) is None:
        raise FinanceError("Amount must be a positive decimal string with exactly two fractional digits.")
    result = int(Decimal(value) * 100)
    if result <= 0 or result > 9_999_999_999:
        raise FinanceError("Amount must be between 0.01 and 99999999.99.")
    return result


def amount_text(value: int) -> str:
    return f"{value // 100}.{value % 100:02d}"


@dataclass(frozen=True)
class ExpenseCategory:
    id: str
    display_name: str
    normalized_name: str
    description: str | None
    display_order: int
    archived_at: str | None
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, object]:
        return _camel(asdict(self))


@dataclass(frozen=True)
class Expense:
    id: str
    idempotency_key: str
    request_fingerprint: str
    property_id: str
    space_id: str | None
    category_id: str
    provider_party_id: str | None
    payee_name: str
    paid_by_kind: Literal["local_operator", "party"]
    paid_by_party_id: str | None
    paid_on: str
    amount_minor: int
    currency_code: Literal["USD"]
    description: str
    reference: str | None
    notes: str | None
    replaces_expense_id: str | None
    voided_at: str | None
    void_reason: str | None
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, object]:
        return _camel(asdict(self))


@dataclass(frozen=True)
class ExpenseRefund:
    id: str
    expense_id: str
    idempotency_key: str
    received_on: str
    amount_minor: int
    currency_code: Literal["USD"]
    notes: str | None
    replaces_refund_id: str | None
    voided_at: str | None
    void_reason: str | None
    created_at: str

    def to_dict(self) -> dict[str, object]:
        return _camel(asdict(self))


@dataclass(frozen=True)
class CategoryCreateCommand:
    display_name: str
    description: str | None = None
    display_order: int = 0

    def __post_init__(self) -> None:
        name = text(self.display_name, "Category name", 100, required=True)
        if type(self.display_order) is not int or not 0 <= self.display_order <= 10_000:
            raise FinanceError("Category display order must be an integer from 0 through 10,000.")
        object.__setattr__(self, "display_name", name)
        category_normalized_name(name)
        object.__setattr__(self, "description", text(self.description, "Category description", 1000))


@dataclass(frozen=True)
class CategoryPatchCommand:
    fields: frozenset[str]
    display_name: str | None = None
    description: str | None = None
    display_order: int | None = None

    def __post_init__(self) -> None:
        if not self.fields or not self.fields <= {"display_name", "description", "display_order"}:
            raise FinanceError("At least one valid category field is required.")
        if "display_name" in self.fields:
            object.__setattr__(self, "display_name", text(self.display_name, "Category name", 100, required=True))
            category_normalized_name(self.display_name)
        if "description" in self.fields:
            object.__setattr__(self, "description", text(self.description, "Category description", 1000))
        if "display_order" in self.fields and (type(self.display_order) is not int or not 0 <= self.display_order <= 10_000):
            raise FinanceError("Category display order must be an integer from 0 through 10,000.")


@dataclass(frozen=True)
class ExpenseCreateCommand:
    idempotency_key: str
    property_id: str
    category_id: str
    paid_by_kind: str
    paid_on: str
    amount: str
    currency_code: str
    description: str
    space_id: str | None = None
    provider_party_id: str | None = None
    payee_name: str | None = None
    paid_by_party_id: str | None = None
    reference: str | None = None
    notes: str | None = None
    replaces_expense_id: str | None = None
    duplicate_confirmed: bool = False
    historical_entry_confirmed: bool = False
    historical_entry_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "idempotency_key", identifier(self.idempotency_key, "Idempotency key"))
        object.__setattr__(self, "property_id", identifier(self.property_id, "Property ID"))
        object.__setattr__(self, "category_id", identifier(self.category_id, "Category ID"))
        for field, label in (("space_id", "Space ID"), ("provider_party_id", "Provider party ID"),
                             ("paid_by_party_id", "Payer party ID"), ("replaces_expense_id", "Replacement expense ID")):
            value = getattr(self, field)
            if value is not None:
                object.__setattr__(self, field, identifier(value, label))
        if self.currency_code != "USD":
            raise FinanceError("FIN-002 supports USD expenses only.")
        if self.paid_by_kind not in {"local_operator", "party"}:
            raise FinanceError("Paid-by kind must be local_operator or party.")
        if (self.paid_by_kind == "local_operator") != (self.paid_by_party_id is None):
            raise FinanceError("Paid-by party must be present exactly for party-funded expenses.")
        if (self.provider_party_id is None) == (self.payee_name is None):
            raise FinanceError("Provide exactly one provider or payee name.")
        if type(self.duplicate_confirmed) is not bool or type(self.historical_entry_confirmed) is not bool:
            raise FinanceError("Confirmation values must be boolean.")
        if (self.historical_entry_reason is not None) != self.historical_entry_confirmed:
            raise FinanceError(
                "Historical-entry confirmation and reason must be supplied together."
            )
        object.__setattr__(self, "paid_on", local_date(self.paid_on, "Paid date"))
        amount_minor(self.amount)
        object.__setattr__(self, "payee_name", text(self.payee_name, "Payee name", 200))
        object.__setattr__(self, "description", text(self.description, "Description", 500, required=True))
        object.__setattr__(self, "reference", text(self.reference, "Reference", 200))
        object.__setattr__(self, "notes", text(self.notes, "Notes", 4000))
        object.__setattr__(self, "historical_entry_reason", text(self.historical_entry_reason, "Historical-entry reason", 1000))

    @property
    def amount_minor(self) -> int:
        return amount_minor(self.amount)


@dataclass(frozen=True)
class ExpensePatchCommand:
    fields: frozenset[str]
    category_id: str | None = None
    notes: str | None = None
    category_change_reason: str | None = None
    historical_entry_confirmed: bool = False
    historical_entry_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.fields or not self.fields <= {"category_id", "notes"}:
            raise FinanceError("At least one editable expense field is required.")
        if "category_id" in self.fields:
            object.__setattr__(self, "category_id", identifier(self.category_id, "Category ID"))
            object.__setattr__(self, "category_change_reason", text(self.category_change_reason, "Category-change reason", 1000, required=True))
        elif self.category_change_reason is not None:
            raise FinanceError("A category-change reason requires a category change.")
        if "notes" in self.fields:
            object.__setattr__(self, "notes", text(self.notes, "Notes", 4000))
        if type(self.historical_entry_confirmed) is not bool:
            raise FinanceError("Historical-entry confirmation must be boolean.")
        object.__setattr__(self, "historical_entry_reason", text(self.historical_entry_reason, "Historical-entry reason", 1000))
        if (self.historical_entry_reason is not None) != self.historical_entry_confirmed:
            raise FinanceError(
                "Historical-entry confirmation and reason must be supplied together."
            )
        if self.historical_entry_confirmed and "category_id" not in self.fields:
            raise FinanceError(
                "Historical-entry confirmation requires a category change."
            )


@dataclass(frozen=True)
class RefundCreateCommand:
    idempotency_key: str
    received_on: str
    amount: str
    currency_code: str
    notes: str | None = None
    replaces_refund_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "idempotency_key", identifier(self.idempotency_key, "Idempotency key"))
        object.__setattr__(self, "received_on", local_date(self.received_on, "Refund received date"))
        if self.currency_code != "USD":
            raise FinanceError("FIN-002 supports USD refunds only.")
        amount_minor(self.amount)
        object.__setattr__(self, "notes", text(self.notes, "Refund notes", 4000))
        if self.replaces_refund_id is not None:
            object.__setattr__(self, "replaces_refund_id", identifier(self.replaces_refund_id, "Replacement refund ID"))

    @property
    def amount_minor(self) -> int:
        return amount_minor(self.amount)


@dataclass(frozen=True)
class ExpenseQueryCommand:
    property_id: str | None = None
    space_id: str | None = None
    category_id: str | None = None
    provider_party_id: str | None = None
    paid_by_kind: str | None = None
    paid_by_party_id: str | None = None
    paid_from: str | None = None
    paid_to: str | None = None
    has_evidence: bool | None = None
    include_voided: bool = False
    cursor: str | None = None
    page_size: int = 100

    def __post_init__(self) -> None:
        for field, label in (
            ("property_id", "Property ID"),
            ("space_id", "Space ID"),
            ("category_id", "Category ID"),
            ("provider_party_id", "Provider party ID"),
            ("paid_by_party_id", "Payer party ID"),
        ):
            value = getattr(self, field)
            if value is not None:
                object.__setattr__(self, field, identifier(value, label))
        if self.paid_by_kind not in {None, "local_operator", "party"}:
            raise FinanceError("Paid-by kind filter must be local_operator or party.")
        if self.paid_by_kind == "local_operator" and self.paid_by_party_id is not None:
            raise FinanceError("A local-operator payer filter cannot include a party ID.")
        for field, label in (("paid_from", "Paid-from date"), ("paid_to", "Paid-to date")):
            value = getattr(self, field)
            if value is not None:
                object.__setattr__(self, field, local_date(value, label))
        if self.paid_from is not None and self.paid_to is not None:
            if self.paid_from > self.paid_to:
                raise FinanceError("Paid-from date cannot follow paid-to date.")
        if self.has_evidence is not None and type(self.has_evidence) is not bool:
            raise FinanceError("Evidence filter must be boolean.")
        if type(self.include_voided) is not bool:
            raise FinanceError("Include-voided filter must be boolean.")
        if type(self.page_size) is not int or not 1 <= self.page_size <= 500:
            raise FinanceError("Page size must be from 1 through 500.")
        if self.cursor is not None:
            paid_on, record_id = _expense_cursor(self.cursor)
            object.__setattr__(self, "cursor", f"{paid_on}|{record_id}")

    @property
    def cursor_value(self) -> tuple[str, str] | None:
        if self.cursor is None:
            return None
        paid_on, record_id = self.cursor.split("|", 1)
        return paid_on, record_id

    def filters(self) -> dict[str, object]:
        return {
            "property_id": self.property_id,
            "space_id": self.space_id,
            "category_id": self.category_id,
            "provider_party_id": self.provider_party_id,
            "paid_by_kind": self.paid_by_kind,
            "paid_by_party_id": self.paid_by_party_id,
            "paid_from": self.paid_from,
            "paid_to": self.paid_to,
            "has_evidence": self.has_evidence,
            "include_voided": self.include_voided,
            "cursor": self.cursor_value,
            "limit": self.page_size + 1,
        }


def _expense_cursor(value: str) -> tuple[str, str]:
    if not isinstance(value, str) or "|" not in value:
        raise FinanceError("Expense cursor is invalid.")
    paid_on, record_id = value.split("|", 1)
    canonical_id = identifier(record_id, "Expense cursor ID")
    assert canonical_id is not None
    return (
        local_date(paid_on, "Expense cursor date"),
        canonical_id,
    )


def expense_request_fingerprint(command: ExpenseCreateCommand) -> str:
    """Return the stable Finance-owned semantic identity of an expense request."""
    payload = {
        "idempotencyKey": command.idempotency_key,
        "propertyId": command.property_id,
        "spaceId": command.space_id,
        "categoryId": command.category_id,
        "providerPartyId": command.provider_party_id,
        "payeeName": command.payee_name,
        "paidByKind": command.paid_by_kind,
        "paidByPartyId": command.paid_by_party_id,
        "paidOn": command.paid_on,
        "amountMinor": command.amount_minor,
        "currencyCode": command.currency_code,
        "description": command.description,
        "reference": command.reference,
        "notes": command.notes,
        "replacesExpenseId": command.replaces_expense_id,
        "duplicateConfirmed": command.duplicate_confirmed,
        "historicalEntryConfirmed": command.historical_entry_confirmed,
        "historicalEntryReason": command.historical_entry_reason,
    }
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _camel(values: dict[str, object]) -> dict[str, object]:
    return {
        key.split("_")[0] + "".join(word.title() for word in key.split("_")[1:]): value
        for key, value in values.items()
    }
