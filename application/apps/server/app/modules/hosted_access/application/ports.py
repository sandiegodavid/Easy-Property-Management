"""Small identity/session ports; consumers do not interpret JWTs or SQLAlchemy rows."""

from datetime import datetime
from typing import Mapping, Protocol

from app.modules.hosted_access.domain.models import VerifiedIdentity


class IdentityVerifier(Protocol):
    def verify(self, assertion: str) -> VerifiedIdentity: ...


class HostedSessionStore(Protocol):
    def begin_session(self, values: Mapping[str, object]) -> None: ...
    def session(self, token_hash: str) -> Mapping[str, object] | None: ...
    def revoke(self, token_hash: str, now: datetime, *, all_devices: bool) -> None: ...
