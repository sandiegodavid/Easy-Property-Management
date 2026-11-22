"""Admin authorization from verified provider proof and the protected principal store."""

from dataclasses import dataclass
from typing import Protocol

from app.modules.hosted_access.application.identity_setup import HOUR, MINUTE, IdentityRealm
from app.modules.hosted_access.application.identity_states import AdminSessionState
from app.modules.hosted_access.application.managed_provider import (
    ProviderDenied,
    VerifiedProviderIdentity,
)


@dataclass(frozen=True)
class AdminPrincipal:
    principal_id: str
    enabled: bool
    session_generation: int


class AdminPrincipalReader(Protocol):
    def by_identity(self, issuer: str, subject: str) -> AdminPrincipal | None: ...


CLOCK_SKEW_MS = 30_000


class AdminAdmission:
    def __init__(self, realm: IdentityRealm, principals: AdminPrincipalReader):
        self.realm = realm
        self.principals = principals

    def require_principal(self, proof: VerifiedProviderIdentity, *, now: int) -> AdminPrincipal:
        """Authorize entry to the factor flow without issuing a session."""
        if (
            proof.realm != self.realm.alias
            or proof.method not in {"google", "google_totp"}
            or not proof.authenticated_at <= proof.issued_at <= now + CLOCK_SKEW_MS
            or now >= proof.expires_at
            or now - proof.authenticated_at >= 15 * MINUTE
        ):
            raise ProviderDenied()
        principal = self.principals.by_identity(self.realm.alias, proof.subject)
        if principal is None or not principal.enabled:
            raise ProviderDenied()
        return principal

    def session_deadline(
        self, proof: VerifiedProviderIdentity, *, now: int
    ) -> tuple[AdminPrincipal, int]:
        principal = self.require_principal(proof, now=now)
        if (
            proof.method != "google_totp"
            or proof.mfa_verified_at is None
            or not proof.authenticated_at <= proof.mfa_verified_at <= proof.issued_at
            or now - proof.mfa_verified_at >= 15 * MINUTE
        ):
            raise ProviderDenied()
        return principal, min(proof.expires_at, proof.authenticated_at + 8 * HOUR)


def require_admin_session(
    session: AdminSessionState, principal: AdminPrincipal, *, now: int, sensitive: bool = False
) -> None:
    if (
        not principal.enabled
        or principal.principal_id != session.principal_id
        or principal.session_generation != session.generation
        or session.revoked_at is not None
        or not session.mfa_verified_at <= now + CLOCK_SKEW_MS
        or now >= min(session.expires_at, session.revocation_valid_until)
        or (sensitive and now - session.mfa_verified_at >= 15 * MINUTE)
    ):
        raise ProviderDenied()
