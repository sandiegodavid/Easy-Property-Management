"""FIN-002 recorded-expense workflows."""

from __future__ import annotations

from dataclasses import asdict, replace
from json import loads
from datetime import UTC, date, datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.modules.finance.application.commands import (
    FinanceCommandIdentity,
    FinanceCommandOutcome,
    FinanceScope,
    apply_finance_command,
    validate_command_concurrency,
)
from app.modules.finance.application.expense_ports import ExpenseUnitOfWork
from app.modules.finance.application.category_commands import (
    ExpenseCategoryCommand,
    start_category,
    finish_category,
)
from app.modules.finance.application.commands import canonical_uuid
from app.modules.finance.domain.expense_models import (
    CategoryCreateCommand,
    CategoryPatchCommand,
    Expense,
    ExpenseCategory,
    ExpenseCreateCommand,
    ExpensePatchCommand,
    ExpenseQueryCommand,
    ExpenseRefund,
    RefundCreateCommand,
    amount_text,
    category_normalized_name,
    expense_request_fingerprint,
    normalized_label,
    text,
)
from app.modules.finance.domain.models import (
    FinanceConflictError,
    FinanceError,
    FinanceNotFoundError,
    VoidCommand,
)


class PossibleDuplicateExpenseError(FinanceConflictError):
    def __init__(self, candidates: list[dict[str, object]]) -> None:
        super().__init__("A possible duplicate expense requires operator review.")
        self.candidates = candidates


