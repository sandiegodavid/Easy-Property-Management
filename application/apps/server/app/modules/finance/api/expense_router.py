"""Typed FIN-002 HTTP contract."""

from __future__ import annotations

from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query, status
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    field_validator,
    model_validator,
)

from app.modules.finance.api.conflicts import FinanceConflictDetail

from app.platform.api_errors import domain_problem, workspace_unavailable

from app.modules.finance.application.expense_service import (
    ExpenseService,
    PossibleDuplicateExpenseError,
)
from app.modules.finance.domain.expense_models import (
    CategoryCreateCommand,
    CategoryPatchCommand,
    ExpenseCreateCommand,
    ExpensePatchCommand,
    ExpenseQueryCommand,
    RefundCreateCommand,
)
from app.modules.finance.domain.models import (
    FinanceConflictError,
    FinanceError,
    FinanceNotFoundError,
    VoidCommand,
)
from app.modules.workspace.application.runtime import WorkspaceRuntime


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CategoryCommandInput(Contract):
    expectedRevision: StrictInt = Field(ge=1)
    idempotencyKey: UUID

    @field_validator("idempotencyKey", mode="before")
    @classmethod
    def canonical_key(cls, value):
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError("idempotencyKey must be a canonical UUID.")
        return value


class CategoryInput(CategoryCommandInput):
    expectedRevision: StrictInt = Field(ge=0, le=0)
    displayName: str = Field(min_length=1, max_length=100)
    description: str | None = Field(None, max_length=1000)
    displayOrder: StrictInt = Field(0, ge=0, le=10_000)


class CategoryPatchInput(CategoryCommandInput):
    displayName: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = Field(None, max_length=1000)
    displayOrder: StrictInt | None = Field(None, ge=0, le=10_000)

    @model_validator(mode="after")
    def reject_null_nonnullable_fields(self):
        if not self.model_fields_set & {"displayName", "description", "displayOrder"}:
            raise ValueError("Select at least one category field.")
        if "displayName" in self.model_fields_set and self.displayName is None:
            raise ValueError("displayName cannot be null.")
        if "displayOrder" in self.model_fields_set and self.displayOrder is None:
            raise ValueError("displayOrder cannot be null.")
        return self


class ConfirmReasonInput(Contract):
    confirmed: StrictBool
    reason: str = Field(min_length=1, max_length=1000)


class CategoryLifecycleInput(ConfirmReasonInput, CategoryCommandInput):
    pass


class ExpenseCommandInput(Contract):
    expectedRevision: StrictInt = Field(ge=0)
    idempotencyKey: UUID


class ExpenseVoidInput(ConfirmReasonInput, ExpenseCommandInput):
    pass


class ExpenseInput(ExpenseCommandInput):
    idempotencyKey: UUID
    propertyId: UUID
    spaceId: UUID | None = None
    categoryId: UUID
    providerPartyId: UUID | None = None
    payeeName: str | None = Field(None, min_length=1, max_length=200)
    paidByKind: Literal["local_operator", "party"]
    paidByPartyId: UUID | None = None
    paidOn: date
    amount: str = Field(pattern=r"^(?:0|[1-9][0-9]{0,7})\.[0-9]{2}$", strict=True)
    currencyCode: Literal["USD"]
    description: str = Field(min_length=1, max_length=500)
    reference: str | None = Field(None, max_length=200)
    notes: str | None = Field(None, max_length=4000)
    replacesExpenseId: UUID | None = None
    duplicateConfirmed: StrictBool = False
    historicalEntryConfirmed: StrictBool = False
    historicalEntryReason: str | None = Field(None, max_length=1000)

    @model_validator(mode="after")
    def validate_pairs(self):
        if (self.providerPartyId is None) == (self.payeeName is None):
            raise ValueError("Provide exactly one providerPartyId or payeeName.")
        if (self.paidByKind == "local_operator") != (self.paidByPartyId is None):
            raise ValueError("paidByPartyId is required exactly when paidByKind is party.")
        if (self.historicalEntryReason is not None) != self.historicalEntryConfirmed:
            raise ValueError(
                "historicalEntryConfirmed and historicalEntryReason must be supplied together."
            )
        return self


