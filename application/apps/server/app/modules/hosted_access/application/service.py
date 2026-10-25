"""Explicit enrollment/session admission, immediate revocation and bounded read authorization."""

from datetime import UTC, datetime
from hashlib import sha256
import hmac
import re
import secrets
from typing import Callable

from app.modules.hosted_access.application.configuration import HostedDeployment, SESSION_DURATION
from app.modules.hosted_access.application.ports import HostedSessionStore
from app.modules.hosted_access.domain.models import (
    HostedAccessError,
    HostedActor,
    SessionGrant,
    VerifiedIdentity,
)


def token_hash(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def session_csrf(token: str) -> str:
    """Recoverable on refresh from the HttpOnly cookie, without storing another secret."""
    return hmac.new(token.encode("ascii"), b"epm-hosted-csrf-v1", sha256).hexdigest()


class HostedAccessService:
    def __init__(
        self,
        deployment: HostedDeployment,
        store: HostedSessionStore,
        now: Callable[[], datetime] | None = None,
    ):
        self.deployment = deployment
        self.store = store
        self.now = now or (lambda: datetime.now(UTC))

    def _require_identity(self, identity: VerifiedIdentity) -> datetime:
        now = self.now()
        if not self.deployment.enabled_at <= now < self.deployment.expires_at:
            raise HostedAccessError("hosted_demo_expired", "Demo is inactive or expired.", 403)
        if (
            identity.issuer != self.deployment.identity_issuer
            or identity.email != self.deployment.allowed_email
            or identity.expires_at <= now
            or identity.issued_at > now
        ):
            raise HostedAccessError("hosted_identity_rejected", "Identity is not authorized.", 403)
        return now

    def begin_session(self, identity: VerifiedIdentity) -> SessionGrant:
        now = self._require_identity(identity)
        token = secrets.token_urlsafe(32)
        csrf = session_csrf(token)
        expires = min(now + SESSION_DURATION, identity.expires_at, self.deployment.expires_at)
        self.store.begin_session(
            {
                "subject": identity.subject,
                "email": identity.email,
                "token_hash": token_hash(token),
                "csrf_hash": token_hash(csrf),
                "assertion_hash": identity.fingerprint,
                "assertion_expiry": identity.expires_at.timestamp(),
                "issued_at": identity.issued_at.timestamp(),
                "now": now.timestamp(),
                "expires_at": expires.timestamp(),
            }
        )
        return SessionGrant(token, csrf, expires)

    def authenticate(
        self,
        identity: VerifiedIdentity,
        token: str,
        *,
        csrf: str | None = None,
    ) -> HostedActor:
        now = self._require_identity(identity)
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
            raise HostedAccessError("hosted_session_required", "Sign in to this workspace.")
        hashed = token_hash(token)
        row = self.store.session(hashed)
        if row is None or (
            row["revoked"]
            or not row["active"]
            or row["generation"] != row["current_generation"]
            or row["subject"] != identity.subject
            or row["issuer"] != identity.issuer
            or row["email"] != identity.email
            or row["operator_id"] != str(self.deployment.operator_id)
            or row["workspace_id"] != str(self.deployment.workspace_id)
            or row["expires_at"] <= now.timestamp()
            or identity.issued_at.timestamp() <= row["not_before"]
        ):
            raise HostedAccessError("hosted_session_expired", "Sign in again to this workspace.")
        if csrf is not None and not hmac.compare_digest(token_hash(csrf), row["csrf_hash"]):
            raise HostedAccessError("hosted_csrf_rejected", "Request verification failed.", 403)
        return HostedActor(
            row["operator_id"],
            row["workspace_id"],
            hashed,
            datetime.fromtimestamp(row["expires_at"], UTC),
        )

    def logout(
        self, actor: HostedActor, identity: VerifiedIdentity, *, all_devices: bool = False
    ) -> None:
        self.store.revoke(
            actor.session_reference,
            self.now(),
            assertion_hash=identity.fingerprint,
            assertion_expiry=identity.expires_at.timestamp(),
            all_devices=all_devices,
        )
