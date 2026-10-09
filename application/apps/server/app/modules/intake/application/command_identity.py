"""Source-owned semantic identities shared by commands and recovery preparation."""

from app.modules.intake.domain.models import IntakeAdmissionContext


def admission_request(command, context: IntakeAdmissionContext, envelope):
    result = {
        "admit": envelope,
        "origin": command.origin_system,
        "scope": context.account_scope_hash,
        "identity": context.account_identity_state,
        "submitter": {"kind": context.submitter_kind, "reference": context.submitter_reference},
        "supersedes": command.supersedes_source_id,
    }
    if command.supersedes_source_id is not None:
        result["expectedSourceRevision"] = command.expected_source_revision
        result["expectedEvidenceRevisionId"] = command.expected_evidence_revision_id
    return result


def correction_request(source_id, envelope, reason, expected_revision, evidence_revision):
    return {
        "correct": source_id,
        "envelope": envelope,
        "reason": reason,
        "expectedSourceRevision": expected_revision,
        "expectedEvidenceRevisionId": evidence_revision,
    }


def attention_request(transition):
    return {
        "attention": transition.source_id,
        "target": transition.target,
        "reason": transition.reason,
        "expectedRevision": transition.expected_revision,
        "expectedSourceRevision": transition.expected_source_revision,
        "expectedStatus": transition.expected_status,
        "actorKind": transition.actor_kind,
        "actorReference": transition.actor_reference,
    }
