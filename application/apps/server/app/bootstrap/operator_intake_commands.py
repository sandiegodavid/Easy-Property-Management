"""Approved Slice 32 composition, without publication or evidence disclosure."""

from app.modules.intake.application.command_identity import (
    admission_request,
    correction_request,
    attention_request,
)
from app.modules.intake.application.service import IntakeAdmissionCommand
from app.modules.intake.domain.models import (
    EvidenceEnvelope,
    IntakeAdmissionContext,
    AttentionTransition,
    bounded,
    fingerprint,
    source_revision,
    attention_transition_allowed,
)
from app.modules.intake.infrastructure.recovery_reader import SQLiteIntakeRecoveryReader
from app.modules.operator.application.ports import RecoveryBinding
from app.modules.operator.application.intake_forms import INTAKE_SCHEMAS
from app.modules.operator.domain.models import OperatorError


def intake_request(action, source, payload, key):
    revision = payload["expectedRevision"]
    if action in {"dismiss", "reopen"}:
        transition = AttentionTransition(
            source,
            "dismissed" if action == "dismiss" else "unprocessed",
            payload.get("reason"),
            key,
            payload.get("expectedEvidenceRevisionId"),
            revision,
            payload.get("expectedStatus"),
            key,
        )
        return fingerprint(attention_request(transition))
    envelope = EvidenceEnvelope(
        payload.get("sourceKind"),
        payload.get("channel"),
        payload.get("body"),
        payload.get("occurredAtUtc"),
        payload.get("subject"),
        tuple(
            {name: value for name, value in participant.items() if value is not None}
            for participant in payload.get("participants", ())
        ),
        payload.get("provider"),
        payload.get("conversationRef"),
        payload.get("externalSourceId"),
    )
    manifest = tuple(payload.get("attachments", ()))
    hashes = [item["contentSha256"] for item in manifest]
    if len(set(hashes)) != len(hashes):
        raise OperatorError("Duplicate attachment content is not allowed.")
    if action == "correct":
        source_revision(revision)
        return fingerprint(
            correction_request(
                source,
                envelope.canonical(manifest),
                bounded(payload.get("correctionReason"), "correctionReason", 1000, required=True),
                revision,
                payload["expectedEvidenceRevisionId"],
            )
        )
    supersedes = source if action == "supersede" else None
    if supersedes is None and revision != 0:
        raise OperatorError("Intake admission requires revision zero.")
    command = IntakeAdmissionCommand(
        envelope,
        payload.get("originSystem"),
        key,
        supersedes_source_id=supersedes,
        expected_source_revision=revision if supersedes else None,
        expected_evidence_revision_id=payload.get("expectedEvidenceRevisionId")
        if supersedes
        else None,
    )
    return fingerprint(
        admission_request(
            command, IntakeAdmissionContext.local_operator(), envelope.canonical(manifest)
        )
    )


def intake_form_state(action, state, payload):
    evidence = payload.get("expectedEvidenceRevisionId")
    expected_status = payload.get("expectedStatus")
    if (evidence is not None and evidence != state["evidence_revision_id"]) or (
        expected_status is not None and expected_status != state["attention_status"]
    ):
        return "source_changed"
    targets = {"dismiss": "dismissed", "reopen": "unprocessed"}
    if action in targets and not attention_transition_allowed(
        state["attention_status"], targets[action]
    ):
        return "source_unavailable"
    return "available"


def compose_intake_forms():
    reader = SQLiteIntakeRecoveryReader()
    return {
        form: RecoveryBinding(
            None if action in {"admit", "import"} else "intake_source",
            action,
            "intake",
            reader,
            lambda source, payload, key, action=action: intake_request(
                action, source, payload, key
            ),
            "intake_source",
            fingerprint_payload=reader.correction_payload if action == "correct" else None,
        )
        for form in INTAKE_SCHEMAS
        for action in [form.rsplit(".", 1)[1]]
    }