class ExpenseService:
    def __init__(self, unit_of_work: ExpenseUnitOfWork, *, now=lambda: datetime.now(UTC)) -> None:
        self.unit_of_work = unit_of_work
        self.now = now

    def list_categories(self, *, include_archived: bool = False):
        return self.unit_of_work.read(
            lambda tx: [item.to_dict() for item in tx.categories(include_archived)]
        )

    def create_category(
        self, command: CategoryCreateCommand, *, expected_revision: int, idempotency_key: str
    ):
        receipt = ExpenseCategoryCommand(
            "create", None, expected_revision, idempotency_key, asdict(command)
        )

        def operation(tx):
            prior = start_category(tx, receipt)
            if prior is not None:
                return prior
            normalized = category_normalized_name(command.display_name)
            if tx.category_by_name(normalized) is not None:
                raise FinanceConflictError("An expense category with this name already exists.")
            stamp = _stamp(self.now())
            correlation = str(uuid4())
            item = ExpenseCategory(
                str(uuid4()),
                command.display_name,
                normalized,
                command.description,
                command.display_order,
                None,
                stamp,
                stamp,
            )
            tx.insert_category(item)
            tx.record_change(
                entity_type="expense_category",
                entity_id=item.id,
                action="created",
                before=None,
                after=item.to_dict(),
                reason=None,
                correlation_id=correlation,
            )
            return finish_category(tx, receipt, item, stamp, correlation)

        return self.unit_of_work.write(operation)

    def patch_category(
        self,
        category_id: str,
        command: CategoryPatchCommand,
        *,
        expected_revision: int,
        idempotency_key: str,
    ):
        receipt = ExpenseCategoryCommand(
            "patch",
            category_id,
            expected_revision,
            idempotency_key,
            {field: getattr(command, field) for field in command.fields},
        )

        def operation(tx):
            prior = start_category(tx, receipt)
            if prior is not None:
                return prior
            old = tx.category(category_id)
            if old is None:
                raise FinanceNotFoundError("Expense category was not found.")
            name = command.display_name if "display_name" in command.fields else old.display_name
            description = (
                command.description if "description" in command.fields else old.description
            )
            order = (
                command.display_order if "display_order" in command.fields else old.display_order
            )
            normalized = category_normalized_name(name)
            duplicate = tx.category_by_name(normalized)
            if duplicate is not None and duplicate.id != old.id:
                raise FinanceConflictError("An expense category with this name already exists.")
            stamp, correlation = _stamp(self.now()), str(uuid4())
            if (name, description, order) == (old.display_name, old.description, old.display_order):
                return finish_category(tx, receipt, old, stamp, correlation)
            new = replace(
                old,
                display_name=name,
                normalized_name=normalized,
                description=description,
                display_order=order,
                updated_at=stamp,
                revision=old.revision + 1,
            )
            tx.replace_category(new)
            tx.record_change(
                entity_type="expense_category",
                entity_id=new.id,
                action="updated",
                before=old.to_dict(),
                after=new.to_dict(),
                reason=None,
                correlation_id=correlation,
            )
            return finish_category(tx, receipt, new, stamp, correlation)

        return self.unit_of_work.write(operation)

    def archive_category(
        self,
        category_id: str,
        command: VoidCommand,
        *,
        expected_revision: int,
        idempotency_key: str,
    ):
        return self._category_lifecycle(
            category_id,
            command,
            archive=True,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
        )

    def restore_category(
        self,
        category_id: str,
        command: VoidCommand,
        *,
        expected_revision: int,
        idempotency_key: str,
    ):
        return self._category_lifecycle(
            category_id,
            command,
            archive=False,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
        )

    def _category_lifecycle(
        self, category_id, command, *, archive, expected_revision, idempotency_key
    ):
        receipt = ExpenseCategoryCommand(
            "archive" if archive else "restore",
            category_id,
            expected_revision,
            idempotency_key,
            asdict(command),
        )

        def operation(tx):
            prior = start_category(tx, receipt)
            if prior is not None:
                return prior
            old = tx.category(category_id)
            if old is None:
                raise FinanceNotFoundError("Expense category was not found.")
            if archive == (old.archived_at is not None):
                raise FinanceConflictError(
                    f"Expense category is already {'archived' if archive else 'active'}."
                )
            if not archive:
                duplicate = tx.category_by_name(old.normalized_name)
                if (
                    duplicate is not None
                    and duplicate.id != old.id
                    and duplicate.archived_at is None
                ):
                    raise FinanceConflictError("An active category already uses this name.")
            stamp, correlation = _stamp(self.now()), str(uuid4())
            new = replace(
                old,
                archived_at=stamp if archive else None,
                updated_at=stamp,
                revision=old.revision + 1,
            )
            tx.replace_category(new)
            tx.record_change(
                entity_type="expense_category",
                entity_id=new.id,
                action="archived" if archive else "restored",
                before=old.to_dict(),
                after={**new.to_dict(), "lifecycleReason": command.reason},
                reason=None,
                correlation_id=correlation,
            )
            return finish_category(tx, receipt, new, stamp, correlation)

        return self.unit_of_work.write(operation)

    def category_operation(self, operation_id: str):
        canonical_uuid(operation_id)
        return self.unit_of_work.read(
            lambda tx: self._category_result(tx.category_operation(operation_id))
        )

    def category_operation_by_key(self, key: str):
        canonical_uuid(key)
        return self.unit_of_work.read(
            lambda tx: self._category_result(tx.category_operation_by_key(key))
        )

    @staticmethod
    def _category_result(row):
        if row is None:
            raise FinanceNotFoundError("Expense category operation was not found.")
        return loads(row["result_json"])

    def record_expense(self, command: ExpenseCreateCommand, *, expected_revision: int):
        instant = self.now()
        expense_id = str(uuid4())

        def operation(tx):
            old = tx.expense_by_key(command.idempotency_key)
            if old is not None:
                raise FinanceConflictError("Expense key has no matching immutable command receipt.")
            context = tx.portfolio_context(command.property_id, command.space_id, command.paid_on)
            if context is None:
                raise FinanceNotFoundError("Expense property or space was not found.")
            if (
                date.fromisoformat(command.paid_on)
                > instant.astimezone(ZoneInfo(str(context["timeZone"]))).date()
            ):
                raise FinanceError("Paid date cannot be in the future for the property.")
            category = tx.category(command.category_id)
            if category is None:
                raise FinanceNotFoundError("Expense category was not found.")
            provider = None
            payee_name = command.payee_name
            if command.provider_party_id is not None:
                provider = tx.provider_context(command.provider_party_id)
                if provider is None:
                    raise FinanceNotFoundError("Provider was not found.")
                payee_name = text(
                    provider["displayName"],
                    "Provider display-name snapshot",
                    200,
                    required=True,
                )
            archived_reference = bool(
                context["propertyArchived"]
                or context["spaceArchived"]
                or category.archived_at is not None
                or (provider is not None and provider["archived"])
            )
            if archived_reference and (
                not command.historical_entry_confirmed or command.historical_entry_reason is None
            ):
                raise FinanceConflictError(
                    "Archived references require historical-entry confirmation and a reason."
                )
            if not archived_reference and (
                command.historical_entry_confirmed or command.historical_entry_reason is not None
            ):
                raise FinanceError(
                    "Historical-entry confirmation is allowed only for archived references."
                )
            if command.paid_by_party_id is not None:
                if not tx.party_exists(command.paid_by_party_id):
                    raise FinanceNotFoundError("Payer party was not found.")
                if not tx.party_owned_property_on(
                    command.property_id, command.paid_by_party_id, command.paid_on
                ):
                    raise FinanceConflictError(
                        "Party payer was not a client owner on the paid date."
                    )
            stamp = _stamp(instant)
            item = Expense(
                expense_id,
                command.idempotency_key,
                expense_request_fingerprint(command),
                command.property_id,
                command.space_id,
                command.category_id,
                command.provider_party_id,
                str(payee_name),
                command.paid_by_kind,
                command.paid_by_party_id,
                command.paid_on,
                command.amount_minor,
                "USD",
                command.description,
                command.reference,
                command.notes,
                command.replaces_expense_id,
                None,
                None,
                stamp,
                stamp,
            )
            if command.replaces_expense_id is not None:
                replaced = tx.expense(command.replaces_expense_id)
                if replaced is None:
                    raise FinanceNotFoundError("Replaced expense was not found.")
                if replaced.voided_at is None:
                    raise FinanceConflictError("A replacement must target a voided expense.")
                if tx.replacement_expense_exists(replaced.id):
                    raise FinanceConflictError("A replacement expense already exists.")
            candidates = [
                candidate
                for candidate in tx.duplicate_expenses(item)
                if _same_payee_identity(candidate, item)
            ][:10]
            if candidates and not command.duplicate_confirmed:
                raise PossibleDuplicateExpenseError(
                    [_duplicate_summary(candidate) for candidate in candidates]
                )
            tx.insert_expense(item)
            snapshot = _expense_snapshot(item)
            snapshot["duplicateConfirmed"] = command.duplicate_confirmed
            snapshot["historicalEntryConfirmed"] = command.historical_entry_confirmed
            snapshot["historicalEntryReason"] = command.historical_entry_reason
            tx.record_change(
                entity_type="expense",
                entity_id=item.id,
                action="recorded",
                before=None,
                after=snapshot,
                reason=None,
                correlation_id=correlation,
            )
            return self._view(tx, item)

        correlation = str(uuid4())
        return self._command_write(
            operation,
            action="record_expense",
            target_id=None,
            scope_id=expense_id,
            command=command,
            expected_revision=expected_revision,
            idempotency_key=command.idempotency_key,
            instant=instant,
            correlation=correlation,
        )

    def patch_expense(
        self,
        expense_id: str,
        command: ExpensePatchCommand,
        *,
        expected_revision: int,
        idempotency_key: str,
    ):
        instant, correlation = self.now(), str(uuid4())
        effective = False

        def operation(tx):
            nonlocal effective
            old = tx.expense(expense_id)
            if old is None:
                raise FinanceNotFoundError("Expense was not found.")
            category_id = (
                command.category_id if "category_id" in command.fields else old.category_id
            )
            notes = command.notes if "notes" in command.fields else old.notes
            if category_id != old.category_id:
                category = tx.category(category_id)
                if category is None:
                    raise FinanceNotFoundError("Expense category was not found.")
                if category.archived_at is not None and (
                    not command.historical_entry_confirmed
                    or command.historical_entry_reason is None
                ):
                    raise FinanceConflictError(
                        "An archived category requires historical-entry confirmation and a reason."
                    )
                if category.archived_at is None and command.historical_entry_confirmed:
                    raise FinanceError(
                        "Historical-entry confirmation is allowed only for an archived category."
                    )
            if (category_id, notes) == (old.category_id, old.notes):
                return self._view(tx, old)
            effective = True
            new = replace(old, category_id=category_id, notes=notes, updated_at=_stamp(instant))
            tx.replace_expense(new)
            snapshot = _expense_snapshot(new)
            snapshot["categoryChangeReason"] = command.category_change_reason
            snapshot["historicalEntryReason"] = command.historical_entry_reason
            tx.record_change(
                entity_type="expense",
                entity_id=new.id,
                action="updated",
                before=_expense_snapshot(old),
                after=snapshot,
                reason=None,
                correlation_id=correlation,
            )
            return self._view(tx, new)

        return self._command_write(
            operation,
            action="patch_expense",
            target_id=expense_id,
            scope_id=expense_id,
            command=command,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
            instant=instant,
            correlation=correlation,
            effective=lambda: effective,
        )

    def void_expense(
        self,
        expense_id: str,
        command: VoidCommand,
        *,
        expected_revision: int,
        idempotency_key: str,
    ):
        instant, correlation = self.now(), str(uuid4())

        def operation(tx):
            old = tx.expense(expense_id)
            if old is None:
                raise FinanceNotFoundError("Expense was not found.")
            if old.voided_at is not None:
                raise FinanceConflictError("Expense is already voided.")
            if any(item.voided_at is None for item in tx.refunds(old.id)):
                raise FinanceConflictError("An expense with an active refund cannot be voided.")
            new = replace(
                old,
                voided_at=_stamp(instant),
                void_reason=command.reason,
                updated_at=_stamp(instant),
            )
            tx.replace_expense(new)
            tx.record_change(
                entity_type="expense",
                entity_id=new.id,
                action="voided",
                before=_expense_snapshot(old),
                after=_expense_snapshot(new),
                reason=None,
                correlation_id=correlation,
            )
            return self._view(tx, new)

        return self._command_write(
            operation,
            action="void_expense",
            target_id=expense_id,
            scope_id=expense_id,
            command=command,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
            instant=instant,
            correlation=correlation,
        )

    def record_refund(
        self,
        expense_id: str,
        command: RefundCreateCommand,
        *,
        expected_revision: int,
    ):
        instant, correlation = self.now(), str(uuid4())

        def operation(tx):
            old = tx.refund_by_key(command.idempotency_key)
            if old is not None:
                raise FinanceConflictError("Refund key has no matching immutable command receipt.")
            expense = tx.expense(expense_id)
            if expense is None:
                raise FinanceNotFoundError("Expense was not found.")
            if expense.voided_at is not None:
                raise FinanceConflictError("A voided expense cannot receive a refund.")
            context = tx.portfolio_context(expense.property_id, expense.space_id, expense.paid_on)
            if context is None:
                raise FinanceConflictError("Expense property context is unavailable.")
            received = date.fromisoformat(command.received_on)
            if received < date.fromisoformat(expense.paid_on):
                raise FinanceError("Refund date cannot precede the expense date.")
            if received > instant.astimezone(ZoneInfo(str(context["timeZone"]))).date():
                raise FinanceError("Refund date cannot be in the future for the property.")
            item = ExpenseRefund(
                str(uuid4()),
                expense.id,
                command.idempotency_key,
                command.received_on,
                command.amount_minor,
                "USD",
                command.notes,
                command.replaces_refund_id,
                None,
                None,
                _stamp(instant),
            )
            if command.replaces_refund_id is not None:
                replaced = tx.refund(command.replaces_refund_id)
                if replaced is None:
                    raise FinanceNotFoundError("Replaced refund was not found.")
                if replaced.expense_id != expense.id or replaced.voided_at is None:
                    raise FinanceConflictError(
                        "Replacement must target a voided refund on this expense."
                    )
                if tx.replacement_refund_exists(replaced.id):
                    raise FinanceConflictError("A replacement refund already exists.")
            active_total = sum(
                row.amount_minor for row in tx.refunds(expense.id) if row.voided_at is None
            )
            if active_total + item.amount_minor > expense.amount_minor:
                raise FinanceConflictError("Active refunds cannot exceed the expense amount.")
            tx.insert_refund(item)
            tx.record_change(
                entity_type="expense_refund",
                entity_id=item.id,
                action="recorded",
                before=None,
                after=item.to_dict(),
                reason=None,
                correlation_id=correlation,
            )
            return _refund_view(item)

        return self._command_write(
            operation,
            action="record_refund",
            target_id=expense_id,
            scope_id=expense_id,
            command=command,
            expected_revision=expected_revision,
            idempotency_key=command.idempotency_key,
            instant=instant,
            correlation=correlation,
        )

    def void_refund(
        self,
        refund_id: str,
        command: VoidCommand,
        *,
        expected_revision: int,
        idempotency_key: str,
    ):
        instant, correlation = self.now(), str(uuid4())

        def operation(tx):
            old = tx.refund(refund_id)
            if old is None:
                raise FinanceNotFoundError("Expense refund was not found.")
            if old.voided_at is not None:
                raise FinanceConflictError("Expense refund is already voided.")
            new = replace(old, voided_at=_stamp(instant), void_reason=command.reason)
            tx.replace_refund(new)
            tx.record_change(
                entity_type="expense_refund",
                entity_id=new.id,
                action="voided",
                before=old.to_dict(),
                after=new.to_dict(),
                reason=None,
                correlation_id=correlation,
            )
            return _refund_view(new)

        return self._command_write(
            operation,
            action="void_refund",
            target_id=refund_id,
            scope_id=None,
            command=command,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
            instant=instant,
            correlation=correlation,
        )

    def _command_write(
        self,
        operation,
        *,
        action,
        target_id,
        scope_id,
        command,
        expected_revision,
        idempotency_key,
        instant,
        correlation,
        effective=lambda: True,
    ):
        validate_command_concurrency(expected_revision, idempotency_key)
        payload = asdict(command)
        if "fields" in payload:
            payload["fields"] = sorted(payload["fields"])

        def write(tx):
            prior = tx.commands.command_operation(idempotency_key)
            resolved = prior["scope_id"] if prior is not None else scope_id
            if resolved is None:
                refund = tx.refund(target_id)
                if refund is None:
                    raise FinanceNotFoundError("Expense refund was not found.")
                resolved = refund.expense_id
            identity = FinanceCommandIdentity(
                FinanceScope("expense", resolved),
                action,
                target_id or resolved,
                expected_revision,
                idempotency_key,
                payload,
            )
            return apply_finance_command(
                tx.commands,
                identity,
                lambda _: FinanceCommandOutcome(operation(tx), effective()),
                instant=instant,
                correlation_id=correlation,
            )

        return self.unit_of_work.write(write)

    def expense(self, expense_id: str):
        def operation(tx):
            item = tx.expense(expense_id)
            if item is None:
                raise FinanceNotFoundError("Expense was not found.")
            return self._view(tx, item)

        return self.unit_of_work.read(operation)

    def revision(self, expense_id: str) -> int:
        def read(tx):
            if tx.expense(expense_id) is None:
                raise FinanceNotFoundError("Expense was not found.")
            return tx.commands.command_revision(FinanceScope("expense", expense_id))

        return self.unit_of_work.read(read)

    def list_expenses(self, command: ExpenseQueryCommand | None = None):
        if command is None:
            command = ExpenseQueryCommand()
        if not isinstance(command, ExpenseQueryCommand):
            raise FinanceError("Expense query must be a validated ExpenseQueryCommand.")

        def operation(tx):
            rows = tx.expenses(**command.filters())
            page = rows[: command.page_size]
            projection = tx.expense_projection(page)
            items = [self._view(tx, item, projection) for item in page]
            return {
                "items": items,
                "nextCursor": (
                    f"{page[-1].paid_on}|{page[-1].id}" if len(rows) > command.page_size else None
                ),
            }

        return self.unit_of_work.read(operation)

    def _view(self, tx, item: Expense, projection=None):
        projection = projection or tx.expense_projection([item])
        category = projection["categories"].get(item.category_id)
        context = projection["contexts"].get(item.id)
        if category is None or context is None:
            raise FinanceConflictError("Expense reference context is unavailable.")
        provider = (
            projection["providers"].get(item.provider_party_id) if item.provider_party_id else None
        )
        refunds = projection["refunds"].get(item.id, [])
        active_refunded = sum(row.amount_minor for row in refunds if row.voided_at is None)
        evidence = projection["evidence"].get(item.id, [])
        correction_chain = projection["correction_chains"].get(item.id, [])
        values = item.to_dict()
        values.pop("amountMinor")
        values.pop("requestFingerprint")
        return {
            **values,
            "expenseRevision": projection["revisions"].get(item.id, 0),
            "amount": amount_text(item.amount_minor),
            "category": category.to_dict(),
            "property": {"id": context["propertyId"], "displayName": context["propertyName"]},
            "space": None
            if item.space_id is None
            else {"id": context["spaceId"], "displayName": context["spaceName"]},
            "provider": provider,
            "refunds": [_refund_view(row) for row in refunds],
            "activeRefundedAmount": amount_text(active_refunded),
            "netAmount": amount_text(item.amount_minor - active_refunded),
            "lifecycleStatus": "voided" if item.voided_at else "active",
            "activeEvidence": [row for row in evidence if row["archivedAt"] is None],
            "archivedEvidence": [row for row in evidence if row["archivedAt"] is not None],
            "correctionChain": [_expense_chain_summary(row) for row in correction_chain],
        }


