"""Transaction-aware scoped LateFeeReadPort adapter for Operator, Tenant, and Owner views."""

from __future__ import annotations

from datetime import UTC, date, datetime
from json import loads
from typing import Any

from sqlalchemy import and_, func, or_, select

from app.modules.finance.application.commands import canonical_uuid
from app.modules.finance.application.late_fee_ports import LateFeeReadScope
from app.modules.finance.domain.late_fee_models import (
    LateFeeAssessment,
    LateFeeWaiver,
    derive_assessment_settlement_status,
)
from app.modules.finance.domain.models import FinanceValidationError
from app.modules.finance.infrastructure.sqlalchemy_models import (
    LateFeeAssessmentModel,
    LateFeeReceiptAllocationModel,
    LateFeeReceiptModel,
    LateFeeWaiverModel,
    RentReceiptAllocationModel,
    RentReceiptModel,
)

VALID_READ_SCOPES = frozenset({"operator", "tenant", "owner"})


def _validate_scope(scope: str) -> LateFeeReadScope:
    if scope not in VALID_READ_SCOPES:
        raise FinanceValidationError("Late-fee read scope must be operator, tenant, or owner.")
    return scope  # type: ignore[return-value]


def _validate_as_of(as_of: datetime) -> str:
    if not isinstance(as_of, datetime) or as_of.tzinfo is None or as_of.utcoffset() is None:
        raise FinanceValidationError("as_of must be a timezone-aware datetime.")
    return as_of.astimezone(UTC).isoformat()


