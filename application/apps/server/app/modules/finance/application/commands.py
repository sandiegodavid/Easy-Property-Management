"""Finance-owned identities for recoverable, revision-checked financial commands.

Monetary workflows supply their existing transaction-bound mutation. This module
does not implement allocation, correction, duplicate, or settlement policy.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from json import dumps, loads
from typing import Literal, Protocol, TypedDict
from uuid import UUID, uuid4

from app.modules.finance.domain.models import FinanceConflictError, FinanceValidationError

FinanceScopeKind = Literal["rent_ledger", "expense", "deposit_account"]
SCOPE_REVISION_FIELDS = {
    "rent_ledger": "rentLedgerRevision",
    "expense": "expenseRevision",
    "deposit_account": "depositAccountRevision",
}
SCOPE_ACTIONS = {
    "rent_ledger": frozenset(
        {
            "synchronize_expectations",
            "record_receipt",
            "void_receipt",
            "void_expectation",
            "review_timeliness",
            "create_prepaid_check",
            "deposit_prepaid_check",
            "return_prepaid_check",
            "void_prepaid_check",
            "replace_prepaid_check",
        }
    ),
    "expense": frozenset(
        {"record_expense", "patch_expense", "void_expense", "record_refund", "void_refund"}
    ),
    "deposit_account": frozenset(
        {
            "create_account",
            "record_receipt",
            "void_receipt",
            "create_settlement",
            "patch_settlement",
            "add_deduction",
            "update_deduction",
            "delete_deduction",
            "add_credit",
            "update_credit",
            "delete_credit",
            "add_deduction_source",
            "delete_deduction_source",
            "approve_settlement",
            "record_refund",
            "void_refund",
            "complete_settlement",
            "void_settlement",
        }
    ),
}


def canonical_json(value: object) -> str:
    return dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def fingerprint(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def recovery_request_fingerprint(request_json: str, key: str) -> str:
    """Normalize only server-generated creation identities for pre-dispatch OPS.

    The persisted financial identity remains unchanged. All semantic fields,
    including revision, key in the payload and selected Lease, remain bound.
    """
    request = loads(request_json)
    if request["scopeKind"] == "expense" and request["action"] == "record_expense":
        request.update(scopeId=key, targetId=key)
    elif request["scopeKind"] == "deposit_account" and request["action"] == "create_account":
        request["scopeId"] = key
    return fingerprint(canonical_json(request))


def canonical_uuid(value: str) -> str:
    try:
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError
    except (ValueError, TypeError, AttributeError) as error:
        raise FinanceValidationError(
            "Financial command identities must be canonical UUIDs."
        ) from error
    return value


def validate_command_concurrency(expected_revision: int, idempotency_key: str) -> None:
    if type(expected_revision) is not int or expected_revision < 0:
        raise FinanceValidationError("Expected financial revision must be a non-negative integer.")
    canonical_uuid(idempotency_key)


@dataclass(frozen=True)
class FinanceScope:
    kind: FinanceScopeKind
    id: str

    def __post_init__(self):
        if self.kind not in SCOPE_ACTIONS:
            raise FinanceValidationError("Unknown financial revision scope.")
        canonical_uuid(self.id)


@dataclass(frozen=True, init=False)
class FinanceCommandIdentity:
    """Freeze the full semantic request, including the selected revision and target.

    Keys are globally scoped within Finance, not scoped to a row or workflow.
    Callers must retain the same revision on retry; later source changes do not
    invalidate an exact replay. Existing creation keys remain the command keys.
    """

    scope: FinanceScope
    action: str
    target_id: str
    expected_revision: int
    idempotency_key: str
    request_json: str

    def __init__(
        self,
        scope: FinanceScope,
        action: str,
        target_id: str,
        expected_revision: int,
        idempotency_key: str,
        payload: Mapping[str, object],
    ):
        validate_command_concurrency(expected_revision, idempotency_key)
        if action not in SCOPE_ACTIONS[scope.kind]:
            raise FinanceValidationError("Financial action does not belong to this revision scope.")
        canonical_uuid(target_id)
        if not isinstance(payload, Mapping) or any(not isinstance(key, str) for key in payload):
            raise FinanceValidationError("A financial command payload must be an object.")
        try:
            request = canonical_json(
                {
                    "scopeKind": scope.kind,
                    "scopeId": scope.id,
                    "action": action,
                    "targetId": target_id,
                    "expectedRevision": expected_revision,
                    "payload": dict(payload),
                }
            )
        except (TypeError, ValueError) as error:
            raise FinanceValidationError(
                "Financial command payload must be finite JSON."
            ) from error
        for name, value in (
            ("scope", scope),
            ("action", action),
            ("target_id", target_id),
            ("expected_revision", expected_revision),
            ("idempotency_key", idempotency_key),
            ("request_json", request),
        ):
            object.__setattr__(self, name, value)


@dataclass(frozen=True)
class FinanceCommandContext:
    operation_id: str
    correlation_id: str
    committed_at: str


@dataclass(frozen=True)
class FinanceCommandOutcome:
    representation: dict[str, object]
    effective: bool

    def __post_init__(self):
        if type(self.effective) is not bool or not isinstance(self.representation, dict):
            raise FinanceValidationError("A financial mutation must declare its result and effect.")


class FinanceCommandReceipt(TypedDict):
    id: str
    scope_kind: str
    scope_id: str
    idempotency_key: str
    action: str
    target_id: str
    expected_revision: int
    result_revision: int
    effective: int
    request_json: str
    request_fingerprint: str
    response_json: str
    response_fingerprint: str
    correlation_id: str
    created_at: str


def receipt_audit(receipt: FinanceCommandReceipt) -> dict[str, object]:
    return {
        key: value for key, value in receipt.items() if key not in {"request_json", "response_json"}
    }


class FinanceCommandTransaction(Protocol):
    """All operations use the caller's already-open write transaction."""

    def command_operation(self, key: str) -> FinanceCommandReceipt | None: ...
    def command_revision(self, scope: FinanceScope) -> int: ...
    def command_revisions(self, scopes: list[FinanceScope]) -> dict[FinanceScope, int]: ...
    def store_command(self, receipt: FinanceCommandReceipt) -> None: ...


