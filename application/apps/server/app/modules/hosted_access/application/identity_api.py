"""H03.1 browser contracts. No routes, cookies or authentication are installed here."""

from typing import Annotated, Literal

from pydantic import Field, SecretStr, model_validator

from app.modules.hosted_access.application.identity_states import DeviceLabel, ReturnPath
from app.platform.hosted_contracts.values import (
    CanonicalId,
    Contract,
    DisplayName,
    EmailAddress,
    EpochMillis,
)


class StartLogin(Contract):
    version: Literal[1] = 1
    return_path: ReturnPath
    remembered: bool
    continuation_id: CanonicalId | None = None


class SendEmailLink(Contract):
    version: Literal[1] = 1
    attempt_id: CanonicalId
    email: EmailAddress


class CompleteHandoff(Contract):
    """POST body only. Browser challenge comes from the observed host-only cookie."""

    version: Literal[1] = 1
    attempt_id: CanonicalId
    handoff_code: SecretStr = Field(min_length=32, max_length=1024)


class CurrentSession(Contract):
    version: Literal[1] = 1
    state: Literal["authenticated", "workspace_not_ready", "renewal_required"]
    display_name: DisplayName
    expires_at: EpochMillis
    renewal_required_at: EpochMillis
    remembered_until: EpochMillis
    can_use_workspace: bool
    support_contact: EmailAddress

    @model_validator(mode="after")
    def truthful_access(self):
        if self.renewal_required_at > min(self.expires_at, self.remembered_until):
            raise ValueError("Renewal must be offered before existing authority ends.")
        if self.can_use_workspace != (self.state == "authenticated"):
            raise ValueError("Pending setup or renewal cannot claim business access.")
        return self


class SessionDevice(Contract):
    session_id: CanonicalId
    current: bool
    display_label: DeviceLabel
    last_seen_at: EpochMillis
    expires_at: EpochMillis


class SessionDevices(Contract):
    version: Literal[1] = 1
    items: Annotated[tuple[SessionDevice, ...], Field(max_length=50)]
    continuation: CanonicalId | None

    @model_validator(mode="after")
    def unique_devices(self):
        if len({item.session_id for item in self.items}) != len(self.items):
            raise ValueError("Device selectors must be unique.")
        if sum(item.current for item in self.items) > 1:
            raise ValueError("Only one device can be current.")
        return self


class AdminSession(Contract):
    version: Literal[1] = 1
    display_name: DisplayName
    expires_at: EpochMillis
    recent_auth_required: bool
    support_contact: EmailAddress
    business_access: Literal[False] = False
