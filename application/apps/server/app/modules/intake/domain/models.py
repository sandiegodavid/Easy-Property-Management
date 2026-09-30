"""Immutable INGEST-001 values and canonical evidence helpers."""
from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

SOURCE_KINDS = frozenset({"email_message", "sms_message", "chat_message", "operator_note", "voice_transcript"})
CHANNELS = frozenset({"email", "sms", "chat", "internal", "voice"})
KIND_CHANNEL = {"email_message": "email", "sms_message": "sms", "chat_message": "chat", "operator_note": "internal", "voice_transcript": "voice"}
IDENTITY_STATES = frozenset({"transport_verified", "operator_confirmed", "unverified_claim", "not_applicable"})
# Failure codes are intentionally small, non-sensitive retained facts.  The
# owning workflow may store detailed diagnostics only in its correlated audit
# history; Intake state itself must stay portable and safe to project.
FAILURE_CODES = frozenset({"attachment_content_unavailable"})


class IntakeError(ValueError):
    code = "intake_validation"


class IntakeConflictError(IntakeError):
    def __init__(self, message: str, code: str = "intake_conflict") -> None:
        super().__init__(message); self.code = code


class IntakeNotFoundError(IntakeError):
    code = "intake_not_found"


@dataclass(frozen=True)
class IntakeAdmissionContext:
    """Provenance supplied by an authenticated application boundary."""

    submitter_kind: str
    submitter_reference: str | None = None
    account_scope_hash: str | None = None
    account_identity_state: str = "not_applicable"
    account_display_hint: str | None = None

    @classmethod
    def local_operator(cls) -> "IntakeAdmissionContext":
        return cls("local_operator")

    def __post_init__(self) -> None:
        if self.submitter_kind not in {"local_operator", "assistant_connection", "voice_workflow"}:
            raise IntakeError("submitter kind is invalid.")
        if self.submitter_kind == "local_operator":
            if (self.submitter_reference is not None or self.account_scope_hash is not None
                    or self.account_identity_state != "not_applicable" or self.account_display_hint is not None):
                raise IntakeError("Operator admission cannot claim trusted provenance.")
        elif not isinstance(self.submitter_reference, str) or not self.submitter_reference.strip():
            raise IntakeError("Trusted admission requires a submitter reference.")
        else:
            object.__setattr__(self, "submitter_reference", bounded(self.submitter_reference, "submitterReference", 500, required=True))
        if self.account_identity_state not in IDENTITY_STATES:
            raise IntakeError("account identity state is invalid.")
        if self.account_scope_hash is not None and (len(self.account_scope_hash) != 64 or any(c not in "0123456789abcdef" for c in self.account_scope_hash)):
            raise IntakeError("account scope hash is invalid.")
        if self.account_identity_state in {"transport_verified", "operator_confirmed"} and not self.account_scope_hash:
            raise IntakeError("trusted account identity requires accountScopeHash.")
        object.__setattr__(self, "account_display_hint", bounded(self.account_display_hint, "accountDisplayHint", 500))


@dataclass(frozen=True)
class AttentionTransition:
    """The complete concurrency and audit contract for an Intake review decision."""
    source_id: str
    target: str
    reason: str
    idempotency_key: str
    expected_revision: str
    expected_status: str
    correlation_id: str
    actor_kind: str = "local_operator"
    actor_reference: str | None = None

    def __post_init__(self) -> None:
        uuid(self.source_id, "sourceId")
        uuid(self.idempotency_key, "idempotencyKey")
        uuid(self.expected_revision, "expectedRevision")
        uuid(self.correlation_id, "correlationId")
        if self.target not in {"unprocessed", "in_review", "resolved", "dismissed"}:
            raise IntakeError("attention status is invalid.")
        if self.expected_status not in {"unprocessed", "in_review", "resolved", "dismissed"}:
            raise IntakeError("expected attention status is invalid.")
        object.__setattr__(self, "reason", bounded(self.reason, "reason", 1000, required=True))
        if self.actor_kind not in {"local_operator", "assistant_connection", "system"}:
            raise IntakeError("attention actor kind is invalid.")
        if self.actor_kind == "assistant_connection":
            actor_reference = bounded(self.actor_reference, "actorReference", 500, required=True)
            if actor_reference is None:
                raise IntakeError("assistant attention requires an actor reference.")
            # Intake's connection vocabulary deliberately does not leak into
            # AUDIT-001.  The durable audit actor is the registered equivalent.
            object.__setattr__(self, "actor_kind", "ai_assistant")
            object.__setattr__(self, "actor_reference", actor_reference)
        elif self.actor_reference is not None:
            object.__setattr__(self, "actor_reference", bounded(self.actor_reference, "actorReference", 500))