def apply_finance_command(
    transaction: FinanceCommandTransaction,
    identity: FinanceCommandIdentity,
    mutation: Callable[[FinanceCommandContext], FinanceCommandOutcome],
    *,
    instant: datetime,
    correlation_id: str | None = None,
) -> dict[str, object]:
    """Replay before lifecycle checks; commit result, revision, and audit together.

    The owning workflow opens the transaction and performs its monetary writes in
    `mutation`. No connection, transaction, provider, or keyring is opened here.
    If result serialization, receipt persistence, or auditing fails, the caller's
    unit of work must roll back the *whole* transaction.
    """
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise FinanceValidationError("Financial command time must be timezone-aware.")
    if correlation_id is not None:
        canonical_uuid(correlation_id)
    prior = transaction.command_operation(identity.idempotency_key)
    request_hash = fingerprint(identity.request_json)
    if prior is not None:
        if prior["request_fingerprint"] != request_hash:
            raise FinanceConflictError(
                "Financial command key was reused with a different request.",
                code="finance_idempotency_conflict",
            )
        return loads(prior["response_json"])
    current = transaction.command_revision(identity.scope)
    if current != identity.expected_revision:
        raise FinanceConflictError(
            "Financial revision is stale.",
            code="finance_revision_conflict",
            details={
                "scopeKind": identity.scope.kind,
                "scopeId": identity.scope.id,
                "currentRevision": current,
            },
        )
    context = FinanceCommandContext(
        str(uuid4()), correlation_id or str(uuid4()), instant.astimezone(UTC).isoformat()
    )
    outcome = mutation(context)
    revision = current + int(outcome.effective)
    response = {
        **outcome.representation,
        SCOPE_REVISION_FIELDS[identity.scope.kind]: revision,
        "operationId": context.operation_id,
    }
    try:
        response_json = canonical_json(response)
    except (ValueError, TypeError) as error:
        raise FinanceValidationError("Financial result must be finite JSON.") from error
    transaction.store_command(
        {
            "id": context.operation_id,
            "scope_kind": identity.scope.kind,
            "scope_id": identity.scope.id,
            "idempotency_key": identity.idempotency_key,
            "action": identity.action,
            "target_id": identity.target_id,
            "expected_revision": current,
            "result_revision": revision,
            "effective": int(outcome.effective),
            "request_json": identity.request_json,
            "request_fingerprint": request_hash,
            "response_json": response_json,
            "response_fingerprint": fingerprint(response_json),
            "correlation_id": context.correlation_id,
            "created_at": context.committed_at,
        }
    )
    return response
