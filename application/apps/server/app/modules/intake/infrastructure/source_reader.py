"""Consumer-neutral, connection-owned reads of retained Intake evidence."""
from __future__ import annotations

import json
from typing import Any, Collection, Mapping

from sqlalchemy import func, select

from app.modules.intake.infrastructure.sqlalchemy_models import (
    IntakeEvidenceRevisionModel,
    IntakeRevisionFileLinkModel,
    IntakeSourceModel,
)


class SQLiteIntakeSourceReader:
    """Read current and historical Intake facts without opening a transaction."""

    _MAX_HISTORY = 100
    _MAX_ATTACHMENTS = 20

    def source_projection(self, connection: Any, source_id: str) -> dict[str, object] | None:
        return dict(self.source_projections(connection, (source_id,)).get(source_id, {})) or None

    def source_projections(
        self,
        connection: Any,
        source_ids: Collection[str],
    ) -> Mapping[str, Mapping[str, object]]:
        ids = tuple(dict.fromkeys(source_ids))
        if not ids:
            return {}
        counts = (
            select(
                IntakeRevisionFileLinkModel.revision_id.label("revision_id"),
                func.count().label("attachment_count"),
            )
            .where(
                IntakeRevisionFileLinkModel.revision_id.in_(
                    select(IntakeSourceModel.current_revision_id).where(
                        IntakeSourceModel.id.in_(ids),
                    ),
                ),
            )
            .group_by(IntakeRevisionFileLinkModel.revision_id)
            .subquery()
        )
        rows = connection.execute(
            select(
                IntakeSourceModel,
                IntakeEvidenceRevisionModel.content_fingerprint.label("current_fingerprint"),
                func.coalesce(counts.c.attachment_count, 0).label("attachment_count"),
            )
            .outerjoin(
                IntakeEvidenceRevisionModel,
                IntakeEvidenceRevisionModel.id == IntakeSourceModel.current_revision_id,
            )
            .outerjoin(counts, counts.c.revision_id == IntakeSourceModel.current_revision_id)
            .where(IntakeSourceModel.id.in_(ids)),
        ).mappings()
        return {row["id"]: self._summary(row) for row in rows}

    def revision_projection(
        self,
        connection: Any,
        source_id: str,
        revision_id: str,
    ) -> Mapping[str, object] | None:
        counts = (
            select(
                IntakeRevisionFileLinkModel.revision_id.label("revision_id"),
                func.count().label("attachment_count"),
            )
            .where(IntakeRevisionFileLinkModel.revision_id == revision_id)
            .group_by(IntakeRevisionFileLinkModel.revision_id)
            .subquery()
        )
        row = connection.execute(
            select(
                IntakeSourceModel,
                IntakeEvidenceRevisionModel.id.label("revision_id"),
                IntakeEvidenceRevisionModel.revision_number,
                IntakeEvidenceRevisionModel.revision_kind,
                IntakeEvidenceRevisionModel.content_fingerprint,
                IntakeEvidenceRevisionModel.correction_reason,
                IntakeEvidenceRevisionModel.created_at.label("revision_created_at"),
                func.coalesce(counts.c.attachment_count, 0).label("attachment_count"),
            )
            .join(
                IntakeEvidenceRevisionModel,
                IntakeEvidenceRevisionModel.source_id == IntakeSourceModel.id,
            )
            .outerjoin(counts, counts.c.revision_id == IntakeEvidenceRevisionModel.id)
            .where(
                IntakeSourceModel.id == source_id,
                IntakeEvidenceRevisionModel.id == revision_id,
            ),
        ).mappings().first()
        if row is None:
            return None
        return {
            **self._summary(row, fingerprint=row["content_fingerprint"]),
            "revision": row["revision_id"],
            "revisionNumber": row["revision_number"],
            "revisionKind": row["revision_kind"],
            "correctionReason": row["correction_reason"],
            "revisionCreatedAt": row["revision_created_at"],
        }

    def evidence_detail(
        self,
        connection: Any,
        source_id: str,
        revision_id: str,
        *,
        max_history: int = _MAX_HISTORY,
    ) -> Mapping[str, object] | None:
        if isinstance(max_history, bool) or not isinstance(max_history, int) or not 1 <= max_history <= self._MAX_HISTORY:
            raise ValueError("max_history must be between 1 and 100.")
        revision = self.revision_projection(connection, source_id, revision_id)
        if revision is None:
            return None
        evidence = connection.execute(
            select(IntakeEvidenceRevisionModel.envelope_json).where(
                IntakeEvidenceRevisionModel.id == revision_id,
                IntakeEvidenceRevisionModel.source_id == source_id,
            ),
        ).scalar_one()
        attachments = list(connection.execute(
            select(
                IntakeRevisionFileLinkModel.file_link_id,
                IntakeRevisionFileLinkModel.attachment_role,
                IntakeRevisionFileLinkModel.display_order,
            )
            .where(IntakeRevisionFileLinkModel.revision_id == revision_id)
            .order_by(IntakeRevisionFileLinkModel.display_order)
            .limit(self._MAX_ATTACHMENTS + 1),
        ).mappings())
        if len(attachments) > self._MAX_ATTACHMENTS:
            raise ValueError("Retained Intake revision has too many attachments.")
        history = list(connection.execute(
            select(
                IntakeEvidenceRevisionModel.id,
                IntakeEvidenceRevisionModel.revision_number,
                IntakeEvidenceRevisionModel.revision_kind,
                IntakeEvidenceRevisionModel.created_at,
                IntakeEvidenceRevisionModel.correction_reason,
            )
            .where(IntakeEvidenceRevisionModel.source_id == source_id)
            .order_by(IntakeEvidenceRevisionModel.revision_number.desc())
            .limit(max_history + 1),
        ).mappings())
        return {
            **revision,
            "evidence": json.loads(evidence),
            "attachments": [
                {
                    "fileLinkId": row["file_link_id"],
                    "role": row["attachment_role"],
                    "displayOrder": row["display_order"],
                }
                for row in attachments
            ],
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

    @staticmethod
    def _summary(row: Mapping[str, object], *, fingerprint: str | None = None) -> dict[str, object]:
        return {
            "sourceId": row["id"],
            "sourceKind": row["source_kind"],
            "channel": row["channel"],
            "revision": row["current_revision_id"],
            "fingerprint": fingerprint if fingerprint is not None else row["current_fingerprint"],
            "technicalStatus": row["technical_status"],
            "attentionStatus": row["attention_status"],
            "occurredAtUtc": row["occurred_at_utc"],
            "receivedAtUtc": row["received_at_utc"],
            "supersedesSourceId": row["supersedes_source_id"],
            "supersededBySourceId": row["superseded_by_source_id"],
            "provenance": {
                "originSystem": row["origin_system"],
                "accountIdentityState": row["account_identity_state"],
                "submitterKind": row["submitter_kind"],
            },
            "attachmentCount": row["attachment_count"],
            "comparisonAvailable": row["technical_status"] == "ready",
        }
