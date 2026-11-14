"""Managed provider values only; no assignment, session or workspace authority."""

from typing import Literal

from app.platform.hosted_contracts.values import Contract, EpochMillis, Reference


class ProviderDenied(ValueError):
    code = "managed_identity_rejected"

    def __init__(self):
        super().__init__("Sign-in could not be verified. Start sign-in again.")


class ProviderUnavailable(RuntimeError):
    code = "managed_identity_unavailable"

    def __init__(self):
        super().__init__("The sign-in provider is unavailable. Try again shortly.")


class VerifiedProviderIdentity(Contract):
    realm: Reference
    subject: str
    email: str
    email_key: str
    method: Literal["google", "email_link", "google_totp"]
    authenticated_at: EpochMillis
    issued_at: EpochMillis
    expires_at: EpochMillis
    mfa_verified_at: EpochMillis | None


def email_key(alias: str, email: str) -> str:
    """Conservative matching: preserve local case, dots and plus tags; lowercase domain."""
    if (
        not isinstance(email, str)
        or len(email) > 254
        or email.count("@") != 1
        or any(char.isspace() or ord(char) < 32 for char in email)
    ):
        raise ProviderDenied()
    local, domain = email.rsplit("@", 1)
    if not local or not domain or "." not in domain or any(char in email for char in "<>"):
        raise ProviderDenied()
    result = alias + ":" + local + "@" + domain.lower()
    if len(result) > 254:
        raise ProviderDenied()
    return result
