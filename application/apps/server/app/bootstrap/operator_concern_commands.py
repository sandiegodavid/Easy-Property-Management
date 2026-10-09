"""Slice 37 composition using Owner-concern's canonical command identities."""

from dataclasses import asdict
import re

from app.modules.operator.application.concern_forms import CONCERN_SCHEMAS
from app.modules.operator.application.ports import RecoveryBinding
from app.modules.operator.domain.models import OperatorError
from app.modules.owner_management.application.commands import ConcernCommand, fingerprint
from app.modules.owner_management.domain.models import (
    ConcernCreateCommand,
    FollowUpInput,
    OwnerConcernError,
)
from app.modules.owner_management.infrastructure.recovery_reader import (
    SQLiteOwnerConcernRecoveryReader,
)


def snake_fields(payload):
    return {re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower(): value for name, value in payload.items()}


def concern_fingerprint(action, source, payload, key):
    try:
        values = {name: value for name, value in payload.items() if name != "expectedRevision"}
        if action == "create":
            values = snake_fields(values)
            if values.get("follow_up") is not None:
                values["follow_up"] = FollowUpInput(**snake_fields(values["follow_up"]))
            request = asdict(ConcernCreateCommand(idempotency_key=key, **values))
            request.pop("idempotency_key")
        elif action == "follow_up":
            request = asdict(FollowUpInput(**snake_fields(values)))
        elif action == "patch":
            if any(value is None for value in values.values()):
                raise OperatorError("Complete the supplied patch fields.")
            request = values
        else:
            if values.get("confirmed") is not True:
                raise OperatorError("Confirm the concern transition.")
            # Start ignores summary at the owning HTTP boundary. Other transitions
            # fingerprint the raw narrative, before business-field normalization.
            request = {
                "confirmed": True,
                "narrative": None if action == "in_progress" else values.get("summary"),
            }
            if action in {"resolved", "dismissed"} and not (request["narrative"] or "").strip():
                raise OperatorError("Complete the transition summary.")
        return fingerprint(
            ConcernCommand(action, source, payload["expectedRevision"], key, request).request()
        )
    except OwnerConcernError as error:
        raise OperatorError(str(error)) from error


def compose_concern_forms():
    reader = SQLiteOwnerConcernRecoveryReader()
    return {
        key: RecoveryBinding(
            None if key == "owner_concern.create" else "owner_concern",
            key.split(".")[1],
            "owner_concern",
            reader,
            lambda source, payload, attempt, action=key.split(".")[1]: concern_fingerprint(
                action, source, payload, attempt
            ),
            result_kind="owner_concern",
        )
        for key in CONCERN_SCHEMAS
    }