class ExpensePatchInput(ExpenseCommandInput):
    categoryId: UUID | None = None
    notes: str | None = Field(None, max_length=4000)
    categoryChangeReason: str | None = Field(None, max_length=1000)
    historicalEntryConfirmed: StrictBool = False
    historicalEntryReason: str | None = Field(None, max_length=1000)

    @model_validator(mode="after")
    def reject_null_category(self):
        if "categoryId" in self.model_fields_set and self.categoryId is None:
            raise ValueError("categoryId cannot be null.")
        if "categoryId" in self.model_fields_set and self.categoryChangeReason is None:
            raise ValueError("categoryChangeReason is required when categoryId changes.")
        if "categoryId" not in self.model_fields_set and self.categoryChangeReason is not None:
            raise ValueError("categoryChangeReason requires categoryId.")
        if (self.historicalEntryReason is not None) != self.historicalEntryConfirmed:
            raise ValueError(
                "historicalEntryConfirmed and historicalEntryReason must be supplied together."
            )
        return self


class RefundInput(ExpenseCommandInput):
    idempotencyKey: UUID
    receivedOn: date
    amount: str = Field(pattern=r"^(?:0|[1-9][0-9]{0,7})\.[0-9]{2}$", strict=True)
    currencyCode: Literal["USD"]
    notes: str | None = Field(None, max_length=4000)
    replacesRefundId: UUID | None = None


class CategoryResponse(Contract):
    revision: StrictInt = Field(ge=1)
    operationId: UUID | None = None
    id: UUID
    displayName: str
    normalizedName: str
    description: str | None
    displayOrder: int
    archivedAt: AwareDatetime | None
    createdAt: AwareDatetime
    updatedAt: AwareDatetime


class CategoryMutationResponse(CategoryResponse):
    operationId: UUID


class RecordSummary(Contract):
    id: UUID
    displayName: str


class ProviderSummary(Contract):
    partyId: UUID
    displayName: str
    archived: bool


class EvidenceResponse(Contract):
    linkId: UUID
    fileId: UUID
    originalName: str
    mediaType: str
    sizeBytes: int
    contentSha256: str
    purpose: Literal["receipt", "invoice", "proof_of_payment", "supporting_document"]
    createdAt: AwareDatetime
    archivedAt: AwareDatetime | None
    archiveReason: str | None


class RefundResponse(Contract):
    id: UUID
    expenseId: UUID
    idempotencyKey: UUID
    receivedOn: date
    amount: str
    currencyCode: Literal["USD"]
    notes: str | None
    replacesRefundId: UUID | None
    voidedAt: AwareDatetime | None
    voidReason: str | None
    createdAt: AwareDatetime
    lifecycleStatus: Literal["active", "voided"]


class ExpenseCorrectionSummary(Contract):
    id: UUID
    paidOn: date
    amount: str
    lifecycleStatus: Literal["active", "voided"]
    replacesExpenseId: UUID | None


class ExpenseResponse(Contract):
    expenseRevision: StrictInt
    id: UUID
    idempotencyKey: UUID
    propertyId: UUID
    spaceId: UUID | None
    categoryId: UUID
    providerPartyId: UUID | None
    payeeName: str
    paidByKind: Literal["local_operator", "party"]
    paidByPartyId: UUID | None
    paidOn: date
    amount: str
    currencyCode: Literal["USD"]
    description: str
    reference: str | None
    notes: str | None
    replacesExpenseId: UUID | None
    voidedAt: AwareDatetime | None
    voidReason: str | None
    createdAt: AwareDatetime
    updatedAt: AwareDatetime
    category: CategoryResponse
    property: RecordSummary
    space: RecordSummary | None
    provider: ProviderSummary | None
    refunds: list[RefundResponse]
    activeRefundedAmount: str
    netAmount: str
    lifecycleStatus: Literal["active", "voided"]
    activeEvidence: list[EvidenceResponse]
    archivedEvidence: list[EvidenceResponse]
    correctionChain: list[ExpenseCorrectionSummary]


class ExpensePageResponse(Contract):
    items: list[ExpenseResponse]
    nextCursor: str | None


class ExpenseMutationResponse(ExpenseResponse):
    operationId: UUID


class RefundMutationResponse(RefundResponse):
    expenseRevision: StrictInt
    operationId: UUID


class ExpenseDuplicateCandidate(Contract):
    id: UUID
    paidOn: date
    amount: str
    payeeName: str
    description: str


class ExpenseConflictDetail(FinanceConflictDetail):
    candidates: list[ExpenseDuplicateCandidate] | None = None
    currentCategory: CategoryResponse | None = None


