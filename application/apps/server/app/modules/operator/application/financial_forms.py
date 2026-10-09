"""Bounded incomplete forms for approved Slice 31C–E workflows."""

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, StrictBool, StrictInt

from app.modules.operator.domain.models import Contract


class FinancialForm(Contract):
    expectedRevision: StrictInt | None = Field(None, ge=0)


class MoneyForm(FinancialForm):
    amount: str | None = Field(None, pattern=r"^(?:0|[1-9][0-9]{0,7})\.[0-9]{2}$", strict=True)
    currencyCode: Literal["USD"] | None = None
    notes: str | None = Field(None, max_length=4000)


class FinancialVoidForm(FinancialForm):
    confirmed: StrictBool | None = None
    reason: str | None = Field(None, max_length=1000)


class TargetVoidForm(FinancialVoidForm):
    targetId: UUID | None = None


class ExpenseCreateForm(MoneyForm):
    propertyId: UUID | None = None
    spaceId: UUID | None = None
    categoryId: UUID | None = None
    providerPartyId: UUID | None = None
    payeeName: str | None = Field(None, max_length=200)
    paidByKind: Literal["local_operator", "party"] | None = None
    paidByPartyId: UUID | None = None
    paidOn: date | None = None
    description: str | None = Field(None, max_length=500)
    reference: str | None = Field(None, max_length=200)
    replacesExpenseId: UUID | None = None
    duplicateConfirmed: StrictBool = False
    historicalEntryConfirmed: StrictBool = False
    historicalEntryReason: str | None = Field(None, max_length=1000)


class ExpenseChanges(Contract):
    categoryId: UUID | None = None
    notes: str | None = Field(None, max_length=4000)
    categoryChangeReason: str | None = Field(None, max_length=1000)
    historicalEntryConfirmed: StrictBool = False
    historicalEntryReason: str | None = Field(None, max_length=1000)


class ExpensePatchForm(FinancialForm):
    changes: ExpenseChanges | None = None


class ExpenseRefundForm(MoneyForm):
    receivedOn: date | None = None
    replacesRefundId: UUID | None = None


class CategoryFields(Contract):
    displayName: str | None = Field(None, max_length=100)
    description: str | None = Field(None, max_length=1000)
    displayOrder: StrictInt | None = Field(None, ge=0, le=10000)


class CategoryCreateForm(FinancialForm, CategoryFields):
    pass


class CategoryPatchForm(FinancialForm):
    changes: CategoryFields | None = None


class DepositAccountForm(FinancialForm):
    leaseId: UUID | None = None
    leaseTermId: UUID | None = None


class DepositReceiptForm(MoneyForm):
    receivedOn: date | None = None
    receivedByKind: Literal["local_operator", "party"] | None = None
    receivedFromPartyId: UUID | None = None
    receivedByPartyId: UUID | None = None
    reference: str | None = Field(None, max_length=200)
    replacesReceiptId: UUID | None = None
    duplicateConfirmed: StrictBool = False
    historicalEntryConfirmed: StrictBool = False
    historicalEntryReason: str | None = Field(None, max_length=1000)
    overageConfirmed: StrictBool = False
    overageReason: str | None = Field(None, max_length=1000)
    historicalPartyConfirmed: StrictBool = False
    historicalPartyReason: str | None = Field(None, max_length=1000)


class SettlementFields(Contract):
    settlementDueOn: date | None = None
    legalRuleReference: str | None = Field(None, max_length=500)
    reviewNotes: str | None = Field(None, max_length=4000)
    deadlineOverrideConfirmed: StrictBool | None = None
    deadlineOverrideReason: str | None = Field(None, max_length=1000)


class SettlementCreateForm(FinancialForm, SettlementFields):
    eligibilityOverrideConfirmed: StrictBool = False
    eligibilityOverrideReason: str | None = Field(None, max_length=1000)
    replacesSettlementId: UUID | None = None


class SettlementPatchForm(FinancialForm):
    targetId: UUID | None = None
    changes: SettlementFields | None = None


class DepositTargetForm(FinancialForm):
    targetId: UUID | None = None


class DeductionForm(DepositTargetForm):
    category: (
        Literal["unpaid_rent", "damage", "cleaning", "missing_property", "contractual_fee", "other"]
        | None
    ) = None
    amount: str | None = Field(None, pattern=r"^(?:0|[1-9][0-9]{0,7})\.[0-9]{2}$", strict=True)
    description: str | None = Field(None, max_length=500)
    rationale: str | None = Field(None, max_length=2000)


class CreditForm(DepositTargetForm):
    kind: Literal["interest", "other"] | None = None
    amount: str | None = Field(None, pattern=r"^(?:0|[1-9][0-9]{0,7})\.[0-9]{2}$", strict=True)
    description: str | None = Field(None, max_length=500)
    calculatorPrincipal: str | None = Field(
        None, pattern=r"^(?:0|[1-9][0-9]{0,7})\.[0-9]{2}$", strict=True
    )
    annualRateBasisPoints: StrictInt | None = Field(None, ge=1, le=100000)
    startsOn: date | None = None
    endsOn: date | None = None
    overrideReason: str | None = Field(None, max_length=1000)


