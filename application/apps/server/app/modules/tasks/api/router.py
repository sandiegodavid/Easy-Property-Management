from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, StrictBool, model_validator
from app.modules.tasks.application.service import TaskConflictError, TaskError, TaskNotFoundError, TaskService
from app.modules.workspace.application.runtime import WorkspaceRuntime


def build_router(service: TaskService, runtime: WorkspaceRuntime) -> APIRouter:
    router = APIRouter(prefix="/api/tasks", tags=["tasks"])
    def ready(write: bool = False) -> None:
        if not runtime.ready or runtime.error: raise HTTPException(503, str(runtime.error or "Workspace is not ready."))
        if write and not runtime.can_write: raise HTTPException(503, "Workspace writer lock is unavailable.")
    def invoke(fn):
        try: return fn()
        except TaskNotFoundError as error: raise HTTPException(404, str(error)) from error
        except TaskConflictError as error: raise HTTPException(409, str(error)) from error
        except TaskError as error: raise HTTPException(400, str(error)) from error
    @router.post("", status_code=status.HTTP_201_CREATED)
    def create(data: TaskCreateRequest): ready(True); return invoke(lambda: service.create(data.model_dump()).to_dict())
    @router.get("")
    def list_tasks(status: str | None = None): ready(); return invoke(lambda: [task.to_dict() for task in service.list(status)])
    @router.get("/summary")
    def summary(): ready(); return service.summary()
    @router.get("/{task_id}")
    def get(task_id: str): ready(); return invoke(lambda: service.get(task_id).to_dict())
    @router.post("/{task_id}/complete")
    def complete(task_id: str, data: OutcomeRequest | None = None): ready(True); return invoke(lambda: service.transition(task_id, "completed", data.outcomeNote if data else None).to_dict())
    @router.post("/{task_id}/start")
    def start(task_id: str): ready(True); return invoke(lambda: service.transition(task_id, "in_progress").to_dict())
    @router.post("/{task_id}/reopen")
    def reopen(task_id: str): ready(True); return invoke(lambda: service.transition(task_id, "open").to_dict())
    @router.post("/{task_id}/cancel")
    def cancel(task_id: str, data: OutcomeRequest | None = None): ready(True); return invoke(lambda: service.transition(task_id, "cancelled", data.outcomeNote if data else None).to_dict())
    @router.post("/{task_id}/reminders", status_code=status.HTTP_201_CREATED)
    def add_reminder(task_id: str, data: ReminderRequest): ready(True); return invoke(lambda: service.add_reminder(task_id, data.remindAtUtc).to_dict())
    @router.post("/{task_id}/reminders/{reminder_id}/acknowledge")
    def acknowledge(task_id: str, reminder_id: str): ready(True); return invoke(lambda: service.set_reminder_status(task_id, reminder_id, "acknowledged").to_dict())
    @router.post("/{task_id}/reminders/{reminder_id}/dismiss")
    def dismiss(task_id: str, reminder_id: str): ready(True); return invoke(lambda: service.set_reminder_status(task_id, reminder_id, "dismissed").to_dict())
    return router
class TaskCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=240); notes: str | None = None
    status: str = "open"; priority: str = "normal"; dueAtUtc: str | None = None; dueTimezone: str | None = None; isAllDay: StrictBool = False
    relatedEntityType: str | None = None; relatedEntityId: str | None = None; relatedLabel: str | None = None
    @model_validator(mode="after")
    def linked_pair(self):
        related_type = self.relatedEntityType.strip() if self.relatedEntityType is not None else None
        related_id = self.relatedEntityId.strip() if self.relatedEntityId is not None else None
        related_label = self.relatedLabel.strip() if self.relatedLabel is not None else None
        if (related_type is None) != (related_id is None) or related_type == "" or related_id == "":
            raise ValueError("relatedEntityType and relatedEntityId must be nonblank and supplied together")
        if related_label == "":
            raise ValueError("relatedLabel must be nonblank when supplied")
        if related_label is not None and related_type is None:
            raise ValueError("relatedLabel requires relatedEntityType and relatedEntityId")
        return self
class OutcomeRequest(BaseModel): outcomeNote: str | None = None
class ReminderRequest(BaseModel): remindAtUtc: str = Field(min_length=1)