def _expense_snapshot(item: Expense) -> dict[str, object]:
    values = item.to_dict()
    values.pop("requestFingerprint")
    return values


def _same_payee_identity(left: Expense, right: Expense) -> bool:
    if left.provider_party_id is not None or right.provider_party_id is not None:
        return left.provider_party_id == right.provider_party_id
    return normalized_label(left.payee_name) == normalized_label(right.payee_name)


def _refund_view(item: ExpenseRefund):
    values = item.to_dict()
    values.pop("amountMinor")
    return {
        **values,
        "amount": amount_text(item.amount_minor),
        "lifecycleStatus": "voided" if item.voided_at else "active",
    }


def _expense_chain_summary(item: Expense):
    return {
        "id": item.id,
        "paidOn": item.paid_on,
        "amount": amount_text(item.amount_minor),
        "lifecycleStatus": "voided" if item.voided_at else "active",
        "replacesExpenseId": item.replaces_expense_id,
    }


def _duplicate_summary(item: Expense):
    return {
        "id": item.id,
        "paidOn": item.paid_on,
        "amount": amount_text(item.amount_minor),
        "payeeName": item.payee_name,
        "description": item.description,
    }


def _stamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise FinanceError("The application clock must be timezone-aware.")
    return value.astimezone(UTC).isoformat()
