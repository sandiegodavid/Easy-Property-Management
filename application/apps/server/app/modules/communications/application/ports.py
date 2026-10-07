"""Application-owned contracts for communication persistence and context."""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from typing import TYPE_CHECKING, Any, Protocol, TypeVar

from app.modules.communications.domain.models import (
    Communication,
    CommunicationLink,
    CommunicationOperation,
    CommunicationParticipant,
)

if TYPE_CHECKING:
    from app.modules.communications.application.service import FollowUpInput

Result = TypeVar("Result")


class CommunicationLinkReader(Protocol):
    """Bounded, transaction-aware summaries for generic linked entities."""

    def summaries_for_entities(
        self,
        connection: Any,
        entity_type: str,
        entity_ids: Collection[str],
        limit_per_entity: int = 10,
    ) -> Mapping[str, list[Mapping[str, object]]]: ...


class CommunicationContextOperations(Protocol):
    def participant_snapshot(
        self, connection: Any, party_id: str, contact_method_id: str | None
    ) -> tuple[str, str | None]: ...
    def validate_link(self, connection: Any, entity_type: str, entity_id: str) -> str | None: ...
    def validate_retained_link(
        self, connection: Any, entity_type: str, entity_id: str
    ) -> str | None: ...
    def create_follow_up(
        self,
        connection: Any,
        *,
        communication: Communication,
        follow_up: FollowUpInput,
    ) -> dict[str, object]: ...
    def task_views(self, connection: Any, communication_id: str) -> list[dict[str, object]]: ...
    def matching_communication_ids_for_task_status(
        self, connection: Any, communication_ids: set[str], status: str
    ) -> set[str]: ...
    def validate_retained_participant(
        self, connection: Any, party_id: str, contact_method_id: str | None
    ) -> None: ...
    def validate_follow_up_task(
        self, connection: Any, communication_id: str, task_id: str
    ) -> None: ...
    def validate_communication_task_references(
        self, connection: Any, communication_ids: set[str]
    ) -> None: ...
    def link_context(
        self, connection: Any, entity_type: str, entity_id: str
    ) -> Mapping[str, object] | None: ...


class CommunicationTransaction(Protocol):
    def communication(self, communication_id: str) -> Communication | None: ...
    def participants(self, communication_id: str) -> list[CommunicationParticipant]: ...
    def links(self, communication_id: str) -> list[CommunicationLink]: ...
    def insert_communication(self, item: Communication) -> None: ...
    def replace_communication(self, item: Communication) -> None: ...
    def insert_participant(self, item: CommunicationParticipant) -> None: ...
    def insert_link(self, item: CommunicationLink) -> None: ...
    def replace_link(self, item: CommunicationLink) -> None: ...
    def delete_participants(self, communication_id: str) -> None: ...
    def delete_links(self, communication_id: str) -> None: ...
    def operation(self, idempotency_key: str) -> CommunicationOperation | None: ...
    def insert_operation(self, item: CommunicationOperation) -> None: ...
    def validate_participant(
        self, party_id: str, contact_method_id: str | None
    ) -> tuple[str, str | None]: ...
    def validate_link(self, entity_type: str, entity_id: str) -> str | None: ...
    def create_follow_up(
        self,
        *,
        communication: Communication,
        follow_up: FollowUpInput,
    ) -> dict[str, object]: ...
    def task_views(self, communication_id: str) -> list[dict[str, object]]: ...
    def link_context(self, entity_type: str, entity_id: str) -> Mapping[str, object] | None: ...
    def list_views(
        self,
        status: str | None,
        direction: str | None = None,
        channel: str | None = None,
        party_id: str | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
        limit: int = 100,
        cursor: tuple[str, str] | None = None,
        occurred_on_or_after: str | None = None,
        occurred_on_or_before: str | None = None,
        task_status: str | None = None,
    ) -> tuple[list[dict[str, object]], tuple[str, str] | None]: ...
    def record_change(
        self,
        *,
        entity_type: str,
        entity_id: str,
        action: str,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
        reason: str,
        correlation_id: str,
    ) -> None: ...


class CommunicationUnitOfWork(Protocol):
    def write(self, operation: Callable[[CommunicationTransaction], Result]) -> Result: ...
    def read(self, operation: Callable[[CommunicationTransaction], Result]) -> Result: ...
