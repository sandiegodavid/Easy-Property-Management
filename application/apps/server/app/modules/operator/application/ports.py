"""OPS persistence and runtime ports; no database connection reaches use cases."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, TypeVar

from app.modules.operator.domain.models import Preferences

Result = TypeVar("Result")


@dataclass(frozen=True)
class RuntimeIdentity:
    state: str
    workspace_id: str | None
    epoch: str
    can_write: bool
    reason_code: str | None = None


class RecoveryReferences(Protocol):
    def validate(self, connection, value: Mapping) -> str: ...
    def resolve_attempt(
        self, connection, form_key: str, key: str, request_fingerprint: str
    ) -> Mapping | None: ...


class OperatorTransaction(Protocol):
    def source_marker(self) -> str: ...
    def preferences(self) -> Preferences: ...
    def save_preferences(self, value: Preferences) -> None: ...
    def operation(self, key: str) -> Mapping | None: ...
    def insert_operation(self, value: Mapping) -> None: ...
    def recovery(self, record_id: str) -> Mapping | None: ...
    def save_recovery(self, value: Mapping) -> None: ...
    def active_recovery_count(self) -> int: ...
    def recovery_page(
        self, *, limit: int, after: tuple[str, str] | None
    ) -> tuple[int, list[Mapping]]: ...
    def expired_recovery(self, now: str, limit: int) -> list[Mapping]: ...
    def validate_recovery(self, value: Mapping) -> str: ...
    def resolve_attempt(self, value: Mapping) -> Mapping | None: ...
    def record_change(
        self,
        *,
        entity_type: str,
        entity_id: str,
        action: str,
        before: Mapping | None,
        after: Mapping,
        correlation_id: str,
        occurred_at: datetime,
    ) -> None: ...


class OperatorUnitOfWork(Protocol):
    def read(self, operation: Callable[[OperatorTransaction], Result]) -> Result: ...
    def write(self, operation: Callable[[OperatorTransaction], Result]) -> Result: ...
