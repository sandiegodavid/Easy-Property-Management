"""INGEST-001 admission and immutable evidence lifecycle."""
from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4
from sqlalchemy import select
from app.modules.files.application.service import FileService
from app.modules.intake.application.ports import IntakeUnitOfWork
from app.modules.intake.domain.models import EvidenceEnvelope, IDENTITY_STATES, IntakeConflictError, IntakeError, IntakeNotFoundError, bounded, canonical_json, fingerprint, utc, utc_now, uuid


@dataclass(frozen=True)
class AttachmentInput:
    source: Path
    original_name: str
    media_type: str | None
    role: str = "source_attachment"
    def __post_init__(self):
        if self.role not in {"source_attachment", "raw_source"}: raise IntakeError("attachment role is invalid.")


@dataclass(frozen=True)
class IntakeAdmissionCommand:
    envelope: EvidenceEnvelope
    origin_system: str
    idempotency_key: str
    account_scope_hash: str | None = None
    account_identity_state: str = "not_applicable"
    account_display_hint: str | None = None
    attachments: tuple[AttachmentInput, ...] = ()
    submitter_kind: str = "local_operator"
    submitter_reference: str | None = None
    def __post_init__(self):
        uuid(self.idempotency_key, "idempotencyKey")
        object.__setattr__(self, "origin_system", bounded(self.origin_system, "originSystem", 500, required=True))
        if self.account_identity_state not in IDENTITY_STATES: raise IntakeError("account identity state is invalid.")
        if self.account_scope_hash is not None and (len(self.account_scope_hash) != 64 or any(c not in "0123456789abcdef" for c in self.account_scope_hash)):
            raise IntakeError("account scope hash is invalid.")
        if self.account_identity_state in {"transport_verified", "operator_confirmed"} and not self.account_scope_hash:
            raise IntakeError("trusted account identity requires accountScopeHash.")
        if len(self.attachments) > 20 or any(not isinstance(item, AttachmentInput) for item in self.attachments): raise IntakeError("attachments are invalid.")
        if self.submitter_kind not in {"local_operator", "assistant_connection", "voice_workflow"}: raise IntakeError("submitter kind is invalid.")
        if self.submitter_kind != "local_operator": raise IntakeError("Public intake cannot claim trusted submitter provenance.")