class ExpenseConflictResponse(Contract):
    detail: ExpenseConflictDetail


def build_router(service: ExpenseService, runtime: WorkspaceRuntime) -> APIRouter:
    router = APIRouter(tags=["expenses"], responses={409: {"model": ExpenseConflictResponse}})

    def ready(write=False):
        if not runtime.ready or runtime.error:
            raise workspace_unavailable(str(runtime.error or "Workspace is not ready."))
        if write and not runtime.can_write:
            raise workspace_unavailable("Workspace writer lock is unavailable.")

    def invoke(operation):
        try:
            return operation()
        except PossibleDuplicateExpenseError as error:
            raise domain_problem(
                error,
                status_code=409,
                code="possible_duplicate_expense",
                candidates=error.candidates,
            ) from error
        except FinanceNotFoundError as error:
            raise domain_problem(error, status_code=404, code="finance_not_found") from error
        except FinanceConflictError as error:
            raise domain_problem(
                error, status_code=409, code=error.code, **error.details
            ) from error
        except FinanceError as error:
            raise domain_problem(error, status_code=400, code="finance_validation") from error

    @router.get(
        "/api/expense-categories",
        response_model=list[CategoryResponse],
        operation_id="listExpenseCategories",
    )
    def categories(includeArchived: bool = False):
        ready()
        return invoke(lambda: service.list_categories(include_archived=includeArchived))

    @router.post(
        "/api/expense-categories",
        response_model=CategoryMutationResponse,
        status_code=201,
        operation_id="createExpenseCategory",
    )
    def create_category(data: CategoryInput):
        ready(True)
        return invoke(
            lambda: service.create_category(
                CategoryCreateCommand(data.displayName, data.description, data.displayOrder),
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    @router.patch(
        "/api/expense-categories/{category_id}",
        response_model=CategoryMutationResponse,
        operation_id="patchExpenseCategory",
    )
    def patch_category(category_id: UUID, data: CategoryPatchInput):
        ready(True)
        fields = frozenset(
            {
                {
                    "displayName": "display_name",
                    "description": "description",
                    "displayOrder": "display_order",
                }[name]
                for name in data.model_fields_set
                if name in {"displayName", "description", "displayOrder"}
            }
        )
        return invoke(
            lambda: service.patch_category(
                str(category_id),
                CategoryPatchCommand(fields, data.displayName, data.description, data.displayOrder),
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    @router.post(
        "/api/expense-categories/{category_id}/archive",
        response_model=CategoryMutationResponse,
        operation_id="archiveExpenseCategory",
    )
    def archive_category(category_id: UUID, data: CategoryLifecycleInput):
        ready(True)
        return invoke(
            lambda: service.archive_category(
                str(category_id),
                VoidCommand(data.confirmed, data.reason),
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    @router.post(
        "/api/expense-categories/{category_id}/restore",
        response_model=CategoryMutationResponse,
        operation_id="restoreExpenseCategory",
    )
    def restore_category(category_id: UUID, data: CategoryLifecycleInput):
        ready(True)
        return invoke(
            lambda: service.restore_category(
                str(category_id),
                VoidCommand(data.confirmed, data.reason),
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    @router.get(
        "/api/expense-categories/operations/by-key/{key}",
        response_model=CategoryMutationResponse,
        operation_id="getExpenseCategoryOperationByKey",
    )
    def category_operation_by_key(key: UUID):
        ready()
        return invoke(lambda: service.category_operation_by_key(str(key)))

    @router.get(
        "/api/expense-categories/operations/{operation_id}",
        response_model=CategoryMutationResponse,
        operation_id="getExpenseCategoryOperation",
    )
    def category_operation(operation_id: UUID):
        ready()
        return invoke(lambda: service.category_operation(str(operation_id)))

    @router.post(
        "/api/expenses",
        response_model=ExpenseMutationResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="recordExpense",
    )
    def record_expense(data: ExpenseInput):
        ready(True)
        return invoke(
            lambda: service.record_expense(
                ExpenseCreateCommand(
                    str(data.idempotencyKey),
                    str(data.propertyId),
                    str(data.categoryId),
                    data.paidByKind,
                    data.paidOn.isoformat(),
                    data.amount,
                    data.currencyCode,
                    data.description,
                    str(data.spaceId) if data.spaceId else None,
                    str(data.providerPartyId) if data.providerPartyId else None,
                    data.payeeName,
                    str(data.paidByPartyId) if data.paidByPartyId else None,
                    data.reference,
                    data.notes,
                    str(data.replacesExpenseId) if data.replacesExpenseId else None,
                    data.duplicateConfirmed,
                    data.historicalEntryConfirmed,
                    data.historicalEntryReason,
                ),
                expected_revision=data.expectedRevision,
            )
        )

    @router.get("/api/expenses", response_model=ExpensePageResponse, operation_id="listExpenses")
    def expenses(
        propertyId: UUID | None = None,
        spaceId: UUID | None = None,
        categoryId: UUID | None = None,
        providerPartyId: UUID | None = None,
        paidByKind: Literal["local_operator", "party"] | None = None,
        paidByPartyId: UUID | None = None,
        paidFrom: date | None = None,
        paidTo: date | None = None,
        hasEvidence: bool | None = None,
        includeVoided: bool = False,
        cursor: str | None = None,
        pageSize: int = Query(100, ge=1, le=500),
    ):
        ready()
        return invoke(
            lambda: service.list_expenses(
                ExpenseQueryCommand(
                    property_id=str(propertyId) if propertyId else None,
                    space_id=str(spaceId) if spaceId else None,
                    category_id=str(categoryId) if categoryId else None,
                    provider_party_id=str(providerPartyId) if providerPartyId else None,
                    paid_by_kind=paidByKind,
                    paid_by_party_id=str(paidByPartyId) if paidByPartyId else None,
                    paid_from=paidFrom.isoformat() if paidFrom else None,
                    paid_to=paidTo.isoformat() if paidTo else None,
                    has_evidence=hasEvidence,
                    include_voided=includeVoided,
                    cursor=cursor,
                    page_size=pageSize,
                )
            )
        )

    @router.get(
        "/api/expenses/{expense_id}", response_model=ExpenseResponse, operation_id="getExpense"
    )
    def expense(expense_id: UUID):
        ready()
        return invoke(lambda: service.expense(str(expense_id)))

    @router.patch(
        "/api/expenses/{expense_id}",
        response_model=ExpenseMutationResponse,
        operation_id="patchExpense",
    )
    def patch_expense(expense_id: UUID, data: ExpensePatchInput):
        ready(True)
        fields = frozenset(
            {
                {"categoryId": "category_id", "notes": "notes"}[name]
                for name in data.model_fields_set
                if name in {"categoryId", "notes"}
            }
        )
        return invoke(
            lambda: service.patch_expense(
                str(expense_id),
                ExpensePatchCommand(
                    fields,
                    str(data.categoryId) if data.categoryId else None,
                    data.notes,
                    data.categoryChangeReason,
                    data.historicalEntryConfirmed,
                    data.historicalEntryReason,
                ),
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    @router.post(
        "/api/expenses/{expense_id}/void",
        response_model=ExpenseMutationResponse,
        operation_id="voidExpense",
    )
    def void_expense(expense_id: UUID, data: ExpenseVoidInput):
        ready(True)
        return invoke(
            lambda: service.void_expense(
                str(expense_id),
                VoidCommand(data.confirmed, data.reason),
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    @router.post(
        "/api/expenses/{expense_id}/refunds",
        response_model=RefundMutationResponse,
        status_code=201,
        operation_id="recordExpenseRefund",
    )
    def record_refund(expense_id: UUID, data: RefundInput):
        ready(True)
        return invoke(
            lambda: service.record_refund(
                str(expense_id),
                RefundCreateCommand(
                    str(data.idempotencyKey),
                    data.receivedOn.isoformat(),
                    data.amount,
                    data.currencyCode,
                    data.notes,
                    str(data.replacesRefundId) if data.replacesRefundId else None,
                ),
                expected_revision=data.expectedRevision,
            )
        )

    @router.post(
        "/api/expense-refunds/{refund_id}/void",
        response_model=RefundMutationResponse,
        operation_id="voidExpenseRefund",
    )
    def void_refund(refund_id: UUID, data: ExpenseVoidInput):
        ready(True)
        return invoke(
            lambda: service.void_refund(
                str(refund_id),
                VoidCommand(data.confirmed, data.reason),
                expected_revision=data.expectedRevision,
                idempotency_key=str(data.idempotencyKey),
            )
        )

    return router
