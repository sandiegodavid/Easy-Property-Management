"""Incomplete browser forms, not official commands or source-owned drafts."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, StrictBool, ValidationError

from app.platform.validation_errors import is_size_limit_violation

from app.modules.operator.domain.models import (
    Contract,
    OperatorError,
    OperatorTooLarge,
    MAX_RECOVERY_BYTES,
    canonical,
)


class TaskForm(Contract):
    title: str | None = Field(None, max_length=240)
    notes: str | None = Field(None, max_length=10000)
    priority: Literal["low", "normal", "high", "urgent"] | None = None
    dueAtUtc: AwareDatetime | None = None
    dueTimezone: str | None = Field(None, max_length=100)
    isAllDay: StrictBool | None = None
    relatedEntityType: (
        Literal["property", "space", "lease", "maintenance_issue", "owner_concern", "party"] | None
    ) = None
    relatedEntityId: UUID | None = None


class ReporterForm(Contract):
    role: Literal["owner", "tenant", "manager", "staff"] | None = None
    subjectKind: Literal["party", "local_operator"] | None = None
    partyId: UUID | None = None
    historicalSelectionConfirmed: StrictBool | None = None
    historicalSelectionReason: str | None = Field(None, max_length=1000)


class IssueForm(Contract):
    propertyId: UUID | None = None
    spaceId: UUID | None = None
    summary: str | None = Field(None, max_length=240)
    description: str | None = Field(None, max_length=10000)
    category: (
        Literal[
            "plumbing",
            "electrical",
            "heating_cooling",
            "appliance",
            "structural",
            "safety_security",
            "pest",
            "exterior_grounds",
            "cleaning",
            "other",
        ]
        | None
    ) = None
    categoryDetail: str | None = Field(None, max_length=200)
    priority: Literal["low", "normal", "high", "urgent"] | None = None
    reportedAtUtc: AwareDatetime | None = None
    reporter: ReporterForm | None = None


class ParticipantForm(Contract):
    partyId: UUID
    role: Literal["sender", "recipient", "reporter", "other"]
    partyContactMethodId: UUID | None = None


class LinkForm(Contract):
    entityType: Literal[
        "party",
        "property",
        "space",
        "lease",
        "rent_expectation",
        "rent_receipt",
        "renewal_option",
        "task",
        "maintenance_issue",
        "owner_concern",
        "intake_source",
    ]
    entityId: UUID


class CommunicationForm(Contract):
    direction: Literal["inbound", "outbound", "internal"] | None = None
    channel: Literal["phone", "email", "sms", "in_person", "letter", "other"] | None = None
    subject: str | None = Field(None, max_length=240)
    body: str | None = Field(None, max_length=10000)
    occurredAtUtc: AwareDatetime | None = None
    occurredTimezone: str | None = Field(None, max_length=100)
    participants: list[ParticipantForm] = Field(default_factory=list, max_length=100)
    links: list[LinkForm] = Field(default_factory=list, max_length=100)


SCHEMAS = {
    "task.create": TaskForm,
    "maintenance.issue.create": IssueForm,
    "communication.record": CommunicationForm,
}


def registered_schemas():
    from app.modules.operator.application.command_forms import COMMAND_SCHEMAS

    return {**SCHEMAS, **COMMAND_SCHEMAS}


def validate_payload(form_key, schema_version, payload):
    schemas = registered_schemas()
    if form_key not in schemas or type(schema_version) is not int or schema_version != 1:
        raise OperatorError("Recovery form or schema version is unsupported.")
    try:
        encoded = canonical(payload)
        if len(encoded.encode("utf-8")) > MAX_RECOVERY_BYTES:
            raise OperatorTooLarge("Recovery payload exceeds 64 KiB.")
        # Incomplete fields are allowed; extra fields, bytes and domain state are not.
        validated = schemas[form_key].model_validate(payload)
        return validated.model_dump(mode="json", exclude_unset=True)
    except ValidationError as error:
        if any(is_size_limit_violation(item) for item in error.errors()):
            raise OperatorTooLarge("Recovery form content exceeds an allowed limit.") from error
        raise OperatorError("Recovery payload does not match the registered form.") from error
    except (TypeError, ValueError) as error:
        if isinstance(error, OperatorError):
            raise
        raise OperatorError("Recovery payload does not match the registered form.") from error
