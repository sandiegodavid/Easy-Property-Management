"""Narrow transaction-aware ports exposed by INGEST-001."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Collection, Literal, Mapping, Protocol, TypeVar

from app.modules.intake.domain.models import (
    AttentionTransition,
    IntakeAdmissionContext,
    IntakeError,
    bounded,
    uuid,
)

T = TypeVar("T")
MAX_INTAKE_SOURCE_BATCH = 200
MAX_EVIDENCE_HISTORY = 100
MAX_EVIDENCE_ATTACHMENTS = 20


@dataclass(frozen=True)
class IntakeEvidenceDetailRequest:
    """Trusted consumer request for a durable, audited exact-revision read."""

    source_id: str
    revision_id: str
    actor_kind: Literal["local_operator", "system", "connector", "ai_assistant"]
    actor_reference: str | None
    reason: str
    correlation_id: str
    max_history: int = MAX_EVIDENCE_HISTORY
    max_attachments: int = MAX_EVIDENCE_ATTACHMENTS

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_id", uuid(self.source_id, "sourceId"))
        object.__setattr__(self, "revision_id", uuid(self.revision_id, "revisionId"))
        object.__setattr__(self, "correlation_id", uuid(self.correlation_id, "correlationId"))
        if self.actor_kind not in {"local_operator", "system", "connector", "ai_assistant"}:
            raise IntakeError("actorKind is invalid.")
        object.__setattr__(self, "actor_reference", bounded(self.actor_reference, "actorReference", 500))
        if self.actor_kind in {"connector", "ai_assistant"} and self.actor_reference is None:
            raise IntakeError("actorReference is required for connected actors.")
        reason = bounded(self.reason, "reason", 64, required=True)
        if not reason.replace("_", "").isalnum() or reason.lower() != reason:
            raise IntakeError("reason must be a non-sensitive identifier.")
        object.__setattr__(self, "reason", reason)
        for name, maximum in (("max_history", MAX_EVIDENCE_HISTORY), ("max_attachments", MAX_EVIDENCE_ATTACHMENTS)):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
                raise IntakeError(f"{name} is invalid.")

if TYPE_CHECKING:
    from app.modules.intake.application.service import IntakeAdmissionCommand


class IntakeSourceReader(Protocol):
    def source_projection(self, connection: Any, source_id: str) -> dict[str, object] | None: ...
    def source_projections(self, connection: Any, source_ids: Collection[str]) -> Mapping[str, Mapping[str, object]]: ...
    def revision_projection(self, connection: Any, source_id: str, revision_id: str) -> Mapping[str, object] | None: ...


class IntakeEvidenceDetailPort(Protocol):
    def evidence_detail(self, request: IntakeEvidenceDetailRequest) -> Mapping[str, object]: ...


class IntakeAttachmentBatch(Protocol):
    def add(self, source: Path, original_name: str, media_type: str | None, *, entity_type: str,
            entity_id: str, purpose: str, correlation_id: str, owning_workflow: bool = False) -> Any: ...
    def commit(self) -> None: ...
    def rollback(self, original_failure: BaseException | None = None) -> None: ...


class IntakeFileOperations(Protocol):
    def attachment_batch(self, connection: Any) -> IntakeAttachmentBatch: ...


class IntakeAttentionOperations(Protocol):
    """Apply one reasoned attention transition on the caller's transaction."""
    def transition_attention(
        self,
        connection: Any,
        transition: AttentionTransition,
    ) -> dict[str, object]: ...


class IntakeTransaction(Protocol):
    """Persistence vocabulary for one retained-source transaction."""
    def file_connection(self) -> Any: ...
    def source(self, source_id: str) -> dict[str, object] | None: ...
    def revision(self, revision_id: str) -> dict[str, object] | None: ...
    def operation(self, key: str) -> dict[str, object] | None: ...
    def exact_source(self, origin: str, scope: str, kind: str, external_id: str) -> dict[str, object] | None: ...
    def exact_source_for_evidence(self, current_source_id: str, origin: str, scope: str, kind: str,
                                  external_id: str, content_fingerprint: str) -> dict[str, object] | None: ...
    def duplicate_source(self, content_fingerprint: str, source_id: str) -> str | None: ...
    def insert_source(self, values: dict[str, object]) -> None: ...
    def update_source(self, source_id: str, values: dict[str, object]) -> None: ...
    def insert_revision(self, values: dict[str, object]) -> None: ...
    def replace_revision(self, revision_id: str, values: dict[str, object]) -> None: ...
    def insert_attachment(self, values: dict[str, object]) -> None: ...
    def copy_attachments(self, from_revision_id: str, to_revision_id: str) -> None: ...
    def insert_operation(self, values: dict[str, object]) -> None: ...
    def insert_candidate(self, values: dict[str, object]) -> None: ...
    def source_projection(self, source_id: str) -> dict[str, object] | None: ...
    def detail_projection(
        self,
        source_id: str,
        pending_operation: dict[str, object] | None = None,
    ) -> dict[str, object] | None: ...
    def evidence_detail_projection(self, source_id: str, revision_id: str, *, max_history: int,
                                   max_attachments: int) -> Mapping[str, object] | None: ...
    def list_projections(self, **filters: Any) -> tuple[list[dict[str, object]], tuple[str, str] | None]: ...
    def record(self, *, entity_type: str, entity_id: str, action: str, before: dict | None,
               after: dict | None, reason: str, correlation_id: str, actor_kind: str = "local_operator",
               actor_reference: str | None = None) -> None: ...


class IntakeAdmissionPort(Protocol):
    """Internal-only admission boundary for authenticated transports."""
    def admit(self, command: IntakeAdmissionCommand, context: IntakeAdmissionContext) -> dict[str, object]: ...


class IntakeUnitOfWork(Protocol):
    def write(self, operation: Callable[[IntakeTransaction], T]) -> T: ...
    def read(self, operation: Callable[[IntakeTransaction], T]) -> T: ...