class DeductionSourceForm(DepositTargetForm):
    sourceKind: (
        Literal["inspection_comparison", "inspection_observation", "rent_expectation", "expense"]
        | None
    ) = None
    sourceId: UUID | None = None
    historicalConfirmed: StrictBool = False
    historicalReason: str | None = Field(None, max_length=1000)
    duplicateUseConfirmed: StrictBool = False


class SettlementApproveForm(DepositTargetForm):
    confirmed: StrictBool | None = None
    zeroDollarClosureConfirmed: StrictBool = False


class SettlementCompleteForm(DepositTargetForm):
    zeroRefundConfirmed: StrictBool | None = None


class DepositRefundForm(MoneyForm):
    targetId: UUID | None = None
    recipientPartyId: UUID | None = None
    paidOn: date | None = None
    reference: str | None = Field(None, max_length=200)
    recipientOverrideConfirmed: StrictBool = False
    recipientOverrideReason: str | None = Field(None, max_length=1000)
    replacesRefundId: UUID | None = None
    duplicateConfirmed: StrictBool = False
    historicalPartyConfirmed: StrictBool = False
    historicalPartyReason: str | None = Field(None, max_length=1000)


class OwnerClaimFields(Contract):
    ownerPartyId: UUID | None = None
    receivedOn: date | None = None
    amountMinor: StrictInt | None = Field(None, ge=1, le=9999999999)
    paymentMethodKind: (
        Literal[
            "automatic_bank_payment", "bank_transfer", "check", "cash", "online_payment", "other"
        ]
        | None
    ) = None
    paymentMethodLabel: str | None = Field(None, max_length=100)
    maskedReference: str | None = Field(None, max_length=80)
    otherPaymentMethodNote: str | None = Field(None, max_length=200)
    reportedAtUtc: AwareDatetime | None = None
    sourceNote: str | None = Field(None, max_length=4000)


class OwnerCreateForm(FinancialForm, OwnerClaimFields):
    leaseId: UUID | None = None
    replacesReportId: UUID | None = None


class OwnerPatchForm(FinancialForm):
    changes: OwnerClaimFields | None = None


class OwnerAllocation(Contract):
    expectationId: UUID | None = None
    amountMinor: StrictInt | None = Field(None, ge=1, le=9999999999)


class OwnerVerifyForm(FinancialForm):
    expectedLedgerRevision: StrictInt | None = Field(None, ge=0)
    confirmed: StrictBool | None = None
    reviewNote: str | None = Field(None, max_length=1000)
    existingReceiptId: UUID | None = None
    receiptIdempotencyKey: UUID | None = None
    allocations: list[OwnerAllocation] = Field(default_factory=list, max_length=100)
    replacesReceiptId: UUID | None = None


FINANCIAL_SCHEMAS = {
    "finance.expense.create": ExpenseCreateForm,
    "finance.expense.patch": ExpensePatchForm,
    "finance.expense.void": FinancialVoidForm,
    "finance.expense_refund.create": ExpenseRefundForm,
    "finance.expense_refund.void": TargetVoidForm,
    "finance.expense_category.create": CategoryCreateForm,
    "finance.expense_category.patch": CategoryPatchForm,
    "finance.expense_category.archive": FinancialVoidForm,
    "finance.expense_category.restore": FinancialVoidForm,
    "finance.deposit_account.create": DepositAccountForm,
    "finance.deposit_receipt.create": DepositReceiptForm,
    "finance.deposit_receipt.void": TargetVoidForm,
    "finance.deposit_settlement.create": SettlementCreateForm,
    "finance.deposit_settlement.patch": SettlementPatchForm,
    "finance.deposit_settlement.approve": SettlementApproveForm,
    "finance.deposit_settlement.complete": SettlementCompleteForm,
    "finance.deposit_settlement.void": TargetVoidForm,
    "finance.deposit_deduction.create": DeductionForm,
    "finance.deposit_deduction.update": DeductionForm,
    "finance.deposit_deduction.delete": DepositTargetForm,
    "finance.deposit_credit.create": CreditForm,
    "finance.deposit_credit.update": CreditForm,
    "finance.deposit_credit.delete": DepositTargetForm,
    "finance.deposit_deduction_source.add": DeductionSourceForm,
    "finance.deposit_deduction_source.delete": DepositTargetForm,
    "finance.deposit_refund.create": DepositRefundForm,
    "finance.deposit_refund.void": TargetVoidForm,
    "owner_rent_report.create": OwnerCreateForm,
    "owner_rent_report.patch": OwnerPatchForm,
    "owner_rent_report.verify": OwnerVerifyForm,
    "owner_rent_report.reject": FinancialVoidForm,
}
