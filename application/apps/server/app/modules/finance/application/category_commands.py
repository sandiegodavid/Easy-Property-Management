"""Category-owned concurrency and durable original results for FIN-002."""

from dataclasses import dataclass
from json import loads
from uuid import uuid4

from app.modules.finance.application.commands import canonical_json, canonical_uuid, fingerprint
from app.modules.finance.domain.models import (
    FinanceConflictError,
    FinanceNotFoundError,
    FinanceValidationError,
)


@dataclass(frozen=True)
class ExpenseCategoryCommand:
    action: str
    category_id: str | None
    expected_revision: int
    idempotency_key: str
    payload: dict

    def __post_init__(self):
        if self.action not in {"create", "patch", "archive", "restore"}:
            raise FinanceValidationError("Unsupported expense category command.")
        if type(self.expected_revision) is not int or (
            self.expected_revision != 0 if self.action == "create" else self.expected_revision < 1
        ):
            raise FinanceValidationError(
                "Category revision must be zero for creation or a positive integer."
            )
        canonical_uuid(self.idempotency_key)
        if self.action == "create":
            if self.category_id is not None:
                raise FinanceValidationError("Category creation cannot select an existing ID.")
        else:
            canonical_uuid(self.category_id)

    def request(self):
        return {
            "action": self.action,
            "categoryId": self.category_id,
            "expectedRevision": self.expected_revision,
            "payload": self.payload,
        }


def start_category(tx, command):
    previous = tx.category_operation_by_key(command.idempotency_key)
    if previous is not None:
        if previous["request_fingerprint"] != fingerprint(canonical_json(command.request())):
            raise FinanceConflictError(
                "Category key was used for a different request.",
                code="expense_category_idempotency_conflict",
            )
        return loads(previous["result_json"])
    if command.category_id is not None:
        current = tx.category(command.category_id)
        if current is None:
            raise FinanceNotFoundError("Expense category was not found.")
        if current.revision != command.expected_revision:
            raise FinanceConflictError(
                "Expense category revision has changed.",
                code="expense_category_revision_conflict",
                details={"currentCategory": current.to_dict(), "currentRevision": current.revision},
            )
    return None


def category_receipt_audit(row):
    return {
        "id": row["id"],
        "categoryId": row["category_id"],
        "action": row["action"],
        "expectedRevision": row["expected_revision"],
        "revision": row["resulting_revision"],
    }


def finish_category(tx, command, category, stamp, correlation):
    operation_id = str(uuid4())
    result = {**category.to_dict(), "operationId": operation_id}
    request_json = canonical_json(command.request())
    row = {
        "id": operation_id,
        "category_id": category.id,
        "action": command.action,
        "idempotency_key": command.idempotency_key,
        "request_json": request_json,
        "request_fingerprint": fingerprint(request_json),
        "expected_revision": command.expected_revision,
        "resulting_revision": category.revision,
        "result_json": canonical_json(result),
        "correlation_id": correlation,
        "created_at": stamp,
    }
    tx.insert_category_operation(row)
    tx.record_change(
        entity_type="expense_category_command_operation",
        entity_id=operation_id,
        action="recorded",
        before=None,
        after=category_receipt_audit(row),
        reason="expense_category_command_recorded",
        correlation_id=correlation,
    )
    return result
