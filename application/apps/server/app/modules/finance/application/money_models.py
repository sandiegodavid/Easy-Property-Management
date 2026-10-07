"""FIN-003 typed read contracts; money is formatted only at this boundary."""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from uuid import UUID


class MoneyError(ValueError):
    code = "money_request_invalid"
    status_code = 422


class MoneyTooLarge(MoneyError):
    code = "money_request_too_large"
    status_code = 413


class MoneyViewChanged(MoneyError):
    code = "money_view_changed"
    status_code = 409


class MoneyNotFound(MoneyError):
    code = "money_property_not_found"
    status_code = 404


class MoneyUnavailable(MoneyError):
    code = "money_read_failed"
    status_code = 500


class MoneyBusy(MoneyError):
    code = "workspace_busy"
    status_code = 503


class MoneyWorkspaceUnavailable(MoneyError):
    code = "workspace_unavailable"
    status_code = 503


class Metric(StrEnum):
    RENT = "rentReceived"
    EXPENSES = "expensesPaid"
    REFUNDS = "expenseRefundsReceived"
    NET_EXPENSES = "netRecordedExpenses"
    REMAINDER = "operatingRemainder"
    DEPOSIT_RECEIPTS = "depositReceipts"
    DEPOSIT_REFUNDS = "depositRefunds"
    CREDITS = "settlementCredits"
    DEDUCTIONS = "settlementDeductions"
    OBLIGATION = "recordedDepositObligation"
    CURRENT_RECEIPTS = "currentDepositReceipts"
    CURRENT_REFUNDS = "currentDepositRefunds"
    CURRENT_CREDITS = "currentDepositCredits"
    CURRENT_DEDUCTIONS = "currentDepositDeductions"


@dataclass(frozen=True)
class MoneyQuery:
    from_on: str
    through_on: str
    property_state: str = "all"
    property_ids: tuple[str, ...] = ()
    page_size: int = 50
    cursor: str | None = None
    source_revision: str | None = None

    def __post_init__(self):
        try:
            start, end = date.fromisoformat(self.from_on), date.fromisoformat(self.through_on)
            if start.isoformat() != self.from_on or end.isoformat() != self.through_on:
                raise ValueError()
            if not 0 <= (end - start).days < 3660 or self.property_state not in {
                "active",
                "archived",
                "all",
            }:
                raise ValueError()
            if type(self.page_size) is not int or not 1 <= self.page_size <= 100:
                raise ValueError()
            if len(self.property_ids) > 100:
                raise MoneyTooLarge("Select at most 100 properties.")
            ids = tuple(sorted({str(UUID(value)) for value in self.property_ids}))
            object.__setattr__(self, "property_ids", ids)
            for value in (self.cursor, self.source_revision):
                if value is not None and (not isinstance(value, str) or not value):
                    raise ValueError()
                if value is not None and len(value) > 4096:
                    raise MoneyTooLarge("Continuation content is too large.")
            if self.source_revision is not None and (
                len(self.source_revision) != 64
                or any(char not in "0123456789abcdef" for char in self.source_revision)
            ):
                raise ValueError()
        except (ValueError, TypeError, AttributeError) as error:
            if isinstance(error, MoneyError):
                raise
            raise MoneyError("Dates, scope, property IDs, or page bounds are invalid.") from error


@dataclass(frozen=True)
class AmountCount:
    amount_minor: int = 0
    record_count: int = 0


@dataclass(frozen=True)
class Scope:
    property_count: int
    excluded_property_count: int


@dataclass(frozen=True)
class Filters:
    from_on: str
    through_on: str
    property_state: str
    property_ids: tuple[str, ...]


@dataclass(frozen=True)
class Operating:
    rent_received: str
    expenses_paid: str
    expense_refunds_received: str
    net_recorded_expenses: str
    operating_remainder: str
    rent_receipt_count: int
    expense_count: int
    expense_refund_count: int
    available: bool = True


@dataclass(frozen=True)
class DepositActivity:
    deposit_receipts: str
    deposit_refunds: str
    settlement_credits: str
    settlement_deductions: str
    receipt_count: int
    refund_count: int
    approved_settlement_count: int
    completed_settlement_count: int
    available: bool = True


@dataclass(frozen=True)
class DepositObligations:
    positive_obligations: str
    negative_reconciliation_amount: str
    net_recorded_obligation: str
    account_count: int
    negative_account_count: int
    unresolved_account_count: int
    available: bool = True


@dataclass(frozen=True)
class MetricDescriptor:
    metric: Metric
    amount: str
    path: str = "/api/money/sources"


@dataclass(frozen=True, kw_only=True)
class MoneySummary:
    as_of: str
    source_revision: str
    filters: Filters
    scope: Scope
    operating: Operating
    deposit_activity: DepositActivity
    deposit_obligations: DepositObligations
    metrics: tuple[MetricDescriptor, ...]
    contract_version: int = 1
    currency_code: str = "USD"
    period_basis: str = "property_local_business_date"
    financial_state: str = "current_corrected"
    deposit_balance_basis: str = "current_all_recorded_dates"


@dataclass(frozen=True)
class PropertyMoney:
    property_id: str
    property_name: str
    property_state: str
    operating: Operating
    deposit_activity: DepositActivity
    deposit_obligations: DepositObligations


@dataclass(frozen=True)
class PropertyMoneyPage:
    summary: MoneySummary
    items: tuple[PropertyMoney, ...]
    matching_total: int
    next_cursor: str | None


@dataclass(frozen=True)
class Contribution:
    source_kind: str
    source_id: str
    property_id: str
    business_on: str
    contribution: str
    lifecycle: str
    reason: str
    detail_route: str
    lease_id: str | None = None
    space_id: str | None = None
    account_id: str | None = None
    parent_id: str | None = None
    authorization_id: str | None = None
    party_id: str | None = None


@dataclass(frozen=True)
class SourcePage:
    as_of: str
    source_revision: str
    filters: Filters
    metric: Metric
    total: str
    matching_total: int
    items: tuple[Contribution, ...]
    next_cursor: str | None
    contract_version: int = 1
    currency_code: str = "USD"
    period_basis: str = "property_local_business_date"
    financial_state: str = "current_corrected"
    deposit_balance_basis: str = "current_all_recorded_dates"


@dataclass(frozen=True)
class DepositAccountMoney:
    account_id: str
    property_id: str
    lease_id: str
    space_id: str
    receipts: str
    refunds: str
    credits: str
    deductions: str
    recorded_deposit_obligation: str
    agreed_amount: str
    variance_amount: str
    unsettled_receipt_amount: str
    settlement_id: str | None
    settlement_status: str | None
    approved_refund_due: str | None
    unresolved: bool
    requires_review: bool
    detail_route: str


@dataclass(frozen=True)
class DepositAccountPage:
    as_of: str
    source_revision: str
    filters: Filters
    totals: DepositObligations
    items: tuple[DepositAccountMoney, ...]
    matching_total: int
    next_cursor: str | None
    contract_version: int = 1
    currency_code: str = "USD"
    financial_state: str = "current_corrected"
    deposit_balance_basis: str = "current_all_recorded_dates"


def checked_minor(value: int) -> int:
    if type(value) is not int or not -(2**63) <= value < 2**63:
        raise MoneyUnavailable("Recorded money exceeds the supported integer range.")
    return value


def money(value: int) -> str:
    value = checked_minor(value)
    return f"{'-' if value < 0 else ''}{abs(value) // 100}.{abs(value) % 100:02d}"
