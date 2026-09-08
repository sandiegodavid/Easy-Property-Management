"""Reusable creation boundary for shared party identities."""

from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

from app.modules.parties.domain.models import Party


class PartyValidationError(ValueError):
    pass


@dataclass(frozen=True)
class PartyCreateCommand:
    party_kind: str
    display_name: str
    email: str | None = None
    phone: str | None = None

    def __post_init__(self) -> None:
        if self.party_kind not in {"individual", "organization"}:
            raise PartyValidationError("Party kind is invalid.")
        object.__setattr__(self, "display_name", _required(self.display_name, "Display name", 240))
        object.__setattr__(self, "email", _optional(self.email, "Email", 320))
        object.__setattr__(self, "phone", _optional(self.phone, "Phone", 80))


class PartyFactory(Protocol):
    def create(self, command: PartyCreateCommand, timestamp: str) -> Party: ...


class SharedPartyFactory:
    def create(self, command: PartyCreateCommand, timestamp: str) -> Party:
        if not isinstance(command, PartyCreateCommand):
            raise PartyValidationError("A valid party creation command is required.")
        return Party(
            id=str(uuid4()),
            party_kind=command.party_kind,
            display_name=command.display_name,
            email=command.email,
            phone=command.phone,
            created_at=timestamp,
            updated_at=timestamp,
            archived_at=None,
        )


def _required(value: object, label: str, limit: int) -> str:
    if not isinstance(value, str) or not (text := value.strip()) or len(text) > limit:
        raise PartyValidationError(f"{label} must contain 1 to {limit} characters.")
    return text


def _optional(value: object, label: str, limit: int) -> str | None:
    if value is None:
        return None
    return _required(value, label, limit)
