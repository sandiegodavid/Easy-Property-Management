"""Category-owned concurrency and immutable command receipts."""

import json
from dataclasses import dataclass
from uuid import uuid4

from app.modules.vendors.application.commands import canonical, fingerprint, identifier
from app.modules.vendors.application.errors import (
    ProviderError,
    ProviderLifecycleConflict,
    ProviderNotFoundError,
)


@dataclass(frozen=True)
class CategoryCommand:
    action: str
    category_id: str | None
    expected_revision: int
    idempotency_key: str
    payload: dict

    def __post_init__(self):
        if self.action not in {"create", "patch", "archive", "restore"}:
            raise ProviderError("Unsupported category command.")
        if type(self.expected_revision) is not int or (
            self.expected_revision != 0 if self.action == "create" else self.expected_revision < 1
        ):
            raise ProviderError(
                "Category revision must be zero for creation or a positive integer."
            )
        identifier(self.idempotency_key)
        if self.action == "create":
            if self.category_id is not None:
                raise ProviderError("Category creation cannot select an existing ID.")
        else:
            identifier(self.category_id)

    def request(self):
        return {
            "action": self.action,
            "categoryId": self.category_id,
            "expectedRevision": self.expected_revision,
            "payload": self.payload,
        }


def start_category(tx, command):
    previous = tx.category_operation_by_key(command.idempotency_key)
    if previous:
        if previous["request_fingerprint"] != fingerprint(command.request()):
            raise ProviderLifecycleConflict(
                "Category key was used for another command.",
                code="provider_category_idempotency_conflict",
            )
        return json.loads(previous["result_json"])
    if command.category_id is not None:
        current = tx.category(command.category_id)
        if current is None:
            raise ProviderNotFoundError("Provider category was not found.")
        check_category_revision(current, command.expected_revision)
    return None


def check_category_revision(category, expected_revision):
    if type(expected_revision) is not int or expected_revision < 1:
        raise ProviderError("expectedCategoryRevision must be a positive integer.")
    if category.revision != expected_revision:
        raise ProviderLifecycleConflict(
            "Category revision has changed.",
            code="provider_category_revision_conflict",
            current=category.to_dict(),
        )


def category_receipt_audit(row):
    return {
        "id": row["id"],
        "categoryId": row["category_id"],
        "action": row["action"],
        "expectedRevision": row["expected_revision"],
        "revision": row["resulting_revision"],
    }


def finish_category(tx, command, category, now, correlation):
    operation_id = str(uuid4())
    count = tx.effective_assignment_counts([category.id]).get(category.id, 0)
    result = {
        "category": {**category.to_dict(), "effectiveProviderCount": count},
        "revision": category.revision,
        "operationId": operation_id,
    }
    row = {
        "id": operation_id,
        "category_id": category.id,
        "action": command.action,
        "idempotency_key": command.idempotency_key,
        "request_json": canonical(command.request()),
        "request_fingerprint": fingerprint(command.request()),
        "expected_revision": command.expected_revision,
        "resulting_revision": category.revision,
        "result_json": canonical(result),
        "correlation_id": correlation,
        "created_at": now,
    }
    tx.insert_category_operation(row)
    tx.record_change(
        entity_type="provider_category_command_operation",
        entity_id=operation_id,
        action="recorded",
        before=None,
        after=category_receipt_audit(row),
        reason="provider_category_command_recorded",
        correlation_id=correlation,
    )
    return result
