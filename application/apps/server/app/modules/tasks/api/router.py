from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query, status
from pydantic import (
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    model_validator,
)

from app.modules.tasks.application.waiting import FollowUpQuery, WaitingCommand, WaitingError
from app.modules.tasks.application.waiting_service import TaskWaitingService

from app.platform.api_errors import api_problem, domain_problem, workspace_unavailable

from app.modules.tasks.application.service import (
    TaskConflictError,
    TaskError,
    TaskNotFoundError,
    TaskService,
)
from app.modules.workspace.application.runtime import WorkspaceRuntime


def build_router(
    service: TaskService, runtime: WorkspaceRuntime, waiting: TaskWaitingService | None = None
) -> APIRouter:
    router = APIRouter(prefix="/api/tasks", tags=["tasks"])

    def ready(write: bool = False) -> None:
        if not runtime.ready or runtime.error:
            raise workspace_unavailable(str(runtime.error or "Workspace is not ready."))
        if write and not runtime.can_write:
            raise workspace_unavailable("Workspace writer lock is unavailable.")

    def invoke(fn):
        try:
            return fn()
        except WaitingError as error:
            details = (
                {"currentRevision": error.current_revision}
                if getattr(error, "current_revision", None) is not None
                else {}
            )
            raise domain_problem(error, status_code=error.status_code, **details) from error
        except TaskNotFoundError as error:
            raise domain_problem(error, status_code=404, code="task_not_found") from error
        except TaskConflictError as error:
            raise domain_problem(error, status_code=409, code="task_conflict") from error
        except TaskError as error:
            raise domain_problem(error, status_code=400, code="task_validation") from error

    @router.post("", status_code=status.HTTP_201_CREATED, response_model=TaskResponse)
    def create(data: TaskCreateRequest):
        ready(True)
        return invoke(lambda: service.view(service.create(data.model_dump())))

    @router.get("", response_model=TaskPageResponse)
    def list_tasks(
        status: str | None = None,
        due: str | None = None,
        priority: str | None = None,
        includeVoided: bool = False,
        relatedEntityType: str | None = None,
        relatedEntityId: str | None = None,
        pageSize: int = Query(100, ge=1, le=500),
        cursor: str | None = None,
    ):
        ready()
        if (relatedEntityType is None) != (relatedEntityId is None):
            raise api_problem(
                422,
                "task_validation",
                "relatedEntityType and relatedEntityId must be supplied together.",
            )
        now = service.instant()
        tasks, next_cursor = invoke(
            lambda: service.page(
                status=status,
                due=due,
                priority=priority,
                include_voided=includeVoided,
                related_entity_type=relatedEntityType,
                related_entity_id=relatedEntityId,
                page_size=pageSize,
                cursor=cursor,
                as_of=now,
            )
        )
        return {
            "items": [service.view(task, now) for task in tasks],
            "nextCursor": next_cursor,
            "asOf": now.isoformat(),
        }

    @router.get("/summary", response_model=TaskSummaryResponse, operation_id="getTaskSummary")
    def summary(limitPerBucket: int = Query(20, ge=1, le=100)):
        ready()
        return invoke(lambda: service.summary(limit_per_bucket=limitPerBucket))

    @router.get("/follow-ups", response_model=FollowUpPageResponse, operation_id="getTaskFollowUps")
    def follow_ups(
        state: Literal["scheduled", "due", "overdue", "unscheduled"] | None = None,
        actionable: bool | None = None,
        priority: Literal["low", "normal", "high", "urgent"] | None = None,
        relatedEntityType: str | None = None,
        relatedEntityId: UUID | None = None,
        limit: int = Query(50, ge=1, le=100),
        cursor: str | None = None,
    ):
        ready()
        if waiting is None:
            raise workspace_unavailable("Follow-up service is unavailable.")
        return invoke(
            lambda: waiting.follow_ups(
                FollowUpQuery(
                    state,
                    actionable,
                    priority,
                    relatedEntityType,
                    str(relatedEntityId) if relatedEntityId else None,
                    limit,
                    cursor,
                )
            )
        )

    @router.get(
        "/waiting-operations/{key}",
        response_model=WaitingMutationResponse,
        operation_id="getTaskWaitingOperation",
    )
    def operation(key: UUID):
        ready()
        if waiting is None:
            raise workspace_unavailable("Follow-up service is unavailable.")
        return invoke(lambda: waiting.operation(str(key)))

    def waiting_change(task_id, data, action):
        ready(True)
        if waiting is None:
            raise workspace_unavailable("Follow-up service is unavailable.")
        return invoke(
            lambda: waiting.mutate(
                WaitingCommand(
                    task_id=str(task_id),
                    action=action,
                    expected_revision=data.expectedRevision,
                    idempotency_key=str(data.idempotencyKey),
                    kind=getattr(data, "waitingForKind", None),
                    label=getattr(data, "waitingForLabel", None),
                    follow_up_at=data.followUpAt.isoformat()
                    if getattr(data, "followUpAt", None)
                    else None,
                    timezone=getattr(data, "followUpTimezone", None),
                    confirmed=getattr(data, "confirmed", False),
                    clear_follow_up=getattr(data, "clearFollowUp", False),
                )
            )
        )

    @router.post(
        "/{task_id}/waiting", response_model=WaitingMutationResponse, operation_id="setTaskWaiting"
    )
    def set_waiting(task_id: UUID, data: WaitingSetRequest):
        return waiting_change(task_id, data, "set")

    @router.post(
        "/{task_id}/waiting/clear",
        response_model=WaitingMutationResponse,
        operation_id="clearTaskWaiting",
    )
    def clear_waiting(task_id: UUID, data: WaitingClearRequest):
        return waiting_change(task_id, data, "clear")

    @router.post(
        "/{task_id}/waiting/follow-up",
        response_model=WaitingMutationResponse,
        operation_id="rescheduleTaskFollowUp",
    )
    def reschedule(task_id: UUID, data: FollowUpRequest):
        return waiting_change(task_id, data, "reschedule")

    @router.get("/{task_id}", response_model=TaskResponse)
    def get(task_id: str):
        ready()
        return invoke(lambda: service.view(service.get(task_id)))

    @router.post("/{task_id}/complete")
    def complete(task_id: str, data: OutcomeRequest | None = None):
        ready(True)
        return invoke(
            lambda: service.transition(
                task_id, "completed", data.outcomeNote if data else None
            ).to_dict()
        )

    @router.post("/{task_id}/start")
    def start(task_id: str):
        ready(True)
        return invoke(lambda: service.transition(task_id, "in_progress").to_dict())

    @router.post("/{task_id}/reopen")
    def reopen(task_id: str):
        ready(True)
        return invoke(lambda: service.transition(task_id, "open").to_dict())

    @router.post("/{task_id}/cancel")
    def cancel(task_id: str, data: OutcomeRequest | None = None):
        ready(True)
        return invoke(
            lambda: service.transition(
                task_id, "cancelled", data.outcomeNote if data else None
            ).to_dict()
        )

    @router.post("/{task_id}/reminders", status_code=status.HTTP_201_CREATED)
    def add_reminder(task_id: str, data: ReminderRequest):
        ready(True)
        return invoke(lambda: service.add_reminder(task_id, data.remindAtUtc).to_dict())

    @router.post("/{task_id}/reminders/{reminder_id}/acknowledge")
    def acknowledge(task_id: str, reminder_id: str):
        ready(True)
        return invoke(
            lambda: service.set_reminder_status(task_id, reminder_id, "acknowledged").to_dict()
        )

    @router.post("/{task_id}/reminders/{reminder_id}/dismiss")
    def dismiss(task_id: str, reminder_id: str):
        ready(True)
        return invoke(
            lambda: service.set_reminder_status(task_id, reminder_id, "dismissed").to_dict()
        )

    return router


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TaskResponse(Contract):
    id: str
    title: str
    notes: str | None
    status: Literal["open", "in_progress", "completed", "cancelled"]
    priority: Literal["low", "normal", "high", "urgent"]
    dueAtUtc: datetime | None
    dueTimezone: str | None
    isAllDay: bool
    completedAtUtc: datetime | None
    cancelledAtUtc: datetime | None
    outcomeNote: str | None
    relatedEntityType: str | None
    relatedEntityId: str | None
    relatedLabel: str | None
    createdAtUtc: datetime
    updatedAtUtc: datetime
    revision: int
    waitingForKind: str | None
    waitingForLabel: str | None
    followUpAt: AwareDatetime | None
    followUpTimezone: str | None
    waitingSetAtUtc: AwareDatetime | None
    waitingClearedAtUtc: AwareDatetime | None
    isWaiting: bool
    waitingFor: "WaitingForResponse | None"
    followUpState: Literal["scheduled", "due", "overdue", "unscheduled"] | None
    followUpDueToday: bool
    followUpActionable: bool
    taskDeadlineState: Literal["none", "overdue", "today", "upcoming", "inactive"]
    asOf: AwareDatetime


