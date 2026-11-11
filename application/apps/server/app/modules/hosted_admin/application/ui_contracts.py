"""H01.6 strict Admin-lite presentation contracts; no routes or repositories."""

from typing import Annotated, Literal

from pydantic import Field, StrictStr, model_validator

from app.modules.hosted_admin.application.pilot_contracts import AdminResult
from app.platform.hosted_contracts.authority import ObservationPage, ObservationQuery
from app.platform.hosted_contracts.operations import OperationOutcome, OperationState
from app.platform.hosted_contracts.semantic import SemanticRequest, semantic_hash
from app.platform.hosted_contracts.ui_states import (
    Actions,
    FreeUsage,
    Gate,
    Preservation,
    Protection,
    Section,
)
from app.platform.hosted_contracts.values import (
    CanonicalId,
    Contract,
    DisplayName,
    Reference,
    PublicSlug,
    Revision,
)


class Access(Contract):
    effective_enabled: bool
    access_epoch: Revision
    source_proof_ref: Reference


class OperatorSummary(Contract):
    operator_id: CanonicalId
    workspace_id: CanonicalId
    display_name: DisplayName
    slug: PublicSlug
    setup_state: Literal[
        "pending", "preparing", "ready_for_claim", "active", "needs_attention", "retired"
    ]
    desired_enabled: bool
    access: Section[Access]
    usage: Section[FreeUsage]
    protection: Section[Protection]
    release_id: CanonicalId
    operation: OperationOutcome[AdminResult] | None = None
    actions: Actions


class AdminFilters(SemanticRequest):
    search: Annotated[StrictStr, Field(max_length=120)] = ""
    setup_state: Literal[
        "all", "pending", "preparing", "ready_for_claim", "active", "needs_attention", "retired"
    ] = "all"
    access_state: Literal["all", "enabled", "disabled", "unknown"] = "all"


class AdminList(Contract):
    surface: Literal["admin_list"] = "admin_list"
    delivery_owner: Literal["H04"] = "H04"
    query: ObservationQuery
    filters: AdminFilters = AdminFilters()
    directory: Section[ObservationPage[OperatorSummary]]
    read_strategy: Literal["registry_projection_set_based"] = "registry_projection_set_based"
    source_refresh: Literal["explicit_async_operation"] = "explicit_async_operation"
    preservation: Preservation = Preservation()
    actions: Actions

    @model_validator(mode="after")
    def bounded_page(self):
        page = self.directory.data
        filter_hash = semantic_hash(self.filters)
        if self.query.cursor is not None and (
            self.query.cursor.context.filter_hash != filter_hash
            or self.query.cursor.context.endpoint != "admin_operators"
        ):
            raise ValueError("Filter/endpoint changes require a fresh directory continuation.")
        if self.query.scope.kind != "deployment":
            raise ValueError("Admin directory requires the deployment scope.")
        if page is not None:
            if len(page.items) > self.query.limit:
                raise ValueError("Directory exceeds the requested page bound.")
            if page.continuation is not None and (
                page.continuation.context.filter_hash != filter_hash
                or page.continuation.context.endpoint != "admin_operators"
                or page.continuation.context.deployment_id != self.query.deployment_id
                or page.continuation.context.scope != self.query.scope
                or page.continuation.limit != self.query.limit
            ):
                raise ValueError("Directory continuation changed its deployment/scope/page size.")
        if (
            page is not None
            and self.query.cursor is not None
            and (
                self.query.cursor.context.as_of != page.freshness.as_of
                or self.query.cursor.context.source_revision != page.freshness.source_revision
            )
        ):
            raise ValueError("Continuation cannot silently change capture/source revision.")
        return self


class AddDraft(Contract):
    """Raw bounded form input intentionally retains invalid values until submit."""

    display_name: Annotated[StrictStr, Field(max_length=120)] = ""
    email: Annotated[StrictStr, Field(max_length=254)] = ""
    slug: Annotated[StrictStr, Field(max_length=63)] = ""
    support_contact: Annotated[StrictStr, Field(max_length=254)] = ""
    release_id: Annotated[StrictStr, Field(max_length=36)] = ""
    initial_data: Literal["empty", "synthetic"] = "empty"
    seed_bundle: Annotated[StrictStr, Field(max_length=1024)] = ""
    plan: Literal["free"] = "free"
    usable_bytes: Literal[50_000_000] = 50_000_000


class FieldIssue(Contract):
    field: Literal["display_name", "email", "slug", "support_contact", "release_id", "seed_bundle"]
    message: Annotated[StrictStr, Field(min_length=1, max_length=1000)]


class AdminAdd(Contract):
    surface: Literal["admin_add"] = "admin_add"
    delivery_owner: Literal["H04"] = "H04"
    draft: AddDraft
    state: Literal["editing", "invalid", "conflicted", "submitting", "outcome_unknown", "completed"]
    issues: Annotated[tuple[FieldIssue, ...], Field(max_length=6)] = ()
    expected_revision: Revision | None = None
    current_revision: Revision | None = None
    original_outcome: OperationOutcome[AdminResult] | None = None
    preservation: Preservation = Preservation()
    actions: Actions

    @model_validator(mode="after")
    def retained_form(self):
        if self.state == "invalid" and not self.issues:
            raise ValueError("Invalid input needs field guidance and retained draft values.")
        if self.state == "conflicted" and (
            self.expected_revision is None
            or self.current_revision is None
            or self.current_revision <= self.expected_revision
        ):
            raise ValueError("Conflict needs expected/current revisions without resetting input.")
        outcomes = {
            "submitting": {OperationState.PENDING, OperationState.RUNNING},
            "outcome_unknown": {OperationState.UNKNOWN},
            "completed": {OperationState.SUCCEEDED},
        }
        if self.state in outcomes and (
            self.original_outcome is None or self.original_outcome.state not in outcomes[self.state]
        ):
            raise ValueError("Submission state must retain its matching original operation.")
        return self


class Readiness(Contract):
    state: Literal["pending", "ready", "failed", "unavailable"]
    checks: Annotated[tuple[Gate, ...], Field(min_length=5, max_length=5)]

    @model_validator(mode="after")
    def complete_readiness(self):
        required = {"isolation", "schema", "routing", "protection", "binding"}
        if {item.name for item in self.checks} != required:
            raise ValueError("Readiness must retain every required independent check.")
        states = {item.state for item in self.checks}
        if self.state == "ready" and states != {"passed"}:
            raise ValueError("Pending/unknown checks are not ready.")
        return self


class AdminDetail(Contract):
    surface: Literal["admin_detail"] = "admin_detail"
    delivery_owner: Literal["H04"] = "H04"
    operator: OperatorSummary
    readiness: Section[Readiness]
    refresh_operation: OperationOutcome[AdminResult] | None = None
    source_refresh: Literal["explicit_async_operation"] = "explicit_async_operation"
    preservation: Preservation = Preservation()
    actions: Actions
