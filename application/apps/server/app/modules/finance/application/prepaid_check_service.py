"""FIN-007 prepaid-check lifecycle and FIN-001 handoff."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, replace
from datetime import UTC, date, datetime, time
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from app.modules.finance.application.commands import (
    FinanceCommandIdentity,
    FinanceCommandOutcome,
    FinanceScope,
    apply_finance_command,
    validate_command_concurrency,
)
from app.modules.finance.application.ports import FinanceUnitOfWork
from app.modules.finance.application.receipt_handoff import (
    compatible_prepaid_receipt,
    record_receipt_in_transaction,
    void_receipt_in_transaction,
)
from app.modules.finance.domain.models import (
    FinanceConflictError,
    FinanceError,
    FinanceNotFoundError,
    PrepaidCheck,
    PrepaidCheckCommand,
    PrepaidCheckTransitionCommand,
    ReceiptAllocationCommand,
    RecordReceiptCommand,
    RentExpectation,
    RentReceipt,
)


class PrepaidCheckService:
    def __init__(self, unit_of_work: FinanceUnitOfWork, *, now=lambda: datetime.now(UTC)) -> None:
        self.unit_of_work = unit_of_work
        self.now = now

    def create(self, command: PrepaidCheckCommand, *, expected_revision: int) -> dict[str, object]:
        instant = self.now()

        def operation(tx, context):
            self._ensure_unused_operation_key(tx, command.idempotency_key)
            expectation, zone = self._eligible_expectation(
                tx, command, require_open_balance=True, instant=instant
            )
            if any(
                item.expectation_id == expectation.id
                for item in tx.prepaid_checks(lease_id=expectation.lease_id)
            ):
                raise self._conflict(
                    "An expectation with prepaid-check history must use explicit replacement.",
                    "prepaid_check_replacement_required",
                )
            correlation = context.correlation_id
            now = context.committed_at
            item = PrepaidCheck(
                str(uuid4()),
                expectation.id,
                expectation.lease_id,
                command.payer_party_id,
                command.received_on,
                command.check_dated_on,
                expectation.expected_amount_minor,
                "USD",
                command.masked_reference,
                "scheduled",
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                now,
                now,
            )
            tx.insert_prepaid_check(item)
            local_due = (
                datetime.combine(date.fromisoformat(item.check_dated_on), time.min, ZoneInfo(zone))
                .astimezone(UTC)
                .isoformat()
            )
            task_id = tx.create_prepaid_check_reminder(
                check_id=item.id,
                due_at_utc=local_due,
                due_timezone=zone,
                correlation_id=correlation,
                committed_at=context.committed_at,
            )
            item = replace(item, reminder_task_id=task_id, updated_at=context.committed_at)
            tx.replace_prepaid_check(item)
            self._record_operation(
                tx,
                item.id,
                item.id,
                "create",
                command.idempotency_key,
                _fingerprint(command.__dict__),
                correlation,
                context.operation_id,
                context.committed_at,
            )
            tx.record_change(
                entity_type="prepaid_check",
                entity_id=item.id,
                action="created",
                before=None,
                after=item.to_dict(),
                reason="prepaid_check_created",
                correlation_id=correlation,
            )
            return self._view(tx, item, instant)

        return self._command_write(
            operation,
            action="create_prepaid_check",
            target_id=command.expectation_id,
            command=command,
            expected_revision=expected_revision,
            instant=instant,
            extra={},
        )

    def _command_write(
        self, operation, *, action, target_id, command, expected_revision, instant, extra
    ):
        validate_command_concurrency(expected_revision, command.idempotency_key)

        def write(tx):
            prior = tx.commands.command_operation(command.idempotency_key)
            if prior is not None:
                lease_id = prior["scope_id"]
            elif action == "create_prepaid_check":
                expectation = tx.expectation(command.expectation_id)
                if expectation is None:
                    raise FinanceNotFoundError("Rent expectation was not found.")
                lease_id = expectation.lease_id
            else:
                lease_id = self._require(tx, target_id).lease_id
            identity = FinanceCommandIdentity(
                FinanceScope("rent_ledger", lease_id),
                action,
                target_id,
                expected_revision,
                command.idempotency_key,
                {**asdict(command), **extra},
            )
            return apply_finance_command(
                tx.commands,
                identity,
                lambda context: FinanceCommandOutcome(operation(tx, context), True),
                instant=instant,
            )

        return self.unit_of_work.write(write)

    def get(self, check_id: str) -> dict[str, object]:
        def operation(tx):
            item = tx.prepaid_check(check_id)
            if item is None:
                raise FinanceNotFoundError("Prepaid check was not found.")
            return self._view(tx, item)

        return self.unit_of_work.read(operation)

    def list(
        self,
        *,
        lease_id: str | None = None,
        property_id: str | None = None,
        space_id: str | None = None,
        payer_party_id: str | None = None,
        expectation_id: str | None = None,
        status: str | None = None,
        eligibility: str | None = None,
        cursor: str | None = None,
        page_size: int = 100,
    ) -> dict[str, object]:
        if status is not None and status not in {
            "scheduled",
            "deposited",
            "returned",
            "voided",
            "replaced",
        }:
            raise FinanceError("Prepaid-check status is invalid.")
        if eligibility is not None and eligibility not in {
            "not_yet_eligible",
            "eligible",
            "not_applicable",
        }:
            raise FinanceError("Prepaid-check eligibility is invalid.")
        if type(page_size) is not int or not 1 <= page_size <= 500:
            raise FinanceError("Page size must be between 1 and 500.")
        cursor_key = None
        if cursor is not None:
            if not isinstance(cursor, str) or "|" not in cursor:
                raise FinanceError("Prepaid-check cursor is invalid.")
            cursor_parts = cursor.split("|", 1)
            try:
                cursor_key = (
                    date.fromisoformat(cursor_parts[0]).isoformat(),
                    str(UUID(cursor_parts[1])),
                )
            except (TypeError, ValueError, AttributeError) as error:
                raise FinanceError("Prepaid-check cursor is invalid.") from error

        def operation(tx):
            # The adapter applies identity filters, ordering, cursor, and a bounded
            # chunk in SQL.  The two contextual filters and eligibility require the
            # lease-owned local-date projection, so they are evaluated only for the
            # selected chunks rather than for the whole workspace.
            values: list[dict[str, object]] = []
            scan_cursor = cursor_key
            has_more = False
            while len(values) <= page_size:
                rows = tx.prepaid_check_page(
                    lease_id=lease_id,
                    payer_party_id=payer_party_id,
                    expectation_id=expectation_id,
                    status=status,
                    cursor=scan_cursor,
                    limit=page_size + 1,
                )
                if not rows:
                    break
                for record in rows:
                    scan_cursor = (record.check_dated_on, record.id)
                    view = self._view(tx, record)
                    if property_id is not None and view["propertyId"] != property_id:
                        continue
                    if space_id is not None and view["spaceId"] != space_id:
                        continue
                    if eligibility is not None and view["depositEligibility"] != eligibility:
                        continue
                    values.append(view)
                    if len(values) > page_size:
                        has_more = True
                        break
                if len(rows) <= page_size or len(values) > page_size:
                    has_more = has_more or len(rows) > page_size
                    break
            page = values[:page_size]
            next_cursor = None
            if has_more and page:
                next_cursor = f"{page[-1]['checkDatedOn']}|{page[-1]['id']}"
            return {"items": page, "nextCursor": next_cursor}

        return self.unit_of_work.read(operation)

    def deposit(
        self, check_id: str, command: PrepaidCheckTransitionCommand, *, expected_revision: int
    ) -> dict[str, object]:
        instant = self.now()

        def operation(tx, context):
            item = self._require(tx, check_id)
            fingerprint = _fingerprint({"id": check_id, "action": "deposit", **command.__dict__})
            self._ensure_unused_operation_key(tx, command.idempotency_key)
            if item.status != "scheduled":
                raise self._conflict("Only scheduled prepaid checks may be deposited.")
            zone = tx.lease_time_zone(item.lease_id)
            if zone is None or self._eligibility(item, zone, instant) != "eligible":
                raise self._conflict("Prepaid check is not eligible for deposit.")
            if not tx.participant_active(
                item.lease_id, item.payer_party_id, self._today(zone, instant).isoformat()
            ):
                raise self._conflict(
                    "Prepaid-check payer must still be an active lease participant.",
                    "prepaid_check_inactive_payer",
                )
            expectation = tx.expectation(item.expectation_id)
            if expectation is None or expectation.voided_at is not None or expectation.is_prorated:
                raise self._conflict("Prepaid-check expectation is no longer eligible.")
            # A supplied compatible receipt necessarily has one allocation.  Validate it
            # before asking whether the expectation is otherwise open.
            existing_receipt = self._compatible_existing_receipt(
                tx, item, command.existing_receipt_id
            )
            allocated = tx.allocated_amount(item.expectation_id)
            if existing_receipt is None and allocated:
                raise self._conflict("Prepaid-check expectation is no longer open.")
            if existing_receipt is not None and allocated != item.amount_minor:
                raise self._conflict(
                    "Selected receipt does not represent the complete expectation balance."
                )
            deposited_on = command.occurred_on or self._today(zone, instant).isoformat()
            if date.fromisoformat(deposited_on) > self._today(zone, instant):
                raise FinanceError("Deposit date cannot be in the future.")
            if deposited_on < item.check_dated_on:
                raise FinanceError("Deposit date cannot be before the check date.")
            correlation = context.correlation_id
            receipt, _created_receipt = self._select_or_create_receipt(
                tx, item, command, deposited_on, existing_receipt, correlation, instant
            )
            updated = replace(
                item,
                status="deposited",
                receipt_id=receipt.id,
                deposited_on=deposited_on,
                updated_at=context.committed_at,
            )
            tx.replace_prepaid_check(updated)
            tx.dismiss_prepaid_check_reminder(
                updated.reminder_task_id,
                correlation_id=correlation,
                committed_at=context.committed_at,
            )
            self._record_operation(
                tx,
                updated.id,
                updated.id,
                "deposit",
                command.idempotency_key,
                fingerprint,
                correlation,
                context.operation_id,
                context.committed_at,
            )
            tx.record_change(
                entity_type="prepaid_check",
                entity_id=updated.id,
                action="deposited",
                before=item.to_dict(),
                after=updated.to_dict(),
                reason="prepaid_check_deposited",
                correlation_id=correlation,
            )
            return self._view(tx, updated, instant)

        return self._command_write(
            operation,
            action="deposit_prepaid_check",
            target_id=check_id,
            command=command,
            expected_revision=expected_revision,
            instant=instant,
            extra={},
        )

    def return_check(
        self, check_id: str, command: PrepaidCheckTransitionCommand, *, expected_revision: int
    ) -> dict[str, object]:
        if command.reason is None:
            raise FinanceError("A return reason is required.")

        instant = self.now()

        def operation(tx, context):
            item = self._require(tx, check_id)
            fingerprint = _fingerprint({"id": check_id, "action": "return", **command.__dict__})
            self._ensure_unused_operation_key(tx, command.idempotency_key)
            if item.status != "deposited" or item.receipt_id is None:
                raise self._conflict("Only deposited prepaid checks may be returned.")
            receipt = tx.receipt(item.receipt_id)
            if receipt is None or receipt.voided_at is not None:
                raise self._conflict("The linked receipt cannot be returned.")
            zone = tx.lease_time_zone(item.lease_id)
            if zone is None:
                raise FinanceConflictError("Prepaid-check lease context is unavailable.")
            returned_on = command.occurred_on or self._today(zone, instant).isoformat()
            if date.fromisoformat(returned_on) > self._today(zone, instant):
                raise FinanceError("Return date cannot be in the future.")
            if item.deposited_on is None or returned_on < item.deposited_on:
                raise FinanceError("Return date cannot be before the deposit date.")
            correlation = context.correlation_id
            void_receipt_in_transaction(
                tx,
                receipt,
                now=lambda: instant,
                reason="Prepaid check returned: " + command.reason,
                correlation_id=correlation,
            )
            updated = replace(
                item,
                status="returned",
                returned_on=returned_on,
                returned_reason=command.reason,
                updated_at=context.committed_at,
            )
            tx.replace_prepaid_check(updated)
            self._record_operation(
                tx,
                updated.id,
                updated.id,
                "return",
                command.idempotency_key,
                fingerprint,
                correlation,
                context.operation_id,
                context.committed_at,
            )
            tx.record_change(
                entity_type="prepaid_check",
                entity_id=updated.id,
                action="returned",
                before=item.to_dict(),
                after=updated.to_dict(),
                reason="prepaid_check_returned",
                correlation_id=correlation,
            )
            return self._view(tx, updated, instant)

        return self._command_write(
            operation,
            action="return_prepaid_check",
            target_id=check_id,
            command=command,
            expected_revision=expected_revision,
            instant=instant,
            extra={},
        )

    def void(
        self, check_id: str, command: PrepaidCheckTransitionCommand, *, expected_revision: int
    ) -> dict[str, object]:
        if command.reason is None:
            raise FinanceError("A void reason is required.")

        instant = self.now()

        def operation(tx, context):
            item = self._require(tx, check_id)
            fingerprint = _fingerprint({"id": check_id, "action": "void", **command.__dict__})
            self._ensure_unused_operation_key(tx, command.idempotency_key)
            if item.status != "scheduled":
                raise self._conflict("Only scheduled prepaid checks may be voided.")
            correlation = context.correlation_id
            updated = replace(
                item,
                status="voided",
                voided_at=context.committed_at,
                void_reason=command.reason,
                updated_at=context.committed_at,
            )
            tx.replace_prepaid_check(updated)
            tx.dismiss_prepaid_check_reminder(
                updated.reminder_task_id,
                correlation_id=correlation,
                committed_at=context.committed_at,
            )
            self._record_operation(
                tx,
                updated.id,
                updated.id,
                "void",
                command.idempotency_key,
                fingerprint,
                correlation,
                context.operation_id,
                context.committed_at,
            )
            tx.record_change(
                entity_type="prepaid_check",
                entity_id=updated.id,
                action="voided",
                before=item.to_dict(),
                after=updated.to_dict(),
                reason="prepaid_check_voided",
                correlation_id=correlation,
            )
            return self._view(tx, updated, instant)

        return self._command_write(
            operation,
            action="void_prepaid_check",
            target_id=check_id,
            command=command,
            expected_revision=expected_revision,
            instant=instant,
            extra={},
        )

    def replace(
        self,
        check_id: str,
        command: PrepaidCheckCommand,
        *,
        expected_revision: int,
        confirmed: bool,
        reason: str | None = None,
    ) -> dict[str, object]:
        if type(confirmed) is not bool or not confirmed:
            raise FinanceError("Explicit confirmation is required.")
        if (
            reason is None
            or not isinstance(reason, str)
            or not (reason := reason.strip())
            or len(reason) > 1000
        ):
            raise FinanceError("A replacement reason between 1 and 1000 characters is required.")

        instant = self.now()

        def operation(tx, context):
            previous = self._require(tx, check_id)
            fingerprint = _fingerprint(
                {"id": check_id, "action": "replace", "reason": reason, **command.__dict__}
            )
            self._ensure_unused_operation_key(tx, command.idempotency_key)
            if (
                previous.status not in {"returned", "voided"}
                or previous.replaced_by_prepaid_check_id is not None
            ):
                raise self._conflict("Only un-replaced returned or voided checks may be replaced.")
            if (
                command.expectation_id != previous.expectation_id
                or command.payer_party_id != previous.payer_party_id
            ):
                raise self._conflict("Replacement must retain the original expectation and payer.")
            expectation, zone = self._eligible_expectation(
                tx, command, require_open_balance=True, instant=instant
            )
            if expectation.id != previous.expectation_id or zone is None:
                raise self._conflict("Replacement expectation is no longer eligible.")
            correlation = context.correlation_id
            now = context.committed_at
            replacement = PrepaidCheck(
                str(uuid4()),
                previous.expectation_id,
                previous.lease_id,
                previous.payer_party_id,
                command.received_on,
                command.check_dated_on,
                previous.amount_minor,
                "USD",
                command.masked_reference,
                "scheduled",
                None,
                None,
                None,
                None,
                None,
                None,
                previous.id,
                None,
                None,
                None,
                now,
                now,
            )
            tx.insert_prepaid_check(replacement)
            due = (
                datetime.combine(
                    date.fromisoformat(replacement.check_dated_on), time.min, ZoneInfo(zone)
                )
                .astimezone(UTC)
                .isoformat()
            )
            replacement = replace(
                replacement,
                reminder_task_id=tx.create_prepaid_check_reminder(
                    check_id=replacement.id,
                    due_at_utc=due,
                    due_timezone=zone,
                    correlation_id=correlation,
                    committed_at=context.committed_at,
                ),
            )
            tx.replace_prepaid_check(replacement)
            previous_updated = replace(
                previous,
                status="replaced",
                replaced_by_prepaid_check_id=replacement.id,
                replacement_reason=reason,
                updated_at=context.committed_at,
            )
            tx.replace_prepaid_check(previous_updated)
            self._record_operation(
                tx,
                previous.id,
                replacement.id,
                "replace",
                command.idempotency_key,
                fingerprint,
                correlation,
                context.operation_id,
                context.committed_at,
            )
            tx.record_change(
                entity_type="prepaid_check",
                entity_id=previous_updated.id,
                action="replaced",
                before=previous.to_dict(),
                after=previous_updated.to_dict(),
                reason="prepaid_check_replaced",
                correlation_id=correlation,
            )
            tx.record_change(
                entity_type="prepaid_check",
                entity_id=replacement.id,
                action="created",
                before=None,
                after=replacement.to_dict(),
                reason="prepaid_check_replacement_created",
                correlation_id=correlation,
            )
            return self._view(tx, replacement, instant)

        return self._command_write(
            operation,
            action="replace_prepaid_check",
            target_id=check_id,
            command=command,
            expected_revision=expected_revision,
            instant=instant,
            extra={"confirmed": confirmed, "reason": reason},
        )

    def _select_or_create_receipt(
        self,
        tx,
        item: PrepaidCheck,
        command: PrepaidCheckTransitionCommand,
        deposited_on: str,
        existing_receipt: RentReceipt | None,
        correlation_id: str,
        instant: datetime,
    ) -> tuple[RentReceipt, bool]:
        if existing_receipt is not None:
            return existing_receipt, False
        internal = RecordReceiptCommand(
            lease_id=item.lease_id,
            idempotency_key=command.idempotency_key,
            received_on=deposited_on,
            amount_minor=item.amount_minor,
            currency_code="USD",
            allocations=(ReceiptAllocationCommand(item.expectation_id, item.amount_minor),),
            payment_method_kind="check",
            masked_reference=item.masked_reference,
        )
        receipt = record_receipt_in_transaction(
            tx,
            internal,
            now=lambda: instant,
            correlation_id=correlation_id,
            audit_reason="prepaid_check_deposited",
            duplicate_conflict=lambda duplicates: self._conflict(
                "A likely duplicate receipt exists; select a compatible receipt explicitly.",
                "prepaid_check_likely_duplicate",
                candidateReceiptIds=[candidate.id for candidate in duplicates[:20]],
            ),
        )
        return receipt, True

    def _compatible_existing_receipt(
        self, tx, item: PrepaidCheck, receipt_id: str | None
    ) -> RentReceipt | None:
        if receipt_id is None:
            return None
        try:
            return compatible_prepaid_receipt(
                tx,
                receipt_id=receipt_id,
                lease_id=item.lease_id,
                expectation_id=item.expectation_id,
                amount_minor=item.amount_minor,
            )
        except FinanceConflictError as error:
            raise self._conflict(str(error)) from error

    def _eligible_expectation(
        self, tx, command: PrepaidCheckCommand, *, require_open_balance: bool, instant: datetime
    ) -> tuple[RentExpectation, str]:
        expectation = tx.expectation(command.expectation_id)
        if expectation is None:
            raise FinanceNotFoundError("Rent expectation was not found.")
        if (
            expectation.voided_at is not None
            or expectation.currency_code != "USD"
            or expectation.is_prorated
        ):
            raise self._conflict(
                "A prepaid check requires a current complete USD expectation.",
                "prepaid_check_ineligible_expectation",
            )
        zone = tx.lease_time_zone(expectation.lease_id)
        if zone is None:
            raise self._conflict("Prepaid-check lease context is unavailable.")
        if not tx.participant_active(
            expectation.lease_id, command.payer_party_id, self._today(zone, instant).isoformat()
        ):
            raise self._conflict(
                "Prepaid-check payer must be an active lease participant.",
                "prepaid_check_inactive_payer",
            )
        if date.fromisoformat(command.received_on) > self._today(zone, instant):
            raise FinanceError("Received date cannot be in the future.")
        if require_open_balance and tx.allocated_amount(expectation.id):
            raise self._conflict(
                "A prepaid check requires a fully open expectation.",
                "prepaid_check_expectation_not_open",
            )
        return expectation, zone

    @staticmethod
    def _conflict(
        message: str, code: str = "prepaid_check_lifecycle_conflict", **details: object
    ) -> FinanceConflictError:
        return FinanceConflictError(message, code=code, details=details)

    def _require(self, tx, check_id: str) -> PrepaidCheck:
        item = tx.prepaid_check(check_id)
        if item is None:
            raise FinanceNotFoundError("Prepaid check was not found.")
        return item

    def _ensure_unused_operation_key(self, tx, key: str) -> None:
        if tx.prepaid_check_by_operation_key(key) is not None:
            raise self._conflict(
                "Prepaid-check key has no corresponding command result.",
                "prepaid_check_idempotency_conflict",
            )

    def _record_operation(
        self,
        tx,
        target_check_id: str,
        result_check_id: str,
        action: str,
        key: str,
        fingerprint: str,
        correlation: str,
        operation_id: str,
        committed_at: str,
    ) -> None:
        tx.insert_prepaid_check_operation(
            {
                "id": operation_id,
                "target_prepaid_check_id": target_check_id,
                "result_prepaid_check_id": result_check_id,
                "action": action,
                "idempotency_key": key,
                "request_fingerprint": fingerprint,
                "correlation_id": correlation,
                "created_at": committed_at,
            }
        )

    def _view(self, tx, item: PrepaidCheck, instant=None) -> dict[str, object]:
        expectation = tx.expectation(item.expectation_id)
        zone = tx.lease_time_zone(item.lease_id)
        context = (
            None
            if expectation is None
            else tx.historical_term_snapshot(expectation.lease_id, expectation.lease_term_id)
        )
        if expectation is None or zone is None or context is None:
            raise FinanceConflictError("Prepaid-check context is unavailable.")
        receipt = tx.receipt(item.receipt_id) if item.receipt_id else None
        return {
            **item.to_dict(),
            "propertyId": context.property_id,
            "spaceId": context.space_id,
            "depositEligibility": self._eligibility(item, zone, instant),
            "reminderStatus": tx.prepaid_check_reminder_status(item.reminder_task_id),
            "expectation": {
                "id": expectation.id,
                "periodStartsOn": expectation.period_starts_on,
                "periodEndsOn": expectation.period_ends_on,
                "dueOn": expectation.due_on,
                "amountMinor": expectation.expected_amount_minor,
            },
            "receipt": None
            if receipt is None
            else {
                "id": receipt.id,
                "receivedOn": receipt.received_on,
                "voidedAt": receipt.voided_at,
            },
        }

    def _eligibility(self, item: PrepaidCheck, zone: str, instant=None) -> str:
        if item.status != "scheduled":
            return "not_applicable"
        return (
            "eligible"
            if date.fromisoformat(item.check_dated_on) <= self._today(zone, instant)
            else "not_yet_eligible"
        )

    def _today(self, zone: str, instant=None) -> date:
        return (instant or self.now()).astimezone(ZoneInfo(zone)).date()


def _fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