class DueReminderResponse(Contract):
    id: str
    taskId: str
    remindAtUtc: datetime
    status: Literal["pending", "acknowledged", "dismissed", "sent"]
    acknowledgedAtUtc: datetime | None
    dismissedAtUtc: datetime | None
    createdAtUtc: datetime
    taskTitle: str
    taskDueAtUtc: datetime | None
    taskDueTimezone: str | None
    taskIsAllDay: bool
    relatedLabel: str | None
    taskRevision: int
    taskWaitingForKind: str | None
    taskWaitingForLabel: str | None
    taskFollowUpAt: AwareDatetime | None
    taskFollowUpTimezone: str | None
    taskFollowUpState: Literal["scheduled", "due", "overdue", "unscheduled"] | None
    taskFollowUpDueToday: bool
    taskFollowUpActionable: bool
    taskDeadlineState: Literal["none", "overdue", "today", "upcoming", "inactive"]


class TaskSummaryResponse(Contract):
    asOf: AwareDatetime
    overdue: list[TaskResponse]
    overdueTotal: int
    today: list[TaskResponse]
    todayTotal: int
    next7days: list[TaskResponse]
    next7daysTotal: int
    dueReminders: list[DueReminderResponse]
    dueRemindersTotal: int


class TaskPageResponse(Contract):
    items: list[TaskResponse]
    nextCursor: str | None
    asOf: AwareDatetime


