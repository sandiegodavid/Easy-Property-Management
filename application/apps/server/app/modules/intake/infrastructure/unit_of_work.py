"""SQLite persistence adapter for the retained source aggregate."""
from __future__ import annotations
from pathlib import Path
from typing import Any, Callable, TypeVar
from datetime import UTC, datetime
from sqlalchemy import select
from app.modules.audit.application.recorder import AuditRecorder
from app.modules.intake.infrastructure.sqlalchemy_models import (IntakeDuplicateCandidateModel, IntakeEvidenceRevisionModel, IntakeRevisionFileLinkModel, IntakeSourceModel, IntakeSourceOperationModel)
from app.platform.sqlite_engine import create_sqlite_engine, immediate_transaction

T = TypeVar("T")


class SQLiteIntakeUnitOfWork:
    def __init__(self, database: Path, recorder: AuditRecorder) -> None:
        self.engine = create_sqlite_engine(database); self.recorder = recorder
    def write(self, operation: Callable[["SQLiteIntakeTransaction"], T]) -> T:
        with immediate_transaction(self.engine) as connection: return operation(SQLiteIntakeTransaction(connection, self.recorder))
    def read(self, operation: Callable[["SQLiteIntakeTransaction"], T]) -> T:
        with self.engine.connect() as connection: return operation(SQLiteIntakeTransaction(connection, self.recorder))


class SQLiteIntakeTransaction:
    def __init__(self, connection: Any, recorder: AuditRecorder) -> None: self.connection = connection; self.recorder = recorder
    def source(self, source_id: str): return self.connection.execute(select(IntakeSourceModel).where(IntakeSourceModel.id == source_id)).mappings().first()
    def revision(self, revision_id: str): return self.connection.execute(select(IntakeEvidenceRevisionModel).where(IntakeEvidenceRevisionModel.id == revision_id)).mappings().first()
    def operation(self, key: str): return self.connection.execute(select(IntakeSourceOperationModel).where(IntakeSourceOperationModel.idempotency_key == key)).mappings().first()
    def exact_source(self, origin: str, scope: str, kind: str, external_id: str):
        return self.connection.execute(select(IntakeSourceModel).where(IntakeSourceModel.origin_system == origin, IntakeSourceModel.account_scope_hash == scope, IntakeSourceModel.source_kind == kind, IntakeSourceModel.external_source_id == external_id)).mappings().first()
    def insert_source(self, values: dict[str, object]) -> None: self.connection.execute(IntakeSourceModel.__table__.insert().values(**values))
    def update_source(self, source_id: str, values: dict[str, object]) -> None: self.connection.execute(IntakeSourceModel.__table__.update().where(IntakeSourceModel.id == source_id).values(**values))
    def insert_revision(self, values: dict[str, object]) -> None: self.connection.execute(IntakeEvidenceRevisionModel.__table__.insert().values(**values))
    def insert_attachment(self, values: dict[str, object]) -> None: self.connection.execute(IntakeRevisionFileLinkModel.__table__.insert().values(**values))
    def insert_operation(self, values: dict[str, object]) -> None: self.connection.execute(IntakeSourceOperationModel.__table__.insert().values(**values))
    def insert_candidate(self, values: dict[str, object]) -> None: self.connection.execute(IntakeDuplicateCandidateModel.__table__.insert().values(**values))
    def record(self, *, entity_type: str, entity_id: str, action: str, before: dict | None, after: dict | None, reason: str, correlation_id: str, actor_kind: str = "local_operator", actor_reference: str | None = None) -> None:
        self.recorder.record_change(self.connection.connection.driver_connection, entity_type=entity_type, entity_id=entity_id, action=action, before=before, after=after, reason=reason, correlation_id=correlation_id, actor_kind=actor_kind, actor_reference=actor_reference)
    def source_projection(self, source_id: str) -> dict[str, object] | None:
        source = self.source(source_id)
        if source is None: return None
        revision = self.revision(source["current_revision_id"])
        return {"sourceId": source["id"], "sourceKind": source["source_kind"], "channel": source["channel"], "revision": source["current_revision_id"], "fingerprint": None if revision is None else revision["content_fingerprint"], "technicalStatus": source["technical_status"], "attentionStatus": source["attention_status"], "occurredAtUtc": source["occurred_at_utc"], "receivedAtUtc": source["received_at_utc"], "provenance": {"originSystem": source["origin_system"], "accountIdentityState": source["account_identity_state"], "submitterKind": source["submitter_kind"]}, "attachmentCount": self.connection.execute(select(IntakeRevisionFileLinkModel).where(IntakeRevisionFileLinkModel.revision_id == source["current_revision_id"])).rowcount if False else len(self.connection.execute(select(IntakeRevisionFileLinkModel.file_link_id).where(IntakeRevisionFileLinkModel.revision_id == source["current_revision_id"])).all()), "comparisonAvailable": source["technical_status"] == "ready"}
    def transition_attention(self, source_id: str, *, from_status: str, to_status: str, reason: str, correlation_id: str) -> None:
        row = self.source(source_id)
        if row is None: raise KeyError("Intake source was not found.")
        if row["attention_status"] != from_status: raise ValueError("Intake attention state changed concurrently.")
        self.update_source(source_id, {"attention_status": to_status, "updated_at": datetime.now(UTC).isoformat()})
