"""Narrow transaction-aware ports exposed by INGEST-001."""
from __future__ import annotations
from typing import Any, Callable, Protocol, TypeVar
T = TypeVar("T")


class IntakeSourceReader(Protocol):
    def source_projection(self, connection: Any, source_id: str) -> dict[str, object] | None: ...


class IntakeAttentionOperations(Protocol):
    def transition_attention(self, connection: Any, source_id: str, *, from_status: str, to_status: str, reason: str, correlation_id: str) -> None: ...


class IntakeAdmissionPort(Protocol):
    def admit(self, command: Any) -> dict[str, object]: ...


class IntakeUnitOfWork(Protocol):
    def write(self, operation: Callable[[Any], T]) -> T: ...
    def read(self, operation: Callable[[Any], T]) -> T: ...