class TaskCreateRequest(Contract):
    title: str = Field(min_length=1, max_length=240)
    notes: str | None = None
    status: str = "open"
    priority: str = "normal"
    dueAtUtc: str | None = None
    dueTimezone: str | None = None
    isAllDay: StrictBool = False
    relatedEntityType: str | None = None
    relatedEntityId: str | None = None
    relatedLabel: str | None = None

    @model_validator(mode="after")
    def linked_pair(self):
        related_type = (
            self.relatedEntityType.strip() if self.relatedEntityType is not None else None
        )
        related_id = self.relatedEntityId.strip() if self.relatedEntityId is not None else None
        related_label = self.relatedLabel.strip() if self.relatedLabel is not None else None
        if (related_type is None) != (related_id is None) or related_type == "" or related_id == "":
            raise ValueError(
                "relatedEntityType and relatedEntityId must be nonblank and supplied together"
            )
        if related_label == "":
            raise ValueError("relatedLabel must be nonblank when supplied")
        if related_label is not None and related_type is None:
            raise ValueError("relatedLabel requires relatedEntityType and relatedEntityId")
        return self


class OutcomeRequest(Contract):
    outcomeNote: str | None = None


class ReminderRequest(Contract):
    remindAtUtc: str = Field(min_length=1)


class WaitingForResponse(Contract):
    kind: Literal["person", "organization", "event", "other"]
    label: str


class WaitingMutationResponse(TaskResponse):
    operationId: UUID


class FollowUpPageResponse(Contract):
    items: list[TaskResponse]
    matchingTotal: int
    nextCursor: str | None
    asOf: AwareDatetime
    evaluatedAt: AwareDatetime
    filters: "FollowUpFiltersResponse"


class FollowUpFiltersResponse(Contract):
    state: Literal["scheduled", "due", "overdue", "unscheduled"] | None
    actionable: bool | None
    priority: Literal["low", "normal", "high", "urgent"] | None
    related_entity_type: str | None
    related_entity_id: str | None


class WaitingRequest(Contract):
    expectedRevision: StrictInt = Field(ge=1)
    idempotencyKey: UUID


def _offset_iso_instant(value: object) -> str:
    message = "Follow-up requires an offset-bearing ISO timestamp string."
    if not isinstance(value, str):
        raise ValueError(message)
    try:
        instant = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(message) from error
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError(message)
    return value


FollowUpInstant = Annotated[AwareDatetime, BeforeValidator(_offset_iso_instant)]


class WaitingSetRequest(WaitingRequest):
    waitingForKind: Literal["person", "organization", "event", "other"]
    waitingForLabel: str = Field(min_length=1, max_length=255)
    followUpAt: FollowUpInstant | None = None
    followUpTimezone: str | None = None

    @model_validator(mode="after")
    def paired(self):
        if (self.followUpAt is None) != (self.followUpTimezone is None):
            raise ValueError("Follow-up date and timezone must be paired.")
        return self


class WaitingClearRequest(WaitingRequest):
    confirmed: StrictBool

    @model_validator(mode="after")
    def confirmation(self):
        if not self.confirmed:
            raise ValueError("confirmed=true is required.")
        return self


class FollowUpRequest(WaitingRequest):
    followUpAt: FollowUpInstant | None = None
    followUpTimezone: str | None = None
    clearFollowUp: StrictBool = False

    @model_validator(mode="after")
    def exclusive(self):
        if (self.followUpAt is None) != (self.followUpTimezone is None) or self.clearFollowUp == (
            self.followUpAt is not None
        ):
            raise ValueError("Supply paired date/zone or clearFollowUp=true.")
        return self