def utc_now() -> str: return datetime.now(UTC).isoformat()


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def fingerprint(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def uuid(value: object, label: str) -> str:
    if not isinstance(value, str): raise IntakeError(f"{label} must be a UUID.")
    try: return str(UUID(value))
    except ValueError as error: raise IntakeError(f"{label} must be a UUID.") from error


def utc(value: object, label: str) -> str:
    if not isinstance(value, str): raise IntakeError(f"{label} must be an aware UTC timestamp.")
    try: parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error: raise IntakeError(f"{label} must be an aware UTC timestamp.") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None: raise IntakeError(f"{label} must be an aware UTC timestamp.")
    return parsed.astimezone(UTC).isoformat()


def failure_code(value: object) -> str:
    if not isinstance(value, str) or value not in FAILURE_CODES:
        raise IntakeError("failureCode is invalid.")
    return value


def bounded(value: object, label: str, maximum: int, *, required: bool = False) -> str | None:
    if value is None and not required: return None
    if not isinstance(value, str): raise IntakeError(f"{label} must be text.")
    result = unicodedata.normalize("NFC", value).strip()
    if (required and not result) or len(result) > maximum or any(unicodedata.category(c) == "Cc" for c in result):
        raise IntakeError(f"{label} is invalid.")
    return result


def body(value: object) -> str:
    if not isinstance(value, str): raise IntakeError("body must be text.")
    result = unicodedata.normalize("NFC", value).replace("\r\n", "\n").replace("\r", "\n")
    if not result or len(result.encode("utf-8")) > 131_072 or "\x00" in result:
        raise IntakeError("body is invalid.")
    if any(unicodedata.category(c) == "Cc" and c not in "\t\n" for c in result): raise IntakeError("body is invalid.")
    return result


@dataclass(frozen=True)
class EvidenceEnvelope:
    source_kind: str
    channel: str
    body: str
    occurred_at_utc: str
    subject: str | None = None
    participants: tuple[dict[str, str], ...] = ()
    provider: str | None = None
    conversation_ref: str | None = None
    external_source_id: str | None = None
    # The instant is normalized for ordering, while the original offset (or
    # IANA-bearing value supplied by a future transport) remains evidence.
    occurred_at_context: str | None = None

    def __post_init__(self) -> None:
        if self.source_kind not in SOURCE_KINDS or self.channel != KIND_CHANNEL.get(self.source_kind): raise IntakeError("source kind and channel are incompatible.")
        object.__setattr__(self, "body", body(self.body))
        reported = self.occurred_at_context or self.occurred_at_utc
        if not isinstance(reported, str): raise IntakeError("occurredAtUtc must be an aware UTC timestamp.")
        object.__setattr__(self, "occurred_at_context", reported)
        object.__setattr__(self, "occurred_at_utc", utc(self.occurred_at_utc, "occurredAtUtc"))
        for key in ("subject", "provider", "conversation_ref", "external_source_id"):
            object.__setattr__(self, key, bounded(getattr(self, key), key, 500))
        if len(self.participants) > 50: raise IntakeError("Too many participants.")
        normalized = []
        for participant in self.participants:
            if not isinstance(participant, dict) or set(participant) - {"role", "display", "address"} or not participant.get("role"):
                raise IntakeError("participant is invalid.")
            normalized.append({key: bounded(value, f"participant {key}", 500, required=key == "role") for key, value in participant.items()})
        object.__setattr__(self, "participants", tuple(normalized))

    def canonical(self, attachments: tuple[dict[str, str], ...] = ()) -> dict[str, object]:
        return {"schemaVersion": 1, "sourceKind": self.source_kind, "channel": self.channel, "subject": self.subject,
                "body": self.body, "participants": list(self.participants), "occurredAtUtc": self.occurred_at_utc,
                "occurredAtContext": self.occurred_at_context,
                "provider": self.provider, "conversationRef": self.conversation_ref, "externalSourceId": self.external_source_id,
                "attachments": list(attachments)}
