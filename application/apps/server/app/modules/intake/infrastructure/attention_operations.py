"""Connection-owned INGEST-001 attention lifecycle persistence."""
from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy import select

from app.modules.audit.application.recorder import AuditRecorder
from app.modules.intake.domain.models import (
    AttentionTransition,
    IntakeConflictError,
    IntakeNotFoundError,
    canonical_json,
    fingerprint,
    utc_now,
)
from app.modules.intake.infrastructure.sqlalchemy_models import IntakeSourceModel, IntakeSourceOperationModel
from app.modules.intake.infrastructure.unit_of_work import SQLiteIntakeTransaction

_ALLOWED_TRANSITIONS = {
    "unprocessed": {"in_review", "dismissed"},
    "in_review": {"resolved", "dismissed", "unprocessed"},
    "dismissed": {"unprocessed"},
    "resolved": set(),
}


class SQLiteIntakeAttentionOperations:
    """The one transaction-aware adapter shared by operator and review flows."""

    def __init__(self, recorder: AuditRecorder) -> None:
        self.recorder = recorder

    def transition_attention(
        self,
        connection: Any,
        transition: AttentionTransition,
    ) -> dict[str, object]:
        request_fingerprint = fingerprint({
            "attention": transition.source_id,
            "target": transition.target,
            "reason": transition.reason,
            "expectedRevision": transition.expected_revision,
            "expectedStatus": transition.expected_status,
            # These values are normalized by AttentionTransition before the
            # idempotency check.  The retry correlation is intentionally not
            # part of request identity, but actor attribution is.
            "actorKind": transition.actor_kind,
            "actorReference": transition.actor_reference,
        })
        prior = connection.execute(
            select(IntakeSourceOperationModel).where(
                IntakeSourceOperationModel.idempotency_key == transition.idempotency_key,
            ),
        ).mappings().first()
        if prior is not None:
            if prior["request_fingerprint"] != request_fingerprint:
                raise IntakeConflictError(
                    "Idempotency key was reused with different input.",
                    "intake_idempotency_conflict",
                )
            if prior["operation_type"] != "attention_transition" or prior["result_json"] is None:
                raise IntakeConflictError("Idempotency key is not an attention transition.", "intake_idempotency_conflict")
            return self._result(prior["result_json"])

        source = self._source(connection, transition.source_id)
        if source["technical_status"] != "ready":
            raise IntakeConflictError("Only ready sources can change attention.", "intake_lifecycle_conflict")
        if (
            source["current_revision_id"] != transition.expected_revision
            or source["attention_status"] != transition.expected_status
        ):
            raise IntakeConflictError(
                "Intake attention state changed concurrently.",
                "intake_attention_conflict",
            )
        if transition.target == source["attention_status"]:
            raise IntakeConflictError("Attention status is unchanged.", "intake_lifecycle_conflict")
        if transition.target not in _ALLOWED_TRANSITIONS[source["attention_status"]]:
            raise IntakeConflictError("Attention transition is not allowed.", "intake_lifecycle_conflict")

        now = utc_now()
        connection.execute(
            IntakeSourceModel.__table__.update().where(
                IntakeSourceModel.id == transition.source_id,
            ).values(attention_status=transition.target, updated_at=now),
        )
        result = SQLiteIntakeTransaction(connection, self.recorder).source_projection(transition.source_id)
        if result is None:
            raise IntakeNotFoundError("Intake source was not found.")
        connection.execute(IntakeSourceOperationModel.__table__.insert().values(
            id=str(uuid4()),
            operation_type="attention_transition",
            idempotency_key=transition.idempotency_key,
            request_fingerprint=request_fingerprint,
            source_id=transition.source_id,
            result_revision_id=source["current_revision_id"],
            result_json=canonical_json(result),
            outcome="succeeded",
            error_code=None,
            correlation_id=transition.correlation_id,
            actor_kind=transition.actor_kind,
            actor_reference=transition.actor_reference,
            created_at=now,
        ))
        self.recorder.record_change(
            connection.connection.driver_connection,
            entity_type="intake_source",
            entity_id=transition.source_id,
            action="attention_changed",
            before={"attentionStatus": source["attention_status"]},
            after={"attentionStatus": transition.target},
            reason=transition.reason,
            correlation_id=transition.correlation_id,
            actor_kind=transition.actor_kind,
            actor_reference=transition.actor_reference,
        )
        return result

    @staticmethod
    def _source(connection: Any, source_id: str) -> dict[str, object]:
        source = connection.execute(
            select(IntakeSourceModel).where(IntakeSourceModel.id == source_id),
        ).mappings().first()
        if source is None:
            raise IntakeNotFoundError("Intake source was not found.")
        return dict(source)

    @staticmethod
    def _result(value: object) -> dict[str, object]:
        import json
        try:
            result = json.loads(str(value))
        except (TypeError, ValueError) as error:
            raise IntakeConflictError("Stored attention result is invalid.", "intake_integrity_conflict") from error
        if not isinstance(result, dict):
            raise IntakeConflictError("Stored attention result is invalid.", "intake_integrity_conflict")
        return result