class SQLiteLateFeeReadAdapter:
    """Projects immutable assessed late fees using one source of truth across all portals."""

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
    ) -> dict[str, object]:
        lease_id = canonical_uuid(lease_id)
        scope = _validate_scope(scope)
        captured_as_of = _validate_as_of(as_of)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise FinanceValidationError("Limit must be between 1 and 100.")
        # Tenant and Owner portals never see voided operator corrections or unassessed previews.
        effective_include_voided = bool(include_voided) if scope == "operator" else False
        cursor_key = None
        if cursor is not None:
            if not isinstance(cursor, str) or "|" not in cursor:
                raise FinanceValidationError("Assessment cursor is invalid.")
            day_str, id_str = cursor.split("|", 1)
            try:
                cursor_key = (date.fromisoformat(day_str).isoformat(), canonical_uuid(id_str))
            except (TypeError, ValueError) as error:
                raise FinanceValidationError("Assessment cursor is invalid.") from error

        query = LateFeeAssessmentModel.__table__.select().where(
            LateFeeAssessmentModel.lease_id == lease_id
        )
        if not effective_include_voided:
            query = query.where(LateFeeAssessmentModel.voided_at.is_(None))
        if cursor_key is not None:
            query = query.where(
                or_(
                    LateFeeAssessmentModel.as_of_date < cursor_key[0],
                    and_(
                        LateFeeAssessmentModel.as_of_date == cursor_key[0],
                        LateFeeAssessmentModel.id < cursor_key[1],
                    ),
                )
            )
        rows = (
            connection.execute(
                query.order_by(
                    LateFeeAssessmentModel.as_of_date.desc(), LateFeeAssessmentModel.id.desc()
                ).limit(limit + 1)
            )
            .mappings()
            .all()
        )
        has_more = len(rows) > limit
        assessments = [LateFeeAssessment(**dict(row)) for row in rows[:limit]]
        if not assessments:
            return {
                "leaseId": lease_id,
                "scope": scope,
                "asOf": captured_as_of,
                "items": [],
                "nextCursor": None,
            }

        projected = self._hydrate_and_project(connection, assessments, scope=scope)
        next_cursor = f"{assessments[-1].as_of_date}|{assessments[-1].id}" if has_more else None
        return {
            "leaseId": lease_id,
            "scope": scope,
            "asOf": captured_as_of,
            "items": projected,
            "nextCursor": next_cursor,
        }

    def get_assessed_late_fee(
        self,
        connection: Any,
        *,
        assessment_id: str,
        scope: LateFeeReadScope,
        as_of: datetime,
    ) -> dict[str, object] | None:
        assessment_id = canonical_uuid(assessment_id)
        scope = _validate_scope(scope)
        _validate_as_of(as_of)
        row = (
            connection.execute(
                LateFeeAssessmentModel.__table__.select().where(
                    LateFeeAssessmentModel.id == assessment_id
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        assessment = LateFeeAssessment(**dict(row))
        if scope != "operator" and assessment.voided_at is not None:
            return None
        return self._hydrate_and_project(connection, [assessment], scope=scope)[0]

    def _hydrate_and_project(
        self,
        connection: Any,
        assessments: list[LateFeeAssessment],
        *,
        scope: LateFeeReadScope,
    ) -> list[dict[str, object]]:
        ids = [item.id for item in assessments]
        waivers_by_id: dict[str, list[LateFeeWaiver]] = {}
        for row in (
            connection.execute(
                LateFeeWaiverModel.__table__.select()
                .where(LateFeeWaiverModel.assessment_id.in_(ids))
                .order_by(LateFeeWaiverModel.waived_at, LateFeeWaiverModel.id)
            )
            .mappings()
            .all()
        ):
            waiver = LateFeeWaiver(**dict(row))
            waivers_by_id.setdefault(waiver.assessment_id, []).append(waiver)

        allocs_by_id: dict[str, list[dict[str, object]]] = {}
        for row in (
            connection.execute(
                select(
                    LateFeeReceiptAllocationModel.id.label("allocationId"),
                    LateFeeReceiptAllocationModel.assessment_id.label("assessmentId"),
                    LateFeeReceiptAllocationModel.receipt_id.label("receiptId"),
                    LateFeeReceiptModel.received_on.label("receivedOn"),
                    LateFeeReceiptAllocationModel.amount_minor.label("amountMinor"),
                    LateFeeReceiptModel.voided_at.label("voidedAt"),
                )
                .join(
                    LateFeeReceiptModel,
                    LateFeeReceiptModel.id == LateFeeReceiptAllocationModel.receipt_id,
                )
                .where(LateFeeReceiptAllocationModel.assessment_id.in_(ids))
                .order_by(LateFeeReceiptModel.received_on, LateFeeReceiptAllocationModel.id)
            )
            .mappings()
            .all()
        ):
            allocs_by_id.setdefault(row["assessmentId"], []).append(
                {
                    "allocationId": row["allocationId"],
                    "receiptId": row["receiptId"],
                    "receivedOn": row["receivedOn"],
                    "amountMinor": int(row["amountMinor"]),
                    "receiptLifecycleStatus": "voided" if row["voidedAt"] is not None else "active",
                }
            )

        replaced_by: dict[str, str] = {}
        drift_allocs: dict[str, list[tuple[str, int]]] = {}
        if scope == "operator":
            for old_id, new_id in connection.execute(
                select(
                    LateFeeAssessmentModel.replaces_assessment_id,
                    LateFeeAssessmentModel.id,
                ).where(LateFeeAssessmentModel.replaces_assessment_id.in_(ids))
            ).all():
                if old_id is not None:
                    replaced_by[old_id] = new_id
            active = [item for item in assessments if item.voided_at is None]
            if active:
                max_as_of = max(item.as_of_date for item in active)
                exp_ids = {item.rent_expectation_id for item in active}
                for exp_id, received_on, total in connection.execute(
                    select(
                        RentReceiptAllocationModel.expectation_id,
                        RentReceiptModel.received_on,
                        func.sum(RentReceiptAllocationModel.amount_minor),
                    )
                    .join(
                        RentReceiptModel,
                        RentReceiptModel.id == RentReceiptAllocationModel.receipt_id,
                    )
                    .where(
                        RentReceiptAllocationModel.expectation_id.in_(exp_ids),
                        RentReceiptModel.voided_at.is_(None),
                        RentReceiptModel.received_on <= max_as_of,
                    )
                    .group_by(
                        RentReceiptAllocationModel.expectation_id, RentReceiptModel.received_on
                    )
                ).all():
                    drift_allocs.setdefault(exp_id, []).append((received_on, int(total)))

        results: list[dict[str, object]] = []
        for item in assessments:
            waivers = waivers_by_id.get(item.id, [])
            allocations = allocs_by_id.get(item.id, [])
            active_allocs = [a for a in allocations if a["receiptLifecycleStatus"] == "active"]
            waived_minor = sum(w.waived_amount_minor for w in waivers)
            paid_minor = sum(int(a["amountMinor"]) for a in active_allocs)
            status, remaining = derive_assessment_settlement_status(
                assessed_amount_minor=item.assessed_amount_minor,
                waived_amount_minor=waived_minor,
                paid_amount_minor=paid_minor,
                voided_at=item.voided_at,
            )
            snapshot = loads(item.calculation_snapshot_json)
            shared_base: dict[str, object] = {
                "id": item.id,
                "leaseId": item.lease_id,
                "rentExpectationId": item.rent_expectation_id,
                "occurrenceNumber": item.occurrence_number,
                "asOfDate": item.as_of_date,
                "accrualStartsOn": item.accrual_starts_on,
                "accrualEndsOn": item.accrual_ends_on,
                "accrualDays": item.accrual_days,
                "assessedAmountMinor": item.assessed_amount_minor,
                "waivedAmountMinor": waived_minor,
                "paidAmountMinor": paid_minor,
                "remainingBalanceMinor": remaining,
                "settlementStatus": status,
                "currencyCode": item.currency_code,
                "timeZone": item.time_zone,
                "ruleBasisSnapshot": item.rule_basis_snapshot,
                "calculationSteps": snapshot.get("calculationSteps", []),
                "assessedAt": item.assessed_at,
            }
            if scope == "operator":
                drift = _compute_drift(
                    item, snapshot, drift_allocs.get(item.rent_expectation_id, [])
                )
                results.append(
                    {
                        **shared_base,
                        "policyVersionId": item.policy_version_id,
                        "calculationSnapshotHash": item.calculation_snapshot_hash,
                        "processingAcknowledged": item.processing_acknowledged,
                        "processingAcknowledgmentReason": item.processing_acknowledgment_reason,
                        "internalNotes": item.internal_notes,
                        "replacesAssessmentId": item.replaces_assessment_id,
                        "replacedByAssessmentId": replaced_by.get(item.id),
                        "voidedAt": item.voided_at,
                        "voidReason": item.void_reason,
                        "assessedByActor": item.assessed_by_actor,
                        "sourceDriftWarning": drift,
                        "waivers": [w.to_dict() for w in waivers],
                        "allocations": allocations,
                    }
                )
            elif scope == "tenant":
                results.append(
                    {
                        **shared_base,
                        "waivers": [
                            {
                                "id": w.id,
                                "waivedAmountMinor": w.waived_amount_minor,
                                "currencyCode": w.currency_code,
                                "reason": w.reason,
                                "waivedOn": w.waived_on,
                                "waivedAt": w.waived_at,
                            }
                            for w in waivers
                        ],
                        "appliedFeePaymentTotalMinor": paid_minor,
                        "appliedFeePaymentCount": len(active_allocs),
                    }
                )
            else:  # owner
                results.append(
                    {
                        **shared_base,
                        "waivers": [
                            {
                                "id": w.id,
                                "waivedAmountMinor": w.waived_amount_minor,
                                "currencyCode": w.currency_code,
                                "reason": w.reason,
                                "waivedOn": w.waived_on,
                                "waivedAt": w.waived_at,
                            }
                            for w in waivers
                        ],
                        "collectedFeeTotalMinor": paid_minor,
                        "collectedFeeReceiptCount": len(active_allocs),
                    }
                )
        return results


def _compute_drift(
    assessment: LateFeeAssessment,
    snapshot: dict[str, object],
    current_allocations: list[tuple[str, int]],
) -> bool:
    if assessment.voided_at is not None:
        return False
    grace_ends_on = snapshot.get("graceEndsOn")
    if not isinstance(grace_ends_on, str):
        return False
    through_grace = sum(amt for d, amt in current_allocations if d <= grace_ends_on)
    after_grace = sum(
        amt for d, amt in current_allocations if grace_ends_on < d <= assessment.as_of_date
    )
    return through_grace != snapshot.get("paidThroughGraceMinor", 0) or after_grace != snapshot.get(
        "paidAfterGraceThroughAsOfMinor", 0
    )
