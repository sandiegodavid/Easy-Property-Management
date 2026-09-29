"""INGEST-001 admission and immutable evidence lifecycle."""
from __future__ import annotations
import json
from dataclasses import dataclass, replace
from pathlib import Path
from uuid import uuid4
from app.modules.intake.application.ports import IntakeFileOperations, IntakeUnitOfWork
from app.modules.intake.domain.models import EvidenceEnvelope, IDENTITY_STATES, IntakeConflictError, IntakeError, IntakeNotFoundError, bounded, canonical_json, failure_code, fingerprint, utc, utc_now, uuid


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
    supersedes_source_id: str | None = None
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
        if self.supersedes_source_id is not None: uuid(self.supersedes_source_id, "supersedesSourceId")


class IntakeService:
    def __init__(self, unit_of_work: IntakeUnitOfWork, files: IntakeFileOperations | None = None) -> None:
        self.unit_of_work = unit_of_work; self.files = files

    def admit(self, command: IntakeAdmissionCommand) -> dict[str, object]:
        # This is only a bounded preflight.  The immutable manifest below is
        # built from FILE-001's verified StoredFile values, never this read.
        preflight_hashes = tuple(_digest(item.source) for item in command.attachments)
        if len(set(preflight_hashes)) != len(preflight_hashes): raise IntakeError("Duplicate attachment content is not allowed.")
        if sum(item.source.stat().st_size for item in command.attachments) > 100 * 1024 * 1024: raise IntakeError("Attachment aggregate is too large.")
        provisional = command.envelope.canonical(tuple({"role": item.role, "contentSha256": digest} for item, digest in zip(command.attachments, preflight_hashes)))
        request_fingerprint = fingerprint({"admit": provisional, "origin": command.origin_system, "scope": command.account_scope_hash, "identity": command.account_identity_state, "supersedes": command.supersedes_source_id})
        source_id = str(uuid4()); revision_id = str(uuid4()); correlation_id = str(uuid4()); now = utc_now()
        batch_holder: dict[str, object] = {}
        def operation(tx):
            prior = tx.operation(command.idempotency_key)
            if prior:
                if prior["request_fingerprint"] != request_fingerprint: raise IntakeConflictError("Idempotency key was reused with different input.", "intake_idempotency_conflict")
                return self._view(tx, prior["source_id"]), None
            exact = None
            if command.account_scope_hash and command.account_identity_state in {"transport_verified", "operator_confirmed"} and command.envelope.external_source_id:
                exact = tx.exact_source(command.origin_system, command.account_scope_hash, command.envelope.source_kind, command.envelope.external_source_id)
            if exact is not None:
                existing = tx.revision(exact["current_revision_id"])
                if existing is None or existing["content_fingerprint"] != fingerprint(provisional):
                    raise IntakeConflictError("Trusted external source identity conflicts with retained evidence.", "intake_exact_identity_conflict")
                tx.insert_operation({"id": str(uuid4()), "operation_type": "admit", "idempotency_key": command.idempotency_key, "request_fingerprint": request_fingerprint, "source_id": exact["id"], "result_revision_id": exact["current_revision_id"], "outcome": "succeeded", "error_code": None, "correlation_id": correlation_id, "actor_kind": command.submitter_kind, "actor_reference": command.submitter_reference, "created_at": now})
                return self._view(tx, exact["id"]), None
            batch = self.files.attachment_batch(tx.file_connection()) if command.attachments and self.files else None
            if batch is not None: batch_holder["batch"] = batch
            try:
                links = []
                if command.attachments and batch is None: raise IntakeError("Attachment store is unavailable.")
                for item in command.attachments:
                    stored = batch.add(item.source, item.original_name, item.media_type, entity_type="intake_source", entity_id=source_id, purpose=item.role, correlation_id=correlation_id, owning_workflow=True)
                    links.append((stored, item.role))
                attachment_manifest = tuple({"role": role, "contentSha256": stored.content_sha256} for stored, role in links)
                if len({entry["contentSha256"] for entry in attachment_manifest}) != len(attachment_manifest): raise IntakeError("Duplicate attachment content is not allowed.")
                envelope = command.envelope.canonical(attachment_manifest)
                final_request_fingerprint = fingerprint({"admit": envelope, "origin": command.origin_system, "scope": command.account_scope_hash, "identity": command.account_identity_state, "supersedes": command.supersedes_source_id})
                if command.supersedes_source_id is not None:
                    previous = tx.source(command.supersedes_source_id)
                    if previous is None or previous["technical_status"] != "ready" or previous["superseded_by_source_id"] is not None:
                        raise IntakeConflictError("The source cannot be superseded.", "intake_lifecycle_conflict")
                source = {"id": source_id, "source_kind": command.envelope.source_kind, "channel": command.envelope.channel, "origin_system": command.origin_system, "external_source_id": command.envelope.external_source_id, "conversation_ref": command.envelope.conversation_ref, "account_scope_hash": command.account_scope_hash, "account_identity_state": command.account_identity_state, "account_display_hint": bounded(command.account_display_hint, "accountDisplayHint", 500), "submitter_kind": command.submitter_kind, "submitter_reference": command.submitter_reference, "occurred_at_utc": command.envelope.occurred_at_utc, "received_at_utc": now, "technical_status": "ready", "attention_status": "unprocessed", "current_revision_id": revision_id, "supersedes_source_id": command.supersedes_source_id, "superseded_by_source_id": None, "failure_code": None, "created_at": now, "updated_at": now}
                revision = {"id": revision_id, "source_id": source_id, "revision_number": 1, "envelope_schema_version": 1, "revision_kind": "submitted", "envelope_json": canonical_json(envelope), "content_fingerprint": fingerprint(envelope), "correction_reason": None, "actor_kind": command.submitter_kind, "actor_reference": command.submitter_reference, "created_at": now, "supersedes_revision_id": None, "superseded_by_revision_id": None}
                tx.insert_source(source); tx.insert_revision(revision)
                if command.supersedes_source_id is not None:
                    tx.update_source(command.supersedes_source_id, {"technical_status": "superseded", "superseded_by_source_id": source_id, "updated_at": now})
                for order, (stored, role) in enumerate(links):
                    link_id = next(link["id"] for link in stored.links if link["entityId"] == source_id)
                    tx.insert_attachment({"revision_id": revision_id, "file_link_id": link_id, "attachment_role": role, "display_order": order})
                tx.insert_operation({"id": str(uuid4()), "operation_type": "supersede" if command.supersedes_source_id else "admit", "idempotency_key": command.idempotency_key, "request_fingerprint": final_request_fingerprint, "source_id": source_id, "result_revision_id": revision_id, "outcome": "succeeded", "error_code": None, "correlation_id": correlation_id, "actor_kind": command.submitter_kind, "actor_reference": command.submitter_reference, "created_at": now})
                tx.record(entity_type="intake_source", entity_id=source_id, action="admitted", before=None, after=self._safe_source(source), reason="intake_admitted", correlation_id=correlation_id)
                if command.supersedes_source_id is not None:
                    tx.record(entity_type="intake_source", entity_id=command.supersedes_source_id, action="superseded", before={"technicalStatus": "ready"}, after={"supersededBySourceId": source_id, "technicalStatus": "superseded"}, reason="intake_source_superseded", correlation_id=correlation_id)
                tx.record(entity_type="intake_evidence_revision", entity_id=revision_id, action="created", before=None, after={"sourceId": source_id, "revisionNumber": 1, "contentFingerprint": revision["content_fingerprint"]}, reason="intake_revision_admitted", correlation_id=correlation_id)
                self._candidate(tx, source_id, revision["content_fingerprint"], now, correlation_id)
                return self._view(tx, source_id), batch
            except BaseException as error:
                if batch is not None: batch.rollback(error)
                raise
        try:
            result, batch = self.unit_of_work.write(operation)
        except BaseException as error:
            batch = batch_holder.get("batch")
            if batch is not None:
                try:
                    batch.rollback(error)
                finally:
                    # The immediate transaction has exited, so this
                    # independent FILE-001 attention write cannot contend
                    # with its writer lock, including when cleanup fails.
                    batch.persist_cleanup_attention()
            raise
        if batch is not None: batch.commit()
        return result

    def supersede(self, source_id: str, replacement: IntakeAdmissionCommand) -> dict[str, object]:
        """Create a replacement evidence source in the same admission transaction."""
        uuid(source_id, "sourceId")
        return self.admit(replace(replacement, supersedes_source_id=source_id))

    def get(self, source_id: str) -> dict[str, object]:
        # Evidence reads are deliberately writes: the audit event is part of
        # authorization, so a failed audit denies disclosure.
        def operation(tx):
            result = self._view(tx, source_id, detail=True)
            tx.record(entity_type="intake_source", entity_id=source_id, action="evidence_read", before=None,
                      after={"sourceId": source_id, "revision": result["revision"]}, reason="intake_evidence_read",
                      correlation_id=str(uuid4()))
            return result
        return self.unit_of_work.write(operation)

    def list(self, *, limit: int = 50, cursor: tuple[str, str] | None = None, source_kind: str | None = None, technical_status: str | None = None, attention_status: str | None = None, channel: str | None = None, origin_system: str | None = None, received_from: str | None = None, received_to: str | None = None, has_duplicate: bool | None = None) -> tuple[list[dict[str, object]], str | None]:
        if not isinstance(limit, int) or not 1 <= limit <= 200: raise IntakeError("limit must be between 1 and 200.")
        def operation(tx):
            rows, next_value = tx.list_projections(limit=limit, cursor=cursor, source_kind=source_kind,
                technical_status=technical_status, attention_status=attention_status, channel=channel,
                origin_system=origin_system, received_from=received_from, received_to=received_to,
                has_duplicate=has_duplicate)
            return rows, None if next_value is None else f"{next_value[0]}|{next_value[1]}"
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
            now = utc_now(); revision_id = str(uuid4()); correlation_id = str(uuid4())
            revision = {"id": revision_id, "source_id": source_id, "revision_number": old["revision_number"] + 1, "envelope_schema_version": 1, "revision_kind": "transcript_revision" if source["source_kind"] == "voice_transcript" else "operator_correction", "envelope_json": canonical_json(payload), "content_fingerprint": fingerprint(payload), "correction_reason": reason, "actor_kind": "local_operator", "actor_reference": None, "created_at": now, "supersedes_revision_id": old["id"], "superseded_by_revision_id": None}
            tx.insert_revision(revision); tx.update_source(source_id, {"current_revision_id": revision_id, "updated_at": now})
            tx.replace_revision(old["id"], {"superseded_by_revision_id": revision_id})
            tx.copy_attachments(old["id"], revision_id)
            tx.insert_operation({"id": str(uuid4()), "operation_type": "correct", "idempotency_key": idempotency_key, "request_fingerprint": request, "source_id": source_id, "result_revision_id": revision_id, "outcome": "succeeded", "error_code": None, "correlation_id": correlation_id, "actor_kind": "local_operator", "actor_reference": None, "created_at": now})
            tx.record(entity_type="intake_source", entity_id=source_id, action="corrected", before={"revision": old["id"]}, after={"revision": revision_id}, reason="intake_corrected", correlation_id=correlation_id)
            tx.record(entity_type="intake_evidence_revision", entity_id=revision_id, action="created", before=None, after={"sourceId": source_id, "revisionNumber": revision["revision_number"], "contentFingerprint": revision["content_fingerprint"]}, reason="intake_revision_corrected", correlation_id=correlation_id)
            return self._view(tx, source_id, detail=True)
        return self.unit_of_work.write(operation)

    def attention(self, source_id: str, *, target: str, reason: str, idempotency_key: str,
                  expected_revision: str, expected_status: str) -> dict[str, object]:
        if target not in {"unprocessed", "in_review", "resolved", "dismissed"}: raise IntakeError("attention status is invalid.")
        uuid(source_id, "sourceId"); uuid(idempotency_key, "idempotencyKey"); uuid(expected_revision, "expectedRevision"); reason = bounded(reason, "reason", 1000, required=True)
        def operation(tx):
            source = tx.source(source_id)
            if source is None: raise IntakeNotFoundError("Intake source was not found.")
            request = fingerprint({"attention": source_id, "target": target, "reason": reason, "expectedRevision": expected_revision, "expectedStatus": expected_status}); prior = tx.operation(idempotency_key)
            if prior:
                if prior["request_fingerprint"] != request: raise IntakeConflictError("Idempotency key was reused with different input.", "intake_idempotency_conflict")
                return self._view(tx, source_id)
            if source["technical_status"] != "ready": raise IntakeConflictError("Only ready sources can change attention.", "intake_lifecycle_conflict")
            if source["current_revision_id"] != expected_revision or source["attention_status"] != expected_status:
                raise IntakeConflictError("Intake attention state changed concurrently.", "intake_attention_conflict")
            if target == source["attention_status"]: raise IntakeConflictError("Attention status is unchanged.")
            allowed = {"unprocessed": {"in_review", "dismissed"}, "in_review": {"resolved", "dismissed", "unprocessed"}, "dismissed": {"unprocessed"}, "resolved": set()}
            if target not in allowed[source["attention_status"]]:
                raise IntakeConflictError("Attention transition is not allowed.", "intake_lifecycle_conflict")
            now=utc_now(); correlation_id=str(uuid4()); tx.update_source(source_id, {"attention_status":target,"updated_at":now}); tx.insert_operation({"id":str(uuid4()),"operation_type":"attention_transition","idempotency_key":idempotency_key,"request_fingerprint":request,"source_id":source_id,"result_revision_id":source["current_revision_id"],"outcome":"succeeded","error_code":None,"correlation_id":correlation_id,"actor_kind":"local_operator","actor_reference":None,"created_at":now}); tx.record(entity_type="intake_source",entity_id=source_id,action="attention_changed",before={"attentionStatus":source["attention_status"]},after={"attentionStatus":target},reason="intake_attention_transition",correlation_id=correlation_id); return self._view(tx,source_id)
        return self.unit_of_work.write(operation)

    def set_integrity(self, source_id: str, *, available: bool, reason: str, idempotency_key: str) -> dict[str, object]:
        """Synchronous FILE-001 consequence: evidence failures never masquerade as attention decisions."""
        uuid(source_id, "sourceId"); uuid(idempotency_key, "idempotencyKey")
        code = failure_code(reason)
        def operation(tx):
            source = tx.source(source_id)
            if source is None: raise IntakeNotFoundError("Intake source was not found.")
            target = "ready" if available else "failed"
            request = fingerprint({"integrity": source_id, "target": target, "reason": code})
            prior = tx.operation(idempotency_key)
            if prior:
                if prior["request_fingerprint"] != request: raise IntakeConflictError("Idempotency key was reused with different input.", "intake_idempotency_conflict")
                return self._view(tx, source_id)
            if source["technical_status"] == "superseded": raise IntakeConflictError("Superseded source cannot change integrity.", "intake_lifecycle_conflict")
            if source["technical_status"] == target: raise IntakeConflictError("Technical status is unchanged.", "intake_lifecycle_conflict")
            now = utc_now(); correlation_id = str(uuid4())
            tx.update_source(source_id, {"technical_status": target, "failure_code": None if available else code, "updated_at": now})
            tx.insert_operation({"id": str(uuid4()), "operation_type": "integrity_restored" if available else "integrity_failed", "idempotency_key": idempotency_key, "request_fingerprint": request, "source_id": source_id, "result_revision_id": source["current_revision_id"], "outcome": "succeeded", "error_code": None, "correlation_id": correlation_id, "actor_kind": "system", "actor_reference": None, "created_at": now})
            tx.record(entity_type="intake_source", entity_id=source_id, action="integrity_restored" if available else "integrity_failed", before={"technicalStatus": source["technical_status"]}, after={"technicalStatus": target, "failureCode": None if available else code}, reason="intake_integrity_transition", correlation_id=correlation_id, actor_kind="system")
            return self._view(tx, source_id)
        return self.unit_of_work.write(operation)

    def _candidate(self, tx, source_id: str, content_fingerprint: str, now: str, correlation_id: str) -> None:
        row = tx.duplicate_source(content_fingerprint, source_id)
        if row:
            left, right = sorted((source_id, row)); tx.insert_candidate({"id":str(uuid4()),"source_id":left,"candidate_source_id":right,"reason":"content_fingerprint","confidence_label":"high","confidence_provenance":"exact_canonical_evidence","disposition":"unreviewed","decided_at":None,"decision_reason":None,"created_at":now})

    def _view(self, tx, source_id: str, detail: bool = False) -> dict[str, object]:
        source = tx.source(source_id)
        if source is None: raise IntakeNotFoundError("Intake source was not found.")
        projection = tx.source_projection(source_id)
        if not detail: return projection
        result = tx.detail_projection(source_id)
        if result is None: raise IntakeNotFoundError("Intake source was not found.")
        return result

    @staticmethod
    def _safe_source(source: dict[str, object]) -> dict[str, object]: return {"id":source["id"],"sourceKind":source["source_kind"],"technicalStatus":source["technical_status"],"attentionStatus":source["attention_status"],"receivedAtUtc":source["received_at_utc"]}


def _digest(path: Path) -> str:
    import hashlib
    digest=hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024*1024), b""): digest.update(block)
    return digest.hexdigest()
