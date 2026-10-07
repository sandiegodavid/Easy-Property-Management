"""Typed FIN-003 read-only HTTP contracts."""

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.modules.finance.application.money_models import Metric, MoneyError, MoneyQuery
from app.modules.finance.application.money_ports import MoneySummaryReader
from app.platform.api_errors import api_problem, workspace_unavailable


class Contract(BaseModel):
    model_config = ConfigDict(
        extra="forbid", from_attributes=True, alias_generator=to_camel, populate_by_name=True
    )


class PeriodInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fromOn: date
    throughOn: date
    propertyState: Literal["active", "archived", "all"] = "all"
    propertyIds: list[UUID] = Field(default_factory=list, max_length=100)
    sourceRevision: str | None = Field(default=None, max_length=4096, pattern=r"^[0-9a-f]{64}$")

    def command(self, **changes):
        values = dict(
            from_on=self.fromOn.isoformat(),
            through_on=self.throughOn.isoformat(),
            property_state=self.propertyState,
            property_ids=tuple(map(str, self.propertyIds)),
            source_revision=self.sourceRevision,
        )
        values.update(changes)
        return MoneyQuery(**values)


class PageInput(PeriodInput):
    pageSize: int = Field(default=50, ge=1, le=100)
    cursor: str | None = Field(default=None, max_length=4096)

    def command(self, **changes):
        return super().command(page_size=self.pageSize, cursor=self.cursor, **changes)


class SourceInput(PageInput):
    metric: Metric


class PropertyPeriodInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fromOn: date
    throughOn: date
    sourceRevision: str | None = Field(default=None, max_length=4096, pattern=r"^[0-9a-f]{64}$")


class FiltersResponse(Contract):
    from_on: date
    through_on: date
    property_state: Literal["active", "archived", "all"]
    property_ids: tuple[UUID, ...]


class ScopeResponse(Contract):
    property_count: int
    excluded_property_count: int


Money = Annotated[str, Field(pattern=r"^-?(0|[1-9][0-9]*)\.[0-9]{2}$")]


class OperatingResponse(Contract):
    rent_received: Money
    expenses_paid: Money
    expense_refunds_received: Money
    net_recorded_expenses: Money
    operating_remainder: Money
    rent_receipt_count: int
    expense_count: int
    expense_refund_count: int
    available: bool


class DepositActivityResponse(Contract):
    deposit_receipts: Money
    deposit_refunds: Money
    settlement_credits: Money
    settlement_deductions: Money
    receipt_count: int
    refund_count: int
    approved_settlement_count: int
    completed_settlement_count: int
    available: bool


class DepositObligationsResponse(Contract):
    positive_obligations: Money
    negative_reconciliation_amount: Money
    net_recorded_obligation: Money
    account_count: int
    negative_account_count: int
    unresolved_account_count: int
    available: bool


class MetricResponse(Contract):
    metric: Metric
    amount: Money
    path: str


class SummaryResponse(Contract):
    as_of: datetime
    source_revision: str
    filters: FiltersResponse
    scope: ScopeResponse
    operating: OperatingResponse
    deposit_activity: DepositActivityResponse
    deposit_obligations: DepositObligationsResponse
    metrics: tuple[MetricResponse, ...]
    contract_version: Literal[1]
    currency_code: Literal["USD"]
    period_basis: Literal["property_local_business_date"]
    financial_state: Literal["current_corrected"]
    deposit_balance_basis: Literal["current_all_recorded_dates"]


class PropertyResponse(Contract):
    property_id: UUID
    property_name: str
    property_state: Literal["active", "archived"]
    operating: OperatingResponse
    deposit_activity: DepositActivityResponse
    deposit_obligations: DepositObligationsResponse


class PropertyPageResponse(Contract):
    summary: SummaryResponse
    items: tuple[PropertyResponse, ...]
    matching_total: int
    next_cursor: str | None


class ContributionResponse(Contract):
    source_kind: str
    source_id: UUID
    property_id: UUID
    business_on: date
    contribution: Money
    lifecycle: str
    reason: Metric
    detail_route: str
    lease_id: UUID | None
    space_id: UUID | None
    account_id: UUID | None
    parent_id: UUID | None
    authorization_id: UUID | None
    party_id: UUID | None


class SourcePageResponse(Contract):
    as_of: datetime
    source_revision: str
    filters: FiltersResponse
    metric: Metric
    total: Money
    matching_total: int
    items: tuple[ContributionResponse, ...]
    next_cursor: str | None
    contract_version: Literal[1]
    currency_code: Literal["USD"]
    period_basis: Literal["property_local_business_date"]
    financial_state: Literal["current_corrected"]
    deposit_balance_basis: Literal["current_all_recorded_dates"]


class AccountResponse(Contract):
    account_id: UUID
    property_id: UUID
    lease_id: UUID
    space_id: UUID
    receipts: Money
    refunds: Money
    credits: Money
    deductions: Money
    recorded_deposit_obligation: Money
    agreed_amount: Money
    variance_amount: Money
    unsettled_receipt_amount: Money
    settlement_id: UUID | None
    settlement_status: str | None
    approved_refund_due: Money | None
    unresolved: bool
    requires_review: bool
    detail_route: str


class AccountPageResponse(Contract):
    as_of: datetime
    source_revision: str
    filters: FiltersResponse
    totals: DepositObligationsResponse
    items: tuple[AccountResponse, ...]
    matching_total: int
    next_cursor: str | None
    contract_version: Literal[1]
    currency_code: Literal["USD"]
    financial_state: Literal["current_corrected"]
    deposit_balance_basis: Literal["current_all_recorded_dates"]


def build_router(reader: MoneySummaryReader, runtime):
    router = APIRouter(tags=["money"])

    def invoke(operation):
        if not runtime.ready:
            raise workspace_unavailable("Open a validated workspace to read money summaries.")
        try:
            return operation()
        except MoneyError as error:
            raise api_problem(error.status_code, error.code, str(error)) from error

    @router.get(
        "/api/money/summary", response_model=SummaryResponse, operation_id="getMoneySummary"
    )
    def summary(query: Annotated[PeriodInput, Query()]):
        return invoke(lambda: reader.summary(query.command()))

    @router.get(
        "/api/money/properties",
        response_model=PropertyPageResponse,
        operation_id="getPropertyMoneyPage",
    )
    def properties(query: Annotated[PageInput, Query()]):
        return invoke(lambda: reader.properties(query.command()))

    @router.get(
        "/api/properties/{property_id}/money-summary",
        response_model=SummaryResponse,
        operation_id="getPropertyMoneySummary",
    )
    def property_summary(property_id: UUID, query: Annotated[PropertyPeriodInput, Query()]):
        return invoke(
            lambda: reader.summary(
                MoneyQuery(
                    query.fromOn.isoformat(),
                    query.throughOn.isoformat(),
                    property_ids=(str(property_id),),
                    source_revision=query.sourceRevision,
                )
            )
        )

    @router.get(
        "/api/money/sources", response_model=SourcePageResponse, operation_id="getMoneySources"
    )
    def sources(query: Annotated[SourceInput, Query()]):
        return invoke(lambda: reader.sources(query.command(), query.metric))

    @router.get(
        "/api/money/deposit-accounts",
        response_model=AccountPageResponse,
        operation_id="getMoneyDepositAccounts",
    )
    def accounts(query: Annotated[PageInput, Query()]):
        return invoke(lambda: reader.deposit_accounts(query.command()))

    return router