class IntakeService:
    def __init__(self, unit_of_work: IntakeUnitOfWork, files: FileService | None = None) -> None:
        self.unit_of_work = unit_of_work; self.files = files

    def admit(self, command: IntakeAdmissionCommand) -> dict[str, object]:
        attachment_manifest = tuple({"role": item.role, "contentSha256": _digest(item.source)} for item in command.attachments)
        if len({item["contentSha256"] for item in attachment_manifest}) != len(attachment_manifest): raise IntakeError("Duplicate attachment content is not allowed.")
        if sum(item.source.stat().st_size for item in command.attachments) > 100 * 1024 * 1024: raise IntakeError("Attachment aggregate is too large.")
        envelope = command.envelope.canonical(attachment_manifest); request_fingerprint = fingerprint({"admit": envelope, "origin": command.origin_system, "scope": command.account_scope_hash, "identity": command.account_identity_state})
        source_id = str(uuid4()); revision_id = str(uuid4()); correlation_id = str(uuid4()); now = utc_now()
        def operation(tx):
            prior = tx.operation(command.idempotency_key)
            if prior:
                if prior["request_fingerprint"] != request_fingerprint: raise IntakeConflictError("Idempotency key was reused with different input.", "intake_idempotency_conflict")
                return self._view(tx, prior["source_id"]), None
            if command.account_scope_hash and command.account_identity_state in {"transport_verified", "operator_confirmed"} and command.envelope.external_source_id:
                exact = tx.exact_source(command.origin_system, command.account_scope_hash, command.envelope.source_kind, command.envelope.external_source_id)
                if exact:
                    return self._view(tx, exact["id"]), None
            tx.connection.exec_driver_sql("PRAGMA defer_foreign_keys = ON")
            batch = self.files.attachment_batch(tx.connection) if command.attachments and self.files else None
            try:
                links = []
                if command.attachments and batch is None: raise IntakeError("Attachment store is unavailable.")
                for item in command.attachments:
                    stored = batch.add(item.source, item.original_name, item.media_type, entity_type="intake_source", entity_id=source_id, purpose=item.role, correlation_id=correlation_id, owning_workflow=True)
                    links.append((stored, item.role))
                source = {"id": source_id, "source_kind": command.envelope.source_kind, "channel": command.envelope.channel, "origin_system": command.origin_system, "external_source_id": command.envelope.external_source_id, "conversation_ref": command.envelope.conversation_ref, "account_scope_hash": command.account_scope_hash, "account_identity_state": command.account_identity_state, "account_display_hint": bounded(command.account_display_hint, "accountDisplayHint", 500), "submitter_kind": command.submitter_kind, "submitter_reference": command.submitter_reference, "occurred_at_utc": command.envelope.occurred_at_utc, "received_at_utc": now, "technical_status": "ready", "attention_status": "unprocessed", "current_revision_id": revision_id, "supersedes_source_id": None, "superseded_by_source_id": None, "failure_code": None, "created_at": now, "updated_at": now}
                revision = {"id": revision_id, "source_id": source_id, "revision_number": 1, "envelope_schema_version": 1, "revision_kind": "submitted", "envelope_json": canonical_json(envelope), "content_fingerprint": fingerprint(envelope), "correction_reason": None, "actor_kind": command.submitter_kind, "actor_reference": command.submitter_reference, "created_at": now, "supersedes_revision_id": None, "superseded_by_revision_id": None}
                tx.insert_source(source); tx.insert_revision(revision)
                for order, (stored, role) in enumerate(links):
                    link_id = next(link["id"] for link in stored.links if link["entityId"] == source_id)
                    tx.insert_attachment({"revision_id": revision_id, "file_link_id": link_id, "attachment_role": role, "display_order": order})
                tx.insert_operation({"id": str(uuid4()), "operation_type": "admit", "idempotency_key": command.idempotency_key, "request_fingerprint": request_fingerprint, "source_id": source_id, "result_revision_id": revision_id, "outcome": "succeeded", "error_code": None, "correlation_id": correlation_id, "actor_kind": command.submitter_kind, "actor_reference": command.submitter_reference, "created_at": now})
                tx.record(entity_type="intake_source", entity_id=source_id, action="admitted", before=None, after=self._safe_source(source), reason="intake_admitted", correlation_id=correlation_id)
                tx.record(entity_type="intake_evidence_revision", entity_id=revision_id, action="created", before=None, after={"sourceId": source_id, "revisionNumber": 1, "contentFingerprint": revision["content_fingerprint"]}, reason="intake_revision_admitted", correlation_id=correlation_id)
                self._candidate(tx, source_id, revision["content_fingerprint"], now, correlation_id)
                return self._view(tx, source_id), batch
            except BaseException as error:
                if batch is not None: batch.rollback(error)
                raise
        result, batch = self.unit_of_work.write(operation)
        if batch is not None: batch.commit()
        return result

    def get(self, source_id: str) -> dict[str, object]: return self.unit_of_work.read(lambda tx: self._view(tx, source_id, detail=True))

    def list(self, *, limit: int = 50, cursor: tuple[str, str] | None = None, source_kind: str | None = None, technical_status: str | None = None, attention_status: str | None = None) -> tuple[list[dict[str, object]], str | None]:
        if not isinstance(limit, int) or not 1 <= limit <= 200: raise IntakeError("limit must be between 1 and 200.")
        def operation(tx):
            from sqlalchemy import select
            from app.modules.intake.infrastructure.sqlalchemy_models import IntakeSourceModel
            query = select(IntakeSourceModel).order_by(IntakeSourceModel.received_at_utc.desc(), IntakeSourceModel.id.desc())
            for column, value in ((IntakeSourceModel.source_kind, source_kind), (IntakeSourceModel.technical_status, technical_status), (IntakeSourceModel.attention_status, attention_status)):
                if value is not None: query = query.where(column == value)
            if cursor: query = query.where((IntakeSourceModel.received_at_utc < cursor[0]) | ((IntakeSourceModel.received_at_utc == cursor[0]) & (IntakeSourceModel.id < cursor[1])))
            rows = list(tx.connection.execute(query.limit(limit + 1)).mappings()); next_value = None if len(rows) <= limit else rows[limit]
            return [self._view(tx, row["id"]) for row in rows[:limit]], None if next_value is None else f"{next_value['received_at_utc']}|{next_value['id']}"
        return self.unit_of_work.read(operation)

    def correct(self, source_id: str, envelope: EvidenceEnvelope, reason: str, idempotency_key: str) -> dict[str, object]:
        uuid(source_id, "sourceId"); uuid(idempotency_key, "idempotencyKey"); reason = bounded(reason, "correctionReason", 1000, required=True)
        def operation(tx):
            source = tx.source(source_id)
            if source is None: raise IntakeNotFoundError("Intake source was not found.")
            old = tx.revision(source["current_revision_id"]); old_envelope = json.loads(old["envelope_json"])
            if any(getattr(envelope, field) != old_envelope.get(key) for field, key in (("source_kind", "sourceKind"), ("channel", "channel"), ("provider", "provider"), ("conversation_ref", "conversationRef"), ("external_source_id", "externalSourceId"))):
                raise IntakeConflictError("Source identity or attachment membership requires source supersession.", "intake_supersession_required")
            payload = envelope.canonical(tuple(old_envelope["attachments"]))
            request = fingerprint({"correct": source_id, "envelope": payload, "reason": reason})
            prior = tx.operation(idempotency_key)
            if prior:
                if prior["request_fingerprint"] != request: raise IntakeConflictError("Idempotency key was reused with different input.", "intake_idempotency_conflict")
                return self._view(tx, source_id, detail=True)
            if source["technical_status"] == "superseded": raise IntakeConflictError("Superseded source cannot be corrected.")
            now = utc_now(); revision_id = str(uuid4()); correlation_id = str(uuid4()); tx.connection.exec_driver_sql("PRAGMA defer_foreign_keys = ON")
            revision = {"id": revision_id, "source_id": source_id, "revision_number": old["revision_number"] + 1, "envelope_schema_version": 1, "revision_kind": "transcript_revision" if source["source_kind"] == "voice_transcript" else "operator_correction", "envelope_json": canonical_json(payload), "content_fingerprint": fingerprint(payload), "correction_reason": reason, "actor_kind": "local_operator", "actor_reference": None, "created_at": now, "supersedes_revision_id": old["id"], "superseded_by_revision_id": None}
            from app.modules.intake.infrastructure.sqlalchemy_models import IntakeEvidenceRevisionModel, IntakeRevisionFileLinkModel
            tx.insert_revision(revision); tx.update_source(source_id, {"current_revision_id": revision_id, "updated_at": now})
            tx.connection.execute(IntakeEvidenceRevisionModel.__table__.update().where(IntakeEvidenceRevisionModel.id == old["id"]).values(superseded_by_revision_id=revision_id))
            for row in tx.connection.execute(select(IntakeRevisionFileLinkModel).where(IntakeRevisionFileLinkModel.revision_id == old["id"])).mappings():
                tx.insert_attachment({"revision_id": revision_id, "file_link_id": row["file_link_id"], "attachment_role": row["attachment_role"], "display_order": row["display_order"]})
            tx.insert_operation({"id": str(uuid4()), "operation_type": "correct", "idempotency_key": idempotency_key, "request_fingerprint": request, "source_id": source_id, "result_revision_id": revision_id, "outcome": "succeeded", "error_code": None, "correlation_id": correlation_id, "actor_kind": "local_operator", "actor_reference": None, "created_at": now})
            tx.record(entity_type="intake_source", entity_id=source_id, action="corrected", before={"revision": old["id"]}, after={"revision": revision_id}, reason="intake_corrected", correlation_id=correlation_id)
            return self._view(tx, source_id, detail=True)
        return self.unit_of_work.write(operation)

    def attention(self, source_id: str, *, target: str, reason: str, idempotency_key: str) -> dict[str, object]:
        if target not in {"unprocessed", "in_review", "resolved", "dismissed"}: raise IntakeError("attention status is invalid.")
        uuid(source_id, "sourceId"); uuid(idempotency_key, "idempotencyKey"); reason = bounded(reason, "reason", 1000, required=True)
        def operation(tx):
            source = tx.source(source_id)
            if source is None: raise IntakeNotFoundError("Intake source was not found.")
            request = fingerprint({"attention": source_id, "target": target, "reason": reason}); prior = tx.operation(idempotency_key)
            if prior:
                if prior["request_fingerprint"] != request: raise IntakeConflictError("Idempotency key was reused with different input.", "intake_idempotency_conflict")
                return self._view(tx, source_id)
            if source["technical_status"] == "superseded": raise IntakeConflictError("Superseded source cannot change attention.")
            if target == source["attention_status"]: raise IntakeConflictError("Attention status is unchanged.")
            now=utc_now(); correlation_id=str(uuid4()); tx.update_source(source_id, {"attention_status":target,"updated_at":now}); tx.insert_operation({"id":str(uuid4()),"operation_type":"attention_transition","idempotency_key":idempotency_key,"request_fingerprint":request,"source_id":source_id,"result_revision_id":source["current_revision_id"],"outcome":"succeeded","error_code":None,"correlation_id":correlation_id,"actor_kind":"local_operator","actor_reference":None,"created_at":now}); tx.record(entity_type="intake_source",entity_id=source_id,action="attention_changed",before={"attentionStatus":source["attention_status"]},after={"attentionStatus":target},reason="intake_attention_transition",correlation_id=correlation_id); return self._view(tx,source_id)
        return self.unit_of_work.write(operation)

    def _candidate(self, tx, source_id: str, content_fingerprint: str, now: str, correlation_id: str) -> None:
        from app.modules.intake.infrastructure.sqlalchemy_models import IntakeEvidenceRevisionModel
        row = tx.connection.execute(select(IntakeEvidenceRevisionModel.source_id).where(IntakeEvidenceRevisionModel.content_fingerprint == content_fingerprint, IntakeEvidenceRevisionModel.source_id != source_id).limit(1)).scalar_one_or_none()
        if row:
            left, right = sorted((source_id, row)); tx.insert_candidate({"id":str(uuid4()),"source_id":left,"candidate_source_id":right,"reason":"content_fingerprint","confidence_label":"high","confidence_provenance":"exact_canonical_evidence","disposition":"unreviewed","decided_at":None,"decision_reason":None,"created_at":now})

    def _view(self, tx, source_id: str, detail: bool = False) -> dict[str, object]:
        source = tx.source(source_id)
        if source is None: raise IntakeNotFoundError("Intake source was not found.")
        projection = tx.source_projection(source_id)
        if not detail: return projection
        from app.modules.intake.infrastructure.sqlalchemy_models import IntakeEvidenceRevisionModel, IntakeRevisionFileLinkModel, IntakeSourceOperationModel, IntakeDuplicateCandidateModel
        current = tx.revision(source["current_revision_id"]); revisions = list(tx.connection.execute(select(IntakeEvidenceRevisionModel).where(IntakeEvidenceRevisionModel.source_id == source_id).order_by(IntakeEvidenceRevisionModel.revision_number)).mappings()); links=list(tx.connection.execute(select(IntakeRevisionFileLinkModel).where(IntakeRevisionFileLinkModel.revision_id==source["current_revision_id"]).order_by(IntakeRevisionFileLinkModel.display_order)).mappings()); ops=list(tx.connection.execute(select(IntakeSourceOperationModel).where(IntakeSourceOperationModel.source_id==source_id).order_by(IntakeSourceOperationModel.created_at)).mappings()); candidates=list(tx.connection.execute(select(IntakeDuplicateCandidateModel).where((IntakeDuplicateCandidateModel.source_id==source_id)|(IntakeDuplicateCandidateModel.candidate_source_id==source_id))).mappings())
        return {**projection,"evidence":json.loads(current["envelope_json"]),"revisions":[{"id":r["id"],"number":r["revision_number"],"kind":r["revision_kind"],"createdAt":r["created_at"],"correctionReason":r["correction_reason"]} for r in revisions],"attachments":[{"fileLinkId":r["file_link_id"],"role":r["attachment_role"],"displayOrder":r["display_order"]} for r in links],"operations":[{"type":r["operation_type"],"outcome":r["outcome"],"createdAt":r["created_at"]} for r in ops],"duplicateCandidates":[{"sourceId":r["source_id"],"candidateSourceId":r["candidate_source_id"],"reason":r["reason"],"disposition":r["disposition"]} for r in candidates]}

    @staticmethod
    def _safe_source(source: dict[str, object]) -> dict[str, object]: return {"id":source["id"],"sourceKind":source["source_kind"],"technicalStatus":source["technical_status"],"attentionStatus":source["attention_status"],"receivedAtUtc":source["received_at_utc"]}


def _digest(path: Path) -> str:
    import hashlib
    digest=hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024*1024), b""): digest.update(block)
    return digest.hexdigest()
