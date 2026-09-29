"""Transaction-aware FILE-001 consequences for retained Intake evidence."""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select

from app.modules.files.application.ports import FileLinkReader
from app.modules.intake.domain.models import failure_code, fingerprint
from app.modules.intake.infrastructure.sqlalchemy_models import (
    IntakeRevisionFileLinkModel,
    IntakeSourceModel,
)
from app.modules.intake.infrastructure.unit_of_work import SQLiteIntakeTransaction


class SQLiteIntakeIntegrityConsequences:
    """Moves current, nonsuperseded Intake sources with their FILE-001 bytes.

    The FILE verification writer supplies its active connection.  This keeps
    the location change, both audit streams, and the Intake operation atomic.
    """

    def __init__(self, recorder, file_links: FileLinkReader) -> None:
        self.recorder = recorder
        self.file_links = file_links

    def apply_storage_verification(self, connection, file_id: str,
                                   storage_state: str, correlation_id: str) -> None:
        source_ids = self.file_links.active_entity_ids_for_file(
            connection, file_id, "intake_source"
        )
        if not source_ids:
            return
        transaction = SQLiteIntakeTransaction(connection, self.recorder)
        sources = connection.execute(select(IntakeSourceModel).where(
            IntakeSourceModel.id.in_(source_ids),
            IntakeSourceModel.technical_status != "superseded",
        )).mappings().all()
        evidence_by_source = self.file_links.links_for_entities(
            connection, "intake_source", [row["id"] for row in sources]
        )
        associations: dict[str, set[str]] = {row["id"]: set() for row in sources}
        for row in connection.execute(select(
            IntakeSourceModel.id.label("source_id"),
            IntakeRevisionFileLinkModel.file_link_id,
        ).join(
            IntakeRevisionFileLinkModel,
            IntakeRevisionFileLinkModel.revision_id == IntakeSourceModel.current_revision_id,
        ).where(IntakeSourceModel.id.in_(associations))).mappings():
            associations[row["source_id"]].add(row["file_link_id"])
        for source in sources:
            attachment_ids = associations[source["id"]]
            # Only an association on the current revision is affected.  A
            # retained historical revision must never change current status.
            if not attachment_ids:
                continue
            attachments = [link for link in evidence_by_source[source["id"]]
                           if link.id in attachment_ids]
            available = (len(attachments) == len(attachment_ids)
                         and all(link.storage_state == "available" for link in attachments))
            target = "ready" if available else "failed"
            if source["technical_status"] == target:
                continue
            now = datetime.now(UTC).isoformat()
            code = None if available else failure_code("attachment_content_unavailable")
            operation_type = "integrity_restored" if available else "integrity_failed"
            transaction.update_source(source["id"], {
                "technical_status": target,
                "failure_code": code,
                "updated_at": now,
            })
            transaction.insert_operation({
                "id": str(uuid4()), "operation_type": operation_type,
                "idempotency_key": str(uuid4()),
                "request_fingerprint": fingerprint({
                    "integrity": source["id"], "state": target,
                    "fileId": file_id, "storageState": storage_state,
                }),
                "source_id": source["id"],
                "result_revision_id": source["current_revision_id"],
                "outcome": "succeeded", "error_code": None,
                "correlation_id": correlation_id, "actor_kind": "system",
                "actor_reference": None, "created_at": now,
            })
            transaction.record(
                entity_type="intake_source", entity_id=source["id"],
                action=operation_type,
                before={"technicalStatus": source["technical_status"],
                        "failureCode": source["failure_code"]},
                after={"technicalStatus": target, "failureCode": code},
                reason="intake_integrity_transition", correlation_id=correlation_id,
                actor_kind="system",
            )
