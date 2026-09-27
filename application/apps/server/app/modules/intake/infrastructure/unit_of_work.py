"""SQLite persistence adapter for the retained source aggregate."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Callable, TypeVar
from datetime import UTC, datetime
from sqlalchemy import func, or_, select
from app.modules.audit.application.recorder import AuditRecorder
from app.modules.intake.infrastructure.sqlalchemy_models import (IntakeDuplicateCandidateModel, IntakeEvidenceRevisionModel, IntakeRevisionFileLinkModel, IntakeSourceModel, IntakeSourceOperationModel)
from app.platform.sqlite_engine import create_sqlite_engine, immediate_transaction

T = TypeVar("T")


class SQLiteIntakeUnitOfWork:
    def __init__(self, database: Path, recorder: AuditRecorder) -> None:
        self.engine = create_sqlite_engine(database); self.recorder = recorder
    def write(self, operation: Callable[["SQLiteIntakeTransaction"], T]) -> T:
        with immediate_transaction(self.engine) as connection:
            connection.exec_driver_sql("PRAGMA defer_foreign_keys = ON")
            return operation(SQLiteIntakeTransaction(connection, self.recorder))
    def read(self, operation: Callable[["SQLiteIntakeTransaction"], T]) -> T:
        with self.engine.connect() as connection: return operation(SQLiteIntakeTransaction(connection, self.recorder))


class SQLiteIntakeTransaction:
    def __init__(self, connection: Any, recorder: AuditRecorder) -> None: self.connection = connection; self.recorder = recorder
    def source(self, source_id: str): return self.connection.execute(select(IntakeSourceModel).where(IntakeSourceModel.id == source_id)).mappings().first()
    def file_connection(self): return self.connection
    def revision(self, revision_id: str): return self.connection.execute(select(IntakeEvidenceRevisionModel).where(IntakeEvidenceRevisionModel.id == revision_id)).mappings().first()
    def operation(self, key: str): return self.connection.execute(select(IntakeSourceOperationModel).where(IntakeSourceOperationModel.idempotency_key == key)).mappings().first()
    def exact_source(self, origin: str, scope: str, kind: str, external_id: str):
        return self.connection.execute(select(IntakeSourceModel).where(IntakeSourceModel.origin_system == origin, IntakeSourceModel.account_scope_hash == scope, IntakeSourceModel.source_kind == kind, IntakeSourceModel.external_source_id == external_id)).mappings().first()
    def duplicate_source(self, content_fingerprint: str, source_id: str) -> str | None:
        return self.connection.execute(select(IntakeEvidenceRevisionModel.source_id).where(IntakeEvidenceRevisionModel.content_fingerprint == content_fingerprint, IntakeEvidenceRevisionModel.source_id != source_id).limit(1)).scalar_one_or_none()
    def insert_source(self, values: dict[str, object]) -> None: self.connection.execute(IntakeSourceModel.__table__.insert().values(**values))
    def update_source(self, source_id: str, values: dict[str, object]) -> None: self.connection.execute(IntakeSourceModel.__table__.update().where(IntakeSourceModel.id == source_id).values(**values))
    def insert_revision(self, values: dict[str, object]) -> None: self.connection.execute(IntakeEvidenceRevisionModel.__table__.insert().values(**values))
    def insert_attachment(self, values: dict[str, object]) -> None: self.connection.execute(IntakeRevisionFileLinkModel.__table__.insert().values(**values))
    def insert_operation(self, values: dict[str, object]) -> None: self.connection.execute(IntakeSourceOperationModel.__table__.insert().values(**values))
    def insert_candidate(self, values: dict[str, object]) -> None: self.connection.execute(IntakeDuplicateCandidateModel.__table__.insert().values(**values))
    def replace_revision(self, revision_id: str, values: dict[str, object]) -> None:
        self.connection.execute(IntakeEvidenceRevisionModel.__table__.update().where(IntakeEvidenceRevisionModel.id == revision_id).values(**values))
    def copy_attachments(self, from_revision_id: str, to_revision_id: str) -> None:
        rows = self.connection.execute(select(IntakeRevisionFileLinkModel).where(IntakeRevisionFileLinkModel.revision_id == from_revision_id)).mappings()
        for row in rows:
            self.insert_attachment({"revision_id": to_revision_id, "file_link_id": row["file_link_id"], "attachment_role": row["attachment_role"], "display_order": row["display_order"]})
    def record(self, *, entity_type: str, entity_id: str, action: str, before: dict | None, after: dict | None, reason: str, correlation_id: str, actor_kind: str = "local_operator", actor_reference: str | None = None) -> None:
        self.recorder.record_change(self.connection.connection.driver_connection, entity_type=entity_type, entity_id=entity_id, action=action, before=before, after=after, reason=reason, correlation_id=correlation_id, actor_kind=actor_kind, actor_reference=actor_reference)
    def source_projection(self, source_id: str) -> dict[str, object] | None:
        source = self.source(source_id)
        if source is None: return None
        revision = self.revision(source["current_revision_id"])
        return {"sourceId": source["id"], "sourceKind": source["source_kind"], "channel": source["channel"], "revision": source["current_revision_id"], "fingerprint": None if revision is None else revision["content_fingerprint"], "technicalStatus": source["technical_status"], "attentionStatus": source["attention_status"], "occurredAtUtc": source["occurred_at_utc"], "receivedAtUtc": source["received_at_utc"], "supersedesSourceId": source["supersedes_source_id"], "supersededBySourceId": source["superseded_by_source_id"], "provenance": {"originSystem": source["origin_system"], "accountIdentityState": source["account_identity_state"], "submitterKind": source["submitter_kind"]}, "attachmentCount": self.connection.execute(select(IntakeRevisionFileLinkModel).where(IntakeRevisionFileLinkModel.revision_id == source["current_revision_id"])).rowcount if False else len(self.connection.execute(select(IntakeRevisionFileLinkModel.file_link_id).where(IntakeRevisionFileLinkModel.revision_id == source["current_revision_id"])).all()), "comparisonAvailable": source["technical_status"] == "ready"}
    def list_projections(self, *, limit: int, cursor: tuple[str, str] | None,
                         source_kind: str | None, technical_status: str | None,
                         attention_status: str | None, channel: str | None = None,
                         origin_system: str | None = None,
                         received_from: str | None = None, received_to: str | None = None,
                         has_duplicate: bool | None = None) -> tuple[list[dict[str, object]], tuple[str, str] | None]:
        query = select(IntakeSourceModel)
        for column, value in ((IntakeSourceModel.source_kind, source_kind), (IntakeSourceModel.technical_status, technical_status),
                              (IntakeSourceModel.attention_status, attention_status), (IntakeSourceModel.channel, channel),
                              (IntakeSourceModel.origin_system, origin_system)):
            if value is not None: query = query.where(column == value)
        if received_from is not None: query = query.where(IntakeSourceModel.received_at_utc >= received_from)
        if received_to is not None: query = query.where(IntakeSourceModel.received_at_utc <= received_to)
        candidate = or_(IntakeDuplicateCandidateModel.source_id == IntakeSourceModel.id, IntakeDuplicateCandidateModel.candidate_source_id == IntakeSourceModel.id)
        if has_duplicate is not None:
            exists = select(IntakeDuplicateCandidateModel.id).where(candidate).exists()
            query = query.where(exists if has_duplicate else ~exists)
        if cursor:
            query = query.where((IntakeSourceModel.received_at_utc < cursor[0]) | ((IntakeSourceModel.received_at_utc == cursor[0]) & (IntakeSourceModel.id < cursor[1])))
        rows = list(self.connection.execute(query.order_by(IntakeSourceModel.received_at_utc.desc(), IntakeSourceModel.id.desc()).limit(limit + 1)).mappings())
        page = rows[:limit]
        if not page: return [], None
        ids = [row["id"] for row in page]
        revisions = {row["id"]: row for row in self.connection.execute(select(IntakeEvidenceRevisionModel).where(IntakeEvidenceRevisionModel.id.in_([row["current_revision_id"] for row in page]))).mappings()}
        counts = dict(self.connection.execute(select(IntakeRevisionFileLinkModel.revision_id, func.count()).where(IntakeRevisionFileLinkModel.revision_id.in_([row["current_revision_id"] for row in page])).group_by(IntakeRevisionFileLinkModel.revision_id)).all())
        results = [{"sourceId": row["id"], "sourceKind": row["source_kind"], "channel": row["channel"], "revision": row["current_revision_id"], "fingerprint": revisions[row["current_revision_id"]]["content_fingerprint"], "technicalStatus": row["technical_status"], "attentionStatus": row["attention_status"], "occurredAtUtc": row["occurred_at_utc"], "receivedAtUtc": row["received_at_utc"], "supersedesSourceId": row["supersedes_source_id"], "supersededBySourceId": row["superseded_by_source_id"], "provenance": {"originSystem": row["origin_system"], "accountIdentityState": row["account_identity_state"], "submitterKind": row["submitter_kind"]}, "attachmentCount": counts.get(row["current_revision_id"], 0), "comparisonAvailable": row["technical_status"] == "ready"} for row in page]
        next_cursor = None if len(rows) <= limit else (page[-1]["received_at_utc"], page[-1]["id"])
        return results, next_cursor
    def detail_projection(self, source_id: str) -> dict[str, object] | None:
        source = self.source(source_id)
        if source is None: return None
        projection = self.source_projection(source_id)
        current = self.revision(source["current_revision_id"])
        revisions = list(self.connection.execute(select(IntakeEvidenceRevisionModel).where(IntakeEvidenceRevisionModel.source_id == source_id).order_by(IntakeEvidenceRevisionModel.revision_number)).mappings())
        links = list(self.connection.execute(select(IntakeRevisionFileLinkModel).where(IntakeRevisionFileLinkModel.revision_id == source["current_revision_id"]).order_by(IntakeRevisionFileLinkModel.display_order)).mappings())
        operations = list(self.connection.execute(select(IntakeSourceOperationModel).where(IntakeSourceOperationModel.source_id == source_id).order_by(IntakeSourceOperationModel.created_at)).mappings())
        candidates = list(self.connection.execute(select(IntakeDuplicateCandidateModel).where(or_(IntakeDuplicateCandidateModel.source_id == source_id, IntakeDuplicateCandidateModel.candidate_source_id == source_id))).mappings())
        from app.modules.files.infrastructure.sqlalchemy_models import FileContentLocationModel, FileLinkModel, FileRecordModel
        metadata = {row["link_id"]: row for row in self.connection.execute(select(FileLinkModel.id.label("link_id"), FileRecordModel.id.label("file_id"), FileRecordModel.original_name, FileRecordModel.media_type, FileRecordModel.size_bytes, FileRecordModel.content_sha256, FileContentLocationModel.storage_state, FileContentLocationModel.verified_at).join(FileRecordModel, FileRecordModel.id == FileLinkModel.file_id).join(FileContentLocationModel, FileContentLocationModel.file_id == FileRecordModel.id).where(FileLinkModel.id.in_([row["file_link_id"] for row in links]))).mappings()}
        return {**projection, "evidence": json.loads(current["envelope_json"]), "revisions": [{"id": row["id"], "number": row["revision_number"], "kind": row["revision_kind"], "createdAt": row["created_at"], "correctionReason": row["correction_reason"]} for row in revisions], "attachments": [{"fileLinkId": row["file_link_id"], "role": row["attachment_role"], "displayOrder": row["display_order"], "file": dict(metadata[row["file_link_id"]]) if row["file_link_id"] in metadata else None} for row in links], "operations": [{"type": row["operation_type"], "outcome": row["outcome"], "createdAt": row["created_at"]} for row in operations], "duplicateCandidates": [{"sourceId": row["source_id"], "candidateSourceId": row["candidate_source_id"], "reason": row["reason"], "disposition": row["disposition"]} for row in candidates]}
    def transition_attention(self, source_id: str, *, from_status: str, to_status: str, reason: str, correlation_id: str) -> None:
        row = self.source(source_id)
        if row is None: raise KeyError("Intake source was not found.")
        if row["attention_status"] != from_status: raise ValueError("Intake attention state changed concurrently.")
        self.update_source(source_id, {"attention_status": to_status, "updated_at": datetime.now(UTC).isoformat()})
