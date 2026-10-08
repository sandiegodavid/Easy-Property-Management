"""Maintenance issue aggregate command boundary; uses the caller's transaction."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Literal
from uuid import uuid4

from app.modules.maintenance.domain.models import (
    MaintenanceConflictError,
    MaintenanceError,
    MaintenanceNotFoundError,
    uuid,
)

from .ports import MaintenanceTransaction, MaintenanceUnitOfWork

TargetKind = Literal["issue", "appointment", "cost_context", "expense_link", "quote", "assignment"]


def canonical_payload(value: object) -> str:
    def encode(item):
        if is_dataclass(item):
            return asdict(item)
        raise TypeError(f"Unsupported maintenance command value: {type(item).__name__}")

    return json.dumps(value, default=encode, sort_keys=True, separators=(",", ":"), allow_nan=False)


def command_request(
    *,
    action: str,
    target_kind: TargetKind,
    target_id: str | None,
    payload: Mapping[str, object],
    expected_revision: int,
) -> str:
    """Canonical source request envelope shared with outcome reconciliation."""
    if type(expected_revision) is not int or expected_revision < 0:
        raise MaintenanceError("expectedRevision must be a nonnegative integer.")
    if target_id is not None:
        target_id = uuid(target_id, "targetId")
    return canonical_payload(
        {
            "action": action,
            "targetKind": target_kind,
            "targetId": target_id,
            "expectedRevision": expected_revision,
            "payload": payload,
        }
    )


def command_fingerprint(
    *,
    action: str,
    target_kind: TargetKind,
    target_id: str | None,
    payload: Mapping[str, object],
    expected_revision: int,
) -> str:
    """Issue creation: create_issue/issue/None, {'command': IssueCreate}, revision 0."""
    return sha256(
        command_request(
            action=action,
            target_kind=target_kind,
            target_id=target_id,
            payload=payload,
            expected_revision=expected_revision,
        ).encode()
    ).hexdigest()


def execute_command(
    unit_of_work: MaintenanceUnitOfWork,
    operation: Callable[[MaintenanceTransaction], Mapping[str, object]],
    *,
    action: str,
    target_kind: TargetKind,
    target_id: str | None,
    payload: Mapping[str, object],
    idempotency_key: str,
    expected_revision: int,
    transaction: MaintenanceTransaction | None = None,
) -> dict[str, object]:
    key = uuid(idempotency_key, "idempotencyKey")
    if type(expected_revision) is not int or expected_revision < 0:
        raise MaintenanceError("expectedRevision must be a nonnegative integer.")
    if target_id is not None:
        target_id = uuid(target_id, "targetId")
    request = command_request(
        action=action,
        target_kind=target_kind,
        target_id=target_id,
        payload=payload,
        expected_revision=expected_revision,
    )

    def apply(tx: MaintenanceTransaction):
        prior = tx.command_receipt_by_key(key)
        # This lookup precedes target lookup, revision checks and all live policy.
        if prior is not None:
            if prior["request_payload"] != request:
                current = tx.issue(prior["issue_id"])
                raise MaintenanceConflictError(
                    "Idempotency key payload changed.",
                    "idempotency_conflict",
                    current_revision=current["revision"] if current else None,
                )
            return json.loads(prior["response_payload"])
        issue_id = None
        current_revision = 0
        if target_id is not None:
            getter = getattr(tx, target_kind)
            target = getter(target_id)
            if target is None:
                raise MaintenanceNotFoundError("Maintenance command target was not found.")
            issue_id = target_id if target_kind == "issue" else target["issue_id"]
            issue = tx.issue(issue_id)
            if issue is None:
                raise MaintenanceNotFoundError("Issue was not found.")
            current_revision = issue["revision"]
        if current_revision != expected_revision:
            raise MaintenanceConflictError(
                "Issue revision changed.", "stale_revision", current_revision=current_revision
            )
        operation_id = str(uuid4())
        with tx.command_scope(operation_id):
            try:
                result = dict(operation(tx))
            except MaintenanceConflictError as error:
                error.current_revision = current_revision
                raise
            effective = tx.command_has_changes()
            if issue_id is None:
                issue_id = result["id"]
                revision = 1
            else:
                revision = current_revision + int(effective)
                if effective:
                    tx.advance_issue_revision(issue_id, current_revision)
            result.update(revision=revision, operationId=operation_id)
            response = canonical_payload(result)
            tx.record_change(
                entity_type="maintenance_issue",
                entity_id=issue_id,
                action="command_recorded",
                before=None,
                after={
                    "operationId": operation_id,
                    "commandAction": action,
                    "expectedRevision": expected_revision,
                    "revision": revision,
                    "effective": effective,
                    "requestFingerprint": sha256(request.encode()).hexdigest(),
                    "responseFingerprint": sha256(response.encode()).hexdigest(),
                },
                reason="maintenance_command",
                correlation_id=operation_id,
            )
            tx.insert_command_receipt(
                {
                    "id": operation_id,
                    "idempotency_key": key,
                    "issue_id": issue_id,
                    "action": action,
                    "target_kind": target_kind,
                    "target_id": target_id,
                    "expected_revision": expected_revision,
                    "revision": revision,
                    "effective": int(effective),
                    "request_payload": request,
                    "request_fingerprint": sha256(request.encode()).hexdigest(),
                    "response_payload": response,
                    "response_fingerprint": sha256(response.encode()).hexdigest(),
                    "created_at": datetime.now(UTC).isoformat(),
                }
            )
            return json.loads(response)

    return apply(transaction) if transaction is not None else unit_of_work.write(apply)


def receipt_view(receipt: Mapping[str, object]) -> dict[str, object]:
    return {
        "operationId": receipt["id"],
        "idempotencyKey": receipt["idempotency_key"],
        "issueId": receipt["issue_id"],
        "action": receipt["action"],
        "expectedRevision": receipt["expected_revision"],
        "revision": receipt["revision"],
        "effective": bool(receipt["effective"]),
        "createdAt": receipt["created_at"],
        "request": json.loads(receipt["request_payload"]),
        "response": json.loads(receipt["response_payload"]),
    }
