"""FIN-009 application ports (PendingPaymentReader for PAY-001 integration)."""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Protocol

LateFeeReadScope = Literal["operator", "tenant", "owner"]


@dataclass(frozen=True)
class PendingPaymentSummary:
    count: int = 0
    total_minor: int = 0
    earliest_submitted_on: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "count": self.count,
            "totalMinor": self.total_minor,
            "earliestSubmittedOn": self.earliest_submitted_on,
        }


EMPTY_PENDING_PAYMENTS = PendingPaymentSummary()


class PendingPaymentReader(Protocol):
    """Supplies active processing reservation totals on the caller's transaction."""

    def processing_for_expectations(
        self, connection: Any, expectation_ids: Collection[str]
    ) -> dict[str, PendingPaymentSummary]: ...

    def processing_for_assessments(
        self, connection: Any, assessment_ids: Collection[str]
    ) -> dict[str, PendingPaymentSummary]: ...


class NoOpPendingPaymentReader:
    """Default adapter until PAY-001 wires live bank-processing reservations."""

    def processing_for_expectations(
        self, connection: Any, expectation_ids: Collection[str]
    ) -> dict[str, PendingPaymentSummary]:
        return {}

    def processing_for_assessments(
        self, connection: Any, assessment_ids: Collection[str]
    ) -> dict[str, PendingPaymentSummary]:
        return {}


class LateFeeReadPort(Protocol):
    """Transaction-aware scoped read contract shared by Operator, PORTAL-001, and PORTAL-002."""

    def list_assessed_late_fees_for_lease(
        self,
        connection: Any,
        *,
        lease_id: str,
        scope: LateFeeReadScope,
        as_of: datetime,
        include_voided: bool = False,
        cursor: str | None = None,
        limit: int = 50,
    ) -> dict[str, object]: ...

    def get_assessed_late_fee(
        self,
        connection: Any,
        *,
        assessment_id: str,
        scope: LateFeeReadScope,
        as_of: datetime,
    ) -> dict[str, object] | None: ...
