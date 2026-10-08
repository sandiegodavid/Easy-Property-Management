"""SQLite persistence adapter for the retained source aggregate."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, TypeVar

from sqlalchemy import func, or_, select

from app.modules.audit.application.recorder import AuditRecorder
from app.modules.files.application.ports import FileLinkReader
from app.modules.intake.infrastructure.sqlalchemy_models import (
    IntakeDuplicateCandidateModel,
    IntakeEvidenceRevisionModel,
    IntakeRevisionFileLinkModel,
    IntakeSourceModel,
    IntakeSourceOperationModel,
)
from app.modules.intake.infrastructure.source_reader import SQLiteIntakeSourceReader
from app.modules.intake.infrastructure.source_summary import source_summary
from app.platform.sqlite_engine import create_sqlite_engine, immediate_transaction

T = TypeVar("T")


def _file_metadata(item: Any) -> dict[str, object] | None:
    if item is None:
        return None
    return {
        "link_id": item.id,
        "file_id": item.file_id,
        "original_name": item.original_name,
        "media_type": item.media_type,
        "size_bytes": item.size_bytes,
        "content_sha256": item.content_sha256,
        "storage_state": item.storage_state,
        "verified_at": item.verified_at,
    }


class SQLiteIntakeUnitOfWork:
    def __init__(self, database: Path, recorder: AuditRecorder, file_links: FileLinkReader) -> None:
        self.engine = create_sqlite_engine(database)
        self.recorder = recorder
        self.file_links = file_links

    def write(self, operation: Callable[["SQLiteIntakeTransaction"], T]) -> T:
        with immediate_transaction(self.engine) as connection:
            connection.exec_driver_sql("PRAGMA defer_foreign_keys = ON")
            return operation(SQLiteIntakeTransaction(connection, self.recorder, self.file_links))

    def read(self, operation: Callable[["SQLiteIntakeTransaction"], T]) -> T:
        with self.engine.connect() as connection:
            return operation(SQLiteIntakeTransaction(connection, self.recorder, self.file_links))


class SQLiteIntakeTransaction:
    def __init__(
        self, connection: Any, recorder: AuditRecorder, file_links: FileLinkReader
    ) -> None:
        self.connection = connection
        self.recorder = recorder
        self.file_links = file_links

    def source(self, source_id: str):
        return (
            self.connection.execute(
                select(IntakeSourceModel).where(IntakeSourceModel.id == source_id)
            )
            .mappings()
            .first()
        )

    def file_connection(self):
        return self.connection

    def revision(self, revision_id: str):
        return (
            self.connection.execute(
                select(IntakeEvidenceRevisionModel).where(
                    IntakeEvidenceRevisionModel.id == revision_id
                )
            )
            .mappings()
            .first()
        )

    def operation(self, key: str):
        return (
            self.connection.execute(
                select(IntakeSourceOperationModel).where(
                    IntakeSourceOperationModel.idempotency_key == key
                )
            )
            .mappings()
            .first()
        )

    def exact_source(self, origin: str, scope: str, kind: str, external_id: str):
        return (
            self.connection.execute(
                select(IntakeSourceModel).where(
                    IntakeSourceModel.origin_system == origin,
                    IntakeSourceModel.account_scope_hash == scope,
                    IntakeSourceModel.source_kind == kind,
                    IntakeSourceModel.external_source_id == external_id,
                    IntakeSourceModel.account_identity_state.in_(
                        ("transport_verified", "operator_confirmed")
                    ),
                    IntakeSourceModel.superseded_by_source_id.is_(None),
                )
            )
            .mappings()
            .first()
        )

    def operation_by_id(self, operation_id: str):
        return (
            self.connection.execute(
                select(IntakeSourceOperationModel).where(
                    IntakeSourceOperationModel.id == operation_id
                )
            )
            .mappings()
            .first()
        )

    def exact_source_for_evidence(
        self,
        current_source_id: str,
        origin: str,
        scope: str,
        kind: str,
        external_id: str,
        content_fingerprint: str,
    ):
        lineage = (
            select(
                IntakeSourceModel.id,
                IntakeSourceModel.supersedes_source_id,
            )
            .where(IntakeSourceModel.id == current_source_id)
            .cte("intake_source_lineage", recursive=True)
        )
        lineage = lineage.union_all(
            select(
                IntakeSourceModel.id,
                IntakeSourceModel.supersedes_source_id,
            ).join(lineage, IntakeSourceModel.id == lineage.c.supersedes_source_id)
        )
        return (
            self.connection.execute(
                select(IntakeSourceModel)
                .join(
                    IntakeEvidenceRevisionModel,
                    IntakeEvidenceRevisionModel.source_id == IntakeSourceModel.id,
                )
                .where(
                    IntakeSourceModel.id.in_(select(lineage.c.id)),
                    IntakeSourceModel.origin_system == origin,
                    IntakeSourceModel.account_scope_hash == scope,
                    IntakeSourceModel.source_kind == kind,
                    IntakeSourceModel.external_source_id == external_id,
                    IntakeSourceModel.account_identity_state.in_(
                        ("transport_verified", "operator_confirmed")
                    ),
                    IntakeEvidenceRevisionModel.content_fingerprint == content_fingerprint,
                )
                .order_by(
                    IntakeEvidenceRevisionModel.created_at.desc(),
                    IntakeEvidenceRevisionModel.id.desc(),
                    IntakeSourceModel.id.desc(),
                )
            )
            .mappings()
            .first()
        )

    def duplicate_source(self, content_fingerprint: str, source_id: str) -> str | None:
        return self.connection.execute(
            select(IntakeEvidenceRevisionModel.source_id)
            .where(
                IntakeEvidenceRevisionModel.content_fingerprint == content_fingerprint,
                IntakeEvidenceRevisionModel.source_id != source_id,
            )
            .limit(1)
        ).scalar_one_or_none()

    def insert_source(self, values: dict[str, object]) -> None:
        self.connection.execute(IntakeSourceModel.__table__.insert().values(**values))

    def update_source(self, source_id: str, values: dict[str, object]) -> None:
        self.connection.execute(
            IntakeSourceModel.__table__.update()
            .where(IntakeSourceModel.id == source_id)
            .values(**values)
        )

    def insert_revision(self, values: dict[str, object]) -> None:
        self.connection.execute(IntakeEvidenceRevisionModel.__table__.insert().values(**values))

    def insert_attachment(self, values: dict[str, object]) -> None:
        self.connection.execute(IntakeRevisionFileLinkModel.__table__.insert().values(**values))

    def insert_operation(self, values: dict[str, object]) -> None:
        self.connection.execute(IntakeSourceOperationModel.__table__.insert().values(**values))

    def insert_candidate(self, values: dict[str, object]) -> None:
        self.connection.execute(IntakeDuplicateCandidateModel.__table__.insert().values(**values))

    def replace_revision(self, revision_id: str, values: dict[str, object]) -> None:
        self.connection.execute(
            IntakeEvidenceRevisionModel.__table__.update()
            .where(IntakeEvidenceRevisionModel.id == revision_id)
            .values(**values)
        )

    def copy_attachments(self, from_revision_id: str, to_revision_id: str) -> None:
        rows = self.connection.execute(
            select(IntakeRevisionFileLinkModel).where(
                IntakeRevisionFileLinkModel.revision_id == from_revision_id
            )
        ).mappings()
        for row in rows:
            self.insert_attachment(
                {
                    "revision_id": to_revision_id,
                    "file_link_id": row["file_link_id"],
                    "attachment_role": row["attachment_role"],
                    "display_order": row["display_order"],
                }
            )

    def record(
        self,
        *,
        entity_type: str,
        entity_id: str,
        action: str,
        before: dict | None,
        after: dict | None,
        reason: str,
        correlation_id: str,
        actor_kind: str = "local_operator",
        actor_reference: str | None = None,
    ) -> None:
        self.recorder.record_change(
            self.connection.connection.driver_connection,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            before=before,
            after=after,
            reason=reason,
            correlation_id=correlation_id,
            actor_kind=actor_kind,
            actor_reference=actor_reference,
        )

    def source_projection(self, source_id: str) -> dict[str, object] | None:
        source = self.source(source_id)
        if source is None:
            return None
        revision = self.revision(source["current_revision_id"])
        count = len(
            self.connection.execute(
                select(IntakeRevisionFileLinkModel.file_link_id).where(
                    IntakeRevisionFileLinkModel.revision_id == source["current_revision_id"],
                ),
            ).all()
        )
        return source_summary(
            source,
            fingerprint=None if revision is None else revision["content_fingerprint"],
            attachment_count=count,
        )

    def list_projections(
        self,
        *,
        limit: int,
        cursor: tuple[str, str] | None,
        source_kind: str | None,
        technical_status: str | None,
        attention_status: str | None,
        channel: str | None = None,
        origin_system: str | None = None,
        account_identity_state: str | None = None,
        received_from: str | None = None,
        received_to: str | None = None,
        has_duplicate: bool | None = None,
    ) -> tuple[list[dict[str, object]], tuple[str, str] | None]:
        query = select(IntakeSourceModel)
        for column, value in (
            (IntakeSourceModel.source_kind, source_kind),
            (IntakeSourceModel.technical_status, technical_status),
            (IntakeSourceModel.attention_status, attention_status),
            (IntakeSourceModel.channel, channel),
            (IntakeSourceModel.origin_system, origin_system),
            (IntakeSourceModel.account_identity_state, account_identity_state),
        ):
            if value is not None:
                query = query.where(column == value)
        if received_from is not None:
            query = query.where(IntakeSourceModel.received_at_utc >= received_from)
        if received_to is not None:
            query = query.where(IntakeSourceModel.received_at_utc <= received_to)
        candidate = or_(
            IntakeDuplicateCandidateModel.source_id == IntakeSourceModel.id,
            IntakeDuplicateCandidateModel.candidate_source_id == IntakeSourceModel.id,
        )
        if has_duplicate is not None:
            exists = select(IntakeDuplicateCandidateModel.id).where(candidate).exists()
            query = query.where(exists if has_duplicate else ~exists)
        if cursor:
            query = query.where(
                (IntakeSourceModel.received_at_utc < cursor[0])
                | (
                    (IntakeSourceModel.received_at_utc == cursor[0])
                    & (IntakeSourceModel.id < cursor[1])
                )
            )
        rows = list(
            self.connection.execute(
                query.order_by(
                    IntakeSourceModel.received_at_utc.desc(), IntakeSourceModel.id.desc()
                ).limit(limit + 1)
            ).mappings()
        )
        page = rows[:limit]
        if not page:
            return [], None
        revisions = {
            row["id"]: row
            for row in self.connection.execute(
                select(IntakeEvidenceRevisionModel).where(
                    IntakeEvidenceRevisionModel.id.in_([row["current_revision_id"] for row in page])
                )
            ).mappings()
        }
        counts = dict(
            self.connection.execute(
                select(IntakeRevisionFileLinkModel.revision_id, func.count())
                .where(
                    IntakeRevisionFileLinkModel.revision_id.in_(
                        [row["current_revision_id"] for row in page]
                    )
                )
                .group_by(IntakeRevisionFileLinkModel.revision_id)
            ).all()
        )
        results = [
            source_summary(
                row,
                fingerprint=revisions[row["current_revision_id"]]["content_fingerprint"],
                attachment_count=counts.get(row["current_revision_id"], 0),
            )
            for row in page
        ]
        next_cursor = None if len(rows) <= limit else (page[-1]["received_at_utc"], page[-1]["id"])
        return results, next_cursor

    def detail_projection(
        self, source_id: str, pending_operation: dict[str, object] | None = None
    ) -> dict[str, object] | None:
        source = self.source(source_id)
        if source is None:
            return None
        projection = self.source_projection(source_id)
        current = self.revision(source["current_revision_id"])
        revisions = list(
            self.connection.execute(
                select(IntakeEvidenceRevisionModel)
                .where(
                    IntakeEvidenceRevisionModel.source_id == source_id,
                )
                .order_by(IntakeEvidenceRevisionModel.revision_number)
            ).mappings()
        )
        links = list(
            self.connection.execute(
                select(IntakeRevisionFileLinkModel)
                .where(IntakeRevisionFileLinkModel.revision_id == current["id"])
                .order_by(IntakeRevisionFileLinkModel.display_order)
            ).mappings()
        )
        operations = list(
            self.connection.execute(
                select(IntakeSourceOperationModel)
                .where(
                    IntakeSourceOperationModel.source_id == source_id,
                )
                .order_by(IntakeSourceOperationModel.created_at)
            ).mappings()
        )
        if pending_operation is not None:
            operations.append(pending_operation)
        candidates = list(
            self.connection.execute(
                select(IntakeDuplicateCandidateModel).where(
                    or_(
                        IntakeDuplicateCandidateModel.source_id == source_id,
                        IntakeDuplicateCandidateModel.candidate_source_id == source_id,
                    ),
                )
            ).mappings()
        )
        metadata = self.file_links.links_with_files_for_ids(
            self.connection,
            [row["file_link_id"] for row in links],
        )
        return {
            **projection,
            "revision": current["id"],
            "fingerprint": current["content_fingerprint"],
            "attachmentCount": len(links),
            "evidence": json.loads(current["envelope_json"]),
            "revisions": [
                {
                    "id": row["id"],
                    "number": row["revision_number"],
                    "kind": row["revision_kind"],
                    "createdAt": row["created_at"],
                    "correctionReason": row["correction_reason"],
                }
                for row in revisions
            ],
            "attachments": [
                {
                    "fileLinkId": row["file_link_id"],
                    "role": row["attachment_role"],
                    "displayOrder": row["display_order"],
                    "file": _file_metadata(metadata.get(row["file_link_id"])),
                }
                for row in links
            ],
            "operations": [
                {
                    "type": row["operation_type"],
                    "outcome": row["outcome"],
                    "createdAt": row["created_at"],
                }
                for row in operations
            ],
            "duplicateCandidates": [
                {
                    "sourceId": row["source_id"],
                    "candidateSourceId": row["candidate_source_id"],
                    "reason": row["reason"],
                    "disposition": row["disposition"],
                }
                for row in candidates
            ],
        }

    def evidence_detail_projection(
        self, source_id: str, revision_id: str, *, max_history: int, max_attachments: int
    ) -> dict[str, object] | None:
        """Return bounded sensitive evidence only for the audited application port."""
        revision = SQLiteIntakeSourceReader().revision_projection(
            self.connection,
            source_id,
            revision_id,
        )
        if revision is None:
            return None
        envelope = self.connection.execute(
            select(IntakeEvidenceRevisionModel.envelope_json).where(
                IntakeEvidenceRevisionModel.id == revision_id,
                IntakeEvidenceRevisionModel.source_id == source_id,
            )
        ).scalar_one()
        attachments = list(
            self.connection.execute(
                select(
                    IntakeRevisionFileLinkModel.file_link_id,
                    IntakeRevisionFileLinkModel.attachment_role,
                    IntakeRevisionFileLinkModel.display_order,
                )
                .where(
                    IntakeRevisionFileLinkModel.revision_id == revision_id,
                )
                .order_by(
                    IntakeRevisionFileLinkModel.display_order,
                )
                .limit(max_attachments + 1)
            ).mappings()
        )
        history = list(
            self.connection.execute(
                select(
                    IntakeEvidenceRevisionModel.id,
                    IntakeEvidenceRevisionModel.revision_number,
                    IntakeEvidenceRevisionModel.revision_kind,
                    IntakeEvidenceRevisionModel.created_at,
                    IntakeEvidenceRevisionModel.correction_reason,
                )
                .where(
                    IntakeEvidenceRevisionModel.source_id == source_id,
                )
                .order_by(
                    IntakeEvidenceRevisionModel.revision_number.desc(),
                )
                .limit(max_history + 1)
            ).mappings()
        )
        return {
            **revision,
            "evidence": json.loads(envelope),
            "attachments": [
                {
                    "fileLinkId": row["file_link_id"],
                    "role": row["attachment_role"],
                    "displayOrder": row["display_order"],
                }
                for row in attachments[:max_attachments]
            ],
            "attachmentsTruncated": len(attachments) > max_attachments,
            "history": [
                {
                    "id": row["id"],
                    "number": row["revision_number"],
                    "kind": row["revision_kind"],
                    "createdAt": row["created_at"],
                    "correctionReason": row["correction_reason"],
                }
                for row in history[:max_history]
            ],
            "historyTruncated": len(history) > max_history,
        }
